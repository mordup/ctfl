"""Dates use English names, with the clock, day order and week start of LC_TIME."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from PyQt6.QtCore import QLocale

from ctfl import dates

_TUESDAY = date(2026, 9, 22)


@pytest.fixture(params=["fr_FR", "en_US"])
def lc_time(request, monkeypatch):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale(request.param))
    return request.param


def _pick(lc_time: str, fr: str, us: str) -> str:
    return fr if lc_time == "fr_FR" else us


def test_day_label(lc_time):
    assert dates.day_label(_TUESDAY) == _pick(lc_time, "22 September", "September 22")


def test_short_date(lc_time):
    assert dates.short_date(date(2026, 10, 1)) == _pick(lc_time, "1 Oct", "Oct 1")


def test_weekday_time(lc_time):
    at = datetime(2026, 9, 25, 21, 0)
    assert dates.weekday_time(at) == _pick(lc_time, "Fri 21:00", "Fri 9:00\u202fPM")


def test_time_hm(lc_time):
    assert dates.time_hm(datetime(2026, 9, 25, 9, 5)) == _pick(lc_time, "09:05", "9:05\u202fAM")


def test_week_starts_on_the_locale_first_day(lc_time):
    assert dates.week_start(_TUESDAY) == _pick(lc_time, date(2026, 9, 21), date(2026, 9, 20))


def test_week_start_on_its_own_first_day_is_that_day(lc_time):
    first = date(2026, 9, 21) if lc_time == "fr_FR" else date(2026, 9, 20)
    assert dates.week_start(first) == first


@pytest.mark.parametrize("period, offset, expected", [
    ("today", 0, (_TUESDAY, _TUESDAY)),
    ("today", -1, (date(2026, 9, 21), date(2026, 9, 21))),
    ("week", 0, (date(2026, 9, 21), date(2026, 9, 27))),
    ("week", -1, (date(2026, 9, 14), date(2026, 9, 20))),
    ("month", 0, (date(2026, 9, 1), date(2026, 9, 30))),
    ("month", -1, (date(2026, 8, 1), date(2026, 8, 31))),
    ("month", -9, (date(2025, 12, 1), date(2025, 12, 31))),
])
def test_period_range(monkeypatch, period, offset, expected):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    assert dates.period_range(period, _TUESDAY, offset) == expected


@pytest.mark.parametrize("period, offset, expected", [
    ("today", 0, "Today"),
    ("today", -1, "Yesterday"),
    ("today", -2, "Sun 20 Sep"),
    ("week", 0, "This week"),
    ("week", -1, "Last week"),
    ("week", -2, "7 Sep \u2013 13 Sep"),
    ("month", 0, "September"),
    ("month", -9, "December 2025"),
])
def test_period_label(monkeypatch, period, offset, expected):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    assert dates.period_label(period, _TUESDAY, offset) == expected


@pytest.mark.parametrize("period, offset, expected", [
    ("month", 0, True),
    ("month", -1, False),             # August is the oldest month kept
    ("week", -7, True),               # 27 Jul - 2 Aug still reaches into August
    ("week", -8, False),
    ("today", -51, True),             # 2 August
    ("today", -52, False),
])
def test_navigation_stops_at_the_previous_month(monkeypatch, period, offset, expected):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    assert dates.has_earlier_period(period, _TUESDAY, offset) is expected


@pytest.mark.parametrize("today, days", [
    (_TUESDAY, 53),                   # 1 August to 22 September
    (date(2026, 3, 1), 29),           # 1 February to 1 March
    (date(2026, 8, 31), 62),
])
def test_days_to_fetch_reaches_the_previous_month(today, days):
    assert dates.days_to_fetch(today) == days
