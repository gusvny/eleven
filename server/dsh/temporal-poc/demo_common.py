"""demo 公共：连服务端、等条件、导历史。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowHandle

from shared import NAMESPACE, OUT_DIR, TARGET_HOST, TASK_QUEUE  # noqa: F401


async def connect() -> Client:
    return await Client.connect(TARGET_HOST, namespace=NAMESPACE)


def say(*parts: Any) -> None:
    print(*parts, flush=True)


def jdump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


async def wait_for(
    handle: WorkflowHandle,
    pred: Callable[[Dict[str, Any]], bool],
    what: str,
    timeout: float = 60.0,
    interval: float = 0.4,
) -> Dict[str, Any]:
    """轮询 query 等状态到位（query 是实时读，不改历史）。"""
    waited = 0.0
    while waited < timeout:
        snap = await handle.query("snapshot")
        if pred(snap):
            return snap
        await asyncio.sleep(interval)
        waited += interval
    raise TimeoutError(f"等「{what}」超时（{timeout}s），当前 snapshot=\n{jdump(await handle.query('snapshot'))}")


def _readable(raw: bytes, limit: int = 170) -> str:
    """payload 原文是 ASCII 转义的 JSON，转回中文便于人读（只做展示，不改历史）。"""
    try:
        text = raw.decode("utf-8")
    except Exception:
        return ""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False)
    except Exception:
        pass
    return text[:limit]


async def history_lines(handle: WorkflowHandle) -> List[str]:
    """把不可变事件历史压成可读清单：事件号 类型 [细节]。"""
    out: List[str] = []
    hist = await handle.fetch_history()
    for ev in hist.events:
        name = EventType.Name(ev.event_type).replace("EVENT_TYPE_", "")
        detail = ""
        if name == "ACTIVITY_TASK_SCHEDULED":
            detail = ev.activity_task_scheduled_event_attributes.activity_type.name
        elif name == "WORKFLOW_EXECUTION_SIGNALED":
            a = ev.workflow_execution_signaled_event_attributes
            payload = ""
            try:
                payload = _readable(a.input.payloads[0].data, 130)
            except Exception:
                pass
            detail = f"{a.signal_name} {payload}"
        elif name == "WORKFLOW_EXECUTION_STARTED":
            detail = ev.workflow_execution_started_event_attributes.workflow_type.name
        elif name == "ACTIVITY_TASK_COMPLETED":
            try:
                detail = _readable(
                    ev.activity_task_completed_event_attributes.result.payloads[0].data
                )
            except Exception:
                pass
        out.append(f"#{ev.event_id:>3} {name}{(' | ' + detail) if detail else ''}")
    return out


async def terminate_if_running(client: Client, wf_id: str) -> Optional[str]:
    """demo 可重跑：同 id 若有 running 实例先终止（终止本身也进历史，不是删除）。"""
    handle = client.get_workflow_handle(wf_id)
    try:
        desc = await handle.describe()
    except Exception:
        return None
    if desc.status is not None and desc.status.name == "RUNNING":
        await handle.terminate(reason="demo 重跑，清场")
        await asyncio.sleep(0.5)
        return desc.run_id
    return None


def write_out(filename: str, text: str) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename
    path.write_text(text, encoding="utf-8")
    return str(path)
