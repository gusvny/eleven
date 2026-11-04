#!/usr/bin/env python3
"""t261031-20 L1 battery: the gate receipt must name the tree it judged.

Incident (project-vision integration report): three tickets went "gate red -> arbitrate
says it changed the criterion -> straight to merge", and the human signature rested on
a FAILED receipt. Root cause in code:

  * the suite receipt carries no tree identity (`dev_lane.py` results literal);
  * `arbitrate` / `acceptance_walkthrough` commit their own writes after the round;
  * the only mechanical tree check on that line (the KI-220 green-run item) was removed
    by the host order of 261009;
  * the closing run replaces the pass basis but never the receipt face.

The fix: a receipt is valid only for the tree it ran on. Layers pinned here:

  a. `gate_receipt_freshness` truth table + malformed shapes (pure);
  b. `gate_receipt_void_text` names both exits, and never claims who committed (R4);
  c. `gate_receipt_surface` vocabulary (C4 iv);
  d. `gate_receipt_delta_causes` - main sync of THIS pass, `auto_settle` (a commit, not
     an attempt), `foreign_repair:<sha>` (K1), dedupe, malformed input;
  e. `_gate_receipt_arm` - patched OR the event-gated arm (S1: every command site);
  f. anchor recorder: resolves the head FIRST, one identity with the face key, a
     resolver failure writes `gate_receipt_note` and mints nothing (R5);
  g. guard: fresh / stale / no_receipt / unprovable, the caps (2 stale re-runs, 1
     no-receipt re-run, 0 unprovable rounds), the counter window and its resets;
  g2. t261104-03: a successful live probe supersedes a stale miss note (the note
     is dropped and the drop recorded), a failing probe keeps it, and a cleared
     note still spends the one no-receipt round;
  h. the merge-line delta: written only when the head moved, `land_sha` refreshed (K2);
  i. the closing run replaces the face receipt in place, surface named;
  j. the real main loop: fresh -> merge; a main sync lands as a named delta and does not
     void; a stale receipt routes back to the gate;
  k. source locks: the arm sits at every command site, the guard runs before `_enter`
     and before the main sync, the two handler resets sit outside the E9DAA05 gate, one
     AST-visible receipt assignment survives, and the self-heal row precedes the
     rehearsal.

Run: server/engine/.venv/bin/python -B -m pytest \
  server/engine/tests/test_261031_20_gate_receipt_freshness.py -q
"""
from __future__ import annotations

import ast
import asyncio
import datetime
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
from shared import IntegrationRunResult  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
TICKET = "t26103120ut"


# ---------------------------------------------------------------------------
# framework stubs
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _restore_workflow_module():
    """Every test may replace `dev_lane.workflow`; restore it afterwards."""
    original = dev_lane.workflow
    try:
        yield
    finally:
        dev_lane.workflow = original


def _wf(patched_ids=(), head=SHA_A, now=None):
    """A permissive workflow facade: only the ids in `patched_ids` are live."""
    ids = set(patched_ids)
    state = {"head": head, "commands": [], "now": now}

    async def _execute_activity(activity, args=None, **kw):
        name = (getattr(activity, "name", None) or getattr(activity, "__name__", "")
                or str(activity))
        state["commands"].append(name)
        if name == "lane_head_sha":
            return {"ok": True, "sha": state["head"], "error": ""}
        raise AssertionError("unexpected activity on the unit shell: %s" % name)

    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid in ids,
        now=lambda: state["now"] or datetime.datetime(
            2026, 10, 31, 12, 0, 0, tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        execute_activity=_execute_activity,
        sleep=lambda *_a, **_k: asyncio.sleep(0),
        upsert_memo=lambda *a, **k: None,
        info=lambda: SimpleNamespace(start_time=datetime.datetime(
            2026, 1, 1, tzinfo=datetime.timezone.utc)),
        wait_condition=None)
    return state


def _shell(meta=None):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = TICKET
    wf.meta = dict(meta or {})
    wf.meta.setdefault("worktree", "/tmp/ut-lane")
    wf.meta.setdefault("branch", "ut")
    wf.meta.setdefault("log", [])
    wf.meta.setdefault("handoffs", [])
    wf.meta.setdefault("checks", {})
    wf.timeline = []
    wf.refused = []
    wf.results = {}
    wf.signatures = {}
    wf.human_context = {}
    wf.gate_runs = []
    wf.engine_version = 2
    wf._gens = {}
    wf._detail_face_on = False
    wf._narrowed_anchor_enabled = False
    wf._gate_receipt_guard_enabled = False
    wf._receipt_void_rounds = 0
    wf._ledger_enqueue = lambda entry: None
    wf._ledger_marks = []
    wf._annex_requests = []
    wf._terminal_slot_pending = False
    wf._conflict_rounds = 0
    wf._prev_conflict_files = []
    wf._rework = None
    wf._retry_token = 0
    wf._arb_over_limit_seq = 0
    wf._acc_verdict_seq = 0
    wf._terminal_slot_pending = False
    return wf


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 12)
        self.passed = kw.get("passed", 10)
        self.failed = kw.get("failed", 2)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", ["sc_x"])
        self.error = kw.get("error", "")
        self.details = kw.get("details", [{"name": "sc_x", "cmd": "", "exit": 1,
                                           "output_tail": ""}])


ANCHOR = {"receipt_sha": SHA_A, "deltas": [], "surface": "full suite",
          "ran": 12, "failed": 2, "env_fail": 0, "green": False,
          "closing": False, "at": 1, "merge_face": {}}


# ---------------------------------------------------------------------------
# a. the state machine (pure)
# ---------------------------------------------------------------------------
def test_fresh_when_head_equals_the_receipt():
    assert dev_lane.gate_receipt_freshness(ANCHOR, SHA_A) == ("fresh", "")


def test_fresh_against_the_last_delta_head():
    anchor = dict(ANCHOR, deltas=[{"from": SHA_A, "to": SHA_B,
                                   "cause": "main_sync", "at": 2}])
    assert dev_lane.gate_receipt_freshness(anchor, SHA_B, base_sha=SHA_B)[0] == "fresh"
    assert dev_lane.gate_receipt_freshness(anchor, SHA_C, base_sha=SHA_B)[0] == "stale"


