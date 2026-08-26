"""Test-wide setup for the Qt-backed tests.

Applied before PyQt is imported by any test module, which is why it lives in
conftest rather than in the test files.
"""

from __future__ import annotations

import os

# Headless: no display is available in CI, and the GUI tests only need
# geometry, not pixels.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
