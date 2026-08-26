"""Regression tests for popup sizing across a refresh.

Rebuilt rows are hidden until their posted show events are delivered, and
QLayout::sizeHint() ignores hidden widgets. Measuring the tab content before
those events land collapses the tab area to roughly the tab bar's height,
which is what made the popup shrink on refresh while it was already open.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from ctfl.config import Config
from ctfl.popup import PopupWidget
from ctfl.providers import ModelTokens, RateLimitInfo, UsageData

# Enough rows that a correctly-measured tab is clearly taller than the tab bar.
_MODELS = [
    ModelTokens(model=f"claude-opus-{i}", input_tokens=1000 * (i + 1),
                output_tokens=500, cache_read_tokens=2000,
                cache_creation_tokens=100)
    for i in range(6)
]

_LIMITS = [
    RateLimitInfo("Session", 18.0, "2026-08-26T12:30:00+00:00", "five_hour"),
    RateLimitInfo("Weekly", 25.0, "2026-08-28T19:00:00+00:00", "seven_day"),
    RateLimitInfo("Weekly (Fable)", 26.0, "2026-08-28T19:00:00+00:00",
                  "seven_day_fable"),
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _data() -> UsageData:
    return UsageData(by_model=list(_MODELS), limits=list(_LIMITS))


@pytest.fixture
def popup(qapp):
    w = PopupWidget(Config())
    w.update_data(_data())
    w.show()
    w._tabs.setCurrentIndex(1)  # By Model, the tab in the bug report
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_tab_area_survives_a_refresh(popup, qapp):
    before = popup._tabs.height()
    assert before > 100, "fixture did not produce a populated tab to begin with"

    # The tray's refresh cycle: clear, then deliver new data while visible.
    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_data())
    qapp.processEvents()

    assert popup._tabs.height() == before


def test_tab_area_does_not_collapse_to_the_tab_bar(popup, qapp):
    # The failure mode was a tab area pinned to tab-bar height plus padding,
    # which is what a margins-only sizeHint produces.
    tab_bar_h = popup._tabs.tabBar().sizeHint().height()

    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_data())
    qapp.processEvents()

    assert popup._tabs.height() > tab_bar_h * 2


def test_repeated_refreshes_stay_stable(popup, qapp):
    # Stability alone is not enough: a collapsed tab area is also stable.
    # Pin to the height the popup opened at.
    before = popup._tabs.height()
    heights = []
    for _ in range(4):
        popup.show_loading()
        qapp.processEvents()
        popup.update_data(_data())
        qapp.processEvents()
        heights.append(popup._tabs.height())

    assert heights == [before] * 4, f"tab height drifted: {before} -> {heights}"


def test_content_hint_counts_rebuilt_rows(popup, qapp):
    # Direct check on the mechanism the fix relies on: once update_data has
    # run, the active tab's layout must report its rebuilt rows rather than
    # just its margins. Deliberately does not flush events itself -- that is
    # the popup's job, and doing it here would mask a regression.
    inner = popup._tabs.currentWidget().widget()

    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_data())

    assert inner.layout().sizeHint().height() > 100
