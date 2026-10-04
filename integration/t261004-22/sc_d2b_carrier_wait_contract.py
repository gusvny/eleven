#!/usr/bin/env python3
"""sc_d2b_carrier_wait_contract — the D2b carrier test must wait, not sleep, and
must name its cause on a genuine failure (t261004-22, grey-box L3).

Tested exit (the user-perceivable contract): the engine test file
`server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py`, single case
`test_d2b_carrier_detected_through_unresolved_root`, driven as a real pytest
subprocess on the real tree. Intent: a fixed sleep there flaked under load and
blocked unrelated tickets at merge_check; the fix must (R1) poll to a deadline
instead of sleeping, (R2) name the slow-child cause on timeout instead of the
generic carrier-is-invisible message, and (R3) degrade by a named skip when
process enumeration is unavailable instead of a false red. Requirement 4 (keep
the unresolved-root regression assertion) is pinned by the green path A: the
case must still pass with real enumeration.

Sub-cases (each drives the real test via a real venv pytest subprocess):
  A green path: untouched environment -> pytest exit 0, "1 passed", and the
    case finishes well inside its own deadline (the fixed 1.0 s sleep is gone;
    polling must be cheap on the green path).
  B enumeration unavailable: a PATH stub shadowing `pgrep` with exit 127 (the
    executor sandbox refuses process tools; `_all_pids` then returns a named
    error) -> pytest must NOT go red for the wrong reason: exit 0 with the case
    skipped and the named reason (mentions pgrep/enumeration) visible.
  C cwd unresolvable: PATH stubs where `pgrep` answers two pids and `lsof`
    resolves only pid 1 (any other pid, including the test's child, gets no
    cwd) -> enumeration looks healthy, some cwd is resolvable, but the child
    can never be seen: the deadline must fire, pytest must FAIL with the
    named slow-child message (deadline + cwd scan), and must NOT carry the
    generic carrier-is-invisible regression message.

Intent split: the poll/deadline unit matrix and the skip choice belong to the
developer L1 battery in the same test file; this scenario locks the end-to-end
subprocess face — what a reader of a red or yellow run actually sees.

Three states: venv/pytest absent = ENV_FAIL exit 2; any assertion below fails =
FAIL exit 1; all pass = PASS exit 0.

Run directly: python3 integration/t261004-22/sc_d2b_carrier_wait_contract.py (cwd = repo root).
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = ("server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py"
          "::test_d2b_carrier_detected_through_unresolved_root")
GENERIC_MSG = "carrier invisible through unresolved root"
PYTEST_BUDGET_S = 180          # generous: case C legitimately burns the deadline
GREEN_BUDGET_S = 90            # green path must stay far below its own deadline

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def venv_python():
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat 回落路径（t260907-10；摘除票删旧路径）
        if cand.is_file():
            return str(cand)
    return None


def make_stub_dir(stubs):
    """A directory of PATH stubs; TemporaryDirectory reclaims every exit path."""
    td = tempfile.TemporaryDirectory(prefix="t261004-22-s1-stubs-")
    d = Path(td.name)
    for name, body in stubs.items():
        p = d / name
        p.write_text("#!/bin/sh\n%s\n" % body, encoding="utf-8")
        p.chmod(0o755)
    return td, str(d)


def run_case(py, stubs):
    env = dict(os.environ)
    td = None
    if stubs is not None:
        td, stubdir = make_stub_dir(stubs)
        env["PATH"] = stubdir + os.pathsep + env.get("PATH", "")
    t0 = time.monotonic()
    try:
        # -ra: the short summary prints skip/fail reasons — with bare -q a named
        # skip degrades to a bare "1 skipped" and the reader never sees the
        # reason (gate arbitrate gen0: B4 false red on exactly this channel).
        r = subprocess.run([py, "-m", "pytest", TARGET, "-q", "-ra"],
                           cwd=str(REPO), env=env, capture_output=True,
                           text=True, timeout=PYTEST_BUDGET_S)
        rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = -99, "pytest timed out after %ss" % PYTEST_BUDGET_S
    finally:
        if td is not None:
            td.cleanup()
    return rc, out, time.monotonic() - t0


def main():
    py = venv_python()
    if not py or not (REPO / "server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py").is_file():
        print("ENV_FAIL: engine venv/pytest or the target test file is missing (py=%s)" % py,
              file=sys.stderr)
        return 2

    print("A green path (untouched environment)")
    rc, out, wall = run_case(py, None)
    ok(rc == 0, "A1 pytest exit 0 (got rc=%s)" % rc)
    ok("1 passed" in out, "A2 exactly the single case passed")
    ok(GENERIC_MSG not in out, "A3 green path never shows the regression message")
    ok(wall < GREEN_BUDGET_S,
       "A4 green wall clock %.1fs < %ss (poll must be cheap, fixed sleep gone)" % (wall, GREEN_BUDGET_S))
    print("     wall=%.1fs" % wall)

    print("B enumeration unavailable (pgrep stub exits 127)")
    rc, out, wall = run_case(py, {"pgrep": "exit 127"})
    ok(rc == 0, "B1 not a false red (got rc=%s)" % rc)
    ok("failed" not in out, "B2 zero failures in the run")
    ok("skipped" in out, "B3 the case is skipped, not silently passed")
    ok(("pgrep" in out) or ("enumeration" in out.lower()),
       "B4 the skip names the reason (pgrep/enumeration)")
    print("     wall=%.1fs tail=%r" % (wall, out.strip().splitlines()[-1:]))

    print("C cwd unresolvable (pgrep answers, lsof reports no cwd)")
    # pgrep answers 1 2; lsof resolves only pid 1 (args: -a -p PID -> $3 = PID),
    # so the test's own child never resolves while enumeration looks healthy.
    rc, out, wall = run_case(py, {"pgrep": "echo 1 2",
                                  "lsof": 'if [ "$3" = "1" ]; then echo n/tmp; fi'})
    ok(rc != 0, "C1 a genuine failure is a failure, not a pass (got rc=%s)" % rc)
    ok("failed" in out, "C2 the run reports the failure")
    ok(re.search(r"within\s+~?\s*\d+(\.\d+)?\s*s", out) is not None,
       "C3 the timeout names its deadline (within Ns)")
    ok("cwd" in out.lower(), "C4 the timeout names the cwd scan, not just 'no hit'")
    ok(GENERIC_MSG not in out, "C5 the generic carrier-is-invisible message is NOT shown")
    ok(wall < PYTEST_BUDGET_S, "C6 the burn is bounded by the deadline, not hung (%.1fs)" % wall)
    print("     wall=%.1fs" % wall)

    print("summary: pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
