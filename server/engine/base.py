"""TicketWorkflowBase — the shared base class of the six M11 v2 "template as code"
templates (ticket t260822-m11).

Template as code + stage as activity + state only in the workflow. This base
class carries every mechanism shared by the ticket workflows; the six subclasses
only declare STAGES (+ their own patched ids):

  - Generic main loop `_main`: drives the stages in STAGES order —
      agent stage  → activity (name = stage name) spawns a headless agent, the
                     result file is idempotent;
      script gate  → script_gate activity (green is the only pass; red goes
                     blocked waiting for a retry_qc / rework signal);
      human gate   → prepare_human_gate activity does the mechanical prep →
                     workflow.wait_condition waits for sign;
  - sign signal: human-gate signature (approve advances / reject sends back =
    rework along the revision_to loop);
  - rework signal: rerun from a target stage (payload carries target_stage and
    the rework instruction);
  - retry_qc signal: after blocked, request a rerun of the current stage (agent
    stage reruns the activity / gate stage reruns the script);
  - update_status update: note/pending/book_path/status maintenance (external
    protocol same name and payload as the old class);
  - snapshot query: keeps the old TicketWorkflow keys (stage/stage_state/checks/
    handoffs/timeline…) plus the full meta (JSON-compatible ticket shape) and
    results (per-stage artifacts); the ticket desk / ticket.py consume it directly;
  - invariants: closed⇒¬awaiting-human; blocked only allows dispatched/settled/
    rework; awaiting-human only on exit=human stages.

Determinism discipline: zero IO, zero randomness, zero wall-clock in this file
(only workflow.now()); all side effects live in activities. Versioning: each
subclass declares its own PATCH_ID; before changing execution logic, bump or add
a patch id and branch with workflow.patched() at the change point (old running
instances replay without breaking).

temporalio inheritance constraint (verified on 1.18.2): @workflow.run must be
defined on the subclass (a thin shell forwarding to _main); signal/query/update
can be inherited directly.
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
        PAUSE_NOTE_INPUT_LIMIT,
        PAUSE_PATCH_ID,
        PauseRequest,
        ReworkRequest,
        Signature,
        Stage,
        StageResult,
        TicketInput,
        WORKER_SHUTDOWN_RETRY_PATCH_ID,
        cross_project_judge,
        format_agent_stage_failure,
        normalize_files_changed,
        retry_once_on_worker_termination,
        WorkspacePrepResult,
        agent_log_for,
        build_stage_prompt,
        build_workspace_prep,
        lane_workspace_gate_error,
        result_file_for,
        stage_workspace,
    )

SHORT = timedelta(minutes=2)
GATE_TO = timedelta(minutes=15)
# Agent stages: a headless agent is a long runner — give start_to_close plenty of
# room, heartbeats keep it alive (the activity side heartbeats every 5s).
AGENT_TO = timedelta(hours=6)
HEARTBEAT_TO = timedelta(minutes=3)
RETRY = RetryPolicy(maximum_attempts=3)  # only for infrastructure failures; business failures go through StageResult.status
# KI-003: versioned marker for the stage-transition yield point (consumed by
# workflow.patched inside _breathe; old running instances replaying old history
# have no marker → no yield, keeping replay deterministic).
BREATHE_PATCH_ID = "ki003-breathe-v1"


class TicketPauseMixin:
    """段间暂停机制（工单 t260908-01，设计基准=notes/epics/ticket-pause.md）——所有
    工单 workflow 的共用骨架：pause/resume 信号 + 段间等待门 + paused 二态快照。

    子类接线（dev_lane 侧零私有逻辑=本 mixin 全包）：
      ①继承本 mixin——temporalio 的 signal/query/update 装饰器可继承（本文件头注
        已证 1.18.2），TicketWorkflowBase 与 DevLaneWorkflow 同款挂法；
      ②在自己的主循环段间门口调 `await self._pause_gate()`（每轮相位/段切换前）；
      ③snapshot() 返回字典并 `**self._pause_snapshot()`。

    语义（拍板①②）：
    - 粒度=段间暂停：pause 受理只置位，不打断在飞 activity——当前段（含在飞 agent
      activity）自然跑完，主循环走到下一个段间门口时门把它停住，不派下一段；
      resume 清位后 wait_condition 唤醒，接着走。
    - 仅人门：信号唯一入口=client.py ticket op=pause/resume（与 sign/rework 同族
      的 CLI 信号通道），agent prompt/activities 无发送面。
    - 暂停是正交维度：不碰 status/stage_state 状态机（blocked/awaiting-human 票
      也可暂停——语义=retry_qc 重跑完本段即停门口）。
    - pause×rework 交互（显式声明）：门插在 rework 分支之前，暂停期间到达的 rework
      压在门口，resume 后循环先走 rework 分支（打回先于下一段派发）。

    反馈可辨（幂等）：重复 pause / 空态 resume / 畸形 payload（who 空白、note 超
    PAUSE_NOTE_INPUT_LIMIT）均落 refused（文案点名原因，不进事件历史，host_ruling
    同款 intake gate）；成功 pause/resume 落 _log+timeline。
    """

    _paused: bool = False         # 类属性缺省（布尔不可变，不碰子类 __init__）
    _paused_at_gate: bool = False

    @workflow.signal
    def pause(self, req: PauseRequest) -> None:
        who = str(req.who or "").strip()
        note = str(req.note or "")
        # R4（review_plan gen1）：老 RUNNING 实例（功能上线前开出的票）重放/执行时
        # 事件历史无 PAUSE marker → 门恒 no-op。若受理置位，snapshot/UI 会谎称
        # 「已暂停」而 workflow 照跑（KI-018 误导信号同族）——改为一处可辨拒绝。
        if not workflow.patched(PAUSE_PATCH_ID):
            self.refused.append({"who": who, "want": "pause",
                                 "why": "该工单启动于暂停功能上线前，不支持暂停"
                                        "（事件历史无 ticket-pause-v1 marker）"})
            return
        if not who:
            self.refused.append({"who": who, "want": "pause",
                                 "why": "who 必填非空（空/纯空白拒收）"})
            return
        if len(note) > PAUSE_NOTE_INPUT_LIMIT:
            self.refused.append({"who": who, "want": "pause",
                                 "why": "note 超限（%d > %d 字符），不进事件历史——"
                                        "拆条后重发" % (len(note), PAUSE_NOTE_INPUT_LIMIT)})
            return
        if self._paused:
            self.refused.append({"who": who, "want": "pause",
                                 "why": "已处于暂停（幂等拒绝，重复 pause 不重复置位）"})
            return
        # t260915-12 跨项目闸（第二道）：受理置位前的项目归属校验（记名/拒收）。
        if not self._cross_project_gate(str(getattr(req, "caller_project", "") or ""),
                                        str(getattr(req, "cross_project_note", "") or ""),
                                        "pause", who, "pause"):
            return
        self._paused = True
        self._paused_at_gate = False
        self._log("pause 受理（%s）%s——当前段自然跑完，停在段间门口等 resume"
                  % (who, "：%s" % note if note else ""))
        self._mark(str(self.meta.get("stage") or ""), "paused",
                   "%s（%s）" % (note, who) if note else who)
        self._touch()

    @workflow.signal
    def resume(self, req: PauseRequest) -> None:
        who = str(req.who or "").strip()
        note = str(req.note or "")
        # resume 无 patched 前置分支：老实例 _paused 恒 False（pause 已被前置拒收），
        # 自然落「未处于暂停」空态拒绝——一处分支不重复。
        if not who:
            self.refused.append({"who": who, "want": "resume",
                                 "why": "who 必填非空（空/纯空白拒收）"})
            return
        if len(note) > PAUSE_NOTE_INPUT_LIMIT:
            self.refused.append({"who": who, "want": "resume",
                                 "why": "note 超限（%d > %d 字符），不进事件历史——"
                                        "拆条后重发" % (len(note), PAUSE_NOTE_INPUT_LIMIT)})
            return
        if not self._paused:
            self.refused.append({"who": who, "want": "resume",
                                 "why": "未处于暂停（空态拒绝）"})
            return
        # t260915-12 跨项目闸（第二道）：同 pause 口径。
        if not self._cross_project_gate(str(getattr(req, "caller_project", "") or ""),
                                        str(getattr(req, "cross_project_note", "") or ""),
                                        "resume", who, "resume"):
            return
        self._paused = False
        self._paused_at_gate = False
        self._log("resume（%s）%s——段间门口放行，继续派段"
                  % (who, "：%s" % note if note else ""))
        self._mark(str(self.meta.get("stage") or ""), "resumed",
                   "%s（%s）" % (note, who) if note else who)
        self._touch()

    async def _pause_gate(self) -> None:
        """段间门口：主循环每次相位/段切换前调用。未暂停=零开销返回；已暂停→
        paused_at_gate 置位 + wait_condition 等 resume。门本身是 await 点，事件
        循环让出，snapshot 查询暂停期照常可跑（KI-008 相邻面天然覆盖）。
        回放安全（KI-003 _breathe 同款纪律）：老实例重放无 marker → 门为 no-op。"""
        if not workflow.patched(PAUSE_PATCH_ID):
            return
        if not self._paused:
            return
        self._paused_at_gate = True
        self._mark(str(self.meta.get("stage") or ""), "paused-waiting",
                   "段间暂停生效，等 resume signal")
        await workflow.wait_condition(lambda: not self._paused)
        self._paused_at_gate = False
        self._mark(str(self.meta.get("stage") or ""), "resumed",
                   "resume 放行，继续派段")

    def _pause_snapshot(self) -> Dict[str, Any]:
        """paused 二态快照键（pending=已受理待段间生效——当前段还在跑/在人门/
        blocked 等位；at_gate=已停在段间门口）。UI 徽标按此二态文案，
        防「已暂停却还在跑」被误读为 bug。"""
        if not self._paused:
            return {"paused": False, "paused_phase": ""}
        return {"paused": True,
                "paused_phase": "at_gate" if self._paused_at_gate else "pending"}


class TicketCrossProjectMixin:
    """跨项目写操作闸的 workflow 侧第二道（t260915-12；宿主令 260915 补强的机器面）。

    消费信号载荷盖章值（caller_project：注册表 key | CALLER_UNDECLARED_MARK 哨兵 |
    ""=老 client 未盖章），按 shared.cross_project_judge 三态动作：
      refuse        → 本类拒收面（refused[] + _log 人话点名「谁要动谁的票」）+ False
                      （handler 必须立即 return，不执行该操作——Temporal 事件历史只留拒收）；
      allow_record  → meta['cross_project_uses'] 记名 + timeline + _log（undeclared 哨兵
                      或 declared 异项目带越权旗）+ True 放行；
      allow         → True 零动作（同项目 / 未盖章兼容 / 无项目身份面的引擎件）。
    宿主契约与 TicketPauseMixin 同一份成员：meta/refused/timeline/_log/_now_epoch/
    _now_iso。重放安全：盖章字段带默认值 ""，老历史解码→judge 首分支放行零动作。
    """

    def _cross_project_gate(self, stamped_caller: str, note: str, op: str,
                            who: str, want: str) -> bool:
        g = cross_project_judge(stamped_caller, str(self.meta.get("project") or ""), note)
        if g["action"] == "refuse":
            self.refused.append({"who": who, "want": want, "why": g["why"]})
            self._log(g["why"])
            return False
        if g["action"] == "allow_record":
            rec = dict(g["record"] or {})
            rec.update({"ts": self._now_epoch(), "op": op, "by": who})
            # 对账面词=reason（场景/README 契约：by/reason 原文在条目）；note 保留
            # （shared 层词，直发 SDK 载荷字段名同源）
            rec["reason"] = rec.get("note", "")
            self.meta.setdefault("cross_project_uses", []).append(rec)
            self.timeline.append({"at": self._now_iso(),
                                  "stage": str(self.meta.get("stage") or ""),
                                  "state": "cross-project-recorded",
                                  "reason": g["why"] or ("跨项目写操作记名（op=%s）" % op)})
            self._log(g["why"] or "跨项目写操作记名（op=%s）" % op)
            self._touch()
        return True


class TicketWorkflowBase(TicketPauseMixin, TicketCrossProjectMixin):
    """Shared mechanisms for the six template subclasses. A subclass only declares:
      STAGES: Tuple[Stage, ...]   — the stage chain (source of truth = code)
      PATCH_ID: str               — this template's own patched id
      TEMPLATE_ID / TEMPLATE_NAME / TEMPLATE_LANE / TEMPLATE_DESC — for snapshots and yaml generation
      TEMPLATE_WORKSPACE_DIR: bool — dir-isolated workspace convention for cleanup-type templates (retired 260904)
      REVISION_STAGE / REVISION_LIMIT / REVISION_OVERFLOW — the revision loop (content-pipeline, retired 260904)
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
        self.results: Dict[str, Dict[str, Any]] = {}      # stage_id → StageResult summary
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self._sigs: Dict[str, Signature] = {}
        self._rework: Optional[ReworkRequest] = None
        self._retry_token: int = 0
        self._gens: Dict[str, int] = {}                   # stage_id → entry count (result-file generation)
        self.gate_runs: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.human_context: Dict[str, Any] = {}
        self.engine_version: int = ENGINE_VERSION_V2

    # ---------- Internal: time/log/bookkeeping ----------
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
        """Stage-transition yield point (KI-003): await yields the event loop,
        giving queued snapshot queries (which share the same workflow event loop
        as the main coroutine) a window to run.

        Why a patched branch instead of a bare sleep(0): in temporalio 1.18.2,
        sleep(0) emits a real StartTimer command (zero duration gets no special
        case), and old running tickets replaying old history have no such command
        — sleeping directly would break determinism. So old history replays the
        original path (no marker, no yield), and new execution / the live edge
        reaches this point, records the marker, and then sleep(0) takes effect
        (a zero-length timer fires immediately).
        wait_condition(lambda: True) cannot serve as the yield shape: during
        replay, the ordering of the condition check and the future creation can
        park the coroutine until the next activation, with no wake-up guarantee.
        Note: DevLaneWorkflow does not inherit this base class (same shape, no
        inheritance); it carries its own _breathe (ticket t260901-23: adding it
        only on the base would be an AttributeError for dev-lane tickets)."""
        if not workflow.patched(BREATHE_PATCH_ID):
            return  # old-history replay: no marker, skip the yield to keep replay deterministic
        await asyncio.sleep(0)

    # ---------- Internal: stage lookup ----------
    def _stage_idx(self, stage_id: str) -> int:
        for i, s in enumerate(self.STAGES):
            if s.id == stage_id:
                return i
        return -1

    def _gen(self, stage_id: str) -> int:
        return self._gens.get(stage_id, 0)

    # ---------- Init ----------
    def _init(self, inp: TicketInput) -> None:
        self.ticket_id = inp.ticket_id
        self.template_id = inp.template_id
        # Patched discipline: record the patch marker on first use of this class;
        # bump the subclass PATCH_ID for later logic changes.
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
            # Ticket t260908-02: source-of-truth slot for the per-repo detail of
            # multi-repo / mixed shapes (top level of meta). workspace stays a
            # pure {type, path} — no embedded list (Dict[str, str] annotation is
            # Temporal codec compatible).
            "repo_worktrees": list(inp.repo_worktrees),
            # Ticket t260910-08: same-family completion — the fallback ring ③
            # (write_set+project_root derivation) in prepare_workspace stays dead
            # without the anchor; old RUNNING instances replay without the key and
            # fall back to "" (ring inactive, same as before — zero regression).
            "project_root": str(getattr(inp, "project_root", "") or ""),
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
            # M16: body = the raw user request (user_request kept verbatim, takes
            # priority; falls back to body when absent); spec = the processed
            # dispatch spec (separate field, does not overwrite the body).
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
            # Input snapshot (for the ticket detail page)
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

    # ---------- Stage execution: agent activity ----------
    async def _run_agent_stage(self, st: Stage) -> Optional[StageResult]:
        """Run an agent-stage activity. Returns None = success; raising = infrastructure retries exhausted (the caller turns it into blocked)."""
        gen = self._gen(st.id)
        # Stage-rerun context inheritance: on a same-role recall, read the
        # previous return value from the workflow history
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
        def _exec_once():
            return workflow.execute_activity(
                st.id, args,                    # activity name = stage name (stage as activity)
                start_to_close_timeout=AGENT_TO, heartbeat_timeout=HEARTBEAT_TO,
                retry_policy=RETRY)

        # t260916-29 要求④：worker 停机取消 → 自动重跑一次（patched 门内，老实例重放恒旧分支）
        raw = await retry_once_on_worker_termination(
            _exec_once,
            gate=workflow.patched(WORKER_SHUTDOWN_RETRY_PATCH_ID),
            on_retry=lambda e: self._log(
                "%s 段活动被 worker 停机取消，自动重跑一次（第 %d 次）" % (st.id, gen + 1)))
        # A by-name call has no return type annotation; the dataclass comes back
        # as a dict — normalize it into a StageResult. files_changed keeps its
        # shape normalized (ticket t260904-18 KI-049 gate ②): the shape travels
        # with the receipt into the results dict verbatim (the consumer dev_lane
        # reads the results dict, not the StageResult object itself).
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

    # ---------- Stage execution: script gate ----------
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

    # ---------- Stage execution: human gate ----------
    async def _run_human_stage(self, st: Stage, idx: int) -> str:
        """Human-gate stage: activity does the mechanical prep → wait_condition
        waits for sign/rework. Returns 'next' (signed pass) or 'rework' (reject /
        explicit rework; the main loop jumps stages uniformly)."""
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
        # reject = send-back: default target is revision_to / the previous stage
        target = st.revision_to or (self.STAGES[idx - 1].id if idx > 0 else "")
        self._rework = ReworkRequest(
            who=sig.who, target_stage=target,
            note="人在 %s 打回：%s（签字人 %s）" % (st.id, sig.note, sig.who))
        return "rework"

    # ---------- Bookkeeping: checks/handoff ----------
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
        """Compute the rework landing stage. Returns the target stage index
        (illegal target → refuse with a record, stay on the current stage)."""
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
        self.meta["last_rework_note"] = req.note     # stage-rerun context inheritance: the send-back reason feeds previous_context
        self._touch()
        self._log("rework: %s（回 %s）%s——%s" % (req.note, target, extra, req.who))
        self._mark(target, "rework", "%s（%s）" % (req.note, req.who))
        return tidx

    # ---------- M16: workspace prep (the workflow's first activity) ----------
    async def _prepare_workspace(self) -> Dict[str, Any]:
        """Run the prepare_workspace activity (worktree add / dir mkdir / main-tree
        skip; a failed receipt does not raise).

        First pass the lane-field gate (lane_workspace_gate_error): the normal
        creation path derives + validates at the ticket-start single point, and
        this catches cases that bypass it ("old payload / future new entry") —
        when lane=worktree but the lane fields are incomplete or inconsistent, go
        through the failure receipt into blocked-waiting-for-human instead of
        letting the activity silently skip to the main tree."""
        gate = lane_workspace_gate_error(self.meta)
        if gate:
            return {"ok": False, "kind": "config", "action": "rejected",
                    "path": "", "error": gate}
        # t260910-08: construction collapsed onto the single point
        # (shared.build_workspace_prep) — same reason as dev_lane.run; the base copy
        # additionally gains the write_set/project_root feeds its inline form never had
        # (fallback ring ③ was dead here too).
        prep = build_workspace_prep(self.ticket_id, self.meta)
        raw = await workflow.execute_activity(
            prepare_workspace, prep, start_to_close_timeout=SHORT, retry_policy=RETRY)
        # A by-name call has no return type annotation; the payload comes back as
        # a dict — normalize it into field reads
        res = raw if isinstance(raw, WorkspacePrepResult) else WorkspacePrepResult(
            ok=bool(raw.get("ok", True)), kind=str(raw.get("kind") or ""),
            action=str(raw.get("action") or ""), path=str(raw.get("path") or ""),
            error=str(raw.get("error") or ""))
        return {"ok": bool(res.ok), "kind": res.kind, "action": res.action,
                "path": res.path, "error": res.error}

    # ---------- Generic main loop (the subclass @workflow.run thin shell forwards here) ----------
    async def _main(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)
        # M16: the workspace is created/reused by the workflow's first activity
        # (prepare_workspace); agents no longer set it up themselves. Failure →
        # blocked waiting for a retry_qc retry / rework send-back (the target
        # stage is still computed as usual); errors are not swallowed.
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
            # 段间暂停门（t260908-01）：上一段（含在飞 activity）已自然跑完，此处即
            # 段间门口——已暂停则停住等 resume，不派下一段。
            await self._pause_gate()
            st = self.STAGES[idx]
            self._gens[st.id] = self._gen(st.id) + 1
            self.meta["stage"] = st.id
            self.meta["role"] = st.role
            # v2 status semantics: always dispatched while orchestration is in
            # progress (no per-item settle/verify manual actions); re-entering a
            # stage after rework returns to dispatched; the tail sets the final
            # state to closed.
            self.meta["status"] = "dispatched"
            self.meta["stage_state"] = "running"
            acc = list(st.acceptance)
            if not self.meta.get("acceptance") or self.meta.get("stage") == st.id:
                # The first stage keeps the instance extras from create; later stages use the template list
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

            # agent / gate stages: failure (business red or activity fault) →
            # blocked, waiting for retry_qc / rework
            while True:
                failure = ""
                if st.kind == "agent":
                    try:
                        res = await self._run_agent_stage(st)
                    except Exception as e:  # activity retries exhausted: infrastructure failure
                        failure = format_agent_stage_failure(self.ticket_id, st.id, e,
                                                             gen=self._gen(st.id))
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

        # All stages done: auto-settle (v2 has no manual driving; human gates excepted)
        last = self.STAGES[-1]
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("全部段完成，自动收口（closed）")
        self._mark(last.id, "closed", "workflow 完成")
        return self._snapshot()

    # ---------- signals: human-gate sign / rework / retry_qc ----------
    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """Human-gate signature. gate must be the currently-waiting exit=human stage id (empty = the current stage)."""
        # t260912-03：带 authorize 的人授权载荷只认 dev_lane 的 sign 面；本模板（v1
        # 人门族）无授权面——显式拒收（误投不得被当作普通人门签字按 approve 放行）。
        if getattr(sig, "authorize", None) is not None:
            self.refused.append({"who": sig.who, "want": "sign(authorize)",
                                 "why": "本模板无人授权面，authorize 载荷拒收（不落签字）"})
            return
        # t260915-12 跨项目闸（第二道）：不符无旗=refused 不落签字；哨兵/旗=记名放行。
        if not self._cross_project_gate(str(getattr(sig, "caller_project", "") or ""),
                                        str(getattr(sig, "cross_project_note", "") or ""),
                                        "sign", str(sig.who or ""), "sign"):
            return
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
        """Send-back rerun: re-enter the target stage (gen+1 → new result file, the agent really reruns)."""
        # t260915-12 跨项目闸（第二道）：同 sign 口径。
        if not self._cross_project_gate(str(getattr(req, "caller_project", "") or ""),
                                        str(getattr(req, "cross_project_note", "") or ""),
                                        "rework", str(req.who or ""), "rework"):
            return
        self._rework = req
        self._log("rework 请求：%s → %s（%s）"
                  % (req.note, req.target_stage or "缺省目标", req.who))

    @workflow.signal
    def retry_qc(self, who: str) -> None:
        """After blocked, request a rerun of the current stage (script gate rerun / agent stage rerun)."""
        self._retry_token += 1
        self.timeline.append(
            {"at": self._now_iso(), "stage": str(self.meta.get("stage") or ""),
             "state": "retry-requested",
             "reason": "%s 请求重跑（第 %d 次）" % (who, self._retry_token)})

    # ---------- update: status maintenance (external protocol same name and payload as the old class) ----------
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

    # ---------- query: read-only snapshot (all old keys kept + full meta + results) ----------
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
            **self._pause_snapshot(),
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
