"""Auto-update support for CTFL.

Checks GitHub releases for newer versions and can self-update
for pip and AppImage installs. System package installs (deb/rpm/pacman)
only get a notification with a link.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
from enum import Enum, auto
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import __version__

_RELEASES_URL = "https://api.github.com/repos/mordup/ctfl/releases/latest"
_GITHUB_RELEASE_PAGE = "https://github.com/mordup/ctfl/releases/latest"

# Release assets must be served from GitHub over HTTPS. browser_download_url
# is always a github.com URL; the others cover GitHub's redirect targets.
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_CHECKSUMS_ASSET = "SHA256SUMS"
_MAX_ASSET_BYTES = 200 * 1024 * 1024  # largest artifact (AppImage) is ~100 MB
_MAX_CHECKSUMS_BYTES = 64 * 1024


class UpdateVerificationError(Exception):
    """Downloaded release asset failed integrity verification."""


class InstallMethod(Enum):
    APPIMAGE = auto()
    PIP = auto()
    SYSTEM = auto()
    UNKNOWN = auto()


def detect_install_method() -> InstallMethod:
    if os.environ.get("APPIMAGE"):
        return InstallMethod.APPIMAGE
    # pip install: the package lives in a site-packages directory
    pkg_dir = Path(__file__).resolve().parent
    if "site-packages" in pkg_dir.parts:
        return InstallMethod.PIP
    exe = shutil.which("ctfl")
    if exe:
        exe_path = Path(exe).resolve()
        if exe_path.is_relative_to(Path("/usr")):
            return InstallMethod.SYSTEM
    return InstallMethod.UNKNOWN


def check_for_update() -> dict | None:
    """Check GitHub for a newer release.

    Returns {"tag": "v2.3.0", "version": "2.3.0", "url": "...", "assets": [...]}
    or None if already up to date or on error.
    """
    try:
        req = Request(_RELEASES_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ctfl-updater",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return None

    tag = data.get("tag_name", "")
    remote_version = tag.lstrip("v")
    if not remote_version or not _is_newer(remote_version, __version__):
        return None

    assets = []
    for asset in data.get("assets", []):
        assets.append({
            "name": asset["name"],
            "url": asset["browser_download_url"],
            "size": asset.get("size", 0),
        })

    return {
        "tag": tag,
        "version": remote_version,
        "url": data.get("html_url", _GITHUB_RELEASE_PAGE),
        "assets": assets,
    }


def _is_newer(remote: str, local: str) -> bool:
    try:
        r = tuple(int(x) for x in remote.split("."))
        loc = tuple(int(x) for x in local.split("."))
        return r > loc
    except (ValueError, TypeError):
        return False


def _find_asset(assets: list[dict], suffix: str) -> dict | None:
    for a in assets:
        if a["name"].endswith(suffix):
            return a
    return None


def can_auto_update() -> bool:
    return detect_install_method() in (InstallMethod.PIP, InstallMethod.APPIMAGE)


def apply_update(release: dict) -> str | None:
    """Download and apply an update. Returns error string or None on success."""
    method = detect_install_method()
    if method == InstallMethod.PIP:
        return _update_pip(release)
    if method == InstallMethod.APPIMAGE:
        return _update_appimage(release)
    return "Auto-update not supported for this install method"


def _update_pip(release: dict) -> str | None:
    asset = _find_asset(release["assets"], ".whl")
    if not asset:
        return "No .whl file found in release"
    try:
        whl_data = _download_verified(asset, release["assets"])
    except UpdateVerificationError as e:
        return f"Update verification failed: {e}"
    except Exception as e:
        return f"Download failed: {e}"

    tmp_dir = tempfile.mkdtemp(prefix="ctfl-update-")
    whl_path = Path(tmp_dir) / asset["name"]
    whl_path.write_bytes(whl_data)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", str(whl_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return f"pip install failed: {result.stderr.strip()}"
    except Exception as e:
        return f"pip install failed: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def _update_appimage(release: dict) -> str | None:
    asset = _find_asset(release["assets"], ".AppImage")
    if not asset:
        return "No .AppImage file found in release"
    appimage_path = os.environ.get("APPIMAGE")
    if not appimage_path:
        return "APPIMAGE env var not set"
    try:
        new_data = _download_verified(asset, release["assets"])
    except UpdateVerificationError as e:
        return f"Update verification failed: {e}"
    except Exception as e:
        return f"Download failed: {e}"

    target = Path(appimage_path)
    tmp = target.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755)
    try:
        os.write(fd, new_data)
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.rename(target)
    return None


def _check_download_url(url: str) -> None:
    """Reject asset URLs that don't point at GitHub over HTTPS."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateVerificationError(f"insecure download URL (not https): {url}")
    if parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateVerificationError(f"untrusted download host: {parsed.hostname}")


def _download(url: str, max_bytes: int = _MAX_ASSET_BYTES) -> bytes:
    _check_download_url(url)
    req = Request(url, headers={"User-Agent": "ctfl-updater"})
    chunks: list[bytes] = []
    total = 0
    with urlopen(req, timeout=120) as resp:
        while chunk := resp.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise UpdateVerificationError(
                    f"download exceeds {max_bytes // (1024 * 1024)} MB limit"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _parse_checksums(text: str) -> dict[str, str]:
    """Parse sha256sum output lines ("<64-hex>  <filename>") into a mapping."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _download_verified(asset: dict, assets: list[dict]) -> bytes:
    """Download an asset and verify its SHA-256 against the release's
    SHA256SUMS asset. Raises UpdateVerificationError when verification
    cannot be performed or fails — updates fail closed.
    """
    sums_asset = next((a for a in assets if a["name"] == _CHECKSUMS_ASSET), None)
    if sums_asset is None:
        raise UpdateVerificationError(
            "release has no SHA256SUMS asset; refusing unverified install"
        )
    sums = _parse_checksums(
        _download(sums_asset["url"], max_bytes=_MAX_CHECKSUMS_BYTES).decode(
            "utf-8", "replace"
        )
    )
    expected = sums.get(asset["name"])
    if expected is None:
        raise UpdateVerificationError(f"no checksum listed for {asset['name']}")

    data = _download(asset["url"])
    digest = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise UpdateVerificationError(f"checksum mismatch for {asset['name']}")
    return data
