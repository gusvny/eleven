#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-78 — the lane watchdog's three buffer-stall legs (L1 regression bar).

The develop-buffer flow's silent stalls, named by the inspection design's closing
section (item 7), now judged by the watchdog face (pure, ledger-fed):

  A. `resolve_stall_thresholds`: declaration parsing, per-key named fallback,
     WATCHDOG_ALL_KEYS universe.
  B. `stall_facts`: ledger rows -> facts; malformed rows / non-list / undeclared
     line / missing patch_ids each degrade BY NAME, never as "fine".
  C. `stall_legs`: one hit per shape (cert-wait-overdue / freeze-without-remedy /
     repair-points-nowhere), one counterexample per shape; the human-gate
     suppression reuses `_not_in_flight_reasons`; a missing run-reader degrades
     to "cert coverage unknown".
  D. `lane_findings` wiring: stall_required=True without ledger -> ONE report-level
     low finding (never a per-ticket flood); with ledger -> legs-tokened findings +
     meta.stall counting; the opt-out keeps the old behaviour byte-for-byte.

Run: repo root `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261009_78_watchdog_buffer_stalls.py -q`
(UT: no network / no real Temporal / no real git; the ledger rows are literal
dict fixtures, never an external source).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_lane_watchdog as lw  # noqa: E402

NOW = 1_790_430_000.0
NOW_MS = int(NOW * 1000)
H = 3600 * 1000  # one hour in ms

LINE = "line-a"
OTHER = "line-b"


def _repos(rev="rev1", repo="r1"):
    return [{"repo": repo, "revision": rev}]


def _landing(tid="t-fix", line=LINE, at=None, lid="ldg-fix", rev="rev1", seq=1):
    return {"kind": "landing", "id": lid, "ticket": tid, "line": line,
            "repos": _repos(rev), "actor": "developer", "seq": seq,
            "at": at or (NOW_MS - 1 * H)}


def _rel(rid="rel-fix", kind="repairs", frm="t-other", to="ldg-fix",
         at=None, evidence=None, seq=2):
    return {"kind": kind, "id": rid, "from": frm, "to": to,
            "recorded_by": "integration", "reason": "fix the red", "seq": seq,
            "evidence": evidence or {"what": "revision", "ref": "rev1"},
            "at": at or (NOW_MS - 2 * H)}


def _freeze(fid="frz-fix", line=LINE, cause="cert-cause", at=None, seq=3):
    return {"kind": "freeze", "id": fid, "line": line, "cause": cause, "seq": seq,
            "at": at or (NOW_MS - 40 * H)}


def _facts(rows, *, lines=(LINE, OTHER), patch_ids=None):
    return lw.stall_facts(rows, lines=list(lines), patch_ids=patch_ids, now_ms=NOW_MS)


def _thr(**kw):
    thr = dict(lw.STALL_WATCHDOG_DEFAULTS)
    thr.update(kw)
    return thr


def _ticket(tid="t-fix", **kw):
    f = {"ticket_id": tid, "project": "p", "workflow_id": tid, "stage": "implement",
         "stage_state": "running", "status": "dispatched", "paused": False,
         "blocked_reason": "", "suite_rounds": 0, "suite_entries": [],
         "verdict": "", "verdict_at": 0.0, "last_activity_at": NOW,
         "created_at": NOW - 86400, "parse_notes": []}
    f.update(kw)
    return f


# ---------------------------------------------------------------- A. thresholds

def test_a1_defaults_when_no_declaration():
    thr, source, note, problems = lw.resolve_stall_thresholds(None)
    assert source == lw.THRESHOLD_SOURCE_DEFAULT
    assert thr == lw.STALL_WATCHDOG_DEFAULTS and problems == []
    assert "default" in note


def test_a2_declared_values_win_and_source_is_declaration():
    thr, source, note, problems = lw.resolve_stall_thresholds(
        {"cert_wait_overdue_min": 60, "freeze_without_remedy_min": 120})
    assert source == lw.THRESHOLD_SOURCE_DECL and problems == []
    assert thr == {"cert_wait_overdue_min": 60, "freeze_without_remedy_min": 120}
    assert "declaration" in note


