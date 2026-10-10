#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_buffer_stall_legs_fire.py — the develop-buffer silent stalls become
visible (t261009-78, grey-box L2, offline seconds, zero docker/Temporal/browser).

intent (user-perceivable; ticket t261009-78, design item 7 of
docs/design/inspection-produce-face-extension.md): a patrol operator reading the
lane-watchdog findings face must SEE the three silent stall shapes the design
names —
  A  cert-wait-overdue: a ticket LANDED on a line, no certification covers it,
     wait age past the declared window -> a finding naming the ticket, the line,
     the landing revision and the wait age (data fields untranslated);
  B  within the window -> no such finding (a young landing is not a stall);
  C  a ticket parked at a human gate (paused/blocked) with a stale landing is
     NOT a stall — suppressed by the existing single-writer rule, named, not
     silently dropped;
  D  freeze-without-remedy: a line with an OPEN freeze episode and NO remedy in
     flight past the declared window -> a finding naming the line, the freeze
     episode, its cause certification and how long it has been open;
  E  the same freeze WITH a current repairs relation whose repairing ticket is
     in flight -> remedy in flight, the leg stays silent about it;
  F  repair-points-nowhere: a current repairs relation whose target landing is
     NOT in the delivery ledger -> a finding naming the relation id, both ends,
     and exactly what was looked for (a relation pointing at nothing must not
     read as handled);
  G  a superseded relation (corrected by a later supersedes row) is exempt —
     only CURRENT relations are judged;
  H  threshold boundary: a landing at exactly the window age is a finding
     (>= convention, same as the existing legs).

intent split: per-input truth tables and unit-level parse degradation belong to
developer L1 (server/engine/tests); this scenario owns the user-perceivable
discrimination contract through the watchdog's public findings face. The
machine-pin shape is out of this ticket's scope and is not asserted here.
Pre-implement tree red = the expected TDD signal; green required at the
integration gate / merge. Engine module unimportable = ENV_FAIL exit 2.

Run directly (cwd = repo root):
  python3 integration/t261009-78/sc_buffer_stall_legs_fire.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from lib_stall_harness import (  # noqa: E402
    CERT_WAIT, FREEZE_NO_REMEDY, NOW_MS, NOW_S, REPAIR_NOWHERE, WINDOW_MIN,
    WINDOW_MS, all_legs, blob, call_lane_findings, cert_row, check_outcomes,
    contract_fn, freeze_row, findings_with_leg, human_gate_facts, in_flight_facts, landing_row,
    load_watchdog, relation_row,
)


