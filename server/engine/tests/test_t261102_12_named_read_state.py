#!/usr/bin/env python3
"""t261102-12 L1: the named read states of a finished / unreadable ticket.

Measured defect (host 261101 "the left column shows many inspection tickets as timed out"):
seven inspection period tickets were RUNNING in Temporal but could never answer a
snapshot query — their workflow tasks were in a FAILED state, so the server refused every
read ("Unable to query workflow due to Workflow Task in failed state"). Two engine lies
made that invisible:

  1. the named-cause probe read a queue DERIVED from the ticket id
     (`sandbar-ticket-<id>`), while the execution was polling the shared `sandbar` queue —
     an inspection ticket therefore always "proved" zero live pollers on a queue nobody is
     supposed to poll, and the receipt claimed `no_poller` with a queue that does not
     exist for that ticket;
  2. the deterministic refusal was retried like jitter (3 x 8s) and then dressed as a
     transient timeout, so the row read as a running ticket and the panel re-polled it.

Truth table pinned here:
  A DETECTION - the server wording is matched case-insensitively; any other exception
    (timeout / RPC / a broken __str__) is never mistaken for it.
  B WHICH QUEUE - the queue comes from describe (the execution's own task_queue); the
    id-derived name is only a fallback and the face says which source it used.
  C CLASSIFICATION - a deterministic refusal is kind=workflow_task_failed (deterministic,
    not retryable), NEVER no_poller and NEVER transient, even when a poller face proves
    zero pollers.
  D NO RETRY BUDGET - the deterministic refusal leaves at the FIRST attempt (exactly one
    query call) and consults no poller probe.
  E NO FALSE no_poller ON THE SHARED QUEUE - a ticket on `sandbar` with a live poller there
    is not named no_poller (the pre-fix shape claimed it from the derived queue).
  F RETAINED FACTS - the failure cause comes from the durable history (type + first line);
    an unreadable history is named `retained_unavailable`, never invented, never raised.
  G RETAINED TICKET STATE - a finished ticket whose workflow is gone is answered from the
    post-close witness / archive manifest on disk (no Temporal, no poller); with neither
    present the state is named unavailable.
  H DETAIL FACE - cmd_ticket_query answers kind=workflow_task_failed with the durable
    facts on the face (face_state / queue / queue_source / retained).
  I LIST ROWS - the deterministic inspection row keeps its identity as its title, says
    status/stage_state failed and carries read_state=workflow_task_failed; the generic
    degraded row keeps its legacy title/state and names read_state=query_timeout (the
    t260901-23 pin is not weakened, it is narrowed to the case it was written for).

Offline: no Temporal server, no network, no docker, no console. Handles/clients are stubs.
Run: server/engine/.venv/bin/python -m pytest server/engine/tests/test_t261102_12_named_read_state.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import client as client_mod  # noqa: E402
import shared  # noqa: E402

# retry delays to zero: the degradation paths finish in milliseconds (the production
# defaults are untouched).
client_mod.QUERY_RETRY_BASE_DELAY = 0.0
client_mod.QUERY_RETRY_JITTER = 0.0
client_mod.QUERY_RETRY_MAX_DELAY = 0.0
client_mod.DESCRIBE_BASE_DELAY = 0.0
client_mod.DESCRIBE_RETRY_JITTER = 0.0

WTF_MESSAGE = ("Unable to query workflow due to Workflow Task in failed state.")
_K = client_mod.SearchAttributeKey


def run(coro):
    return asyncio.run(coro)


class WorkflowTaskFailed(Exception):
    """The server's deterministic refusal (message shape = the real RPCError text)."""

    def __init__(self):
        super().__init__(WTF_MESSAGE)


class _BrokenStr(Exception):
    def __str__(self):  # noqa: D105 - deliberate: a face reader must not depend on __str__
        raise RuntimeError("broken __str__")


class _Status:
    def __init__(self, name):
        self.name = name


class _Desc:
    """describe() stub: the execution's own task_queue is the point of this ticket."""

    def __init__(self, status_name="RUNNING", task_queue="sandbar", close_time=None):
        self.status = _Status(status_name)
        self.task_queue = task_queue
        self.close_time = close_time
        self.typed_search_attributes = {}
        self.result_run_id = None
        self.run_id = "run-stub"
        self.history_length = 39


