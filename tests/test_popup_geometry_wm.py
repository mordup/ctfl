"""Geometry tracking under a real window manager.

The offscreen platform never delivers the events this logic exists to filter:
a WM echoes our own resize back as a ConfigureNotify after the guard flag has
cleared, and repositions windows unprompted. Both were invisible offscreen and
both produced a popup that persisted a size the user never chose. So this runs
the scenarios in a subprocess against a real X server, and skips where there is
none (CI).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="needs a real X server; offscreen cannot show this"
)

DRIVER = textwrap.dedent('''
    import sys
    from PyQt6.QtWidgets import QApplication
    from ctfl.config import Config
    from ctfl.popup import PopupWidget
    from ctfl.providers import ModelTokens, RateLimitInfo, UsageData

    app = QApplication(sys.argv)

    def data(rows=6):
        return UsageData(
            by_model=[ModelTokens(model=f"claude-opus-{i}", input_tokens=1000,
                                  output_tokens=500, cache_read_tokens=200)
                      for i in range(rows)],
            limits=[RateLimitInfo("Session", 18.0, None, "five_hour"),
                    RateLimitInfo("Weekly", 25.0, None, "seven_day")])

    def pump(n=8):
        for _ in range(n):
            app.processEvents()

    c = Config()
    out = {}

    c.popup_geometry = None
    w = PopupWidget(c); w.close(); pump()
    out["never_shown"] = bool(c.popup_geometry)

    c.popup_geometry = None
    w = PopupWidget(c); w.update_data(data()); w.show(); pump()
    w.hide(); pump()
    out["shown_untouched"] = bool(c.popup_geometry)

    c.popup_geometry = None
    w = PopupWidget(c); w.update_data(data()); w.show(); pump()
    for _ in range(3):
        w.show_loading(); pump(); w.update_data(data()); pump()
    w.hide(); pump()
    out["refreshed_untouched"] = bool(c.popup_geometry)

    # Refreshes where the row count actually changes, so _fit_to_content
    # genuinely resizes the window rather than no-opping on an identical
    # sizeHint. This is what makes the guards load-bearing.
    c.popup_geometry = None
    w = PopupWidget(c); w.update_data(data(2)); w.show(); pump()
    for rows in (9, 3, 11, 4):
        w.show_loading(); pump()
        w.update_data(data(rows)); pump()
    w.hide(); pump()
    out["resized_by_data_changes"] = bool(c.popup_geometry)

    c.popup_geometry = None
    w = PopupWidget(c); w.update_data(data()); w.show(); pump()
    w.resize(700, 640); pump(); w.hide(); pump()
    out["user_resized"] = bool(c.popup_geometry)

    print(repr(out))
''')


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wm")
    script = tmp / "driver.py"
    script.write_text(DRIVER)
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="xcb",
        XDG_CONFIG_HOME=str(tmp / "config"),
        PYTHONPATH=os.getcwd(),
    )
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, env=env, timeout=120)
    if proc.returncode != 0:
        pytest.skip(f"could not drive a real window: {proc.stderr.strip()[:300]}")
    return ast.literal_eval(proc.stdout.strip().splitlines()[-1])


def test_never_shown_popup_saves_nothing(results):
    assert results["never_shown"] is False


def test_open_and_close_saves_nothing(results):
    assert results["shown_untouched"] is False


def test_refreshes_do_not_look_like_a_user_resize(results):
    # The one offscreen could not catch: the WM's echo of our own resize, and
    # its unprompted repositioning, both arrived after the guard flag cleared.
    assert results["refreshed_untouched"] is False


def test_data_driven_resizes_are_not_a_user_resize(results):
    # Row counts change between refreshes, so _fit_to_content really does
    # resize the window. None of that is the user choosing a size.
    assert results["resized_by_data_changes"] is False


def test_a_real_resize_is_remembered(results):
    assert results["user_resized"] is True
