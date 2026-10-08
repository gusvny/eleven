#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""261008 host report (live case t261005-11): the rerun-rounds leg must not fire
on a ticket parked at a human gate.

Fix (t261008-30): the rerun leg shares the tier-3 not-in-flight rule (single writer
`_not_in_flight_reasons`); the exemption names itself in the `suppressed` channel
(leg-token prefix); the human-gate wait is its own low-key `human_gate` datum (no
severity, no by_leg slot, no say in green/red); per-round durations and the total
span carry separate labels (the span never dresses up as per-round).
Run: repo root `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261008_30_lane_watchdog_human_gate.py -q`."""
from __future__ import annotations

import re
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_lane_watchdog as lw  # noqa: E402

NOW = 1_800_000_000.0


def _facts(**kw):
    f = {"ticket_id": "t-gate", "project": "sandbar", "workflow_id": "t-gate",
         "stage": "merge", "stage_state": "awaiting-human", "status": "dispatched",
         "verdict": "", "verdict_at": 0.0, "suite_rounds": 6,
         "suite_entries": [NOW - 42.6 * 3600 + i * 3600 for i in range(6)],
         "last_activity_at": NOW - 42 * 3600, "created_at": NOW - 86400,
         "paused": False, "blocked_reason": "", "parse_notes": []}
    f.update(kw)
    return f


def _scan(facts, **thr):
    return lw.lane_findings(facts, now_ts=NOW, thresholds=thr or None)


def test_a1_human_gate_row_yields_no_rerun_finding_and_names_itself():
    finds, meta = _scan([_facts()], rerun_rounds=3)
    assert finds == []
    assert meta["suppressed"] and meta["suppressed"][0].startswith(
        "t-gate: rerun-rounds NOT reported"), meta["suppressed"]
    assert "stage_state=awaiting-human (waiting on a human gate)" in meta["suppressed"][0]
    assert "suite re-runs=6" in meta["suppressed"][0]
    # Low-key waiting fact: not a finding, but the age is readable and reasons listed
    hg = meta["human_gate"]
    assert len(hg) == 1 and hg[0]["ticket_id"] == "t-gate"
    assert hg[0]["reasons"] == ["stage_state=awaiting-human (waiting on a human gate)"]
    assert hg[0]["waiting"] and hg[0]["age_unknown"] is False
    sec = lw.lane_section(finds, meta)
    assert sec["finding_count"] == 0 and sec["max_severity"] == ""
    assert sec["by_leg"][lw.LEG_RERUN] == 0
    assert sec["suppressed"] == meta["suppressed"] and sec["human_gate"] == hg


def test_a2_paused_and_blocked_rows_behave_the_same():
    for tag, kw in (("paused", {"paused": True, "status": "paused"}),
                    ("blocked", {"status": "blocked"})):
        finds, meta = _scan([_facts(**kw)], rerun_rounds=3)
        assert finds == [], tag
        assert meta["suppressed"] and meta["suppressed"][0].startswith(
            "t-gate: rerun-rounds NOT reported"), tag
        assert tag in meta["suppressed"][0], tag
        assert meta["human_gate"] and tag in meta["human_gate"][0]["reasons"][0], tag


def test_a3_inflight_thrashing_still_fires_with_todays_severity():
    # In flight (suite stage running) -> still reported: med at N+1, high at 2N (today's ladder)
    med, _ = _scan([_facts(stage="run_integration_tests", stage_state="running",
                           suite_rounds=4,
                           suite_entries=[NOW - 5 * 3600 + i * 3600 for i in range(4)],
                           last_activity_at=NOW - 3600)],
                   rerun_rounds=3)
    assert [f["legs"] for f in med] == [[lw.LEG_RERUN]] and med[0]["severity"] == "med"
    high, meta = _scan([_facts(stage="run_integration_tests", stage_state="running")],
                       rerun_rounds=3)
    assert high[0]["severity"] == "high" and meta["suppressed"] == []
    assert meta["human_gate"] == []
    # The same row also carries inflight-silent (in flight, 42h silent = a real zombie) - not this ticket's target
    assert lw.LEG_RERUN in high[0]["legs"] and lw.LEG_INFLIGHT in high[0]["legs"]
    # Anti-blanket: even a waiting-shaped state word inside the suite stage does not exempt (the rounds measure that stage)
    guard, _ = _scan([_facts(stage="run_integration_tests", stage_state="awaiting-cleanup")],
                     rerun_rounds=3)
    assert lw.LEG_RERUN in guard[0]["legs"]


def test_a4_span_and_per_round_are_distinct_labelled_fields():
    finds, _ = _scan([_facts(stage="run_integration_tests", stage_state="running")],
                     rerun_rounds=3)
    ev = finds[0]["evidence"]
    assert "per-round wall: " in ev and "total span: " in ev
    # the span value never sits after the per-round label: per-round comes before total span
    assert ev.index("per-round wall: ") < ev.index("total span: ")
    per_round = ev.split("per-round wall: ", 1)[1].split(" | total span: ", 1)[0]
    assert "42.6h" not in per_round, per_round           # the span value stays out of the per-round field
    span = ev.split("total span: ", 1)[1].split(" | ", 1)[0]
    assert "over 6 rounds" in span, span
    # Single-entry degenerate case: span keeps its span label and says it equals the last round
    one, _ = _scan([_facts(stage="run_integration_tests", stage_state="running",
                           suite_rounds=4, suite_entries=[NOW - 2 * 3600])],
                   rerun_rounds=3)
    assert "total span: " in one[0]["evidence"] and \
        "single round: span equals the last round" in one[0]["evidence"]
    # No entries: span = unavailable (not 0, never per-round wording)
    none, _ = _scan([_facts(stage="run_integration_tests", stage_state="running",
                            suite_entries=[])], rerun_rounds=3)
    assert "total span: unavailable (no suite entries)" in none[0]["evidence"]


def test_a5_period_scan_not_dragged_red_by_a_waiting_ticket():
    thrashing = _facts(ticket_id="t-thrash", stage="run_integration_tests",
                       stage_state="running")
    waiting = _facts(ticket_id="t-wait", last_activity_at=NOW - 42 * 3600)
    finds, meta = _scan([waiting, thrashing], rerun_rounds=3)
    assert {f["ticket_id"] for f in finds} == {"t-thrash"}
    assert meta["by_leg"][lw.LEG_RERUN] == 1              # only the thrashing ticket counts
    assert meta["suppressed"] and "t-wait" in meta["suppressed"][0]
    assert meta["human_gate"] and meta["human_gate"][0]["ticket_id"] == "t-wait"
    sec = lw.lane_section(finds, meta)
    assert sec["max_severity"] == "high" and sec["finding_count"] == 1
    assert [h["ticket_id"] for h in sec["human_gate"]] == ["t-wait"]


def test_a6_malformed_inputs_no_crash_and_no_silent_drop():
    # Age anchor missing: the datum still lands (exemption visible), age_unknown=True, waiting empty
    finds, meta = _scan([_facts(last_activity_at=0.0)], rerun_rounds=3)
    assert finds == []
    hg = meta["human_gate"]
    assert hg and hg[0]["age_unknown"] is True and hg[0]["waiting"] == ""
    assert hg[0]["reasons"], "the exemption reasons must not vanish with the age"
    # Malformed suite_entries mixed in: the exemption path is unaffected (the span side reports unavailable)
    bad = _facts(suite_entries=[None, "x", NOW])
    f2, m2 = _scan([bad], rerun_rounds=3)
    assert f2 == [] and m2["suppressed"]
    # facts not a dict / no ticket_id: the existing named demotion (no throw, no silence)
    f3, m3 = _scan([None, {"suite_rounds": 6}], rerun_rounds=3)
    assert f3 == [] and len(m3["skipped"]) == 2
    # section human_gate malformed entries dropped one by one
    sec = lw.lane_section([], {"human_gate": ["x", {"ticket_id": "t-ok"}], "by_leg": {}})
    assert sec["human_gate"] == [{"ticket_id": "t-ok"}]
    sec2 = lw.lane_section([], {"human_gate": "not-a-list"})
    assert sec2["human_gate"] == []
    # Report language gate: the new copy is English-only (reasons/waiting all reach the section face)
    import inspection_inspect as ins
    joined = "".join(str(r) for r in meta["suppressed"]) + \
        "".join(str(h) for h in meta["human_gate"] for h2 in (h.get("reasons") or []))
    assert not ins.CJK_RE.search(joined), joined
    assert re.search(r"rerun-rounds NOT reported", joined)   # leg-token prefix keeps families separable
