# CTFL — Claude Tracker For Linux

## Quick Reference

```bash
# Run the working tree as the live app (stops the running instance first)
bash scripts/dev-run.sh          # `installed` to switch back, `stop` to stop

# Run tests
python -m pytest tests/ -q

# Lint
ruff check ctfl/ tests/

# Auto-fix lint issues
ruff check --fix ctfl/ tests/
```

## Code Conventions

- **Python 3.11+** — use modern syntax (`X | Y` unions, `removeprefix`, etc.)
- **No type stub files** — use inline type hints
- **Imports**: stdlib → third-party → local, separated by blank lines. Use `from __future__ import annotations` in modules with forward references.
- **Private helpers**: prefix with `_` if module-internal
- **Qt signals/slots**: connect in `_build_ui()`, not in constructors

## Commit Messages

- Use [conventional commits](https://www.conventionalcommits.org/): `type: description`
- Types: `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `chore`
- Keep the subject line under 72 characters
- No `Co-Authored-By` lines
- Examples:
  - `feat: add weekly model breakdown to tooltip`
  - `fix: handle missing reset timestamp in rate limits`
  - `refactor: shorten format_reset output`

## Architecture

- `ctfl/tray.py` — system tray icon, tooltip, menu
- `ctfl/popup.py` — main popup window with charts
- `ctfl/providers/` — data fetching (local JSONL, OAuth API)
- `ctfl/providers/prediction.py` — burn rate / exhaustion prediction
- `ctfl/config.py` — QSettings wrapper
- `ctfl/updater.py` — GitHub release update checker
- `tests/` — pytest suite, no mocking of DB/filesystem unless necessary

Non-obvious rules the code relies on:
- Network and JSONL parsing run in QThread workers; results cross to the UI thread only through Qt signals. Never touch a widget from a worker.
- The OAuth API reports utilization as a percentage (6.0 means 6%), not a 0–1 ratio.
- The app must keep working offline from its cache; features that need connectivity degrade, they don't fail.
- The app is single-instance (fcntl lock); `scripts/dev-run.sh` stops the running copy before launching another.

## Tests

- One file per module under `tests/`, named `test_<module>.py`; plain functions named `test_<what>_<scenario>`, no unittest classes
- Mock network, keyring and the filesystem only when the real thing is unavailable; never mock internal logic
- Use `pytest.mark.parametrize` for the same behaviour across inputs; no sleep-based timing, no real network
- Qt tests run offscreen and with an isolated config; `tests/conftest.py` sets both, so no per-test setup

## Security

- Never store secrets in code — credentials go through `keyring`
- OAuth tokens are cached in `~/.cache/ctfl/`, not in the repo
- Validate all external API responses before use
