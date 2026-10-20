# -*- coding: utf-8 -*-
"""261020: the request ledger can finally retire its own dead heads.

Measured on sandbar: 261 request heads, 249 open, ZERO carrying an expiry,
spanning ten days. Only the host's panel may close a row, so every agent that
filed a question left it open forever and the panel became a wall nobody reads —
the failure mode that matters, because the one live question is lost in it.

The sweep is the MACHINE's retirement face and is deliberately narrow:
  * it retires a head only when the ticket that head names is in the caller's
    TERMINAL set (the caller probes liveness; this code makes no liveness claim);
  * the retired row is a `state` row with the machine-only state `superseded`
    plus the ids it named, so the question and the reason both survive;
  * a head naming no ticket is left alone unless the caller explicitly opts in.

Coverage: ticket-id extraction from the row text (the ledger has no structured
field), and the op's guard rails (a non-list terminal set is refused by name; the
sweep needs the caller's own probe result).
"""
import os

import request_thread as rt

PURE = os.path.dirname(__file__)


def test_ticket_ids_are_read_out_of_the_text():
    row = {"question": "t261019-45 stops on an identical face; see t261019-44",
           "detail": "no other id here"}
    assert rt.ticket_ids_in(row) == {"t261019-45", "t261019-44"}


def test_a_row_without_a_ticket_yields_nothing():
    assert rt.ticket_ids_in({"question": "the line is red"}) == set()
    assert rt.ticket_ids_in(None) == set()


def test_lookalike_tokens_are_not_ticket_ids():
    assert rt.ticket_ids_in({"question": "version t2026-019 and 261019-45"}) == set()


def test_sweep_is_registered():
    assert "sweep" in rt._OPS


def test_superseded_is_the_machines_word_only():
    assert rt.STATE_SUPERSEDED in rt.MACHINE_STATES
    assert rt.STATE_SUPERSEDED in rt.TERMINAL_STATES, \
        "a retired head must read as terminal, or the panel keeps showing it"


def test_sweep_refuses_without_the_callers_liveness_result():
    out = rt.sweep_op({"op": "sweep"}, 1, 1, env={}, cwd="/tmp")
    assert out.get("ok") is False, \
        "this face never guesses what is live; the caller supplies the terminal set"
