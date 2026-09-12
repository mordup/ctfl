Release workflow for the ctfl project. It has exactly two stops: one
checkpoint after the audit (step 4) and the GUI look at the built package
(step 8). Everything else runs without asking.

## 1. Commit and scope

If `git status` shows uncommitted changes, run `/commit` first; the release
covers everything committed, so pending work has to land before the range
is measured.

Scope is the change since the last tag, never the whole package:
```bash
git diff --stat $(git describe --tags --abbrev=0)..HEAD
git log --oneline $(git describe --tags --abbrev=0)..HEAD
```

If the log is empty, say there is nothing to release and stop.

## 2. Audit the diff

In parallel:
- Run the `docs-freshness` skill only when the range has a `feat:` commit or
  touches `ctfl/popup.py`, `tray.py`, `settings_dialog.py` or
  `about_dialog.py`. Bugfix-only releases skip it; the report just lists
  `.claude/docs-deferred.md`.
- Launch the code-auditor and quality-analyst agents only when the range
  touches a file under `ctfl/` beyond table or string edits (pricing rows,
  changelog entries, labels). Give each the commit range and the touched
  files plus their direct callers, and ask for exactly that scope: security,
  resource leaks, correctness; UX consistency, edge cases; dead code.
  Findings outside the scope go in the release report, not into fixes.
  When the agents are skipped, say so in the release report.

An agent that returns without an explicit findings section was cut off, not
clean. Resume it (`SendMessage` to its id) and get its results. A clean result
says so explicitly, e.g. "no findings at CONFIRMED or HIGH".

Reproduce a CONFIRMED finding yourself before acting on it. Fix only
CONFIRMED or HIGH; a defect you demonstrated directly counts as CONFIRMED
whatever the agent said. Lower tiers go in the report.

Commit fixes with `/commit`, with one adjustment to its one-commit-per-unit
rule: a fix that changes what the user sees (a figure, a label, a window, a
setting's effect) gets its own commit; every other audit fix (hardening,
wording, dead code, comments) goes into a single
`fix: address release audit findings` commit with one bullet per item.

## 3. Prepare the release content

Do all of this before saying anything to the user.

- Propose the version from the commit types since the last tag: any `feat:`
  means a minor bump, otherwise patch. The user may have named one already.
- Draft the in-app changelog, `__changelog__` in `ctfl/__init__.py`: a tuple
  of strings, one per user-facing change, rendered as bullets in the About
  dialog. Each entry is a short phrase, under about eight words, stating what
  changed: no justification, no "it used to", no internal field names.
  User-facing means features, UX changes, bugs the user would notice,
  security fixes. Skip dependency bumps, refactors, tests, tooling, agent or
  skill changes.
- Draft the GitHub release notes covering everything since the last tag,
  grouped under "### Features", "### Fixes", "### Security", "### Internal".
  One line per item, stating what changed and, where not obvious, why it was
  wrong. Detail belongs in the commit messages. Never restate one change in
  two sections.
- When docs-freshness ran, read `.claude/docs-deferred.md`, merge its entries
  with the punch list, and choose a default per item: "defer" unless the docs
  state something now false, in which case "fix now".

## 4. Checkpoint

Present in one message: the proposed version, the changelog entries, the
release notes, and, when docs-freshness ran, the docs list with a default
decision per item. Ask for a single go. Apply whatever the user changes, then run every following step
without further questions until step 8.

When docs decisions were taken, update `.claude/docs-deferred.md`: add newly
deferred items with the release they were deferred at, remove fixed or
dropped ones. Docs fixes marked "fix now" are made in the ctfl-docs repo
before continuing.

## 5. Bump version

Update `__version__` and `__changelog__` in `ctfl/__init__.py`, `pkgver` in
`PKGBUILD` and in `aur/PKGBUILD` (its sha256sums come in step 11). Then check
they agree, because `release.sh` reads only `ctfl/__init__.py` and nothing
downstream would notice a drift:

