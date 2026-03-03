from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .autostart import Autostart
from .config import Config
from .credentials import Credentials
from .popup import PopupWidget
from .providers import UsageData
from .providers.api import ApiProvider
from .providers.local import LocalProvider
from .settings_dialog import SettingsDialog


class _FetchWorker(QObject):
    finished = pyqtSignal(UsageData)

    def __init__(self, providers: list, days: int) -> None:
        super().__init__()
        self._providers = providers
        self._days = days

    def run(self) -> None:
        merged = UsageData()
        errors = []
        for provider in self._providers:
            result = provider.fetch(self._days)
            if result.error:
                errors.append(result.error)
            else:
                # Merge: use first provider's daily as base, extend model data
                if not merged.daily:
                    merged.daily = result.daily
                if result.by_model:
                    existing = {m.model for m in merged.by_model}
                    for m in result.by_model:
                        if m.model not in existing:
                            merged.by_model.append(m)
                            existing.add(m.model)
        if errors and not merged.daily:
            merged.error = "; ".join(errors)
        self.finished.emit(merged)


class TrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        config: Config,
        credentials: Credentials,
        autostart: Autostart,
        local_provider: LocalProvider,
        api_provider: ApiProvider,
    ) -> None:
        super().__init__()
        self._config = config
        self._credentials = credentials
        self._autostart = autostart
        self._local = local_provider
        self._api = api_provider
        self._thread: QThread | None = None
        self._latest_data: UsageData | None = None

        icon = QIcon.fromTheme("ctfl")
        if icon.isNull():
            icon = QIcon.fromTheme("utilities-system-monitor")
        self.setIcon(icon)
        self.setToolTip("ctfl — Claude Usage")

        self._popup = PopupWidget(config)
        self._popup.refresh_requested.connect(self.refresh)
        self._popup.settings_requested.connect(self._show_settings)

        self._build_menu()

        self.activated.connect(self._on_activated)

        self._timer = QTimer()
        self._timer.timeout.connect(self.refresh)
        self._start_timer()

        # Initial fetch
        self.refresh()

    def _build_menu(self) -> None:
        menu = QMenu()
        refresh_action = QAction("Refresh Now", menu)
        refresh_action.triggered.connect(self.refresh)
        menu.addAction(refresh_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._popup.isVisible():
                self._popup.close()
            else:
                self._popup.position_near_tray(self.geometry())
                if self._latest_data:
                    self._popup.update_data(self._latest_data)
                self._popup.show()

    def refresh(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        providers = self._get_providers()
        if not providers:
            self._popup.update_data(UsageData(error="No data source configured"))
            return

        self._thread = QThread()
        worker = _FetchWorker(providers, self._config.days_to_show)
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished.connect(self._on_data)
        worker.finished.connect(self._thread.quit)
        # prevent GC
        self._worker = worker
        self._thread.start()

    def _on_data(self, data: UsageData) -> None:
        self._latest_data = data

        # Update tooltip
        today = datetime.now().strftime("%Y-%m-%d")
        today_data = next((d for d in data.daily if d.date == today), None)
        if today_data:
            from .providers import format_tokens
            self.setToolTip(f"Claude: {format_tokens(today_data.total_tokens)} tokens today")

        if self._popup.isVisible():
            self._popup.update_data(data)

    def _get_providers(self) -> list:
        source = self._config.data_source
        providers = []
        if source in ("local", "both"):
            providers.append(self._local)
        if source in ("api", "both"):
            providers.append(self._api)
        return providers

    def _show_settings(self) -> None:
        self._popup.close()
        dlg = SettingsDialog(self._config, self._credentials, self._autostart)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self) -> None:
        self._start_timer()
        self.refresh()

    def _start_timer(self) -> None:
        self._timer.start(self._config.refresh_interval * 1000)

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