def test_stale_names_the_measured_tree_and_the_current_head():
    state, reason = dev_lane.gate_receipt_freshness(ANCHOR, SHA_C)
    assert state == "stale"
    assert SHA_A[:12] in reason and SHA_C[:12] in reason
    # R4: the reason names measurements, never a committer
    assert "committed" not in reason and "arbitrate committed" not in reason


def test_no_receipt_when_no_anchor_and_no_note():
    for receipt in (None, {}):
        assert dev_lane.gate_receipt_freshness(receipt, SHA_A)[0] == "no_receipt"


def test_unprovable_shapes_never_read_as_fresh():
    note = {"face": "gate_receipt", "recorded": False,
            "reason": "lane_head_sha failed", "error": "git rev-parse ut failed"}
    state, reason = dev_lane.gate_receipt_freshness(ANCHOR, SHA_A, note=note)
    assert state == "unprovable" and "git rev-parse ut failed" in reason
    assert dev_lane.gate_receipt_freshness(ANCHOR, "")[0] == "unprovable"
    assert dev_lane.gate_receipt_freshness(ANCHOR, None)[0] == "unprovable"
    assert dev_lane.gate_receipt_freshness(ANCHOR, 42)[0] == "unprovable"
    assert dev_lane.gate_receipt_freshness("garbage", SHA_A)[0] == "unprovable"
    assert dev_lane.gate_receipt_freshness({"deltas": []}, SHA_A)[0] == "unprovable"


# ---------------------------------------------------------------------------
# b/c/d. the copy and the cause vocabulary (pure)
# ---------------------------------------------------------------------------
def test_void_text_names_both_exits_and_never_a_committer():
    for state, cap in ((dev_lane.GATE_RECEIPT_STATE_STALE,
                        dev_lane.MAX_GATE_RECEIPT_RERUNS_STALE),
                       (dev_lane.GATE_RECEIPT_STATE_NO_RECEIPT,
                        dev_lane.MAX_GATE_RECEIPT_RERUNS_NO_RECEIPT)):
        txt = dev_lane.gate_receipt_void_text(state, "the lane HEAD moved", SHA_A,
                                             SHA_B, "arbitrate", cap, cap)
        assert "rework(to_stage=implement)" in txt
        assert "retry_qc" in txt
        assert SHA_A[:12] in txt and SHA_B[:12] in txt and "arbitrate" in txt
        assert "committed" not in txt
    unprovable = dev_lane.gate_receipt_void_text(
        dev_lane.GATE_RECEIPT_STATE_UNPROVABLE, "git rev-parse ut failed", SHA_A,
        "", "merge_check", 1, 0)
    assert "does not spend a suite round" in unprovable
    assert "retry_qc" in unprovable and "rework(to_stage=implement)" in unprovable


def test_surface_vocabulary():
    f = dev_lane.gate_receipt_surface
    assert f(closing=False, targeted=[]) == "full suite"
    assert f(closing=False, targeted=["a", "b"]) == "targeted: 2 scenario(s)"
    assert f(closing=False, targeted="broken") == "full suite"
    assert f(closing=True, fast_set=False) == "full suite (closing)"
    assert f(closing=True, fast_set=True) == "fast set (closing)"


def test_delta_causes_read_only_commit_evidence():
    g = dev_lane.gate_receipt_delta_causes
    # nothing named the move
    assert g(False, []) == []
    assert g(False, None) == []
    assert g(False, "broken") == []
    # this pass merged main
    assert g(True, []) == ["main_sync"]
    # the in-write-set self-heal committed (the row exists only on a real move)
    assert g(False, [{"id": "auto_settle", "green": True}]) == ["merge_check_acts"]
    # K1: the out-of-write-set repair committed
    assert g(False, [{"id": "foreign_file_repair",
                      "foreign_repair": {"repair_commit": "abc1234"}}]) == \
        ["foreign_repair:abc1234"]
    # malformed rows never mint a cause
    assert g(False, [None, 3, {"foreign_repair": "x"},
                     {"foreign_repair": {"repair_commit": "  "}}]) == []
    # dedupe keeps the first tag of each family, order stable
    assert g(True, [{"id": "foreign_file_repair",
                     "foreign_repair": {"repair_commit": "abc1234"}},
                    {"id": "foreign_file_repair",
                     "foreign_repair": {"repair_commit": "def5678"}}]) == \
        ["main_sync", "foreign_repair:abc1234"]


# ---------------------------------------------------------------------------
# e. the arm
# ---------------------------------------------------------------------------
def test_arm_is_patched_or_the_event_flag():
    wf = _shell()
    _wf(patched_ids=())
    assert dev_lane._gate_receipt_arm(dev_lane.workflow, wf) is False
    _wf(patched_ids=(dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID,))
    assert dev_lane._gate_receipt_arm(dev_lane.workflow, wf) is True
    _wf(patched_ids=())
    wf._gate_receipt_guard_enabled = True
    assert dev_lane._gate_receipt_arm(dev_lane.workflow, wf) is True
    # a shell without the attribute answers False, never AttributeError
    bare = object.__new__(dev_lane.DevLaneWorkflow)
    assert dev_lane._gate_receipt_arm(dev_lane.workflow, bare) is False


# ---------------------------------------------------------------------------
# f. the anchor recorder
# ---------------------------------------------------------------------------
def test_anchor_records_one_identity_and_clears_a_stale_note():
    state = _wf(patched_ids=())
    wf = _shell(meta={"gate_receipt_note": {"recorded": False, "error": "old"}})
    face = asyncio.run(wf._record_gate_receipt_anchor(_Receipt(), closing=False,
                                                     surface="full suite"))
    assert face == {"receipt_sha": SHA_A, "receipt_at": face["receipt_at"],
                    "surface": "full suite"}
    assert wf.meta["gate_receipt"]["receipt_sha"] == SHA_A
    assert wf.meta["gate_receipt"]["receipt_sha"] == face["receipt_sha"]
    assert wf.meta["gate_receipt"]["surface"] == "full suite"
    assert wf.meta["gate_receipt"]["green"] is False   # a red round is still anchored
    assert "gate_receipt_note" not in wf.meta
    # t261104-03: the drop is recorded, not silent (same marker as the guard)
    assert wf.meta["gate_receipt_note_superseded"][-1]["superseded"] == "old"
    assert wf.meta["gate_receipt_note_superseded"][-1]["by_probe_sha"] == SHA_A
    assert state["commands"] == ["lane_head_sha"]
    # the recorder never resets the void counter (that would make the cap unreachable)
    assert wf._receipt_void_rounds == 0


