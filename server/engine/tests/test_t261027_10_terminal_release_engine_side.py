# -*- coding: utf-8 -*-
"""t261027-10 (KI-378 ①): a TERMINAL ticket's slot release no longer depends
on the ending caller's write access to the projects root.

Two engine arms, both tested here against a REAL ledger in a tmp projects
root (the t261004-27 lesson: assert the state-file bytes, not a receipt):

- PROMPT arm: cancel_notice / close_out_notice set `_terminal_slot_pending`
  (plain attribute, replay-deterministic, offline-stubbable handlers); the
  lane's run loop consumes it at the next async boundary behind
  TERMINAL_SLOT_PATCH_ID and releases via the worker-executed release
  activity. The headline case: the caller-side write is BLOCKED
  (PermissionError, the measured sandbox fault) and the slot still comes back.
- GUARANTEE arm: the acquire-time sweep (tested in
  test_t261027_10_bounded_probe_and_sweep.py) reclaims what even this arm
  loses to the terminate-vs-notice race.

Regression case (deliverable c): a ticket holding a slot reaches terminal,
concurrency-state.json no longer lists it, and a new ticket's acquire
succeeds immediately.

Patch guard (TMPRL1100 discipline): a history without the marker replays with
NO new command and the flag is retained — covered for BOTH notice signals and
for the failure path (a release fault is named on the ticket face, never
raised into the workflow task).
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import base  # noqa: E402
import client as cl  # noqa: E402  (existing tests import it the same way)
import concurrency as cc  # noqa: E402
import dev_lane  # noqa: E402

PATCH = dev_lane.TERMINAL_SLOT_PATCH_ID


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    return root, key


def _patched_all(monkeypatch):
    """Recording workflow facade: every patch on, execute_activity runs the
    REAL ledger function (the worker's side of the seam, minus Temporal)."""
    import datetime as _dt
    recorded = []

    async def execute_activity(act, arg=None, **k):
        name = getattr(act, "__name__", str(act))
        recorded.append((name, arg))
        if name == "concurrency_release":
            return cc.release(arg.project, arg.ticket, cause=arg.cause)
        if name == "concurrency_acquire":
            return cc.acquire(arg.project, arg.ticket, priority=bool(arg.priority))
        if name == "concurrency_renew":
            return cc.renew(arg.project, arg.ticket,
                            reason=cc.REASON_HUMAN_HOLD)
        return {}

    stub = SimpleNamespace(
        patched=lambda pid: True,
        execute_activity=execute_activity,
        info=lambda: SimpleNamespace(start_time=None),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None),
        sleep=lambda s: None,
        wait_condition=None,
        now=lambda: _dt.datetime(2026, 10, 27, 9, 0, 0,
                                 tzinfo=_dt.timezone.utc),
        upsert_memo=lambda *a, **k: None,
    )
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    return recorded


def _patched_none(monkeypatch):
    """Old-history replay: NO marker at all (the TMPRL1100 leg)."""
    import datetime as _dt
    stub = SimpleNamespace(
        patched=lambda pid: False,
        execute_activity=None,  # any command here would explode the test
        info=lambda: SimpleNamespace(start_time=None),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None),
        sleep=lambda s: None, wait_condition=None,
        now=lambda: _dt.datetime(2026, 10, 27, 9, 0, 0,
                                 tzinfo=_dt.timezone.utc),
        upsert_memo=lambda *a, **k: None,
    )
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)


def _wf(ticket, project):
    """A bare workflow instance carrying just what the handlers and the
    release helper read (the handlers never call workflow.* runtime APIs -
    that discipline is what makes this shape testable offline). Install the
    `recorded` fixture (or call _patched_none) BEFORE building one, so
    dev_lane._now_epoch/_log stay offline too."""
    wf = dev_lane.DevLaneWorkflow()
    wf.ticket_id = ticket
    wf.meta = {"project": project, "stage": "merge", "status": "running"}
    wf.timeline = []
    wf.refused = []
    return wf


