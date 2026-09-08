#!/usr/bin/env python3
"""inspection_trigger —— 巡检调度运维通道（inspection epic 票①，t260905-03）。

定位（照搬 scan_schedule.py 运维通道取舍清单②③）：本工具是**人/总管的运维通道**，
不进 dsh 模型工具面——模型侧对巡检调度的可见性只读，防模型侧随意触发破坏每期一票。

照搬取舍清单（review_plan R2 六项逐项）：
  ① overlap：SKIP（同实例同期重复触发合并为一张票——票号=workflow id 幂等，
     AlreadyStarted 即 deduped；schedule 层再叠 SKIP，撞期不另开）。
  ② note 治理：schedule-up 必带 --note（谁、为什么、什么频率），进 schedule state 可查。
  ③ 运维通道定位：不进 dsh 模型工具面（见上）。
  ④ stdout 单行 JSON {ok, result|error}（与 client.py/scan_schedule.py 同契约）。
  ⑤ 报错精确：RPCError 显式转译「…不存在或不可达」，不静默。
  ⑥ 参数区间 fail-closed：instance 须命中声明**已启用**实例（未启用=显式报错，先于
     任何网络动作）；period 须 YYYYMMDD 且为真实日历日；decision 只认 approve/reject；
     who 非空且不得是 agent 角色名（签字只能人）。

声明驱动（验收③行为级）：触发面只消费 build_schedule_specs 的输出——声明里
enabled=false 的实例在 specs 中不存在，trigger/schedule-up 对它一律显式报错；
改声明即改行为，不改引擎码。

用法（venv python 或任一装了 temporalio 的解释器；decl 子操作零依赖纯标准库）：
    inspection_trigger.py decl [--decl-path P]
    inspection_trigger.py trigger --instance test-face [--period YYYYMMDD] [--repo-root R]
    inspection_trigger.py sign --instance test-face --who 用户 [--decision approve|reject] [--note 文本] [--period P]
    inspection_trigger.py describe --instance test-face [--period P]
    inspection_trigger.py schedule-up --instance test-face --note 文本
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
    """声明 → 该实例的调度意图；未启用/未声明一律显式报错（fail-closed 先于网络）。"""
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
# 服务端动作（temporalio 延迟导入：decl 子操作零依赖可跑，也供场景道 stdlib 复用）
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
    except Exception as e:  # noqa: BLE001——声明解析 fail-closed 转译
        return _err("声明不可用：%s" % e)
    InspectionPeriodicInput, ticket_id_of, _, _, _, task_queue = _lazy_engine()
    ticket_id = ticket_id_of(args.instance, period)
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001——连接故障显式点名（取舍⑤精神，不静默）
        return _err("temporal server 不可达：%s" % e)
    from temporalio.service import RPCError
    try:
        handle = await client.start_workflow(
            spec["workflow"],
            InspectionPeriodicInput(
                instance_id=args.instance, face=spec["face"], period=period,
                repo_root=args.repo_root or ""),
            id=ticket_id, task_queue=task_queue)
        return _ok({"triggered": True, "ticket_id": ticket_id, "period": period,
                    "workflow": spec["workflow"], "instance": args.instance,
                    "first_run_id": handle.first_execution_run_id})
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "WorkflowAlreadyStartedError" or "already started" in str(e).lower():
            # 取舍①：同票号重复触发=同票去重（每期一票的机械保证）
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
    """声明 → Temporal Schedule（通用调度器的接线动作；行为随声明，不改引擎码）。
    note 治理（取舍②）：必带 --note。"""
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

        # 先试更新（幂等），不存在再创建——改声明（cron）后重跑 schedule-up 即生效。
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
                        InspectionPeriodicInput(instance_id=spec["instance_id"], face=spec["face"], period=""),
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
    """离线声明视图（零 temporalio 依赖；声明驱动的解析级证据面）。"""
    try:
        decl = load_inspection_decl(args.decl_path) if args.decl_path else load_inspection_decl()
    except Exception as e:  # noqa: BLE001——DeclError/IO 一律单行 JSON 显式报错
        return _err("声明不可用：%s" % e)
    return _ok({
        "source": decl.source,
        "schema": decl.schema,
        "instances": [{"id": i.id, "face": i.face, "enabled": i.enabled, "kind": i.kind,
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
                                  "describe": cmd_describe, "schedule-up": cmd_schedule_up}[args.op](args))
    except Exception as e:  # noqa: BLE001——通道级兜底：任何异常都转单行 JSON，不裸栈
        result = _err("inspection_trigger.%s 异常：%s: %s" % (args.op, type(e).__name__, e))
    _emit(result, exit_code=0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
