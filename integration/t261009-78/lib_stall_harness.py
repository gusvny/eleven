#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_stall_harness.py — shared fixture/preparation helper for t261009-78
scenarios (grey-box L2, offline seconds, zero docker/Temporal/browser).

Contract discovery only: this lib binds to the PUBLIC face named by the ticket
(the lane watchdog judgement face and the three stall leg tokens
cert-wait-overdue / freeze-without-remedy / repair-points-nowhere) and degrades
by NAME when a contract piece is absent (TDD signal pre-implement). It never
binds to private helpers or internal row plumbing.

Shared by:
  sc_buffer_stall_legs_fire.py   (the three legs fire with named facts)
  sc_buffer_stall_failclosed.py  (cannot-tell is never rendered as fine)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"

NOW_MS = 1_790_430_000_000          # fixed "now" in ledger milliseconds
NOW_S = NOW_MS / 1000.0             # same instant in watchdog seconds
WINDOW_MIN = 1440                  # declared window (minutes) used in fixtures
WINDOW_MS = WINDOW_MIN * 60 * 1000

#: the three stall leg tokens are the ticket's public contract
CERT_WAIT = "cert-wait-overdue"
FREEZE_NO_REMEDY = "freeze-without-remedy"
REPAIR_NOWHERE = "repair-points-nowhere"

_CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")


def load_watchdog():
    """Import the lane watchdog module from server/engine.

    Returns the module, or (None, reason) when the engine module cannot be
    imported (environment red, exit 2 — never a fake assertion red).
    """
    if not ENGINE.is_dir():
        return None, "engine module dir missing: %s" % ENGINE
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        import inspection_lane_watchdog as lw  # noqa: E402
    except Exception as exc:  # unimportable engine = environment red
        return None, "inspection_lane_watchdog unimportable: %r" % (exc,)
    return lw, ""


def contract_fn(lw, candidates, what):
    """Discover a public function by candidate names. Returns (fn|None, err).

    A missing capability is a NAMED FAIL (TDD signal), never a silent skip.
    """
    for name in candidates:
        fn = getattr(lw, name, None)
        if callable(fn):
            return fn, ""
    return None, "contract missing: no %s among %s" % (what, list(candidates))


# ---- fixture rows (shapes follow the delivery-ledger public contract: kinds
# ---- landing / certification / freeze / freeze_change / relations rel-*) ----

def landing_row(rid, ticket, line, at_ms, revision="r42", seq=1):
    return {"kind": "landing", "id": rid, "ticket": ticket, "line": line,
            "at": at_ms, "actor": "agent-fixture", "seq": seq,
            "repos": [{"repo": "sandbar", "revision": revision}]}


def cert_row(rid, line, at_ms, seq=1):
    """A certification cites its run; it deliberately carries NO verdict field
    (the run's verdict is read through the run-verdict reader — record-models
    section A: restating would be a second stored answer)."""
    return {"kind": "certification", "id": rid, "line": line, "at": at_ms,
            "run": "run-fixture-1", "booked_red": "no", "judged_by": "agent",
            "seq": seq, "repos": [{"repo": "sandbar", "revision": "r41"}]}


def freeze_row(rid, line, at_ms, cert="cert-cause", seq=1):
    return {"kind": "freeze", "id": rid, "line": line, "at": at_ms,
            "cause": cert, "seq": seq}


def relation_row(rid, kind, ticket, ref, at_ms, evidence=None, seq=1,
                 supersedes_relation=None):
    """A relation asserts an attribution: the evidence shape is declared
    (what in revision/patch_id/ticket/certification/path_line + ref) and the
    recorder may never be the beneficiary (``from``) — so the recorder here is
    the patrol, an outside actor."""
    row = {"kind": kind, "id": rid, "from": ticket, "to": ref, "at": at_ms,
           "recorded_by": "patrol-fixture", "reason": "fixture reason",
           "evidence": evidence or {"what": "ticket", "ref": ref},
           "seq": seq}
    if evidence is not None:
        row["evidence"] = evidence
    if supersedes_relation is not None:
        row["supersedes_relation"] = supersedes_relation
    return row


def in_flight_facts(ticket_id):
    """Minimal ticket facts dict: in flight, no human gate, quiet timeline
    (so only the stall legs can fire on this ticket, never the thrash legs)."""
    return {"ticket_id": ticket_id, "project": "sandbar",
            "workflow_id": ticket_id, "stage": "develop_buffer",
            "stage_state": "running", "status": "dispatched",
            "verdict": "", "verdict_at": 0.0,
            "suite_rounds": 0, "suite_entries": [],
            "last_activity_at": NOW_S, "created_at": NOW_S,
            "paused": False, "blocked_reason": "", "parse_notes": []}


def human_gate_facts(ticket_id):
    """Ticket parked at a human gate: NOT a stall (the existing suppression)."""
    f = in_flight_facts(ticket_id)
    f.update({"paused": True, "blocked_reason": "awaiting human review"})
    return f


# ---- assertion helpers (three states: PASS / FAIL named / ENV_FAIL) --------

def all_legs(findings):
    """Every leg token named in the findings list (aggregated shape: each
    finding carries a legs list; tolerate a flat leg field too)."""
    toks = []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        for l in (f.get("legs") or []):
            toks.append(str(l))
        if f.get("leg"):
            toks.append(str(f.get("leg")))
    return toks


def findings_with_leg(findings, token):
    return [f for f in (findings or [])
            if isinstance(f, dict) and token in all_legs([f])]


def blob(findings):
    """Case-insensitive text of the whole findings face, for named-fact checks
    (data fields must appear untranslated somewhere a human can read them)."""
    return json.dumps(findings, ensure_ascii=False, default=str)


def check_outcomes(results):
    """Print a SUMMARY line and exit by the three-state protocol."""
    fails = [r for r in results if not r[0]]
    for name, ok_, detail in results:
        print("%s %s%s" % ("PASS" if ok_ else "FAIL", name,
                           (" :: " + detail) if detail else ""))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
          % (len(results) - len(fails), len(fails)))
    if fails:
        sys.exit(1)
    sys.exit(0)


def english_copy_ok(findings):
    """Findings copy is English (261004 STE rule); data fields untranslated is
    fine — CJK ideographs/fullwidth punctuation anywhere in copy is not."""
    return not _CJK.search(blob(findings)), "CJK characters in findings copy"


def call_lane_findings(lane_findings, tickets, **kw):
    """Call lane_findings with the stall inputs; a TypeError on the new keyword
    is the pre-implement TDD signal, surfaced by the caller as named FAIL.

    The declared window is pinned through the EXISTING public thresholds input
    (same declared/resolved way as the current legs), so the scenarios bind to
    the contract, not to whatever the shipped default happens to be."""
    thr = dict(kw.pop("thresholds", None) or {})
    thr.setdefault("cert_wait_overdue_min", WINDOW_MIN)
    thr.setdefault("freeze_without_remedy_min", WINDOW_MIN)
    kw.setdefault("stall_required", True)   # the patrol declares it judges the buffer
    return lane_findings(tickets, now_ts=NOW_S, thresholds=thr, **kw)
