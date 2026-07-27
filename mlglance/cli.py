"""Command-line entry point + the watch loop."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

from . import __version__, theme
from .render import render
from .theme import dim
from .tui import Keyboard, Settings, render_settings

_CLEAR = "cls" if os.name == "nt" else "clear"

# Auto-poll tuning. In --interval auto we wake at a fraction of the observed write
# cadence (gap between metric appends), so a slow run doesn't redraw between steps
# and a fast run still feels live. Clamped, with a gentle back-off once the stream
# goes quiet (run finished / stalled) so we don't spin on an unchanging file.
AUTO_MIN, AUTO_MAX, AUTO_FRAC, AUTO_COLD = 0.5, 10.0, 0.5, 1.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def parse_interval(s: str):
    """--interval value: 'auto' (dynamic) or a duration — 5, 10, 30, 1min, 0.5s.
       Returns None for auto, else seconds (float)."""
    s = s.strip().lower()
    if s in ("auto", "a", "dynamic"):
        return None
    mult = 1.0
    if s.endswith("min"):
        mult, s = 60.0, s[:-3]
    elif s.endswith("m"):
        mult, s = 60.0, s[:-1]
    elif s.endswith("s"):
        s = s[:-1]
    try:
        v = float(s) * mult
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"interval must be 'auto' or a number/duration (e.g. 5, 30, 1min); got {s!r}")
    if v <= 0:
        raise argparse.ArgumentTypeError("interval must be positive")
    return v


def auto_interval(cadence, idle_for: float) -> float:
    """Next poll delay for auto mode.
       cadence:  smoothed seconds between the last two metric writes (None until learned).
       idle_for: seconds since the last write (or since watch start, before any write)."""
    if cadence is None:
        # not learned yet: start responsive, but ease toward the ceiling if nothing
        # ever arrives (a finished/static file opened with -w).
        return _clamp(max(AUTO_COLD, idle_for * AUTO_FRAC), AUTO_MIN, AUTO_MAX)
    base = _clamp(cadence * AUTO_FRAC, AUTO_MIN, AUTO_MAX)
    if idle_for > 3 * cadence:                  # stream went quiet — back off toward the ceiling
        base = _clamp(max(base, idle_for * AUTO_FRAC), AUTO_MIN, AUTO_MAX)
    return base


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mlglance",
        description="Terminal-native live training monitor (loss curves + verdict).")
    p.add_argument("path", nargs="?", default=None,
                   help="metrics JSONL to watch (or 'demo' for a live demo)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-w", "--watch", action="store_true", help="refresh continuously")
    p.add_argument("-n", "--interval", type=parse_interval, default=None, metavar="AUTO|SECS",
                   help="refresh: 'auto' (tracks step cadence, default) or fixed 5 / 30 / 1min / 0.5s")
    p.add_argument("--total", type=int, default=0, help="total steps (else auto-detected)")
    p.add_argument("--title", default=None, help="dashboard title (else from path)")
    p.add_argument("--log-y", action="store_true", help="log-scale loss axis")
    p.add_argument("--ascii", action="store_true", help="force the zero-dep ascii backend")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    p.add_argument("--width", type=int, default=0, help="override canvas width")
    p.add_argument("--height", type=int, default=0, help="override canvas height")
    p.add_argument("--demo", action="store_true", help="run a live synthetic demo")
    p.add_argument("--scenario", default="overfit",
                   choices=["converge", "overfit", "diverge"], help="demo scenario")
    return p


def _clear():
    # ANSI home+erase: atomic, no per-cycle fork, less flicker. Fall back to the
    # clear/cls binary only when stdout isn't a tty (the ANSI codes would be noise).
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[2J")
    else:
        os.system(_CLEAR)


def watch_loop(path, args):
    st = Settings(args.interval, args.log_y, args.ascii)
    last_dash_key, cached = None, ""
    last_mtime = None
    start_t = time.monotonic()
    last_change_t = None          # monotonic time the last metric write landed
    cadence = None                # smoothed seconds between writes (auto mode)
    with Keyboard() as kb:
        try:
            while True:
                try:
                    mtime = os.stat(path).st_mtime
                except OSError:
                    mtime = None
                now = time.monotonic()
                if last_mtime is not None and mtime != last_mtime:   # a new write landed
                    if last_change_t is not None:
                        gap = now - last_change_t
                        cadence = gap if cadence is None else 0.5 * gap + 0.5 * cadence
                    last_change_t = now
                last_mtime = mtime

                # Re-run the (expensive) chart render only when an input to it changes;
                # log-y / ascii are now live-toggleable, so they're part of the key.
                size = shutil.get_terminal_size()
                cols = size.columns
                dash_key = (mtime, size, st.log_y, st.ascii)
                if dash_key != last_dash_key:
                    try:
                        cached = render(path, args.total, args.title, args.width, args.height,
                                        st.log_y, st.ascii)
                        last_dash_key = dash_key
                    except Exception as e:    # one bad frame must not kill a live watch — retry next tick
                        cached = f"  [mlglance: render error — {e}]\n  retrying…"

                # Poll delay = the auto/fixed refresh; it doubles as the keyboard timeout.
                if st.interval is None:       # auto: a fraction of the observed step cadence
                    idle = now - (last_change_t if last_change_t is not None else start_t)
                    base_delay = auto_interval(cadence, idle)
                    rate = f"~{base_delay:.1f}s (auto)"
                else:
                    base_delay = st.interval
                    rate = f"every {base_delay:g}s"

                if st.view == "settings":
                    frame = render_settings(st, cols)
                    foot = "↑↓ select · ←→ change · s/esc back · q quit"
                    delay = min(base_delay, 0.5)   # stay snappy while editing
                else:
                    frame = cached
                    foot = (f"watching {rate} · s settings · q quit" if kb.active
                            else f"watching {rate} — Ctrl-C to stop")
                    delay = base_delay

                _clear()
                print(frame)
                print(dim(f"\n  {foot}"))

                key = kb.read(delay)               # blocks ≤ delay; returns on a keypress
                if key is None:
                    continue
                if key == "q":
                    break
                if st.view == "dash":
                    if key in ("s", "enter"):
                        st.view = "settings"
                elif key in ("s", "esc", "enter"):
                    st.view = "dash"
                elif key in ("up", "down"):
                    st.move(key)
                elif key in ("left", "right"):
                    st.adjust(key)
        except KeyboardInterrupt:
            pass


def main(argv=None):
    args = build_parser().parse_args(argv)
    theme.enabled(sys.stdout.isatty() and not args.no_color)

    if args.demo or args.path == "demo":
        from .demo import run_demo
        run_demo(args)
        return

    path = args.path or "metrics.jsonl"
    if args.watch:
        watch_loop(path, args)
    else:
        print(render(path, args.total, args.title, args.width, args.height,
                     args.log_y, args.ascii))


if __name__ == "__main__":
    main()
