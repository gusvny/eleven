"""t261009-80 honest pause/resume receipt + face effect statement (unit layer).

Incident KI-01M4HQ5FJ8HKGY156YCE97X0K7: a pause accepted on a ticket that can
never reach a segment boundary (blocked / awaiting-human) changed nothing
observable, and the receipt read like it took effect. This file pins the pure
layer: the three-state landing evaluator (with baseline refusal masking), the
effect-statement wording (including the review-condition-2 pairing
`landing: landed` + will-not-take-effect wording on a blocked ticket), the
single-snapshot-read discipline, malformed-snapshot degradation, the receipt
face key set (review condition 4), and the client/ticket wording-consistency
pin. Workflow-runtime behaviour belongs to the integration scenario, not here.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import client
from client import (
    PAUSE_BLOCKED_EFFECT,
    PAUSE_BOUNDARY_EFFECT,
    RESUME_EFFECT,
    _pause_receipt_face,
    evaluate_pause_landing,
    pause_effect_statement,
)

REPO = Path(__file__).resolve().parents[3]


def _load_ticket_mod():
    """Load server/tools/ticket.py standalone (stdlib-only module; the engine
    venv has no Temporal server involved — this is a plain module load)."""
    name = "_ticket_t261009_80"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "server" / "tools" / "ticket.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- landing evaluator: three states ----

def test_landing_pause_landed_on_true():
    snap = {"paused": True, "paused_phase": "pending"}
    assert evaluate_pause_landing([], snap, "pause") == ("landed", "pending")
    snap["paused_phase"] = "at_gate"
    assert evaluate_pause_landing([], snap, "pause") == ("landed", "at_gate")


def test_landing_resume_landed_on_false():
    assert evaluate_pause_landing([], {"paused": False}, "resume") == ("landed", "")


def test_landing_pending_when_state_absent():
    # old worker / missing key / non-dict snapshot -> never a fake landed
    assert evaluate_pause_landing([], {}, "pause") == ("pending", None)
    assert evaluate_pause_landing([], {"paused": None}, "pause") == ("pending", None)
    assert evaluate_pause_landing([], None, "pause") == ("pending", None)
    assert evaluate_pause_landing([], "junk", "resume") == ("pending", None)
    assert evaluate_pause_landing([], {}, "resume") == ("pending", None)


def test_landing_refused_new_entry_wins_over_paused_true():
    # repeated pause: paused stays True but a NEW refusal is the truth -> refused
    snap = {"paused": True, "paused_phase": "pending",
            "refused": [{"who": "host", "want": "pause",
                         "why": "already paused (idempotent refusal)"}]}
    state, why = evaluate_pause_landing([], snap, "pause")
    assert state == "refused"
    assert "already paused" in why


def test_landing_baseline_refusals_are_masked():
    # a refusal that existed BEFORE delivery must not be misattributed
    baseline = [{"who": "host", "want": "pause", "why": "old refusal"}]
    snap = {"paused": False, "refused": [{"who": "host", "want": "pause",
                                          "why": "old refusal"}]}
    assert evaluate_pause_landing(baseline, snap, "pause") == ("pending", None)
    # same who, NEW why -> a genuinely new refusal -> refused
    snap["refused"].append({"who": "host", "want": "pause", "why": "new refusal"})
    state, why = evaluate_pause_landing(baseline, snap, "pause")
    assert state == "refused" and why == "new refusal"


def test_landing_other_ops_refusals_ignored():
    snap = {"paused": True,
            "refused": [{"who": "h", "want": "rework", "why": "x"},
                        {"who": "h", "want": "pause", "why": "y"}]}
    state, _ = evaluate_pause_landing([], snap, "pause")
    assert state == "refused"  # only the pause-shaped one counts; rework ignored
    assert evaluate_pause_landing([], {"paused": True}, "sign") == ("pending", None)


# ---- effect statement (single snapshot read; review condition 3) ----

def test_effect_not_paused_is_empty():
    assert pause_effect_statement(False, "blocked", "awaiting-human") == ""
    assert pause_effect_statement(None, "running", "") == ""
    assert pause_effect_statement("", "running", "") == ""


def test_effect_running_pause_names_the_boundary():
    assert pause_effect_statement(True, "running", "") == PAUSE_BOUNDARY_EFFECT
    assert pause_effect_statement(True, None, "") == PAUSE_BOUNDARY_EFFECT


def test_effect_blocked_pause_names_the_non_effect_and_slot():
    for status, stage in (("blocked", ""), ("", "awaiting-human"),
                          ("blocked", "awaiting-human")):
        assert pause_effect_statement(True, status, stage) == PAUSE_BLOCKED_EFFECT
    assert "will not take effect" in PAUSE_BLOCKED_EFFECT
    assert "slot stays held" in PAUSE_BLOCKED_EFFECT


# ---- receipt face: key set pinned (review condition 4) ----

def test_receipt_face_keeps_existing_keys_and_adds_honest_ones():
    snap = {"paused": True, "paused_phase": "pending", "status": "running",
            "stage_state": ""}
    face = _pause_receipt_face("t1", "pause", "host", "landed", None, snap)
    # existing key set preserved, delivered semantics untouched
    assert face["ticket_id"] == "t1" and face["signal"] == "pause"
    assert face["who"] == "host" and face["delivered"] is True
    assert face["landing"] == "landed"
    assert face["paused"] is True and face["paused_phase"] == "pending"
    assert face["effect"] == PAUSE_BOUNDARY_EFFECT


def test_receipt_face_blocked_landed_pairing_is_non_success_read():
    # review condition 2: landing=landed AND will-not-take-effect wording must
    # coexist so the honesty wording cannot regress into a success read.
    snap = {"paused": True, "paused_phase": "pending", "status": "blocked",
            "stage_state": ""}
    face = _pause_receipt_face("t1", "pause", "host", "landed", None, snap)
    assert face["landing"] == "landed"
    assert face["effect"] == PAUSE_BLOCKED_EFFECT
    assert "will not take effect" in face["effect"]
    assert "slot stays held" in face["effect"]


def test_receipt_face_resume_landed_names_the_clear():
    snap = {"paused": False, "paused_phase": "", "status": "running"}
    face = _pause_receipt_face("t1", "resume", "host", "landed", None, snap)
    assert face["landing"] == "landed" and face["paused"] is False
    assert face["effect"] == RESUME_EFFECT


def test_receipt_face_refused():
    face = _pause_receipt_face("t1", "pause", "host", "refused",
                               "already paused", {"paused": True})
    assert face["landing"] == "refused" and face["refused_why"] == "already paused"
    assert face["delivered"] is True
    assert "effect" not in face and "paused" not in face


def test_receipt_face_unconfirmed_keeps_delivered_and_names_recheck():
    face = _pause_receipt_face("t1", "pause", "host", "unconfirmed", None, None)
    assert face["delivered"] is True
    assert face["landing"] == "unconfirmed"
    assert face["effect"] == ""  # no fake prediction without a snapshot
    assert "op=query" in face["receipt_note"]


def test_receipt_face_non_dict_snapshot_degrades():
    face = _pause_receipt_face("t1", "pause", "host", "landed", None, "junk")
    assert face["paused"] is None and face["paused_phase"] == ""
    assert face["effect"] == ""


# ---- bounded landing poll: full-terminal-state paths ----

def _fake_handle(snaps, fail_first=0):
    state = {"i": 0, "failed": 0}

    class H:
        async def query(self, name):
            i = state["i"]
            state["i"] += 1
            if i < fail_first:
                state["failed"] += 1
                raise RuntimeError("transient jitter")
            return snaps[min(i, len(snaps) - 1)]

    return H()


def test_poll_lands_on_first_good_snapshot():
    snaps = [{"paused": True, "paused_phase": "pending"}]
    st, pl, last = asyncio.run(_await("pause", snaps))
    assert (st, pl) == ("landed", "pending") and last["paused"] is True


async def _await(op, snaps, **kw):
    return await client._await_pause_landing(_fake_handle(snaps, **kw), [], op,
                                             polls=3, base_delay=0.001,
                                             max_delay=0.002, timeout=0.5)


def test_poll_treats_query_failure_as_transient_then_lands():
    snaps = [None, {"paused": True, "paused_phase": "at_gate"}]
    st, pl, _ = asyncio.run(_await("pause", snaps, fail_first=1))
    assert (st, pl) == ("landed", "at_gate")


def test_poll_budget_exhaustion_returns_pending_with_last_snapshot():
    snaps = [{}]  # never lands
    st, pl, last = asyncio.run(_await("pause", snaps))
    assert st == "pending" and pl is None and last == {}


# ---- wording consistency: client.py is the truth source, ticket.py mirrors it ----

def test_ticket_face_wording_matches_client_truth():
    t = _load_ticket_mod()
    cases = [(False, "running", ""), (True, "running", ""),
             (True, "blocked", ""), (True, "", "awaiting-human")]
    for paused, status, stage in cases:
        assert t._pause_effect_of(paused, status, stage) == \
            pause_effect_statement(paused, status, stage), (paused, status, stage)
    assert t._PAUSE_BOUNDARY_EFFECT == PAUSE_BOUNDARY_EFFECT
    assert t._PAUSE_BLOCKED_EFFECT == PAUSE_BLOCKED_EFFECT


def test_ticket_face_effect_landed_on_blocked_names_non_effect():
    t = _load_ticket_mod()
    eff = t._pause_effect_of(True, "blocked", "")
    assert "will not take effect" in eff and "slot stays held" in eff
