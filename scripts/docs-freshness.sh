#!/usr/bin/env bash
# Print evidence of drift between the CTFL app and the ctfl-docs site.
# Consumed by the docs-freshness skill, which interprets the output.

set -euo pipefail

CTFL_REPO="$(git rev-parse --show-toplevel)"
DOCS_REPO="${DOCS_REPO:-$CTFL_REPO/../ctfl-docs}"

if [ ! -d "$DOCS_REPO/docs" ]; then
  echo "docs repo not found at $DOCS_REPO (set DOCS_REPO to override)" >&2
  exit 1
fi

last_docs="$(git -C "$DOCS_REPO" log -1 --format=%ci 2>/dev/null || true)"
echo "Last docs commit: ${last_docs:-never}"
echo

echo "== UI source files changed since last docs commit =="
changed="$(git -C "$CTFL_REPO" log --since="$last_docs" --name-only --pretty=format: -- \
  ctfl/popup.py ctfl/tray.py ctfl/settings_dialog.py ctfl/about_dialog.py \
  2>/dev/null | sort -u | sed '/^$/d')"
if [ -z "$changed" ]; then
  echo "  (none)"
else
  printf '%s\n' "$changed" | sed 's/^/  /'
fi
echo

echo "== app commits since last docs commit =="
git -C "$CTFL_REPO" log --since="$last_docs" --oneline || echo "  (none)"
echo

echo "== screenshots: source newer than docs copy =="
any=0
for shot in "$CTFL_REPO"/screenshots/*.png; do
  [ -f "$shot" ] || continue
  name="$(basename "$shot")"
  doc_copy="$DOCS_REPO/docs/assets/images/$name"
  if [ ! -f "$doc_copy" ]; then
    echo "  $name  (missing in docs)"
    any=1
  elif [ "$(stat -c %Y "$shot")" -gt "$(stat -c %Y "$doc_copy")" ]; then
    echo "  $name  (source newer)"
    any=1
  fi
done
[ "$any" -eq 0 ] && echo "  (none)"
