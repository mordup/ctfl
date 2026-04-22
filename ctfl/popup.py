from __future__ import annotations

from datetime import datetime as _dt

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .constants import (
    COLOR_ACCENT,
    COLOR_MUTED,
    DATE_FMT_DISPLAY,
    DATE_FMT_ISO,
    FONT_SIZE_SMALL,
    ICON_THEME_NAME,
    TIME_FMT_HM,
)
from .providers import (
    RateLimitInfo,
    UsageData,
    format_cost,
    format_credits,
    format_reset,
    format_tokens,
)

_PROGRESS_BAR_STYLE = (
    "QProgressBar { background: #3a3a3a; border: none; border-radius: 3px; }"
    f"QProgressBar::chunk {{ background: {COLOR_ACCENT}; border-radius: 3px; }}"
)

# Below this ratio the /compact hint is noise; suppress the whole line.
_LONG_CONTEXT_DISPLAY_MIN_RATIO = 0.15

# Maximum pixel height of the tab content area. Sized to comfortably display
# ~7 rows (label + bar + breakdown per row). Beyond that, a scrollbar
# appears inside the tab instead of the popup growing off-screen. Below
# that, the area shrinks to fit — so sparse data doesn't leave a tall
# empty panel.
_TAB_CONTENT_MAX_HEIGHT = 380


