#!/usr/bin/env python3
"""inspection_trigger — the ops channel for inspection scheduling (inspection epic
ticket 1, t260905-03).

Positioning (following scan_schedule.py's ops-channel trade-off list items 2 and 3):
this tool is the **ops channel for humans/the supervisor** and does not enter the dsh
model tool surface — the model side's visibility into inspection scheduling is
read-only, preventing arbitrary model-side triggers from breaking one ticket per period.

Borrowed trade-off list (review_plan R2, all six items):
  (1) overlap: SKIP (a repeated trigger of the same instance in the same period merges
      into one ticket — the ticket id = the workflow id, so idempotent; AlreadyStarted
      means deduped; the schedule layer adds SKIP on top, so a period collision opens no
      extra ticket).
  (2) note governance: schedule-up must carry --note (who, why, what frequency); it goes
      into the schedule state and stays queryable.
  (3) ops-channel positioning: not in the dsh model tool surface (see above).
  (4) stdout emits a single line of JSON {ok, result|error} (the same contract as
      client.py/scan_schedule.py).
  (5) precise errors: RPCError is translated explicitly as "... does not exist or is
      unreachable", never silently.
  (6) fail-closed argument ranges: instance must match an **enabled** instance in the
      declaration (not enabled = explicit error, before any network action); period must
      be YYYYMMDD and a real calendar day; decision accepts only approve/reject; who must
      be non-empty and must not be an agent role name (only humans sign).

Declaration-driven (acceptance 3, behavior level): the trigger surface consumes only
build_schedule_specs's output — an instance with enabled=false in the declaration simply
does not exist in specs, and trigger/schedule-up always error explicitly on it; changing
the declaration changes the behavior, no engine code involved.

Usage (venv python or any interpreter with temporalio; the decl subcommand is
dependency-free pure stdlib):
    inspection_trigger.py decl [--decl-path P]
    inspection_trigger.py trigger --instance integration-tests [--period YYYYMMDD] [--repo-root R]
    inspection_trigger.py sign --instance integration-tests --who <user> [--decision approve|reject] [--note <text>] [--period P]
    inspection_trigger.py describe --instance integration-tests [--period P]
    inspection_trigger.py schedule-up --instance integration-tests --note <text>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspection_decl import (  # noqa: E402
    build_schedule_specs,
    default_decl_path,
    load_inspection_decl,
)

USAGE = ("用法：inspection_trigger.py <decl|trigger|sign|describe|schedule-up> …\n"
         "运维通道（不进模型工具面）；每期一票：票号=inspection-<实例>-<期号>，重复触发即去重。")


def _ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


def _emit(payload: Dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    if exit_code:
        sys.exit(exit_code)


def _valid_period(period: str) -> Optional[str]:
    if not re.match(r"^\d{8}$", period or ""):
        return "period 非法：%r（须 YYYYMMDD）" % period
    try:
        datetime.strptime(period, "%Y%m%d")
    except ValueError:
        return "period 非真实日历日：%r" % period
    return None


def _enabled_spec(decl_path: Optional[Path], instance_id: str) -> Dict[str, Any]:
    """Declaration → that instance's scheduling intent; not enabled / not declared always
    errors explicitly (fail-closed before any network)."""
    decl = load_inspection_decl(decl_path) if decl_path else load_inspection_decl()
    if decl.instance(instance_id) is None:
        raise ValueError("实例 %r 未在声明中（在册：%s）"
                         % (instance_id, "、".join(i.id for i in decl.instances)))
    spec = next((s for s in build_schedule_specs(decl) if s["instance_id"] == instance_id), None)
    if spec is None:
        raise ValueError("实例 %r 在声明中未启用（enabled=false 不触发）；已启用：%s——改声明即改行为"
                         % (instance_id, "、".join(i.id for i in decl.enabled_instances()) or "无"))
    return spec


# ========================================================================================
# Server-side actions (temporalio imported lazily: the decl subcommand runs with zero
# dependencies and stays reusable by the scenario lane's stdlib)
# ========================================================================================

def _lazy_engine():
    from inspection_flow import CLOSE_GATE_ID, InspectionPeriodicInput, inspection_ticket_id
    from shared import NAMESPACE, TARGET_HOST, TASK_QUEUE
    return InspectionPeriodicInput, inspection_ticket_id, CLOSE_GATE_ID, TARGET_HOST, NAMESPACE, TASK_QUEUE


async def _connect():
    from temporalio.client import Client
    _, _, _, target, namespace, _tq = _lazy_engine()
    return await Client.connect(target, namespace=namespace)


async def cmd_trigger(args: argparse.Namespace) -> Dict[str, Any]:
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    try:
        spec = _enabled_spec(args.decl_path, args.instance)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001 — declaration parsing fails closed, translated here
        return _err("声明不可用：%s" % e)
    InspectionPeriodicInput, ticket_id_of, _, _, _, task_queue = _lazy_engine()
    ticket_id = ticket_id_of(args.instance, period)
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001 — connection failures are named explicitly (the spirit of trade-off 5, never silent)
        return _err("temporal server 不可达：%s" % e)
    from temporalio.service import RPCError
    try:
        handle = await client.start_workflow(
            spec["workflow"],
            InspectionPeriodicInput(
                instance_id=args.instance, period=period,
                repo_root=args.repo_root or ""),
            id=ticket_id, task_queue=task_queue)
        return _ok({"triggered": True, "ticket_id": ticket_id, "period": period,
                    "workflow": spec["workflow"], "instance": args.instance,
                    "first_run_id": handle.first_execution_run_id})
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "WorkflowAlreadyStartedError" or "already started" in str(e).lower():
            # Trade-off 1: a repeated trigger with the same ticket id = deduped to the same
            # ticket (the mechanical one-ticket-per-period guarantee)
            return _ok({"triggered": False, "deduped": True, "ticket_id": ticket_id,
                        "period": period, "reason": "同期巡检票已在（每期一票）"})
        if isinstance(e, RPCError):
            return _err("workflow %s 启动失败（不存在或不可达）：%s" % (ticket_id, e))
        return _err("workflow %s 启动失败：%s: %s" % (ticket_id, type(e).__name__, e))


async def cmd_sign(args: argparse.Namespace) -> Dict[str, Any]:
    from inspection_flow import CLOSE_GATE_ID, inspection_ticket_id, validate_close_signature
    from shared import Signature
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    payload, verr = validate_close_signature(
        {"who": args.who or "", "gate": CLOSE_GATE_ID, "decision": args.decision, "note": args.note or ""},
        expected_gate=CLOSE_GATE_ID)
    if verr:
        return _err(verr)
    ticket_id = inspection_ticket_id(args.instance, period)
    try:
        client = await _connect()
        handle = client.get_workflow_handle(ticket_id)
        await handle.signal("sign", Signature(
            who=payload["who"], gate=CLOSE_GATE_ID, decision=payload["decision"], note=payload["note"]))
        snap = await handle.query("snapshot")
        return _ok({"signed": True, "ticket_id": ticket_id, "decision": payload["decision"],
                    "who": payload["who"], "status": (snap or {}).get("status")})
    except Exception as e:  # noqa: BLE001
        return _err("巡检票 %s 签字失败（不存在或不可达）：%s: %s" % (ticket_id, type(e).__name__, e))


def ticket_receipt(snap: Dict[str, Any], ticket_id: str) -> Dict[str, Any]:
    """workflow snapshot 查询 → 工单详情同构回执（纯函数；畸形快照逐字段降级不崩，
    畸形≠缺省：缺键如实出 None/空，不编造值）。"""
    face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
    findings = face.get("findings") if isinstance(face.get("findings"), list) else []
    brief = [{"id": f.get("id"), "scan": f.get("scan"), "severity": f.get("severity"),
              "subject": str(f.get("subject") or "")[:80]}
             for f in findings[:10] if isinstance(f, dict)]
    return {
        "id": snap.get("id") or ticket_id,
        "kind": snap.get("kind"),
        "stage": snap.get("stage"),
        "stage_state": snap.get("stage_state"),
        "status": snap.get("status"),
        "decision": snap.get("decision"),
        "face": {
            "summary": face.get("summary") if isinstance(face.get("summary"), dict) else {},
            "heartbeat": face.get("heartbeat"),
            "findings_total": len(findings),
            "findings_brief": brief,
            "red_line": face.get("red_line"),
        },
        "timeline_len": len(snap.get("timeline") or []) if isinstance(snap.get("timeline"), list) else 0,
        "human_gate": face.get("human_gate"),
        "report_path": face.get("report_path") or "",
    }


async def cmd_ticket(args: argparse.Namespace) -> Dict[str, Any]:
    """巡检票只读查询面（t260910-11 验收⑤）：与工单详情同构的阶段/状态/发现清单摘要。

    形状口径：result 顶层 = {id, kind, stage, stage_state, status, decision, face,
    timeline, report_path}——face 只出摘要（summary/high·med 前 N 条主题），防满屏
    刷屏；查不到=精确点名实例/票号（不许笼统「连不上/transient」把诊断引向网络方向）。
    降级口径：工单台（workbench 插件）查询面不在本票写集，工单台侧继续不可查是**已知
    降级**；本子命令是巡检票的唯一查询面（运维通道）。"""
    from temporalio.service import RPCError
    from inspection_flow import inspection_ticket_id
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    ticket_id = inspection_ticket_id(args.instance, period)
    try:
        client = await _connect()
        handle = client.get_workflow_handle(ticket_id)
        snap = await handle.query("snapshot")
    except RPCError as e:
        return _err("巡检票 %s（实例 %s 期 %s）不存在或未开（RPC %s）——查无此票≠连不上"
                    % (ticket_id, args.instance, period, type(e).__name__))
    except Exception as e:  # noqa: BLE001——连接失败精确翻译，不谎报票不存在
        return _err("temporal 不可达（查询 %s 失败）：%s: %s" % (ticket_id, type(e).__name__, e))
    if not isinstance(snap, dict):
        return _err("巡检票 %s（实例 %s 期 %s）无快照——查无此票≠连不上" % (ticket_id, args.instance, period))
    return _ok(ticket_receipt(snap, ticket_id))


async def cmd_describe(args: argparse.Namespace) -> Dict[str, Any]:
    from inspection_flow import inspection_ticket_id
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    ticket_id = inspection_ticket_id(args.instance, period)
    try:
        client = await _connect()
        handle = client.get_workflow_handle(ticket_id)
        snap = await handle.query("snapshot")
        if snap is None:
            return _err("巡检票 %s 无快照（不存在或不可达）" % ticket_id)
        return _ok({"ticket_id": ticket_id, "snapshot": snap})
    except Exception as e:  # noqa: BLE001
        return _err("巡检票 %s 查询失败（不存在或不可达）：%s: %s" % (ticket_id, type(e).__name__, e))


async def cmd_schedule_up(args: argparse.Namespace) -> Dict[str, Any]:
    """Declaration → Temporal Schedule (the wiring action for the generic scheduler;
    behavior follows the declaration, no engine code changes).
    note governance (trade-off 2): --note is mandatory."""
    if not args.note:
        return _err("schedule-up 必须带 --note（note 治理：不留无解释的常驻定时器）")
    try:
        spec = _enabled_spec(args.decl_path, args.instance)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001
        return _err("声明不可用：%s" % e)
    if spec["kind"] != "cron":
        return _err("kind %r 未接线，schedule-up 只支持 cron（已接线清单见 inspection_decl.WIRED_KINDS）" % spec["kind"])
    try:
        from temporalio.client import (
            Schedule,
            ScheduleActionStartWorkflow,
            ScheduleOverlapPolicy,
            SchedulePolicy,
            ScheduleSpec,
            ScheduleUpdate,
        )
        from temporalio.service import RPCError
        from inspection_flow import InspectionPeriodicInput
        from shared import NAMESPACE, TARGET_HOST, TASK_QUEUE
        from temporalio.client import Client
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        schedule_id = "sandbar-inspection-%s" % spec["instance_id"]
        handle = client.get_schedule_handle(schedule_id)
        cron_expr = spec["cron"]

        # Try an update first (idempotent), create only if absent — after changing the
        # declaration's cron, re-running schedule-up makes it take effect.
        def _upd(inp) -> ScheduleUpdate:
            sched = inp.description.schedule
            sched.spec = ScheduleSpec(cron_expressions=[cron_expr])
            sched.policy = SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)
            return ScheduleUpdate(schedule=sched)

        try:
            await handle.update(_upd)
            await handle.unpause(note=args.note)
            mode = "updated"
        except RPCError:
            await client.create_schedule(
                schedule_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        spec["workflow"],
                        InspectionPeriodicInput(instance_id=spec["instance_id"], period=""),
                        id="inspection-%s-period" % spec["instance_id"],
                        task_queue=TASK_QUEUE,
                    ),
                    spec=ScheduleSpec(cron_expressions=[cron_expr]),
                    policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
                ),
            )
            mode = "created"
        desc = await handle.describe()
        return _ok({"schedule_id": schedule_id, "mode": mode, "cron": cron_expr,
                    "overlap": "SKIP", "note": args.note, "instance": spec["instance_id"],
                    "next_action_times": [t.isoformat(timespec="seconds")
                                          for t in (desc.info.next_action_times or [])][:3]})
    except ImportError as e:
        return _err("temporalio SDK 缺失：%s（运维通道需 venv：server/engine/setup.sh）" % e)
    except Exception as e:  # noqa: BLE001
        return _err("schedule sandbar-inspection-%s 建立失败（不存在或不可达）：%s: %s"
                    % (args.instance, type(e).__name__, e))


def cmd_decl(args: argparse.Namespace) -> Dict[str, Any]:
    """Offline declaration view (zero temporalio dependency; the declaration-driven,
    parsing-level evidence surface)."""
    try:
        decl = load_inspection_decl(args.decl_path) if args.decl_path else load_inspection_decl()
    except Exception as e:  # noqa: BLE001 — DeclError/IO always becomes an explicit single-line JSON error
        return _err("声明不可用：%s" % e)
    return _ok({
        "source": decl.source,
        "schema": decl.schema,
        "instances": [{"id": i.id, "enabled": i.enabled, "kind": i.kind,
                       "cron": i.cron, "workflow": i.workflow, "template": i.template}
                      for i in decl.instances],
        "schedule_specs": build_schedule_specs(decl),
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="巡检调度运维通道（不进模型工具面）")
    sub = ap.add_subparsers(dest="op")
    p = sub.add_parser("decl", help="离线声明视图")
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("trigger", help="手动触发一期（每期一票：同票号去重）")
    p.add_argument("--instance", required=True)
    p.add_argument("--period", default=None)
    p.add_argument("--repo-root", default="")
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("sign", help="人门签字（who=签字人；agent 角色名拒收）")
    p.add_argument("--instance", required=True)
    p.add_argument("--who", required=True)
    p.add_argument("--decision", default="approve", choices=["approve", "reject"])
    p.add_argument("--note", default="")
    p.add_argument("--period", default=None)
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("ticket", help="巡检票只读查询（工单详情同构：阶段/状态/发现摘要）")
    p.add_argument("--instance", required=True)
    p.add_argument("--period", default=None)
    p = sub.add_parser("describe", help="查一期巡检票快照")
    p.add_argument("--instance", required=True)
    p.add_argument("--period", default=None)
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("schedule-up", help="声明→Temporal Schedule（必带 --note）")
    p.add_argument("--instance", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--decl-path", default=None)
    args = ap.parse_args()
    if not args.op:
        _emit(_err(USAGE))
        return
    try:
        if args.op == "decl":
            result = cmd_decl(args)
        else:
            result = asyncio.run({"trigger": cmd_trigger, "sign": cmd_sign,
                                  "describe": cmd_describe, "ticket": cmd_ticket, "schedule-up": cmd_schedule_up}[args.op](args))
    except Exception as e:  # noqa: BLE001 — channel-level backstop: any exception becomes single-line JSON, never a bare stack
        result = _err("inspection_trigger.%s 异常：%s: %s" % (args.op, type(e).__name__, e))
    _emit(result, exit_code=0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
