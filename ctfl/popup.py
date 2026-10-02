from __future__ import annotations

from datetime import datetime as _dt

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .constants import (
    COLOR_ACCENT,
    COLOR_MUTED,
    DATE_FMT_ISO,
    FONT_SIZE_SMALL,
    ICON_THEME_NAME,
)
from .dates import (
    PERIOD_LABELS,
    PERIODS,
    day_label,
    has_earlier_period,
    period_label,
    period_range,
    time_hm,
)
from .providers import (
    RateLimitInfo,
    UsageData,
    format_cost,
    format_credits_range,
    format_reset,
    format_tokens,
    models_between,
    projects_between,
)

_PROGRESS_BAR_STYLE = (
    "QProgressBar { background: #3a3a3a; border: none; border-radius: 3px; }"
    f"QProgressBar::chunk {{ background: {COLOR_ACCENT}; border-radius: 3px; }}"
)

# The popup sizes itself and cannot be resized: a height chosen by hand
# suits either one row or thirty, never both. The list shows up to this many
# whole rows -- a full week -- and scrolls beyond; counted in rows, not
# pixels, so it never ends on a cut-off row.
_VISIBLE_ROWS = 7
# Room for at least this many, so a single row does not leave a sliver.
_MIN_ROWS = 3
# Wider only stretches the rows apart; the popup widens past this only when
# its content cannot fit, e.g. under a large system font.
_POPUP_WIDTH = 500


def _wrap_in_scroll(widget: QWidget) -> QScrollArea:
    """Put a chart widget in a vertically scrollable frame."""
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


