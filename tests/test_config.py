"""The popup's reporting period is persisted and validated."""

from __future__ import annotations

import pytest

from ctfl.config import Config


def test_period_defaults_to_the_week():
    config = Config()
    config._s.remove("period")
    assert config.period == "week"


@pytest.mark.parametrize("period", ["today", "week", "month"])
def test_period_round_trips(period):
    config = Config()
    config.period = period
    assert Config().period == period


def test_unknown_stored_period_falls_back_to_the_week():
    config = Config()
    config.period = "fortnight"
    assert config.period == "week"
