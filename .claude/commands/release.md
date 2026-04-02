Release workflow for the ctfl project. Follow these steps exactly:

## 1. Check for uncommitted changes

Run `git status`. If there are uncommitted changes, run `/commit` first to commit them before proceeding.

## 2. Determine version

- Read `ctfl/__init__.py` to get the current `__version__` and `__changelog__`
- Ask the user what the new version should be (patch/minor/major bump) unless they already specified it
- Ask the user for a changelog summary unless `__changelog__` already has the right content

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

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "CHANGELOG_SUMMARY" \
  dist/ctfl-X.Y.Z-py3-none-any.whl \
  dist/ctfl_X.Y.Z_amd64.deb \
  dist/ctfl-X.Y.Z-1.x86_64.rpm \
  dist/ctfl-X.Y.Z-1-any.pkg.tar.zst \
  dist/CTFL-x86_64.AppImage
```

## 9. Verify

- Run `gh release view vX.Y.Z` to confirm all assets are uploaded
- Report the release URL to the user