class _Event:
    def __init__(self, failure_type="", message="", event_id=0):
        if failure_type or message:
            class _Info:
                type = failure_type

            class _Failure:
                failure_info = _Info()
                message = None

            _Failure.message = message
            self.workflow_task_failed_event_attributes = type(
                "Attrs", (), {"failure": _Failure})()
            self.event_id = event_id
        else:
            self.workflow_task_failed_event_attributes = None
            self.event_id = event_id


class _History:
    def __init__(self, events):
        self.events = events


class _Handle:
    """One ticket's handle: query() behaviour, describe(), fetch_history()."""

    def __init__(self, behaviour="ok", snap=None, desc=None, history=None,
                 history_raises=False):
        self.behaviour = behaviour
        self.snap = snap if snap is not None else {"meta": {"title": "x"}}
        self._desc = desc if desc is not None else _Desc()
        self._history = history if history is not None else _History([])
        self._history_raises = history_raises
        self.queries = 0
        self.result_run_id = None
        self.run_id = "run-stub"

    async def query(self, name):
        assert name == "snapshot"
        self.queries += 1
        if self.behaviour == "wtf":
            raise WorkflowTaskFailed()
        if self.behaviour == "timeout":
            raise asyncio.TimeoutError("stub timeout")
        return self.snap

    async def describe(self):
        return self._desc

    async def fetch_history(self):
        if self._history_raises:
            raise RuntimeError("history service unavailable")
        return self._history


class _PollerService:
    def __init__(self, pollers_by_queue):
        self._by_queue = pollers_by_queue
        self.probed = []

    async def describe_task_queue(self, request, **kw):
        name = request.task_queue.name
        self.probed.append(name)
        pollers = self._by_queue.get(name, [])

        class _Resp:
            pass

        resp = _Resp()
        resp.pollers = pollers
        return resp


class _Poller:
    def __init__(self, identity):
        self.identity = identity


class _StubClient:
    namespace = "default"

    def __init__(self, pollers_by_queue):
        self.workflow_service = _PollerService(pollers_by_queue)

    def get_workflow_handle(self, tid):
        return _HANDLES.get(tid)


_HANDLES: dict = {}


def _client_with(handles):
    global _HANDLES
    _HANDLES = dict(handles)
    live = _Poller("%d@host" % os.getpid())
    return _StubClient({"sandbar": [live], "sandbar-ticket-t-x": []})


# ---------------------------------------------------------------- A detection

def test_a_detection_truth_table():
    assert client_mod.is_workflow_task_failed_exc(WorkflowTaskFailed()) is True
    assert client_mod.is_workflow_task_failed_exc(
        RuntimeError("unable to query workflow due to workflow task in failed state")) is True
    assert client_mod.is_workflow_task_failed_exc(asyncio.TimeoutError("slow")) is False
    assert client_mod.is_workflow_task_failed_exc(RuntimeError("connection refused")) is False
    assert client_mod.is_workflow_task_failed_exc(Exception("")) is False
    assert client_mod.is_workflow_task_failed_exc(_BrokenStr()) is False


# ---------------------------------------------------------------- B which queue

def test_b_queue_comes_from_describe_then_id():
    assert client_mod.ticket_read_queue(_Desc(task_queue="sandbar"), "t-1") == (
        "sandbar", "describe")
    assert client_mod.ticket_read_queue(_Desc(task_queue=""), "t-1") == (
        client_mod.ticket_task_queue("t-1"), "derived")
    assert client_mod.ticket_read_queue(None, "t-1") == (
        client_mod.ticket_task_queue("t-1"), "derived")


# ---------------------------------------------------------------- C classification

def test_c_deterministic_is_named_and_never_no_poller():
    zero_face = {"available": True, "live_pollers": 0, "queue": "sandbar",
                 "stale_history": 0, "unverifiable": 0}
    receipt = client_mod._classify_snapshot_failure(
        WorkflowTaskFailed(), "t-1", "sandbar", zero_face, "describe")
    assert receipt["kind"] == client_mod.KIND_WORKFLOW_TASK_FAILED
    assert receipt["kind"] != client_mod.KIND_NO_POLLER
    assert receipt["kind"] != client_mod.KIND_TRANSIENT
    assert "deterministic" in receipt["error"]
    face = receipt["face"]
    assert face["deterministic"] is True and face["retryable"] is False
    assert face["queue"] == "sandbar" and face["queue_source"] == "describe"
    assert face["face_state"] == client_mod.KIND_WORKFLOW_TASK_FAILED


