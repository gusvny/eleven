"""inspection_flow — the inspection ticket skeleton (inspection epic ticket 1,
t260905-03).

A lightweight inspection ticket template: scan → report → human gate → close (no plan /
implement stages). One ticket per period: the period key = instance id + current date,
the ticket id is the workflow id (inspection-<instance>-<period>), and a repeated trigger
with the same ticket id is rejected by the server's AlreadyStarted — that is the
mechanical guarantee of one ticket per period (overlap semantics SKIP, borrowed from
trade-off list item 1; a ticket opens even on an all-green run — a zero-finding ticket is
the heartbeat proof).

Red line (carried on every ticket-face posting): inspection only produces reports and
ticket-opening suggestions, it never modifies code directly; every fix goes through a
dev-lane ticket that references the inspection ticket (source_inspection=<inspection
ticket id>).

Human gate (M3): reuses the existing ticket approval-gate machinery — signal sign with a
Signature payload (shared.Signature: who is injected by the caller, agents may not sign
for themselves); this template only defines its own gate id (inspection-close). Closing
is unreachable before approval (stage_state=awaiting-human really blocks) and happens
only after it.

Determinism discipline: the workflow body does zero IO and zero wall-clock (only
workflow.now()); every side effect lives in an activity (run_inspection_scan /
write_inspection_report, thin shells in activities.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

# shared's module top has Path.resolve/environ (non-deterministic), so inside a workflow
# context this import must be passed through per repo convention (same as workflows.py's
# header), otherwise the sandbox validation goes red.
with workflow.unsafe.imports_passed_through():
    from shared import Signature

CLOSE_GATE_ID = "inspection-close"
INSPECTION_RED_LINE = "巡检只出报告与开票建议，绝不直接改码；修复一律走 dev-lane 工单。"
# Agents may not sign for themselves (reusing Signature semantics): the human gate's who
# must not be one of the M10 five agent role names.
AGENT_ROLE_NAMES = frozenset({"developer", "integration", "ops", "product-operation", "artist"})
# 期号两形态（t260911-02 接线 every-n-tickets/race-first）：cron 期=纯 YYYYMMDD；
# 计数期=YYYYMMDD-<bucket>（同日多期可区分；一票一期按（实例,期号）去重不变）。
PERIOD_RE = re.compile(r"^\d{8}(-[1-9]\d*)?$")
MAX_WHO_LEN = 64

RETRY = RetryPolicy(maximum_attempts=3)
SHORT_TO = timedelta(minutes=5)
SCAN_TO = timedelta(minutes=15)


# ========================================================================================
# Pure logic (the unit-test surface): period keys / ticket ids / face rendering /
# signature validation / posting
# ========================================================================================

def period_key(now: Optional[datetime] = None) -> str:
    """Period key = the current date (YYYYMMDD) — the cron-period form. Count periods
    (YYYYMMDD-<bucket>) are minted by the ticket-count watcher
    (inspection_ticket_count.decide / count_period)."""
    dt = now or datetime.now()
    return dt.strftime("%Y%m%d")


def inspection_ticket_id(instance_id: str, period: str) -> str:
    """Inspection ticket id = workflow id (a repeated trigger with the same id = the same
    ticket, the mechanical one-ticket-per-period guarantee)."""
    if not instance_id or not PERIOD_RE.match(period or ""):
        raise ValueError("票号组成非法：instance=%r period=%r（期号须 YYYYMMDD 或 "
                         "YYYYMMDD-<bucket>）" % (instance_id, period))
    return "inspection-%s-%s" % (instance_id, period)


def watcher_workflow_id(instance_id: str) -> str:
    """watcher workflow id（C-2，review_plan gen1 条件项）：id 从声明确定导出——同声明
    重跑 schedule-up 必命中同一 workflow（幂等拉起/复活的前提）。形状变更=运维契约
    变更，须带单测锁定（test_t260911_02_watcher.py）。"""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        raise ValueError("watcher id 组成非法：instance=%r（小写 slug）" % instance_id)
    return "inspection-watcher-%s" % instance_id


def validate_trigger_args(instance_id: str, period: str) -> Optional[str]:
    """Trigger arguments fail-closed (an extension of trade-off list item 6); returns an
    error message or None."""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        return "instance 非法：%r（小写 slug）" % instance_id
    if not PERIOD_RE.match(period or ""):
        return "period 非法：%r（须 YYYYMMDD 或 YYYYMMDD-<bucket>）" % period
    return None


def build_ticket_face(
    ticket_id: str,
    instance_id: str,
    period: str,
    scan_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Put the finding list onto the ticket face (rendering data): per-severity with
    evidence + heartbeat + ticket-opening suggestions (zero code changes)."""
    if not ticket_id or not instance_id:
        raise ValueError("票面缺票号/实例")
    if not isinstance(scan_result, dict) or not isinstance(scan_result.get("findings"), list):
        raise ValueError("扫描结果畸形：缺 findings 列表（fail-closed，不渲染）")
    findings = scan_result.get("findings") or []
    counts = scan_result.get("summary") or {"high": 0, "med": 0, "low": 0}
    heartbeat = bool(scan_result.get("heartbeat"))
    suggestions: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("severity") not in ("high", "med"):
            continue
        suggestions.append({
            "template": "dev-lane",
            "title": "修:%s %s" % (f.get("scan", ""), str(f.get("subject", ""))[:60]),
            "source_inspection": ticket_id,           # the fix ticket references the inspection ticket id (epic tickets 1/4)
            "urgency": "立即开票" if f.get("severity") == "high" else "人审后定",
            "evidence": f.get("evidence", ""),
        })
    return {
        "ticket_id": ticket_id,
        "kind": "inspection",
        "instance_id": instance_id,
        "period": period,
        "red_line": INSPECTION_RED_LINE,
        "heartbeat": heartbeat,
        "heartbeat_note": "全绿期=零发现票（心跳证明）" if heartbeat else "",
        "summary": counts,
        "findings": findings,
        "suggested_fix_tickets": suggestions,
        "scan_meta": scan_result.get("meta") or {},
    }


