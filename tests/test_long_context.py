from __future__ import annotations

import json
from pathlib import Path

from ctfl.providers.instance import Instance
from ctfl.providers.local import LONG_CONTEXT_THRESHOLD, LocalProvider


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _assistant(
    *,
    timestamp: str = "2026-04-15T10:00:00Z",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read: int = 0,
    cache_creation: int = 0,
    session_id: str = "sess",
    model: str = "claude-opus-4-7",
) -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
        },
    }


def _pin(monkeypatch, instance_path: Path) -> None:
    instance = Instance(name="test", path=instance_path)
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: instance,
    )


def test_long_context_metric_zero_when_all_short(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "proj"
    _write_jsonl(
        projects / "sess.jsonl",
        [_assistant(input_tokens=5_000, output_tokens=1_000)],
    )
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert data.long_context_tokens == 0


def test_long_context_metric_counts_messages_at_or_above_threshold(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "proj"
    # One short message, one at exactly the threshold (cache_read portion puts
    # context_size at 150k exactly), one well above.
    short = _assistant(input_tokens=1_000, output_tokens=500)
    at_threshold = _assistant(
        input_tokens=50_000,
        cache_read=100_000,
        cache_creation=0,
        output_tokens=2_000,
    )
    above = _assistant(
        input_tokens=10_000,
        cache_read=180_000,
        cache_creation=0,
        output_tokens=3_000,
    )
    _write_jsonl(projects / "sess.jsonl", [short, at_threshold, above])
    _pin(monkeypatch, tmp_path)

    data = LocalProvider().fetch(days=30)

    short_cost = 1_000 + 500
    at_threshold_cost = 50_000 + 2_000 + 100_000 + 0
    above_cost = 10_000 + 3_000 + 180_000 + 0
    assert data.long_context_tokens == at_threshold_cost + above_cost
    # Denominator is every record seen in the JSONL scan window, not just
    # ones past the threshold.
    assert data.long_context_total_tokens == short_cost + at_threshold_cost + above_cost


def test_long_context_threshold_excludes_just_below(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "proj"
    just_below = _assistant(
        input_tokens=LONG_CONTEXT_THRESHOLD - 1,
        cache_read=0,
        output_tokens=1_000,
    )
    _write_jsonl(projects / "sess.jsonl", [just_below])
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert data.long_context_tokens == 0


def test_long_context_empty_projects_dir(tmp_path, monkeypatch):
    (tmp_path / "projects").mkdir()
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert data.long_context_tokens == 0
