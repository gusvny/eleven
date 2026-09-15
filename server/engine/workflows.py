"""Workflow layer = the state machine itself.

Multi-project cleanup (260823): the old `TicketWorkflow` (from the step-2 adopt
era, a JSON projection) was retired together with the server/tickets/ projection
directory — the ticket source of truth is always the Temporal workflow, and the
v2 templates live as code in base.py / workflows_v2.py (six template subclasses).

This file keeps the step-1 ContentPipelineWorkflow / DispatcherScanWorkflow
(backward compatibility).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from activities import (
        ai_review_stub,
        machine_qc,
        process_stage,
        publish_dry_run,
        reconcile_ticket_workers,
        record_signature,
        scan_tickets_report,
        ticket_scan,
        write_scan_report,
    )
    from inspection_flow import (  # noqa: F401——registered into ALL_WORKFLOWS
        InspectionPeriodicWorkflow,
        InspectionTicketCountWatcherWorkflow,
    )
    from shared import (
        HUMAN_GATES,
        STAGES,
        PipelineInput,
        QcResult,
        ScanReport,
        Signature,
        StageAttempt,
        TicketScan,
        cross_project_judge,
    )


# ========================================================================================
# Step-1 backward compat: ContentPipelineWorkflow / DispatcherScanWorkflow
# ========================================================================================

MAX_REVISIONS = 2


@workflow.defn
class ContentPipelineWorkflow:
    """content-pipeline, seven stages: propose→approve(human)→process→machine-qc(script)
    →ai-review→final-review(human)→publish."""

    def __init__(self) -> None:
        self.stage: str = STAGES[0]
        self.stage_state: str = "running"
        self.blocked_reason: str = ""
        self.timeline: List[Dict[str, Any]] = []
        self.signatures: Dict[str, Dict[str, str]] = {}
        self._sigs: Dict[str, Signature] = {}
        self.qc_runs: List[Dict[str, Any]] = []
        self.qc_retry_token: int = 0
        self.revisions: int = 0
        self.refused_attempts: List[Dict[str, Any]] = []
        self.result: str = ""

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        assert stage in STAGES, f"未知段 {stage}"
        self.stage = stage
        self.stage_state = state
        self.blocked_reason = reason
        self.timeline.append(
            {"at": workflow.now().isoformat(timespec="seconds"),
             "stage": stage, "state": state, "reason": reason})
        workflow.logger.info("stage → %s (%s) %s", stage, state, reason)

    @workflow.run
    async def run(self, inp: PipelineInput) -> Dict[str, Any]:
        short = timedelta(minutes=2)
        qc_to = timedelta(minutes=10)
        retry = RetryPolicy(maximum_attempts=3)

        self._enter("propose")
        await workflow.execute_activity(
            process_stage, f"提案 {inp.proposal_id} 已登记：{inp.title}",
            start_to_close_timeout=short, retry_policy=retry)

        self._enter("approve", "awaiting-human", "等人签字：sign(gate=approve)")
        await workflow.wait_condition(lambda: "approve" in self._sigs)
        sig = self._sigs["approve"]
        await workflow.execute_activity(
            record_signature, sig, start_to_close_timeout=short, retry_policy=retry)
        if sig.decision != "approve":
            self._enter("approve", "blocked", f"人否决：{sig.note}")
            self.result = "rejected-at-approve"
            return self.snapshot()

        while True:
            self._enter("process", "running", f"第 {self.revisions + 1} 轮加工")
            await workflow.execute_activity(
                process_stage, f"{inp.proposal_id} 加工轮次 {self.revisions + 1}",
                start_to_close_timeout=short, retry_policy=retry)

            while True:
                self._enter("machine-qc", "running", f"跑 {inp.qc.label}")
                res: QcResult = await workflow.execute_activity(
                    machine_qc, inp.qc, start_to_close_timeout=qc_to, retry_policy=retry)
                self.qc_runs.append(
                    {"green": res.green, "red_count": res.red_count, "scope": res.scope,
                     "label": res.label, "exit_code": res.exit_code, "checks": res.checks})
                if res.green:
                    break
                self._enter("machine-qc", "blocked",
                            f"机器门红灯 {res.red_count} 项 → 不推进；修好后 signal retry_qc")
                token = self.qc_retry_token
                await workflow.wait_condition(lambda: self.qc_retry_token > token)

            self._enter("ai-review")
            review = await workflow.execute_activity(
                ai_review_stub, inp.qc.scope, start_to_close_timeout=short, retry_policy=retry)
            workflow.logger.info("ai-review: %s", review)

            self._sigs.pop("final-review", None)
            self.signatures.pop("final-review", None)
            self._enter("final-review", "awaiting-human", "等人终审：sign(gate=final-review)")
            await workflow.wait_condition(lambda: "final-review" in self._sigs)
            fsig = self._sigs["final-review"]
            await workflow.execute_activity(
                record_signature, fsig, start_to_close_timeout=short, retry_policy=retry)
            if fsig.decision == "approve":
                break
            self.revisions += 1
            if self.revisions > MAX_REVISIONS:
                self._enter("final-review", "blocked",
                            f"修订已 {self.revisions} 轮（上限 {MAX_REVISIONS}）→ 交人裁决，不自动发布")
                self.result = "blocked-revision-limit"
                return self.snapshot()
            self._enter("final-review", "running", f"人打回：{fsig.note} → 回加工")

        self._enter("publish")
        self.result = await workflow.execute_activity(
            publish_dry_run, inp.proposal_id, start_to_close_timeout=short, retry_policy=retry)
        self._enter("publish", "awaiting", "已发布（dry-run）")
        return self.snapshot()

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        # t260912-03：带 authorize 的人授权载荷只认 dev_lane 的 sign 面；本模板
        # （content-pipeline 人门族）无授权面——显式拒收（不得被当作普通人门签字
        # 按 decision=approve 放行）。
        if getattr(sig, "authorize", None) is not None:
            self.refused_attempts.append(
                {"who": sig.who, "want": "sign(authorize)",
                 "why": "本模板无人授权面，authorize 载荷拒收（不落签字）"})
            workflow.logger.warn("拒绝 authorize 载荷：本模板无人授权面")
            return
        if sig.gate not in HUMAN_GATES:
            self.refused_attempts.append(
                {"who": sig.who, "want": f"sign({sig.gate})", "why": "非人门，签字无效"})
            workflow.logger.warn("拒绝签字：%s 不是人门", sig.gate)
            return
        # t260915-12 跨项目闸（第二道，统一接闸不留分叉）：本模板 meta 无 project 面
        # →judge 对 target="" 恒放行；未来模板补项目面时此处自动升级为拒收/记名。
        g = cross_project_judge(str(getattr(sig, "caller_project", "") or ""), "",
                                str(getattr(sig, "cross_project_note", "") or ""))
        if g["action"] == "refuse":
            self.refused_attempts.append({"who": sig.who, "want": "sign", "why": g["why"]})
            workflow.logger.warn("%s", g["why"])
            return
        if g["action"] == "allow_record":  # 理论不可达（无项目面）——防御性 log 留痕
            workflow.logger.warn("跨项目写操作记名（本模板无 meta 记名面，仅此处日志）：%s",
                                 g["why"])
        self._sigs[sig.gate] = sig
        self.signatures[sig.gate] = {
            "who": sig.who, "decision": sig.decision, "note": sig.note,
            "at": workflow.now().isoformat(timespec="seconds")}

    @workflow.signal
    def retry_qc(self, who: str) -> None:
        self.qc_retry_token += 1
        self.timeline.append(
            {"at": workflow.now().isoformat(timespec="seconds"), "stage": self.stage,
             "state": "retry-requested",
             "reason": f"{who} 请求重跑机器门（第 {self.qc_retry_token} 次）"})

    @workflow.signal
    def force_stage(self, attempt: StageAttempt) -> None:
        self.refused_attempts.append(
            {"who": attempt.who, "want": attempt.want_stage,
             "why": "状态只由 workflow 代码推进；越过门的写状态请求无效",
             "stage_when_asked": self.stage})
        workflow.logger.warn("拒绝改状态：%s 想把 %s 改成 %s", attempt.who, self.stage, attempt.want_stage)

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_state": self.stage_state,
            "blocked_reason": self.blocked_reason,
            "signatures": self.signatures,
            "qc_runs": self.qc_runs,
            "qc_retry_count": self.qc_retry_token,
            "revisions": self.revisions,
            "refused_attempts": self.refused_attempts,
            "result": self.result,
            "timeline": self.timeline,
        }


# M6 (t260821-m6-scan-expand) version-branch patch id for the scan expansion:
# old running instances replay the old branch (distribution stats); new instances
# take the expanded branch (check report). When changing this workflow's execution
# logic, bump or add a patch id.
SCAN_PATCH_ID = "dispatcher-scan-v2"
# 260824 per-ticket dedicated worker: the scan also reconciles workers (pull
# missing / reap stray). Separate patch id — old running instances skip the
# reconcile section on replay, keeping determinism.
WORKER_RECONCILE_PATCH_ID = "dispatcher-scan-worker-reconcile"


@workflow.defn
class DispatcherScanWorkflow:
    """Dispatcher routine scan. M6 expansion: from "ticket distribution stats" to
    a "settled/awaiting-human pending-ticket check report" — per ticket it emits
    stage / dwell time / acceptance check rate / script-gate red-green / pending
    count / suggested action (suspected-stuck / needs-supply / signable), written
    to out/scan/<date>.json for the ticket desk to display.
    260824 addition: dedicated-worker reconcile (reconcile_ticket_workers, reaping
    workers that failed to exit; since plan A, pull-missing moved to console
    keepalive ensure, so this workflow only records, never spawns).

    Red line: suggestions only, no decisions — signing is human-only. Determinism
    contract: reading tickets, checking script gates, and writing files all happen
    in activities (scan_tickets_report / write_scan_report); the workflow only
    consumes their return values.
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        retry = RetryPolicy(maximum_attempts=3)
        if not workflow.patched(SCAN_PATCH_ID):
            # Pre-M6 old branch (kept for replay compat of old instances): distribution stats only.
            scan: TicketScan = await workflow.execute_activity(
                ticket_scan,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry)
            workflow.logger.info("巡检：%s 张工单，卡住 %s 张", scan.total, len(scan.stuck))
            return {
                "total": scan.total,
                "by_status": scan.by_status,
                "stuck": scan.stuck,
                "scanned_at": workflow.now().isoformat(timespec="seconds"),
            }
        report: ScanReport = await workflow.execute_activity(
            scan_tickets_report,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry)
        written: Dict[str, Any] = await workflow.execute_activity(
            write_scan_report, report,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry)
        reconcile: Dict[str, Any] = {}
        if workflow.patched(WORKER_RECONCILE_PATCH_ID):
            # Dedicated-worker reconcile: reap workers that failed to exit for
            # settled tickets; RUNNING tickets missing a worker are recorded as
            # missing (since plan A, pull-missing moved to console keepalive
            # ensure — the scan no longer daemon-pulls).
            reconcile = await workflow.execute_activity(
                reconcile_ticket_workers,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry)
        workflow.logger.info(
            "巡检：%s 张工单，待决 %s 张（疑似卡死 %s / 待补 %s / 可签 %s）→ %s",
            report.total_tickets, len(report.items),
            report.summary.get("疑似卡死", 0), report.summary.get("待补", 0),
            report.summary.get("可签", 0), written.get("path"))
        return {
            "total": report.total_tickets,
            "by_status": report.by_status,
            "pending_decision": len(report.items),
            "summary": report.summary,
            "report_file": written.get("file"),
            "report_path": written.get("path"),
            "worker_reconcile": reconcile,
            "scanned_at": workflow.now().isoformat(timespec="seconds"),
        }


# t260911-02：watcher（计数触发调度器）入注册表——workflow 注册真源只有这一行清单
# （worker.py 只汇总导入本清单；R4 修正：不新增 per-workflow 注册点）。
ALL_WORKFLOWS = [ContentPipelineWorkflow, DispatcherScanWorkflow, InspectionPeriodicWorkflow,
                 InspectionTicketCountWatcherWorkflow]