def validate_close_signature(sig: Any, expected_gate: str = CLOSE_GATE_ID) -> Tuple[Optional[Dict[str, str]], str]:
    """Validate the human-gate signature (reusing Signature semantics): returns
    (normalized payload, error message). Self-signing by an agent (who matches one of the
    five agent role names) is refused — only a human may sign."""
    if isinstance(sig, Signature):
        payload = {"who": sig.who, "gate": sig.gate, "decision": sig.decision, "note": sig.note or ""}
    elif isinstance(sig, dict):
        payload = {"who": str(sig.get("who") or ""), "gate": str(sig.get("gate") or ""),
                   "decision": str(sig.get("decision") or ""), "note": str(sig.get("note") or "")}
    else:
        return None, "签字载荷类型非法：%s" % type(sig).__name__
    if not payload["who"].strip():
        return None, "签字缺 who（签字身份由调用方注入）"
    if len(payload["who"]) > MAX_WHO_LEN:
        return None, "who 超长（>%d）" % MAX_WHO_LEN
    if payload["who"].strip().lower() in AGENT_ROLE_NAMES:
        return None, "agent 不得自签（who=%r 是 agent 角色名；签字只能人）" % payload["who"]
    if payload["gate"] != expected_gate:
        return None, "签字 gate 不匹配：%r（本门=%r）" % (payload["gate"], expected_gate)
    if payload["decision"] not in ("approve", "reject"):
        return None, "decision 只认 approve/reject（got %r）" % payload["decision"]
    return payload, ""