def test_a3_malformed_degrades_by_name_per_key():
    thr, source, note, problems = lw.resolve_stall_thresholds("nope")
    assert source == lw.THRESHOLD_SOURCE_DEFAULT
    assert thr == lw.STALL_WATCHDOG_DEFAULTS
    assert any("not a mapping" in p for p in problems)
    thr2, source2, _, problems2 = lw.resolve_stall_thresholds(
        {"cert_wait_overdue_min": -5, "freeze_without_remedy_min": "abc"})
    assert thr2 == lw.STALL_WATCHDOG_DEFAULTS
    assert source2 == lw.THRESHOLD_SOURCE_DEFAULT
    assert any("cert_wait_overdue_min=-5" in p for p in problems2)
    assert any("freeze_without_remedy_min='abc'" in p for p in problems2)


def test_a4_stall_keys_in_declaration_universe():
    assert set(lw.STALL_WATCHDOG_KEYS) <= set(lw.WATCHDOG_ALL_KEYS)
    assert set(lw.STALL_WATCHDOG_RANGES) == set(lw.STALL_WATCHDOG_KEYS)
    assert set(lw.STALL_WATCHDOG_DEFAULTS) == set(lw.STALL_WATCHDOG_KEYS)


# ---------------------------------------------------------------- B. stall_facts

def test_b1_happy_fixture_parses_clean():
    rows = [_landing(), _freeze(), _rel()]
    f = _facts(rows)
    assert f["ledger_read"] and f["parse_notes"] == []
    assert "ldg-fix" in f["landings"] and f["freezes"][LINE]["episode"] == "frz-fix"
    assert f["freezes"][LINE]["cause"] == "cert-cause"
    assert [r["id"] for r in f["relations"]] == ["rel-fix"]


def test_b2_non_list_rows_degrades_by_name():
    f = _facts("not-a-list")
    assert not f["ledger_read"]
    assert any("not a list" in n for n in f["parse_notes"])
    assert lw.stall_legs(f, {}, NOW, _thr()) == []


def test_b3_malformed_rows_degrade_by_name_and_are_skipped():
    rows = [_landing(), {"kind": "landing"}, 42,
            dict(_landing(lid="ldg-bad"), ticket="", seq=4)]
    f = _facts(rows)
    assert f["ledger_read"] and "ldg-fix" in f["landings"]
    assert "ldg-bad" not in f["landings"]
    assert len(f["parse_notes"]) >= 3
    assert any("#2 is not an object" in n for n in f["parse_notes"])
    assert any("refused by the ledger validator" in n for n in f["parse_notes"])


def test_b4_undeclared_line_is_a_named_blind_spot():
    f = _facts([_landing()], lines=(OTHER,))
    assert "ldg-fix" in f["landings"]
    assert any("undeclared line" in n for n in f["parse_notes"])
    # and the cert-wait leg does not judge it
    hits = lw.stall_legs(f, {}, NOW, _thr(cert_wait_overdue_min=1))
    assert hits == []


def test_b5_missing_patch_ids_with_patch_named_relation_is_a_named_note():
    f = _facts([_rel(evidence={"what": "patch_id", "ref": "pid-1"})])
    assert f["patch_named_unresolved"] == 1
    assert any("patch_ids map not supplied" in n for n in f["parse_notes"])


# ---------------------------------------------------------------- C. stall legs

def test_c1_cert_wait_overdue_hit_names_ticket_line_revision_age():
    f = _facts([_landing(at=NOW_MS - 48 * H)])  # no certs at all -> state=waiting
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW,
                         _thr(cert_wait_overdue_min=2000))
    assert len(hits) == 1
    h = hits[0]
    assert h["leg"] == lw.LEG_CERT_WAIT and h["severity"] == "med"
    assert "t-fix" in h["subject"] and LINE in h["subject"]
    assert "rev1" in h["evidence"] and "48.0h" in h["evidence"]
    assert "threshold=2000min" in h["evidence"]
    assert h["ticket_id"] == "t-fix" and h["landing_id"] == "ldg-fix"


