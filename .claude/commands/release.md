Release workflow for the ctfl project. Follow these steps exactly:

## 1. Audit the codebase

Run a full audit before releasing. Launch the code-auditor agent, the quality-analyst agent, and the `docs-freshness` skill in parallel to check for:
- Security vulnerabilities, resource leaks, correctness bugs
- UX consistency, edge cases, behavioral issues
- Unused imports, dead code
- Drift between the app and the ctfl-docs site (copy + screenshots)

**An agent that returns without an explicit findings section has not finished — it was cut off.** Silence is not a clean audit. Resume it (`SendMessage` to its id) and ask for its results before believing them. During the 2.8.0 release the code-auditor came back with only its opening sentence; resuming it surfaced a bug that had been inflating every token and cost figure by 2.2x. A genuinely clean result says so explicitly, e.g. "no findings at CONFIRMED or HIGH".

**Verify a CONFIRMED finding yourself before acting on it.** Agents are sometimes wrong, and the fix is often invasive. Reproduce it against real data first.

**Only fix findings with confidence CONFIRMED or HIGH.** Skip PROBABLE/POSSIBLE/SPECULATIVE — those need investigation, not a rushed fix before release. Exception: a defect you have demonstrated directly is CONFIRMED regardless of how the agent rated it.

If code fixes are needed, apply them and commit using `/commit` before proceeding.

For each item in the docs-freshness punch list, ask the user whether to update docs now (blocks the release), defer with an explicit ticket, or ship as-is. Don't silently skip.

**Also re-check what was deferred last release.** The punch list is generated from current state, so an item deferred with a ticket never reappears on its own — "defer" quietly becomes "drop". Read back the tickets raised at the previous release and ask about each again. As of 2.8.0 two are still open: the "verification failed" troubleshooting note in updating.md, and two passages stating monthly spend is Enterprise-only when it is not.

## 2. Check for uncommitted changes

Run `git status`. If there are uncommitted changes, run `/commit` first to commit them before proceeding.

## 3. Determine version and changelogs

- Read `ctfl/__init__.py` to get the current `__version__` and `__changelog__`
- Ask the user what the new version should be (patch/minor/major bump) unless they already specified it
- Run `git log --oneline $(git describe --tags --abbrev=0)..HEAD` to see all commits since last release

### In-app changelog (`__changelog__`)

This is shown in the app's About/Update dialog. **User-facing changes only:**
- New features
- UX changes (layout, formatting, wording)
- Bug fixes the user would notice
- Security fixes

**Skip:** dependency bumps, refactors, test additions, tooling, internal renames, agent/skill changes.

Ask the user to confirm the in-app changelog text.

### GitHub release notes

Cover everything from the commits since the last tag — user-facing changes,
security hardening, developer-facing work, test coverage — grouped under
"### Features", "### Fixes", "### Security", "### Internal".

**One line per item.** State what changed and, where it is not obvious, why it
was wrong — in a sentence, not a paragraph. The 2.8.0 notes ran to dense
multi-sentence bullets with measured ratios and internal field names; nobody
reads that on a release page, and the detail belongs in the commit messages
where it already is. If a bullet needs more than about two lines, it is
carrying explanation that should stay in the commit.

Do not restate the same change in more than one section.

## 4. Bump version

Update the version string in ALL of these files (they must match):
- `ctfl/__init__.py` — update `__version__` and `__changelog__`
- `PKGBUILD` — update `pkgver`
- `aur/PKGBUILD` — update `pkgver` (sha256sums updated later in step 11)

`appimage/requirements.txt` is deliberately not in this list: `release.sh`
overwrites it with an absolute path to the freshly-built wheel before invoking
python-appimage, so editing it by hand achieves nothing. It is gitignored.

Then verify they actually match, rather than trusting the edits. `release.sh`
reads the version from `ctfl/__init__.py` alone, so a missed bump elsewhere
produces mismatched artifacts silently — no step downstream would catch it:

```bash
VERSION=$(python3 -c "from ctfl import __version__; print(__version__)")
grep -q "pkgver=${VERSION}" PKGBUILD \
  && grep -q "pkgver=${VERSION}" aur/PKGBUILD \
  && echo "versions agree on ${VERSION}" \
  || { echo "VERSION DRIFT — fix before continuing"; exit 1; }
```