def write_inspection_report_impl(face: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    """Posting (a pure impl; the activity is a thin shell around it):
    out/inspection/<ticket id>.json, a re-run of the same ticket overwrites that single
    file."""
    ticket_id = str(face.get("ticket_id") or "")
    if not ticket_id:
        raise ValueError("落账缺 ticket_id")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.json" % ticket_id)
    path.write_text(json.dumps(face, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file": path.name, "path": str(path), "ticket_id": ticket_id}


# ========================================================================================
# Workflow: scan → report → human gate → close
# ========================================================================================

@dataclass
class InspectionPeriodicInput:
    """Input for one inspection period (declaration instance + period key; an empty
    period = derived from workflow.now() — the schedule-triggered path)."""

    instance_id: str
    # 兼容红线（t260910-11）：声明 schema 的 face 字段已除名（零消费者），但本输入
    # 结构保留 face 并给默认值——历史 workflow 重放按字段名解码，删字段会解码报错。
    # 新代码不得再消费该值（报告输出里的 "face" 键已随本票删除）。
    face: str = "test"
    period: str = ""
    repo_root: str = ""
    scenarios_path: str = ""


@workflow.defn
class InspectionPeriodicWorkflow:
    """One inspection-period ticket. State machine: scan → report → close (human gate) →
    a terminal closed state.
    Business refusals do not raise: a scan/posting failure → a blocked terminal ticket
    (visible, queryable), never a fake green."""

    def __init__(self) -> None:
        self.stage: str = ""
        self.stage_state: str = "running"
        self.status: str = "running"
        self.decision: str = ""
        self.face: Dict[str, Any] = {}
        self.timeline: List[Dict[str, Any]] = []
        self._close_sig: Optional[Dict[str, str]] = None
        self._gate_err: str = ""

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        self.stage = stage
        self.stage_state = state
        self.timeline.append({
            "at": workflow.now().isoformat(timespec="seconds"),
            "stage": stage, "state": state, "reason": reason})

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """Human-gate signature (the existing approval-gate machinery). A signature whose
        gate does not match is ignored with a note, never accepted by mistake.

        t260912-03：本巡检模板无授权面——带 authorize 的载荷在 validate 之前显式拒收
        （validate_close_signature 不感知 authorize，若放行会被当作普通人门签字）。"""
        if getattr(sig, "authorize", None) is not None:
            self._gate_err = "本巡检模板无人授权面，authorize 载荷拒收（不落签字）"
            workflow.logger.warning("拒收 authorize 载荷：本巡检模板无人授权面")
            return
        payload, err = validate_close_signature(sig)
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收签字：%s", err)
            return
        if self._close_sig is None:
            self._close_sig = payload

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        """Ticket-face snapshot (consumed by the workbench / ops channel; shape = a
        ticket: stage/stage_state/status/face/timeline)."""
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection",
            "template": "inspection-lite",
            "stage": self.stage,
            "stage_state": self.stage_state,
            "status": self.status,
            "decision": self.decision,
            "face": self.face,
            "timeline": self.timeline,
            "gate_error": self._gate_err,
        }

    @workflow.run
    async def run(self, inp: InspectionPeriodicInput) -> Dict[str, Any]:
        period = inp.period or period_key(workflow.now())
        ticket_id = inspection_ticket_id(inp.instance_id, period)
        # C4（t260910-09 review）：时间线文案带 face 值——新面票不再误写「测试面」；face 字段透传进 activity 分派
        self._enter("scan", "running", "%s 面扫描（实例 %s 期 %s）" % (inp.face, inp.instance_id, period))
        scan_result: Dict[str, Any] = await workflow.execute_activity(
            "run_inspection_scan",
            args=[{"repo_root": inp.repo_root, "scenarios_path": inp.scenarios_path,
                   "face": inp.face}],
            start_to_close_timeout=SCAN_TO, retry_policy=RETRY)
        if not scan_result.get("ok"):
            self.status = "blocked"
            self._enter("scan", "blocked", str(scan_result.get("error") or "扫描失败"))
            self.face = {"ticket_id": ticket_id, "kind": "inspection", "instance_id": inp.instance_id,
                         "period": period, "red_line": INSPECTION_RED_LINE,
                         "heartbeat": False, "summary": {}, "findings": [],
                         "suggested_fix_tickets": [], "blocked_reason": str(scan_result.get("error"))}
            return self.snapshot()
        self._enter("report", "running", "发现清单落票面（%d 条）" % len(scan_result["result"].get("findings") or []))
        self.face = build_ticket_face(ticket_id, inp.instance_id, period, scan_result["result"])
        written: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self.face],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if written.get("ok"):
            self.face["report_path"] = written["result"].get("path", "")
        # Human gate: closing is unreachable before approval (awaiting-human really blocks)
        self._enter("close", "awaiting-human", "人审发现清单：sign(gate=%s) approve=收口 / reject=毙单收口" % CLOSE_GATE_ID)
        await workflow.wait_condition(lambda: self._close_sig is not None)
        self.decision = self._close_sig["decision"]  # type: ignore[index]
        self.status = "closed"
        self.face["human_gate"] = dict(self._close_sig or {})
        self._enter("close", "running", "收口：人门决策=%s（who=%s）" % (self.decision, (self._close_sig or {}).get("who", "")))
        final: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self.face],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if final.get("ok"):
            self.face["report_path"] = final["result"].get("path", "")
        self._enter("close", "done", "巡检票收口（决策=%s，发现 high=%s/med=%s/low=%s）" % (
            self.decision, self.face.get("summary", {}).get("high", 0),
            self.face.get("summary", {}).get("med", 0), self.face.get("summary", {}).get("low", 0)))
        return self.snapshot()


