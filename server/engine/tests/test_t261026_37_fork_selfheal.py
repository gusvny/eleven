#!/usr/bin/env python3
"""t261026-37 unit rig: the lane-dsh missing-profile self-heal journey converges.

Pins, in-process and temporal-free, the sub-case C journey of scenario
``integration/t260916-28/sc_t260916_28_lane_dsh_missing_profile.py`` at the level of
the dev_lane main loop (real loop code, stubbed activities):

    B-heal wake: implement+design edges re-run (design's stub prunes the profile)
      -> join settle -> mechanical tests (green stub)
      -> arb_acc fork: both edges hit the spawn-precheck refusal
      -> blocked(arbitrate)                      [scenario TOK_C_ARB]
      -> host supplies profile + retry_qc -> arbitrate edge re-runs (verdict=pass)
      -> gate-5 consumes the stranded FAILED walkthrough receipt
      -> blocked(acceptance_walkthrough)         [scenario TOK_C_ACC]
      -> host supplies profile + retry_qc -> walkthrough edge re-runs ok
      -> verdict=pass consumes the ok receipt -> merge_check

The fake machine models the two environmental facts the scenario prunes (source
profile home, lane .dsh copy). A spawn whose candidates are both empty returns the
failed StageResult carrying the lane_dsh refusal (``_lane_dsh_refusal`` predicate);
a spawn that passes precheck copies source -> lane; the design edge's stub prunes
BOTH homes mid-run (the scenario control.prune list).

Incident context (KI-376): at revision 0e67ab24 the scenario fails with the first C
blocked carrying stage=design_integration_tests and the ticket never reaching
merge_check. This rig runs the same journey through the real loop on that code and
must stay green: it pins the loop-side half of the contract (fork bookkeeping, the
KI-120 wake reset, gate-5) so a loop-level regression can never resurface silently.
UT runs no network and no Temporal (conftest only extends sys.path), per the shell
discipline of test_t260925_17_fork_gate_wake.py.

Run: engine venv ``python -m pytest server/engine/tests/test_t261026_37_fork_selfheal.py -q``.
"""
from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
from shared import IntegrationRunResult, SettleLaneResult  # noqa: E402

TICKET = "t26102637ut"
PRUNE_STAGES = ("review_plan", "design_integration_tests")


class _MergeCheckReached(Exception):
    """Terminal-success sentinel: the loop handed off to merge_check."""


class _OutOfRetries(Exception):
    """The machine blocked but the scripted host had no retry left."""


def _stage_result(status="ok", summary="", gate_refusal=None):
    return dev_lane.StageResult(
        status=status, summary=summary, report="[ut]", deliverables=[],
        files_changed=[], files_changed_shape="ok", evidence="ut",
        gate_refusal=gate_refusal, env_fail=False, env_reason="",
        handover_runs=[], handover_dropped=[])


class FakeMachine:
    """Two profile homes + the scripted stub, mirroring the scenario fixture."""

    def __init__(self, spawn_overrides=None):
        self.src_profile = True            # candidate 1: worker DSH_HOME source home
        self.lane_profile = False          # candidate 2: lane .dsh copy (pruned state)
        self.calls = []                    # every real stub invocation, in order
        self.retries_left = 2              # host hands: supply profile + retry_qc
        self.spawn_overrides = spawn_overrides or {}

    def spawn(self, stage: str):
        override = self.spawn_overrides.get(stage)
        if override is not None and not self.spawn_overrides.get("_after_prep"):
            return override()
        if not (self.src_profile or self.lane_profile):
            return _stage_result(
                status="failed",
                summary="lane .dsh missing sandbar-headless profile (t260916-28)",
                gate_refusal={"reason_code": "lane_dsh_profile_missing"})
        self.lane_profile = bool(self.src_profile)   # prep copy: source -> lane
        if override is not None:
            return override()
        self.calls.append(stage)
        if stage in PRUNE_STAGES:
            self.src_profile = False                 # stub control.prune: both homes
            self.lane_profile = False
        summary = "[ut] %s done" % stage
        if stage == "arbitrate":
            summary = "verdict=pass " + summary
        return _stage_result(summary=summary)

    def host_wake(self):
        if self.retries_left <= 0:
            raise _OutOfRetries(
                "blocked with no scripted retry left: %d blocks so far"
                % len([1]))
        self.retries_left -= 1
        self.src_profile = True


