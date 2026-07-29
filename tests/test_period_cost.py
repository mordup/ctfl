"""The popup's "Period total" cost must cover the whole period or be omitted.

Days sourced from stats-cache carry no per-model breakdown and so no cost, and
lastComputedDate is normally yesterday — so summing only the priced days
produced a figure labelled as a period total that was, in practice, always just
today's cost repeated from the line above.
"""

from ctfl.popup import _period_cost
from ctfl.providers import DailyUsage


def _day(date: str, cost: float | None) -> DailyUsage:
    return DailyUsage(date=date, cost_usd=cost)


def test_all_days_priced_sums():
    days = [_day("2026-07-29", 10.0), _day("2026-07-28", 5.5)]
    assert _period_cost(days) == 15.5


def test_single_priced_day():
    assert _period_cost([_day("2026-07-29", 10.0)]) == 10.0


def test_any_unpriced_day_suppresses_total():
    # Regression: this used to return 10.0 and render as a period total.
    days = [_day("2026-07-29", 10.0), _day("2026-07-28", None)]
    assert _period_cost(days) is None


def test_all_unpriced_suppresses_total():
    assert _period_cost([_day("2026-07-29", None), _day("2026-07-28", None)]) is None


def test_empty_period():
    assert _period_cost([]) is None


def test_zero_cost_days_are_not_treated_as_missing():
    days = [_day("2026-07-29", 0.0), _day("2026-07-28", 0.0)]
    assert _period_cost(days) == 0.0
