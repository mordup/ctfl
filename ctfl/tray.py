from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .autostart import Autostart
from .config import Config
from .constants import (
    APP_DISPLAY_NAME,
    APP_NAME,
    DATE_FMT_ISO,
    ICON_THEME_NAME,
    TIME_FMT_HM,
)
from .credentials import Credentials
from .popup import PopupWidget
from .providers import UsageData, UsageProvider
from .providers.api import ApiProvider
from .providers.local import LocalProvider
from .providers.oauth import OAuthUsageProvider
from .settings_dialog import SettingsDialog

_ICON_PATHS = [
    Path(f"/usr/share/icons/hicolor/scalable/apps/{ICON_THEME_NAME}.svg"),
    Path(__file__).resolve().parent / "icons" / f"{ICON_THEME_NAME}.svg",      # bundled in package
    Path(__file__).resolve().parent.parent / "icons" / f"{ICON_THEME_NAME}.svg",  # dev layout
]


class _FetchWorker(QObject):
    finished = pyqtSignal(UsageData)

    def __init__(self, providers: list[UsageProvider], days: int) -> None:
        super().__init__()
        self._providers: list[UsageProvider] = providers
        self._days = days

    def run(self) -> None:
        merged = UsageData()
        errors = []
        try:
            for provider in self._providers:
                result = provider.fetch(self._days)
                if result.error:
                    errors.append(result.error)
                else:
                    if not merged.daily:
                        merged.daily = result.daily
                    if result.by_model:
                        existing = {m.model for m in merged.by_model}
                        for m in result.by_model:
                            if m.model not in existing:
                                merged.by_model.append(m)
                                existing.add(m.model)
                    if result.by_project:
                        existing_projects = {p.path for p in merged.by_project}
                        for p in result.by_project:
                            if p.path not in existing_projects:
                                merged.by_project.append(p)
                                existing_projects.add(p.path)
                    if result.limits:
                        merged.limits.extend(result.limits)
        except Exception as e:
            errors.append(f"Merge error: {e}")
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
        self._warned_limits: set[str] = set()

        icon = QIcon.fromTheme(ICON_THEME_NAME)
        if icon.isNull():
            for path in _ICON_PATHS:
                if path.exists():
                    icon = QIcon(str(path))
                    break
        if icon.isNull():
            icon = QIcon.fromTheme("utilities-system-monitor")
        self.setIcon(icon)
        self.setToolTip(APP_DISPLAY_NAME)

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

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        from . import __version__
        version_action = QAction(f"CTFL - v{__version__}", menu)
        version_action.triggered.connect(self._show_about)
        menu.addAction(version_action)

        menu.addSeparator()

        restart_action = QAction("Restart", menu)
        restart_action.triggered.connect(self._restart)
        menu.addAction(restart_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._popup.isVisible():
                self._popup.hide()
            else:
                self._popup.position_near_tray(self.geometry())
                if self._latest_data:
                    self._popup.update_data(self._latest_data)
                self._popup.show()

    def refresh(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        self._popup.show_loading()

        # Previous thread already finished — clear references
        self._thread = None
        self._worker = None

        providers = self._get_providers()
        if not providers:
            self._popup.update_data(UsageData(error="No data source configured"))
            return

        thread = QThread()
        worker = _FetchWorker(providers, self._config.days_to_show)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_data)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._on_thread_finished(thread))
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_thread_finished(self, thread: QThread) -> None:
        thread.deleteLater()
        if self._thread is thread:
            self._thread = None
            self._worker = None

    def _on_data(self, data: UsageData) -> None:
        self._latest_data = data
        self._update_tooltip(data)
        self._check_rate_limits(data)
        if self._popup.isVisible():
            self._popup.update_data(data)

    def _update_tooltip(self, data: UsageData) -> None:
        from .providers import format_cost, format_tokens
        from .providers.oauth import read_plan_name
        from .popup import _format_reset

        lines = [APP_DISPLAY_NAME]

        plan = read_plan_name()
        if plan and self._config.tooltip_today:
            today = datetime.now().strftime(DATE_FMT_ISO)
            today_data = next((d for d in data.daily if d.date == today), None)
            if today_data:
                today_line = f"Today: {format_tokens(today_data.total_tokens)} tokens"
                if today_data.cost_usd is not None:
                    today_line += f" · {format_cost(today_data.cost_usd)}"
                lines.append(f"{plan} — {today_line}")
            else:
                lines.append(plan)
        elif plan:
            lines.append(plan)
        elif self._config.tooltip_today:
            today = datetime.now().strftime(DATE_FMT_ISO)
            today_data = next((d for d in data.daily if d.date == today), None)
            if today_data:
                today_line = f"Today: {format_tokens(today_data.total_tokens)} tokens"
                if today_data.cost_usd is not None:
                    today_line += f" · {format_cost(today_data.cost_usd)}"
                lines.append(today_line)

        if self._config.tooltip_limits and data.limits:
            lines.append("")
            for info in data.limits:
                reset = _format_reset(info.resets_at)
                reset_part = f" ({reset.lower()})" if reset else ""
                lines.append(f"{info.name}: {info.utilization:.0f}%{reset_part}")

        if self._config.tooltip_sync:
            lines.append("")
            lines.append(f"Last sync: {datetime.now().strftime(TIME_FMT_HM)}")

        self.setToolTip("\n".join(lines))

    def _check_rate_limits(self, data: UsageData) -> None:
        if not self._config.rate_limit_warning or not data.limits:
            return
        threshold = self._config.rate_limit_threshold
        for info in data.limits:
            if info.utilization >= threshold:
                if info.name not in self._warned_limits:
                    self._warned_limits.add(info.name)
                    self.showMessage(
                        APP_DISPLAY_NAME,
                        f"{info.name} at {info.utilization:.0f}%",
                        QSystemTrayIcon.MessageIcon.Warning,
                        5000,
                    )
            else:
                self._warned_limits.discard(info.name)

    def _get_providers(self) -> list[UsageProvider]:
        source = self._config.data_source
        providers: list[UsageProvider] = []
        if source in ("local", "both"):
            providers.append(self._local)
        if source in ("api", "both"):
            providers.append(self._api)
        # Only fetch OAuth rate limits when they'll actually be shown
        if self._config.tooltip_limits or self._config.rate_limit_warning:
            providers.append(self._oauth)
        return providers

    def _show_about(self) -> None:
        from .about_dialog import AboutDialog
        AboutDialog(self.contextMenu()).exec()

    def _show_settings(self) -> None:
        self._popup.hide()
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

    def _cleanup_thread(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(2000)

    def _restart(self) -> None:
        self._cleanup_thread()
        from PyQt6.QtCore import QProcess
        from PyQt6.QtWidgets import QApplication
        QProcess.startDetached(sys.executable, ["-m", APP_NAME])
        QApplication.quit()

    def _quit(self) -> None:
        self._cleanup_thread()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