def test_anchor_resolver_failure_mints_nothing():
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: True,
        now=lambda: datetime.datetime(2026, 10, 31, tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        execute_activity=lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("worker gone")),
        sleep=lambda *_a, **_k: asyncio.sleep(0),
        upsert_memo=lambda *a, **k: None, info=lambda: None, wait_condition=None)
    wf = _shell()
    face = asyncio.run(wf._record_gate_receipt_anchor(_Receipt(), closing=False,
                                                     surface="full suite"))
    assert face["receipt_sha"] == ""
    assert "gate_receipt" not in wf.meta
    note = wf.meta["gate_receipt_note"]
    assert note["recorded"] is False and "worker gone" in note["error"]
    # fail-closed: the guard reads that note as unprovable
    assert dev_lane.gate_receipt_freshness(None, SHA_A, note=note)[0] == "unprovable"


# ---------------------------------------------------------------------------
# g. the guard
# ---------------------------------------------------------------------------
def _guard_wf(anchor, head, void_rounds=0, note=None, probe=None,
              conflict_rounds=0):
    state = _wf(patched_ids=())
    if isinstance(anchor, dict):
        _anchor = dict(anchor)
    else:
        _anchor = anchor
    meta = {"stage": "arbitrate", "gate_receipt": _anchor}
    if note is not None:
        meta["gate_receipt_note"] = note
    wf = _shell(meta=meta)
    wf._receipt_void_rounds = void_rounds
    wf._conflict_rounds = conflict_rounds
    calls = []

    async def _blocked(step, why):
        calls.append((step, why))

    wf._blocked = _blocked
    dev_lane.workflow.execute_activity = (lambda activity, args=None, **kw:
                                          _head_answer(head, probe))
    return wf, calls, state


def _head_answer(head, probe=None):
    async def _inner():
        if probe is not None:
            return probe
        return {"ok": True, "sha": head, "error": ""}
    return _inner()


def test_guard_fresh_proceeds_and_resets_the_counter():
    wf, calls, _ = _guard_wf(ANCHOR, SHA_A, void_rounds=2)
    assert asyncio.run(wf._gate_receipt_guard()) == ""
    assert wf._receipt_void_rounds == 0
    assert calls == []
    mf = wf.meta["gate_receipt"]["merge_face"]
    assert mf["receipt_sha"] == SHA_A and mf["land_sha"] == SHA_A
    assert mf["void"] is None
    line = wf.meta["handoffs"][-1]["summary"]
    # C4: the human face names the measured tree, the merge tree and the surface
    assert SHA_A[:12] in line and "surface: full suite" in line


def test_guard_stale_voids_and_routes_to_the_gate():
    wf, calls, _ = _guard_wf(ANCHOR, SHA_C, void_rounds=0)
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert calls == []                      # a normal void does not stop
    assert wf._receipt_void_rounds == 1
    void = wf.meta["gate_receipt_void"]
    assert void["state"] == "stale" and void["cap"] == 2
    assert void["receipt_sha"] == SHA_A and void["head_sha"] == SHA_C
    assert void["last_stage"] == "arbitrate"   # R4: named by measurement
    line = wf.meta["handoffs"][-1]["summary"]
    assert "VOID" in line and SHA_A[:12] in line and SHA_C[:12] in line
    assert "committed" not in line
    # the measured identity is never rewritten
    assert wf.meta["gate_receipt"]["receipt_sha"] == SHA_A


def test_guard_no_receipt_gets_one_round_then_stops():
    wf, calls, _ = _guard_wf(None, SHA_A, void_rounds=0)
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert wf.meta["gate_receipt_void"]["cap"] == 1
    assert calls == []
    # the second miss is over the cap: stop for a human, then one genuine re-run
    wf2, calls2, _ = _guard_wf(None, SHA_A, void_rounds=1)
    assert asyncio.run(wf2._gate_receipt_guard()) == "rerun_gate"
    assert [c[0] for c in calls2] == ["merge_check"]
    assert wf2._receipt_void_rounds == 0     # reset after the wake


def test_guard_stop_names_the_live_probe_error():
    """F2 (acceptance round 1): the stop must name the failing check."""
    probe = {"ok": False, "sha": "", "error": "rev-parse boom: fatal bad revision"}
    wf, calls, _ = _guard_wf(ANCHOR, SHA_A, probe=probe)
    assert asyncio.run(wf._gate_receipt_guard()) == "stopped"
    assert [c[0] for c in calls] == ["merge_check"]
    why = calls[0][1]
    assert "rev-parse boom" in why, why
    assert "live head probe" in why, why
    assert "rework(to_stage=implement)" in why and "retry_qc" in why


def test_guard_stop_names_both_counters_at_the_cap():
    """F1(b) (acceptance round 1): the cap stop names the conflict counter too."""
    wf, calls, _ = _guard_wf(ANCHOR, SHA_C, void_rounds=2, conflict_rounds=3)
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    why = calls[0][1]
    assert "cap 2" in why, why
    assert "Conflict-resolution rounds in this attempt: 3" in why, why
    assert "their own cap is separate" in why, why
    assert "rework(to_stage=implement)" in why and "retry_qc" in why


def test_guard_reads_a_malformed_anchor_as_unprovable():
    wf, calls, _ = _guard_wf("not-an-anchor", SHA_A)
    assert asyncio.run(wf._gate_receipt_guard()) == "stopped"
    assert [c[0] for c in calls] == ["merge_check"]
    assert "malformed gate-receipt face" in calls[0][1]


