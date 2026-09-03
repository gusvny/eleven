#!/usr/bin/env python3
"""replay_check —— 存量运行中工单的 Temporal replay 安全实测（t260828-01）。

用途：改 workflow 代码（如 STAGES 加 parts 字段）后，把**当前 RUNNING** 的 v2 模版工单
历史逐条拉下来，用本地新代码过 temporalio.worker.Replayer 回放——非确定性改动
（缺 patched、改了已执行路径）会在回放时直接炸，本脚本把它变成一条机械红灯。

只读：只调 list_workflows / fetch_history（与工单台 ticket-query 同级只读路径），
不写任何信号、不启 worker、不碰 3099/8233。连接参数沿用 shared.py 环境变量口径
（SUYOU_TARGET_HOST / SUYOU_NAMESPACE），可用 --host/--ns 覆盖（如 Docker 隔离环境
127.0.0.1:17233 / suyou-test）。

解释器自探测（泳道 worktree 内无 .venv）：直接跑 import temporalio 失败时，按
$SUYOU_POC_PYTHON → 本目录 .venv → 主库 temporal-poc/.venv（worktree 场景）顺序
找候选解释器 re-exec 自己，换机器不断。

用法（temporal-poc 目录）：
    replay_check.py                      # 回放当前 RUNNING 的五模版 v2 工单
    replay_check.py --workflow <id>      # 只回放指定工单（不限运行态）
    replay_check.py --history <file>     # 离线回放导出的 history JSON（temporal workflow show -o json）
    replay_check.py --limit 20           # 最多回放条数（缺省 50）

stdout 一律单行 JSON {"ok": bool, "results": [...]}（与 client.py 同契约）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent


def _candidate_pythons() -> list:
    cands = []
    env = os.environ.get("SUYOU_POC_PYTHON")
    if env:
        cands.append(Path(env))
    cands.append(POC / ".venv" / "bin" / "python")
    # worktree 场景：<main>/.worktrees/<lane>/server/dsh/temporal-poc/replay_check.py
    parts = POC.parts
    if ".worktrees" in parts:
        main = Path(*parts[: parts.index(".worktrees")])
    elif ".lane" in parts:
        main = Path(*parts[: parts.index(".lane")])
        cands.append(main / "server" / "dsh" / "temporal-poc" / ".venv" / "bin" / "python")
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

sys.path.insert(0, str(POC))  # 保证 import 的是本文件旁（泳道内）的模版代码
from shared import NAMESPACE, TARGET_HOST  # noqa: E402
from workflows_v2 import ALL_WORKFLOWS_V2, TEMPLATE_CLASSES  # noqa: E402

TEMPLATE_TYPES = {cls.__name__ for cls in ALL_WORKFLOWS_V2}


def _replayer() -> Replayer:
    # UnsandboxedWorkflowRunner（Replayer 缺省）：回放只看确定性，不套 sandbox 限流，
    # 避免泳道内模块 passthrough 配置与 worker 漂移造成假红。
    return Replayer(workflows=ALL_WORKFLOWS_V2)


async def _replay_one_history(history: WorkflowHistory, label: str) -> Dict[str, Any]:
    r: Dict[str, Any] = {"id": label, "events": len(history.events)}
    try:
        await _replayer().replay_workflow(history)
        r["ok"] = True
    except Exception as e:  # 非确定性/代码不兼容 → 红灯但不中断其它条
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
            continue  # 只回放五模版 v2 工单；dispatcher-scan 等调度流不在本单范围
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        history = await handle.fetch_history()
        r = await _replay_one_history(history, wf.id)
        r["type"] = wtype
        results.append(r)
    return {"ok": all(r["ok"] for r in results), "results": results}


async def cmd_history_file(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    # temporal CLI `workflow show -o json` 输出 {"events": [...]}；也容忍裸 events 列表
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
    except Exception as e:  # 基础设施故障（连不上等）→ 结构化回执
        out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "results": []}
    out.update(meta)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
