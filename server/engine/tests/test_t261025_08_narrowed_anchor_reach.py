"""t261025-08 (KI-356) unit battery: the narrowed landing anchor must be
REACHABLE for a long-lived IN-FLIGHT lane, not only for fresh executions.

Root cause pinned in the plan: temporalio memoizes the first
`workflow.patched()` verdict per workflow-instance object
(`_patches_memoized`, allocated once at `WorkflowInstanceImpl.__init__`),
so a lane whose first evaluation of `KI350_NARROWED_FACE_PATCH_ID` happened
while replaying pre-KI-350 history reads False forever — its green targeted
gate rounds never refresh `meta.last_green_run` (measured: t261022-14 face
stuck at ran=90, t261022-12 at ran=0, both gates green). The fix is an
EVENT-GATED enable: the new `enable_narrowed_anchor` signal (a name that
cannot exist in pre-fix history) sets `_narrowed_anchor_enabled`, and the
recorder takes the narrowed arm on `patched(...) OR enabled`.

Layers pinned here:
  a. recorder, un-patched + NOT enabled + green targeted round → nothing
     (byte-identical old replay leg);
  b. recorder, un-patched + ENABLED + green targeted round → the narrowed face
     `{"ran": N, "narrowed": True, "sha", "at"}` on the current lane HEAD;
  c. enabled + red / failed / errored / blockers / zero-run / malformed
     receipts → nothing (fail-closed, same faces as the patched arm);
  d. enabled + `lane_head_sha` activity failure (both the raise and the
     ok=False shape) → no face + `green_run_note` (the fail-closed branch);
  e. signal handler idempotence + payload tolerance: re-delivery changes
     nothing; a malformed/foreign payload never crashes;
  f. full-round arm unchanged under the enable (no narrowed marker);
  g. merge-side regression re-assert: a stale narrowed face refuses BY NAME
     and names the run that would satisfy it (acceptance item 3);
  h. wiring parity: the client helper and the workflow class share one signal
     name; the workflow class really declares the handler and the recorder
     really reads the enable flag (source lock).

Run: server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261025_08_narrowed_anchor_reach.py -q
"""
import asyncio
import inspect
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import shared  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
KI350 = dev_lane.KI350_NARROWED_FACE_PATCH_ID


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


class _StubWf:
    ki220 = True
    ki350 = True
    result = {"ok": True, "sha": SHA}

    @staticmethod
    def patched(pid):
        return _StubWf.ki220 if pid != KI350 else _StubWf.ki350

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        res = _StubWf.result
        if isinstance(res, Exception):
            raise res
        return res


def _stub_self(meta=None, enabled=False):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = meta if meta is not None else {}
    wf.ticket_id = "t261025-08"
    wf._narrowed_anchor_enabled = enabled
    wf._log = lambda *a, **k: None
    wf._touch = lambda *a, **k: None
    wf._now_epoch = lambda: 1234
    return wf


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    _StubWf.ki220 = True
    _StubWf.ki350 = True
    _StubWf.result = {"ok": True, "sha": SHA}
    yield
    _StubWf.ki220 = True
    _StubWf.ki350 = True
    _StubWf.result = {"ok": True, "sha": SHA}


# ---------------- a. un-patched, un-enabled: byte-identical old replay --------

def test_unpatched_unenabled_green_targeted_records_nothing(stubbed):
    _StubWf.ki350 = False
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=3), True))
    assert "last_green_run" not in wf.meta
    assert "green_run_note" not in wf.meta


# ---------------- b. un-patched, ENABLED: the narrowed face records ------------

def test_enabled_unpatched_green_targeted_records_narrowed_face(stubbed):
    _StubWf.ki350 = False
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"}, enabled=True)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=3), True))
    face = wf.meta["last_green_run"]
    assert face == {"ran": 3, "narrowed": True, "sha": SHA, "at": 1234}


def test_enabled_patched_still_records_narrowed_face(stubbed):
    # the two enable legs are OR-ed; the patched leg must keep working
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"}, enabled=True)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=5), True))
    assert wf.meta["last_green_run"]["narrowed"] is True


# ---------------- c. enabled but fail-closed shapes ----------------------------

