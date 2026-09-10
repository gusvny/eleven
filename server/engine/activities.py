"""Activity layer = every action that touches the outside world.

Two main channels:
  - `admin_call`: the only channel for `python3 server/admin.py call <tool> <args>`
    (ticket list/show, workflow show, qc_run, verify_lane…). Ticket **read**
    operations go through here.
  - `script_gate`: the script gate (qc_run / verify_lane), returns a structured
    red-green result; green is the only pass credential.

Ticket t260823: project_ticket (the tickets/*.json projection writer) was
deleted — the ticket source of truth is always the Temporal workflow.

Design point: the engine's **business refusals** are not raised as exceptions;
they return ok=False and let the workflow decide. Only true infrastructure
failures (timeouts, crashes) raise, so Temporal retries them.
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
    # Pipeline/admin scripts always run from the repo root (CLAUDE.md)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)


def _admin_cmd(tool: str, args: Dict[str, Any]) -> List[str]:
    return [sys.executable, str(ADMIN_PY), "call", tool, json.dumps(args or {}, ensure_ascii=False)]


def _parse(stdout: str) -> Dict[str, Any]:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


# ---------- Step-2 generic engine channel ----------

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
    """Run the real acceptance script (qc_run / verify_lane). Green is the only pass credential."""
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


# ---------- Step-1 backward compat (ContentPipelineWorkflow / DispatcherScanWorkflow) ----------

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


# ---------- M6 scan expansion: pending-ticket check report ----------
#
# Red line: suggestions only (suspected-stuck / needs-supply / signable), no
# decisions; signing is human-only.
# Ticket reads go through admin.py (read-only list/show); script-gate red-green
# goes through a Temporal snapshot query (read-only), falling back to the
# "脚本门" record in the ticket log when unreachable. The report lands in
# out/scan/<date>.json (same-day reruns overwrite; runtime output is gitignored;
# rationale in engine/README §10).


async def _admin_payload(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    proc = await asyncio.to_thread(_run, _admin_cmd(tool, args))
    return _parse(proc.stdout)


async def _temporal_gate(ticket_id: str) -> Dict[str, Any]:
    """Latest script-gate red-green: read-only query of the ticket workflow's snapshot.gate_runs.

    Workflow not running (never adopted / already finished) or server unreachable
    → green=None plus a source note, and the caller falls back to log parsing.
    A fresh connection each time: the scan is a low-frequency action, not worth
    a persistent connection.
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
    except Exception as e:  # unreachable / not adopted / finished → structured degradation, no raise (the scan must still emit a full report)
        return {"label": "", "green": None,
                "source": "temporal 不可达（%s）" % type(e).__name__}


async def scan_tickets_report_impl(now_ts: float, stuck_hours: float,
                                   list_fn, show_fn, gate_fn) -> ScanReport:
    """Scan core (dependency-injected): the three channels list/show/gate are
    supplied by the caller, so tests can stub them all.

    list_fn() → admin ticket list payload; show_fn(tid) → ticket show payload;
    gate_fn(tid) → {"label","green","source"}.
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
    # Most urgent first (suspected-stuck → needs-supply → signable), same tier
    # sorted by dwell time descending.
    rank = {s: i for i, s in enumerate(SCAN_SUGGESTIONS)}
    items.sort(key=lambda i: (rank.get(i.suggestion, 9), -i.dwell_hours))
    # Unfiled list (epic-linkage acceptance criterion 3): in-flight tickets with
    # no epic go on the list. The rule is "with ownership you must bind; the scan
    # watches for strays" — starting a ticket without an epic is allowed, but the
    # report must show it. Closed tickets are excluded: settled tickets are
    # history, and including them all would only grow the list into noise.
    # The epic data source is the ticket-list row shape (client.py reads the
    # EpicCode search attribute directly).
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
    """Scan expansion: per settled/awaiting-human ticket emit a check item + a suggestion (suggestions only, no decisions)."""
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
    """Dedicated-worker reconcile (legacy duty from the one-worker-per-ticket era,
    now reap-only).

    Ticket workers are spawned by console keepalive as child processes and follow
    the console. This activity no longer pulls missing workers — daemon-style
    pulling would create orphan workers and break "console gone = workers gone".
    It only reaps the stragglers that are "workflow settled but worker still
    alive"; RUNNING tickets missing a worker are recorded in the return value
    (missing) for the record, and pull-missing belongs to console ensure.

    Same red line as the scan: fix processes only, never touch workflow state.
    Failures do not raise; the next scan reconciles again.
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
    """Write the report to out/scan/<date>.json (same-day reruns overwrite that day's file; at most one file per day)."""
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
        # Unfiled list (epic-linkage): in-flight ticket ids with no EpicCode; the desk watches strays by it.
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
# Inspection ticket ① (t260905-03): test-face scan + inspection-ticket ledger write.
# Thin shell — the pure functions live in inspection_scan.py / inspection_flow.py;
# business refusals return ok=False for the workflow to decide, and only true
# infrastructure failures raise so Temporal retries.
# ========================================================================================

