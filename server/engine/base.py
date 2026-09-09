"""TicketWorkflowBase —— M11 v2「模版即代码」的六模版共享基类（票 t260822-m11）。

模版即代码 + stage 即 activity + 状态只在 workflow。本基类承载所有工单 workflow
共享的机制，六个子类只声明 STAGES（+各自 patched id）：

  - 通用主循环 `_main`：按 STAGES 顺序驱动——
      agent 段  → activity（名=stage 名）spawn headless agent，结果文件幂等；
      脚本门段  → script_gate activity（绿才推进，红则 blocked 等 retry_qc / rework signal）；
      人门段    → prepare_human_gate activity 做机械准备 → workflow.wait_condition 等 sign；
  - sign signal：人门签字（approve 推进 / reject 打回=按 revision_to 回路 rework）；
  - rework signal：回目标段重跑（payload 带 target_stage 与返工指令）；
  - retry_qc signal：blocked 后请求重跑本段（agent 段重跑活动 / 门段重跑脚本）；
  - update_status update：note/pending/book_path/status 维护（对外协议与旧类同名同载荷）；
  - snapshot query：保留旧 TicketWorkflow 的键（stage/stage_state/checks/handoffs/timeline…）
    并附 meta 全文（JSON 兼容工单形态）与 results（各段产物），工单台/ticket.py 直接消费；
  - 不变式：closed⇒¬awaiting-human；blocked 只允许 dispatched/settled/rework；
    awaiting-human 只在 exit=human 段。

确定性纪律：本文件零 IO、零随机、零 wall-clock（只有 workflow.now()）；一切副作用在
activity。版本化：每个子类声明独立 PATCH_ID，改执行逻辑前 bump/新增 patch id 并在变更点
用 workflow.patched() 分支（老 running 实例 replay 不破）。

temporalio 继承约束（实测 1.18.2）：@workflow.run 必须定义在子类上（薄壳转调 _main），
signal/query/update 可直接继承。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import asyncio
    from activities import script_gate
    from agent_activities import prepare_human_gate, prepare_workspace
    from shared import (
        ENGINE_V2,
        ENGINE_VERSION_V2,
        TICKET_STATUSES,
        WS_DIR_BASE,
        AgentStageArgs,
        GateResult,
        HumanGateContext,
        HumanGatePrep,
        ReworkRequest,
        Signature,
        Stage,
        StageResult,
        TicketInput,
        normalize_files_changed,
        WorkspacePrep,
        WorkspacePrepResult,
        agent_log_for,
        build_stage_prompt,
        lane_workspace_gate_error,
        result_file_for,
        stage_workspace,
    )

SHORT = timedelta(minutes=2)
GATE_TO = timedelta(minutes=15)
# agent 段：headless agent 是长活——start_to_close 给足，心跳保活（activity 侧 5s 一次）。
AGENT_TO = timedelta(hours=6)
HEARTBEAT_TO = timedelta(minutes=3)
RETRY = RetryPolicy(maximum_attempts=3)  # 只对基础设施故障生效；业务失败走 StageResult.status
# KI-003：stage 转换突变串让路点的版本化 marker（_breathe 内 workflow.patched 消费；
# 老在跑实例重放旧 history 无此 marker → 不让路，保重放确定）。
BREATHE_PATCH_ID = "ki003-breathe-v1"


class TicketWorkflowBase:
    """六模版子类的共享机制。子类只声明：
      STAGES: Tuple[Stage, ...]   —— stage 链（真源=代码）
      PATCH_ID: str               —— 本模版独立 patched id
      TEMPLATE_ID / TEMPLATE_NAME / TEMPLATE_LANE / TEMPLATE_DESC —— 供快照与 yaml 生成
      TEMPLATE_WORKSPACE_DIR: bool —— cleanup 类模板（已退役 260904）的 dir 隔离目录约定
      REVISION_STAGE / REVISION_LIMIT / REVISION_OVERFLOW —— 修订回路（content-pipeline，已退役 260904）
    """

    STAGES: tuple = ()
    PATCH_ID: str = "ticket-base-v3"
    TEMPLATE_ID: str = ""
    TEMPLATE_NAME: str = ""
    TEMPLATE_LANE: str = "main"
    TEMPLATE_DESC: str = ""
    TEMPLATE_WORKSPACE_DIR: bool = False
    REVISION_STAGE: str = ""
    REVISION_LIMIT: int = 2
    REVISION_OVERFLOW: str = ""

    def __init__(self) -> None:
        self.ticket_id: str = ""
        self.template_id: str = ""
        self.meta: Dict[str, Any] = {}
        self.results: Dict[str, Dict[str, Any]] = {}      # stage_id → StageResult 摘要
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self._sigs: Dict[str, Signature] = {}
        self._rework: Optional[ReworkRequest] = None
        self._retry_token: int = 0
        self._gens: Dict[str, int] = {}                   # stage_id → 进入次数（结果文件分代）
        self.gate_runs: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.human_context: Dict[str, Any] = {}
        self.engine_version: int = ENGINE_VERSION_V2

    # ---------- 内部：时间/日志/记账 ----------
    def _now_epoch(self) -> int:
        return int(workflow.now().timestamp())

    def _now_iso(self) -> str:
        return workflow.now().isoformat(timespec="seconds")

    def _log(self, note: str, status: Optional[str] = None) -> None:
        self.meta.setdefault("log", []).append(
            {"ts": self._now_epoch(), "status": status or self.meta.get("status", ""), "note": note})

    def _mark(self, stage: str, state: str, reason: str = "") -> None:
        self.timeline.append(
            {"at": self._now_iso(), "stage": stage, "state": state, "reason": reason})
        workflow.logger.info("[%s] %s/%s %s", self.ticket_id, stage, state, reason)

    def _touch(self) -> None:
        self.meta["updated"] = self._now_epoch()

    async def _breathe(self) -> None:
        """stage 转换突变串让路点（KI-003）：await 让出事件循环，给排队的
        snapshot query（与主协程共用同一 workflow 事件循环）一个执行窗口。

        为什么是 patched 分支而不是裸 sleep(0)：temporalio 1.18.2 里 sleep(0) 会发
        真 StartTimer 命令（0 时长无特判），旧在跑票重放旧 history 没有这个命令，
        直接睡会破确定性。所以旧 history 重放走原路径（无 marker 不让路），新执行 /
        live edge 走到这里 marker 落史后 sleep(0) 生效（0 长 timer 即发即回）。
        wait_condition(lambda: True) 不能当让路形态：重放期条件检查和 future 创建的
        时序可能让协程挂到下个 activation，没有唤回保证。
        另：DevLaneWorkflow 不继承本基类（同形不继承），它自带一份 _breathe
        （票 t260901-23：只加在 base 上对 dev-lane 票是 AttributeError）。"""
        if not workflow.patched(BREATHE_PATCH_ID):
            return  # 旧 history 重放：无 marker，跳过让路保重放确定
        await asyncio.sleep(0)

    # ---------- 内部：stage 查找 ----------
    def _stage_idx(self, stage_id: str) -> int:
        for i, s in enumerate(self.STAGES):
            if s.id == stage_id:
                return i
        return -1

    def _gen(self, stage_id: str) -> int:
        return self._gens.get(stage_id, 0)

    # ---------- 初始化 ----------
    def _init(self, inp: TicketInput) -> None:
        self.ticket_id = inp.ticket_id
        self.template_id = inp.template_id
        # patched 纪律：本类首次启用即打 patch 标记，后续改逻辑 bump 子类 PATCH_ID。
        workflow.patched(self.PATCH_ID)
        ws = inp.workspace
        if ws is None and self.TEMPLATE_WORKSPACE_DIR:
            ws = {"type": "dir", "path": WS_DIR_BASE + "/" + inp.ticket_id}
        first = self.STAGES[0]
        acc = list(first.acceptance) + [x for x in inp.acceptance_extra
                                        if x not in first.acceptance]
        self.meta = {
            "id": inp.ticket_id,
            "workflow_id": inp.template_id,
            "project": inp.project,
            "epic": inp.epic,
            "title": inp.title,
            "role": first.role,
            "lane": inp.lane or self.TEMPLATE_LANE,
            "workspace": ws,
            # 票 t260908-02：多仓/混合形态逐仓明细的真源位（meta 顶层）。workspace 归纯
            # {type, path}，不再内嵌 list（Dict[str, str] 注解与 Temporal 编解码兼容）。
            "repo_worktrees": list(inp.repo_worktrees),
            "worktree": inp.worktree,
            "branch": inp.branch,
            "base_ref": inp.base_ref,
            "proposal_id": inp.proposal_id,
            "book_path": inp.book_path,
            "stage": first.id,
            "stage_state": "awaiting",
            "write_set": list(inp.write_set),
            "acceptance": acc,
            "checks": {first.id: [{"item": it, "done": False, "by": ""} for it in acc]},
            "deliverables": inp.deliverables,
            # M16：正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body）；
            # spec=加工后派发规格（独立字段，不覆盖正文）。
            "user_request": inp.user_request,
            "spec": inp.spec,
            "body": inp.user_request or inp.body,
            "pending": [],
            "handoffs": [],
            "status": "dispatched",
            "created": inp.created or self._now_epoch(),
            "updated": self._now_epoch(),
            "revision_count": 0,
            "last_advance_stage": None,
            "temporal": True,
            # 入参快照（供工单详情页展示）
            "workflow_input": {
                "ticket_id": inp.ticket_id,
                "template_id": inp.template_id,
                "project": inp.project,
                "epic": inp.epic,
                "title": inp.title,
                "lane": inp.lane or self.TEMPLATE_LANE,
                "worktree": inp.worktree,
                "branch": inp.branch,
                "base_ref": inp.base_ref,
                "proposal_id": inp.proposal_id,
                "book_path": inp.book_path,
                "write_set": list(inp.write_set),
                "acceptance_extra": list(inp.acceptance_extra),
                "deliverables": inp.deliverables,
                "user_request": inp.user_request,
                "spec": inp.spec,
                "body": inp.body,
                "created": inp.created or self._now_epoch(),
            },
            "temporal_engine_version": self.engine_version,
            "engine": ENGINE_V2,
            "log": [{"ts": self._now_epoch(), "status": "dispatched",
                     "note": "工单创建（v2 模版即代码：%s → %s，stage=%s）"
                             % (inp.template_id, type(self).__name__, first.id)}],
        }
        self._gate_overrides = dict(inp.gate_overrides or {})
        self._mark(first.id, "awaiting", "adopt v2（模版=%s，stages=%s）"
                   % (inp.template_id, [s.id for s in self.STAGES]))

    # ---------- 段执行：agent 活动 ----------
    async def _run_agent_stage(self, st: Stage) -> Optional[StageResult]:
        """跑 agent 段活动。返回 None=成功；抛错=基础设施重试耗尽（调用方转 blocked）。"""
        gen = self._gen(st.id)
        # 阶段重跑上下文继承：同 role 再次调用时从工作流历史读上一次返回值
        previous_context = ""
        if gen > 1:
            prev = self.results.get(st.id)
            if prev:
                parts = ["- 上次状态：%s" % (prev.get("status") or "?")]
                summary = str(prev.get("summary") or "")
                if summary:
                    parts.append("- 上次摘要：%s" % summary)
                report = str(prev.get("report") or "")
                if report:
                    parts.append("- 上次报告：%s" % report[:1200])
                dels = prev.get("deliverables") or []
                if dels:
                    parts.append("- 上次产物：%s" % ", ".join(str(x) for x in dels))
                changed = prev.get("files_changed") or []
                if changed:
                    parts.append("- 上次改动文件：%s" % ", ".join(str(x) for x in changed))
                evidence = str(prev.get("evidence") or "")
                if evidence:
                    parts.append("- 上次验收证据：%s" % evidence)
                rework_note = str(self.meta.get("last_rework_note") or "")
                if rework_note:
                    parts.append("- 打回原因：%s" % rework_note)
                previous_context = "\n".join(parts)
        ws = stage_workspace(self.meta.get("workspace"), self.ticket_id)
        rfile = result_file_for(self.ticket_id, st.id, gen, ws)
        prompt = build_stage_prompt(self.ticket_id, self.meta, st,
                                    list(self.meta.get("handoffs") or []), rfile, gen,
                                    previous_context)
        args = AgentStageArgs(
            ticket_id=self.ticket_id, stage_id=st.id, role=st.role, prompt=prompt,
            workspace=ws, result_file=rfile,
            log_file=agent_log_for(self.ticket_id, st.id, gen, ws),
            gen=gen,
            workflow_id=str(self.meta.get("workflow_id") or ""),
            previous_context=previous_context)
        raw = await workflow.execute_activity(
            st.id, args,                       # activity 名 = stage 名（stage 即 activity）
            start_to_close_timeout=AGENT_TO, heartbeat_timeout=HEARTBEAT_TO,
            retry_policy=RETRY)
        # 按名调用无返回类型注解，dataclass 回包以 dict 形态回来——归一成 StageResult。
        # files_changed 保形归一（票 t260904-18 KI-049 门②）：形状随回执进 results
        # 字面（消费点 dev_lane 读 results dict，不读 StageResult 本体）。
        if isinstance(raw, StageResult):
            res = raw
        else:
            _fc, _fc_shape = normalize_files_changed(raw.get("files_changed"))
            res = StageResult(
                status=str(raw.get("status") or "ok"),
                summary=str(raw.get("summary") or ""),
                report=str(raw.get("report") or ""),
                deliverables=[str(x) for x in (raw.get("deliverables") or [])],
                files_changed=_fc,
                files_changed_shape=_fc_shape,
                evidence=str(raw.get("evidence") or ""))
        self.results[st.id] = {
            "status": res.status, "summary": res.summary, "report": res.report,
            "deliverables": list(res.deliverables),
            "files_changed": list(res.files_changed),
            "files_changed_shape": res.files_changed_shape,
            "evidence": res.evidence, "gen": gen}
        return res

    # ---------- 段执行：脚本门 ----------
    def _gate_for(self, st: Stage):
        return self._gate_overrides.get(st.id) or st.gate

    async def _run_gate(self, st: Stage) -> GateResult:
        gate = self._gate_for(st)
        res: GateResult = await workflow.execute_activity(
            script_gate, gate, start_to_close_timeout=GATE_TO, retry_policy=RETRY)
        self.gate_runs.append(
            {"stage": st.id, "label": res.label, "green": res.green,
             "red_count": res.red_count, "exit_code": res.exit_code, "checks": res.checks})
        return res

    # ---------- 段执行：人门 ----------
    async def _run_human_stage(self, st: Stage, idx: int) -> str:
        """人门段：activity 机械准备 → wait_condition 等 sign/rework。
        返回 'next'（签字通过）或 'rework'（打回/显式 rework，主循环统一跳段）。"""
        prep: HumanGateContext = await workflow.execute_activity(
            prepare_human_gate,
            HumanGatePrep(ticket_id=self.ticket_id, stage_id=st.id,
                          proposal_id=str(self.meta.get("proposal_id") or ""),
                          workspace=self.meta.get("workspace"),
                          worktree=str(self.meta.get("worktree") or ""),
                          base_ref=str(self.meta.get("base_ref") or ""),
                          title=str(self.meta.get("title") or "")),
            start_to_close_timeout=SHORT, retry_policy=RETRY)
        self.human_context[st.id] = {"context_text": prep.context_text, "note": prep.note}
        self.meta["stage_state"] = "awaiting-human"
        self._touch()
        self._log("人门挂起（%s），等 sign signal；%s" % (st.id, prep.note or "审查上下文已备妥"))
        self._mark(st.id, "awaiting-human", "等人签字：sign(gate=%s)" % st.id)
        await workflow.wait_condition(
            lambda: (st.id in self._sigs) or (self._rework is not None))
        if self._rework is not None:
            return "rework"
        sig = self._sigs.pop(st.id)
        self.signatures[st.id] = {"who": sig.who, "decision": sig.decision,
                                  "note": sig.note, "at": self._now_iso()}
        if sig.decision == "approve":
            self._finish_stage(st, by=sig.who,
                               evidence="人门签字：%s（%s，经 Temporal signal）"
                                        % (sig.note, sig.who))
            self._handoff(st, "人门签字通过（签字人 %s：%s）" % (sig.who, sig.note))
            self._log("sign approve: %s 放行（%s）" % (st.id, sig.who))
            return "next"
        # reject = 打回：缺省回 revision_to / 上一段
        target = st.revision_to or (self.STAGES[idx - 1].id if idx > 0 else "")
        self._rework = ReworkRequest(
            who=sig.who, target_stage=target,
            note="人在 %s 打回：%s（签字人 %s）" % (st.id, sig.note, sig.who))
        return "rework"

    # ---------- 记账：勾选/handoff ----------
    def _finish_stage(self, st: Stage, by: str, evidence: str) -> None:
        checks = self.meta.setdefault("checks", {}).setdefault(st.id, [])
        items = {c.get("item") for c in checks}
        for it in st.acceptance:
            if it not in items:
                checks.append({"item": it, "done": False, "by": ""})
        for c in checks:
            c["done"], c["by"] = True, by
            if evidence:
                c["evidence"] = evidence
        self.meta["last_advance_stage"] = st.id
        self._touch()

    def _handoff(self, st: Stage, summary: str,
                 artifacts: Optional[List[str]] = None, report: str = "") -> None:
        self.meta.setdefault("handoffs", []).append({
            "stage": st.id, "agent_id": "", "summary": summary, "report": report,
            "artifacts": list(artifacts or []), "ts": self._now_epoch(),
            "engine_version": self.engine_version})

    # ---------- rework ----------
    def _apply_rework(self, cur_idx: int) -> int:
        """rework 落段计算。返回目标段下标（非法目标 → 拒绝留痕，停原段）。"""
        req = self._rework
        self._rework = None
        cur = self.STAGES[cur_idx]
        target = req.target_stage or cur.revision_to \
            or (self.STAGES[cur_idx - 1].id if cur_idx > 0 else "")
        extra = ""
        if self.REVISION_STAGE and target == self.REVISION_STAGE:
            self.meta["revision_count"] = int(self.meta.get("revision_count") or 0) + 1
            if self.meta["revision_count"] > self.REVISION_LIMIT:
                target = self.REVISION_OVERFLOW or target
                extra = "（修订 %d 轮超限，回 %s）" % (self.meta["revision_count"], target)
        tidx = self._stage_idx(target)
        if tidx < 0:
            self.refused.append({"who": req.who, "want": "rework(%s)" % target,
                                 "why": "目标段不在本模版 stage 链中"})
            self._log("rework 拒绝：目标段 %r 不存在（%s）" % (target, req.who))
            return cur_idx
        tdef = self.STAGES[tidx]
        self.meta["stage"] = target
        self.meta["role"] = tdef.role
        self.meta["acceptance"] = list(tdef.acceptance)
        self.meta.setdefault("checks", {}).setdefault(
            target, [{"item": it, "done": False, "by": ""} for it in tdef.acceptance])
        self.meta["status"] = "rework"
        self.meta["stage_state"] = "awaiting"
        self.meta["last_advance_stage"] = None
        self.meta["last_rework_note"] = req.note     # 阶段重跑上下文继承：打回原因注入 previous_context
        self._touch()
        self._log("rework: %s（回 %s）%s——%s" % (req.note, target, extra, req.who))
        self._mark(target, "rework", "%s（%s）" % (req.note, req.who))
        return tidx

    # ---------- M16：工作区准备（workflow 第一个 activity） ----------
    async def _prepare_workspace(self) -> Dict[str, Any]:
        """跑 prepare_workspace 活动（worktree add / dir mkdir / 主树跳过；失败回执不抛）。

        先过泳道字段闸（lane_workspace_gate_error）：正常创建链路在 ticket-start 单点
        推导+校验，这里兜「旧 payload/未来新入口」绕过的情形——lane=worktree 但泳道
        字段不齐/不一致时按失败回执走 blocked 等人，不放给 activity 静默跳主树。"""
        gate = lane_workspace_gate_error(self.meta)
        if gate:
            return {"ok": False, "kind": "config", "action": "rejected",
                    "path": "", "error": gate}
        prep = WorkspacePrep(
            ticket_id=self.ticket_id,
            workspace=self.meta.get("workspace"),
            # 票 t260908-02：逐仓明细走独立字段（workspace 不再内嵌 list，编解码兼容）
            repo_worktrees=list(self.meta.get("repo_worktrees") or []),
            branch=str(self.meta.get("branch") or ""),
            base_ref=str(self.meta.get("base_ref") or ""))
        raw = await workflow.execute_activity(
            prepare_workspace, prep, start_to_close_timeout=SHORT, retry_policy=RETRY)
        # 按名调用无返回类型注解，回包以 dict 形态回来——归一成字段读
        res = raw if isinstance(raw, WorkspacePrepResult) else WorkspacePrepResult(
            ok=bool(raw.get("ok", True)), kind=str(raw.get("kind") or ""),
            action=str(raw.get("action") or ""), path=str(raw.get("path") or ""),
            error=str(raw.get("error") or ""))
        return {"ok": bool(res.ok), "kind": res.kind, "action": res.action,
                "path": res.path, "error": res.error}

    # ---------- 通用主循环（子类 @workflow.run 薄壳转调这里） ----------
    async def _main(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)
        # M16：工作区由 workflow 第一个 activity（prepare_workspace）创建/复用，agent 不再自己搞。
        # 失败 → blocked 等 retry_qc 重试 / rework 打回（目标段照常计算），不吞错。
        start_idx = 0
        while True:
            prep = await self._prepare_workspace()
            self.meta["workspace_prep"] = prep
            self._touch()
            if prep.get("ok"):
                self._mark("workspace", "ready",
                           "prepare_workspace: %s/%s" % (prep.get("kind"), prep.get("action")))
                break
            self.meta["stage_state"] = "blocked"
            self._log("工作空间准备失败 → blocked：%s" % (prep.get("error") or "未知"))
            self._mark("workspace", "blocked", prep.get("error") or "")
            token = self._retry_token
            await workflow.wait_condition(
                lambda: self._retry_token > token or self._rework is not None)
            if self._rework is not None:
                start_idx = self._apply_rework(start_idx)
            self.meta["stage_state"] = "running"
            self._mark("workspace", "running", "重试 prepare_workspace（retry_qc / rework 后）")
        idx = start_idx
        while idx < len(self.STAGES):
            st = self.STAGES[idx]
            self._gens[st.id] = self._gen(st.id) + 1
            self.meta["stage"] = st.id
            self.meta["role"] = st.role
            # v2 状态语义：编排进行中恒 dispatched（无逐项 settle/verify 人工动作）；
            # rework 后重进段即回 dispatched；终态由收尾置 closed。
            self.meta["status"] = "dispatched"
            self.meta["stage_state"] = "running"
            acc = list(st.acceptance)
            if not self.meta.get("acceptance") or self.meta.get("stage") == st.id:
                # 首段保留 create 时的实例增项；后续段=模版清单
                if self._gen(st.id) > 1 or idx > 0:
                    self.meta["acceptance"] = acc
            self.meta.setdefault("checks", {}).setdefault(
                st.id, [{"item": it, "done": False, "by": ""} for it in acc])
            self._touch()
            self._mark(st.id, "running", "进入本段（kind=%s，第 %d 次）"
                       % (st.kind, self._gen(st.id)))

            if st.kind == "human":
                outcome = await self._run_human_stage(st, idx)
                if outcome == "rework":
                    idx = self._apply_rework(idx)
                    continue
                idx += 1
                continue

            # agent / gate 段：失败（业务红灯或活动故障）→ blocked，等 retry_qc / rework
            while True:
                failure = ""
                if st.kind == "agent":
                    try:
                        res = await self._run_agent_stage(st)
                    except Exception as e:  # activity 重试耗尽：基础设施故障
                        failure = "agent 活动故障（已重试）：%s: %s" % (type(e).__name__, e)
                        res = None
                    if res is not None and res.status != "ok":
                        failure = "agent 报失败：%s" % (res.summary or res.status)
                    if res is not None and res.status == "ok":
                        self._finish_stage(st, by=st.role + "-agent",
                                           evidence=res.evidence or res.summary)
                        self._handoff(st, res.summary or "阶段完成",
                                      artifacts=res.deliverables, report=res.report)
                gate = self._gate_for(st) if not failure else None
                if gate is not None:
                    gres = await self._run_gate(st)
                    if not gres.green:
                        failure = "脚本门 %s 红灯 %d 项" % (gres.label, gres.red_count)
                if not failure:
                    break
                self.meta["stage_state"] = "blocked"
                self._touch()
                self._log("%s → blocked，等 retry_qc 重跑或 rework 打回" % failure)
                self._mark(st.id, "blocked", failure)
                token = self._retry_token
                await workflow.wait_condition(
                    lambda: self._retry_token > token or self._rework is not None)
                if self._rework is not None:
                    break
                self.meta["stage_state"] = "running"
                self._mark(st.id, "running", "retry_qc 重跑本段")
            if self._rework is not None:
                idx = self._apply_rework(idx)
                continue
            self._touch()
            idx += 1

        # 全部段完成：自动收口（v2 无人工驱动；人门除外）
        last = self.STAGES[-1]
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("全部段完成，自动收口（closed）")
        self._mark(last.id, "closed", "workflow 完成")
        return self._snapshot()

    # ---------- signal：人门签字 / rework / retry_qc ----------
    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """人门签字。gate 必须是当前等待的 exit=human 段 id（空则取当前段）。"""
        stage = str(self.meta.get("stage") or "")
        st = self.STAGES[self._stage_idx(stage)] if self._stage_idx(stage) >= 0 else None
        if not (st and st.exit == "human"):
            self.refused.append({"who": sig.who, "want": "sign(%s)" % sig.gate,
                                 "why": "当前段 %s 非人门，签字无效" % stage})
            return
        if sig.gate and sig.gate != stage:
            self.refused.append({"who": sig.who, "want": "sign(%s)" % sig.gate,
                                 "why": "gate 与当前等待段 %s 不符" % stage})
            return
        self._sigs[stage] = sig

    @workflow.signal
    def rework(self, req: ReworkRequest) -> None:
        """打回重跑：目标段重进（gen+1 → 结果文件换新，agent 真重跑）。"""
        self._rework = req
        self._log("rework 请求：%s → %s（%s）"
                  % (req.note, req.target_stage or "缺省目标", req.who))

    @workflow.signal
    def retry_qc(self, who: str) -> None:
        """blocked 后请求重跑本段（脚本门重跑 / agent 段重跑）。"""
        self._retry_token += 1
        self.timeline.append(
            {"at": self._now_iso(), "stage": str(self.meta.get("stage") or ""),
             "state": "retry-requested",
             "reason": "%s 请求重跑（第 %d 次）" % (who, self._retry_token)})

    # ---------- update：状态维护（对外协议与旧类同名同载荷） ----------
    @workflow.update
    async def update_status(self, status: str, note: str, pending_add: str,
                            book_path: Optional[str]) -> Dict[str, Any]:
        if status:
            if status not in TICKET_STATUSES:
                return {"ok": False, "error": "非法 status: %r" % status}
            self.meta["status"] = status
            if status == "settled" and self.meta.get("stage_state") == "running":
                self.meta["stage_state"] = "awaiting"
        if self.meta.get("status") == "closed" and self.meta.get("stage_state") == "awaiting-human":
            self.meta["stage_state"] = "awaiting"
            note = (note + "；" if note else "") + "closed 清 awaiting-human（A3.3）"
        if self.meta.get("stage_state") == "blocked" \
                and self.meta["status"] not in ("dispatched", "settled", "rework"):
            return {"ok": False, "error": "blocked 只允许 status∈{dispatched,settled,rework}（A3.5），当前 %s"
                    % self.meta["status"]}
        if book_path is not None:
            self.meta["book_path"] = book_path
        if pending_add:
            self.meta.setdefault("pending", []).append(
                {"ts": self._now_epoch(), "note": pending_add})
        if note:
            self._log(note)
        self._touch()
        return {"ok": True, "id": self.ticket_id, "status": self.meta["status"],
                "stage": self.meta.get("stage"), "stage_state": self.meta.get("stage_state"),
                "log_len": len(self.meta.get("log") or [])}

    # ---------- query：只读快照（旧键全保留 + meta 全文 + results） ----------
    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        stage = str(self.meta.get("stage") or "")
        idx = self._stage_idx(stage)
        sdef: Optional[Stage] = self.STAGES[idx] if idx >= 0 else None
        return {
            "engine": ENGINE_V2,
            "ticket_id": self.ticket_id,
            "template_id": self.template_id,
            "workflow_class": type(self).__name__,
            "stage": stage,
            "stage_name": sdef.name if sdef else "",
            "stage_acceptance": list(sdef.acceptance) if sdef else [],
            "stage_state": self.meta.get("stage_state"),
            "status": self.meta.get("status"),
            "role": self.meta.get("role"),
            "workspace": self.meta.get("workspace"),
            "revision_count": self.meta.get("revision_count"),
            "last_advance_stage": self.meta.get("last_advance_stage"),
            "temporal_engine_version": self.meta.get("temporal_engine_version"),
            "acceptance": self.meta.get("acceptance"),
            "checks": self.meta.get("checks"),
            "handoffs": self.meta.get("handoffs"),
            "pending": self.meta.get("pending"),
            "signatures": self.signatures,
            "gate_runs": self.gate_runs,
            "refused": self.refused,
            "timeline": self.timeline,
            "results": self.results,
            "human_context": self.human_context,
            "retry_count": self._retry_token,
            "meta": dict(self.meta),
        }

    def _snapshot(self) -> Dict[str, Any]:
        return self.snapshot()
