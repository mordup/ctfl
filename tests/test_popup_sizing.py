"""Regression tests for popup sizing across a refresh.

Rebuilt rows are hidden until their posted show events are delivered, and
QLayout::sizeHint() ignores hidden widgets. Measuring the tab content before
those events land collapses the tab area to roughly the tab bar's height,
which is what made the popup shrink on refresh while it was already open.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QRect, Qt
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


def test_hiding_after_a_user_resize_saves_geometry(popup, config, qapp):
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


def test_closing_after_a_user_resize_saves_geometry(popup, config, qapp):
    # Quit and Restart close the window rather than dropping it, because
    # QApplication.quit() fires neither hideEvent nor closeEvent.
    assert config.popup_geometry is None
    popup.resize(660, 540)
    qapp.processEvents()
    popup.close()
    qapp.processEvents()
    assert config.popup_geometry


# --- only a size the user actually chose is remembered -----------------------


def test_never_shown_popup_does_not_save_geometry(qapp, config):
    # TrayIcon builds the popup at startup and may never show it; tray Quit and
    # Restart close it. Persisting Qt's default 640x480 there would freeze every
    # later open at a size the user never picked.
    assert config.popup_geometry is None
    w = PopupWidget(config)
    w.close()
    qapp.processEvents()
    assert config.popup_geometry is None
    w.deleteLater()
    qapp.processEvents()


def test_show_then_hide_without_resizing_does_not_save(popup, config, qapp):
    # Opening the popup and closing it again is not the user choosing a size.
    assert config.popup_geometry is None
    popup.hide()
    qapp.processEvents()
    assert config.popup_geometry is None


def test_auto_fit_survives_an_open_close_cycle(qapp, config):
    # Cold start: the popup opens while the fetch is still in flight, so it
    # renders empty and small. Closing it must not freeze that size. Asserting
    # merely that it "grew" is not enough -- layout minimums grow it anyway --
    # so pin it to what a popup that never went through the cycle picks.
    ref = PopupWidget(config)
    ref.update_data(_data())
    ref.show()
    qapp.processEvents()
    expected = ref.height()
    ref.hide()
    ref.deleteLater()
    qapp.processEvents()
    config.popup_geometry = None        # discard anything the reference wrote

    w = PopupWidget(config)
    w.update_data(UsageData())          # loading state: no limits, no charts
    w.show()
    qapp.processEvents()
    w.hide()                            # closed without ever being resized
    qapp.processEvents()

    w.show()
    w.update_data(_data())              # real data arrives
    qapp.processEvents()
    assert w.height() == expected, (
        f"froze at {w.height()}px; a never-cycled popup picks {expected}px"
    )
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_restored_geometry_is_clamped_to_the_screen(qapp, config):
    # A geometry saved under one screen layout must not put the window, and its
    # Refresh/Settings buttons, off-screen when restored under another.
    w = PopupWidget(config)
    w.show()
    qapp.processEvents()
    avail = w.screen().availableGeometry()
    w.resize(600, 500)                          # a real user resize
    w.move(avail.right() + 4000, avail.bottom() + 4000)
    qapp.processEvents()
    w.hide()
    qapp.processEvents()
    assert config.popup_geometry

    w2 = PopupWidget(config)
    assert w2.restore_or_position(avail) is True
    w2.show()
    qapp.processEvents()
    assert avail.contains(w2.geometry()), (
        f"restored off-screen at {w2.geometry()}, screen is {avail}"
    )
    w2.close()
    w2.deleteLater()
    qapp.processEvents()


def test_moving_without_resizing_is_not_remembered(popup, config, qapp):
    # A deliberate narrowing, not an oversight: window managers move windows
    # on their own (one was seen repositioning this popup mid-refresh), and a
    # WM move is indistinguishable from a drag. Counting moves made an
    # ordinary refresh look like the user had chosen a size. Position still
    # rides along in saveGeometry() as soon as a resize happens.
    assert config.popup_geometry is None
    popup.move(popup.x() + 120, popup.y() + 90)
    qapp.processEvents()
    popup.hide()
    qapp.processEvents()
    assert config.popup_geometry is None


def test_config_sync_flushes_for_a_replacement_process(config):
    # _restart spawns the new instance immediately; without an explicit flush
    # the resize the user just made can still be sitting in memory.
    config.popup_geometry = b"sentinel-geometry-blob"
    config.sync()
    assert Config().popup_geometry == b"sentinel-geometry-blob"


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
    def restore_or_position(self, geo): self.calls.append("position")


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
