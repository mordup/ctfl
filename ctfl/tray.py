from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import __version__
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


class _UpdateCheckWorker(QObject):
    finished = pyqtSignal(object)  # dict or None

    def run(self) -> None:
        from .updater import check_for_update
        self.finished.emit(check_for_update())


class _UpdateApplyWorker(QObject):
    finished = pyqtSignal(str)  # error message or empty string on success

    def __init__(self, release: dict) -> None:
        super().__init__()
        self._release = release

    def run(self) -> None:
        from .updater import apply_update
        err = apply_update(self._release)
        self.finished.emit(err or "")


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
        self._update_thread: QThread | None = None
        self._latest_data: UsageData | None = None
        self._pending_release: dict | None = None
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

        # Periodic update checks
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._check_for_updates)
        self._start_update_timer()

        # Initial check after short delay
        if self._config.update_check_interval > 0:
            QTimer.singleShot(5000, self._check_for_updates)

    def _build_menu(self) -> None:
        menu = QMenu()
        refresh_action = QAction("Refresh Now", menu)
        refresh_action.triggered.connect(self.refresh)
        menu.addAction(refresh_action)

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        self._update_action = QAction("Check for Updates", menu)
        self._update_action.triggered.connect(self._on_update_action)
        menu.addAction(self._update_action)

        menu.addSeparator()

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
        from .providers import format_cost, format_reset, format_tokens
        from .providers.oauth import read_plan_name

        # Header: app name + plan
        plan = read_plan_name()
        header = f"{APP_DISPLAY_NAME} — {plan}" if plan else APP_DISPLAY_NAME
        lines = [header]

        # Second line: today + sync time
        sync_time = f"synced {datetime.now().strftime(TIME_FMT_HM)}" \
            if self._config.tooltip_sync else None
        today_line = self._tooltip_today_line(data, format_tokens, format_cost) \
            if self._config.tooltip_today else None

        if today_line and sync_time:
            lines.append(f"{today_line} — {sync_time}")
        elif today_line:
            lines.append(today_line)
        elif sync_time:
            lines.append(sync_time.capitalize())

        # Limits
        if self._config.tooltip_limits and data.limits:
            limit_lines = self._tooltip_limits_lines(data, format_reset)
            if limit_lines:
                lines.append("")
                lines.extend(limit_lines)

        self.setToolTip("\n".join(lines))

    def _tooltip_today_line(self, data, format_tokens, format_cost):
        today = datetime.now().strftime(DATE_FMT_ISO)
        today_data = next((d for d in data.daily if d.date == today), None)
        if not today_data:
            return None
        line = f"Today: {format_tokens(today_data.total_tokens)} tokens"
        if today_data.cost_usd is not None:
            line += f" · {format_cost(today_data.cost_usd)}"
        return line

    def _tooltip_limits_lines(self, data, format_reset):
        from .providers.prediction import predict_exhaustion

        # Separate session (five_hour) from weekly (seven_day*) limits
        session_lines = []
        weekly_parts = []
        weekly_reset = ""
        weekly_pred = None

        for info in data.limits:
            pred = predict_exhaustion(info, info.window_key)
            if info.window_key == "five_hour":
                parts = [f"{info.name}: {info.utilization:.0f}%"]
                if pred:
                    parts.append(pred)
                reset = format_reset(info.resets_at)
                short = reset.removeprefix("Resets in ").removeprefix("Resets ")
                if short:
                    parts.append(f"resets {short}")
                session_lines.append(" | ".join(parts))
            else:
                # Weekly limits — collect for grouping
                label = info.name
                if label.startswith("Weekly (") and label.endswith(")"):
                    label = label[8:-1]  # "Sonnet", "Opus"
                weekly_parts.append(f"{label}: {info.utilization:.0f}%")
                if pred and weekly_pred is None:
                    weekly_pred = pred
                if not weekly_reset and info.resets_at:
                    reset = format_reset(info.resets_at)
                    weekly_reset = reset.removeprefix("Resets in ").removeprefix("Resets ")

        result = session_lines[:]

        if weekly_parts:
            line = " · ".join(weekly_parts)
            if weekly_pred:
                line += f" | {weekly_pred}"
            elif weekly_reset:
                line += f" | resets {weekly_reset}"
            result.append(line)

        return result

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

    def _check_for_updates(self) -> None:
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        thread = QThread()
        worker = _UpdateCheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_update_check_done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._on_update_thread_finished(thread))
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    def _on_update_thread_finished(self, thread: QThread) -> None:
        thread.deleteLater()
        if self._update_thread is thread:
            self._update_thread = None
            self._update_worker = None

    def _on_update_check_done(self, release) -> None:
        if release is None:
            if getattr(self, "_manual_update_check", False):
                self._manual_update_check = False
                self._update_action.setText("Check for Updates")
                self._update_action.setEnabled(True)
                self.showMessage(
                    APP_DISPLAY_NAME,
                    "You're on the latest version",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            return
        self._manual_update_check = False
        self._pending_release = release
        version = release["version"]
        self._update_action.setText(f"Update to v{version}")

        from .updater import can_auto_update
        if can_auto_update():
            self.showMessage(
                APP_DISPLAY_NAME,
                f"v{version} is available — click 'Update to v{version}' in the menu to install",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        else:
            self.showMessage(
                APP_DISPLAY_NAME,
                f"v{version} is available — click 'Update to v{version}' in the menu to download",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _on_update_action(self) -> None:
        if self._pending_release:
            self._show_update_dialog(self._pending_release)
        else:
            self._update_action.setText("Checking...")
            self._update_action.setEnabled(False)
            self._manual_update_check = True
            self._check_for_updates()
            # Re-enable after check completes via a connection
            QTimer.singleShot(10000, self._reset_update_action)

    def _reset_update_action(self) -> None:
        if not self._pending_release:
            self._update_action.setText("Check for Updates")
            self._update_action.setEnabled(True)

    def _open_release_page(self, url: str) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _show_update_dialog(self, release: dict) -> None:
        from PyQt6.QtWidgets import QMessageBox

        from .updater import InstallMethod, can_auto_update, detect_install_method

        version = release["version"]
        method = detect_install_method()

        dlg = QMessageBox()
        dlg.setWindowTitle(f"Update to v{version}")
        dlg.setIcon(QMessageBox.Icon.Information)

        if can_auto_update():
            method_name = "pip" if method == InstallMethod.PIP else "AppImage"
            dlg.setText(
                f"CTFL v{version} is available (you have v{__version__}).\n\n"
                f"Install method: {method_name}"
            )
            update_btn = dlg.addButton("Update Now", QMessageBox.ButtonRole.AcceptRole)
            download_btn = dlg.addButton("Download", QMessageBox.ButtonRole.ActionRole)
            dlg.addButton(QMessageBox.StandardButton.Cancel)
            dlg.exec()
            if dlg.clickedButton() == update_btn:
                self._apply_update(release)
            elif dlg.clickedButton() == download_btn:
                self._open_release_page(release["url"])
        else:
            dlg.setText(
                f"CTFL v{version} is available (you have v{__version__}).\n\n"
                f"Auto-update is not available for system package installs."
            )
            download_btn = dlg.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
            dlg.addButton(QMessageBox.StandardButton.Cancel)
            dlg.exec()
            if dlg.clickedButton() == download_btn:
                self._open_release_page(release["url"])

    def _apply_update(self, release: dict) -> None:

        self._update_action.setText("Updating...")
        self._update_action.setEnabled(False)

        thread = QThread()
        worker = _UpdateApplyWorker(release)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_update_applied)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda: self._on_update_thread_finished(thread))
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    def _on_update_applied(self, error: str) -> None:
        from PyQt6.QtWidgets import QMessageBox

        if error:
            QMessageBox.warning(None, "Update Failed", error)
            self._update_action.setText(f"Update to v{self._pending_release['version']}")
            self._update_action.setEnabled(True)
        else:
            reply = QMessageBox.information(
                None,
                "Update Complete",
                f"CTFL has been updated to v{self._pending_release['version']}.\n"
                f"Restart now to use the new version?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._restart()

    def _show_about(self) -> None:
        from .about_dialog import AboutDialog
        AboutDialog(self.contextMenu()).exec()

    def _show_settings(self) -> None:
        was_popup_visible = self._popup.isVisible()
        self._popup.hide()
        dlg = SettingsDialog(self._config, self._credentials, self._autostart)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()
        if was_popup_visible:
            self._popup.show()
            self._popup.activateWindow()

    def _on_settings_changed(self) -> None:
        self._start_timer()
        self._start_update_timer()
        self.refresh()

    def _start_timer(self) -> None:
        if self._config.auto_refresh:
            self._timer.start(self._config.refresh_interval * 1000)
        else:
            self._timer.stop()

    def _start_update_timer(self) -> None:
        hours = self._config.update_check_interval
        if hours > 0:
            self._update_timer.start(hours * 3600 * 1000)
        else:
            self._update_timer.stop()

    def _cleanup_thread(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(2000)

    def _cleanup_update_thread(self) -> None:
        if self._update_thread is None or not self._update_thread.isRunning():
            return
        self._update_thread.quit()
        if not self._update_thread.wait(5000):
            self._update_thread.terminate()
            self._update_thread.wait(2000)

    def _restart(self) -> None:
        self._cleanup_thread()
        self._cleanup_update_thread()
        from PyQt6.QtCore import QProcess
        from PyQt6.QtWidgets import QApplication
        QProcess.startDetached(sys.executable, ["-m", APP_NAME])
        QApplication.quit()

    def _quit(self) -> None:
        self._cleanup_thread()
        self._cleanup_update_thread()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