def _mk_wf(machine: FakeMachine):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: True,   # new-history face: every live gate on, as in prod
        now=lambda: datetime.datetime(2026, 10, 26, 12, 0, 0,
                                      tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None,
        sleep=lambda *_a, **_k: asyncio.sleep(0),
        wait_condition=None)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = TICKET
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 2          # scenario TOK_C_ARB: two retry_qc already consumed
    wf._rework = None
    wf.results = {}
    wf.engine_version = 2
    wf.machine = machine

    async def _wait_condition(cond):
        # one blocked == one human face: supply profile + retry_qc (token +1)
        machine.host_wake()
        wf._retry_token += 1
        assert cond(), "wait_condition predicate still false after host wake"
    dev_lane.workflow.wait_condition = _wait_condition

    async def _execute_activity(activity, args, **kw):
        name = getattr(activity, "name", None) or getattr(activity, "__name__", "") \
            or str(activity)
        if name in ("implement", "design_integration_tests",
                    "arbitrate", "acceptance_walkthrough"):
            return machine.spawn(name)
        if name == "settle_lane":
            return SettleLaneResult(note="clean", lane_commits=1, error="")
        if name == "run_integration_tests":
            return IntegrationRunResult(
                ran=1, passed=1, failed=0, env_fail=0,
                details=[{"name": "ut", "cmd": "", "exit": 0, "output_tail": ""}])
        if name == "merge_check":
            raise _MergeCheckReached()   # terminal-success sentinel
        if name in ("concurrency_acquire", "concurrency_renew",
                    "concurrency_release", "concurrency_release_if_paused"):
            return {"granted": True, "holding": True, "reason": "",
                    "released": True, "position": 0, "limit": 1, "waiting": 0,
                    "promoted": False, "dropped_stale": []}
        # remaining mechanical faces (main sync, changed-files, ui decl, ...):
        # permissive dict receipts; every consumer reads defensively via .get
        return {"ok": True, "note": "ut", "error": "", "phase": "", "stop": False,
                "files": [], "names": [], "mode": "none", "reason": "", "surfaces": [],
                "members": [], "own_members": [], "budget_min": 0,
                "own_error": "", "blocked_reason": "", "warning": "",
                "lane_commits": 1, "git_error": "", "shots_path_error": "",
                "png_count": 0, "prefixes": [], "mode_absent": "absent",
                "dir": "absent", "dirs": []}
    dev_lane.workflow.execute_activity = _execute_activity

    async def _noop():
        return None
    wf._pause_gate = _noop
    wf._concurrency_release_if_paused = _noop
    wf._drain_annex_requests = _noop
    wf._ledger_flush = _noop
    wf._ledger_enqueue = lambda entry: None

    async def _prep_ws():
        # the real prepare_workspace would reset the stage; the rig starts the
        # journey directly at the B-heal wake (impl fork, both edges pending)
        wf.meta["stage"] = "parallel_impl_design"
    wf._prepare_workspace_step = _prep_ws

    real_finish = dev_lane.DevLaneWorkflow._finish

    def _finish(self, step_id, by, evidence):
        if step_id == "merge_check":
            raise _MergeCheckReached()
        real_finish(self, step_id, by, evidence)
    wf._finish = _finish.__get__(wf)
    return wf


def _run_journey(machine=None):
    m = machine or FakeMachine()
    wf = _mk_wf(m)
    wf.meta = {
        "id": TICKET, "workflow_id": "dev-lane", "project": "ut", "title": "ut",
        "role": "developer", "lane": "worktree",
        "workspace": "/tmp/ut-t261026-37", "worktree": "/tmp/ut-t261026-37",
        "branch": "ut", "base_ref": "main", "stage": "parallel_impl_design",
        "stage_state": "running", "write_set": ["docs/"], "no_file_changes": False,
        "path_gate": False, "path_gate_rules": {}, "repo_worktrees": [],
        "project_root": "", "acceptance": [], "checks": {}, "deliverables": [],
        "user_request": "ut", "spec": "", "body": "", "pending": [], "handoffs": [],
        "status": "dispatched", "created": 0, "updated": 0, "log": [],
    }
    try:
        asyncio.run(dev_lane.DevLaneWorkflow.run(wf, SimpleNamespace(
            ticket_id=TICKET, template_id="dev-lane", project="ut", title="ut",
            lane="worktree", workspace="/tmp/ut-t261026-37",
            worktree="/tmp/ut-t261026-37", branch="ut", base_ref="main",
            proposal_id="", book_path="", epic="", write_set=["docs/"],
            deliverables=[], user_request="ut", spec="", body="", created=0)))
    except _MergeCheckReached:
        pass
    return m, wf


