"""'Days to show: N' must yield N calendar days including today, not N+1."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ctfl.providers.instance import Instance
from ctfl.providers.local import LocalProvider


def _record(days_ago: int) -> dict:
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "sess",
        "requestId": f"req-{days_ago}",
        "message": {
            "model": "claude-opus-5",
            "content": [{"type": "text"}],
            "usage": {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        },
    }


def _fetch(tmp_path: Path, monkeypatch, days: int):
    path = tmp_path / "projects" / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    with open(path, "w") as f:
        for days_ago in range(0, 10):
            f.write(json.dumps(_record(days_ago)) + "\n")
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="test", path=tmp_path),
    )
    return LocalProvider().fetch(days=days)


def test_window_has_exactly_n_days(tmp_path, monkeypatch):
    data = _fetch(tmp_path, monkeypatch, days=7)
    assert len(data.daily) == 7


def test_window_includes_today(tmp_path, monkeypatch):
    data = _fetch(tmp_path, monkeypatch, days=1)
    assert [d.date for d in data.daily] == [datetime.now().strftime("%Y-%m-%d")]


def test_file_last_written_early_on_the_oldest_day_is_scanned(tmp_path, monkeypatch):
    """The mtime pre-filter must use local midnight: a file whose last write
    was at 01:00 local on the oldest day sits before UTC midnight east of UTC."""
    import os

    oldest = datetime.now().date() - timedelta(days=6)
    at = datetime.combine(oldest, datetime.min.time()).replace(hour=1).astimezone()
    rec = _record(0)
    rec["timestamp"] = at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = tmp_path / "projects" / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(rec) + "\n")
    os.utime(path, (at.timestamp(), at.timestamp()))
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="test", path=tmp_path),
    )
    data = LocalProvider().fetch(days=7)
    assert [d.date for d in data.daily] == [oldest.strftime("%Y-%m-%d")]
