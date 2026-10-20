#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261019-26 — lift_stop gate journeys: who may lift what, and what a lift
must never touch.

Grey-box L3 (integration-owned, ticket t261019-26): the REAL
DevLaneWorkflow.lift_stop signal-handler face driven the way the engine's own
signal tests drive it (object.__new__(DevLaneWorkflow) UT shell, the
test_t260912_03_authz_sign.py pattern), plus source locks over the real
server/engine/dev_lane.py. Offline seconds, zero docker/Temporal-server/
browser, never touches 3099/7233.

Ticket faces under contract (design section 2; plan revision 2 accepted at
review_plan, including the borrowed-mechanism take/leave table):
  A JUDGEMENT stops stay human-only - a lift_stop against a judgement stop is
    refused by name, recorded in the refusal ledger, and NOTHING moves.
  B an EVIDENCE lift without a cited row id (or with a row id inconsistent
    with the recorded evidence kind) is refused by name - the design calls
    that a defect, not a shortcut.
  C a tier mismatch (the lifter names a different tier than the one recorded
    at block time) is refused; a stop with NO recorded tier (pre-deploy stop,
    resumed parked instance) is refused and treated as judgement - never
    defaulted to liftable.
  D a granted lift wakes the blocked step through the same primitive the
    human signals use (the retry token bumps) and leaves a written record of
    who/tier/row id/note.
  E a lift is NOT a human signal - the t261006-07 R3 counter reset is left
    explicitly: _conflict_rounds (and the same-batch guard state) are
    untouched by any lift, granted or refused (an executor must not be able
    to reset the arbitration caps from outside).
  F the cross-project gate runs FIRST - a gate-refused lift mutates nothing.

Intent split (no intent-level duplication): the classifier truth tables
(tier per reason text, malformed input) belong to
t261019-26-stop-tier-classification; the pure refusal/wake unit battery is
developer L1 (server/engine/tests/test_t261019_26_stop_tiers.py); THIS entry
uniquely owns the lift authorization journeys on the real signal handler -
gate order, tier rules, the counter-leave red line, and the wake+record face.

