#!/usr/bin/env bash
# Build an .rpm package for CTFL using fpm
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

echo "==> Building .rpm with fpm..."
fpm \
    -s dir \
    -t rpm \
    -n ctfl \
    -v "$VERSION" \
    --description "Claude Tracker For Linux — system tray monitor for Claude usage" \
    --url "https://github.com/mordup/ctfl" \
    --license MIT \
    --maintainer "Morgan <morgan@mordup.com>" \
    --depends python3-qt6 \
    --depends python3-keyring \
    --category Utilities \
    -C "$DESTDIR" \
    .

echo "==> Done: ctfl-${VERSION}.noarch.rpm"
