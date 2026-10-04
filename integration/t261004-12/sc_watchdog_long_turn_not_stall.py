#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_long_turn_not_stall.py — busy executor in a long turn is never a stall
redline (t261004-12, gray-box L2, offline seconds, zero docker/ports/browser).

intent (user-perceivable): the executor working inside one long turn used to be declared
"stalled" after 15 silent minutes (false redline) because the stall judgment ignored the
session's running bit. This scenario locks: a running session with no message/ledger
advance never produces a stall alert, no matter how far past stall_minutes the silence
goes; past the SEPARATE long-turn knob a distinct warn-level case appears (its own state
and wording, never the redline stall rule); the long-turn threshold is reachable across
grace beats (the silence clock must not reset each beat — t261001-19 defect-A shape); and
a message landing while running still counts as progress.

intent split: the pure judgment truth table per input tuple is developer L1
(liveness.test.mjs); the real-host wiring face (real sessionController.list()) is
t260929-08-sc_watchdog_real_progress_signal; this scenario locks the component contract
through the public Watchdog face (status + alert ledger) with the running bit injected —
neither of the other two covers "stall redline must NOT fire for a busy session".

Three states: node missing = ENV_FAIL exit 2; assertion red / driver FAIL = FAIL exit 1
(TDD red expected until implement lands; arbitrate/merge must be green).
Run directly: python3 integration/t261004-12/sc_watchdog_long_turn_not_stall.py (cwd=repo root).
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
    p = subprocess.run(["node", str(DRIVER), "long-turn"], capture_output=True, text=True,
                       cwd=str(REPO), timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    m = re.search(r"^SUMMARY pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+)", out, re.M)
    if not m:
        print("FAIL: driver produced no SUMMARY line (undeterminable = red, never fake green)")
        sys.exit(1)
    if int(m.group(2)) > 0 or p.returncode == 1:
        print("FAIL: long-turn contract red (see named assertions above)")
        sys.exit(1)
    if p.returncode != 0:
        print("FAIL: driver exit %d without a fail count (undeterminable = red)" % p.returncode)
        sys.exit(1)
    print("PASS=%s" % m.group(1))
    sys.exit(0)


if __name__ == "__main__":
    main()
