"""Merging provider results in the fetch worker."""

from __future__ import annotations

from ctfl.providers import DailyUsage, ModelTokens, ProjectUsage, RateLimitInfo, UsageData
from ctfl.tray import _FetchWorker


class _Provider:
    def __init__(self, result: UsageData) -> None:
        self.result = result
        self.days: list[int] = []

    def fetch(self, days: int) -> UsageData:
        self.days.append(days)
        return self.result


def _run(providers, days: int = 22) -> UsageData:
    out: list[UsageData] = []
    worker = _FetchWorker(providers, days)
    worker.finished.connect(out.append)
    worker.run()
    return out[0]


def _usage(model: str) -> UsageData:
    return UsageData(
        daily=[DailyUsage(date="2026-09-22", input_tokens=1)],
        models_by_day={"2026-09-22": [ModelTokens(model=model, input_tokens=1)]},
        projects_by_day={"2026-09-22": [ProjectUsage(model, model, total_tokens=1)]},
    )


def test_per_day_views_come_from_the_same_source_as_daily():
    local, api = _Provider(_usage("local")), _Provider(_usage("api"))
    merged = _run([local, api])
    assert merged.daily is local.result.daily
    assert merged.models_by_day is local.result.models_by_day
    assert merged.projects_by_day is local.result.projects_by_day


def test_limits_are_collected_from_every_provider():
    limits = UsageData(limits=[RateLimitInfo("Session", 5.0, None, "five_hour")])
    merged = _run([_Provider(_usage("local")), _Provider(limits)])
    assert [info.name for info in merged.limits] == ["Session"]


def test_every_provider_is_asked_for_the_same_window():
    a, b = _Provider(_usage("a")), _Provider(UsageData())
    _run([a, b], days=31)
    assert a.days == b.days == [31]
