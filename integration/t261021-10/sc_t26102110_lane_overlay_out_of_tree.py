#!/usr/bin/env python3
"""t261021-10 scenario: the lane sandbox overlay lives OUTSIDE the measured
tree, and a static brake refuses any in-tree regrowth (grey-box L3, the REAL
integration/lib_lane_overlay.py + the REAL integration/lint_tests.py over tmp
fixtures, offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233).

intent (user-perceivable; ticket t261021-10, incident = t261021-05 blocked at
arbitrate by path_gate@arbitrate / unauthorized_path on
integration/t261021-05/overlay/server/engine/.venv — a scratch overlay the
lane's scenario sandbox materialised INSIDE the ticket worktree, so the stage
path gate auto-quarantined it and the ticket could not settle; chosen option A:
the overlay home moves out of the measured tree, the gate itself is untouched):
  A THE HOME JOURNEY — a lane asks the shared helper for its overlay home and
    gets a path OUTSIDE the repo tree (the gate never measures it); an overlay
    materialised there (mirrored bit + a venv-shaped symlink, the incident
    shape) is judged LAWFUL by the one predicate, and dispose reclaims the
    whole tree (reader-side: the directory is gone from disk, not from a
    writer receipt).
  B BOTH DIRECTIONS, THE TICKET'S HARD RULE — inside a tmp fixture repo, a
    path under integration/<ticket>/overlay/ is REFUSED and a HAND-WRITTEN
    file next to it under integration/<ticket>/ is REFUSED too (the fix opens
    nothing about integration/ generally); only the declared out-of-tree root
    is admitted. One predicate, one place, both directions proven.
  C THE STATIC BRAKE — the real lint reds on a planted in-tree overlay dir in
    a throwaway copy (its output NAMES the path and points at the helper as
    the lawful home) and stays silent on the same copy without the fixture.
  D MALFORMED INPUT, FAIL-CLOSED — an empty ticket id and a '../'-traversal id
    never yield a path; an env knob pointed INTO the repo tree either raises
    or yields a path the predicate refuses (the knob cannot re-import the
    incident). Nothing is created on any refusal.

high-level steps: import the real helper module; for A ask for the home, assert
it is outside the repo root this scenario runs in, materialise the incident
shape there, judge lawfulness, dispose, judge the disk; for B build a tmp fake
repo with the refused shapes and judge the predicate both ways; for C copy the
real lint script into a tmp tree twice (with/without a planted
integration/zz-l26-fixture/overlay/) and judge its output text; for D drive
the helper with malformed ids and a poisoned env knob. Intent split (no
intent-level duplication): the predicate/env-knob unit truth table and the
lint rule's internals belong to developer L1 (integration/tests/
test_lib_lane_overlay.py); the settle-side unauthorized-write/disposal journeys
belong to t260911-03 and t261016-19 (different faces: those judge the SETTLE
gate over delivered files, this entry owns the overlay HOME contract and the
lint brake that stops the pattern regrowing).

Pre-implement tree: missing helper module = ENV_FAIL exit 2 (supply face);
A-D red = the named TDD signal; green required at the integration gate /
merge. Binding note: the helper's public names (overlay_root /
overlay_path_is_lawful / build_overlay / dispose_overlay) and the lint rule
label L26 are the plan-declared contract of this ticket, not implementation
accidents.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TAG = "t261021-10-lane-overlay-out-of-tree"
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]          # integration/t261021-10/ -> repo root
INTEG = REPO / "integration"
LIB = INTEG / "lib_lane_overlay.py"
LINT = INTEG / "lint_tests.py"

failures = []
env_reds = []
na = 0


def check(cond, label, detail=""):
    global na
    if cond:
        print("ok   %s" % label)
    else:
        print("red  %s  %s" % (label, detail))
        failures.append("%s %s" % (label, detail))


def na_if(cond, label, detail=""):
    """A system-state-conditioned subface: N/A is recorded, never silent."""
    global na
    if cond:
        print("n/a  %s  %s" % (label, detail))
        na += 1
        return True
    return False


def under(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def main():
    if not LIB.exists():
        env_reds.append("supply: %s missing (pre-implement or moved)" % LIB)
        return
    sys.path.insert(0, str(INTEG))   # the helper lives in integration/, the script does not
    try:
        import lib_lane_overlay as llo
    except Exception as exc:
        env_reds.append("supply: lib_lane_overlay unimportable: %r" % exc)
        return

    tmp = Path(tempfile.mkdtemp(prefix="sandbar-sc-t26102110-"))
    try:
        # ---- A: the home journey, out of the measured tree ----
        try:
            home = Path(str(llo.overlay_root("t261021-10")))
        except Exception as exc:
            env_reds.append("supply: overlay_root raised on a lawful id: %r" % exc)
            return
        check(not under(home, REPO),
              "A1 overlay home sits OUTSIDE the repo tree the gate measures",
              "home=%s repo=%s" % (home, REPO))
        incident = home / "server" / "engine" / ".venv"   # the incident shape
        incident.parent.mkdir(parents=True, exist_ok=True)
        incident.symlink_to(str(REPO / "server" / "engine"), target_is_directory=True)
        (home / "fixtures").mkdir(exist_ok=True)
        (home / "fixtures" / "f.txt").write_text("x", encoding="utf-8")
        check(llo.overlay_path_is_lawful(str(home), str(REPO)),
              "A2 the materialised out-of-tree overlay is LAWFUL (one predicate, positive direction)",
              "home=%s" % home)
        disposed = False
        for name in ("dispose_overlay", "dispose", "reclaim_overlay"):
            fn = getattr(llo, name, None)
            if fn is not None:
                fn("t261021-10")
                disposed = True
                break
        check(disposed and not home.exists(),
              "A3 dispose reclaims the whole overlay tree (reader-side: gone from disk)",
              "disposed=%s home_exists=%s" % (disposed, home.exists()))

        # ---- B: both directions inside a tmp fixture repo ----
        fake = tmp / "fake-repo"
        (fake / "integration" / "t261021-05" / "overlay" / "server" / "engine").mkdir(parents=True)
        (fake / "integration" / "t261021-05" / "overlay" / "server" / "engine" / ".venv").write_text(
            "link", encoding="utf-8")
        (fake / "integration" / "t261021-05" / "hand_written.txt").write_text(
            "a human deliverable", encoding="utf-8")
        check(not llo.overlay_path_is_lawful(
                str(fake / "integration" / "t261021-05" / "overlay" / "server" / "engine" / ".venv"),
                str(fake)),
              "B1 a path under integration/<ticket>/overlay/ is REFUSED (the exact incident shape)",
              "")
        check(not llo.overlay_path_is_lawful(
                str(fake / "integration" / "t261021-05" / "hand_written.txt"), str(fake)),
              "B2 a HAND-WRITTEN file next to it under integration/<ticket>/ is refused too — "
              "the fix opens nothing about integration/ generally",
              "")

        # ---- C: the static brake, real lint over a throwaway copy ----
        if LINT.exists():
            tree = tmp / "lint-tree" / "integration"
            tree.mkdir(parents=True)
            lint_copy = tree / "lint_tests.py"
            shutil.copy2(str(LINT), str(lint_copy))
            for py in sorted(INTEG.glob("*.py")):        # the lint imports its siblings
                shutil.copy2(str(py), str(tree / py.name))
            probe = "integration/zz-l26-fixture/overlay/x.txt"

            def run_lint():
                # SANCTIONED-WAIT: hard ceiling on the seconds-scale lint subprocess
                p = subprocess.run([sys.executable, "-B", "integration/lint_tests.py"],
                                   cwd=str(tmp / "lint-tree"), capture_output=True, text=True,
                                   # SANCTIONED-WAIT: hung lint must fail this scenario, not the round
                                   timeout=300)
                return (p.stdout or "") + (p.stderr or "")
            (tree / "zz-l26-fixture" / "overlay").mkdir(parents=True)
            (tree / "zz-l26-fixture" / "overlay" / "x.txt").write_text("x", encoding="utf-8")
            planted = run_lint()
            shutil.rmtree(str(tree / "zz-l26-fixture"))
            clean = run_lint()
            l26_planted = [ln for ln in planted.splitlines()
                           if "L26" in ln and "zz-l26-fixture" in ln]
            check(bool(l26_planted),
                  "C1 the lint REDS on the planted in-tree overlay dir and NAMES the path",
                  "no L26 line naming zz-l26-fixture; tail=%r" % planted[-400:])
            check(any("overlay_root" in ln or "lib_lane_overlay" in ln for ln in l26_planted),
                  "C2 the red text points at the helper as the lawful home (named, not silent)",
                  "lines=%r" % l26_planted[:3])
            l26_clean = [ln for ln in clean.splitlines()
                         if "L26" in ln and "zz-l26-fixture" in ln]
            check(not l26_clean,
                  "C3 the same copy without the fixture stays silent about the brake",
                  "lines=%r" % l26_clean[:3])
        else:
            env_reds.append("supply: %s missing (lint face C could not run)" % LINT)

        # ---- D: malformed input, fail-closed ----
        poisoned = dict(os.environ)
        poisoned["SANDBAR_LANE_OVERLAY_ROOT"] = str(fake / "integration" / "t261021-05" / "overlay")

        def refused(fn):
            try:
                v = fn()
            except Exception:
                return True          # named refusal is a lawful fail-closed shape
            return v is None or not llo.overlay_path_is_lawful(str(v), str(REPO))
        check(refused(lambda: llo.overlay_root("")),
              "D1 an empty ticket id never yields a lawful path (raise or refuse)",
              "")
        check(refused(lambda: llo.overlay_root("../../etc")),
              "D2 a '../'-traversal ticket id never yields a lawful path",
              "")
        check(refused(lambda: llo.overlay_root("t-ok", env=poisoned)),
              "D3 an env knob pointed INTO the repo tree cannot re-import the incident "
              "(raise or a path the predicate refuses)",
              "")
        check(not (fake / "integration" / "t261021-05" / "overlay" / "sandbar-lane-overlay").exists()
              and not (REPO / "sandbar-lane-overlay").exists(),
              "D4 no refusal left a directory behind (fail-closed means fail-quiet too)",
              "")
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


try:
    main()
except SystemExit:
    raise
except Exception as exc:  # environment-level failure: the scenario could not run
    import traceback
    traceback.print_exc()
    print("ENV_FAIL [%s] %s: %r" % (TAG, type(exc).__name__, exc))
    sys.exit(2)

if env_reds:
    print("ENV_FAIL [%s] %d env red: %s" % (TAG, len(env_reds), "; ".join(env_reds)))
    sys.exit(2)
if failures or na:
    print("FAILED [%s] %d red, %d n/a: %s" % (TAG, len(failures), na, "; ".join(failures)))
    sys.exit(1)
print("PASS [%s] all legs green" % TAG)
sys.exit(0)
