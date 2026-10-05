"""light-lane —— 轻道工单泳道（独立 workflow 类，短段链）。

宿主令 260930 定案（devlane-lite 直修，不开票；设计文档 docs/design/devlane-lite-v1.md §4.1）：
**轻道是独立 workflow 类，不是既有泳道里的一个模式**——既有泳道的段机是体量很大、
对重放极敏感的控制流，往里穿一条 profile 分支会拿每一张在途票的事件历史冒险。两条道
**共用真正干活的机器**（活动：工作空间准备、agent 段、worker 代落盘、机器闸、合并检查、
合并、归档、拆道），轻道只带自己那条短段链。

段链（段 id 与 DevLaneWorkflow 同名同类语义，只是短）：

    prepare_workspace（无 agent，前置）
      → implement（developer：落地 + 单测；worker 代落盘 commit）
      → [ui_evidence]（**脚本条件段**：仅 UI 票；worker 代跑隔离台截图，无 agent 无 LLM）
      → run_integration_tests（机器闸：项目声明的集成命令；一轮一判）
      → merge_check（程序化四项）
      → merge（人审签字 → 真合并 → 归档 → 拆道）

**没有** create_plan、没有 plan review、没有 design_integration_tests、没有仲裁、
没有验收走查（宿主 260930 裁定：轻道不写方案）。

UI 证据段的口径（宿主 260930 第二轮裁定「把 UI 证据步加回轻道」）：截图步是**脚本段**
（worker 代跑隔离台，约 1 分钟/票），轻道真正省的大头是 agent 段——上一轮把「便宜但必需」
的那步跟重活一起砍了，现加回。判据与截图**全部复用** dev_lane._ui_evidence_step（同一
diff 源判据、同一 prepare_ui_evidence、同一软失败口径），**非 UI 票零活动零痕迹**。

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
（reason_code=ui_evidence_missing），这条判据一个字不改。轻道**能产证据**（上面那个条件
段）：所以这条红在轻道上的含义是「**本道能产证据，但这次没产生/没挂上**」——出路照旧
具名且可行动（重跑截图步＝rework(to_stage=implement) 让条件段再跑一次，或截图已在泳道
后 retry_qc 重验闸），见类尾 `_light_merge_blocked_text` 的 `ui_evidence_missing` 专段。

红转人（宿主 260930 定案②）：机器闸不绿 ⇒ 票面进 blocked，**票面是给人看的摘要**
（一行结论 + 需要人做的决定 + 计数 + 本票的账最多 5 个可行动名字 + 出路 ≤3）；**全量机器
清单**（收窄面全表、完整违规集、逐名归因表、台账复用面、在册红面）进 `blocked_detail` /
闸回执 / 报告文件（宿主 260930 实报旧文案：一坨机器清单，人找不到「我该做什么」）。
**不调仲裁活动，不自动循环**——一个 attempt 只跑一轮机器闸，重跑由人（retry_qc）或打回
（rework）显式触发。

**段链之外的一步：闸相位入口的主同步**（宿主 260930 直修令，根因级）。段表里没有它，但
它是闸相位的第一件事（0-commit 前置检查之后、跑闸之前）——把 `main` 并进泳道一次。为什么
必须有：闸在**泳道自己的 worktree** 里跑项目声明的集成命令，而泳道=开票那一刻 `main` 的
快照 ⇒ 开票之后落进 `main` 的修复**不会出现在泳道里**，闸于是把「`main` 的旧账」判成
lane-only（本票的账），让 developer 去修根本不在它身上的东西（真票 t260930-09 实测：4 条
pool-exclude 假红的根因就是如此）。同步一次 ⇒ **被验证树 = 被合并树**，归因才落回真正的
责任人。机制=dev-lane 的 `_main_sync_before_gate`（本票从 dev-lane run() 原块抽出的共用
helper，命令序列/入参/等待点逐字不变，已追平=is-ancestor 快路径幂等，冲突走既有消解回路，
不可达响亮转人）——**轻道侧零第二份实现**；门=`LIGHT_MAIN_SYNC_PATCH_ID`（在飞老实例重放
旧轮走旧路径，追平历史后的新一轮才真同步）。**判据零改动**：只改被验证的树。

复用面（本票的要点，逐项都不是抄的）：
  · 工作空间准备：dev_lane._prepare_workspace_step（本票从 dev-lane run() 原块逐字抽出的
    共用 helper，dev-lane 同调用，命令序列逐字不变）；
  · 闸前主同步：dev_lane._main_sync_before_gate（同上抽法；轻道传英文文案档
    `LIGHT_MAIN_SYNC_TEXTS`，机制与命令序列走那一份）；
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
        REPROBE_TO,
        SHORT,
        FLOW_BRIEF,
        DevLaneWorkflow,
        MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID,
    )
    import shared  # 纯函数面（exception_chain_note 等，零 IO）
    # t261004-32: rule-point constants of the concurrency slot gate (the gate
    # helpers themselves live in the parent DevLaneWorkflow).
    from concurrency import CAUSE_HUMAN_GATE, CAUSE_TERMINATED  # noqa: F401
    import failure_protocol  # 纯函数面（归属前复验 KI-182，t261002-02）
    from agent_activities import (
        archive_ticket,
        changed_files,
        merge,
        merge_check,
        prepare_human_gate,
        reprobe_red_scenarios,
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
        ReprobeRedArgs,
        ReprobeRedResult,
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

#: 闸前主同步门（宿主 260930 直修令，根因级）。为什么用**新门**而不是无条件执行：
#: 在飞的老实例（如真票 t260930-09：历史里已有若干闸轮，但没有本标记）重放旧轮时
#: `workflow.patched()`=False ⇒ 旧命令序列逐字不变（绝不撞 NonDeterminismError）；而
#: 重放追平历史之后的**新一轮**执行 patched()=True ⇒ 记标记并真的同步一次（正是本修法
#: 要救的那一轮）。机制本体=dev-lane 的 `_main_sync_before_gate`（唯一实现，不另造）。
LIGHT_MAIN_SYNC_PATCH_ID = "light-lane-main-sync-v1"

#: Patch guard LIGHT_CONCURRENCY_GATE_PATCH_ID (t261005-14; same root cause
#: and same fix as dev-lane). CL-1 (775bdb1) wired the concurrency gate into
#: this lane's run entry / stage loop without a patched() guard - replaying an
#: in-flight pre-CL-1 history schedules concurrency_acquire (absent from
#: history) and dies with TMPRL1100. This lane-scoped id covers the two gate
#: call sites; the release/renew emitting helpers physically live in
#: dev_lane.py and are covered by that file's CONCURRENCY_GATE_PATCH_ID early
#: returns (pre-CL-1 history has no marker, so the family is skipped verbatim
#: = exact replay; new runs record the marker and stay gated). Full semantics:
#: see the CONCURRENCY_GATE_PATCH_ID comment block in dev_lane.py.
LIGHT_CONCURRENCY_GATE_PATCH_ID = "light-lane-concurrency-gate-v1"

#: 空收窄面回落门（宿主 260930 实报：真票 t260930-14 第 4 轮「点名面全被在册豁免 ⇒ 跑 0 条
#: ⇒ 判红」）。**必须走新门**，理由与上一条同源但更硬：本修法给 `_light_gate_plan` 里**新增
#: 一次活动调用**（读挂账册的名册活动）。在飞老实例（t260930-14：历史里已有 4 个闸轮、没有
#: 本标记）重放旧轮时，若无门 ⇒ 多出一条 ScheduleActivityTask 命令 ⇒ 与历史逐条对不上 ⇒
#: NonDeterminismError，票直接卡死。有门 ⇒ 重放旧轮 `patched()`=False（旧命令序列逐字不变），
#: 追平历史之后的新一轮 `patched()`=True ⇒ 记标记并真的走回落逻辑（正是要救的那一轮）。
LIGHT_NARROWED_FACE_PATCH_ID = "light-lane-narrowed-face-empty-v1"

#: 门=LIGHT_GATE_RECHECK_PATCH_ID（t261002-02，KI-182 落成机制）：闸红转人**之前**
#: 新增一次 `reprobe_red_scenarios` 探针活动调用（对闸拦名单=「本票的账」家族在
#: **同一棵泳道树**上单跑复验）。无门会让在飞老实例重放旧轮时多出一条命令 ⇒
#: NonDeterminismError；门 False ⇒ 旧命令序列逐字不变（红轮直接 blocked，零探针）。
#: 判定面（纯函数）=failure_protocol.apply_reprobe_recheck：探针全绿 ⇒ 该名降级
#: unattributable（台面族，不记本票的账）；未证全绿 ⇒ 维持本票的账。**放行口径
#: 零改动**：轮仍红、仍 blocked、仍转人——降级只改账本，不造「绿」（堵「靠重跑碰
#: 绿」的放行路径：现在复验跑绿也是 blocked，人看到的是「不可归因」而不是「碰绿」）。
LIGHT_GATE_RECHECK_PATCH_ID = "light-lane-gate-recheck-v1"

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

#: 环境红面的三态（票面用；判据零改动——**无具名通道即不豁免**，B2 口径）：
#:   named      = 至少一路（闸权威 env_red / 执行器侧 env_red_names）给出了名字；
#:   unnameable = env_fail>0 而两路都空/缺键/畸形 —— 必须**显式点名这一事实**；
#:   none       = 本轮没有环境红计数。
ENV_RED_NAMED = "named"
ENV_RED_UNNAMEABLE = "unnameable"
ENV_RED_NONE = "none"

#: 逐名归因三态（t260930-09 真票教训：只给红名不给归因 = 让人对着存量红反复返工）：
#:   lane-only    = 基线（main 尖端）该名是绿的 ⇒ 本票的账；
#:   main-red-too = 基线该名也红 ⇒ 存量，记录不阻断（不是本票的账）；
#:   unknown      = 基线**没有该名的答案**（没跑到/缺基线/指纹不等）——**绝不读作
#:                  main 绿，也绝不读作「可以放行」**，保守按「本票的账」对待。
ATTR_LANE_ONLY = "lane-only"
ATTR_MAIN_RED_TOO = "main-red-too"
ATTR_UNKNOWN = "unknown"

#: 轻道可打回段（rework 词表）：比 PHASE_MAIN_CHAIN 窄——审方案/仲裁/验收走查在轻道
#: **不存在**，打回它们只会在主循环落到「未知相位」。词表窄于闸＝拒收点名，绝不放进去。
LIGHT_REWORK_TARGETS = frozenset({
    # 宿主 260930：create_plan 段已删——它**也不再是可返工目标**（打回一个不存在的段
    # 只会把票打到未知相位；拒收面会具名点名「不是轻道段」）。
    "implement", "run_integration_tests", "merge_check", "merge"})

#: 轻道段级补述：在 dev-lane 的同段补述**前面**加一段轻道契约说明；正文 import 复用，
#: 纪律条文（英文报告义务 + developer 段集成禁跑执法）因此与 dev-lane 同源、不会漂移。
LIGHT_LANE_PRELUDE = (
    "【本票走轻道（light lane）】段链=implement →（UI 票才有 ui_evidence 截图步）"
    "→ run_integration_tests（机器闸）→ merge_check → merge（人审）。"
    "本道**没有**方案段、没有方案复审、没有集测设计、没有仲裁、没有验收走查："
    "范围的真源=票面声明的写集，机器闸不绿就停下等人（不自动重跑、不自动仲裁），"
    "所以一轮交付要尽量把事做完。\n")

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
    TEMPLATE_DESC = ("轻道（light lane）：prepare_workspace→implement→（UI 票 ui_evidence）"
                     "→run_integration_tests（机器闸，一轮一判）→merge_check→merge（人审）"
                     "——红转人，不自动仲裁、不自动重跑；不写方案（范围=票面声明的写集）")
    #: 段补述来源（dev-lane 的 _run_agent_step 读本属性；dev-lane 侧值=FLOW_BRIEF，
    #: 逐字不变——纯加法钩子）。
    FLOW_BRIEF_SET: Dict[str, str] = LIGHT_FLOW_BRIEF

    #: 闸前主同步的**票面/提示文案**覆写档（宿主 260930）：机制与命令序列走 dev-lane 的
    #: `_main_sync_before_gate` 那一份（唯一实现），只把「人读的那几句」换成英文——
    #: 轻道票面与控制台文案一律英文（CLAUDE.md 规则 6 及 260925 补充令）。缺省（全车道）
    #: 仍是 dev-lane 的中文历史原文，逐字不变。
    LIGHT_MAIN_SYNC_TEXTS: Dict[str, str] = {
        "unreachable": ("Main sync failed — a human has to take it: this lane never skips "
                        "the sync (otherwise the verified tree is not the tree that would "
                        "be merged): %s%s"),
        "resolve_round": "Main sync conflict, resolution round %d (%s): %s",
        "conflict_ctx": (
            "【main-sync conflict round gen%d/cap%d】This round is NOT feature work: the "
            "pre-gate main sync merged main into the lane (repo %s) and the worker already "
            "ran git merge main. These files carry conflict markers (<<<<<<< lane / "
            "======= / >>>>>>> main):\n%s\n"
            "merge output summary (ours=lane / theirs=main):\n%s\n"
            "Task: resolve the conflict markers file by file, keep both sides' semantics "
            "(same as t260825-03); touch only the conflicted files, no unrelated edits; "
            "**do NOT git commit** (the worker settles the merge commit after you deliver "
            "your result file). "
            # t261004-35: same two clauses as the default text — the forbidden-entry
            # list is rendered by dev_lane from FORBIDDEN_ENTRIES (same source as the
            # matcher), filled into the extra %s below.
            "This round must NOT run any integration entry (named: %s) — running any "
            "one of them fails the entire round and the resolved work is discarded "
            "(mechanical scan at settle; the declaration is the enforcement). "
            "Self-check only at parse level: python3 -m py_compile <file> (python "
            "syntax), python3 -m json.tool <file> (JSON validity), "
            "git diff --check (leftover conflict markers / whitespace), "
            "node --check <file> (JS syntax) — never by running the suite. "
            "Write the result file when done."),
        "agent_failed_fmt": "Main sync conflict resolution round %d: %s",
        "settle_unconverged": (
            "Main sync conflict resolution round %d did not converge (the worker's settle "
            "check failed): %s. The workspace is mid-merge. The executor can settle this: "
            "send rework(to_stage=implement). The implement stage resolves the conflict "
            "markers, then the gate re-runs. A human has to run git merge --abort in the "
            "lane if a reset is needed; send retry_qc after that reset"),
        "back_to_implement": ("Main sync conflict resolved (round %d) — back to implement to "
                              "adapt to the main changes"),
        "synced_log": "main sync (%s): %s",
        "reset_exception": (" | merge reset attempt raised (%s: %s) — the lane may still be "
                            "mid-merge; a human has to finish it"),
        "reset_ok": (" | merge reset done (MERGE_HEAD cleared) — the next main sync retries "
                     "from a clean tree"),
        "reset_failed": (" | merge reset failed: %s — the lane is still mid-merge; a human "
                         "has to finish it"),
    }

    # 票面纪律（宿主 260930 实报：阻断面是一大坨机器清单，人找不到「我该做什么」）：
    # 票面=给人看的摘要（一段结论 + 需要人做的决定 + 可行动的点名），机器清单进
    # blocked_detail / 闸回执 / 报告文件。三条上限即机械判据（UT 钉死，判据一字不放宽）。
    FACE_NAME_LIMIT = 5      # 「本票的账」最多列 5 个名字，多了给 (+N more)
    FACE_SAMPLE_MAX_LEN = 200  # 名单片段字节上限（名字很长时自动少列，保证字数不爆）
    FACE_MAX_LINES = 10      # blocked_reason 行数上限
    # blocked_reason 字数上限。261001 由 1200 提到 1350：**新增了一行强制内容**——
    # 「谁验的」（host 令 260930：每轮报都要能读到），它随回执里的 worker 身份/代码指纹走。
    # 示例面（最丰富的那种：全量+窄面+存量红+环境红+本票的账全在场）实测 1265 字。
    # 上限只随**强制行**增长，不随可选内容增长——加行不加预算的做法等于让票面慢慢长回墙。
    FACE_MAX_CHARS = 1350    # blocked_reason 字数上限
    FACE_BULK_MIN_ITEMS = 6  # 机械判据：逗号分隔 ≥6 项…
    FACE_BULK_MIN_LEN = 400  # …且该片段总长 >400 = 机器清单内联（票面不得出现）

    # 段声明（角色/种类/人门标记/条件段注记与 run() 同序；acceptance 是**票面文字**，
    # 按 CLAUDE.md 规则 6 全英文）。**首段=implement**（宿主 260930 裁定删 create_plan：
    # 见模块头注「为什么没有 create_plan」——口径与代价都在那里）。
    # **条件段 ui_evidence**（宿主 260930 第二轮裁定加回）：脚本段，仅 UI 票；判据=dev-lane
    # 同一 diff 源（非 UI 票零活动零痕迹，见 `_light_record_ui_evidence` 的落痕口径）。
    STAGES = (
        Stage(id="implement", name="实现", role="developer", next="ui_evidence",
              desc="按方案开发：写集白名单内；agent 沙箱写不了真 .git，commit 由 worker "
                   "代落盘；单测随实现交付",
              parts=("agent", "script"),
              acceptance=("Changes stay inside the write set",
                          "Changes are committed to the lane branch (the worker settles "
                          "on the agent's behalf)",
                          "Unit tests for the change run green")),
        # 条件段（仅 UI 票；非 UI 票零活动零痕迹）。真编排在 implement 段尾部 inline 调用
        # dev_lane._ui_evidence_step（同一 helper、同一判据）；本类只做「段有没有跑」的记账。
        Stage(id="ui_evidence", name="UI截图证据", role="developer",
              next="run_integration_tests",
              desc="条件段（仅 UI 票）：实现落盘/结算后 worker 代跑 ui-check 隔离台截图，落 "
                   ".sandbar/screenshots/（脚本段、无 agent 无 LLM；软失败不拦主链，merge_check "
                   "的 UI 证据闸兜底）",
              parts=("script",),
              acceptance=("UI tickets carry screenshots under .sandbar/screenshots/ "
                          "(the merge_check UI-evidence gate checks it mechanically)",)),
        # 注：本段相位的第一件事是**闸前主同步**（把 main 并进泳道一次，机制=dev-lane 的
        # `_main_sync_before_gate` 共享 helper，门=LIGHT_MAIN_SYNC_PATCH_ID）——它是**段链
        # 之外的一步**（段表里没有它），却决定「被验证树=被合并树」；见模块头注与相位注释。
        Stage(id="run_integration_tests", name="跑集成测试", role="integration",
              next="merge_check", agent=False,
              desc="程序化（无 agent）：泳道 0-commit 前置检查 → 闸前主同步（把 main 并进泳道一次，"
                   "被验证树=被合并树）→ 改动清单 → 面计划收窄快反馈面 "
                   "→ 跑项目声明的集成命令（与 dev-lane 同一条命令、同一个执行器）；不绿即 blocked "
                   "（票面=给人看的摘要：计数 + 本票的账最多 5 名 + 出路 ≤3；完整违规集在 "
                   "blocked_detail/回执里）；不自动重跑、不调仲裁；定点轮放行只认收口全量跑",
              parts=("script",),
              gate=LIGHT_LANE_GATES[(LIGHT_LANE_TEMPLATE_ID, "run_integration_tests")],
              acceptance=("The project-declared integration command ran and produced a receipt",
                          "Any red is carried through in full — every failing scenario "
                          "name, the counts, and the receipt pointer")),
        Stage(id="merge_check", name="合并检查", role="integration", next="merge",
              agent=False,
              desc="程序化检查（无 agent）：泳道有 commit、工作区干净、泳道内 verify_lane 绿、"
                   "merge-tree 无冲突；phase entry re-merges main before the check "
                   "(t261002-10: a retry_qc brings a main-side fix into the lane within "
                   "one retry; up to date = zero action; re-merge conflict goes to the "
                   "existing resolution loop, unreachable = loud blocked)；"
                   "任一项红 → blocked 等人（轻道不做自动冲突消解轮）",
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

    # ------------------------------------------------- UI 证据条件段的票面记账
    def _light_record_ui_evidence(self, started_epoch: int) -> bool:
        """把**真跑过**的 UI 证据条件段落进票面；返回是否落痕。

        判据来源=dev_lane._ui_evidence_step 的产物：它只在 UI 票上写
        `self.results['ui_evidence']`（内部判据=diff 源 + 宣布门 + fail-closed，一字不重写）。
        没这份回执（非 UI 票）→ **零条目零记账**（这是「非 UI 票 ui_evidence 四处零出现」
        负断言的实现面）。

        落痕口径（诚实声明，不铸假证据）：判据在 helper **内部**、且 helper 先判后拍，调用点
        无法在拍之前知道是不是 UI 票，所以这里落的两条是**终态痕迹**——`running` 条目的
        reason 明确写出「本段在 implement 分支 inline 跑完，这是终态痕迹」并带上**真实时长**
        （调用点自己掐的墙钟），`done` 由 `_finish` 落（同时勾掉本段验收项）。段序仍然正确：
        两条都排在 implement/done 之后、机器闸 `_enter` 之前。"""
        rec = self.results.get("ui_evidence")
        if not isinstance(rec, dict):
            return False
        dur = max(0, self._now_epoch() - int(started_epoch or 0))
        self._mark("ui_evidence", "running",
                   "conditional stage (UI ticket, diff source): the capture ran inline in the "
                   "implement branch through the shared UI-evidence helper — this entry is its "
                   "terminal trace (real duration %ds); the next station is the machine gate"
                   % dur)
        self._finish("ui_evidence", by="ui-capture",
                     evidence=str(rec.get("summary") or ""))
        self._handoff("ui_evidence",
                      "UI evidence: %s" % (str(rec.get("summary") or "")[:200]),
                      artifacts=list(rec.get("deliverables") or []),
                      report=str(rec.get("evidence") or ""))
        return True

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
        """机器闸二态判定（轻道自己的判词，不引仲裁，但**照失败分类协议吃闸的归因结论**）：
        green / red。

        为什么必须消费 `blockers`（t260930-09 实况：violations=15 而 blockers=6）：全车道靠
        仲裁段消化「本票的账 vs main 存量」这个差别；轻道没有仲裁，只能**机械地照闸已经算好
        的归因结论**走——否则只要 main 上有存量红（常态），每一张轻道票每一轮都会被判红，
        永远落不了地。闸的 `blockers` = 归因后「本票的账」（决策表 verdict=block），
        `violations` 则含 main 存量与不可归因面，两者**不是一个集合**。

        green ⟺ 三条同时成立（任一不成立 = red，保守方向一个字不放宽）：
          ① `blockers` 为空（= 归因后本票无欠账）；
          ② 本轮**没有不可归因的红** —— 每个 violation 都有基线答案（无 `unknown`；
             「没跑到/基线不可得」不算答案，绝不当 main 绿）；
          ③ `env_fail>0` 时必须**具名**（两路具名通道任一给出名字；unnameable 仍判红）。
        判绿的轮次必须**记录在案**：调用方用 `_light_recorded_pre_existing()` 把「本轮被
        记录而不阻断的存量红（逐名）+ 基线参考 + 来源」写进回执/票面，绝不静默变绿。"""
        if ir is None:
            return "red"
        if str(getattr(ir, "error", "") or ""):
            return "red"
        # ① 本票的账（闸的归因结论）
        if [str(b) for b in (getattr(ir, "blockers", None) or []) if str(b)]:
            return "red"
        # 形状守卫（保守方向：计数读不懂 / 有计数无名单 ⇒ 红名单不可信，不许静默放行）
        try:
            failed = int(getattr(ir, "failed", 0) or 0)
            env_fail = int(getattr(ir, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            return "red"
        prod_names = self._tests_product_red_names(ir)
        if failed > 0 and not prod_names:
            return "red"
        # ② 不可归因的红不许当绿：**每个产品红名**都要有基线答案（环境红由 ③ 处置）
        attr = self._light_gate_attribution(ir, prod_names)
        if attr["unknown"]:
            return "red"
        # ③ 环境红必须具名
        if env_fail > 0:
            env_face = self._light_env_red_face(ir)
            if env_face["state"] == ENV_RED_UNNAMEABLE:
                return "red"
        return "green"

    def _light_recorded_pre_existing(self, ir: Any) -> Dict[str, Any]:
        """判绿轮次的「记录在案」面（自证：这些红被看见了、被记账了、不是漏跑）。

        返回块（空 dict=本轮没有需要记录的存量红）：`names` 逐名 + `count` +
        `baseline_ref` + `source` + 协议口径一句。消费方把它写进闸回执与票面（handoff/log）。"""
        names = self._tests_product_red_names(ir)
        if not names:
            return {}
        attr = self._light_gate_attribution(ir, names)
        if not attr["main_red_too"]:
            return {}
        return {
            "names": list(attr["main_red_too"]),
            "count": len(attr["main_red_too"]),
            "baseline_ref": attr["baseline_ref"],
            "source": attr["source"],
            "note": ("recorded, not blocking: these scenarios are red on the main baseline too "
                     "(failure-classification protocol: main red ⇒ record, do not block). They "
                     "were seen this round, booked here, and are NOT a silent skip."),
        }

    def _light_run_face(self, ir: Any, run_only: Any) -> Dict[str, Any]:
        """本轮**跑面**（诚实面：跑了什么、没跑什么、有没有复用）——直接取闸回执的现成
        注记，不重判：
          · narrowed：ir.only_names（非空=定点快反馈面，空=全量）；
          · excluded_pools/excluded_count：声明池跳过面；
          · reuse：闸回执的复用块（老回执缺键=如实记 absent，不冒充）；
          · known_red：在册红豁免面——**260930 起给具名原因**（真票 t260930-09 的
            "absent" 说不清是「没注入」还是「没搬到」）：在场=块（含 injected/skipped/
            names）；缺席=标注 available=False + 原因（老闸回执没搬这一块 + 注入事实）。"""
        reuse = getattr(ir, "reuse", None)
        known_red = getattr(ir, "known_red", None)

        def _face(v):
            """在场（非空 dict）→ 原样；缺席/空/畸形 → 如实点名（不冒充）。"""
            if isinstance(v, dict):
                return dict(v) if v else "absent: the receipt carried no such block"
            return "absent: the receipt carried no such block" if v is None else str(v)

        _kr_face = _face(known_red)
        if not isinstance(_kr_face, dict):
            # 缺席/畸形：把「注入事实」与「没搬到」分开点名（两者含义不同）
            _kr_face = {"available": False, "injected": "unknown",
                        "names": [], "skipped": 0, "reason": str(_kr_face)}

        return {
            "requested_only_names": [str(x) for x in (run_only or [])],
            "narrowed": [str(x) for x in (getattr(ir, "only_names", None) or [])],
            "excluded_pools": [str(x) for x in (getattr(ir, "excluded_pools", None) or [])],
            "excluded_count": int(getattr(ir, "excluded_count", 0) or 0),
            "reuse": _face(reuse),
            "known_red": _kr_face,
        }

    def _light_env_red_face(self, ir: Any) -> Dict[str, Any]:
        """环境红面（纯读，判据零改动）：两路具名通道并列 + 三态点名。

        两路的分工（不许混读）：
          · gate  = 闸的**权威**通道 `env_red`（not-checked × external；豁免只认它，B2）；
          · runner= 执行器侧具名名单 `env_red_names`（观测面，**不是**豁免依据）。
        env_fail>0 而两路都拿不出名字 → `unnameable`，票面**必须显式点名**（不许静默空表）。"""
        gate_names, channel_ok = self._tests_env_red_names(ir)
        runner_raw = getattr(ir, "env_red_names", None)
        runner_names = [str(x).strip() for x in runner_raw
                        if str(x or "").strip()] if isinstance(runner_raw, list) else []
        try:
            env_fail = int(getattr(ir, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            env_fail = 0
        if env_fail <= 0:
            state = ENV_RED_NONE
            note = "no environment red was counted this round"
        elif gate_names or runner_names:
            state = ENV_RED_NAMED
            note = ("named by %s" % " + ".join(
                [p for p, v in (("the gate channel (authoritative, B2)", gate_names),
                                ("the runner-side list (observation only)", runner_names)) if v]))
        else:
            state = ENV_RED_UNNAMEABLE
            note = ("the gate's named channel (env_red, B2 authoritative) is %s and the "
                    "runner-side name list is empty"
                    % ("present but empty" if channel_ok else "absent/malformed"))
        return {"count": env_fail, "gate": gate_names, "gate_channel_ok": bool(channel_ok),
                "runner": runner_names, "state": state, "note": note}

    def _light_gate_attribution(self, ir: Any, names: List[str]) -> Dict[str, Any]:
        """逐名归因（纯读）：`lane-only` / `main-red-too` / `unknown` + 来源点名。

        数据面=闸回执的活基线证据（`live_baseline_green/red/source`，来源=本轮闸基线主跑
        逐名答案 ∪ 场景台账可信行；合成单点=shared.live_baseline_evidence）——**不新增判据、
        不改闸的拦/记**，只把「这条红是谁的账」搬到票面。

        保守方向（t260930-09 教训）：两路都有名字时**绿优先**（按本票的账）；没有答案的
        名字一律 `unknown`，并在票面写明「unknown ≠ main 绿 ≠ 可以放行」。"""
        green, red = set(), set()
        for raw, bucket in ((getattr(ir, "live_baseline_green", None), green),
                            (getattr(ir, "live_baseline_red", None), red)):
            if isinstance(raw, (list, tuple, set, frozenset)):
                for x in raw:
                    if isinstance(x, str) and x.strip():
                        bucket.add(x.strip())
        src = str(getattr(ir, "live_baseline_source", "") or "") or \
            "no source named by the receipt"
        lane_only, main_too, unknown = [], [], []
        for n in names:
            if n in green:
                lane_only.append(n)
            elif n in red:
                main_too.append(n)
            else:
                unknown.append(n)
        return {"lane_only": lane_only, "main_red_too": main_too, "unknown": unknown,
                "baseline_ref": str(getattr(ir, "baseline_ref", "") or ""),
                "source": src,
                "rule": ("green wins when both lists name a red (conservative: it stays this "
                         "ticket's account); unknown means the baseline produced no answer for "
                         "that name and is NEVER read as main-green and NEVER as a landing "
                         "permit")}

    async def _light_gate_recheck(self, ir: Any) -> Dict[str, Any]:
        """归属前复验（KI-182 / t261002-02）：闸拦名单（=「本票的账」家族，基线红
        名单已在闸侧记 record 不在拦名单里）逐名在**同一棵泳道树**上单跑复验
        （`reprobe_red_scenarios` 探针活动——与 dev-lane 计轮探针同一活动、同一执行
        器语义，name→cmd 解析仍=执行器 SCENARIOS 单一真源）。判定面=
        `failure_protocol.apply_reprobe_recheck`（纯函数）：探针全绿 ⇒ 该名降级
        unattributable（台面族，不记本票的账）；未证全绿 ⇒ 维持本票的账。

        fail-closed：活动故障/回执形状未知/名单空 ⇒ recheck.available=False，调用方
        按零降级处理（绝不因探针缺席放行或洗账）。返回 apply_reprobe_recheck 的
        输出形状（verdicts/unattributable/rechecked/ticket_account/recheck）。"""
        names = [str(b).strip() for b in (getattr(ir, "blockers", None) or [])
                 if str(b).strip()]
        if not names:
            return {"verdicts": [], "unattributable": [], "rechecked": [],
                    "ticket_account": [],
                    "recheck": {"available": False, "all_green": False, "ran": 0,
                                "error": "", "unattributable": [],
                                "ticket_account": [],
                                "skipped": "no blockers to re-check"}}
        try:
            raw = await workflow.execute_activity(
                reprobe_red_scenarios,
                ReprobeRedArgs(ticket_id=self.ticket_id,
                               worktree=str(self.meta.get("worktree") or ""),
                               names=names),
                start_to_close_timeout=REPROBE_TO, retry_policy=RETRY)
            receipt = raw if isinstance(raw, ReprobeRedResult) else None
            if receipt is None:
                return failure_protocol.apply_reprobe_recheck(
                    [{"name": n, "verdict": "block",
                      "why": "regression(lane red; main green)"} for n in names],
                    {"available": False, "error": "probe receipt shape unknown",
                     "ran": 0, "failed": 0, "env_fail": 0, "missing": []})
        except Exception as e:  # noqa: BLE001——探针故障=fail-closed，不洗账不放行
            err = "probe activity fault: %s: %s" % (type(e).__name__, str(e)[:200])
            return failure_protocol.apply_reprobe_recheck(
                [{"name": n, "verdict": "block",
                  "why": "regression(lane red; main green)"} for n in names],
                {"available": False, "error": err, "ran": 0, "failed": 0,
                 "env_fail": 0, "missing": []})
        doc = {"error": str(receipt.error or ""), "ran": int(receipt.ran or 0),
               "failed": int(receipt.failed or 0),
               "env_fail": int(receipt.env_fail or 0),
               "missing": list(receipt.missing or []),
               "entries": [dict(x) for x in (receipt.entries or [])
                           if isinstance(x, dict)]}
        return failure_protocol.apply_reprobe_recheck(
            [{"name": n, "verdict": "block",
              "why": "regression(lane red; main green)"} for n in names], doc)

    def _light_env_red_note(self, face: Dict[str, Any]) -> str:
        """环境红面的票面句子（三态各一句；unnameable 必须说清为什么）。"""
        if face["state"] == ENV_RED_NONE:
            return ""
        parts = ["Environment reds: %d counted" % face["count"]]
        if face["gate"]:
            parts.append("named by the gate channel (authoritative, B2): %s"
                         % ", ".join(face["gate"]))
        if face["runner"]:
            parts.append("named by the runner-side list (observation only, not an exemption "
                         "basis): %s" % ", ".join(face["runner"]))
        if face["state"] == ENV_RED_UNNAMEABLE:
            parts.append("**NOT NAMEABLE** — the gate's named channel is %s and the "
                         "runner-side list is empty; an unnameable environment red is NOT "
                         "exempt (no name, no exemption)"
                         % ("present but empty" if face["gate_channel_ok"]
                            else "absent/malformed"))
        if face["state"] != ENV_RED_UNNAMEABLE:
            parts.append("source: %s" % face["note"])
        return ("; ".join(parts) + ".")

    def _light_name_sample(self, names: Any, limit: Optional[int] = None,
                           max_len: Optional[int] = None) -> str:
        """票面具名样本：最多 `limit` 个 + `(+N more)`（全量名单在回执/明细里）。

        宿主 260930：票面「本票的账」最多列 5 个可行动名字，多了给计数与指针——
        人面对一屏场景名找不到「我该做什么」。**双重闸**：条数上限（`limit`）+ 片段字节
        上限（`max_len`）——名字很长时自动少列几个，保证票面字数不爆（这是「票面 ≤1200
        字」的机械保证，不是审美偏好）。"""
        lim = int(self.FACE_NAME_LIMIT if limit is None else limit)
        budget = int(self.FACE_SAMPLE_MAX_LEN if max_len is None else max_len)
        items = [str(n).strip() for n in (names or []) if str(n or "").strip()]
        if not items:
            return "none"
        picked: List[str] = []
        used = 0
        for n in items[:lim]:
            add = len(n) + (2 if picked else 0)
            if picked and used + add > budget:
                break
            picked.append(n)
            used += add
        if len(picked) == len(items):
            return ", ".join(picked)
        return "%s (+%d more)" % (", ".join(picked), len(items) - len(picked))

    def _light_face_pointer(self) -> Dict[str, str]:
        """机器清单的**指针面**（票面只给指针，清单本体进明细/回执/报告文件）。"""
        return {"receipt_ref": "results.run_integration_tests",
                "detail_ref": "blocked_detail",
                "report_path": "out/integration-report-*.json"}

    def _light_blocked_reasons(self, ir: Any) -> List[str]:
        """本轮**为什么红**（与 `_light_gate_verdict` 的三条判据一一对应，只给原因不给清单）。

        票面必须让人一眼看出是**哪条判据**把本轮按住的（判据一个字不改，只改呈现）。"""
        if ir is None:
            return ["no gate receipt at all"]
        reasons: List[str] = []
        if str(getattr(ir, "error", "") or ""):
            reasons.append("no receipt (gate error: %s)" % str(ir.error)[:120])
        blockers = [str(b) for b in (getattr(ir, "blockers", None) or []) if str(b)]
        if blockers:
            reasons.append("blockers non-empty (%d) — this ticket's account" % len(blockers))
        try:
            failed = int(getattr(ir, "failed", 0) or 0)
            env_fail = int(getattr(ir, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            return reasons + ["counts malformed — treated as red"]
        prod_names = self._tests_product_red_names(ir)
        if failed > 0 and not prod_names:
            reasons.append("%d failure(s) counted but none named — an unnamed red is never "
                           "green" % failed)
        attr = self._light_gate_attribution(ir, prod_names)
        if attr["unknown"]:
            reasons.append("%d red(s) with no baseline answer (unknown is NOT main-green)"
                           % len(attr["unknown"]))
        if env_fail > 0 and self._light_env_red_face(ir)["state"] == ENV_RED_UNNAMEABLE:
            reasons.append("%d env red(s) not nameable (no name, no exemption)" % env_fail)
        if not reasons:
            reasons.append("the round is not green — raw details in the receipt")
        return reasons

    def _light_attribution_note(self, attr: Dict[str, Any]) -> str:
        """归因面的**计数句**（票面口径，宿主 260930：逐名归因表不进票面）。

        逐名归因表本体仍在 `blocked_detail.attribution`（审计/消费面）；票面只说
        「几成是本票的账 / 几成是 main 存量 / 几条无基线答案」+ 指针。"""
        return ("Red attribution against main (baseline ref %s; source: %s): %d lane-only "
                "(this ticket's account, main is green); %d main-red-too (pre-existing on "
                "main, recorded, not this ticket's account); %d unknown (no baseline answer — "
                "NOT main-green and NOT a landing permit). Per-name table: blocked_detail."
                % (attr["baseline_ref"] or "unavailable", attr["source"],
                   len(attr["lane_only"]), len(attr["main_red_too"]), len(attr["unknown"])))

    def _light_gate_blocked_text(self, ir: Any, run_only: Any, phase_note: str,
                                 recheck: Optional[Dict[str, Any]] = None) -> str:
        """轻道机器闸 blocked 文案（票面英文）——**给人看的一屏摘要**，不是机器清单。

        宿主 260930 实报：旧文案把收窄面全表（200+ 个场景名）、全量违例表、逐名归因表、
        台账复用面、在册红面全内联进票面，人对着机器清单找不到「我该做什么」。本函数即
        该口径的执法点，固定四段（行数上限 `FACE_MAX_LINES`、字数上限 `FACE_MAX_CHARS`）：
          ① 一行结论 + 一行「需要你做什么」；
          ② 本轮轮次与**判红原因**（哪条判据按住）+ 计数一行；
          ③ 本票的账（可行动）：最多 `FACE_NAME_LIMIT` 个名字 + `(+N more)` + 指向回执；
             空则明写「none of the reds are this ticket's account」；
          ④ 存量红/环境红：**只给计数**与「已记录、不阻断（详见回执）」——不列名；不可具名
             的环境红单独一行点名（它**阻断**，不是「已记录」）；
          ⑤ 出路 ≤3（rework / retry_qc / 另开全车道票）。
        机器清单（收窄面全表、全量违例表、逐名归因表、台账复用面、在册红面）一律只进
        `_light_gate_blocked_detail` / 闸回执 / 报告文件——票面只留计数与指针。"""
        names = self._light_red_names(ir)
        env_face = self._light_env_red_face(ir)
        attr = self._light_gate_attribution(ir, names)
        face = self._light_run_face(ir, run_only)
        ptr = self._light_face_pointer()
        blockers = [str(b) for b in (getattr(ir, "blockers", None) or [])
                    if str(b) and not str(b).startswith("__")]
        main_too = set(attr["main_red_too"])
        # 归属前复验（t261002-02）：探针全绿的名字降级 unattributable，**不算本票
        # 的账**（不进 Fix 面、不进计数）——但轮仍红仍 blocked（降级只改账本不造绿）。
        unattr = [str(n) for n in ((recheck or {}).get("unattributable") or [])
                  if str(n)]
        # 本票的账（可行动）= 闸的拦名单 − 基线已证「main 也红」的名字 − 复验降级
        # unattributable 的名字；unknown 仍算本票的账
        actionable = [b for b in blockers
                      if b not in main_too and b not in set(unattr)]
        lines = [
            "Blocked: the machine gate is red — one machine round per attempt: no "
            "arbitration, no automatic re-run; a human decides.",
            "Round: %s. Why red: %s." % (phase_note or "gate round",
                                         "; ".join(self._light_blocked_reasons(ir))),
            "Counts: %s ran / %s passed / %s failed / %s env-red; this ticket's account: "
            "%d red(s)." % (getattr(ir, "ran", 0), getattr(ir, "passed", 0),
                            getattr(ir, "failed", 0), getattr(ir, "env_fail", 0),
                            len(actionable)),
        ]
        if actionable:
            lines.append("Fix (this ticket's account): %s."
                         % self._light_name_sample(actionable))
        else:
            lines.append("This ticket's account: none of the reds are this ticket's account.")
        _face_sent = failure_protocol.unattributable_face_sentence(
            unattr, (recheck or {}).get("ticket_account") or [])
        if _face_sent:
            lines.append(_face_sent)
        recorded = []
        if attr["main_red_too"]:
            recorded.append("%d pre-existing on main" % len(attr["main_red_too"]))
        if env_face["count"] > 0 and env_face["state"] != ENV_RED_UNNAMEABLE:
            recorded.append("%d environment red(s)" % env_face["count"])
        if recorded:
            lines.append("Recorded, not blocking: %s — booked, never a silent skip."
                         % "; ".join(recorded))
        if env_face["state"] == ENV_RED_UNNAMEABLE:
            lines.append("Environment red(s): %d NOT NAMEABLE (gate channel %s) — not "
                         "exempt: no name, no exemption."
                         % (env_face["count"],
                            "present but empty" if env_face["gate_channel_ok"]
                            else "absent/malformed"))
        lines.append("Outcome: (1) rework(to_stage=implement) to repair; (2) retry_qc to "
                     "re-run the gate; (3) open a full-lane ticket (dev-lane).")
        face_bits = ["full registry (not narrowed)" if not face["narrowed"]
                     else "narrowed to %d entr%s" % (len(face["narrowed"]),
                                                     "y" if len(face["narrowed"]) == 1
                                                     else "ies")]
        if face["excluded_pools"]:
            face_bits.append("pools skipped: %s (%d entries)"
                             % (", ".join(face["excluded_pools"]), face["excluded_count"]))
        # 复用面/在册红面：只给计数；老回执缺块=「n/a (old receipt)」（两块都缺时合成一句，
        # 省票面字数——这两块都不是判据，只是「少跑面」的诚实计数）
        _reuse_abs = not isinstance(face["reuse"], dict)
        _kr_abs = face["known_red"].get("available") is False
        if not _reuse_abs:
            face_bits.append("ledger reuse: reused=%s of expected=%s"
                             % (face["reuse"].get("reused"), face["reuse"].get("expected")))
        if not _kr_abs:
            face_bits.append("known-red excluded: %d"
                             % int(face["known_red"].get("skipped") or 0))
        if _reuse_abs and _kr_abs:
            face_bits.append("reuse/known-red: n/a (old receipt)")
        elif _reuse_abs:
            face_bits.append("ledger reuse: n/a (old receipt)")
        elif _kr_abs:
            face_bits.append("known-red: n/a (old receipt)")
        # 「谁验的」一行（宿主令 260930：每轮报都要能读到）。口径与回执 summary 里那句同源
        # （shared.worker_verified_line 单点），不可得也具名——票面上不出现「验过了」这种无主语断言。
        _vf = shared.worker_verified_line(getattr(ir, "worker_identity", ""),
                                         getattr(ir, "code_stamp", None))
        if _vf:
            lines.append(_vf)
        lines.append("Details: %s (full machine lists) + report %s (receipt %s). Round "
                     "face: %s."
                     % (ptr["detail_ref"], ptr["report_path"], ptr["receipt_ref"],
                        "; ".join(face_bits)))
        return "\n".join(lines)

    def _light_gate_blocked_detail(self, ir: Any, run_only: Any, reason_code: str,
                                   phase_note: str,
                                   recheck: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """机器闸 blocked 的结构化明细（**机器清单的家**；键族与父类 blocked_detail 同形；
        additive 键承载完整违规集与跑面，供票面/控制台机读）。

        宿主 260930 分面：票面（`_light_gate_blocked_text`）只留摘要与指针，**全量机器数据
        全部留在本明细**（消费方与审计面），并给三个显式指针键
        （`report_path` / `receipt_ref` / `detail_ref`）让人一键找到全量。"""
        names = self._light_red_names(ir)
        env_names, channel_ok = self._tests_env_red_names(ir)
        env_face = self._light_env_red_face(ir)
        attr = self._light_gate_attribution(ir, names)
        face = self._light_run_face(ir, run_only)
        ptr = self._light_face_pointer()
        return {
            "check_id": "run_integration_tests",
            "item": "machine gate (the project-declared integration command)",
            "red": True,
            "reason_code": reason_code,
            "files": [],
            "next_action": ("retry_qc re-runs the gate on the same tree; "
                            "rework(to_stage=implement) sends it back for repair; "
                            "open a dev-lane ticket for work beyond this lane"),
            # evidence=**计数 + 指针**（宿主 260930：收窄面/全量违例/逐名归因是全表，
            # 不许内联进票面；这里也只给计数与指针，全表在同块的 violations/attribution/
            # round 与报告文件里）
            "evidence": ("%s | counts: %s ran / %s passed / %s failed / %s env-red | "
                         "round: %s | complete violation set, per-name attribution and the "
                         "run face: this blocked_detail + the lane report %s"
                         % (phase_note or "gate round",
                            getattr(ir, "ran", 0), getattr(ir, "passed", 0),
                            getattr(ir, "failed", 0), getattr(ir, "env_fail", 0),
                            ("%d narrowed entr%s, pools skipped %d (%d entries)"
                             % (len(face["narrowed"]),
                                "y" if len(face["narrowed"]) == 1 else "ies",
                                len(face["excluded_pools"]), face["excluded_count"]))
                            if face["narrowed"] or face["excluded_pools"]
                            else "full registry, no pools skipped",
                            ptr["report_path"]))[:600],
            "violations": names,
            "violations_complete": True,
            "blockers": [str(b) for b in (getattr(ir, "blockers", None) or [])],
            "env_red": env_names,
            "env_red_channel_ok": bool(channel_ok),
            # 260930（真票 t260930-09 三处面缺陷之①）：环境红面三态 + 两路并列；不可具名
            # 必须显式点名（不许静默给空表）。
            "env_red_state": env_face["state"],
            "env_red_count": env_face["count"],
            "env_red_runner": env_face["runner"],
            "env_red_note": env_face["note"],
            # 三态各一句的可读句子（审计面；票面只给计数，句子留在这里）
            "env_red_face_note": self._light_env_red_note(env_face),
            # 之③：逐名归因（lane-only / main-red-too / unknown）+ 来源与保守口径
            # （`note` 是同一块的计数句，供人读明细时不必自己数）
            "attribution": dict(attr, note=self._light_attribution_note(attr)),
            # 归属前复验（t261002-02，KI-182）：降级名单/复验后仍账名单/探针面——
            # additive 键；探针没跑（门关/活动故障/零拦名单）= available=False 如实记。
            "recheck": dict({"available": False, "all_green": False, "ran": 0,
                             "error": "", "unattributable": [],
                             "ticket_account": [],
                             **((recheck or {}).get("recheck") or {})},
                            verdicts=[{"name": str(v.get("name")),
                                       "verdict": str(v.get("verdict")),
                                       "why": str(v.get("why"))}
                                      for v in (recheck or {}).get("verdicts", [])
                                      if isinstance(v, dict)]),
            "counts": {"ran": int(getattr(ir, "ran", 0) or 0),
                       "passed": int(getattr(ir, "passed", 0) or 0),
                       "failed": int(getattr(ir, "failed", 0) or 0),
                       "env_fail": int(getattr(ir, "env_fail", 0) or 0)},
            "round": face,
            "receipt": "results.run_integration_tests",
            # 显式指针键（宿主 260930：让人一键找到全量机器清单）
            "report_path": ptr["report_path"],
            "receipt_ref": ptr["receipt_ref"],
            "detail_ref": ptr["detail_ref"],
            "remedies": ["retry_qc: re-run the gate on the same tree",
                         "rework(to_stage=implement, note=...): repair, then the gate re-runs",
                         "open a full-lane ticket (template dev-lane) for the remaining work"],
        }

    def _light_face_note(self, ir: Any, run_only: Any) -> str:
        """票面注记（票面英文）：本轮**少跑面的计数**（定点面条数/跳过池/台账复用/在册红）。

        宿主 260930：名单一律不进票面——这里只给计数与「名单在回执里」的指针
        （全量在 `blocked_detail.round` / 闸回执 / 报告文件）。空串=全量且无少跑面。"""
        face = self._light_run_face(ir, run_only)
        bits = []
        if face["narrowed"]:
            bits.append("narrowed to %d entr%s (list in the receipt)"
                        % (len(face["narrowed"]),
                           "y" if len(face["narrowed"]) == 1 else "ies"))
        if face["excluded_pools"]:
            bits.append("declared pools skipped: %s (%d entries)"
                        % (", ".join(face["excluded_pools"]), face["excluded_count"]))
        if isinstance(face["reuse"], dict) and int(face["reuse"].get("reused") or 0) > 0:
            bits.append("ledger reuse: reused=%s of expected=%s (not executed)"
                        % (face["reuse"].get("reused"), face["reuse"].get("expected")))
        if isinstance(face["known_red"], dict) \
                and int(face["known_red"].get("skipped") or 0):
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

    async def _booked_red_names(self) -> List[str]:
        """本轮挂账册（`booked`/`isolated`）里的名字——**只读**活动，用于「空收窄面回落全量」。

        词表取 `shared.KNOWN_RED_VERDICTS`（唯一真源，与执行器侧 `known_red_names`、名册卫生
        测试同源）：写死字面量会在词表演进时静默错位——引擎少认一个词=「面没空」而执行器照
        豁免 ⇒ 又回到「跑 0 条」，正是本修法要堵的那个形态。

        读不到/畸形 ⇒ 空集（读侧 fail-open）：豁免面不可得时**不得不窄**，而且执行器侧对
        「扣完为空」还有一道回落（两侧互为兜底，任一侧单独失效都不会退化成「跑 0 条」）。"""
        try:
            out = await self._known_red_roster_payload()
            payload = out.get("payload") or {}
            entries = ((payload.get("result") or {}).get("entries") or {})
            vocab = tuple(str(v).lower() for v in shared.KNOWN_RED_VERDICTS)
            return [str(n) for n, v in entries.items()
                    if str((v or {}).get("verdict") or "").lower() in vocab]
        except Exception as e:  # noqa: BLE001——只读诊断面，绝不拦主链
            self._log("known-red roster unavailable for the narrowed-face fallback (%s: %s) — "
                      "treating it as no exemption (the executor still falls back to the full "
                      "registry when a narrowed face empties)" % (type(e).__name__, str(e)[:120]))
            return []

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
            # 宿主 260930 实报（真票 t260930-14 第 4 轮）：快反馈面=上轮红名；那批红名若**全被
            # 挂账册豁免**（或在被排除池里），点名面扣完为空 ⇒ 执行器「一轮零场景」⇒ 闸判红。
            # 两个各自都对的机制（快反馈面=上轮红名 × 在册红不进每轮路径）撞出空集——空集必须
            # **回落全量**（空 run_only 在本类的既有约定就是「全量跑」），**空=更宽，不是红**。
            # 「未跑 ≠ 判绿」不变：回落跑出来的绿才是绿。
            # **门**（LIGHT_NARROWED_FACE_PATCH_ID）：本块新增一次名册活动调用，无门会让在飞
            # 老实例重放旧轮时多出命令 ⇒ NonDeterminismError（见该常量的注释）。
            if workflow.patched(LIGHT_NARROWED_FACE_PATCH_ID):
                _booked = set(await self._booked_red_names())
                _kept = [n for n in run_only if n not in _booked]
                if not _kept:
                    self.meta["narrowed_face_trace"] = {
                        "requested": list(run_only), "kept": [], "empty": True,
                        "exempted": [n for n in run_only if n in _booked],
                        "reason": "every member of the previous round's red list is "
                                  "booked/validated this round (known-red exemption) ⇒ an "
                                  "empty narrowed face is UNDECIDABLE, not a product red",
                        "action": "fall back to the full registry"}
                    self._log("the fast-feedback face is empty after this round's known-red "
                              "exemptions (%d member(s): %s) — an empty face is undecidable, "
                              "not a product red: falling back to the FULL registry (an empty "
                              "run_only is this lane's existing 'full run' convention)"
                              % (len(run_only), ", ".join(run_only[:12])))
                    self._handoff("run_integration_tests",
                                  "fast-feedback face empty after exemptions (%d) → full registry"
                                  % len(run_only))
                    return []
                if len(_kept) != len(run_only):
                    self.meta["narrowed_face_trace"] = {
                        "requested": list(run_only), "kept": list(_kept), "empty": False,
                        "exempted": [n for n in run_only if n in _booked],
                        "reason": "known-red exemption removed member(s) from the narrowed face",
                        "action": "run the kept members (fast feedback only)"}
                    self._log("fast-feedback face: %d of %d member(s) survive this round's "
                              "known-red exemptions: %s"
                              % (len(_kept), len(run_only), ", ".join(_kept[:12])))
                    run_only = _kept
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
        """机器闸回执上台面（results.run_integration_tests 形状与 dev-lane 同族）。

        260930 追加（additive 键）：`recorded_pre_existing` —— 判绿轮次里「被记录而不阻断」
        的存量红逐名 + 基线参考 + 来源（空 dict=本轮无存量红）。这是「绝不静默变绿」的自证面：
        读回执的人能直接看到那些红被看见了、被记账了。"""
        head = "closing full run" if closing else "integration gate"
        rec = self._light_recorded_pre_existing(ir) if not ir.error else {}
        # 宿主令 260930（B 档「谁验的」上票面）：服务本轮的 worker 身份 + 它的代码指纹
        # （结构化两键 + 人面最多一行）。**不可得也是具名面**（明写 unavailable + 原因），
        # 绝不留空让人误以为「验过了」。判据零改动：不参与 status/拦/记任何判定。
        _wf_line = shared.worker_verified_line(getattr(ir, "worker_identity", ""),
                                               getattr(ir, "code_stamp", None))
        out = {
            # status 跟**轻道判词**走（不是跟裸计数走）：判绿轮里若有 main-red-too，计数仍
            # 照实写进 summary、逐名进 recorded_pre_existing，但本段对票而言是绿的——
            # 否则控制台会出现「段 failed 却继续推进」的自相矛盾面。
            "status": "ok" if self._light_gate_verdict(ir) == "green" else "failed",
            "summary": ("%s: %s ran / %s passed / %s failed / %s env-red%s%s"
                        % (head, ir.ran, ir.passed, ir.failed, ir.env_fail,
                           (" | " + str(ir.error)) if ir.error else "",
                           (" | " + _wf_line) if _wf_line else "")),
            "report": "", "deliverables": [], "files_changed": [],
            "evidence": json.dumps(ir.details, ensure_ascii=False)[-4000:],
            "gen": gen,
            "worker_identity": str(getattr(ir, "worker_identity", "") or ""),
            "code_stamp": getattr(ir, "code_stamp", None) or {},
            "blockers": [str(b) for b in (getattr(ir, "blockers", None) or [])],
            "violations": self._light_red_names(ir),
            "recorded_pre_existing": rec,
        }
        if rec:
            out["summary"] += (" | recorded (main-red-too, not blocking): %d — %s"
                               % (rec["count"], ", ".join(rec["names"])))
        return out

    # ================================================================== 主流程
    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)

        # t261004-32: concurrency gate - same face as dev-lane (helpers in the
        # parent): judge the slot before the first stage, queue when not granted;
        # a declaration refusal fails the ticket here by name (rule 9).
        # t261005-14: patched guard - a pre-CL-1 history carries no marker, so
        # its replay must not schedule concurrency_acquire at all (TMPRL1100).
        if workflow.patched(LIGHT_CONCURRENCY_GATE_PATCH_ID):
            await self._concurrency_gate()

        # 1) 工作空间准备（dev-lane 同 helper：同活动/同失败转 blocked/同 rework 语义）
        await self._prepare_workspace_step()

        # 首段=implement（宿主 260930 删 create_plan）——相位默认值必须跟着首段走，
        # 否则「票面初始态」会指向一个不存在的段。
        phase = str(self.meta.get("stage") or self.STAGES[0].id)
        prev_ctx = ""
        run_only: List[str] = []          # 最近一轮跑面（空=全量）
        prev_red_names: List[str] = []    # 最近一轮红名（下一轮快反馈面来源）
        gate_rounds = 0                   # 本 attempt 内机器闸轮次（每跑一趟 +1）
        # 闸前主同步的跨轮反例守卫状态（与 dev-lane 同名同义；机制在共享 helper 里）
        conflict_rounds = 0               # 冲突消解轮次（上限 MAX_CONFLICT_ROUNDS）
        prev_conflict_files: List[str] = []   # 上一轮冲突文件签名（同批反复冲突守卫）

        while phase != "done":
            # 段间暂停门（t260908-01 通用骨架，本类只接线）：当前段（含在飞活动）
            # 自然跑完，主循环走到下一个段间门口时门把它停住。
            # t261004-32: pause accounting before the gate (rule 4: a paused ticket holds
            # nothing); after resume the slot gate below re-acquires.
            await self._concurrency_release_if_paused()
            await self._pause_gate()
            # t261004-32: slot gate before a stage (rule 1) - holding = atomic renewal,
            # not holding = queued acquire.
            # t261005-14: patched guard (same id, same reasoning as run entry).
            if workflow.patched(LIGHT_CONCURRENCY_GATE_PATCH_ID):
                await self._concurrency_gate()
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
                # UI 证据（**脚本条件段**，宿主 260930 第二轮裁定加回）：判据与截图全在
                # dev_lane._ui_evidence_step 里（同一 diff 源、同一 prepare_ui_evidence、
                # 同一软失败口径）——它只在 UI 票上写 results['ui_evidence']，本类据此做
                # 「段有没有跑」的票面记账（非 UI 票零活动零痕迹）。
                _ui_t0 = self._now_epoch()
                await self._ui_evidence_step()
                self._light_record_ui_evidence(_ui_t0)
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
                # 4.2 闸前主同步（宿主 260930 直修，根因级）：把 main 并进泳道一次。
                # **为什么必须**：闸在**泳道自己的 worktree** 里跑 `run_scenarios.py`，
                # 而泳道=开票那一刻从 main 建的快照——开票之后落进 main 的修复**不会**
                # 出现在泳道里（真票 t260930-09 实测：4 条 pool-exclude 假红的根因是
                # main 上才提交的夹具清理修，泳道那份夹具还是旧的），闸于是把「main 的
                # 旧账」判成 lane-only（本票的账）=让 agent 去修不在它身上的东西。
                # 同步一次 ⇒ **被验证树 = 被合并树**，归因才落回真正的责任人。
                # 机制=dev-lane 的 `_main_sync_before_gate`（抽出的共享 helper，唯一实现；
                # 已追平=is-ancestor 快路径幂等，每轮一次）；冲突 → 既有冲突消解回路
                # （rework 回 implement）/不可达 → 响亮转人——本道**不自造**打回。
                # 位置=跑闸相位入口、0-commit 前置检查之后（同步落下的 merge 提交会让
                # lane_commits +1，放前面=给「实现未落盘」放水）、跑闸之前（同轮直线
                # 衔接、必重跑不复用旧报告）——与 dev-lane 同一同位点纪律。
                # **判据零改动**：只改被验证的树，不改任何闸判据、不改归因口径、不放宽
                # 任何理由（红仍红、拦仍拦）。
                if workflow.patched(LIGHT_MAIN_SYNC_PATCH_ID):
                    _ms = await self._main_sync_before_gate(
                        conflict_rounds, prev_conflict_files,
                        texts=self.LIGHT_MAIN_SYNC_TEXTS)
                    conflict_rounds = int(_ms.get("conflict_rounds") or 0)
                    prev_conflict_files = list(_ms.get("prev_conflict_files") or [])
                    if _ms.get("phase"):
                        phase = str(_ms["phase"])
                    if _ms.get("stop"):
                        continue
                # 4.3 快反馈面（改动清单 ∪ 面计划；不可得=全量）
                run_only = await self._light_gate_plan(prev_red_names)
                # 4.3 跑闸（一轮）
                ir = await self._light_gate_round(run_only)
                if not ir.error:
                    self._handover_debt_clear()
                prev_red_names = self._tests_red_names(ir)
                _face_note = self._light_face_note(ir, run_only)
                self.results["run_integration_tests"] = self._light_gate_receipt(ir, gen0)
                # 261001 补：**机器闸每轮也进 gate_runs**（与 merge_check 那一处同形，键族与
                # dev_lane 的消费面一致）。此前轻道只有 merge_check 一处 append ⇒ 闸轮在这本账上
                # 是空的：泳道图/回执面看不到「这一轮闸跑了几条、绿不绿、窄面多少、豁免多少」。
                # 纯内存追加，**不新增任何命令**（无活动/定时器/信号）⇒ 重放安全，不需要版本门。
                _face = self._light_run_face(ir, run_only)
                self.gate_runs.append({
                    "stage": "run_integration_tests",
                    "label": "machine gate (verify_lane integ, round %d)" % gate_rounds,
                    "green": self._light_gate_verdict(ir) == "green",
                    "red_count": len(self._light_red_names(ir)),
                    "counts": {"ran": ir.ran, "passed": ir.passed, "failed": ir.failed,
                               "env_fail": ir.env_fail},
                    "exit_code": 0 if not ir.error else 1,
                    "narrowed": len(_face.get("narrowed") or []),
                    "excluded_pools": list(_face.get("excluded_pools") or []),
                    "known_red_skipped": len((_face.get("known_red") or {}).get("names") or []),
                    "error": str(ir.error or "")})
                # 段 evidence=计数 + 指针（宿主 260930：票面/段面不许内联逐条机器清单；
                # 逐条行仍在 results.run_integration_tests.evidence 与报告文件里）
                self._finish("run_integration_tests", by="run_integration_tests",
                             evidence=("run_integration_tests: %s ran / %s passed / "
                                       "%s failed / %s env-red (per-scenario rows: "
                                       "results.run_integration_tests.evidence + the lane "
                                       "report out/integration-report-*.json)"
                                       % (ir.ran, ir.passed, ir.failed, ir.env_fail)))
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
                    # 票面口径（宿主 260930）：轮次只给**计数**——收窄面 200+ 个名字不许内联
                    # 进票面（全量在闸回执与 blocked_detail.round 里）。两个注记分工：
                    #   round_desc = 票面用（轮次 + 跑面计数），
                    #   note       = 明细 evidence 用（round_desc + 分类尾注，诊断面）。
                    round_desc = ("gate round %d of this attempt" % gate_rounds
                                  + (" (fast-feedback round narrowed to %d entr%s)"
                                     % (len(run_only), "y" if len(run_only) == 1 else "ies")
                                     if run_only else " (full registry)"))
                    note = round_desc + self._light_gate_note_tail(ir)
                    # 归属前复验（t261002-02，KI-182；门=LIGHT_GATE_RECHECK_PATCH_ID）：
                    # 产品红转人之前，把闸拦名单（本票的账家族）在**同一棵泳道树**上
                    # 逐名单跑复验——全绿 ⇒ 降级 unattributable（不记本票的账），
                    # 未证全绿 ⇒ 维持。只改账本，不改放行口径：轮仍红仍 blocked 仍转人。
                    recheck = None
                    if (workflow.patched(LIGHT_GATE_RECHECK_PATCH_ID)
                            and reason_code == "light_gate_red"):
                        recheck = await self._light_gate_recheck(ir)
                        self.meta["gate_recheck"] = recheck
                    if getattr(self, "_detail_face_on", False):
                        self.meta["blocked_detail"] = self._light_gate_blocked_detail(
                            ir, run_only, reason_code, note, recheck=recheck)
                        self._touch()
                    await self._blocked("run_integration_tests",
                                        self._light_gate_blocked_text(ir, run_only,
                                                                      round_desc,
                                                                      recheck=recheck))
                    continue
                env_names, _ok = self._tests_env_red_names(ir)
                if env_names:
                    # 具名环境红不拦（供给面），但绝不静默：逐条进票面日志
                    self._log("named environment reds this round (not blocking): %s"
                              % ", ".join(env_names))
                # 判绿 ≠ 无视红：把「被记录而不阻断」的存量红逐名记账（绝不静默变绿）
                rec_face = self._light_recorded_pre_existing(ir)
                if rec_face:
                    self._log("green by protocol: %d red(s) are main-red-too and recorded, "
                              "not blocking (baseline %s; source: %s): %s"
                              % (rec_face["count"], rec_face["baseline_ref"],
                                 rec_face["source"], ", ".join(rec_face["names"])))
                    self._handoff("run_integration_tests",
                                  "recorded, not blocking (%d main-red-too): %s"
                                  % (rec_face["count"], ", ".join(rec_face["names"])))
                phase = "merge_check"
                continue

            # 4) merge_check（程序化四项；任一项红 → 转人）
            if phase == "merge_check":
                self._enter("merge_check")
                # t261002-10：重并 main 再重跑在检——retry_qc 在 merge_check 唤醒的路径
                # 由此到达；机制=dev-lane 同一条 `_main_sync_before_gate`（唯一实现，
                # 英文文案档；已追平=零动作幂等）。否则开票后落进 main 的修复到不了停
                # 在 merge_check 的票（t261001-20 实测）。本道无自动消解回路 ⇒ 重并冲突
                # 仍走 helper 的既有回路（rework 回 implement），不可达=响亮 blocked
                # （step_id 点名 merge_check），绝不静默跳过同步继续检查。判据零改动。
                if workflow.patched(MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID):
                    _ms = await self._main_sync_before_gate(
                        conflict_rounds, prev_conflict_files,
                        texts=self.LIGHT_MAIN_SYNC_TEXTS, step_id="merge_check")
                    conflict_rounds = int(_ms.get("conflict_rounds") or 0)
                    prev_conflict_files = list(_ms.get("prev_conflict_files") or [])
                    if _ms.get("phase"):
                        phase = str(_ms["phase"])
                    if _ms.get("stop"):
                        continue
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
                # t261004-32 (rule 3): the human gate eats the slot on purpose - the ledger
                # atomically flips to human-hold; post-signature continuation never
                # re-queues (no window).
                await self._concurrency_renew(CAUSE_HUMAN_GATE)
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
        # t261004-32 (rule 2): terminal = real slot release, queue head promoted. An
        # external kill (terminate/cancel) leaves no code path - zombie holders
        # are cleared by ticket.py op=concurrency reconcile, by name.
        await self._concurrency_release(CAUSE_TERMINATED)
        self._log("merge booked, ticket closed")
        self._mark("merge", "closed", "workflow finished")
        await self._ledger_flush()
        return self._snapshot()

    # ---------------------------------------------------------------- merge_check 阻断面
    #: UI 证据闸的 reason_code（真源=agent_activities merge_check 3.6 两处产出，同一常量
    #: 值；本类只**读**回执、不重判）。
    UI_EVIDENCE_RED = "ui_evidence_missing"

    def _light_merge_blocked_text(self, mc: Any, red: str) -> str:
        """merge_check 阻断文案（票面英文；**给人看的摘要**：结论 + 逐条红 + 决定 + 出路）。

        **UI 证据闸专段**（宿主 260930 两轮裁定：先「不产证据→另开全车道票」，后把
        ui_evidence 条件段加回，本条口径随之改写）：3.6 那条闸是**模板无关的全车道纪律**
        （reason_code=ui_evidence_missing，判据一个字不改）。轻道**现在能产证据**（条件段），
        所以这条红的含义是「本道能产证据，但这次没产生/没挂上」——专段说清这一点、给出
        **可行动**出路（rework(to_stage=implement) 让条件段重跑；截图已在泳道后 retry_qc
        重验闸），绝不静默、绝不假绿，也不再把「另开全车道票」当唯一出路。
        宿主 260930 同一条票面纪律：机器清单不内联——命中的 UI 文件最多列 3 个 + 「(+N)」，
        明细（哪一段失败/哪几条红）在 `blocked_detail` 与 `results.ui_evidence` 里。"""
        ui_reds = [c for c in (getattr(mc, "checks", None) or [])
                   if not c.get("green") and str(c.get("reason_code") or "") == self.UI_EVIDENCE_RED]
        lines = [
            "Blocked: the merge check is red — every red here goes to a human (no automatic "
            "send-back in this lane).",
            "What is red: %s%s." % (red or "no per-item detail in the receipt",
                                    " | error: %s" % mc.error if mc.error else ""),
        ]
        if ui_reds:
            files = []
            for c in ui_reds:
                for f in (c.get("files") or []):
                    if str(f) not in files:
                        files.append(str(f))
            lines.append(
                "UI-surface change detected (the UI evidence gate, reason_code=%s): this gate "
                "is a full-lane discipline that is template-independent (it applies to every "
                "lane; screenshots must land under .sandbar/screenshots/). This lane CAN "
                "produce that evidence — the ui_evidence conditional stage captures it — so "
                "this red means the capture did not run or its screenshots did not land (a "
                "blocked/aborted implement round, a stale lane, or a capture failure; "
                "results.ui_evidence says which). UI paths hit: %s."
                % (self.UI_EVIDENCE_RED, self._light_name_sample(files, limit=3)))
        lines.append("Outcome: (1) rework(to_stage=implement) — re-run the capture step after "
                     "the implementation lands; (2) retry_qc — re-run the check once the "
                     "screenshots (or the fix) are in the lane; (3) if neither clears it, the "
                     "receipt names the failing item — bring it to a human.")
        lines.append("Details: blocked_detail (reds / next_action / files) + the receipt "
                     "results.merge_check and results.ui_evidence.")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 判词小工具
    def _light_gate_note_tail(self, ir: Any) -> str:
        """blocked 轮注记尾（票面英文）：**只给计数与分类**——具名清单在回执/明细里
        （宿主 260930：票面不许内联机器清单）。"""
        names = self._tests_red_names(ir)
        env_names, _ok = self._tests_env_red_names(ir)
        bits = []
        if names:
            bits.append("%d product red(s)" % len(names))
        if env_names:
            bits.append("%d named env red(s)" % len(env_names))
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