def test_c2_cert_wait_escalates_to_high_at_twice_the_window():
    f = _facts([_landing(at=NOW_MS - 200 * H)])
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=60))
    assert hits[0]["severity"] == "high"


def test_c3_cert_wait_below_window_is_silent():
    f = _facts([_landing(at=NOW_MS - 30 * H)])
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=2880))
    assert hits == []


def test_c4_certified_landing_is_not_a_stall():
    cert = {"kind": "certification", "id": "cert-ok", "line": LINE,
            "repos": _repos("rev1"), "run": "run-ok", "booked_red": "none",
            "judged_by": "inspector", "seq": 9, "at": NOW_MS - 1 * H}
    f = _facts([_landing(), cert])
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=1),
                         is_green=lambda run: True)
    assert hits == []


def test_c5_human_gate_ticket_is_suppressed_by_name_not_reported():
    f = _facts([_landing()])
    sup: list = []
    hits = lw.stall_legs(f, {"t-fix": _ticket(status="blocked")}, NOW,
                         _thr(cert_wait_overdue_min=1), suppressed=sup)
    assert hits == []
    assert len(sup) == 1 and "cert-wait-overdue NOT reported" in sup[0]
    assert "blocked" in sup[0]


def test_c6_missing_run_reader_with_certs_on_line_degrades_to_named_note():
    # landing rev1 not covered by cert on rev2 -> the wait face needs a run reader;
    # without one the leg must NOT assume every cert is green.
    cert = {"kind": "certification", "id": "cert-x", "line": LINE,
            "repos": _repos("rev2"), "run": "run-x", "booked_red": "none",
            "judged_by": "inspector", "seq": 9, "at": NOW_MS - 1 * H}
    f = _facts([_landing(), cert])
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=1))
    assert hits == []
    notes: list = []
    lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=1),
                  parse_notes=notes)
    assert any("cert coverage unknown" in n and "UNVERIFIED" in n for n in notes)


def test_c7_freeze_without_remedy_hit_names_line_episode_cause_age():
    f = _facts([_freeze()])  # open 40h, no relations
    hits = lw.stall_legs(f, {}, NOW, _thr(freeze_without_remedy_min=1440))
    assert len(hits) == 1
    h = hits[0]
    assert h["leg"] == lw.LEG_FREEZE_NO_REMEDY and h["severity"] == "high"
    assert LINE in h["subject"] and "40.0h" in h["subject"]
    assert h["freeze_episode"] == "frz-fix" and h["cause_cert"] == "cert-cause"
    assert "remedies_in_flight=0" in h["evidence"]
    assert "audited reading" in h["why"]


def test_c8_running_repair_ticket_counts_as_remedy_in_flight():
    f = _facts([_freeze(), _rel(frm="t-fixer", to="t-fixer")])
    hits = lw.stall_legs(f, {"t-fixer": _ticket("t-fixer")}, NOW,
                         _thr(freeze_without_remedy_min=60))
    assert hits == []


def test_c9_repair_ticket_parked_at_a_human_gate_is_not_remedy_in_flight():
    f = _facts([_freeze(), _rel(frm="t-fixer", to="t-fixer")])
    hits = lw.stall_legs(f, {"t-fixer": _ticket("t-fixer", status="blocked")}, NOW,
                         _thr(freeze_without_remedy_min=60))
    assert len(hits) == 1 and hits[0]["leg"] == lw.LEG_FREEZE_NO_REMEDY


def test_c10_pending_target_landing_counts_as_remedy_in_flight():
    # t261011-23 fixture update (named reason, intent unchanged): under the
    # range-coverage rule, a certification whose range contains the landing
    # COVERS it (certified), and a certified target is no longer a PENDING
    # remedy. For the landing to be genuinely pending, its seq must lie AFTER
    # the last certification (outside every range) — which is what the old
    # fixture could only express through a revision mismatch.
    cert = {"kind": "certification", "id": "cert-r", "line": LINE,
            "repos": _repos("rev-other"), "run": "run-r", "booked_red": "none",
            "judged_by": "inspector", "seq": 9, "at": NOW_MS - 1 * H}
    f = _facts([_freeze(), _landing(tid="t-fixer", lid="ldg-fix", seq=10),
                _rel(frm="t-fixer"), cert])
    hits = lw.stall_legs(f, {}, NOW, _thr(freeze_without_remedy_min=60,
                                          cert_wait_overdue_min=10080),
                         is_green=lambda run: True)
    assert hits == []


