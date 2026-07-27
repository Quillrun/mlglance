"""Interactive layer for watch mode: raw-mode keyboard + the settings overlay.

Stdlib only (termios/tty/select) — no curses, no third-party TUI. The design goal
is fast/reliable/cheap: one select() serves both keypresses and the refresh timer,
the terminal is always restored on exit, and anywhere without a real tty (pipes,
CI, Windows) we degrade to a passive sleep so the watch loop behaves exactly as it
did before keys existed.
"""
from __future__ import annotations

import os
import select
import sys
import time

from .render import _div
from .theme import bold, cyan, dim, green

try:                                   # POSIX only; absent on Windows → passive watch
    import termios
    import tty
except ImportError:                    # pragma: no cover
    termios = tty = None

# Single-byte keys and the CSI tails arrow keys send (ESC '[' X). os.read gives bytes.
_KEYS = {b"\r": "enter", b"\n": "enter", b" ": "space", b"\x7f": "backspace", b"\x1b": "esc"}
_ARROWS = {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}


class Keyboard:
    """Context manager that puts the tty in cbreak mode and reads keys with a timeout.

    cbreak (not raw) keeps ISIG, so Ctrl-C/Ctrl-Z still signal normally. `read(t)`
    blocks at most `t` seconds, returning a normalized key name or None on timeout —
    so the watch loop stays responsive to keys *and* refreshes on schedule from the
    same call. When there's no tty, `active` is False and `read` just sleeps."""

    def __init__(self):
        self.active = bool(termios) and sys.stdin.isatty() and sys.stdout.isatty()
        self.fd = sys.stdin.fileno() if self.active else -1
        self._saved = None

    def __enter__(self):
        if self.active:
            self._saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            sys.stdout.write("\033[?25l")          # hide cursor — steadier redraw
            sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        if self._saved is not None:                # restore on every exit path
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            self._saved = None
        return False

    def read(self, timeout: float):
        if not self.active:
            time.sleep(max(0.0, timeout))
            return None
        if not select.select([self.fd], [], [], max(0.0, timeout))[0]:
            return None
        ch = os.read(self.fd, 1)
        if ch == b"\x1b":                          # ESC alone, or an arrow/CSI sequence
            if not select.select([self.fd], [], [], 0.0006)[0]:
                return "esc"
            return _ARROWS.get(os.read(self.fd, 2), "esc")
        return _KEYS.get(ch, ch.decode("utf-8", "ignore"))


# ── Settings model ────────────────────────────────────────────────────────────
# The refresh slider's discrete stops; None = "auto" (the dynamic-cadence mode).
INTERVAL_STOPS = [None, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
INTERVAL_LABELS = ["auto", "0.5s", "1s", "2s", "5s", "10s", "30s", "1min"]
_ROWS = ("Refresh", "Y-axis", "Chart")


def _nearest_stop(v) -> int:
    """Snap a starting --interval value onto the slider (None → auto at index 0)."""
    if v is None:
        return 0
    return min(range(1, len(INTERVAL_STOPS)), key=lambda i: abs(INTERVAL_STOPS[i] - v))


class Settings:
    """Live, keyboard-editable view state layered over the parsed CLI args."""

    def __init__(self, interval, log_y: bool, ascii_: bool):
        self.idx = _nearest_stop(interval)
        self.log_y = log_y
        self.ascii = ascii_
        self.view = "dash"                         # "dash" | "settings"
        self.row = 0

    @property
    def interval(self):
        return INTERVAL_STOPS[self.idx]            # None (auto) or seconds

    def move(self, direction: str):                # up/down through the rows
        self.row = (self.row + (1 if direction == "down" else -1)) % len(_ROWS)

    def adjust(self, direction: str):              # left/right on the selected row
        d = 1 if direction == "right" else -1
        if self.row == 0:
            self.idx = max(0, min(len(INTERVAL_STOPS) - 1, self.idx + d))
        elif self.row == 1:
            self.log_y = d > 0                     # left=linear, right=log
        else:
            self.ascii = d > 0                     # left=plotext, right=ascii


def _slider(idx: int) -> str:
    knob = "".join(cyan("●") if i == idx else dim("─") for i in range(len(INTERVAL_STOPS)))
    return f"{dim('◀')} {knob} {dim('▶')}   {bold(INTERVAL_LABELS[idx])}"


def _toggle(opts, active: int) -> str:
    return "   ".join(green(bold(f"[{o}]")) if j == active else dim(o)
                      for j, o in enumerate(opts))


def render_settings(st: Settings, width: int) -> str:
    bodies = [
        _slider(st.idx),
        _toggle(("linear", "log"), 1 if st.log_y else 0),
        _toggle(("plotext", "ascii"), 1 if st.ascii else 0),
    ]
    lines = [_div("SETTINGS", width), ""]
    for i, (name, body) in enumerate(zip(_ROWS, bodies)):
        cursor = cyan(bold("▸ ")) if i == st.row else "  "
        label = bold(name) if i == st.row else name
        lines.append(f"  {cursor}{label:<8} {body}")
    lines += ["", dim("  ↑↓ select   ←→ change   s/esc back   q quit")]
    return "\n".join(lines)
