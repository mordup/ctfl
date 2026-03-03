from datetime import datetime, timedelta, timezone

from ctfl.popup import _format_reset


def test_none():
    assert _format_reset(None) == ""


def test_empty_string():
    assert _format_reset("") == ""


def test_past_time():
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert _format_reset(past) == "Resets soon"


def test_under_one_minute():
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in <1 min"


def test_minutes():
    future = (datetime.now(timezone.utc) + timedelta(minutes=45, seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in 45 min"


def test_hours():
    future = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=30, seconds=30)).isoformat()
    assert _format_reset(future) == "Resets in 2 hr 30 min"


def test_days():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    result = _format_reset(future)
    assert result.startswith("Resets ")


def test_invalid_format():
    assert _format_reset("not-a-date") == ""
