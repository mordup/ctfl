#!/usr/bin/env python3
"""Claude Tracker For Linux"""

import sys

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtWidgets import QApplication

from .autostart import Autostart
from .config import Config
from .credentials import Credentials
from .providers.api import ApiProvider
from .providers.local import LocalProvider
from .providers.oauth import OAuthUsageProvider
from .tray import TrayIcon


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ctfl")
    app.setQuitOnLastWindowClosed(False)

    # Singleton guard
    shared = QSharedMemory("ctfl-singleton")
    if not shared.create(1):
        print("Claude Tracker For Linux is already running.", file=sys.stderr)
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