def _blocked_stages(wf):
    return [e.get("stage") for e in wf.timeline if e.get("state") == "blocked"]


# ---------- the journey ----------

def test_selfheal_journey_converges_to_merge_check():
    m, wf = _run_journey()
    # both scripted host hands consumed exactly (C_ARB wake, C_ACC wake)
    assert m.retries_left == 0, "journey ended with host hands left; blocks=%s" \
        % (_blocked_stages(wf),)
    # B-heal round: implement/design each ran exactly once (scenario :430 face)
    assert m.calls.count("implement") == 1, m.calls
    assert m.calls.count("design_integration_tests") == 1, m.calls
    # C chain: arbitrate re-ran once, acceptance re-ran once (scenario :468/:489)
    assert m.calls.count("arbitrate") == 1, m.calls
    assert m.calls.count("acceptance_walkthrough") == 1, m.calls
    # blocked face order: arbitrate (C_ARB) then acceptance_walkthrough (C_ACC) —
    # never stage=design_integration_tests (the incident's observed face, KI-376)
    assert _blocked_stages(wf) == ["arbitrate", "acceptance_walkthrough"], \
        _blocked_stages(wf)


# ---------- malformed receipts on the journey (external-input rule) ----------

def test_malformed_refusal_receipt_is_not_mistaken_for_lane_dsh():
    # a failed receipt whose gate_refusal is malformed (non-dict / missing code) must
    # NOT take the lane_dsh blocked path; the predicate stays silent and the existing
    # verdict/send-back handling owns the face (no crash, no false env narrative).
    from shared import StageResult as _SR  # noqa: F401  (shape sanity only)
    for bad in (None, "not-a-dict", {}, {"reason_code": ""}):
        res = _stage_result(status="failed", summary="x", gate_refusal=bad)
        assert dev_lane.DevLaneWorkflow._lane_dsh_refusal(None, res) is False, bad
    # a well-formed lane_dsh refusal still reads True (the pinned positive face)
    good = _stage_result(status="failed", summary="x",
                         gate_refusal={"reason_code": "lane_dsh_profile_missing"})
    assert dev_lane.DevLaneWorkflow._lane_dsh_refusal(None, good) is True


def test_malformed_acceptance_receipt_without_a_named_item_is_an_observation():
    # t261027-26 (KI-382): a failed walkthrough receipt WITHOUT a lane_dsh refusal and
    # WITHOUT a named failed acceptance item is not a send-back — the ticket proceeds to
    # merge_check (the observation face) and must not crash, not bounce, and not be
    # silently consumed as a pass.
    class NoFindingMachine(FakeMachine):
        bad_fired = False

        def spawn(self, stage):
            if stage == "acceptance_walkthrough" and not self.bad_fired:
                self.bad_fired = True
                return _stage_result(status="failed",
                                     summary="walkthrough found a defect")
            return super().spawn(stage)

    m = NoFindingMachine()
    m.retries_left = 6
    _, wf = _run_journey(m)
    stages = _blocked_stages(wf)
    assert stages == ["arbitrate"], stages       # no acceptance stop, no crash
    assert m.bad_fired, "the scripted failed receipt never reached the edge"
    assert m.calls.count("implement") == 1, m.calls   # an observation is not a send-back
    assert any(e.get("stage") == "acceptance_walkthrough" and e.get("state") == "done"
               for e in wf.timeline), wf.timeline[-6:]


def test_failed_acceptance_receipt_that_names_an_item_still_bounces():
    # the control half: the new rule must never turn the counter off — a receipt that
    # names a failed acceptance item still sends the work back to implement.
    class NamedFindingMachine(FakeMachine):
        bad_fired = False

        def spawn(self, stage):
            if stage == "acceptance_walkthrough" and not self.bad_fired:
                self.bad_fired = True
                return _stage_result(status="failed",
                                     summary="acceptance item 2 failed: the CLI exits 1")
            return super().spawn(stage)

    m = NamedFindingMachine()
    m.retries_left = 6
    _, wf = _run_journey(m)
    stages = _blocked_stages(wf)
    assert "arbitrate" in stages, stages
    assert m.calls.count("implement") >= 2, (m.calls, stages)


if __name__ == "__main__":
    m, wf = _run_journey()
    print("calls:", m.calls)
    print("blocks:", _blocked_stages(wf))
    print("retries_left:", m.retries_left)
