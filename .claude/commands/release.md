Release workflow for the ctfl project. Follow these steps exactly:

## 1. Audit the codebase

Run a full audit before releasing. Launch the code-auditor agent, the quality-analyst agent, and the `docs-freshness` skill in parallel to check for:
- Security vulnerabilities, resource leaks, correctness bugs
- UX consistency, edge cases, behavioral issues
- Unused imports, dead code
- Drift between the app and the ctfl-docs site (copy + screenshots)

**Only fix findings with confidence CONFIRMED or HIGH.** Skip PROBABLE/POSSIBLE/SPECULATIVE — those need investigation, not a rushed fix before release.

If code fixes are needed, apply them and commit using `/commit` before proceeding.

For each item in the docs-freshness punch list, ask the user whether to update docs now (blocks the release), defer with an explicit ticket, or ship as-is. Don't silently skip.

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

Generate full release notes from commits since last tag. Include everything:
- User-facing changes (same as in-app)
- Security hardening details
- Developer-facing changes (linting, agents, hooks, CI)
- Test coverage improvements

Format as markdown with sections (e.g., "### Features", "### Fixes", "### Internal").

## 4. Bump version

Update the version string in ALL of these files (they must match):
- `ctfl/__init__.py` — update `__version__` and `__changelog__`
- `PKGBUILD` — update `pkgver`
- `appimage/requirements.txt` — update the version in the ctfl requirement line
- `aur/PKGBUILD` — update `pkgver` (sha256sums updated later in step 10)

## 5. Commit the version bump

Stage the four version files and commit: `release: X.Y.Z`

## 6. Tag

- Create a git tag: `git tag vX.Y.Z`

## 7. Push

- Push the commit and tag: `git push && git push --tags`

## 8. Build artifacts

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

## 9. Create GitHub release

Use the full release notes (not the in-app changelog) as the body:

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "FULL_RELEASE_NOTES" \
  dist/ctfl-X.Y.Z-py3-none-any.whl \
  dist/ctfl_X.Y.Z_amd64.deb \
  dist/ctfl-X.Y.Z-1.x86_64.rpm \
  dist/ctfl-X.Y.Z-1-any.pkg.tar.zst \
  dist/CTFL-x86_64.AppImage
```

## 10. Update AUR package

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

## 11. Verify and remind

- Run `gh release view vX.Y.Z` to confirm all assets are uploaded
- Report the release URL to the user
- Check if any user-facing features/settings/installation changed since the last docs update. If so, remind the user to update the ctfl-docs site (separate repo). Don't nag on internal-only releases.
