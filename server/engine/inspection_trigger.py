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
    coverage_decl_path,
    default_decl_path,
    enabled_instance_whitelist,
    iter_project_decls,
    load_decl_for_instance,
    load_inspection_decl,
)
from shared import list_registered_projects  # noqa: E402

USAGE = ("用法：inspection_trigger.py <decl|trigger|sign|describe|schedule-up> …\n"
         "运维通道（不进模型工具面）；每期一票：按（实例,期号）显式去重，票号=工单号形式 "
         "t<YYMMDD>-<NN>，重复触发返回既有票号。")


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
    """声明 → 该实例的调度意图（t260916-02 起声明来源三层：显式 --decl-path（场景注入）
    > env 测试覆盖层（单文件）> 项目注册表聚合（生产路径——遍历注册项目找到定义本实例
    的那份声明）；not enabled / 不在任何项目声明中一律显式报错（网络动作前 fail-closed）。"""
    explicit = str(decl_path or "").strip() or coverage_decl_path()
    if explicit:
        decl = load_inspection_decl(Path(explicit))
        if decl.instance(instance_id) is None:
            raise ValueError("实例 %r 未在声明中（在册：%s）"
                             % (instance_id, "、".join(i.id for i in decl.instances)))
    else:
        decl, _project_key = load_decl_for_instance(instance_id)
    spec = next((s for s in build_schedule_specs(decl) if s["instance_id"] == instance_id), None)
    if spec is None:
        raise ValueError("实例 %r 在声明中未启用（enabled=false 不触发）；已启用：%s——改声明即改行为"
                         % (instance_id, "、".join(i.id for i in decl.enabled_instances()) or "无"))
    return spec


def resolve_repo_root(spec: Dict[str, Any], explicit_repo_root: str) -> str:
    """巡检 repo_root 解析（t260915-20，三分支 precedence，纯面单测友好）：
      ① explicit 非空 → 原样（--repo-root 显式旁路：隔离台/运维场景夹具全靠它，不触注册表）；
      ② 否则按实例级身份 spec["instance_project_key"] 经 shared.resolve_project_root
         解析注册条目主目录（dirs[0]）——未知 key 在此显式爆（错误点名注册表语境）；
      ③ 两者皆无 → ValueError（防御性：解析层已把实例身份设为必填，正常不可达；
         可达即说明旁路起票绕过了声明面，绝不静默回落引擎仓）。
    返回 str（起票 payload 面一律字符串路径，与既有 repo_root 语义同形）。"""
    explicit = str(explicit_repo_root or "").strip()
    if explicit:
        return explicit
    identity = str((spec or {}).get("instance_project_key") or "").strip()
    if not identity:
        raise ValueError("实例 %r 无项目身份且未给 --repo-root：repo_root 无解析依据"
                         "（无项目身份的巡检=无主票，绝不静默回落引擎仓）"
                         % (spec or {}).get("instance_id", "?"))
    from shared import resolve_project_root
    return str(resolve_project_root(identity))


# ========================================================================================
# Server-side actions (temporalio imported lazily: the decl subcommand runs with zero
# dependencies and stays reusable by the scenario lane's stdlib)
# ========================================================================================

def _lazy_engine():
    from inspection_flow import CLOSE_GATE_ID, InspectionPeriodicInput
    from shared import NAMESPACE, TARGET_HOST, TASK_QUEUE
    return InspectionPeriodicInput, CLOSE_GATE_ID, TARGET_HOST, NAMESPACE, TASK_QUEUE


