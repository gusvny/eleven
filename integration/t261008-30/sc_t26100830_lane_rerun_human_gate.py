#!/usr/bin/env python3
"""sc_t26100830_lane_rerun_human_gate — lane watchdog rerun-rounds must not
fire on a ticket parked at a human gate (t261008-30, grey-box L2/L3, offline
seconds, pure stdlib, zero docker/Temporal/browser, never touches 3099).

Incident face (261008 host report, live case t261005-11 / dengzhufpv): a ticket
at stage=merge, stage_state=awaiting-human, waiting two days for a signature,
was reported as severity=high "stuck in the lane: re-ran the integration suite
6 times (threshold 3)" with 42.6h quoted as per-round wall — a reader was sent
chasing a ticket that needs one signature.

Pinned faces (all through the module's public functions, no private internals):

  W1  Human-gate exemption: the incident fingerprint yields NO rerun-rounds
      finding; the shared `suppressed` channel names the ticket and the
      human-gate reason; a `human_gate` datum carries the waiting age.
  W2  paused=True and status=blocked rows behave the same (exempt + named).
  W3  Negative: an in-flight ticket (stage=run_integration_tests) with the
      same round count is STILL reported, with today's severity ladder
      (med at N+1, high at 2N) — the exemption must not silence thrashing.
  W4  Anti-blanket guard: a suite-stage ticket with an awaiting-looking
      stage_state is still reported (the stage is what the rounds measure).
  W5  Span vs per-round: the finding evidence carries "per-round wall:" and
      "total span:" as distinct labelled fields; the span value never sits
      under the per-round label; single-entry and no-entry rows keep span
      labelled span.
  W6  Period scan (lane_findings + lane_section): the waiting ticket produces
      no fault-leg entry, its waiting age stays readable in meta.human_gate,
      and the period max_severity / by_leg reflect only the thrashing ticket.
  W7  Malformed input: missing/zero last_activity_at, non-dict facts, no
      suite entries — no crash, suppression still named, age_unknown named.
  W8  Tier-3 regression: the existing inflight-silent exemption and its
      "inflight-silent NOT reported" suppressed line are intact.
  W9  Single-writer drift guard: the human-gate reason strings are built in
      one place — a second copy of the rule drifting apart is the exact
      defect this ticket forbids.

Threshold pins: rerun_rounds default stays 3 (no threshold change to make the
case disappear); fault-loop and inflight-silent defaults unchanged.

Run: python3 integration/t261008-30/sc_t26100830_lane_rerun_human_gate.py
(cwd = repo root).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


try:
    import inspection_lane_watchdog as lw
except Exception as exc:                       # noqa: BLE001
    print("FAIL named: server/engine/inspection_lane_watchdog.py not importable: "
          "%s: %s" % (type(exc).__name__, exc))
    sys.exit(1)

DAY = 86400.0
NOW = 1_800_000_000.0

#: The t261005-11 incident fingerprint, as facts (the shape the module's own
#: snapshot reader produces for stage=merge / awaiting-human / 6 suite rounds,
#: converged 2 days ago, silent since).
INCIDENT = {
    "ticket_id": "t261005-11", "project": "dengzhufpv",
    "stage": "merge", "stage_state": "awaiting-human", "status": "dispatched",
    "suite_rounds": 6,
    "suite_entries": [NOW - 6 * DAY, NOW - 6 * DAY + 560, NOW - 5 * DAY,
                      NOW - 5 * DAY + 610, NOW - 4 * DAY, NOW - 4 * DAY + 590],
    "last_activity_at": NOW - 2 * DAY,
    "paused": False, "verdict": "", "verdict_at": 0.0, "parse_notes": [],
}

THR = dict(lw.WATCHDOG_DEFAULTS)
LEG = lw.LEG_RERUN


def run_legs(facts, now=NOW, thr=THR):
    sup, hg = [], []
    legs = lw.lane_legs(facts, now, thr, sup, hg)
    return legs, sup, hg


# ---------- W1 incident fingerprint: exempt + named + low-key wait datum ----------
section("W1 human-gate exemption (incident fingerprint)")
legs, sup, hg = run_legs(INCIDENT)
ok(not any(l["leg"] == LEG for l in legs),
   "no rerun-rounds finding for the awaiting-human incident row")
ok(any("rerun-rounds NOT reported" in s for s in sup),
   "suppressed channel names the rerun exemption (not a silent drop)")
ok(any("t261005-11" in s and "waiting on a human gate" in s for s in sup),
   "suppressed line names the ticket and the human-gate reason")
ok(any("suite re-runs=6" in s for s in sup),
   "suppressed line keeps the round count readable")
ok(len(hg) == 1 and hg[0]["ticket_id"] == "t261005-11",
   "human_gate datum carries the waiting ticket")
ok("waiting" in hg[0] and hg[0]["waiting"], "human_gate datum carries the waiting age")
ok(all("severity" not in d for d in hg),
   "human_gate datum carries no fault severity (queueing is not a fault)")
ok(not any(l["leg"] == lw.LEG_INFLIGHT for l in legs),
   "no inflight-silent finding either (the ticket is parked, not zombie)")

# ---------- W2 paused / blocked rows behave the same ----------
section("W2 paused and blocked rows")
for key, val in (("paused", True), ("status", "blocked")):
    f = dict(INCIDENT)
    f["ticket_id"] = "t-x-%s" % key
    f["stage_state"] = "running"           # remove the awaiting reason
    f[key] = val
    legs, sup, hg = run_legs(f)
    ok(not any(l["leg"] == LEG for l in legs), "%s=%s row: no rerun finding" % (key, val))
    ok(any("rerun-rounds NOT reported" in s and "t-x-%s" % key in s for s in sup),
       "%s=%s row: exemption named in suppressed" % (key, val))
    ok(len(hg) == 1, "%s=%s row: human_gate datum present" % (key, val))

# ---------- W3 negative: real thrashing still reported ----------
section("W3 negative: in-flight thrashing still reported")
f = dict(INCIDENT)
f.update({"ticket_id": "t-thrash", "stage": "run_integration_tests",
          "stage_state": "running", "status": "dispatched", "paused": False,
          "suite_entries": [NOW - 560 * i for i in range(6, 0, -1)]})
legs, sup, hg = run_legs(f)
rerun = [l for l in legs if l["leg"] == LEG]
ok(len(rerun) == 1, "in-flight row with 6 rounds still yields the rerun finding")
ok(rerun and rerun[0]["severity"] == "high",
   "severity ladder unchanged at 2N (high for 6 rounds, N=3)")
ok(not sup, "in-flight row: nothing suppressed")
f4 = dict(f); f4["suite_rounds"] = 4
f4["suite_entries"] = [NOW - 560 * i for i in range(4, 0, -1)]
legs4, _, _ = run_legs(f4)
ok(any(l["leg"] == LEG and l["severity"] == "med" for l in legs4),
   "severity ladder unchanged at N+1 (med for 4 rounds)")

# ---------- W4 anti-blanket guard: suite stage is always checked ----------
section("W4 anti-blanket guard (suite stage never exempt)")
f = dict(INCIDENT)
f.update({"ticket_id": "t-suite-await", "stage": "run_integration_tests",
          "stage_state": "awaiting-input", "status": "dispatched"})
legs, sup, hg = run_legs(f)
ok(any(l["leg"] == LEG for l in legs),
   "awaiting-looking state inside run_integration_tests does NOT swallow the finding")
ok(not any("rerun-rounds NOT reported" in s for s in sup),
   "no suppression line minted for a suite-stage row")
ok(not hg, "no human_gate datum for a suite-stage row")

# ---------- W5 span never wears a per-round label ----------
section("W5 span vs per-round labelling")
ev = [l for l in legs if l["leg"] == LEG][0]["evidence"] if legs else ""
thrashing = dict(f)
thrashing.update({"stage_state": "running",
                  "suite_entries": [NOW - 9 * DAY + 560 * i for i in range(6)]})
legs_t, _, _ = run_legs(thrashing)
ev_t = [l for l in legs_t if l["leg"] == LEG][0]["evidence"]
ok("per-round wall:" in ev_t and "total span:" in ev_t,
   "evidence carries BOTH a per-round wall field and a total span field")
per_round_part = ev_t.split("per-round wall:", 1)[1].split("|", 1)[0]
ok("over" not in per_round_part and "span" not in per_round_part,
   "the per-round field contains no span value (span never under a per-round label)")
ok("42.6h" not in per_round_part or "total span: 42.6h" in ev_t,
   "a multi-day tail is reported as span, not as the last per-round value")
single = dict(thrashing); single["suite_entries"] = [NOW - DAY]; single["suite_rounds"] = 4
ev_s = [l for l in run_legs(single)[0] if l["leg"] == LEG][0]["evidence"]
ok("total span:" in ev_s and "single round" in ev_s,
   "single-entry row keeps the span labelled span (named degenerate case)")
empty = dict(thrashing); empty["suite_entries"] = []
ev_e = [l for l in run_legs(empty)[0] if l["leg"] == LEG][0]["evidence"]
ok("total span:" in ev_e and "unavailable" in ev_e,
   "no-entry row names the span unavailable instead of faking a number")

# ---------- W6 period scan: waiting ticket never drags the period red ----------
section("W6 period scan (lane_findings + lane_section)")
thrash_facts = dict(thrashing); thrash_facts["ticket_id"] = "t-thrash"
findings, meta = lw.lane_findings([INCIDENT, thrash_facts], now_ts=NOW)
section_f = lw.lane_section(findings, meta)
ok(not any(f.get("ticket_id") == "t261005-11" for f in findings),
   "waiting ticket produces no fault-leg entry in the period findings")
ok(any(f.get("ticket_id") == "t-thrash" for f in findings),
   "thrashing ticket still reported in the same period")
ok(section_f["by_leg"].get(LEG) == 1,
   "by_leg counts only the thrashing ticket under rerun-rounds")
ok(section_f["max_severity"] == "high",
   "period max_severity reflects only the thrashing ticket (waiting ticket drags nothing)")
ok(any("t261005-11" in s for s in section_f["suppressed"]),
   "suppressed face on the section names the waiting ticket")
ok(any(d.get("ticket_id") == "t261005-11" and d.get("waiting")
       for d in section_f.get("human_gate") or []),
   "waiting age stays readable on the section's human_gate face")

# ---------- W7 malformed input ----------
section("W7 malformed input")
f = dict(INCIDENT); f.pop("last_activity_at")
try:
    legs, sup, hg = run_legs(f)
    ok(not any(l["leg"] == LEG for l in legs) and sup and hg
       and hg[0].get("age_unknown") is True and not hg[0].get("waiting"),
       "missing last_activity_at: exemption holds, age_unknown named, no crash")
except Exception as exc:                       # noqa: BLE001
    ok(False, "missing last_activity_at crashed: %r" % exc)
f = dict(INCIDENT); f["last_activity_at"] = 0.0
_, _, hg = run_legs(f)
ok(hg and hg[0].get("age_unknown") is True,
   "zero last_activity_at: age unknown, not a fabricated 0 wait")
try:
    legs, sup, hg = run_legs("not-a-dict")
    ok(legs == [] and not sup and not hg, "non-dict facts: empty judgement, no crash")
except Exception as exc:                       # noqa: BLE001
    ok(False, "non-dict facts crashed: %r" % exc)
findings, meta = lw.lane_findings(["junk", {"ticket_id": ""}, 42], now_ts=NOW)
ok(findings == [] and len(meta.get("skipped") or []) == 3,
   "lane_findings malformed rows: skipped named, never silent, no crash")

# ---------- W8 tier-3 regression ----------
section("W8 tier-3 exemption intact")
f = dict(INCIDENT)
f.update({"ticket_id": "t-silent-wait", "suite_rounds": 1, "suite_entries": []})
legs, sup, _ = run_legs(f)
ok(not any(l["leg"] == lw.LEG_INFLIGHT for l in legs),
   "parked ticket still exempt from inflight-silent (tier-3 exemption not deleted)")
f2 = dict(f); f2.update({"ticket_id": "t-silent-live", "stage_state": "running",
                         "status": "dispatched", "paused": False})
legs2, sup2, _ = run_legs(f2)
ok(any(l["leg"] == lw.LEG_INFLIGHT for l in legs2),
   "a genuinely in-flight silent ticket is still reported by tier 3")
f3 = dict(f); f3.update({"ticket_id": "t-silent-parked2", "suite_rounds": 1})
_, sup3, _ = run_legs(f3)
ok(any("inflight-silent NOT reported" in s for s in sup3),
   "tier-3 suppressed line keeps its own leg-name prefix (two families separable)")

# ---------- W9 single-writer drift guard + threshold pins ----------
section("W9 single-writer judgement + unchanged thresholds")
src = (ROOT / "server" / "engine" / "inspection_lane_watchdog.py").read_text("utf-8")
ok(src.count("def _not_in_flight_reasons(") == 1,
   "the helper is defined once (single writer — no second copy of the rule)")
ok(src.count("_not_in_flight_reasons(") >= 3,
   "every leg consumes the one judgement (def + at least two call sites — "
   "t261009-78's buffer-stall suppression routes through the same helper via "
   "_not_in_flight, never an inline copy)")
ok(src.count("not_in_flight.append(") == 0,
   "no leg rebuilds the reason list inline (drift between the two copies is the "
   "exact defect this ticket forbids)")
for reason in ("paused=True (stop-the-bleeding action, KI-122)",
               "status=%s (waiting on a human decision)",
               "stage_state=%s (waiting on a human gate)"):
    ok(src.count(reason) == 1,
       "reason text constructed exactly once: %r" % reason)
ok(lw.DEFAULT_RERUN_ROUNDS == 3, "rerun_rounds default unchanged (3)")
ok(lw.WATCHDOG_DEFAULTS["fault_loop_min"] and lw.WATCHDOG_DEFAULTS["inflight_silent_min"],
   "fault-loop / inflight-silent defaults present and untouched")

# ---------- summary ----------
print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
