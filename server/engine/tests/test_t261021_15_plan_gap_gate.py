"""t261021-15 unit tests: the plan-side write-set gap gate.

Incident: tickets born with a write set of only the auto-injected
``integration/`` got a create_plan receipt with ``files_changed=[]``; the union
admitted nothing; implement then reverted every out-of-set edit. The gate
refuses to advance to implement when THREE facts hold together — an empty
receipt alone must keep the 260930 non-blocking reminder (conjunction, not
single fact).

Coverage (no Temporal server / no model / no network):
  A. shared pure faces: integration-only detection (mixed / empty / non-list /
     non-string entry / nested integration path), prose detector (hit, miss,
     non-string), stop reason (code + three facts + lawful outs, prose clause),
     classify_stop_tier on the reason = judgement.
  B. gate matrix through _refresh_write_set_after_plan (stub workflow shell,
     t261009-58 style): each fact missing in turn does NOT refuse; the full
     conjunction refuses with the named code and the meta key; prior widening
     (initial_write_set real scope) does not refuse; real-scope set + empty
     receipt keeps the reminder path; prose signal lights the named log line.
  C. replay safety: unpatched gate = legacy path, zero new meta keys.
  D. malformed inputs: receipt files_changed as string / dict /
     list-of-non-strings → no gate fire, no crash (shape faces own the report).

Malformed-input discipline: fixed-shape stubs, never a real external source.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402

import shared  # noqa: E402
from shared import (  # noqa: E402
    STOP_TIER_JUDGEMENT,
    WRITE_SET_PLAN_GAP_STOP_CODE,
    classify_stop_tier,
    plan_prose_needs_wider_write_set,
    plan_write_set_gap_stop_reason,
    write_set_is_integration_only,
)


# ---------- A. shared pure faces ----------

def test_integration_only_detection_matrix():
    assert write_set_is_integration_only(["integration/"])
    assert write_set_is_integration_only(["integration/", "integration/x.py"])
    # real scope: any entry outside integration/
    assert not write_set_is_integration_only(["integration/", "server/a.py"])
    assert not write_set_is_integration_only(["server/engine/dev_lane.py"])
    # shape-strict: fail-open, never crash
    assert not write_set_is_integration_only([])
    assert not write_set_is_integration_only(None)
    assert not write_set_is_integration_only("integration/")
    assert not write_set_is_integration_only([1, 2])
    assert not write_set_is_integration_only([None])


def test_prose_detector_hit_and_miss():
    # measured t261021-11 wording
    assert plan_prose_needs_wider_write_set(
        "engine conversion flagged for widened write set")
    assert plan_prose_needs_wider_write_set(
        "no changes this round", "please authorize a wider write set for tools/")
    # misses: write set mentioned without a widening word / widening word alone
    assert not plan_prose_needs_wider_write_set("the write set follows the plan")
    assert not plan_prose_needs_wider_write_set("wider testing needed")
    # non-string / empty inputs never raise
    assert not plan_prose_needs_wider_write_set(None, 42, "", [], {})


def test_stop_reason_names_three_facts_and_lawful_out():
    reason = plan_write_set_gap_stop_reason(["integration/"], "empty", False)
    assert reason.startswith(WRITE_SET_PLAN_GAP_STOP_CODE + ":")
    assert "integration-only" in reason and "integration/" in reason
    assert "empty array" in reason
    assert "no_file_changes is not declared" in reason
    assert "rework back to create_plan" in reason
    assert "files_changed" in reason and "write set follows the plan" in reason
    assert "authorize specific paths" in reason
    assert "prose" not in reason
    absent = plan_write_set_gap_stop_reason(["integration/"], "absent", True)
    assert "absent" in absent
    assert "prose itself names a wider write set" in absent


def test_stop_reason_classifies_judgement():
    # judgement tier: lift stays human-only, matching the lawful outs
    tier, kind = classify_stop_tier(
        plan_write_set_gap_stop_reason(["integration/"], "empty", True))
    assert tier == STOP_TIER_JUDGEMENT and kind == ""


# ---------- B/C. gate matrix through _refresh_write_set_after_plan ----------

def _mk_lane(patched_ids, meta=None):
    import datetime
    import dev_lane
    orig = dev_lane.workflow
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid in patched_ids,
        now=lambda: datetime.datetime(2026, 10, 21, 12, 0, 0))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict({"write_set": ["integration/"], "ticket_id": "t-ut"}, **(meta or {}))
    wf.results = {}
    wf.timeline = []
    yield wf, dev_lane, orig
    dev_lane.workflow = orig


GATE_IDS = {"dev-lane-refresh-write-set", "dev-lane-write-set-plan-gap-v1",
            "dev-lane-write-set-fault"}   # production: fault patch rides along


def test_gate_fires_on_full_conjunction():
    for wf, dev_lane, _ in _mk_lane(GATE_IDS):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        reason = dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert isinstance(reason, str) and reason.startswith(
            WRITE_SET_PLAN_GAP_STOP_CODE + ":")
        assert wf.meta["write_set_plan_gap"]["stage"] == "create_plan"
        assert wf.meta["write_set"] == ["integration/"]     # untouched
        assert "write_set_refresh_fault" not in wf.meta     # never fell to the reminder
        assert any(WRITE_SET_PLAN_GAP_STOP_CODE in e["note"]
                   for e in wf.meta.get("log", []))


def test_gate_fires_on_absent_receipt():
    for wf, dev_lane, _ in _mk_lane(GATE_IDS):
        wf.results["create_plan"] = {"files_changed_shape": "absent"}
        reason = dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert isinstance(reason, str) and "absent" in reason
        assert "write_set_plan_gap" in wf.meta


def test_fact1_missing_real_scope_does_not_refuse():
    # empty receipt alone (real-scope set) → today's non-blocking reminder
    for wf, dev_lane, _ in _mk_lane(GATE_IDS, {"write_set": ["server/a.py"]}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        assert "write_set_plan_gap" not in wf.meta
        assert "write_set_refresh_fault" in wf.meta          # KI-049 reminder, unchanged
        assert wf.meta["write_set"] == ["server/a.py"]


def test_fact2_missing_nonempty_receipt_does_not_refuse():
    # integration-only set but the receipt lists files → union proceeds, no stop
    for wf, dev_lane, _ in _mk_lane(GATE_IDS | {"dev-lane-effective-write-set"}):
        wf.results["create_plan"] = {"files_changed": ["server/b.py"],
                                     "files_changed_shape": "ok"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        assert "write_set_plan_gap" not in wf.meta
        assert wf.meta["write_set"] == ["integration/", "server/b.py"]


def test_fact3_missing_no_file_changes_does_not_refuse():
    for wf, dev_lane, _ in _mk_lane(GATE_IDS, {"no_file_changes": True}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        assert "write_set_plan_gap" not in wf.meta


def test_prior_widening_real_scope_does_not_refuse():
    # review condition 2: the gate reads the INITIAL set; a prior plan's union
    # is a real scope, so a later empty receipt must not refuse
    for wf, dev_lane, _ in _mk_lane(GATE_IDS, {
            "write_set": ["integration/", "server/plan.py"],
            "initial_write_set": ["integration/"]}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        assert "write_set_plan_gap" not in wf.meta


def test_prose_signal_lights_named_line_on_reminder_path():
    for wf, dev_lane, _ in _mk_lane(GATE_IDS, {"write_set": ["server/a.py"]}):
        wf.results["create_plan"] = {
            "files_changed": [], "files_changed_shape": "ok",
            "summary": "conversion flagged for widened write set"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        notes = [e["note"] for e in wf.meta.get("log", [])]
        assert any("wider write set in prose but files_changed is empty" in n
                   for n in notes)


def test_prose_signal_named_inside_stop_reason():
    for wf, dev_lane, _ in _mk_lane(GATE_IDS):
        wf.results["create_plan"] = {
            "files_changed": [], "files_changed_shape": "ok",
            "summary": "engine conversion flagged for widened write set"}
        reason = dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "prose itself names a wider write set" in reason


def test_unpatched_gate_keeps_legacy_path():
    # an existing ticket replaying: the new gate never sees the decision —
    # legacy behavior byte for byte, zero new meta keys
    for wf, dev_lane, _ in _mk_lane({"dev-lane-refresh-write-set",
                                     "dev-lane-write-set-fault"}):
        wf.results["create_plan"] = {"files_changed": [], "files_changed_shape": "ok"}
        assert dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf) is None
        for key in ("write_set_plan_gap", "initial_write_set"):
            assert key not in wf.meta
        assert "write_set_refresh_fault" in wf.meta


# ---------- D. malformed inputs (external-input discipline) ----------

@pytest.mark.parametrize("bad", ["server/a.py", {"files": ["x"]}, [1, 2], 7])
def test_malformed_receipt_never_gates_or_crashes(bad):
    for wf, dev_lane, _ in _mk_lane(GATE_IDS):
        wf.results["create_plan"] = {"files_changed": bad,
                                     "files_changed_shape": "malformed"}
        # no exception, no refusal (shape faces own the report)
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert "write_set_plan_gap" not in wf.meta
