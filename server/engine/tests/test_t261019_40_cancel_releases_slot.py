# -*- coding: utf-8 -*-
"""261019: cancelling a ticket returns its concurrency slot.

Measured twice in one night: a TERMINATED ticket keeps its slot because
terminate runs no cleanup and nothing else took the job. dengzhufpv: five
terminated tickets held all five slots while the only two live tickets queued
for hours. sandbar: five of seven slots held by dead tickets, nine live tickets
starved. The queue-side fix (heartbeat + live-head promotion) stops a corpse
from being *promoted*; this closes the other half, where the slot is already
held and the only actor left is the CLI that terminated it.

Coverage:
- the helper's contract: names the project it releases in, refuses to guess one
  (an empty project must never free somebody else's slot), and reports a
  failure as a note on the receipt rather than failing the cancel (the
  terminate already happened, and a dead slot is repairable with
  `ticket.py op=concurrency reconcile=true`);
- the wiring: the cancel path calls it AFTER terminate and rides the receipt
  as `slot_released` (source anchors — the cancel path itself needs Temporal).

No Temporal, no network: `concurrency.release` is monkeypatched.
"""
import os

import client as cl
import concurrency as cc

CLIENT_PY = os.path.join(os.path.dirname(__file__), "..", "client.py")


def test_release_names_the_project_and_reports_the_promotion(monkeypatch):
    seen = {}

    def fake_release(project, ticket, cause):
        seen.update(project=project, ticket=ticket, cause=cause)
        return {"released": True, "promoted": "next-up", "dropped_stale": ["corpse"],
                "holders": 1, "waiting": 0}

    monkeypatch.setattr(cc, "release", fake_release)
    out = cl._release_slot_after_cancel("dengzhufpv", "t1")
    assert seen == {"project": "dengzhufpv", "ticket": "t1", "cause": "terminated"}
    assert out["released"] is True and out["promoted"] == "next-up"
    assert out["dropped_stale"] == ["corpse"]


def test_release_refuses_to_guess_a_project(monkeypatch):
    called = []
    monkeypatch.setattr(cc, "release", lambda *a, **k: called.append(a))
    out = cl._release_slot_after_cancel("", "t1")
    assert called == [], "an unknown project must never free another project's slot"
    assert out == {"released": False, "reason": "project_unknown"}


def test_a_release_fault_is_a_named_note_never_a_failed_cancel(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ledger locked")

    monkeypatch.setattr(cc, "release", boom)
    out = cl._release_slot_after_cancel("sandbar", "t1")
    assert out["released"] is False
    assert "RuntimeError" in out["reason"] and "reconcile=true" in out["reason"], \
        "the note must tell the operator how to repair the slot"


def test_cancel_calls_the_release_after_terminate():
    src = open(CLIENT_PY, encoding="utf-8").read()
    lines = src.splitlines()
    # the LAST terminate call is the ticket-cancel one (close_out has its own)
    term_line = max(i for i, l in enumerate(lines)
                    if "await handle.terminate(reason=reason)" in l)
    call_line = next(i for i, l in enumerate(lines)
                     if "_release_slot_after_cancel(" in l and "def " not in l)
    assert call_line > term_line, \
        "the release must follow the terminate, never precede it"
    body = "\n".join(lines[term_line:call_line])
    assert "except Exception" in body, \
        "a release fault must be caught between terminate and the receipt"
    assert '"slot_released": _slot' in src