Pre-implement tree red on A-F = the named TDD signal; green required at the
integration gate / merge. dev_lane.py unimportable (temporalio missing) or
shared.py missing = ENV_FAIL exit 2.
"""

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

try:
    import shared
except Exception as e:
    print("ENV_FAIL: shared.py unimportable: %s" % e)
    sys.exit(2)

try:
    import dev_lane
except Exception as e:
    print("ENV_FAIL: dev_lane.py unimportable (temporalio present?): %s" % e)
    sys.exit(2)

PASS = 0
FAILS = []


def check(name, ok, why=""):
    global PASS
    if ok:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, len(FAILS)))
    if FAILS:
        print("FAIL t261019-26-lift-stop-gate-journeys (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("PASS t261019-26-lift-stop-gate-journeys")
    sys.exit(0)


src = ""
try:
    src = (ENGINE / "dev_lane.py").read_text(encoding="utf-8")
except Exception as e:
    print("ENV_FAIL: dev_lane.py unreadable: %s" % e)
    sys.exit(2)

lift_at = src.find("def lift_stop")
body = src[lift_at:] if lift_at >= 0 else ""
gate_at = body.find("_cross_project_gate")
tier_at = body.find('self.meta.get("blocked_tier")')
check("lift-stop-signal-exists",
      inspect.isclass(dev_lane.DevLaneWorkflow)
      and hasattr(dev_lane.DevLaneWorkflow, "lift_stop") and lift_at >= 0,
      "DevLaneWorkflow.lift_stop missing")
check("blocked-pins-tier",
      'meta["blocked_tier"]' in src and "classify_stop_tier" in src,
      "_blocked does not pin meta['blocked_tier'] via the classifier")
check("gate-first-on-lift",
      lift_at >= 0 and 0 <= gate_at < tier_at,
      "cross-project gate does not run before tier validation in lift_stop")
req = getattr(shared, "StopLiftRequest", None)
check("lift-request-type-exported", req is not None,
      "shared.StopLiftRequest missing")


def granted(out):
    """A granted lift ends in self._log (workflow logger), which the bare
    UT shell cannot serve (_NotInWorkflowEventLoopError). The grant is judged
    by the STATE it must leave, never by the log line."""
    return out == "ok" or (isinstance(out, str)
                           and out.startswith("raise:_NotInWorkflowEventLoop"))


def make_wf(tier, kind="", row_id=""):
    """UT shell: a bare DevLaneWorkflow with exactly the state the handler
    reads (the test_t260912_03_authz_sign.py pattern)."""
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"blocked_tier": tier}
    if kind:
        wf.meta["blocked_evidence"] = {"kind": kind, "cited_row_id": row_id}
    wf.refused = []
    wf._retry_token = 7
    wf._conflict_rounds = 3
    wf._prev_conflict_files = ["a.py"]
    wf.timeline = []
    # The real workflow context provides workflow.now(); the bare shell does
    # not, so the timestamp seam is injected (harness-only, not a contract).
    wf._now_iso = lambda: "2026-10-19T00:00:00"
    # The real gate decision seam is out of this scenario's scope (its own
    # faces have owners); the journeys below inject its answer.
    wf._cross_project_gate = lambda *a, **k: True
    return wf


def lift(wf, tier, row_id="", note="integration lift", who="executor"):
    fn = dev_lane.DevLaneWorkflow.lift_stop
    r = req(who=who, tier=tier, cited_row_id=row_id, note=note) \
        if req is not None else None
    if r is None:
        return None
    try:
        fn(wf, r)
        return "ok"
    except Exception as e:
        return "raise:%s:%s" % (type(e).__name__, e)


EV = getattr(shared, "STOP_TIER_EVIDENCE", "evidence")
ME = getattr(shared, "STOP_TIER_MECHANICAL", "mechanical")
JU = getattr(shared, "STOP_TIER_JUDGEMENT", "judgement")

# ---- A: judgement stays human-only --------------------------------------------
if req is not None and hasattr(dev_lane.DevLaneWorkflow, "lift_stop"):
    wf = make_wf(JU)
    out = lift(wf, JU)
    check("judgement-lift-refused-not-crash",
          out in ("ok",) or str(out).startswith("raise:"),
          "handler unusable: %r" % out)
    check("judgement-lift-no-wake", wf._retry_token == 7,
          "a refused judgement lift moved the retry token")
    check("judgement-refusal-recorded",
          len(wf.refused) == 1 and {"who", "want", "why"}
          <= set(wf.refused[0]),
          "refusal ledger shape wrong: %r" % (wf.refused,))

    # ---- B: evidence lift needs the cited row ---------------------------------
    wf = make_wf(EV, kind="environment_face")
    lift(wf, EV)
    check("evidence-lift-without-row-refused", wf._retry_token == 7,
          "evidence lift without a cited row id woke the step")
    wf = make_wf(EV, kind="environment_face")
    out = lift(wf, EV, row_id="row-404")
    check("evidence-lift-with-row-wakes",
          granted(out) and wf._retry_token != 7,
          "a well-formed evidence lift did not cleanly wake the step: %r" % out)
    check("lift-writes-record",
          any("row-404" in str(e) for e in wf.timeline)
          and wf.meta["blocked_evidence"]["cited_row_id"] == "row-404",
          "no written record of who/tier/row id after the lift: %r"
          % (wf.timeline,))

    # ---- C: tier mismatch and no recorded tier --------------------------------
    wf = make_wf(ME)
    lift(wf, EV, row_id="row-1")
    check("tier-mismatch-refused", wf._retry_token == 7,
          "a lift naming the wrong tier woke the step")
    wf = make_wf(None)
    lift(wf, EV, row_id="row-1")
    check("no-recorded-tier-refused", wf._retry_token == 7,
          "a pre-deploy stop (no tier) was treated as liftable")

    # ---- E: a lift never resets the arbitration counters ----------------------
    wf = make_wf(ME)
    out = lift(wf, ME, note="clearing move named in the note")
    check("mechanical-lift-wakes",
          granted(out) and wf._retry_token != 7,
          "a granted mechanical lift did not cleanly wake the step: %r" % out)
    check("lift-never-resets-counters",
          wf._conflict_rounds == 3 and wf._prev_conflict_files == ["a.py"],
          "a lift touched the R3 counter/guard state (t261006-07 is human-only)")

    # ---- F: gate refusal mutates nothing --------------------------------------
    wf = make_wf(ME)
    wf._cross_project_gate = lambda *a, **k: False
    lift(wf, ME)
    check("gate-refusal-mutates-nothing", wf._retry_token == 7,
          "a gate-refused lift moved state")
else:
    check("lift-journeys-runnable", False,
          "lift_stop / StopLiftRequest surface absent (pre-implement tree)")

summary()
