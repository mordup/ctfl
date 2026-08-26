"""Regression tests for popup sizing across a refresh.

Rebuilt rows are hidden until their posted show events are delivered, and
QLayout::sizeHint() ignores hidden widgets. Measuring the tab content before
those events land collapses the tab area to roughly the tab bar's height,
which is what made the popup shrink on refresh while it was already open.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QWidget

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
def config():
    c = Config()
    c.popup_geometry = None      # first-run state: the popup sizes itself
    return c


@pytest.fixture
def popup(qapp, config):
    w = PopupWidget(config)
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


# --- normal-window behaviour -------------------------------------------------


def test_popup_is_an_ordinary_window(popup):
    # Not a Tool panel, and not forced above every other window. The window
    # *type* lives in the low byte and is a value, not a bit -- masking is
    # required; a plain `flags & Qt.Tool` matches any decorated window.
    flags = popup.windowFlags()
    window_type = flags & Qt.WindowType.WindowType_Mask
    assert window_type == Qt.WindowType.Window
    assert window_type != Qt.WindowType.Tool
    assert not (flags & Qt.WindowType.WindowStaysOnTopHint)


def test_losing_focus_does_not_hide_the_window(popup, qapp):
    # The old changeEvent hid the popup the moment it stopped being active,
    # which is what made copy-paste from a browser unworkable. Deliver the
    # activation change explicitly -- offscreen windows are never "active",
    # so merely losing focus raises no event and would prove nothing.
    assert popup.isVisible()

    # Hand activation to another window so the popup is genuinely inactive,
    # then deliver the activation change it would receive in that moment.
    other = QWidget()
    other.show()
    other.activateWindow()
    qapp.processEvents()
    QApplication.sendEvent(popup, QEvent(QEvent.Type.ActivationChange))
    qapp.processEvents()

    still_visible = popup.isVisible()
    other.close()
    other.deleteLater()
    qapp.processEvents()
    assert still_visible


def test_hiding_saves_geometry(popup, config, qapp):
    assert config.popup_geometry is None
    popup.resize(700, 600)
    qapp.processEvents()
    popup.hide()
    qapp.processEvents()
    assert config.popup_geometry


def test_saved_geometry_suppresses_resize_on_refresh(popup, config, qapp):
    popup.resize(700, 600)
    qapp.processEvents()
    popup.hide()          # persists the user's size
    popup.show()
    qapp.processEvents()
    chosen = popup.size()

    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_data())
    qapp.processEvents()

    assert popup.size() == chosen


def test_restore_or_position_reports_whether_geometry_was_used(popup, config, qapp):
    assert popup.restore_or_position(popup.geometry()) is False
    popup.resize(680, 580)
    popup.hide()
    qapp.processEvents()
    assert popup.restore_or_position(popup.geometry()) is True


def test_first_run_sizes_to_the_tallest_tab(qapp, config):
    # Daily deliberately sparse, By Model tall: the window must open big
    # enough for the tallest tab so switching never resizes it.
    data = UsageData(
        by_model=[ModelTokens(model=f"claude-opus-{i}", input_tokens=1000,
                              output_tokens=500, cache_read_tokens=200)
                  for i in range(9)],
        limits=list(_LIMITS),
    )
    w = PopupWidget(config)
    w.update_data(data)
    w.show()
    qapp.processEvents()
    opened = w.height()

    w._tabs.setCurrentIndex(1)   # By Model, the tallest
    qapp.processEvents()
    assert w.height() == opened

    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_tab_area_can_shrink_below_the_first_run_size(popup, qapp):
    # setFixedHeight pins both bounds; if the minimum is not released the
    # user cannot make the window smaller than it first opened.
    assert popup._tabs.minimumHeight() == 0


def test_closing_saves_geometry(popup, config, qapp):
    # Quit and Restart close the window rather than dropping it, because
    # QApplication.quit() fires neither hideEvent nor closeEvent.
    assert config.popup_geometry is None
    popup.resize(660, 540)
    qapp.processEvents()
    popup.close()
    qapp.processEvents()
    assert config.popup_geometry
