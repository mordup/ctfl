"""CTFL's own record of finished days, one file per Claude Code instance.

Claude Code deletes transcripts once they are cleanupPeriodDays old (30 by
default) and refreshes stats-cache.json only when /stats is opened, so neither
reliably covers the previous month. Each finished day is kept here, as token
aggregates only, from the first day of the previous month on.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..constants import DATE_FMT_ISO

_DIR = Path.home() / ".cache" / "ctfl"
_VERSION = 1

# (input, output, cache_read, cache_creation, cache_creation_5m, cache_creation_1h)
Tokens = tuple[int, int, int, int, int, int]


@dataclass
class DayRecord:
    messages: int = 0
    sessions: int = 0
    tokens: dict[tuple[str, str], Tokens] = field(default_factory=dict)  # (model, speed)
    projects: dict[str, tuple[str, int, int]] = field(default_factory=dict)  # dir -> (name, tokens, messages)


def history_start(today: date) -> date:
    """First day kept: the first of the previous month."""
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def history_file(instance_path: Path) -> Path:
    digest = hashlib.sha1(str(instance_path).encode(), usedforsecurity=False).hexdigest()[:8]
    return _DIR / f"history_{digest}.json"


def load(path: Path) -> dict[str, DayRecord] | None:
    """The stored days, {} when there is no usable file, or None when the file
    must be left alone: it could not be read, so its days may still be intact,
    or a newer CTFL wrote it."""
    try:
        raw = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    except ValueError:
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("days"), dict):
        return {}
    if raw.get("version") != _VERSION:
        return None if isinstance(raw.get("version"), int) and raw["version"] > _VERSION else {}
    days: dict[str, DayRecord] = {}
    for day, entry in raw["days"].items():
        record = _parse_day(day, entry)
        if record is not None:
            days[day] = record
    return days


def save(path: Path, days: dict[str, DayRecord]) -> None:
    payload = {
        "version": _VERSION,
        "days": {
            day: {
                "messages": r.messages,
                "sessions": r.sessions,
                "tokens": [[model, speed, *t] for (model, speed), t in r.tokens.items()],
                "projects": [[d, *p] for d, p in r.projects.items()],
            }
            for day, r in sorted(days.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _parse_day(day, entry) -> DayRecord | None:
    try:
        datetime.strptime(day, DATE_FMT_ISO)
    except (TypeError, ValueError):
        return None
    if not isinstance(entry, dict):
        return None
    messages, sessions = entry.get("messages"), entry.get("sessions")
    tokens, projects = entry.get("tokens"), entry.get("projects")
    if not (_count(messages) and _count(sessions)
            and isinstance(tokens, list) and isinstance(projects, list)):
        return None
    record = DayRecord(messages=messages, sessions=sessions)
    for row in tokens:
        if not (isinstance(row, list) and len(row) == 8
                and isinstance(row[0], str) and isinstance(row[1], str)
                and all(_count(v) for v in row[2:])):
            return None
        record.tokens[(row[0], row[1])] = tuple(row[2:])
    for row in projects:
        if not (isinstance(row, list) and len(row) == 4
                and isinstance(row[0], str) and isinstance(row[1], str)
                and _count(row[2]) and _count(row[3])):
            return None
        record.projects[row[0]] = (row[1], row[2], row[3])
    return record
