#!/usr/bin/env python3
"""t261025-02 scenario: on an UNPOINTED per-ticket gate round the ticket's OWN
scenarios stay in the run list AND in the expected caliber, whatever pool
they live in (the KI-355 witness t261022-12: its own scenario lives in the
ENGINE pool, the gate excludes engine/exclusive wholesale AFTER the own set
is computed, and every round reported meta.last_green_run ran=0; user words:
'the per-ticket gate excludes engine/exclusive wholesale AFTER the own set is
computed, and an own scenario that lives in those pools disappears from the
run list').

intent (user-perceivable): a pool exclusion schedules work - it never drops
the ticket's own case, and it never breaks the round's completeness
arithmetic. t261024-40 already keeps the OWN entry on the run side of the
UNPOINTED path (the pool split), but the expected caliber still subtracts the
whole excluded pool, so the round self-reds on its own invariant
(ran > expected); this ticket moves the rule to the exclusion side so the
round is green and honest, and a declared OWN name that is genuinely absent
refuses BY NAME instead of round-tripping ran=0.

high-level steps: build a minimal REAL lane (real run_scenarios.py source,
mini registry whose OWN fixtures live under integration/t261025-02/ so the
own-set derivation matches, verify.yaml excluding engine,exclusive like the
live gate); drive the real executor as a subprocess, one UNPOINTED round
(no SANDBAR_SCENARIO_ONLY) per case on a fresh lane, and judge public faces
(exit code, INTEG_SUMMARY JSON, on-disk execution markers read reader-side):
  A THE WEDGE, POSITIVE - OWN in the engine pool + OWN in main + a NON-own in
    exclusive, own list declared: both OWN cases run (markers on disk,
    ran>=2), the NON-own excluded entry does NOT run, and the completeness
    invariant holds exactly (expected == ran, expected counts the kept
    engine-pool own entry once - the pre-fix tree reds here: the pool split
    runs it but the expected caliber subtracts it).
  B EXCLUSION CONTROL - the same shape with NO own list: the engine and
    exclusive entries stay dropped, only the main entry runs
    (expected == ran == 1), the skip face names the excluded pools, and no
    own-exemption keys leak into an own-less receipt (legacy byte-stable).
  C FAIL-CLOSED - a declared OWN name absent from the registry on an
    UNPOINTED round refuses BY NAME (non-zero rc, REFUSED shape naming the
    ghost) instead of silently running a subset while claiming own coverage;
    zero scripts executed.
  D MALFORMED - a whitespace-only own list behaves as absent on an UNPOINTED
    round: no phantom refusal, the exclusion economy of B stands.

Offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233. Intent split: the POINTED-path keep/refusal/roster faces belong
to t261024-40-own-scenario-gate-round; the ledger-reuse wedge belongs to
t261024-60-own-never-ledger-reused; the pool-exclusion knob consumption
matrix belongs to t260913-03; the narrowed-empty fallback contract belongs
to t260922-12; the engine-side faces (closing fast-union-own caliber,
own-coverage named red, stale-lane capability probe) belong to developer L1
batteries plus the engine-gate stage driving the two live lanes; THIS entry
uniquely owns 'the UNPOINTED gate round is green and complete with an own
scenario in a wholesale-excluded pool, and refuses by name when a declared
own name is genuinely absent'. Pre-implement tree red on A/C = the named TDD
signal; green required at the integration gate/merge. run_scenarios.py
missing = ENV_FAIL exit 2.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26102502_lane as F  # noqa: E402
from lib_env import clean_narrowing_env  # noqa: E402

C = F.Checker("t261025-02-own-never-peeled")

OWN_ENV = "SANDBAR_SCENARIO_OWN"
EXCLUDE_ENV = "SANDBAR_SCENARIO_EXCLUDE_POOLS"

if not F.RUNNER.is_file():
    print("ENV_FAIL run_scenarios.py missing at %s" % F.RUNNER)
    sys.exit(2)


def _round(root, name, env):
    """One UNPOINTED round on a fresh lane (fresh lane = no ledger rows, so
    the reuse economy never enters these faces)."""
    lane = F.build_lane(Path(root) / name)
    p = F.run_executor(lane["lane"], env=env)
    return lane, p


def _summary(p):
    s = F.integ_summary(p.stdout)
    return s if isinstance(s, dict) else {}


with tempfile.TemporaryDirectory(prefix="t261025-02-") as td:
    root = Path(td)

    # ------- A: the wedge - own in a wholesale-excluded pool stays counted --
    laneA, pA = _round(root, "laneA", {
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        OWN_ENV: "%s,%s" % (F.OWN_ENGINE, F.OWN_MAIN),
    })
    sA = _summary(pA)
    ranA = F.markers_ran(laneA)
    C.check(pA.returncode == 0, "A rc==0", "rc=%s out=%r" % (pA.returncode, pA.stdout[-400:]))
    C.check(F.OWN_ENGINE in ranA and F.OWN_MAIN in ranA,
            "A own cases ran (engine-pool own included)", "markers=%r" % ranA)
    C.check(F.NONOWN_EXCL not in ranA, "A non-own excluded entry stayed out",
            "markers=%r" % ranA)
    C.check(int(sA.get("ran", 0)) >= 2, "A ran>=2", "summary=%r" % (sA,))
    C.check(int(sA.get("expected", -1)) == int(sA.get("ran", -2)),
            "A completeness invariant expected==ran (own counted exactly once)",
            "summary=%r" % (sA,))

    # ------- B: exclusion control - no own list, economy byte-stable --------
    laneB, pB = _round(root, "laneB", {EXCLUDE_ENV: F.EXCLUDE_VALUE})
    sB = _summary(pB)
    ranB = F.markers_ran(laneB)
    C.check(pB.returncode == 0, "B rc==0", "rc=%s" % pB.returncode)
    C.check(ranB == [F.OWN_MAIN], "B only the main entry ran",
            "markers=%r" % ranB)
    C.check(int(sB.get("expected", -1)) == 1 and int(sB.get("ran", -1)) == 1,
            "B expected==ran==1 (excluded pools subtracted once)",
            "summary=%r" % (sB,))
    C.check("engine" in pB.stdout and "exclusive" in pB.stdout,
            "B skip face names the excluded pools", "stdout=%r" % pB.stdout[:600])
    C.check(not [k for k in sB if "own" in k and "known" not in k],
            "B no own-exemption keys leak into an own-less receipt",
            "summary keys=%r" % sorted(sB))

    # ------- C: declared own name genuinely absent -> refuse by name --------
    laneC, pC = _round(root, "laneC", {
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        OWN_ENV: "t261025-02-fx-ghost",
    })
    ranC = F.markers_ran(laneC)
    C.check(pC.returncode != 0, "C refuses (non-zero rc)", "rc=%s" % pC.returncode)
    C.check(F.refused_face(pC.stdout + pC.stderr), "C REFUSED shape present",
            "out=%r" % (pC.stdout[-400:] + pC.stderr[-200:]))
    C.check("ghost" in (pC.stdout + pC.stderr), "C refusal names the own name",
            "out=%r" % (pC.stdout[-400:] + pC.stderr[-200:]))
    C.check(ranC == [], "C zero scripts executed", "markers=%r" % ranC)

    # ------- D: malformed own env behaves as absent --------------------------
    laneD, pD = _round(root, "laneD", {
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        OWN_ENV: "   ",
    })
    sD = _summary(pD)
    ranD = F.markers_ran(laneD)
    C.check(pD.returncode == 0, "D rc==0 (no phantom refusal)", "rc=%s" % pD.returncode)
    C.check(ranD == [F.OWN_MAIN], "D exclusion economy stands", "markers=%r" % ranD)
    C.check(int(sD.get("expected", -1)) == 1, "D expected==1", "summary=%r" % (sD,))

    sys.exit(C.finish())