def test_guard_unprovable_stops_without_a_suite_round():
    """t261104-03: a FAILING probe still reads unprovable, and names both errors.

    The note stands here because the probe failed too: a note explains the attempt
    that wrote it, and this attempt did not prove the resolver works.
    """
    note = {"recorded": False, "reason": "lane_head_sha failed",
            "error": "git rev-parse ut failed"}
    probe = {"ok": False, "sha": "",
             "error": "rev-parse ut: fatal: bad revision"}
    wf, calls, _ = _guard_wf(ANCHOR, SHA_A, note=note, probe=probe)
    assert asyncio.run(wf._gate_receipt_guard()) == "stopped"
    assert [c[0] for c in calls] == ["merge_check"]
    assert "does not spend a suite round" in calls[0][1]
    assert "git rev-parse ut failed" in calls[0][1]          # the note's own error
    assert "rev-parse ut: fatal: bad revision" in calls[0][1]  # F2: the live one
    assert wf._receipt_void_rounds == 0
    # nothing was superseded: the note is still the readable explanation
    assert wf.meta["gate_receipt_note"] == note
    assert "gate_receipt_note_superseded" not in wf.meta
    # retry_qc re-arms the guard: once the probe answers, the next evaluation can
    # be fresh (and then it IS superseded - see the supersession tests below)
    wf2, calls2, _ = _guard_wf(ANCHOR, SHA_A)
    assert asyncio.run(wf2._gate_receipt_guard()) == ""


def test_guard_stale_twice_then_the_third_stale_state_stops():
    wf, calls, _ = _guard_wf(ANCHOR, SHA_C, void_rounds=2)
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert [c[0] for c in calls] == ["merge_check"]
    assert "cap 2" in calls[0][1]
    assert "rework(to_stage=implement)" in calls[0][1] and "retry_qc" in calls[0][1]
    assert wf._receipt_void_rounds == 0
    # a fresh evaluation at the cap still proceeds (tree first, cap second)
    wf2, calls2, _ = _guard_wf(ANCHOR, SHA_A, void_rounds=2)
    assert asyncio.run(wf2._gate_receipt_guard()) == ""
    assert calls2 == [] and wf2._receipt_void_rounds == 0


# ---------------------------------------------------------------------------
# g2. t261104-03: a SUCCESSFUL probe supersedes a stale miss note
#
# Measured on project-vision t261103-08: after the resolver fix (t261104-01) the
# live probe answered `lane HEAD sha256:1c39a`, and the blocked_reason still read
# the OLD resolver miss - both facts at once. The note is judged FIRST, the
# `unprovable` state spends no suite round, and the note's only clearing path (a
# successful anchor recording) is unreachable from there. So the stop was
# terminal and the named `retry_qc` remedy provably could not clear it.
# ---------------------------------------------------------------------------
def test_supersession_rule_truth_table():
    """Pure: only a successful probe drops a `recorded=False` note; never a pass."""
    f = dev_lane.gate_receipt_note_supersession
    note = {"face": "gate_receipt", "recorded": False,
            "reason": "lane_head_sha failed", "error": "resolver miss", "at": 7}
    rec = f(note, True, SHA_A, at=9)
    assert rec["face"] == "gate_receipt"
    assert rec["superseded"] == "resolver miss"      # the earlier words survive
    assert rec["reason"] == "lane_head_sha failed"
    assert rec["note_at"] == 7 and rec["at"] == 9
    assert rec["by_probe_sha"] == SHA_A
    # a FAILING probe keeps the note: it is this attempt's explanation
    assert f(note, False, "", at=9) is None
    assert f(note, False, SHA_A, at=9) is None
    # an empty head is not a success, and neither is a malformed one
    assert f(note, True, "", at=9) is None
    assert f(note, True, "   ", at=9) is None
    assert f(note, True, 42, at=9) is None
    # nothing to supersede: absent note, a recorded note, malformed shapes
    assert f(None, True, SHA_A) is None
    assert f({"recorded": True, "error": "x"}, True, SHA_A) is None
    assert f("garbage", True, SHA_A) is None
    assert f(["recorded"], True, SHA_A) is None
    # a note without a named error still supersedes and stays readable
    assert f({"recorded": False}, True, SHA_A)["superseded"] == "unknown"


def test_guard_supersedes_a_stale_note_when_the_probe_succeeds():
    """(a) note + successful probe -> note gone, NO_RECEIPT, one round allowed."""
    note = {"face": "gate_receipt", "recorded": False,
            "reason": "lane_head_sha failed",
            "error": "lane branch 'lane/t261103-08' is not resolvable", "at": 5}
    wf, calls, _ = _guard_wf(None, SHA_A, note=note)     # no anchor; probe answers
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert calls == []                                   # no stop: the lane moves on
    assert "gate_receipt_note" not in wf.meta            # the stale note is gone
    void = wf.meta["gate_receipt_void"]
    assert void["state"] == "no_receipt" and void["cap"] == 1
    assert void["head_sha"] == SHA_A
    assert wf._receipt_void_rounds == 1                  # the ONE allowed round
    # the supersession is recorded (never a silent disappearance), and the earlier
    # error is still readable
    hist = wf.meta["gate_receipt_note_superseded"]
    assert [h["superseded"] for h in hist] == \
        ["lane branch 'lane/t261103-08' is not resolvable"]
    assert hist[-1]["by_probe_sha"] == SHA_A
    assert hist[-1]["note_at"] == 5
    text = "\n".join(h["summary"] for h in wf.meta["handoffs"])
    assert "superseded" in text, text
    assert "lane branch 'lane/t261103-08' is not resolvable" in text, text
    log = "\n".join(e["note"] for e in wf.meta["log"])
    assert "gate-receipt miss note superseded" in log
    assert "lane branch 'lane/t261103-08' is not resolvable" in log


def test_guard_superseded_note_can_also_read_fresh():
    """The measured case: a note plus an anchor whose sha the probe confirms."""
    note = {"recorded": False, "reason": "lane_head_sha failed",
            "error": "old resolver miss"}
    wf, calls, _ = _guard_wf(ANCHOR, SHA_A, note=note)
    assert asyncio.run(wf._gate_receipt_guard()) == ""
    assert calls == [] and wf._receipt_void_rounds == 0
    assert "gate_receipt_note" not in wf.meta
    assert wf.meta["gate_receipt"]["merge_face"]["land_sha"] == SHA_A
    line = wf.meta["handoffs"][-1]["summary"]
    assert SHA_A[:12] in line and "superseded" in line
    assert "old resolver miss" in line