# ========================================================================================
# Ticket-count watcher（t260911-02）：every-n-tickets / race-first 的通用调度器。
# 每个启用的计数 kind 实例一个；workflow id=inspection-watcher-<instance>（从声明确定
# 导出——schedule-up 幂等拉起/复活的前提，C-2）。语义按方案 R2：计数越桶先触发
# （期号=YYYYMMDD-<bucket>）；cron 到点触发并复位基线（期号=纯 YYYYMMDD）；双侧规则
# 单点在 inspection_ticket_count.decide（单测面）。确定性纪律同主 workflow：workflow
# 体零 IO 零钟表（计数与开票都在 activity，唯一时间源=workflow.now()）。
# ========================================================================================

@dataclass
class InspectionWatcherInput:
    """Watcher 输入，全部由声明 spec 导出（schedule-up 是唯一生产侧拉起点）。
    baseline / cron_anchor / triggered_total 三字段跨 continue_as_new 携带状态
    （无界历史治理：每 WATCHER_MAX_ITERATIONS 轮换一代历史）。"""

    instance_id: str
    n: int = 0
    cron: str = ""
    scan_face: str = "test"
    repo_root: str = ""
    project_key: str = ""
    poll_seconds: float = 60.0
    baseline: int = -1                 # -1 = 基线未立（首轮成功计数即立，不回看历史票）
    cron_anchor: str = ""              # ISO datetime；空=cron 侧未激活
    triggered_total: int = 0


WATCHER_MAX_ITERATIONS = 500   # continue_as_new 节流（默认 60s 轮询≈每 8.3 小时换一代）


