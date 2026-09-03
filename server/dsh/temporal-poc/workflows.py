"""Workflow 层 = 状态机本体。

260823 多项目化清理：旧 `TicketWorkflow`（步2 adopt 时代，JSON 投影）已随
server/dsh/tickets/ 投影目录一并退场——工单真源恒为 Temporal workflow，
v2 模版即代码在 base.py / workflows_v2.py（六模版子类）。

本文件保留步1 的 ContentPipelineWorkflow / DispatcherScanWorkflow（向后兼容）。
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
    from shared import (
        HUMAN_GATES,
        STAGES,
        PipelineInput,
        QcResult,
        ScanReport,
        Signature,
        StageAttempt,
        TicketScan,
    )


# ========================================================================================
# 步1 向后兼容：ContentPipelineWorkflow / DispatcherScanWorkflow
# ========================================================================================

MAX_REVISIONS = 2


@workflow.defn
class ContentPipelineWorkflow:
    """content-pipeline 七段：propose→approve(人)→process→machine-qc(脚本)
    →ai-review→final-review(人)→publish。"""

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
        if sig.gate not in HUMAN_GATES:
            self.refused_attempts.append(
                {"who": sig.who, "want": f"sign({sig.gate})", "why": "非人门，签字无效"})
            workflow.logger.warn("拒绝签字：%s 不是人门", sig.gate)
            return
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


# M6（t260821-m6-scan-expand）巡检扩权的版本分支 id：老 running 实例 replay 走旧分支
# （分布统计），新实例走扩权分支（检查报告）。改本 workflow 执行逻辑时必须 bump/新增。
SCAN_PATCH_ID = "dispatcher-scan-v2"
# 260824 每工单专属 worker：巡检顺带做 worker 对账（补拉/回收）。独立 patch id——
# 在跑的旧实例 replay 时跳过对账段，保持确定性。
WORKER_RECONCILE_PATCH_ID = "dispatcher-scan-worker-reconcile"


@workflow.defn
class DispatcherScanWorkflow:
    """dispatcher 例行巡检。M6 扩权：从「工单分布统计」扩为「settled/awaiting-human
    待决工单检查报告」——逐张出 stage/停留时长/验收勾选率/脚本门红绿灯/pending 数/
    建议动作（疑似卡死/待补/可签），落盘 out/scan/<日期>.json 供工单台展示。
    260824 追加：专属 worker 对账（reconcile_ticket_workers，回收漏退的；
    A 案起补拉归 console keepalive ensure，本 workflow 只记账不 spawn）。

    红线：只出建议不出决定，签字只能人。确定性规约：读工单、查脚本门、写文件
    全在 activity（scan_tickets_report / write_scan_report），workflow 只消费返回值。
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        retry = RetryPolicy(maximum_attempts=3)
        if not workflow.patched(SCAN_PATCH_ID):
            # M6 前旧分支（老实例 replay 兼容）：只做分布统计。
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
            # 专属 worker 对账：回收收口工单的漏退 worker；RUNNING 缺 worker 记 missing
            # 留痕（A 案起补拉归 console keepalive ensure，巡检不再 daemon 补拉）。
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


ALL_WORKFLOWS = [ContentPipelineWorkflow, DispatcherScanWorkflow]