def test_guard_healthy_paths_are_unchanged():
    """(c) + (d): fresh and stale judge exactly as before, no supersession key."""
    wf, calls, _ = _guard_wf(ANCHOR, SHA_A)              # no note, fresh
    assert asyncio.run(wf._gate_receipt_guard()) == ""
    assert wf.meta["gate_receipt"].get("merge_face", {}).get("void") is None
    assert "gate_receipt_note_superseded" not in wf.meta
    wf2, calls2, _ = _guard_wf(ANCHOR, SHA_C)            # no note, moved head
    assert asyncio.run(wf2._gate_receipt_guard()) == "rerun_gate"
    assert wf2.meta["gate_receipt_void"]["state"] == "stale"
    assert wf2.meta["gate_receipt_void"]["cap"] == 2
    assert "gate_receipt_note_superseded" not in wf2.meta


def test_guard_superseded_note_never_launders_a_malformed_anchor():
    """Clearing the note is not a pass: an anchor we cannot read still stops."""
    note = {"recorded": False, "reason": "lane_head_sha failed",
            "error": "old resolver miss"}
    wf, calls, _ = _guard_wf("not-an-anchor", SHA_A, note=note)
    assert asyncio.run(wf._gate_receipt_guard()) == "stopped"
    assert [c[0] for c in calls] == ["merge_check"]
    why = calls[0][1]
    assert "malformed gate-receipt face" in why, why
    assert "old resolver miss" in why          # the history is still named
    assert wf._receipt_void_rounds == 0        # unprovable spends no round


def test_guard_superseded_note_still_spends_the_one_no_receipt_round():
    """(e) the cap holds in the superseded path: one round, then a stop."""
    wf, calls, _ = _guard_wf(None, SHA_A, note={
        "recorded": False, "reason": "lane_head_sha failed",
        "error": "miss one", "at": 1})
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"   # round 1 of 1
    assert calls == [] and wf._receipt_void_rounds == 1
    # the sanctioned round ran and missed the anchor again: a NEW note is written
    wf.meta["gate_receipt_note"] = {"recorded": False,
                                    "reason": "lane_head_sha failed",
                                    "error": "miss two", "at": 2}
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert [c[0] for c in calls] == ["merge_check"]      # over the cap: stop
    why = calls[0][1]
    assert "cap 1" in why, why
    assert "miss two" in why              # the newest failure is named
    assert "miss one" not in why          # superseded, not re-read (it is history)
    assert wf._receipt_void_rounds == 0                   # reset after the wake
    hist = wf.meta["gate_receipt_note_superseded"]
    assert [h["superseded"] for h in hist] == ["miss one", "miss two"]


# ---------------------------------------------------------------------------
# h. the merge-line delta
# ---------------------------------------------------------------------------
def test_delta_written_only_when_the_head_moved():
    state = _wf(patched_ids=())
    wf = _shell(meta={"gate_receipt": dict(ANCHOR)})
    asyncio.run(wf._record_merge_line_delta([], main_sync_this_pass=False))
    assert wf.meta["gate_receipt"]["deltas"] == []      # to == from: no delta
    state["head"] = SHA_B
    asyncio.run(wf._record_merge_line_delta(
        [{"id": "auto_settle", "green": True}], main_sync_this_pass=True))
    deltas = wf.meta["gate_receipt"]["deltas"]
    assert len(deltas) == 1
    assert deltas[0]["from"] == SHA_A and deltas[0]["to"] == SHA_B
    assert deltas[0]["cause"] == "main_sync+merge_check_acts"
    # K2: the face names the tree the merge will land
    assert wf.meta["gate_receipt"]["merge_face"]["land_sha"] == SHA_B
    assert wf.meta["gate_receipt"]["receipt_sha"] == SHA_A


def test_delta_records_the_repair_commit_as_its_cause():
    state = _wf(patched_ids=())
    wf = _shell(meta={"gate_receipt": dict(ANCHOR)})
    state["head"] = SHA_B
    asyncio.run(wf._record_merge_line_delta(
        [{"id": "foreign_file_repair",
          "foreign_repair": {"repair_commit": "abc1234"}}],
        main_sync_this_pass=False))
    assert wf.meta["gate_receipt"]["deltas"][0]["cause"] == "foreign_repair:abc1234"


def test_delta_skips_when_the_resolver_fails():
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: datetime.datetime(2026, 10, 31, tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        execute_activity=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        sleep=lambda *_a, **_k: asyncio.sleep(0),
        upsert_memo=lambda *a, **k: None, info=lambda: None, wait_condition=None)
    wf = _shell(meta={"gate_receipt": dict(ANCHOR)})
    asyncio.run(wf._record_merge_line_delta([], main_sync_this_pass=True))
    assert wf.meta["gate_receipt"]["deltas"] == []


# ---------------------------------------------------------------------------
# i. the closing run replaces the face receipt
# ---------------------------------------------------------------------------
def test_closing_receipt_replaces_the_face_in_place():
    _wf(patched_ids=(dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID,))
    wf = _shell()
    wf.results["run_integration_tests"] = {
        "status": "failed", "summary": "legacy receipt face (1 ran / 1 failed)",
        "report": "", "deliverables": [], "files_changed": [],
        "evidence": "old", "gen": 0}
    wf._gens["run_integration_tests"] = 3
    closing = IntegrationRunResult(
        ran=40, passed=40, failed=0, env_fail=0,
        details=[{"name": "sc_y", "cmd": "", "exit": 0, "output_tail": ""}])
    asyncio.run(wf._accept_closing_receipt(closing))
    face = wf.results["run_integration_tests"]
    assert face["status"] == "ok" and face["closing"] is True
    assert "40 ran / 40 passed" in face["summary"]
    assert "surface: full suite (closing)" in face["summary"]
    assert face["receipt_sha"] == SHA_A
    assert wf.meta["gate_receipt"]["closing"] is True
    assert wf.meta["gate_receipt"]["surface"] == "full suite (closing)"


