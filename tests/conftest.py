"""Test-wide isolation for the Qt-backed tests.

Both settings here must be applied before PyQt is imported by any test
module, which is why they live in conftest rather than in the test files.
"""

from __future__ import annotations

import os
import tempfile

# Headless: no display is available in CI, and the GUI tests only need
# geometry, not pixels.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Redirect QSettings away from the developer's real ~/.config/ctfl. Note that
# QSettings.setPath() is NOT enough on Linux: Qt resolves UserScope through
# XDG_CONFIG_HOME first, so a setPath() redirect is silently ignored and the
# tests write to (and read geometry from) the live config.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="ctfl-test-config-")
