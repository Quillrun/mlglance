import re

from mlglance import theme
from mlglance.tui import (Keyboard, Settings, render_settings,
                          INTERVAL_STOPS, _nearest_stop)

_ANSI = re.compile(r"\033\[[0-9;]*m")


def plain(s):
    return _ANSI.sub("", s)


def test_nearest_stop_snaps():
    assert _nearest_stop(None) == 0                 # auto
    assert INTERVAL_STOPS[_nearest_stop(5.0)] == 5.0
    assert INTERVAL_STOPS[_nearest_stop(7.0)] == 5.0   # 7 closer to 5 than 10
    assert INTERVAL_STOPS[_nearest_stop(1000)] == 60.0  # clamps to the last stop


def test_settings_init_from_interval():
    assert Settings(None, False, False).interval is None
    assert Settings(30.0, False, False).interval == 30.0


def test_row_navigation_wraps():
    st = Settings(None, False, False)
    assert st.row == 0
    st.move("up")
    assert st.row == 2                              # wraps to last
    st.move("down")
    assert st.row == 0


def test_slider_adjust_and_clamp():
    st = Settings(None, False, False)               # row 0 = Refresh, idx 0 = auto
    st.adjust("left")
    assert st.interval is None                      # can't go below auto
    st.adjust("right")
    assert st.interval == INTERVAL_STOPS[1]         # steps off auto
    for _ in range(50):
        st.adjust("right")
    assert st.interval == 60.0                      # clamps at the top stop


def test_toggle_rows():
    st = Settings(None, False, False)
    st.row = 1                                       # Y-axis
    st.adjust("right")
    assert st.log_y is True
    st.adjust("left")
    assert st.log_y is False
    st.row = 2                                       # Chart
    st.adjust("right")
    assert st.ascii is True


def test_render_settings_shows_state():
    theme.enabled(False)
    st = Settings(5.0, False, False)
    out = plain(render_settings(st, 80))
    assert "SETTINGS" in out
    for label in ("Refresh", "Y-axis", "Chart"):
        assert label in out
    assert "5s" in out                               # current slider label
    assert "▸" in out                                # a cursor is drawn
    assert "linear" in out and "plotext" in out


def test_keyboard_passive_without_tty():
    # Under pytest stdin/stdout are not ttys → Keyboard degrades to a passive sleep.
    kb = Keyboard()
    assert kb.active is False
    with kb:
        assert kb.read(0) is None                    # returns immediately, no key
