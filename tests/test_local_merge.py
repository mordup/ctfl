"""Transcripts are the primary source; the stats cache only fills days they lack.

The cache has no per-category breakdown, so a day sourced from it cannot be
priced, and its totals count every content block rather than every request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ctfl.config import Config
from ctfl.providers.instance import Instance
from ctfl.providers.local import LocalProvider


def _date(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _record(days_ago: int, model: str = "claude-opus-5") -> dict:
    return {
        "type": "assistant",
        "timestamp": (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessionId": "sess",
        "requestId": f"req-{days_ago}-{model}",
        "message": {
            "model": model,
            "content": [{"type": "text"}],
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        },
    }


def _setup(tmp_path: Path, monkeypatch, records: list[dict], cache: dict) -> LocalProvider:
    path = tmp_path / "projects" / "proj" / "sess.jsonl"
    path.parent.mkdir(parents=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    (tmp_path / "stats-cache.json").write_text(json.dumps(cache))
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="test", path=tmp_path),
    )
    config = Config()
    config.estimate_costs = True
    return LocalProvider(config)


def _cache(days: dict[int, dict[str, int]], last_computed_days_ago: int = 1) -> dict:
    return {
        "lastComputedDate": _date(last_computed_days_ago),
        "dailyActivity": [
            {"date": _date(d), "messageCount": 99, "sessionCount": 9} for d in days
        ],
        "dailyModelTokens": [
            {"date": _date(d), "tokensByModel": models} for d, models in days.items()
        ],
    }


def test_transcript_day_wins_over_cache_day(tmp_path, monkeypatch):
    provider = _setup(
        tmp_path, monkeypatch, [_record(1)], _cache({1: {"claude-opus-5": 999_999}})
    )
    day = provider.fetch(days=7).daily[0]
    assert day.date == _date(1)
    assert day.total_tokens == 150
    assert day.breakdown_available
    assert day.cost_usd is not None
    assert day.message_count == 1


def test_cache_fills_day_without_transcript(tmp_path, monkeypatch):
    provider = _setup(
        tmp_path, monkeypatch, [_record(1)], _cache({3: {"claude-opus-5": 5_000}})
    )
    daily = {d.date: d for d in provider.fetch(days=7).daily}
    assert daily[_date(1)].cost_usd is not None
    filled = daily[_date(3)]
    assert filled.total_tokens == 5_000
    assert not filled.breakdown_available
    assert filled.cost_usd is None
    assert filled.message_count == 99


def test_cache_day_outside_window_is_ignored(tmp_path, monkeypatch):
    provider = _setup(
        tmp_path, monkeypatch, [_record(1)], _cache({10: {"claude-opus-5": 5_000}})
    )
    assert [d.date for d in provider.fetch(days=7).daily] == [_date(1)]


def test_by_model_counts_a_shared_day_once(tmp_path, monkeypatch):
    provider = _setup(
        tmp_path, monkeypatch, [_record(1)], _cache({1: {"claude-opus-5": 999_999}})
    )
    by_model = provider.fetch(days=7).by_model
    assert [(m.model, m.total, m.breakdown_available) for m in by_model] == [
        ("claude-opus-5", 150, True)
    ]


def test_by_model_merges_cache_only_day_without_breakdown(tmp_path, monkeypatch):
    provider = _setup(
        tmp_path, monkeypatch,
        [_record(1)],
        _cache({3: {"claude-opus-5": 5_000, "claude-sonnet-5": 700}}),
    )
    by_model = {m.model: m for m in provider.fetch(days=7).by_model}
    assert by_model["claude-opus-5"].total == 5_150
    assert not by_model["claude-opus-5"].breakdown_available
    assert by_model["claude-sonnet-5"].total == 700
    assert not by_model["claude-sonnet-5"].breakdown_available
