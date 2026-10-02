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
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from temporalio import activity
from temporalio.client import Client

# t260928-13：事件账本写活动的注册转发（活动体真源在 event_ledger.py；worker 经
# ALL_ACTIVITIES 注册，保持「活动单一注册面」纪律）。
from event_ledger import append_event_ledger as _append_event_ledger

from shared import (
    ADMIN_PY,
    INSPECTION_DIR,
    KNOWN_RED_BASELINE_REL,
    NAMESPACE,
    PROJECT_SA_NAME,
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
    gate_failure_note,
    gate_from_log,
    gate_receipt_parse,
    gate_verdict,
    is_pending_decision,
    known_red_roster,
    list_registered_projects,
    scan_summary,
)


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    # Pipeline/admin scripts always run from the repo root (CLAUDE.md)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout)


def _admin_cmd(tool: str, args: Dict[str, Any]) -> List[str]:
    return [sys.executable, str(ADMIN_PY), "call", tool, json.dumps(args or {}, ensure_ascii=False)]


def _parse(stdout: str) -> Dict[str, Any]:
    """回执解析（单点=shared.gate_receipt_parse）：容忍「说明行 + 回执行」的多对象 stdout。

    t260927：老实现是整段 `json.loads`，遇上多对象 stdout 就返回 {} —— 门于是被判非绿而
    red_count 也是 0，票面写成「脚本门 … 红灯 0 项」，票永远收不了口（宿主实报）。
    """
    return gate_receipt_parse(stdout)


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
    v = gate_verdict(payload, proc.returncode)          # t260927：判定三要素逐项带出
    return GateResult(
        green=v["green"],
        red_count=v["red_count"],
        label=gate.label or "%s %s" % (gate.tool, json.dumps(gate.args, ensure_ascii=False)),
        exit_code=proc.returncode,
        checks=v["checks"],
        raw_head=(proc.stdout or proc.stderr or "")[:400],
        parsed=v["parsed"], receipt_ok=v["receipt_ok"], receipt_green=v["receipt_green"],
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


def _git_ref_commit_iso(root, ref) -> tuple:
    """`base_ref` 的**提交时刻**（ISO8601 带时区）→ (iso, error)。只读幂等零写。

    KI-122① 260926 时间证据判据要拿「票面 base_ref 的提交时间」当开票基点：提交时刻是
    仓里的事实，工作流体零 IO 纪律不破，故在本壳里解析。ref 畸形（空 / 以 `-` 开头=疑似
    参数注入）→ 直接判不可得（不猜、不外传）；git 不可用/超时/解析不出 → 具名 error
    （调用方据此回落到票面 created，二者都不可得才 fail-closed）。"""
    ref = str(ref or "").strip()
    if not ref or ref.startswith("-"):
        return "", "base_ref is empty or malformed (%r)" % (ref,)
    try:
        r = subprocess.run(["git", "-C", str(root), "show", "-s", "--format=%cI", ref],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return "", "base_ref commit time unresolved (%s: %s)" % (type(e).__name__, e)
    if r.returncode != 0:
        return "", ("base_ref commit time unresolved (git exit %d: %s)"
                    % (r.returncode, (r.stderr or r.stdout or "").strip()[-200:]))
    return r.stdout.strip(), ""


@activity.defn
async def read_known_red_roster(args: Dict[str, Any]) -> Dict[str, Any]:
    """KI-122①：读仓根已知红挂账册（integration/known-red-baseline.json）——**只读**面。

    裁决采纳判据要用「这条闸拦（blocker）是否已挂账」这一既有名册归属，而名册是仓内文件：
    workflow 体零 IO 纪律不破，IO 全在本壳。回执形状：
      {ok: True, result: {entries: {name: {verdict, home, booked_at, booked_sha}},
                          error: "", path: <绝对路径>, base_ref: <票面基点>,
                          base_at: <base_ref 的提交时刻 ISO 或 "">,
                          base_at_error: <解析失败原因或 "">}}
    名册读不到 / JSON 畸形 / 条目畸形 → **不抛**，error 非空（fail-closed 由调用方判定：
    照旧拦、照旧重跑，并把路径与原因点名进票面）——「名册确实缺失」不是基础设施故障，
    不该被 Temporal 重试成无限循环。零写零信号：绝不改文件、绝不碰票态。"""
    rel = str((args or {}).get("rel") or KNOWN_RED_BASELINE_REL)
    root = Path(str((args or {}).get("repo_root") or REPO_ROOT))
    path = root / rel
    base_ref = str((args or {}).get("base_ref") or "")
    base_at, base_err = _git_ref_commit_iso(root, base_ref)
    if not base_ref:
        base_err = "base_ref is empty or malformed ('')"
    entries: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": True, "result": {"entries": entries, "path": str(path),
                                       "base_ref": base_ref, "base_at": base_at,
                                       "base_at_error": base_err,
                                       "error": "cannot read %s: %s" % (rel, type(e).__name__)}}
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as e:
        return {"ok": True, "result": {"entries": entries, "path": str(path),
                                       "base_ref": base_ref, "base_at": base_at,
                                       "base_at_error": base_err,
                                       "error": "malformed JSON in %s: %s" % (rel, type(e).__name__)}}
    entries, err = known_red_roster(payload)
    return {"ok": True, "result": {"entries": entries, "path": str(path),
                                   "base_ref": base_ref, "base_at": base_at,
                                   "base_at_error": base_err, "error": err}}


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
#
# 【退役注记（t260916-22，宿主令「不需要这个静态扫描，巡检要用 agent 来做」）】
# 本活动已从生产路径摘除：InspectionPeriodicWorkflow 的新票走 inspect 段
# （run_inspection_inspect，agent_activities.py，INSPECT_PATCH_ID 门内）。本活动与
# 四个静态扫描器文件**保留一版**，唯一消费者=老在途票 replay（Temporal 重放历史里
# 已记录的 run_inspection_scan 调用必须仍能匹配）——新代码禁接线（退役票号
# t260916-22）。S1~S4 自此不再产出；274 条旧发现整体作废不迁移（宿主裁定④）。
# ========================================================================================