@pytest.fixture
def recorded(monkeypatch):
    """Default facade for one test: patches on, real ledger functions."""
    return _patched_all(monkeypatch)


def _face_notes(wf):
    return [row.get("note", "") for row in wf.meta.get("log", [])]


# ---------- the handlers schedule the release ----------

def test_cancel_notice_acceptance_sets_the_pending_flag(proj, recorded):
    wf = _wf("t-old", proj[1])
    wf.cancel_notice({"who": "host", "reason": "cleanup",
                      "caller_project": "", "cross_project_note": ""})
    assert wf._terminal_slot_pending is True
    assert not wf.refused


def test_close_out_notice_acceptance_sets_the_pending_flag(proj, recorded):
    wf = _wf("t-old", proj[1])
    wf._mark = lambda *a, **k: None  # keep the offline shape (no ledger enqueue)
    wf.close_out_notice({"who": "host", "reason": "work is done",
                         "caller_project": "", "cross_project_note": ""})
    assert wf._terminal_slot_pending is True
    assert not wf.refused


def test_malformed_cancel_notice_refused_zero_side_effects(proj):
    wf = _wf("t-old", proj[1])
    wf.cancel_notice({"who": "", "reason": "cleanup"})
    assert wf._terminal_slot_pending is False
    assert any(r["want"] == "cancel_notice" for r in wf.refused)
    wf.cancel_notice({"who": "host", "reason": "   "})
    assert wf._terminal_slot_pending is False


def test_malformed_close_out_notice_refused_zero_side_effects(proj):
    wf = _wf("t-old", proj[1])
    wf._mark = lambda *a, **k: None
    wf.close_out_notice({"who": "host", "reason": ""})
    assert wf._terminal_slot_pending is False
    assert any(r["want"] == "close_out_notice" for r in wf.refused)


def test_cross_project_refusal_schedules_no_release(proj, monkeypatch, recorded):
    import shared
    wf = _wf("t-old", proj[1])
    # A declared DIFFERENT project without the escalation flag: refused.
    monkeypatch.setattr(shared, "PROJECT_CALLERS", {"proj-beta": {}}, raising=False)
    wf.cancel_notice({"who": "host", "reason": "cleanup",
                      "caller_project": "proj-beta", "cross_project_note": ""})
    assert wf._terminal_slot_pending is False


# ---------- the async-boundary consumption ----------

def test_pending_flag_is_consumed_once_with_the_right_cause(proj, recorded):
    wf = _wf("t-old", proj[1])
    wf._terminal_slot_pending = True
    asyncio.run(wf._terminal_slot_release_if_pending())
    assert wf._terminal_slot_pending is False
    rel = [(n, a) for n, a in recorded if n == "concurrency_release"]
    assert len(rel) == 1 and rel[0][1].cause == "terminated"
    assert rel[0][1].ticket == "t-old" and rel[0][1].project == proj[1]


def test_no_flag_no_command(proj, recorded):
    wf = _wf("t-old", proj[1])
    asyncio.run(wf._terminal_slot_release_if_pending())
    assert recorded == []


def test_patch_guard_old_history_keeps_the_flag_and_emits_nothing(
        proj, monkeypatch):
    """Replay discipline: a history recorded before TERMINAL_SLOT_PATCH_ID
    emits no new command and does NOT lose the flag (a later replay that HAS
    the marker still gets the release)."""
    _patched_none(monkeypatch)
    wf = _wf("t-old", proj[1])
    wf._terminal_slot_pending = True
    asyncio.run(wf._terminal_slot_release_if_pending())
    assert wf._terminal_slot_pending is True  # retained, not silently eaten


def test_release_fault_is_named_on_the_face_never_raised(proj, recorded):
    wf = _wf("t-old", proj[1])
    wf._terminal_slot_pending = True

    async def _boom(cause):
        raise RuntimeError("ledger unwritable")

    wf._concurrency_release = _boom
    asyncio.run(wf._terminal_slot_release_if_pending())
    assert wf._terminal_slot_pending is False
    hits = [n for n in _face_notes(wf) if "Terminal slot release failed" in n]
    assert hits and "RuntimeError" in hits[0] and "ledger unwritable" in hits[0]


