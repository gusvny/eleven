"""t261018-11 unit tests: terminal-face honesty at the engine read boundary.

The ticket: a COMPLETED dev-lane ticket's frozen return snapshot says
status=closed + stage_state=awaiting + signatures={} while its acceptance list
claims "Human sign-off recorded" — the served face must not keep a waiting word
for a workflow that has ended, and the acceptance line must state the real gate
disposition (satisfied by the develop-buffer landing, or explicitly unreadable).

Locked layers (all in server/engine/client.py, the write set):
  - `_terminal_face_reconcile`: pure helper, one honesty ladder;
  - the COMPLETED detail face (cmd_ticket_query) and the hydrate meta both
    reconcile (word `closed`, honest acceptance, close_ts, meta note);
  - the past-window COMPLETED minimal row carries `closed`, never `awaiting`
    (the relapse path), with the label inside the existing `title` key
    (row-family parity, no new top-level row key).

Run: server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_t261018_11_terminal_face_honesty.py -q
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import client as cl  # noqa: E402

CLAIM = cl._TERMINAL_SIGN_OFF_CLAIM
LANDED = cl._TERMINAL_LANDED_ACCEPTANCE
UNREADABLE = cl._TERMINAL_UNREADABLE_ACCEPTANCE


def _frozen_snap(**over):
    """The evidence shape (t261018-05 and siblings): a frozen close-out snapshot."""
    snap = {
        "engine": "v2",
        "ticket_id": "t261018-05",
        "status": "closed",
        "stage": "merge",
        "stage_state": "awaiting",
        # The FROZEN result() snapshot carries NO top-level stage_acceptance —
        # the only acceptance carrier is meta["acceptance"] (dev_lane._enter
        # copy); anchored to the real shape after the arbitrate code-fault.
        "signatures": {},
        "timeline": [{"note": "merge done (engine:land: develop-buffer landing)"}],
        "meta": {
            "id": "t261018-05",
            "status": "closed",
            "stage_state": "awaiting",
            "acceptance": [CLAIM, "Merge booked + lane cleaned up"],
            "checks": {"merge": [{"done": True, "by": "engine:land",
                                  "evidence": "develop-buffer landing"}]},
        },
    }
    snap.update(over)
    return snap


# ---------- truth rows: the evidence shape gets an honest face ----------

def test_evidence_shape_reconciles_word_acceptance_note():
    out = cl._terminal_face_reconcile(_frozen_snap(), "COMPLETED", 1700000000.0)
    assert out["stage_state"] == "closed"
    assert out["meta"]["stage_state"] == "closed"
    assert LANDED in out["meta"]["acceptance"]
    assert CLAIM not in out["meta"]["acceptance"]
    assert "Merge booked + lane cleaned up" in out["meta"]["acceptance"]
    # the frozen carrier is meta["acceptance"] — the reconciliation must land there
    assert out.get("stage_acceptance") is None  # not fabricated on the frozen shape
    assert out["meta"]["close_ts"] == 1700000000.0
    assert out["meta"]["close_time_txt"]


def test_top_level_projection_carrier_reconciled_defensively():
    # a LIVE snapshot query projects stage_acceptance top-level; when present it
    # is reconciled too, and both carriers agree.
    snap = _frozen_snap()
    snap["stage_acceptance"] = [CLAIM, "Merge booked + lane cleaned up"]
    out = cl._terminal_face_reconcile(snap, "COMPLETED", 1.0)
    assert LANDED in out["stage_acceptance"]
    assert out["stage_acceptance"] == out["meta"]["acceptance"]
    note = out["meta"]["terminal_face_note"]
    assert "awaiting -> closed" in note and "engine:land" in note


def test_close_time_unreadable_is_named_not_guessed():
    out = cl._terminal_face_reconcile(_frozen_snap(), "COMPLETED", 0.0)
    assert "close_ts" not in out["meta"]
    assert "close time unavailable" in out["meta"]["terminal_face_note"]


def test_awaiting_human_word_also_reconciles():
    snap = _frozen_snap(stage_state="awaiting-human")
    snap["meta"]["stage_state"] = "awaiting-human"
    out = cl._terminal_face_reconcile(snap, "COMPLETED", 1.0)
    assert out["stage_state"] == "closed"


def test_claim_without_land_proof_says_not_signed():
    snap = _frozen_snap()
    snap["meta"]["checks"] = {}
    out = cl._terminal_face_reconcile(snap, "COMPLETED", 1.0)
    assert UNREADABLE in out["meta"]["acceptance"]
    assert LANDED not in out["meta"]["acceptance"]
    assert "not signed" in out["meta"]["terminal_face_note"]


# ---------- a real signature keeps the acceptance honest-and-true ----------

def test_signed_ticket_acceptance_untouched():
    snap = _frozen_snap(signatures={"merge": {"who": "host", "decision": "approve"}})
    out = cl._terminal_face_reconcile(snap, "COMPLETED", 1.0)
    assert CLAIM in out["meta"]["acceptance"]
    assert out["stage_state"] == "closed"  # word still reconciles


# ---------- pass-through guards: no over-broad rewriting ----------

@pytest.mark.parametrize("exec_status", ["RUNNING", "FAILED", "CANCELED", ""])
def test_non_completed_passes_through(exec_status):
    snap = _frozen_snap()
    assert cl._terminal_face_reconcile(snap, exec_status, 1.0) is snap


def test_status_not_closed_passes_through():
    snap = _frozen_snap(status="dispatched")
    assert cl._terminal_face_reconcile(snap, "COMPLETED", 1.0) is snap


def test_terminal_word_already_served_passes_through():
    snap = _frozen_snap(stage_state="closed")
    assert cl._terminal_face_reconcile(snap, "COMPLETED", 1.0) is snap


# ---------- malformed-input discipline (untrusted external input) ----------

def test_non_dict_snap_returns_as_is():
    assert cl._terminal_face_reconcile(None, "COMPLETED", 1.0) is None
    assert cl._terminal_face_reconcile("garbage", "COMPLETED", 1.0) == "garbage"


def test_malformed_shapes_never_throw_and_conservatively_not_signed():
    snap = {
        "status": "closed", "stage_state": "awaiting",
        "signatures": 123,                       # malformed: truthy -> claim treated as signed? no:
        # signatures non-empty-looking garbage is NOT a real signature proof, but the
        # helper's contract is: only EMPTY means unsigned; garbage is left alone.
        "stage_acceptance": "not-a-list",
        "meta": {"checks": {"merge": "garbage"}, "acceptance": None},
    }
    out = cl._terminal_face_reconcile(snap, "COMPLETED", 1.0)
    assert out["stage_state"] == "closed"        # the word always heals
    assert out["stage_acceptance"] == "not-a-list"  # malformed list untouched
    assert "terminal_face_note" in out["meta"]


def test_missing_meta_still_reconciles_word():
    snap = {"status": "closed", "stage_state": "awaiting",
            "signatures": {}, "meta": {"acceptance": [CLAIM]}}
    out = cl._terminal_face_reconcile(snap, "COMPLETED", None)
    assert out["stage_state"] == "closed"
    assert UNREADABLE in out["meta"]["acceptance"]
    assert out["meta"]["terminal_face_note"]


# ---------- the past-window minimal row (the relapse path) ----------

class _FakeAsyncForList:
    """Drives the list-row assembly indirectly is heavy; instead pin the word the
    minimal-row branch serves via a source check PLUS the pure helper contract.
    The branch itself is a dict literal in cmd-level code; the source assertion
    below keeps it honest without a live Temporal client."""

    pass


def test_minimal_row_branch_serves_closed_not_awaiting():
    src = (POC / "client.py").read_text(encoding="utf-8")
    marker = src.index("snapshot unavailable (closed past the window")
    block = src[marker:marker + 1600]
    assert '"stage_state": "closed" if exec_status == "COMPLETED" else "awaiting"' in block
    assert '"stage_state": "awaiting",' not in block
    # row-family parity: the reconciliation label rides inside `title`, no new key
    assert "terminal_face_note" not in block
    assert "stage_state reconciled: awaiting -> closed" in block


# ---------- consumer sweep pins (Delta 2: classify the new served word) ----------

def test_awaiting_gate_consumer_keys_on_awaiting_human_not_closed():
    # client.py ~2533: awaiting_gate derivation only fires on 'awaiting-human';
    # the reconciled word 'closed' must not flip it (closed ticket is not a gate).
    src = (POC / "client.py").read_text(encoding="utf-8")
    assert '"awaiting_gate": stage_state == "awaiting-human"' in src


def test_live_workflow_vocabulary_out_of_reach_statement():
    # dev_lane.py:6657 matches live meta awaiting-human; the read boundary cannot
    # reach it and must not try. Recorded here so the sweep classification is
    # explicit in a runnable form (the workflow-side vocabulary is untouched).
    lane_src = (POC / "dev_lane.py").read_text(encoding="utf-8")
    assert 'stage_state"] = "awaiting"' in lane_src  # producer word unchanged (follow-up ticket)