async def _connect():
    from temporalio.client import Client
    _, _, target, namespace, _tq = _lazy_engine()
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
    # 实例级项目身份（t260915-20）：起票三真源同值——payload project_key、
    # ProjectKey SA（工单板项目过滤/行 project 的真源）、repo_root 注册表解析。
    project_key = str(spec.get("instance_project_key") or "")
    try:
        repo_root = resolve_repo_root(spec, args.repo_root)
    except ValueError as e:
        return _err(str(e))
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001 — connection failures are named explicitly (the spirit of trade-off 5, never silent)
        return _err("temporal server 不可达：%s" % e)
    # t260916-02：起票收敛到 open_period_ticket 单点——铸 t 形工单号 + 显式去重
    # （实例+期号 SA 查询 / 指针三态 / AlreadyStarted 归属判定）+ 盖 ProjectKey 与
    # InspectionInstance/InspectionPeriod SA。本壳只做声明校验与回执拼装。
    from shared import TASK_QUEUE  # noqa: E402——本函数局部导入（同 _lazy_engine 模式；arbitrate gen2 缺陷①：漏导入=CLI trigger 主路径 NameError）
    from inspection_ticketing import open_period_ticket
    res = await open_period_ticket(
        client, instance_id=args.instance, period=period, project_key=project_key,
        repo_root=repo_root, scan_face=str(spec.get("scan_face") or "test"),
        decl_path=abs_decl_path(args.decl_path), task_queue=TASK_QUEUE)
    if not res.get("ok"):
        return res
    r = dict(res["result"] or {})
    r.update({"period": period, "workflow": spec["workflow"],
              "instance": args.instance, "project": project_key,
              "repo_root": repo_root})
    return _ok(r)


async def cmd_trigger_produce(args: argparse.Namespace) -> Dict[str, Any]:
    """产出型巡检手动触发（t260925-01）：与 cmd_trigger 同一声明校验与起票单点，
    两处差异——workflow=InspectionProduceWorkflow；队列=per-ticket（KI-113 口径，
    产出型链不落共享队列）。"""
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    try:
        spec = _enabled_spec(args.decl_path, args.instance)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001
        return _err("声明不可用：%s" % e)
    project_key = str(spec.get("instance_project_key") or "")
    try:
        repo_root = resolve_repo_root(spec, args.repo_root)
    except ValueError as e:
        return _err(str(e))
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001
        return _err("temporal server 不可达：%s" % e)
    from inspection_ticketing import open_produce_period_ticket
    res = await open_produce_period_ticket(
        client, instance_id=args.instance, period=period, project_key=project_key,
        repo_root=repo_root, scan_face=str(spec.get("scan_face") or "doc"),
        decl_path=abs_decl_path(args.decl_path))
    if not res.get("ok"):
        return res
    r = dict(res["result"] or {})
    r.update({"period": period, "workflow": "InspectionProduceWorkflow",
              "instance": args.instance, "project": project_key,
              "repo_root": repo_root, "queue": "per-ticket"})
    return _ok(r)


async def cmd_sign(args: argparse.Namespace) -> Dict[str, Any]:
    from inspection_flow import CLOSE_GATE_ID, validate_close_signature
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
    payload, verr = validate_close_signature(
        {"who": args.who or "", "gate": CLOSE_GATE_ID, "decision": args.decision, "note": args.note or ""},
        expected_gate=CLOSE_GATE_ID)
    if verr:
        return _err(verr)
    # t260916-02：票号不再由（实例,期）铸造——SA 查询解析既有票号（legacy 只读探测兜
    # 过渡窗旧形票，见 inspection_ticketing.resolve_period_ticket_id）
    from inspection_ticketing import resolve_period_ticket_id
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001
        return _err("temporal server 不可达：%s" % e)
    found = await resolve_period_ticket_id(client, args.instance, period)
    if not found.get("ok"):
        return _err("签字失败：%s" % found.get("error"))
    ticket_id = str(found["ticket_id"])
    try:
        from shared import Signature
        handle = client.get_workflow_handle(ticket_id)
        await handle.signal("sign", Signature(
            who=payload["who"], gate=CLOSE_GATE_ID, decision=payload["decision"], note=payload["note"]))
        snap = await handle.query("snapshot")
        return _ok({"signed": True, "ticket_id": ticket_id, "decision": payload["decision"],
                    "who": payload["who"], "ticket_source": found.get("source"),
                    "status": (snap or {}).get("status")})
    except Exception as e:  # noqa: BLE001
        return _err("巡检票 %s 签字失败（不存在或不可达）：%s: %s" % (ticket_id, type(e).__name__, e))