class PopupWidget(QWidget):
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._config = config
        self.setWindowTitle("Claude Usage")
        self.setWindowIcon(QIcon.fromTheme(ICON_THEME_NAME))
        self._data: UsageData | None = None
        # "Loading..." or an error, shown in place of the period total until
        # the next data arrives, whatever the period.
        self._status_text: str | None = None
        # Periods back from the current one; every opening starts on it.
        self._period_offset = 0
        self._build_ui()
        self._fit_to_content()

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

        period_row = QHBoxLayout()
        self._period_combo = QComboBox()
        for key in PERIODS:
            self._period_combo.addItem(PERIOD_LABELS[key], key)
        self._period_combo.setCurrentIndex(self._period_combo.findData(self._config.period))
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        period_row.addWidget(self._period_combo)
        self._prev_period_btn = QToolButton()
        self._prev_period_btn.setArrowType(Qt.ArrowType.LeftArrow)
        self._prev_period_btn.setAutoRaise(True)
        self._prev_period_btn.clicked.connect(lambda: self._step_period(-1))
        period_row.addWidget(self._prev_period_btn)
        self._period_name_label = QLabel()
        self._period_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wide enough for the longest name, so the arrows hold still.
        metrics = self._period_name_label.fontMetrics()
        self._period_name_label.setMinimumWidth(max(
            metrics.horizontalAdvance(text) for text in ("Sep 30 \u2013 Oct 30", "September 2026")
        ) + 8)
        period_row.addWidget(self._period_name_label)
        self._next_period_btn = QToolButton()
        self._next_period_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._next_period_btn.setAutoRaise(True)
        self._next_period_btn.clicked.connect(lambda: self._step_period(1))
        period_row.addWidget(self._next_period_btn)
        period_row.addSpacing(8)
        # Also carries the loading and error states.
        self._period_total_label = QLabel()
        self._period_total_label.setTextFormat(Qt.TextFormat.PlainText)
        self._period_total_label.setWordWrap(True)
        period_row.addWidget(self._period_total_label, 1)
        layout.addLayout(period_row)

        # Tabs — sized to content, capped at _VISIBLE_ROWS rows so long
        # lists scroll instead of overflowing the screen.
        self._tabs = QTabWidget()
        self._daily_chart = _BarChartWidget()
        self._model_chart = _BarChartWidget()
        self._project_chart = _BarChartWidget()
        self._tabs.addTab(_wrap_in_scroll(self._daily_chart), "Usage")
        self._tabs.addTab(_wrap_in_scroll(self._model_chart), "By Model")
        self._tabs.addTab(_wrap_in_scroll(self._project_chart), "By Project")
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
            self._data = None
            # Plain text only: error strings can embed raw exception text from
            # network/JSON sources.
            self._status_text = f"Error: {data.error}"
            self._render_period()
            self._update_status()
            self._fit_to_content()
            return

        self._data = data
        self._status_text = None
        self._render_period()
        self._update_status()
        self._fit_to_content()

    def _on_period_changed(self, _index: int) -> None:
        self._config.period = self._period_combo.currentData()
        self._period_offset = 0
        self._render_period()
        self._fit_to_content()

    def _step_period(self, step: int) -> None:
        self._period_offset += step
        self._render_period()
        self._fit_to_content()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not event.spontaneous() and self._period_offset:
            self._period_offset = 0
            self._render_period()

    def _render_period(self) -> None:
        period = self._period_combo.currentData()
        today = _dt.now().date()
        self._period_name_label.setText(period_label(period, today, self._period_offset))
        self._prev_period_btn.setEnabled(has_earlier_period(period, today, self._period_offset))
        self._next_period_btn.setEnabled(self._period_offset < 0)

        data = self._data
        if data is None:
            self._period_total_label.setText(self._status_text or "")
            self._daily_chart.set_rows([])
            self._model_chart.set_rows([])
            self._project_chart.set_rows([])
            return

        show_bd = self._config.show_token_breakdown
        first, last = period_range(period, today, self._period_offset)
        start, end = first.isoformat(), last.isoformat()
        days = [d for d in data.daily if start <= d.date <= end]

        total_text = f"{format_tokens(sum(d.total_tokens for d in days))} tokens"
        total_cost = _period_cost(days)
        if total_cost is not None:
            total_text += f" · {format_cost(total_cost)}"
        self._period_total_label.setText(self._status_text or total_text)

        max_day_tokens = max((d.total_tokens for d in days), default=1) or 1
        daily_rows = []
        for day in days:
            try:
                label = day_label(_dt.strptime(day.date, DATE_FMT_ISO).date())
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

        models = models_between(data, start, end)
        max_model_total = max((m.total for m in models), default=1) or 1
        model_rows = []
        for mt in models:
            detail = f"{format_tokens(mt.total)} tokens"
            if mt.cost_usd is not None:
                detail += f" · {format_cost(mt.cost_usd)}"
            breakdown = _format_breakdown(
                mt.input_tokens, mt.output_tokens,
                mt.cache_read_tokens, mt.cache_creation_tokens,
            ) if show_bd and mt.breakdown_available else None
            model_rows.append((_short_model(mt.model), mt.total, max_model_total, detail, breakdown))
        self._model_chart.set_rows(model_rows)

        # No token breakdown is available per project
        projects = projects_between(data, start, end)
        max_project = max((p.total_tokens for p in projects), default=1) or 1
        self._project_chart.set_rows([
            (proj.name, proj.total_tokens, max_project, format_tokens(proj.total_tokens), None)
            for proj in projects
        ])

    def _fit_to_content(self) -> None:
        # Rows rebuilt by set_rows()/_update_limits() are still hidden at this
        # point: Qt shows freshly-added children when their posted show events
        # are delivered, not when they are added. QLayout::sizeHint() skips
        # hidden widgets, so measuring now would see only margins and pin the
        # tab area to ~46px. Deliver those events first. sendPostedEvents()
        # rather than processEvents(), which would re-enter the event loop
        # mid-resize; DeferredDelete is excluded by default, so the
        # deleteLater() cleanup is untouched.
        QApplication.sendPostedEvents()

        # Every tab gets the height of the tallest one, so switching tabs
        # never resizes the window. With NoFrame and no horizontal scrollbar
        # the scroll area's height is its viewport's.
        rows_h = max(
            _rows_height(self._tabs.widget(i).widget().layout(), _VISIBLE_ROWS, _MIN_ROWS)
            for i in range(self._tabs.count())
        )
        for i in range(self._tabs.count()):
            self._tabs.widget(i).setFixedHeight(rows_h)
        # Hidden pages do not propagate their new size to the tab widget's
        # page stack, so its cached size hint must be dropped by hand.
        self._tabs.findChild(QStackedWidget).layout().invalidate()
        self._tabs.updateGeometry()

        # activate() computes geometry synchronously; invalidate() alone only
        # marks it dirty, and sizeHint() would return the pre-update value.
        self._limits_frame.layout().activate()
        self._limits_frame.updateGeometry()
        self.layout().invalidate()
        self.layout().activate()
        width = max(_POPUP_WIDTH, self.layout().minimumSize().width())
        self.setFixedSize(width, max(
            self.layout().sizeHint().height(), self.layout().totalHeightForWidth(width),
        ))

    def _update_limits(self, limits: list[RateLimitInfo]) -> None:
        # Clear previous widgets. setParent(None) detaches them from the
        # layout hierarchy synchronously so sizeHint() reflects the new
        # layout immediately; deleteLater() still handles memory cleanup
        # on the next event loop tick.
        while self._limits_layout.count():
            item = self._limits_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
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
        omelette_limits = [i for i in limits if i.window_key == "seven_day_omelette"]
        weekly_limits = [
            i for i in limits
            if i.window_key not in ("five_hour", "monthly_spend", "seven_day_omelette")
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

        if omelette_limits and (session_limits or weekly_limits):
            from PyQt6.QtWidgets import QSizePolicy, QSpacerItem
            self._limits_layout.addItem(
                QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            )

        # Claude Design has its own quota window, separate from the
        # model-share weekly buckets — render as its own section.
        for info in omelette_limits:
            reset_text = (
                format_reset(info.resets_at) if info.resets_at else "Not used yet"
            )
            label_text = info.name
            if label_text.startswith("Weekly (") and label_text.endswith(")"):
                label_text = label_text[8:-1]
            header_row = QHBoxLayout()
            header_row.addWidget(QLabel(f"<b>{label_text}</b>"))
            header_row.addStretch()
            if reset_text:
                reset_label = QLabel(reset_text)
                reset_label.setStyleSheet(f"color: {COLOR_MUTED};")
                header_row.addWidget(reset_label)
            self._limits_layout.addLayout(header_row)
            self._add_limit_bar(info, None, None)

        if spend_limits and (session_limits or weekly_limits or omelette_limits):
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
            bar_row.addWidget(QLabel(format_credits_range(
                info.used_credits, info.monthly_limit, info.currency
            )))
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
            f"Last updated: {time_hm(_dt.now())}"
        )

    def show_loading(self) -> None:
        self._status_text = "Loading..."
        self._period_total_label.setText(self._status_text)
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Loading...")
        # Clear the previous profile's limit bars so they don't stay
        # visible (or size the popup) while the new fetch is in flight.
        self._update_limits([])

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
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
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
            label = _ElidedLabel(label_text)
            font = label.font()
            font.setFamily("monospace")
            label.setFont(font)
            label.setMinimumWidth(100)
            top.addWidget(label)
            top.addStretch()
            detail = QLabel(detail_text)
            detail.setTextFormat(Qt.TextFormat.PlainText)
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


