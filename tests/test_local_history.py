"""CTFL's history fills the days whose transcripts Claude Code has deleted."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ctfl.config import Config
from ctfl.providers import history
from ctfl.providers.history import DayRecord, history_file, history_start
from ctfl.providers.instance import Instance
from ctfl.providers.local import LocalProvider


def _date(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _record(days_ago: int, request: str = "a") -> dict:
    return {
        "type": "assistant",
        "timestamp": (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessionId": "sess",
        "requestId": f"req-{days_ago}-{request}",
        "message": {
            "model": "claude-opus-5",
            "content": [{"type": "text"}],
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        },
    }


def _write(instance_path: Path, records: list[dict]) -> Path:
    path = instance_path / "projects" / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _provider(tmp_path: Path, monkeypatch) -> LocalProvider:
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="test", path=tmp_path),
    )
    config = Config()
    config.estimate_costs = True
    return LocalProvider(config)


def test_finished_day_survives_transcript_deletion(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    transcript = _write(tmp_path, [_record(1)])
    before = provider.fetch(days=7).daily[0]

    transcript.unlink()
    after = provider.fetch(days=7).daily[0]
    assert after == before
    assert after.breakdown_available
    assert after.cost_usd is not None


def test_today_is_not_kept(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    transcript = _write(tmp_path, [_record(0)])
    provider.fetch(days=7)

    transcript.unlink()
    assert provider.fetch(days=7).daily == []


def test_partly_deleted_day_keeps_the_fuller_record(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    _write(tmp_path, [_record(1, "a"), _record(1, "b")])
    provider.fetch(days=7)

    _write(tmp_path, [_record(1, "a")])
    assert provider.fetch(days=7).daily[0].message_count == 2
    assert history.load(history_file(tmp_path))[_date(1)].messages == 2


def test_days_before_the_previous_month_are_pruned(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    start = history_start(datetime.now().date())
    kept, dropped = start.isoformat(), (start - timedelta(days=1)).isoformat()
    history.save(history_file(tmp_path), {kept: DayRecord(messages=1), dropped: DayRecord(messages=1)})

    provider.fetch(days=7)
    assert list(history.load(history_file(tmp_path))) == [kept]


def test_history_written_by_a_newer_version_is_left_alone(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    path = history_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 99, "days": {}}))
    _write(tmp_path, [_record(1)])

    assert [d.date for d in provider.fetch(days=7).daily] == [_date(1)]
    assert json.loads(path.read_text()) == {"version": 99, "days": {}}


def test_instances_not_on_display_are_kept_too(tmp_path, monkeypatch):
    shown, other = tmp_path / "shown", tmp_path / "other"
    _write(other, [_record(1)])
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="shown", path=shown),
    )
    monkeypatch.setattr(
        "ctfl.providers.local.discover_instances",
        lambda: [Instance(name="shown", path=shown), Instance(name="other", path=other)],
    )
    LocalProvider().fetch(days=7)
    assert list(history.load(history_file(other))) == [_date(1)]


def test_history_wins_over_stats_cache(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch)
    transcript = _write(tmp_path, [_record(1)])
    provider.fetch(days=7)

    transcript.unlink()
    (tmp_path / "stats-cache.json").write_text(json.dumps({
        "dailyActivity": [{"date": _date(1), "messageCount": 99, "sessionCount": 9}],
        "dailyModelTokens": [{"date": _date(1), "tokensByModel": {"claude-opus-5": 999_999}}],
    }))
    day = provider.fetch(days=7).daily[0]
    assert (day.total_tokens, day.message_count, day.breakdown_available) == (150, 1, True)
    assert day.cost_usd is not None


def test_idle_instance_is_scanned_again_the_next_day(tmp_path, monkeypatch):
    shown, other = Instance(name="shown", path=tmp_path / "shown"), tmp_path / "other"
    _write(other, [_record(0)])
    monkeypatch.setattr(
        "ctfl.providers.local.discover_instances",
        lambda: [shown, Instance(name="other", path=other)],
    )
    provider = LocalProvider()
    today = datetime.now().date()
    provider._archive_other_instances(shown, today)
    assert history.load(history_file(other)) == {}

    provider._archive_other_instances(shown, today + timedelta(days=1))
    assert list(history.load(history_file(other))) == [_date(0)]


def test_unwritable_history_does_not_break_the_refresh(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr("ctfl.providers.history._DIR", blocker)
    provider = _provider(tmp_path, monkeypatch)
    _write(tmp_path, [_record(1)])

    data = provider.fetch(days=7)
    assert data.error is None
    assert [d.date for d in data.daily] == [_date(1)]
