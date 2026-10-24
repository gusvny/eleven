#!/usr/bin/env python3
"""t261024-40 scenario: a ticket's OWN scenario is never peeled out of its
gate round, whatever pool it lives in (the t261022-14 landing-starvation
incident, user words: 'its own scenario ... is in the browser-free pool and
passes alone ... the run list was emptied ... every landing is refused').

intent (user-perceivable): the gate round's run list keeps the change's OWN
declared scenario (the integration/<ticket_id>/ derived set) even when a
supply-side filter - the lane's pool exclusion or the known-red roster skip -
would drop it; a cheap pool is a scheduling property, not a drop reason.
When the ticket genuinely has no own scenario, the round refuses BY NAME
(which face was expected, why the derived set was empty) instead of reporting
a legal-looking ran=0 that starves the landing anchor (KI-220).

high-level steps: build a minimal REAL lane (real run_scenarios.py source,
mini registry whose fixture entries live under integration/t261024-40/ so the
own-set derivation matches, real pool-exclusion consumption, fixture roster);
drive the real executor as a subprocess per case and judge the user-visible
receipt faces (SCENARIOS counts, INTEG_SUMMARY, marker files on disk):
  A THE INCIDENT SHAPE, POSITIVE - own scenario in an EXCLUDED pool, prev-red
    pointed name dropped too: the own case still runs (ran>=1), its marker is
    on disk, the kept decision is named, and the summary carries the
    attribution face (which name was dropped by which filter).
  B ROSTER - the own scenario booked in the known-red roster still runs and
    is named; a NON-own booked entry stays skipped (t260930-01 economy kept).
  C FAIL-CLOSED - an OWN name missing from the registry refuses rc=2 in the
    REFUSED shape naming it as an OWN scenario; zero scripts executed.
  D LEGACY PRESERVED - with no own list the current contracts are byte-stable:
    a fully-dropped pointed round still widens (INTEG_NARROWED_EMPTY face) and
    the receipt carries no own-exemption keys (additive-only drift).
  E MALFORMED - a whitespace/empty SANDBAR_SCENARIO_OWN value behaves as
    absent, never as a phantom drop or a crash.

Offline seconds, zero docker/Temporal-server/browser, never touches 3099/7233.
Intent split: the empty-derivation refusal copy and the args/env threading
belong to developer L1 (test_t261018_01 / test_t260922_12 batteries per plan
gen1); the pool-exclusion switch forms and the narrowed-empty fallback
contract have their own entries (t260913-03, t260922-12 battery) and are only
asserted here as the legacy-preservation control. THIS entry uniquely owns
'own scenario stays in the run across both supply-side filters, with the
drop-attribution face on the receipt'. Pre-implement tree red on A/B/C = the
named TDD signal (the OWN face is absent); green required at the integration
gate/merge. run_scenarios.py missing = ENV_FAIL exit 2.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26102440_lane as F  # noqa: E402
from lib_env import clean_narrowing_env  # noqa: E402

C = F.Checker("t261024-40-own-scenario-gate-round")

OWN_ENV = "SANDBAR_SCENARIO_OWN"
ONLY_ENV = "SANDBAR_SCENARIO_ONLY"
EXCLUDE_ENV = "SANDBAR_SCENARIO_EXCLUDE_POOLS"
KR_EXCLUDE_ENV = "SANDBAR_KNOWN_RED_EXCLUDE"
KR_ROSTER_ENV = "SANDBAR_KNOWN_RED_ROSTER"

OWN = "t261024-40-fx-own"        # pool browser-free (the cheap pool)
OTHER = "t261024-40-fx-other"    # pool exclusive (the prev-red stand-in)
SPEC = [(OWN, "browser-free"), (OTHER, "exclusive")]

if not (F.RUNNER).is_file():
    print("ENV_FAIL run_scenarios.py missing at %s" % F.RUNNER)
    sys.exit(2)


def _markers(lane, names):
    return {n: (F.Path(lane) / ("marker-%s" % n)).exists() for n in names}


def _keep_face(out):
    """The named own-kept decision face (stable substrings, copy is text)."""
    return ("OWN_KEPT" in out) or ("own_kept" in out)


with tempfile.TemporaryDirectory(prefix="t261024-40-") as td:
    root = Path(td)

    # ---------------- A: incident shape - own in excluded pool still runs -----
    laneA = F.build_lane(root / "laneA", SPEC, exclude_pools=F.EXCLUDE_VALUE)
    p = F.run_executor(laneA["lane"], env={
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        # the real gate round points own ∪ prev-reds (dev_lane scoped
        # feedback face); the prev-red name, pool exclusive -> dropped
        ONLY_ENV: "%s,%s" % (OTHER, OWN),
        OWN_ENV: OWN,             # the change's own declared scenario
    })
    mk = _markers(laneA["lane"], (OWN, OTHER))
    summ = F.integ_summary(p.stdout)
    C.check(p.returncode == 0,
            "A1 round is judged (rc=0), never a supply-side refusal",
            "rc=%s tail=%s" % (p.returncode, p.stdout[-300:]))
    C.check(mk[OWN] and not mk[OTHER],
            "A2 the OWN scenario ran (marker on disk); the dropped name did not",
            "markers=%s" % mk)
    counts = F.summary_line(p.stdout)
    C.check("ran=1" in counts,
            "A3 receipt counts ran>=1 containing the own scenario",
            "summary=%s" % counts)
    C.check("INTEG_OWN_KEPT" in p.stdout,
            "A4 the keep decision is NAMED on the round (INTEG_OWN_KEPT face)",
            "tail=%s" % p.stdout[-400:])
    plan = F.only_plan(laneA["lane"], p.stdout)
    C.check(isinstance(plan, dict) and OTHER in json.dumps(plan),
            "A5 attribution face names the dropped pointed name and its filter",
            "plan=%r" % (plan,))
    C.check(isinstance(summ, dict) and summ.get("expected") == 1,
            "A6 expected counted once for the own-exempt entry (no double cut)",
            "summary=%r" % (summ,))

    # ---------------- B: roster-booked own still runs, economy kept ----------
    laneB = F.build_lane(root / "laneB",
                         [(OWN, "browser-free"), (OTHER, "main")],
                         exclude_pools=F.EXCLUDE_VALUE)
    roster = F.roster_file(laneB["lane"], [OWN, OTHER])
    p = F.run_executor(laneB["lane"], env={
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        KR_EXCLUDE_ENV: "1",
        KR_ROSTER_ENV: str(roster),
        ONLY_ENV: "%s,%s" % (OTHER, OWN),
        OWN_ENV: OWN,
    })
    mk = _markers(laneB["lane"], (OWN, OTHER))
    C.check(p.returncode == 0 and mk[OWN],
            "B1 the roster-booked OWN scenario still runs and is named",
            "rc=%s markers=%s tail=%s" % (p.returncode, mk, p.stdout[-300:]))
    C.check("INTEG_KNOWN_RED" in p.stdout and OTHER in p.stdout.split("INTEG_OWN_KEPT")[0],
            "B2 the NON-own roster skip stays named with its entry",
            "tail=%s" % p.stdout[-400:])
    C.check(not mk[OTHER],
            "B3 the NON-own booked entry stays skipped (t260930-01 economy kept)",
            "markers=%s" % mk)

    # ---------------- C: own name missing from registry -> fail-closed -------
    laneC = F.build_lane(root / "laneC", SPEC, exclude_pools=F.EXCLUDE_VALUE)
    p = F.run_executor(laneC["lane"], env={
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        ONLY_ENV: "t261024-40-fx-ghost",
        OWN_ENV: "t261024-40-fx-ghost",
    })
    mk = _markers(laneC["lane"], (OWN, OTHER))
    C.check(p.returncode == 2 and "REFUSED [" in p.stdout,
            "C1 an unregistered OWN name refuses rc=2 in the REFUSED shape",
            "rc=%s head=%s" % (p.returncode, p.stdout[:200]))
    C.check("t261024-40-fx-ghost" in p.stdout,
            "C2 the refusal NAMES the missing own scenario (never anonymous)",
            "head=%s" % p.stdout[:300])
    C.check(not any(mk.values()),
            "C3 nothing ran on the refusal (zero side effects)",
            "markers=%s" % mk)

    # ---------------- D: legacy preserved when the own list is absent --------
    laneD = F.build_lane(root / "laneD", SPEC, exclude_pools=F.EXCLUDE_VALUE)
    p = F.run_executor(laneD["lane"], env={
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        ONLY_ENV: OTHER,
    })
    C.check("INTEG_NARROWED_EMPTY" in p.stdout,
            "D1 without an own list the narrowed-empty widen contract stands",
            "tail=%s" % p.stdout[-300:])
    summ = F.integ_summary(p.stdout)
    planD = F.only_plan(laneD["lane"], p.stdout)
    C.check(isinstance(summ, dict) and "only_plan" not in summ
            and (planD is None or (planD.get("own") == []
                                   and planD.get("own_kept") == [])),
            "D2 an own-less round carries no own-exemption effect "
            "(attribution face stays additive, own lists empty)",
            "summary=%r plan=%r" % (summ, planD))
    laneD2 = F.build_lane(root / "laneD2", SPEC, exclude_pools=F.EXCLUDE_VALUE)
    p2 = F.run_executor(laneD2["lane"], env={})
    mk2 = _markers(laneD2["lane"], (OWN, OTHER))
    C.check(p2.returncode == 0 and all(mk2.values()),
            "D3 an unpointed, exclusion-free round with no own list runs all as today",
            "rc=%s markers=%s" % (p2.returncode, mk2))

    # ---------------- E: malformed own value degrades to absent --------------
    laneE = F.build_lane(root / "laneE", SPEC, exclude_pools=F.EXCLUDE_VALUE)
    p = F.run_executor(laneE["lane"], env={
        EXCLUDE_ENV: F.EXCLUDE_VALUE,
        OWN_ENV: "  , ,, ",
    })
    C.check(p.returncode == 0 and "INTEG_NARROWED_EMPTY" not in p.stdout,
            "E1 a whitespace-only own value behaves as absent (no phantom face)",
            "rc=%s tail=%s" % (p.returncode, p.stdout[-300:]))

sys.exit(C.finish())