## 5. Commit the version bump

Stage the three version files and commit: `release: X.Y.Z`

## 6. Build artifacts

Run the release build script. fpm needs a PATH export:
```bash
export PATH="$HOME/.local/share/gem/ruby/3.4.0/bin:$PATH"
bash scripts/release.sh
```

Verify that all expected artifacts exist in `dist/`:
- `ctfl-X.Y.Z-py3-none-any.whl`
- `ctfl_X.Y.Z_amd64.deb`
- `ctfl-X.Y.Z-1.x86_64.rpm`
- `ctfl-X.Y.Z-1-any.pkg.tar.zst`
- `CTFL-x86_64.AppImage`
- `SHA256SUMS` — **required**: the in-app updater (≥2.7.3) refuses to install
  releases without it. Verify it lists the wheel and AppImage names exactly.

## 7. Smoke-test the built package

Install the built wheel into a throwaway venv and actually run it. Every step
so far has checked that files exist, not that the program works — and the test
suite does not catch what only appears at runtime. Both bugs fixed after 2.8.0 — the dropped per-model weekly bucket, and the
popup collapsing on refresh — passed a green suite and were visible only once
the app was actually driven.

```bash
tmp=$(mktemp -d)
python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install --quiet dist/ctfl-X.Y.Z-py3-none-any.whl
"$tmp/venv/bin/python" -m ctfl &
smoke_pid=$!
```

Then, in the running app:

- Open the popup from the tray icon and confirm the limit bars render with
  real numbers — not "Loading...", not an error row.
- Switch through all three tabs; confirm the window does not collapse or
  jump.
- Hover the tray icon and confirm the tooltip shows the same figures.

Kill it when done (`kill $smoke_pid; rm -rf "$tmp"`). A failure here is a
release blocker: nothing is tagged or pushed yet, so fix, re-commit, and
restart from step 4.

## 8. Tag

Build first, tag second. A tag pushed before a successful build has to be
deleted from the remote if `release.sh` fails, and anything that already
fetched it sees a version that was never released.

- Create a git tag: `git tag vX.Y.Z`

## 9. Push

- Push the commit and tag: `git push && git push --tags`

## 10. Create GitHub release

Use the full release notes (not the in-app changelog) as the body:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "FULL_RELEASE_NOTES" \
  dist/ctfl-X.Y.Z-py3-none-any.whl \
  dist/ctfl_X.Y.Z_amd64.deb \
  dist/ctfl-X.Y.Z-1.x86_64.rpm \
  dist/ctfl-X.Y.Z-1-any.pkg.tar.zst \
  dist/CTFL-x86_64.AppImage \
  dist/SHA256SUMS
```

## 11. Update AUR package

Now that the tag is on GitHub, update the AUR package:

1. Download the source tarball to a file and compute the sha256sum. Always download to a file — do NOT pipe `curl | sha256sum` as shell hooks can corrupt piped output:
   ```bash
   curl -sL https://github.com/mordup/ctfl/archive/refs/tags/vX.Y.Z.tar.gz -o /tmp/ctfl-vX.Y.Z.tar.gz
   sha256sum /tmp/ctfl-vX.Y.Z.tar.gz
   rm /tmp/ctfl-vX.Y.Z.tar.gz
   ```
2. Update `sha256sums` in `aur/PKGBUILD` with the verified hash
3. Regenerate `.SRCINFO`:
   ```bash
   cd aur && makepkg --printsrcinfo > .SRCINFO && cd ..
   ```
4. Commit: `chore: update AUR package to X.Y.Z`
5. Push the commit: `git push`
6. Push to AUR — clone the AUR repo into a temp dir, copy files, and push:
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

## 12. Verify and remind

- Run `gh release view vX.Y.Z` to confirm all assets are uploaded
- Report the release URL to the user
- Check if any user-facing features/settings/installation changed since the last docs update. If so, remind the user to update the ctfl-docs site (separate repo). Don't nag on internal-only releases.
