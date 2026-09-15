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
import os
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


def abs_decl_path(raw: Any) -> str:
    """声明路径归一（t260913-02 实现段实锤）：--decl-path 由调用方 cwd 解析，而 workflow
    侧的 plan 活动在 **worker 的 cwd** 里读它——相对路径会读不到（实测：drill 票
    「声明文件不可读：out/drill/decl.yaml」→ 票被 blocked）。凡随票走的路径一律先转绝对，
    与泳道路径「payload 里的路径都是绝对形」的既有约定同族（t260903-10）。"""
    txt = str(raw or "").strip()
    if not txt:
        return ""
    return str(Path(txt).expanduser().resolve())


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


def _emit(payload: Dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    if exit_code:
        sys.exit(exit_code)


def _valid_period(period: str) -> Optional[str]:
    # t260911-02：计数期=YYYYMMDD-<bucket>（与 inspection_flow.PERIOD_RE 同词法）；
    # 桶段须正整数（前导 0 拒绝——期号是去重键，形态必须规范化唯一）
    if not re.match(r"^\d{8}(-[1-9]\d*)?$", period or ""):
        return "period 非法：%r（须 YYYYMMDD 或 YYYYMMDD-<bucket>）" % period
    try:
        datetime.strptime(period.split("-")[0], "%Y%m%d")
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
                # 声明驱动：跑哪个巡检面由实例 scan_face 声明决定（缺省 test=票① 行为）
                face=str(spec.get("scan_face") or "test"),
                repo_root=args.repo_root or "",
                # 触发面校验用的声明 == workflow 运行期读的声明（两处同源；缺省空=worker 缺省）
                # 绝对化：worker 的 cwd 与调用方不同，相对路径会读不到
                decl_path=abs_decl_path(args.decl_path)),
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
    """Declaration → scheduler wiring（t260911-02 双形态）:
      - kind=cron → Temporal Schedule（现状语义不变）；
      - kind=every-n-tickets / race-first → 幂等拉起/复活计数 watcher workflow
        （id=inspection-watcher-<instance>，从声明确定导出——重跑即幂等：running 原样
        回执，非 running/不存在 → 起新 run。复活路径=KI-049 对答：可死机制必有可辨
        的拉活手段）。
    note governance (trade-off 2): --note is mandatory (both forms)."""
    if not args.note:
        return _err("schedule-up 必须带 --note（note 治理：不留无解释的常驻定时器）")
    try:
        spec = _enabled_spec(args.decl_path, args.instance)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001
        return _err("声明不可用：%s" % e)
    if spec["kind"] != "cron":
        return await _schedule_up_watcher(args, spec)
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
        tz = str(spec.get("tz") or "")

        # Try an update first (idempotent), create only if absent — after changing the
        # declaration's cron, re-running schedule-up makes it take effect.
        def _upd(inp) -> ScheduleUpdate:
            sched = inp.description.schedule
            sched.spec = ScheduleSpec(cron_expressions=[cron_expr],
                                      time_zone_name=tz or None)
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
                        InspectionPeriodicInput(
                            instance_id=spec["instance_id"], period="",
                            # t260913-02 顺手修：原实现不透传 scan_face/repo_root——
                            # docs-sync 真建调度后会跑错面（test 而非 doc）。声明面
                            # （scan_face）必须一路透传到票的输入，否则「调度在声明」
                            # 名不副实。套件开关不在此列：它由 workflow 运行期读声明
                            # （resolve_inspection_plan 活动）决定，不进 payload。
                            face=str(spec.get("scan_face") or "test"),
                            repo_root=str(args.repo_root or "")),
                        id="inspection-%s-period" % spec["instance_id"],
                        task_queue=TASK_QUEUE,
                    ),
                    spec=ScheduleSpec(cron_expressions=[cron_expr],
                                      time_zone_name=tz or None),
                    policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
                ),
            )
            mode = "created"
        desc = await handle.describe()
        return _ok({"schedule_id": schedule_id, "mode": mode, "cron": cron_expr,
                    "tz": tz or "UTC（Temporal 缺省）",
                    "overlap": "SKIP", "note": args.note, "instance": spec["instance_id"],
                    "next_action_times": [t.isoformat(timespec="seconds")
                                          for t in (desc.info.next_action_times or [])][:3]})
    except ImportError as e:
        return _err("temporalio SDK 缺失：%s（运维通道需 venv：server/engine/setup.sh）" % e)
    except Exception as e:  # noqa: BLE001
        return _err("schedule sandbar-inspection-%s 建立失败（不存在或不可达）：%s: %s"
                    % (args.instance, type(e).__name__, e))


