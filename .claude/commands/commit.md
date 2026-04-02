Commit workflow for the ctfl project. Follow these steps exactly:

## 1. Pre-commit checks

Run these in parallel:
- `ruff check ctfl/ tests/` — if it fails, fix the issues (auto-fix with `ruff check --fix` then manually fix remaining) and re-run until clean
- `python -m pytest tests/ -q` — if it fails, fix the failing tests and re-run until green

If either check required code changes, include those changes in the commit.

## 2. Prepare commit

- Run `git status` and `git diff` to review all changes (staged + unstaged)
- Run `git log --oneline -5` to see recent commit style

## 3. Stage and commit

- Stage relevant files by name (never `git add -A` or `git add .`)
- Do NOT stage files that contain secrets (.env, credentials, tokens)
- Do NOT stage `.claude/settings.local.json`
- Write a commit message using conventional commits format: `type: description`
  - Types: `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `chore`
  - Subject line under 72 characters
  - **No Co-Authored-By lines** — never add them
- Use a HEREDOC for the commit message

## 4. Verify

- Run `git status` after commit to confirm success
- Report what was committed
