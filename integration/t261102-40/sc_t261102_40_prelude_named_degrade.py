#!/usr/bin/env python3
"""t261102-40 scenario: the suite NAMES an unavailable test bench and still runs
its cases, and a lane that carries the bench module finishes the same round with
a bounded prelude.

Incident (line head 2d2d42a8, measured by the integration gate): the two incident
fixtures failed at their 120 s cap and capture-redline-gate timed out, because the
nested suite they spawn exited rc=1 after 140.2 s - ``_provision_test_target`` ->
``_bench_module`` raised ``ModuleNotFoundError`` for a lane that copies only a
subset of ``integration/``, after the prelude had already burned a 120 s docker
prune timeout plus a 20 s daemon probe. User words: "the suite's test-target
provisioning now hard-requires integration/process_bench.py, while fixture lanes
copy only a subset of integration/ - the lane crashes instead of degrading".

intent (user-perceivable): a suite round in a tree whose bench module is missing
or broken degrades to the SAME named outcome the suite already prints for a
refused binary ("NO TEST TARGET") and still runs its scenario children - it never
crashes. A lane that carries the module finishes the round with a bounded prelude
(the 140 s prelude must not come back), and the nested round resolves its own
test target instead of inheriting the parent round's statement.

high-level steps: build a minimal REAL lane per case (real ``run_scenarios.py``
source with an injected two-entry mini registry, real prelude, real provision,
real child spawns; only the registry contents and ``stage_docker.py`` are stubs),
drive the real executor as a subprocess (bounded, process group killed on expiry)
and judge public faces - the round's exit code, its stderr copy, its
``INTEG_SUMMARY`` receipt, the ``prelude-legs`` line and the on-disk execution
markers (read reader-side):

  A THE INCIDENT SHAPE - the lane carries the runner and the judge-face modules
    but NOT ``process_bench.py``: exit 0 with no traceback, both stub children ran
    (markers on disk), the provision prints the named NO TEST TARGET line and
    names ``process_bench.py missing at <lane>/integration/process_bench.py``, and
    the receipt's ``test_target`` block reads ``source="absent"`` with that
    ``absent_reason`` (value null). A missing module degrades; it never crashes.
  B THE LANE THAT CARRIES THE ASSETS - the same round with ``process_bench.py``,
    ``bench_deadman.py`` and the batch manifest present (the bench binary is pinned
    to a nonexistent path, so no server is started): exit 0, children ran, no
    traceback, the ``prelude-legs`` line carries a numeric ``test_target`` leg and
    a total below the 30 s bound, the receipt's ``test_target.source`` is one of
    ``absent``/``reused`` and never ``ambient`` (the lane cleared the inherited
    statement), and the lane's bench registry holds no entry (nothing was started).
  C MALFORMED MODULE - a ``process_bench.py`` that is present and raises at
    import: exit 0, children ran, no traceback, and the named line says
    ``present at ... but failed to import`` with the error type - a broken bench
    is a code fault named as one, never read as an environment absence (the
    "missing" wording must not appear for it).

Intent split: the provisioning truth tables over a fake bench (the two-wordings
note, the ambient branch, the teardown-after-import state) belong to developer L1
(``integration/tests/test_t261101_20_suite_test_target.py``); the probe matrix,
the lane-contract copies and the nested-env clearing belong to developer L1
(``integration/tests/test_t261102_40_suite_prelude_budget.py``); the own-set and
exclusion faces of the two incident fixtures stay theirs (t261024-40, t261025-02);
THIS entry uniquely owns the nested-round journey - a real suite round that
degrades by name and still runs its children.

Pre-implement tree red on A = the named TDD signal; green required at the
integration gate/merge. ``integration/run_scenarios.py`` missing = ENV_FAIL exit 2.
Grey-box L3, offline seconds, zero docker stage, zero Temporal server, never
touches 3099/7233.
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib_t26110240_lane as F  # noqa: E402  (lane builder + round driver)

PRELUDE_BOUND_S = F.PRELUDE_BOUND_S   # one spelling: the shared contract


class Checker:
    def __init__(self, title):
        self.title = title
        self.passed = 0
        self.failed = 0

    def check(self, cond, label, detail=""):
        if cond:
            self.passed += 1
            print("  ok %s" % label, flush=True)
        else:
            self.failed += 1
            print("  FAIL %s  [%s]" % (label, detail), flush=True)
        return bool(cond)

    def finish(self):
        print("\n%s: SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (self.title, self.passed, self.failed), flush=True)
        return 1 if self.failed else 0


C = Checker("t261102-40-prelude-named-degrade")


def _round_faces(label, run, lane, want_sources):
    """Judge the faces every case shares: exit, crash, children, receipt source."""
    C.check(not run["timed_out"],
            "%s round finishes inside the hang guard" % label,
            "timed out after %ss" % F.ROUND_WAIT_S)
    C.check(run["rc"] == 0,
            "%s round exits 0 (the prelude degrades, it never crashes)" % label,
            "rc=%r tail=%r" % (run["rc"], run["both"][-400:]))
    C.check(F.traceback_free(run["both"]),
            "%s no traceback leaves the prelude" % label,
            "traceback in output: %r" % run["both"][-400:])
    C.check(F.markers_ran(lane) == sorted(n for n, _ in F.MINI),
            "%s every stub child ran (markers on disk, reader side)" % label,
            "markers=%r" % F.markers_ran(lane))
    s = F.summary(run["out"]) or {}
    tt = s.get("test_target") or {}
    C.check(s.get("ran") == len(F.MINI),
            "%s the round counted both entries" % label, "summary=%r" % s)
    C.check(tt.get("source") in want_sources,
            "%s the receipt states a resolved target (%s)"
            % (label, "/".join(want_sources)), "test_target=%r" % tt)
    C.check(tt.get("source") != "ambient",
            "%s the nested run resolved its own target (never ambient)" % label,
            "test_target=%r" % tt)
    return tt


def case_a(work):
    lane = F.build_lane(work / "a", asset="absent")
    C.check(not any(k in lane["env"] for k in F.PRELUDE.SUITE_TARGET_ENV_NAMES),
            "A the lane clears the parent round's test-target statement",
            "env carries %r" % [k for k in F.PRELUDE.SUITE_TARGET_ENV_NAMES
                                if k in lane["env"]])
    run = F.run_round(lane["lane"])
    missing = str(Path(lane["lane"]) / "integration" / "process_bench.py")
    C.check("NO TEST TARGET for scenario children:" in run["err"],
            "A the provision prints the SAME named NO TEST TARGET line",
            "stderr=%r" % run["err"][-500:])
    C.check(missing in run["err"] and "missing" in run["err"],
            "A the named absence names the missing module path and says missing",
            "stderr=%r" % run["err"][-500:])
    tt = _round_faces("A", run, lane, ("absent",))
    C.check(tt.get("value") is None,
            "A the receipt states no address (value null)", "test_target=%r" % tt)
    C.check("process_bench.py missing at" in str(tt.get("absent_reason") or ""),
            "A the receipt's absent_reason carries the missing-module wording",
            "absent_reason=%r" % tt.get("absent_reason"))


def case_b(work):
    lane = F.build_lane(work / "b", asset="real")
    no_bin = str(Path(lane["lane"]) / "no-such-temporal")
    run = F.run_round(lane["lane"], extra={"SANDBAR_TEMPORAL_BIN": no_bin})
    legs = F.prelude_legs(run["out"])
    C.check(legs is not None,
            "B the round prints the prelude-legs line", "stdout=%r" % run["out"][-500:])
    C.check(isinstance(legs, dict) and isinstance(legs.get("test_target"), float),
            "B the prelude-legs line carries a numeric test_target leg",
            "legs=%r" % legs)
    C.check(bool(legs) and legs.get("sum", float("inf")) <= PRELUDE_BOUND_S,
            "B the nested prelude stays inside the %.0f s bound" % PRELUDE_BOUND_S,
            "legs=%r" % legs)
    tt = _round_faces("B", run, lane, ("absent", "reused"))
    C.check(not any(k in lane["env"] for k in F.PRELUDE.SUITE_TARGET_ENV_NAMES),
            "B the lane clears the parent round's test-target statement",
            "env carries %r" % [k for k in F.PRELUDE.SUITE_TARGET_ENV_NAMES
                                if k in lane["env"]])
    reg = Path(lane["lane"]) / F.PRELUDE.REGISTRY_DIRNAME
    reg_entries = sorted(reg.glob("*.json")) if reg.is_dir() else []
    C.check(not reg_entries,
            "B no bench was started (the lane registry holds no entry)",
            "registry=%r" % [p.name for p in reg_entries])
    C.check(not run["timed_out"] and run["rc"] == 0
            and F.traceback_free(run["both"])
            and F.markers_ran(lane) == sorted(n for n, _ in F.MINI),
            "B the asset-carrying round is green with both children on disk",
            "rc=%r markers=%r" % (run["rc"], F.markers_ran(lane)))


def case_c(work):
    lane = F.build_lane(work / "c", asset="broken")
    run = F.run_round(lane["lane"])
    present = str(Path(lane["lane"]) / "integration" / "process_bench.py")
    C.check("NO TEST TARGET for scenario children:" in run["err"],
            "C the provision prints the SAME named NO TEST TARGET line",
            "stderr=%r" % run["err"][-500:])
    C.check(present in run["err"] and "present at" in run["err"]
            and "failed to import" in run["err"],
            "C the named line says present ... but failed to import",
            "stderr=%r" % run["err"][-500:])
    C.check("RuntimeError" in run["err"],
            "C the named line carries the error type", "stderr=%r" % run["err"][-500:])
    tt = _round_faces("C", run, lane, ("absent",))
    reason = str(tt.get("absent_reason") or "")
    C.check("failed to import" in reason,
            "C the receipt names the code fault, not an environment absence",
            "absent_reason=%r" % reason)
    C.check("missing at" not in reason,
            "C the broken module is never read as a missing file",
            "absent_reason=%r" % reason)


def main():
    work = Path(tempfile.mkdtemp(prefix="t261102-40-prelude-"))
    try:
        case_a(work)
        case_b(work)
        case_c(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return C.finish()


if __name__ == "__main__":
    if not F.RUNNER.is_file():
        print("ENV_FAIL [t261102-40-prelude-named-degrade] %s missing - the suite "
              "cannot be driven" % F.RUNNER, flush=True)
        sys.exit(2)
    sys.exit(main())
