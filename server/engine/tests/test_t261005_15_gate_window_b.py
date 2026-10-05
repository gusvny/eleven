# -*- coding: utf-8 -*-
"""t261005-15 replay window (b) of the CL-1 concurrency family - unit tests.

Incident: the t261005-14 guard (`workflow.patched("dev-lane-concurrency-gate-v1")`)
skips the gate for a history that STARTED after CL-1 (775bdb1, 07:20:14 +0800)
but before the guard landed (16:15). Such a history HAS `concurrency_acquire`
(the then-unguarded code scheduled it) yet carries no marker, so the marker arm
returns False, the guard skips the gate, and the replay schedules
`prepare_workspace` where history says `concurrency_acquire` -> TMPRL1100,
workflow task fails forever (live freeze: t261005-09 / t261005-10). This is
the mirror of KI-201.

Fix under test: predicate `_concurrency_gate_active(wf, patch_id)` -
  arm 1 (marker, t261005-14 kept): `wf.patched(patch_id)` -> gate on;
  arm 2 (window (b)): `wf.info().start_time >= CL1_GATE_LANDED_AT` -> gate on.
`start_time` is part of the history, constant per instance across every
replay; the anchor is a frozen module constant - one verdict per history
forever.

Test matrix:
  W1 window (b) run entry (RED on pre-fix code): patched=False, start after
     CL-1 -> the first recorded command is `concurrency_acquire` and the run
     reaches prepare_workspace, i.e. the replay matches the existing history
     shape with NO TMPRL1100-class divergence.
  W2 window (a) preserved: patched=False, start before CL-1 -> zero
     concurrency commands, prepare_workspace reached (exact historical skip).
  W3 window (c) preserved: patched=True -> gate runs regardless of time.
  W4 window (b) through _concurrency_release (paused boundary) - emits.
  W5 window (b) through _concurrency_renew (blocked leg) - emits.
  W6 boundary: start_time exactly at the anchor -> gate on.
  W7 degenerate inputs: start_time None / non-datetime / raising info()
     -> no raise, falls back to the marker verdict.
  W8 light lane: same predicate semantics through its run entry.
  W9 static lock: every family site reads the predicate; the anchor
     constant literal is pinned (a rename or a silent change of the
     anchor breaks the discipline).

Zero Temporal / zero network / zero git; the `workflow` facade is
monkeypatched (auto-restored) with a recording stub.
"""
import asyncio
import contextlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import light_lane  # noqa: E402

ANCHOR = dev_lane.CL1_GATE_LANDED_AT
AFTER_CL1 = ANCHOR + timedelta(hours=8)    # window (b): between CL-1 and the guard
BEFORE_CL1 = ANCHOR - timedelta(hours=8)   # window (a)


class _StopAtPrepare(Exception):
    """Sentinel: run() reached _prepare_workspace_step - stop the harness."""


def _stub_workflow(patched_value, recorded, start_time=AFTER_CL1,
                   info_raises=False):
    """Recording facade with a controllable info().start_time."""

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

    def info():
        if info_raises:
            raise RuntimeError("degenerate info()")
        return SimpleNamespace(start_time=start_time)

    return SimpleNamespace(
        patched=lambda pid: patched_value,
        execute_activity=execute_activity,
        sleep=sleep,
        wait_condition=wait_condition,
        info=info,
        now=lambda: datetime(2026, 10, 5, 15, 0, 0),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))


@contextlib.contextmanager
def pytest_stop():
    try:
        yield
    except _StopAtPrepare:
        pass


def _build(patched_value, monkeypatch, recorded, project="proj-alpha",
           start_time=AFTER_CL1, lane="dev", info_raises=False):
    stub = _stub_workflow(patched_value, recorded,
                          start_time=start_time, info_raises=info_raises)
    if lane == "dev":
        monkeypatch.setattr(dev_lane, "workflow", stub)
        wf = object.__new__(dev_lane.DevLaneWorkflow)
    else:
        monkeypatch.setattr(light_lane, "workflow", stub)
        monkeypatch.setattr(dev_lane, "workflow", stub)  # inherited helpers
        wf = object.__new__(light_lane.LightLaneWorkflow)
    wf.ticket_id = "t26100515ut"
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
    return SimpleNamespace(
        ticket_id="t26100515ut", template_id="dev-lane-v2", project=project,
        title="ut", lane="", workspace="/tmp/wt", worktree="/tmp/wt",
        branch="lane/x", base_ref="main", proposal_id="", book_path="",
        epic="", acceptance_extra=None, repo_worktrees=None, project_root="",
        write_set=[], user_request="", spec="", body="", created=0,
        deliverables=[])


# ---------- W1: window (b) run entry - the required red regression ----------

