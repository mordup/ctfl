"""Date formatting and the popup's reporting periods.

The UI is English-only, so day and month names are English whatever LC_TIME
says; the conventions (clock, day/month order, first day of the week) still
follow LC_TIME through QLocale.system().
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, QDateTime, QLocale, QTime

from .providers.history import history_start

PERIODS = ("today", "week", "month")
# The keys are saved in the config; renaming one would reset that choice.
PERIOD_LABELS = {"today": "Day", "week": "Week", "month": "Month"}

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


def period_range(period: str, today: date, offset: int = 0) -> tuple[date, date]:
    """First and last day of the period `offset` periods away from today's."""
    if period == "week":
        start = week_start(today) + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    if period == "month":
        months = today.year * 12 + today.month - 1 + offset
        start = date(months // 12, months % 12 + 1, 1)
        following = date((months + 1) // 12, (months + 1) % 12 + 1, 1)
        return start, following - timedelta(days=1)
    day = today + timedelta(days=offset)
    return day, day


def period_label(period: str, today: date, offset: int) -> str:
    """'Yesterday', 'Last week', 'September'; dates beyond those."""
    start, end = period_range(period, today, offset)
    if period == "week":
        named = {0: "This week", -1: "Last week"}
        return named.get(offset) or f"{short_date(start)} \u2013 {short_date(end)}"
    if period == "month":
        fmt = "MMMM" if start.year == today.year else "MMMM yyyy"
        return _NAMES.toString(QDate(start.year, start.month, 1), fmt)
    named = {0: "Today", -1: "Yesterday"}
    return named.get(offset) or _NAMES.toString(QDate(start.year, start.month, start.day), "ddd ") + short_date(start)


def has_earlier_period(period: str, today: date, offset: int) -> bool:
    """Whether the period before this one still holds kept history."""
    return period_range(period, today, offset - 1)[1] >= history_start(today)


def days_to_fetch(today: date) -> int:
    """Days, today included, that cover every period the popup can show."""
    return (today - history_start(today)).days + 1
