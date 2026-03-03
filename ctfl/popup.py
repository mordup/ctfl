from __future__ import annotations

from datetime import datetime as _dt, timezone as _tz

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .providers import RateLimitInfo, UsageData, format_tokens


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
        self.setWindowIcon(QIcon.fromTheme("ctfl"))
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

        # Tabs
        self._tabs = QTabWidget()
        self._daily_chart = _BarChartWidget()
        self._model_chart = _BarChartWidget()
        self._tabs.addTab(self._daily_chart, "Daily")
        self._tabs.addTab(self._model_chart, "By Model")
        self._tabs.currentChanged.connect(lambda _: self._fit_to_content())
        layout.addWidget(self._tabs)

        # Footer
        footer = QHBoxLayout()
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray;")
        footer.addWidget(self._status_label)
        footer.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        footer.addWidget(refresh_btn)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        footer.addWidget(settings_btn)
        layout.addLayout(footer)

    def update_data(self, data: UsageData) -> None:
        self._update_limits(data.limits)

        if data.error:
            self._summary_label.setText(f"Error: {data.error}")
            self._daily_chart.set_rows([])
            self._model_chart.set_rows([])
            self._update_status()
            return

        # Summary
        today = _dt.now().strftime("%Y-%m-%d")
        today_data = next((d for d in data.daily if d.date == today), None)
        total_tokens = sum(d.total_tokens for d in data.daily)

        parts = []
        if today_data:
            parts.append(
                f"Today: {format_tokens(today_data.total_tokens)} tokens"
            )
        parts.append(
            f"Period total: {format_tokens(total_tokens)} tokens"
        )
        html = "".join(f"<p style='margin: 2px 0;'>{p}</p>" for p in parts)
        self._summary_label.setText(html)

        # Daily bar chart
        max_day_tokens = max((d.total_tokens for d in data.daily), default=1) or 1
        daily_rows = []
        for day in data.daily:
            # Format date: "Mar 03" from "2026-03-03"
            try:
                label = _dt.strptime(day.date, "%Y-%m-%d").strftime("%d %B").title()
            except ValueError:
                label = day.date
            detail = f"{format_tokens(day.total_tokens)} tokens"
            daily_rows.append((label, day.total_tokens, max_day_tokens, detail))
        self._daily_chart.set_rows(daily_rows)

        # Model bar chart
        max_model_total = max((m.total for m in data.by_model), default=1) or 1
        model_rows = []
        for mt in data.by_model:
            label = _short_model(mt.model)
            detail = format_tokens(mt.total)
            model_rows.append((label, mt.total, max_model_total, detail))
        self._model_chart.set_rows(model_rows)

        self._update_status()
        self._fit_to_content()

    def _update_limits(self, limits: list[RateLimitInfo]) -> None:
        # Clear previous widgets
        while self._limits_layout.count():
            item = self._limits_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

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

        for info in limits:
            reset_text = _format_reset(info.resets_at)
            text = info.name
            if reset_text:
                text += f"<br><span style='color: gray;'>{reset_text}</span>"
            name_label = QLabel(text)
            self._limits_layout.addWidget(name_label)

            bar_row = QHBoxLayout()
            bar_row.setSpacing(8)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(info.utilization))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { background: #3a3a3a; border: none; border-radius: 5px; }"
                "QProgressBar::chunk { background: #5B9BF6; border-radius: 5px; }"
            )
            pct_label = QLabel(f"{info.utilization:.0f}% used")

            bar_row.addWidget(bar, 1)
            bar_row.addWidget(pct_label)
            self._limits_layout.addLayout(bar_row)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        self._limits_layout.addWidget(sep)

    def _update_status(self) -> None:
        self._status_label.setText(
            f"Last updated: {_dt.now().strftime('%H:%M')}"
        )

    def _fit_to_content(self) -> None:
        # Size the tab widget to fit the active tab content
        active = self._tabs.currentWidget()
        if active:
            hint = active.sizeHint()
            tab_bar_h = self._tabs.tabBar().sizeHint().height()
            needed = hint.height() + tab_bar_h + 8
            # Only grow, never shrink (avoids flicker on refresh)
            if needed > self._tabs.minimumHeight():
                self._tabs.setMinimumHeight(needed)
        self.adjustSize()

    def show_loading(self) -> None:
        self._summary_label.setText("Loading...")

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

    def set_rows(self, rows: list[tuple[str, int, int, str]]) -> None:
        """Set bar chart data. Each row is (label, value, max_value, detail_text)."""
        # Clear previous rows (keep the trailing stretch)
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                _clear_layout(item.layout())

        for label_text, value, max_value, detail_text in rows:
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
            label.setMinimumWidth(70)
            top.addWidget(label)
            top.addStretch()
            detail = QLabel(detail_text)
            detail.setStyleSheet("color: #aaa; font-size: 11px;")
            top.addWidget(detail)
            row_layout.addLayout(top)

            # Bar
            bar = QProgressBar()
            bar.setRange(0, max_value)
            bar.setValue(value)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { background: #3a3a3a; border: none; border-radius: 5px; }"
                "QProgressBar::chunk { background: #5B9BF6; border-radius: 5px; }"
            )
            row_layout.addWidget(bar)

            self._layout.insertWidget(self._layout.count() - 1, row_widget)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().setParent(None)
        elif item.layout():
            _clear_layout(item.layout())


def _format_reset(resets_at: str | None) -> str:
    if not resets_at:
        return ""
    try:
        reset_time = _dt.fromisoformat(resets_at)
        now = _dt.now(_tz.utc)
        delta = reset_time - now
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "Resets soon"
        if total_seconds < 60:
            return "Resets in <1 min"
        if total_seconds < 3600:
            return f"Resets in {total_seconds // 60} min"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours < 24:
            return f"Resets in {hours} hr {minutes} min"
        # More than a day: show weekday and time
        local_time = reset_time.astimezone()
        return f"Resets {local_time.strftime('%a %H:%M')}"
    except (ValueError, TypeError):
        return ""


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
