#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261022-12: main-sync conflict handback for the quickmanual lane — unit tests.

Measured on two tickets: the quickmanual settle path's pre-verification main sync
hit a conflict and entered the shared resolution loop, which hard-codes an
implement agent step. QuickmanualLaneWorkflow.STAGES has no implement, so
_step('implement') raised ValueError: unknown step 'implement' and the ticket
wedged with a reason naming neither the file nor the way out.

The fix, locked here:
  H1 a lane with no agent resolution stage hands the conflict back to its OWN
     working stage (quickmanual = work) — no agent stage is invented;
  H2 the pinned blocked reason names the conflicting files, the failed merge
     (`git merge main`, sha, repo) and the exact way out (resolve in the lane
     worktree, do NOT git commit, signal work_done again);
  H3 dev-lane and light-lane keep their own agent stage (implement) — unchanged
     behaviour where the stage exists;
  H4 replay safety: the new branch sits behind
     MAIN_SYNC_CONFLICT_HANDBACK_PATCH_ID; gate off = the old path verbatim;
  S  the post-handback work_done settle routes through settle_conflict_resolution
     (the merge is left OPEN on purpose), residue / infra failure block named,
     success resets the counters and records the merged main_sync face.

Run: python3 -m pytest server/engine/tests/test_t261022_12_main_sync_handback.py -q
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import light_lane  # noqa: E402
from shared import classify_stop_tier  # noqa: E402

QMW = dev_lane.QuickmanualLaneWorkflow
DW = dev_lane.DevLaneWorkflow
LW = light_lane.LightLaneWorkflow

HB = dev_lane.MAIN_SYNC_CONFLICT_HANDBACK_PATCH_ID

NOW = SimpleNamespace(start_time=None)


def _prep_conflict(**over):
    """A conflict-shaped prepare_conflict_resolution receipt (dict transport
    shape — the workflow's dict fallback reconstruction is the consumer)."""
    base = dict(ok=True, conflict_files=["server/engine/x.py"],
                merge_output="CONFLICT (content): Merge conflict in x.py",
                already_clean=False, error="", target_sha="abc1234def56",
                lane_head="1234567", up_to_date=False, branch_tip="abc1234")
    base.update(over)
    return base


class _Shell:
    """Offline dev_lane.workflow facade: per-test patched set + recorded
    activity calls (test_quickmanual_lane.py's discipline)."""

    def __init__(self, patched_ids=(), activities=None, prep=None, settle=None,
                 settle_exc=None):
        self.patched_ids = set(patched_ids)
        self.calls = activities if activities is not None else []
        self.prep = prep
        self.settle = settle if settle is not None else dict(
            ok=True, commit="fedcba9", remaining_files=[], error="")
        self.settle_exc = settle_exc
        self.args = {}

        async def execute_activity(fn, arg, **kw):
            self.calls.append(getattr(fn, "__name__", str(fn)))
            self.args[getattr(fn, "__name__", str(fn))] = arg
            name = getattr(fn, "__name__", "")
            if name == "prepare_conflict_resolution":
                return self.prep
            if name == "settle_conflict_resolution":
                if self.settle_exc is not None:
                    raise self.settle_exc
                return self.settle
            raise AssertionError("unexpected activity requested: %s" % name)

        self.execute_activity = execute_activity

    def patched(self, pid):
        return pid in self.patched_ids

    def now(self):
        return None

    def info(self):
        return NOW

    async def wait_condition(self, cond):
        return None

    class _L:
        @staticmethod
        def info(*a, **k):
            pass

        warning = warn = info


def _mk_wf(cls, activities, patched_ids=(), prep=None, settle=None,
           settle_exc=None):
    """A lane workflow shell without a Temporal runtime (records, never runs)."""
    shell = _Shell(patched_ids=patched_ids, activities=activities, prep=prep,
                   settle=settle, settle_exc=settle_exc)
    dev_lane.workflow = shell
    wf = object.__new__(cls)
    wf.meta = {"worktree": "/tmp/lane-wt", "branch": "lane",
               "stage": "run_integration_tests"}
    wf.ticket_id = "t-ut-261022-12"
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.refused = []
    wf._detail_face_on = True
    wf._conflict_rounds = 0
    wf._prev_conflict_files = []
    wf._main_sync_settle_pending = False
    wf._main_sync_handback_sha = ""
    wf._main_sync_handback_wt = ""
    wf._main_sync_handback_branch = ""
    blocked = []

    wf._log = lambda *a, **k: None
    wf._touch = lambda: None
    wf._now_epoch = lambda: 0.0
    wf._handoff = lambda *a, **k: None
    wf._mark = lambda *a, **k: None
    wf._persist_stage_memo = lambda *a, **k: None

    async def _blocked(step_id, why):
        blocked.append((step_id, why))

    wf._blocked = _blocked
    wf.blocked_calls = blocked

    def _no_agent_step(*a, **k):
        raise AssertionError("an agent step was requested: %r" % (a,))

    wf._run_agent_step = _no_agent_step
    return wf


