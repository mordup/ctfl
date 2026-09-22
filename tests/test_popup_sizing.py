"""The popup sizes itself to its content and cannot be resized.

Also the regression behind the refresh tests: rebuilt rows are hidden until
their posted show events are delivered, and QLayout::sizeHint() ignores hidden
widgets. Measuring the tab content before those events land collapses the tab
area to roughly the tab bar's height, which made the popup shrink on refresh.
"""

from __future__ import annotations

from datetime import date

import pytest
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from ctfl.config import Config
from ctfl.popup import PopupWidget
from ctfl.providers import DailyUsage, ModelTokens, RateLimitInfo, UsageData

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


@pytest.fixture
def config():
    c = Config()
    c.period = "today"
    return c


def _models(rows: int) -> UsageData:
    return UsageData(
        models_by_day={date.today().isoformat(): [
            ModelTokens(model=f"claude-opus-{i}", input_tokens=1000 * (i + 1),
                        output_tokens=500, cache_read_tokens=2000,
                        cache_creation_tokens=100)
            for i in range(rows)]},
        limits=list(_LIMITS),
    )


def _open(qapp, config, data: UsageData, tab: int = 1) -> PopupWidget:
    w = PopupWidget(config)
    w.update_data(data)
    w.show()
    w._tabs.setCurrentIndex(tab)
    qapp.processEvents()
    return w


@pytest.fixture
def popup(qapp, config):
    w = _open(qapp, config, _models(6))
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _visible_rows(w: PopupWidget) -> list[int]:
    """Indexes of the By Model rows that are shown whole."""
    area = w._tabs.currentWidget()
    shown = area.viewport().rect().translated(0, area.verticalScrollBar().value())
    rows = w._model_chart.layout()
    return [i for i in range(rows.count() - 1) if shown.contains(rows.itemAt(i).geometry())]


def _cut_rows(w: PopupWidget) -> list[int]:
    area = w._tabs.currentWidget()
    shown = area.viewport().rect().translated(0, area.verticalScrollBar().value())
    rows = w._model_chart.layout()
    return [
        i for i in range(rows.count() - 1)
        if shown.intersects(rows.itemAt(i).geometry())
        and not shown.contains(rows.itemAt(i).geometry())
    ]


# --- self-sizing -------------------------------------------------------------


def test_popup_cannot_be_resized(popup):
    assert popup.minimumSize() == popup.maximumSize()


def test_width_is_fixed(popup, qapp):
    popup.resize(1400, popup.height() + 300)
    qapp.processEvents()
    assert popup.width() == 500


def test_long_list_shows_seven_whole_rows(qapp, config):
    w = _open(qapp, config, _models(12))
    assert _visible_rows(w) == list(range(7))
    assert _cut_rows(w) == []
    w.close()


def test_short_list_fits_without_scrolling(qapp, config):
    w = _open(qapp, config, _models(3))
    assert _visible_rows(w) == [0, 1, 2]
    assert not w._tabs.currentWidget().verticalScrollBar().isVisible()
    w.close()


def test_fewer_rows_make_a_shorter_popup(qapp, config):
    short, tall = _open(qapp, config, _models(4)), _open(qapp, config, _models(12))
    assert short.height() < tall.height()
    short.close()
    tall.close()


@pytest.mark.parametrize("rows", [1, 2])
def test_a_short_list_still_gets_room_for_three_rows(qapp, config, rows):
    w, three = _open(qapp, config, _models(rows)), _open(qapp, config, _models(3))
    assert w.height() == three.height()
    w.close()
    three.close()


def test_switching_tabs_keeps_the_size(qapp, config):
    # Usage has one row, By Model nine: sized to the tallest tab, so switching
    # between them does not move the window's edges.
    data = _models(9)
    data.daily = [DailyUsage(date=date.today().isoformat(), input_tokens=10)]
    w = _open(qapp, config, data, tab=0)
    opened = w.size()
    w._tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert w.size() == opened
    w.close()


def test_changing_period_refits(qapp, config):
    today = date.today()
    data = _models(1)
    if today.day > 1:
        earlier = today.replace(day=1).isoformat()
        data.models_by_day[earlier] = [ModelTokens(model=f"claude-sonnet-{i}", input_tokens=5)
                                       for i in range(6)]
    w = _open(qapp, config, data)
    before = w.height()
    w._period_combo.setCurrentIndex(w._period_combo.findData("month"))
    qapp.processEvents()
    assert (w.height() > before) == (today.day > 1)
    w.close()


# --- refresh keeps the measured size -----------------------------------------


def test_tab_area_survives_a_refresh(popup, qapp):
    before = popup._tabs.height()
    assert before > 100, "fixture did not produce a populated tab to begin with"

    # The tray's refresh cycle: clear, then deliver new data while visible.
    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_models(6))
    qapp.processEvents()

    assert popup._tabs.height() == before


def test_tab_area_does_not_collapse_to_the_tab_bar(popup, qapp):
    # The failure mode was a tab area pinned to tab-bar height plus padding,
    # which is what a margins-only sizeHint produces.
    tab_bar_h = popup._tabs.tabBar().sizeHint().height()

    popup.show_loading()
    qapp.processEvents()
    popup.update_data(_models(6))
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
        popup.update_data(_models(6))
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
    popup.update_data(_models(6))

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


# --- settings ------------------------------------------------------------------


def test_config_sync_flushes_for_a_replacement_process(config):
    # _restart spawns the new instance immediately; without an explicit flush
    # a setting changed just before can still be sitting in memory.
    config.period = "month"
    config.sync()
    assert Config().period == "month"


def test_settings_from_earlier_versions_are_dropped(config):
    config._s.setValue("popup_geometry", b"old")
    config._s.setValue("days_to_show", 7)
    config.sync()
    fresh = Config()
    assert not fresh._s.contains("popup_geometry")
    assert not fresh._s.contains("days_to_show")


# --- tray toggle -------------------------------------------------------------


class _StubPopup:
    """Minimal stand-in: constructing a real TrayIcon pulls in keyring."""

    def __init__(self, visible, active):
        self._visible, self._active = visible, active
        self.calls = []

    def isVisible(self): return self._visible
    def isActiveWindow(self): return self._active
    def hide(self): self.calls.append("hide")
    def show(self): self.calls.append("show")
    def raise_(self): self.calls.append("raise")
    def activateWindow(self): self.calls.append("activate")
    def update_data(self, data): self.calls.append("update")
    def position_near_tray(self, geo): self.calls.append("position")


class _StubTray:
    def __init__(self, popup):
        self._popup, self._latest_data = popup, None

    def geometry(self): return QRect(0, 0, 10, 10)


def _trigger(popup):
    from PyQt6.QtWidgets import QSystemTrayIcon

    from ctfl.tray import TrayIcon
    TrayIcon._on_activated(_StubTray(popup),
                           QSystemTrayIcon.ActivationReason.Trigger)
    return popup.calls


def test_tray_click_hides_the_popup_the_user_is_looking_at():
    assert _trigger(_StubPopup(visible=True, active=True)) == ["hide"]


def test_tray_click_raises_a_visible_but_inactive_popup():
    # The regression: as an ordinary window the popup can sit behind the
    # browser, and hiding it there reads as the click doing nothing.
    calls = _trigger(_StubPopup(visible=True, active=False))
    assert "hide" not in calls
    assert calls[-2:] == ["raise", "activate"]


def test_tray_click_opens_a_hidden_popup():
    calls = _trigger(_StubPopup(visible=False, active=False))
    assert "hide" not in calls
    assert "show" in calls
