"""Tests for Enterprise spend-limit parsing & rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ctfl.providers import RateLimitInfo, format_credits
from ctfl.providers.instance import Instance
from ctfl.providers.oauth import (
    _first_of_next_month_utc,
    _load_limits_cache,
    _parse_limits,
    _save_limits_cache,
    read_plan_name,
)

# Sample payload observed on an Enterprise account — all rate windows null,
# usage expressed as a single monthly-spend block in USD cents.
_ENTERPRISE_PAYLOAD = {
    "five_hour": None,
    "seven_day": None,
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "extra_usage": {
        "is_enabled": True,
        "monthly_limit": 100000,
        "used_credits": 1987,
        "utilization": 1.987,
        "currency": "USD",
    },
}


def _pin_profile(monkeypatch, instance_path: Path) -> None:
    instance = Instance(name="test", path=instance_path)
    monkeypatch.setattr(
        "ctfl.providers.oauth.resolve_profile",
        lambda config=None: instance,
    )


def test_parse_limits_enterprise_emits_monthly_spend():
    limits = _parse_limits(_ENTERPRISE_PAYLOAD)
    assert len(limits) == 1
    info = limits[0]
    assert info.name == "Monthly spend"
    assert info.window_key == "monthly_spend"
    assert info.used_credits == 1987
    assert info.monthly_limit == 100000
    assert info.currency == "USD"
    assert round(info.utilization, 3) == 1.987
    # Synthetic reset is always ISO 8601 at a first-of-month UTC boundary.
    reset = datetime.fromisoformat(info.resets_at)
    assert reset.day == 1
    assert reset.tzinfo is not None


def test_parse_limits_enterprise_disabled_extra_usage():
    payload = dict(_ENTERPRISE_PAYLOAD)
    payload["extra_usage"] = {**payload["extra_usage"], "is_enabled": False}
    assert _parse_limits(payload) == []


def test_parse_limits_enterprise_missing_fields():
    # Even with is_enabled=True, skip when any required figure is missing.
    payload = {"extra_usage": {"is_enabled": True, "monthly_limit": 100000}}
    assert _parse_limits(payload) == []


def test_parse_limits_enterprise_tolerates_non_dict_extra_usage():
    # Malformed API payload (extra_usage as a list/string) must not break
    # parsing of the other windows.
    payload = {
        "five_hour": {"utilization": 30.0, "resets_at": "2026-04-17T12:00:00+00:00"},
        "extra_usage": [],
    }
    limits = _parse_limits(payload)
    assert len(limits) == 1
    assert limits[0].window_key == "five_hour"


def test_parse_limits_enterprise_skips_nan_utilization():
    payload = {"extra_usage": {
        "is_enabled": True,
        "utilization": float("nan"),
        "monthly_limit": 100000,
        "used_credits": 1987,
        "currency": "USD",
    }}
    assert _parse_limits(payload) == []


def test_parse_limits_enterprise_skips_zero_limit():
    payload = {"extra_usage": {
        "is_enabled": True,
        "utilization": 0.0,
        "monthly_limit": 0,
        "used_credits": 0,
        "currency": "USD",
    }}
    assert _parse_limits(payload) == []


def test_parse_limits_enterprise_rounds_fractional_used_credits():
    payload = {"extra_usage": {
        "is_enabled": True,
        "utilization": 2.0,
        "monthly_limit": 100000,
        "used_credits": 1987.6,
        "currency": "USD",
    }}
    limits = _parse_limits(payload)
    assert len(limits) == 1
    assert limits[0].used_credits == 1988


def test_parse_limits_max_plan_still_ignores_extra_usage():
    # Regression guard: a Pro/Max payload with sibling windows populated
    # should still emit the session/weekly entries and skip extra_usage when
    # not present.
    payload = {
        "five_hour": {"utilization": 30.0, "resets_at": "2026-04-17T12:00:00+00:00"},
    }
    limits = _parse_limits(payload)
    assert len(limits) == 1
    assert limits[0].window_key == "five_hour"


# --- newer top-level `spend` block ---

# Shape observed on a Max account with usage credits enabled: extra_usage is
# still present but its utilization is null, and the live figures live in the
# sibling `spend` block instead.
_SPEND_BLOCK_PAYLOAD = {
    "five_hour": {"utilization": 15.0, "resets_at": "2026-07-29T11:30:00+00:00"},
    "seven_day": {"utilization": 4.0, "resets_at": "2026-07-31T19:00:00+00:00"},
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "extra_usage": {
        "is_enabled": True, "currency": "EUR", "monthly_limit": 6000,
        "used_credits": 0.0, "utilization": None,
    },
    "spend": {
        "enabled": True, "percent": 25, "severity": "normal",
        "used": {"amount_minor": 1500, "currency": "EUR", "exponent": 2},
        "limit": {"amount_minor": 6000, "currency": "EUR", "exponent": 2},
        "cap": {"credits": None,
                "money": {"amount_minor": 6000, "currency": "EUR", "exponent": 2}},
    },
}


def test_spend_block_emits_monthly_spend_row():
    limits = _parse_limits(_SPEND_BLOCK_PAYLOAD)
    assert [li.window_key for li in limits] == ["five_hour", "seven_day", "monthly_spend"]
    spend = limits[-1]
    assert spend.name == "Monthly spend"
    assert spend.utilization == 25
    assert spend.used_credits == 1500
    assert spend.monthly_limit == 6000
    assert spend.currency == "EUR"


def test_spend_block_renders_as_euros():
    spend = _parse_limits(_SPEND_BLOCK_PAYLOAD)[-1]
    assert format_credits(spend.used_credits, spend.currency) == "15 EUR"
    assert format_credits(spend.monthly_limit, spend.currency) == "60 EUR"


def test_spend_block_wins_over_legacy_extra_usage():
    # extra_usage says 0 used; the spend block says 1500. The newer block wins.
    assert _parse_limits(_SPEND_BLOCK_PAYLOAD)[-1].used_credits == 1500


def test_spend_block_disabled_falls_back_to_extra_usage():
    payload = dict(_SPEND_BLOCK_PAYLOAD)
    payload["spend"] = {**payload["spend"], "enabled": False}
    payload["extra_usage"] = {**payload["extra_usage"], "utilization": 3.0}
    spend = _parse_limits(payload)[-1]
    assert spend.used_credits == 0
    assert spend.utilization == 3.0


def test_spend_block_malformed_falls_back_to_extra_usage():
    payload = dict(_SPEND_BLOCK_PAYLOAD)
    payload["spend"] = {"enabled": True}  # no money blocks
    payload["extra_usage"] = {**payload["extra_usage"], "utilization": 3.0}
    assert _parse_limits(payload)[-1].utilization == 3.0


def test_spend_block_uses_cap_when_limit_absent():
    payload = {"spend": {
        "enabled": True, "percent": 10,
        "used": {"amount_minor": 600, "currency": "EUR", "exponent": 2},
        "cap": {"money": {"amount_minor": 6000, "currency": "EUR", "exponent": 2}},
    }}
    spend = _parse_limits(payload)[0]
    assert spend.monthly_limit == 6000


def test_spend_block_uses_cap_when_limit_is_zeroed():
    # Regression: _money returns a tuple, so (0, "EUR") is truthy and an `or`
    # fallback would never consult cap, dropping the row entirely.
    payload = {"spend": {
        "enabled": True, "percent": 25,
        "used": {"amount_minor": 1500, "currency": "EUR", "exponent": 2},
        "limit": {"amount_minor": 0, "currency": "EUR", "exponent": 2},
        "cap": {"money": {"amount_minor": 6000, "currency": "EUR", "exponent": 2}},
    }}
    limits = _parse_limits(payload)
    assert len(limits) == 1
    assert limits[0].monthly_limit == 6000
    assert limits[0].used_credits == 1500


def test_spend_block_zero_limit_and_zero_cap_drops_row():
    payload = {"spend": {
        "enabled": True, "percent": 0,
        "used": {"amount_minor": 0, "currency": "EUR", "exponent": 2},
        "limit": {"amount_minor": 0, "currency": "EUR", "exponent": 2},
        "cap": {"money": {"amount_minor": 0, "currency": "EUR", "exponent": 2}},
    }}
    assert _parse_limits(payload) == []


def test_spend_block_derives_percent_when_absent():
    payload = {"spend": {
        "enabled": True,
        "used": {"amount_minor": 1500, "currency": "EUR", "exponent": 2},
        "limit": {"amount_minor": 6000, "currency": "EUR", "exponent": 2},
    }}
    assert _parse_limits(payload)[0].utilization == 25.0


def test_spend_block_rescales_zero_decimal_currency():
    # JPY reports exponent 0; format_credits assumes hundredths.
    payload = {"spend": {
        "enabled": True, "percent": 50,
        "used": {"amount_minor": 3000, "currency": "JPY", "exponent": 0},
        "limit": {"amount_minor": 6000, "currency": "JPY", "exponent": 0},
    }}
    spend = _parse_limits(payload)[0]
    assert format_credits(spend.monthly_limit, "JPY") == "6,000 JPY"
    assert format_credits(spend.used_credits, "JPY") == "3,000 JPY"


def test_spend_block_tolerates_non_dict():
    payload = {"five_hour": {"utilization": 30.0, "resets_at": None}, "spend": []}
    assert [li.window_key for li in _parse_limits(payload)] == ["five_hour"]


def test_legacy_null_utilization_is_derived():
    # Regression: the API began sending extra_usage.utilization = null while
    # still reporting a live limit, which silently dropped the spend row.
    payload = {"extra_usage": {
        "is_enabled": True, "currency": "EUR", "monthly_limit": 6000,
        "used_credits": 1500, "utilization": None,
    }}
    limits = _parse_limits(payload)
    assert len(limits) == 1
    assert limits[0].utilization == 25.0
    assert limits[0].used_credits == 1500


def test_first_of_next_month_rolls_year_on_december():
    dec = datetime(2026, 12, 15, tzinfo=UTC)
    iso = _first_of_next_month_utc(dec)
    parsed = datetime.fromisoformat(iso)
    assert (parsed.year, parsed.month, parsed.day) == (2027, 1, 1)


def test_first_of_next_month_mid_year():
    apr = datetime(2026, 4, 17, tzinfo=UTC)
    iso = _first_of_next_month_utc(apr)
    parsed = datetime.fromisoformat(iso)
    assert (parsed.year, parsed.month, parsed.day) == (2026, 5, 1)


def test_read_plan_name_enterprise(tmp_path, monkeypatch):
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({
        "claudeAiOauth": {
            "subscriptionType": "enterprise",
            "rateLimitTier": "default_claude_zero",
        }
    }))
    _pin_profile(monkeypatch, tmp_path)
    assert read_plan_name() == "Enterprise"


def test_limits_cache_roundtrip_preserves_spend_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("ctfl.providers.oauth._CACHE_DIR", tmp_path)
    creds_file = tmp_path / "instance" / ".credentials.json"
    creds_file.parent.mkdir(parents=True)
    original = [RateLimitInfo(
        name="Monthly spend",
        utilization=1.987,
        resets_at="2026-05-01T00:00:00+00:00",
        window_key="monthly_spend",
        used_credits=1987,
        monthly_limit=100000,
        currency="USD",
    )]
    _save_limits_cache(creds_file, original)
    loaded = _load_limits_cache(creds_file)
    assert loaded == original


def test_load_limits_cache_tolerates_legacy_schema(tmp_path, monkeypatch):
    monkeypatch.setattr("ctfl.providers.oauth._CACHE_DIR", tmp_path)
    creds_file = tmp_path / "instance" / ".credentials.json"
    creds_file.parent.mkdir(parents=True)
    # Cache file written by an older build lacks the spend fields.
    from ctfl.providers.oauth import _limits_cache_file
    legacy = [{
        "name": "Session",
        "utilization": 30.0,
        "resets_at": "2026-04-17T12:00:00+00:00",
        "window_key": "five_hour",
    }]
    cache_path = _limits_cache_file(creds_file)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(legacy))
    loaded = _load_limits_cache(creds_file)
    assert len(loaded) == 1
    assert loaded[0].name == "Session"
    assert loaded[0].used_credits is None


def test_format_credits_round_dollars():
    assert format_credits(100000, "USD") == "$1,000"


def test_format_credits_cents():
    assert format_credits(1987, "USD") == "$19.87"


def test_format_credits_none():
    assert format_credits(None) == ""


def test_format_credits_non_usd_appends_iso_code():
    assert format_credits(123456, "EUR") == "1,234.56 EUR"


def test_format_credits_non_usd_round():
    assert format_credits(100000, "GBP") == "1,000 GBP"