def test_enabled_fail_closed_shapes_record_nothing(stubbed):
    _StubWf.ki350 = False
    for receipt in (_Receipt(ran=3, failed=1),          # failed
                    _Receipt(ran=3, error="boom"),      # errored
                    _Receipt(ran=3, blockers=["x"]),    # blockers
                    _Receipt(ran=0),                    # zero-run targeted
                    _Receipt(ran="x")):                 # malformed ran
        wf = _stub_self(meta={}, enabled=True)
        asyncio.run(wf._ki220_record_green_run(receipt, True))
        assert "last_green_run" not in wf.meta
        assert "green_run_note" not in wf.meta


# ---------------- d. enabled + lane_head_sha failure: fail closed + note -------

def test_enabled_sha_failure_note(stubbed):
    _StubWf.ki350 = False
    _StubWf.result = {"ok": False, "sha": "", "error": "rev-parse boom"}
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"}, enabled=True)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=3), True))
    assert "last_green_run" not in wf.meta
    note = wf.meta["green_run_note"]
    assert note["recorded"] is False and "rev-parse boom" in note["error"]


def test_enabled_sha_activity_raise_note(stubbed):
    _StubWf.ki350 = False
    _StubWf.result = RuntimeError("activity gone")
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"}, enabled=True)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=3), True))
    assert "last_green_run" not in wf.meta
    assert wf.meta["green_run_note"]["recorded"] is False


# ---------------- e. signal handler: idempotence + payload tolerance -----------

def test_signal_handler_enables_once_and_is_idempotent():
    wf = _stub_self(meta={})
    wf._now_iso = lambda: "2026-10-25T00:00:00+00:00"
    wf._touch = lambda: None
    handler = dev_lane.DevLaneWorkflow.enable_narrowed_anchor.__get__(wf)
    handler("steward-a")
    assert wf._narrowed_anchor_enabled is True
    note = wf.meta["narrowed_anchor_note"]
    assert note["enabled"] is True and note["who"] == "steward-a"
    wf.meta["narrowed_anchor_note"]["who"] = "untouched"
    handler("steward-b")  # re-delivery changes nothing
    assert wf._narrowed_anchor_enabled is True
    assert wf.meta["narrowed_anchor_note"]["who"] == "untouched"


def test_signal_handler_tolerates_malformed_payload():
    wf = _stub_self(meta={})
    wf._now_iso = lambda: "x"
    wf._touch = lambda: None
    handler = dev_lane.DevLaneWorkflow.enable_narrowed_anchor.__get__(wf)
    handler()                 # absent payload
    handler(None)             # null payload
    handler({"who": 7})       # foreign shape
    assert wf._narrowed_anchor_enabled is True


# ---------------- f. the full-round arm is unchanged under the enable ----------

def test_enabled_full_round_face_carries_no_narrowed_marker(stubbed):
    _StubWf.ki350 = False
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"}, enabled=True)
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=7), False))
    face = wf.meta["last_green_run"]
    assert face["ran"] == 7 and "narrowed" not in face


# ---------------- g. merge side: stale refusal names the satisfying run --------

def test_stale_narrowed_face_refusal_names_the_satisfying_run():
    it = shared.green_run_check_item(
        {"sha": OTHER, "ran": 3, "narrowed": True, "at": 1234}, SHA)
    assert it["green"] is False and it["reason_code"] == "stale"
    # names the recorded sha, the tree to merge, and WHICH run re-anchors
    assert OTHER[:12] in it["detail"] and SHA[:12] in it["detail"]
    assert "green gate round" in it["detail"]


def test_fresh_narrowed_face_on_current_head_is_green_by_name():
    it = shared.green_run_check_item(
        {"sha": SHA, "ran": 3, "narrowed": True, "at": 1234}, SHA)
    assert it["green"] is True and it["reason_code"] == "narrowed"
    assert "NOT a full close" in it["detail"]


# ---------------- h. wiring parity / source lock --------------------------------

def test_signal_name_parity_between_client_and_dev_lane():
    import client  # engine client module (import builds no connection)
    assert client.ENABLE_NARROWED_ANCHOR_SIGNAL == \
        dev_lane.ENABLE_NARROWED_ANCHOR_SIGNAL


def test_workflow_class_declares_the_enable_handler():
    assert hasattr(dev_lane.DevLaneWorkflow, "enable_narrowed_anchor")


def test_recorder_source_reads_the_enable_flag():
    # source lock: the narrowed arm is reachable via the event-gated enable,
    # not only via the poisoned patch gate
    src = inspect.getsource(dev_lane.DevLaneWorkflow._ki220_record_green_run)
    assert "_narrowed_anchor_enabled" in src
    assert "KI350_NARROWED_FACE_PATCH_ID" in src
