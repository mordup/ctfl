import shutil
import sys
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "ctfl.desktop"

DESKTOP_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=Claude Tracker For Linux
Comment=Claude usage tracker for Linux
Exec={exec_path}
Icon=ctfl
Terminal=false
X-KDE-autostart-after=panel
"""


class Autostart:
    def is_enabled(self) -> bool:
        return DESKTOP_FILE.exists()

    def enable(self, exec_path: str | None = None) -> None:
        if exec_path is None:
            installed = shutil.which("ctfl")
            if installed:
                exec_path = installed
            else:
                exec_path = f"{sys.executable} -m ctfl"
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(DESKTOP_TEMPLATE.format(exec_path=exec_path))

    def disable(self) -> None:
        try:
            DESKTOP_FILE.unlink()
        except FileNotFoundError:
            pass