async def _schedule_up_watcher(args: argparse.Namespace, spec: Dict[str, Any]) -> Dict[str, Any]:
    """计数 kind 的拉起/复活面（R3）：describe 探活 → running 原样回执；否则起 watcher。
    同声明重跑必命中同一 workflow id（C-2，形状单点=inspection_flow.watcher_workflow_id）。"""
    try:
        from temporalio.client import Client
        from inspection_flow import (
            InspectionTicketCountWatcherWorkflow,
            InspectionWatcherInput,
            watcher_workflow_id,
        )
        from shared import NAMESPACE, TARGET_HOST, TASK_QUEUE
        wf_id = watcher_workflow_id(spec["instance_id"])
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        handle = client.get_workflow_handle(wf_id)
        try:
            desc = await handle.describe()
            status = str(getattr(desc.status, "name", desc.status) or "")
            if "RUNNING" in status.upper() or "CONTINUED" in status.upper():
                return _ok({"schedule_id": wf_id, "mode": "already-running",
                            "status": status, "note": args.note,
                            "instance": spec["instance_id"],
                            "kind": spec["kind"], "n": spec["n"]})
            mode = "revived"
        except Exception:  # noqa: BLE001——不存在/已终态 → 起新 run（复活路径）
            mode = "created"
        await client.start_workflow(
            InspectionTicketCountWatcherWorkflow,
            InspectionWatcherInput(
                instance_id=spec["instance_id"], n=spec["n"], cron=spec["cron"],
                scan_face=str(spec.get("scan_face") or "test"),
                project_key=str(spec.get("project_key") or ""),
                repo_root=args.repo_root or "",
                # 计数形态的「两处同源」：watcher 开票时把本声明路径随票传（cron 形态
                # **不**钉路径——调度每次触发都读 worker 当前声明，改声明即改行为）
                decl_path=abs_decl_path(args.decl_path)),
            id=wf_id, task_queue=TASK_QUEUE)
        return _ok({"schedule_id": wf_id, "mode": mode, "note": args.note,
                    "instance": spec["instance_id"], "kind": spec["kind"],
                    "n": spec["n"], "cron": spec["cron"]})
    except ImportError as e:
        return _err("temporalio SDK 缺失：%s（运维通道需 venv：server/engine/setup.sh）" % e)
    except Exception as e:  # noqa: BLE001
        return _err("watcher %s 拉起失败（不存在或不可达）：%s: %s"
                    % (spec["instance_id"], type(e).__name__, e))


async def cmd_watcher(args: argparse.Namespace) -> Dict[str, Any]:
    """watcher 只读活性观测面（R3）：快照回执；不 RUNNING=非 running 状态点名
    （「死了」必须可辨——KI-049 族：死机制无人知即事故）。"""
    from temporalio.service import RPCError
    try:
        from inspection_flow import watcher_workflow_id
        wf_id = watcher_workflow_id(args.instance)
    except ValueError as e:
        return _err(str(e))
    try:
        from temporalio.client import Client
        from shared import NAMESPACE, TARGET_HOST
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        handle = client.get_workflow_handle(wf_id)
        try:
            snap = await handle.query("snapshot")
            desc = await handle.describe()
            status = str(getattr(desc.status, "name", desc.status) or "")
        except RPCError as e:
            return _err("watcher %s（实例 %s）不存在或未拉起（RPC %s）——schedule-up 可复活；"
                        "查无此票≠连不上" % (wf_id, args.instance, type(e).__name__))
        if not isinstance(snap, dict):
            return _err("watcher %s 无快照（状态=%s）——查无此票≠连不上" % (wf_id, status))
        return _ok({"watcher_id": wf_id, "status": status, "snapshot": snap})
    except ImportError as e:
        return _err("temporalio SDK 缺失：%s" % e)
    except Exception as e:  # noqa: BLE001
        return _err("temporal 不可达（查询 %s 失败）：%s: %s" % (wf_id, type(e).__name__, e))


