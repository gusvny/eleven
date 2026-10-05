# -*- coding: utf-8 -*-
"""t261005-14 replay compatibility of the CL-1 concurrency family - unit tests.

Incident: CL-1 (775bdb1, 2026-10-05) wired the project concurrency gate into
both lanes UNGUARDED. A ticket whose history was recorded before CL-1 has
`prepare_workspace` as its first scheduled activity; a worker on post-CL-1 code
replays it and schedules `concurrency_acquire` first -> deterministic
TMPRL1100 "Nondeterminism error" -> the workflow task fails forever (three live
tickets frozen: t261005-02 / t261005-06 / t261004-36).

Fix under test (plan rev 2, review round 2): the whole CL-1-new command family
is wrapped under one patch id per lane -
  - gate call sites: dev_lane.run entry + stage loop, light_lane.run entry +
    stage loop -> `workflow.patched(<lane id>)`;
  - emitting helpers `_concurrency_release` / `_concurrency_renew`: early
    return when not patched (covers stage boundary pause accounting, human-gate
    renew, blocked renew, terminal release).
A pre-CL-1 history has no marker -> patched() = False -> zero new commands ->
byte-identical replay. New runs record the marker and stay fully gated.

Test matrix (plan rev 2 T1-T6):
  T1 required regression (red on unguarded code): patched->False run entry
     records `prepare_workspace`, never `concurrency_acquire`;
  T2 family regression (red on unguarded code): patched->False + paused at a
     stage boundary records NO `concurrency_release`;
  T3 positive proof: patched->True run entry records `concurrency_acquire`
     first (new runs stay gated);
  T4 positive proof: patched->True release/renew emit their activities;
  T5 static lock: patch id literals pinned + every family site inside a
     patched() guard (unwinding any of them is red) - covers the light-lane
     renew site per review;
  T6 malformed input: empty project key under patched->False must not raise
     (the gate is never entered in replay mode); patched->True + empty key
     fails closed with the named rule-9 ValueError.

Zero Temporal / zero network / zero git; the `workflow` facade is monkeypatched
(auto-restored) with a recording stub.
"""
import asyncio
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import light_lane  # noqa: E402


class _StopAtPrepare(Exception):
    """Sentinel: run() reached _prepare_workspace_step - stop the harness."""


def _stub_workflow(patched_value, recorded):
    """Recording facade: execute_activity appends the activity NAME, sleep is
    forbidden (a queue wait would hang the harness - fail loud instead)."""

    async def execute_activity(act, *a, **k):
        name = getattr(act, "__name__", str(act))
        recorded.append(name)
        if name == "concurrency_acquire":
            return {"granted": True, "position": None, "limit": 2,
                    "holders": [], "waiting": 0}
        if name == "concurrency_release":
            return {"released": True, "promoted": False, "waiting": 0}
        return {"holding": True, "reason": "ok"}

    def sleep(_):
        raise AssertionError("queue sleep reached: gate was not granted")

    async def wait_condition(cond):
        pass

    return SimpleNamespace(
        patched=lambda pid: patched_value,
        execute_activity=execute_activity,
        sleep=sleep,
        wait_condition=wait_condition,
        now=lambda: __import__("datetime").datetime(2026, 10, 5, 15, 0, 0),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))


@contextlib.contextmanager
def pytest_stop():
    """Let run() proceed until the prepare sentinel, re-raise anything else."""
    try:
        yield
    except _StopAtPrepare:
        pass


def _build(patched_value, monkeypatch, recorded, project="proj-alpha"):
    stub = _stub_workflow(patched_value, recorded)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = "t26100514ut"
    wf.meta = {"status": "dispatched", "log": [], "project": project,
               "stage_state": "running", "stage": "implement"}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 0
    wf._rework = None
    wf._paused = False
    wf.engine_version = 2
    wf._reached_prepare = False

    async def prepare():
        wf._reached_prepare = True
        raise _StopAtPrepare()
    wf._prepare_workspace_step = prepare
    return wf


def _inp(project="proj-alpha"):
    """Minimal TicketInput for _init (all direct-attr keys it reads)."""
    return SimpleNamespace(
        ticket_id="t26100514ut", template_id="dev-lane-v2", project=project,
        title="ut", lane="", workspace="/tmp/wt", worktree="/tmp/wt",
        branch="lane/x", base_ref="main", proposal_id="", book_path="",
        epic="", acceptance_extra=None, repo_worktrees=None, project_root="",
        write_set=[], user_request="", spec="", body="", created=0,
        deliverables=[])


