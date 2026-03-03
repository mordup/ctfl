from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

_ICON_PATHS = [
    Path("/usr/share/icons/hicolor/scalable/apps/ctfl.svg"),
    Path(__file__).resolve().parent.parent / "icons" / "ctfl.svg",
]

from .autostart import Autostart
from .config import Config
from .credentials import Credentials
from .popup import PopupWidget
from .providers import UsageData
from .providers.api import ApiProvider
from .providers.local import LocalProvider
from .providers.oauth import OAuthUsageProvider
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
                if result.limits:
                    merged.limits.extend(result.limits)
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
        oauth_provider: OAuthUsageProvider,
    ) -> None:
        super().__init__()
        self._config = config
        self._credentials = credentials
        self._autostart = autostart
        self._local = local_provider
        self._api = api_provider
        self._oauth = oauth_provider
        self._thread: QThread | None = None
        self._latest_data: UsageData | None = None

        icon = QIcon.fromTheme("ctfl")
        if icon.isNull():
            for path in _ICON_PATHS:
                if path.exists():
                    icon = QIcon(str(path))
                    break
        if icon.isNull():
            icon = QIcon.fromTheme("utilities-system-monitor")
        self.setIcon(icon)
        self.setToolTip("Claude Tracker For Linux")

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
        show_action = QAction("Show Usage", menu)
        show_action.triggered.connect(self._show_popup)
        menu.addAction(show_action)

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

        # Build rich tooltip
        from .providers import format_tokens
        from .popup import _format_reset

        lines = ["Claude Tracker For Linux"]

        # Today's usage right under the title
        today = datetime.now().strftime("%Y-%m-%d")
        today_data = next((d for d in data.daily if d.date == today), None)
        if today_data:
            lines.append(f"Today: {format_tokens(today_data.total_tokens)} tokens")

        # Blank line then rate limits
        if data.limits:
            lines.append("")
            for info in data.limits:
                reset = _format_reset(info.resets_at)
                reset_part = f" ({reset.lower()})" if reset else ""
                lines.append(f"{info.name}: {info.utilization:.0f}%{reset_part}")

        self.setToolTip("\n".join(lines))

        if self._popup.isVisible():
            self._popup.update_data(data)

    def _get_providers(self) -> list:
        source = self._config.data_source
        providers = []
        if source in ("local", "both"):
            providers.append(self._local)
        if source in ("api", "both"):
            providers.append(self._api)
        providers.append(self._oauth)
        return providers

    def _show_popup(self) -> None:
        self._popup.position_near_tray(self.geometry())
        if self._latest_data:
            self._popup.update_data(self._latest_data)
        self._popup.show()

    def _show_settings(self) -> None:
        self._popup.close()
        dlg = SettingsDialog(self._config, self._credentials, self._autostart)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self) -> None:
        self._start_timer()
        self.refresh()

    def _start_timer(self) -> None:
        if self._config.auto_refresh:
            self._timer.start(self._config.refresh_interval * 1000)
        else:
            self._timer.stop()

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
