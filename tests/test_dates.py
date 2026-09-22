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


def test_month_name_is_english(lc_time):
    assert dates.month_name(9) == "September"


def test_week_starts_on_the_locale_first_day(lc_time):
    assert dates.week_start(_TUESDAY) == _pick(lc_time, date(2026, 9, 21), date(2026, 9, 20))


def test_week_start_on_its_own_first_day_is_that_day(lc_time):
    first = date(2026, 9, 21) if lc_time == "fr_FR" else date(2026, 9, 20)
    assert dates.week_start(first) == first


@pytest.mark.parametrize("period, expected", [
    ("today", _TUESDAY),
    ("month", date(2026, 9, 1)),
    ("week", date(2026, 9, 21)),
])
def test_period_start(monkeypatch, period, expected):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    assert dates.period_start(period, _TUESDAY) == expected


@pytest.mark.parametrize("today, days", [
    (_TUESDAY, 22),               # month reaches further back than the week
    (date(2026, 10, 2), 5),       # week started in September, month on the 1st
    (date(2026, 9, 1), 2),        # Tuesday the 1st: week began Monday 31 Aug
])
def test_days_to_fetch_covers_every_period(monkeypatch, today, days):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    assert dates.days_to_fetch(today) == days