```bash
VERSION=$(python3 -c "from ctfl import __version__; print(__version__)")
grep -q "pkgver=${VERSION}" PKGBUILD \
  && grep -q "pkgver=${VERSION}" aur/PKGBUILD \
  && echo "versions agree on ${VERSION}" \
  || { echo "VERSION DRIFT — fix before continuing"; exit 1; }
```

`appimage/requirements.txt` is not on the list: `release.sh` overwrites it.

Commit the three files as `release: X.Y.Z`.

## 6. Build

```bash
export PATH="$HOME/.local/share/gem/ruby/3.4.0/bin:$PATH"
bash scripts/release.sh
```

Confirm `dist/` contains the wheel, the .deb, the .rpm, the .pkg.tar.zst,
`CTFL-x86_64.AppImage`, and `SHA256SUMS` listing the wheel and AppImage by
their exact names. The in-app updater refuses a release without SHA256SUMS.

## 7. Headless smoke test

```bash
bash scripts/smoke.sh dist/ctfl-X.Y.Z-py3-none-any.whl
```

It installs the wheel into a throwaway venv, imports it from outside the
repo, checks the version, runs one real fetch with the user's config and
prints the tooltip. Any FAIL line is a release blocker: nothing is tagged
yet, so fix, re-commit, and restart from step 5. The suite does not catch
what only appears at runtime; this step is the one that exercises the
artifact.

## 8. GUI look

Start the built wheel with the display and let the user look:

```bash
tmp=$(mktemp -d)
python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install --quiet dist/ctfl-X.Y.Z-py3-none-any.whl
bash scripts/dev-run.sh stop
(cd "$tmp" && nohup "$tmp/venv/bin/python" -m ctfl >"$tmp/log" 2>&1 &)
```

Ask the user to open the popup, switch through the tabs, and hover the tray
icon. This is the second and last stop. Afterwards run
`bash scripts/dev-run.sh installed` to put the packaged build back and
remove `$tmp`.

## 9. Tag and push

Build first, tag second: a tag pushed before a successful build has to be
deleted from the remote if the build fails.

```bash
git tag vX.Y.Z
git push && git push --tags
```

## 10. GitHub release

Use the release notes, not the in-app changelog, as the body:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "RELEASE_NOTES" \
  dist/ctfl-X.Y.Z-py3-none-any.whl \
  dist/ctfl_X.Y.Z_amd64.deb \
  dist/ctfl-X.Y.Z-1.x86_64.rpm \
  dist/ctfl-X.Y.Z-1-any.pkg.tar.zst \
  dist/CTFL-x86_64.AppImage \
  dist/SHA256SUMS
```

## 11. AUR package

1. Download the tarball to a file and hash it. Never pipe `curl | sha256sum`;
   shell hooks can corrupt piped output.
   ```bash
   curl -sL https://github.com/mordup/ctfl/archive/refs/tags/vX.Y.Z.tar.gz -o /tmp/ctfl-vX.Y.Z.tar.gz
   sha256sum /tmp/ctfl-vX.Y.Z.tar.gz
   rm /tmp/ctfl-vX.Y.Z.tar.gz
   ```
2. Put the hash in `sha256sums` in `aur/PKGBUILD`.
3. `cd aur && makepkg --printsrcinfo > .SRCINFO && cd ..`
4. Commit `chore: update AUR package to X.Y.Z` and `git push`.
5. Push to AUR:
   ```bash
   tmp=$(mktemp -d)
   git clone ssh://aur@aur.archlinux.org/ctfl.git "$tmp/ctfl-aur"
   cp aur/PKGBUILD aur/.SRCINFO "$tmp/ctfl-aur/"
   cd "$tmp/ctfl-aur"
   git add PKGBUILD .SRCINFO
   git commit -m "Update to X.Y.Z"
   git push
   cd -
   rm -rf "$tmp"
   ```

## 12. Report

Run `gh release view vX.Y.Z` to confirm every asset is up. Report the release
URL, whether the agents ran, any out-of-scope findings, and the docs items
still deferred.