@activity.defn
async def run_inspection_scan(args: Dict[str, Any]) -> Dict[str, Any]:
    """Inspection scan by declared face (ticket 2, t260910-09; rework r2 semantics):
      - face=test (also the default / missing key) → ticket-1 test-face scan, behavior
        identical to before ticket 2 (existing callers/scenarios unchanged);
      - face=mechanism/simplify → the ticket-2 scanners;
      - ANY OTHER face (a declared-but-unwired face like doc, or a typo) → FALLBACK to
        the test-face scan with an explicit meta annotation (face_fallback naming the
        requested face and the wired scanners). Rationale (arbitrate code-fault 260910):
        ticket-1 treated face as a display-only field, so declared-but-unwired instances
        (doc-face) legitimately ran the test scan — rejecting them turned the zero-finding
        heartbeat ticket into a blocked terminal, breaking ticket-1 semantics. The
        activity cannot see the trigger-side declaration (--decl-path lives with the
        trigger), so "declared" vs "typo" is indistinguishable here; per the
        no-silent-degradation discipline the fallback is never silent — it is annotated
        on the ticket face (scan_meta.face_fallback) and logged. Fail-closed stays at the
        CLI (--face choices) and run_face_scan layer, where the caller is the operator.
    Lazy import: prevents an activities↔inspection_flow module cycle (same precedent as agent_activities)."""
    from inspection_scan import ScanError, run_test_face_scan
    from inspection_scan_ms import run_face_scan

    root = Path(args.get("repo_root") or REPO_ROOT)
    face = str(args.get("face") or "test")
    try:
        if face == "test":
            sp = args.get("scenarios_path")
            result = run_test_face_scan(root, Path(sp) if sp else None)
        elif face in ("mechanism", "simplify"):
            result = run_face_scan(face, root)
        else:
            result = run_test_face_scan(root, None)
            fallback_note = ("声明面 %r 未接线扫描器（已接线：mechanism、simplify）——回落 test 面"
                             "扫描（票① 行为）；接线或改名走 dev-lane 工单" % face)
            result.setdefault("meta", {})["face_fallback"] = fallback_note
            activity.logger.warning("巡检面回落：%s", fallback_note)
        activity.logger.info(
            "巡检面 %s 扫描完成：%d 条发现（high=%s/med=%s/low=%s）heartbeat=%s",
            face,
            result["summary"].get("high", 0) + result["summary"].get("med", 0)
            + result["summary"].get("low", 0),
            result["summary"].get("high", 0), result["summary"].get("med", 0),
            result["summary"].get("low", 0), result["heartbeat"])
        return {"ok": True, "result": result}
    except ScanError as e:
        return {"ok": False, "error": str(e)}


@activity.defn
async def write_inspection_report(face: Dict[str, Any]) -> Dict[str, Any]:
    """Inspection-ticket ledger write to out/inspection/<ticket-id>.json (same-ticket reruns overwrite the single file); written again at settle for the final state."""
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
