#!/usr/bin/env bash
# Build a .deb package for CTFL using fpm
# Requires: fpm, python3, python3-pip
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(python3 -c "from ctfl import __version__; print(__version__)")
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

echo "==> Building wheel..."
python3 -m build --wheel --outdir "$STAGING/wheel"

echo "==> Installing into staging directory..."
DESTDIR="$STAGING/install"
python3 -m installer --destdir="$DESTDIR" "$STAGING"/wheel/*.whl

# Copy icon
install -Dm644 icons/ctfl.svg \
    "$DESTDIR/usr/share/icons/hicolor/scalable/apps/ctfl.svg"

# Copy desktop file
install -Dm644 ctfl.desktop \
    "$DESTDIR/usr/share/applications/ctfl.desktop"

# Copy license
install -Dm644 LICENSE \
    "$DESTDIR/usr/share/licenses/ctfl/LICENSE"

mkdir -p dist

echo "==> Building .deb with fpm..."
${FPM:-fpm} \
    -s dir \
    -t deb \
    -n ctfl \
    -v "$VERSION" \
    -p dist/ \
    --description "Claude Tracker For Linux — system tray monitor for Claude usage" \
    --url "https://github.com/mordup/ctfl" \
    --license MIT \
    --maintainer "Morgan <morgan@mordup.com>" \
    --depends python3-pyqt6 \
    --depends python3-keyring \
    --category utils \
    -C "$DESTDIR" \
    .

echo "==> Done: dist/ctfl_${VERSION}_amd64.deb"
