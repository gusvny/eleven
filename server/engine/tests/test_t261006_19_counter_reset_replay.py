# -*- coding: utf-8 -*-
"""t261006-19 replay compatibility of the t261006-07 counter resets - unit tests.

Incident (KI-212): e9daa05 (t261006-07, 2026-10-06 15:25:58 +0800) added NEW
conflict-counter mutations without a patched() guard - the R3 resets in the
``rework`` / ``retry_qc`` signal handlers and the R2 resets after a successful
settle. A run started before e9daa05 keeps its over-cap counter on replay
(history: main-sync route blocked -> _blocked -> concurrency_renew); a
post-e9daa05 worker fires the signal handler, zeroes the counter, the conflict
route flips to resolve, and the code schedules ``implement`` where history says
``concurrency_renew`` -> deterministic TMPRL1100, workflow task fails forever
(live freeze: t261005-10 run 01a10a77-... / t261006-13 run 01a10ff1-..., their
snapshot queries die with it).

Fix under test (plan rev2): predicate ``_counter_reset_active(wf)`` -
  arm 1 (marker): ``wf.patched(COUNTER_RESET_PATCH_ID)`` -> resets on;
  arm 2 (mandatory window (b)): ``wf.info().start_time >= E9DAA05_LANDED_AT``
  (2026-10-06 07:25:58 UTC, the verified squash instant of e9daa05) -> resets
  on. Every run started after e9daa05 but before this guard carries the resets
  in its history yet no marker, so the marker arm alone would diverge on the
  next code swap. Degenerate ``info()`` falls back to the marker verdict and
  never raises; a naive ``start_time`` is coerced to UTC.
Four gated sites: rework handler, retry_qc handler, settle-success reset in
``_main_sync_before_gate``, settle-success reset in the merge_check path.

Test matrix:
  R1 required regression (RED on pre-fix code): a pre-e9daa05 history
     (prefix recorded: concurrency_renew, from the over-cap blocked wake
     point) replayed on current code - the rework signal does NOT reset the
     counters, so the main-sync conflict route stays blocked and the next
     command the code schedules is still ``concurrency_renew``: the replayed
     command sequence continues the history, no TMPRL1100-class divergence.
  R2 red-proof: the identical scenario with the predicate forced True resets
     the counter, the route flips to resolve, and the next command would be
     ``implement`` - the exact divergence face, documented so unwinding the
     guard is visibly red.
  R3 window (b): patched=False, start after the anchor -> resets still fire.
  R4 marker positive: patched=True -> resets fire regardless of time;
     boundary start_time exactly at the anchor fires; naive start_time
     (no tzinfo) at the anchor fires (UTC coercion).
  R5 malformed inputs: start_time None / non-datetime / raising info() ->
     no raise, marker-verdict fallback (pre-fix: counters untouched).
  R6 static lock: the patch id and anchor literals are pinned, and all four
     gated sites read the predicate (unwinding any one is red).

Zero Temporal / zero network / zero git; the ``workflow`` facade is
monkeypatched (auto-restored) with a stub.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402

ANCHOR = dev_lane.E9DAA05_LANDED_AT
BEFORE_E9DAA05 = ANCHOR - timedelta(hours=20)   # window (a): pre-fix history
AFTER_E9DAA05 = ANCHOR + timedelta(hours=2)     # window (b): post-commit run
CAP = 3
SIG = ["repo:file_a.txt", "repo:file_b.txt"]    # repo-tagged conflict signature


def _stub_workflow(patched_value, start_time, raising_info=False):
    """Minimal workflow facade: only patched() and info() are consumed by the
    predicate and the signal handlers (no activity is executed here)."""
    def info():
        if raising_info:
            raise RuntimeError("degenerate info()")
        return SimpleNamespace(start_time=start_time)
    return SimpleNamespace(patched=lambda pid: patched_value, info=info,
                           now=lambda: datetime(2026, 10, 6, 12, 0, 0,
                                                tzinfo=timezone.utc),
                           logger=SimpleNamespace(info=lambda *a, **k: None,
                                                  warning=lambda *a, **k: None))


def _build(monkeypatch, patched_value, start_time, rounds=CAP + 1,
           raising_info=False):
    """Fresh DevLaneWorkflow instance (bypass __init__) mid-conflict-loop:
    an over-cap counter plus a pending rework - the KI-212 wake shape."""
    stub = _stub_workflow(patched_value, start_time, raising_info)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = "t26100619ut"
    wf.meta = {"status": "dispatched", "log": [], "project": "proj-alpha",
               "stage_state": "running", "stage": "merge_check"}
    wf.timeline = []
    wf._retry_token = 0
    wf._conflict_rounds = rounds
    wf._prev_conflict_files = list(SIG)
    monkeypatch.setattr(wf, "_cross_project_gate", lambda *a, **k: True)
    return wf


def _rework_request():
    return SimpleNamespace(who="human", target_stage="implement",
                           note="KI-212 revive", caller_project="",
                           cross_project_note="")


def _next_command(route: str) -> str:
    """Map the main-sync conflict route to the NEXT activity command the
    workflow code schedules (the replay contract Temporal enforces):
    blocked -> _blocked -> concurrency_renew; resolve -> the implement
    agent activity. TMPRL1100 fires exactly when this differs from the
    history's next event."""
    return "concurrency_renew" if route.startswith("blocked") else "implement"


# ---------- R1: required regression - pre-fix history replays clean ----------

