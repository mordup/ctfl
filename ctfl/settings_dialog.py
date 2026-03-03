from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .autostart import Autostart
from .config import Config
from .credentials import Credentials


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal()

    def __init__(
        self,
        config: Config,
        credentials: Credentials,
        autostart: Autostart,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._credentials = credentials
        self._autostart = autostart
        self.setWindowTitle("Claude Tracker For Linux — Settings")
        self.setWindowIcon(QIcon.fromTheme("ctfl"))
        self.setMinimumWidth(400)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Data source
        source_group = QGroupBox("Usage Data Source")
        source_layout = QVBoxLayout(source_group)
        self._source_buttons = QButtonGroup(self)
        self._rb_local = QRadioButton("Local logs (Claude Code conversation files)")
        self._rb_api = QRadioButton("Admin API (organization usage)")
        self._rb_both = QRadioButton("Both")
        self._source_buttons.addButton(self._rb_local, 0)
        self._source_buttons.addButton(self._rb_api, 1)
        self._source_buttons.addButton(self._rb_both, 2)
        source_layout.addWidget(self._rb_local)
        source_layout.addWidget(self._rb_api)
        source_layout.addWidget(self._rb_both)
        layout.addWidget(source_group)

        # API key
        api_group = QGroupBox("Admin API Key")
        api_layout = QFormLayout(api_group)
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Enter Anthropic Admin API key")
        api_layout.addRow("API Key:", self._api_key_input)
        layout.addWidget(api_group)
        self._api_group = api_group

        # Display
        display_group = QGroupBox("Display")
        display_layout = QFormLayout(display_group)
        self._days_spin = QSpinBox()
        self._days_spin.setRange(1, 90)
        display_layout.addRow("Days to show:", self._days_spin)
        self._auto_refresh_check = QCheckBox("Auto-refresh")
        display_layout.addRow(self._auto_refresh_check)
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(1, 60)
        self._refresh_spin.setSuffix(" min")
        display_layout.addRow("Refresh interval:", self._refresh_spin)
        self._auto_refresh_check.toggled.connect(self._refresh_spin.setEnabled)
        layout.addWidget(display_group)

        # Tooltip
        tooltip_group = QGroupBox("Tooltip Info")
        tooltip_layout = QVBoxLayout(tooltip_group)
        self._tooltip_today = QCheckBox("Today's usage")
        self._tooltip_limits = QCheckBox("Rate limits")
        self._tooltip_sync = QCheckBox("Last sync time")
        tooltip_layout.addWidget(self._tooltip_today)
        tooltip_layout.addWidget(self._tooltip_limits)
        tooltip_layout.addWidget(self._tooltip_sync)
        layout.addWidget(tooltip_group)

        # Autostart
        self._autostart_check = QCheckBox("Start on login")
        layout.addWidget(self._autostart_check)

        # Wire source radio to enable/disable API key
        self._source_buttons.idToggled.connect(self._on_source_changed)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_source_changed(self, id_: int, checked: bool) -> None:
        if checked:
            needs_api = id_ in (1, 2)
            self._api_group.setEnabled(needs_api)

    def _load(self) -> None:
        source = self._config.data_source
        if source == "api":
            self._rb_api.setChecked(True)
        elif source == "both":
            self._rb_both.setChecked(True)
        else:
            self._rb_local.setChecked(True)

        existing_key = self._credentials.get_api_key()
        if existing_key:
            self._api_key_input.setText(existing_key)

        self._days_spin.setValue(self._config.days_to_show)
        self._auto_refresh_check.setChecked(self._config.auto_refresh)
        self._refresh_spin.setEnabled(self._config.auto_refresh)
        self._refresh_spin.setValue(self._config.refresh_interval // 60)
        self._tooltip_today.setChecked(self._config.tooltip_today)
        self._tooltip_limits.setChecked(self._config.tooltip_limits)
        self._tooltip_sync.setChecked(self._config.tooltip_sync)
        self._autostart_check.setChecked(self._autostart.is_enabled())

        # Trigger initial state
        self._on_source_changed(self._source_buttons.checkedId(), True)

    def _apply(self) -> None:
        source_map = {0: "local", 1: "api", 2: "both"}
        self._config.data_source = source_map.get(
            self._source_buttons.checkedId(), "local"
        )
        self._config.auto_refresh = self._auto_refresh_check.isChecked()
        self._config.refresh_interval = self._refresh_spin.value() * 60
        self._config.days_to_show = self._days_spin.value()

        # Tooltip
        self._config.tooltip_today = self._tooltip_today.isChecked()
        self._config.tooltip_limits = self._tooltip_limits.isChecked()
        self._config.tooltip_sync = self._tooltip_sync.isChecked()

        # API key
        key_text = self._api_key_input.text().strip()
        if key_text:
            self._credentials.set_api_key(key_text)
        elif self._config.data_source == "local":
            pass  # don't delete key just because field is empty on local mode
        else:
            self._credentials.delete_api_key()

        # Autostart
        if self._autostart_check.isChecked():
            self._autostart.enable()
            self._config.autostart = True
        else:
            self._autostart.disable()
            self._config.autostart = False

        self.settings_changed.emit()
        self.accept()