async def cmd_deadman(args: argparse.Namespace) -> Dict[str, Any]:
    """漏跑（dead-man）查询面（t260913-02 验收 D 的列表可读面）：
    声明 cron 的期望触发日 × 巡检台账（out/inspection/，SANDBAR_INSPECTION_DIR 可覆盖）
    → 漏跑期号清单；可达时顺带取 Temporal Schedule 的 next_run（「下次该跑」也要能看见）。

    退出码：漏跑非空 = 1（ops 自动化可踩），否则 0——但 stdout 恒为单行 JSON
    {ok, result|error}（本通道既有契约不变：ok=False 只表示「查不了」）。
    离线也可用（--offline 不连 Temporal）：隔离台/注入演练不依赖服务器。"""
    from inspection_deadman import deadman_findings, ledger_periods, missed_periods
    try:
        decl = load_inspection_decl(args.decl_path) if args.decl_path else load_inspection_decl()
    except Exception as e:  # noqa: BLE001——声明不可用=ok False 点名（不猜）
        return _err("声明不可用：%s" % e)
    it = decl.instance(args.instance)
    if it is None:
        return _err("实例 %r 未在声明中（在册：%s）"
                    % (args.instance, "、".join(i.id for i in decl.instances)))
    if it.kind != "cron":
        return _err("实例 %r 的调度 kind=%r 不是 cron（漏跑核查只对 cron 期有定义）"
                    % (args.instance, it.kind))
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _default_ledger_dir()
    try:
        ledger = ledger_periods(ledger_dir, args.instance)
        missed = missed_periods(it.cron, ledger["periods"], None,
                                int(args.lookback_days), int(args.grace_days),
                                it.tz)
    except ValueError as e:            # cron 不可解析 → 点名（不静默当没漏）
        return _err("漏跑判定失败（实例 %s，cron=%r）：%s" % (args.instance, it.cron, e))
    except Exception as e:  # noqa: BLE001
        return _err("漏跑核查异常：%s: %s" % (type(e).__name__, e))
    result: Dict[str, Any] = {
        "instance": args.instance, "cron": it.cron, "enabled": it.enabled,
        "suite": it.suite, "ledger_dir": str(ledger_dir),
        "ledger_exist": ledger["exist"], "ledger_periods": sorted(ledger["periods"]),
        "last_ledger_period": max(ledger["periods"]) if ledger["periods"] else "",
        "lookback_days": int(args.lookback_days), "grace_days": int(args.grace_days),
        "tz": it.tz,
        "missed": missed, "alarmed": bool(missed),
        "malformed": ledger["malformed"],
        "findings": deadman_findings(missed, args.instance, it.cron, int(args.lookback_days)),
        "schedule": {"checked": False},
    }
    if args.offline:
        result["schedule"] = {"checked": False, "reason": "--offline"}
        return _ok(result)
    try:
        from temporalio.client import Client
        from shared import NAMESPACE, TARGET_HOST
        c = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        h = c.get_schedule_handle("sandbar-inspection-%s" % args.instance)
        try:
            d = await h.describe()
        except Exception as e:  # noqa: BLE001——查无此 schedule 要精确点名（≠连不上）
            result["schedule"] = {"checked": True, "exists": False,
                                  "error": "schedule 不存在或不可达（RPC %s）——schedule-up 可建"
                                           % type(e).__name__}
            return _ok(result)
        info = d.info
        result["schedule"] = {
            "checked": True, "exists": True,
            "next_action_times": [t.isoformat(timespec="seconds")
                                  for t in (getattr(info, "next_action_times", None) or [])][:3],
            "recent_actions": [{"scheduled_at": str(getattr(a, "scheduled_at", "")),
                                "status": str(getattr(a, "start_workflow_status", ""))}
                               for a in (getattr(info, "recent_actions", None) or [])][:3],
            "num_actions": getattr(info, "num_actions", None),
            "note": getattr(info, "note", ""),
        }
    except ImportError as e:
        result["schedule"] = {"checked": False, "error": "temporalio SDK 缺失：%s" % e}
    except Exception as e:  # noqa: BLE001——查不了调度面不遮蔽漏跑结论（各自分开报）
        result["schedule"] = {"checked": False, "error": "%s: %s" % (type(e).__name__, e)}
    return _ok(result)


