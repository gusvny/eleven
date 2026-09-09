"""Activity 层 = 一切碰外部世界的动作。

两个主通道：
  - `admin_call`：`python3 server/admin.py call <tool> <args>` 的唯一通道（ticket list/show、
    workflow show、qc_run、verify_lane…）。工单**读**操作走这里。
  - `script_gate`：脚本门（qc_run / verify_lane），返回结构化红绿灯，绿才放行。

票 t260823：project_ticket（tickets/*.json 投影写入器）已删除——工单真源恒为 Temporal workflow。

设计要点：引擎的**业务拒绝**不当异常抛，返回 ok=False 交 workflow 决策；只有真·基础设施
故障（超时、崩）才抛，让 Temporal 重试。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from temporalio import activity
from temporalio.client import Client

from shared import (
    ADMIN_PY,
    INSPECTION_DIR,
    NAMESPACE,
    REPO_ROOT,
    SCAN_DIR,
    SCAN_RED_LINE,
    SCAN_STUCK_HOURS,
    SCAN_SUGGESTIONS,
    TARGET_HOST,
    EngineCall,
    EngineResult,
    GateResult,
    GateSpec,
    QcRequest,
    QcResult,
    ScanReport,
    ScanTicketItem,
    Signature,
    TicketScan,
    build_scan_item,
    gate_from_log,
    is_pending_decision,
    scan_summary,
)


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    # 管线/admin 脚本一律在仓库根跑（CLAUDE.md）
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)


def _admin_cmd(tool: str, args: Dict[str, Any]) -> List[str]:
    return [sys.executable, str(ADMIN_PY), "call", tool, json.dumps(args or {}, ensure_ascii=False)]


def _parse(stdout: str) -> Dict[str, Any]:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


# ---------- 步2 通用引擎通道 ----------

@activity.defn
async def admin_call(call: EngineCall) -> EngineResult:
    cmd = _admin_cmd(call.tool, call.args)
    activity.logger.info("engine: %s %s（%s）", call.tool, call.args, call.why)
    proc = await asyncio.to_thread(_run, cmd)
    payload = _parse(proc.stdout)
    if payload.get("ok"):
        res = payload.get("result")
        return EngineResult(
            ok=True,
            result=res if isinstance(res, dict) else {"value": res},
            run_id=str(payload.get("run_id") or ""),
            exit_code=proc.returncode,
            cmd="%s %s" % (call.tool, json.dumps(call.args, ensure_ascii=False)),
        )
    err = str(payload.get("error") or (proc.stderr or proc.stdout or "").strip())[:600]
    return EngineResult(
        ok=False,
        error=err or "引擎无输出",
        run_id=str(payload.get("run_id") or ""),
        exit_code=proc.returncode,
        cmd="%s %s" % (call.tool, json.dumps(call.args, ensure_ascii=False)),
    )


@activity.defn
async def script_gate(gate: GateSpec) -> GateResult:
    """跑真实验收脚本（qc_run / verify_lane）。绿=放行的唯一凭据。"""
    cmd = gate.cmd or _admin_cmd(gate.tool, gate.args)
    activity.logger.info("gate[%s] %s", gate.stage, " ".join(cmd))
    proc = await asyncio.to_thread(_run, cmd)
    payload = _parse(proc.stdout)
    res = payload.get("result") or {}
    green = bool(payload.get("ok")) and bool(res.get("green")) and proc.returncode == 0
    return GateResult(
        green=green,
        red_count=int(res.get("red_count") or 0),
        label=gate.label or "%s %s" % (gate.tool, json.dumps(gate.args, ensure_ascii=False)),
        exit_code=proc.returncode,
        checks=[
            {"check": c.get("check"), "level": c.get("level"), "count": c.get("count")}
            for c in (res.get("checks") or [])
        ],
        raw_head=(proc.stdout or proc.stderr or "")[:400],
    )


# ---------- 步1 向后兼容（ContentPipelineWorkflow / DispatcherScanWorkflow）----------

@activity.defn
async def machine_qc(req: QcRequest) -> QcResult:
    cmd = req.cmd or [
        sys.executable,
        str(ADMIN_PY),
        "call",
        "qc_run",
        json.dumps({"scope": req.scope}, ensure_ascii=False),
    ]
    activity.logger.info("machine_qc 执行：%s", " ".join(cmd))
    proc = await asyncio.to_thread(_run, cmd)
    payload = _parse(proc.stdout)
    result = payload.get("result") or {}
    green = bool(result.get("green")) and proc.returncode == 0 and bool(payload.get("ok"))
    return QcResult(
        green=green,
        red_count=int(result.get("red_count") or 0),
        scope=str(result.get("scope") or req.scope),
        label=req.label,
        exit_code=proc.returncode,
        checks=[
            {"check": c.get("check"), "level": c.get("level"), "count": c.get("count")}
            for c in (result.get("checks") or [])
        ],
        raw_head=(proc.stdout or proc.stderr or "")[:400],
    )


@activity.defn
async def process_stage(note: str) -> str:
    activity.logger.info("process_stage: %s", note)
    return f"加工交接已登记：{note}"


@activity.defn
async def ai_review_stub(scope: str) -> Dict[str, Any]:
    activity.logger.info("ai_review_stub scope=%s", scope)
    return {"findings": 0, "note": f"AI 审校占位（未调模型），scope={scope}"}


@activity.defn
async def publish_dry_run(proposal_id: str) -> str:
    activity.logger.info("publish_dry_run proposal=%s", proposal_id)
    return f"[dry-run] 若为真发布，此处才会动 app/public/data；POC 零写入（proposal={proposal_id}）"


@activity.defn
async def record_signature(sig: Signature) -> str:
    activity.logger.info("signature by=%s decision=%s", sig.who, sig.decision)
    return f"{sig.decision} by {sig.who}: {sig.note}"


@activity.defn
async def ticket_scan() -> TicketScan:
    cmd = _admin_cmd("ticket", {"op": "list"})
    proc = await asyncio.to_thread(_run, cmd)
    payload = _parse(proc.stdout)
    tickets = ((payload.get("result") or {}).get("tickets")) or []
    by_status: Dict[str, int] = {}
    stuck: List[str] = []
    for t in tickets:
        st = str(t.get("status") or "?")
        by_status[st] = by_status.get(st, 0) + 1
        if st == "settled" or t.get("stage_state") == "blocked":
            stuck.append(str(t.get("id")))
    return TicketScan(
        total=len(tickets),
        by_status=by_status,
        stuck=stuck[:20],
        exit_code=proc.returncode,
    )


# ---------- M6 巡检扩权：待决工单检查报告 ----------
#
# 红线：只出建议（疑似卡死/待补/可签），不出决定；签字只能人。
# 读工单走 admin.py（只读 list/show）；脚本门红绿灯走 Temporal snapshot query（只读），
# 不可达时回退工单 log 的「脚本门」记录。落盘 out/scan/<日期>.json（同日重跑覆盖，
# 运行产物 gitignore 不入库；判断依据见 engine/README §10）。


async def _admin_payload(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    proc = await asyncio.to_thread(_run, _admin_cmd(tool, args))
    return _parse(proc.stdout)


async def _temporal_gate(ticket_id: str) -> Dict[str, Any]:
    """最近一次脚本门红绿灯：只读 query 工单 workflow 的 snapshot.gate_runs。

    workflow 不在跑（未 adopt / 已完成）或 server 不可达 → green=None + source 说明，
    调用方回退 log 判读。连接每次新建：巡检是低频动作，不值得常驻连接。
    """
    try:
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
        snap = await client.get_workflow_handle(ticket_id).query("snapshot")
        runs = (snap or {}).get("gate_runs") or []
        if runs:
            last = runs[-1] or {}
            return {"label": str(last.get("label") or ""),
                    "green": bool(last.get("green")), "source": "temporal"}
        return {"label": "", "green": None, "source": "temporal（无脚本门记录）"}
    except Exception as e:  # 不可达/未 adopt/已完成 → 结构化降级，不抛（巡检要出全量报告）
        return {"label": "", "green": None,
                "source": "temporal 不可达（%s）" % type(e).__name__}


async def scan_tickets_report_impl(now_ts: float, stuck_hours: float,
                                   list_fn, show_fn, gate_fn) -> ScanReport:
    """巡检本体（依赖注入版）：list/show/gate 三个通道由调用方给，自测可全假。

    list_fn() → admin ticket list 的 payload；show_fn(tid) → ticket show 的 payload；
    gate_fn(tid) → {"label","green","source"}。
    """
    payload = await list_fn()
    tickets = ((payload.get("result") or {}).get("tickets")) or []
    by_status: Dict[str, int] = {}
    for t in tickets:
        st = str(t.get("status") or "?")
        by_status[st] = by_status.get(st, 0) + 1
    items: List[ScanTicketItem] = []
    for t in tickets:
        if not isinstance(t, dict) or not is_pending_decision(t):
            continue
        tid = str(t.get("id") or "")
        show = await show_fn(tid)
        full = (show.get("result") or {}) if show.get("ok") else dict(t)
        if not full.get("id"):
            full["id"] = tid
        gate = await gate_fn(tid)
        if gate.get("green") is None and str(gate.get("source") or "").startswith("temporal 不可达"):
            gate = gate_from_log(full)
        items.append(build_scan_item(
            full, gate_label=str(gate.get("label") or ""), gate_green=gate.get("green"),
            gate_source=str(gate.get("source") or ""), now_ts=now_ts, stuck_hours=stuck_hours))
    # 最紧急在前（疑似卡死→待补→可签），同档按停留时长倒序。
    rank = {s: i for i, s in enumerate(SCAN_SUGGESTIONS)}
    items.sort(key=lambda i: (rank.get(i.suggestion, 9), -i.dwell_hours))
    # 未归档清单（epic-linkage 验收标准 3）：无 epic 的在途工单进清单。规则是
    # 「有归属必须绑，巡检盯漏网」——允许无 epic 开工单，但报告里要有它。
    # closed 不收：已收口工单是历史，全收只会让清单无限增殖变噪音。
    # epic 数据源 = ticket list 行形态（client.py 从 EpicCode SA 直取）。
    unfiled = sorted(
        str(t.get("id") or "") for t in tickets
        if isinstance(t, dict) and str(t.get("id") or "")
        and not str(t.get("epic") or "")
        and str(t.get("status") or "") != "closed")
    return ScanReport(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        total_tickets=len(tickets),
        by_status=by_status,
        items=items,
        summary=scan_summary(items),
        stuck_hours=stuck_hours,
        unfiled=unfiled,
    )


@activity.defn
async def scan_tickets_report() -> ScanReport:
    """巡检扩权：对 settled/awaiting-human 工单逐张出检查条目 + 建议（只出建议不出决定）。"""
    activity.logger.info("巡检扩权：扫 settled/awaiting-human 工单（阈值 %.0fh）", SCAN_STUCK_HOURS)
    return await scan_tickets_report_impl(
        now_ts=time.time(),
        stuck_hours=SCAN_STUCK_HOURS,
        list_fn=lambda: _admin_payload("ticket", {"op": "list"}),
        show_fn=lambda tid: _admin_payload("ticket", {"op": "show", "id": tid}),
        gate_fn=_temporal_gate,
    )


@activity.defn
async def reconcile_ticket_workers() -> Dict[str, Any]:
    """专属 worker 对账（一工单一 worker 时代的遗留职责，现为 reap-only）。

    工单 worker 由 console keepalive 以子进程 spawn、跟 console 走。本 activity
    不再补拉——daemon 补拉会造出无主 worker，破坏「console 没了就没了」。只回收
    「workflow 已收口但 worker 还活着」的漏退者；RUNNING 缺 worker 的记进
    返回值（missing）留痕，补拉归 console ensure。

    红线同巡检：只修进程，不碰 workflow 状态。失败不抛，下次巡检再对。
    """
    from ticket_worker import reap_ticket_worker, worker_pid
    from workflows_v2 import TEMPLATE_CLASSES

    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__ for c in TEMPLATE_CLASSES.values())
    running, known = [], []
    async for wf in client.list_workflows(type_filter):
        known.append(wf.id)
        if wf.status is not None and wf.status.name == "RUNNING":
            running.append(wf.id)
    reaped = [tid for tid in sorted(set(known) - set(running))
              if await asyncio.to_thread(worker_pid, tid)
              and await asyncio.to_thread(reap_ticket_worker, tid) == 'reaped']
    missing = [tid for tid in running if not await asyncio.to_thread(worker_pid, tid)]
    if reaped or missing:
        activity.logger.info("worker 对账：回收漏退 %s；RUNNING 缺 worker %s（等 console ensure 补拉）",
                             reaped or '无', missing or '无')
    else:
        activity.logger.info("worker 对账：%s 张在跑工单 worker 全在册，无回收", len(running))
    return {"running": len(running), "known": len(known),
            "missing": missing, "reaped": reaped}


@activity.defn
async def write_scan_report(report: ScanReport) -> Dict[str, Any]:
    """报告落盘 out/scan/<日期>.json（同日重跑覆盖当日文件；每日最多一个文件）。"""
    import dataclasses

    date = time.strftime("%Y-%m-%d", time.localtime())
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    path = SCAN_DIR / (date + ".json")
    payload = {
        "generated_at": report.generated_at,
        "total_tickets": report.total_tickets,
        "by_status": report.by_status,
        "pending_decision_count": len(report.items),
        "stuck_threshold_hours": report.stuck_hours,
        "red_line": SCAN_RED_LINE,
        "summary": report.summary,
        # 未归档清单（epic-linkage）：无 EpicCode 的在途工单 id，台面按它盯漏网。
        "unfiled": list(report.unfiled),
        "items": [dataclasses.asdict(it) for it in report.items],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    await asyncio.to_thread(path.write_text, text, "utf-8")
    activity.logger.info("巡检报告落盘 %s（待决 %d 张，未归档 %d 张）",
                         path, len(report.items), len(report.unfiled))
    return {"path": str(path), "file": path.name, "bytes": len(text),
            "items": len(report.items)}


# ========================================================================================
# inspection 票①（t260905-03）：测试面扫描 + 巡检票落账。薄壳——纯函数在
# inspection_scan.py / inspection_flow.py；业务拒绝返回 ok=False 交 workflow 决策，
# 只有真·基础设施故障才抛，让 Temporal 重试。
# ========================================================================================

@activity.defn
async def run_inspection_scan(args: Dict[str, Any]) -> Dict[str, Any]:
    """测试面扫描：仓库根（缺省 REPO_ROOT）+ 场景清单路径（可选）→ findings。
    延迟导入：防 activities↔inspection_flow 模块环（同 agent_activities 先例）。"""
    from inspection_scan import ScanError, run_test_face_scan

    root = Path(args.get("repo_root") or REPO_ROOT)
    sp = args.get("scenarios_path")
    try:
        result = run_test_face_scan(root, Path(sp) if sp else None)
        activity.logger.info(
            "测试面扫描完成：%d 条发现（high=%s/med=%s/low=%s）heartbeat=%s",
            result["summary"].get("high", 0) + result["summary"].get("med", 0)
            + result["summary"].get("low", 0),
            result["summary"].get("high", 0), result["summary"].get("med", 0),
            result["summary"].get("low", 0), result["heartbeat"])
        return {"ok": True, "result": result}
    except ScanError as e:
        return {"ok": False, "error": str(e)}


@activity.defn
async def write_inspection_report(face: Dict[str, Any]) -> Dict[str, Any]:
    """巡检票落账 out/inspection/<票号>.json（同票重跑覆盖单文件）；收口时再写一次终态。"""
    from inspection_flow import write_inspection_report_impl

    try:
        result = await asyncio.to_thread(
            write_inspection_report_impl, face, INSPECTION_DIR)
        activity.logger.info("巡检票落账 %s", result.get("path"))
        return {"ok": True, "result": result}
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "巡检票落账失败：%s" % e}


ALL_ACTIVITIES = [
    admin_call,
    script_gate,
    machine_qc,
    process_stage,
    ai_review_stub,
    publish_dry_run,
    record_signature,
    ticket_scan,
    scan_tickets_report,
    reconcile_ticket_workers,
    write_scan_report,
    run_inspection_scan,
    write_inspection_report,
]
