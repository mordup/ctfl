import shutil
import sys
from pathlib import Path

from .constants import APP_DISPLAY_NAME, APP_NAME, ICON_THEME_NAME

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / f"{APP_NAME}.desktop"

DESKTOP_TEMPLATE = f"""\
[Desktop Entry]
Type=Application
Name={APP_DISPLAY_NAME}
Comment=Claude usage tracker for Linux
Exec={{exec_path}}
Icon={ICON_THEME_NAME}
Terminal=false
X-KDE-autostart-after=panel
"""


class Autostart:
    def is_enabled(self) -> bool:
        return DESKTOP_FILE.exists()

    def enable(self, exec_path: str | None = None) -> None:
        if exec_path is None:
            installed = shutil.which(APP_NAME)
            if installed:
                exec_path = installed
            else:
                exec_path = f"{sys.executable} -m {APP_NAME}"
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(DESKTOP_TEMPLATE.format(exec_path=exec_path))

    def disable(self) -> None:
        try:
            DESKTOP_FILE.unlink()
        except FileNotFoundError:
            pass