def test_w1_window_b_run_entry_gates_with_no_marker(monkeypatch):
    """Red on pre-fix code: a history that started after CL-1 but before the
    guard HAS concurrency_acquire and has no marker. The replay must schedule
    the SAME command first (no TMPRL1100-class divergence) and reach the
    first stage."""
    recorded = []
    wf = _build(False, monkeypatch, recorded)  # no marker exists in history
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded[:1] == ["concurrency_acquire"], (
        "window-(b) replay diverges: history's first command is "
        "concurrency_acquire, replay scheduled %r (TMPRL1100 face)" % (recorded,))
    assert wf._reached_prepare, "run() never reached prepare_workspace"


# ---------- W2: window (a) preserved ----------

def test_w2_window_a_skip_is_exact(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded, start_time=BEFORE_CL1)
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded == [], recorded
    assert wf._reached_prepare


# ---------- W3: window (c) preserved ----------

def test_w3_window_c_marker_wins(monkeypatch):
    for st in (BEFORE_CL1, None):
        recorded = []
        wf = _build(True, monkeypatch, recorded, start_time=st)
        with pytest_stop():
            asyncio.run(wf.run(_inp()))
        assert recorded[:1] == ["concurrency_acquire"], recorded
        assert wf._reached_prepare


# ---------- W4/W5: window (b) through the emitting helpers ----------

def test_w4_window_b_paused_boundary_releases(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded)
    wf._paused = True
    asyncio.run(wf._concurrency_release_if_paused())
    assert "concurrency_release" in recorded, recorded


def test_w5_window_b_blocked_leg_renews(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded)
    asyncio.run(wf._blocked("implement", "blocked why"))
    assert "concurrency_renew" in recorded, recorded


# ---------- W6: boundary ----------

def test_w6_start_time_exactly_at_anchor_gates(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded, start_time=ANCHOR)
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded[:1] == ["concurrency_acquire"], recorded


# ---------- W7: degenerate inputs never raise ----------

def test_w7_degenerate_start_time_falls_back_to_marker(monkeypatch):
    # None / non-datetime: falls back to the patched verdict, no raise.
    for st in (None, "not-a-datetime", 12345):
        recorded = []
        wf = _build(False, monkeypatch, recorded, start_time=st)
        with pytest_stop():
            asyncio.run(wf.run(_inp()))
        assert recorded == [], (st, recorded)
    # Raising info(): same, no raise.
    recorded = []
    wf = _build(False, monkeypatch, recorded, info_raises=True)
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded == [], recorded
    # Naive datetime (no tzinfo): treated as UTC, still compared.
    recorded = []
    wf = _build(False, monkeypatch, recorded,
                start_time=datetime(2026, 10, 5, 12, 0, 0))
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded[:1] == ["concurrency_acquire"], recorded


# ---------- W8: light lane same semantics ----------

def test_w8_light_lane_window_b_gates(monkeypatch):
    recorded = []
    wf = _build(False, monkeypatch, recorded, lane="light")
    with pytest_stop():
        asyncio.run(wf.run(_inp()))
    assert recorded[:1] == ["concurrency_acquire"], recorded
    assert wf._reached_prepare
    # Window (a) on the light lane stays an exact skip.
    recorded2 = []
    wf2 = _build(False, monkeypatch, recorded2, lane="light",
                 start_time=BEFORE_CL1)
    with pytest_stop():
        asyncio.run(wf2.run(_inp()))
    assert recorded2 == [], recorded2


# ---------- W9: static lock ----------

def _src(p):
    return Path(p).read_text(encoding="utf-8")


def test_w9_static_lock_predicate_and_anchor():
    dl = _src(POC / "dev_lane.py")
    ll = _src(POC / "light_lane.py")
    # The anchor literal is pinned: renaming it or moving the instant breaks
    # the per-history determinism contract silently.
    assert 'CL1_GATE_LANDED_AT = datetime(2026, 10, 4, 23, 20, 14, tzinfo=timezone.utc)' in dl
    assert 'CONCURRENCY_GATE_PATCH_ID = "dev-lane-concurrency-gate-v1"' in dl
    assert ('LIGHT_CONCURRENCY_GATE_PATCH_ID = '
            '"light-lane-concurrency-gate-v1"' in ll)
    # Every gate call site reads the predicate (4 dev + 2 light sites).
    for src in (dl, ll):
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "await self._concurrency_gate()" in line:
                window = "\n".join(lines[max(0, i - 4):i + 1])
                assert "_concurrency_gate_active(" in window, (
                    "gate call not behind the replay predicate at line %d"
                    % (i + 1,))
    # Both emitting helpers gate on the predicate, not on bare patched().
    for helper in ("async def _concurrency_release(",
                   "async def _concurrency_renew("):
        idx = dl.index(helper)
        body = dl[idx:idx + 700]
        assert "if not _concurrency_gate_active(" in body, helper
