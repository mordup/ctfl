"""Tests for the structured `limits` array (per-model weekly buckets)."""

from __future__ import annotations

from ctfl.providers.oauth import _parse_limits
from ctfl.providers.prediction import _window_hours

# Trimmed from a live Max payload. Note that every top-level seven_day_* key
# is null: once the array is present it is the only source of weekly buckets.
_PAYLOAD_WITH_ARRAY = {
    "five_hour": {"utilization": 18.0, "resets_at": "2026-08-26T12:30:00+00:00"},
    "seven_day": {"utilization": 25.0, "resets_at": "2026-08-28T19:00:00+00:00"},
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "seven_day_omelette": None,
    "nimbus_quill": {"utilization": 0.0, "resets_at": None},
    "limits": [
        {
            "kind": "session", "group": "session", "percent": 18,
            "resets_at": "2026-08-26T12:30:00+00:00", "scope": None,
        },
        {
            "kind": "weekly_all", "group": "weekly", "percent": 25,
            "resets_at": "2026-08-28T19:00:00+00:00", "scope": None,
        },
        {
            "kind": "weekly_scoped", "group": "weekly", "percent": 26,
            "resets_at": "2026-08-28T19:00:00+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
        },
    ],
    "extra_usage": {"is_enabled": False},
    "spend": {"enabled": False},
}


def test_scoped_model_bucket_is_emitted():
    by_key = {li.window_key: li for li in _parse_limits(_PAYLOAD_WITH_ARRAY)}
    assert "seven_day_fable" in by_key
    fable = by_key["seven_day_fable"]
    assert fable.name == "Weekly (Fable)"
    assert fable.utilization == 26.0
    assert fable.resets_at == "2026-08-28T19:00:00+00:00"


def test_array_does_not_duplicate_session_and_weekly():
    keys = [li.window_key for li in _parse_limits(_PAYLOAD_WITH_ARRAY)]
    assert keys == ["five_hour", "seven_day", "seven_day_fable"]


def test_unused_codename_keys_are_not_mistaken_for_buckets():
    # nimbus_quill sits at the top level next to the real keys; it must not
    # leak into the limit list just because it happens to carry a utilization.
    keys = [li.window_key for li in _parse_limits(_PAYLOAD_WITH_ARRAY)]
    assert not any("nimbus" in k for k in keys)


def test_falls_back_to_legacy_keys_when_array_absent():
    payload = dict(_PAYLOAD_WITH_ARRAY)
    del payload["limits"]
    payload["seven_day_sonnet"] = {
        "utilization": 4.0, "resets_at": "2026-08-28T19:00:00+00:00",
    }
    by_key = {li.window_key: li for li in _parse_limits(payload)}
    assert by_key["seven_day_sonnet"].name == "Weekly (Sonnet)"
    assert by_key["five_hour"].utilization == 18.0


def test_claude_design_scope_keeps_its_legacy_window_key():
    # The popup and tray special-case seven_day_omelette to give Claude Design
    # its own section; a scoped row must map back onto that key.
    payload = {"limits": [{
        "kind": "weekly_scoped", "percent": 3,
        "resets_at": "2026-08-28T19:00:00+00:00",
        "scope": {"surface": {"display_name": "Claude Design"}},
    }]}
    (info,) = _parse_limits(payload)
    assert info.window_key == "seven_day_omelette"
    assert info.name == "Weekly (Claude Design)"


def test_multiword_scope_slugifies():
    payload = {"limits": [{
        "kind": "weekly_scoped", "percent": 5, "resets_at": None,
        "scope": {"model": {"display_name": "Fable 5 Mini"}},
    }]}
    (info,) = _parse_limits(payload)
    assert info.window_key == "seven_day_fable_5_mini"
    assert info.name == "Weekly (Fable 5 Mini)"


def test_scoped_row_without_a_usable_scope_is_dropped():
    payload = {"limits": [{"kind": "weekly_scoped", "percent": 7, "scope": None}]}
    assert _parse_limits(payload) == []


