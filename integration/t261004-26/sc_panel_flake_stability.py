#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_panel_flake_stability.py — the two timing-sensitive panel tests are
run-to-run stable (t261004-26 B2, gray-box L3, real browser via the declared
node --test entries, zero docker, never touches 3099/7233).

intent (reviewer-perceivable): requests -0006/-0011/-0019 — a flaky guard
trains readers to ignore red. The two named panel test files were random-red
(2 of 6 runs; the detail-scroll case order-sensitive under load). This entry
pins the stability face itself: each file runs THREE consecutive rounds through
its declared entry (`node --test <file>`) and every round must be green — the
round count and per-round rc are printed so a residual flake is visible, not
averaged away.

Intent split (no duplication): the behavioral contracts of the panel (width,
markdown, list contract, expand persistence, save contract) belong to their own
registered scenarios; the unit-level determinism of the retry/assertion
separation belongs to the developer battery; this entry pins only the
run-to-run stability of the two de-flaked files, which no other entry asserts.

Three states: node missing across the declared chain = ENV_FAIL exit 2; the
inner tests' own missing-environment face is theirs to name (their rc!=0 here
is FAIL — a flake is product red, which is exactly the property under test);
pre-implement the files are still flaky, so red is expected (TDD-phase signal;
arbitrate/merge must be green over 3/3 rounds). Run directly:
python3 integration/t261004-26/sc_panel_flake_stability.py (cwd=repo root).
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGETS = [
    "server/plugins/executor-panel/tests/browser-state.test.mjs",
    "server/plugins/executor-panel/tests/browser-save.test.mjs",
]
ROUNDS = 3

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok " + label)
    else:
        FAIL += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def main():
    print("== t261004-26 panel flake stability (B2: 2 files x %d rounds)" % ROUNDS)
    try:
        v = subprocess.run(["node", "--version"], capture_output=True, text=True)
    except OSError:
        v = None
    if not v or v.returncode != 0:
        print("ENV_FAIL: node missing (browser scenario has no face)")
        return 2
    env = dict(os.environ)
    for k in ("SANDBAR_SCENARIO_ONLY", "SANDBAR_INTEG_POOL", "SANDBAR_POOL_CONC",
              "SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC"):
        env.pop(k, None)          # the fixture declares its own surface; inherit nothing
    for rel in TARGETS:
        rcs = []
        for r in range(1, ROUNDS + 1):
            cp = subprocess.run(["node", "--test", rel], cwd=REPO, env=env,
                                capture_output=True, text=True,
                                errors="backslashreplace", timeout=600)
            rcs.append(cp.returncode)
            print("  round %d/%d %s -> rc=%s" % (r, ROUNDS, rel, cp.returncode))
            if cp.returncode != 0:
                print("    " + (cp.stdout + cp.stderr)[-400:])
        ok(all(rc == 0 for rc in rcs),
           "%s green %d/%d consecutive rounds (random red retired)" % (rel, ROUNDS, ROUNDS),
           rcs)
    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
