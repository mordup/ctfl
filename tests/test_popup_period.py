"""The period dropdown drives the total and every tab."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtWidgets import QApplication, QLabel

from ctfl import dates
from ctfl.config import Config
from ctfl.popup import PopupWidget
from ctfl.providers import DailyUsage, ModelTokens, ProjectUsage, UsageData

_TODAY = date.today()


def _iso(days_ago: int) -> str:
    return (_TODAY - timedelta(days=days_ago)).isoformat()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def popup(qapp, monkeypatch):
    monkeypatch.setattr(dates, "_conventions", lambda: QLocale("fr_FR"))
    config = Config()
    config.period = "today"
    w = PopupWidget(config)
    yield w
    w.close()


def _data(yesterday_cost: float | None = 1.0) -> UsageData:
    return UsageData(
        daily=[
            DailyUsage(date=_iso(0), input_tokens=2_000_000, cost_usd=8.0),
            DailyUsage(date=_iso(1), input_tokens=1_000_000, cost_usd=yesterday_cost),
        ],
        models_by_day={
            _iso(0): [ModelTokens(model="claude-opus-5-5", input_tokens=2_000_000, cost_usd=8.0)],
            _iso(1): [ModelTokens(model="claude-opus-5", input_tokens=1_000_000, cost_usd=yesterday_cost)],
        },
        projects_by_day={
            _iso(0): [ProjectUsage("Ctfl", "-p-ctfl", total_tokens=2_000_000)],
            _iso(1): [ProjectUsage("Docs", "-p-docs", total_tokens=1_000_000)],
        },
    )


def _texts(widget) -> list[str]:
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


def _select(popup: PopupWidget, period: str) -> None:
    popup._period_combo.setCurrentIndex(popup._period_combo.findData(period))


def test_tabs_are_usage_model_project(popup):
    assert [popup._tabs.tabText(i) for i in range(popup._tabs.count())] == [
        "Usage", "By Model", "By Project",
    ]


def test_dropdown_offers_the_three_periods(popup):
    labels = [popup._period_combo.itemText(i) for i in range(popup._period_combo.count())]
    assert labels == ["Today", "This week", "This month"]


def test_dropdown_opens_on_the_saved_period(qapp):
    config = Config()
    config.period = "month"
    assert PopupWidget(config)._period_combo.currentData() == "month"


def test_today_shows_only_today(popup):
    popup.update_data(_data())
    assert popup._period_total_label.text() == "2.0M tokens · $8.00"
    assert "Opus-5-5" in _texts(popup._model_chart)
    assert "Opus-5" not in _texts(popup._model_chart)
    assert "Docs" not in _texts(popup._project_chart)


def test_longer_period_includes_earlier_days(popup):
    popup.update_data(_data())
    _select(popup, "month" if _TODAY.day > 1 else "week")
    assert popup._period_total_label.text() == "3.0M tokens · $9.00"
    assert {"Opus-5-5", "Opus-5"} <= set(_texts(popup._model_chart))
    assert {"Ctfl", "Docs"} <= set(_texts(popup._project_chart))


def test_changing_period_is_remembered(popup):
    _select(popup, "month")
    assert Config().period == "month"


def test_period_total_withheld_when_a_day_is_unpriced(popup):
    popup.update_data(_data(yesterday_cost=None))
    _select(popup, "month" if _TODAY.day > 1 else "week")
    assert popup._period_total_label.text() == "3.0M tokens"


def test_model_rows_carry_their_cost(popup):
    popup.update_data(_data())
    assert "2.0M tokens · $8.00" in _texts(popup._model_chart)


def test_usage_rows_are_labelled_in_english(popup):
    popup.update_data(_data())
    assert dates.day_label(_TODAY) in _texts(popup._daily_chart)
    assert dates.month_name(_TODAY.month) in dates.day_label(_TODAY)


def test_loading_is_shown_beside_the_dropdown(popup):
    popup.update_data(_data())
    popup.show_loading()
    assert popup._period_total_label.text() == "Loading..."


def test_error_replaces_the_period(popup):
    popup.update_data(_data())
    popup.update_data(UsageData(error="<b>boom</b>"))
    assert popup._period_total_label.text() == "Error: <b>boom</b>"
    assert popup._period_total_label.textFormat() == Qt.TextFormat.PlainText
    assert _texts(popup._model_chart) == []
