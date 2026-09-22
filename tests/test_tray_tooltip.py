"""Layout of the tray tooltip: header, today's line, limit lines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ctfl.dates import time_hm
from ctfl.providers import DailyUsage, RateLimitInfo, UsageData, format_reset
from ctfl.tray import TrayIcon


class _Tray:
    _update_tooltip = TrayIcon._update_tooltip
    _tooltip_today_line = TrayIcon._tooltip_today_line
    _tooltip_limits_lines = TrayIcon._tooltip_limits_lines

    def __init__(self, **config) -> None:
        defaults = dict(tooltip_sync=True, tooltip_today=True, tooltip_limits=True, profile="auto")
        self._config = SimpleNamespace(**{**defaults, **config})
        self.tooltip = ""

    def setToolTip(self, text: str) -> None:
        self.tooltip = text


@pytest.fixture
def plan(monkeypatch):
    # The plan name comes from the credentials file and the instance list from
    # ~/.claude*; neither exists in a test run.
    monkeypatch.setattr("ctfl.providers.instance.discover_instances", lambda: [])
    name = {"value": "Max 5x"}
    monkeypatch.setattr("ctfl.providers.oauth.read_plan_name", lambda config: name["value"])
    return name


def _today() -> UsageData:
    return UsageData(daily=[DailyUsage(date=datetime.now().strftime("%Y-%m-%d"),
                                       input_tokens=48_100_000, cost_usd=31.08)])


def test_sync_time_sits_in_the_header(plan):
    tray = _Tray()
    tray._update_tooltip(_today())
    lines = tray.tooltip.splitlines()
    assert lines[1].startswith("Max 5x · synced ")
    assert lines[2] == "Today: 48.1M tokens · $31.08"


def test_sync_time_alone_starts_the_header(plan):
    plan["value"] = None
    tray = _Tray()
    tray._update_tooltip(_today())
    assert tray.tooltip.splitlines()[1] == f"Synced {time_hm(datetime.now())}"


def test_no_sync_time_when_disabled(plan):
    tray = _Tray(tooltip_sync=False)
    tray._update_tooltip(_today())
    assert tray.tooltip.splitlines()[1:3] == ["Max 5x", "Today: 48.1M tokens · $31.08"]


def test_weekly_line_names_its_window():
    reset = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    data = UsageData(limits=[
        RateLimitInfo("Weekly", 11.0, reset, "seven_day"),
        RateLimitInfo("Weekly (Fable)", 12.0, reset, "seven_day_fable"),
    ])
    (line,) = TrayIcon._tooltip_limits_lines(None, data, format_reset)
    assert line.startswith("Weekly: 11% · Fable 12% | resets ")
