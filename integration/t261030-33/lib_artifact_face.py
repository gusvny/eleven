#!/usr/bin/env python3
"""Shared offline rig for the t261030-33 integration scenarios (grey-box L2/L3).

The ticket adds an engine-side data path. A stage writes a receipt file. The
activity intake reads and normalizes it. The Temporal boundary carries a dict of
`StageResult` field names. The workflow copies three keys into its results face.
`_handoff` derives the declaration from that face. The snapshot query serves the
normalized list.

This rig drives those production seams without a Temporal server, Docker, or the
console:

- the REAL receipt reader (`agent_activities._read_result`) over a real file;
- the REAL workflow copy and step code (`DevLaneWorkflow._run_agent_step`) with a
  stubbed activity seam (one `execute_activity` returning the boundary dict);
- the REAL `_handoff` writers and the REAL `snapshot()` query body on bare
  workflow instances (the offline proxy this repository already uses for the
  workflow face; the query decorator does not need a runtime).

Nothing here re-implements a production rule. The shell fields mirror what the
engine's own `_init` sets; a field the query reads but the shell omits is a rig
bug, not a product judgement.

Engine modules unimportable (no temporalio in the selected interpreter) is an
environment fact: the caller prints ENV_FAIL and exits 2.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import datetime
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import agent_activities  # noqa: E402
import base  # noqa: E402
import dev_lane  # noqa: E402
import light_lane  # noqa: E402
import shared  # noqa: E402

FIXED_NOW = datetime.datetime(2026, 10, 30, 12, 0, 0,
                              tzinfo=datetime.timezone.utc)


class PatchedCalled(AssertionError):
    """Raised when a query body calls the SDK gate (a read-only violation)."""


def stub_workflow(patched_raises: bool = False):
    """The stub the workflow modules call instead of the Temporal runtime."""
    def _patched(_patch_id):
        if patched_raises:
            raise PatchedCalled("workflow.patched called inside the snapshot query")
        return False

    return SimpleNamespace(
        patched=_patched,
        now=lambda: FIXED_NOW,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None,
        sleep=lambda *a, **k: None,
    )


def install_stub(stub=None):
    """Point every workflow module at the stub (the repo's offline rig pattern)."""
    stub = stub or stub_workflow()
    dev_lane.workflow = stub
    base.workflow = stub
    light_lane.workflow = stub
    return stub


def shell(cls, gens=None, stage="", workspace=None, meta_extra=None):
    """A bare workflow instance: exactly the fields the step code and the query read."""
    wf = object.__new__(cls)
    wf.meta = {
        "stage": stage, "stage_state": "done", "status": "dispatched",
        "handoffs": [], "log": [], "checks": {},
        "workspace": workspace or os.getcwd(),
        "write_set": [], "revision_count": 0,
    }
    if meta_extra:
        wf.meta.update(meta_extra)
    wf.timeline = []
    wf._gens = dict(gens or {})
    wf._retry_token = 0
    wf._rework = None
    wf.results = {}
    wf.engine_version = 2
    wf.ticket_id = "t26103033-ut"
    wf._detail_face_on = False
    wf._paused = False
    wf._paused_at_gate = False
    wf.signatures = {}
    wf.gate_runs = []
    wf.refused = []
    wf.human_context = {}
    wf._ledger_marks = []
    wf._now_epoch = lambda: 1700000000
    if cls is base.TicketWorkflowBase:
        wf.template_id = "generic-probe"
    return wf


def write_receipt(tmpdir, payload, name="stage_create_plan_gen0.json"):
    path = Path(tmpdir) / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return path


def intake(tmpdir, payload, stage="create_plan"):
    """Read a real receipt file with the production reader."""
    path = write_receipt(tmpdir, payload)
    res = agent_activities._read_result(path, stage)
    # dataclasses.asdict mirrors what the Temporal data converter does to the
    # StageResult on the way to the workflow (a dict of field names).
    boundary = None if res is None else json.loads(
        json.dumps(dataclasses.asdict(res), default=str))
    return res, boundary


def drive_step(boundary, step="create_plan", gens=None):
    """Run the REAL workflow copy block (`_run_agent_step`) over the boundary dict."""
    stub = stub_workflow()

    async def _execute(activity, args, **kw):
        return copy.deepcopy(boundary)

    stub.execute_activity = _execute
    install_stub(stub)
    wf = shell(dev_lane.DevLaneWorkflow, gens=gens)
    res = asyncio.run(wf._run_agent_step(step))
    return wf, res


def chain(tmpdir, payload, step="create_plan", gens=None):
    """receipt file -> production intake -> production workflow copy."""
    res, boundary = intake(tmpdir, payload, stage=step)
    wf, step_res = drive_step(boundary, step=step, gens=gens)
    return wf, step_res, boundary, res


def handoff(wf, step, res):
    """The lane's own handoff call shape (artifacts = the receipt's path list)."""
    wf._handoff(step, res.summary or "s", artifacts=list(res.deliverables),
                report=res.report)


def snap(wf):
    return wf.snapshot()


def descriptor(receipt_id="a", title="A", kind="text", source="docs/a.md", **kw):
    d = {"id": receipt_id, "title": title, "kind": kind, "source": source}
    d.update(kw)
    return d
