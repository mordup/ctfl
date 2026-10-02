"""Test-wide isolation for the Qt-backed tests.

The two environment settings must be applied before PyQt is imported by any
test module, which is why they live in conftest rather than in the test files.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Headless: no display is available in CI, and the GUI tests only need
# geometry, not pixels.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Redirect QSettings away from the developer's real ~/.config/ctfl. Note that
# QSettings.setPath() is NOT enough on Linux: Qt resolves UserScope through
# XDG_CONFIG_HOME first, so a setPath() redirect is silently ignored and the
# tests write to (and read geometry from) the live config.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="ctfl-test-config-")


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path_factory, monkeypatch):
    # The local provider writes CTFL's history and scans every discovered
    # instance; keep both off the developer's real ~/.cache and ~/.claude.
    monkeypatch.setattr("ctfl.providers.history._DIR", tmp_path_factory.mktemp("history"))
    monkeypatch.setattr("ctfl.providers.local.discover_instances", lambda: [])
