#!/usr/bin/env bash
# Build all release artifacts for CTFL
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(python3 -c "from ctfl import __version__; print(__version__)")
echo "Building CTFL v${VERSION} release artifacts..."
echo

# PyPI wheel + sdist
echo "=== PyPI (wheel + sdist) ==="
python3 -m build
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
    python-appimage build app -p 3.11 appimage/
    echo
else
    echo "--- Skipping AppImage (python-appimage not installed) ---"
    echo
fi

echo "=== Release artifacts ==="
ls -lh dist/*.whl dist/*.tar.gz 2>/dev/null || true
ls -lh *.pkg.tar.zst 2>/dev/null || true
ls -lh *.deb 2>/dev/null || true
ls -lh *.rpm 2>/dev/null || true
ls -lh *.AppImage 2>/dev/null || true
