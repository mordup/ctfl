"""Claude Code writes one JSONL record per assistant content block.

A single API request appears as 2-3 records (thinking / text / tool_use), each
repeating a byte-identical `message.usage`. Counting per record inflated every
token, message and cost figure by roughly 2x.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ctfl.providers.instance import Instance
from ctfl.providers.local import LocalProvider

_RECENT_TS = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _assistant(*, request_id=None, message_id=None, uuid=None, block="text",
               input_tokens=1000, output_tokens=500, timestamp=_RECENT_TS):
    """One content-block record. Usage is repeated verbatim, as the real logs do."""
    rec = {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": "sess",
        "message": {
            "model": "claude-opus-5",
            "content": [{"type": block}],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }
    if request_id is not None:
        rec["requestId"] = request_id
    if message_id is not None:
        rec["message"]["id"] = message_id
    if uuid is not None:
        rec["uuid"] = uuid
    return rec


def _pin(monkeypatch, instance_path: Path) -> None:
    monkeypatch.setattr(
        "ctfl.providers.local.resolve_profile",
        lambda config=None: Instance(name="test", path=instance_path),
    )


def _day(tmp_path, monkeypatch, records, filename="proj/sess.jsonl"):
    _write_jsonl(tmp_path / "projects" / filename, records)
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert len(data.daily) == 1
    return data.daily[0]


def test_one_request_across_three_blocks_counts_once(tmp_path, monkeypatch):
    day = _day(tmp_path, monkeypatch, [
        _assistant(request_id="req_1", block="thinking"),
        _assistant(request_id="req_1", block="text"),
        _assistant(request_id="req_1", block="tool_use"),
    ])
    assert day.input_tokens == 1000
    assert day.output_tokens == 500
    assert day.message_count == 1


def test_distinct_requests_are_summed(tmp_path, monkeypatch):
    day = _day(tmp_path, monkeypatch, [
        _assistant(request_id="req_1"),
        _assistant(request_id="req_2"),
    ])
    assert day.input_tokens == 2000
    assert day.message_count == 2


def test_falls_back_to_message_id_without_request_id(tmp_path, monkeypatch):
    day = _day(tmp_path, monkeypatch, [
        _assistant(message_id="msg_1", block="text"),
        _assistant(message_id="msg_1", block="tool_use"),
    ])
    assert day.input_tokens == 1000
    assert day.message_count == 1


def test_falls_back_to_uuid_without_request_or_message_id(tmp_path, monkeypatch):
    day = _day(tmp_path, monkeypatch, [
        _assistant(uuid="u_1", block="text"),
        _assistant(uuid="u_1", block="tool_use"),
    ])
    assert day.input_tokens == 1000


def test_records_with_no_identifier_are_all_counted(tmp_path, monkeypatch):
    # Nothing to dedupe on: counting twice is wrong but dropping data is worse.
    day = _day(tmp_path, monkeypatch, [_assistant(), _assistant()])
    assert day.input_tokens == 2000


def test_dedup_spans_multiple_files(tmp_path, monkeypatch):
    _write_jsonl(tmp_path / "projects" / "proj" / "a.jsonl",
                 [_assistant(request_id="req_1")])
    _write_jsonl(tmp_path / "projects" / "proj" / "b.jsonl",
                 [_assistant(request_id="req_1")])
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert data.daily[0].input_tokens == 1000


def test_dedup_applies_to_cost_estimate(tmp_path, monkeypatch):
    from types import SimpleNamespace
    _write_jsonl(tmp_path / "projects" / "proj" / "sess.jsonl", [
        _assistant(request_id="req_1", input_tokens=1_000_000, output_tokens=0),
        _assistant(request_id="req_1", input_tokens=1_000_000, output_tokens=0),
    ])
    _pin(monkeypatch, tmp_path)
    cfg = SimpleNamespace(estimate_costs=True, profile="auto")
    data = LocalProvider(cfg).fetch(days=30)
    # 1M input on Opus 5 at $5/MTok, counted once.
    assert data.daily[0].cost_usd == 5.00


def test_dedup_applies_to_long_context_metric(tmp_path, monkeypatch):
    day_records = [
        _assistant(request_id="req_1", input_tokens=200_000, output_tokens=0),
        _assistant(request_id="req_1", input_tokens=200_000, output_tokens=0),
    ]
    _write_jsonl(tmp_path / "projects" / "proj" / "sess.jsonl", day_records)
    _pin(monkeypatch, tmp_path)
    data = LocalProvider().fetch(days=30)
    assert data.long_context_total_tokens == 200_000


def test_parse_jsonl_emits_request_id(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [_assistant(request_id="req_1", message_id="msg_1")])
    assert LocalProvider()._parse_jsonl(path)[0]["request_id"] == "req_1"


def test_parse_jsonl_request_id_prefers_request_over_message(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [_assistant(request_id="req_1", message_id="msg_1", uuid="u_1")])
    assert LocalProvider()._parse_jsonl(path)[0]["request_id"] == "req_1"
