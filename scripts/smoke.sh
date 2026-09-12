#!/usr/bin/env bash
# Headless smoke test of a built wheel: install it into a throwaway venv, run
# it from outside the repo with the user's real config, wait for one fetch and
# print the tooltip. Fails on import-from-tree, version mismatch, fetch error
# or timeout. It cannot see the popup; the GUI check in the release workflow
# still covers rendering.
#
#   scripts/smoke.sh [dist/ctfl-X.Y.Z-py3-none-any.whl]
set -euo pipefail

cd "$(dirname "$0")/.."
WHEEL="${1:-$(ls -t dist/ctfl-*-py3-none-any.whl | head -n1)}"
WHEEL="$(realpath "$WHEEL")"
EXPECTED="$(python3 -c "from ctfl import __version__; print(__version__)")"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install --quiet "$WHEEL"

cd "$tmp"
QT_QPA_PLATFORM=offscreen "$tmp/venv/bin/python" - "$EXPECTED" "$tmp" <<'PY'
import sys
import time

expected, tmp = sys.argv[1], sys.argv[2]

import ctfl

if not ctfl.__file__.startswith(tmp):
    sys.exit(f"FAIL: imported {ctfl.__file__}, not the wheel")
if ctfl.__version__ != expected:
    sys.exit(f"FAIL: wheel is {ctfl.__version__}, tree is {expected}")

from PyQt6.QtWidgets import QApplication

from ctfl.autostart import Autostart
from ctfl.config import Config
from ctfl.credentials import Credentials
from ctfl.providers.api import ApiProvider
from ctfl.providers.local import LocalProvider
from ctfl.providers.oauth import OAuthUsageProvider
from ctfl.tray import TrayIcon

app = QApplication([])
config = Config()
credentials = Credentials()
tray = TrayIcon(
    config,
    credentials,
    Autostart(),
    LocalProvider(config),
    ApiProvider(credentials.get_api_key),
    OAuthUsageProvider(
        credentials.get_session_key, credentials.get_cf_clearance, config=config
    ),
)

# The constructor already started the first fetch; wait for it to land.
deadline = time.monotonic() + 60
while tray._latest_data is None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.05)

data = tray._latest_data
if data is None:
    sys.exit("FAIL: no data within 60s")
if data.error:
    sys.exit(f"FAIL: fetch error: {data.error}")
tray._popup.update_data(data)

print(f"OK: ctfl {ctfl.__version__} from {ctfl.__file__}")
print("--- tooltip ---")
print(tray.toolTip())
PY
