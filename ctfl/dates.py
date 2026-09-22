"""Date formatting and the popup's reporting periods.

The UI is English-only, so day and month names are English whatever LC_TIME
says; the conventions (clock, day/month order, first day of the week) still
follow LC_TIME through QLocale.system().
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, QDateTime, QLocale, QTime

PERIODS = ("today", "week", "month")
PERIOD_LABELS = {"today": "Today", "week": "This week", "month": "This month"}

_NAMES = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)


def _conventions() -> QLocale:
    return QLocale.system()


def _month_first() -> bool:
    fmt = _conventions().dateFormat(QLocale.FormatType.ShortFormat)
    return fmt.find("M") < fmt.find("d")


def _time_pattern() -> str:
    return _conventions().timeFormat(QLocale.FormatType.ShortFormat)


def _qdatetime(dt: datetime) -> QDateTime:
    return QDateTime(
        QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute, dt.second)
    )


def day_label(d: date) -> str:
    """'22 September', or 'September 22' where the locale puts the month first."""
    return _NAMES.toString(QDate(d.year, d.month, d.day), "MMMM d" if _month_first() else "d MMMM")


def short_date(d: date) -> str:
    return _NAMES.toString(QDate(d.year, d.month, d.day), "MMM d" if _month_first() else "d MMM")


def time_hm(dt: datetime) -> str:
    return _NAMES.toString(_qdatetime(dt), _time_pattern())


def weekday_time(dt: datetime) -> str:
    """'Fri 21:00'."""
    return _NAMES.toString(_qdatetime(dt), f"ddd {_time_pattern()}")


def week_start(today: date) -> date:
    first = _conventions().firstDayOfWeek().value  # 1 = Monday .. 7 = Sunday
    return today - timedelta(days=(today.isoweekday() - first) % 7)


def period_start(period: str, today: date) -> date:
    if period == "week":
        return week_start(today)
    if period == "month":
        return today.replace(day=1)
    return today


def days_to_fetch(today: date) -> int:
    """Days, today included, that cover every period the popup can show."""
    earliest = min(period_start(p, today) for p in PERIODS)
    return (today - earliest).days + 1