def test_closing_receipt_surface_names_the_fast_set_for_a_buffer_ticket():
    _wf(patched_ids=(dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID,))
    wf = _shell(meta={"lane_version": "develop-buffer-v1"})  # develop_line.LANE_VERSION_DEVELOP_BUFFER
    wf.results["run_integration_tests"] = {"status": "ok", "summary": "x",
                                           "report": "", "deliverables": [],
                                           "files_changed": [], "evidence": "",
                                           "gen": 0}
    asyncio.run(wf._accept_closing_receipt(IntegrationRunResult(
        ran=3, passed=3, failed=0, env_fail=0, details=[])))
    assert wf.results["run_integration_tests"]["surface"] == "fast set (closing)"
    assert wf.meta["gate_receipt"]["surface"] == "fast set (closing)"


# ---------------------------------------------------------------------------
# i2. the armed in-flight lane (S1): the flag reaches the WRITES, not only the read
# ---------------------------------------------------------------------------
def test_armed_lane_mints_its_anchor_with_the_patch_gate_closed():
    """patched() is False forever on a pre-fix lane; the flag must still write."""
    state = _wf(patched_ids=())            # the SDK's memoized False
    wf = _shell()
    wf._gate_receipt_guard_enabled = True  # the operator arm event
    assert dev_lane._gate_receipt_arm(dev_lane.workflow, wf) is True

    # entry 1: no anchor -> one gate round is asked for (no waste beyond that)
    assert asyncio.run(wf._gate_receipt_guard()) == "rerun_gate"
    assert wf.meta["gate_receipt_void"]["state"] == "no_receipt"
    assert state["commands"] == ["lane_head_sha"]

    # the armed recorder really mints the anchor (this is the command the arm
    # must reach: without it the lane can never leave no_receipt)
    face = asyncio.run(wf._record_gate_receipt_anchor(_Receipt(), closing=False,
                                                     surface="full suite"))
    assert face["receipt_sha"] == SHA_A
    assert wf.meta["gate_receipt"]["receipt_sha"] == SHA_A

    # entry 2: fresh, and the void counter resets
    assert asyncio.run(wf._gate_receipt_guard()) == ""
    assert "gate_receipt_void" not in wf.meta
    assert wf._receipt_void_rounds == 0


def test_armed_lane_gets_one_more_round_after_retry_qc():
    """The pre-anchor population is exactly the one _counter_reset_active skips."""
    _wf(patched_ids=())                    # COUNTER_RESET_PATCH_ID is False too
    wf = _shell(meta={"stage": "merge_check"})
    wf._gate_receipt_guard_enabled = True
    wf._receipt_void_rounds = dev_lane.MAX_GATE_RECEIPT_RERUNS_STALE
    wf._conflict_rounds = 3
    wf._prev_conflict_files = ["a"]
    handler = dev_lane.DevLaneWorkflow.retry_qc.__get__(wf)
    handler("host")
    # the gate-receipt window opens; the conflict counters stay gated as before
    assert wf._receipt_void_rounds == 0
    assert wf._conflict_rounds == 3
    wf._receipt_void_rounds = 1
    rework = dev_lane.DevLaneWorkflow.rework.__get__(wf)
    wf._cross_project_gate = lambda *a, **k: True
    rework(SimpleNamespace(note="ut", target_stage="implement", who="host",
                           caller_project="", cross_project_note=""))
    assert wf._receipt_void_rounds == 0


def test_arm_handler_is_idempotent_and_tolerates_a_garbage_payload():
    _wf(patched_ids=())
    wf = _shell()
    handler = dev_lane.DevLaneWorkflow.enable_gate_receipt_guard.__get__(wf)
    handler(None)                          # garbage payload never raises
    handler("host")
    handler("host")                        # re-delivery changes nothing
    assert wf._gate_receipt_guard_enabled is True
    arm = wf.meta["gate_receipt_guard_arm"]
    assert arm["enabled"] is True and arm["who"] == "host"
    assert isinstance(arm["at"], int)


# ---------------------------------------------------------------------------
# j. the real main loop
# ---------------------------------------------------------------------------
class _MergeGateReached(BaseException):
    """Sentinel: the loop reached the merge human gate."""


class _GateRoundReached(BaseException):
    """Sentinel: the loop went back to the gate phase."""


class _Journey:
    """One main-loop drive with a scripted activity seam."""

    def __init__(self, head=SHA_A, sync_mode="up_to_date", stop_at_gate=True,
                 start_stage="merge_check", lift=False, conflict_rounds=0):
        self.head = head
        self.sync_mode = sync_mode
        self.stop_at_gate = stop_at_gate
        self.start_stage = start_stage
        self.lift = lift
        self.conflict_rounds = conflict_rounds
        self.commands = []
        self.blocks = []
        self.spawns = []

    def note_probe(self, wf):
        """Model the entry AFTER a conflict-resolution round.

        `run()` initialises the conflict counter in its loop setup, so the value
        has to arrive after that. The first head probe is the first call of the
        merge_check entry, and the guard reads the counter after it.
        """
        if self.conflict_rounds:
            wf._conflict_rounds = self.conflict_rounds
            self.conflict_rounds = 0

    def prepare(self, prep):
        """The main-sync activity: merge main on request (moves the fake head)."""
        if self.sync_mode == "merged":
            self.head = SHA_B
            return {"ok": True, "conflict_files": [], "merge_output": "",
                    "already_clean": True, "error": "", "target_sha": "main0123",
                    "lane_head": self.head[:12], "up_to_date": False,
                    "branch_tip": ""}
        return {"ok": True, "conflict_files": [], "merge_output": "",
                "already_clean": False, "error": "", "target_sha": "main0123",
                "lane_head": self.head[:12], "up_to_date": True,
                "branch_tip": ""}