# ---------- T1: required regression - pre-CL-1 replay skips the gate ----------

def test_t1_pre_cl1_replay_first_activity_is_prepare_workspace(monkeypatch):
    """Red on today's code: the ungated run entry schedules concurrency_acquire
    before prepare_workspace (the reported TMPRL1100 divergence)."""
    recorded = []
    wf = _build(False, monkeypatch, recorded)
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert "concurrency_acquire" not in recorded, (
        "pre-CL-1 replay scheduled a CL-1-new command: %r" % (recorded,))
    # And the run did reach the first stage (the sentinel proves the ordering
    # point was passed, i.e. the gate was skipped, not the run derailed).
    assert wf._reached_prepare, "run() never reached prepare_workspace"
    assert recorded == [], recorded


# ---------- T2: family regression - paused replay emits no release ----------

def test_t2_pre_cl1_replay_paused_boundary_no_release(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded)
    wf._paused = True
    asyncio.run(wf._concurrency_release_if_paused())
    # Same replay leg through _blocked's renew path (t261005-06 sits blocked).
    asyncio.run(wf._blocked("implement", "blocked why"))
    assert "concurrency_release" not in recorded, recorded
    assert "concurrency_renew" not in recorded, recorded


# ---------- T3: positive proof - new runs stay gated ----------

def test_t3_new_run_still_gated(monkeypatch):
    recorded = []
    wf = _build(True, monkeypatch, recorded)
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded[:1] == ["concurrency_acquire"], recorded


# ---------- T4: positive proof - the release family still emits ----------

def test_t4_new_run_release_family_emits(monkeypatch):
    recorded = []
    wf = _build(True, monkeypatch, recorded)
    wf._paused = True
    asyncio.run(wf._concurrency_release_if_paused())
    asyncio.run(wf._concurrency_release(dev_lane.CAUSE_TERMINATED))
    asyncio.run(wf._concurrency_renew(dev_lane.CAUSE_HUMAN_GATE))
    assert "concurrency_release" in recorded, recorded
    assert "concurrency_renew" in recorded, recorded


# ---------- T6: malformed input across the guard ----------

def test_t6_empty_project_key_replay_leg_silent_new_leg_fails_closed(monkeypatch):
    # Replay leg: the gate is never entered, the empty key never judged.
    recorded = []
    wf = _build(False, monkeypatch, recorded, project="")
    with pytest_stop():
        asyncio.run(wf.run(_inp(project="")))
    assert "concurrency_acquire" not in recorded
    assert wf._reached_prepare
    # New-run leg: the gate runs and fails closed by name (rule 9).
    recorded2 = []
    wf2 = _build(True, monkeypatch, recorded2, project="")
    try:
        asyncio.run(wf2._concurrency_gate())
        raise AssertionError("empty project key admitted (rule 9 broken)")
    except ValueError as e:
        assert "no project key" in str(e) and "fail-closed" in str(e)


# ---------- T5: static lock over the whole family ----------

def _src(p):
    return Path(p).read_text(encoding="utf-8")


def test_t5_static_lock_family_guarded():
    dl = _src(POC / "dev_lane.py")
    ll = _src(POC / "light_lane.py")
    # Id literals pinned (a rename breaks in-flight replay discipline).
    assert 'CONCURRENCY_GATE_PATCH_ID = "dev-lane-concurrency-gate-v1"' in dl
    assert ('LIGHT_CONCURRENCY_GATE_PATCH_ID = '
            '"light-lane-concurrency-gate-v1"') in ll
    # Every gate call site is individually guarded (4 sites).
    for src in (dl, ll):
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "await self._concurrency_gate()" in line:
                window = "\n".join(lines[max(0, i - 4):i + 1])
                # t261005-15: the guard reads the shared predicate now - the
                # marker arm lives inside it; a bare patched() call here
                # would silently drop the window-(b) time arm.
                assert ("workflow.patched(" in window
                        or "_concurrency_gate_active(" in window), (
                    "unguarded gate call at %s line %d" % (i + 1,))
    # The emitting helpers open with the patched early return (shared by both
    # lanes - this is what covers the light-lane renew/release sites).
    # t261005-15: the predicate call satisfies the same lock.
    for helper in ("async def _concurrency_release(", "async def _concurrency_renew("):
        idx = dl.index(helper)
        body = dl[idx:idx + 600]
        assert ("if not workflow.patched(" in body
                or "if not _concurrency_gate_active(" in body), helper