def _verdict_ledger_face(ledger_dir: Path, instance: str, period: str) -> Path:
    """台账票面文件路径（与 write_inspection_report_impl 同名约定，只读复算）。"""
    from inspection_flow import inspection_ledger_name
    return ledger_dir / inspection_ledger_name(instance, period)


async def cmd_verdict(args: argparse.Namespace) -> Dict[str, Any]:
    """发现级裁定（t260916-22 要点⑥）：人对单条发现标 假报/待修/存疑。

    两分支（回执带 mode 供场景断言）：
      - signal：票在途（running）→ workflow signal finding_verdict（票内面：timeline
        + findings[].verdict；verdicts 台账由收口段一次写齐）；
      - ledger：票已收口（closed/blocked）或查无在途票或显式 --offline → 直改台账
        票面 JSON（findings[].verdict 原位改写）+ verdicts 台账追加（dedupe 幂等，
        跨期假报压制消费的就是它）。
    载荷校验复用票面闸纯函数（who 非空/≤64/agent 名拒收/gate/verdict 词表含中文
    别名）——两分支同一套校验，机器不得裁定。"""
    from inspection_flow import (CLOSE_GATE_ID, MAX_WHO_LEN, validate_finding_verdict_payload)
    from inspection_inspect import (append_verdict_entry, verdicts_ledger_name)
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    payload, verr = validate_finding_verdict_payload(
        {"gate": CLOSE_GATE_ID, "finding_id": args.finding_id or "",
         "verdict": args.verdict or "", "who": args.who or "", "note": args.note or ""},
        expected_gate=CLOSE_GATE_ID)
    if verr:
        return _err(verr)

    ledger_dir = _default_ledger_dir()
    ticket_id = ""
    snap: Dict[str, Any] = {}
    if not args.offline:
        from inspection_ticketing import resolve_period_ticket_id
        try:
            client = await _connect()
        except Exception as e:  # noqa: BLE001
            return _err("temporal server 不可达（--offline 可直改台账）：%s" % e)
        found = await resolve_period_ticket_id(client, args.instance, period)
        if found.get("ok"):
            ticket_id = str(found["ticket_id"])
            try:
                snap = await client.get_workflow_handle(ticket_id).query("snapshot") or {}
            except Exception as e:  # noqa: BLE001
                return _err("巡检票 %s 快照不可读：%s: %s" % (ticket_id, type(e).__name__, e))

    status = str(snap.get("status") or "")
    if status == "running":
        # ---- 票在途：signal（票内面；台账收口时写齐） ----
        try:
            from inspection_flow import FindingVerdict
            handle = client.get_workflow_handle(ticket_id)
            await handle.signal("finding_verdict", FindingVerdict(
                gate=CLOSE_GATE_ID, finding_id=payload["finding_id"],
                verdict=payload["verdict"], who=payload["who"], note=payload["note"]))
            snap2 = await handle.query("snapshot") or {}
            face2 = snap2.get("face") if isinstance(snap2.get("face"), dict) else {}
            findings2 = face2.get("findings") if isinstance(face2.get("findings"), list) else []
            hit = next((f for f in findings2 if isinstance(f, dict)
                        and str(f.get("id") or "") == payload["finding_id"]), None)
            if hit is None or hit.get("verdict") != payload["verdict"]:
                return _err("裁定未落票（finding-id 不在清单或载荷被拒）：%s｜gate_error=%s"
                            % (payload["finding_id"], face2.get("human_gate") is not None
                               and snap2.get("gate_error") or snap2.get("gate_error")))
            return _ok({"verdicted": True, "mode": "signal", "ticket_id": ticket_id,
                        "finding_id": payload["finding_id"],
                        "verdict": payload["verdict"], "who": payload["who"]})
        except Exception as e:  # noqa: BLE001
            return _err("巡检票 %s 裁定 signal 失败：%s: %s" % (ticket_id, type(e).__name__, e))

    # ---- 台账分支（已收口 / 查无在途票 / --offline） ----
    face_path = _verdict_ledger_face(ledger_dir, args.instance, period)
    if not face_path.is_file():
        return _err("台账票面不存在：%s（无票可裁定；期号/实例核对）" % face_path)
    try:
        doc = json.loads(face_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _err("台账票面不可读（%s）：%s: %s" % (face_path, type(e).__name__, e))
    if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
        return _err("台账票面形状坏（缺 findings 列表）：%s" % face_path)
    from inspection_inspect import apply_verdict_to_face
    err = apply_verdict_to_face(doc, payload["finding_id"], payload["verdict"],
                                payload["who"], payload["note"])
    if err:
        return _err("裁定未落：%s" % err)
    face_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    vpath = ledger_dir / verdicts_ledger_name(args.instance, period)
    append_verdict_entry(vpath, {
        "finding_id": payload["finding_id"], "verdict": payload["verdict"],
        "who": payload["who"], "note": payload["note"],
        "source_ticket": str(doc.get("ticket_id") or ticket_id or ""),
        "mode": "ledger"}, dedupe=True)
    return _ok({"verdicted": True, "mode": "ledger", "face_path": str(face_path),
                "verdicts_path": str(vpath), "finding_id": payload["finding_id"],
                "verdict": payload["verdict"], "who": payload["who"]})


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
        # 票归属项目（t260915-20）：payload 侧真源（起票面写入 input.project_key），
        # 与 SA 各自独立——两真源同值由集成场景钉住，此处如实透传不编造
        "project": str(snap.get("project") or ""),
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
    from inspection_ticketing import resolve_period_ticket_id
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001——连接失败精确翻译，不谎报票不存在
        return _err("temporal 不可达：%s: %s" % (type(e).__name__, e))
    found = await resolve_period_ticket_id(client, args.instance, period)
    if not found.get("ok"):
        return _err(str(found.get("error")))
    ticket_id = str(found["ticket_id"])
    try:
        handle = client.get_workflow_handle(ticket_id)
        snap = await handle.query("snapshot")
    except RPCError as e:
        return _err("巡检票 %s（实例 %s 期 %s）不存在或未开（RPC %s）——查无此票≠连不上"
                    % (ticket_id, args.instance, period, type(e).__name__))
    except Exception as e:  # noqa: BLE001——连接失败精确翻译，不谎报票不存在
        return _err("temporal 不可达（查询 %s 失败）：%s: %s" % (ticket_id, type(e).__name__, e))
    if not isinstance(snap, dict):
        return _err("巡检票 %s（实例 %s 期 %s）无快照——查无此票≠连不上" % (ticket_id, args.instance, period))
    receipt = ticket_receipt(snap, ticket_id)
    receipt["ticket_source"] = found.get("source")
    return _ok(receipt)


async def cmd_describe(args: argparse.Namespace) -> Dict[str, Any]:
    from inspection_ticketing import resolve_period_ticket_id
    period = args.period or datetime.now().strftime("%Y%m%d")
    err = _valid_period(period)
    if err:
        return _err(err)
    try:
        client = await _connect()
    except Exception as e:  # noqa: BLE001
        return _err("temporal server 不可达：%s" % e)
    found = await resolve_period_ticket_id(client, args.instance, period)
    if not found.get("ok"):
        return _err(str(found.get("error")))
    ticket_id = str(found["ticket_id"])
    try:
        handle = client.get_workflow_handle(ticket_id)
        snap = await handle.query("snapshot")
        if snap is None:
            return _err("巡检票 %s 无快照（不存在或不可达）" % ticket_id)
        result: Dict[str, Any] = {"ticket_id": ticket_id, "ticket_source": found.get("source"),
                                  "snapshot": snap}
        # 迁移自检面（t260915-20 §5.1）：在册 cron 调度的 action 摘要——payload 的
        # project_key/repo_root 有无 + SA ProjectKey 值。查不到/非 cron 形态=显式
        # error 字段，不阻塞票快照本体（票面真源优先）。
        result["schedule_action"] = await _schedule_action_summary(client, args.instance)
        return _ok(result)
    except Exception as e:  # noqa: BLE001
        return _err("巡检票 %s 查询失败（不存在或不可达）：%s: %s" % (ticket_id, type(e).__name__, e))


async def _schedule_action_summary(client: Any, instance_id: str) -> Dict[str, Any]:
    """在册调度 action 摘要（尽力而为面，t260915-20；t260916-02 认 spawner action）：
    无调度/SDK 缺失/形状不合都显式落 error 字段——迁移自检「action 指没指 spawner /
    带没带新 payload/SA」靠它可读，绝不静默。action 仍是旧直发 workflow（未重跑
    schedule-up）→ error 点名旧形票号残留与刷新入口。"""
    out: Dict[str, Any] = {"schedule_id": "sandbar-inspection-%s" % instance_id}
    try:
        handle = client.get_schedule_handle(out["schedule_id"])
        desc = await handle.describe()
        action = desc.schedule.action
        wf_name = str(getattr(action, "workflow", "") or "")
        args_list = list(getattr(action, "args", None) or [])
        inp = args_list[0] if args_list else None
        out.update({
            "workflow": wf_name,
            "instance_id": str(getattr(inp, "instance_id", "") or ""),
            "face": str(getattr(inp, "face", "") or ""),
            "project_key": str(getattr(inp, "project_key", "") or ""),
            "repo_root": str(getattr(inp, "repo_root", "") or ""),
        })
        if wf_name != "InspectionPeriodicSpawnWorkflow":
            out["error"] = ("action 仍直发 %s（旧形固定 id——票号残留旧形状）：重跑 "
                            "schedule-up --instance %s --note <…> 重铸 action 到 spawner"
                            % (wf_name or "未知", instance_id))
        sa_val = ""
        for pair in (getattr(action, "typed_search_attributes", None) or []):
            if str(getattr(getattr(pair, "key", None), "name", "")) == "ProjectKey":
                sa_val = str(getattr(pair, "value", "") or "")
                break
        out["sa_project_key"] = sa_val
        if wf_name and not out["project_key"] and not out["sa_project_key"]:
            out["error"] = "action 无 project_key/SA（旧调度未刷新）——重跑 schedule-up（update 分支重铸 action）"
    except Exception as e:  # noqa: BLE001——无调度/不可达如实点名（自检面不阻塞票快照）
        out["error"] = "调度 action 摘要不可得：%s: %s" % (type(e).__name__, e)
    return out


def _schedule_action(spec: Dict[str, Any], task_queue: str, explicit_repo_root: str = ""):
    """调度 action 单点 builder（t260915-20 R1 修复核心；t260916-02 改指 spawner）：
    ScheduleActionStartWorkflow + InspectionPeriodicSpawnWorkflow（face/repo_root/
    project_key 全部从声明 spec 决议）+ ProjectKey typed SA。

    为什么是 spawner：Schedule 的 action 参数是静态的，铸不了「起票瞬间分配」的
    t 形工单号——spawner（id=inspection-spawn-<实例>，固定，重叠 SKIP 同现状）每 fire
    起 activity 铸号+显式去重+起真票。期号/票号/声明决议全部延迟到起票时刻，旧 action
    的固定 id 撞号去重语义由（实例,期）显式去重承接。

    **create 与 update 两分支共用本函数**——update 分支同样重铸 sched.action（旧实现
    只改 spec/policy 不碰 action，重跑 schedule-up 刷不了 payload/SA，t260913-02
    同族坑的一般化：payload 面单点，两分支不再各写一份）。
    explicit_repo_root=schedule-up 的 --repo-root（显式旁路优先，隔离台/运维用）。"""
    from temporalio.client import ScheduleActionStartWorkflow
    from inspection_flow import InspectionPeriodicSpawnWorkflow, InspectionSpawnInput, spawn_workflow_id
    from shared import ticket_search_attributes
    identity = str(spec.get("instance_project_key") or "")
    return ScheduleActionStartWorkflow(
        InspectionPeriodicSpawnWorkflow,
        InspectionSpawnInput(
            instance_id=spec["instance_id"],
            # scan_face 声明透传（t260913-02）；repo_root 注册表解析（t260915-20，
            # --repo-root 显式旁路优先）+ 实例级项目身份进 payload（t260915-20）
            face=str(spec.get("scan_face") or "test"),
            repo_root=resolve_repo_root(spec, explicit_repo_root),
            project_key=identity),
        id=spawn_workflow_id(spec["instance_id"]),
        task_queue=task_queue,
        # ProjectKey SA（t260915-20）：spawner 本体带归属（真票的 SA 由开票单点盖全套）
        typed_search_attributes=ticket_search_attributes(identity, ""))


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
            ScheduleOverlapPolicy,
            SchedulePolicy,
            ScheduleSpec,
            ScheduleUpdate,
        )
        from temporalio.service import RPCError
        from shared import NAMESPACE, TARGET_HOST, TASK_QUEUE
        from temporalio.client import Client
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        schedule_id = "sandbar-inspection-%s" % spec["instance_id"]
        handle = client.get_schedule_handle(schedule_id)
        cron_expr = spec["cron"]
        tz = str(spec.get("tz") or "")

        # Try an update first (idempotent), create only if absent — after changing the
        # declaration's cron, re-running schedule-up makes it take effect.
        # t260915-20 R1：update 分支同步**重铸 action**（新 payload+SA）——两分支共用
        # _schedule_action 单点，create/update 无分叉；修复前重跑 schedule-up 刷不了
        # 已建调度的 payload/SA（迁移硬前提，见 README 迁移步）。
        def _upd(inp) -> ScheduleUpdate:
            sched = inp.description.schedule
            sched.spec = ScheduleSpec(cron_expressions=[cron_expr],
                                      time_zone_name=tz or None)
            sched.policy = SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)
            sched.action = _schedule_action(spec, TASK_QUEUE, args.repo_root)
            return ScheduleUpdate(schedule=sched)

        try:
            await handle.update(_upd)
            await handle.unpause(note=args.note)
            mode = "updated"
        except RPCError:
            await client.create_schedule(
                schedule_id,
                Schedule(
                    action=_schedule_action(spec, TASK_QUEUE, args.repo_root),
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
                    "project": str(spec.get("instance_project_key") or ""),
                    "repo_root": resolve_repo_root(spec, args.repo_root),
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
        # t260915-20 R2：instance_project_key=实例级身份（≠schedule.project_key 计数源
        # 键——两 key 分叉时 SA/票面必须归身份键，串键回归单测钉住）；repo_root 与
        # cron 形态同一条解析链（--repo-root 显式旁路优先，否则按身份解析注册表主目录），
        # 起 watcher 时刻解析定死——watcher 开票 args 原样透传，不再缺省引擎仓。
        watcher_repo_root = resolve_repo_root(spec, args.repo_root)
        await client.start_workflow(
            InspectionTicketCountWatcherWorkflow,
            InspectionWatcherInput(
                instance_id=spec["instance_id"], n=spec["n"], cron=spec["cron"],
                scan_face=str(spec.get("scan_face") or "test"),
                project_key=str(spec.get("project_key") or ""),
                instance_project_key=str(spec.get("instance_project_key") or ""),
                repo_root=watcher_repo_root,
                # 计数形态的「两处同源」：watcher 开票时把本声明路径随票传（cron 形态
                # **不**钉路径——调度每次触发都读 worker 当前声明，改声明即改行为）
                decl_path=abs_decl_path(args.decl_path)),
            id=wf_id, task_queue=TASK_QUEUE)
        return _ok({"schedule_id": wf_id, "mode": mode, "note": args.note,
                    "instance": spec["instance_id"], "kind": spec["kind"],
                    "project": str(spec.get("instance_project_key") or ""),
                    "repo_root": watcher_repo_root,
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


def _resolve_decl(decl_path: Optional[Path], instance_id: str) -> Any:
    """声明定位三层（t260916-02）：显式 --decl-path > env 测试覆盖层（单文件）> 项目
    注册表聚合（load_decl_for_instance，返回 (decl, 定义它的项目 key)）。
    deadman 用它——enabled 只是不该触发，台账口径对 disabled 实例照旧成立，不过滤；
    trigger/schedule-up 用 _enabled_spec（enabled 闸在它）。"""
    explicit = str(decl_path or "").strip() or coverage_decl_path()
    if explicit:
        return load_inspection_decl(Path(explicit)), ""
    return load_decl_for_instance(instance_id)


async def cmd_deadman(args: argparse.Namespace) -> Dict[str, Any]:
    """漏跑（dead-man）查询面（t260913-02 验收 D 的列表可读面）：
    声明 cron 的期望触发日 × 巡检台账（out/inspection/，SANDBAR_INSPECTION_DIR 可覆盖）
    → 漏跑期号清单；可达时顺带取 Temporal Schedule 的 next_run（「下次该跑」也要能看见）。

    退出码：漏跑非空 = 1（ops 自动化可踩），否则 0——但 stdout 恒为单行 JSON
    {ok, result|error}（本通道既有契约不变：ok=False 只表示「查不了」）。
    离线也可用（--offline 不连 Temporal）：隔离台/注入演练不依赖服务器。"""
    from inspection_deadman import (deadman_findings, ledger_periods, missed_periods,
                                    skip_findings)
    try:
        decl, decl_project = _resolve_decl(args.decl_path, args.instance)
    except ValueError as e:  # noqa: BLE001——声明不可用=ok False 点名（不猜）
        return _err(str(e))
    except Exception as e:  # noqa: BLE001
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
        "decl_project": decl_project,
        "suite": it.suite, "ledger_dir": str(ledger_dir),
        "ledger_exist": ledger["exist"], "ledger_periods": sorted(ledger["periods"]),
        "last_ledger_period": max(ledger["periods"]) if ledger["periods"] else "",
        "lookback_days": int(args.lookback_days), "grace_days": int(args.grace_days),
        "tz": it.tz,
        "missed": missed, "alarmed": bool(missed),
        "malformed": ledger["malformed"],
        "findings": deadman_findings(missed, args.instance, it.cron, int(args.lookback_days)),
        # t260917-02（C1）：跳火回执两键——None=未查（在线面才有真值），非 None=调度面
        # 直接计数在案（1.18.2 ScheduleInfo 字段实证；跳火可观测，不再推断为准）。
        "skip_count": None, "running_actions": None,
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
        skip_count = getattr(info, "num_actions_skipped_overlap", None)
        running_actions = list(getattr(info, "running_actions", None) or [])
        action_summary = await _schedule_action_summary(c, args.instance)
        result["schedule"] = {
            "checked": True, "exists": True,
            "next_action_times": [t.isoformat(timespec="seconds")
                                  for t in (getattr(info, "next_action_times", None) or [])][:3],
            "recent_actions": [{"scheduled_at": str(getattr(a, "scheduled_at", "")),
                                "status": str(getattr(a, "start_workflow_status", ""))}
                               for a in (getattr(info, "recent_actions", None) or [])][:3],
            "num_actions": getattr(info, "num_actions", None),
            # t260917-02（C1）：skip 计数/Running action/补窗错失三键并回执（additive）
            "skip_count": skip_count, "running_actions": len(running_actions),
            "missed_catchup_window": getattr(info, "num_actions_missed_catchup_window", None),
            "note": getattr(info, "note", ""),
        }
        result["skip_count"] = skip_count
        result["running_actions"] = len(running_actions)
        if action_summary is not None:
            result["schedule_action"] = action_summary
        # 跳火 finding（C1 两分支：observed 实锤优先 / inferred 兜底，leg 键可辨不混装）
        skip_f = skip_findings(skip_count, len(running_actions), action_summary, missed)
        if skip_f:
            result["findings"] = list(result["findings"]) + skip_f
            if any((f or {}).get("leg") == "observed" for f in skip_f):
                result["alarmed"] = True   # 此刻就在跳火=每天可见的告警（ops 退出码可踩）
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
    parsing-level evidence surface).

    t260916-02：显式 --decl-path / env 覆盖层=单文件视图（mode=single）；两者皆无=
    **聚合视图**（mode=aggregate）——遍历注册项目读各自 inspection.yaml，逐项目
    ok/absent/error 状态与降级清单进 result（验收 5「聚合可读面」），调度意图附
    project 来源。"""
    explicit = str(args.decl_path or "").strip() or coverage_decl_path()
    if explicit:
        try:
            decl = load_inspection_decl(Path(explicit))
        except Exception as e:  # noqa: BLE001 — DeclError/IO always becomes an explicit single-line JSON error
            return _err("声明不可用：%s" % e)
        return _ok({
            "mode": "single", "source": decl.source, "schema": decl.schema,
            "instances": [_decl_instance_view(i) for i in decl.instances],
            "schedule_specs": build_schedule_specs(decl),
        })
    try:
        _projects, quarantined = list_registered_projects()
        enabled, degraded, coverage = enabled_instance_whitelist()
    except Exception as e:  # noqa: BLE001
        return _err("项目注册表不可用：%s" % e)
    items = []
    for state in iter_project_decls():
        item: Dict[str, Any] = {"project": state.project_key, "state": state.state,
                                "decl_path": str(state.path or "")}
        if state.state == "ok" and state.decl is not None:
            item["instances"] = [_decl_instance_view(i) for i in state.decl.instances]
            item["schedule_specs"] = [dict(s, project=state.project_key)
                                      for s in build_schedule_specs(state.decl)]
        elif state.state == "error":
            item["error"] = state.error
        items.append(item)
    if not items and not quarantined:
        # 空注册表=显式报错（t260916-02 口径①：零项目可遍历不许冒充「全绿无巡检面」）
        return _err("项目注册表为空（%s 下零 project.yaml 条目）——聚合视图无项目可遍历，"
                    "请检查 SANDBAR_PROJECTS_DIR/注册表落位"
                    % shared.perkey_projects_root())
    specs = [it for i in items for it in (i.get("schedule_specs") or [])]
    return _ok({
        "mode": "aggregate",
        "projects": items,
        "quarantined": list(quarantined or []),
        "coverage_overlay": coverage or "",
        "enabled_instances": sorted(enabled),
        "degraded": [{"project": d[0], "path": str(d[1] or ""), "error": d[2]} for d in degraded],
        "schedule_specs": specs,
    })


def _decl_instance_view(i: Any) -> Dict[str, Any]:
    """decl 子命令的实例条目视图（cmd_decl 单/聚合两模式共用）。"""
    return {"id": i.id, "enabled": i.enabled, "kind": i.kind,
            "cron": i.cron, "n": i.n, "source": i.source,
            # 实例级身份（t260915-20）与计数源 project_key 并列出，人读两清
            "instance_project_key": i.instance_project_key,
            "project_key": i.project_key, "scan_face": i.scan_face,
            "suite": i.suite, "tz": i.tz,
            "workflow": i.workflow, "template": i.template}


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
    p = sub.add_parser("trigger-produce", help="手动触发产出型巡检一期（per-ticket 队列，t260925-01）")
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
    p = sub.add_parser("verdict", help="发现级裁定：--finding-id --verdict 假报|待修|存疑（逐条；假报跨期压制）")
    p.add_argument("--instance", required=True)
    p.add_argument("--finding-id", required=True)
    p.add_argument("--verdict", required=True,
                   help="false-positive|to-fix|doubt 或中文别名 假报|待修|存疑")
    p.add_argument("--who", required=True, help="裁定人（agent 角色名拒收）")
    p.add_argument("--note", default="")
    p.add_argument("--period", default=None)
    p.add_argument("--decl-path", default=None)
    p.add_argument("--offline", action="store_true",
                   help="不连 Temporal，直改台账票面+verdicts 台账")
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
            result = asyncio.run({"trigger": cmd_trigger, "trigger-produce": cmd_trigger_produce,
                                  "sign": cmd_sign,
                                  "describe": cmd_describe, "ticket": cmd_ticket,
                                  "watcher": cmd_watcher, "deadman": cmd_deadman,
                                  "schedule-up": cmd_schedule_up,
                                  "verdict": cmd_verdict}[args.op](args))
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
