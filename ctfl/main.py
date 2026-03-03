#!/usr/bin/env python3
"""Claude Tracker For Linux"""

import fcntl
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .autostart import Autostart
from .config import Config
from .constants import APP_DISPLAY_NAME, APP_NAME
from .credentials import Credentials
from .providers.api import ApiProvider
from .providers.local import LocalProvider
from .providers.oauth import OAuthUsageProvider
from .tray import TrayIcon


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Singleton guard — auto-released on crash/SIGKILL
    lock_path = Path(
        os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    ) / f"{APP_NAME}.lock"
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"{APP_DISPLAY_NAME} is already running.", file=sys.stderr)
        return 1

    config = Config()
    credentials = Credentials()
    autostart = Autostart()
    local_provider = LocalProvider()
    api_provider = ApiProvider(credentials.get_api_key)
    oauth_provider = OAuthUsageProvider()

    tray = TrayIcon(config, credentials, autostart, local_provider, api_provider, oauth_provider)
    tray.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
