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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .autostart import Autostart
from .config import Config
from .constants import ICON_THEME_NAME
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
        self.setWindowTitle("Settings")
        self.setWindowIcon(QIcon.fromTheme(ICON_THEME_NAME))
        self.setMinimumWidth(600)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        columns = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()

        # --- Left column ---

        # Data source
        source_group = QGroupBox("Usage Data Source")
        source_layout = QVBoxLayout(source_group)
        self._source_buttons = QButtonGroup(self)
        self._rb_local = QRadioButton("Local logs")
        self._rb_api = QRadioButton("Admin API")
        self._rb_both = QRadioButton("Both")
        self._source_buttons.addButton(self._rb_local, 0)
        self._source_buttons.addButton(self._rb_api, 1)
        self._source_buttons.addButton(self._rb_both, 2)
        source_layout.addWidget(self._rb_local)
        source_layout.addWidget(self._rb_api)
        source_layout.addWidget(self._rb_both)
        left.addWidget(source_group)

        # API key
        api_group = QGroupBox("Admin API Key")
        api_layout = QFormLayout(api_group)
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Anthropic Admin API key")
        api_layout.addRow("API Key:", self._api_key_input)
        left.addWidget(api_group)
        self._api_group = api_group

        # Display
        display_group = QGroupBox("Display")
        display_layout = QFormLayout(display_group)
        self._days_spin = QSpinBox()
        self._days_spin.setRange(1, 90)
        display_layout.addRow("Days to show:", self._days_spin)
        self._breakdown_check = QCheckBox("Show token breakdown")
        display_layout.addRow(self._breakdown_check)
        self._estimate_costs_check = QCheckBox("Estimate costs from local data")
        display_layout.addRow(self._estimate_costs_check)
        self._auto_refresh_check = QCheckBox("Auto-refresh")
        display_layout.addRow(self._auto_refresh_check)
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(1, 60)
        self._refresh_spin.setSuffix(" min")
        display_layout.addRow("Refresh interval:", self._refresh_spin)
        self._auto_refresh_check.toggled.connect(self._refresh_spin.setEnabled)
        left.addWidget(display_group)

        left.addStretch()

        # --- Right column ---

        # Session key (for rate limits)
        session_group = QGroupBox("Rate Limits (claude.ai)")
        session_layout = QFormLayout(session_group)
        self._session_key_input = QLineEdit()
        self._session_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._session_key_input.setPlaceholderText("sk-ant-sid...")
        session_layout.addRow("Session Key:", self._session_key_input)
        self._cf_clearance_input = QLineEdit()
        self._cf_clearance_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._cf_clearance_input.setPlaceholderText("cf_clearance value")
        session_layout.addRow("CF Clearance:", self._cf_clearance_input)
        hint = QLabel("From claude.ai → DevTools → Cookies")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        session_layout.addRow(hint)
        right.addWidget(session_group)

        # Tooltip
        tooltip_group = QGroupBox("Tooltip Info")
        tooltip_layout = QVBoxLayout(tooltip_group)
        self._tooltip_today = QCheckBox("Today's usage")
        self._tooltip_limits = QCheckBox("Rate limits")
        self._tooltip_sync = QCheckBox("Last sync time")
        tooltip_layout.addWidget(self._tooltip_today)
        tooltip_layout.addWidget(self._tooltip_limits)
        tooltip_layout.addWidget(self._tooltip_sync)
        right.addWidget(tooltip_group)

        # Notifications
        notif_group = QGroupBox("Notifications")
        notif_layout = QFormLayout(notif_group)
        self._rate_limit_check = QCheckBox("Warn when rate limit is high")
        notif_layout.addRow(self._rate_limit_check)
        self._rate_limit_spin = QSpinBox()
        self._rate_limit_spin.setRange(1, 100)
        self._rate_limit_spin.setSuffix("%")
        notif_layout.addRow("Threshold:", self._rate_limit_spin)
        self._rate_limit_check.toggled.connect(self._rate_limit_spin.setEnabled)
        right.addWidget(notif_group)

        # System
        system_group = QGroupBox("System")
        system_layout = QVBoxLayout(system_group)
        self._autostart_check = QCheckBox("Start on login")
        system_layout.addWidget(self._autostart_check)
        right.addWidget(system_group)

        right.addStretch()

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns)

        # Wire source radio to enable/disable API key
        self._source_buttons.idToggled.connect(self._on_source_changed)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

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

        existing_session = self._credentials.get_session_key()
        if existing_session:
            self._session_key_input.setText(existing_session)
        existing_cf = self._credentials.get_cf_clearance()
        if existing_cf:
            self._cf_clearance_input.setText(existing_cf)

        self._days_spin.setValue(self._config.days_to_show)
        self._breakdown_check.setChecked(self._config.show_token_breakdown)
        self._estimate_costs_check.setChecked(self._config.estimate_costs)
        self._auto_refresh_check.setChecked(self._config.auto_refresh)
        self._refresh_spin.setEnabled(self._config.auto_refresh)
        self._refresh_spin.setValue(self._config.refresh_interval // 60)
        self._tooltip_today.setChecked(self._config.tooltip_today)
        self._tooltip_limits.setChecked(self._config.tooltip_limits)
        self._tooltip_sync.setChecked(self._config.tooltip_sync)
        self._rate_limit_check.setChecked(self._config.rate_limit_warning)
        self._rate_limit_spin.setValue(self._config.rate_limit_threshold)
        self._rate_limit_spin.setEnabled(self._config.rate_limit_warning)
        self._autostart_check.setChecked(self._autostart.is_enabled())

        # Trigger initial state
        self._on_source_changed(self._source_buttons.checkedId(), True)

    def _apply(self) -> None:
        source_map = {0: "local", 1: "api", 2: "both"}
        self._config.data_source = source_map.get(
            self._source_buttons.checkedId(), "local"
        )
        self._config.show_token_breakdown = self._breakdown_check.isChecked()
        self._config.estimate_costs = self._estimate_costs_check.isChecked()
        self._config.auto_refresh = self._auto_refresh_check.isChecked()
        self._config.refresh_interval = self._refresh_spin.value() * 60
        self._config.days_to_show = self._days_spin.value()

        # Tooltip
        self._config.tooltip_today = self._tooltip_today.isChecked()
        self._config.tooltip_limits = self._tooltip_limits.isChecked()
        self._config.tooltip_sync = self._tooltip_sync.isChecked()

        # Notifications
        self._config.rate_limit_warning = self._rate_limit_check.isChecked()
        self._config.rate_limit_threshold = self._rate_limit_spin.value()

        # API key
        key_text = self._api_key_input.text().strip()
        try:
            if key_text:
                self._credentials.set_api_key(key_text)
            elif self._config.data_source == "local":
                pass  # don't delete key just because field is empty on local mode
            else:
                self._credentials.delete_api_key()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        # Session key + cf_clearance
        session_text = self._session_key_input.text().strip()
        cf_text = self._cf_clearance_input.text().strip()
        try:
            if session_text:
                self._credentials.set_session_key(session_text)
            else:
                self._credentials.delete_session_key()
            if cf_text:
                self._credentials.set_cf_clearance(cf_text)
            else:
                self._credentials.delete_cf_clearance()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        # Autostart
        try:
            if self._autostart_check.isChecked():
                self._autostart.enable()
                self._config.autostart = True
            else:
                self._autostart.disable()
                self._config.autostart = False
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        self.settings_changed.emit()
        self.accept()