def _journey_wf(journey):
    _wf(patched_ids=(dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID,
                     dev_lane.MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID,
                     dev_lane.REVIEW_GATE_PATCH_ID))

    async def _execute_activity(activity, args=None, **kw):
        name = (getattr(activity, "name", None) or getattr(activity, "__name__", "")
                or str(activity))
        journey.commands.append(name)
        if name == "lane_head_sha":
            journey.note_probe(wf)
            return {"ok": True, "sha": journey.head, "error": ""}
        if name == "prepare_conflict_resolution":
            return journey.prepare(None)
        if name in ("concurrency_acquire", "concurrency_renew", "concurrency_release"):
            return {"granted": True, "holding": True, "reason": "", "released": True,
                    "position": 0, "limit": 1, "waiting": 0, "promoted": False,
                    "dropped_stale": []}
        if name == "verify_review_gate":
            if journey.stop_at_gate:
                raise _GateRoundReached()      # the loop chose to re-run the gate
            return {"git_error": "", "lane_commits": 1, "shots_path_error": "",
                    "png_count": 0}
        if name == "run_integration_tests":
            return IntegrationRunResult(
                ran=1, passed=1, failed=0, env_fail=0,
                details=[{"name": "ut", "cmd": "", "exit": 0, "output_tail": ""}])
        if name in ("arbitrate", "acceptance_walkthrough"):
            journey.spawns.append(name)
            summary = ("verdict=pass ut" if name == "arbitrate"
                       else "acceptance ok")
            return dev_lane.StageResult(
                status="ok", summary=summary, report="[ut]", deliverables=[],
                files_changed=[], files_changed_shape="ok", evidence="ut",
                gate_refusal=None, env_fail=False, env_reason="",
                handover_runs=[], handover_dropped=[])
        if name == "merge_check":
            return {"green": True, "checks": [], "error": "", "conflict": False,
                    "conflict_files": [], "merge_tree_excerpt": "",
                    "write_set_history": []}
        if name == "prepare_human_gate":
            raise _MergeGateReached()
        return {"ok": True, "note": "ut", "error": "", "phase": "", "stop": False,
                "files": [], "names": [], "mode": "none", "reason": "",
                "surfaces": [], "members": [], "own_members": [], "budget_min": 0,
                "own_error": "", "blocked_reason": "", "warning": "",
                "lane_commits": 1, "git_error": "", "shots_path_error": "",
                "png_count": 0, "prefixes": [], "mode_absent": "absent",
                "dir": "absent", "dirs": [], "detail": ""}

    dev_lane.workflow.execute_activity = _execute_activity

    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.engine_version = 2
    wf._gens = {}
    wf.results = {}
    wf.signatures = {}
    wf.refused = []
    wf.timeline = []
    wf.gate_runs = []
    wf.human_context = {}
    wf._detail_face_on = False
    wf._narrowed_anchor_enabled = False
    wf._gate_receipt_guard_enabled = False
    wf._receipt_void_rounds = 0
    wf._terminal_slot_pending = False
    wf._conflict_rounds = 0
    wf._prev_conflict_files = []
    wf._acc_verdict_seq = 0
    wf._arb_over_limit_seq = 0
    wf._annex_requests = []
    wf._ledger_marks = []
    wf._rework = None
    wf._retry_token = 0

    async def _noop():
        return None

    async def _blocked(step, why):
        journey.blocks.append((step, why))
        if len(journey.blocks) > 5:
            raise RuntimeError("journey spun into %d blocks: %r"
                               % (len(journey.blocks), journey.blocks))

    wf._pause_gate = _noop
    wf._concurrency_release_if_paused = _noop
    wf._drain_annex_requests = _noop
    wf._ledger_flush = _noop
    wf._ledger_enqueue = lambda entry: None
    wf._blocked = _blocked

    async def _prep_ws():
        wf.meta["stage"] = journey.start_stage
        wf.meta["gate_receipt"] = dict(ANCHOR, deltas=[])
        if journey.conflict_rounds:
            wf._conflict_rounds = journey.conflict_rounds
        if journey.lift:
            # an armed cap lift whose citation is the current stop and whose
            # stopped report is still the latest walkthrough round
            _now = int(dev_lane.workflow.now().timestamp())
            _tok = "ut-report-token"
            wf._gens[str(dev_lane.ACCEPTANCE_REPORT_STAGE)] = _LIFT_REPORT_GEN + 1
            wf.meta["acc_cap_stop"] = {
                "rounds": 4, "report_gen": _LIFT_REPORT_GEN,
                "report_token": _tok, "finding_sig": "ut-sig", "at": _now}
            wf.meta["acceptance_cap_lifts"] = [
                {"who": "host", "at": _now - 5, "reason": "ut",
                 "report_token": _tok}]

    wf._prepare_workspace_step = _prep_ws
    return wf


_LIFT_REPORT_GEN = 4


def _run_journey(journey):
    wf = _journey_wf(journey)
    inp = SimpleNamespace(
        ticket_id=TICKET, template_id="dev-lane", project="ut", title="ut",
        lane="worktree", workspace="/tmp/ut-t261031-20", worktree="/tmp/ut-lane",
        branch="ut", base_ref="main", proposal_id="", book_path="", epic="",
        write_set=["server/engine/"], deliverables=[], user_request="ut", spec="",
        body="", created=0)
    raised = None
    try:
        asyncio.run(dev_lane.DevLaneWorkflow.run(wf, inp))
    except (_MergeGateReached, _GateRoundReached) as exc:   # pragma: no cover
        raised = type(exc).__name__
    return wf, raised


def test_journey_fresh_receipt_reaches_the_merge_gate():
    journey = _Journey(head=SHA_A)
    wf, raised = _run_journey(journey)
    assert raised == "_MergeGateReached", (raised, journey.blocks)
    assert journey.blocks == []
    assert wf.meta["gate_receipt"]["deltas"] == []
    assert wf.meta["gate_receipt"]["merge_face"]["land_sha"] == SHA_A


def test_journey_main_sync_lands_as_a_named_delta_and_does_not_void():
    journey = _Journey(head=SHA_A, sync_mode="merged")
    wf, raised = _run_journey(journey)
    assert raised == "_MergeGateReached", (raised, journey.blocks)
    assert journey.blocks == []
    deltas = wf.meta["gate_receipt"]["deltas"]
    assert [(d["from"], d["to"], d["cause"]) for d in deltas] == \
        [(SHA_A, SHA_B, "main_sync")]
    assert wf.meta["gate_receipt"]["merge_face"]["land_sha"] == SHA_B