def test_both_run_loops_wired_source_lock():
    """Mechanical wiring guard (t261004-32 idiom): BOTH lane loops must call
    the consumer before the pause gate — a missed wiring is red here, never a
    silent bypass."""
    src = (ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    assert src.count("await self._terminal_slot_release_if_pending()") >= 2, (
        "both run loops (dev-lane + quickmanual) must consume the flag")
    for chunk in src.split("while phase != \"done\":")[1:]:
        rel = chunk.find("await self._terminal_slot_release_if_pending()")
        pause = chunk.find("await self._pause_gate()")
        assert rel != -1 and pause != -1 and rel < pause, (
            "the terminal release must be consumed BEFORE the pause gate "
            "renews a hold the ticket is about to give back")


# ---------- headline + regression, real ledger bytes ----------

def test_caller_write_blocked_engine_arm_still_returns_the_slot(proj, monkeypatch, recorded):
    """THE ticket case: the ending caller cannot write the projects root
    (PermissionError on the lock, as measured in the agent sandbox) - the
    receipt is honest (released:false) AND the engine arm returns the slot."""
    root, key = proj
    assert cc.acquire(key, "t-old")["granted"] is True
    state = root / key / cc.STATE_FILE
    assert "t-old" in state.read_text(encoding="utf-8")

    # Caller-side write blocked: the exact measured fault.
    real_release = cc.release

    def _locked_out(*a, **k):
        raise PermissionError(
            "[Errno 1] Operation not permitted: .../concurrency-state.json.lock")

    monkeypatch.setattr(cc, "release", _locked_out)
    receipt = cl._release_slot_after_cancel(key, "t-old")
    assert receipt["released"] is False
    assert "PermissionError" in str(receipt.get("reason", ""))
    # The state file still lists the holder - the caller truly wrote nothing.
    assert "t-old" in state.read_text(encoding="utf-8")

    # Engine prompt arm: notice accepted -> boundary consumes -> REAL release
    # (the stub facade reaches the unblocked engine-side function).
    monkeypatch.setattr(cc, "release", real_release)
    wf = _wf("t-old", key)
    wf.cancel_notice({"who": "host", "reason": "cleanup",
                      "caller_project": "", "cross_project_note": ""})
    asyncio.run(wf._terminal_slot_release_if_pending())

    # Deliverable (c), reader's side: the STATE FILE no longer lists it.
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert doc["holders"] == [], doc
    assert "t-old" not in state.read_text(encoding="utf-8")

    # ...and a new ticket's acquire succeeds IMMEDIATELY (no queue, no wait).
    res = cc.acquire(key, "t-new")
    assert res["granted"] is True and res["position"] == 0
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert [h["ticket"] for h in doc["holders"]] == ["t-new"]


def test_close_out_notice_engine_arm_also_returns_the_slot(proj, recorded):
    """Review condition: the close_out path gets the same patch-guard +
    release treatment as cancel (the guard test covers both notices)."""
    root, key = proj
    assert cc.acquire(key, "t-old")["granted"] is True
    wf = _wf("t-old", key)
    wf._mark = lambda *a, **k: None
    wf.close_out_notice({"who": "host", "reason": "done",
                         "caller_project": "", "cross_project_note": ""})
    asyncio.run(wf._terminal_slot_release_if_pending())
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    assert doc["holders"] == []
    assert cc.acquire(key, "t-new")["granted"] is True


def test_old_history_replay_writes_nothing_while_holding(proj, monkeypatch):
    _patched_none(monkeypatch)
    root, key = proj
    assert cc.acquire(key, "t-old")["granted"] is True
    wf = _wf("t-old", key)
    wf.cancel_notice({"who": "host", "reason": "cleanup",
                      "caller_project": "", "cross_project_note": ""})
    asyncio.run(wf._terminal_slot_release_if_pending())
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    assert [h["ticket"] for h in doc["holders"]] == ["t-old"]
