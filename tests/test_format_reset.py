from datetime import UTC, datetime, timedelta

from ctfl.providers import format_reset as _format_reset


def test_none():
    assert _format_reset(None) == ""


def test_empty_string():
    assert _format_reset("") == ""


def test_past_time():
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert _format_reset(past) == "Resets soon"


def test_under_one_minute():
    future = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in <1m"


def test_minutes():
    future = (datetime.now(UTC) + timedelta(minutes=45, seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in 45m"


def test_hours():
    future = (datetime.now(UTC) + timedelta(hours=2, minutes=30, seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in 2h30m"


def test_days():
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    result = _format_reset(future)
    assert result.startswith("Resets ")


def test_invalid_format():
    assert _format_reset("not-a-date") == ""
