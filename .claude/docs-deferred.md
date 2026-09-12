# Deferred ctfl-docs work

Punch-list items deferred at a release. The release workflow re-raises every
entry here at the next release; an item leaves this file only when the docs
are updated or the user drops it explicitly. `scripts/docs-freshness.sh`
cannot surface any of these on its own.

- `docs/updating.md`: a ~3-line troubleshooting note for the "Update
  verification failed" dialog. It means the release failed the SHA256SUMS
  check, not that the user's machine is at fault; wait for a corrected
  release or update via the package manager. Not a full section. Deferred
  at 2.7.3 (2026-06-09), 2.9.0, 2.9.1.
- `docs/getting-started.md`: a section on the popup being an ordinary window
  since 2.9.0: resizable, remembers the size you chose, stays open when you
  click another application. Deferred at 2.9.0 (2026-08-26), 2.9.1.
- Screenshots that predate 2.9.0 and contradict it: `rate_limits.png` (no
  Fable bar, no monthly-spend row on a Max plan), `tray_overlay.png`,
  `usage_daily.png`, `usage_models.png` (old Tool-style popup). Note
  `rate_limits.png` and `tray_enterprise.png` exist only in the docs repo,
  so the freshness script never examines them. Deferred at 2.9.0, 2.9.1.
