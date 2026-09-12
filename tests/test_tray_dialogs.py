"""Dialog registry and update-menu state on the tray, headless.

The tray is not constructed: it needs providers and a running fetch. The
methods under test only touch `_dialogs`, `_update_action`,
`_pending_release` and `_installed_version`, so a stub carrying those is
enough.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ctfl import __version__
from ctfl.about_dialog import AboutDialog
from ctfl.tray import TrayIcon


class _Action:
    def __init__(self) -> None:
        self.text = "Check for Updates"
        self.enabled = True

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _Tray:
    _show_dialog = TrayIcon._show_dialog
    _show_update_dialog = TrayIcon._show_update_dialog
    _make_update_dialog = TrayIcon._make_update_dialog
    _make_restart_dialog = TrayIcon._make_restart_dialog
    _on_update_applied = TrayIcon._on_update_applied
    _on_update_check_done = TrayIcon._on_update_check_done
    _on_update_action = TrayIcon._on_update_action
    _reset_update_action = TrayIcon._reset_update_action
    _check_installed_version = TrayIcon._check_installed_version

    def __init__(self) -> None:
        self._dialogs = {}
        self._update_action = _Action()
        self._pending_release = None
        self._installed_version = None
        self._manual_update_check = False
        self.calls: list[tuple] = []
        self.messages: list[str] = []

    def _apply_update(self, release: dict) -> None:
        self.calls.append(("apply", release["version"]))

    def _open_release_page(self, url: str) -> None:
        self.calls.append(("open", url))

    def _restart(self) -> None:
        self.calls.append(("restart",))

    def _check_for_updates(self) -> None:
        self.calls.append(("check",))

    def showMessage(self, title: str, message: str, *args) -> None:
        self.messages.append(message)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(app):
    return _Tray()


def _click(dlg: QMessageBox, text: str) -> None:
    [btn] = [b for b in dlg.buttons() if b.text() == text]
    btn.click()
    QApplication.processEvents()


def test_second_request_raises_the_open_dialog(tray):
    tray._show_dialog("about", AboutDialog)
    first = tray._dialogs["about"]
    tray._show_dialog("about", AboutDialog)
    assert tray._dialogs["about"] is first
    assert first.isVisible()


def test_closed_dialog_leaves_the_registry(tray, app):
    tray._show_dialog("about", AboutDialog)
    tray._dialogs["about"].accept()
    app.processEvents()
    assert "about" not in tray._dialogs


def test_update_dialog_download_opens_release_page(tray):
    tray._show_update_dialog({"version": "9.0.0", "url": "https://example/rel"})
    _click(tray._dialogs["update"], "Download")
    assert tray.calls == [("open", "https://example/rel")]
    assert "update" not in tray._dialogs


def test_failed_then_successful_update_still_offers_restart(tray):
    tray._pending_release = {"version": "9.0.0", "url": ""}
    tray._on_update_applied("network down")
    assert "update-failed" in tray._dialogs
    assert tray._update_action.enabled

    tray._on_update_applied("")
    restart = tray._dialogs["update-restart"]
    assert "9.0.0" in restart.text()
    _click(restart, "&Yes")
    assert tray.calls == [("restart",)]


def test_declined_restart_keeps_a_usable_menu_entry(tray):
    tray._pending_release = {"version": "9.0.0", "url": ""}
    tray._on_update_applied("")
    _click(tray._dialogs["update-restart"], "&No")
    assert tray.calls == []
    assert tray._update_action.enabled
    assert tray._update_action.text == "Restart to use v9.0.0"

    tray._on_update_action()
    assert tray.calls == [("restart",)]


def test_manual_check_that_finds_a_release_reenables_the_entry(tray):
    tray._on_update_action()
    assert not tray._update_action.enabled
    tray._on_update_check_done({"version": "9.0.0", "url": ""})
    assert tray._update_action.enabled
    assert tray._update_action.text == "Update to v9.0.0"


def test_release_found_after_install_is_ignored(tray):
    tray._installed_version = "9.0.0"
    tray._on_update_check_done({"version": "9.1.0", "url": ""})
    assert tray._pending_release is None
    assert tray._update_action.text == "Check for Updates"


def test_package_upgraded_on_disk_offers_restart(tray, monkeypatch):
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: "9.0.0")
    tray._check_installed_version()
    assert tray._update_action.text == "Restart to use v9.0.0"
    assert tray.messages == ["v9.0.0 has been installed — click 'Restart to use v9.0.0' in the menu"]

    tray._on_update_action()
    assert tray.calls == [("restart",)]


def test_package_upgraded_on_disk_notifies_once(tray, monkeypatch):
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: "9.0.0")
    tray._check_installed_version()
    tray._check_installed_version()
    assert len(tray.messages) == 1


@pytest.mark.parametrize("on_disk", [None, __version__])
def test_unchanged_or_unreadable_package_keeps_the_entry(tray, monkeypatch, on_disk):
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: on_disk)
    tray._check_installed_version()
    assert tray._installed_version is None
    assert tray._update_action.text == "Check for Updates"
    assert tray.messages == []


def test_manual_check_settling_after_disk_upgrade_keeps_the_restart_entry(tray, monkeypatch):
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: "9.0.0")
    tray._on_update_action()
    tray._check_installed_version()
    tray._on_update_check_done(None)
    tray._reset_update_action()
    assert tray._update_action.text == "Restart to use v9.0.0"


def test_package_reverted_on_disk_withdraws_the_restart_entry(tray, monkeypatch):
    on_disk = {"version": "9.0.0"}
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: on_disk["version"])
    tray._check_installed_version()
    on_disk["version"] = __version__
    tray._check_installed_version()
    assert tray._installed_version is None
    assert tray._update_action.text == "Check for Updates"

    tray._on_update_check_done({"version": "9.1.0", "url": ""})
    assert tray._update_action.text == "Update to v9.1.0"


def test_release_found_after_disk_upgrade_is_ignored(tray, monkeypatch):
    monkeypatch.setattr("ctfl.tray.installed_version", lambda: "9.0.0")
    tray._check_installed_version()
    tray._on_update_check_done({"version": "9.1.0", "url": ""})
    assert tray._update_action.text == "Restart to use v9.0.0"