# ---------------------------------------------------------------- D no retry budget

def test_d_deterministic_leaves_at_the_first_attempt_and_probes_no_queue():
    handle = _Handle(behaviour="wtf", desc=_Desc(task_queue="sandbar"))
    stub = _client_with({"t-1": handle})
    snap, receipt = run(client_mod._snapshot_read_named(
        handle, "t-1", stub, timeout=0.2, desc=handle._desc))
    assert snap is None
    assert receipt["kind"] == client_mod.KIND_WORKFLOW_TASK_FAILED
    assert handle.queries == 1, "a deterministic refusal must not spend the retry budget"
    assert stub.workflow_service.probed == [], (
        "no poller probe for a failed workflow task: a live poller cannot help")


# ---------------------------------------------------------------- E shared queue

def test_e_live_poller_on_the_real_queue_is_not_named_no_poller():
    # The pre-fix shape: the ticket runs on the shared queue, nobody polls the id-derived
    # queue -> a false no_poller. Now the real queue has a live poller, so the read keeps
    # the legacy transient path (it is re-raised to the caller's own wording).
    handle = _Handle(behaviour="timeout", desc=_Desc(task_queue="sandbar"))
    stub = _client_with({"t-2": handle})
    raised = None
    try:
        run(client_mod._snapshot_read_named(handle, "t-2", stub, timeout=0.05,
                                           desc=handle._desc))
    except Exception as e:  # noqa: BLE001 - the legacy transient raise is the expected path
        raised = e
    assert raised is not None, "a live poller on the real queue must not become no_poller"
    assert stub.workflow_service.probed == ["sandbar"], (
        "the probe must read the queue the execution polls")


def test_e_no_poller_names_the_real_queue():
    handle = _Handle(behaviour="timeout", desc=_Desc(task_queue="sandbar-ticket-t-3"))
    stub = _client_with({"t-3": handle})
    _, receipt = run(client_mod._snapshot_read_named(
        handle, "t-3", stub, timeout=0.05, desc=handle._desc))
    assert receipt["kind"] == client_mod.KIND_NO_POLLER
    assert receipt["face"]["queue"] == "sandbar-ticket-t-3"
    assert receipt["face"]["queue_source"] == "describe"


# ---------------------------------------------------------------- F retained facts

def test_f_failure_cause_is_read_from_the_history():
    hist = _History([_Event("RestrictedWorkflowAccessError",
                            "Cannot access os.path.join from inside a workflow.\nsecond line",
                            event_id=36)])
    facts = run(client_mod.workflow_task_failure_facts(_Handle(history=hist), timeout=0.5))
    assert facts["available"] is True
    assert facts["failure_type"] == "RestrictedWorkflowAccessError"
    assert "os.path.join" in facts["failure_message"]
    assert "\n" not in facts["failure_message"], "one line only, never a stack trace"
    assert facts["event_id"] == 36


def test_f_unreadable_history_is_named_unavailable():
    facts = run(client_mod.workflow_task_failure_facts(
        _Handle(history_raises=True), timeout=0.5))
    assert facts["available"] is False
    assert "history unreadable" in facts["reason"]


def test_f_history_without_the_event_names_that():
    facts = run(client_mod.workflow_task_failure_facts(_Handle(), timeout=0.5))
    assert facts["available"] is False
    assert "no WorkflowTaskFailed event" in facts["reason"]


# ---------------------------------------------------------------- G retained ticket

# Retained for the life of the process so the temp projects root is reclaimed on exit
# (L8 tmp-dir hygiene: one reclaim verb per mkdtemp site).
_TMP_DIRS: list = []


def _tmp_projects_root():
    tmp = tempfile.TemporaryDirectory(prefix="t261102-12-projects-")
    _TMP_DIRS.append(tmp)
    return tmp.name


def test_g_closed_witness_is_the_retained_answer(monkeypatch):
    root = _tmp_projects_root()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", root)
    res = shared.write_closed_witness("sandbar", "t-9", "completed",
                                      "engine:client.ticket-close-out",
                                      workflow_id="t-9", observed_by="test")
    assert res.get("written") is True, res
    face = client_mod.retained_ticket_face("t-9")
    assert face["face_state"] == client_mod.FACE_STATE_RETAINED
    assert face["project"] == "sandbar"
    assert face["terminal_status"].upper() == "COMPLETED"
    assert face["source"].endswith(shared.CLOSED_WITNESS_FILE)


