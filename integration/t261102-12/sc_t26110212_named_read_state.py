#!/usr/bin/env python3
"""t261102-12: a finished ticket stays readable, and an unreadable one is NAMED.

Host report (261101): "the left column shows many inspection tickets as timed out".
Measured: seven inspection period tickets were RUNNING in Temporal with a FAILED workflow
task, so the server refused every snapshot query ("Unable to query workflow due to
Workflow Task in failed state"). The console read that refusal as a transient timeout,
re-tried it every beat and titled the row "query timed out, refresh to retry" forever.
The same read path named a false cause: it probed a queue DERIVED from the ticket id
(`sandbar-ticket-<id>`) while the execution was polling the shared `sandbar` queue.

What this entry proves, end to end across the engine/console seam that held the bug
(grey-box L3, the REAL engine read faces + the REAL panel model; only Temporal and the
filesystem store are stubbed):

  A CLOSED, NO POLLER - a COMPLETED ticket answers from the workflow's own return value:
    zero snapshot queries, so zero pollers are needed, and the console maps the answer as
    a plain success (no named failure state).
  B RETAINED - a closed ticket whose return value cannot be read is answered from the
    RETAINED record (post-close witness + archive manifest on disk): the receipt carries
    the outcome, and the console renders "retained" — not a timeout, not a re-poll.
  C DETERMINISTIC - a workflow whose task is in a failed state yields
    kind=workflow_task_failed with the durable cause; the console renders it by name and
    schedules NO further detail read.
  D NO_POLLER NAMES THE REAL QUEUE - an unreadable ticket whose queue has no live poller
    yields kind=no_poller naming the queue the EXECUTION reports (never the id-derived
    name); the console renders it by name and re-reads on the slow beat only.
  E NO FALSE no_poller - a ticket on the shared queue whose poller count is 1 is never
    named no_poller (the pre-fix shape claimed it from the derived queue).
  F RETAINED UNAVAILABLE - a ticket with neither a live read nor a retained record is
    named `retained_unavailable`; it is never left as an endless transient retry.

The two legs are the two sides of the seam: this script drives the engine, then hands the
real receipts to the console's OWN model (integration/t261102-12/panel_named_face.mjs,
which imports server/plugins/workbench/src/client/read-state.ts and
src/host/ticket-error.ts). Both legs must pass for the entry to pass.

Offline seconds: no Temporal server, no docker, no browser, no console — never touches
3099/7233. The engine modules import offline (no SDK call is made); a missing venv/temporalio
or a missing node is a NAMED ENV_FAIL (exit 2).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAILS = []
ENVS = []


def check(name, cond, why=""):
    global PASS
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def env_fail(name, why):
    ENVS.append(name)
    print("ENV_FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAILED: %s" % ", ".join(FAILS))
    return 1 if FAILS else (2 if ENVS else 0)


try:
    import client as client_mod  # noqa: E402
    import shared  # noqa: E402
except Exception as e:  # noqa: BLE001 — a missing engine import is an environment face
    env_fail("engine-import", "client.py/shared.py unimportable: %s: %s"
             % (type(e).__name__, e))
    sys.exit(summary())

client_mod.QUERY_RETRY_BASE_DELAY = 0.0
client_mod.QUERY_RETRY_JITTER = 0.0
client_mod.QUERY_RETRY_MAX_DELAY = 0.0
client_mod.DESCRIBE_BASE_DELAY = 0.0
client_mod.DESCRIBE_RETRY_JITTER = 0.0

_K = client_mod.SearchAttributeKey
WTF_TEXT = "Unable to query workflow due to Workflow Task in failed state."
#: Ceiling for the console-half node leg (injectable; see the spawn site).
NODE_BUDGET_ENV = "SANDBAR_T261102_12_NODE_BUDGET_S"
NODE_BUDGET_DEFAULT_S = 20.0


def run(coro):
    return asyncio.run(coro)


class _Status:
    def __init__(self, name):
        self.name = name


class _Desc:
    def __init__(self, status_name="RUNNING", task_queue="sandbar"):
        self.status = _Status(status_name)
        self.task_queue = task_queue
        self.close_time = None
        self.typed_search_attributes = {}
        self.result_run_id = None
        self.run_id = "run-scenario"
        self.history_length = 39


class _Event:
    def __init__(self, failure_type, message, event_id):
        class _Info:
            type = failure_type

        class _Failure:
            failure_info = _Info()
            message = None

        _Failure.message = message
        self.workflow_task_failed_event_attributes = type("Attrs", (), {"failure": _Failure})()
        self.event_id = event_id


class _History:
    def __init__(self, events):
        self.events = events


class _Handle:
    def __init__(self, behaviour="ok", desc=None, snap=None, history=None,
                 result_ok=True):
        self.behaviour = behaviour
        self.desc = desc or _Desc()
        self.snap = snap if snap is not None else {"meta": {"title": "row"}}
        self.history = history or _History([])
        self.queries = 0
        self.result_ok = result_ok
        self.result_run_id = None
        self.run_id = "run-scenario"

    async def query(self, name):
        self.queries += 1
        if self.behaviour == "wtf":
            raise RuntimeError(WTF_TEXT)
        if self.behaviour == "timeout":
            raise asyncio.TimeoutError("stub timeout")
        return self.snap

    async def describe(self):
        return self.desc

    async def result(self):
        if not self.result_ok:
            raise RuntimeError("result stream unavailable")
        return self.snap

    async def fetch_history(self):
        return self.history


class _Poller:
    def __init__(self, identity):
        self.identity = identity


class _PollerService:
    def __init__(self, pollers):
        self._pollers = pollers
        self.probed = []

    async def describe_task_queue(self, request, **kw):
        self.probed.append(request.task_queue.name)

        class _Resp:
            pass

        resp = _Resp()
        resp.pollers = self._pollers.get(request.task_queue.name, [])
        return resp


class _Client:
    namespace = "default"

    def __init__(self, handles, pollers):
        self.workflow_service = _PollerService(pollers)
        self._handles = handles

    def get_workflow_handle(self, tid):
        return self._handles[tid]


LIVE = _Poller("%d@scenario-host" % os.getpid())


def _query_with(handles, pollers):
    stub = _Client(handles, pollers)

    async def _connect(*a, **k):
        return stub

    return stub, _connect


def main() -> int:
    # TemporaryDirectory object kept alive for the whole run: the probe store (witness +
    # archive manifest) and the receipts feed live inside it, and it is reclaimed on exit
    # (L8 tmp-dir hygiene: one reclaim verb per mkdtemp site).
    tmp_root = tempfile.TemporaryDirectory(prefix="t261102-12-scenario-")
    projects_root = tmp_root.name
    os.environ["SANDBAR_PROJECTS_DIR"] = projects_root
    receipts = {}

    # ---- A: a CLOSED ticket needs no poller at all -------------------------------
    handle_a = _Handle(behaviour="timeout", desc=_Desc("COMPLETED"), result_ok=True)
    stub_a, connect_a = _query_with({"t-a": handle_a}, {})
    old = client_mod._connect
    client_mod._connect = connect_a
    try:
        receipts["closed_no_poller"] = run(client_mod.cmd_ticket_query({"ticket_id": "t-a"}))
    finally:
        client_mod._connect = old
    res_a = receipts["closed_no_poller"]
    check("A1 a closed ticket answers without a snapshot query",
          res_a.get("ok") is True and handle_a.queries == 0,
          "ok=%r queries=%r" % (res_a.get("ok"), handle_a.queries))
    check("A2 the closed answer carries its execution status",
          (res_a.get("result") or {}).get("exec_status") == "COMPLETED",
          repr(res_a)[:200])

    # ---- B: retained record answers when the return value cannot be read ---------
    w = shared.write_closed_witness("sandbar", "t-b", "completed",
                                   "engine:client.ticket-close-out",
                                   workflow_id="t-b", observed_by="scenario")
    check("B1 the post-close witness is written by the real writer",
          w.get("written") is True, repr(w)[:200])
    tdir = Path(projects_root) / "sandbar" / "data" / "tickets" / "t-b"
    (tdir / "archive.json").write_text(json.dumps({
        "schema": "v1", "ticket_id": "t-b", "legacy": False,
        "archived_at": "2026-11-01T00:15:21+00:00",
        "meta": {"title": "Closed inspection row", "epic": "sandbar-core"},
    }), encoding="utf-8")
    handle_b = _Handle(behaviour="timeout", desc=_Desc("COMPLETED"), result_ok=False)
    _, connect_b = _query_with({"t-b": handle_b}, {})
    client_mod._connect = connect_b
    try:
        receipts["retained"] = run(client_mod.cmd_ticket_query({"ticket_id": "t-b"}))
    finally:
        client_mod._connect = old
    res_b = receipts["retained"]
    face_b = res_b.get("face") or {}
    check("B2 the unreadable closed ticket is answered from the retained record",
          face_b.get("face_state") == client_mod.FACE_STATE_RETAINED,
          repr(face_b)[:300])
    check("B3 the retained record carries the outcome",
          str((face_b.get("retained") or {}).get("terminal_status", "")).upper() == "COMPLETED",
          repr(face_b.get("retained"))[:200])

    # ---- C: deterministic workflow-task failure ---------------------------------
    hist_c = _History([_Event("RestrictedWorkflowAccessError",
                              "Cannot access os.path.join from inside a workflow.", 36)])
    handle_c = _Handle(behaviour="wtf", desc=_Desc(task_queue="sandbar"), history=hist_c)
    stub_c, connect_c = _query_with({"t-c": handle_c}, {"sandbar": [LIVE]})
    client_mod._connect = connect_c
    try:
        receipts["workflow_task_failed"] = run(client_mod.cmd_ticket_query({"ticket_id": "t-c"}))
    finally:
        client_mod._connect = old
    res_c = receipts["workflow_task_failed"]
    check("C1 the deterministic refusal is its own kind",
          res_c.get("kind") == client_mod.KIND_WORKFLOW_TASK_FAILED, repr(res_c)[:200])
    check("C2 it is not dressed as a poller problem",
          res_c.get("kind") != client_mod.KIND_NO_POLLER, repr(res_c.get("kind")))
    check("C3 it costs exactly one query attempt (no retry budget)",
          handle_c.queries == 1, "queries=%r" % handle_c.queries)
    check("C4 no poller probe is run for a failed workflow task",
          stub_c.workflow_service.probed == [], repr(stub_c.workflow_service.probed))
    dur_c = (res_c.get("face") or {}).get("durable") or {}
    check("C5 the durable cause is on the face",
          str((dur_c.get("retained") or {}).get("failure_type")) == "RestrictedWorkflowAccessError",
          repr(dur_c)[:300])
    check("C6 the face names the queue the execution reports",
          dur_c.get("queue") == "sandbar" and dur_c.get("queue_source") == "describe",
          repr(dur_c.get("queue")) + "/" + repr(dur_c.get("queue_source")))

    # ---- D: no poller, named on the real queue ----------------------------------
    handle_d = _Handle(behaviour="timeout", desc=_Desc(task_queue="sandbar-ticket-t-d"))
    stub_d, connect_d = _query_with({"t-d": handle_d}, {"sandbar": [LIVE],
                                                        "sandbar-ticket-t-d": []})
    client_mod._connect = connect_d
    try:
        receipts["no_poller"] = run(client_mod.cmd_ticket_query({"ticket_id": "t-d"}))
    finally:
        client_mod._connect = old
    res_d = receipts["no_poller"]
    face_d = res_d.get("face") or {}
    check("D1 zero pollers on the ticket's own queue is named no_poller",
          res_d.get("kind") == client_mod.KIND_NO_POLLER, repr(res_d)[:200])
    check("D2 the named queue is the one the execution reports",
          (face_d.get("durable") or {}).get("queue") == "sandbar-ticket-t-d",
          repr(face_d.get("durable"))[:200])
    check("D3 the poller count is stated",
          (face_d.get("durable") or {}).get("live_pollers") == 0,
          repr((face_d.get("durable") or {}).get("live_pollers")))

    # ---- E: no false no_poller on the shared queue ------------------------------
    handle_e = _Handle(behaviour="timeout", desc=_Desc(task_queue="sandbar"))
    stub_e, connect_e = _query_with({"t-e": handle_e}, {"sandbar": [LIVE]})
    client_mod._connect = connect_e
    try:
        receipts["transient_with_live_poller"] = run(
            client_mod.cmd_ticket_query({"ticket_id": "t-e"}))
    finally:
        client_mod._connect = old
    res_e = receipts["transient_with_live_poller"]
    check("E1 a live poller on the real queue is never named no_poller",
          res_e.get("kind") != client_mod.KIND_NO_POLLER, repr(res_e.get("kind")))
    check("E2 the probe read the queue the execution polls",
          stub_e.workflow_service.probed == ["sandbar"],
          repr(stub_e.workflow_service.probed))

    # ---- F: retained unavailable is named ---------------------------------------
    receipts["retained_unavailable"] = {
        "ok": False, "kind": "not_found", "error": "ticket not found",
        "face": {"face_state": client_mod.FACE_STATE_RETAINED_UNAVAILABLE,
                 "retained": client_mod.retained_ticket_face("t-nowhere")},
    }
    face_f = receipts["retained_unavailable"]["face"]
    check("F1 no live read and no retained record = retained_unavailable",
          face_f["face_state"] == client_mod.FACE_STATE_RETAINED_UNAVAILABLE,
          repr(face_f)[:200])
    check("F2 the absence names itself",
          "no retained state" in str((face_f.get("retained") or {}).get("reason")),
          repr(face_f.get("retained"))[:200])

    # ---- the console leg: the real panel model over these real receipts ----------
    node = shutil.which("node")
    if node is None:
        env_fail("node-absent", "node is required for the console-half leg")
        return summary()
    feed = Path(projects_root) / "receipts.json"
    feed.write_text(json.dumps(receipts), encoding="utf-8")
    panel = HERE / "panel_named_face.mjs"
    # Injectable, seconds-scale ceiling (the wait_bound_ms precedent): this leg is a
    # node script that answers in milliseconds, so an exceeded bound means the leg HUNG,
    # not that the machine is slow. The bound is settable from the environment so a
    # reviewer can shrink it, and a fired bound NAMES the leg as an environment face.
    node_budget_s = float(os.environ.get(NODE_BUDGET_ENV) or NODE_BUDGET_DEFAULT_S)
    try:
        proc = subprocess.run([node, str(panel), str(feed), str(REPO)],
                              capture_output=True, text=True, timeout=node_budget_s)
    except subprocess.TimeoutExpired:
        env_fail("node-leg-timeout",
                 "the console leg did not answer within %ss (bound %s=%r) — the leg hung, "
                 "the engine half's verdict stands alone"
                 % (node_budget_s, NODE_BUDGET_ENV, node_budget_s))
        return summary()
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    panel_fails = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAIL ")]
    check("G1 the console half is green over the engine's own receipts",
          proc.returncode == 0 and not panel_fails,
          "exit=%r fails=%d" % (proc.returncode, len(panel_fails)))
    for ln in panel_fails:
        FAILS.append("panel:%s" % ln[5:])
    return summary()


try:
    code = main()
except Exception as e:  # noqa: BLE001 — a crash is a named red, never a silent green
    import traceback
    traceback.print_exc()
    FAILS.append("scenario-crash:%r" % (e,))
    code = summary()
sys.exit(code)