@pytest.fixture(autouse=True)
def _restore_workflow_facade():
    saved = dev_lane.workflow
    yield
    dev_lane.workflow = saved


# ---------------- H1+H2: quickmanual conflict hands back to work ----------------

def test_quickmanual_conflict_hands_back_to_work_no_implement():
    acts = []
    wf = _mk_wf(QMW, acts, patched_ids={HB},
                prep=_prep_conflict())
    res = asyncio.run(wf._main_sync_before_gate(texts={}))
    # no implement step is requested (the _run_agent_step stub raises), and the
    # only activity the loop ran is the sync prep
    assert acts == ["prepare_conflict_resolution"]
    assert res["stop"] == "rework" and res["phase"] == "work"
    assert wf.meta["stage"] == "work"
    assert wf.meta["stage_state"] == "awaiting"
    assert wf.meta["status"] == "rework"
    assert wf.meta["role"] == "developer"  # the work stage's own role
    reason = wf.meta["blocked_reason"]
    assert "server/engine/x.py" in reason            # the conflicting files
    assert "git merge main" in reason                # the merge that failed
    assert "abc1234" in reason                       # the merged-in sha
    assert "MERGE_HEAD" in reason                    # the open-merge face
    assert "do NOT git commit" in reason             # the worker settles
    assert "work_done" in reason                     # the exact way out
    # the blocked tier/kind stay whatever the reason classifies to — pinned so
    # the "awaiting its session, not faulted" reading is a deliberate choice
    tier, kind = classify_stop_tier(reason)
    assert wf.meta["blocked_tier"] == tier
    assert wf.meta["blocked_evidence"] == {"kind": kind, "cited_row_id": ""}
    # the handback state for the work-phase settle routing
    assert wf._main_sync_settle_pending is True
    assert wf._main_sync_handback_sha == "abc1234def56"
    assert wf._main_sync_handback_wt == "/tmp/lane-wt"
    assert wf._main_sync_handback_branch == "lane"
    # the cap/same-batch guard state still advances (a spinning lane still stops)
    assert wf._conflict_rounds == 1
    assert wf._prev_conflict_files == ["root:server/engine/x.py"]


def test_quickmanual_handback_reason_survives_malformed_sync_receipt():
    """House rule, malformed input: a receipt with files but no sha/output
    degrades to named fallbacks in the reason — never an exception, still lands
    on work with the pending settle armed."""
    acts = []
    wf = _mk_wf(QMW, acts, patched_ids={HB},
                prep=_prep_conflict(target_sha="", merge_output=None))
    res = asyncio.run(wf._main_sync_before_gate(texts={}))
    assert res["stop"] == "rework" and res["phase"] == "work"
    reason = wf.meta["blocked_reason"]
    assert "server/engine/x.py" in reason
    assert "main" in reason           # the sha falls back to the bare ref name
    assert wf._main_sync_settle_pending is True


# ---------------- H3: dev/light keep their own agent stage ----------------

def test_lane_vocabulary_attributes():
    assert DW.MAIN_SYNC_RESOLVE_STEP == "implement"
    assert DW.MAIN_SYNC_WORK_STAGE is None
    assert LW.MAIN_SYNC_WORK_STAGE is None      # inherited: light lane keeps implement
    assert LW.MAIN_SYNC_RESOLVE_STEP == "implement"
    assert QMW.MAIN_SYNC_WORK_STAGE == "work"   # the only handback lane


def test_dev_lane_conflict_still_requests_implement_with_gate_on():
    """Requirement 3: the handback branch is unreachable where the agent stage
    exists — dev-lane, gate ON, still runs the implement resolution loop."""
    acts = []
    wf = _mk_wf(DW, acts, patched_ids={HB, dev_lane.COUNTER_RESET_PATCH_ID},
                prep=_prep_conflict())

    class _Ok:
        status = "ok"

    wf._run_agent_step = lambda step_id, *a, **k: (
        acts.append("agent_step:" + str(step_id)), _async(_Ok()))[1]
    res = asyncio.run(wf._main_sync_before_gate(texts={}))
    assert "agent_step:implement" in acts                    # the agent step was requested
    assert "settle_conflict_resolution" in acts   # ...then the worker settle
    assert res["stop"] == "rework"
    assert res["phase"] == "implement"            # back to implement, as before
    assert not wf.blocked_calls


def _async(v):
    async def _go():
        return v
    return _go()