def test_journey_stale_receipt_routes_back_to_the_gate():
    journey = _Journey(head=SHA_C)
    wf, raised = _run_journey(journey)
    assert raised == "_GateRoundReached", (raised, journey.blocks)
    assert wf.meta["stage"] == "run_integration_tests"
    assert wf.meta["gate_receipt_void"]["state"] == "stale"
    assert "verify_review_gate" in journey.commands


def test_journey_cap_lift_is_spent_and_a_fresh_walkthrough_runs():
    """F1(a) from the acceptance round: the real order, pinned end to end.

    A human cap lift fires at the loop top BEFORE the dispatch, the guard then
    voids the stale receipt, the gate re-runs, and the fork spawns a fresh
    walkthrough. The human ruling is recorded as used, and the merge gate is
    reached only on the refreshed receipt.
    """
    journey = _Journey(head=SHA_B, start_stage="acceptance", lift=True,
                       stop_at_gate=False)
    wf, raised = _run_journey(journey)
    assert raised == "_MergeGateReached", (raised, journey.blocks, journey.commands)
    # the lift was consumed, and the stop record it cited is gone
    lift = wf.meta["acceptance_cap_lifts"][0]
    assert lift.get("used_at"), lift
    assert "acc_cap_stop" not in wf.meta
    # the gate re-ran, then a fresh walkthrough ran (order matters)
    assert "verify_review_gate" in journey.commands, journey.commands
    assert "acceptance_walkthrough" in journey.spawns, journey.commands
    assert journey.commands.index("verify_review_gate") < \
        journey.commands.index("acceptance_walkthrough")
    # the carrier is now measured on the tree the gate just judged
    assert wf.meta["gate_receipt"]["receipt_sha"] == SHA_B
    assert wf.meta["gate_receipt"]["merge_face"]["land_sha"] == SHA_B
    # the void line names the measured tree, the current head and the last stage.
    # (The meta key is cleared by the later fresh verification, so the readable
    # face is where this fact lives after the round.)
    text = "\n".join(h["summary"] for h in wf.meta["handoffs"])
    assert "Gate receipt VOID" in text, text
    assert "last stage entered: acceptance" in text, text
    assert SHA_A[:12] in text and SHA_B[:12] in text
    assert "committed" not in text.lower()


def test_journey_conflict_moved_tree_is_stale_and_names_the_conflict_counter():
    """F1(b) from the acceptance round: a conflict round's settle moves the head.

    The next entry is `stale`, one gate round runs, and the void text names the
    conflict-round counter next to the receipt counter.
    """
    journey = _Journey(head=SHA_C, conflict_rounds=2)
    wf, raised = _run_journey(journey)
    assert raised == "_GateRoundReached", (raised, journey.blocks)
    assert wf.meta["gate_receipt_void"]["state"] == "stale"
    assert "verify_review_gate" in journey.commands
    text = "\n".join(h["summary"] for h in wf.meta["handoffs"])
    assert "Conflict-resolution rounds in this attempt: 2" in text, text
    assert "rework(to_stage=implement)" in text and "retry_qc" in text


# ---------------------------------------------------------------------------
def _run_src():
    return inspect.getsource(dev_lane.DevLaneWorkflow.run)


def test_guard_runs_before_enter_and_before_the_main_sync():
    src = _run_src()
    guard = src.index("_gate_receipt_guard()")
    enter = src.index('self._enter("merge_check")')
    sync = src.index('_main_sync_before_gate(step_id="merge_check")')
    assert guard < enter
    assert guard < sync


def test_every_new_command_site_sits_behind_the_arm():
    src = Path(dev_lane.__file__).read_text(encoding="utf-8")
    assert src.count("_gate_receipt_arm(workflow, self)") >= 4
    # the closing-run helper refuses to issue a command without the arm
    helper = inspect.getsource(dev_lane.DevLaneWorkflow._accept_closing_receipt)
    assert "_gate_receipt_arm" in helper
    # the receipt site and the delta site are guarded inside run()
    run_src = _run_src()
    assert run_src.index("_gate_receipt_arm(workflow, self)") < \
        run_src.index("_record_gate_receipt_anchor(")
    assert "_gate_receipt_arm(workflow, self)" in run_src.split(
        "_record_merge_line_delta(")[0]


def test_handler_resets_sit_outside_the_e9daa05_gate():
    src = Path(dev_lane.__file__).read_text(encoding="utf-8")
    for name in ("def rework(self, req", "def retry_qc(self, who"):
        start = src.index(name)
        body = src[start:start + 2200]
        gate = body.index("if _counter_reset_active(workflow):")
        reset = body.index("self._receipt_void_rounds = 0")
        assert reset > gate
        # the reset line is at method-body indentation, not inside the gate block
        line = body[:reset].rsplit("\n", 1)[-1]
        assert line.strip() == ""            # the reset line starts its own line
        assert body.splitlines()[body[:reset].count("\n")].startswith("        ")
        assert not body.splitlines()[body[:reset].count("\n")].startswith("            ")


def test_one_ast_visible_receipt_assignment_survives():
    tree = ast.parse(Path(dev_lane.__file__).read_text(encoding="utf-8"))
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if any(isinstance(t, ast.Subscript) and "run_integration_tests" in
               ast.unparse(t) for t in node.targets):
            found += 1
            keys = [k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)]
            assert "status" in keys and "receipt_sha" in keys
    assert found == 1, "the receipt face must keep ONE AST-visible assignment"


def test_selfheal_row_marks_a_commit_and_keeps_the_rehearsal_last():
    act = Path(dev_lane.__file__).with_name("agent_activities.py").read_text(
        encoding="utf-8")
    assert '"id": "auto_settle"' in act
    append = act.index("checks.append(auto_settle_row)")
    rehearsal = act.index('_git(["merge-tree", "--write-tree", "main"')
    assert append < rehearsal
    # the row is built only when the head moved
    assert "_head_before != _head_after" in act


def test_repair_row_already_carries_its_commit():
    act = Path(dev_lane.__file__).with_name("agent_activities.py").read_text(
        encoding="utf-8")
    assert 'record["repair_commit"] = str(rep.get("committed") or "")' in act
