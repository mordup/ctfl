"""Spend rows for usage credits that are configured but currently inactive."""

from __future__ import annotations

from ctfl.providers.oauth import _parse_limits

# Max account with the credits toggle on, monthly cap set, balance run down to
# zero. claude.ai still renders the bar; enabled is False on both blocks.
_EXHAUSTED = {
    "extra_usage": {
        "is_enabled": False, "monthly_limit": 6000, "used_credits": 572.0,
        "utilization": 9.533333333333333, "currency": "EUR",
        "disabled_reason": "out_of_credits", "user_disabled": False,
        "spend_limit_reached": False, "credits_ever_enabled": True,
    },
    "spend": {
        "used": {"amount_minor": 572, "currency": "EUR", "exponent": 2},
        "limit": {"amount_minor": 6000, "currency": "EUR", "exponent": 2},
        "percent": 10, "enabled": False, "disabled_reason": "out_of_credits",
        "cap": {"money": {"amount_minor": 6000, "currency": "EUR", "exponent": 2}},
    },
}


def test_exhausted_credits_still_emit_a_spend_row():
    (info,) = _parse_limits(_EXHAUSTED)
    assert info.window_key == "monthly_spend"
    assert info.utilization == 10.0
    assert info.used_credits == 572
    assert info.monthly_limit == 6000
    assert info.currency == "EUR"


def test_user_disabled_credits_emit_nothing():
    payload = {
        "extra_usage": {**_EXHAUSTED["extra_usage"], "user_disabled": True},
        "spend": _EXHAUSTED["spend"],
    }
    assert _parse_limits(payload) == []


def test_never_enabled_credits_emit_nothing():
    # Same out_of_credits reason, but the user has never switched credits on:
    # a zero balance is their steady state, not a limit they are up against.
    payload = {
        "extra_usage": {**_EXHAUSTED["extra_usage"], "credits_ever_enabled": False},
        "spend": _EXHAUSTED["spend"],
    }
    assert _parse_limits(payload) == []


def test_spend_limit_reached_also_counts_as_configured():
    payload = {
        "extra_usage": {
            **_EXHAUSTED["extra_usage"], "disabled_reason": "spend_limit_reached",
        },
        "spend": {**_EXHAUSTED["spend"], "disabled_reason": "spend_limit_reached"},
    }
    (info,) = _parse_limits(payload)
    assert info.utilization == 10.0


def test_unrecognised_disabled_reason_stays_hidden():
    payload = {
        "extra_usage": {**_EXHAUSTED["extra_usage"], "disabled_reason": "suspended"},
        "spend": {**_EXHAUSTED["spend"], "disabled_reason": "suspended"},
    }
    assert _parse_limits(payload) == []


def test_exhausted_falls_back_to_extra_usage_when_spend_block_malformed():
    payload = {"extra_usage": _EXHAUSTED["extra_usage"], "spend": {"enabled": False}}
    (info,) = _parse_limits(payload)
    assert info.used_credits == 572
    assert info.monthly_limit == 6000


def test_enabled_credits_are_unaffected_by_the_gate():
    payload = {
        "extra_usage": {**_EXHAUSTED["extra_usage"], "is_enabled": True},
        "spend": {**_EXHAUSTED["spend"], "enabled": True},
    }
    (info,) = _parse_limits(payload)
    assert info.utilization == 10.0
