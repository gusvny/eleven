"""t261011-17: registration-surface guards + green-run-face miss observability.

Root cause this ticket fixes: the develop-buffer landing path activities
(lane_head_sha / land_to_line / certification_wait) were decorated and executed
but never registered on the worker — a missing registration only surfaces at
runtime, and the green-run-face miss was swallowed into a single log line.

Layers pinned here:
  ① registration — lane_head_sha / land_to_line / certification_wait are members
    of the COMPOSED worker table (worker.compose_worker_activities()), not of any
    single list.
  ② activity guard — every @activity.defn importable under server/engine is in
    the composed table or on a NAMED exemption list with a reason. Exemption
    class: self-check stubs (never dispatched on the production queue). The
    vestigial inspection_period_identity decorator was dropped (t261011-17
    rework) instead of exempted — a production module is not a selfcheck stub.
  ③ workflow guard — same shape for @workflow.defn versus the composed workflow
    registry (ALL_WORKFLOWS + ALL_WORKFLOWS_V2, not a single list).
  ④ negative control — a synthetic defn inside THIS test module proves the
    guard fires (it is unregistered and unexempt by construction; production
    code is never left unregistered to keep the guard red).
  ⑤ malformed input — a callable without the temporal attribute falls back to
    __name__ (worker.activity_registered_name contract); a non-mapping activity
    result is caught by the existing except path, not crashed on.
  ⑥ green-run-face note — both failure exits of dev_lane._ki220_record_green_run
    leave a machine-readable meta["green_run_note"] beside the log line; the
    success path records the face AND clears a stale note; no patch => inert.

Run: server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261011_17_registration_guard.py -q
"""
import asyncio
import contextlib
import importlib
import io
import os
import pkgutil
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import workflows  # noqa: E402
import workflows_v2  # noqa: E402
import worker  # noqa: E402

SHA = "a" * 40


# ---------------- shared scan helpers ----------------

#: Modules that SystemExit on import: they are self-check SCRIPTS (run by
#: selfcheck_scan / by hand), never imported by the worker; the guard skips them
#: by name and the skip is asserted so it cannot silently grow.
SYSTEMEXIT_ON_IMPORT = {
    "selfcheck_integ_loop",
    "selfcheck_scan",
    "selfcheck_stage_prompt",
    "selfcheck_write_lifecycle",
}


def _import_engine_modules():
    """Import every top-level module under server/engine except tests/ and the
    named SystemExit scripts; import output is silenced per module. Yields
    (module_name, module)."""
    for m in sorted(x.name for x in pkgutil.iter_modules([str(POC)])
                    if not x.name.startswith("_")):
        if m == "tests" or m in SYSTEMEXIT_ON_IMPORT:
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield m, importlib.import_module(m)


def _composed_activity_names():
    return {worker.activity_registered_name(a)
            for a in worker.compose_worker_activities()}


def _composed_workflow_names():
    reg = list(workflows.ALL_WORKFLOWS) + list(workflows_v2.ALL_WORKFLOWS_V2)
    return {getattr(w, "__temporal_workflow_definition").name for w in reg}


#: (module, defn name) -> reason. Judged against the COMPOSED table, so a defn
#: that leaves a registered list still fails the guard even if its old list
#: entry lingers in some other constant.
ACTIVITY_EXEMPT = {
    # Self-check stubs: zero-IO activity stand-ins for offline self-check runs;
    # they re-use production defn NAMES but are never dispatched on the
    # production queue, so they must not (and cannot) join the composed table.
    ("selfcheck_ki061_wake_reset", "*"): "self-check stubs (stub*), offline "
    "self-check run only, never dispatched on the production queue",
    ("selfcheck_t260916_19_join_escape", "*"): "self-check stubs (stub*), "
    "offline self-check run only, never dispatched on the production queue",
    ("selfcheck_graceful_stop_probe", "guarded_probe"): "self-check probe "
    "activity, guarded offline probe only (same stub class as the two above)",
    ("selfcheck_worker_graceful_stop", "guarded_probe"): "self-check probe "
    "activity, guarded offline probe only (same stub class; found by this "
    "ticket's scan, named here rather than exempted silently)",
    # inspection_period_identity is NOT exempted: its vestigial decorator was
    # dropped (t261011-17 rework), so it left the defn surface entirely — the
    # guard proves it structurally instead.
}

WORKFLOW_EXEMPT = {
    ("selfcheck_graceful_stop_probe", "ProbeWorkflow"): "self-check probe "
    "workflow for graceful-stop drills, never registered on the production "
    "worker",
    ("selfcheck_worker_graceful_stop", "ProbeWorkflow"): "self-check probe "
    "workflow for worker graceful-stop drills, never registered on the "
    "production worker",
}


# ---------------- ① the fix: three develop-buffer activities registered ----------------

def test_develop_buffer_landing_activities_registered():
    names = _composed_activity_names()
    for n in ("lane_head_sha", "land_to_line", "certification_wait"):
        assert n in names, \
            "%s missing from the composed worker table (develop-buffer " \
            "landing path unservable, the t261011-17 root cause)" % n


# ---------------- ② activity guard ----------------

