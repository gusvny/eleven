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
    # t260928-13：事件账本写活动（账面 IO 的活动承载面；详见 event_ledger.py）
    from event_ledger import append_event_ledger
    from shared import (
        ENGINE_V2,
        ENGINE_VERSION_V2,
        TICKET_STATUSES,
        WS_DIR_BASE,
        ws_dir_default,
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
    gate_failure_note,
        normalize_files_changed,
        normalize_handover_runs,
        env_note_for,
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
# 260927（宿主令直修；实案 t260926-05/t260927-03/t260927-04 一小时内三票同形 blocked）：
#   3 分钟静默阈值会**误杀仍在干活的 agent**——实锤：验收 agent 02:09 spawn、02:41 被判死后
#   会话文件最后写入时刻恰是 02:41（一直有产出），AGENT_TO=6h 远未到 ⇒ 死因=心跳断供≥3min。
#   切到更慢的路由（zai-coding-cn/glm-5.3）后单次调用更长，长模型/长工具步内 3 分钟无心跳是常态。
#   故放宽到 15 分钟（宁可晚发现真卡死，不可续杀在干活的 agent）；后续应改成「进展驱动心跳」
#   （会话文件/mtime 增长即续），见 KI-138 修法方向。
HEARTBEAT_TO = timedelta(minutes=15)
RETRY = RetryPolicy(maximum_attempts=3)  # only for infrastructure failures; business failures go through StageResult.status
# KI-003: versioned marker for the stage-transition yield point (consumed by
# workflow.patched inside _breathe; old running instances replaying old history
# have no marker → no yield, keeping replay deterministic).
BREATHE_PATCH_ID = "ki003-breathe-v1"

# t260922-09（review C5）：update_status 拒绝回执形状变更的重放安全 patch——update
# handler 的返回载荷会作为完成载荷记入历史且重放时重执行比对（temporalio 1.18.2
# _apply_do_update），形状变更必须 workflow.patched 两分支承载：旧历史（patch 前）
# 逐字复刻旧两键回执且零留痕，新历史走四键+留痕。命名同 ticket-pause-v1 家族
# （全仓既有 patch id grep 无撞名）。deprecate_patch 收尾属后续另票。
TICKET_UPDATE_RECEIPT_PATCH_ID = "ticket-update-receipt-v1"
# t260922-09：update 拒绝留痕的不受信回显上限（intake 上限家族同款取舍——超长回显
# 截断进留痕，原文不落盘；比较/判定一律用原值，截断只影响展示面；update_status 的
# 旧历史重放分支不经 _update_echo——旧文案逐字复刻，保证重放逐字节兼容）。
UPDATE_ECHO_LIMIT = 200


def _update_echo(v) -> str:
    """update 拒绝留痕的不受信回显截断单点（t260922-09）。

    host_ruling 的截断标记是「全文见 host_rulings」（全文有第二真源 meta）；
    本处故意不存原文（原文=不受信畸形载荷，存了就违背有界初衷），标记如实写
    「原文不落盘」。非字符串（int/list/dict——handler 直调面没有 client.py:807
    的 str() 强转）先 str() 再截断。"""
    s = str(v)
    if len(s) <= UPDATE_ECHO_LIMIT:
        return s
    return s[:UPDATE_ECHO_LIMIT] + "…（截断，原文不落盘）"


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

    # ---------- t260927：人工记名收口信号（close_out 前置留痕，先留痕后终结） ----------
    @workflow.signal
    def close_out_notice(self, req: dict) -> None:
        """人工记名收口预告（`ticket.py op=close_out` 的引擎侧入口；260927 宿主实报④）。

        为什么需要它：票被误判 blocked、工作其实已完成时，A3.5 护栏（blocked 态只允许
        `dispatched/settled/rework`）把「置 closed 收口」正路也堵死了——完成态只能靠
        dispatched→settled 变通，且工作流仍挂在 blocked（看板永不归零）。本信号=**记名
        收口**：把 who/reason 落票面与事件历史，把 status 置 closed，随后由 client 侧
        terminate（与 cancel 同款「先留痕、后终结」次序纪律，事件历史里本信号恒先于
        terminated）。

        A3.5 关系（必须读明白再改）：本 handler **不走** `update` op 的 A3.5 判据——那条
        判据防的是「用通用 update 把 blocked 悄悄写成非 blocked」；本信号是**专门的、强制
        记名（who+reason 必填非空）**的收口语义，记录里带 `was_state/was_stage`，把被覆盖
        的状态如实留痕（掩盖不成立=留下证据）。畸形载荷=refused[] 零副作用、不动 status。

        放在共享 mixin（TicketCrossProjectMixin）里而非某个模板基类：dev_lane 与模板族
        两个工作流都要这条能力（dev_lane 原本连 cancel_notice 都没有，票面留痕缺口同源）。
        handler 只写两棵类树都有的面（meta/refused/_now_iso/_log/_mark），不新增 Temporal
        command，老历史重放不会触达（事件驱动 handler，sign/rework 先例）。
        """
        if not isinstance(req, dict):
            req = {}
        who = str(req.get("who") or "").strip()
        reason = str(req.get("reason") or "").strip()
        if not who:
            self.refused.append({"who": who, "want": "close_out_notice",
                                 "why": "who 必填非空（空/纯空白拒收，零副作用）"})
            return
        if not reason:
            self.refused.append({"who": who, "want": "close_out_notice",
                                 "why": "reason 必填非空（收口理由是记名对账锚，空=拒收零副作用）"})
            return
        if not self._cross_project_gate(str(req.get("caller_project") or ""),
                                        str(req.get("cross_project_note") or ""),
                                        "close_out", who, "close_out"):
            return
        at = self._now_iso()
        meta = self.meta
        was_state = str(meta.get("stage_state") or "")
        was_stage = str(meta.get("stage") or "")
        meta["close_out"] = {"who": who, "reason": reason, "at": at,
                             "was_state": was_state, "was_stage": was_stage}
        meta["status"] = "closed"
        meta["stage_state"] = "awaiting"
        meta["blocked_reason"] = ""
        meta["blocked_detail"] = None
        self._log("人工记名收口（close_out）：%s——原状态 stage=%s state=%s（who=%s，at=%s）"
                  % (reason, was_stage or "（无）", was_state or "（无）", who, at))
        self._mark(was_stage or "close_out", "closed",
                   "人工记名收口（工作已完成）：%s" % reason)
        self._touch()

    # ---------- t260922-10：记名清场信号（cancel 前置留痕，先留痕后终结） ----------
    @workflow.signal
    def cancel_notice(self, req: dict) -> None:
        """记名清场预告：client.py ticket-cancel（ticket.py op=cancel 的引擎侧入口）
        在 terminate 之前投递，把 who+reason 落进票面可见面——本 handler 受理后 log+
        timeline 各一条（who/reason 原文）；跨项目/未声明身份经 _cross_project_gate
        落 meta['cross_project_uses']（by/reason 原文，note≤300 既有截断口径）。

        对账口径（宿主令 260922「终结后在 admin.log 与 workflow 事件历史能查到同一
        reason 字符串」）：本信号事件由 server 落事件历史（与 worker 是否执行本 handler
        无关，KI-081：老 worker 静默丢新信号只丢票面窗口尽力面，不破坏对账面）；
        事件历史里 cancel_notice（载荷含 who+reason 原文）恒先于 terminated 事件
        （terminate 的 reason=同一串）——次序纪律「留痕必须先写、后终结」的机械面。
        终态后票面快照不可得，权威对账=事件历史×admin.log 同串；票面 log/timeline/
        cross_project_uses 是终结前窗口尽力面。巡检票（inspection workflow 类）无本
        信号 handler：仅事件历史+admin.log 留痕（其票面无 cross_project_uses 消费面）。

        载荷=纯 dict {who, reason, caller_project, cross_project_note}：不新增 shared.py
        dataclass（该文件不在本票写集；retry_qc 裸串先例证明非 dataclass 信号合法）。
        无 patched marker：事件驱动 handler 只在事件存在于历史时执行（sign/rework
        先例），老历史重放不会触达；不调 workflow.* 运行时 API → 可离线桩测（同款）。
        畸形/越权=refused[] 落账零副作用（pause intake gate 同款纪律）。"""
        if not isinstance(req, dict):
            req = {}
        who = str(req.get("who") or "").strip()
        reason = str(req.get("reason") or "").strip()
        if not who:
            self.refused.append({"who": who, "want": "cancel_notice",
                                 "why": "who 必填非空（空/纯空白拒收，零副作用）"})
            return
        if not reason:
            self.refused.append({"who": who, "want": "cancel_notice",
                                 "why": "reason 必填非空（清场理由是记名对账锚，空=拒收零副作用）"})
            return
        # 跨项目闸第二道（与 pause/sign 同口径）：refuse→已落 refused/log 点名，False
        # 即 return；allow_record→cross_project_uses+timeline+log 已落（by/reason 原文）。
        if not self._cross_project_gate(str(req.get("caller_project") or ""),
                                        str(req.get("cross_project_note") or ""),
                                        "cancel", who, "cancel"):
            return
        self._log("cancel 清场记名（%s）：%s——终结前留痕；终态后权威对账=事件历史"
                  "（本条 cancel_notice 事件）×admin.log 同串" % (who, reason))
        self.timeline.append({"at": self._now_iso(),
                              "stage": str(self.meta.get("stage") or ""),
                              "state": "cancel-noticed",
                              "reason": "%s 请求清场：%s" % (who, reason)})
        self._touch()


# t260928-13：事件账本发射的重放安全 patch——老 RUNNING 实例重放无 marker ⇒ enqueue
# 恒 no-op、无活动命令进入旧历史（与 PAUSE/BREATHE patch 同一家族纪律）。
EVENT_LEDGER_PATCH_ID = "event-ledger-v1"
# 账面写活动的超时/重试口径：写一行 <4KB 的事，5s 足够；不重试（maximum_attempts=1）
# ——writer 本身 fail-open（event_ledger.append_event 永不 raise），重试风暴只会和
# 幂等去重打架而无所获，失败面由 gap 记录/计数器承载。
LEDGER_EMIT_TO = timedelta(seconds=5)
LEDGER_EMIT_RETRY = RetryPolicy(maximum_attempts=1)


class TicketEventLedgerMixin:
    """事件账本发射 mixin（t260928-13，epic project-executor 第一片）——
    TicketPauseMixin / TicketCrossProjectMixin 的同族兄弟：把本工作流的每次段状态
    迁移（_mark 的 timeline 条目）以「恰好一事件」的口径投给每项目 append-only
    JSONL 账本（server/engine/event_ledger.py，写面在活动里）。

    接线（与 pause mixin 同款分工：机制全在本类，子类只接线）：
      ①继承本 mixin；②在自己的 _mark 里 timeline.append 之后调
      `self._ledger_enqueue(entry)`（唯一入队点，调用面不可能漏带载荷）；
      ③在异步上下文的迁移点/长等待前/主循环顶/收口 return 前调
      `await self._ledger_flush()`。

    语义与取舍（对齐已过审方案 .sandbar/plan_event_ledger.md）：
    - 载荷构建是纯计算（重放安全）：idem = project|ticket|run_id|seq——run_id 在
      首次 enqueue 时取一次 `workflow.info().run_id` 并钉在 self 上（[R3]：同票新
      run 的 seq 重启不会撞旧 run 的键；review 非阻塞项：run_id 只在 enqueue 时取，
      活动侧不再推导）；seq=本 run 内 enqueue 计数（重放稳定）。
    - flush 是批量排空：把 pending 逐条经活动投出（start_to_close=5s、不重试）。
      同步 signal handler（sign/rework）里的迁移只入队，由下一个异步边界冲走
      （seq 保证全序，延迟有界）；**终态取消/失败路径**（terminate/超时强杀）下
      pending 可能不冲即亡——取消面的权威留痕=cancel_notice 事件历史 ×admin.log
      （t260922-10 同口径），账面缺行可由 op=ledger_rebuild 从 timeline 补齐
      （ Derived & rebuildable）。
    - 账面写失败 fail-open 且 LOUD：活动内点名 stderr+计数器+gap 记录
      （event_ledger._announce 家族），本类对活动的意外异常再兜一层日志——
      任何一层都绝不把失败抛回 workflow 主流程。
    - 未声明/停用（project.yaml 无 event_ledger: 或 enabled=false）⇒ 活动侧
      直接零行为返回；workflow 侧不读文件保持确定性，代价只是停用项目每迁移
      多一次空跑活动（验收⑧：零行为变化指账面/票面，不含这一次活动命令）。
    """

    # 类属性缺省（可变状态走懒初始化，不碰子类 __init__——_paused 同款纪律）
    _ledger_pending: Optional[List[Dict[str, Any]]] = None
    _ledger_marks: Optional[List[Dict[str, Any]]] = None
    _ledger_seq: int = 0
    _ledger_run_id: str = ""
    # t260928-20：发射面声明旋钮。`_ledger_scope="project"`（缺省=t260928-13 原语义，
    # DevLaneWorkflow 零变化）；引擎级发射器（spawner / watcher / dispatcher scan，
    # 无票面归属的「执行器自己的手」）声明 `_ledger_scope="engine"`——行落引擎所属
    # 项目（engine-owner，活动侧按既有 dirs-覆盖-引擎仓根规则解析
    # event_ledger._engine_project_key）的账本，workflow 侧绝不猜项目键。
    _ledger_scope: str = "project"

    def _ledger_project(self) -> str:
        """项目键解析钩子（t260928-20）。缺省=meta['project']（t260928-13 原语义，
        DevLaneWorkflow 不感知）；有票身份但身份不在 meta 的族覆写本钩子（巡检两链
        =_input.project_key）。返回空串=「本行无项目身份」→ 交 _ledger_enqueue 按
        声明 scope 分流（project 族=跳过+点名，绝不冒充 engine 行；见该函数注）。"""
        return str((getattr(self, "meta", None) or {}).get("project") or "")

    def _ledger_note(self, stage: str, state: str, reason: str = "") -> None:
        """无 timeline 类的入队便桥（t260928-20）：spawner/dispatcher scan 没有
        _enter/timeline，用合成条目走同一入队点——seq/patched 门/idem 机制全同族，
        不另起第二套发射路径。_ledger_marks 的 i 对无 timeline 类无消费面（其快照
        不带 timeline），记 -1 明示「无条目可回指」。"""
        self._ledger_enqueue({"stage": str(stage or ""), "state": str(state or ""),
                              "reason": str(reason or ""), "at":
                              workflow.now().isoformat(timespec="seconds")})

    def _ledger_enqueue(self, entry: Dict[str, Any]) -> None:
        """唯一入队点（_mark 调用）：从 timeline 条目构建账面载荷（纯计算），
        并把迁移标记（{i,seq,run}）记入 _ledger_marks——timeline 条目本身零改动
        （票面形状逐字不变），rebuild 面由 snapshot 的 timeline+ledger_marks
        重导出账面行（派生投影的钩子）。patched 门内：老实例重放零变化。"""
        try:
            gated = workflow.patched(EVENT_LEDGER_PATCH_ID)
        except Exception:
            # 出口①：非 workflow 事件循环（temporalio 真壳在场但不在工作流协程里，
            # 单测直调 _mark 等）——零行为返回，与「老实例重放零变化」同语义。
            # 与出口②严格分开：这里只吃 patched 的环境错，绝不掩护下面的载荷构造
            # （后者对未初始化实例走逐字段 getattr 防御，见 [R-merge] 注）。
            return
        if not gated:
            # 出口②：老 RUNNING 实例重放（patched 判 False）——零行为。
            return
        # [R-merge]（merge_check 打回，t260928-13 gen2）：载荷构造对「实例未初始化」
        # 全防御——全量测试语境下其它用例会把 workflow 壳换成 patched 恒 True 的桩，
        # 裸 object.__new__ 实例（没跑 _init、无 meta/template_id）也会走到这里；
        # 事件账本是旁路观测面，绝不允许因自身缺字段把主流程炸出（getattr 逐字段
        # 兜底；pending/seq/run_id 三件由 class-attribute 缺省保底）。
        if self._ledger_pending is None:
            self._ledger_pending = []
        if not self._ledger_run_id:
            try:
                self._ledger_run_id = str(workflow.info().run_id)
            except Exception:               # noqa: BLE001——info 不可得（极端重放面）
                self._ledger_run_id = "unknown"
        self._ledger_seq += 1
        # [R-merge]（acceptance round2）：迁移标记**不写回 timeline 条目**——票面
        # timeline 形状保持逐字不变（t260915-01 detail-face「四键逐字」锁 + 未声明
        # 零变化承诺）；标记落独立的 _ledger_marks（snapshot 增量键 ledger_marks），
        # rebuild 面由 timeline+marks 重导出账面行（派生投影钩子移居于此）。
        if self._ledger_marks is None:
            self._ledger_marks = []
        self._ledger_marks.append({"i": len(getattr(self, "timeline", ()) or ()) - 1,
                                   "seq": self._ledger_seq,
                                   "run": self._ledger_run_id})
        meta = getattr(self, "meta", None) or {}
        template = str(meta.get("workflow_id")
                       or getattr(self, "template_id", "") or "")
        # t260928-20 scope/project 分流（review C2 防冒充守卫）：
        #   - 声明 scope="engine"（引擎级发射器）⇒ 恒 engine 行：project 留空哨兵，
        #     由活动侧解析 engine-owner（event_ledger._engine_project_key）。
        #   - 声明 scope="project" 但项目键解析为空 ⇒ **绝不**冒充 engine 行（那会把
        #     项目票的迁移错挂到引擎账本）：跳过本行 + LOUD 点名（fail-open 同纪律，
        #     主流程零打断；账面缺行可由 rebuild 从 timeline 补，身份修复后重放补齐）。
        #   - ticket 面：无 ticket_id 属性的类（巡检两链/引擎级发射器）回落 workflow
        #     id——它是该行的唯一稳定身份（rebuild 派生投影用它对账，缺了闭环即断）。
        scope = "engine" if self._ledger_scope == "engine" else "project"
        ticket = str(getattr(self, "ticket_id", "") or "")
        if not ticket:
            try:
                ticket = str(workflow.info().workflow_id)
            except Exception:               # noqa: BLE001——info 不可得（极端重放面）
                ticket = "unknown"
        if scope == "engine":
            project = ""
        else:
            project = self._ledger_project()
            if not project:
                self._ledger_seq -= 1       # 本行未发射，seq 不留空洞
                self._ledger_marks.pop()
                try:
                    workflow.logger.warning(
                        "[event-ledger] 项目键为空（project-scope 行跳过，绝不"
                        "冒充 engine 行）：%s %s/%s", ticket,
                        entry.get("stage"), entry.get("state"))
                except Exception:           # noqa: BLE001——日志面也防弹
                    pass
                return
        self._ledger_pending.append({
            "v": "event-ledger-v1",
            "project": project,
            "scope": scope,
            "ticket": ticket,
            "workflow": type(self).__name__,
            "template": template,
            "stage": str(entry.get("stage") or ""),
            "state": str(entry.get("state") or ""),
            "reason": str(entry.get("reason") or ""),
            "gen": int(entry.get("gen") or 0),
            "ts": str(entry.get("at") or ""),
            "seq": self._ledger_seq,
            "run_id": self._ledger_run_id,
            "idem": "%s|%s|%s|%d" % (project, ticket,
                                     self._ledger_run_id, self._ledger_seq),
            "engine": ENGINE_VERSION_V2,
        })

    async def _ledger_flush(self) -> None:
        """排空 pending：逐条经活动投给账面（不重试；见 LEDGER_EMIT_RETRY 注）。
        pending 空=零开销返回（无活动命令，主循环热路径不加负担）。"""
        if not self._ledger_pending:
            return
        batch = self._ledger_pending
        self._ledger_pending = []
        for ev in batch:
            try:
                await workflow.execute_activity(
                    append_event_ledger, ev,
                    start_to_close_timeout=LEDGER_EMIT_TO,
                    retry_policy=LEDGER_EMIT_RETRY)
            except Exception as e:          # noqa: BLE001——fail-open 兜底（活动本身
                # 已不抛；此处防活动级基础设施异常（超时/不可用）打断主流程）。
                # 兜底日志自身也防弹（[R-merge]：测试泄漏壳可能连 logger 都没有
                # ——观测面的失败绝不二次炸出打断主流程）。
                try:
                    workflow.logger.error(
                        "[event-ledger] 投递失败（fail-open，账面缺口已由活动侧 "
                        "stderr/gaps/计数器留痕）：%s %s/%s: %s",
                        ev.get("ticket"), ev.get("stage"), ev.get("state"), e)
                except Exception:           # noqa: BLE001
                    pass


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
            # 260927 ⑤a(i)：与创建链同一真源——缺省落项目内 <项目根>/.ticket-ws/<票号>
            ws = {"type": "dir", "path": ws_dir_default(inp.project_root, inp.ticket_id)}
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
            # KI-124（t260925-23）：段路径闸对基类通用模板链生效——总开关随派单输入
            # 钉死（getattr 缺省 False=老在途票不追溯）；本票模板段规则表同源钉死
            # （client.py ticket-start 自模板类 PATH_GATE_RULES 声明读取，空表=回落
            # 内建 STAGE_PATH_RULES）。不声明 PATH_GATE 的模板两键皆缺省，零行为变化。
            "path_gate": bool(getattr(inp, "path_gate", False)),
            "path_gate_rules": dict(getattr(inp, "path_gate_rules", None) or {}),
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
            previous_context=previous_context,
            # KI-124：闸四件随段活动下传（write_set/base_ref/path_gate/path_gate_rules
            # ——与 dev-lane 同款；meta 缺键=缺省 False/空表=关闸，老实例 replay 不破）
            write_set=list(self.meta.get("write_set") or []),
            base_ref=str(self.meta.get("base_ref") or ""),
            path_gate=bool(self.meta.get("path_gate")),
            path_gate_rules=dict(self.meta.get("path_gate_rules") or {}))
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
            # t260917-08：环境信号位随回执归一（第三解析点，normalize_files_changed
            # docstring 自证的解析点纪律；缺省=老回执零改动）。generic 模板只透传
            # 上台面，不做债表簿记/文案路由——那是 dev-lane 的消费面。
            _legs, _hshape, _hdrop = normalize_handover_runs(raw.get("handover_runs"))
            res = StageResult(
                status=str(raw.get("status") or "ok"),
                summary=str(raw.get("summary") or ""),
                report=str(raw.get("report") or ""),
                deliverables=[str(x) for x in (raw.get("deliverables") or [])],
                files_changed=_fc,
                files_changed_shape=_fc_shape,
                evidence=str(raw.get("evidence") or ""),
                env_fail=bool(raw.get("env_fail") or False),
                env_reason=str(raw.get("env_reason") or ""),
                handover_runs=_legs,
                handover_dropped=_hdrop)
        self.results[st.id] = {
            "status": res.status, "summary": res.summary, "report": res.report,
            "deliverables": list(res.deliverables),
            "files_changed": list(res.files_changed),
            "files_changed_shape": res.files_changed_shape,
            "evidence": res.evidence, "gen": gen,
            # t260917-08：环境信号上台面（snapshot 可见；env_note 单源注记）
            "env_fail": bool(res.env_fail), "env_reason": str(res.env_reason or ""),
            "env_note": env_note_for(res),
            "handover_runs": [dict(l) for l in (res.handover_runs or [])],
            "handover_dropped": list(res.handover_dropped or [])}
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
                        # t260927（宿主实报「门绿了也判 blocked」）：文案必须点名到底哪个检查
                        # 没过——老文案恒写「红灯 N 项」，于是「回执不可解析」与「真红 5 项」
                        # 写出同一句「红灯 0 项」，读日志的人无从分辨（处置完全不同）。
                        failure = gate_failure_note(
                            gres.label,
                            {"parsed": gres.parsed, "receipt_ok": gres.receipt_ok,
                             "receipt_green": gres.receipt_green, "red_count": gres.red_count},
                            gres.exit_code, gres.raw_head)
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
                            book_path: Optional[str], who: str = "") -> Dict[str, Any]:
        """工单状态维护（t260922-09 两段式）：前置校验区 → 写入区。

        前置校验区：全部拒绝判定在任何 meta 写入之前完成——拒绝=业务字段零副作用
        （status/stage_state/updated/pending/book_path/cross_project_uses 不动，请求
        note 原文不进 log）。被拒留痕（新历史）=refused 结构化条目（at/who/want/
        kind/why）+ _log 拒绝行（原因+who+时间），与 _cross_project_gate 拒收家族
        双落同构；不受信回显（status/who）过 _update_echo 有界，原文不落盘。
        回执一致性：ok:true ⟺ 副作用已落（含 _touch()/updated 刷新）；ok:false ⟺
        零副作用。

        重放安全（t260922-09 review C5）：update handler 返回载荷入历史且重放比对，
        回执形状变更由 workflow.patched(TICKET_UPDATE_RECEIPT_PATCH_ID) 两分支承载
        ——旧历史（patch 前）逐字复刻旧两键回执且零留痕；新历史四键+留痕。accept
        回执键集不变，无重放面。

        who：操作人记名（可选；带默认值=老四位置参数 wire 兼容、老历史重放安全）。
        今天 wire 侧尚无透传，缺省落 refused 记 '(未记名)'（t260922-09 §7-1 接线债，
        接线票须激活 UT 的 N5 真名分支）。
        """
        receipt_v2 = workflow.patched(TICKET_UPDATE_RECEIPT_PATCH_ID)
        if status and status not in TICKET_STATUSES:
            if not receipt_v2:
                # 旧历史重放分支：旧两键回执逐字复刻（旧文案含不截断回显），零留痕。
                return {"ok": False, "error": "非法 status: %r" % status}
            why = "非法 status: %s" % _update_echo(repr(status))
            w = _update_echo(who)
            at = self._now_iso()
            self.refused.append({"at": at, "who": w or "(未记名)", "want": "update",
                                 "kind": "illegal_status", "why": why})
            self._log("update 被拒（非法 status）：%s（who=%s，at=%s）——未落任何改动"
                      % (why, w or "(未记名)", at))
            return {"ok": False, "kind": "illegal_status", "reason": why, "error": why}
        new_status = status or str(self.meta.get("status") or "")
        if self.meta.get("stage_state") == "blocked" \
                and new_status not in ("dispatched", "settled", "rework"):
            if not receipt_v2:
                # 旧历史重放分支：旧两键回执逐字复刻（旧码写入后的 meta['status']
                # 恒等于此处 new_status，前置判定全输入域等价），零留痕。
                return {"ok": False, "error": "blocked 只允许 status∈{dispatched,settled,rework}（A3.5），当前 %s"
                        % new_status}
            why = ("blocked 只允许 status∈{dispatched,settled,rework}（A3.5），当前 %s"
                   % _update_echo(new_status))
            w = _update_echo(who)
            at = self._now_iso()
            self.refused.append({"at": at, "who": w or "(未记名)", "want": "update",
                                 "kind": "blocked_status_guard", "why": why})
            self._log("update 被拒（A3.5）：%s（who=%s，at=%s）——未落任何改动"
                      % (why, w or "(未记名)", at))
            return {"ok": False, "kind": "blocked_status_guard", "reason": why, "error": why}
        # ——校验全过，才进写入区（与旧代码逐行同序同语义；回执键集不动=零重放面）——
        if status:
            self.meta["status"] = status
            if status == "settled" and self.meta.get("stage_state") == "running":
                self.meta["stage_state"] = "awaiting"
        if self.meta.get("status") == "closed" and self.meta.get("stage_state") == "awaiting-human":
            self.meta["stage_state"] = "awaiting"
            note = (note + "；" if note else "") + "closed 清 awaiting-human（A3.3）"
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
