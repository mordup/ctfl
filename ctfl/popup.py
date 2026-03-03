from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .providers import UsageData, format_tokens


class PopupWidget(QWidget):
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._config = config
        self._build_ui()
        self.setMinimumWidth(480)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Claude Usage")
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        header.addWidget(title)
        header.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.setFlat(True)
        settings_btn.clicked.connect(self.settings_requested.emit)
        header.addWidget(settings_btn)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(24, 24)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Summary
        self._summary_label = QLabel()
        layout.addWidget(self._summary_label)

        # Tabs
        self._tabs = QTabWidget()
        self._daily_table = QTableWidget()
        self._model_table = QTableWidget()
        self._tabs.addTab(self._daily_table, "Daily")
        self._tabs.addTab(self._model_table, "By Model")
        layout.addWidget(self._tabs)

        # Footer
        footer = QHBoxLayout()
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        footer.addWidget(self._status_label)
        footer.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        footer.addWidget(refresh_btn)
        layout.addLayout(footer)

    def update_data(self, data: UsageData) -> None:
        if data.error:
            self._summary_label.setText(f"Error: {data.error}")
            self._daily_table.setRowCount(0)
            self._model_table.setRowCount(0)
            self._update_status()
            return

        # Summary
        today = datetime.now().strftime("%Y-%m-%d")
        today_data = next((d for d in data.daily if d.date == today), None)
        total_tokens = sum(d.total_tokens for d in data.daily)
        total_msgs = sum(d.message_count for d in data.daily)

        parts = []
        if today_data:
            parts.append(
                f"Today: {format_tokens(today_data.total_tokens)} tokens, "
                f"{today_data.message_count} messages"
            )
        parts.append(
            f"Period total: {format_tokens(total_tokens)} tokens, "
            f"{total_msgs} messages"
        )
        self._summary_label.setText("\n".join(parts))

        # Daily table
        show_cache = self._config.show_cache_tokens
        daily_cols = ["Date", "Messages", "Sessions", "Tokens"]
        if show_cache:
            daily_cols.extend(["Cache Read", "Cache Write"])

        self._daily_table.setColumnCount(len(daily_cols))
        self._daily_table.setHorizontalHeaderLabels(daily_cols)
        self._daily_table.setRowCount(len(data.daily))
        self._daily_table.verticalHeader().setVisible(False)

        for i, day in enumerate(data.daily):
            self._daily_table.setItem(i, 0, QTableWidgetItem(day.date))
            self._daily_table.setItem(i, 1, _num_item(day.message_count))
            self._daily_table.setItem(i, 2, _num_item(day.session_count))
            self._daily_table.setItem(i, 3, _num_item(day.total_tokens, fmt=True))
            if show_cache:
                self._daily_table.setItem(i, 4, _num_item(day.cache_read_tokens, fmt=True))
                self._daily_table.setItem(i, 5, _num_item(day.cache_creation_tokens, fmt=True))

        self._daily_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        # Model table
        model_cols = ["Model", "Input", "Output"]
        if show_cache:
            model_cols.extend(["Cache Read", "Cache Write"])
        model_cols.append("Total")

        self._model_table.setColumnCount(len(model_cols))
        self._model_table.setHorizontalHeaderLabels(model_cols)
        self._model_table.setRowCount(len(data.by_model))
        self._model_table.verticalHeader().setVisible(False)

        for i, mt in enumerate(data.by_model):
            col = 0
            self._model_table.setItem(i, col, QTableWidgetItem(_short_model(mt.model)))
            col += 1
            self._model_table.setItem(i, col, _num_item(mt.input_tokens, fmt=True))
            col += 1
            self._model_table.setItem(i, col, _num_item(mt.output_tokens, fmt=True))
            col += 1
            if show_cache:
                self._model_table.setItem(i, col, _num_item(mt.cache_read_tokens, fmt=True))
                col += 1
                self._model_table.setItem(i, col, _num_item(mt.cache_creation_tokens, fmt=True))
                col += 1
            self._model_table.setItem(i, col, _num_item(mt.total, fmt=True))

        self._model_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        self._update_status()

    def _update_status(self) -> None:
        self._status_label.setText(
            f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
        )

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


def _num_item(value: int, fmt: bool = False) -> QTableWidgetItem:
    text = format_tokens(value) if fmt else str(value)
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


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
    return "-".join(cleaned)
