#!/usr/bin/env python3
"""replay_check — replay-safety check for in-flight tickets against the local
workflow code (t260828-01).

Purpose: after changing workflow code (for example adding a parts field to
STAGES), pull the history of every currently RUNNING v2-template ticket and
replay it through temporalio.worker.Replayer with the new local code. A
nondeterministic change (a missing patched marker, an altered already-executed
path) blows up during replay; this script turns that into a mechanical red
light.

Read-only: it only calls list_workflows / fetch_history (the same read-only
level as the workbench ticket-query path). It writes no signals, starts no
worker, and never touches 3099/8233. Connection parameters follow the shared.py
env conventions (SANDBAR_TARGET_HOST / SANDBAR_NAMESPACE); --host/--ns override
them (e.g. the Docker-isolated environment 127.0.0.1:17233 / sandbar-test).

Interpreter auto-detection (a lane worktree has no .venv): when a direct
`import temporalio` fails, this script re-execs itself with the first candidate
interpreter found in the order $SANDBAR_POC_PYTHON -> this directory's .venv ->
the main repo's engine/.venv (worktree case), so it keeps working on other
machines.

Usage (from the engine directory):
    replay_check.py                      # replay all currently RUNNING v2 tickets
    replay_check.py --workflow <id>      # replay one ticket only (any status)
    replay_check.py --history <file>     # offline replay of an exported history JSON
                                         # (temporal workflow show -o json)
    replay_check.py --limit 20           # max entries to replay (default 50)

stdout is always a single JSON line {"ok": bool, "results": [...]} (same
contract as client.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent


def _candidate_pythons() -> list:
    cands = []
    env = os.environ.get("SANDBAR_POC_PYTHON")
    if env:
        cands.append(Path(env))
    cands.append(POC / ".venv" / "bin" / "python")
    # worktree case: <main>/.worktrees/<lane>/server/engine/replay_check.py
    parts = POC.parts
    if ".worktrees" in parts:
        main = Path(*parts[: parts.index(".worktrees")])
    elif ".lane" in parts:
        main = Path(*parts[: parts.index(".lane")])
        cands.append(main / "server" / "engine" / ".venv" / "bin" / "python")
        # multi-repo lanes (ticket B, t260907-06): the POC copy may sit inside
        # a child repo tree under <proj>/.lane/<id>/<repo>/ — probe each child
        # directory for a .venv (main-repo candidates above stay unchanged, so
        # single-repo paths regress nothing).
        lane_container = Path(*parts[: parts.index(".lane") + 2])
        if lane_container.is_dir():
            for child in sorted(lane_container.iterdir()):
                if child.is_dir() and child.name != "__pycache__":
                    cands.append(child / "server" / "engine"
                                 / ".venv" / "bin" / "python")
    return cands


try:
    import temporalio  # noqa: F401
except ImportError:
    for py in _candidate_pythons():
        if py.is_file() and str(py) != sys.executable:
            os.execv(str(py), [str(py), str(Path(__file__).resolve())] + sys.argv[1:])
    print(json.dumps({"ok": False, "error": "import temporalio 失败且无候选解释器（试过 %s）"
                      % [str(p) for p in _candidate_pythons()]}, ensure_ascii=False))
    sys.exit(1)

import asyncio  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

from temporalio.client import Client, WorkflowHistory  # noqa: E402
from temporalio.worker import Replayer  # noqa: E402

sys.path.insert(0, str(POC))  # make sure we import the template code next to this file (inside the lane)
from shared import NAMESPACE, TARGET_HOST  # noqa: E402
from workflows_v2 import ALL_WORKFLOWS_V2, TEMPLATE_CLASSES  # noqa: E402
# t260913-02：巡检 workflow 族也进 replay 面——旧版只注册 v2 模板族，巡检票被重放器
# 直接判「未注册」（不是非确定），等于巡检的 replay 安全检查是**空的**（本票改巡检阶段机
# 时实测：四张在途老票全被「not registered」挡回，无法证 replay 安全）。
from workflows import ALL_WORKFLOWS  # noqa: E402

TEMPLATE_TYPES = {cls.__name__ for cls in ALL_WORKFLOWS_V2} | {
    cls.__name__ for cls in ALL_WORKFLOWS}


def _replayer() -> Replayer:
    # UnsandboxedWorkflowRunner (Replayer default): replay only checks
    # determinism, so we skip sandbox throttling — this avoids false reds from
    # lane-local module passthrough config drifting from the worker's.
    return Replayer(workflows=list(ALL_WORKFLOWS_V2) + list(ALL_WORKFLOWS))


async def _replay_one_history(history: WorkflowHistory, label: str) -> Dict[str, Any]:
    r: Dict[str, Any] = {"id": label, "events": len(history.events)}
    try:
        await _replayer().replay_workflow(history)
        r["ok"] = True
    except Exception as e:  # nondeterminism / code incompatibility -> red, but keep replaying the rest
        r["ok"] = False
        r["error"] = "%s: %s" % (type(e).__name__, e)
    return r


async def cmd_running(host: str, ns: str, limit: int,
                      only: Optional[str]) -> Dict[str, Any]:
    client = await Client.connect(host, namespace=ns)
    results: List[Dict[str, Any]] = []
    if only:
        handle = client.get_workflow_handle(only)
        desc = await handle.describe()
        history = await handle.fetch_history()
        r = await _replay_one_history(history, only)
        r["type"] = desc.workflow_type
        r["status"] = str(desc.status).split(".")[-1]
        return {"ok": r["ok"], "results": [r]}
    query = 'ExecutionStatus="Running"'
    async for wf in client.list_workflows(query, limit=limit):
        wtype = wf.workflow_type
        if wtype not in TEMPLATE_TYPES:
            continue  # only replay v2-template tickets; dispatcher-scan and other scheduler flows are out of scope
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        history = await handle.fetch_history()
        r = await _replay_one_history(history, wf.id)
        r["type"] = wtype
        results.append(r)
    return {"ok": all(r["ok"] for r in results), "results": results}


async def cmd_history_file(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    # temporal CLI `workflow show -o json` outputs {"events": [...]}; a bare
    # events list is also accepted
    if isinstance(data, list):
        data = {"events": data}
    history = WorkflowHistory.from_json(path.stem, data)
    r = await _replay_one_history(history, path.name)
    return {"ok": r["ok"], "results": [r]}


USAGE = ("用法：replay_check.py [--workflow <id> | --history <file>] "
         "[--host h:p] [--ns name] [--limit N]")


def main() -> int:
    argv = sys.argv[1:]
    host, ns, limit = TARGET_HOST, NAMESPACE, 50
    only: Optional[str] = None
    hfile: Optional[str] = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--workflow" and i + 1 < len(argv):
            only = argv[i + 1]
            i += 2
        elif a == "--history" and i + 1 < len(argv):
            hfile = argv[i + 1]
            i += 2
        elif a == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
        elif a == "--ns" and i + 1 < len(argv):
            ns = argv[i + 1]
            i += 2
        elif a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
        else:
            print(json.dumps({"ok": False, "error": "未知参数 %r。%s" % (a, USAGE)},
                             ensure_ascii=False))
            return 1
    meta = {"interpreter": sys.executable, "host": host, "ns": ns,
            "templates": sorted(TEMPLATE_TYPES)}
    try:
        if hfile:
            out = asyncio.run(cmd_history_file(Path(hfile)))
        else:
            out = asyncio.run(cmd_running(host, ns, limit, only))
    except Exception as e:  # infrastructure failure (connect error etc.) -> structured receipt
        out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "results": []}
    out.update(meta)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
