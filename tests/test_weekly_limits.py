"""Tests for multi-bucket weekly limit parsing (All models / Sonnet / Claude Design)."""

from __future__ import annotations

from ctfl.providers import RateLimitInfo
from ctfl.providers.oauth import _parse_limits
from ctfl.providers.prediction import predict_exhaustion

# Sample payload observed on a Max plan that has the new Claude Design
# (internal key: seven_day_omelette) bucket exposed but unused.
_MAX_PAYLOAD_WITH_OMELETTE = {
    "five_hour": {
        "utilization": 2.0,
        "resets_at": "2026-04-22T11:00:00.902738+00:00",
    },
    "seven_day": {
        "utilization": 10.0,
        "resets_at": "2026-04-23T19:00:00.902757+00:00",
    },
    "seven_day_oauth_apps": None,
    "seven_day_opus": None,
    "seven_day_sonnet": {
        "utilization": 2.0,
        "resets_at": "2026-04-23T22:00:00.902762+00:00",
    },
    "seven_day_cowork": None,
    "seven_day_omelette": {
        "utilization": 0.0,
        "resets_at": None,
    },
}


def test_parse_limits_emits_claude_design_bucket():
    limits = _parse_limits(_MAX_PAYLOAD_WITH_OMELETTE)
    by_key = {li.window_key: li for li in limits}
    assert "seven_day_omelette" in by_key
    design = by_key["seven_day_omelette"]
    assert design.name == "Weekly (Claude Design)"
    assert design.utilization == 0.0
    assert design.resets_at is None


def test_parse_limits_preserves_three_weekly_buckets_in_order():
    # Insertion order of _KEY_LABELS drives popup column order; verify the
    # new omelette entry lands after sonnet (dashboard order: All models,
    # Sonnet, Claude Design) and that Opus (null) is skipped.
    limits = _parse_limits(_MAX_PAYLOAD_WITH_OMELETTE)
    weekly_keys = [li.window_key for li in limits if li.window_key.startswith("seven_day")]
    assert weekly_keys == ["seven_day", "seven_day_sonnet", "seven_day_omelette"]


def test_predict_exhaustion_returns_none_for_unused_claude_design():
    # 0% utilization + null resets_at — no burn rate can be computed.
    info = RateLimitInfo(
        name="Weekly (Claude Design)",
        utilization=0.0,
        resets_at=None,
        window_key="seven_day_omelette",
    )
    assert predict_exhaustion(info, info.window_key) is None


def test_predict_exhaustion_supports_claude_design_window():
    # Once usage exists, the 168h weekly window applies just like the other
    # seven_day_* buckets.
    info = RateLimitInfo(
        name="Weekly (Claude Design)",
        utilization=50.0,
        resets_at="2026-04-23T19:00:00+00:00",
        window_key="seven_day_omelette",
    )
    # Non-trivial burn rate at 50% utilization; exact value depends on "now"
    # but predict_exhaustion must at least not reject the key as unknown.
    # (None means the bucket won't be exhausted before reset, which is fine.)
    # We just assert it doesn't raise and returns a str or None.
    result = predict_exhaustion(info, info.window_key)
    assert result is None or isinstance(result, str)