@workflow.defn
class InspectionTicketCountWatcherWorkflow:
    """常驻轮询调度器：计数 → 纯决策（decide）→ 开期票（票号幂等=一票一期去重兜底）。
    取消/失败终态随 workflow 自身收敛（Temporal 持久化）；死亡+复活=schedule-up
    （inspection_trigger.py）——本票新引入的可死机制的 KI-049 对答。"""

    def __init__(self) -> None:
        self.last_count: int = -1
        self.last_error: str = ""
        self.last_trigger: Dict[str, Any] = {}
        self.iterations: int = 0
        self._baseline: int = -1
        self._triggered_total: int = 0
        self._next_fire: Optional[datetime] = None
        self._last_event: Dict[str, Any] = {}

    def _enter(self, stage: str, state: str, reason: str) -> None:
        self._last_event = {"at": workflow.now().isoformat(timespec="seconds"),
                            "stage": stage, "state": state, "reason": reason}

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        """活性/运维面（`watcher` 子命令消费）：没有这份快照，死 watcher 不可见
        （KI-049 族纪律）。"""
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection-watcher",
            "last_count": self.last_count,
            "last_error": self.last_error,
            "last_trigger": self.last_trigger,
            "triggered_total": self._triggered_total,
            "baseline": self._baseline,
            "next_cron_fire": self._next_fire.isoformat(timespec="seconds") if self._next_fire else "",
            "iterations": self.iterations,
            "last_event": self._last_event,
        }

    @workflow.run
    async def run(self, inp: InspectionWatcherInput) -> Dict[str, Any]:
        # 输入形状 fail-closed：畸形 watcher 绝不「跑着但什么都不做」
        if not inp.instance_id or not inp.project_key or inp.n < 1:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                "watcher 输入非法：instance=%r project_key=%r n=%r"
                % (inp.instance_id, inp.project_key, inp.n), non_retryable=True)
        from inspection_ticket_count import decide, next_cron_fire
        self._baseline = inp.baseline
        self._triggered_total = inp.triggered_total
        anchor: datetime = (datetime.fromisoformat(inp.cron_anchor)
                            if inp.cron_anchor else workflow.now())
        self._next_fire = next_cron_fire(inp.cron, anchor) if inp.cron else None
        self._enter("poll", "running", "计数 watcher 运行（实例 %s，n=%d，源=archive-dir:%s，"
                    "cron=%s）" % (inp.instance_id, inp.n, inp.project_key, inp.cron or "无"))
        while True:
            res: Dict[str, Any] = await workflow.execute_activity(
                "count_archived_tickets",
                args=[{"project_key": inp.project_key}],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            now = workflow.now()
            cron_due = False
            if res.get("ok"):
                self.last_count = int((res.get("result") or {}).get("count", -1))
                self.last_error = ""
                if self._baseline < 0:
                    # 初始基线=0（存量计数按桶即判：当前计数已达 k*n 即触发当期；watcher
                    # 死亡复活后同桶重放由票号幂等去重兜底，不会双开票）
                    self._baseline = 0
                if self._next_fire is not None and now >= self._next_fire:
                    cron_due = True
            else:
                # 计数失败：如实进快照，绝不拿旧计数或 0 假判（「数不了」≠「0 张」）
                self.last_error = str(res.get("error") or "count failed")
                self._enter("poll", "running", "计数失败（本轮不判触发）：%s" % self.last_error)
            if res.get("ok") and self._baseline >= 0:
                d = decide(self.last_count, self._baseline, inp.n, cron_due, now)
                if d["trigger"]:
                    opened: Dict[str, Any] = await workflow.execute_activity(
                        "trigger_inspection_period",
                        args=[{"instance_id": inp.instance_id, "period": d["period"],
                               "repo_root": inp.repo_root, "scan_face": inp.scan_face}],
                        start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
                    deduped = bool((opened.get("result") or {}).get("deduped"))
                    self.last_trigger = {"kind": d["trigger"], "period": d["period"],
                                         "deduped": deduped}
                    self._triggered_total += 1
                    self._baseline = d["baseline"]
                    anchor = now                          # R2：任一侧触发都推进 cron 相位
                    self._next_fire = next_cron_fire(inp.cron, anchor) if inp.cron else None
                    self._enter("trigger", "running",
                                "%s 触发 → 期 %s（deduped=%s，基线=%d）"
                                % (d["trigger"], d["period"], deduped, self._baseline))
            self.iterations += 1
            if self.iterations >= WATCHER_MAX_ITERATIONS:
                workflow.continue_as_new(InspectionWatcherInput(
                    instance_id=inp.instance_id, n=inp.n, cron=inp.cron,
                    scan_face=inp.scan_face, repo_root=inp.repo_root,
                    project_key=inp.project_key, poll_seconds=inp.poll_seconds,
                    baseline=self._baseline,
                    cron_anchor=anchor.isoformat(timespec="seconds"),
                    triggered_total=self._triggered_total))
            await workflow.sleep(timedelta(seconds=inp.poll_seconds))
