#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_running_bit_fallbacks.py — status face + unchanged fallbacks
(t261004-12, gray-box L2, offline seconds, zero docker/ports/browser).

intent (user-perceivable): after the running bit enters the stall judgment, a human must
be able to tell "busy in a long turn" from "genuinely stalled" from the watchdog status
face alone (the face shows the running bit next to the chosen case), an unreadable bit
stays an EXPLICIT unknown (no_signal) and never collapses to normal or to stalled, while
the useful old behaviour is NOT weakened: a not-running session silent past stall_minutes
still reports stalled with the stall redline (also at 45min — long_turn must not swallow
the genuine-stall case), and evidence names which check produced the verdict.

intent split: developer L1 owns the per-input truth table and the config knob parse;
t260929-08 owns the real-host signal wiring; this scenario owns the public-face
discrimination contract and the fallback legs through the Watchdog public surface.

Three states: node missing = ENV_FAIL exit 2; assertion red = FAIL exit 1 (TDD red
expected until implement lands; arbitrate/merge must be green).
Run directly: python3 integration/t261004-12/sc_watchdog_running_bit_fallbacks.py (cwd=repo root).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DRIVER = REPO / "integration" / "t261004-12" / "lib_judge_driver.mjs"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（watchdog 面是 node 缝）")
        sys.exit(2)
    if not DRIVER.is_file():
        print("FAIL: 驱动脚本缺席：%s" % DRIVER)
        sys.exit(1)
    p = subprocess.run(["node", str(DRIVER), "fallbacks"], capture_output=True, text=True,
                       cwd=str(REPO), timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    m = re.search(r"^SUMMARY pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+)", out, re.M)
    if not m:
        print("FAIL: driver produced no SUMMARY line (undeterminable = red, never fake green)")
        sys.exit(1)
    if int(m.group(2)) > 0 or p.returncode == 1:
        print("FAIL: fallback/face contract red (see named assertions above)")
        sys.exit(1)
    if p.returncode != 0:
        print("FAIL: driver exit %d without a fail count (undeterminable = red)" % p.returncode)
        sys.exit(1)
    print("PASS=%s" % m.group(1))
    sys.exit(0)


if __name__ == "__main__":
    main()