def _default_ledger_dir() -> Path:
    """台账目录默认值（与 shared.INSPECTION_DIR 同口径：server/engine/out/inspection，
    env SANDBAR_INSPECTION_DIR 覆盖）——不 import shared，decl/deadman 子命令保持零
    temporalio 依赖（既有纪律）；同口径由单测锁（test_deadman_default_ledger_matches_shared）。"""
    env = os.environ.get("SANDBAR_INSPECTION_DIR") or ""
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "out" / "inspection"



def cmd_sweep_lanes(args: argparse.Namespace) -> Dict[str, Any]:
    """人工清场入口（t260913-02）：删本实例命名空间里**早于水位**的巡检 worktree/分支
    残留（崩溃/取消路径的兜底；setup 前置也走同一实现，不新造第二套）。

    需 temporalio 环境（复用 agent_activities 的同步实现）；--keep-period 空=无水位（全清，
    人工显式使用）；开发泳道与别的实例一律不碰（决策在 inspection_flow.sweep_plan）。"""
    try:
        from agent_activities import sweep_inspection_lanes_impl
    except Exception as e:  # noqa: BLE001
        return _err("清扫实现不可用（需 venv：server/engine/setup.sh）：%s: %s"
                    % (type(e).__name__, e))
    return sweep_inspection_lanes_impl(
        {"instance_id": args.instance, "repo_root": args.repo_root or "",
         "keep_period": args.keep_period or "",
         "remove_period": getattr(args, "remove_period", "") or ""})


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
                       "cron": i.cron, "n": i.n, "source": i.source,
                       "project_key": i.project_key, "scan_face": i.scan_face,
                       "suite": i.suite, "tz": i.tz,
                       "workflow": i.workflow, "template": i.template}
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
    p = sub.add_parser("watcher", help="计数 watcher 只读活性观测（快照回执）")
    p.add_argument("--instance", required=True)
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("schedule-up", help="声明→调度器接线（cron→Schedule；计数 kind→watcher，必带 --note）")
    p.add_argument("--instance", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--repo-root", default="")
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("deadman", help="漏跑核查（列表可读面；missed 非空 exit=1）")
    p.add_argument("--instance", required=True)
    p.add_argument("--ledger-dir", default=None,
                   help="台账目录（缺省 out/inspection；env SANDBAR_INSPECTION_DIR 覆盖）")
    p.add_argument("--lookback-days", default=7)
    p.add_argument("--grace-days", default=0)
    p.add_argument("--offline", action="store_true", help="不连 Temporal（只查声明+台账）")
    p.add_argument("--decl-path", default=None)
    p = sub.add_parser("sweep-lanes", help="人工清巡检泳道残留（早于水位；开发泳道不碰）")
    p.add_argument("--instance", required=True)
    p.add_argument("--keep-period", default="", help="水位期号；空=无水位（全清）")
    p.add_argument("--remove-period", default="", help="定向模式：只清恰好等于该期号的条目（忽略水位）")
    p.add_argument("--repo-root", default="")
    args = ap.parse_args()
    if not args.op:
        _emit(_err(USAGE))
        return
    try:
        if args.op == "decl":
            result = cmd_decl(args)
        elif args.op == "sweep-lanes":
            result = cmd_sweep_lanes(args)
        else:
            result = asyncio.run({"trigger": cmd_trigger, "sign": cmd_sign,
                                  "describe": cmd_describe, "ticket": cmd_ticket,
                                  "watcher": cmd_watcher, "deadman": cmd_deadman,
                                  "schedule-up": cmd_schedule_up}[args.op](args))
    except Exception as e:  # noqa: BLE001 — channel-level backstop: any exception becomes single-line JSON, never a bare stack
        result = _err("inspection_trigger.%s 异常：%s: %s" % (args.op, type(e).__name__, e))
    _emit(result, exit_code=0 if result.get("ok") else 1)
    # deadman 的告警语义：missed 非空=exit 1（数据仍在 stdout 单行 JSON 里；与
    # 「查不了」（ok=False→exit 1）共用退出码 1 但靠 ok 字段区分，不混两个事实）
    if result.get("ok") and isinstance(result.get("result"), dict) \
            and result["result"].get("alarmed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