def test_c10b_covered_target_landing_is_no_longer_a_pending_remedy():
    # Named consequence of the range rule (t261011-23): a target landing
    # INSIDE the green certification's range is certified — the remedy is
    # done, not in flight — so an open freeze with nothing else in flight
    # names the freeze-without-remedy leg (the repair relation should have
    # been resolved; a stuck-open freeze stays visible, never silenced).
    cert = {"kind": "certification", "id": "cert-r", "line": LINE,
            "repos": _repos("rev-other"), "run": "run-r", "booked_red": "none",
            "judged_by": "inspector", "seq": 9, "at": NOW_MS - 1 * H}
    f = _facts([_freeze(), _landing(tid="t-fixer", lid="ldg-fix", seq=1),
                _rel(frm="t-fixer"), cert])
    hits = lw.stall_legs(f, {}, NOW, _thr(freeze_without_remedy_min=60,
                                          cert_wait_overdue_min=10080),
                         is_green=lambda run: True)
    assert len(hits) == 1
    h = hits[0]
    assert h["leg"] == lw.LEG_FREEZE_NO_REMEDY
    assert "remedies_in_flight=0" in h["evidence"]


def test_c11_frozen_but_young_is_silent():
    f = _facts([_freeze(at=NOW_MS - 12 * H)])
    hits = lw.stall_legs(f, {}, NOW, _thr(freeze_without_remedy_min=1440))
    assert hits == []


def test_c12_repair_points_nowhere_dangling_landing_id():
    f = _facts([_rel(to="ldg-nope")])
    hits = lw.stall_legs(f, {}, NOW, _thr())
    assert len(hits) == 1
    h = hits[0]
    assert h["leg"] == lw.LEG_REPAIR_NOWHERE and h["severity"] == "med"
    assert h["relation_id"] == "rel-fix" and h["from"] == "t-other"
    assert h["to"] == "ldg-nope"
    assert "no landing row in the ledger" in h["evidence"]
    assert "looked_for=to" in h["evidence"]


def test_c13_patch_named_relation_without_map_is_blind_note_not_finding():
    # `to` names a real landing; only the patch-named EVIDENCE is uncheckable.
    f = _facts([_landing(), _rel(to="ldg-fix",
                                 evidence={"what": "patch_id", "ref": "pid-9"})])
    notes: list = []
    hits = lw.stall_legs(f, {}, NOW, _thr(), parse_notes=notes)
    assert hits == []
    assert any("UNVERIFIED" in n and "pid-9" in n for n in notes)


def test_c14_patch_named_relation_resolves_through_patch_ids_map():
    f = _facts([_landing(), _rel(evidence={"what": "patch_id", "ref": "pid-9"})],
               patch_ids={"ldg-fix": "pid-9"})
    # the landing is 48h old, so keep the cert-wait window past it: this test is
    # about leg 3 only.
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=10080))
    assert hits == []


def test_c15_superseded_relation_is_not_reported():
    old = _rel(rid="rel-old", to="ldg-nope", at=NOW_MS - 5 * H)
    new = dict(_rel(rid="rel-new", seq=6), supersedes_relation="rel-old")
    f = _facts([_landing(), old, new])   # rel-new's own target (ldg-fix) exists
    hits = lw.stall_legs(f, {"t-fix": _ticket()}, NOW, _thr(cert_wait_overdue_min=10080))
    assert hits == []


