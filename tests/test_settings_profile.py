"""The profile can change under an open Settings dialog (tray menu), so OK
must only write the combo back when the user actually moved it."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from ctfl.config import Config
from ctfl.providers.instance import Instance
from ctfl.settings_dialog import SettingsDialog

_app = None
_INSTANCES = [
    Instance("personal", Path("/inst/personal")),
    Instance("work", Path("/inst/work")),
]


class _Credentials:
    def get_api_key(self):
        return None

    def get_session_key(self):
        return None

    def get_cf_clearance(self):
        return None

    def delete_api_key(self):
        pass

    def delete_session_key(self):
        pass

    def delete_cf_clearance(self):
        pass


class _Autostart:
    def is_enabled(self):
        return False

    def disable(self):
        pass


@pytest.fixture
def dialog(monkeypatch):
    global _app
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "ctfl.providers.instance.discover_instances", lambda: _INSTANCES
    )
    config = Config()
    config.profile = "/inst/personal"
    return config, SettingsDialog(config, _Credentials(), _Autostart())


def test_ok_keeps_a_profile_switched_from_the_tray(dialog):
    config, dlg = dialog
    config.profile = "/inst/work"
    dlg._apply()
    assert config.profile == "/inst/work"


def test_ok_writes_a_profile_chosen_in_the_combo(dialog):
    config, dlg = dialog
    dlg._profile_combo.setCurrentIndex(dlg._profile_combo.findData("/inst/work"))
    dlg._apply()
    assert config.profile == "/inst/work"