class _ElidedLabel(QLabel):
    """Row label that ends in "…" instead of being cut off when too long for
    the fixed-width popup; the full text is then in its tooltip."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._full = text
        # Model/project names come from external data — plain text only, so
        # HTML-looking names can't restyle the popup.
        self.setTextFormat(Qt.TextFormat.PlainText)

    def sizeHint(self):
        # Pinned to the full text, or eliding would shrink the hint and let
        # the layout squeeze the label further on every pass.
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 2)
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        self.setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


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


def _period_cost(daily: list) -> float | None:
    """Total cost across the period, or None when it would be partial.

    Days sourced from stats-cache have no per-model token breakdown and so no
    cost, as do days containing an unpriced model. Summing only the priced days
    yields a figure that reads as a whole-period total while usually covering
    just today — whose cost the Today line already shows.
    """
    if not daily or any(d.cost_usd is None for d in daily):
        return None
    return sum(d.cost_usd for d in daily)


def _rows_height(layout, rows: int, at_least: int = 0) -> int:
    """Height of a chart's first `rows` rows; fewer when it has fewer, but
    never less than `at_least` rows of its tallest one."""
    # The chart's last item is its trailing stretch, not a row. The widget's
    # own sizeHint, not the item's: the item reports a row as 0px while the
    # popup has not been shown yet.
    heights = [
        layout.itemAt(i).widget().sizeHint().height()
        for i in range(min(rows, layout.count() - 1))
    ]
    if not heights:
        return 0
    heights += [max(heights)] * (at_least - len(heights))
    margins = layout.contentsMargins()
    return (
        sum(heights)
        + layout.spacing() * (len(heights) - 1)
        + margins.top() + margins.bottom()
    )


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _short_model(model: str) -> str:
    """'claude-opus-4-5-20251101' -> 'Opus 4.5', as Anthropic names its models.

    Words form the name and numbers the version, so the older id order
    ('claude-3-5-sonnet-20241022') reads the same way: 'Sonnet 3.5'.
    """
    words, version = [], []
    for part in model.removeprefix("claude-").split("[", 1)[0].split("-"):
        if not part.isdigit():
            words.append(part)
        elif len(part) != 8:  # 8 digits is a date suffix
            version.append(part)
    if not words:
        return model
    name = " ".join(w.capitalize() for w in words)
    return f"{name} {'.'.join(version)}" if version else name