def test_light_lane_conflict_still_requests_implement():
    acts = []
    wf = _mk_wf(LW, acts, patched_ids={HB, dev_lane.COUNTER_RESET_PATCH_ID},
                prep=_prep_conflict())

    class _Ok:
        status = "ok"

    wf._run_agent_step = lambda step_id, *a, **k: (
        acts.append("agent_step:" + str(step_id)), _async(_Ok()))[1]
    res = asyncio.run(wf._main_sync_before_gate(texts={}))
    assert "agent_step:implement" in acts
    assert res["phase"] == "implement"


# ---------------- H4: replay safety ----------------

def test_gate_off_replays_the_old_implement_path():
    acts = []
    wf = _mk_wf(QMW, acts, patched_ids=set(),  # patched() all-False
                prep=_prep_conflict())

    class _Ok:
        status = "ok"

    wf._run_agent_step = lambda step_id, *a, **k: (
        acts.append("agent_step:" + str(step_id)), _async(_Ok()))[1]
    res = asyncio.run(wf._main_sync_before_gate(texts={}))
    # a pre-marker history re-records the old command sequence verbatim
    assert "agent_step:implement" in acts
    assert res["phase"] == "implement"
    assert wf._main_sync_settle_pending is False


# ---------------- S: the post-handback work_done settle ----------------

def _handed_back_wf(activities, settle=None, settle_exc=None):
    wf = _mk_wf(QMW, activities, patched_ids={HB}, prep=_prep_conflict(),
                settle=settle, settle_exc=settle_exc)
    asyncio.run(wf._main_sync_before_gate(texts={}))
    assert wf._main_sync_settle_pending is True
    wf._conflict_rounds = 2  # a later round: the settle must see the real round
    return wf


def test_handback_settle_routes_through_conflict_settle():
    acts = []
    wf = _handed_back_wf(acts, settle=dict(ok=True, commit="deadbee",
                                           remaining_files=[], error=""))
    s = asyncio.run(wf._quick_conflict_settle_after_handback())
    assert s is not None and s.error == ""
    assert "deadbee" in s.note
    assert acts == ["prepare_conflict_resolution", "settle_conflict_resolution"]
    args = wf._Shell_args if hasattr(wf, "_Shell_args") else None
    a = dev_lane.workflow.args["settle_conflict_resolution"]
    assert a.worktree == "/tmp/lane-wt"      # the handback's repo, not the root
    assert a.branch == "lane"
    assert a.base_ref == "main"
    assert a.round_no == 2
    assert wf._main_sync_settle_pending is False   # consumed (retry re-enters clean)
    assert wf._conflict_rounds == 0                # progress = reset (R2)
    assert wf._prev_conflict_files == []
    ms = wf.meta["main_sync"]
    assert ms["mode"] == "merged" and ms["lane_head"] == "deadbee"
    assert ms["main_sha"] == "abc1234def56"
    assert not wf.blocked_calls


def test_handback_settle_residue_blocks_named():
    acts = []
    wf = _handed_back_wf(acts, settle=dict(ok=False, commit="",
                                           remaining_files=["a.txt", "b.txt"],
                                           error=""))
    s = asyncio.run(wf._quick_conflict_settle_after_handback())
    assert s is None
    step, why = wf.blocked_calls[-1]
    assert step == "work"
    assert "a.txt" in why and "b.txt" in why
    assert "work_done" in why                      # the way out is named again
    assert "engine_ops.py" in why and "--abort" in why   # the operator exit
    assert wf._main_sync_settle_pending is False   # consumed either way


def test_handback_settle_infra_failure_blocks_named():
    acts = []
    wf = _handed_back_wf(acts, settle_exc=RuntimeError("git died"))
    s = asyncio.run(wf._quick_conflict_settle_after_handback())
    assert s is None
    step, why = wf.blocked_calls[-1]
    assert step == "work"
    assert "RuntimeError" in why and "git died" in why
    assert wf._main_sync_settle_pending is False


def test_handback_settle_already_settled_face_is_success():
    """KI-213 stance: an already_settled=True receipt (merge commit on disk) is a
    success, not a block — the next gate round's sync goes up_to_date."""
    acts = []
    wf = _handed_back_wf(acts, settle=dict(ok=False, commit="deadbee",
                                           remaining_files=[], error=""))
    # the dict transport has no already_settled key; exercise the attribute face
    settle = SimpleNamespace(ok=False, commit="deadbee", remaining_files=[],
                             error="no merge in progress", already_settled=True)
    wf._Shell_settle = settle
    dev_lane.workflow.settle = settle
    s = asyncio.run(wf._quick_conflict_settle_after_handback())
    assert s is not None and "deadbee" in s.note
    assert not wf.blocked_calls


# ---------------- structural: the wake clears the pinned blocked face --------

def test_work_phase_wake_clears_the_blocked_face():
    src = inspect.getsource(QMW._run_quickmanual)
    wait_at = src.index("wait_condition")
    clear_at = src.index('self.meta["blocked_reason"] = ""')
    assert wait_at < clear_at  # the clear sits after the park's wake point
