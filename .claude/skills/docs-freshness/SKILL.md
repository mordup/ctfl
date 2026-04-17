---
name: docs-freshness
description: Audit whether ctfl-docs reflects the current CTFL state. Run before releasing or when the user asks whether docs are current. Produces a punch list; never edits docs without explicit confirmation.
---

# docs-freshness

Purpose: surface drift between the CTFL app and the ctfl-docs site as a
concrete punch list, so each item becomes an explicit keep-or-defer
decision during release rather than a vague reminder that gets skipped.

## Steps

1. Run `bash scripts/docs-freshness.sh` from the repo root. If it exits
   non-zero (docs repo missing at the expected path), tell the user and
   stop — there's nothing to audit.

2. For each UI source file in the "UI source files changed" section,
   open the file(s) where that UI is documented and check for drift:
   - `ctfl/popup.py` → `docs/getting-started.md`
   - `ctfl/tray.py` → `docs/getting-started.md`
   - `ctfl/settings_dialog.py` → `docs/configuration.md`
   - `ctfl/about_dialog.py` → `docs/updating.md`

   Drift signals to look for: feature names or UI elements described in
   docs that no longer exist; new UI elements in the code with no docs
   mention; described behavior that has since changed.

3. Scan the commit list for `feat:` and user-visible `fix:` subjects.
   Each is a candidate for a docs mention. Skip `chore:`, `refactor:`,
   `test:`, `build:` unless they changed something user-facing.

4. For screenshots flagged as "source newer" or "missing in docs",
   grep the docs for that filename (`grep -r '!\[.*\]' ../ctfl-docs/docs/`)
   to see which pages reference it — those pages likely need a fresh
   capture.

5. Produce a punch list — one item per line, each citing a file and
   the specific drift:

   - `update docs/getting-started.md — tooltip section doesn't mention the profile header`
   - `re-shoot screenshots/settings.png — dialog has profile controls not in the image`
   - `add a docs page or section for Enterprise monthly spend (new in v2.6.0)`

6. Report the punch list. Stop. The user decides what to fix and when.

## Scope

- Does NOT take screenshots (requires GUI interaction).
- Does NOT edit docs or copy images.
- Its only job is to surface drift before release in a form the user
  can't skim past.

## When invoked

- Release workflow step 1, alongside code-auditor and quality-analyst.
- Ad-hoc when the user asks "are the docs fresh?" or similar.