def main():
    lw, err = load_watchdog()
    if lw is None:
        print("ENV_FAIL: %s" % err)
        sys.exit(2)
    lane_findings, ferr = contract_fn(
        lw, ["lane_findings"], "the lane findings face")
    if lane_findings is None:
        print("FAIL: %s" % ferr)
        sys.exit(1)
    stall_facts_fn, serr = contract_fn(
        lw, ["stall_facts", "buffer_stall_facts", "facts_from_ledger",
             "ledger_stall_facts"],
        "the delivery-ledger facts builder (stall_facts)")
    if stall_facts_fn is None:
        # contract discovery failed: named FAIL (TDD signal), never a fake pass
        print("FAIL: %s" % serr)
        sys.exit(1)

    line = "line-main"
    overdue_at = NOW_MS - WINDOW_MS - 60 * 1000        # past the window
    fresh_at = NOW_MS - 5 * 60 * 1000                  # inside the window
    exact_at = NOW_MS - WINDOW_MS                      # exactly at the window

    tickets = [
        in_flight_facts("t-wait"),       # landed, uncovered, in flight -> A
        in_flight_facts("t-fresh"),      # landed recently -> B (no finding)
        human_gate_facts("t-gate"),      # parked at a human gate -> C
        in_flight_facts("t-fix"),        # the repairing ticket in flight -> E
        in_flight_facts("t-exact"),      # boundary case -> H
    ]

    def facts_for(rows):
        got = stall_facts_fn(rows, lines=[line])
        return got

    results = []

    # ---- A: cert-wait-overdue fires with named facts ------------------------
    rows_a = [landing_row("ldg-wait", "t-wait", line, overdue_at)]
    try:
        findings, _meta = call_lane_findings(lane_findings, tickets,
                                             stall_facts=facts_for(rows_a))
    except TypeError as exc:
        print("FAIL: lane_findings refuses stall_facts (contract not landed): %r"
              % (exc,))
        sys.exit(1)
    hits = findings_with_leg(findings, CERT_WAIT)
    txt = blob(findings)
    ok = len(hits) == 1
    detail = "" if ok else "expected exactly one %s finding, got %d" % (
        CERT_WAIT, len(hits))
    for fact in ("t-wait", "ldg-wait", line, "r42"):
        if fact not in txt:
            ok = False
            detail += "; finding does not name %s" % fact
    results.append(("A cert-wait-overdue fires naming ticket/line/landing/"
                    "revision", ok, detail))

    # ---- B: inside the window is not a stall --------------------------------
    rows_b = [landing_row("ldg-fresh", "t-fresh", line, fresh_at)]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_b))
    hits = findings_with_leg(findings, CERT_WAIT)
    results.append(("B landing inside the window stays silent",
                    len(hits) == 0,
                    "unexpected %s on a fresh landing: %s" % (CERT_WAIT, hits)))

    # ---- C: human-gate ticket suppressed, by name ---------------------------
    rows_c = [landing_row("ldg-gate", "t-gate", line, overdue_at)]
    findings, meta_c = call_lane_findings(lane_findings, tickets,
                                          stall_facts=facts_for(rows_c))
    hits = findings_with_leg(findings, CERT_WAIT)
    face_txt = blob(findings) + blob([meta_c])
    ok = len(hits) == 0
    detail = "human-gate ticket still produced a %s finding" % CERT_WAIT
    if "t-gate" not in face_txt:
        # suppression must be VISIBLE: the ticket is named as suppressed, not
        # silently absent from the face
        ok = False
        detail += "; suppression not named anywhere on the face"
    results.append(("C ticket at a human gate is not a stall (named "
                    "suppression)", ok, detail))

    # ---- D: freeze-without-remedy fires with named facts --------------------
    rows_d = [freeze_row("frz-e1", line, overdue_at, cert="cert-cause"),
              landing_row("ldg-exact", "t-exact", line, exact_at)]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_d))
    hits = findings_with_leg(findings, FREEZE_NO_REMEDY)
    txt = blob(findings)
    ok = len(hits) == 1
    detail = "" if ok else "expected exactly one %s finding, got %d" % (
        FREEZE_NO_REMEDY, len(hits))
    for fact in ("frz-e1", "cert-cause", line):
        if fact not in txt:
            ok = False
            detail += "; finding does not name %s" % fact
    if not any(ch.isdigit() for ch in txt):
        ok = False
        detail += "; open age not reported"
    results.append(("D freeze-without-remedy fires naming line/episode/cause/"
                    "open-age", ok, detail))

    # ---- E: a current repairs relation = remedy in flight, leg silent -------
    rows_e = [freeze_row("frz-e2", line, overdue_at, cert="cert-cause"),
              relation_row("rel-r1", "repairs", "t-fix", "ldg-exact", NOW_MS)]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_e))
    hits = findings_with_leg(findings, FREEZE_NO_REMEDY)
    results.append(("E freeze WITH remedy in flight stays silent",
                    len(hits) == 0,
                    "unexpected %s despite a current repairs relation: %s"
                    % (FREEZE_NO_REMEDY, hits)))

    # ---- F: repair-points-nowhere fires naming both ends + what was sought --
    rows_f = [relation_row("rel-d1", "repairs", "t-fix", "ldg-nowhere", NOW_MS),
              landing_row("ldg-real", "t-wait", line, overdue_at)]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_f))
    hits = findings_with_leg(findings, REPAIR_NOWHERE)
    txt = blob(findings)
    ok = len(hits) == 1
    detail = "" if ok else "expected exactly one %s finding, got %d" % (
        REPAIR_NOWHERE, len(hits))
    for fact in ("rel-d1", "t-fix", "ldg-nowhere"):
        if fact not in txt:
            ok = False
            detail += "; finding does not name %s" % fact
    results.append(("F repair-points-nowhere fires naming relation/both ends/"
                    "looked-for", ok, detail))

    # ---- G: a superseded relation is exempt --------------------------------
    rows_g = [
        relation_row("rel-old", "repairs", "t-fix", "ldg-nowhere",
                     NOW_MS - 60 * 1000),
        relation_row("rel-new", "supersedes", "t-fix", "rel-old", NOW_MS,
                     supersedes_relation="rel-old"),
        landing_row("ldg-real", "t-wait", line, overdue_at),
    ]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_g))
    txt = blob(findings)
    hits = findings_with_leg(findings, REPAIR_NOWHERE)
    ok = "rel-old" not in txt and len(hits) == 0
    results.append(("G superseded relation is exempt (only current relations "
                    "are judged)", ok,
                    "superseded rel-old still reported: %s" % hits))

    # ---- H: boundary — exactly at the window is a finding ------------------
    rows_h = [landing_row("ldg-exact", "t-exact", line, exact_at)]
    findings, _m = call_lane_findings(lane_findings, tickets,
                                      stall_facts=facts_for(rows_h))
    hits = findings_with_leg(findings, CERT_WAIT)
    results.append(("H landing at exactly the window age is a finding (>=)",
                    len(hits) == 1,
                    "expected the exact-boundary landing to fire, got %d"
                    % len(hits)))

    check_outcomes(results)


if __name__ == "__main__":
    main()