def _wrap_in_scroll(widget: QWidget) -> QScrollArea:
    """Put a chart widget in a vertically scrollable frame capped at
    _TAB_CONTENT_MAX_HEIGHT. Shrinks to content when smaller.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setMaximumHeight(_TAB_CONTENT_MAX_HEIGHT)
    return area


class PopupWidget(QWidget):
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._config = config
        self.setWindowTitle("Claude Usage")
        self.setWindowIcon(QIcon.fromTheme(ICON_THEME_NAME))
        self._build_ui()
        self.setMinimumWidth(480)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Rate limits section (hidden until data arrives)
        self._limits_frame = QFrame()
        self._limits_layout = QVBoxLayout(self._limits_frame)
        self._limits_layout.setContentsMargins(0, 0, 0, 0)
        self._limits_layout.setSpacing(6)
        self._limits_frame.setVisible(False)
        layout.addWidget(self._limits_frame)

        # Summary
        self._summary_label = QLabel()
        layout.addWidget(self._summary_label)

        # Tabs — popup sizes to content, but each tab's content is capped at
        # _TAB_CONTENT_MAX_HEIGHT so long lists scroll instead of overflowing
        # the screen.
        self._tabs = QTabWidget()
        self._daily_chart = _BarChartWidget()
        self._model_chart = _BarChartWidget()
        self._project_chart = _BarChartWidget()
        self._tabs.addTab(_wrap_in_scroll(self._daily_chart), "Daily")
        self._tabs.addTab(_wrap_in_scroll(self._model_chart), "By Model")
        self._tabs.addTab(_wrap_in_scroll(self._project_chart), "By Project")
        self._tabs.currentChanged.connect(lambda _: self._fit_to_content())
        layout.addWidget(self._tabs)

        # Footer
        footer = QHBoxLayout()
        self._status_label = QLabel()
        self._status_label.setStyleSheet(f"color: {COLOR_MUTED};")
        footer.addWidget(self._status_label)
        footer.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        footer.addWidget(self._refresh_btn)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        footer.addWidget(settings_btn)
        layout.addLayout(footer)

    def update_data(self, data: UsageData) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Refresh")

        self._update_limits(data.limits)

        if data.error:
            self._summary_label.setText(f"Error: {data.error}")
            self._daily_chart.set_rows([])
            self._model_chart.set_rows([])
            self._project_chart.set_rows([])
            self._update_status()
            return

        # Summary
        today = _dt.now().strftime(DATE_FMT_ISO)
        today_data = next((d for d in data.daily if d.date == today), None)
        total_tokens = sum(d.total_tokens for d in data.daily)

        parts = []
        if today_data:
            today_text = f"Today: {format_tokens(today_data.total_tokens)} tokens"
            if today_data.cost_usd is not None:
                today_text += f" · {format_cost(today_data.cost_usd)}"
            parts.append(today_text)
        total_text = f"Period total: {format_tokens(total_tokens)} tokens"
        total_cost = sum(d.cost_usd for d in data.daily if d.cost_usd is not None)
        if total_cost:
            total_text += f" · {format_cost(total_cost)}"
        parts.append(total_text)

        # Long-context usage insight: the ratio is computed over the
        # JSONL-scan window (recent sessions), not the full period —
        # stats-cache-era days lack per-message context size. The label
        # says "Recent sessions" to make that scope explicit to the user.
        if data.long_context_total_tokens and data.long_context_tokens:
            ratio = data.long_context_tokens / data.long_context_total_tokens
            if ratio >= _LONG_CONTEXT_DISPLAY_MIN_RATIO:
                pct = round(ratio * 100)
                hint = (
                    f"<span style='color: {COLOR_MUTED}; font-size: {FONT_SIZE_SMALL};'>"
                    f"Recent sessions: {pct}% of tokens used at &gt;150k context · "
                    f"<code>/compact</code> mid-task, <code>/clear</code> between tasks"
                    f"</span>"
                )
                parts.append(hint)

        html = "".join(f"<p style='margin: 2px 0;'>{p}</p>" for p in parts)
        self._summary_label.setText(html)

        # Daily bar chart
        show_bd = self._config.show_token_breakdown
        max_day_tokens = max((d.total_tokens for d in data.daily), default=1) or 1
        daily_rows = []
        for day in data.daily:
            # Format date: "Mar 03" from "2026-03-03"
            try:
                label = _dt.strptime(day.date, DATE_FMT_ISO).strftime(DATE_FMT_DISPLAY).title()
            except ValueError:
                label = day.date
            detail = f"{format_tokens(day.total_tokens)} tokens"
            if day.cost_usd is not None:
                detail += f" · {format_cost(day.cost_usd)}"
            breakdown = _format_breakdown(
                day.input_tokens, day.output_tokens,
                day.cache_read_tokens, day.cache_creation_tokens,
            ) if show_bd and day.breakdown_available else None
            daily_rows.append((label, day.total_tokens, max_day_tokens, detail, breakdown))
        self._daily_chart.set_rows(daily_rows)

        # Model bar chart
        max_model_total = max((m.total for m in data.by_model), default=1) or 1
        model_rows = []
        for mt in data.by_model:
            label = _short_model(mt.model)
            detail = format_tokens(mt.total)
            breakdown = _format_breakdown(
                mt.input_tokens, mt.output_tokens,
                mt.cache_read_tokens, mt.cache_creation_tokens,
            ) if show_bd else None
            model_rows.append((label, mt.total, max_model_total, detail, breakdown))
        self._model_chart.set_rows(model_rows)

        # Project bar chart (no token breakdown available)
        if data.by_project:
            max_project = max(p.total_tokens for p in data.by_project) or 1
            project_rows = []
            for proj in data.by_project:
                detail = format_tokens(proj.total_tokens)
                project_rows.append((proj.name, proj.total_tokens, max_project, detail, None))
            self._project_chart.set_rows(project_rows)
        else:
            self._project_chart.set_rows([])

        self._update_status()
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        # Size the popup to fit the active tab's content, up to the scroll
        # area's max height. When content exceeds the max, the scrollbar
        # inside the tab takes over and the popup caps at that height.
        active_scroll = self._tabs.currentWidget()
        inner = active_scroll.widget() if isinstance(active_scroll, QScrollArea) else None
        if inner is not None:
            # sizeHint() of the inner widget reflects rows * row_height + padding.
            content_h = inner.sizeHint().height()
            capped = min(content_h, _TAB_CONTENT_MAX_HEIGHT)
            tab_bar_h = self._tabs.tabBar().sizeHint().height()
            self._tabs.setFixedHeight(capped + tab_bar_h + 8)
        if self.isVisible():
            # Don't shrink while visible — avoid yanking the window out from
            # under the user's cursor on tab switch. Only grow if needed.
            current = self.size()
            ideal = self.sizeHint()
            if ideal.height() > current.height() or ideal.width() > current.width():
                self.resize(max(current.width(), ideal.width()),
                            max(current.height(), ideal.height()))
        else:
            self.adjustSize()
        self._tabs.setMaximumHeight(16777215)

    def _update_limits(self, limits: list[RateLimitInfo]) -> None:
        # Clear previous widgets
        while self._limits_layout.count():
            item = self._limits_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _clear_layout(item.layout())

        if not limits:
            self._limits_frame.setVisible(False)
            return

        self._limits_frame.setVisible(True)

        section_label = QLabel("Plan usage limits")
        font = section_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        section_label.setFont(font)
        self._limits_layout.addWidget(section_label)

        from .providers.prediction import predict_exhaustion

        # Partition limits by window type. Enterprise plans return null for
        # session/weekly and only populate the monthly spend window.
        session_limits = [i for i in limits if i.window_key == "five_hour"]
        spend_limits = [i for i in limits if i.window_key == "monthly_spend"]
        weekly_limits = [
            i for i in limits
            if i.window_key not in ("five_hour", "monthly_spend")
        ]

        for info in session_limits:
            pred = predict_exhaustion(info, info.window_key)

            # Header: "Session · prediction" on left, reset on right
            reset_text = format_reset(info.resets_at)

            header_row = QHBoxLayout()
            left_text = f"<b>{info.name}</b>"
            if pred:
                left_text += f" · {pred}"
            header_label = QLabel(left_text)
            header_row.addWidget(header_label)
            header_row.addStretch()
            if reset_text:
                reset_label = QLabel(reset_text)
                reset_label.setStyleSheet(f"color: {COLOR_MUTED};")
                header_row.addWidget(reset_label)
            self._limits_layout.addLayout(header_row)

            # Bar only, no separate prediction line
            self._add_limit_bar(info, None, None)

        if weekly_limits and session_limits:
            # Add spacing between session and weekly sections
            from PyQt6.QtWidgets import QSizePolicy, QSpacerItem
            self._limits_layout.addItem(
                QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            )

        if weekly_limits:
            # Group header; reset timestamps render per-bar below
            self._limits_layout.addWidget(QLabel("<b>Weekly</b>"))

            for info in weekly_limits:
                if info.name.startswith("Weekly (") and info.name.endswith(")"):
                    label = info.name[8:-1]  # "Weekly (Sonnet)" -> "Sonnet"
                else:
                    label = "All models"
                reset_text = (
                    format_reset(info.resets_at) if info.resets_at else "Not used yet"
                )
                self._add_limit_bar(info, label, predict_exhaustion, reset_text=reset_text)

        if spend_limits and (session_limits or weekly_limits):
            from PyQt6.QtWidgets import QSizePolicy, QSpacerItem
            self._limits_layout.addItem(
                QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            )

        for info in spend_limits:
            reset_text = format_reset(info.resets_at)
            header_row = QHBoxLayout()
            header_row.addWidget(QLabel(f"<b>{info.name}</b>"))
            header_row.addStretch()
            if reset_text:
                reset_label = QLabel(reset_text)
                reset_label.setStyleSheet(f"color: {COLOR_MUTED};")
                header_row.addWidget(reset_label)
            self._limits_layout.addLayout(header_row)
            self._add_limit_bar(info, None, None)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        self._limits_layout.addWidget(sep)

    def _add_limit_bar(self, info, label, predict_exhaustion, reset_text=None) -> None:
        """Add a progress bar row with optional left label and prediction."""
        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        if label:
            lbl = QLabel(label)
            # Wide enough for "Claude Design" without eliding
            lbl.setFixedWidth(95)
            lbl.setStyleSheet(f"font-size: {FONT_SIZE_SMALL};")
            bar_row.addWidget(lbl)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(round(info.utilization))
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(_PROGRESS_BAR_STYLE)
        bar_row.addWidget(bar, 1)
        if info.used_credits is not None and info.monthly_limit is not None:
            spend_text = (
                f"{format_credits(info.used_credits, info.currency)} / "
                f"{format_credits(info.monthly_limit, info.currency)}"
            )
            bar_row.addWidget(QLabel(spend_text))
            pct_label = QLabel(f"({info.utilization:.0f}%)")
            pct_label.setStyleSheet(f"color: {COLOR_MUTED};")
            bar_row.addWidget(pct_label)
        else:
            bar_row.addWidget(QLabel(f"{info.utilization:.0f}% used"))
        self._limits_layout.addLayout(bar_row)

        if reset_text:
            reset_label = QLabel(reset_text)
            reset_label.setStyleSheet(f"color: {COLOR_MUTED}; font-size: {FONT_SIZE_SMALL};")
            self._limits_layout.addWidget(reset_label)

        if predict_exhaustion is not None:
            pred = predict_exhaustion(info, info.window_key)
            if pred:
                pred_label = QLabel(pred)
                pred_label.setStyleSheet(f"color: {COLOR_MUTED}; font-size: {FONT_SIZE_SMALL};")
                self._limits_layout.addWidget(pred_label)

    def _update_status(self) -> None:
        self._status_label.setText(
            f"Last updated: {_dt.now().strftime(TIME_FMT_HM)}"
        )

    def show_loading(self) -> None:
        self._summary_label.setText("Loading...")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Loading...")

    def position_near_tray(self, tray_geometry) -> None:
        screen = self.screen()
        if screen is None:
            return
        screen_rect = screen.availableGeometry()
        self.adjustSize()
        size = self.size()

        # Try to position above the tray icon, centered horizontally
        x = tray_geometry.center().x() - size.width() // 2
        y = tray_geometry.top() - size.height() - 4

        # Clamp to screen
        x = max(screen_rect.left(), min(x, screen_rect.right() - size.width()))
        if y < screen_rect.top():
            y = tray_geometry.bottom() + 4
        y = max(screen_rect.top(), min(y, screen_rect.bottom() - size.height()))

        self.move(x, y)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)


class _BarChartWidget(QWidget):
    """List of horizontal bar-chart rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch()

    def set_rows(
        self,
        rows: list[tuple[str, int, int, str, BreakdownItems | None]],
    ) -> None:
        """Set bar chart data.

        Each row is (label, value, max_value, detail_text, breakdown).
        breakdown is a list of (symbol, formatted_value, label, color) tuples, or None.
        """
        # Clear previous rows (keep the trailing stretch)
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _clear_layout(item.layout())

        # Compute max pixel width for each fixed column position
        bd_font = QFont()
        bd_font.setPixelSize(10)
        fm = QFontMetrics(bd_font)
        # All category labels in fixed order
        all_labels = [label for _, label, _ in _BREAKDOWN_CATEGORIES]
        col_widths: dict[str, int] = {}
        for *_, breakdown in rows:
            if not breakdown:
                continue
            for symbol, val_text, label, _ in breakdown:
                text = f"{symbol}{val_text} {label}"
                w = fm.horizontalAdvance(text)
                col_widths[label] = max(col_widths.get(label, 0), w)

        for label_text, value, max_value, detail_text, breakdown in rows:
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)

            # Top line: label ... detail
            top = QHBoxLayout()
            top.setSpacing(8)
            label = QLabel(label_text)
            font = label.font()
            font.setFamily("monospace")
            label.setFont(font)
            label.setMinimumWidth(100)
            top.addWidget(label)
            top.addStretch()
            detail = QLabel(detail_text)
            detail.setStyleSheet(f"color: {COLOR_MUTED}; font-size: {FONT_SIZE_SMALL};")
            top.addWidget(detail)
            row_layout.addLayout(top)

            # Bar — normalize to 0-1000 to avoid 32-bit int overflow
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(value / max_value * 1000) if max_value else 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(_PROGRESS_BAR_STYLE)
            row_layout.addWidget(bar)

            # Breakdown line — fixed column positions
            if breakdown:
                bd_map = {label: (sym, val, color) for sym, val, label, color in breakdown}
                bd_row = QHBoxLayout()
                bd_row.setContentsMargins(0, 0, 0, 0)
                bd_row.setSpacing(8)
                for cat_label in all_labels:
                    if cat_label not in col_widths:
                        continue  # no row uses this category
                    w = col_widths[cat_label] + 4
                    if cat_label in bd_map:
                        sym, val, color = bd_map[cat_label]
                        bd_lbl = QLabel(f"{sym}{val} {cat_label}")
                        bd_lbl.setFont(bd_font)
                        bd_lbl.setStyleSheet(f"color: {color};")
                    else:
                        bd_lbl = QLabel("")
                    bd_lbl.setFixedWidth(w)
                    bd_row.addWidget(bd_lbl)
                bd_row.addStretch()
                row_layout.addLayout(bd_row)

            self._layout.insertWidget(self._layout.count() - 1, row_widget)


_BREAKDOWN_CATEGORIES = [
    ("↓", "in", COLOR_ACCENT),
    ("↑", "out", "#F59E0B"),
    ("⟳", "cache", "#9B8ECE"),
    ("✦", "new cache", "#6366F1"),
]

# Each entry: (symbol, formatted_value, label, color) — only non-zero categories
BreakdownItems = list[tuple[str, str, str, str]]


def _format_breakdown(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> BreakdownItems | None:
    """Return structured breakdown items for non-zero token categories."""
    values = [input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens]
    items = []
    for (symbol, label, color), value in zip(_BREAKDOWN_CATEGORIES, values, strict=True):
        if value:
            items.append((symbol, format_tokens(value), label, color))
    return items or None


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _short_model(model: str) -> str:
    # "claude-opus-4-6" -> "opus-4-6", "claude-opus-4-5-20251101" -> "opus-4-5"
    name = model.removeprefix("claude-")
    # Strip date suffix like -20251101
    parts = name.split("-")
    cleaned = []
    for p in parts:
        if len(p) == 8 and p.isdigit():
            continue
        cleaned.append(p)
    return "-".join(cleaned).capitalize()
