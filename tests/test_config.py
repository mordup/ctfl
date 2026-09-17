"""A days_to_show above the transcript retention was allowed by earlier versions."""

from __future__ import annotations

from ctfl.config import Config
from ctfl.constants import MAX_DAYS_TO_SHOW


def test_days_to_show_clamps_stored_value_above_max():
    config = Config()
    config.days_to_show = 90
    assert config.days_to_show == MAX_DAYS_TO_SHOW


def test_days_to_show_keeps_value_within_max():
    config = Config()
    config.days_to_show = 14
    assert config.days_to_show == 14


def test_days_to_show_clamps_stored_value_below_one():
    config = Config()
    config.days_to_show = 0
    assert config.days_to_show == 1
