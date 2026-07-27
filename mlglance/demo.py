"""Live demo: a synthetic trainer streams realistic metrics while the dashboard
watches it."""
from __future__ import annotations

import json
import math
import os
import random
import tempfile
import threading
import time

from .cli import watch_loop

VAL_EVERY = 20
STEPS = 240


def _curve(scenario, i):
    base = 2.6 * math.exp(-i / 45) + 0.32
    train = base + random.uniform(-0.05, 0.05)
    val = None
    if i % VAL_EVERY == 0:
        if scenario == "converge":
            val = 2.5 * math.exp(-i / 50) + 0.45
        elif scenario == "diverge":
            val = (2.4 * math.exp(-i / 40) + 0.5) if i <= 70 else 0.85 + 0.012 * (i - 70)
        else:
            val = (2.3 * math.exp(-i / 35) + 0.5) if i <= 90 else 0.95 + 0.004 * (i - 90)
        val = round(val + random.uniform(-0.01, 0.01), 4)
    return round(train, 4), val


def _producer(path, scenario, stop):
    lr0, peak = 1e-4, 7.2
    with open(path, "w") as fh:
        for i in range(1, STEPS + 1):
            if stop.is_set():
                return
            train, val = _curve(scenario, i)
            row = {
                "iter": i,
                "train_loss": train,
                "lr": round(lr0 * 0.5 * (1 + math.cos(math.pi * i / STEPS)), 8),
                "step_s": round(random.uniform(0.18, 0.30), 3),
                "peak_gb": round(peak + random.uniform(-0.3, 0.5), 2),
                "grad_norm": round(abs(1.5 + random.uniform(-0.4, 0.6)), 2),
                "tokens": 8192,
            }
            if val is not None:
                row["val_loss"] = val
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            time.sleep(0.18)
        while not stop.is_set():
            time.sleep(0.5)


def run_demo(args):
    scenario = args.scenario
    tmp = os.path.join(tempfile.gettempdir(), f"mlglance-demo-{scenario}.jsonl")
    open(tmp, "w").close()
    stop = threading.Event()
    prod = threading.Thread(target=_producer, args=(tmp, scenario, stop), daemon=True)
    prod.start()

    args.title = f"demo:{scenario}"
    args.total = STEPS
    # leave args.interval as parsed — None (auto) by default, or the user's -n — so the
    # demo dogfoods auto-cadence against the ~0.18s/step producer below.
    try:
        watch_loop(tmp, args)
    finally:
        stop.set()
        try:
            os.unlink(tmp)
        except OSError:
            pass
