#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_copy_language_console_english.py — console-visible watchdog copy is English
(t261004-24, gray-box L2, offline seconds, zero docker/ports/browser).

intent (user-perceivable): executor request -0003 — t261004-12 shipped new
user-visible copy in Chinese while the writing standard
(docs/reference/writing-standard.md §1/§2) makes the console surface English.
This scenario locks the language family of everything the operator actually sees:
the executor_long_turn alert title + detail, the liveness evidence strings behind
them, the degraded-heartbeat reason, and the settings validation copy returned to
the panel when a save is refused — all English (no CJK ideographs, no fullwidth/CJK
punctuation) — while the deciding precision survives (session id verbatim, the
stall/long-turn threshold numbers, the running bit named as the deciding source).

intent split: WHICH state fires when (long_turn vs stalled vs no_signal) belongs to
t261004-12's two scenarios; exact English wording/style belongs to developer L1;
the per-diff mechanical gate is a separate scenario
(t261004-24-copy-language-per-diff-gate). This entry locks only "what the user
sees is English AND still says which check decided".

Three states: node missing = ENV_FAIL exit 2; driver FAIL = FAIL exit 1 (TDD red
expected until implement lands; arbitrate/merge must be green).
Run directly: python3 integration/t261004-24/sc_copy_language_console_english.py (cwd=repo root).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DRIVER = REPO / "integration" / "t261004-24" / "lib_copy_face_driver.mjs"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node not in PATH (the watchdog face is a node seam)")
        sys.exit(2)
    if not DRIVER.is_file():
        print("FAIL: driver script missing: %s" % DRIVER)
        sys.exit(1)
    p = subprocess.run(["node", str(DRIVER)], capture_output=True, text=True,
                       cwd=str(REPO), timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    sums = re.findall(r"^SUMMARY leg=(\S+) pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+)", out, re.M)
    if not sums:
        print("FAIL: driver produced no SUMMARY line (undeterminable = red, never fake green)")
        sys.exit(1)
    if p.returncode == 1 or any(int(f) > 0 for _, _, f, _, _ in sums):
        print("FAIL: console-visible copy language red (see named assertions above)")
        sys.exit(1)
    if p.returncode != 0:
        print("FAIL: driver exit %d without a fail count (undeterminable = red)" % p.returncode)
        sys.exit(1)
    print("PASS=%s" % sum(int(x) for _, x, _, _, _ in sums))
    sys.exit(0)


if __name__ == "__main__":
    main()
