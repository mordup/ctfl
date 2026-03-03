from ctfl.providers.api import ApiProvider


def _make_provider():
    return ApiProvider(lambda: "fake-key")


def test_parse_basic():
    provider = _make_provider()
    usage_data = {
        "data": [
            {
                "date": "2026-03-03",
                "model": "claude-opus-4-6",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 100,
            }
        ]
    }
    cost_data = {
        "data": [
            {"date": "2026-03-03", "cost_usd": 0.42}
        ]
    }
    result = provider._parse(usage_data, cost_data)
    assert len(result.daily) == 1
    assert result.daily[0].date == "2026-03-03"
    assert result.daily[0].input_tokens == 1000
    assert result.daily[0].output_tokens == 500
    assert result.daily[0].cost_usd == 0.42
    assert len(result.by_model) == 1
    assert result.by_model[0].model == "claude-opus-4-6"


def test_parse_no_cost():
    provider = _make_provider()
    usage_data = {
        "data": [
            {
                "date": "2026-03-01",
                "model": "claude-sonnet-4-6",
                "input_tokens": 500,
                "output_tokens": 250,
            }
        ]
    }
    result = provider._parse(usage_data, {})
    assert result.daily[0].cost_usd is None


def test_parse_multiple_days():
    provider = _make_provider()
    usage_data = {
        "data": [
            {"date": "2026-03-01", "model": "claude-opus-4-6", "input_tokens": 100, "output_tokens": 50},
            {"date": "2026-03-02", "model": "claude-opus-4-6", "input_tokens": 200, "output_tokens": 100},
        ]
    }
    result = provider._parse(usage_data, {})
    assert len(result.daily) == 2
    # Sorted descending
    assert result.daily[0].date == "2026-03-02"


def test_parse_bad_structure():
    provider = _make_provider()
    result = provider._parse({"data": "not-a-list"}, {})
    assert result.error is not None


def test_parse_aggregates_same_date():
    """Multiple API entries for the same date (different models) should merge into one DailyUsage."""
    provider = _make_provider()
    usage_data = {
        "data": [
            {"date": "2026-03-03", "model": "claude-opus-4-6", "input_tokens": 1000, "output_tokens": 500},
            {"date": "2026-03-03", "model": "claude-sonnet-4-6", "input_tokens": 2000, "output_tokens": 800},
            {"date": "2026-03-02", "model": "claude-opus-4-6", "input_tokens": 100, "output_tokens": 50},
        ]
    }
    result = provider._parse(usage_data, {})
    assert len(result.daily) == 2
    # The 2026-03-03 entry should be aggregated
    day_03 = next(d for d in result.daily if d.date == "2026-03-03")
    assert day_03.input_tokens == 3000
    assert day_03.output_tokens == 1300
    # Models should still be separate
    assert len(result.by_model) == 2
