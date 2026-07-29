import json

from ctfl.providers.local import LocalProvider


def _write_jsonl(path, records):
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _make_assistant_record(timestamp="2026-03-03T10:00:00Z", model="claude-opus-4-6",
                            input_tokens=100, output_tokens=50,
                            cache_read=10, cache_creation=5,
                            session_id="sess-1"):
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
            }
        }
    }


def test_parse_jsonl_basic(tmp_path):
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [
        _make_assistant_record(),
        _make_assistant_record(timestamp="2026-03-03T11:00:00Z"),
    ])
    provider = LocalProvider()
    records = provider._parse_jsonl(jsonl_file)
    assert len(records) == 2
    assert records[0]["date"] == "2026-03-03"
    assert records[0]["model"] == "claude-opus-4-6"
    assert records[0]["input_tokens"] == 100


def test_parse_jsonl_skips_non_assistant(tmp_path):
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [
        {"type": "human", "timestamp": "2026-03-03T10:00:00Z"},
        _make_assistant_record(),
    ])
    provider = LocalProvider()
    records = provider._parse_jsonl(jsonl_file)
    assert len(records) == 1


def test_parse_jsonl_skips_bad_json(tmp_path):
    jsonl_file = tmp_path / "test.jsonl"
    with open(jsonl_file, "w") as f:
        f.write("not json\n")
        f.write(json.dumps(_make_assistant_record()) + "\n")
    provider = LocalProvider()
    records = provider._parse_jsonl(jsonl_file)
    assert len(records) == 1


def test_parse_jsonl_caches_by_mtime(tmp_path):
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [_make_assistant_record()])
    provider = LocalProvider()
    records1 = provider._parse_jsonl(jsonl_file)
    records2 = provider._parse_jsonl(jsonl_file)
    assert records1 is records2  # Same object from cache


def test_parse_jsonl_missing_file(tmp_path):
    provider = LocalProvider()
    records = provider._parse_jsonl(tmp_path / "nonexistent.jsonl")
    assert records == []


def test_parse_jsonl_splits_cache_creation_by_ttl(tmp_path):
    rec = _make_assistant_record(cache_creation=1000)
    rec["message"]["usage"]["cache_creation"] = {
        "ephemeral_1h_input_tokens": 800,
        "ephemeral_5m_input_tokens": 200,
    }
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [rec])
    records = LocalProvider()._parse_jsonl(jsonl_file)
    assert records[0]["cache_creation"] == 1000
    assert records[0]["cache_creation_1h"] == 800
    assert records[0]["cache_creation_5m"] == 200


def test_parse_jsonl_without_ttl_breakdown_bills_5m(tmp_path):
    # Records predating the breakdown carry only the aggregate; it must land in
    # the cheaper 5-minute bucket rather than being dropped.
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [_make_assistant_record(cache_creation=500)])
    records = LocalProvider()._parse_jsonl(jsonl_file)
    assert records[0]["cache_creation_5m"] == 500
    assert records[0]["cache_creation_1h"] == 0


def test_parse_jsonl_partial_ttl_breakdown_keeps_remainder(tmp_path):
    rec = _make_assistant_record(cache_creation=1000)
    rec["message"]["usage"]["cache_creation"] = {"ephemeral_1h_input_tokens": 600}
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [rec])
    records = LocalProvider()._parse_jsonl(jsonl_file)
    assert records[0]["cache_creation_1h"] == 600
    assert records[0]["cache_creation_5m"] == 400  # unattributed remainder


def test_parse_jsonl_reads_speed(tmp_path):
    rec = _make_assistant_record()
    rec["message"]["usage"]["speed"] = "fast"
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [rec])
    assert LocalProvider()._parse_jsonl(jsonl_file)[0]["speed"] == "fast"


def test_parse_jsonl_speed_defaults_to_standard(tmp_path):
    # Records predating the field, or with it null, bill at standard rates.
    jsonl_file = tmp_path / "test.jsonl"
    _write_jsonl(jsonl_file, [_make_assistant_record()])
    assert LocalProvider()._parse_jsonl(jsonl_file)[0]["speed"] == "standard"


def test_parse_jsonl_empty_lines(tmp_path):
    jsonl_file = tmp_path / "test.jsonl"
    with open(jsonl_file, "w") as f:
        f.write("\n")
        f.write(json.dumps(_make_assistant_record()) + "\n")
        f.write("\n")
    provider = LocalProvider()
    records = provider._parse_jsonl(jsonl_file)
    assert len(records) == 1
