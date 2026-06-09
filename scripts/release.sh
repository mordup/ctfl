#!/usr/bin/env bash
# Build all release artifacts for CTFL
# All outputs go into dist/
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(python3 -c "from ctfl import __version__; print(__version__)")
echo "Building CTFL v${VERSION} release artifacts..."
echo

mkdir -p dist

# Wheel
echo "=== Wheel ==="
python3 -m build --wheel
echo

# Arch Linux
if command -v makepkg &>/dev/null; then
    echo "=== Arch Linux (.pkg.tar.zst) ==="
    makepkg -f
    echo
fi

# .deb
if command -v fpm &>/dev/null; then
    echo "=== Debian (.deb) ==="
    bash scripts/build-deb.sh
    echo

    echo "=== RPM (.rpm) ==="
    bash scripts/build-rpm.sh
    echo
else
    echo "--- Skipping .deb/.rpm (fpm not installed) ---"
    echo
fi

# AppImage
if command -v python-appimage &>/dev/null; then
    echo "=== AppImage ==="
    # Point requirements.txt at the local wheel (absolute path for python-appimage)
    WHEEL_PATH="$(pwd)/dist/ctfl-${VERSION}-py3-none-any.whl"
    echo "$WHEEL_PATH" > appimage/requirements.txt
    python-appimage build app -p 3.11 appimage/
    # Move AppImage artifacts into dist/
    mv -f ./*.AppImage dist/ 2>/dev/null || true
    echo
else
    echo "--- Skipping AppImage (python-appimage not installed) ---"
    echo
fi

# Checksums — the in-app updater verifies downloads against this file,
# so it must be uploaded as a release asset alongside the artifacts.
echo "=== SHA256SUMS ==="
(cd dist && rm -f SHA256SUMS && sha256sum -- * > SHA256SUMS)
cat dist/SHA256SUMS
echo

echo "=== Release artifacts ==="
ls -lh dist/ 2>/dev/null || true