@activity.defn
async def run_inspection_scan(args: Dict[str, Any]) -> Dict[str, Any]:
    """【已退役（t260916-22）】Inspection scan by declared face (ticket 2, t260910-09;
    rework r2 semantics):
      - face=test (also the default / missing key) → ticket-1 test-face scan, behavior
        identical to before ticket 2 (existing callers/scenarios unchanged);
      - face=doc → docs-face scanner (t260911-02); face=stage → stage-capacity
        scanner (t260915-18, stage_docker inventory read-only); face=mechanism/simplify
        → the ticket-2 scanners;
      - ANY OTHER face (a declared-but-unwired face, or a typo) → FALLBACK to
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
        elif face == "doc":
            # t260911-02：docs 面接线（docs-sync 第二实例）——声明 scan_face=doc 的实例
            # 不再回落 test 面（fallback 名单同步收窄）。
            from inspection_scan_doc import run_doc_face_scan
            result = run_doc_face_scan(root)
        elif face == "stage":
            # t260915-18：stage 面接线（stage-capacity 实例）——台面容量可见性，
            # inventory 只读清点；docker 缺席=响亮未检查（S14 不假绿）。
            from inspection_scan_stage import run_stage_face_scan
            result = await asyncio.to_thread(run_stage_face_scan, root)
        elif face in ("mechanism", "simplify"):
            result = run_face_scan(face, root)
        else:
            result = run_test_face_scan(root, None)
            fallback_note = ("声明面 %r 未接线扫描器（已接线：doc、stage、mechanism、"
                             "simplify）——回落 test 面扫描（票① 行为）；接线或改名"
                             "走 dev-lane 工单" % face)
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
async def verify_inspection_findings(args: Dict[str, Any]) -> Dict[str, Any]:
    """report 段机械复核链的 IO 壳（t260916-22）：铸 id 后的 agent 发现 → 证据复核 →
    跨期去重/假报压制 → 预算截断 → 汇总/心跳。判定全部在 inspection_inspect 纯函数
    （UT 主面）；本活动只做台账 IO（读上期台账+裁定台账），失败=ok=False 点名。

    上期台账/裁定台账读不出 → 对应去重分支缺席但 meta 点名（不静默当空集，R7②）。
    复核不过的发现**保留**（降级 unverified 并逐项点名，不静默丢——工单要点②）。"""
    from inspection_inspect import (  # 懒 import：同 run_inspection_scan 防环先例
        NON_ENGLISH_REASON, apply_budget, collect_fake_ids, dedupe_and_suppress,
        finding_language_violations, heartbeat_of, mark_non_english,
        read_prev_ledger_ids, recheck_evidence, summarize_counts)

    instance_id = str(args.get("instance_id") or "")
    period = str(args.get("period") or "")
    base_dir = str(args.get("base_dir") or "")
    findings = args.get("findings")
    max_findings = int(args.get("max_findings") or 0)
    # 台账目录三优先：显式 args > 进程 env（场景/UT 运行时注入）> shared 常量
    # （import 时刻固化——env 注入晚于 import 的形态必须活，故每次调用重读 env）。
    from shared import INSPECTION_DIR
    ledger_dir = Path(str(args.get("ledger_dir")
                          or os.environ.get("SANDBAR_INSPECTION_DIR")
                          or INSPECTION_DIR))

    if not instance_id or not period or not base_dir:
        return {"ok": False, "error": "verify 输入缺 instance/period/base_dir（fail-closed）"}
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return {"ok": False, "error": "verify 输入 findings 畸形（缺列表或条目非对象）"}
    if not Path(base_dir).is_dir():
        return {"ok": False, "error": "审查基座目录不存在：%s（证据复核无从做起）" % base_dir}

    prev_ids, prev_note = read_prev_ledger_ids(ledger_dir, instance_id, period)
    fake_ids, fake_notes = collect_fake_ids(ledger_dir, instance_id, period)
    findings = recheck_evidence(findings, base_dir)
    # 260930 报告面语言闸（宿主令「report 用英语写」）：agent 自写的叙述字段含 CJK ⇒
    # 降级 unverified 并点名 non_english_text（提示词只是引导，机械面必须可判且可见；
    # 降级后 verified 门自动不生成修码建议票——数据字段 quote/path 不扫，不译）。
    lang_violations = finding_language_violations(findings)
    if lang_violations:
        mark_non_english(findings)
        # 票面**显式标红**（不是只在 meta 里记一笔）：聚合成一条 med 机械发现——
        # 「agent 有 N 条叙述字段没按英文写」是流程质量信号，suggest=False（不是代码缺陷，
        # 不开修码票）；逐条原因在各条的 unverified_reasons 里（可下钻）。
        from inspection_deadman import make_finding
        # 261001 归因精确化：这条聚合条过去写「N **agent** finding(s) …」，而闸扫的是
        # **所有**发现（含引擎自产的系统发现）——20261001 实案就是引擎自己那条
        # 「Scope collapsed to 0 files」的 suggestion 写中文触发的。归因错会把排查引向
        # agent/提示词，而真因在引擎文案。故改为按**事实**说「叙述字段非英文的发现」，
        # 并逐条点名 id+字段（可下钻）。
        findings.append(make_finding(
            "agent", "med",
            "%d finding(s) are not written in English" % len(lang_violations),
            "the report face and the ticket face are English-only: %s | each such finding is "
            "marked unverified (%s) and opens no fix ticket; fix the wording (engine-generated "
            "findings included) or re-run the inspect stage"
            % (", ".join("%s(%s)" % (v["id"] or v["index"], "/".join(v["fields"]))
                         for v in lang_violations[:10]), NON_ENGLISH_REASON),
            suggest=False))
    dedupe_and_suppress(findings, prev_ids or set(), fake_ids)
    if max_findings > 0:
        findings, budget_meta = apply_budget(findings, max_findings)
    else:
        budget_meta = {"truncated": 0}
    counts = summarize_counts(findings)
    n_unverified = sum(1 for f in findings if f.get("verified") == "unverified")
    meta = {
        "base_dir": base_dir,
        # 语言闸计数与逐条点名（报告/票面可见；0=全英文）
        "non_english": len(lang_violations),
        "non_english_findings": [{"id": v["id"] or v["index"], "fields": v["fields"]}
                                 for v in lang_violations],
        "prev_ledger": prev_note,
        "fake_notes": fake_notes,
        "fake_pool": len(fake_ids),
        "deduped": sum(1 for f in findings if f.get("recurring")),
        "suppressed": sum(1 for f in findings if f.get("suppressed")),
        "unverified": n_unverified,
        **budget_meta,
    }
    activity.logger.info(
        "巡检发现复核完成：%d 条（verified=%d unverified=%d recurring=%d suppressed=%d "
        "truncated=%s）heartbeat=%s", len(findings),
        len(findings) - n_unverified - int(meta["deduped"]) - int(meta["suppressed"]),
        n_unverified, meta["deduped"], meta["suppressed"], budget_meta["truncated"],
        heartbeat_of(findings))
    return {"ok": True, "result": {"findings": findings, "summary": counts,
                                   "heartbeat": heartbeat_of(findings), "meta": meta}}


@activity.defn
async def write_inspection_verdicts(args: Dict[str, Any]) -> Dict[str, Any]:
    """收口段把票面裁定批量落 verdicts 台账（t260916-22 要点⑥的持久面）。

    票内 signal（finding_verdict）只改内存票面（回放安全零活动）；跨期假报压制
    消费的是 verdicts 台账（collect_fake_ids），所以在收口时一次写齐。幂等=同
    (finding_id, source_ticket) 已在册跳过（Temporal 活动至少一次语义，重试不
    重复落账）；坏台账=ValueError（Temporal 重试同败→可见不静默）。"""
    from datetime import datetime, timezone
    from inspection_inspect import append_verdict_entry, verdicts_ledger_name

    instance_id = str(args.get("instance_id") or "")
    period = str(args.get("period") or "")
    entries = args.get("entries")
    if not instance_id or not period:
        return {"ok": False, "error": "verdicts 落账缺 instance/period（fail-closed）"}
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return {"ok": False, "error": "verdicts 落账 entries 畸形（缺列表或条目非对象）"}
    path = Path(str(args.get("ledger_dir") or INSPECTION_DIR)) / verdicts_ledger_name(
        instance_id, period)
    written, skipped = 0, 0
    for e in entries:
        entry = {"finding_id": str(e.get("finding_id") or ""),
                 "verdict": str(e.get("verdict") or ""),
                 "who": str(e.get("who") or ""),
                 "note": str(e.get("note") or ""),
                 "source_ticket": str(e.get("source_ticket") or ""),
                 "booked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if not entry["finding_id"] or not entry["verdict"]:
            return {"ok": False,
                    "error": "verdicts 落账条目缺 finding_id/verdict：%r" % (e,)}
        if append_verdict_entry(path, entry, dedupe=True):
            written += 1
        else:
            skipped += 1
    activity.logger.info("巡检裁定落账 %s（新 %d / 幂等跳过 %d）", path, written, skipped)
    return {"ok": True, "result": {"path": str(path), "written": written,
                                   "skipped": skipped}}


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


#: 水位扫描的顶层条目计数上界（防呆）：越过即截断并点名——计数是**下界**，
#: 绝不因为「扫不动」就静默当成水位 0（巡检面不许有静默零）。
TMP_SCAN_MAX_ENTRIES = 2_000_000
#: `skipped` 名单的条数上界（260927）：白名单里现在也有**文件族**（`*-integ-run-*.lock`
#: 单飞锁档、`sandbar-admin-log-*.log` 影子、`sandbar-credentials-*.yaml` 凭据副本——存量
#: 上万条），而水位判据只数真目录，这些条目会逐条进 `skipped`。不设上界的话，一份回执里
#: 塞进上万条名字：既是白烧的 payload（Temporal 单 payload 上限 2MB，越过即活动结果上报
#: 失败=整期巡检哑掉），也让「跳过 N 条」这个信号淹在名单里。截断**不静默**：名单末尾
#: 补一条具名计数行（`... (N more skipped entries suppressed)`），计数由 `skipped_count`
#: 单独给全量。判据零改动（水位仍只数真目录）。
TMP_SCAN_SKIPPED_CAP = 40
#: 同进程内同 root 的水位扫描缓存 TTL（秒；0=不用缓存）。为什么可以缓存：水位是分钟级
#: 慢变量，同一 worker 进程一次巡检期内多次调用（UT/重试）扫同一个顶层目录是纯浪费；
#: 跨期（>TTL）=新一次真扫。**只缓存只读结果**，不写任何状态。
TMP_SCAN_CACHE_TTL_S = 60.0
_TMP_SCAN_CACHE: Dict[Any, Any] = {}


def scan_tmp_fixture_dirs(root: str, prefixes=()) -> Dict[str, Any]:
    """只读扫临时根**顶层**一次：白名单前缀的**真目录** + mtime（零写、零递归、零 du）。

    为什么要单独一个函数而不是写在活动里：这是本面唯一的 IO（巡检纪律=只读、可复核），
    抽出来便于单测注入/替换，也便于「扫不动」的三态（OK/截断/读不到）逐态点名。
    白名单外一律只计数（untouched）——宿主 temp 里还有别的程序的东西，绝不算进水位。
    非真目录但命中白名单的条目（文件族/符号链接）进 `skipped`：**可见但不判水位**，
    且名单有上界（`TMP_SCAN_SKIPPED_CAP`，截断处具名给计数，全量在 `skipped_count`）。
    """
    out: Dict[str, Any] = {"root": str(root), "entries": [], "entries_seen": 0,
                           "untouched": 0, "skipped": [], "skipped_count": 0,
                           "scan_error": "", "truncated": False, "scanned_at": time.time()}

    def _skip(msg: str) -> None:
        """记一条跳过（可见性面）：全量计数 + 名单上界内逐条点名，截断处具名。"""
        out["skipped_count"] += 1
        if len(out["skipped"]) < TMP_SCAN_SKIPPED_CAP:
            out["skipped"].append(msg)
        elif len(out["skipped"]) == TMP_SCAN_SKIPPED_CAP:
            out["skipped"].append("... (%d more skipped entries suppressed)"
                                  % (out["skipped_count"] - TMP_SCAN_SKIPPED_CAP))

    prefixes = tuple(prefixes)
    try:
        with os.scandir(root) as it:
            for ent in it:
                out["entries_seen"] += 1
                if out["entries_seen"] > TMP_SCAN_MAX_ENTRIES:
                    out["truncated"] = True
                    break
                name = ent.name
                if not any(name.startswith(p) for p in prefixes):
                    out["untouched"] += 1
                    continue
                try:
                    if not ent.is_dir(follow_symlinks=False):
                        # 符号链接/文件族不算夹具目录（跟进去量的是别人的东西；文件族由
                        # 清扫器处置）——但绝不静默丢：逐条点名 + 全量计数
                        _skip("%s (not a real directory)" % name[:120])
                        continue
                    out["entries"].append(
                        {"name": name, "mtime": ent.stat(follow_symlinks=False).st_mtime})
                except OSError as e:
                    _skip("%s (stat failed: %s: %s)" % (name[:120], type(e).__name__, e))
    except OSError as e:
        out["scan_error"] = "%s: %s" % (type(e).__name__, e)
    return out


def _scan_tmp_fixture_cached(root: str, prefixes, ttl: float) -> Dict[str, Any]:
    """带 TTL 的只读扫描（同 root+白名单 命中缓存；ttl<=0 直扫）。"""
    key = (str(root), tuple(prefixes))
    now = time.time()
    hit = _TMP_SCAN_CACHE.get(key)
    if hit and ttl > 0 and (now - float(hit[0])) < ttl:
        scan = dict(hit[1])
        scan["cached"] = True
        return scan
    scan = scan_tmp_fixture_dirs(root, prefixes)
    scan["cached"] = False
    if ttl > 0:
        _TMP_SCAN_CACHE[key] = (now, scan)
    return scan


# t261001-05：读失败两分类 + 瞬态一次加预算重试。
# 瞬态（transient）=快照 query 在超时内无人应答（扫描时 worker 缺位/控制台停机的巡检期
# 形态，过后可自愈）；永久（permanent）=工作流本体条件（如 "Workflow Task in failed
# state"，需要人处置）。两类分开计数、分开文案——「197 次超时」不许再被读成「197 张坏票」。
# 重试：瞬态第一读超时后给**一次**更长单票预算的重试（总预算/并发闸不动——重试仍受
# deadline 钳制，几百张无 worker 的票依旧拖不垮扫描面）；可用 snapshot_retry_timeout_sec
# 显式覆盖倍算缺省。
SNAPSHOT_RETRY_TIMEOUT_MULT = 4.0


def _is_transient_read_error(exc: BaseException) -> bool:
    """单票快照读失败分类：超时无应答=瞬态（t261001-05），其余按永久工作流条件点名。"""
    return isinstance(exc, (asyncio.TimeoutError, TimeoutError))


@activity.defn
async def run_inspection_lane_watchdog(args: Dict[str, Any]) -> Dict[str, Any]:
    """lane/watchdog 面（KI-122 追加面 / KI-126 同源）：扫**非终态票**的工作流快照与时间线。

    宿主追问（260926）「巡检发现这个问题了吗」→ 没有：巡检各面只读制品与代码（套件回执/
    变化面 diff/KI 清单/台账），**没有一面读票的工作流时间线**——而活锁只体现在泳道层
    （同一票 `gate → tests-fault → 重跑`）。本面补这一路，与 `suite`/`deadman` 族并列。

    **只读铁律**：只 `list_workflows`（筛 RUNNING）与 `query("snapshot")`——**零写零信号**，
    绝不 update/signal/cancel/terminate 任何票，绝不改文件（与巡检红线一致）。
    判定全部在纯函数面 inspection_lane_watchdog（UT 主面）；本壳只做 IO（注册表解析、
    枚举、快照查询、时钟）。

    范围：按项目注册表解析出的**全部项目**的非终态票（票的 ProjectKey SA ∈ 注册表 key），
    不只宿主项目——逐票超阈出发现（同票多族由纯函数聚合为一条）。回执含计数（scanned /
    with_findings / by_leg）与阈值来源（declaration|default + 逐键回落原因），不静默。
    单票查询失败=点名进 errors（绝不静默吞成「这票没问题」）。

    第四判据（260926 补）：**测试夹具临时目录水位**——只读扫临时根顶层（白名单前缀的真
    目录 + mtime，零写零递归），越线出宿主级发现（`tmp-fixture-water`），回执挂在
    `result["tmp_fixture"]`（自己的 facts/findings/section：与票级三族的计数口径分开，
    票级断言零回归）。阈值同样走声明侧 `watchdog:` 档（`tmp_fixture_max_dirs`/
    `tmp_fixture_max_age_h`），来源=declaration|env|default 且逐键点名。扫描三态
    （OK/截断/读不到）逐态显式化：读不到=具名 med 发现（绝不渲染成「绿」）。
    """
    from inspection_lane_watchdog import (TMP_ENV_MAX_AGE_H, TMP_ENV_MAX_DIRS,
                                          TMP_FIXTURE_PREFIXES, facts_from_snapshot,
                                          lane_findings, lane_section, merge_lane_section,
                                          resolve_thresholds, resolve_tmp_thresholds,
                                          tmp_fixture_scan_result)

    thresholds, thr_source, thr_note, _problems = resolve_thresholds(args.get("watchdog"))
    try:
        max_tickets = int(args.get("max_tickets") or 200)
    except (TypeError, ValueError):
        max_tickets = 200
    max_tickets = max(1, min(max_tickets, 2000))   # 硬上限：防呆（一次扫描的票数上界）
    try:
        q_to = float(args.get("query_timeout_sec") or 5.0)
    except (TypeError, ValueError):
        q_to = 5.0
    try:
        concurrency = int(args.get("concurrency") or 12)
    except (TypeError, ValueError):
        concurrency = 12
    try:
        scan_budget_sec = float(args.get("scan_budget_sec") or 90.0)
    except (TypeError, ValueError):
        scan_budget_sec = 90.0
    try:
        q_to_retry = float(args.get("snapshot_retry_timeout_sec"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        q_to_retry = 0.0
    if q_to_retry <= 0:
        q_to_retry = q_to * SNAPSHOT_RETRY_TIMEOUT_MULT

    # ---- 项目注册表（"全部项目"的真源；读不到=fail-closed 点名，不静默扫零票）----
    try:
        projects, quarantined = await asyncio.to_thread(list_registered_projects)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "项目注册表读取失败（lane/watchdog 面无从确定范围）：%s: %s"
                                      % (type(e).__name__, e)}
    known_keys = {str(p.get("key") or "") for p in (projects or []) if isinstance(p, dict)}
    known_keys.discard("")

    from temporalio.common import SearchAttributeKey
    from workflows_v2 import TEMPLATE_CLASSES

    try:
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "temporal server 不可达：%s: %s" % (type(e).__name__, e)}
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    now_ts = time.time()
    facts: List[Dict[str, Any]] = []
    errors: List[str] = []          # 跳过的（不在扫面口径内：无身份/非注册项目）
    unreadable: List[str] = []      # 在册非终态票但快照读不到（僵尸形态候选，逐票点名）
    enum_note = ""
    # ---- 枚举（快：只 list + 读 SA；真在册项目的非终态票）----
    targets: List[tuple] = []          # (ticket_id, run_id, project)
    try:
        async for wf in client.list_workflows('%s AND ExecutionStatus="Running"' % type_filter):
            try:
                sa_project = str(wf.typed_search_attributes.get(
                    SearchAttributeKey.for_keyword(PROJECT_SA_NAME)) or "")
            except Exception:  # noqa: BLE001 —— SA 读不出=归属未知，点名（不静默扫）
                sa_project = ""
            if not sa_project:
                errors.append("%s: no ProjectKey search attribute (ownership unknown, skipped)"
                              % wf.id)
                continue
            if known_keys and sa_project not in known_keys:
                # 非注册项目的票不属于本投影面（点名进 errors，不静默）
                errors.append("%s: project %r not in the project registry (skipped)"
                              % (wf.id, sa_project))
                continue
            if len(targets) >= max_tickets:
                enum_note = ("scan truncated at max_tickets=%d (more in-scope non-terminal "
                             "tickets exist)" % max_tickets)
                break
            targets.append((wf.id, wf.run_id, sa_project))
    except Exception as e:  # noqa: BLE001 —— 枚举面故障显式化（不静默零发现）
        return {"ok": False, "error": "非终态票枚举失败：%s: %s" % (type(e).__name__, e)}
    non_terminal = len(targets)

    # ---- 并发取快照（有界：并发度 + 总预算 + 单票超时；死票查询会等到超时，
    #     故必须三闸齐备——否则一次巡检被几百张无 worker 的 RUNNING 票拖死）----
    deadline = time.monotonic() + scan_budget_sec
    sem = asyncio.Semaphore(concurrency)
    budget_note: List[str] = []
    # t261001-05：读失败两分类台账。unreadable 仍是**全量**点名清单（fail-closed 不变，
    # 老消费方零回归）；transient/permanent 是它的两个互斥子清单（计数与文案分开）。
    unreadable_transient: List[str] = []
    unreadable_permanent: List[str] = []

    async def _read_once(tid: str, run_id: str, timeout_s: float):
        return await asyncio.wait_for(
            client.get_workflow_handle(tid, run_id=run_id).query("snapshot"),
            timeout=timeout_s)

    async def _read(tid: str, run_id: str, project: str):
        async with sem:
            if time.monotonic() >= deadline:
                budget_note.append(tid)
                # 预算耗尽=没读成，归瞬态（与「扫描时无应答」同性质），但不再重试（预算已尽）
                return (tid, project, None,
                        "scan budget (%ds) exhausted before this ticket " % int(scan_budget_sec),
                        True)
            try:
                snap = await _read_once(tid, run_id, q_to)
            except Exception as e:  # noqa: BLE001 —— 查不到=分类点名，绝不当「无问题」
                if _is_transient_read_error(e) and time.monotonic() < deadline:
                    # 瞬态：加长单票预算重试一次（仍受总预算 deadline 与并发闸钳制）
                    left = max(0.05, deadline - time.monotonic())
                    try:
                        snap = await _read_once(tid, run_id, min(q_to_retry, left))
                    except Exception as e2:  # noqa: BLE001 —— 重试仍败=按类点名
                        transient2 = _is_transient_read_error(e2)
                        return (tid, project, None,
                                "snapshot query failed after 1 retry: %s: %s"
                                % (type(e2).__name__, e2), transient2)
                    return tid, project, snap, "", False
                return (tid, project, None,
                        "snapshot query failed: %s: %s" % (type(e).__name__, e), False)
            return tid, project, snap, "", False

    for tid, project, snap, err, transient in await asyncio.gather(
            *[_read(*t) for t in targets]):
        if err:
            line = "%s: %s" % (tid, err)
            unreadable.append(line)
            (unreadable_transient if transient else unreadable_permanent).append(line)
            continue
        facts.append(facts_from_snapshot(tid, project, snap, workflow_id=tid, now_ts=now_ts))
    if budget_note:
        enum_note = (enum_note + " | " if enum_note else "") + (
            "%d ticket(s) not read within the %ds scan budget (first: %s)"
            % (len(budget_note), int(scan_budget_sec), budget_note[0]))

    findings, meta = lane_findings(facts, now_ts=now_ts, thresholds=thresholds,
                                   tickets_meta={"non_terminal": non_terminal})

    # ---- 第四判据：测试夹具临时目录水位（宿主级；只读扫描，零写）----
    #     注入口（tmp_fixture=扫描回执 dict）供 UT 用私有根跑真判据，绝不碰宿主真 $TMPDIR；
    #     缺省走 tmp_fixture_root（缺省 tempfile.gettempdir()）真扫。
    tmp_env = {TMP_ENV_MAX_DIRS: os.environ.get(TMP_ENV_MAX_DIRS),
               TMP_ENV_MAX_AGE_H: os.environ.get(TMP_ENV_MAX_AGE_H)}
    tmp_thr, tmp_src, tmp_note, tmp_problems = resolve_tmp_thresholds(
        args.get("watchdog"), tmp_env)
    injected = args.get("tmp_fixture")
    if isinstance(injected, dict):
        tmp_scan = dict(injected)
        tmp_scan.setdefault("root", str(args.get("tmp_fixture_root") or "<injected>"))
        tmp_scan["scanned_at"] = float(tmp_scan.get("scanned_at") or time.time())
        tmp_scan["injected"] = True
    else:
        tmp_root = str(args.get("tmp_fixture_root") or tempfile.gettempdir())
        try:
            tmp_ttl = float(args.get("tmp_fixture_scan_ttl_sec")
                            if args.get("tmp_fixture_scan_ttl_sec") is not None
                            else TMP_SCAN_CACHE_TTL_S)
        except (TypeError, ValueError):
            tmp_ttl = TMP_SCAN_CACHE_TTL_S
        tmp_scan = _scan_tmp_fixture_cached(tmp_root, TMP_FIXTURE_PREFIXES, tmp_ttl)
        tmp_scan["injected"] = False
    tmp_out = tmp_fixture_scan_result(tmp_scan, tmp_thr, source=tmp_src, note=tmp_note,
                                      now_ts=now_ts)
    tmp_out["scan_mode"] = "injected" if isinstance(injected, dict) else "scanned"
    tmp_out["scan_cached"] = bool(tmp_scan.get("cached"))
    tmp_out["threshold_problems"] = list(tmp_problems)

    meta["errors"] = errors
    meta["unreadable"] = unreadable
    meta["unreadable_transient"] = unreadable_transient
    meta["unreadable_permanent"] = unreadable_permanent
    meta["quarantined_projects"] = [str(q.get("dir") or "") for q in (quarantined or [])
                                    if isinstance(q, dict)]
    meta["enum_note"] = enum_note
    meta["scan_budget_sec"] = scan_budget_sec
    meta["concurrency"] = concurrency
    meta["threshold_source"] = thr_source
    meta["threshold_note"] = thr_note
    meta["scanned_at"] = now_ts
    meta["tmp_fixture"] = {"dirs": tmp_out["section"]["dirs"],
                           "oldest_age_h": tmp_out["section"]["oldest_age_h"],
                           "finding_count": tmp_out["section"]["finding_count"],
                           "thresholds": tmp_out["section"]["thresholds"],
                           "threshold_source": tmp_out["section"]["threshold_source"],
                           "scan_error": tmp_out["section"]["scan_error"],
                           "scan_mode": tmp_out["scan_mode"],
                           "scan_cached": tmp_out["scan_cached"],
                           "prefixes": list(TMP_FIXTURE_PREFIXES)}
    activity.logger.info("lane/watchdog：非终态票 %d 张（读到 %d 张；注册项目 %d 个），发现 %d 条（%s）；"
                         "夹具水位：%d 目录 / 最老 %.1fh / 发现 %d 条（%s）",
                         meta["non_terminal"], meta["scanned"], len(known_keys), len(findings),
                         ", ".join("%s=%d" % (k, v) for k, v in meta["by_leg"].items()),
                         tmp_out["section"]["dirs"], tmp_out["section"]["oldest_age_h"],
                         tmp_out["section"]["finding_count"],
                         tmp_out["section"]["threshold_source"])
    return {"ok": True, "result": {
        "findings": findings,
        "section": lane_section(findings, meta, source=thr_source, source_note=thr_note),
        # 票面用的**合并段**（票级三族 + 宿主水位；计数合并单点在纯函数面）：在活动侧算好，
        # 工作流只需取字段——工作流侧零算法、零新 import 面（沙箱/回放确定性都最省事）。
        "section_merged": merge_lane_section(
            lane_section(findings, meta, source=thr_source, source_note=thr_note),
            tmp_out["section"]),
        "tmp_fixture": tmp_out,
        "meta": meta}}


@activity.defn
async def resolve_inspection_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    """运行期「本期怎么跑」决议（t260913-02）：读**当前**巡检声明 → 是否跑套件 / cron /
    扫描面。纯实现=inspection_decl.resolve_instance_plan（本壳零业务判断）。

    为什么读声明而不是读输入：套件开关不进 workflow 输入 payload——老 worker 解新字段是
    反向兼容风险，且「改声明即改行为」纪律下 payload 不该成为第二真源；活动结果进
    history，replay 用记录值，确定性不破。失败=ok False 点名（workflow 转 blocked，
    绝不静默当 no-suite 放过去——调度还在触发而声明已停用/除名=配置漂移，必须可见）。"""
    from inspection_decl import resolve_instance_plan

    try:
        result = await asyncio.to_thread(
            resolve_instance_plan, str(args.get("instance_id") or ""),
            args.get("decl_path") or None)
    except Exception as e:  # noqa: BLE001——声明面故障显式化（不静默降级）
        return {"ok": False, "error": "声明决议 activity 故障：%s: %s" % (type(e).__name__, e)}
    if not result.get("ok"):
        return {"ok": False, "error": str(result.get("error") or "声明决议失败")}
    return {"ok": True, "result": result}


@activity.defn
async def run_inspection_deadman(args: Dict[str, Any]) -> Dict[str, Any]:
    """漏跑核查（t260913-02，票面注入面）：台账目录 × 声明 cron 期望触发日 → 漏跑清单 +
    发现条目。纯实现=inspection_deadman（本壳只做 IO 与时钟）。

    时间口径：**本地** datetime.now()（与期号 period_key 同一口径；workflow.now() 是 UTC，
    不用于漏跑判定）。台账目录走 shared.INSPECTION_DIR（env SANDBAR_INSPECTION_DIR 可覆盖
    ——隔离台/注入演练用）。"""
    from inspection_deadman import deadman_findings, ledger_periods, missed_periods
    from inspection_ticketing import spawn_skip_periods
    from shared import INSPECTION_DIR

    instance = str(args.get("instance_id") or "")
    cron = str(args.get("cron") or "")
    try:
        lookback = int(args.get("lookback_days") or 7)
    except (TypeError, ValueError):
        lookback = 7
    ledger_dir = Path(str(args.get("ledger_dir") or INSPECTION_DIR))
    tz_name = str(args.get("tz") or "")
    try:
        ledger = await asyncio.to_thread(ledger_periods, ledger_dir, instance)
        # 260929：声明式空转（skip_when_unchanged）的期号并入「已解释」集合——它们没跑是
        # **按声明判定的结果**，不是漏跑（审计面既不说谎，也不把告警报成噪声）。
        skipped = spawn_skip_periods(ledger_dir, instance)
        missed = (missed_periods(cron, ledger["periods"] | skipped, None, lookback, 0, tz_name)
                  if cron else [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "漏跑核查故障：%s: %s" % (type(e).__name__, e)}
    findings = deadman_findings(missed, instance, cron, lookback)
    activity.logger.info("[%s] 漏跑核查（tz=%s）：台账 %d 期（exist=%s）、漏 %d 期、畸形 %d 条",
                         instance, tz_name or "进程缺省", ledger["count"], ledger["exist"],
                         len(missed), len(ledger["malformed"]))
    # 260927 code_stamp（宿主裁定②）：漏跑核查活动同样落一行代码身份（无套件档的期也有）
    from shared import code_stamp_line, worker_code_stamp
    _stamp = worker_code_stamp()
    return {"ok": True, "result": {
        "code_stamp": code_stamp_line(_stamp), "code_stamp_detail": _stamp,
        "instance_id": instance, "cron": cron, "lookback_days": lookback,
        "tz": tz_name,
        "ledger_dir": str(ledger_dir), "ledger_exist": ledger["exist"],
        "ledger_periods": sorted(ledger["periods"]), "missed": missed,
        "skipped_no_change": sorted(skipped),
        "malformed": ledger["malformed"], "findings": findings}}


@activity.defn
async def count_archived_tickets(args: Dict[str, Any]) -> Dict[str, Any]:
    """Ticket-count source for the watcher（t260911-02）：per-key 归档目录计数。
    纯实现=inspection_ticket_count.count_archived_tickets（本壳零业务判断）；
    projects_root 可由 args 显式注入（隔离台用），缺省走 env/默认根（shared 同语义）。"""
    from inspection_ticket_count import count_archived_tickets as count_impl

    try:
        result = await asyncio.to_thread(
            count_impl, str(args.get("projects_root") or ""),
            str(args.get("project_key") or ""))
    except Exception as e:  # noqa: BLE001——真基础设施故障显式化（Temporal 重试面）
        return {"ok": False, "error": "计数 activity 异常：%s: %s" % (type(e).__name__, e)}
    if not result.get("ok"):
        return {"ok": False, "error": str(result.get("error"))}
    return {"ok": True, "result": result["result"]}


@activity.defn
def inspection_period_identity(args: Dict[str, Any]) -> str:
    """期票归属项目身份的单一取值点（t260915-20 R2/R3，纯函数单测友好）：
    **只认** args["instance_project_key"]（实例级身份键）——watcher 计数源
    project_key 即使混进 args 也不得串用（身份≠计数源，两 key 分叉时票面/SA 必须归
    身份键；串键=静默错挂，正是本票要杀的族）。缺省空=旧 watcher payload（跨部署
    过渡窗）——票面 project 空，双空形态在 workflow 侧被无主守卫拦成 blocked。"""
    return str((args or {}).get("instance_project_key") or "").strip()


@activity.defn
async def trigger_inspection_period(args: Dict[str, Any]) -> Dict[str, Any]:
    """watcher → 巡检期票（t260911-02；t260916-02 起票收敛到 inspection_ticketing 单点）：
    铸 t 形工单号 + 显式去重（实例+期号 SA 查询 / 指针三态 / AlreadyStarted 归属判定）
    + 盖 ProjectKey 与 InspectionInstance/InspectionPeriod SA——去重与铸号语义全部住在
    open_period_ticket，本壳零业务判断。task_queue 用 activity 自身所在队列（watcher 与
    巡检票同 worker 池）。
    t260915-20：instance_project_key（watcher 透传的实例级身份）→ payload project_key
    + ProjectKey SA，全链用身份键（inspection_period_identity 单一取值点）。"""
    from inspection_ticketing import open_period_ticket

    instance_id = str(args.get("instance_id") or "")
    period = str(args.get("period") or "")
    if not instance_id or not period:
        return {"ok": False, "error": "watcher 开票缺 instance/period（%r/%r）"
                % (instance_id, period)}
    project_key = inspection_period_identity(args)
    try:
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    except Exception as e:  # noqa: BLE001——连接失败显式点名（不谎报去重/票号）
        return {"ok": False, "error": "temporal server 不可达：%s" % e}
    res = await open_period_ticket(
        client, instance_id=instance_id, period=period, project_key=project_key,
        repo_root=str(args.get("repo_root") or ""),
        scan_face=str(args.get("scan_face") or "test"),
        decl_path=str(args.get("decl_path") or ""),
        fixture_mark=str(args.get("fixture_mark") or ""),
        task_queue=activity.info().task_queue)
    if res.get("ok"):
        res["result"]["period"] = period
        res["result"]["instance"] = instance_id
    return _with_spawn_decision(res, instance_id, period, face="watcher")


def _resolve_spawn_identity(args: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, str]:
    """起票身份决议（t260917-02 R2 身份回退链，纯函数）。

    project_key = args 显式 → plan.instance_project_key（声明面真源）→ ""；
    repo_root  = args 显式 → 按决议身份 resolve_project_root（注册表 dirs[0]）。

    为何必须在起票前点名（fail-closed）：无主守卫只拦「双空」票——260917 实况的旧
    action payload 恰是「repo_root 单键非空、无 project_key」，若原样透传会铸出
    ProjectKey 空的票（SA 三件套缺一=本票要消的缺陷族新形态）。身份与 repo_root 都
    决议不出（无身份/未知 key）→ ValueError，调用方显式失败可见，绝不静默回落引擎仓。

    face 不在本函数：旧 payload 的 face 一律不采信（scan_face 恒由调用处
    `args.face or plan.scan_face` 决议——重定向路径 face 空传即走当前声明，「改声明即
    改行为」纪律不变）。"""
    from shared import resolve_project_root
    project_key = str(args.get("project_key") or "").strip() \
        or str(plan.get("instance_project_key") or "").strip()
    repo_root = str(args.get("repo_root") or "").strip()
    if not repo_root:
        repo_root = str(resolve_project_root(project_key))
    return {"project_key": project_key, "repo_root": repo_root}


def _inspection_ledger_dir() -> Path:
    """巡检台账目录（口径与 inspection_trigger._default_ledger_dir / 各处活动一致：
    SANDBAR_INSPECTION_DIR → shared.INSPECTION_DIR）。"""
    return Path(os.environ.get("SANDBAR_INSPECTION_DIR") or INSPECTION_DIR)


def _no_change_skip(instance_id: str, repo_root: str) -> Dict[str, Any]:
    """声明式空转判据（260929 宿主令：simplify-face 每天跑一次、无新变更不干活）。

    「上次运行的基点 sha」↔「当前 main HEAD」相同 ⇒ 本期无事可做。任一侧读不出/形态不合
    ⇒ 不跳（宁可多跑一次，绝不假跳）。git 面复用 agent_activities.resolve_main_head_impl
    （单一真源；阻塞 git 一律 to_thread，同该模块纪律）。"""
    from agent_activities import resolve_main_head_impl
    from inspection_ticketing import last_run_base, no_change_skip
    head = resolve_main_head_impl({"repo_root": repo_root, "ref": "main"})
    if not head.get("ok"):
        return {"unchanged": False, "why": "", "head": "",
                "note": "HEAD 解析不出（%s）——不跳，照常起票" % str(head.get("error"))[:160]}
    sha = str((head.get("result") or {}).get("sha") or "")
    last = last_run_base(_inspection_ledger_dir(), instance_id)
    verdict = no_change_skip(last.get("base_ref", ""), sha, last.get("period", ""))
    return {"unchanged": bool(verdict["unchanged"]), "why": verdict["why"], "head": sha,
            "last_period": last.get("period", ""), "last_base": last.get("base_ref", ""),
            "note": ""}


def _with_spawn_decision(res: Any, instance_id: str, period: str, face: str) -> Any:
    """起票回执补「裁决摘要」并落可观测面（260929，KI-129 修法②/KI-131 未修块）。

    去重命中（triggered=false）此前只活在 workflow 返回值里——自动班连着几天不产出
    任何票/报告/告警而无人知（260929 宿主体感「巡检没有了」的机制半边）。本壳把裁决
    写进台账目录 `inspection-spawn.jsonl` 与 admin.log（inspection_ticketing.
    note_spawn_decision），并把摘要并回回执：workflow 结果里也能直接读到
    decision/alarm/note。写失败只在回执点名（journal_error/audit_write_failed），
    绝不影响起票结果本身。"""
    from inspection_ticketing import note_spawn_decision
    note = note_spawn_decision(_inspection_ledger_dir(), instance_id, period, res, face=face)
    keys = ("decision", "alarm", "note", "journal_path", "journal_error",
            "audit_call_id", "audit_write_failed")
    if isinstance(res, dict):
        target = res["result"] if isinstance(res.get("result"), dict) else res
        for k in keys:
            if k in note:
                target[k] = note[k]
    return res


@activity.defn
async def spawn_inspection_period(args: Dict[str, Any]) -> Dict[str, Any]:
    """spawner → 真票起票薄壳（t260916-02；t260917-02 扩重定向复用面）：cron 调度每
    fire 的铸期与开票都在这里——期号按**声明 tz 的日历日**铸（resolve_instance_plan 的
    tz 口径，与 deadman 期望键同链；声明 enabled=false/除名 → plan ok=False → spawner
    action 显式失败可见，延续「调度还在触发而声明已停用=配置漂移」的点名语义）。开票走
    open_period_ticket 单点（并发去重全链/指针三态/SA 三件套全数继承，零重实现）。
    decl_path 恒空（cron 形态）→ plan 走聚合解析（worker 当前声明），改声明即改行为。

    t260917-02 新增两分支（存量 spawner 调用零变化）：
    - args.period 可选透传：空=按声明 tz 现铸（原行为）；非空=workflow 侧重定向守卫
      把**自己已铸的期号**传下来（防双决议在 tz 边界漂移出两个期）。
    - 身份回退链 _resolve_spawn_identity：args 缺 project_key（旧 action payload 的
      260917 实况）→ 按 plan.instance_project_key 回退；repo_root 缺 → 按身份解析
      注册表。都决议不出=显式失败（见该函数 docstring）。

    260929（KI-129 修法②/KI-131 未修块）：起票裁决一律落可观测面（台账目录
    `inspection-spawn.jsonl` + admin.log 一行，见 inspection_ticketing.note_spawn_decision）
    ——去重命中不再是「只活在返回值里」的静默跳过，回执也把裁决摘要带回 workflow 结果。"""
    from datetime import datetime
    from inspection_decl import resolve_instance_plan
    from inspection_flow import period_key_in_tz
    from inspection_ticketing import note_spawn_decision, open_period_ticket

    instance_id = str(args.get("instance_id") or "")
    if not instance_id:
        return {"ok": False, "error": "spawn 缺 instance_id"}
    plan = resolve_instance_plan(instance_id, str(args.get("decl_path") or "") or None)
    if not plan.get("ok"):
        return {"ok": False, "error": str(plan.get("error") or "声明决议失败")}
    period = str(args.get("period") or "") \
        or period_key_in_tz(datetime.now(), str(plan.get("tz") or ""))
    try:
        ident = _resolve_spawn_identity(args, plan)
    except ValueError as e:  # noqa: BLE001——身份决议不出=显式失败（fail-closed 点名）
        return {"ok": False, "error": "spawn 身份决议失败：%s" % e}
    # 声明式空转（260929 宿主令，decl 键 skip_when_unchanged）：无新变更 → 只落一行裁决
    # 记录、不铸票不跑（漏跑核查读该记录，不误报漏跑）。判据读不出 ⇒ 不跳（绝不假跳）。
    if bool(plan.get("skip_when_unchanged")):
        skip = await asyncio.to_thread(_no_change_skip, instance_id, ident["repo_root"])
        if skip.get("unchanged"):
            return _with_spawn_decision(
                {"ok": True, "result": {
                    "triggered": False, "deduped": False, "skipped": "no-new-changes",
                    "skipped_because": str(skip.get("why") or ""),
                    "head": skip.get("head", ""), "last_period": skip.get("last_period", ""),
                    "last_base": skip.get("last_base", ""),
                    "instance": instance_id, "period": period}},
                instance_id, period, face="cron")
    try:
        client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "temporal server 不可达：%s" % e}
    res = await open_period_ticket(
        client, instance_id=instance_id, period=period,
        project_key=ident["project_key"],
        repo_root=ident["repo_root"],
        scan_face=str(args.get("face") or plan.get("scan_face") or "test"),
        decl_path=str(args.get("decl_path") or ""),
        # KI-191：夹具标记透传（cron 真班缺省空串=真班语义逐字不变；快进夹具经
        # spawn payload 带 fixture_mark 即入隔离的夹具期空间）
        fixture_mark=str(args.get("fixture_mark") or ""),
        task_queue=activity.info().task_queue)
    if res.get("ok"):
        res["result"]["period"] = period
        res["result"]["instance"] = instance_id
    return _with_spawn_decision(res, instance_id, period, face="cron")


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
    # KI-122①（260926 宿主直修令）：已知红名册只读面（裁决采纳判据的名册归属）
    read_known_red_roster,
    write_scan_report,
    run_inspection_scan,
    write_inspection_report,
    count_archived_tickets,
    trigger_inspection_period,
    # t260913-02：运行期声明决议（套件开关）+ 漏跑核查（票面注入面）
    resolve_inspection_plan,
    run_inspection_deadman,
    # 260926（KI-122 追加面 / KI-126 同源）：lane/watchdog 只读面——扫非终态票的
    # 工作流快照与时间线（同票重跑轮次 / tests-fault 回路停留 / 在飞静默僵尸）
    run_inspection_lane_watchdog,
    # t260916-02：spawner→真票起票薄壳（cron 调度铸 t 形号的载体）
    spawn_inspection_period,
    # t260916-22：inspect 段 report 面机械复核（证据复核/去重压制/预算/汇总）；
    # run_inspection_scan 已退役（保留服务老票 replay，见其退役注记）。
    verify_inspection_findings,
    # t260916-22：发现级裁定的持久面（收口一次写齐；票内 signal 只改内存）。
    write_inspection_verdicts,
    # t260928-13：事件账本写活动（append-only per-project JSONL；真源 event_ledger.py）
    _append_event_ledger,
]
