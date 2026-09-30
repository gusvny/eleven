"""light-lane —— 轻道工单泳道（独立 workflow 类，短段链）。

宿主令 260930 定案（devlane-lite 直修，不开票；设计文档 docs/design/devlane-lite-v1.md §4.1）：
**轻道是独立 workflow 类，不是既有泳道里的一个模式**——既有泳道的段机是体量很大、
对重放极敏感的控制流，往里穿一条 profile 分支会拿每一张在途票的事件历史冒险。两条道
**共用真正干活的机器**（活动：工作空间准备、agent 段、worker 代落盘、机器闸、合并检查、
合并、归档、拆道），轻道只带自己那条短段链。

段链（段 id 与 DevLaneWorkflow 同名同类语义，只是短）：

    prepare_workspace（无 agent，前置）
      → implement（developer：落地 + 单测；worker 代落盘 commit）
      → run_integration_tests（机器闸：项目声明的集成命令；一轮一判）
      → merge_check（程序化四项）
      → merge（人审签字 → 真合并 → 归档 → 拆道）

**没有** create_plan、没有 plan review、没有 design_integration_tests、没有仲裁、
没有验收走查，**也不产 UI 证据**（宿主 260930 两道裁定：轻道不带 create_plan 段与
ui_evidence 段——段声明、派单面、时间线三处都不许出现这两段）。

为什么没有 create_plan（宿主 260930 裁定，口径留档供后人复核）：轻道的适用面靠**人选**
（人选时已经判过一次「这是小活」），需求的真源是**票面**（含写集声明），范围内的真源是
**声明的写集**（引擎越权闸照旧咬）。全车道留 create_plan 的价值是「写码前发现活比想象
的大」，而轻道已经放弃 review_plan 那道纪律，再留一个「自己写给自己的方案」收益不抵成本
（实测该段 3~17 分钟/票）。**代价已写明**：这个「发现」时点后移到机器闸——活比想象的大
时，闸会以**完整违规集**转人（那时人或打回实现、或另开全车道票）；将来若做机械选道，
再补一个便宜的「范围自检」即可，不必恢复整段。写集不再随方案刷新（没有方案回执可读），
声明的写集就是范围内的真源。

UI 面改动的口径（连带后果，**具名不静默**）：merge_check 的 3.6「UI 证据闸」是
**模板无关的全车道纪律**——改动面命中 UI 路径即要求 `.sandbar/screenshots/` 下有截图
（reason_code=ui_evidence_missing）。轻道不产截图，所以「改到 UI 路径的轻道票」会在
merge_check 被这条闸**具名挡住**：详见 §6 的口径注释与 _light_merge_blocked_text 的
`ui_evidence_missing` 专段（出路=另开全车道票 / 人裁定豁免），绝不静默、绝不假绿。

红转人（宿主 260930 定案②）：机器闸不绿 ⇒ 票面进 blocked，带上**完整违规集**（全部失败场景名、
计数、闸回执指针，绝不给样本）与具名出路清单（重跑闸 / 打回实现 / 为余下工作另开全道
票），等人发信号。**不调仲裁活动，不自动循环**——一个 attempt 只跑一轮机器闸，重跑由人
（retry_qc）或打回（rework）显式触发。

复用面（本票的要点，逐项都不是抄的）：
  · 工作空间准备：dev_lane._prepare_workspace_step（本票从 dev-lane run() 原块逐字抽出的
    共用 helper，dev-lane 同调用，命令序列逐字不变）；
  · agent 段派发与回执/落盘流转：dev_lane._run_agent_step（含 worker 代落盘 settle、
    结果文件归一、闸拒绝明细、环境信号、移交命令债表）——本类直接调用；
  · 机器闸：同一批活动与同一批纯函数单写者——changed_files / surface_plan /
    shared.targeted_rerun_plan / run_integration_tests / dev_lane._integ_run_args /
    dev_lane._closing_full_run（定点轮只作快反馈，放行只认收口全量跑）；
  · 合并检查 / 合并 / 归档 / 拆道：同一批活动同形入参（merge_check、prepare_human_gate、
    merge、archive_ticket、teardown_lane）；
  · 票面/元数据记账：全部继承——_init/_enter/_mark/_finish/_handoff/_blocked/
    _handover_debt_*/_record_authz_uses/_pin_merge_red_detail/snapshot/timeline/gate_runs
    以及人门信号面（sign/rework/retry_qc/host_ruling/pause/resume）与 @query（snapshot/
    sign_face）/@update（update_status）。

为什么是继承而不是复制：Temporal SDK 的 `@workflow.defn` 拒绝「基类已带 workflow 定义」
的子类（_Definition.from_class 沿 MRO 取到父类定义即 ValueError，temporalio 1.x 实测），
所以本类在类体之后显式清掉继承来的定义标记再重新装饰（见文件尾）。这样**段链与类属性
是轻道自己的，其余整面是父类那一份**——既不加复制，也不动 dev-lane 的任何控制流。

中文注释/文档串（CLAUDE.md 规则 3）；**票面文字与控制台可见文案一律英文**（规则 6 及其
260925 补充令）。退役术语不出现。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from dev_lane import (
        INTEG_RUN_TO,
        MERGE_CHECK_TO,
        MERGE_TO,
        RETRY,
        SHORT,
        FLOW_BRIEF,
        DevLaneWorkflow,
    )
    import shared  # 纯函数面（exception_chain_note 等，零 IO）
    from agent_activities import (
        archive_ticket,
        changed_files,
        merge,
        merge_check,
        prepare_human_gate,
        run_integration_tests,
        surface_plan,
        teardown_lane,
        verify_review_gate,
    )
    from shared import (
        ArchiveArgs,
        ArchiveResult,
        ChangedFilesArgs,
        GateSpec,
        HumanGatePrep,
        IntegrationRunResult,
        MergeArgs,
        MergeCheckArgs,
        MergeCheckResult,
        MergeResult,
        ReviewGateArgs,
        ReviewGateResult,
        ReworkRequest,
        Signature,
        Stage,
        SurfacePlanArgs,
        TicketInput,
        format_agent_stage_failure,
        targeted_rerun_plan,
    )


#: 轻道 workflow 的布尔门基名（新类新门：轻道实例首评恒 live→True，与 dev-lane 的
#: 门族互不影响；老 dev-lane 实例重放一个字都不碰）。
LIGHT_PATCH_ID = "light-lane-v1"

LIGHT_LANE_TEMPLATE_ID = "light-lane"

#: 段门表（**按 (template_id, stage_id) 键**，与 shared.default_gate_for 同形同键）。
#: 机器闸=项目声明的集成命令（verify_lane lane=integ）——与 dev-lane 的机器闸**同一条
#: 命令、同一个执行器**；本表是声明面，真跑在 run() 里调同一活动 run_integration_tests。
LIGHT_LANE_GATES: Dict[Any, GateSpec] = {
    (LIGHT_LANE_TEMPLATE_ID, "run_integration_tests"): GateSpec(
        stage="run_integration_tests", tool="verify_lane", args={"lane": "integ"},
        label="verify_lane integ (the project-declared integration command)"),
}

#: 轻道专用出路改写（宿主 260930 裁定）：`path_gates` 的共享出路提示里有一条
#: `write_set_missing` 指向 **create_plan**（「回 create_plan 补结构化回执后再实现」），
#: 那是**全车道的票面文字**，轻道没有那个段 → 提示指空。做法取零风险侧：**不碰共享串**
#: （dev-lane 票面逐字不变），只在**轻道自己的阻断面收敛点**做一次出路改写（见
#: `_light_neutralize_next_action`）。改写的原文留在 `next_action_rewritten_from`
#: 键里（可追溯，不静默丢）。
LIGHT_NEUTRAL_NEXT_ACTION = (
    "Put the files to change into the ticket's declared write set and land again — this "
    "lane has no planning stage, so the write set never widens after creation "
    "(path gate reason: write_set_missing).")

#: 轻道可打回段（rework 词表）：比 PHASE_MAIN_CHAIN 窄——审方案/仲裁/验收走查在轻道
#: **不存在**，打回它们只会在主循环落到「未知相位」。词表窄于闸＝拒收点名，绝不放进去。
LIGHT_REWORK_TARGETS = frozenset({
    # 宿主 260930：create_plan 段已删——它**也不再是可返工目标**（打回一个不存在的段
    # 只会把票打到未知相位；拒收面会具名点名「不是轻道段」）。
    "implement", "run_integration_tests", "merge_check", "merge"})

#: 轻道段级补述：在 dev-lane 的同段补述**前面**加一段轻道契约说明；正文 import 复用，
#: 纪律条文（英文报告义务 + developer 段集成禁跑执法）因此与 dev-lane 同源、不会漂移。
LIGHT_LANE_PRELUDE = (
    "【本票走轻道（light lane）】段链=implement → run_integration_tests（机器闸）"
    "→ merge_check → merge（人审）。"
    "本道**没有**方案段、没有方案复审、没有集测设计、没有仲裁、没有验收走查、"
    "**也不产 UI 证据**（UI 面改动请走全车道）：范围的真源=票面声明的写集，"
    "机器闸不绿就停下等人（不自动重跑、不自动仲裁），所以一轮交付要尽量把事做完。\n")

LIGHT_FLOW_BRIEF: Dict[str, str] = {
    # 轻道唯一 agent 段=implement（宿主 260930 删了 create_plan 与 ui_evidence）；正文
    # import 复用 dev-lane 同段条文，只有前缀是轻道自己的契约说明。
    "implement": LIGHT_LANE_PRELUDE + FLOW_BRIEF["implement"],
}


class LightLaneWorkflow(DevLaneWorkflow):
    """轻道泳道（宿主 260930 定案②③）：短段链 + 红转人 + 不自动循环。

    STAGES 是展示/推导元数据（yaml 快照、控制台泳道图、建票推导），真编排在 run()；
    它与模板拓扑导出面 template_topology 的 light-lane 节点表的一致性由 UT 锁死
    （dev-lane / inspection-lite 同款范式）。"""

    PATCH_ID = LIGHT_PATCH_ID
    TEMPLATE_ID = LIGHT_LANE_TEMPLATE_ID
    #: 模板面显示名（宿主 260930：英文。控制台界面文案以引擎既有英文标识为真源，
    #: 由前端 ui-labels 映射表统一映射——此处是模板面数据）。
    TEMPLATE_NAME = "Light Lane"
    # KI-124：段路径闸总开关随模板类声明（client.py ticket-start 读类属性）。
    PATH_GATE = True
    TEMPLATE_LANE = "worktree"
    TEMPLATE_WORKSPACE_DIR = False
    TEMPLATE_DESC = ("轻道（light lane）：prepare_workspace→implement→run_integration_tests"
                     "（机器闸，一轮一判）→merge_check→merge（人审）——红转人，不自动仲裁、"
                     "不自动重跑；不产 UI 证据、不写方案（UI 面改动走全车道；范围=票面声明的写集）")
    #: 段补述来源（dev-lane 的 _run_agent_step 读本属性；dev-lane 侧值=FLOW_BRIEF，
    #: 逐字不变——纯加法钩子）。
    FLOW_BRIEF_SET: Dict[str, str] = LIGHT_FLOW_BRIEF

    # 段声明（角色/种类/人门标记与 run() 同序；acceptance 是**票面文字**，按 CLAUDE.md
    # 规则 6 全英文）。**首段=implement**（宿主 260930 裁定删 create_plan：见模块头注
    # 「为什么没有 create_plan」——口径与代价都在那里，含「发现时点后移到机器闸」）。
    # **无条件段**（也不带 ui_evidence，UI 面改动由 merge_check 3.6 的 UI 证据闸具名
    # 挡住，见类尾 `_light_merge_blocked_text`）。
    STAGES = (
        Stage(id="implement", name="实现", role="developer", next="run_integration_tests",
              desc="按方案开发：写集白名单内；agent 沙箱写不了真 .git，commit 由 worker "
                   "代落盘；单测随实现交付",
              parts=("agent", "script"),
              acceptance=("Changes stay inside the write set",
                          "Changes are committed to the lane branch (the worker settles "
                          "on the agent's behalf)",
                          "Unit tests for the change run green")),
        Stage(id="run_integration_tests", name="跑集成测试", role="integration",
              next="merge_check", agent=False,
              desc="程序化（无 agent）：泳道 0-commit 前置检查 → 改动清单 → 面计划收窄快反馈面 "
                   "→ 跑项目声明的集成命令（与 dev-lane 同一条命令、同一个执行器）；不绿即 blocked "
                   "并带完整违规集（不自动重跑、不调仲裁）；定点轮放行只认收口全量跑",
              parts=("script",),
              gate=LIGHT_LANE_GATES[(LIGHT_LANE_TEMPLATE_ID, "run_integration_tests")],
              acceptance=("The project-declared integration command ran and produced a receipt",
                          "Any red is carried through in full — every failing scenario "
                          "name, the counts, and the receipt pointer")),
        Stage(id="merge_check", name="合并检查", role="integration", next="merge",
              agent=False,
              desc="程序化检查（无 agent）：泳道有 commit、工作区干净、泳道内 verify_lane 绿、"
                   "merge-tree 无冲突；任一项红 → blocked 等人（轻道不做自动冲突消解轮）",
              parts=("script",),
              acceptance=("Lane branch has commits", "Worktree is clean",
                          "The in-lane verify_lane check is green",
                          "merge dry-run has no conflict")),
        Stage(id="merge", name="合并（人审）", role="integration", next="", exit="human",
              desc="人审签字后执行 merge：合 main + 泳道清理（拆 worktree、删分支）；"
                   "归档失败 fail-closed 保留泳道",
              parts=("human", "script"),
              acceptance=("Human sign-off recorded",
                          "Merge booked and the lane is torn down after a successful archive")),
    )

    # ================================================================== 段级 helper
    async def _light_agent_step(self, step_id: str, previous_context: str = "",
                                settle: bool = True):
        """一段 agent 步的统一样板（复用父类 `_run_agent_step`：派单构造、结果文件轮询、
        worker 代落盘、回执归一、闸拒绝明细、移交债表全在父类那份实现里）。

        基础设施异常与业务失败都落 blocked 并返回 None，调用方 `continue`；文案沿用
        父类 `_agent_failed_why` 单点路由（环境型失败点名环境原因+出路）。"""
        try:
            res = await self._run_agent_step(step_id, previous_context, settle=settle)
        except Exception as e:  # noqa: BLE001——裸 while True 抛出去=打断工作流实例
            await self._blocked(step_id, format_agent_stage_failure(
                self.ticket_id, step_id, e, gen=self._gen(step_id)))
            return None
        if res is None:
            await self._blocked(
                step_id,
                "the agent stage returned no receipt at all (stage=%s) — nothing to "
                "judge. Remedies: retry_qc to re-run this stage, or rework to send it "
                "back with a note." % step_id)
            return None
        if str(getattr(res, "status", "")) != "ok":
            await self._block_agent_failed(step_id, res)
            return None
        return res

    # ------------------------------------------------- 出路改写（轻道专有，宿主 260930）
    def _light_neutralize_next_action(self) -> None:
        """把轻道票面上的「指向 create_plan 的出路提示」改写成模板中立口径。

        覆盖两处 pin 点写进 `meta['blocked_detail']` 的字段（顶层 `next_action` 与
        逐条红的 `reds[*].next_action`，外加嵌套的 `gate_refusal`）；只改**含
        create_plan** 的那些，其它出路一字不动；原文留在 `next_action_rewritten_from`
        键（可追溯）。纯内存、零判定、幂等（改过的不再含 create_plan）。

        为什么在轻道侧做：`path_gates._NEXT_ACTION_HINTS` 是**全车道共享**的票面文字——
        改它=改 dev-lane 的既有票面（宿主「既有泳道零行为变化」那条）。轻道覆写自己的
        pin 点（`self.` 动态派发，dev-lane 不受影响）＝零风险侧。"""
        detail = self.meta.get("blocked_detail")
        if not isinstance(detail, dict):
            return
        targets = [detail]
        inner = detail.get("gate_refusal")
        if isinstance(inner, dict):
            targets.append(inner)
        for red in (detail.get("reds") or []):
            if isinstance(red, dict):
                targets.append(red)
        for t in targets:
            na = t.get("next_action")
            if isinstance(na, str) and "create_plan" in na:
                t["next_action_rewritten_from"] = na
                t["next_action"] = LIGHT_NEUTRAL_NEXT_ACTION

    def _pin_agent_refusal(self, res) -> None:
        """轻道覆写（纯加法）：先跑父类那套逐字记账，再做**轻道票专属**的出路改写。"""
        super()._pin_agent_refusal(res)
        self._light_neutralize_next_action()

    def _pin_merge_red_detail(self, checks, fallback_files=None, disposition="") -> None:
        """轻道覆写（纯加法）：同上——父类记账逐字不变，随后改写指向 create_plan 的出路。"""
        super()._pin_merge_red_detail(checks, fallback_files, disposition)
        self._light_neutralize_next_action()

    def _consume_light_rework(self, phase: str):
        """rework 信号消费（返回 (落点相位, 拒收文案)；拒收时落点=""）。

        轻道纪律：信号先消费（拒收也消费，不残留）再判定；目标必须落在
        LIGHT_REWORK_TARGETS（轻道存在的段）——打回轻道没有的段（review_plan /
        design_integration_tests / arbitrate / acceptance_walkthrough …）＝显式拒收 +
        blocked 点名，**绝不静默回落原地**（「信号回执成功 + 原地空转」的观感根因）。
        落点合法性另过父类 `_auto_rework` 的词表校验（拒绝时它自己落 refused 记录）。"""
        req = self._rework
        self._rework = None
        target = str(getattr(req, "target_stage", "") or "") or phase
        if target not in LIGHT_REWORK_TARGETS:
            why = ("target %r is not a light-lane stage (admissible: %s) — this lane has "
                   "no plan review, no arbitration and no acceptance walkthrough"
                   % (target, ", ".join(sorted(LIGHT_REWORK_TARGETS))))
            self.refused.append({"who": str(getattr(req, "who", "") or ""),
                                 "want": "rework(%s)" % target, "why": why})
            self._log("rework refused: %s" % why)
            return "", ("rework refused: %s" % why)
        landing = self._auto_rework(target, str(getattr(req, "note", "") or ""),
                                    str(getattr(req, "who", "") or ""), phase)
        if landing != target:
            return "", ("rework refused: target %s did not pass the landing check "
                        "(see this ticket's refused records)" % target)
        return landing, ""

    # ---------------------------------------------------------------- 闸判词（纯函数面）
    def _light_red_names(self, ir: Any) -> List[str]:
        """本轮**完整**违规集：产品红名（父类单写者 `_tests_red_names`：details 逐条
        exit≠0 ∪ 闸拦名单，剔除合成条目与具名环境红）∪ 闸拦名单 ∪ 具名环境红名。"""
        names = list(self._tests_red_names(ir))
        for b in list(getattr(ir, "blockers", None) or []):
            b = str(b)
            if b and not b.startswith("__") and b not in names:
                names.append(b)
        env_names, _ok = self._tests_env_red_names(ir)
        for n in env_names:
            if n not in names:
                names.append(n)
        return names

    def _light_gate_has_product_red(self, ir: Any) -> bool:
        """本轮是否存在产品红（红名单非空或 failed>0）——用于 blocked 的 reason_code
        分区（闸故障 / 环境红未具名 / 产品红）。畸形计数按**有红**保守处理。"""
        try:
            failed = int(getattr(ir, "failed", 0) or 0)
        except (TypeError, ValueError):
            return True
        return bool(failed) or bool(self._tests_red_names(ir))

    def _light_gate_verdict(self, ir: Any) -> str:
        """机器闸二态判定（轻道自己的判词，不引仲裁）：green / red。

        保守方向（与「判不了的绝不静默放行」一致）：
          · 回执缺席或 error 非空（闸没产出可用结论）→ red；
          · 产品红（红名单非空或 failed>0）→ red；
          · env_fail>0 而具名环境红通道缺席/为空（老回执形态）→ red（**无具名即无豁免**）；
          · 其余 → green（余红若全是具名环境红：不拦，但票面逐条点名）。"""
        if ir is None:
            return "red"
        if str(getattr(ir, "error", "") or ""):
            return "red"
        if self._light_gate_has_product_red(ir):
            return "red"
        try:
            env_fail = int(getattr(ir, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            return "red"
        if env_fail > 0:
            env_names, channel_ok = self._tests_env_red_names(ir)
            if not (channel_ok and env_names):
                return "red"
        return "green"

    def _light_run_face(self, ir: Any, run_only: Any) -> Dict[str, Any]:
        """本轮**跑面**（诚实面：跑了什么、没跑什么、有没有复用）——直接取闸回执的现成
        注记，不重判：
          · narrowed：ir.only_names（非空=定点快反馈面，空=全量）；
          · excluded_pools/excluded_count：声明池跳过面；
          · reuse：闸回执的复用块（老回执缺键=如实记 absent，不冒充）；
          · known_red：在册红豁免面（回执无此块=如实记 absent）。"""
        reuse = getattr(ir, "reuse", None)
        known_red = getattr(ir, "known_red", None)

        def _face(v):
            """在场（非空 dict）→ 原样；缺席/空/畸形 → 如实点名（不冒充）。"""
            if isinstance(v, dict):
                return dict(v) if v else "absent: the receipt carried no such block"
            return "absent: the receipt carried no such block" if v is None else str(v)

        return {
            "requested_only_names": [str(x) for x in (run_only or [])],
            "narrowed": [str(x) for x in (getattr(ir, "only_names", None) or [])],
            "excluded_pools": [str(x) for x in (getattr(ir, "excluded_pools", None) or [])],
            "excluded_count": int(getattr(ir, "excluded_count", 0) or 0),
            "reuse": _face(reuse),
            "known_red": _face(known_red),
        }

    def _light_gate_blocked_text(self, ir: Any, run_only: Any, phase_note: str) -> str:
        """轻道机器闸 blocked 文案（票面英文；**完整违规集**，绝不给样本）。"""
        names = self._light_red_names(ir)
        env_names, _ok = self._tests_env_red_names(ir)
        face = self._light_run_face(ir, run_only)
        parts = [
            "Machine gate is not green (light lane: one machine round per attempt — no "
            "arbitration, no automatic re-run; a human decides).",
            "Phase: %s." % (phase_note or "gate round"),
            "Counts: %s ran / %s passed / %s failed / %s env-red%s"
            % (getattr(ir, "ran", 0), getattr(ir, "passed", 0), getattr(ir, "failed", 0),
               getattr(ir, "env_fail", 0),
               (" | gate error: %s" % str(ir.error)[:400])
               if str(getattr(ir, "error", "") or "") else ""),
            "Complete violation set (%d): %s"
            % (len(names), ", ".join(names) if names else "(none named)"),
        ]
        if env_names:
            parts.append("Named environment reds (not blocking, but named): %s."
                         % ", ".join(env_names))
        parts.append("Round face: %s."
                     % ("narrowed to %s" % ", ".join(face["narrowed"])
                        if face["narrowed"] else "full registry (not narrowed)"))
        if face["excluded_pools"]:
            parts.append("Declared pools skipped this round: %s (%d entries)."
                         % (", ".join(face["excluded_pools"]), face["excluded_count"]))
        if isinstance(face["reuse"], dict):
            parts.append("Ledger reuse this round: reused=%s of expected=%s (reused "
                         "entries were NOT executed; named: %s)."
                         % (face["reuse"].get("reused"), face["reuse"].get("expected"),
                            ", ".join(face["reuse"].get("names") or []) or "none named"))
        elif face["reuse"]:
            parts.append("Ledger reuse face: %s." % face["reuse"])
        if isinstance(face["known_red"], dict):
            parts.append("Known-red entries excluded from this round: %s."
                         % (", ".join(face["known_red"].get("names") or [])
                            or ("%s entries" % face["known_red"].get("skipped")
                                if face["known_red"].get("skipped") else "none named")))
        elif face["known_red"]:
            parts.append("Known-red exclusion face: %s." % face["known_red"])
        parts.append("Gate receipt: results.run_integration_tests in this ticket's "
                     "snapshot (its evidence holds the raw details), plus the lane's "
                     "out/integration-report-*.json.")
        parts.append("Remedies: (1) re-run the gate on the same tree — send retry_qc; "
                     "(2) send the implementation back — send rework(to_stage=implement) "
                     "with a note, and the gate re-runs after it lands; (3) if the "
                     "remaining work is bigger than this lane carries, open a full-lane "
                     "ticket (template dev-lane) for it — a running workflow cannot "
                     "change lane.")
        return " ".join(parts)

    def _light_gate_blocked_detail(self, ir: Any, run_only: Any, reason_code: str,
                                   phase_note: str) -> Dict[str, Any]:
        """机器闸 blocked 的结构化明细（键族与父类 blocked_detail 同形；additive 键承载
        完整违规集与跑面，供票面/控制台机读）。"""
        names = self._light_red_names(ir)
        env_names, channel_ok = self._tests_env_red_names(ir)
        return {
            "check_id": "run_integration_tests",
            "item": "machine gate (the project-declared integration command)",
            "red": True,
            "reason_code": reason_code,
            "files": [],
            "next_action": ("retry_qc re-runs the gate on the same tree; "
                            "rework(to_stage=implement) sends it back for repair; "
                            "open a dev-lane ticket for work beyond this lane"),
            "evidence": str(getattr(ir, "error", "") or phase_note)[:400],
            "violations": names,
            "violations_complete": True,
            "blockers": [str(b) for b in (getattr(ir, "blockers", None) or [])],
            "env_red": env_names,
            "env_red_channel_ok": bool(channel_ok),
            "counts": {"ran": int(getattr(ir, "ran", 0) or 0),
                       "passed": int(getattr(ir, "passed", 0) or 0),
                       "failed": int(getattr(ir, "failed", 0) or 0),
                       "env_fail": int(getattr(ir, "env_fail", 0) or 0)},
            "round": self._light_run_face(ir, run_only),
            "receipt": "results.run_integration_tests",
            "remedies": ["retry_qc: re-run the gate on the same tree",
                         "rework(to_stage=implement, note=...): repair, then the gate re-runs",
                         "open a full-lane ticket (template dev-lane) for the remaining work"],
        }

    def _light_face_note(self, ir: Any, run_only: Any) -> str:
        """票面注记（票面英文）：本轮跑面**少跑的都必须可见**（定点面/跳过池/台账复用）。
        空串=全量且无少跑面。只读回执，不改判定。"""
        face = self._light_run_face(ir, run_only)
        bits = []
        if face["narrowed"]:
            bits.append("narrowed to %d entries (%s)"
                        % (len(face["narrowed"]), ", ".join(face["narrowed"])))
        if face["excluded_pools"]:
            bits.append("declared pools skipped: %s (%d entries)"
                        % (", ".join(face["excluded_pools"]), face["excluded_count"]))
        if isinstance(face["reuse"], dict) and int(face["reuse"].get("reused") or 0) > 0:
            bits.append("ledger reuse: reused=%s of expected=%s (not executed)"
                        % (face["reuse"].get("reused"), face["reuse"].get("expected")))
        if isinstance(face["known_red"], dict) and int(face["known_red"].get("skipped") or 0):
            bits.append("known-red entries excluded: %d"
                        % int(face["known_red"].get("skipped") or 0))
        return (" | " + "; ".join(bits)) if bits else ""

    # ---------------------------------------------------------------- 活动包装（薄）
    async def _light_gate_round(self, run_only: List[str]) -> IntegrationRunResult:
        """跑一轮机器闸（与 dev-lane 同一活动、同一入参单写者 `_integ_run_args`）。"""
        rraw = await workflow.execute_activity(
            run_integration_tests, self._integ_run_args(run_only),
            start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
        if isinstance(rraw, IntegrationRunResult):
            return rraw
        return IntegrationRunResult(
            ran=int(rraw.get("ran") or 0), passed=int(rraw.get("passed") or 0),
            failed=int(rraw.get("failed") or 0), env_fail=int(rraw.get("env_fail") or 0),
            details=[dict(d) for d in (rraw.get("details") or [])],
            error=str(rraw.get("error") or ""),
            blockers=[str(x) for x in (rraw.get("blockers") or [])],
            excluded_pools=[str(x) for x in (rraw.get("excluded_pools") or [])],
            excluded_count=int(rraw.get("excluded_count") or 0),
            only_names=[str(x) for x in (rraw.get("only_names") or [])],
            env_red=[str(x) for x in (rraw.get("env_red") or [])])

    async def _light_gate_plan(self, prev_red_names: List[str]) -> List[str]:
        """本轮快反馈面（决策单写者仍是 shared.targeted_rerun_plan + 面计划活动，与
        dev-lane 同源同 fail-closed 口径）：改动清单不可得/为空 → 恒全量跑。"""
        cf_files: List[str] = []
        cf_err = ""
        try:
            cf = await workflow.execute_activity(
                changed_files,
                ChangedFilesArgs(ticket_id=self.ticket_id,
                                 worktree=str(self.meta.get("worktree") or ""),
                                 branch=str(self.meta.get("branch") or "")),
                start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
            cf_files = list(getattr(cf, "files", None) or [])
            cf_err = str(getattr(cf, "error", "") or "")
        except Exception as e:  # noqa: BLE001——清单不可得=保守全量，绝不悄悄收窄
            cf_err = "%s: %s" % (type(e).__name__, e)
        self.meta["file_blast_radius_trace"] = {"changed_files": cf_files, "error": cf_err}
        if cf_err:
            self._log("changed-files list unavailable (%s) — running the full registry "
                      "(fail-closed, never a silent narrowing)" % cf_err[:200])
        run_only = targeted_rerun_plan(
            list(self.meta.get("write_set") or []), list(prev_red_names or []),
            first_run=(self._gen("run_integration_tests") == 0),
            changed_files=cf_files, diff_error=cf_err)
        if run_only:
            self._log("targeted re-run face: %s (fast feedback only — the landing "
                      "verdict still requires a closing full run)" % ", ".join(run_only))
            return run_only
        if not cf_files or cf_err:
            return []
        try:
            sp = await workflow.execute_activity(
                surface_plan,
                SurfacePlanArgs(ticket_id=self.ticket_id,
                                worktree=str(self.meta.get("worktree") or ""),
                                changed_files=list(cf_files),
                                prev_red_names=list(prev_red_names or [])),
                start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
        except Exception as e:  # noqa: BLE001——面计划不可得=全量跑（同 dev-lane）
            self.meta["surface_plan_trace"] = {
                "mode": "", "reason": "", "count": 0, "surfaces": [],
                "error": "%s: %s" % (type(e).__name__, e)}
            self._log("surface plan unavailable (%s) — full registry"
                      % self.meta["surface_plan_trace"]["error"][:200])
            return []
        names = list(getattr(sp, "names", None) or [])
        mode = str(getattr(sp, "mode", "") or "")
        self.meta["surface_plan_trace"] = {
            "mode": mode, "reason": str(getattr(sp, "reason", "") or ""),
            "count": len(names), "surfaces": list(getattr(sp, "surfaces", None) or []),
            "error": str(getattr(sp, "error", "") or "")}
        if mode == "targeted" and names:
            self._log("surface plan: %d changed files -> fast-feedback face of %d "
                      "entries (the landing verdict still requires the closing full run)"
                      % (len(cf_files), len(names)))
            return names
        self._log("surface plan: full registry (mode=%s reason=%s)"
                  % (mode or "-", self.meta["surface_plan_trace"]["reason"] or "-"))
        return []

    async def _light_merge_check(self) -> MergeCheckResult:
        """merge_check 活动（与 dev-lane 同一活动、同一入参族）。"""
        raw = await workflow.execute_activity(
            merge_check,
            MergeCheckArgs(ticket_id=self.ticket_id,
                           worktree=str(self.meta.get("worktree") or ""),
                           branch=str(self.meta.get("branch") or ""),
                           base_ref=str(self.meta.get("base_ref") or ""),
                           write_set=list(self.meta.get("write_set") or []),
                           path_gate=bool(self.meta.get("path_gate")),
                           path_gate_rules=dict(self.meta.get("path_gate_rules") or {}),
                           authorizations=self._protected_authz_records(),
                           no_file_changes=bool(self.meta.get("no_file_changes"))),
            start_to_close_timeout=MERGE_CHECK_TO, retry_policy=RETRY)
        mc = raw if isinstance(raw, MergeCheckResult) else MergeCheckResult(
            green=bool(raw.get("green")), checks=list(raw.get("checks") or []),
            error=str(raw.get("error") or ""),
            conflict=bool(raw.get("conflict")),
            conflict_files=[str(x) for x in (raw.get("conflict_files") or [])],
            merge_tree_excerpt=str(raw.get("merge_tree_excerpt") or ""))
        self._record_authz_uses(
            "; ".join(str(c.get("detail") or "") for c in mc.checks), "merge_check")
        self.gate_runs.append({
            "stage": "merge_check", "label": "merge_check (programmatic checks)",
            "green": mc.green,
            "red_count": len([c for c in mc.checks if not c.get("green")]),
            "exit_code": 0, "checks": mc.checks,
            "conflict": mc.conflict, "conflict_files": mc.conflict_files})
        return mc

    def _light_gate_receipt(self, ir: Any, gen: int, closing: bool = False) -> Dict[str, Any]:
        """机器闸回执上台面（results.run_integration_tests 形状与 dev-lane 同族）。"""
        head = "closing full run" if closing else "integration gate"
        return {
            "status": "failed" if (ir.error or ir.failed) else "ok",
            "summary": ("%s: %s ran / %s passed / %s failed / %s env-red%s"
                        % (head, ir.ran, ir.passed, ir.failed, ir.env_fail,
                           (" | " + str(ir.error)) if ir.error else "")),
            "report": "", "deliverables": [], "files_changed": [],
            "evidence": json.dumps(ir.details, ensure_ascii=False)[-4000:],
            "gen": gen,
        }

    # ================================================================== 主流程
    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)

        # 1) 工作空间准备（dev-lane 同 helper：同活动/同失败转 blocked/同 rework 语义）
        await self._prepare_workspace_step()

        # 首段=implement（宿主 260930 删 create_plan）——相位默认值必须跟着首段走，
        # 否则「票面初始态」会指向一个不存在的段。
        phase = str(self.meta.get("stage") or self.STAGES[0].id)
        prev_ctx = ""
        run_only: List[str] = []          # 最近一轮跑面（空=全量）
        prev_red_names: List[str] = []    # 最近一轮红名（下一轮快反馈面来源）
        gate_rounds = 0                   # 本 attempt 内机器闸轮次（每跑一趟 +1）

        while phase != "done":
            # 段间暂停门（t260908-01 通用骨架，本类只接线）：当前段（含在飞活动）
            # 自然跑完，主循环走到下一个段间门口时门把它停住。
            await self._pause_gate()
            # 事件账本：主相循环每轮先冲账（机制在 base.TicketEventLedgerMixin）
            await self._ledger_flush()
            if self._rework is not None:
                landing, refusal = self._consume_light_rework(phase)
                if refusal:
                    await self._blocked(self._safe_phase(phase, self.STAGES[0].id),
                                        refusal)
                    continue
                phase = landing
                prev_ctx = str(self.meta.get("last_rework_note") or "")
                await self._breathe()
                continue

            # 2) implement（首段；developer 落地 + 单测；worker 代落盘）
            #    轻道**没有方案段**（宿主 260930 裁定，见模块头注）——所以这里也**不调**
            #    dev_lane._refresh_write_set_after_plan（它读的是 create_plan 回执的
            #    files_changed；没有方案回执可读时调用只会刷出一条「跳过」日志）。
            #    范围内的真源=建票时声明的写集（越权闸照旧咬）。
            if phase == "implement":
                res = await self._light_agent_step("implement", prev_ctx)
                if res is None:
                    continue
                prev_ctx = ""
                self._finish("implement", by="developer-agent",
                             evidence=res.evidence or res.summary)
                self._handoff("implement", res.summary or "Implementation landed",
                              artifacts=res.deliverables, report=res.report)
                # 宿主 260930 裁定：轻道**不产 UI 证据**（无 ui_evidence 段，也不调
                # dev_lane._ui_evidence_step）——UI 面改动由 merge_check 3.6 的证据闸
                # 具名挡住（reason_code=ui_evidence_missing），出路见类尾那段口径。
                await self._breathe()
                phase = "run_integration_tests"
                continue

            # 3) 机器闸（项目声明的集成命令；一轮一判，红转人）
            if phase == "run_integration_tests":
                gen0 = self._gen("run_integration_tests")
                self._enter("run_integration_tests")
                gate_rounds += 1
                # 4.1 0-commit 前置检查（同活动同判据；no_file_changes 票豁免）
                if not self.meta.get("no_file_changes"):
                    try:
                        graw = await workflow.execute_activity(
                            verify_review_gate,
                            ReviewGateArgs(ticket_id=self.ticket_id,
                                           worktree=str(self.meta.get("worktree") or ""),
                                           write_set=list(self.meta.get("write_set") or []),
                                           no_file_changes=True),
                            start_to_close_timeout=SHORT, retry_policy=RETRY)
                        g = graw if isinstance(graw, ReviewGateResult) else ReviewGateResult(
                            git_error=str(graw.get("git_error") or ""),
                            lane_commits=int(graw.get("lane_commits") or -1),
                            shots_path_error=str(graw.get("shots_path_error") or ""),
                            png_count=int(graw.get("png_count") or -1))
                        if g.lane_commits == 0:
                            await self._blocked(
                                "run_integration_tests",
                                "No implementation landed (the lane branch has 0 commits) "
                                "— the implement stage produced nothing that was settled "
                                "into the lane, so there is nothing to verify. Remedies: "
                                "rework(to_stage=implement) to re-run the stage, or "
                                "retry_qc once the change is in the lane.")
                            continue
                    except Exception as e:  # noqa: BLE001——不拦主链（同 dev-lane 口径）
                        self._log("0-commit pre-check failed (not blocking the main "
                                  "chain): %s: %s" % (type(e).__name__, e))
                # 4.2 快反馈面（改动清单 ∪ 面计划；不可得=全量）
                run_only = await self._light_gate_plan(prev_red_names)
                # 4.3 跑闸（一轮）
                ir = await self._light_gate_round(run_only)
                if not ir.error:
                    self._handover_debt_clear()
                prev_red_names = self._tests_red_names(ir)
                _face_note = self._light_face_note(ir, run_only)
                self.results["run_integration_tests"] = self._light_gate_receipt(ir, gen0)
                self._finish("run_integration_tests", by="run_integration_tests",
                             evidence="; ".join(
                                 "%s:%s" % (d.get("name"),
                                            "pass" if d.get("exit") == 0 else "fail")
                                 for d in ir.details))
                self._handoff("run_integration_tests",
                              "gate round %d: ran=%s passed=%s failed=%s env_fail=%s%s%s"
                              % (gate_rounds, ir.ran, ir.passed, ir.failed, ir.env_fail,
                                 _face_note, (" | " + str(ir.error)) if ir.error else ""))
                verdict = self._light_gate_verdict(ir)
                # 4.4 定点轮只作快反馈：放行只认收口全量跑（与 dev-lane 同一 helper）
                if verdict == "green" and run_only:
                    self._log("the fast-feedback round was narrowed — running the closing "
                              "full run (the landing verdict only accepts a full run)")
                    try:
                        ir2 = await self._closing_full_run()
                    except Exception as e:  # noqa: BLE001——判不定 → 转人
                        await self._blocked(
                            "run_integration_tests",
                            "The closing full run produced no receipt (%s: %s), so the "
                            "landing verdict cannot be established. Remedy: retry_qc to "
                            "re-run the gate." % (type(e).__name__, str(e)[:300]))
                        continue
                    if not ir2.error:
                        self._handover_debt_clear()
                    self.results["run_integration_tests"] = self._light_gate_receipt(
                        ir2, gen0, closing=True)
                    self._handoff("run_integration_tests",
                                  "closing full run: ran=%s passed=%s failed=%s "
                                  "env_fail=%s%s"
                                  % (ir2.ran, ir2.passed, ir2.failed, ir2.env_fail,
                                     self._light_face_note(ir2, [])))
                    verdict = self._light_gate_verdict(ir2)
                    if verdict == "green":
                        self._log("closing full run green — the landing verdict stands")
                    else:
                        self._log("the closing full run found reds the narrowed round "
                                  "could not see — the pass is void, blocking for a human")
                        ir = ir2
                        run_only = []
                if verdict != "green":
                    if str(getattr(ir, "error", "") or ""):
                        reason_code = "light_gate_error"
                    elif not self._light_gate_has_product_red(ir):
                        reason_code = "light_gate_env_unnamed"
                    else:
                        reason_code = "light_gate_red"
                    note = ("gate round %d of this attempt" % gate_rounds
                            + (" (narrowed face: %s)" % ", ".join(run_only)
                               if run_only else " (full registry)")
                            + (self._light_gate_note_tail(ir)))
                    if getattr(self, "_detail_face_on", False):
                        self.meta["blocked_detail"] = self._light_gate_blocked_detail(
                            ir, run_only, reason_code, note)
                        self._touch()
                    await self._blocked("run_integration_tests",
                                        self._light_gate_blocked_text(ir, run_only, note))
                    continue
                env_names, _ok = self._tests_env_red_names(ir)
                if env_names:
                    # 具名环境红不拦（供给面），但绝不静默：逐条进票面日志
                    self._log("named environment reds this round (not blocking): %s"
                              % ", ".join(env_names))
                phase = "merge_check"
                continue

            # 4) merge_check（程序化四项；任一项红 → 转人）
            if phase == "merge_check":
                self._enter("merge_check")
                mc = await self._light_merge_check()
                if mc.green:
                    self._finish("merge_check", by="merge_check",
                                 evidence="; ".join(c.get("item", "") for c in mc.checks))
                    self._handoff("merge_check", "Merge check: all four items green")
                    phase = "merge"
                    continue
                reds = [c for c in mc.checks if not c.get("green")]

                def _handling(c):
                    """逐条红的处置提示——指向 create_plan 的共享提示在轻道票面上改写
                    （宿主 260930：轻道没有方案段，提示不许指空）。"""
                    na = str(c.get("next_action") or "")
                    if "create_plan" in na:
                        return LIGHT_NEUTRAL_NEXT_ACTION
                    return na

                red = "; ".join(
                    "%s: %s%s" % (c.get("item"), c.get("detail"),
                                  (" | handling: %s" % _handling(c)) if _handling(c) else "")
                    for c in reds)
                self._pin_merge_red_detail(
                    mc.checks, mc.conflict_files,
                    disposition="light lane: every merge_check red blocks for a human "
                                "(this lane has no automatic conflict-resolution round); "
                                "rework(to_stage=implement) or retry_qc re-runs the check")
                await self._blocked("merge_check",
                                    self._light_merge_blocked_text(mc, red))
                continue

            # 5) merge（人审签字 → 真合并 → 归档 → 拆道）
            if phase == "merge":
                self._enter("merge")
                prep_ctx = await workflow.execute_activity(
                    prepare_human_gate,
                    HumanGatePrep(ticket_id=self.ticket_id, stage_id="merge",
                                  workspace=self.meta.get("workspace"),
                                  worktree=str(self.meta.get("worktree") or ""),
                                  base_ref=str(self.meta.get("base_ref") or ""),
                                  title=str(self.meta.get("title") or "")),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                ctx_text = getattr(prep_ctx, "context_text", "") or str(prep_ctx)
                self.human_context["merge"] = {"context_text": ctx_text}
                self.meta["stage_state"] = "awaiting-human"
                self._touch()
                self._log("merge gate parked: waiting for the human sign signal "
                          "(merge_check is green)")
                self._mark("merge", "awaiting-human",
                           "Waiting for the human sign-off: sign(gate=merge)")
                await self._ledger_flush()
                await workflow.wait_condition(
                    lambda: ("merge" in self._sigs) or (self._rework is not None))
                if self._rework is not None:
                    continue  # 统一在循环顶消费
                sig: Signature = self._sigs.pop("merge")
                self.signatures["merge"] = {"who": sig.who, "decision": sig.decision,
                                            "note": sig.note, "at": self._now_iso()}
                if sig.decision != "approve":
                    self._rework = ReworkRequest(
                        who=sig.who, target_stage="implement",
                        note=("human rejected at the merge gate: %s (signer %s)"
                              % (sig.note, sig.who)))
                    continue
                self.meta["stage_state"] = "running"
                self._mark("merge", "running", "human signed off (%s) — merging" % sig.who)
                # merge 只落账（defer_teardown）→ 归档（fail-closed）→ 拆道：与 dev-lane
                # 同一批活动、同形入参；归档成功是拆道的前置（段报告不能随泳道一起丢）。
                raw = await workflow.execute_activity(
                    merge,
                    MergeArgs(ticket_id=self.ticket_id,
                              worktree=str(self.meta.get("worktree") or ""),
                              branch=str(self.meta.get("branch") or ""),
                              base_ref=str(self.meta.get("base_ref") or ""),
                              defer_teardown=True,
                              write_set=list(self.meta.get("write_set") or [])),
                    start_to_close_timeout=MERGE_TO, retry_policy=RETRY)
                mr = raw if isinstance(raw, MergeResult) else MergeResult(
                    ok=bool(raw.get("ok")), action=str(raw.get("action") or ""),
                    merge_commit=str(raw.get("merge_commit") or ""),
                    error=str(raw.get("error") or ""),
                    reason=str(raw.get("reason") or ""),
                    files=[str(x) for x in (raw.get("files") or [])])
                if not mr.ok:
                    # 轻道口径：合并未收口（脏主树/冲突/故障）一律转人，点名
                    # action/reason/files 与出路——**不自动打回**（那会悄悄吃掉人的签字）。
                    self.meta["blocked_detail"] = {
                        "check_id": "merge",
                        "item": "merge execution",
                        "red": True,
                        "reason_code": mr.reason or ("merge_%s" % (mr.action or "fault")),
                        "files": list(mr.files)[:20],
                        "next_action": ("resolve the condition named above (commit/stash "
                                        "the listed files on main, or repair the lane), "
                                        "then send retry_qc to re-run the merge"),
                        "evidence": str(mr.error or "")[:400],
                    }
                    self._touch()
                    await self._blocked(
                        "merge",
                        "Merge did not close out (%s/%s): %s | files: %s | Remedies: fix "
                        "the named condition on main or in the lane, then send retry_qc "
                        "(the human sign-off already recorded is not silently consumed — "
                        "the merge re-runs under it)."
                        % (mr.action, mr.reason or "merge_fault",
                           (mr.error or "unknown")[:400],
                           ", ".join(list(mr.files)[:10]) or "(none named)"))
                    continue
                try:
                    ares = await workflow.execute_activity(
                        archive_ticket,
                        ArchiveArgs(ticket_id=self.ticket_id,
                                    project_key=str(self.meta.get("project") or ""),
                                    worktree=str(self.meta.get("worktree") or ""),
                                    meta=dict(self.meta)),
                        start_to_close_timeout=SHORT, retry_policy=RETRY)
                except Exception as e:  # noqa: BLE001——fail-closed：归档失败保泳道
                    await self._blocked(
                        "merge",
                        "Ticket data archive failed (fail-closed: the lane is kept, not "
                        "torn down): %s: %s%s"
                        % (type(e).__name__, str(e)[:400],
                           shared.exception_chain_note(e)))
                    continue
                if not isinstance(ares, ArchiveResult) or not ares.ok:
                    await self._blocked(
                        "merge",
                        "Ticket data archive receipt is not ok (fail-closed: the lane is "
                        "kept, not torn down): %s"
                        % ((getattr(ares, "error", "") or repr(ares))[:400]))
                    continue
                self._log("ticket data archived: %s"
                          % (getattr(ares, "archive_path", "") or "(path unknown)"))
                try:
                    tr = await workflow.execute_activity(
                        teardown_lane,
                        MergeArgs(ticket_id=self.ticket_id,
                                  worktree=str(self.meta.get("worktree") or ""),
                                  branch=str(self.meta.get("branch") or ""),
                                  repo_worktrees=list(self.meta.get("repo_worktrees")
                                                      or [])),
                        start_to_close_timeout=SHORT, retry_policy=RETRY)
                except Exception as e:  # noqa: BLE001
                    await self._blocked(
                        "merge",
                        "Lane teardown failed (data already archived; lane leftovers "
                        "need a human): %s: %s%s"
                        % (type(e).__name__, str(e)[:400],
                           shared.exception_chain_note(e)))
                    continue
                if not isinstance(tr, MergeResult) or not tr.ok:
                    await self._blocked(
                        "merge",
                        "Lane teardown receipt is not ok (data already archived; lane "
                        "leftovers need a human): %s"
                        % ((getattr(tr, "error", "") or repr(tr))[:400]))
                    continue
                if tr.error:
                    self._log("lane teardown warning (reclaimable leftovers, data "
                              "already archived): %s" % tr.error)
                self._finish("merge", by=sig.who,
                             evidence="merge booked %s (human %s: %s)"
                                      % (mr.merge_commit, sig.who, sig.note))
                self._handoff("merge", "Merged %s" % mr.merge_commit)
                phase = "done"
                continue

            # 未知相位：绝不 raise（父类同款纪律——裸 while True 抛出去=打断工作流实例，
            # 票面变不可查）。停为人审并点名合法段名。
            await self._blocked(
                self._safe_phase(self.STAGES[0].id, "merge"),
                "internal phase resolved to an unknown value %r (light-lane stages: %s) — "
                "parked for a human instead of failing the workflow task; use "
                "rework(to_stage=<stage>) to reset, or retry_qc to re-drive."
                % (phase, ", ".join(s.id for s in self.STAGES)))
            phase = self._safe_phase(self.STAGES[0].id, "merge")
            continue

        # 收口（与父类同形：closed + timeline closed 条目 + 末次冲账）
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("merge booked, ticket closed")
        self._mark("merge", "closed", "workflow finished")
        await self._ledger_flush()
        return self._snapshot()

    # ---------------------------------------------------------------- merge_check 阻断面
    #: UI 证据闸的 reason_code（真源=agent_activities merge_check 3.6 两处产出，同一常量
    #: 值；本类只**读**回执、不重判）。
    UI_EVIDENCE_RED = "ui_evidence_missing"

    def _light_merge_blocked_text(self, mc: Any, red: str) -> str:
        """merge_check 阻断文案（票面英文；逐条红 + 处置 + 出路）。

        **UI 证据闸专段**（宿主 260930：轻道不产 UI 证据的连带后果必须具名且可行动）：
        3.6 那条闸是**模板无关的全车道纪律**——改动面命中 UI 路径即要求
        `.sandbar/screenshots/` 下有截图（reason_code=ui_evidence_missing）。轻道没有
        ui_evidence 段、也不调截图 helper，所以「改到 UI 路径的轻道票」必然被它挡住。
        这里把它单独摊开：说明这是全车道纪律、轻道不产截图，出路=**另开全车道票**
        （template dev-lane）或**人裁定豁免**——绝不静默、绝不假绿，也绝不把
        「补截图」这条对轻道结构性不可满足的动作当成出路。"""
        ui_reds = [c for c in (getattr(mc, "checks", None) or [])
                   if not c.get("green") and str(c.get("reason_code") or "") == self.UI_EVIDENCE_RED]
        parts = [
            "Merge check is red (light lane: every red goes to a human — no automatic "
            "send-back). %s%s" % (red or "no per-item detail in the receipt",
                                  " | error: %s" % mc.error if mc.error else ""),
            "Remedies: fix the item named above and send retry_qc to re-run the check, "
            "or rework(to_stage=implement) with a note to repair the lane.",
        ]
        if ui_reds:
            files = []
            for c in ui_reds:
                for f in (c.get("files") or []):
                    if str(f) not in files:
                        files.append(str(f))
            parts.append(
                "UI-surface change detected (the UI evidence gate, "
                "reason_code=%s): this gate is a full-lane discipline applied to every "
                "lane and it is template-independent — a change whose diff hits UI paths "
                "must ship screenshots under .sandbar/screenshots/. The light lane does "
                "not produce UI evidence (no ui_evidence stage, no capture step), so this "
                "ticket cannot satisfy it here. Files hit: %s. Remedies: open a full-lane "
                "ticket (template dev-lane) for this change, or have a human rule an "
                "exemption — do not expect retry_qc to clear this item on the light lane."
                % (self.UI_EVIDENCE_RED, ", ".join(files[:20]) or "(not named in the receipt)"))
        return " ".join(parts)

    # ---------------------------------------------------------------- 判词小工具
    def _light_gate_note_tail(self, ir: Any) -> str:
        """blocked 文案里的分类尾注（产品红/具名环境红/闸错误三类点名）。"""
        names = self._tests_red_names(ir)
        env_names, _ok = self._tests_env_red_names(ir)
        bits = []
        if names:
            bits.append("%d product red(s): %s" % (len(names), ", ".join(names)))
        if env_names:
            bits.append("%d named env red(s): %s" % (len(env_names), ", ".join(env_names)))
        if str(getattr(ir, "error", "") or ""):
            bits.append("gate error: %s" % str(ir.error)[:200])
        return ("; " + "; ".join(bits)) if bits else ""


# ---------------------------------------------------------------------------
# workflow 注册（Temporal SDK 门）
# ---------------------------------------------------------------------------
# 实测（temporalio 1.x）：`@workflow.defn` 对「基类已带 workflow 定义」的子类直接
# ValueError（_Definition.from_class 沿 MRO 取到父类那枚定义）。本类**有意**复用
# dev-lane 的整面定义（信号 sign/rework/retry_qc/host_ruling 与继承自 mixin 的
# pause/resume、查询 snapshot/sign_face、更新 update_status，以及全部私有 helper），
# 所以显式清掉继承来的标记再重新装饰：父类那枚定义一字不动（DevLaneWorkflow 的行为与
# 注册面零变化），本类拿到自己的 run/类属性与自己的 workflow 类型名（=类名）。SDK 的
# MRO 一致性检查在此形态下通过（run 同名、信号/查询/更新同名同签名；UT 钉死该行为，
# 防将来 SDK 收紧时静默退化）。
LightLaneWorkflow.__temporal_workflow_definition = None
LightLaneWorkflow = workflow.defn(LightLaneWorkflow)
