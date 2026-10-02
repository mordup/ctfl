"""Totalling per-day model and project data over a period."""

from __future__ import annotations

import pytest

from ctfl.providers import ModelTokens, ProjectUsage, UsageData, models_between, projects_between


def _model(name: str, tokens: int, cost: float | None = None, breakdown: bool = True) -> ModelTokens:
    return ModelTokens(model=name, input_tokens=tokens, cost_usd=cost, breakdown_available=breakdown)


def test_models_between_sums_days_inside_the_range_only():
    data = UsageData(models_by_day={
        "2026-09-20": [_model("opus", 1_000, 1.0)],
        "2026-09-21": [_model("opus", 200, 0.5), _model("sonnet", 5_000, 2.0)],
        "2026-09-22": [_model("opus", 300, 0.25)],
        "2026-09-23": [_model("opus", 7_000, 9.0)],
    })
    models = models_between(data, "2026-09-21", "2026-09-22")
    assert [(m.model, m.total) for m in models] == [("sonnet", 5_000), ("opus", 500)]
    assert models[1].cost_usd == pytest.approx(0.75)


def test_model_with_an_unpriced_day_has_no_cost():
    data = UsageData(models_by_day={
        "2026-09-21": [_model("opus", 200, None)],
        "2026-09-22": [_model("opus", 300, 0.25)],
    })
    assert models_between(data, "2026-09-21", "2026-09-22")[0].cost_usd is None


def test_breakdown_is_unavailable_when_any_day_lacks_it():
    data = UsageData(models_by_day={
        "2026-09-21": [_model("opus", 200, breakdown=False)],
        "2026-09-22": [_model("opus", 300)],
    })
    assert not models_between(data, "2026-09-21", "2026-09-22")[0].breakdown_available


def test_models_without_tokens_are_dropped():
    data = UsageData(models_by_day={"2026-09-22": [_model("<synthetic>", 0, 0.0)]})
    assert models_between(data, "2026-09-22", "2026-09-22") == []


def test_projects_between_sums_days_inside_the_range_only():
    data = UsageData(projects_by_day={
        "2026-09-20": [ProjectUsage("Ctfl", "-p-ctfl", total_tokens=9_000, message_count=9)],
        "2026-09-21": [ProjectUsage("Ctfl", "-p-ctfl", total_tokens=100, message_count=1),
                       ProjectUsage("Docs", "-p-docs", total_tokens=400, message_count=2)],
        "2026-09-22": [ProjectUsage("Ctfl", "-p-ctfl", total_tokens=200, message_count=3)],
        "2026-09-23": [ProjectUsage("Docs", "-p-docs", total_tokens=9_000, message_count=9)],
    })
    projects = projects_between(data, "2026-09-21", "2026-09-22")
    assert [(p.name, p.total_tokens, p.message_count) for p in projects] == [
        ("Docs", 400, 2), ("Ctfl", 300, 4),
    ]