def test_g_archive_manifest_is_a_retained_answer_too(monkeypatch):
    root = _tmp_projects_root()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", root)
    tdir = Path(root) / "sandbar" / "data" / "tickets" / "t-10"
    tdir.mkdir(parents=True)
    (tdir / "archive.json").write_text(json.dumps({
        "schema": "v1", "ticket_id": "t-10", "legacy": False,
        "archived_at": "2026-11-01T00:15:21+00:00",
        "meta": {"title": "Closed inspection row", "epic": "sandbar-core",
                 "project": "sandbar"},
    }), encoding="utf-8")
    face = client_mod.retained_ticket_face("t-10")
    assert face["face_state"] == client_mod.FACE_STATE_RETAINED
    assert face["title"] == "Closed inspection row"
    assert face["epic"] == "sandbar-core"
    assert face["archived_at"].startswith("2026-11-01")


def test_g_no_retained_state_is_named(monkeypatch):
    root = _tmp_projects_root()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", root)
    (Path(root) / "sandbar" / "data" / "tickets").mkdir(parents=True)
    face = client_mod.retained_ticket_face("t-404")
    assert face["face_state"] == client_mod.FACE_STATE_RETAINED_UNAVAILABLE
    assert "no retained state" in face["reason"]


def test_g_malformed_id_never_raises(monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", _tmp_projects_root())
    face = client_mod.retained_ticket_face("../etc/passwd")
    assert face["face_state"] == client_mod.FACE_STATE_RETAINED_UNAVAILABLE
    assert "malformed ticket id" in face["reason"]


# ---------------------------------------------------------------- H detail face

def test_h_detail_receipt_names_the_state_and_carries_durable_facts():
    hist = _History([_Event("RestrictedWorkflowAccessError", "Cannot access os.path.join",
                            event_id=36)])
    handle = _Handle(behaviour="wtf", desc=_Desc(task_queue="sandbar"), history=hist)
    stub = _client_with({"t-11": handle})

    async def _connect(*a, **k):
        return stub

    old = client_mod._connect
    client_mod._connect = _connect
    try:
        receipt = run(client_mod.cmd_ticket_query({"ticket_id": "t-11"}))
    finally:
        client_mod._connect = old
    assert receipt["ok"] is False
    assert receipt["kind"] == client_mod.KIND_WORKFLOW_TASK_FAILED
    assert "deterministic" in receipt["error"]
    assert "transient" in receipt["error"]  # it says what it is NOT, by name
    face = receipt["face"]
    assert face["face_state"] == client_mod.KIND_WORKFLOW_TASK_FAILED
    durable = face["durable"]
    assert durable["queue"] == "sandbar" and durable["queue_source"] == "describe"
    assert durable["deterministic"] is True and durable["retryable"] is False
    assert durable["retained"]["available"] is True
    assert durable["retained"]["failure_type"] == "RestrictedWorkflowAccessError"


def test_h_closed_ticket_reads_without_any_poller():
    """The closed direction of the promise: a COMPLETED ticket is answered from the
    workflow's own return value — no snapshot query, so no poller is needed at all."""
    class _NoQueryHandle(_Handle):
        async def query(self, name):
            raise AssertionError("a closed ticket must be read without a snapshot query")

        async def result(self):
            return {"meta": {"title": "closed row", "status": "closed"}}

    handle = _NoQueryHandle(desc=_Desc(status_name="COMPLETED"))
    stub = _client_with({"t-12": handle})

    async def _connect(*a, **k):
        return stub

    old = client_mod._connect
    client_mod._connect = _connect
    try:
        receipt = run(client_mod.cmd_ticket_query({"ticket_id": "t-12"}))
    finally:
        client_mod._connect = old
    assert receipt["ok"] is True, receipt
    assert receipt["result"]["exec_status"] == "COMPLETED"
    assert handle.queries == 0, "no poller-dependent read for a closed ticket"


def test_h_closed_read_failure_carries_the_retained_record(monkeypatch):
    """When the workflow's return value cannot be read, the receipt still names the
    ticket's outcome from the retained record (never a bare "refresh and retry")."""
    root = _tmp_projects_root()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", root)
    shared.write_closed_witness("sandbar", "t-13", "completed",
                               "engine:client.ticket-close-out",
                               workflow_id="t-13", observed_by="test")

    class _ResultFails(_Handle):
        async def result(self):
            raise RuntimeError("result stream unavailable")

    handle = _ResultFails(desc=_Desc(status_name="COMPLETED"))
    stub = _client_with({"t-13": handle})

    async def _connect(*a, **k):
        return stub

    old = client_mod._connect
    client_mod._connect = _connect
    try:
        receipt = run(client_mod.cmd_ticket_query({"ticket_id": "t-13"}))
    finally:
        client_mod._connect = old
    assert receipt["ok"] is False
    face = receipt["face"]
    assert face["face_state"] == client_mod.FACE_STATE_RETAINED
    assert face["retained"]["terminal_status"].upper() == "COMPLETED"
    assert face["retained"]["closed_at"] != ""


# ---------------------------------------------------------------- I list rows

class _ListWf:
    def __init__(self, tid, status_name, task_queue, kv, close_time=None,
                 start_time=None, workflow_type="InspectionPeriodicWorkflow"):
        self.id = tid
        self.status = _Status(status_name)
        self.task_queue = task_queue
        self.close_time = close_time
        self.start_time = start_time
        self.workflow_type = workflow_type
        self.typed_search_attributes = _SA(kv)


class _SA:
    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        return self.kv.get(str(key))


class _ListClient(_StubClient):
    def __init__(self, wfs, handles):
        live = _Poller("%d@host" % os.getpid())
        super().__init__({"sandbar": [live]})
        self._wfs = wfs
        global _HANDLES
        _HANDLES = dict(handles)

    def get_workflow_handle(self, tid):
        return _HANDLES.get(tid) or _Handle()

    async def list_workflows(self, filter_str):
        for w in self._wfs:
            if 'WorkflowType="%s"' % w.workflow_type not in filter_str:
                continue
            yield w


def _run_list(wfs, handles, monkeypatch, kind="inspection"):
    stub = _ListClient(wfs, handles)

    async def _connect(*a, **k):
        return stub

    monkeypatch.setattr(client_mod, "_connect", _connect)
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", _tmp_projects_root())
    return run(client_mod.cmd_ticket_list({"kind": kind}))


def _row(res, tid):
    for r in ((res or {}).get("result") or {}).get("tickets") or []:
        if r.get("id") == tid:
            return r
    return None


def _sa(inst, per):
    return {str(_K.for_keyword(client_mod.INSPECTION_INSTANCE_SA_NAME)): inst}


def test_i_deterministic_inspection_row_is_named(monkeypatch):
    hist = _History([_Event("RestrictedWorkflowAccessError", "Cannot access os.path.join",
                            event_id=36)])
    wf = _ListWf("t261101-25", "RUNNING", "sandbar",
                 _sa("integration-tests", "20261101"))
    handle = _Handle(behaviour="wtf", desc=_Desc(task_queue="sandbar"), history=hist)
    res = _run_list([wf], {"t261101-25": handle}, monkeypatch)
    row = _row(res, "t261101-25")
    assert row is not None, "the row must stay on the board (never silently dropped)"
    assert row["read_state"] == client_mod.KIND_WORKFLOW_TASK_FAILED
    assert row["status"] == "failed" and row["stage_state"] == "failed"
    assert "integration-tests" in row["title"], "the identity stays reachable as the name"
    assert "\u5237\u65b0\u91cd\u8bd5" not in row["title"], "the legacy retry-instruction title must not reach the deterministic row"
    assert "timed out" not in row["title"]
    assert "deterministic" in row["read_state_note"]
    assert "RestrictedWorkflowAccessError" in row["read_state_note"]
    assert handle.queries == 1


def test_i_generic_degraded_row_keeps_its_legacy_shape(monkeypatch):
    # The t260901-23 pin is NOT weakened: a genuine timeout of an unreadable ticket keeps
    # the legacy title/state; the new key only names which read state it was.
    wf = _ListWf("t261101-99", "RUNNING", "sandbar",
                 _sa("integration-tests", "20261101"))
    handle = _Handle(behaviour="timeout", desc=_Desc(task_queue="sandbar-ticket-t261101-99"))
    res = _run_list([wf], {"t261101-99": handle}, monkeypatch)
    row = _row(res, "t261101-99")
    assert row is not None
    assert row["read_state"] == client_mod.KIND_NO_POLLER
    assert "0 live pollers" in row["read_state_note"], row["read_state_note"]
    assert "sandbar-ticket-t261101-99" in row["read_state_note"]
    assert row["status"] == "dispatched" and row["stage_state"] == "running"