def test_r1_pre_fix_history_replay_no_nondeterminism(monkeypatch):
    """History prefix: ['concurrency_renew'] (the over-cap blocked recorded
    before the wake). Replaying the current code on that history: the rework
    signal must not reset the counters -> route stays blocked -> the next
    command is still concurrency_renew -> sequence continues, no divergence."""
    wf = _build(monkeypatch, patched_value=False, start_time=BEFORE_E9DAA05)
    history = ["concurrency_renew"]

    wf.rework(_rework_request())

    assert wf._conflict_rounds == CAP + 1          # auxiliary: counter survived
    assert wf._prev_conflict_files == SIG
    route = dev_lane.main_sync_conflict_route(
        wf._conflict_rounds, SIG, wf._prev_conflict_files, CAP)
    next_cmd = _next_command(route)
    assert next_cmd == history[-1], (
        "replay diverges: history next=%s, code would schedule %s "
        "(TMPRL1100 face)" % (history[-1], next_cmd))


def test_r1b_retry_qc_pre_fix_history_replay_no_nondeterminism(monkeypatch):
    """Same contract through the retry_qc signal handler (the other R3 site):
    a pre-fix retry_qc wake also leaves the over-cap route blocked."""
    wf = _build(monkeypatch, patched_value=False, start_time=BEFORE_E9DAA05)
    wf.retry_qc(who="human")
    assert wf._conflict_rounds == CAP + 1
    route = dev_lane.main_sync_conflict_route(
        wf._conflict_rounds, SIG, wf._prev_conflict_files, CAP)
    assert _next_command(route) == "concurrency_renew"


# ---------- R2: red-proof - unguarded code produces the divergence ----------

def test_r2_unguarded_code_diverges(monkeypatch):
    """With the predicate forced True (the pre-fix defect shape: resets run
    unguarded), the same wake zeroes the counter, the route flips to resolve,
    and the next command becomes ``implement`` against a history whose next
    event is concurrency_renew - the exact KI-212 divergence, kept red."""
    wf = _build(monkeypatch, patched_value=False, start_time=BEFORE_E9DAA05)
    monkeypatch.setattr(dev_lane, "_counter_reset_active", lambda wf: True)
    wf.rework(_rework_request())
    assert wf._conflict_rounds == 0
    route = dev_lane.main_sync_conflict_route(
        wf._conflict_rounds, SIG, wf._prev_conflict_files, CAP)
    assert _next_command(route) == "implement"


# ---------- R3: window (b) - post-commit runs keep the resets ----------

def test_r3_window_b_time_arm(monkeypatch):
    wf = _build(monkeypatch, patched_value=False, start_time=AFTER_E9DAA05)
    wf.rework(_rework_request())
    assert wf._conflict_rounds == 0
    assert wf._prev_conflict_files == []


# ---------- R4: marker positive + boundaries ----------

def test_r4_marker_arm_overrides_time(monkeypatch):
    wf = _build(monkeypatch, patched_value=True, start_time=BEFORE_E9DAA05)
    wf.rework(_rework_request())
    assert wf._conflict_rounds == 0


def test_r4b_boundary_start_exactly_at_anchor(monkeypatch):
    wf = _build(monkeypatch, patched_value=False, start_time=ANCHOR)
    wf.rework(_rework_request())
    assert wf._conflict_rounds == 0


def test_r4c_naive_start_time_coerced_to_utc(monkeypatch):
    naive = datetime(2026, 10, 6, 7, 25, 58)      # anchor instant, no tzinfo
    wf = _build(monkeypatch, patched_value=False, start_time=naive)
    wf.rework(_rework_request())
    assert wf._conflict_rounds == 0


# ---------- R5: malformed inputs never raise, fall back to the marker ----------

def test_r5_degenerate_info_falls_back(monkeypatch):
    for bad in (None, "not-a-datetime", 12345):
        wf = _build(monkeypatch, patched_value=False, start_time=bad)
        wf.rework(_rework_request())              # must not raise
        assert wf._conflict_rounds == CAP + 1


def test_r5b_raising_info_falls_back(monkeypatch):
    wf = _build(monkeypatch, patched_value=False, start_time=None,
                raising_info=True)
    wf.rework(_rework_request())                  # must not raise
    assert wf._conflict_rounds == CAP + 1


def test_r5c_predicate_direct():
    assert dev_lane._counter_reset_active(
        _stub_workflow(False, None)) is False
    assert dev_lane._counter_reset_active(
        _stub_workflow(False, None, raising_info=True)) is False
    assert dev_lane._counter_reset_active(
        _stub_workflow(True, None)) is True


# ---------- R6: static lock ----------

def test_r6_literals_and_sites_pinned():
    src = (POC / "dev_lane.py").read_text(encoding="utf-8")
    assert 'COUNTER_RESET_PATCH_ID = "t261006-07-counter-reset-v1"' in src
    assert "E9DAA05_LANDED_AT = datetime(2026, 10, 6, 7, 25, 58, " \
        "tzinfo=timezone.utc)" in src
    # exactly the four gated sites read the predicate through the workflow
    # facade (rework handler, retry_qc handler, two settle-success resets)
    assert src.count("if _counter_reset_active(workflow):") == 4
    # the predicate itself reads the constant through the wf argument
    assert src.count("wf.patched(COUNTER_RESET_PATCH_ID)") == 1
    assert "return start >= E9DAA05_LANDED_AT" in src
