---
name: ctfl-architecture
description: "CTFL architecture reference -- module map, data flow, threading model, config system"
user-invocable: false
---

# CTFL Architecture Reference

## Overview

CTFL (Claude Tracker For Linux) is a PyQt6 system tray app that monitors Claude API token usage. Single-user, Linux-only, ~2k LOC. Distributed as pip wheel, deb, rpm, AppImage, and Arch pkg.

## Module Map

```
ctfl/
├── __init__.py          # __version__, __changelog__
├── main.py              # Entry point, single-instance lock (fcntl)
├── tray.py              # QSystemTrayIcon — tooltip, menu, update check, timer-driven refresh
├── popup.py             # PopupWidget — charts (daily/model/project), rate limit bars
├── config.py            # Config wrapper around QSettings
├── constants.py         # App name, icon theme, date formats
├── about_dialog.py      # About dialog
├── settings_dialog.py   # Settings UI (interval, toggles, tooltip config)
├── autostart.py         # XDG autostart .desktop file management
├── credentials.py       # Keyring read/write for OAuth tokens
├── updater.py           # GitHub release checker, auto-update, version comparison
└── providers/
    ├── __init__.py      # Dataclasses (UsageData, DailyUsage, RateLimitInfo, etc.), format helpers
    ├── api.py           # Console API provider (API key auth)
    ├── oauth.py         # OAuth provider (claude.ai auth), rate limit parsing, plan name
    ├── local.py         # Local JSONL provider (reads ~/.claude/ conversation logs)
    ├── prediction.py    # Burn rate / exhaustion prediction math
    └── pricing.py       # Per-model token pricing for cost calculation
```

## Data Flow

```
                    ┌─────────────┐
                    │  QTimer     │ (configurable interval, default 5min)
                    └──────┬──────┘
                           │ triggers
                    ┌──────▼──────┐
                    │  _Worker    │ (QThread — never blocks UI)
                    │  thread     │
                    └──────┬──────┘
                           │ calls provider.fetch()
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼──┐  ┌─────▼─────┐  ┌──▼────────┐
     │ OAuth API │  │ Console   │  │ Local     │
     │ (claude.ai│  │ API       │  │ JSONL     │
     │ cookie)   │  │ (API key) │  │ (~/.claude│
     └────────┬──┘  └─────┬─────┘  └──┬────────┘
              │            │            │
              └────────────┼────────────┘
                           │ returns UsageData
                    ┌──────▼──────┐
                    │  Signal     │ (data_ready, crosses thread boundary)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼──┐  ┌─────▼─────┐  ┌──▼────────┐
     │ Tooltip   │  │ Popup     │  │ Rate limit│
     │ update    │  │ charts    │  │ warnings  │
     └───────────┘  └───────────┘  └───────────┘
```

## Threading Model

- **UI thread**: All Qt widgets, signal handlers, tooltip updates
- **Worker thread**: Network requests (OAuth, Console API, GitHub update check), JSONL parsing
- **Thread crossing**: Via Qt signals only (`data_ready`, `update_available`, `error`)
- **Rule**: Never access widgets from worker thread. Never do network/IO on UI thread.

## Config System

`Config` wraps `QSettings` (INI-like, stored in `~/.config/ctfl/`):
- `provider` — "oauth", "api", "local"
- `refresh_interval` — seconds between data fetches
- `tooltip_today`, `tooltip_limits`, `tooltip_sync` — tooltip content toggles
- `show_token_breakdown` — show in/out/cache split in charts
- `rate_limit_warning`, `rate_limit_threshold` — notification when limit approaches

## Rate Limits (OAuth only)

The OAuth API returns utilization as direct percentages (6.0 = 6%, NOT 0.0-1.0).

Window keys and their labels:
- `five_hour` → "Session"
- `seven_day` → "Weekly"
- `seven_day_opus` → "Weekly (Opus)"
- `seven_day_sonnet` → "Weekly (Sonnet)"

## Key Constraints

- **Offline-first**: App must work with cached data when network is unavailable
- **Single instance**: Enforced via fcntl file lock in main.py
- **No database**: All state is QSettings config + cache files in ~/.cache/ctfl/
- **Packaging**: Must work across pip, deb, rpm, AppImage, Arch — no native extensions