def test_c16_withdraws_dangling_ticket_form_target_is_reported():
    rel = _rel(rid="rel-w", kind="withdraws", frm="t-owner", to="t-ghost")
    # patch_ids={} declares "we CAN check patch identities" — so a miss is the
    # ledger's dangling fact, not our blindness.
    f = _facts([rel], patch_ids={})
    hits = lw.stall_legs(f, {}, NOW, _thr())
    assert len(hits) == 1 and hits[0]["leg"] == lw.LEG_REPAIR_NOWHERE
    assert "t-ghost" in hits[0]["evidence"]


# ---------------------------------------------------------------- D. lane_findings wiring

def _tickets():
    return [_ticket()]


def test_d1_opt_out_keeps_old_behaviour_byte_for_byte():
    f1, m1 = lw.lane_findings(_tickets(), now_ts=NOW)
    assert m1["stall"]["ledger_supplied"] is False
    assert m1["stall"]["by_leg"] == {k: 0 for k in lw.STALL_LEGS}
    assert not any(lw.LEG_DATA_UNREADABLE in (fd.get("legs") or [])
                   and "ledger not supplied" in fd["subject"] for fd in f1)


def test_d2_stall_required_without_ledger_is_one_report_level_low_finding():
    out, meta = lw.lane_findings(_tickets(), now_ts=NOW, stall_required=True)
    assert len(out) == 1
    fd = out[0]
    assert fd["severity"] == "low" and fd["legs"] == [lw.LEG_DATA_UNREADABLE]
    assert "stall legs did not run" in fd["subject"]
    assert "UNVERIFIED" in fd["why"]
    assert meta["stall"]["by_leg"][lw.LEG_DATA_UNREADABLE] == 1


def test_d3_with_ledger_the_hits_surface_with_tokens_and_meta_counts():
    rows = [_landing(), _freeze()]
    sf = _facts(rows)
    out, meta = lw.lane_findings(_tickets(), now_ts=NOW, stall_facts=sf,
                                 stall_required=True,
                                 thresholds={"cert_wait_overdue_min": 60,
                                             "freeze_without_remedy_min": 60})
    legs = sorted(l for fd in out for l in fd["legs"])
    assert legs == sorted([lw.LEG_CERT_WAIT, lw.LEG_FREEZE_NO_REMEDY])
    by_subject = {fd["legs"][0]: fd for fd in out}
    assert by_subject[lw.LEG_CERT_WAIT]["ticket_id"] == "t-fix"
    assert by_subject[lw.LEG_FREEZE_NO_REMEDY]["line"] == LINE
    assert meta["stall"]["by_leg"][lw.LEG_CERT_WAIT] == 1
    assert meta["stall"]["by_leg"][lw.LEG_FREEZE_NO_REMEDY] == 1
    assert meta["stall"]["thresholds"]["cert_wait_overdue_min"] == 60
    sec = lw.lane_section(out, meta)
    assert sec["by_leg"][lw.LEG_CERT_WAIT] == 1
    assert sec["by_leg"][lw.LEG_RERUN] == 0
    assert sec["stall"]["ledger_supplied"] is True


def test_d4_ticket_findings_and_stall_findings_coexist():
    thrashed = _ticket("t-thrash", suite_rounds=5)
    rows = [_landing()]
    sf = _facts(rows)
    out, meta = lw.lane_findings([thrashed], now_ts=NOW, stall_facts=sf,
                                 stall_required=True,
                                 thresholds={"cert_wait_overdue_min": 60})
    assert meta["by_leg"][lw.LEG_RERUN] == 1        # ticket trio contract unchanged
    assert meta["stall"]["by_leg"][lw.LEG_CERT_WAIT] == 1
    assert len(out) == 2


def test_d5_clean_ledger_is_zero_findings_and_slots_stay_visible():
    rows = [_landing(at=NOW_MS - 1 * H)]  # landed an hour ago: inside any window
    sf = _facts(rows)
    out, meta = lw.lane_findings([], now_ts=NOW, stall_facts=sf, stall_required=True)
    assert out == []
    assert meta["stall"]["by_leg"] == {k: 0 for k in lw.STALL_LEGS}
    assert set(meta["stall"]["parse_notes"]) == set()