def test_malformed_array_falls_back_to_keys():
    payload = dict(_PAYLOAD_WITH_ARRAY, limits="nonsense")
    keys = [li.window_key for li in _parse_limits(payload)]
    assert keys == ["five_hour", "seven_day"]


def test_percent_is_clamped_and_null_percent_skipped():
    payload = {"limits": [
        {"kind": "weekly_all", "percent": 140, "resets_at": None},
        {"kind": "session", "percent": None, "resets_at": None},
    ]}
    (info,) = _parse_limits(payload)
    assert info.window_key == "seven_day"
    assert info.utilization == 100.0


def test_derived_weekly_keys_get_the_weekly_window():
    assert _window_hours("seven_day_fable") == 168.0
    assert _window_hours("five_hour") == 5
    assert _window_hours("monthly_spend") is None


def test_scoped_session_bucket_is_not_minted_as_weekly():
    # A seven_day_* key drives both the UI grouping and prediction's 168h
    # window, so minting one for a *session*-group bucket would show a 5-hour
    # limit as weekly and predict its burn rate over the wrong window.
    payload = {"limits": [{
        "kind": "session_scoped", "group": "session", "percent": 40,
        "resets_at": "2026-08-26T15:30:00+00:00",
        "scope": {"model": {"id": None, "display_name": "Fable"}},
    }]}
    assert _parse_limits(payload) == []


def test_unknown_weekly_kind_is_still_accepted():
    # Forward compatibility: the group field is the authority on the window,
    # so a renamed weekly kind keeps working.
    payload = {"limits": [{
        "kind": "weekly_scoped_v2", "group": "weekly", "percent": 12,
        "resets_at": "2026-08-28T19:00:00+00:00",
        "scope": {"model": {"display_name": "Fable"}},
    }]}
    (info,) = _parse_limits(payload)
    assert info.window_key == "seven_day_fable"
    assert info.utilization == 12.0


def test_scoped_row_of_unknown_window_is_dropped():
    # No kind we recognise and no group saying weekly: there is no basis for
    # choosing a window, and guessing one shows a wrong prediction.
    payload = {"limits": [{
        "kind": "mystery", "percent": 5, "resets_at": None,
        "scope": {"model": {"display_name": "Fable"}},
    }]}
    assert _parse_limits(payload) == []


def test_bad_legacy_utilization_skips_only_that_bucket():
    # The array parser already tolerates a non-numeric percent per entry. The
    # legacy path coerced with a bare float(), so one malformed key raised out
    # of _parse_limits and every rate-limit row disappeared.
    payload = {
        "five_hour": {"utilization": "12%", "resets_at": None},
        "seven_day": {"utilization": 25.0, "resets_at": None},
    }
    keys = [li.window_key for li in _parse_limits(payload)]
    assert keys == ["seven_day"]


def test_scope_display_name_is_stripped_of_markup():
    # The name reaches an auto-rich-text QLabel and the tray tooltip, both of
    # which interpret markup. Before scoped buckets it was always a _KEY_LABELS
    # constant; now it comes straight from the API.
    payload = {"limits": [{
        "kind": "weekly_scoped", "group": "weekly", "percent": 5,
        "resets_at": None,
        "scope": {"model": {"display_name": "<b>Fab</b>le"}},
    }]}
    (info,) = _parse_limits(payload)
    assert "<" not in info.name and ">" not in info.name


def test_scope_display_name_is_length_capped():
    payload = {"limits": [{
        "kind": "weekly_scoped", "group": "weekly", "percent": 5,
        "resets_at": None,
        "scope": {"model": {"display_name": "M" * 500}},
    }]}
    (info,) = _parse_limits(payload)
    assert len(info.name) < 80


def test_scope_display_name_drops_newlines():
    # A newline would break the tray tooltip's line structure.
    payload = {"limits": [{
        "kind": "weekly_scoped", "group": "weekly", "percent": 5,
        "resets_at": None,
        "scope": {"model": {"display_name": "Fable\nSession: 100%"}},
    }]}
    (info,) = _parse_limits(payload)
    assert "\n" not in info.name