def test_activity_guard_all_engine_defns_composed_or_exempt():
    missing = []
    for mname, mod in _import_engine_modules():
        for name in dir(mod):
            obj = getattr(mod, name)
            d = getattr(obj, "__temporal_activity_definition", None)
            if d is None:
                continue
            dn = getattr(d, "name", None) or name
            if dn in _composed_activity_names():
                continue
            if any((mname, pat) in ACTIVITY_EXEMPT
                   for pat in (dn, "*")):
                continue
            missing.append((mname, name, dn))
    assert not missing, (
        "unregistered @activity.defn under server/engine — register it in the "
        "composed worker table or add a NAMED exemption with a reason "
        "(a missing registration only surfaces at runtime): %r" % missing)


def test_exemption_skip_list_is_exhaustive():
    """Every module the guard skips for SystemExit-on-import must be a
    selfcheck_* script — the skip list cannot silently swallow new modules."""
    for m in sorted(x.name for x in pkgutil.iter_modules([str(POC)])
                    if not x.name.startswith("_")):
        if m == "tests" or m in SYSTEMEXIT_ON_IMPORT:
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(buf):
                importlib.import_module(m)
        except SystemExit:
            raise AssertionError(
                "module %s SystemExits on import but is not on the guard's "
                "named skip list — add it by name with a reason" % m)


# ---------------- ③ workflow guard ----------------

def test_workflow_guard_all_engine_defns_registered_or_exempt():
    missing = []
    reg = _composed_workflow_names()
    for mname, mod in _import_engine_modules():
        for name in dir(mod):
            obj = getattr(mod, name)
            d = getattr(obj, "__temporal_workflow_definition", None)
            if d is None:
                continue
            dn = getattr(d, "name", None) or name
            if dn in reg:
                continue
            if (mname, name) in WORKFLOW_EXEMPT:
                continue
            missing.append((mname, name, dn))
    assert not missing, (
        "unregistered @workflow.defn under server/engine — add it to the "
        "composed workflow registry (ALL_WORKFLOWS + ALL_WORKFLOWS_V2) or add "
        "a NAMED exemption with a reason: %r" % missing)


# ---------------- ④ negative control (synthetic, in-test only) ----------------

def test_guard_fires_on_synthetic_unregistered_defn():
    from temporalio import activity as tactivity

    @tactivity.defn
    async def synthetic_unregistered(args) -> dict:  # pragma: no cover
        return {}

    dn = worker.activity_registered_name(synthetic_unregistered)
    assert dn not in _composed_activity_names()
    assert not any((m, pat) in ACTIVITY_EXEMPT
                   for m, _ in [("tests", None)]
                   for pat in (dn, "*")), \
        "synthetic defn must not be exemptable by module wildcard"


# ---------------- ⑤ malformed input ----------------

def test_registered_name_falls_back_for_attributeless_callable():
    def plain_fn(args):  # pragma: no cover
        return {}

    assert worker.activity_registered_name(plain_fn) == "plain_fn"
    assert worker.activity_registered_name(42) == "42"


# ---------------- ⑥ green-run-face note (stubbed facade) ----------------

class _StubWf:
    flag = True          # workflow.patched result
    result = {"ok": True, "sha": SHA}

    @staticmethod
    def patched(_pid):
        return _StubWf.flag

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        res = _StubWf.result
        if isinstance(res, BaseException):
            raise res
        return res


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


def _stub_self(meta=None):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = meta if meta is not None else {}
    wf._blocked_sink = []

    async def _blocked(step_id, why):
        wf._blocked_sink.append((step_id, why))

    wf._blocked = _blocked
    wf.ticket_id = "t261011-17"
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1234
    return wf


@pytest.fixture
def gated_true(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    _StubWf.flag = True
    _StubWf.result = {"ok": True, "sha": SHA}
    yield


def test_note_written_when_activity_raises(gated_true):
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    _StubWf.result = ActivityErrorStub()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    assert "last_green_run" not in wf.meta
    note = wf.meta["green_run_note"]
    assert note["face"] == "green_run" and note["recorded"] is False
    assert note["reason"] == "lane_head_sha activity failed"
    assert "ActivityErrorStub" in note["error"] and note["at"] == 1234


def test_note_written_when_head_sha_fails(gated_true):
    wf = _stub_self()
    _StubWf.result = {"ok": False, "sha": "", "error": "rev-parse boom"}
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=2), False))
    note = wf.meta["green_run_note"]
    assert note["reason"] == "lane_head_sha returned failure"
    assert note["error"] == "rev-parse boom"


def test_malformed_activity_result_caught_not_crashing(gated_true):
    wf = _stub_self()
    _StubWf.result = ["not", "a", "mapping"]
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=1), False))
    assert "last_green_run" not in wf.meta
    assert wf.meta["green_run_note"]["reason"] == \
        "lane_head_sha activity failed"


def test_success_records_face_and_clears_stale_note(gated_true):
    wf = _stub_self(meta={"green_run_note": {"stale": True}})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    assert wf.meta["last_green_run"]["sha"] == SHA
    assert "green_run_note" not in wf.meta


def test_inert_without_patch(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    _StubWf.flag = False
    _StubWf.result = {"ok": False, "sha": "", "error": "boom"}
    wf = _stub_self()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=2), False))
    assert "last_green_run" not in wf.meta
    assert "green_run_note" not in wf.meta


class ActivityErrorStub(Exception):
    """Named stand-in for ActivityError: no temporalio runtime in unit tests."""
