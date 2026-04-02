Release workflow for the ctfl project. Follow these steps exactly:

## 1. Check for uncommitted changes

Run `git status`. If there are uncommitted changes, run `/commit` first to commit them before proceeding.

## 2. Determine version and changelogs

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

## 3. Bump version

Update the version string in ALL of these files (they must match):
- `ctfl/__init__.py` — update `__version__` and `__changelog__`
- `PKGBUILD` — update `pkgver`
- `appimage/requirements.txt` — update the version in the ctfl requirement line

## 4. Commit the version bump

Stage the three version files and commit: `release: X.Y.Z`

## 5. Tag

- Create a git tag: `git tag vX.Y.Z`

## 6. Push

- Push the commit and tag: `git push && git push --tags`

## 7. Build artifacts

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

## 8. Create GitHub release

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

## 9. Verify and remind

- Run `gh release view vX.Y.Z` to confirm all assets are uploaded
- Report the release URL to the user
- Check if any user-facing features/settings/installation changed since the last docs update. If so, remind the user to update the ctfl-docs site (separate repo). Don't nag on internal-only releases.
