"""dev-lane — the single workflow for every developer-family ticket (t260831-02).

No "stage" abstraction: the workflow orchestrates activities directly
(step name == activity name):

    prepare_workspace (code, no agent)
      → create_plan (developer: produce the plan, no code changes)
        ⇄ review_plan (integration: writes review comments + pass/send-back;
          send-back → back to create_plan)
      → [parallel fork] implement (developer: code + unit tests) ∥ design_integration_tests
        (integration: designs the integration test suite from the plan, parallel to implement)
      → join (settle_lane commits both sides in one place) → ui_evidence (UI tickets:
        isolated-bench captures)
      → run_integration_tests (mechanical, zero LLM)
      → arbitrate (three verdicts: pass / tests-fault iterates the test suite /
        code-fault sends back to implement, capped at 5 rounds each)
      → acceptance (integration walks the feature from the user's view → acceptance report)
      → merge_check (four programmatic checks; merge dry-run conflict red → auto
        send back to implement, other reds blocked)
      → merge (human gate: sign-off → real merge → lane torn down only after the
        fail-closed archive succeeds)

Rework-loop context inheritance: returning to create_plan/implement injects the previous
round's review comments plus the last deliverable (previous_context). Per-loop caps live in
shared constants; over limit → blocked.

Determinism discipline same as base.py: this file is zero IO, zero randomness, zero
wall-clock (only workflow.now()), all side effects live in activities. The STAGES class
attribute is display/validation metadata only; orchestration logic is written inline in run().
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from base import (
        TICKET_UPDATE_RECEIPT_PATCH_ID,
        TicketCrossProjectMixin,
        TicketEventLedgerMixin,
        TicketPauseMixin,
        _update_echo,
    )
    import authz_gates
    import path_gates  # t260915-01 ②：闸拒绝结构化明细的构造/校形（纯函数零 IO）
    # t260915-05：模板拓扑导出面（纯数据零 IO；mock ④「引擎按模板导出 stage 图」，
    # 渲染器只认节点+边+kind——KI-019 线性近似泳道图的真拓扑承载）。
    import template_topology
    import shared   # t260925-12：gate_phase_timings 纯函数（零 IO，沙箱安全）
    # t260921-04：developer 段验证纪律文案（宿主令 260921「单测可跑、集成禁跑」）
    # ——FLOW_BRIEF 的 clause 由其 prompt_clause() 从 FORBIDDEN_ENTRIES 渲染，
    # 文案与执法匹配器同源（声明=执法，两侧必须同批改）。
    import integration_discipline
    from agent_activities import (
        INTEG_GUARD_SEC,  # t260924-05 KI-116：外层预算派生源（内层守卫 + 300）
        arbitrate,
        acceptance_walkthrough,
        archive_ticket,
        changed_files,
        merge,
        merge_check,
        prepare_conflict_resolution,
        prepare_human_gate,
        prepare_ui_evidence,
        prepare_workspace,
        reprobe_red_scenarios,
        run_integration_tests,
        surface_plan,
        settle_conflict_resolution,
        settle_lane,
        teardown_lane,
        ui_changed_paths,
        ui_evidence_decl,
        verify_review_gate,
    )
    from shared import (
        ENGINE_V2,
        ENGINE_VERSION_V2,
        ArchiveArgs,
        ArchiveResult,
        MAX_ACCEPTANCE_ROUNDS,
        MAX_CODE_FAULT_ROUNDS,
        MAX_REVIEW_ROUNDS,
        MAX_TESTS_EXEMPT_ROUNDS,
        MAX_TESTS_FAULT_ROUNDS,
        ReprobeRedArgs,
        ReprobeRedResult,
        blockers_known_red_adoption,
        evidence_ts_epoch,
        tests_exempt_cap_blocked_text,
        tests_fault_cap_audit_text,
        tests_round_step,
        tests_supply_assembly_error,
        tests_supply_assembly_note,
        TICKET_STATUSES,
        AUTH_ARBITRATION_VERDICT,
        AUTH_PROTECTED_PATH,
        AUTHZ_SIGNAL_GATE_MARKER,
        AgentStageArgs,
        ChangedFilesArgs,
        SurfacePlanArgs,
        ConflictPrepArgs,
        ConflictPrepResult,
        ConflictSettleArgs,
        ConflictSettleResult,
        GateResult,
        HOST_RULING_NOTE_INPUT_LIMIT,
        HostRulingRequest,
        HumanGatePrep,
        IntegrationRunArgs,
        IntegrationRunResult,
        MergeArgs,
        MergeCheckArgs,
        MergeCheckResult,
        MergeResult,
        ReworkRequest,
        ReviewGateArgs,
        ReviewGateResult,
        SettleLaneArgs,
        SettleLaneResult,
        Signature,
        Stage,
        StageResult,
        TicketInput,
        UiChangedPathsArgs,
        UiChangedPathsResult,
        UiEvidenceArgs,
        UiEvidenceDeclArgs,
        UiEvidenceDeclResult,
        UiEvidenceResult,
        WORKER_SHUTDOWN_RETRY_PATCH_ID,
        WorkspacePrepResult,
        UI_EVIDENCE_DIR,
        active_authorizations,
        agent_log_for,
        arbitrate_blocked_reason,
        arbitrate_settle_refusal,
        arbitration_cap_route,
        build_stage_prompt,
        build_workspace_prep,
        format_agent_stage_failure,
        integration_route,
        # t260925-21：角色报告英文纪律（单源常量，六段共用）
        ROLE_REPORT_ENGLISH_CLAUSE,
        is_ui_write_set,
        lane_workspace_gate_error,
        agent_env_failed_reason,
        env_note_for,
        # t260922-18：主同步冲突路由与证据定形（纯函数面，UT 直测）
        main_sync_conflict_route,
        main_sync_note,
        normalize_files_changed,
        normalize_handover_runs,
        parse_arbitration_summary,
        parse_authz_used,
        parse_review_plan_verdict,
        refresh_write_set,
        retry_once_on_worker_termination,
        review_gate_verdict,
        review_plan_route,
        result_file_for,
        sign_face_fingerprint,
        stage_workspace,
        targeted_rerun_plan,
    )

SHORT = timedelta(minutes=2)
MERGE_CHECK_TO = timedelta(minutes=20)   # merge_check includes the in-lane verify_lane
                                         # (tsc/smoke, can take minutes)
MERGE_TO = timedelta(minutes=5)
AGENT_TO = timedelta(hours=6)
# 260927 同 base.py：3 分钟静默误杀在干活的 agent（实案见 base.py 同注与 KI-138）→ 15 分钟。
HEARTBEAT_TO = timedelta(minutes=15)
# 机械集成测试条目的活动超时（配对不变量，t260913-01 仲裁修 + t260913-02 实测合流；
# t260924-05 KI-116 单源化）：本值自 agent_activities.INTEG_GUARD_SEC（=内层批次
# BATCH_TIMEOUT_SEC + 300 守卫）**派生**=守卫 + 300s 余量——内层结构化超时回报必可
# 达（Temporal 硬杀 + 3 次重试白烧的 260913 形态不再可能），且运维经
# SANDBAR_INTEG_BATCH_TIMEOUT_SEC 覆盖内层时本值自动同抬，「成对锁」是算式事实不是
# 人守纪律。缺省 3000+300+300=3600s=60min，与旧手写值一致（零行为漂移）。单测
# test_t260913_01_integ_budget_pair.py 与 test_t260924_05_ki116_budget.py 锁不等式组。
# **全集（含 engine+exclusive 重池）的长墙钟口径不在本值**——那走每日巡检的
# inspection_flow.SUITE_TO（恒全跑、不经池排除，同式派生自 INTEG_GUARD_SEC），
# 两条预算各守各的面。
INTEG_RUN_TO = timedelta(seconds=INTEG_GUARD_SEC + 300)
# t260917-09：探针活动 start_to_close——红项子集串行复跑（每条执行器侧 900s 帽），
# 预算沿用全量跑同档（子集恒 ≤ 全量；activity 内另有 wait_for 兜底 kill→wait 回收）。
REPROBE_TO = INTEG_RUN_TO
RETRY = RetryPolicy(maximum_attempts=3)  # infra failures only; business verdicts go via StageResult.status
# Boolean patch gates (same family as workflows.py's WORKER_RECONCILE_PATCH_ID): a
# parked old workflow replays down the old branch, so a new gate must not bump
# DevLaneWorkflow.PATCH_ID. Every *_PATCH_ID below follows the same rule and only
# carries a one-line pointer back to this first explanation.
# t260910-14 退役注记：旧「预跑下一单」布尔门（常量已删）随预跑建议段整链退役
# 删除，新代码不再查询该 marker。含预跑建议活动命令的旧 history 对本代码重放必
# 响亮红（Temporal 命令序非确定性，边界证明）——安全前提是
# cutover 前的 drain 核验（RUNNING 集只读回放零分歧）；违例票（merge 已签、suggestion
# 在飞）运维处置=在旧代码 worker 上跑完再重启（见工单 runbook）。
# t260831-02: parallel implement ∥ test design → mechanical tests → arbitration loop
# → acceptance walkthrough. Same-shaped boolean gate (see the first PATCH_ID note).
INTEG_LOOP_PATCH_ID = "dev-lane-integration-tests"
# t260828-09: UI acceptance — the new prepare_ui_evidence step + the merge_check UI
# evidence gate. Same-shaped boolean gate (see the first PATCH_ID note).
UI_EVIDENCE_PATCH_ID = "dev-lane-ui-evidence"
# t260904-13 KI-044 root fix: the UI-ticket test switches to a diff source (actual diff
# × UI prefix table, same source as merge_check 3.6). Deliberately not reusing
# UI_EVIDENCE_PATCH_ID: reusing it would make instances that already patched the
# evidence step but not the diff source take the new command on replay, and the old
# history has no matching event → broken. Same-shaped boolean gate (see the first note).
UI_DIFF_PATCH_ID = "dev-lane-ui-diff-v1"
# t260829-07: after the plan is finalized the write set refreshes to follow it (union);
# tickets starting from an empty write set get their guardrail this way.
# Same-shaped boolean gate (see the first PATCH_ID note).
REFRESH_WRITE_SET_PATCH_ID = "dev-lane-refresh-write-set"
KI061_WAKE_RESET_PATCH_ID = "dev-lane-ki061-wake-reset"
# KI-061 test switch (tests only): default off = fix enabled; set to "1" to skip the
# over-limit wake-reset guard (a selfcheck uses it to reproduce the stuck behavior).
# Read once at worker import, constant for the process; replay safety rests on the
# guard's False being a zero-command value.
SANDBAR_TEST_DISABLE_KI061 = os.environ.get("SANDBAR_TEST_DISABLE_KI061") == "1"
# t260904-18 KI-049 gate 2: an empty/malformed files_changed in the create_plan receipt
# → visible red + warning, write set left untouched (no more silent no-op).
# Same-shaped boolean gate (see the first PATCH_ID note).
WRITE_SET_FAULT_PATCH_ID = "dev-lane-write-set-fault"
# t260904-18 KI-050 gate 3: at lane start, preload verify.yaml's ui_evidence.dirs
# declaration into meta (disk read happens in an activity, the workflow only reads meta
# = replay safe); the review_gate patched branch judges UI tickets from it.
# Same-shaped boolean gate (see the first PATCH_ID note).
UI_EVIDENCE_DECL_PATCH_ID = "dev-lane-ui-evidence-decl"
# t260829-07: after integration_review reports ok, verify_review_gate re-checks it
# mechanically (0 lane commits / missing UI screenshots → forced send-back; git/path
# errors → skip). Same-shaped boolean gate (see the first PATCH_ID note).
REVIEW_GATE_PATCH_ID = "dev-lane-review-gate"
# KI-003 stage-transition yield point inside the mutation burst (consumed by
# workflow.patched inside _breathe): a ticket already running replays history without
# this marker → does not yield, replay stays deterministic.
BREATHE_PATCH_ID = "ki003-breathe-v1"
# t260902-02 M1-3: closing a ticket in three steps — merge only books the ledger →
# archive_ticket ships the data out → teardown_lane tears down the lane. Archive
# succeeding fail-closed is the precondition for tearing down the lane (the stage
# report must not be lost with it). Same-shaped boolean gate (see the first note).
ARCHIVE_PATCH_ID = "dev-lane-archive-ticket"
# 260929 宿主令直修（t260929-22 实案）：**闸测量面零变化 ⇒ 不重跑全套**。
# 病根：integration_route 判 tests-fault 只看「连续轮数 ≤ 5」，不看这一轮测到的东西与
# 上一轮是否逐字相同 ⇒ 票状态一字未变（代码自 gen4 未动、裁判连续四轮同一判词且每轮
# 都写「转人工判读」）却仍被路由回 run_integration_tests，每轮白烧一趟全套。判据=
# shared.gate_round_signature（闸拦名单/具名环境红/四计数/归属置信/基线 ref/逐条失败
# 明细，逐项相同才判停）；判停即转人审（_blocked_over_limit，retry_qc 可复活）。
# 同形布尔门：老在途票 history 无此标记 → patched()=False → 旧路径逐字不变。
INTEG_STALL_PATCH_ID = "t260929-integ-stall-guard"
# 260929 宿主令直修（t260929-22 实案）：**冲突消解交付失败 ⇒ 先把 merge 复位再转人工**。
# 病根：agent 交付被判失败时引擎既没提交也没 abort，把 UU 留在泳道 ⇒ 之后每一轮主同步都在
# 同一批文件上重新冲突（"同批文件反复冲突"成永久死锁，直到有人进泳道手动 git 收尾）。
# 修法：两条失败路径（agent 抛异常 / 交付非 ok）在 blocked 之前调 settle_conflict_resolution
# 的 abort 分支复位（git merge --abort，兜底 reset --merge HEAD），并复位同批计数器 ⇒
# 「永久死锁」降级为「干净重试一次」（上限 MAX_CONFLICT_ROUNDS 仍然封顶）。
# 同形布尔门：老在途票 history 无此标记 → patched()=False → 旧路径逐字不变。
MAIN_SYNC_RECOVERY_PATCH_ID = "t260929-main-sync-abort-on-failed-resolve"
# 260930（宿主令·nusuyou 需求说明第六条·KI-099 实案）：**未知相位绝不 raise**。
# 病根两段：① `_auto_rework` 的两条拒绝返回可能是**空串**（`str(meta["stage"] or fallback)`
# 而 meta['stage'] 为空、fallback 又非法）——旧路径（`_apply_rework`，patched 未激活的
# 在飞票）把它交回主循环；② 主循环尾对未知相位 `raise ValueError`（注释自称 unreachable），
# 而引擎自己的注释写着「主循环是裸 while True，抛出去=打断工作流实例」⇒ 票面 status=None、
# 快照/show/query 全查不到、**不可恢复**（nusuyou t260929-28 实案：照引擎拒收提示推荐的
# 别名 to_stage=acceptance 操作即踩雷）。
# 修法：相位兜底夹到可进入值（候选全非法 ⇒ arbitrate 人门）+ 主循环尾改 blocked（可查、
# 可唤醒、原因具名）。同形布尔门：老在途票 history 无此标记 → 旧路径逐字不变。
UNKNOWN_PHASE_BLOCK_PATCH_ID = "t260930-unknown-phase-block"
#: 相位兜底（260930）：目标与 fallback 都不可用时用的最后落点——取 arbitrate（人门段，
#: 最接近「停下让人看」的语义），绝不把空值/未知值交回主循环。
REWORK_PHASE_FALLBACK = "arbitrate"
#: **可打回相位集**（260930，与拒收提示同源）：PHASE_MAIN_CHAIN 里有几个值是主循环的
#: **编排内部相位**（并行叉的两条边与汇合点），从外部 rework 直接落进去只会得到半套上下文
#: （nusuyou 实案：提示里列了 acceptance，操作员照做就踩雷）。提示词表与合法性判定都取
#: 本集合——**词表里能打的，才是提示里能推的**。
REWORK_ADMISSIBLE_PHASES = frozenset({
    "create_plan", "review_plan", "implement", "run_integration_tests",
    "arbitrate", "acceptance", "merge_check", "merge"})

# t260903-02 speedup 3: a third review_plan verdict, "conditional pass" —
# verdict=conditional for cosmetic nits does not count as a send-back round; comments go
# straight to implement, skipping the plan redo + re-review; reject still uses the loop.
# Same-shaped boolean gate (see the first PATCH_ID note).
REVIEW_CONDITIONAL_PATCH_ID = "dev-lane-review-conditional-v1"
# t260903-02 speedup 2: arbitrate ∥ acceptance_walkthrough run as a parallel fork — both
# consume the same mechanical test result from different angles with no data dependency,
# so gathering saves a serial stretch. Same-shaped boolean gate (see the first note).
ARB_ACC_PARALLEL_PATCH_ID = "dev-lane-arb-acc-parallel-v1"
# t260915-01 详情数据面（三件事一个门）：①blocked 当前态字段解除时清空；②闸拒绝/
# merge_check 红的结构化明细（blocked_detail 泛化写点）；③timeline/handoff 的
# gen+phase 键与 snapshot.gens 新段。纪律：
# - 唯一求值点=_init()（run 起点，非唤醒穿越处）→ 无 KI-061 memo 毒化形态；在途
#   实例重放时首评落在重放段=False 永固化→旧分支逐字不变；新实例首评 live→True。
# - workflow.patched 禁止出现在 @query 定义的可读函数里（SDK _assert_not_read_only
#   硬约束：query handler 整段 read-only）——snapshot 等读 self._detail_face_on
#   缓存位（getattr 防御，UT 壳 object.__new__ 不跑 __init__）。
DETAIL_FACE_PATCH_ID = "dev-lane-detail-face-v1"
# t260916-19 ①：rework 打回出路的可达性（blocked 死结修复，实案=dengzhufpv
# t260916-11）。门纪律同 DETAIL_FACE_PATCH_ID：唯一求值点=_init()，使用点读
# self._rework_escape_on 缓存位（getattr 防御，UT 壳不跑 __init__）。
REWORK_ESCAPE_PATCH_ID = "dev-lane-rework-escape-v1"
# rework 打回目标的 STAGES-only 别名映射：blocked 文案的出路点名「打回目标段」，
# 但 design_integration_tests 是 STAGES 段 id 而非 PHASE_MAIN_CHAIN 值（词表有意
# 区别，见上方 PHASE_MAIN_CHAIN 注释）——操作员按文案发
# rework(to_stage=design_integration_tests) 被 _auto_rework 静默回落当前相位，
# join 已置位的边标记让重进只重跑 settle → 复判同一红 → 死结。
# 取舍：不往 PHASE_MAIN_CHAIN 加值（词表纪律 + 主循环尾「未知阶段」raise 防线），
# 在消费点把别名翻译成「落点相位 + 边重置」，复用既有 parallel_impl_design 编排
# （design 边真重跑、实现边结果保留）。键必须 ⊆ STAGES id（UT 源码锁）；值 =
# (落点相位, 边重置标记)。
REWORK_STAGE_ALIASES: Dict[str, Tuple[str, str]] = {
    "design_integration_tests": ("parallel_impl_design", "design"),
}
# selfcheck 两相法开关（selfcheck_ki061_wake_reset 的 SANDBAR_TEST_DISABLE_KI061
# 同款 pattern）：worker 沙箱在自己的 import 里读模块属性，monkeypatch 够不着——
# 唯一通道=环境变量（worker 构造时生效）。置 1 = 旧静默回落行为（复现 t260916-11
# 死结的相一）；不置 = 修后行为。
SANDBAR_TEST_DISABLE_REWORK_ESCAPE = bool(os.environ.get("SANDBAR_TEST_DISABLE_REWORK_ESCAPE"))
# t260916-28: a failed StageResult carrying a lane_dsh_* gate_refusal（spawn 前的
# 泳道 .dsh 自洽预检拒绝）必须在全部 agent 段消费点直落 blocked「agent 报失败」——
# arbitrate 的 verdict 循环、acceptance 打回循环与 parallel_impl_design 汇合边的
# 既有处理会把它误读成「缺 verdict= 标记」/「走查发现代码问题」/无声吞成假完成。
# Same-shaped boolean gate (see the first PATCH_ID note).
LANE_DSH_BLOCK_PATCH_ID = "dev-lane-lane-dsh-block-v1"
# t260917-04（紧急收口）：t260917-01 在仲裁路径新增的三处 workflow 侧变更（闸拒守门
# 方法的两处调用 + 进 run_integration_tests 段的格式轮次复位）未过 patched 门，落 main
# 后挂起中的旧 workflow 重放即 NondeterminismError（t260916-19/-21 实证）。按既有同构
# 布尔门先例补门：旧历史走旧串行分支（不复位、不调守门），新历史走新分支；不 bump
# 既有 PATCH_ID。
ARBITRATE_REFUSAL_PATCH_ID = "dev-lane-arb-refusal-v1"
# t260917-09：tests_rounds 上限定语义「连续」——计数转移/复位点全走 shared 纯函数
# tests_round_step（pass / code-fault / 非法 verdict / 人工接受判决即复位），tests-fault
# 但红项属环境面或抖动复跑全绿则该轮豁免不计（连续豁免独立上限）；环境面含两形态
# （gen11 打回补）：场景级 env_fail 与装配级供给装配失败（零跑+供给签名，留痕点名
# 供给面）。同构布尔门：旧历史
# （无本 marker）逐字旧行为（累计口径、无复位、无探针），在途票不追溯。
# 门不需要 KI-061 式 #seq 后缀：本门全部求值点都在主循环直线段（不在 wait_condition
# 唤醒路径上），不存在「重放期先评 False、活唤醒须翻 True」的路径；实现后若发现绕行
# 路径再按 _blocked_over_limit 同形补后缀。
TESTS_STREAK_PATCH_ID = "dev-lane-tests-streak-v1"
# KI-122①（260926 实案，宿主直修令）：仲裁判 tests-fault 而闸拦名单**逐条都在已知红名册**
# （integration/known-red-baseline.json）且非环境面/无启动级 error 时，**采纳判决**推进
# acceptance_walkthrough——不再每轮烧一趟全量（t260926-05 实况：5 轮 × ~2h、代码零变化）。
# 名册只读活动（read_known_red_roster）+ 纯判据 shared.blockers_known_red_adoption（单写者）。
# fail-closed（宿主 260926 护栏）：名册读不到/畸形/有一条非在册 → 照旧拦、照旧重跑，并把
# 名册路径与失败原因点名进票面。同构布尔门：旧历史（无本 marker）逐字旧行为（恒重跑），
# 在途票不追溯——门求值点在主循环直线段，无 KI-061 式唤醒重放路径，不需 #seq 后缀。
KI122_ADOPTION_PATCH_ID = "dev-lane-ki122-adoption-v1"
# KI-122① 260926 洞①裁定：采纳除「在册」外还要**机械证据戳 + 时间证据**（名册条目
# booked_at/booked_sha 早于本票开票基点），以及**活基线加保险**——两路**实跑**证据：
#   ① 本轮闸基线主跑逐名答案（failure_protocol.baseline_answers → 闸回执 baseline.answers）
#      ——**这条正是洞①「同名新红」的拦点**：用例被基线跑到且 pass（main 绿）而泳道红 ⇒
#      绿证据在案 ⇒ 不采纳（闸的红绿判据本身零改动，采纳面只是不再放行）；
#   ② 场景台账可信行（同指纹/同宽/祖先或相同/≤7 天）命中红/绿——覆盖「这一趟基线没跑到」
#      的 main 侧红证据（KI-122 实案的「基线覆盖差」形态靠它或「无答案」两路收场）。
# 两名单对该名都无数据 ⇒ 基线不可得：仅时间证据成立也可采纳，但票面必须点名「基线不可得，
# 仅时间证据」（宿主裁定原文口径）——「没跑到」永不等于「main 绿」（C1 口径），故不拦。
# 本常量只在老回执（无 live_baseline_* 键）时兜底作来源点名。
KI122_LIVE_BASELINE_SOURCE = (
    "none: the receipt carried no live-baseline evidence (gate baseline answers / ledger "
    "rows absent) — time evidence only")
# KI-122②：tests 连续计数的**段入口复位**必须停用——旧口径对「任何非 tests-fault 迭代来源
# 的重进」都复位（新实现轮/验收打回/**人工 rework**/retry_qc/blocked 脱困重进），于是两道上限
# （MAX_TESTS_FAULT_ROUNDS=5 / MAX_TESTS_EXEMPT_ROUNDS=5）可被外部处置反复击穿、永不触顶
# （t260925-05 实测：闸轮 7 仍未浮出「超限转人工」）。新口径：复位只认「本票红真的消失/清零」
# （仲裁 pass 收敛 / 人工显式接受判决）——外部处置穿插不再归零。与上一条同族但**独立布门**：
# 两者可分别回退（判据采纳失效不致连带把复位语义也退回去）。旧历史逐字旧行为，在途票不追溯。
KI122_STREAK_HOLD_PATCH_ID = "dev-lane-ki122-streak-hold-v1"
# t260923 D 两层复跑 + 爆炸半径（宿主直修令 260923，不开票）：中间轮定点复跑只作
# 快反馈（上一轮红项面，SANDBAR_SCENARIO_ONLY 点名），放行只认收口全量跑——pass
# 落在定点跑上时引擎机械补收口全量跑：零新增红（闸 blockers 空且无启动级 error）
# → pass 成立；有新增红 → 判决作废回仲裁重裁（全量面）。爆炸半径：写集命中共享
# 基座（引擎内核/worker/verify 闸/执行器与共享库）禁定点恒全跑；首轮恒全跑。
# 决策单写者=shared.targeted_rerun_plan。同构布尔门：旧历史（无本 marker）逐字
# 旧行为（恒全量跑），在途票不追溯。
TARGETED_RERUN_PATCH_ID = "dev-lane-targeted-rerun-v1"
# t260925-04：文件级爆炸半径——定点复跑判据从「票面写集粗前缀」换成「相对泳道基线
# （merge-base main branch）实际改动文件」（engine 票写集必命中共享前缀表 → 旧判据
# 恒禁定点，KI-118）。共享面判定复用同一张 _SHARED_BASE_PREFIXES 表（安全轨①）；
# 收口全量拦截（_closing_full_run）一字不动（安全轨②）；改动清单不可得（diff 失败/
# 空/畸形）→ fail-closed 恒全跑。同构布尔门：旧历史（无本 marker）走 v1 判据逐字
# 旧行为，在途票不追溯。
TARGETED_RERUN_FILE_RADIUS_PATCH_ID = "dev-lane-targeted-rerun-file-radius-v1"
# t260930-02（宿主裁 260930「先 B」）：面计划——快反馈面从「只有上轮红名」扩成
# 「本次改动面 ∪ 上轮红名」。旧判据的缺口是实打实的：定点轮只跑上轮红名，于是**这次
# 改动新碰坏了什么**在快反馈里看不见，只能等收口全量跑才发现（白烧一轮）。判定面
# 在 integration 侧单一真源（声明式 surface 映射 + 未归类即全量），本门只消费其回执：
# mode=full / 查询失败 / 空名单一律按**全量**跑（fail-closed）。**收口全量跑一字不动**
# （放行仍只认全量，见 _closing_full_run）——本门只改快反馈面，不改放行依据。
# 同构布尔门：旧历史（无本 marker）逐字旧行为，在途票不追溯。
SURFACE_PLAN_PATCH_ID = "dev-lane-surface-plan-v1"
# t260922-18：主同步门（宿主拍板「只在机械验证前并一次」）——run_integration_tests 相位
# 入口、0-commit 前置检查之后、跑闸之前，由 worker 活动（prepare_conflict_resolution，
# 唯一「并 ref 进泳道」实现）把 main 并进泳道一次；已追平=is-ancestor 快路径零动作幂等。
# 时点语义（供宿主复核留痕）：「一次」=每轮机械验证前一次，非全票仅一次——多轮 rework/
# 迭代的长周期票若只在首轮同步，验证基点又会漂（正是本票要治的「被验证树≠被合并树」，
# KI-082 同族）；快路径让重复同步零成本。门内新路径：未 patched 的在途实例逐字旧行为
# （回放安全）；门求值点在主循环直线段，无 KI-061 式唤醒重放路径，不需 #seq 后缀。
MAIN_SYNC_PATCH_ID = "dev-lane-main-sync-v1"
# prepare_ui_evidence activity timeout: must be **clearly larger** than the subprocess
# timeout inside the activity (agent_activities.UI_CAPTURE_TIMEOUT_SEC=240s), otherwise
# Temporal kills the activity first and the subprocess's own timeout recovery never runs.
# 260915 宿主令（180→420）：与截图上限同步放宽（实测整套 ~167s；余量还覆盖一次降级候选
# 尝试），自检守则 UI_EVIDENCE_TO >= UI_CAPTURE_TIMEOUT_SEC + 30 仍满足。
UI_EVIDENCE_TO = timedelta(seconds=420)

# MAX_REVIEW_ROUNDS moved to shared.py (t260903-02: the review_plan_route pure function
# must consume the same value); injected via the import below, no longer defined here.
MAX_CONFLICT_ROUNDS = 3  # conflict auto-resolution round cap (t260826-01); over limit or
                         # the same file set conflicting twice → blocked, handed to a human

# t260901-04: the legal vocabulary for rework target/fallback (consumed by the
# _auto_rework validation, spelled out explicitly). Note: this vocabulary intentionally
# differs from the STAGES id vocabulary (acceptance etc. are phase values but not
# STAGES ids) — it serves rework validation only; do not derive it from STAGES or reuse
# it elsewhere.
PHASE_MAIN_CHAIN = frozenset({
    "create_plan", "review_plan", "parallel_impl_design", "implement",
    "integ_join", "integration_review", "run_integration_tests", "arbitrate",
    "arb_acc_parallel", "acceptance", "merge_check", "merge", "done"})
# phase main-chain step → role mapping (used by _auto_rework to record meta['role']).
# Deliberately not via _step(target): the three values in the vocabulary that are not
# STAGES ids would make _step raise "unknown step" and wedge the workflow (t260901-04).
# Role assignment: steps with the same name as STAGES copy it; parallel_impl_design /
# integ_join are the implement-side aggregation/join commits → developer; acceptance →
# integration.
PHASE_MAIN_ROLES: Dict[str, str] = {
    "create_plan": "developer", "review_plan": "integration",
    "parallel_impl_design": "developer", "implement": "developer",
    "integ_join": "developer", "integration_review": "integration",
    "run_integration_tests": "integration", "arbitrate": "integration",
    "arb_acc_parallel": "integration",
    "acceptance": "integration", "merge_check": "integration",
    "merge": "integration", "done": "integration"}


def set_parallel_stages(meta: Dict[str, Any], stages: List[str],
                        phase: str = "") -> None:
    """While a parallel fork is live, record the active edges into
    meta['parallel_stages'] (KI-024).

    Contract (fixed by the ticket body + review_plan C4/C5 rulings; do not improvise):
      - This list is the source of truth for the dual display; the single meta['stage']
        field stays untouched (workbench backward compatibility).
      - Sanitizing: only string ids inside the STAGES id vocabulary are accepted;
        malformed entries dropped, order-preserving dedupe.
      - Empty list → remove the key rather than store an empty list: the UI treats
        "key missing ∨ empty list" alike as "no parallelism" and falls back to the
        existing timeline heuristics. Leaving a parallel period must clear explicitly,
        so a stale list cannot pin finished edges on ▶ forever.
      - Pure in-memory function, replay safe; STAGES is resolved at call time (this
        function is defined before the class).
      - t260915-01 ③ phase 实参三态（review_plan C5 写死）：phase 非空且 stages 非空
        → 同时记 meta['parallel_phase']（分叉相位名，如 arb_acc_parallel——timeline
        条目的 phase 键读它）；stages 清空（离场）→ parallel_stages 与 parallel_phase
        两键同删；phase 缺省 ''且 stages 非空（摘失败边调用）→ parallel_phase 保持
        现值不动（摘边不得抹掉相位）。门纪律：两个分叉调用点只在 self._detail_face_on
        时传 phase——在途实例重放零新键（旧分支逐字不变）。
    """
    valid_ids = {s.id for s in DevLaneWorkflow.STAGES}
    cleaned: List[str] = []
    for s in (stages if isinstance(stages, list) else []):
        if isinstance(s, str) and s in valid_ids and s not in cleaned:
            cleaned.append(s)
    if cleaned:
        meta["parallel_stages"] = cleaned
        if phase:
            meta["parallel_phase"] = phase
    else:
        meta.pop("parallel_stages", None)
        meta.pop("parallel_phase", None)

# Per-step assignment contract supplements (appended after build_stage_prompt's generic
# instructions). Verdict convention for the two review steps: status ok=pass /
# failed=send-back, review comments go into summary.
FLOW_BRIEF = {
    "create_plan": (
        "本步只出方案，不动代码（git 工作区应保持干净）。方案要落到：改哪些文件、"
        "分几步、每步怎么验证。把方案全文写进结果文件 summary/evidence。"
        "备选分解（宿主令 20260903 试行）：方案须另列 1-2 个备选切法"
        "（步骤划分/排序/分层之异，非功能取舍）并各一句说明为何不选——"
        "逼分解成为想过的选择而非习惯模子；review_plan 可据此追问切法合理性。"
        + ROLE_REPORT_ENGLISH_CLAUSE
        + integration_discipline.prompt_clause()),
    "review_plan": (
        "你是 reviewer。审读上一步的方案（见上下文），逐条写 review comments。三态结论"
        "（summary **必须以 verdict= 开头标明**，如「verdict=pass …」；结果文件 status 与"
        " verdict 矛盾时机器以 status=failed 为准恒判打回）："
        "verdict=pass 通过 → status=ok；"
        "verdict=conditional 附条件放行 → status=ok：仅限**轻微瑕疵**（表述级、不影响方案"
        "结构/写集边界/验收口径的修改意见），意见在 report 里分条写，会作为附条件直通 "
        "implement 段执行，不回 create_plan 重做、不复审；"
        "verdict=reject 打回 → status=failed：结构性问题（流程错、写集越界、验收口径缺失），"
        "comments 在 report 分条写（打回后 developer 带着你的 comments 重做方案）。"
        "除三态外不许发明其它结论。"
        "执行钩子：方案声称照搬/参考既有实现 → 必须附该实现的故障模式取舍清单，缺→打回；"
        "方案涉及消费外部输入 → 验收必须含畸形输入用例，缺→打回。"
        + ROLE_REPORT_ENGLISH_CLAUSE),
    "implement": (
        "按已通过方案实现。硬性纪律：写集白名单内；**不要自己 git commit**"
        "（沙箱写不了真 .git，你交付结果文件后 worker 会确定性代落盘）；"
        "相关 smoke/自测跑绿，证据写进 evidence。"
        "本票改动以 UT 交付行为断言（落项目声明的测试目录），verify code 道跑绿。"
        "UI 票（写集命中 UI 口径）交付证据须含改动前后截图"
        "（.sandbar/screenshots/，ui-check/capture.mjs 产出）或说明为何无视觉差异。"
        "环境不可用契约（t260917-08）：bash 沙箱不可用（sandbox_apply: Operation not "
        "permitted / no sandbox backend is usable）时**文件面产物照常交付**，结果文件加 "
        '"env_fail":true 与 "env_reason"（日志原文摘录），没能亲自跑的验证逐条写 '
        '"handover_runs":[{"name":"…","cmd":"…"}]（≤20 条，cmd 为泳道根可独立执行）——'
        "验证由集测段 worker 执行面代跑，票不停摆；不许谎报 status=failed（非实现缺位），"
        "也不许用 status=ok 掩盖「验证未运行」。"
        + ROLE_REPORT_ENGLISH_CLAUSE
        + integration_discipline.prompt_clause()),
    "design_integration_tests": (
        # t260902-12（票）：用例设计依据第三项=组件对外契约与行为规格（以修订二为准）
        "你是 integration，负责从**用户使用场景**出发为本次工单设计集成测试集（灰盒视角："
        "developer 的对抗面而非复核面，不逐行审代码细节）。要求：①读方案，列出用户可感知的行为变化与故障面"
        "（并发、边界、异常输入、资源回收）；②场景文件命名铁律：sc_<slug>.py/.mjs——"
        "场景清单的登记方式与命名约定按项目测试声明（仓库根 verify.yaml integration 道）"
        "（本项目 sc_ 前缀铁律+秒级 lint 见声明内说明；多项目各随其便）；"
        "场景落 integration/ 票目录（cwd=仓库根，可直接执行）；"
        "③结果文件 status=ok + summary 列测试清单；测试集内容不写进结果文件"
        "（不向 developer 引导）。"
        "④用例设计依据三依据穷尽：工单原始 user_request 与用户验收口径 → "
        "项目已知问题清单（KI）中本票改动触及的未闭合项 → 组件对外契约与行为规格"
        "（锚定承诺而非实现，实现细节不作依据）；设计用例前核对项目声明的全局用例清单防 "
        "intent 级重复，已知问题清单（KI）与用例清单的实际路径见项目测试声明。"
        "⑤零场景结论合法（宿主令 20260903，实案=t260903-05 纯盘点文档票）："
        "本票无可执行面（纯文档/盘点/纪要）时，合格产出=「零新增场景」论证"
        "（写清为什么没有可测行为）+ 文档内嵌自校验命令（如 grep 重演步骤，读者可独立复核）；"
        "禁止为快照型文档（清单/盘点/迁移计划）造回归 pin——仓库每票必变，此类断言必 rot；"
        "仅当文档被机器消费（声明被解析器读取、字段表被对账）才值得契约守卫。"
        "发现新缺陷在结果文件上报（描述+定位+复现），不直接写已知问题清单——登记由 integration 岗位统一做。"
        "三态契约（t260904-12，闸内无 SKIP）：场景只有 PASS/FAIL/ENV_FAIL——环境缺失一律 "
        "ENV_FAIL（exit 2）不写 SKIP（exit 0）；N/A 仅给系统状态条件子用例，全部子用例 N/A=场景红。"
        "落盘后先跑 python3 integration/lint_tests.py（秒级静态检查：语法/import/清单/intent），"
        "红则先修再交结果文件——不要把静态错误拖到套件执行时才暴露。"
        "结果文件 status=failed 仅限你无法产出测试集的极端情况。"
        + ROLE_REPORT_ENGLISH_CLAUSE),
    "arbitrate": (
        "你是 integration 仲裁。机械集成测试已跑完，结果见上下文。三态判定（summary "
        "**必须以 verdict= 开头标明**，如「verdict=code-fault …」）："
        "verdict=pass 通过 → 进入验收（含**零新增红**判据，B 口径 260923：闸 blockers "
        "为空=红面全是基线既有欠账/外部环境记录面，属**已知红**——判 pass 并把红名写进"
        "报告备注，**禁止以「重跑一轮等它绿」当收敛手段**：重跑已知红不会绿、只会烧"
        "轮次到超限转人工；只有本票新增红（blockers 非空）且落在测试面内才 tests-fault，"
        "实现面新增红才 code-fault）；"
        "环境红具名口径（B2，宿主 260929 令）：回执的 **env_red 是环境红的具名通道**"
        "（来源=闸的权威判决面 not-checked × external），它=供给面/共享台面的红（缺环境、"
        "台跑不起来），**不是 tests-fault 的迭代理由**——修复动作是补供给声明/补环境，"
        "不是回工重跑整轮（重跑环境红不会绿，只会烧 ~30 分钟一轮并推票到假封）。"
        "本票面绿（无本票新增产品红）且余红均为 env_red 具名环境红/在册既有红时："
        "**判 pass**，并把 env_red 里的红名逐条写进报告备注（引擎侧对具名环境红轮不再"
        "重跑整轮，直接进验收——你判 tests-fault 只会被当环境面/已知红面收口）。"
        "只有**本票新增产品红**才进迭代：红项落在测试面内 → tests-fault（测试面）；"
        "实现面新增红 → code-fault（实现面）。**禁止以重跑等环境红变绿当收敛手段**"
        "（env_red 不是自报 exit=2、也不从 ENV_FAIL 文本行反推——只认闸回执的具名通道）。"
        "env_fail>0 而 env_red 名单为空/缺键（老回执形态）=环境面**未具名**：按保守侧"
        "处置（不得凭「环境面」口头放行，回执无具名即无豁免）。"
        "verdict=tests-fault 测试集自身问题（环境/前提/断言错）→ 红项落在测试面内"
        "（tests/ 目录、test_*.py、sc_* 场景脚本、场景登记表、本票场景目录）才**你直接迭代修正**"
        "（改动随本步落盘），summary 写清改了什么、为什么是测试的问题；红项属共享资产/受保护真源"
        "（共享电池、场景库等仓库级受保护资产）或其它本段不允许面 → **不要改它**：如实出 "
        "verdict=tests-fault 并在 summary 点名红项路径，交引擎按轮次上限转人工判读"
        "（越权改动会被路径闸拒绝落盘——t260916-19/-21 病灶；诚实阻塞到转人工是合法归宿，"
        "不是让你换法子再写）；"
        "verdict=code-fault 实现问题 → report 写**集成测试报告**（失败场景、复现要点、"
        "期望 vs 实际），打回 developer 修改。除三态外不许发明其它结论。"
        "两层复跑口径（D，260923）：中间轮可能是定点复跑面（回执 only_names 点名本轮"
        "在册面），只作快反馈——未点名场景不在本轮在册、不是条目丢失，不得据缺失判红；"
        "放行只认收口全量跑（你判 pass 后引擎机械补全量跑复核零新增红，有新增红则判决"
        "作废回你重裁）。"
        "归因纪律（t260904-12 三态判据）：先固定问句「环境面还是产品面？」——"
        "环境红（回执 **env_red 具名名单**里的名字；判据面=闸的 not-checked × external，"
        "**只认具名通道、绝不采信场景自报 exit=2 / ENV_FAIL 文本行**）归供给面："
        "修复=补测试环境/供给声明（乙段 verify.yaml supply），绝不把环境红记成代码问题、"
        "也绝不把「重跑整轮」当处置（重跑不补供给）。**产品红（FAIL exit 1 / 闸拦）归产品**；"
        "本票新增产品红才进两态（tests-fault / code-fault），具名环境红与在册既有红不进迭代面。"
        "乙段（verify_lane env_fail 计数）落地前环境红以 err/退出码形态出现，按输出尾段"
        "归因。窗口期（供给声明未落地）UI 票过闸只走 break-glass 人显式签字留痕，"
        "不许以「环境面」口头豁免放行。"
        "发现新故障模式在结果文件上报（描述+定位+复现），不直接写已知问题清单——登记由 integration 岗位统一做。"
        "打回轮回审查令：若本轮回打中单测（UT）或集成测试文件发生任何变更（含你自己的 tests-fault 迭代），"
        "逐条核对变更是否弱化了断言/收窄了覆盖面——测试改动必须让契约更准而非让红灯变绿，"
        "summary 单列「测试资产变更审查」小节列出每处测试变更与理由。"
        "交接与环境受限段契约（t260917-08）：details 内 name=handover:* 是前序 agent 段"
        "沙箱受限期间交接、由 worker 执行面代跑的验证命令（单列计数，不进主口径）——"
        "失败命令=验证未过：按既有三态归因处置（rework），不得因命令单列计数而放行；"
        "上下文存在环境受限段（env_fail/环境注记）=验证未闭环，verdict 必须处置，"
        "不得当已验证。"
        "取证纪律（t260924-09）：集成闸回执即全量证据——复现缺陷的口径：①复现"
        "单条红=定点复跑 python3 integration/run_scenarios.py --only <场景名>；"
        "②复现整套红才允许全套，且必须与闸同口径 --exclude-pools engine,exclusive"
        "（闸排除的 engine 池由 pytest 覆盖；确须含 engine 池时报告写明理由）；"
        "③禁止把全量当复现工具：同一段内非定点全套只许 1 趟，机械护栏执法"
        "（裸全量/口径漂移/第二趟全套=段结果红+票面点名 full_suite_violations）；"
        "④走查/仲裁报告涉复现时必含「对照证据」小节：同一场景名在闸回执与定点"
        "复跑回执两列耗时，缺数据面如实标注并给移交命令，不得以跨场景数字顶替。"
        "结果台账契约（t260922-12）：details 内 name=__ledger__ 是闸的结果台账回执——"
        "命中红（既有欠账·同红）不拦是诚实计数不是放行；命中绿而泳道红=真回归仍拦；"
        "歧义/无记录/指纹不等/过期/宽度不等=闸已回退实跑点名。台账不产生任何免签"
        "语义，三态判定仍按本段全部分工执行。"
        + ROLE_REPORT_ENGLISH_CLAUSE),
    "acceptance_walkthrough": (
        "你是 integration 验收。本步与仲裁（arbitrate）**并行**执行：机械集成测试结果已随"
        "上下文注入（与仲裁同源），走查以**用户视角**独立进行，不预设「测试已全部通过」——"
        "你只管从用户场景走查并写验收报告（供人类最终合并审查）。重点审查项：对照打回轮次，若期间 UT/集成测试文件有变更，逐处核实变更意图（契约精确化 vs 绿灯捷径），在报告设「测试资产变更审查」小节；发现可疑弱化即 status=failed。走查实证（隔离台截图/DOM 断言输出）已注入上下文：逐场景"
        "给出结论与证据引用；发现代码问题 → status=failed + report 写明问题（会打回 "
        "developer）；一切正常 → status=ok + report=验收报告全文。报告面向不熟悉本工单的人。"
        "（仲裁若判 tests-fault/code-fault，本轮走查结果会作废、回路收敛后重新走查——不必"
        "在报告里替仲裁下结论。）"
        "取证纪律（t260924-09）：集成闸回执即全量证据——复现缺陷的口径：①复现"
        "单条红=定点复跑 python3 integration/run_scenarios.py --only <场景名>；"
        "②复现整套红才允许全套，且必须与闸同口径 --exclude-pools engine,exclusive"
        "（闸排除的 engine 池由 pytest 覆盖；确须含 engine 池时报告写明理由）；"
        "③禁止把全量当复现工具：同一段内非定点全套只许 1 趟，机械护栏执法"
        "（裸全量/口径漂移/第二趟全套=段结果红+票面点名 full_suite_violations）；"
        "④验收报告必含「对照证据」小节：同一场景名在闸回执与定点复跑回执两列"
        "耗时，缺数据面如实标注并给移交命令，不得以跨场景数字顶替。"
        + ROLE_REPORT_ENGLISH_CLAUSE),
}


# Legacy chain step definition (reachable only by replaying existing workflows —
# t260831-02 retired the integration_review step, but replaying its history still needs
# _step to resolve it, otherwise NonDeterminism fails the workflow task forever. New
# executions never pass through it.)
_LEGACY_STEPS: Dict[str, Stage] = {
    "integration_review": Stage(
        id="integration_review", name="集成审读", role="integration",
        next="merge_check", parts=("agent",),
        desc="（已退役——仅存量 workflow 重放可达；新链把关=集成测试+仲裁+验收走查）"),
}


# t260925-17（KI-120）：并行叉 join-settle 路径闸拒 blocked 的「醒后真重跑」复位门。
# 实案 t260925-05：arb_acc_parallel 两边 gather 完成 → join settle 命 path_gate_reason=
# 落 blocked，但 arb_done/arb_res 簿记不复位 → authorize+retry_qc 唤醒后 pend 恒空
# （两边仍记「已完成」），叉不重入、agent 不重生，settle 只重跑一遍后拿滞留的陈旧
# arb_res 走判决尾段，票定格「blocked + 空 reason」（_blocked 醒后清点①所致）零活动。
# 复位只翻被闸挡住的仲裁边（walkthrough 边结果昂贵且与闸无关，保留——同格式纠正
# 分支的取舍口径）；同构布尔门（旧 history 无本 marker 走旧分支不追溯，在途票重放
# 安全，t260917-04 先例）。本门全部求值点在主循环直线段（_blocked 之前），不在
# wait_condition 唤醒路径上，无 KI-061 式「重放期先评 False」问题。
KI120_FORK_GATE_WAKE_RESET_PATCH_ID = "dev-lane-fork-gate-wake-reset-v1"


def _prompt_next_no(prompt: str) -> int:
    """Largest top-level item number in the prompt, plus 1 (where FLOW_BRIEF's
    supplement gets appended).

    Top-level entries look like "N. " at column 0; the injected previous_context (the
    raw send-back comments) is indented 3 spaces per line, so it never matches. After
    previous_context is injected the generic instructions can reach item 9, so a
    hardcoded 9 would collide."""
    nums = [int(m) for m in re.findall(r"^(\d+)\.", prompt, re.M)]
    return (max(nums) + 1) if nums else 1


@workflow.defn
class DevLaneWorkflow(TicketPauseMixin, TicketCrossProjectMixin,
                      TicketEventLedgerMixin):
    """The single workflow for developer-family tickets (dev-lane). Direct activity
    orchestration, no stage machine.

    STAGES is metadata only (yaml snapshot / create-time derivation / workbench
    display); the snapshot keys match TicketWorkflowBase's shape
    (stage/stage_state/checks/handoffs/timeline…), so the workbench and ticket.py
    consume it without knowing the difference.

    段间暂停（t260908-01）：零私有逻辑——pause/resume 信号、段间门、paused 二态
    快照全部由 TicketPauseMixin（base 通用层）承载；本类只做接线（继承 +
    主相循环顶部一个 _pause_gate() 调用 + snapshot 并 _pause_snapshot()）。"""

    PATCH_ID = "dev-lane-v1"
    TEMPLATE_ID = "dev-lane"
    TEMPLATE_NAME = "开发泳道"
    # KI-124（t260925-23）：段路径闸总开关改为模板类声明（client.py ticket-start 读
    # 类属性，不再硬编码模板名）。dev-lane 恒 True=现行为不变（闸今天就是开的）；段×
    # 允许面规则仍走内建 STAGE_PATH_RULES（本类不声明 PATH_GATE_RULES）。
    PATH_GATE = True
    TEMPLATE_LANE = "worktree"
    TEMPLATE_WORKSPACE_DIR = False
    TEMPLATE_DESC = ("开发泳道（developer 系唯一流程）：prepare_workspace→create_plan⇄review_plan"
                     "→implement∥design_integration_tests→汇合（ui_evidence/UI 票）"
                     "→run_integration_tests（验证前主同步 main）→arbitrate→acceptance_walkthrough"
                     "→merge_check（程序化）→merge（人审）")
    #: 段补述来源（宿主令 260930（light-lane，直修无票） 钩子，**纯加法**）：_run_agent_step 读本属性取
    #: 段补述文案。dev-lane 侧值=模块级 FLOW_BRIEF（逐字不变，行为零变化）；轻道
    #: （light_lane.LightLaneWorkflow）覆写为自己的补述表（正文 import 复用同一批条文，
    #: 只在前缀加一段轻道契约说明）。
    FLOW_BRIEF_SET: Dict[str, str] = FLOW_BRIEF
    # Display/derivation metadata (the real orchestration lives in run(); same order
    # as run). parts = declaration of the executor mix (agent🤖/script⚙️/human👤,
    # static, feeds workbench badges): implement = agent + worker settle-on-behalf +
    # self-test/verify script gates; merge = human sign-off + merge booking + lane
    # cleanup script; merge_check = purely programmatic. Engine plumbing (result-file
    # polling etc.) is not counted.
    STAGES = (
        Stage(id="create_plan", name="做方案", role="developer", next="review_plan",
              desc="读需求出实现方案：改动文件清单、步骤、验收口径；不动代码",
              parts=("agent",),
              acceptance=("方案落结果文件（改动清单+步骤+验收口径）",)),
        Stage(id="review_plan", name="审方案", role="integration", next="implement",
              desc="审读方案写 review comments：通过 ok / 打回 failed+修改意见",
              parts=("agent",),
              acceptance=("review comments 落结果文件", "通过/打回结论明确")),
        # implement and design_integration_tests really run in parallel (asyncio.gather,
        # see run()'s parallel_impl_design branch; the display chain lines them up
        # adjacently as a linear approximation, the join point commits for both).
        # t260915-05：真拓扑的导出面=template_topology（节点+边+并行组+人门，含本处
        # 与 arb_acc_parallel 两分叉）——泳道图消费导出面，不再吃线性近似（KI-019）。
        Stage(id="implement", name="实现", role="developer", next="design_integration_tests",
              desc="按方案开发：写集白名单内；commit 由 worker 代落盘（agent 沙箱写不了真 .git）；"
                   "与 design_integration_tests 并行分叉，两边齐活后汇合统一落盘",
              parts=("agent", "script"),
              acceptance=("写集白名单内", "改动落写集文件（worker 代落盘 commit）", "相关 smoke/自测全绿")),
        # ---- ticket t260831-02: parallel implement ∥ test design → mechanical tests
        #      → arbitration loop → acceptance walkthrough ----
        Stage(id="design_integration_tests", name="设计集成测试", role="integration", next="ui_evidence",
              desc="按方案评估测试需求：从用户场景出发设计/迭代集成测试集（仓库 integration/ 目录，"
                   "并登记进场景清单），覆盖并发与边界故障面；与 implement 并行，测试集不向 developer 引导",
              parts=("agent",),
              acceptance=("测试集落 integration/ 目录（并登记进场景清单）", "场景覆盖与故障面清单落结果文件")),
        # t260828-09: display metadata only (UI tickets only, run inline in run()
        # between the join commit and the mechanical tests; non-UI tickets skip this
        # step; missing screenshots are caught by the merge_check evidence gate).
        Stage(id="ui_evidence", name="UI截图证据", role="developer", next="run_integration_tests",
              desc="UI 票实现落盘后 worker 代跑 ui-check/capture-lane.mjs 隔离台，截控制台"
                   "各视图落 .sandbar/screenshots/（软失败不拦主链，闸兜底）",
              parts=("script",),
              acceptance=("UI 票 .sandbar/screenshots/ 有截图（merge_check 证据闸机械查）",)),
        Stage(id="run_integration_tests", name="跑集成测试", role="integration", next="arbitrate", agent=False,
              desc="程序化（无 agent）：前置检查泳道落盘（0 commit = 实现未落盘 → blocked）；"
                   "跑闸前主同步 main 一次（t260922-18：worker 代并，已追平幂等；冲突走既有消解"
                   "回路回 implement；不可达响亮 blocked 转人工）；然后跑项目声明场景执行器 "
                   "integration/run_scenarios.py（cwd=泳道），结果 JSON 交仲裁判定",
              parts=("script",),
              acceptance=("场景执行器跑完全部场景并产出结果",)),
        Stage(id="arbitrate", name="仲裁", role="integration", next="acceptance_walkthrough",
              desc="读机械测试结果三态判定：pass 通过 / tests-fault 测试集问题（自行迭代后重跑，"
                   "上限 %d 轮）/ code-fault 代码问题（集成测试报告打回 implement，上限 %d 轮）"
                   % (MAX_TESTS_FAULT_ROUNDS, MAX_CODE_FAULT_ROUNDS),
              parts=("agent", "script"),
              acceptance=("三态 verdict 明确（pass/tests-fault/code-fault）", "code-fault 附集成测试报告")),
        Stage(id="acceptance_walkthrough", name="验收走查", role="integration", next="merge_check",
              desc="测试通过后 integration 以用户视角走查新功能、写验收报告（供人审门查阅）；"
                   "走查实证由 worker 前置产出（capture-lane 隔离台实拍 + DOM 断言）；"
                   "走查发现代码问题 → 打回 implement（上限 %d 轮）；"
                   "收口两问（沉淀一问+反向同步闸）随走查顺路带出——不答不阻塞（doc-lifecycle 票②，"
                   "文案=shared.STAGE_ACCEPTANCE_EXTRA，登记=agent_activities.apply_doc_gate）"
                   % MAX_ACCEPTANCE_ROUNDS,
              parts=("agent", "script"),
              acceptance=("验收报告落结果文件（逐场景结论）",
                          "沉淀一问有预填建议或显式无可沉淀（未答留痕不阻塞）",
                          "矛盾核对结论落回执（有矛盾则债条目已登记 pending-doc-sync）")),
        Stage(id="merge_check", name="合并检查", role="integration", next="merge", agent=False,
              desc="程序化检查（无 agent）：泳道有 commit、工作区干净、泳道内 verify_lane 绿、merge-tree 无冲突；"
                   "仅预演冲突红 → 自动打回 implement 消解（上限 %d 轮），其它红灯 blocked 等人" % MAX_CONFLICT_ROUNDS,
              parts=("script",),
              acceptance=("泳道分支有 commit", "工作区干净（无未提交改动）",
                          "泳道内 verify_lane code 绿灯",
                          # 260927（宿主实报「段的说明写会自动消解，实测冲突重驱两次仍红」）：
                          # 自动消解只对**预演冲突这一类红**生效（mc.conflict），其它红（脏工作区/
                          # verify_lane 红/差值闸…）一律 blocked 等人——原文案把两类混写成一句，
                          # 让人以为「任何冲突都会自动消解」。文案按类分开点名。
                          "merge 预演无冲突（**仅**预演冲突这一类红自动打回 implement 消解，"
                          "上限 %d 轮；脏工作区/verify_lane 红等其它红 blocked 等人）"
                          % MAX_CONFLICT_ROUNDS)),
        Stage(id="merge", name="合并（人审）", role="integration", next="", exit="human",
              desc="人审签字后执行 merge：合 main + 泳道清理（拆 worktree、删分支）；"
                   "合并失败（如签字期间他道先进 main 冲突）自动打回 merge_check 重验",
              parts=("human", "script"),
              acceptance=("人审签字", "merge 落账 + 泳道清理")),
        # t260910-14 退役注记：旧「预跑下一单」Stage 整链退役（宿主 260910 拍板）。
        # 老票 results 里残留的该段键由展示/推进面按未知键自然忽略（STAGES 不再含
        # 该 id，不构成推进阻塞）。
    )

    def __init__(self) -> None:
        self.ticket_id: str = ""
        self.meta: Dict[str, Any] = {}
        self.results: Dict[str, Dict[str, Any]] = {}      # activity name → StageResult summary
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self._sigs: Dict[str, Signature] = {}
        self._rework: Optional[ReworkRequest] = None
        self._retry_token: int = 0
        # KI-061: entry sequence number for arbitrate over-limit blocked (+1 per entry,
        # shared across the serial/parallel branches) — the wake-reset guard's patch id
        # suffix takes this value, so the same id is evaluated exactly once per instance
        # at the wake crossing (the SDK memoizes the first patched() verdict: a False
        # seen during replay is remembered forever, so reusing an id means a live wake
        # eats a poisoned value).
        self._arb_over_limit_seq: int = 0
        self._gens: Dict[str, int] = {}                   # activity name → entry count
        # t260915-01：详情数据面门缓存位（唯一求值点在 _init；缺省 False=UT 壳/异常
        # 形态走旧分支；所有使用点读 getattr 防御，@query 内禁调 workflow.patched）。
        self._detail_face_on: bool = False
        self.gate_runs: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.human_context: Dict[str, Any] = {}
        self.engine_version: int = ENGINE_VERSION_V2

    # ---------- internals: time / logging ----------
    def _now_epoch(self) -> int:
        return int(workflow.now().timestamp())

    def _now_iso(self) -> str:
        return workflow.now().isoformat(timespec="seconds")

    def _log(self, note: str, status: Optional[str] = None) -> None:
        self.meta.setdefault("log", []).append(
            {"ts": self._now_epoch(), "status": status or self.meta.get("status", ""), "note": note})

    def _mark(self, step: str, state: str, reason: str = "") -> None:
        entry: Dict[str, Any] = {"at": self._now_iso(), "stage": step,
                                 "state": state, "reason": reason}
        if getattr(self, "_detail_face_on", False):
            # t260915-01 ③：轮次/并行相位可读维度（门内追加键；门关=旧 4 键逐字）。
            # gen=该步当前进入计数（_enter 已自增→本条目归属第几轮）；phase=并行
            # 相位名（meta['parallel_phase'] 由 set_parallel_stages 维护，串行期缺省）。
            entry["gen"] = self._gen(step)
            phase = self.meta.get("parallel_phase")
            if phase:
                entry["phase"] = phase
        self.timeline.append(entry)
        # t260928-13：事件账本入队（唯一入队点，机制在 TicketEventLedgerMixin；
        # patched 门内，老实例重放零变化；flush 由各异步边界/收口点承担）
        self._ledger_enqueue(entry)
        workflow.logger.info("[%s] %s/%s %s", self.ticket_id, step, state, reason)

    def _touch(self) -> None:
        self.meta["updated"] = self._now_epoch()

    async def _breathe(self) -> None:
        """Yield point inside stage-transition mutation bursts (KI-003). This class
        stands alone from TicketWorkflowBase (no inheritance, hence its own _breathe);
        shape and trade-offs mirror base.py's same-named method — a ticket already
        running replays down the old branch (patched branch + zero-length timer).
        Putting it only on the base would make self._breathe raise AttributeError and
        blow up the workflow task."""
        if not workflow.patched(BREATHE_PATCH_ID):
            return  # old history replay: no marker, do not yield, keep replay deterministic
        await asyncio.sleep(0)  # zero-length timer: yields the event loop and carries its own wake event

    def _step(self, step_id: str) -> Stage:
        for s in self.STAGES:
            if s.id == step_id:
                return s
        legacy = _LEGACY_STEPS.get(step_id)
        if legacy:
            return legacy
        raise ValueError("未知步骤 %r" % step_id)

    def _gen(self, step_id: str) -> int:
        return self._gens.get(step_id, 0)

    # ---------- initialization ----------
    def _init(self, inp: TicketInput) -> None:
        self.ticket_id = inp.ticket_id
        workflow.patched(self.PATCH_ID)
        # t260915-01：详情数据面门缓存位——全实例唯一求值点（run 起点非唤醒穿越处，
        # 无 KI-061 memo 毒化形态）。在途实例重放：首评落重放段→False 永固化→旧分支
        # 逐字不变；新实例：首评 live→True+marker→重放同判定。所有使用点（含
        # snapshot）只读本布尔位，不再触碰 SDK 门判定调用。
        self._detail_face_on = workflow.patched(DETAIL_FACE_PATCH_ID)
        # t260916-19 ①：rework 出路可达门（唯一求值点，同上纪律；UT 壳走 getattr
        # 防御读缺省 False=旧回落路径，与在途重放同形）。
        self._rework_escape_on = (workflow.patched(REWORK_ESCAPE_PATCH_ID)
                                  and not SANDBAR_TEST_DISABLE_REWORK_ESCAPE)
        first = self.STAGES[0]
        # t260929-19：实例验收增项（acceptance_extra）随单运输 + create 时净化。
        # 语义（shared.py:3374 声明）：增项补进第一段的清单。畸形项显式降级：
        # str() 收敛→strip→空白项丢弃→与模板段验收重复丢弃（strip 后同形比较，
        # 避免面上出现 ' x'/'x' 近重复对）→增项内部重复丢弃；每个被丢项在台账
        # log 点名（_log，log 类而非段状态类，见 meta 构造后的 _log 调用），
        # 绝不崩溃、绝不静默。
        _tpl = {str(x).strip() for x in first.acceptance}
        _extras: List[str] = []
        _dropped: List[str] = []
        _raw_extra = getattr(inp, "acceptance_extra", None)
        if _raw_extra is None:
            _raw_extra = []                     # 老在途 payload 缺键：无增项，零噪音
        elif not isinstance(_raw_extra, (list, tuple)):
            _dropped.append(repr(_raw_extra))   # 非列表形态：整体显式丢弃并点名
            _raw_extra = []
        for _x in _raw_extra:
            _s = str(_x).strip()
            if not _s or _s in _tpl or _s in _extras:
                _dropped.append(repr(_x))
                continue
            _extras.append(_s)
        acc = list(first.acceptance) + _extras
        self.meta = {
            "id": inp.ticket_id,
            "workflow_id": inp.template_id,
            "project": inp.project,
            "title": inp.title,
            "role": first.role,
            "lane": inp.lane or self.TEMPLATE_LANE,
            "workspace": inp.workspace,
            # Ticket t260910-08（t260910-07 实案收口）: the per-repo detail carried
            # through verbatim — the previous drop of this key left
            # meta.repo_worktrees permanently null and every multi-repo ticket
            # materialized single-repo (dengzhufpv incident). Carried **raw** (no
            # per-entry rewrite): a malformed entry must reach the existing
            # _repo_worktrees_gate_error judge for a readable rejection, not blow up
            # here inside the workflow with a bare ValueError (base._init 既有同款).
            "repo_worktrees": list(getattr(inp, "repo_worktrees", None) or []),
            # Same ticket: the project root feeds prepare_workspace's fallback ring
            # ③ (write_set+project_root derivation). getattr = old payloads replay
            # with the key missing and fall back to "" without breaking replay.
            "project_root": str(getattr(inp, "project_root", "") or ""),
            "worktree": inp.worktree,
            "branch": inp.branch,
            "base_ref": inp.base_ref,
            "proposal_id": inp.proposal_id,
            "book_path": inp.book_path,
            "epic": inp.epic,
            "stage": first.id,
            "stage_state": "awaiting",
            "write_set": list(inp.write_set),
            "no_file_changes": bool(getattr(inp, "no_file_changes", False)),
            # t260911-03 路径闸总开关：随派单输入钉死（getattr 缺省 False=老在途票
            # 永远关闸，patch 门保护不追溯）
            "path_gate": bool(getattr(inp, "path_gate", False)),
            # KI-124：本票模板段规则表随派单钉死（replay 稳定；空表=回落内建规则表）
            "path_gate_rules": dict(getattr(inp, "path_gate_rules", None) or {}),
            "acceptance": acc,
            # t260929-19：第一段清单 = 模板验收 + 净化后实例增项（shared.py:3374
            # 声明语义，与 base.py:716-717 同形）；其余段仍纯模板验收。
            "checks": {s.id: [{"item": it, "done": False, "by": ""}
                              for it in (acc if s.id == first.id else s.acceptance)]
                       for s in self.STAGES},
            "deliverables": inp.deliverables,
            "user_request": inp.user_request,
            "spec": inp.spec,
            "body": inp.user_request or inp.body,
            "pending": [],
            "handoffs": [],
            "status": "dispatched",
            "created": inp.created or self._now_epoch(),
            "updated": self._now_epoch(),
            "last_rework_note": "",
            "temporal": True,
            "workflow_input": {
                "ticket_id": inp.ticket_id, "template_id": inp.template_id,
                "project": inp.project, "title": inp.title,
                "lane": inp.lane or self.TEMPLATE_LANE,
                "worktree": inp.worktree, "branch": inp.branch,
                "base_ref": inp.base_ref, "write_set": list(inp.write_set),
                "path_gate": bool(getattr(inp, "path_gate", False)),
                # KI-124：台账输入镜像同步（consumers read defensively, extra keys safe）
                "path_gate_rules": dict(getattr(inp, "path_gate_rules", None) or {}),
                # t260910-08: mirror the two new carries so the ledger keeps a
                # complete input record (consumers read defensively, extra keys safe)
                "repo_worktrees": list(getattr(inp, "repo_worktrees", None) or []),
                "project_root": str(getattr(inp, "project_root", "") or ""),
                "user_request": inp.user_request, "spec": inp.spec, "body": inp.body,
                "created": inp.created or self._now_epoch(),
            },
            "temporal_engine_version": self.engine_version,
            "engine": ENGINE_V2,
            "log": [{"ts": self._now_epoch(), "status": "dispatched",
                     "note": "工单创建（%s：activity 直编排，步=%s）"
                             % (self.TEMPLATE_ID, [s.id for s in self.STAGES])}],
        }
        if _dropped:
            # t260929-19：畸形/重复增项显式降级——log 类台账点名（非 _mark 段状态，
            # 避免污染下游 snapshot/lane 读的段状态机）。
            self._log("acceptance_extra 丢弃畸形/重复项：%s" % ", ".join(_dropped))
        self._mark(first.id, "awaiting", "adopt %s（步=%s）"
                   % (self.TEMPLATE_ID, [s.id for s in self.STAGES]))

    # ---------- step entry (the meta/ledger trio) ----------
    def _enter(self, step_id: str) -> None:
        st = self._step(step_id)
        self._gens[step_id] = self._gen(step_id) + 1
        self.meta["stage"] = step_id
        self.meta["role"] = st.role
        self.meta["status"] = "dispatched"
        self.meta["stage_state"] = "running"
        # t260929-19：步进入守卫（同族先例 base.py:1046-1049 / 960）——仅首段首次
        # 进入（_gen==1）保留 create 时的实例验收增项；其余段、以及首段重入
        # （rework 回打，_gen>1）一律换成本段模板清单。注意本函数 908 行先自增
        # gen 再走到此处：写点读到的 gen 是自增后的（首进=1、重入=2），守卫条件
        # 依赖这一顺序——勿调换自增与本守卫的先后。
        if step_id != self.STAGES[0].id or self._gen(step_id) > 1:
            self.meta["acceptance"] = list(st.acceptance)
        if getattr(self, "_detail_face_on", False):
            # t260915-01 ②（R2 清点②）：blocked_detail＝「当前受阻明细」，非
            # blocked 期恒空——所有非 blocked 推进的唯一步进入口在此统一清，关掉
            # 不经 _blocked 的失败路径留下的陈旧红卡（merge_check 冲突自动消解成功、
            # 仲裁格式纠正轮失败后下轮成功等）。与 _blocked wake 清（清点①）双保险。
            self.meta["blocked_detail"] = None
        self._touch()
        self._mark(step_id, "running", "进入本步（第 %d 次）" % self._gen(step_id))

    def _finish(self, step_id: str, by: str, evidence: str) -> None:
        for c in self.meta.setdefault("checks", {}).setdefault(step_id, []):
            c["done"], c["by"] = True, by
            if evidence:
                c["evidence"] = evidence
        # t260901-08: terminal-state record (three failure modes weighed):
        # (1) replay safety — _mark is a pure in-memory append, no history command, so
        #     RUNNING instances replaying stay deterministic;
        # (2) old-ticket fallback — existing tickets' history has no done entry, so the
        #     workbench falls back to its current inRun heuristics (no retroactive fix);
        # (3) re-run semantics — when a rework re-enters, running is appended after
        #     done, so the newest state correctly reads as running again.
        self._mark(step_id, "done", by + (("：" + evidence) if evidence else ""))
        self._touch()

    def _handoff(self, step_id: str, summary: str,
                 artifacts: Optional[List[str]] = None, report: str = "") -> None:
        entry: Dict[str, Any] = {"stage": step_id, "agent_id": "", "summary": summary,
                                 "report": report,
                                 "artifacts": list(artifacts or []),
                                 "ts": self._now_epoch(),
                                 "engine_version": self.engine_version}
        if getattr(self, "_detail_face_on", False):
            # t260915-01 ③：handoff 携带轮次（现状 0 条含 gen；详情页轮带消费）。
            entry["gen"] = self._gen(step_id)
        self.meta.setdefault("handoffs", []).append(entry)

    def _refresh_write_set_after_plan(self) -> None:
        """Write-set refresh after the plan is finalized (conditional passes included)
        (t260829-07; the inline code from the old review_plan ok branch moved up
        verbatim — the selfcheck_write_lifecycle section E pins on that exact string)."""
        # t260829-07: plan finalized → refresh the write set (union, pure function; the
        # list comes from the create_plan receipt — already in workflow history, so
        # deterministic).
        if workflow.patched(REFRESH_WRITE_SET_PATCH_ID):
            plan_files = (self.results.get("create_plan") or {}).get("files_changed")
            # t260904-18 KI-049 gate 2: shape is normalized by the parsing layer
            # normalize_files_changed (surfaced as the files_changed_shape key in the
            # results dict). malformed/empty receipt (with no_file_changes undeclared)
            # → visible red + warning, write set untouched — an empty receipt used to be
            # the root cause of the write-set refresh silently no-oping (three tickets
            # each ran 1-2h extra); absent → skip and leave a note (old tickets).
            # Visible red = a top-level meta flag + WARNING log, never a faked
            # blocked/rework timeline state (keeps the workbench ReworkBanner from
            # misfiring, KI-001 family).
            # Accepted blind spot: this judgment is reachable only at the refresh point
            # after review_plan passes; an empty receipt inside a send-back round does
            # not light up that round. The real fix is filed with the write-set reform
            # discussion.
            plan_shape = (self.results.get("create_plan") or {}).get(
                "files_changed_shape") or "absent"
            fault = None
            if plan_shape == "malformed" and workflow.patched(WRITE_SET_FAULT_PATCH_ID):
                fault = ("files_changed 形状非法（%s，非字符串数组——解析层拒收毁形）"
                         % plan_shape)
            elif plan_files == [] and workflow.patched(WRITE_SET_FAULT_PATCH_ID) \
                    and not bool(self.meta.get("no_file_changes")):
                fault = "files_changed 为空数组"
            if fault:
                self.meta["write_set_refresh_fault"] = {
                    "stage": "create_plan", "reason": fault,
                    "ts": self._now_epoch()}
                # 260930（dengzhufpv E6／批次 A）：**两态区分 + 去掉会诱发空转的处方**。
                # 实测（t260929-15/-29/-31/-33 四次）：写集零污染、票自行跑完、**零交付损失**，
                # 四次都不需要 rework——旧文案的「处置：rework 回 create_plan」把人引去一轮空转
                # （与「报错必须精确」相抵）。故：降级为**提醒（非阻塞红）** + 说明两态 + 明确劝止。
                self._log("【提醒·非阻塞】create_plan 回执 %s（KI-049：空/畸形回执使写集刷新"
                          "并集 no-op）——写集保持初始 %d 条。两态：①本段确实没改文件（正常，"
                          "无需动作）；②agent 改了文件但没填结构化字段（回执形状缺口）。"
                          "**不要为它 rework**：四次实案零交付损失、票自行推进；若后续段出现"
                          "写集越界红，那属「写集建票后不可改」的通道缺口（走越界/授权流程），"
                          "不是本红灯的处方"
                          % (fault, len(self.meta.get("write_set") or [])))
                return
            if plan_files is None:
                self._log("写集刷新跳过：create_plan 回执无 files_changed（初始写集保留）")
            else:
                merged, added, dropped = refresh_write_set(
                    list(self.meta.get("write_set") or []), list(plan_files))
                self.meta["write_set"] = merged
                for f in added:
                    self._log("授权扩展：+%s（写集跟随方案）" % f)
                if dropped:
                    self._log("写集刷新丢弃非法条目：%s"
                              % "、".join(str(d) for d in dropped))
                self._log("写集已随方案定稿刷新：现 %d 条" % len(merged))

    # ---------- blocked wait (retry_qc re-runs this step / rework jumps) ----------
    async def _blocked(self, step_id: str, why: str) -> None:
        self.meta["stage_state"] = "blocked"
        # KI-048 (t260911-05): the blocked why is pinned on meta so the snapshot can
        # surface it top-level (blocked_reason / blocked_detail) — the ticket face
        # and the human gate must see WHY without diving into worker logs.
        self.meta["blocked_reason"] = why
        self._touch()
        self._log("%s → blocked，等 retry_qc 重跑或 rework 打回" % why)
        self._mark(step_id, "blocked", why)
        # t260928-13：blocked 是长等待入口，先冲账再等（事件账本 flush 点）
        await self._ledger_flush()
        token = self._retry_token
        await workflow.wait_condition(
            lambda: self._retry_token > token or self._rework is not None)
        if getattr(self, "_detail_face_on", False):
            # t260915-01 ①（清点①）：block 解除的唯一汇合点——retry_qc（token 增）
            # 与 rework（_rework 置位）两条出路都经此，清「当前是否受阻」的两个当前
            # 态字段；上方 _mark 落的 blocked 历史条目＝审计留痕，不动。门缓存位读
            # getattr（R1：@query 只读约束无关此处，但 UT 壳 object.__new__ 不跑
            # __init__，统一防御）。
            self.meta["blocked_reason"] = ""
            self.meta["blocked_detail"] = None
            # t260925-17（KI-120 附条件③，review 意见）：醒后重驱观测面——本次事故
            # 的头号排查成本就是「日志只见放行、不见重驱」。同一门内（旧 history
            # 重放逐字旧行为，零新日志）。
            self._log("%s blocked 解除（%s 唤醒）→ 主循环重驱"
                      % (step_id,
                         "rework" if self._rework is not None else "retry_qc"))
        # On wake, the main loop looks at self._rework / re-runs this step

    async def _blocked_over_limit(self, why: str) -> bool:
        """Wake-reset guard for the arbitrate over-limit blocked state (KI-061). After
        the _blocked wait completes, returns True = the caller must discard the memoized
        arbitration verdict (reset arb_done/arb_res) and genuinely re-run the arbitrate
        edge.

        Why "a unique patch id per entry" instead of a fixed id: the SDK memoizes the
        first patched() verdict per instance — an in-flight workflow replay crosses the
        historical wake points, where a fixed id's first evaluation lands during replay
        (no marker), yields False and is frozen forever, so a live wake eats a poisoned
        False (the mechanical reason the fixed-id hotfix demonstrably did not work,
        t260907-10). With the `#<seq>` suffix: at historical wake points each id's first
        replay evaluation is False and issues zero commands (replay does not break); at
        a live wake point the id has never been evaluated → first evaluation True, the
        reset takes effect. A rework wake is handled centrally by the main loop, so this
        short-circuits to False (patched not evaluated, both sides replay alike)."""
        self._arb_over_limit_seq += 1
        n = self._arb_over_limit_seq
        await self._blocked("arbitrate", why)
        if self._rework is not None or SANDBAR_TEST_DISABLE_KI061:
            return False
        return workflow.patched("%s#%d" % (KI061_WAKE_RESET_PATCH_ID, n))

    # ---------- t260923 D：收口全量跑（串行/平行两分支共用） ----------
    def _integ_run_args(self, only_names=()):
        """集成跑入参构造（t260913-03 唯一真站锁的单写者收拢，260923 D）：
        apply_skip_pools 策略值只此一处显式置位（语句字面量唯一命中=锁的判据）；
        主跑传定点面（可空），收口跑传空=全量。attempt=本代数口径与既有调用点
        逐元素等值。"""
        return IntegrationRunArgs(
            ticket_id=self.ticket_id,
            worktree=str(self.meta.get("worktree") or ""),
            attempt=self._gen("run_integration_tests") + 1,
            # t260913-03：每票段唯一 true 站（策略面只在调用点显式置位；write_set
            # 供例外分支求交）
            write_set=list(self.meta.get("write_set") or []),
            apply_skip_pools=True,
            handover_runs=self._handover_debt_legs(),
            only_names=list(only_names or []))

    async def _closing_full_run(self):
        """D 收口跑（260923 宿主直修令）：定点跑后的全量跑=唯一放行依据。与主跑
        同形入参（同代数、同策略值，走 _integ_run_args 单写者），仅 only_names
        为空（全量面，不注入 SANDBAR_SCENARIO_ONLY）。回执形状同
        IntegrationRunResult。"""
        rraw = await workflow.execute_activity(
            run_integration_tests, self._integ_run_args(),
            start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
        return rraw if isinstance(rraw, IntegrationRunResult) else IntegrationRunResult(
            ran=int(rraw.get("ran") or 0), passed=int(rraw.get("passed") or 0),
            failed=int(rraw.get("failed") or 0),
            env_fail=int(rraw.get("env_fail") or 0),
            details=[dict(d) for d in (rraw.get("details") or [])],
            error=str(rraw.get("error") or ""))

    # ---------- t260917-09：tests 连续计数（串行/平行两分支共用） ----------
    def _tests_supply_assembly_fail(self, cur_integ) -> bool:
        """装配级供给失败形态（机械口径，t260917-09 gen11 打回补）：零跑＋零产品
        红＋零闸拦＋零环境红＋error 命中供给装配签名（verify_lane 乙段 supply 装
        配超时/失败两态，签名单写者=shared.tests_supply_assembly_error）。docker
        长离线类宿主事实在仓内无修复面，保守计轮只会把票推假封（工单正文要掐断的
        「环境红→计轮→假封→人工判读」链的供给形态）；形态判定宁窄勿宽——签名不
        命中/字段畸形=False 照旧保守计轮，绝不因豁免口径扩大放走产品红。"""
        if cur_integ is None:
            return False
        try:
            ran = int(getattr(cur_integ, "ran", 0) or 0)
            failed = int(getattr(cur_integ, "failed", 0) or 0)
            env_fail = int(getattr(cur_integ, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            return False
        if ran != 0 or failed != 0 or env_fail != 0:
            return False
        if getattr(cur_integ, "blockers", None):
            return False
        return tests_supply_assembly_error(getattr(cur_integ, "error", "") or "")

    def _tests_env_red_names(self, cur_integ):
        """B2（宿主 260929 令）环境红**具名**名单读面——唯一认的通道=闸回执的
        `env_red`（B1 已落：来源=闸的权威判决面 `not_checked × external`）。

        红线（本函数是那条红线的单点）：**绝不**采信场景自报 exit=2、**绝不**从
        `ENV_FAIL [...] exit=N` 文本行反推——那条面已知与闸判决不一致（spawn 失败
        -8 执行器记 env、闸按败计）。

        返回 (names, channel_ok)：channel_ok=True 当且仅当 `env_red` 键在场且形状
        可读（list）；缺键/畸形/老回放=False（调用方退回旧口径，逐字节兼容老行为）。
        名字逐条 str(非空) 化，去重保序。不抛。"""
        if cur_integ is None:
            return [], False
        raw = getattr(cur_integ, "env_red", None)
        if not isinstance(raw, list):
            return [], False
        names = []
        for x in raw:
            nm = str(x or "").strip()
            if nm and nm not in names:
                names.append(nm)
        return names, True

    def _env_red_face_note(self, names, *, limit=5) -> str:
        """环境红具名票面注记（B2）：`｜环境红（不拦·具名）：a、b、c…（共 11）`。
        名单为空/畸形=空串（票面不加这一段）。只读展示面，不进任何判定。"""
        if not isinstance(names, (list, tuple)):
            return ""
        got = [str(x).strip() for x in names if str(x or "").strip()]
        if not got:
            return ""
        shown = "、".join(got[:limit])
        return "｜环境红（不拦·具名）：%s%s（共 %d）" % (
            shown, "…" if len(got) > limit else "", len(got))

    def _integ_round_stall(self, cur_integ) -> Dict[str, Any]:
        """本轮闸**测量面**与上一轮判过的逐字相同 ⇒ 判停（260929 宿主令直修）。

        调用点在 tests-fault 非采纳路径：轮数未到上限时 `integration_route` 会把它路由回
        run_integration_tests 再跑一趟全套——但若这一轮测到的东西（闸拦名单/具名环境红/
        四计数/归属置信/基线 ref/逐条失败明细）与上一轮**完全相同**，重跑不可能产生新信息
        （t260929-22 实案：连 4 轮同状态、代码自 gen4 未动、裁判每轮都写「转人工判读」，
        仍被路由回跑，每趟 ~30 分钟）。签名相同 ⇒ 直接转人审（`_blocked_over_limit`，
        人可用 retry_qc/授权复活），判词写明「连续 N 轮零变化」。

        签名单写者=shared.gate_round_signature；本方法只管取用/记账/文案。
        判不准（签名空=老回执/畸形）→ 不判停（照旧重跑，fail-safe）。"""
        from shared import gate_round_signature
        sig = gate_round_signature(cur_integ)
        if not sig:
            return {"stall": False, "rounds": 0, "sig": "", "note": ""}
        prev = str(self.meta.get("integ_signature") or "")
        try:
            rounds = int(self.meta.get("integ_signature_rounds") or 0)
        except (TypeError, ValueError):
            rounds = 0
        if prev and prev == sig:
            rounds += 1
            self.meta["integ_signature_rounds"] = rounds
            return {"stall": True, "rounds": rounds, "sig": sig,
                    "note": ("连续 %d 轮闸测量面逐字相同（same gate blockers / named env-red / "
                             "counts / failure detail / baseline ref）：本票写集与红面零变化 ⇒ "
                             "重跑全套不可能产生新信息。转人审（读仲裁判词与 DESIGN-CONFLICT "
                             "类交接件后裁）；人裁后 retry_qc 可复活。" % rounds)}
        self.meta["integ_signature"] = sig
        self.meta["integ_signature_rounds"] = 1
        return {"stall": False, "rounds": 1, "sig": sig, "note": ""}

    def _acceptance_without_rerun(self, cur_integ) -> bool:
        """B2（260929 宿主令）豁免轮归宿判据：本轮是否属于「环境面/已知红面」——
        属于则**不再重跑整轮**，直接进验收；只有**本票新增产品红**（不在具名环境红
        名单里、且闸 blockers 非空）才重跑。

        口径（与 `_tests_env_side_red` 同源，不另造红绿判据）：
          · 环境面（含装配级供给失败形态）= True（env_fail>0 且红项已被具名 env_red
            整批吸收，见 `_tests_env_side_red`）；
          · 否则，**产品红名单为空**且闸 blockers 显式为空（isinstance 校验，缺席/畸形
            不豁免——保守计轮）且闸有红面计数（env_fail>0 或 failed>0；零红全绿轮由
            `_tests_round_account` 的 known_red 车道处置，不归本判据）= 零新增红
            （全属基线既有欠账/外部环境记录面）= True；
          · 其余（任何**产品红名单非空**——含「名单盖不住那几条」的未具名产品红、
            blockers 缺席或非空、红项名单畸形）= False → 照旧重跑整轮。
        **具名通道盖不住的产品红一律重跑**（红线：任何红都不许被静默）——本判据只对
        「红面已被具名/在册面解释干净」的轮放行。
        调用点在 `if not counted:` 分支内，故 jitter 形态不会走到这里（仍走原重跑）。"""
        if cur_integ is None:
            return False
        if self._tests_env_side_red(cur_integ):
            return True
        try:
            env_fail = int(getattr(cur_integ, "env_fail", 0) or 0)
            failed = int(getattr(cur_integ, "failed", 0) or 0)
        except (TypeError, ValueError):
            return False
        blockers = getattr(cur_integ, "blockers", None)
        return (not self._tests_product_red_names(cur_integ)
                and isinstance(blockers, list) and not blockers
                and (env_fail > 0 or failed > 0))

    def _tests_product_red_names(self, cur_integ):
        """产品红名单（B2）：`_tests_red_names` 结果**减去**环境红具名名单——
        环境红不再被误当产品红（送去定点复跑/计轮都是白烧）。

        口径（按具名通道分区）：
          · 通道可读（env_red 键在场）⇒ 逐名减法；被减去的那批只算环境面。
          · 通道缺席/畸形（老回放）⇒ **逐字节退回旧口径**（名单=原红项名单，
            环境面判据也退回旧口径，见 `_tests_env_side_red`）——保守，从不放走产品红。"""
        names = self._tests_red_names(cur_integ)
        env_names, _ok = self._tests_env_red_names(cur_integ)
        if not env_names:
            return names
        env_set = set(env_names)
        return [n for n in names if n not in env_set]

    def _tests_env_side_red(self, cur_integ) -> bool:
        """本轮红项是否全在环境面（机械口径，t260910-13；t260917-09 gen11 扩口径；
        B2 260929 改按**具名通道**分区）：场景级=产品红整批被 `env_red` 具名名单
        吸收（逐名减法后名单空/子集）＋闸拦 0＋环境红 ≥1；装配级=供给装配失败
        （见 _tests_supply_assembly_fail）。cur_integ 缺席（旧回放/异常路径）=False
        （保守计轮）。

        B2 语义变更的理由（宿主 260929 令）：混合轮（如「11 败 + 11 环境红」）在旧
        口径下产品红计数 `failed ≠ 0` 恒成立 → 环境面识别不出 → 保守计轮 → 每轮烧
        ~30 分钟整轮套件、5–6 轮后假封。新口径用**具名通道**把环境红逐名摘出去，
        摘不动的（无名单/名单盖不住产品红）一律退回旧口径保守计轮——**任何红都不许
        被静默**：具名通道缺席时宁可多计一轮，也不把未具名的红当环境面放行。

        `env_fail>0 但 env_red 缺键/空` ⇒ 旧保守行为（`failed==0` 才认环境面）；
        `env_red` 非空 ⇒ `failed>0` 的混合轮也能识别（含**全条**具名的前提）。"""
        if cur_integ is None:
            return False
        try:
            failed = int(getattr(cur_integ, "failed", 0) or 0)
            env_fail = int(getattr(cur_integ, "env_fail", 0) or 0)
        except (TypeError, ValueError):
            return False
        blockers = getattr(cur_integ, "blockers", None) or []
        # 闸拦名单非空=有闸级红项（不在环境面）——环境面判据不成立。
        if not blockers and env_fail > 0:
            env_names, channel_ok = self._tests_env_red_names(cur_integ)
            if channel_ok and env_names:
                # 具名通道在场：产品红 = 红项名单 − 环境红名单；减法后仍有名字
                # （含「failed≠0 但一条都没被具名吸收」的覆盖不足形态）=产品红仍在。
                return not self._tests_product_red_names(cur_integ)
            # 通道缺席/畸形（老回放）⇒ 逐字节退回旧口径。
            if failed == 0:
                return True
        return self._tests_supply_assembly_fail(cur_integ)

    def _tests_red_names(self, cur_integ):
        """红项名单（C4 单一来源）：details exit≠0 逐案名 ∪ blockers 闸拦名单，
        剔除 __pool_exclude__/__gate_blockers__ 合成条目（前缀 __ 识别）。两源皆缺
        或畸形=空名单（调用方保守计轮，不发探针——绝不把「解析不出」当「无红」）。

        B2（260929）：**再剔除 `env_red` 具名名单里的名字**——环境红不该被送去定点
        复跑（白跑一趟），也不该推进「本轮红项」的抖动探针。具名通道缺席/畸形时只在
        原名单上做「无操作」（先摘出的那一步没有名单可摘），老回放口径不变。

        两名单位（blockers 与 env_red）互斥的**理由**（据此才敢在两侧同做减法）：两者
        同源于闸的逐条 verdicts，一条判决只能落一个 verdict block（闸拦）或
        not_checked_external（环境记录），同名两态除非同一用例在闸侧被记两次。真出现
        同名时，闸拦面（`_arb_json` 的 blockers、采纳判据）仍然点名该名，不被静默。"""
        if cur_integ is None:
            return []
        env_names, _ok = self._tests_env_red_names(cur_integ)
        env_set = set(env_names)
        names = []
        for d in (getattr(cur_integ, "details", None) or []):
            if not isinstance(d, dict):
                continue
            try:
                ex = int(d.get("exit", 0) or 0)
            except (TypeError, ValueError):
                ex = 0
            nm = str(d.get("name") or "")
            if nm and ex != 0 and not nm.startswith("__") and nm not in names \
                    and nm not in env_set:
                names.append(nm)
        for b in (getattr(cur_integ, "blockers", None) or []):
            b = str(b)
            if b and not b.startswith("__") and b not in names \
                    and b not in env_set:
                names.append(b)
        return names

    async def _known_red_roster_payload(self):
        """读仓根已知红名册（只读活动壳；KI-122①）。故障/畸形**不抛**：error 非空 ——
        调用方 fail-closed 照旧拦、照旧重跑，并把原因点名进票面。
        活动回执形状：{ok, result:{entries:{name:{verdict,home,booked_at,booked_sha}},
        error, path, base_ref, base_at, base_at_error}}；本方法顺带把 base_ref 的提交
        时刻带回来（时间证据的比较下界，见 `_ticket_base_point`）。
        260926 独立复核缺口①：回执**形状漂移**（result/entries 非 dict、条目非对象）
        同样 fail-closed 回来（error 非空），**绝不抛未捕获异常**——主循环是裸
        `while True:`，抛出去=打断工作流实例。"""
        meta = getattr(self, "meta", None) or {}
        base_ref = str(meta.get("base_ref") or "")
        out = {"payload": None, "error": "", "base_at": "", "base_ref": base_ref,
               "base_issue": ""}
        try:
            raw = await workflow.execute_activity(
                "read_known_red_roster", args=[{"base_ref": base_ref}],
                start_to_close_timeout=SHORT, retry_policy=RETRY)
        except Exception as e:  # noqa: BLE001 —— 名册读不到=照旧拦（不拦主链、不放行）
            # t260929-18：同款异常链下钻（shared.exception_chain_note，单走法）。
            out["error"] = "roster activity failed: %s: %s%s" % (
                type(e).__name__, e, shared.exception_chain_note(e))
            return out
        if not isinstance(raw, dict):
            out["error"] = ("roster activity receipt is not an object (%s)"
                            % type(raw).__name__)
            return out
        if not raw.get("ok"):
            out["error"] = str(raw.get("error") or "roster activity returned ok=false")
            return out
        res = raw.get("result")
        if res is None:
            res = {}
        if not isinstance(res, dict):
            out["error"] = ("roster activity result is not an object (%s)"
                            % type(res).__name__)
            return out
        entries = res.get("entries")
        if entries is None:
            entries = {}
        if not isinstance(entries, dict):
            out["error"] = ("roster activity entries is not an object (%s)"
                            % type(entries).__name__)
            return out
        bad = [(str(k), type(v).__name__) for k, v in entries.items()
               if not isinstance(v, dict)]
        if bad:
            out["error"] = ("roster entry %s is not an object (%s)"
                            % (bad[0][0], bad[0][1]))
            return out
        err = str(res.get("error") or "")
        if err:
            out["error"] = "%s (%s)" % (err, res.get("path") or "")
            return out
        out["payload"] = {"entries": [dict({"name": k}, **v) for k, v in entries.items()]}
        out["base_at"] = str(res.get("base_at") or "")
        out["base_issue"] = str(res.get("base_at_error") or "")
        return out

    def _ticket_base_point(self, roster_base_at):
        """本票**开票基点**（时间证据的比较下界；KI-122① 260926 裁定）：票面 base_ref 的
        提交时刻 ∪ 票的 created 时刻，取**可得的更早者**=保守下界（只用更严的一侧，绝不用
        更松的一侧放行）。返回 (值, 具名来源)；二者皆不可得 → (None, 具名原因)——判据侧
        fail-closed 不采纳。纯读 meta+入参，零 IO、零墙钟（回放安全）。"""
        meta = getattr(self, "meta", None) or {}
        cands = []
        rb = str(roster_base_at or "")
        if rb:
            cands.append(("base_ref commit time", rb))
        created = meta.get("created")
        if evidence_ts_epoch(created) is not None:
            cands.append(("ticket created", created))
        usable = []
        for tag, v in cands:
            at = evidence_ts_epoch(v)
            if at is not None:
                usable.append((at, tag, v))
        if not usable:
            return None, ("no usable ticket base point (base_ref=%r, created=%r)"
                          % (meta.get("base_ref"), created))
        usable.sort(key=lambda x: x[0])
        _, tag, v = usable[0]
        src = "%s=%s" % (tag, v)
        if len(usable) > 1:
            src += " (earliest of %s)" % ", ".join("%s=%s" % (t, vv) for _, t, vv in usable)
        return v, src

    async def _tests_fault_adoption(self, cur_integ):
        """KI-122①：tests-fault 判决可否采纳（推进而非重跑）。返回
        shared.blockers_known_red_adoption 的形状（adopt/why/known/new/stale/note）。

        单写者=shared 纯函数（判据只此一份）；本方法只做三件事：取闸回执的 blocker
        名单与启动级 error、读名册（含 base_ref 提交时刻）、算本票开票基点。**fail-closed**：
        名册不可用/基点不可得/戳不合格 → adopt=False（照旧拦、照旧重跑），原因随 note 上票面。
        空名单不走本面（既有 known_red 豁免车道语义不动）。
        活基线加保险：回执的 live_baseline_red/green（两路实跑证据：本轮闸基线主跑逐名
        答案 ∪ 场景台账可信行）原样带入；两名单对该名都无数据=不可得，仍按时间证据判，
        但票面点名「基线不可得，仅时间证据」——「没跑到」永不等于「main 绿」。"""
        blockers = getattr(cur_integ, "blockers", None) if cur_integ is not None else None
        names = [b for b in (blockers if isinstance(blockers, (list, tuple)) else [])
                 if isinstance(b, str) and b.strip()]
        if not names:
            return {"adopt": False, "why": "no-blockers", "known": [], "new": [],
                    "roster_ok": False, "note": ""}
        receipt = await self._known_red_roster_payload()
        base_at, base_src = self._ticket_base_point(receipt.get("base_at"))
        if receipt.get("base_issue"):
            base_src = "%s; base_ref resolution issue: %s" % (base_src, receipt["base_issue"])
        # 活基线加保险（洞①第二重）：两路实跑证据由活动壳合成在回执上（live_baseline_*）；
        # 本轮没有活证据（老回执/基线未跑/台账不可用）→ 空名单 + 具名来源，判据侧按
        # 「基线不可得，仅时间证据」走并逐票点名。
        lb_red = [str(x) for x in (getattr(cur_integ, "live_baseline_red", None) or [])
                  if isinstance(x, str) and str(x).strip()]
        lb_green = [str(x) for x in (getattr(cur_integ, "live_baseline_green", None) or [])
                    if isinstance(x, str) and str(x).strip()]
        lb_src = str(getattr(cur_integ, "live_baseline_source", "") or "")
        if not lb_red and not lb_green:
            lb_src = lb_src or KI122_LIVE_BASELINE_SOURCE
        return blockers_known_red_adoption(
            names, receipt.get("payload"), roster_error=receipt.get("error") or "",
            run_error=(getattr(cur_integ, "error", "") if cur_integ is not None else ""),
            env_side_red=self._tests_env_side_red(cur_integ),
            env_red=(getattr(cur_integ, "env_red", None)
                     if cur_integ is not None else None),
            ticket_base_at=base_at, ticket_base_source=base_src,
            live_baseline_red=lb_red, live_baseline_green=lb_green,
            live_baseline_source=lb_src)

    async def _tests_round_account(self, tests_rounds, tests_exempt_rounds,
                                   cur_integ):
        """tests-fault 轮的计轮/豁免判定（串行与平行分支共用，单写者=纯函数
        tests_round_step）。返回 (tests_rounds, tests_exempt_rounds, counted, note)。

        - 环境面红（机械口径，两形态：场景级 env_fail / 装配级供给装配失败）→
          豁免不计，不发探针；装配级留痕点名供给面（gen11 打回③，报错精确纪律：
          不许把宿主供给事实说成「测试集连红」）；
        - 否则红项名单非空 → 发探针（串行复跑一轮）取证负载抖动；全绿=豁免；
        - 名单空 / 探针 error / 未证全绿 → 保守计轮（fail-closed 方向=多计不少计，
          绝不因探针缺席放行）。门关（旧历史）时调用方不进本方法，行为逐字同旧。
        """
        env_side_red = self._tests_env_side_red(cur_integ)
        jitter_green = False
        known_red = False
        probe_note = ""
        if not env_side_red:
            red_names = self._tests_red_names(cur_integ)
            # B 零新增红口径（260923）：闸 blockers 显式为空（isinstance 校验，
            # 缺席/畸形不豁免——保守计轮）=红面全为基线既有欠账/外部环境记录面，
            # 零新增红 → 本轮按「已知红」豁免不计轮、不发探针（重跑已知红不会绿，
            # 只会烧轮次到超限转人工）。
            _blockers = getattr(cur_integ, "blockers", None)
            if red_names and isinstance(_blockers, list) and not _blockers:
                known_red = True
                probe_note = ("已知红轮（红项=%s；闸 blockers 空=零新增红，全属"
                              "基线既有欠账/外部环境记录面）——不计入 tests-fault 轮次"
                              % ",".join(red_names))
            elif red_names and workflow.patched(TESTS_STREAK_PATCH_ID):
                try:
                    rraw = await workflow.execute_activity(
                        reprobe_red_scenarios,
                        ReprobeRedArgs(ticket_id=self.ticket_id,
                                       worktree=str(self.meta.get("worktree") or ""),
                                       names=red_names),
                        start_to_close_timeout=REPROBE_TO, retry_policy=RETRY)
                    probe = rraw if isinstance(rraw, ReprobeRedResult) \
                        else ReprobeRedResult(error="探针回执形状未知（旧 worker？）")
                except Exception as e:  # noqa: BLE001 —— 探针故障=保守计轮，不拦主链
                    # t260929-18：回执 error 可上票面 → 链下钻带上真实根因。
                    probe = ReprobeRedResult(
                        error="探针活动故障：%s: %s%s"
                              % (type(e).__name__, e, shared.exception_chain_note(e)))
                jitter_green = probe.all_green()
                probe_note = ("抖动复跑全绿（红项=%s；%d 跑全过）"
                              % (",".join(red_names), probe.ran)
                              if jitter_green else
                              "复跑未证全绿（%s）" % (probe.error or "有红"))
        nr, ne, counted, step_note = tests_round_step(
            "tests-fault", tests_rounds, tests_exempt_rounds,
            env_side_red=env_side_red, jitter_green=jitter_green,
            known_red=known_red)
        note = probe_note
        if not counted and env_side_red:
            if self._tests_supply_assembly_fail(cur_integ):
                # 装配级形态留痕点名供给面（要求③→票①要求①）：文案单写者=
                # shared.tests_supply_assembly_note（t260920-01，票面/UT 同源，
                # 防「留痕措辞」多写者漂移）；出路封面同族豁免面已带四条真出路。
                note = tests_supply_assembly_note(
                    getattr(cur_integ, "error", ""))
            else:
                note = "环境面红（产品红 0/闸拦 0/环境红 %d）" % (
                    int(getattr(cur_integ, "env_fail", 0) or 0))
        if counted:
            # 保守计轮也要把探针发现随留痕带上（红项不在册/复跑有红点名）——
            # 「不在册」假绿是本票 C1 钉的死源形态，票面必须可读。
            note = ("计轮（%s；%s）" % (step_note, probe_note)
                    if probe_note else "计轮（%s）" % step_note)
        return nr, ne, counted, note

    # ---------- structured red-light detail pins (t260915-01 ②) ----------
    def _pin_agent_refusal(self, res: StageResult) -> None:
        """agent 段闸拒绝的结构化明细 → meta['blocked_detail']（当前受阻明细）。
        只在 status=failed 且回执带 gate_refusal 时写；消费必经 sanitize（C7：跨
        活动边界数据不当契约面）；门关=零写（在途实例逐字不变）。清点=清点①②。"""
        if not getattr(self, "_detail_face_on", False):
            return
        if str(getattr(res, "status", "")) == "ok":
            return
        refusal = getattr(res, "gate_refusal", None)
        if not refusal:
            return
        detail = path_gates.sanitize_gate_refusal(refusal)
        if detail:
            self.meta["blocked_detail"] = detail

    # ---------- lane-dsh preflight refusal routing (t260916-28) ----------
    def _lane_dsh_refusal(self, res: Any) -> bool:
        """True = 本回执是泳道 .dsh 预检拒绝（failed + lane_dsh_* 命名空间的
        gate_refusal）。纯判定：绝不调 workflow.patched（@query 只读硬约束），
        门在各使用点。"""
        if str(getattr(res, "status", "")) != "failed":
            return False
        refusal = getattr(res, "gate_refusal", None)
        if not isinstance(refusal, dict):
            return False
        return str(refusal.get("reason_code") or "").startswith("lane_dsh_")

    def _agent_failed_why(self, res: Any, default: str = "") -> str:
        """agent 报失败的 blocked 文案单点路由（t260917-08 要求②）：环境型失败
        （status=failed + env_fail=true）→ 点名「agent 沙箱不可用（环境）」+
        env_reason 摘要 + 后续出路（worker 执行面承接，票不停摆）；其余回落既有
        「agent 报失败：」文案（逐字保留，零回归）。gate_refusal/lane_dsh/仲裁闸拒
        专道文案优先于 env：那些回执不挂 env 日志扫描（activity 侧 M1 裁定），
        env_fail 恒 False，结构上无竞争。畸形 res 不抛。"""
        why = agent_env_failed_reason(res)
        if why:
            return why
        return default or ("agent 报失败：%s"
                           % (str(getattr(res, "summary", "") or "")
                              or str(getattr(res, "status", "") or "")))

    async def _block_agent_failed(self, step_id: str, res: Any) -> None:
        """agent 报失败（业务裁决失败）在非 generic 站点的统一 blocked 落点
        （t260916-28）：文案经 _agent_failed_why 路由（t260917-08：环境型失败
        点名环境原因+出路，其余同款「agent 报失败：」逐字保留）；结构化明细
        已由 _pin_agent_refusal 在 _run_agent_step 单点钉上 meta.blocked_detail，
        此处不重复写。"""
        await self._blocked(step_id, self._agent_failed_why(res))

    def _conflict_failed_note(self, res: Any, note_fmt: str, round_no: int) -> str:
        """冲突消解站共用的「轮次前缀＋agent 失败归因」构造单点（t260922-18）：
        源码锁 test_f4（test_t260917_08_env_fail_signal）计 dev_lane 内联
        「agent 报失败：%s」字面量恰 2、_agent_failed_why 调用点恰 5——M3 冲突消解
        变体站与本票新增主同步消解站共用本 helper，两站文案逐字不回归（note_fmt
        传各站原格式串），杜绝再有站内联漏挂 env 归因。畸形 res 不抛（同
        _agent_failed_why 契约）。"""
        return note_fmt % (round_no, self._agent_failed_why(
            res, default="agent 报失败：%s" % ((res.summary or res.status)[:200])))

    async def _main_sync_abort(self, wt: str, round_no: int,
                               texts: Optional[Dict[str, str]] = None) -> str:
        """冲突消解失败后的 merge 复位（260929 宿主令直修；返回一句可上票面的结果文案）。

        为什么必须复位：半合并（UU）留在泳道里，下一轮主同步会在**同一批文件**上重新冲突，
        于是「同批文件反复冲突」守卫把票永久封死（t260929-22 实案连撞 3 轮，最后只能人工进
        泳道 git 收尾）。复位后下一轮从干净树重试——cap/同批守卫仍然封顶，不会变成活锁。
        失败/成功都**如实**进票面文案（不许把复位说成成功）。`texts`=文案覆写档
        （缺省=全车道中文历史原文逐字；轻道传英文守票面英文纪律）。"""
        _t = dict(texts or {})

        def _abort_text(key: str, default: str) -> str:
            return str(_t.get(key) or default)

        try:
            raw = await workflow.execute_activity(
                settle_conflict_resolution,
                ConflictSettleArgs(ticket_id=self.ticket_id, worktree=wt,
                                   base_ref="main", round_no=round_no, abort=True),
                start_to_close_timeout=SHORT, retry_policy=RETRY)
        except Exception as e:  # noqa: BLE001——复位失败不许遮蔽原失败原因
            return _abort_text(
                "reset_exception",
                "｜merge 复位尝试异常（%s: %s）——泳道可能仍是合并进行中态，需人工处置") % (
                type(e).__name__, e)
        res = raw if isinstance(raw, ConflictSettleResult) else ConflictSettleResult(
            ok=bool(getattr(raw, "ok", False)) if not isinstance(raw, dict) else bool(raw.get("ok")),
            error=str(getattr(raw, "error", "") if not isinstance(raw, dict)
                      else (raw.get("error") or "")))
        if res.ok:
            return _abort_text("reset_ok",
                              "｜merge 已复位（MERGE_HEAD 已清），下一轮主同步从干净树重试")
        return _abort_text(
            "reset_failed",
            "｜merge 复位失败：%s——泳道仍是合并进行中态，需人工处置") % (res.error or "未知")

    # ---------- t260917-08：移交命令债表（meta['env_handover_pending']） ----------
    # agent 段沙箱受限期间交接的验证命令，等后续机械段（run_integration_tests 的
    # worker 执行面）代跑。单源消费面：put 在 _run_agent_step 回执归一后，take/clear
    # 在集测段派单/销账点——防重复执行 + 债不静默蒸发（review C1 裁定①，方法化
    # 是为离线行为断言可直调，UT-G）。
    def _handover_debt_put(self, step_id: str, res: Any) -> None:
        """回执的移交命令入债表（_run_agent_step 单点调用）：
        - 有效命令 >0 → 同段旧债作废（同 stage 回执重写，防跨代重复累积），新命令替换入表；
        - 有效命令 =0 且本回执**无** env 信号 → 同段旧债销账：该段本轮亲自跑了验证
          （信号已消），旧命令再代跑=过期命令，失败命令会误伤仲裁；
        - 有效命令 =0 且 env_fail=True → 旧债保留（验证仍欠着，旧命令是唯一在册记录，
          清了=验证轨迹静默蒸发，违背 M4「不静默丢」）。
        畸形条目（非 dict）丢弃不记名——入表面只有 normalize 之后的合法回执可到，
        防御性丢弃不构成静默丢（源头上 dropped 已三面落面）。"""
        pending = [p for p in (self.meta.get("env_handover_pending") or [])
                   if isinstance(p, dict)]
        legs = list(getattr(res, "handover_runs", None) or [])
        if legs:
            kept = [p for p in pending if p.get("stage") != step_id]
            kept.extend({"stage": step_id, "name": str(l.get("name") or ""),
                         "cmd": str(l.get("cmd") or "")} for l in legs)
            self.meta["env_handover_pending"] = kept
            return
        if not getattr(res, "env_fail", False) and \
                any(p.get("stage") == step_id for p in pending):
            self.meta["env_handover_pending"] = [
                p for p in pending if p.get("stage") != step_id]
            self._log("%s 本轮亲自完成验证（无环境信号）→ 本段旧移交命令销账"
                      % step_id)

    def _handover_debt_legs(self) -> List[Dict[str, str]]:
        """集测段派单面的在册命令（只读，不销账——销账必须等命令真跑过：activity
        error 早退=命令没跑，留债下轮）。无 cmd 的残条不入单（执行面无法执行）。"""
        return [dict(p) for p in (self.meta.get("env_handover_pending") or [])
                if isinstance(p, dict) and p.get("cmd")]

    def _handover_debt_clear(self) -> None:
        """命令已真跑后的销账（集测段回执无 error 时调用）。命令败≠没跑——结果交
        仲裁/票面处置，此处只管「执行过」的账（防下一轮重复执行）。"""
        self.meta["env_handover_pending"] = []

    def _pin_settle_refusal(self, result: Any) -> None:
        """settle_lane join 点的闸拒绝明细（A3）：SettleLaneResult.gate_refusal 经
        sanitize 后写 blocked_detail；缺键/None=老回执→回落既有文本 why（零改动）。"""
        if not getattr(self, "_detail_face_on", False):
            return
        refusal = getattr(result, "gate_refusal", None)
        if not refusal:
            return
        detail = path_gates.sanitize_gate_refusal(refusal)
        if detail:
            self.meta["blocked_detail"] = detail

    def _pin_merge_red_detail(self, checks: Any, fallback_files: Any = None,
                              disposition: str = "") -> None:
        """merge_check 红灯的结构化明细（A4）：取首红项的既有结论（id/item/
        reason_code/files/next_action/detail）结构化写 blocked_detail——只做「已有
        结论结构化」，红绿判定与文案零改动。无红项时回落 fallback_files（conflict
        类的 conflict_files，D4 已逐文件在 checks 里，此处是畸形兜底）。三处调用点
        全部紧邻 _blocked（非 blocked 期由清点①②清空，R2 生命周期）。

        260927（宿主实报⑥可见性半边，**纯加法**）：旧实现只结构化**首红**，于是「同一轮
        里还有别的红、各属哪一类、各自该怎么处置」在票面上不可见——宿主实案：其红是
        「脏工作区」这一类（处置=提交/暂存/票面说明后 retry_qc），但读起来像「预演冲突不
        会自动消解」。现在**只加两个键**：`reds`（逐条红项：check_id/item/reason_code/
        class/next_action/files）与 `disposition`（本轮路由结论），既有键**逐字节不变**
        （blocked_detail 被 6 个测试文件 41 处引用，只加不改是硬约束）。"""
        if not getattr(self, "_detail_face_on", False):
            return
        red: Optional[Dict[str, Any]] = None
        for c in (checks if isinstance(checks, list) else []):
            if isinstance(c, dict) and c.get("green") is False:
                red = c
                break
        if red is None:
            if not (isinstance(fallback_files, list) and fallback_files):
                return
            detail = {"check_id": "merge_check", "item": "", "red": True,
                      "reason_code": "merge_conflict",
                      "files": [str(f) for f in fallback_files[:20]],
                      "next_action": "冲突消解失败转人工——按票面 blocked 文案处置",
                      "evidence": ""}
        else:
            files = red.get("files")
            detail = {
                "check_id": str(red.get("id") or "merge_check"),
                "item": str(red.get("item") or ""),
                "red": True,
                "reason_code": str(red.get("reason_code") or "merge_check_red"),
                "files": [str(f) for f in files[:20]]
                         if isinstance(files, list) else [],
                "next_action": str(red.get("next_action") or ""),
                "evidence": str(red.get("detail") or ""),
            }
            # 检查项自带的结构化明细（如自愈 settle 的闸拒绝）优先透传
            inner = path_gates.sanitize_gate_refusal(red.get("gate_refusal"))
            if inner:
                detail = inner
        # 260927 ⑥：逐条列出**全部**红项 + 红类 + 各自处置（纯加法，既有键不变）
        reds: List[Dict[str, Any]] = []
        for c in (checks if isinstance(checks, list) else []):
            if not (isinstance(c, dict) and c.get("green") is False):
                continue
            _cid = str(c.get("id") or "merge_check")
            _rc = str(c.get("reason_code") or "merge_check_red")
            _files = c.get("files")
            reds.append({
                "check_id": _cid,
                "item": str(c.get("item") or ""),
                "reason_code": _rc,
                # 红类=引擎本轮将怎么处置：预演冲突类红会（至多 N 轮）自动打回 implement
                # 消解；其余红一律 blocked 等人。判据与 dev_lane 的路由条件同源
                # （merge_rehearsal / merge_conflict 即 conflict 类）。
                "class": "auto_conflict" if (_cid == "merge_rehearsal" or _rc == "merge_conflict")
                         else "human",
                "next_action": str(c.get("next_action") or ""),
                "files": [str(f) for f in _files[:20]] if isinstance(_files, list) else [],
            })
        if isinstance(detail, dict):
            if reds:
                detail["reds"] = reds
            if disposition:
                detail["disposition"] = str(disposition)
        safe = path_gates.sanitize_gate_refusal(detail)
        if safe:
            self.meta["blocked_detail"] = safe

    # ---------- arbitrate settle-refusal guard (t260917-01) ----------
    async def _arbitrate_refusal_blocked(self, res: Any) -> bool:
        """仲裁段回执的 settle 闸拒唯一守门点（t260917-01 ①②③）。

        闸拒可辨 → blocked（主因=闸拒、「缺 verdict」只作双因从句、**不计格式
        轮次**）并返回 True；False = 非闸拒，调用方照旧走既有格式计数路径。

        为什么是单点方法而非两计数点就地 if：本票病根就是两计数点判据漂移
        （t260916-21 的「第 4 次」正是第二处形态），单点守门防再犯；「计数不增」
        由结构保证（守门 continue 先于计数语句）+ 源码锁钉死。
        判据与文案全部出自 shared.arbitrate_settle_refusal / arbitrate_blocked_reason
        纯函数（UT 直调）。结构化明细已由 _run_agent_step 内 _pin_agent_refusal 上
        meta['blocked_detail']；老回执无结构化键时文案自带 next_action 兜底。
        并行叉首轮汇合 settle 的闸拒不走本方法（下方 settle_lane 分支已直接
        blocked，语义相同、不计数）。"""
        refusal = arbitrate_settle_refusal(
            str(getattr(res, "summary", "") or ""), getattr(res, "gate_refusal", None))
        if refusal is None:
            return False
        await self._blocked("arbitrate", arbitrate_blocked_reason(refusal))
        return True

    # ---------- agent steps ----------
    async def _run_agent_step(self, step_id: str, previous_context: str = "",
                              settle: bool = True) -> Optional[StageResult]:
        """Run one agent activity (named after the step). Returns None = infra failure
        (caller turns it into blocked). settle=False: during a parallel fork, skip the
        trailing commit-on-behalf (the join point's settle_lane commits for both)."""
        st = self._step(step_id)
        gen = self._gen(step_id)
        self._enter(step_id)
        ws = stage_workspace(self.meta.get("workspace"), self.ticket_id)
        rfile = result_file_for(self.ticket_id, step_id, gen, ws)
        # gen is 0-based (read before _enter): the prompt's "Nth entry into this section"
        # uses the human-friendly 1-based form; filenames/args.gen stay 0-based (result
        # files start at gen0, keeping the idempotency anchor and disk naming continuous)
        prompt = build_stage_prompt(self.ticket_id, self.meta, st,
                                    list(self.meta.get("handoffs") or []), rfile, gen + 1,
                                    previous_context)
        # 宿主令 260930（light-lane，直修无票）：补述来源与标签走类属性（dev-lane 侧=FLOW_BRIEF + "dev-lane"，
        # 生成的文案逐字不变；轻道覆写两处得到自己的补述与标签）。
        brief = self.FLOW_BRIEF_SET.get(step_id)
        if brief:
            prompt += "\n%d. 本步契约（%s 流程约定）：%s" % (_prompt_next_no(prompt),
                                                      self.TEMPLATE_ID, brief)
        args = AgentStageArgs(
            ticket_id=self.ticket_id, stage_id=step_id, role=st.role, prompt=prompt,
            workspace=ws, result_file=rfile,
            log_file=agent_log_for(self.ticket_id, step_id, gen, ws),
            gen=gen,
            workflow_id=str(self.meta.get("workflow_id") or ""),
            previous_context=previous_context,
            skip_settle=not settle,
            # t260911-03 路径闸：settle 落点判「段 × 允许面 + 受保护名单」；
            # path_gate 随派单输入钉死（老在途票 meta 无此键=False，不追溯）
            write_set=list(self.meta.get("write_set") or []),
            base_ref=str(self.meta.get("base_ref") or ""),
            path_gate=bool(self.meta.get("path_gate")),
            path_gate_rules=dict(self.meta.get("path_gate_rules") or {}),
            # t260912-03：生效中的受保护授权结构化记录（who/issued/reason/scope 逐条
            # 下传，activity 据此豁免+记名点名；时效判定只在此处用 workflow.now()）
            authorizations=self._protected_authz_records())
        def _exec_once():
            return workflow.execute_activity(
                step_id, args,
                start_to_close_timeout=AGENT_TO, heartbeat_timeout=HEARTBEAT_TO,
                retry_policy=RETRY)

        # t260916-29 要求④：worker 停机把在飞活动取消 → 自动重跑一次（patched 门内，
        # 老 history 重放恒走旧分支；重跑仍失败则由各 catch 位落 blocked 文案）。
        raw = await retry_once_on_worker_termination(
            _exec_once,
            gate=workflow.patched(WORKER_SHUTDOWN_RETRY_PATCH_ID),
            on_retry=lambda e: self._log(
                "%s 段活动被 worker 停机取消，自动重跑一次（第 %d 次）"
                % (step_id, gen + 1)))
        # t260904-18 KI-049 gate 2: shape-preserving normalization of files_changed (the
        # shape travels with the receipt into the results dict, consumed by
        # _refresh_write_set_after_plan reading that dict).
        if isinstance(raw, StageResult):
            res = raw
        else:
            _fc, _fc_shape = normalize_files_changed(raw.get("files_changed"))
            _legs, _hshape, _hdrop = normalize_handover_runs(raw.get("handover_runs"))
            res = StageResult(
                status=str(raw.get("status") or "ok"),
                summary=str(raw.get("summary") or ""),
                report=str(raw.get("report") or ""),
                deliverables=[str(x) for x in (raw.get("deliverables") or [])],
                files_changed=_fc,
                files_changed_shape=_fc_shape,
                evidence=str(raw.get("evidence") or ""),
                # t260915-01 ②：结构化闸拒绝明细随回执（缺省 None=老回执/在途重放安全）
                gate_refusal=raw.get("gate_refusal"),
                # t260917-08：环境信号位随回执归一（第二解析点；缺省=老回执零改动）
                env_fail=bool(raw.get("env_fail") or False),
                env_reason=str(raw.get("env_reason") or ""),
                handover_runs=_legs,
                handover_dropped=_hdrop)
        self.results[step_id] = {
            "status": res.status, "summary": res.summary, "report": res.report,
            "deliverables": list(res.deliverables),
            "files_changed": list(res.files_changed),
            "files_changed_shape": res.files_changed_shape,
            "evidence": res.evidence, "gen": gen,
            # t260917-08：环境信号上台面（票面可见，不依赖开日志）；env_note=
            # env_note_for 单源注记（R4 空清单点名/M4 弃单摘要同源措辞）
            "env_fail": bool(res.env_fail), "env_reason": str(res.env_reason or ""),
            "env_note": env_note_for(res),
            "handover_runs": [dict(l) for l in (res.handover_runs or [])],
            "handover_dropped": list(res.handover_dropped or [])}
        # t260917-08（review C1 裁定①）：移交命令入 meta['env_handover_pending'] 债表
        # ——单源消费面（集测段拾取后销账，防重复执行）；put 内含同段回执重写替换
        # 与「本轮亲自完成验证→旧命令销账」两支（方法体见 _handover_debt_put）。
        self._handover_debt_put(step_id, res)
        if self.results[step_id]["env_note"]:
            self._log("%s 环境注记：%s" % (step_id, self.results[step_id]["env_note"]))
        if res.handover_dropped:
            self._log("%s 移交命令弃单（畸形记名不执行）：%s"
                      % (step_id, "; ".join(res.handover_dropped)))
        # t260915-01 ②（A2）：闸拒绝的结构化明细随回执上台面——单点覆盖全部
        # 「agent 报失败」blocked 调用点（~15 处零改动）；清点=_blocked wake（①）+
        # _enter（②）双保险（R2 生命周期：非 blocked 期恒空）。
        self._pin_agent_refusal(res)
        # t260912-03：回执里的 path_gate_authz_used= 机读键 → 授权消费留痕（只在真
        # 豁免时键在场；无键不记——防「用过」被恒真伪造）
        self._record_authz_uses(res.evidence, step_id)
        # KI-003: yield point inside the stage-transition mutation burst — yields the
        # event loop between the results bookkeeping and the following
        # _finish/_handoff/refresh_write_set mutation cluster, so a queued snapshot
        # query is no longer choked to timeout by the whole synchronous burst (root
        # cause of the workbench left column showing only ids in its transition window).
        await self._breathe()
        return res

    # ---------- rework ----------
    def _safe_phase(self, *candidates: str) -> str:
        """候选相位 → 第一个**可进入**的（260930）：绝不把空串/未知值交回主循环。

        主循环尾对未知相位 raise＝打断工作流实例（票不可查、不可恢复，nusuyou t260929-28
        实案）。所以这里做最后一道兜底：候选（fallback / meta 现步）逐个验，全非法 ⇒
        `REWORK_PHASE_FALLBACK`（arbitrate 人门），并**响亮留痕**（refused + _log），
        夹相位这件事本身要能在票面/审计里看见，不静默。"""
        for c in candidates:
            if c and c in PHASE_MAIN_CHAIN and c != "done":
                return c
        self.refused.append({"who": "", "want": "phase-clamp",
                             "why": "候选相位全部非法 %r → 夹到 %s"
                                    % (candidates, REWORK_PHASE_FALLBACK)})
        self._log("相位兜底：候选 %r 全部非法（空串/未知）→ 夹到 %s（绝不把空值交回主循环）"
                  % (candidates, REWORK_PHASE_FALLBACK))
        return REWORK_PHASE_FALLBACK

    def _auto_rework(self, target: str, note: str, who: str, fallback: str) -> str:
        """Internal/unified send-back landing: validates target/fallback ∈
        PHASE_MAIN_CHAIN (except done). Valid → the five meta fields + _touch + _log +
        _mark(target,'rework'), returns target; refused → refused bookkeeping + log,
        returns fallback (if fallback is invalid too, fall back to the current meta
        value — an invalid value must never flow back into the main loop, or "unknown
        stage" would raise).
        role uses the explicit PHASE_MAIN_ROLES mapping, **never _step(target)** (the
        three vocabulary values outside STAGES would make _step raise and wedge the
        workflow)."""
        if target == "done" or target not in PHASE_MAIN_CHAIN:
            why = ("终态不可为打回目标" if target == "done"
                   else "目标步不在打回词表 PHASE_MAIN_CHAIN")
            self.refused.append({"who": who, "want": "rework(%s)" % target,
                                 "why": why})
            self._log("rework 拒绝：%s（%s）" % (why, who))
            if workflow.patched(UNKNOWN_PHASE_BLOCK_PATCH_ID):
                return self._safe_phase(fallback, str(self.meta.get("stage") or ""))
            return fallback if fallback in PHASE_MAIN_CHAIN else \
                str(self.meta.get("stage") or fallback)
        if fallback == "done" or fallback not in PHASE_MAIN_CHAIN:
            self.refused.append({"who": who,
                                 "want": "rework(%s) fallback(%s)" % (target, fallback),
                                 "why": "fallback 不在打回词表（纯防呆，字面量不应出现）"})
            self._log("rework 拒绝：fallback %r 非法，停 meta 现步（%s）" % (fallback, who))
            if workflow.patched(UNKNOWN_PHASE_BLOCK_PATCH_ID):
                return self._safe_phase(str(self.meta.get("stage") or ""), fallback)
            return str(self.meta.get("stage") or fallback)
        self.meta["stage"] = target
        self.meta["role"] = PHASE_MAIN_ROLES[target]
        self.meta["status"] = "rework"
        self.meta["stage_state"] = "awaiting"
        self.meta["last_rework_note"] = note
        self._touch()
        self._log("rework: %s（回 %s）——%s" % (note, target, who))
        self._mark(target, "rework", "%s（%s）" % (note, who))
        return target

    def _apply_rework(self, fallback: str) -> str:
        """Landing for an external rework signal: consume the signal first (refusals
        consume it too), then delegate to _auto_rework (single source for the
        bookkeeping). Returns the target step id (invalid target → refusal note, stay on
        the current step)."""
        req = self._rework
        self._rework = None
        target = req.target_stage or fallback
        if target in ("ui_evidence",):
            # pre-run-next-ticket / UI screenshot evidence are not phase main-chain steps
            # (run inline in the merge and implement branches respectively) and accept no
            # rework — otherwise phase would land on a step with no orchestration and the
            # main loop would raise "unknown stage"
            self.refused.append({"who": req.who, "want": "rework(%s)" % target,
                                 "why": "%s 非主链步，不接受 rework" % target})
            self._log("rework 拒绝：%s 非主链步（%s）" % (target, req.who))
            return fallback
        return self._auto_rework(target, req.note, req.who, fallback)

    # ---------- rework 消费（t260916-19 ①：门内新路径，别名直达 + 显式拒收） ----------
    def _consume_rework(self, fallback: str) -> Tuple[str, Optional[str], str]:
        """rework 信号的消费与落地（门=REWORK_ESCAPE_PATCH_ID；门关走 _apply_rework
        旧路径逐字不变，本方法不触达）。

        返回 (phase, edge, refusal_note)：
          - 正常：phase=落点相位、edge=None（词表内目标）或边名（别名落点，调用方
            重置对应边标记）、refusal_note=""；
          - 拒收：("", None, 拒收文案)——调用方必须显式 blocked 点名，绝不静默回落
            fallback 原地复判（「信号回执成功 + 原地空转」正是 t260916-11 死结的
            观感根因）。

        信号消费纪律与 _apply_rework 同款：先消费（refused 也消费，不残留），再判定。
        留痕保原始目标（review C3）：别名落点的 _mark/_log/last_rework_note 全部
        内嵌 rework(to_stage=<原始目标>)，role 写原始目标本职角色（design 边重跑的
        执行 agent 本就按该段派 integration role；落点相位的 developer role 不适合
        本场景的审计语义）。"""
        req = self._rework
        self._rework = None
        target = req.target_stage or fallback
        if target in ("ui_evidence",):
            why = "%s 非主链步，不接受 rework" % target
            self.refused.append({"who": req.who, "want": "rework(%s)" % target,
                                 "why": why})
            self._log("【rework 拒收】%s 非主链步（%s）" % (target, req.who))
            return "", None, ("【rework 拒收】目标 %s 不可打回：%s" % (target, why))
        alias = REWORK_STAGE_ALIASES.get(target)
        if alias is not None:
            landing, edge = alias
            orig = "rework(to_stage=%s)" % target
            self.meta["stage"] = landing
            self.meta["role"] = self._step(target).role
            self.meta["status"] = "rework"
            self.meta["stage_state"] = "awaiting"
            self.meta["last_rework_note"] = "%s——%s（%s）" % (orig, req.note, req.who)
            self._touch()
            self._log("rework: %s——%s（%s）→ 落点 %s（%s 边重跑，另一边结果保留）"
                      % (orig, req.note, req.who, landing, edge))
            self._mark(landing, "rework", "%s——%s（%s）" % (orig, req.note, req.who))
            return landing, edge, ""
        if target == "done" or target not in PHASE_MAIN_CHAIN:
            why = ("终态不可为打回目标" if target == "done"
                   else "目标步不在打回词表（可打回=%s；integration/ 段可用别名 "
                        "to_stage=design_integration_tests）"
                        % "、".join(sorted((PHASE_MAIN_CHAIN - {"done"}) & REWORK_ADMISSIBLE_PHASES)))
            self.refused.append({"who": req.who, "want": "rework(%s)" % target,
                                 "why": why})
            self._log("【rework 拒收】%s（%s）" % (why, req.who))
            return "", None, ("【rework 拒收】目标 %s 不可打回：%s" % (target, why))
        new_phase = self._auto_rework(target, req.note, req.who, fallback)
        if new_phase != target:
            # 防御：_auto_rework 拒绝（fallback 非法等内部形态）——同款显式拒收，
            # 拒收记录已由 _auto_rework 落账。
            return "", None, ("【rework 拒收】目标 %s 不可打回（落地校验未过，"
                              "见 refused 记录）" % target)
        return target, None, ""

    def _gate_refusal_repeat_suffix(self, files: Any) -> str:
        """t260916-19 A 尾巴：同批闸拒文件第 N 次复判的点名后缀（retry_qc 无变化
        重跑不改变结果——每次信号空转一轮 settle 正是实案观感；首次判红返回 ""）。"""
        key = tuple(str(f) for f in files) if isinstance(files, (list, tuple)) else ()
        if key and key == getattr(self, "_last_gate_refusal_files", None):
            self._gate_refusal_repeat = getattr(self, "_gate_refusal_repeat", 1) + 1
        else:
            self._last_gate_refusal_files = key
            self._gate_refusal_repeat = 1
        if self._gate_refusal_repeat > 1:
            return ("（第 %d 次同批复判：工作区无变化，retry_qc 不会改变结果——"
                    "按回执出路处置越权文件或回 main 侧走票）" % self._gate_refusal_repeat)
        return ""

    # ---------- 两条泳道共用的段级 helper（宿主令 260930（light-lane，直修无票）：纯抽块，语义零变化） ----------
    async def _prepare_workspace_step(self) -> bool:
        """工作空间准备（循环到就绪为止；返回 True=已就绪。失败期间在 _blocked 等人，
        醒来重试——原 run() 的 `while True: … break` 语义整段搬进本方法）。

        宿主令 260930（light-lane，直修无票）：本方法的内容**逐字**取自 DevLaneWorkflow.run() 原第一块
        （同一 lane_workspace_gate_error 前置判、同一 shared.build_workspace_prep 单点
        构造、同一 prepare_workspace 活动、同一 blocked 文案、同一 rework 处置），只把
        「循环 + break」写成「循环 + return True」——命令序列（活动入参/顺序/等待点）与
        抽取前逐字相同，dev-lane 的 run() 改为一行 `await self._prepare_workspace_step()`，
        对在途实例重放同样是同一串命令。轻道（light_lane.py）直接复用本方法。

        布尔返回面保留（恒 True）：两条泳道的调用点写法一致，将来加「放弃」出路时
        调用方无需改形状。"""
        while True:
            # Lane field gate (t260824-04/-10/-11): the creation path validates at the
            # single ticket-start point; this catches bypasses from "old payloads /
            # future new entry points" — a lane=worktree payload with missing fields is
            # treated as a failed receipt and goes blocked, never handed to the activity
            # to silently fall back to the main tree or a temp dir.
            gate = lane_workspace_gate_error(self.meta)
            if gate:
                raw = WorkspacePrepResult(ok=False, kind="config", action="rejected",
                                          path="", error=gate)
            else:
                # t260910-08: construction collapsed onto the single point
                # (shared.build_workspace_prep) — the previous inline copy was the
                # incident's root cause (repo_worktrees read an always-empty meta key;
                # write_set/project_root were never fed → prepare_workspace's three
                # read rings all empty → multi-repo ticket materialized single-repo).
                prep = build_workspace_prep(self.ticket_id, self.meta)
                raw = await workflow.execute_activity(
                    prepare_workspace, prep, start_to_close_timeout=SHORT, retry_policy=RETRY)
            res = raw if isinstance(raw, WorkspacePrepResult) else WorkspacePrepResult(
                ok=bool(raw.get("ok", True)), kind=str(raw.get("kind") or ""),
                action=str(raw.get("action") or ""), path=str(raw.get("path") or ""),
                error=str(raw.get("error") or ""))
            self.meta["workspace_prep"] = {"ok": res.ok, "kind": res.kind,
                                           "action": res.action,
                                           "path": res.path, "error": res.error}
            self._touch()
            if res.ok:
                self._mark("workspace", "ready",
                           "prepare_workspace: %s/%s" % (res.kind, res.action))
                return True
            await self._blocked("workspace", "工作空间准备失败：%s" % (res.error or "未知"))
            if self._rework is not None:
                # target stage is taken over by the main loop
                self._apply_rework(self.STAGES[0].id)

    async def _ui_evidence_step(self) -> str:
        """UI 票截图证据（条件步；非 UI 票零活动）。

        宿主令 260930（light-lane，直修无票）：内容**逐字**取自 DevLaneWorkflow.run() 的汇合点块（同一
        ui_changed_paths 判定活动、同一 prepare_ui_evidence、同一 self.results
        ['ui_evidence'] 记账、同一软失败不拦主链口径、同一两条 patched 门——老在途实例
        重放的命令序列逐字不变）。返回 ui_ctx（给下游 agent 上下文/票面用；非 UI 票或
        失败时为空或含「证据缺失」说明）。"""
        # UI evidence (UI tickets): the worker runs the isolated bench after the
        # commit and before the mechanical tests (soft failures caught by the gate).
        # UI-ticket judgment (t260904-13 KI-044): inside the patched gate the diff
        # source switches — the activity shares a source with merge_check 3.6;
        # unpatched (existing instances replaying) keeps the declaration-based old
        # branch, with the command sequence strictly matching old history. The old
        # chain tail (integration_review branch) freezes the old judgment.
        ui_ctx = ""
        ui_is_ticket = False
        ui_judge_note = ""
        if workflow.patched(UI_EVIDENCE_PATCH_ID):
            if workflow.patched(UI_DIFF_PATCH_ID):
                try:
                    craw = await workflow.execute_activity(
                        ui_changed_paths,
                        UiChangedPathsArgs(
                            ticket_id=self.ticket_id,
                            worktree=str(self.meta.get("worktree") or ""),
                            branch=str(self.meta.get("branch") or ""),
                            base_ref=str(self.meta.get("base_ref") or "")),
                        start_to_close_timeout=UI_EVIDENCE_TO,
                        retry_policy=RETRY)
                    cp = craw if isinstance(craw, UiChangedPathsResult) else UiChangedPathsResult(
                        ui_paths=[str(x) for x in (craw.get("ui_paths") or [])],
                        detail=str(craw.get("detail") or ""))
                    ui_is_ticket = bool(cp.ui_paths)
                    ui_judge_note = cp.detail or (
                        "diff 未命中 UI 路径 → 非 UI 票，跳过实拍" if not ui_is_ticket else "")
                except Exception as e:
                    # fail-closed: an activity failure is treated as "UI ticket
                    # unproven" (capture anyway, the gate catches it)
                    ui_is_ticket = True
                    ui_judge_note = ("ui_changed_paths 故障 fail-closed：%s: %s%s"
                                     % (type(e).__name__, e,
                                        shared.exception_chain_note(e)))
                self._log("UI 票判定（diff 源）：%s" % ui_judge_note)
            else:
                # Unpatched branch (existing instances replaying): the
                # declaration-based judgment is kept as-is
                ui_is_ticket = is_ui_write_set(list(self.meta.get("write_set") or []))
        if workflow.patched(UI_EVIDENCE_PATCH_ID) and ui_is_ticket:
            try:
                uiraw = await workflow.execute_activity(
                    prepare_ui_evidence,
                    UiEvidenceArgs(ticket_id=self.ticket_id,
                                   worktree=str(self.meta.get("worktree") or "")),
                    start_to_close_timeout=UI_EVIDENCE_TO, retry_policy=RETRY)
                ui = uiraw if isinstance(uiraw, UiEvidenceResult) else UiEvidenceResult(
                    ok=bool(uiraw.get("ok")), shots=[str(x) for x in (uiraw.get("shots") or [])],
                    shot_lines=[str(x) for x in (uiraw.get("shot_lines") or [])],
                    detail=str(uiraw.get("detail") or ""), skipped=bool(uiraw.get("skipped")))
                self.results["ui_evidence"] = {
                    "status": "ok" if ui.ok else "failed",
                    "summary": ui.detail, "report": "", "deliverables": list(ui.shots),
                    "files_changed": [],
                    "evidence": (("【UI 票判定（diff 源）】%s\n" % ui_judge_note)
                                 if ui_judge_note else "") + ui.detail,
                    "gen": 0}
                if ui.ok:
                    ui_ctx = "【UI 截图证据（.sandbar/screenshots/，验收必看）】\n" + \
                        "\n".join("- %s" % ln for ln in (ui.shot_lines or ui.shots))
                else:
                    ui_ctx = "【UI 截图证据缺失】%s（验收按「无截图证据」如实记录）" % ui.detail
                self._log("prepare_ui_evidence：%s" % (ui.detail or ("ok" if ui.ok else "failed")))
            except Exception as e:  # infra failure: noted, main chain unaffected, merge_check gate catches it
                # t260929-18：ui_ctx 进 agent 上下文/人审面 → 链下钻。
                ui_ctx = "【UI 截图证据缺失】activity 故障：%s: %s%s" % (
                    type(e).__name__, e, shared.exception_chain_note(e))
                self._log("prepare_ui_evidence 故障（不拦主链，merge_check 闸兜底）：%s" % str(e)[:200])
        return ui_ctx

    # ---------- main flow (direct activity orchestration) ----------
    async def _main_sync_before_gate(self, conflict_rounds: int,
                                     prev_conflict_files: List[str],
                                     texts: Optional[Dict[str, str]] = None
                                     ) -> Dict[str, Any]:
        """机器验证前把 main 并进泳道一次（宿主 260922-18 拍板此机制的**唯一实现**）。

        为什么必须（宿主 260930 直修令，根因级）：闸在**泳道自己的 worktree** 里跑
        `integration/run_scenarios.py`，而泳道=开票那一刻从 main 建的快照——**开票之后
        落进 main 的修复都不会出现在泳道里**。真票 t260930-09 实测：4 条 pool-exclude
        假红的根因是 main 上才提交的夹具清理修，泳道那份夹具还是旧的；闸于是把
        「main 的旧账」判成 lane-only（本票的账），等于让 agent 去修不在它身上的东西。
        同步一次 ⇒ **被验证树 = 被合并树**，闸的归因才落回真正的责任人。

        调用点纪律（本块抽自 dev-lane run() 原内联块，命令序列/入参/等待点逐字不变）：
          · 唯一同位点=跑闸相位入口：**0-commit 前置检查之后**（同步落下的 merge 提交会
            使 lane_commits +1，放前面=给「实现未落盘」放水——判据不放宽）、**跑闸之前**
            （同轮直线衔接=每轮验证前同步一次、必重跑不复用旧报告）；
          · 已追平=`up_to_date` 快路径（is-ancestor，零动作幂等）；每轮一次；
          · 冲突 → 既有「worker 起合并（prep 留现场）→ agent 解冲突 → worker 代提交」
            回路 → `_auto_rework("implement", …)`（实现段适配 main 变更，KI-082 清偿）；
            不可达/非冲突失败 → 响亮 blocked 转人工，绝不静默跳过同步继续验证。
        **判据零改动**：本 helper 只改「被验证的树」——不改任何闸判据、不改归因口径、
        不放宽任何理由；它不判红绿、不决定出路（blocked/rework 全由上面那两条既有回路给）。

        多仓泳道逐仓同步（`meta.repo_worktrees` 唯一真源；单仓=泳道根一条）。

        返回（调用方据此推进主循环，语义与旧内联块逐字一致）：
          `stop` ""=继续跑闸；"blocked"/"rework"=已处置（调用方 `continue`）；
          `phase` 非空=落点相位（`_auto_rework` 给）；`sync_s`=同步活动墙钟秒（计时面）；
          `conflict_rounds`/`prev_conflict_files`=跨轮反例守卫状态（回填局部量）。

        `texts`=票面/提示文案覆写档（缺省=全车道中文历史原文逐字；轻道传英文以守
        「票面英文」纪律——**机制字面量与命令序列不动**，只换人读的那几句）。
        """
        T = dict(texts or {})

        def text(key: str, default: str) -> str:
            """文案单点：优先调用方覆写档（轻道=英文），缺省回落历史原文。"""
            return str(T.get(key) or default)

        _sync_stop = ""      # ""=继续本相位跑闸；"blocked"/"rework"=已处置，跳出
        _sync_phase = ""     # stop=="rework" 时由调用方赋给 phase（落点相位）
        _sync_s = 0.0        # 本 helper 花在同步活动上的墙钟秒（调用方累计进计时面）
        # 多仓泳道逐仓同步（meta.repo_worktrees 唯一真源；单仓=泳道根一条）
        _sync_targets = [
            {"name": str(e.get("name") or str(e.get("repo") or "") or "root"),
             "rel": str(e.get("repo") or ""),
             "branch": str(e.get("branch") or "")}
            for e in (self.meta.get("repo_worktrees") or [])
        ] or [{"name": "root", "rel": "",
               "branch": str(self.meta.get("branch") or "")}]
        _sync_outcomes: List[str] = []
        for _st in _sync_targets:
            _wt_base = str(self.meta.get("worktree") or "")
            _st_wt = (_wt_base + "/" + _st["rel"]) if _st["rel"] else _wt_base
            _sync_t = self._now_epoch()   # t260925-12
            praw = await workflow.execute_activity(
                prepare_conflict_resolution,
                ConflictPrepArgs(ticket_id=self.ticket_id,
                                 worktree=_st_wt,
                                 branch=_st["branch"],
                                 base_ref="main"),
                start_to_close_timeout=SHORT, retry_policy=RETRY)
            _sync_s += max(0, self._now_epoch() - _sync_t)
            prep = praw if isinstance(praw, ConflictPrepResult) else ConflictPrepResult(
                ok=bool(praw.get("ok")),
                conflict_files=[str(x) for x in (praw.get("conflict_files") or [])],
                merge_output=str(praw.get("merge_output") or ""),
                already_clean=bool(praw.get("already_clean")),
                error=str(praw.get("error") or ""),
                # t260922-18 新证据键：dict 回退重建点漏写=证据静默丢，同批补齐
                target_sha=str(praw.get("target_sha") or ""),
                lane_head=str(praw.get("lane_head") or ""),
                up_to_date=bool(praw.get("up_to_date")))
            _tag = _st["name"]
            _mode = ("up_to_date" if prep.up_to_date
                     else "merged" if prep.already_clean else "conflict")
            _sync_outcomes.append("%s=%s@%s" % (
                _tag, _mode, (prep.target_sha or "？")[:7]))
            if not prep.ok:
                # 不可达/非冲突失败：响亮转人工，绝不静默跳过同步继续验证
                await self._blocked(
                    "run_integration_tests",
                    text("unreachable",
                         "主同步失败（转人工，不静默跳过同步——否则被验证树≠被合并树）："
                         "%s%s")
                    % (prep.error or "未知",
                       ("｜各仓同步结果：%s" % "、".join(_sync_outcomes))
                       if len(_sync_targets) > 1 else ""))
                _sync_stop = "blocked"
                break
            if prep.conflict_files:
                # 走既有消解回路：guard（cap/同批）→ agent 解标记 → settle 代提交
                conflict_rounds += 1
                # files_sig 带仓标识：不同仓的同名文件不构成「同批反复冲突」
                files_sig = sorted("%s:%s" % (_tag, f) for f in prep.conflict_files)
                _route = main_sync_conflict_route(
                    conflict_rounds, files_sig, prev_conflict_files,
                    MAX_CONFLICT_ROUNDS)
                if _route.startswith("blocked:"):
                    await self._blocked("run_integration_tests",
                                        _route.split(":", 1)[1])
                    _sync_stop = "blocked"
                    break
                prev_conflict_files = files_sig
                self._log("主同步检出 merge 冲突（%s，第 %d/%d 轮），走既有消解回路：%s"
                          % (_tag, conflict_rounds, MAX_CONFLICT_ROUNDS,
                             "、".join(prep.conflict_files)[:200]))
                self._handoff("run_integration_tests",
                              text("resolve_round",
                                   "主同步冲突消解第 %d 轮（%s）：%s")
                              % (conflict_rounds, _tag,
                                 "、".join(prep.conflict_files)[:200]))
                # 变量名 msolve_ctx（非 solve_ctx）：selfcheck E-1 用
                # 「_run_agent_step("implement", solve_ctx)」首次出现锚定
                # merge_check 分支的 prep→implement→settle 串行——主同步
                # 子回路同名会让该锚错位（t260922-18 实测），改名避开。
                msolve_ctx = (
                    text("conflict_ctx",
                         "【主同步冲突消解轮 gen%d/上限%d】本轮不是功能开发：机械验证前的主同步"
                    "把 main 并进泳道（仓 %s），worker 已跑过 git merge main，以下文件"
                    "留有冲突标记（<<<<<<< 泳道 / ======= / >>>>>>> main）：\n%s\n"
                    "merge 输出摘要（ours=泳道 / theirs=main）：\n%s\n"
                    "任务：逐个文件解掉冲突标记，保持两边语义（t260825-03 同款）；"
                    "只动冲突文件，不做无关改动；**不要 git commit**"
                         "（你交付结果文件后 worker 会代落盘合并提交）。解完写结果文件交付。")
                    % (conflict_rounds, MAX_CONFLICT_ROUNDS, _tag,
                       "\n".join("- %s" % f for f in prep.conflict_files),
                       (prep.merge_output or "（无输出）")[:1200]))
                try:
                    cres = await self._run_agent_step("implement", msolve_ctx)
                except Exception as e:
                    _why = format_agent_stage_failure(
                        self.ticket_id, "implement", e,
                        gen=self._gen("implement"))
                    if workflow.patched(MAIN_SYNC_RECOVERY_PATCH_ID):
                        # 260929：先把 merge 复位再转人工（不给下一轮留 UU 死锁）
                        _why += await self._main_sync_abort(_st_wt, conflict_rounds, T)
                        prev_conflict_files = []
                        conflict_rounds = 0
                    await self._blocked("implement", _why)
                    _sync_stop = "blocked"
                    break
                if cres.status != "ok":
                    # 归因构造走 _conflict_failed_note 单点（t260922-18：
                    # 与 M3 变体站共用，源码锁字面量/调用计数恒 2/5）
                    _why = self._conflict_failed_note(
                        cres,
                        text("agent_failed_fmt", "主同步冲突消解第 %d 轮：%s"),
                        conflict_rounds)
                    if workflow.patched(MAIN_SYNC_RECOVERY_PATCH_ID):
                        _why += await self._main_sync_abort(_st_wt, conflict_rounds, T)
                        prev_conflict_files = []
                        conflict_rounds = 0
                    await self._blocked("implement", _why)
                    _sync_stop = "blocked"
                    break
                sraw = await workflow.execute_activity(
                    settle_conflict_resolution,
                    ConflictSettleArgs(ticket_id=self.ticket_id,
                                       worktree=_st_wt,
                                       branch=_st["branch"],
                                       base_ref="main",
                                       round_no=conflict_rounds),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                sres = sraw if isinstance(sraw, ConflictSettleResult) \
                    else ConflictSettleResult(
                        ok=bool(sraw.get("ok")),
                        commit=str(sraw.get("commit") or ""),
                        remaining_files=[str(x) for x in
                                         (sraw.get("remaining_files") or [])],
                        error=str(sraw.get("error") or ""))
                if not sres.ok:
                    _why = ("仍有未解冲突文件：%s" % "、".join(sres.remaining_files[:10])
                            ) if sres.remaining_files else (sres.error or "未知")
                    await self._blocked(
                        "run_integration_tests",
                        text("settle_unconverged",
                             "主同步冲突消解第 %d 轮未收敛（worker 代落盘校验未过），"
                             "转人工处置：%s。工作区现为合并进行中态——人工解冲突后发 "
                             "rework 回 implement 续解，或泳道内 git merge --abort "
                             "复位后发 retry_qc 重验") % (conflict_rounds, _why))
                    _sync_stop = "blocked"
                    break
                self._log("主同步冲突消解第 %d 轮落盘 %s（%d 个文件），回实现段适配 main 变更"
                          % (conflict_rounds, sres.commit, len(prep.conflict_files)))
                self.meta["main_sync"] = {
                    "mode": "merged", "main_sha": prep.target_sha,
                    "lane_head": sres.commit, "scope": _tag,
                    "detail": "；".join(_sync_outcomes),
                    "note": "冲突经既有消解回路落盘"}
                # 回实现段（宿主指定）：main 增量可能与票改动有语义耦合，
                # 实现段适配后经 join 重走验证；下一轮主同步已追平=快路径
                _sync_phase = self._auto_rework(
                    "implement",
                    text("back_to_implement",
                         "主同步冲突消解完成（第 %d 轮），回实现段适配 main 变更")
                    % conflict_rounds,
                    who="workflow", fallback="run_integration_tests")
                _sync_stop = "rework"
                break
            self.meta["main_sync"] = {
                "mode": _mode, "main_sha": prep.target_sha,
                "lane_head": prep.lane_head, "scope": _tag,
                "detail": "；".join(_sync_outcomes)}
            self._log(text("synced_log", "主同步（%s）：%s") % (
                _tag, main_sync_note(self.meta["main_sync"]) or "回执缺证据键（点名）"))

        return {"stop": _sync_stop, "conflict_rounds": conflict_rounds,
                "prev_conflict_files": prev_conflict_files, "phase": _sync_phase,
                "sync_s": _sync_s}

    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)

        # 1) prepare_workspace (code, no agent; failure → blocked waiting for retry/rework)
        # 宿主令 260930（light-lane，直修无票）：原内联块抽为共用 helper（循环在 helper 内，命令序列逐字不变）
        await self._prepare_workspace_step()

        # t260904-18 KI-050 gate 3: preload the ui_evidence declaration (the disk read
        # happens in an activity, the workflow only reads meta = replay safe).
        # Soft-fail rule: an activity exception does not stop the main chain — a missing
        # meta key is handled at the consumer (the review_gate patched branch) under the
        # "declaration absent" reading, with a note; malformed declarations turn
        # fail-closed red when merge_check 3.6 loads them, here we only leave a note.
        if workflow.patched(UI_EVIDENCE_DECL_PATCH_ID):
            try:
                draw = await workflow.execute_activity(
                    ui_evidence_decl,
                    UiEvidenceDeclArgs(ticket_id=self.ticket_id,
                                       worktree=str(self.meta.get("worktree") or "")),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                d = draw if isinstance(draw, UiEvidenceDeclResult) else UiEvidenceDeclResult(
                    mode=str(draw.get("mode") or "absent"),
                    dirs=[str(x) for x in (draw.get("dirs") or [])],
                    note=str(draw.get("note") or ""))
                self.meta["ui_evidence_dirs"] = list(d.dirs) if d.mode == "ok" else []
                self.meta["ui_evidence_decl_mode"] = d.mode
                self.meta["ui_evidence_decl_note"] = d.note
                self._log("ui_evidence 声明预载：%s（%d 个目录）%s"
                          % (d.mode, len(d.dirs), d.note))
            except Exception as e:
                self._log("ui_evidence 声明预载失败（不拦主链，消费点按声明缺省兜底）：%s: %s"
                          % (type(e).__name__, e))

        phase = str(self.meta.get("stage") or "create_plan")
        plan_rounds = 0
        impl_rounds = 0
        impl_done = False                         # parallel fork: implement edge finished
        design_done = False                       # parallel fork: design_integration_tests edge finished
        code_rounds = 0                           # arbitrate code-fault send-backs to developer, cumulative
        # t260917-09：tests 上限=连续语义（定案，纠正本行旧「cumulative」孤例——注释与
        # shared.py 一致）。转移/复位单写者=tests_round_step 纯函数：
        #   复位点=verdict∈{pass, code-fault, 非法}/人工接受判决（伪 verdict="accept-reset"）
        #   /非迭代来源重进 run_integration_tests 段（tests_streak=False 时段入口）；
        #   豁免轮=tests-fault 但红项属环境面（cur_integ 机械口径）或抖动复跑全绿（探针）。
        tests_rounds = 0                          # consecutive tests-fault rounds judged by arbitrate
        tests_exempt_rounds = 0                   # consecutive exempted (not-counted) rounds（防活循环上限=MAX_TESTS_EXEMPT_ROUNDS）
        tests_streak = False                      # 本段是否由 tests-fault 迭代来源进入（段入口消费：False→复位计数）
        cur_integ = None                          # 本轮 IntegrationRunResult 快照（env_side_red/红项名单判据；段入口清）
        prev_red_names = []                       # t260923 D：上一轮红项名（定点复跑面来源；每跑后刷新）
        last_run_only = []                        # t260923 D：本轮跑面（空=全量；非空=定点——pass 收口拦截判据）
        run_only = []                             # t260923 D：本跑入参面（异常路径兜底定义）
        acc_rounds = 0                            # acceptance-walkthrough send-backs, cumulative
        arb_format_rounds = 0                     # in-section consecutive arbitrate outputs missing the
                                                  # verdict= marker（t260917-01：进 run_integration_tests
                                                  # 段复位，不跨 rework 累积——复位点见该段入口）
        # t260903-02 speedup 2: in-memory state for the arbitrate ∥ acceptance_walkthrough
        # parallel fork. Invariant: entering the run_integration_tests section resets all
        # of it in one place (each mechanical test run produces a fresh arbitration and a
        # fresh walkthrough) — this covers every loop, rework / tests-fault / code-fault,
        # so no scattered branch needs to set these.
        arb_done = False                          # arbitration edge finished
        acc_done = False                          # walkthrough edge finished
        arb_res = None                            # arbitration edge StageResult (judged once both edges are in)
        acc_res = None                            # walkthrough edge StageResult (consumed on pass)
        design_ctx = ""                           # context injected into design_integration_tests
        arb_ctx = ""                              # test results produced by run_integration_tests, injected
        ui_ctx = ""  # t260828-09: UI screenshot evidence (produced at the join, consumed by acceptance)
        conflict_rounds = 0                       # t260826-01: conflict auto-resolution rounds (cap MAX_CONFLICT_ROUNDS)
        prev_conflict_files: List[str] = []       # last round's conflict files (sorted set comparison)
        prev_ctx = ""
        ui_ctx = ""   # t260828-09: UI screenshot evidence list (produced at the join, consumed by the walkthrough)

        while phase != "done":
            # 段间暂停门（t260908-01，接线点，语义=TicketPauseMixin）：当前相位
            # （含在飞 activity）自然跑完后，每轮循环先过门——已暂停则停住等
            # resume，不推进下一相位。门在 rework 分支之前（显式语义：暂停期间
            # 到达的 rework 压在门口，resume 后先打回再派段）。
            await self._pause_gate()
            # t260928-13：主相循环每轮先冲账（同步 signal 里的迁移由本边界冲走）
            await self._ledger_flush()
            if self._rework is not None:
                fb = "implement" if phase == "parallel_impl_design" else phase
                # KI-024: a rework leaving a parallel period (target is a serial section)
                # must clear parallel_stages — otherwise the stale list pins edges that
                # already left on UI ▶ forever (one of two clearing paths, the other is
                # at the join point; the waiting-period contract is spelled out in the
                # failure-edge comments of each parallel branch).
                if phase in ("parallel_impl_design", "arb_acc_parallel"):
                    set_parallel_stages(self.meta, [])
                if getattr(self, "_rework_escape_on", False):
                    # t260916-19 ①（门内新路径）：别名直达目标段 / 显式拒收——拒绝
                    # 信号已被消费（不残留），blocked 点名后等 retry_qc 或新 rework，
                    # 绝不静默回落 fb 原地复判（t260916-11 死结观感根因）。
                    phase, edge, refusal_note = self._consume_rework(fb)
                    if refusal_note:
                        await self._blocked(fb, refusal_note)
                        continue
                    if edge == "design":
                        design_done = False  # 只重跑设计边（实现边结果保留在内存）
                else:
                    phase = self._apply_rework(fb)
                # KI-003: yield once after the rework bookkeeping burst (_auto_rework's
                # _log/_mark/_touch) so a queued snapshot query sees the post-rework state.
                await self._breathe()
                prev_ctx = str(self.meta.get("last_rework_note") or "")
                if workflow.patched(TESTS_STREAK_PATCH_ID):
                    # t260917-09：rework=非迭代来源边（方案 §2.4.3「rework 后重进复位」
                    # ——人审打回/验收打回都经此分支）。只翻 streak 标记：计数转移与
                    # 留痕仍归 run_integration_tests 段入口单点（下一拍 tests_streak
                    # 已 False → 那里复位并 _log「计数复位」）。
                    tests_streak = False
                if phase == "implement":
                    impl_done = False  # re-implement: the join point will commit for both again
                continue

            # 2) create_plan ⇄ review_plan
            if phase == "create_plan":
                try:
                    res = await self._run_agent_step("create_plan", prev_ctx)
                except Exception as e:
                    await self._blocked("create_plan", format_agent_stage_failure(
                        self.ticket_id, "create_plan", e, gen=self._gen("create_plan")))
                    continue
                prev_ctx = ""
                if res.status != "ok":
                    await self._blocked("create_plan", self._agent_failed_why(res))
                    continue
                self._finish("create_plan", by="developer-agent",
                             evidence=res.evidence or res.summary)
                self._handoff("create_plan", res.summary or "方案完成",
                              artifacts=res.deliverables, report=res.report)
                phase = "review_plan"
                continue

            if phase == "review_plan":
                try:
                    res = await self._run_agent_step("review_plan")
                except Exception as e:
                    await self._blocked("review_plan", format_agent_stage_failure(
                        self.ticket_id, "review_plan", e, gen=self._gen("review_plan")))
                    continue
                # t260903-02 speedup 3: three-verdict routing (a conditional pass
                # verdict=conditional does not count a send-back round, comments go
                # straight to implement); unpatched replays take the old ok/failed binary.
                if workflow.patched(REVIEW_CONDITIONAL_PATCH_ID):
                    rv = review_plan_route(
                        parse_review_plan_verdict(res.status, res.summary), plan_rounds)
                else:
                    rv = "parallel_impl_design" if res.status == "ok" else "create_plan"
                if rv.startswith("blocked:"):
                    await self._blocked("review_plan", rv.split(":", 1)[1])
                    continue
                if rv == "parallel_impl_design":
                    is_cond = (workflow.patched(REVIEW_CONDITIONAL_PATCH_ID)
                               and parse_review_plan_verdict(res.status, res.summary)
                               == "conditional")
                    self._finish("review_plan", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("review_plan",
                                  ("方案审读附条件放行：" if is_cond else "方案审读通过：")
                                  + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    if is_cond:
                        # Conditional pass: the change comments are injected into
                        # implement (reusing the previous_context channel, wording
                        # distinguishable from a send-back); no return to create_plan, no
                        # re-review, no send-back round counted.
                        self._log("review_plan 附条件放行（意见直通 implement）")
                        prev_ctx = ("【附条件放行·implement 执行项】review 意见"
                                    "（轻微瑕疵不改打回级，按条件执行）：\n%s"
                                    % (res.report or res.summary or "")).strip()
                    # t260829-07: plan finalized (conditional pass included) → refresh
                    # the write set. Reachability guard: this branch runs only when
                    # review_plan passes; a blocked create_plan leaves the main loop
                    # directly and can never arrive here in a bad state.
                    if workflow.patched(REFRESH_WRITE_SET_PATCH_ID):
                        self._refresh_write_set_after_plan()
                    if workflow.patched(INTEG_LOOP_PATCH_ID):
                        # New chain: parallel fork (implement ∥ design_integration_tests)
                        impl_done = False
                        design_done = False
                        design_ctx = ""
                        phase = "parallel_impl_design"
                        # KI-003: yield once more at the tail of the big
                        # _finish/_handoff/refresh_write_set mutation cluster, splitting
                        # the transition window in two so queued queries do not hit 8s.
                        await self._breathe()
                        continue
                    phase = "implement"
                    continue
                # Send-back: review comments are injected into the next create_plan round
                # (comments listed in report, older result files fall back to summary —
                # the channel changed, the comments must not be lost)
                plan_rounds += 1
                prev_ctx = ("【方案审读打回（第 %d 轮）】review comments：\n%s\n%s"
                            % (plan_rounds, res.report or res.summary or "",
                               res.evidence or "")).strip()
                self._handoff("review_plan", "方案打回：" + (res.summary or ""),
                              report=res.report)
                if plan_rounds > MAX_REVIEW_ROUNDS:
                    await self._blocked("review_plan",
                                        "方案审读打回 %d 轮超限（上限 %d）"
                                        % (plan_rounds, MAX_REVIEW_ROUNDS))
                    continue
                self._log("review_plan 打回 → create_plan（第 %d 轮）：%s"
                          % (plan_rounds, (res.summary or "")[:120]))
                phase = "create_plan"
                continue

            # 3) implement (developer: code + unit tests) — the developer edge of the
            #    parallel fork, or a single-edge re-run after a send-back
            if phase == "implement":
                try:
                    res = await self._run_agent_step("implement", prev_ctx, settle=False)
                except Exception as e:
                    await self._blocked("implement", format_agent_stage_failure(
                        self.ticket_id, "implement", e, gen=self._gen("implement")))
                    continue
                prev_ctx = ""
                if res.status != "ok":
                    await self._blocked("implement", self._agent_failed_why(res))
                    continue
                self._finish("implement", by="developer-agent",
                             evidence=res.evidence or res.summary)
                self._handoff("implement", res.summary or "实现完成",
                              artifacts=res.deliverables, report=res.report)
                if not workflow.patched(INTEG_LOOP_PATCH_ID):
                    # ---- old chain tail (reachable only by replaying existing
                    #      workflows, ticket t260831-02) ----
                    ui_ctx = ""
                    if workflow.patched(UI_EVIDENCE_PATCH_ID) and \
                            is_ui_write_set(list(self.meta.get("write_set") or [])):
                        try:
                            uiraw = await workflow.execute_activity(
                                prepare_ui_evidence,
                                UiEvidenceArgs(ticket_id=self.ticket_id,
                                               worktree=str(self.meta.get("worktree") or "")),
                                start_to_close_timeout=UI_EVIDENCE_TO, retry_policy=RETRY)
                            ui = uiraw if isinstance(uiraw, UiEvidenceResult) else UiEvidenceResult(
                                ok=bool(uiraw.get("ok")), shots=[str(x) for x in (uiraw.get("shots") or [])],
                                shot_lines=[str(x) for x in (uiraw.get("shot_lines") or [])],
                                detail=str(uiraw.get("detail") or ""), skipped=bool(uiraw.get("skipped")))
                            self.results["ui_evidence"] = {
                                "status": "ok" if ui.ok else "failed",
                                "summary": ui.detail, "report": "", "deliverables": list(ui.shots),
                                "files_changed": [], "evidence": ui.detail, "gen": 0}
                            if ui.ok:
                                ui_ctx = "【UI 截图证据（.sandbar/screenshots/，审读必看）】\n" + \
                                    "\n".join("- %s" % ln for ln in (ui.shot_lines or ui.shots))
                            else:
                                ui_ctx = "【UI 截图证据缺失】%s（审读按「无截图证据=打回」处理）" % ui.detail
                            self._log("prepare_ui_evidence：%s" % (ui.detail or ("ok" if ui.ok else "failed")))
                        except Exception as e:
                            # t260929-18：ui_ctx 进 agent 上下文/人审面 → 链下钻。
                            ui_ctx = "【UI 截图证据缺失】activity 故障：%s: %s%s" % (
                                type(e).__name__, e, shared.exception_chain_note(e))
                            self._log("prepare_ui_evidence 故障（不拦主链，merge_check 闸兜底）：%s" % str(e)[:200])
                    phase = "integration_review"
                    continue
                impl_done = True
                self._handoff("implement", res.summary or "实现完成",
                              artifacts=res.deliverables, report=res.report)
                phase = "integ_join"
                continue

            # 3.0) old chain tail: integration_review (reachable only by replaying
            #      existing workflows; the new chain forks in parallel and its gate duty
            #      is taken over by integration tests + arbitration + the acceptance
            #      walkthrough — t260831-02)
            if phase == "integration_review":
                try:
                    res = await self._run_agent_step("integration_review",
                                                     (prev_ctx + "\n" + ui_ctx).strip())
                except Exception as e:
                    await self._blocked("integration_review", format_agent_stage_failure(
                        self.ticket_id, "integration_review", e,
                        gen=self._gen("integration_review")))
                    continue
                prev_ctx = ""
                ui_ctx = ""
                if res.status == "ok":
                    if workflow.patched(REVIEW_GATE_PATCH_ID):
                        try:
                            graw = await workflow.execute_activity(
                                verify_review_gate,
                                ReviewGateArgs(
                                    ticket_id=self.ticket_id,
                                    worktree=str(self.meta.get("worktree") or ""),
                                    write_set=list(self.meta.get("write_set") or []),
                                    no_file_changes=bool(self.meta.get("no_file_changes"))),
                                start_to_close_timeout=SHORT, retry_policy=RETRY)
                            g = graw if isinstance(graw, ReviewGateResult) else ReviewGateResult(
                                git_error=str(graw.get("git_error") or ""),
                                lane_commits=int(graw.get("lane_commits") or -1),
                                shots_path_error=str(graw.get("shots_path_error") or ""),
                                png_count=int(graw.get("png_count") or -1))
                            # t260904-18 KI-050 gate 3: supplying the UI-judgment input —
                            # the patched branch reads the meta-preloaded declaration
                            # (replay safe); a missing meta key (activity retries
                            # exhausted / exception) falls back to the "declaration
                            # absent" reading (is_ui=False, with a note that "declaration
                            # read failure ≠ the project declaring nothing" — a supply
                            # fault must not drift the UI-ticket judgment); unpatched
                            # (existing instances replaying) keeps the old call shape as-is.
                            if workflow.patched(UI_EVIDENCE_DECL_PATCH_ID):
                                decl_dirs = self.meta.get("ui_evidence_dirs")
                                if isinstance(decl_dirs, list):
                                    gate_is_ui = is_ui_write_set(
                                        list(self.meta.get("write_set") or []), decl_dirs)
                                else:
                                    gate_is_ui = False
                                    self._log("机械复核 UI 判定：ui_evidence 声明未预载"
                                              "（声明读取失败≠项目未声明，按声明缺省处理）")
                            else:
                                gate_is_ui = is_ui_write_set(
                                    list(self.meta.get("write_set") or []))
                            gate_rework, gate_note = review_gate_verdict(
                                g.git_error, g.lane_commits, g.shots_path_error, g.png_count,
                                bool(self.meta.get("no_file_changes")),
                                gate_is_ui)
                            if gate_note:
                                self._log(gate_note)
                        except Exception as e:
                            self._log("verify_review_gate 故障（不拦主链）：%s: %s"
                                      % (type(e).__name__, e))
                    if gate_rework:
                        impl_rounds += 1
                        self._handoff("integration_review", gate_rework,
                                      report=res.report)
                        self._log("机械复核强制打回 → implement（第 %d 轮）：%s"
                                  % (impl_rounds, gate_rework))
                        prev_ctx = "【%s】\n%s" % (gate_rework,
                                                  res.report or res.summary or "")
                        if impl_rounds > MAX_REVIEW_ROUNDS:
                            await self._blocked("integration_review",
                                                "机械复核打回 %d 轮超限（上限 %d）"
                                                % (impl_rounds, MAX_REVIEW_ROUNDS))
                            continue
                        phase = self._auto_rework("implement", gate_rework,
                                                  who="workflow",
                                                  fallback="integration_review")
                        continue
                    self._finish("integration_review", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("integration_review", "集成审读通过：" + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    phase = "merge_check"
                    continue
                impl_rounds += 1
                prev_ctx = ("【集成审读打回（第 %d 轮）】review comments：\n%s\n%s"
                            % (impl_rounds, res.report or res.summary or "",
                               res.evidence or "")).strip()
                self._handoff("integration_review", "集成审读打回：" + (res.summary or ""),
                              report=res.report)
                if impl_rounds > MAX_REVIEW_ROUNDS:
                    await self._blocked("integration_review",
                                        "集成审读打回 %d 轮超限（上限 %d）"
                                        % (impl_rounds, MAX_REVIEW_ROUNDS))
                    continue
                note = "集成审读打回（第 %d 轮）" % impl_rounds
                self._log("integration_review 打回 → implement（第 %d 轮）：%s"
                          % (impl_rounds, (res.summary or "")[:120]))
                phase = self._auto_rework("implement", note, who="workflow",
                                          fallback="integration_review")
                continue

                try:
                    res = await self._run_agent_step("implement", prev_ctx, settle=False)
                except Exception as e:
                    await self._blocked("implement", format_agent_stage_failure(
                        self.ticket_id, "implement", e, gen=self._gen("implement")))
                    continue
                prev_ctx = ""
                if res.status != "ok":
                    await self._blocked("implement", self._agent_failed_why(res))
                    continue
                impl_done = True
                self._finish("implement", by="developer-agent",
                             evidence=res.evidence or res.summary)
                self._handoff("implement", res.summary or "实现完成",
                              artifacts=r.deliverables if False else res.deliverables,
                              report=res.report)
                phase = "integ_join"
                continue

            # 3.0) join: one commit-on-behalf for both edges (skip_settle collapses here,
            #      implementation + test suite in the same commit) → UI evidence (UI
            #      tickets) → mechanical integration tests (t260831-02).
            if phase == "integ_join":
                sraw = await workflow.execute_activity(
                    settle_lane,
                    SettleLaneArgs(ticket_id=self.ticket_id,
                                   worktree=str(self.meta.get("worktree") or ""),
                                   stage_id="implement", gen=impl_rounds,
                                   write_set=list(self.meta.get("write_set") or []),
                                   base_ref=str(self.meta.get("base_ref") or ""),
                                   path_gate=bool(self.meta.get("path_gate")),
                                   path_gate_rules=dict(self.meta.get("path_gate_rules") or {}),
                                   authorizations=self._protected_authz_records()),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                s = sraw if isinstance(sraw, SettleLaneResult) else SettleLaneResult(
                    note=str(sraw.get("note") or ""),
                    lane_commits=int(sraw.get("lane_commits") or -1),
                    error=str(sraw.get("error") or ""))
                # t260912-03：join 点落盘的授权消费留痕（机读键在场才记）
                self._record_authz_uses(s.note, "integ_join")
                # t260911-03：路径闸拒绝（error 带 path_gate_reason=）→ blocked 点名
                # 段/文件与合法出路——不静默吞成一条日志（0-commit 预检的红不含闸细节）。
                if s.error and "path_gate_reason=" in s.error:
                    # t260915-01 ②（A3）：新回执带结构化明细→上台面；老回执无键→
                    # 既有文本 why 逐字不变。
                    self._pin_settle_refusal(s)
                    # t260916-19 A：同批复判点名（retry_qc 无变化重跑不改变结果）
                    rep = self._gate_refusal_repeat_suffix(
                        (getattr(s, "gate_refusal", None) or {}).get("files"))
                    # t260925-17（KI-120）：fork 来源（design_done=True＝本轮经
                    # parallel_impl_design 叉汇入）→ 复位被闸挡住的实现边并回到叉
                    # 相位：醒后 pend=["implement"]，实现边真重跑（agent respawn）
                    # → 重新汇入 integ_join 重落 settle（带 _protected_authz_records()
                    # 现取授权重判闸）。串行来源（design_done=False，本轮无叉）→
                    # 不动簿记不回叉，醒后主循环重进本段重跑 settle（串行「原步重入」
                    # 语义零改动）。不卡 patched 门的设计会在途票重放破确定性
                    # （t260917-04 先例）。
                    if workflow.patched(KI120_FORK_GATE_WAKE_RESET_PATCH_ID) \
                            and design_done:
                        impl_done = False
                        phase = "parallel_impl_design"
                    await self._blocked("implement", s.error + rep)
                    continue
                self._log("汇合统一落盘：%s（泳道 commit 数 %s）"
                          % (s.note or "干净", s.lane_commits))
                # UI 证据（仅 UI 票）：宿主令 260930（light-lane，直修无票） 抽块——本处改为调用
                # 共用 helper _ui_evidence_step()（内容逐字即原块，两条泳道同源；
                # 老在途实例重放的命令序列逐字不变）。
                ui_ctx = await self._ui_evidence_step()
                phase = "run_integration_tests"
                continue

            # 3.1) parallel fork: implement ∥ design_integration_tests (t260831-02).
            #      Re-running a missing edge: completion lives in memory, so after a
            #      blocked wake only the failed edge is retried (activities are idempotent).
            if phase == "parallel_impl_design":
                pend = []
                if not impl_done:
                    pend.append("implement")
                if not design_done:
                    pend.append("design_integration_tests")
                if pend:
                    # KI-024: the active edge list of the fork goes into meta (the
                    # workbench's dual-display source of truth; the single stage field
                    # stays untouched).
                    # t260915-01 ③（A6）：相位名随分叉入 meta（timeline phase 键的
                    # 数据源）；门内才传——在途实例重放零新键（C5 门纪律）。
                    set_parallel_stages(
                        self.meta, pend,
                        phase="parallel_impl_design"
                              if getattr(self, "_detail_face_on", False) else "")
                    try:
                        rs = await asyncio.gather(*[
                            self._run_agent_step(
                                n, prev_ctx if n == "implement" else design_ctx,
                                settle=False) for n in pend],
                            return_exceptions=True)
                    except Exception as e:  # gather itself should not raise (return_exceptions); defensive
                        await self._blocked("parallel_impl_design", "并行分叉异常：%s" % e)
                        continue
                    failed = False
                    for name, r in zip(pend, rs):
                        if isinstance(r, Exception):
                            failed = True
                            # KI-024 waiting-period contract (fixed): drop the failed
                            # edge — the list keeps only edges still to redo, so the UI
                            # does not show a to-redo edge as ▶; the failed edge itself
                            # shows ✗ through its timeline blocked entry (_mark inside
                            # _blocked).
                            set_parallel_stages(
                                self.meta, [n for n in pend if n != name])
                            await self._blocked(name, format_agent_stage_failure(
                                self.ticket_id, name, r, gen=self._gen(name)))
                            break  # _blocked waits for retry_qc/rework; after waking, recompute pend and retry only the failed edge
                        if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(r):
                            # t260916-28: 与上方 Exception 分支同形簿记（置 failed+
                            # 剔边+blocked+break）——泳道 .dsh 缺件的环境故障绝不能落进
                            # 下方消费循环被无条件记成假完成；failed 让 `if failed:
                            # continue` 跳过消费循环，醒来重算 pend 重跑未消费边
                            # （与 Exception 分支的重跑面语义一致）。
                            failed = True
                            set_parallel_stages(
                                self.meta, [n for n in pend if n != name])
                            await self._block_agent_failed(name, r)
                            break
                    if failed:
                        continue
                    for name, r in zip(pend, rs):
                        if name == "implement":
                            impl_done = True
                            self._finish("implement", by="developer-agent",
                                         evidence=r.evidence or r.summary)
                            self._handoff("implement", r.summary or "实现完成",
                                          artifacts=r.deliverables, report=r.report)
                        else:
                            design_done = True
                            self._finish("design_integration_tests", by="integration-agent",
                                         evidence=r.evidence or r.summary)
                            self._handoff("design_integration_tests",
                                          r.summary or "集成测试集就绪",
                                          artifacts=r.deliverables, report=r.report)
                if not (impl_done and design_done):
                    continue
                # KI-024: both edges done = leaving the parallel period, delete
                # parallel_stages (the UI falls back to its existing heuristics; the
                # following integ_join/settle is a single serial section with no dual
                # display semantics).
                set_parallel_stages(self.meta, [])
                phase = "integ_join"
                continue

            # 3.2) mechanical integration tests (zero LLM): run the project-declared
            #      scenario runner integration/run_scenarios.py
            if phase == "run_integration_tests":
                self._enter("run_integration_tests")
                # t260925-12 闸段分相计时：段入口墙钟锚（workflow.now 确定性时钟）；
                # 各活动 workflow 侧前后差=「段视角墙钟」（含调度/排队），活动回执
                # 自报 wall_s=「执行面墙钟」——两口径之差就是排队/调度面的归因面。
                gate_t0 = self._now_epoch()
                gate_pre_s = 0.0      # 0-commit 前置检查（verify_review_gate）
                gate_sync_s = 0.0     # 主同步（prepare_conflict_resolution ×各仓）
                gate_cf_s = 0.0       # 改动清单收集（changed_files）
                gate_integ_s = 0.0    # 场景执行活动（run_integration_tests）
                # t260903-02 (2): single-point reset of the in-memory state (invariant:
                # each mechanical test run produces a fresh arbitration and a fresh
                # walkthrough) — covers every convergence path of the rework /
                # tests-fault / code-fault loops, so no scattered branch has to set
                # these (and no stale walkthrough result from before the send-back is
                # consumed).
                arb_done = False
                acc_done = False
                arb_res = None
                acc_res = None
                # t260917-01：格式轮次同口径复位——「连续缺 verdict」的连续性以本段
                # 为界（旧代码跨 rework 累积，是 t260916-21「计数变 4 次」的机制
                # 之一；与 1084 行 consecutive 注释语义自此真正对齐）。
                # t260917-04：过 patched 门——旧历史（无本 marker）保持旧行为（不复位）。
                if workflow.patched(ARBITRATE_REFUSAL_PATCH_ID):
                    arb_format_rounds = 0
                # t260917-09：tests 连续计数的段入口复位——**唯一行为分叉点**：本段
                # 由 tests-fault 迭代来源进入（tests_streak=True）时不清零（否则上限
                # 永不触发），其余来源（新实现轮/验收打回/rework 后重进）复位并留痕。
                # 与上一行 t260917-01 簇同一 patched 门族；cur_integ 每段入口清
                # （本轮回执在本段尾部重赋值，串行/平行两支共用同一 ir）。
                cur_integ = None
                if workflow.patched(TESTS_STREAK_PATCH_ID):
                    if not tests_streak:
                        if workflow.patched(KI122_STREAK_HOLD_PATCH_ID):
                            # KI-122②：外部处置（人工 rework / retry_qc / pause / 脱困
                            # 重进）**不再复位**连续计数——复位只认「本票红真的消失/
                            # 清零」（仲裁 pass 收敛 / 人工显式接受判决）。旧口径对
                            # 任何非 tests-fault 迭代来源的段入口重进都清零，于是两道
                            # 防活循环上限可被外部处置反复击穿、永不触顶
                            # （t260925-05 实测：闸轮 7 仍未浮出「超限转人工」）。
                            if tests_rounds or tests_exempt_rounds:
                                self._log("tests_rounds 计数不复位（外部处置来源重进；"
                                          "连续轮次 %d／连续豁免 %d，上限不被击穿）"
                                          % (tests_rounds, tests_exempt_rounds))
                        else:
                            tests_rounds, tests_exempt_rounds, _, _ = \
                                tests_round_step("streak-reset", tests_rounds,
                                                 tests_exempt_rounds)
                            self._log("tests_rounds 计数复位（非 tests-fault 迭代来源重进，"
                                      "连续语义）")
                    tests_streak = False
                # Pre-check, mechanical: the lane has been committed (guaranteed after
                # the unified settle; tickets with no_file_changes are exempt)
                if workflow.patched(REVIEW_GATE_PATCH_ID) and not self.meta.get("no_file_changes"):
                    _pre_t = self._now_epoch()   # t260925-12
                    try:
                        graw = await workflow.execute_activity(
                            verify_review_gate,
                            ReviewGateArgs(ticket_id=self.ticket_id,
                                           worktree=str(self.meta.get("worktree") or ""),
                                           write_set=list(self.meta.get("write_set") or []),
                                           no_file_changes=True),
                            start_to_close_timeout=SHORT, retry_policy=RETRY)
                        gate_pre_s += max(0, self._now_epoch() - _pre_t)
                        g = graw if isinstance(graw, ReviewGateResult) else ReviewGateResult(
                            git_error=str(graw.get("git_error") or ""),
                            lane_commits=int(graw.get("lane_commits") or -1),
                            shots_path_error=str(graw.get("shots_path_error") or ""),
                            png_count=int(graw.get("png_count") or -1))
                        if g.lane_commits == 0:
                            await self._blocked(
                                "run_integration_tests",
                                "实现未落盘（泳道 0 commit）——实现步产物缺失，"
                                "发 rework 回 implement 或排查实现步")
                            continue
                    except Exception as e:
                        self._log("落盘前置检查故障（不拦主链）：%s: %s" % (type(e).__name__, e))
                # ---- t260922-18 主同步（宿主拍板「只在机械验证前并一次」）----
                # 机制抽到 `_main_sync_before_gate` 单点（宿主 260930 直修：轻道复用同一条，
                # 不许第二份实现）；本处仍是**唯一同位点**：0-commit 前置检查之后（判据不
                # 放宽）、跑闸之前（同轮直线衔接、必重跑）。原内联块逐字搬进 helper——命令
                # 序列/入参/等待点不变，dev-lane 行为零变化。
                if workflow.patched(MAIN_SYNC_PATCH_ID):
                    _ms = await self._main_sync_before_gate(conflict_rounds,
                                                            prev_conflict_files)
                    conflict_rounds = int(_ms.get("conflict_rounds") or 0)
                    prev_conflict_files = list(_ms.get("prev_conflict_files") or [])
                    gate_sync_s += float(_ms.get("sync_s") or 0.0)
                    if _ms.get("phase"):
                        phase = str(_ms["phase"])
                    if _ms.get("stop"):
                        continue
                try:
                    # t260917-08（review C1 裁定①）：移交命令消费面=meta['env_handover_pending']
                    # 债表单源（含集测后段遗留债——rework 回 implement 的下一轮集测
                    # 自然拾取）；销账在回执无 error 时（_run_scenarios 的命令执行块在
                    # 场景执行器成功之后，error 早退=命令没跑，留债下轮）。
                    # t260923 D：爆炸半径+定点面决策（单写者=shared.targeted_rerun_plan；
                    # 首轮/共享基座/无上轮红名=空=全量跑）。过 patched 门——旧历史
                    # 零行为变化（恒全量跑）。
                    # t260925-04：v2 门=文件级爆炸半径——先收集实际改动文件
                    # （changed_files activity：merge-base 三点 diff ∪ status 脏文件），
                    # 传 targeted_rerun_plan(changed_files=…)；清单不可得（error 非空）
                    # 传空清单=fail-closed 恒全跑。v1 门（旧历史）逐字旧判据（写集
                    # 粗前缀）。两门都关=恒全量跑。
                    _cf_files: list = []
                    if workflow.patched(TARGETED_RERUN_FILE_RADIUS_PATCH_ID):
                        _cf_t = self._now_epoch()   # t260925-12
                        _cf = await workflow.execute_activity(
                            changed_files,
                            ChangedFilesArgs(
                                ticket_id=self.ticket_id,
                                worktree=str(self.meta.get("worktree") or ""),
                                branch=str(self.meta.get("branch") or "")),
                            start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
                        gate_cf_s += max(0, self._now_epoch() - _cf_t)
                        _cf_files = list(getattr(_cf, "files", None) or [])
                        _cf_err = str(getattr(_cf, "error", "") or "")
                        self.meta["file_blast_radius_trace"] = {
                            "changed_files": _cf_files, "error": _cf_err}
                        if _cf_err:
                            # fail-closed 留痕：清单不可得 ≠ 无改动，恒全跑
                            self._log("文件级爆炸半径：改动清单不可得（%s）——恒全跑"
                                      % _cf_err[:200])
                        else:
                            self._log("文件级爆炸半径：实际改动 %d 个文件，共享面判定"
                                      "见定点决策" % len(_cf_files))
                        run_only = (targeted_rerun_plan(
                            list(self.meta.get("write_set") or []), prev_red_names,
                            first_run=(self._gen("run_integration_tests") == 0),
                            changed_files=_cf_files, diff_error=_cf_err)
                            if workflow.patched(TARGETED_RERUN_PATCH_ID) else [])
                    else:
                        run_only = (targeted_rerun_plan(
                            list(self.meta.get("write_set") or []), prev_red_names,
                            first_run=(self._gen("run_integration_tests") == 0))
                            if workflow.patched(TARGETED_RERUN_PATCH_ID) else [])
                    if workflow.patched(SURFACE_PLAN_PATCH_ID) and not run_only \
                            and _cf_files and not _cf_err:
                        # 面计划：本改动面该跑哪些场景（integration 侧判定）
                        _sp_t = self._now_epoch()   # t260925-12 归因面
                        _sp = await workflow.execute_activity(
                            surface_plan,
                            SurfacePlanArgs(
                                ticket_id=self.ticket_id,
                                worktree=str(self.meta.get("worktree") or ""),
                                changed_files=list(_cf_files),
                                prev_red_names=list(prev_red_names or [])),
                            start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
                        gate_cf_s += max(0, self._now_epoch() - _sp_t)
                        _sp_names = list(getattr(_sp, "names", None) or [])
                        _sp_mode = str(getattr(_sp, "mode", "") or "")
                        self.meta["surface_plan_trace"] = {
                            "mode": _sp_mode,
                            "reason": str(getattr(_sp, "reason", "") or ""),
                            "count": len(_sp_names),
                            "surfaces": list(getattr(_sp, "surfaces", None) or []),
                            "error": str(getattr(_sp, "error", "") or "")}
                        if _sp_mode == "targeted" and _sp_names:
                            run_only = _sp_names
                            self._log("面计划：改动面 %d 文件 → 快反馈面 %d 条"
                                      "（surfaces=%s；放行仍只认收口全量跑）"
                                      % (len(_cf_files), len(run_only),
                                         ",".join(self.meta["surface_plan_trace"]["surfaces"])
                                         or "-"))
                        else:
                            self._log("面计划：回全量跑（mode=%s reason=%s%s）"
                                      % (_sp_mode or "-",
                                         self.meta["surface_plan_trace"]["reason"] or "-",
                                         ("｜" + self.meta["surface_plan_trace"]["error"])
                                         if self.meta["surface_plan_trace"]["error"] else ""))
                    if run_only:
                        self._log("两层复跑：定点复跑面（%s）——仅快反馈，放行只认收口全量跑"
                                  % ",".join(run_only))
                    _integ_t = self._now_epoch()   # t260925-12
                    rraw = await workflow.execute_activity(
                        run_integration_tests,
                        self._integ_run_args(run_only),
                        start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
                    gate_integ_s += max(0, self._now_epoch() - _integ_t)
                    ir = rraw if isinstance(rraw, IntegrationRunResult) else IntegrationRunResult(
                        ran=int(rraw.get("ran") or 0), passed=int(rraw.get("passed") or 0),
                        failed=int(rraw.get("failed") or 0),
                        env_fail=int(rraw.get("env_fail") or 0),
                        details=[dict(d) for d in (rraw.get("details") or [])],
                        error=str(rraw.get("error") or ""),
                        # t260917-08（review R3）：dict 回退重建点——新计数键漏写=
                        # 命令跑了回执仍显 0（报文与事实相反），与上述键同批补齐
                        handover_ran=int(rraw.get("handover_ran") or 0),
                        handover_passed=int(rraw.get("handover_passed") or 0),
                        handover_failed=int(rraw.get("handover_failed") or 0))
                except Exception as e:
                    # t260929-18：error 进仲裁/票面 → 链下钻带上真实根因。
                    ir = IntegrationRunResult(error="集成测试 activity 故障：%s: %s%s"
                                              % (type(e).__name__, e,
                                                 shared.exception_chain_note(e)))
                # t260917-08：命令已真跑（回执无 error）→ 债表销账（防重复执行；
                # 命令败≠没跑，结果交仲裁/票面处置，此处只管「执行过」的账）
                if not ir.error:
                    self._handover_debt_clear()
                # ---- t260925-12 闸段分相计时上台面（验收④）：段墙钟=段入口→本点；
                # 各相位=workflow 侧活动前后差（含调度/排队）；活动自报（回执 wall_s
                # 族）=执行面。unattributed_s=段墙钟−Σ相位（review 条件②：归账口径
                # 单写者=此处）——超时的第一嫌疑面，永远显式给数不藏。纯回执数字拼装，
                # workflow 不取墙上钟（workflow.now 为 Temporal 确定性时钟，既有
                # _log/_mark 同源先例），replay 零分歧。
                _gate_phases = shared.gate_phase_timings(
                    {"pre_check_s": gate_pre_s,
                     "main_sync_s": gate_sync_s,
                     "changed_files_s": gate_cf_s,
                     "suite_s": gate_integ_s,
                     "handover_s": getattr(ir, "handover_wall_s", 0.0) or 0.0},
                    max(0, self._now_epoch() - gate_t0))
                # 活动自报执行面（回执缺省 0.0=老回放/故障路径未计时，不冒充）——
                # 观测键随拼装结果同置一个键下，不参与 unattributed 归账（0 值不假造）。
                _gate_reported = {"integ_reported_wall_s":
                                  float(getattr(ir, "wall_s", 0.0) or 0.0),
                                  "integ_subprocess_wall_s":
                                  float(getattr(ir, "subprocess_wall_s", 0.0) or 0.0)}
                self.meta["gate_phase_timings"] = dict(_gate_phases, **_gate_reported)
                _gate_phase_keys = ("pre_check_s", "main_sync_s",
                                    "changed_files_s", "suite_s", "handover_s")
                _gate_sum_s = sum(_gate_phases.get(k, 0.0)
                                  for k in _gate_phase_keys)
                ir.details.append({
                    "name": "__gate_timings__", "cmd": "", "exit": 0,
                    "output_tail": (
                        "闸段分相（s）：段=%.0f｜前置=%.0f 主同步=%.0f 改动清单=%.0f "
                        "跑闸=%.0f（执行面 %.0f，其中子进程 %.0f）｜Σ相位=%.0f "
                        "unattributed=%.0f（段−Σ相位，排队/调度/段内非活动面）")
                    % (_gate_phases["unattributed_s"] + _gate_sum_s,
                       _gate_phases.get("pre_check_s", 0.0),
                       _gate_phases.get("main_sync_s", 0.0),
                       _gate_phases.get("changed_files_s", 0.0),
                       _gate_phases.get("suite_s", 0.0),
                       _gate_reported["integ_reported_wall_s"],
                       _gate_reported["integ_subprocess_wall_s"],
                       _gate_sum_s,
                       _gate_phases["unattributed_s"])})
                # t260904-12: the headline carries the environment-red dimension — a
                # mixed suite can no longer tell a fake "all green" story.
                # t260913-03: the exclusion face is named on the ticket face.
                # 宿主 260914 口径：例外分支已撤除——每票段一律跳过声明池，票面只报跳过面；
                # 旧口径命中面（forced_by）只作迁移期留痕，不再出现在票面注记里。
                _pe_note = ""
                if ir.excluded_pools:
                    _pe_note = "｜本轮跳过池=%s（少 %d 条）" % (
                        "、".join(ir.excluded_pools), ir.excluded_count)
                # t260917-08（review N3）：失败命令点名进票面——前 3 个失败命令名+剩余计数，
                # 「｜」注记风格与既有面一致；单列计数不进 status 判定（闸口径零改动）
                _hv_note = ""
                if ir.handover_ran:
                    _red_legs = [str(d.get("name") or "")[len("handover:"):]
                                 for d in ir.details
                                 if str(d.get("name") or "").startswith("handover:")
                                 and d.get("exit") != 0]
                    _hv_note = "｜移交命令 %d 跑 / %d 过 / %d 败" % (
                        ir.handover_ran, ir.handover_passed, ir.handover_failed)
                    if _red_legs:
                        _hv_note += "（失败命令：%s%s）" % (
                            "、".join(_red_legs[:3]), "等" if len(_red_legs) > 3 else "")
                # t260922-18：主同步证据进票面（机械证据三处之一；与闸补 baseline_ref
                # 同轮互证——开跑时 main@sha 一致）。回执畸形/缺键=空文案，票面不铸假证据
                #（同步被 blocked 打断时根本到不了这里）。
                _ms_note = main_sync_note(self.meta.get("main_sync") or {})
                _ms_sum = ("｜主同步=%s" % _ms_note) if _ms_note else ""
                _ms_evi = ("【主同步】%s（时点=机械验证前；同步与跑闸同轮直线衔接，"
                           "未复用旧报告）\n" % _ms_note) if _ms_note else ""
                # B2（260929 宿主令）：环境红**具名**进票面/交接（前 5 个 + 总数；名单空
                # =不加这段）。环境红不再是失败面（status 判据已摘 env_fail）——具名是
                # 「不拦但不许静默」的兑现：票面答得出红的是哪几条，重跑不再当收敛手段。
                _env_note_face = self._env_red_face_note(ir.env_red)
                self.results["run_integration_tests"] = {
                    "status": "failed" if (ir.error or ir.failed) else "ok",
                    "summary": "集成测试：%d 跑 / %d 过 / %d 败 / %d 环境红%s%s%s%s%s"
                               % (ir.ran, ir.passed, ir.failed, ir.env_fail,
                                  ("｜" + ir.error) if ir.error else "", _pe_note, _hv_note,
                                  _env_note_face, _ms_sum),
                    "report": "", "deliverables": [], "files_changed": [],
                    "evidence": _ms_evi + json.dumps(ir.details, ensure_ascii=False)[:4000],
                    "gen": 0}
                self._finish("run_integration_tests", by="run_integration_tests",
                             evidence="；".join("%s:%s" % (d.get("name"),
                                                    "过" if d.get("exit") == 0 else "败")
                                                for d in ir.details))
                self._handoff("run_integration_tests",
                              "集成测试 %d 跑 / %d 过 / %d 败 / %d 环境红%s%s%s%s%s"
                              % (ir.ran, ir.passed, ir.failed, ir.env_fail,
                                 ("｜" + ir.error) if ir.error else "", _pe_note, _hv_note,
                                 _env_note_face, _ms_sum))
                # t260901-19: budget 6000→4000 with tail-keeping ([-4000:]) — details sit
                # at the end of the JSON, so a head slice would squeeze out the failure
                # details; keeping the tail keeps them
                # t260917-09（R3）：本轮机械回执快照落点=翻译处（串行/平行两支共用
                # 同一 ir）——env_side_red 与红项名单判据都从 cur_integ 取。
                cur_integ = ir
                # t260923 D：跑面簿记（少跑必须可见+定点面来源）——每跑后刷新。
                last_run_only = list(run_only)
                prev_red_names = self._tests_red_names(ir)
                # t260917-09：_arb_json 补机械环境面三键（env_fail/闸拦/归属置信）——
                # 仲裁 agent 首次直接看到 t260910-13 归属判定，不再只从 details 尾巴猜；
                # 只读既有字段，与 t260917-08（环境信号一等化）零耦合。
                _arb_json = json.dumps({"ran": ir.ran, "passed": ir.passed,
                                        "failed": ir.failed, "error": ir.error,
                                        "env_fail": ir.env_fail,
                                        # B2（260929）：环境红具名名单进仲裁面——
                                        # 判词据此把环境面与产品面分开归因（B1 已落的
                                        # 只读字段，不改形状、不改任何判定）。
                                        "env_red": list(getattr(ir, "env_red", None) or []),
                                        "blockers": ir.blockers,
                                        "affiliation_confidence":
                                            ir.affiliation_confidence,
                                        "details": ir.details}, ensure_ascii=False)
                arb_ctx = ("【机械集成测试结果】\n%s\n【测试集】仓库 integration/ 目录"
                           "（场景清单为准；你是其作者。tests-fault 只迭代本段允许面内的测试资产（tests/、test_*.py、sc_* 场景、登记表、本票场景），共享资产/受保护真源如实出 verdict 并点名红项，勿直接改——闸会拒）"
                           % _arb_json[-4000:])
                # t260903-02 (2): the walkthrough edge consumes the same test result as
                # the arbitration (the user-view walkthrough is independent and does not
                # assume all tests passed); the UI walkthrough evidence is injected too.
                acc_ctx = ("【机械集成测试结果】\n%s\n" % _arb_json[-4000:]) + \
                    (("【UI 截图/走查实证（.sandbar/screenshots/）】\n%s\n" % ui_ctx)
                     if ui_ctx else "")
                # t260917-08（R4/R5）：交接说明行进仲裁与走查上下文——失败命令处置契约+
                # 未验证段点名（env_note 单源措辞），防「失败命令绿票/空清单洗白」。装配在
                # 两处上下文语句之后追加（不挤进 [-4000:] 尾保装配块——t260901-19
                # T2 静态 pin 以装配行 ±8 行窗锚 json 载荷完整性，勿动装配块结构）。
                _hv_ctx = ""
                if ir.handover_ran:
                    _hv_ctx += ("【移交验证命令（t260917-08）】前序段沙箱受限期间交接的验证已由 "
                                "worker 代跑：%d 跑 / %d 过 / %d 败（details 内 name=handover:* "
                                "条）。失败命令=验证未过，须按三态归因处置（rework），"
                                "不得因单列计数放行。" % (ir.handover_ran, ir.handover_passed,
                                                      ir.handover_failed))
                _env_notes = ["%s：%s" % (sid, r["env_note"]) for sid, r in self.results.items()
                              if isinstance(r, dict) and r.get("env_note")]
                if _env_notes:
                    _hv_ctx += ("\n【环境受限段（未验证声明）】%s——不得当已验证，"
                                "verdict 必须处置。" % "；".join(_env_notes))
                if _hv_ctx:
                    arb_ctx += "\n" + _hv_ctx
                    acc_ctx += _hv_ctx + "\n"
                # t260922-18：主同步证据进仲裁与走查上下文（机械证据三处之二/三；仲裁可
                # 据此把红项归属对着「main+票改动」的验证树判，而不是旧基线）。同样追加
                # 在装配块之后，不挤进 [-4000:] 尾保窗（T2 静态 pin 纪律同上）。
                if _ms_note:
                    _ms_ctx = ("【主同步证据】本轮验证树已并入 %s（时点=机械验证前；"
                               "同步与跑闸同轮直线衔接，未复用旧报告）" % _ms_note)
                    arb_ctx += "\n" + _ms_ctx
                    acc_ctx += _ms_ctx + "\n"
                # B2（260929 宿主令）：环境面归因上下文——具名环境红是**供给/共享台面**，
                # 不是 tests-fault 的迭代理由（修复=补供给声明/环境，不是回工重跑整轮）；
                # 具名/未具名两态分别点名，防「凭环境面口头豁免」与「重跑等它绿」两坑。
                # 同样追加在装配块之后，不挤进 [-4000:] 尾保窗（静态 pin 纪律同上）。
                _env_red_names_ctx = list(getattr(ir, "env_red", None) or [])
                if _env_red_names_ctx:
                    _envf_ctx = (
                        "【环境红（B2 具名通道，不拦·不进迭代面）】%s——判据面=闸回执 "
                        "env_red（not-checked × external），共 %d 条。环境红=供给/共享台面，"
                        "修复动作是补供给声明/补环境，**不是**回工重跑整轮（重跑环境红不会绿）；"
                        "本票面绿且余红均为此名单内/在册既有红时判 verdict=pass，并把红名"
                        "写进报告备注；只有本票新增产品红（不在本名单、闸拦 blockers 非空）"
                        "才进 tests-fault/code-fault。"
                        % (self._env_red_face_note(_env_red_names_ctx) or
                           "（具名名单同上）", len(_env_red_names_ctx)))
                elif int(getattr(ir, "env_fail", 0) or 0) > 0:
                    _envf_ctx = (
                        "【环境红未具名（老回执形态）】本轮环境红计数 %d 但 env_red 具名名单"
                        "为空/缺键——**不得凭「环境面」口头豁免放行**：按保守侧处置（无具名"
                        "即无豁免，红项仍须逐条归因）。"
                        % int(getattr(ir, "env_fail", 0) or 0))
                else:
                    _envf_ctx = ""
                if _envf_ctx:
                    arb_ctx += "\n" + _envf_ctx
                    acc_ctx += _envf_ctx + "\n"
                if workflow.patched(ARB_ACC_PARALLEL_PATCH_ID):
                    # Speedup 2: arbitration ∥ acceptance walkthrough as a parallel fork
                    # (no data dependency, saves one serial stretch)
                    phase = "arb_acc_parallel"
                else:
                    phase = "arbitrate"
                continue

            # 3.3) arbitration (integration, three verdicts: pass / tests-fault / code-fault)
            if phase == "arbitrate":
                try:
                    res = await self._run_agent_step("arbitrate", arb_ctx)
                except Exception as e:
                    await self._blocked("arbitrate", format_agent_stage_failure(
                        self.ticket_id, "arbitrate", e, gen=self._gen("arbitrate")))
                    continue
                if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(res):
                    # t260916-28: 环境（泳道 .dsh 缺件）故障不是格式违约——带人话
                    # 直落 blocked，不烧格式纠正计数、不虚报「缺 verdict= 标记」。
                    await self._block_agent_failed("arbitrate", res)
                    continue
                # t260917-01：闸拒可辨优先于格式计数——settle 被路径闸拒绝时回执
                # summary 已被拒绝文案改写，「缺 verdict」是闸拒的影子，不得计入
                # 格式轮次（真因主因化、出路真实化；结构化明细 _pin_agent_refusal
                # 已在 _run_agent_step 内上台面）。
                # t260917-04：过 patched 门（短路——旧历史不调用新方法、不产生命令）。
                if workflow.patched(ARBITRATE_REFUSAL_PATCH_ID) \
                        and await self._arbitrate_refusal_blocked(res):
                    continue
                verdict = parse_arbitration_summary(res.summary)
                if not verdict:
                    arb_format_rounds += 1
                    if arb_format_rounds > 2:
                        await self._blocked("arbitrate",
                                            "仲裁结论 %d 次缺 verdict= 标记（契约：summary 含 "
                                            "verdict=pass|tests-fault|code-fault）" % arb_format_rounds)
                        continue
                    arb_ctx = ("【格式纠正】你的上一份结论缺少 verdict= 标记。请严格输出三态之一："
                               "verdict=pass / verdict=tests-fault / verdict=code-fault，并重判。")
                    continue
                arb_ctx = ""
                arb_authz = self._arbitration_authz()
                route = arbitration_cap_route(verdict, tests_rounds, code_rounds,
                                              arb_authz is not None)
                if verdict == "pass":
                    # t260923 D 收口拦截：pass 落在定点跑上=放行依据不成立——机械补
                    # 收口全量跑；零新增红（blockers 空且无启动级 error）→ pass 成立
                    # 继续放行；有新增红 → 判决作废回仲裁重裁（全量面）。
                    if workflow.patched(TARGETED_RERUN_PATCH_ID) and last_run_only:
                        closing = await self._closing_full_run()
                        cur_integ = closing
                        last_run_only = []
                        prev_red_names = self._tests_red_names(closing)
                        _new_red = list(getattr(closing, "blockers", None) or [])
                        if _new_red or getattr(closing, "error", ""):
                            self._log("收口全量跑有新增红（%s）——pass 判决作废，回仲裁重裁"
                                      % (",".join(_new_red)
                                         or ("启动级 error：" + str(closing.error))))
                            arb_ctx = ("【收口重裁】上一轮 verdict=pass 落在定点跑上，收口"
                                       "全量跑发现新增红（%s）。请按全量面重判三态。"
                                       % (",".join(_new_red) or "启动级 error"))
                            continue
                        self._log("收口全量跑零新增红——pass 判决成立（放行只认全量）")
                    # t260917-09：连续语义复位点——pass=收敛，tests-fault 连续计数清零
                    # （留痕要求②）；门关=旧历史逐字旧行为。
                    if workflow.patched(TESTS_STREAK_PATCH_ID):
                        tests_rounds, tests_exempt_rounds, _, _ = \
                            tests_round_step("accept-reset", tests_rounds,
                                             tests_exempt_rounds)
                        self._log("tests_rounds 计数复位（仲裁 pass，连续语义）")
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("arbitrate", "仲裁通过：" + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    phase = "acceptance"
                    continue
                if arb_authz is not None and route == "acceptance":
                    # t260912-03：超限 + 本票生效中的「接受本判决」授权 → 不阻断，
                    # 按授权语义推进 acceptance_walkthrough（判决原文+授权一并进历史）。
                    # C2：与 verdict=pass 分支同形（_finish 落 arbitrate 终态 + _handoff）。
                    # 判决原文取「原因文案」本体（split 掉 route 的内部 blocked: 前缀）——
                    # 人读文案里不得漏进路由内部标记。
                    cap_reason = integration_route(verdict, tests_rounds, code_rounds) \
                        .split(":", 1)[-1]
                    # t260917-09：人工接受判决=收敛（要求①「人工接受即复位」）——连续
                    # 计数清零；R2 单写者纪律=伪 verdict 复用 tests_round_step。
                    if workflow.patched(TESTS_STREAK_PATCH_ID):
                        tests_rounds, tests_exempt_rounds, _, _ = \
                            tests_round_step("accept-reset", tests_rounds,
                                             tests_exempt_rounds)
                        self._log("tests_rounds 计数复位（人工接受判决，连续语义）")
                    self._append_authz_use(
                        arb_authz, "arbitrate",
                        "接受仲裁判决：verdict=%s（%s）→ acceptance_walkthrough"
                        % (verdict, cap_reason))
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff(
                        "arbitrate",
                        "仲裁超限封面经人授权接受判决（接受仲裁判决）→ acceptance_walkthrough：verdict=%s，%s"
                        "（授权人 %s，签发 %s，到期 %s，理由 %s）"
                        % (verdict, cap_reason,
                           arb_authz.get("who"), arb_authz.get("issued"),
                           arb_authz.get("expires"), arb_authz.get("reason")),
                        report=res.report)
                    self._log("仲裁超限经人授权接受判决（%s）→ acceptance_walkthrough"
                              % arb_authz.get("who"))
                    phase = "acceptance"
                    continue
                if route.startswith("blocked:"):
                    # KI-061: fixing the wake deadlock of an over-limit blocked state —
                    # genuinely re-run this step. The guard mechanism (a unique patch id
                    # per entry, against the SDK's memoized first verdict) and the replay
                    # stability argument live in _blocked_over_limit; without the reset,
                    # waking eats the memoized arbitration verdict, blocks again at once,
                    # and arbitrate is never re-spawned (the t260907-10 stuck gate).
                    if verdict == "tests-fault" \
                            and workflow.patched(KI122_ADOPTION_PATCH_ID):
                        # KI-122②（要求②）：tests 上限触顶的封面必须**具名**——谁判的
                        # （泳道计轮面按仲裁 verdict 判，非人判）、依据（连续 N 轮／豁免
                        # M 轮，且外部处置不再归零）、下一步（出路四条，不再自动重跑）。
                        # 尾注追加在 route 串尾（split 取用点与既有形态逐字不变）。
                        route += tests_fault_cap_audit_text(
                            tests_rounds, MAX_TESTS_FAULT_ROUNDS,
                            tests_exempt_rounds, MAX_TESTS_EXEMPT_ROUNDS)
                    if await self._blocked_over_limit(route.split(":", 1)[1]):
                        arb_done = False
                        arb_res = None
                    continue
                if verdict == "tests-fault":
                    if workflow.patched(TESTS_STREAK_PATCH_ID):
                        adoption = None
                        if workflow.patched(KI122_ADOPTION_PATCH_ID):
                            # KI-122①（260926 宿主直修令）：**采纳判决**面——零新增红
                            # （blockers 逐条在已知红名册里）+ 非环境面 + 无启动级 error
                            # → 推进 acceptance_walkthrough，不再每轮烧一趟全量。
                            # 判据单写者=shared.blockers_known_red_adoption（名册归属，
                            # 不另造红绿判据）；名册读不到=adopt False（fail-closed）。
                            adoption = await self._tests_fault_adoption(cur_integ)
                            if adoption.get("adopt"):
                                self._finish("arbitrate", by="integration-agent",
                                             evidence=res.evidence or res.summary)
                                self._handoff("arbitrate", adoption["note"],
                                              artifacts=res.deliverables, report=res.report)
                                self._log("仲裁 tests-fault 判决已采纳（零新增红 + "
                                          "blockers 全属在册既有红）→ acceptance_walkthrough")
                                phase = "acceptance"
                                continue
                        adoption_note = str((adoption or {}).get("note") or "")
                        if adoption_note:
                            # 名册不可用/有非在册红 → 照旧拦、照旧重跑，但原因必须
                            # 上票面（名册路径 + 失败原因），不静默。
                            self._log("tests-fault 判决未采纳：%s" % adoption_note)
                        # t260917-09：连续计数转移（计轮/环境红豁免/抖动复跑全绿豁免，
                        # 单写者=tests_round_step；探针只在名单非空时发）。
                        tests_rounds, tests_exempt_rounds, counted, note = \
                            await self._tests_round_account(
                                tests_rounds, tests_exempt_rounds, cur_integ)
                        if tests_exempt_rounds > MAX_TESTS_EXEMPT_ROUNDS:
                            # 连续豁免也超限（防活循环）——封面出路必须真实（要求④）：
                            # 授权在场=接受本判决→复位推进（C2 闭环，与 cap 面同构三件套）；
                            # 无授权=blocked（文案四条出路全部可执行）＋ KI-061 复活守卫。
                            arb_authz = self._arbitration_authz()
                            if arb_authz is not None:
                                self._append_authz_use(
                                    arb_authz, "arbitrate",
                                    "接受仲裁判决：verdict=tests-fault（连续豁免超限面，%s）"
                                    "→ acceptance_walkthrough" % note)
                                tests_rounds, tests_exempt_rounds, _, _ = \
                                    tests_round_step("accept-reset", tests_rounds,
                                                     tests_exempt_rounds)
                                self._finish("arbitrate", by="integration-agent",
                                             evidence=res.evidence or res.summary)
                                self._handoff(
                                    "arbitrate",
                                    "连续豁免超限封面经人授权接受判决（豁免面，"
                                    "接受仲裁判决）→ "
                                    "acceptance_walkthrough：verdict=tests-fault，%s"
                                    "（授权人 %s，签发 %s，到期 %s，理由 %s）"
                                    % (note, arb_authz.get("who"),
                                       arb_authz.get("issued"),
                                       arb_authz.get("expires"),
                                       arb_authz.get("reason")),
                                    report=res.report)
                                self._log("仲裁连续豁免超限经人授权接受判决（%s）→ "
                                          "acceptance_walkthrough"
                                          % arb_authz.get("who"))
                                phase = "acceptance"
                                continue
                            if await self._blocked_over_limit(
                                    tests_exempt_cap_blocked_text(
                                        tests_exempt_rounds,
                                        audit=tests_fault_cap_audit_text(
                                            tests_rounds, MAX_TESTS_FAULT_ROUNDS,
                                            tests_exempt_rounds,
                                            MAX_TESTS_EXEMPT_ROUNDS, adoption_note))):
                                arb_done = False
                                arb_res = None
                            continue
                        # 260929 判停（宿主令直修）：测量面与上轮逐字相同 ⇒ 不再重跑全套
                        if workflow.patched(INTEG_STALL_PATCH_ID):
                            stall = self._integ_round_stall(cur_integ)
                            if stall["stall"]:
                                self._log("集成判停：%s" % stall["note"])
                                if await self._blocked_over_limit(stall["note"]):
                                    arb_done = False
                                    arb_res = None
                                continue
                        # B2（260929 宿主令）：豁免轮归宿收口——**只有本票新增产品红**
                        # 才重跑整轮。环境面/已知红面（红项已被具名 env_red 吸收、或闸
                        # blockers 空=零新增红）不再无脑重跑：重跑不会让环境红变绿
                        # （供给/共享台面），只烧 ~30 分钟一轮 ×5–6 轮后假封。红项一律
                        # 具名（下条 handoff 逐条点名），绝不静默。上限机制
                        # （MAX_TESTS_EXEMPT_ROUNDS 等）保留为兜底，语义不废。
                        if not counted and self._acceptance_without_rerun(cur_integ):
                            self._finish("arbitrate", by="integration-agent",
                                         evidence=res.evidence or res.summary)
                            self._handoff(
                                "arbitrate",
                                "环境面/已知红面，不重跑（%s）：%s%s%s"
                                % (note, (res.summary or "")[:80],
                                   self._env_red_face_note(
                                       getattr(cur_integ, "env_red", None)),
                                   (" " + adoption_note) if adoption_note else ""),
                                report=res.report)
                            self._log("tests-fault 环境面/已知红面（%s）——不重跑整轮，"
                                      "直接进验收（红项具名）" % note)
                            tests_streak = True
                            phase = "acceptance"
                            continue
                        if not counted:
                            # 假封防护（要求③）：该轮不计入——留痕点名原因，直接重跑
                            # 集成测试（上限不吃这一轮，但套件仍要重新收敛）。
                            self._handoff("arbitrate",
                                          "本轮不计入 tests-fault 轮次（%s）：%s%s"
                                          % (note, (res.summary or "")[:120],
                                             (" " + adoption_note) if adoption_note else ""),
                                          report=res.report)
                            self._log("tests-fault 豁免不计轮（%s；连续豁免 %d/%d）"
                                      % (note, tests_exempt_rounds,
                                         MAX_TESTS_EXEMPT_ROUNDS))
                            tests_streak = True
                            phase = "run_integration_tests"
                            continue
                        tests_streak = True
                        acct_note = "（%s）" % note
                    else:
                        tests_rounds += 1
                        acct_note = ""
                        adoption_note = ""
                    self._handoff("arbitrate", "测试集迭代（第 %d 轮）%s：%s%s"
                                  % (tests_rounds, acct_note,
                                     (res.summary or "")[:120],
                                     (" " + adoption_note) if adoption_note else ""),
                                  report=res.report)
                    self._log("tests-fault → 重跑集成测试（第 %d 轮）" % tests_rounds)
                    phase = "run_integration_tests"
                    continue
                code_rounds += 1
                # t260917-09：code-fault=非 tests-fault 轮 → 连续计数复位（留痕要求②）
                if workflow.patched(TESTS_STREAK_PATCH_ID):
                    tests_rounds, tests_exempt_rounds, _, _ = \
                        tests_round_step("streak-reset", tests_rounds,
                                         tests_exempt_rounds)
                    self._log("tests_rounds 计数复位（仲裁 code-fault，连续语义）")
                prev_ctx = ("【集成测试报告（第 %d 轮）】verdict=code-fault\n%s\n%s"
                            % (code_rounds, res.report or res.summary or "",
                               res.evidence or "")).strip()
                self._handoff("arbitrate", "code-fault 打回 implement（第 %d 轮）" % code_rounds,
                              report=res.report)
                self._log("code-fault 打回 → implement（第 %d 轮）" % code_rounds)
                impl_done = False
                phase = self._auto_rework("implement", "code-fault 打回 implement（第 %d 轮）"
                                          % code_rounds, who="workflow",
                                          fallback="arbitrate")
                continue

            # 3.3.1) t260903-02 speedup 2: arbitrate ∥ acceptance_walkthrough as a
            #      parallel fork. Both consume the same mechanical test result from
            #      different angles with no data dependency, so gathering saves a serial
            #      stretch. Edge names are always STAGES ids (resolvable by _step);
            #      arb_acc_parallel is only a phase value for main-loop dispatch.
            #      Sequence: gather completes → single settle_lane (a tests-fault suite
            #      change is committed before the re-run) → arbitrate verdict → routing.
            if phase == "arb_acc_parallel":
                pend = []
                if not arb_done:
                    pend.append("arbitrate")
                if not acc_done:
                    pend.append("acceptance_walkthrough")
                if pend:
                    # KI-024: the fork's active edge list goes into meta (the workbench's
                    # dual-display source of truth; the single stage field stays
                    # untouched).
                    # t260915-01 ③（A6）：同 parallel_impl_design——相位名门内才传。
                    set_parallel_stages(
                        self.meta, pend,
                        phase="arb_acc_parallel"
                              if getattr(self, "_detail_face_on", False) else "")
                    try:
                        rs = await asyncio.gather(*[
                            self._run_agent_step(
                                n, arb_ctx if n == "arbitrate" else acc_ctx,
                                settle=False) for n in pend],
                            return_exceptions=True)
                    except Exception as e:  # gather itself should not raise (return_exceptions); defensive
                        await self._blocked("arb_acc_parallel", "并行分叉异常：%s" % e)
                        continue
                    failed = False
                    for name, r in zip(pend, rs):
                        if isinstance(r, Exception):
                            failed = True
                            # KI-024 waiting-period contract (fixed): drop the failed
                            # edge, same as the parallel_impl_design branch (the failed
                            # edge shows ✗ through its timeline blocked entry).
                            set_parallel_stages(
                                self.meta, [n for n in pend if n != name])
                            await self._blocked(name, format_agent_stage_failure(
                                self.ticket_id, name, r, gen=self._gen(name)))
                            break  # _blocked waits for retry_qc/rework; after waking, recompute pend and retry only the failed edge
                    if failed:
                        continue
                    for name, r in zip(pend, rs):
                        if name == "arbitrate":
                            arb_done = True
                            arb_res = r
                        else:
                            acc_done = True
                            acc_res = r
                if not (arb_done and acc_done):
                    continue
                # KI-024: both edges done = leaving the parallel period, delete
                # parallel_stages (everything after — the verdict judgment, a
                # format-correction re-run of the arbitrate edge — is single-edge serial
                # with no dual display semantics; routing back to run_integration_tests
                # should also return to the single display).
                set_parallel_stages(self.meta, [])
                # Single-point settle: commit first (a tests-fault suite change must be
                # committed before the mechanical tests re-run, otherwise the re-run
                # happens on uncommitted state and a blocked leaves a dirty worktree),
                # then judge the verdict.
                try:
                    sraw = await workflow.execute_activity(
                        settle_lane,
                        SettleLaneArgs(ticket_id=self.ticket_id,
                                       worktree=str(self.meta.get("worktree") or ""),
                                       stage_id="arbitrate", gen=tests_rounds,
                                       write_set=list(self.meta.get("write_set") or []),
                                       base_ref=str(self.meta.get("base_ref") or ""),
                                       path_gate=bool(self.meta.get("path_gate")),
                                       path_gate_rules=dict(self.meta.get("path_gate_rules") or {}),
                                       authorizations=self._protected_authz_records()),
                        start_to_close_timeout=SHORT, retry_policy=RETRY)
                    s = sraw if isinstance(sraw, SettleLaneResult) else SettleLaneResult(
                        note=str(sraw.get("note") or ""),
                        lane_commits=int(sraw.get("lane_commits") or -1),
                        error=str(sraw.get("error") or ""))
                    # t260912-03：仲裁段落盘的授权消费留痕（机读键在场才记）
                    self._record_authz_uses(s.note, "arbitrate")
                    # t260911-03：路径闸拒绝（越权改动不落盘）→ blocked 点名，不进
                    # 「不拦主链」的日志通道——套件改动没 commit 就重跑机械测试是
                    # 假红制造机，必须停在闸上等处置。
                    if s.error and "path_gate_reason=" in s.error:
                        # t260915-01 ②（A3）：同 integ_join——结构化明细上台面
                        self._pin_settle_refusal(s)
                        # t260916-19 A：同批闸拒复判点名（retry_qc 无变化重跑不改变结果）
                        rep = self._gate_refusal_repeat_suffix(
                            (getattr(s, "gate_refusal", None) or {}).get("files"))
                        # t260925-17（KI-120）：复位被闸挡住的仲裁边——否则唤醒后
                        # pend 恒空（两 done 旗仍 True），叉不重入、agent 不重生，
                        # 票定格「blocked + 空 reason」零活动（t260925-05 实案）。
                        # 醒后 pend=["arbitrate"]，仲裁边真重跑（agent respawn），
                        # join settle 随重落时带 _protected_authz_records() 重新判闸
                        # ——「authorize 已 landing 但 settle 仍拒」形态由此收口
                        # （review 附条件①：authorizations 每轮 settle 现取现传）。
                        # arb_ctx 同步注入授权上下文：人外部输入进新 prompt，醒后
                        # 重裁不消费滞留的陈旧判决（KI-061 教训同源）。
                        if workflow.patched(KI120_FORK_GATE_WAKE_RESET_PATCH_ID):
                            arb_done = False
                            arb_res = None
                            arb_ctx = ("【闸拒解除】上一轮 join 落盘被受保护路径闸拒绝；"
                                       "相关路径已经人授权放行（kind=protected_path，"
                                       "meta.authorizations 可查）。请基于本轮全量面续裁。")
                        await self._blocked("arbitrate", s.error + rep)
                        continue
                    self._log("并行分叉统一落盘：%s（泳道 commit 数 %s）"
                              % (s.note or "干净", s.lane_commits))
                except Exception as e:  # settle failure: noted, main chain unaffected; the run's 0-commit pre-check catches it
                    self._log("settle_lane 故障（不拦主链）：%s: %s" % (type(e).__name__, e))
                if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(arb_res):
                    # t260916-28: 环境缺件故障直落 blocked；复位 fork 簿记（对齐下方
                    # 格式纠正段的既有复位形态），retry_qc 醒来后 arbitrate 边真重跑
                    # 而不是吃滞留的 failed 回执（KI-061 同款 no-op 坑）。
                    await self._block_agent_failed("arbitrate", arb_res)
                    arb_done = False
                    arb_res = None
                    continue
                verdict = parse_arbitration_summary(arb_res.summary)
                if not verdict:
                    arb_format_rounds += 1
                    if arb_format_rounds > 2:
                        await self._blocked("arbitrate",
                                            "仲裁结论 %d 次缺 verdict= 标记（契约：summary 含 "
                                            "verdict=pass|tests-fault|code-fault）" % arb_format_rounds)
                        # t260905-10: waking resets that single edge — arb_res is
                        # discarded, arb_done back to False, and the main loop genuinely
                        # re-runs the arbitrate edge (the prompt is rebuilt, so a ruling
                        # injected via host_ruling is visible this round). Without the
                        # reset the join would eat the memoized stale arb_res and block
                        # again immediately, arbitrate never re-spawning — retry_qc's
                        # "re-run this step" would be a no-op. The walkthrough result
                        # stays in memory and is not re-run.
                        arb_done = False
                        arb_res = None
                        continue
                    # The format correction re-runs only the arbitrate edge (the
                    # walkthrough is expensive and format-independent, its result stays in
                    # memory); that edge uses settle=True: there may be a suite change
                    # before the correction that still needs committing.
                    arb_done = False
                    arb_res = None
                    arb_ctx = ("【格式纠正】你的上一份结论缺少 verdict= 标记。请严格输出三态之一："
                               "verdict=pass / verdict=tests-fault / verdict=code-fault，并重判。")
                    pend = ["arbitrate"]
                    try:
                        rraw = await self._run_agent_step("arbitrate", arb_ctx, settle=True)
                    except Exception as e:
                        await self._blocked("arbitrate", format_agent_stage_failure(
                            self.ticket_id, "arbitrate", e, gen=self._gen("arbitrate")))
                        continue
                    if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(rraw):
                        # t260916-28: 环境缺件故障直落 blocked（进入本段前 arb_done/
                        # arb_res 已复位，此处尚未置 True——无需再动簿记，醒来后本边
                        # 真重跑）。
                        await self._block_agent_failed("arbitrate", rraw)
                        continue
                    # t260917-01：同串行分支——纠正分支的 settle 闸拒不进格式计数
                    # （t260916-19/-21 的误判正是本分支三连计数后 blocked）。此处置
                    # False 时 arb_done 已在上方置 False：唤醒后 pend 重算、仲裁边
                    # 真重跑（acc_res 保留不重跑，KI-024 语义）。
                    # t260917-04：过 patched 门（同串行分支，短路语义一致）。
                    if workflow.patched(ARBITRATE_REFUSAL_PATCH_ID) \
                            and await self._arbitrate_refusal_blocked(rraw):
                        continue
                    arb_done = True
                    arb_res = rraw
                    verdict = parse_arbitration_summary(arb_res.summary)
                    if not verdict:
                        continue  # count the format correction on the next loop (re-judged at the outer branch entry)
                arb_ctx = ""
                arb_authz = self._arbitration_authz()
                route = arbitration_cap_route(verdict, tests_rounds, code_rounds,
                                              arb_authz is not None)
                # t260912-03：超限 + 本票生效中的「接受本判决」授权 → 与 verdict=pass
                # 同形推进（_finish 落 arbitrate 终态 + _handoff 记判决原文与授权），
                # 并复用 pass 的在飞走查结果消费路径（C2）。
                authz_advance = bool(verdict != "pass" and arb_authz is not None
                                     and route == "acceptance")
                if verdict == "pass" and workflow.patched(TARGETED_RERUN_PATCH_ID) \
                        and last_run_only:
                    # t260923 D 收口拦截（同串行支）：pass 落在定点跑上——补收口全量跑；
                    # 零新增红 → pass 成立继续走下方放行；有新增红 → 判决作废，仲裁边
                    # 真重跑（arb_done 复位，同 t260917-04 复位置换语义）。
                    closing = await self._closing_full_run()
                    cur_integ = closing
                    last_run_only = []
                    prev_red_names = self._tests_red_names(closing)
                    _new_red = list(getattr(closing, "blockers", None) or [])
                    if _new_red or getattr(closing, "error", ""):
                        self._log("收口全量跑有新增红（%s）——pass 判决作废，仲裁边真重跑"
                                  % (",".join(_new_red)
                                     or ("启动级 error：" + str(closing.error))))
                        arb_done = False
                        arb_res = None
                        arb_ctx = ("【收口重裁】上一轮 verdict=pass 落在定点跑上，收口全量跑"
                                   "发现新增红（%s）。请按全量面重判三态。"
                                   % (",".join(_new_red) or "启动级 error"))
                        continue
                    self._log("收口全量跑零新增红——pass 判决成立（放行只认全量）")
                if verdict == "pass" or authz_advance:
                    # t260917-09：连续语义复位点——pass=收敛、人工接受判决=收敛
                    # （authz_advance 两面都复位；R2 伪 verdict 复用 tests_round_step）。
                    if workflow.patched(TESTS_STREAK_PATCH_ID):
                        tests_rounds, tests_exempt_rounds, _, _ = \
                            tests_round_step("accept-reset", tests_rounds,
                                             tests_exempt_rounds)
                        self._log("tests_rounds 计数复位（%s，连续语义）"
                                  % ("仲裁 pass" if verdict == "pass"
                                     else "人工接受判决"))
                    if authz_advance:
                        reason_txt = integration_route(verdict, tests_rounds,
                                                       code_rounds).split(":", 1)[-1]
                        self._append_authz_use(
                            arb_authz, "arbitrate",
                            "接受仲裁判决：verdict=%s（%s）→ acceptance_walkthrough"
                            % (verdict, reason_txt))
                        arb_note = (
                            "仲裁超限封面经人授权接受判决（接受仲裁判决）→ acceptance_walkthrough：verdict=%s，%s"
                            "（授权人 %s，签发 %s，到期 %s，理由 %s）"
                            % (verdict, reason_txt, arb_authz.get("who"),
                               arb_authz.get("issued"), arb_authz.get("expires"),
                               arb_authz.get("reason")))
                    else:
                        arb_note = "仲裁通过：" + (arb_res.summary or "")
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=arb_res.evidence or arb_res.summary)
                    self._handoff("arbitrate", arb_note,
                                  artifacts=arb_res.deliverables, report=arb_res.report)
                    if authz_advance:
                        self._log("仲裁超限经人授权接受判决（%s）→ acceptance_walkthrough"
                                  % arb_authz.get("who"))
                    # Consume the parallel walkthrough result (valid only on
                    # verdict=pass; non-pass is discarded below)
                    if acc_res is not None and acc_res.status == "ok":
                        self._finish("acceptance_walkthrough", by="integration-agent",
                                     evidence=acc_res.evidence or acc_res.summary)
                        self._handoff("acceptance", "验收报告：" + (acc_res.summary or ""),
                                      artifacts=acc_res.deliverables, report=acc_res.report)
                        phase = "merge_check"
                        # KI-003: yield once at the tail of the judgment+consume mutation
                        # cluster (queued queries do not hit 8s)
                        await self._breathe()
                        continue
                    if acc_res is not None:
                        if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(acc_res):
                            # t260916-28: 环境缺件故障直落 blocked——不打回 implement、
                            # 不污染 acc_rounds；复位 walkthrough 簿记（blocked 返回后
                            # 再复位，醒来的主循环重算 pend 时 acceptance 边真重跑）。
                            await self._block_agent_failed("acceptance_walkthrough", acc_res)
                            acc_done = False
                            acc_res = None
                            continue
                        # Walkthrough edge reported failure: the existing acceptance
                        # send-back loop (same contract as the old acceptance branch)
                        acc_rounds += 1
                        prev_ctx = ("【验收走查打回（第 %d 轮）】走查发现代码问题：\n%s"
                                    % (acc_rounds, acc_res.report or acc_res.summary or "")).strip()
                        self._handoff("acceptance", "验收打回 implement（第 %d 轮）" % acc_rounds,
                                      report=acc_res.report)
                        if acc_rounds > MAX_ACCEPTANCE_ROUNDS:
                            await self._blocked("acceptance",
                                                "验收走查打回 %d 轮超限（上限 %d）"
                                                % (acc_rounds, MAX_ACCEPTANCE_ROUNDS))
                            continue
                        self._log("acceptance 打回 → implement（第 %d 轮）" % acc_rounds)
                        impl_done = False
                        phase = self._auto_rework("implement",
                                                  "验收走查打回（第 %d 轮）" % acc_rounds,
                                                  who="workflow", fallback="arbitrate")
                        continue
                    # Walkthrough edge missing (left behind by an abnormal re-run): fall
                    # back to the old serial acceptance to catch up
                    phase = "acceptance"
                    continue
                if route.startswith("blocked:"):
                    # KI-061: fixing the wake deadlock of an over-limit blocked state —
                    # genuinely re-run this step. The guard mechanism (a unique patch id
                    # per entry, against the SDK's memoized first verdict) and the replay
                    # stability argument live in _blocked_over_limit; without the reset,
                    # waking eats the memoized arbitration verdict, blocks again at once,
                    # and arbitrate is never re-spawned (the t260907-10 stuck gate).
                    if verdict == "tests-fault" \
                            and workflow.patched(KI122_ADOPTION_PATCH_ID):
                        # KI-122②：与串行分支同构——tests 上限触顶封面具名（谁判的/
                        # 依据/下一步），且不再自动重跑；尾注追加在 route 串尾。
                        route += tests_fault_cap_audit_text(
                            tests_rounds, MAX_TESTS_FAULT_ROUNDS,
                            tests_exempt_rounds, MAX_TESTS_EXEMPT_ROUNDS)
                    if await self._blocked_over_limit(route.split(":", 1)[1]):
                        arb_done = False
                        arb_res = None
                    continue
                # Non-pass: this round's parallel walkthrough result is discarded (the
                # single-point reset at the run_integration_tests entry re-walks once the
                # loop converges) — the note is searchable, never silently dropped.
                self._log("acceptance 本轮作废：仲裁 %s，回路收敛后重走查" % verdict)
                acc_res = None
                acc_done = False
                if verdict == "tests-fault":
                    if workflow.patched(TESTS_STREAK_PATCH_ID):
                        adoption = None
                        if workflow.patched(KI122_ADOPTION_PATCH_ID):
                            # KI-122①：与串行分支同构（共用 _tests_fault_adoption，
                            # 判据单写者=shared.blockers_known_red_adoption）——零新增红
                            # + blockers 全属在册既有红 → 采纳判决推进验收，不再重跑全量。
                            adoption = await self._tests_fault_adoption(cur_integ)
                            if adoption.get("adopt"):
                                self._finish("arbitrate", by="integration-agent",
                                             evidence=arb_res.evidence or arb_res.summary)
                                self._handoff("arbitrate", adoption["note"],
                                              artifacts=arb_res.deliverables,
                                              report=arb_res.report)
                                self._log("仲裁 tests-fault 判决已采纳（零新增红 + "
                                          "blockers 全属在册既有红）→ acceptance_walkthrough")
                                phase = "acceptance"
                                continue
                        adoption_note = str((adoption or {}).get("note") or "")
                        if adoption_note:
                            self._log("tests-fault 判决未采纳：%s" % adoption_note)
                        # t260917-09：连续计数转移（与串行分支同构，共用
                        # _tests_round_account；豁免超限封面出路=授权接受/blocked＋
                        # KI-061 复活守卫，见串行分支注）。
                        tests_rounds, tests_exempt_rounds, counted, note = \
                            await self._tests_round_account(
                                tests_rounds, tests_exempt_rounds, cur_integ)
                        if tests_exempt_rounds > MAX_TESTS_EXEMPT_ROUNDS:
                            arb_authz = self._arbitration_authz()
                            if arb_authz is not None:
                                self._append_authz_use(
                                    arb_authz, "arbitrate",
                                    "接受仲裁判决：verdict=tests-fault（连续豁免超限面，%s）"
                                    "→ acceptance_walkthrough" % note)
                                tests_rounds, tests_exempt_rounds, _, _ = \
                                    tests_round_step("accept-reset", tests_rounds,
                                                     tests_exempt_rounds)
                                self._finish("arbitrate", by="integration-agent",
                                             evidence=arb_res.evidence or arb_res.summary)
                                self._handoff(
                                    "arbitrate",
                                    "连续豁免超限封面经人授权接受判决（豁免面，"
                                    "接受仲裁判决）→ "
                                    "acceptance_walkthrough：verdict=tests-fault，%s"
                                    "（授权人 %s，签发 %s，到期 %s，理由 %s）"
                                    % (note, arb_authz.get("who"),
                                       arb_authz.get("issued"),
                                       arb_authz.get("expires"),
                                       arb_authz.get("reason")),
                                    report=arb_res.report)
                                self._log("仲裁连续豁免超限经人授权接受判决（%s）→ "
                                          "acceptance_walkthrough"
                                          % arb_authz.get("who"))
                                phase = "acceptance"
                                continue
                            if await self._blocked_over_limit(
                                    tests_exempt_cap_blocked_text(
                                        tests_exempt_rounds,
                                        audit=tests_fault_cap_audit_text(
                                            tests_rounds, MAX_TESTS_FAULT_ROUNDS,
                                            tests_exempt_rounds,
                                            MAX_TESTS_EXEMPT_ROUNDS, adoption_note))):
                                arb_done = False
                                arb_res = None
                            continue
                        # 260929 判停（宿主令直修）：与串行分支同构——测量面与上轮
                        # 逐字相同 ⇒ 不再重跑全套，转人审（判据单写者=gate_round_signature）
                        if workflow.patched(INTEG_STALL_PATCH_ID):
                            stall2 = self._integ_round_stall(cur_integ)
                            if stall2["stall"]:
                                self._log("集成判停：%s" % stall2["note"])
                                if await self._blocked_over_limit(stall2["note"]):
                                    arb_done = False
                                    arb_res = None
                                continue
                        # B2（260929 宿主令）：与串行分支同构——环境面/已知红面不再重跑
                        # 整轮，直接进验收；只有本票新增产品红才重跑（理由见串行分支注）。
                        if not counted and self._acceptance_without_rerun(cur_integ):
                            self._finish("arbitrate", by="integration-agent",
                                         evidence=arb_res.evidence or arb_res.summary)
                            self._handoff(
                                "arbitrate",
                                "环境面/已知红面，不重跑（%s）：%s%s%s"
                                % (note, (arb_res.summary or "")[:80],
                                   self._env_red_face_note(
                                       getattr(cur_integ, "env_red", None)),
                                   (" " + adoption_note) if adoption_note else ""),
                                report=arb_res.report)
                            self._log("tests-fault 环境面/已知红面（%s）——不重跑整轮，"
                                      "直接进验收（红项具名）" % note)
                            tests_streak = True
                            phase = "acceptance"
                            continue
                        if not counted:
                            self._handoff("arbitrate",
                                          "本轮不计入 tests-fault 轮次（%s）：%s%s"
                                          % (note, (arb_res.summary or "")[:120],
                                             (" " + adoption_note) if adoption_note else ""),
                                          report=arb_res.report)
                            self._log("tests-fault 豁免不计轮（%s；连续豁免 %d/%d）"
                                      % (note, tests_exempt_rounds,
                                         MAX_TESTS_EXEMPT_ROUNDS))
                            tests_streak = True
                            phase = "run_integration_tests"
                            continue
                        tests_streak = True
                        acct_note = "（%s）" % note
                    else:
                        tests_rounds += 1
                        acct_note = ""
                        adoption_note = ""
                    self._handoff("arbitrate", "测试集迭代（第 %d 轮）%s：%s%s"
                                  % (tests_rounds, acct_note,
                                     (arb_res.summary or "")[:120],
                                     (" " + adoption_note) if adoption_note else ""),
                                  report=arb_res.report)
                    self._log("tests-fault → 重跑集成测试（第 %d 轮）" % tests_rounds)
                    phase = "run_integration_tests"
                    continue
                code_rounds += 1
                # t260917-09：code-fault=非 tests-fault 轮 → 连续计数复位（留痕要求②）
                if workflow.patched(TESTS_STREAK_PATCH_ID):
                    tests_rounds, tests_exempt_rounds, _, _ = \
                        tests_round_step("streak-reset", tests_rounds,
                                         tests_exempt_rounds)
                    self._log("tests_rounds 计数复位（仲裁 code-fault，连续语义）")
                prev_ctx = ("【集成测试报告（第 %d 轮）】verdict=code-fault\n%s\n%s"
                            % (code_rounds, arb_res.report or arb_res.summary or "",
                               arb_res.evidence or "")).strip()
                self._handoff("arbitrate", "code-fault 打回 implement（第 %d 轮）" % code_rounds,
                              report=arb_res.report)
                self._log("code-fault 打回 → implement（第 %d 轮）" % code_rounds)
                impl_done = False
                phase = self._auto_rework("implement", "code-fault 打回 implement（第 %d 轮）"
                                          % code_rounds, who="workflow",
                                          fallback="arbitrate")
                continue

            # 3.4) acceptance walkthrough (integration walks it from the user's view →
            #      acceptance report, for the human gate to consult)
            if phase == "acceptance":
                acc_ctx = (("【UI 截图/走查实证（.sandbar/screenshots/）】\n%s\n" % ui_ctx) if ui_ctx else "")
                try:
                    res = await self._run_agent_step("acceptance_walkthrough", acc_ctx)
                except Exception as e:
                    await self._blocked("acceptance", format_agent_stage_failure(
                        self.ticket_id, "acceptance", e,
                        gen=self._gen("acceptance_walkthrough")))
                    continue
                if res.status == "ok":
                    self._finish("acceptance_walkthrough", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("acceptance", "验收报告：" + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    phase = "merge_check"
                    continue
                if workflow.patched(LANE_DSH_BLOCK_PATCH_ID) and self._lane_dsh_refusal(res):
                    # t260916-28: 环境缺件故障直落 blocked——「走查发现代码问题」的
                    # 打回叙事为假、acc_rounds 不被环境故障污染、不白烧一轮 implement
                    # 重入。
                    await self._block_agent_failed("acceptance_walkthrough", res)
                    continue
                acc_rounds += 1
                prev_ctx = ("【验收走查打回（第 %d 轮）】走查发现代码问题：\n%s"
                            % (acc_rounds, res.report or res.summary or "")).strip()
                self._handoff("acceptance", "验收打回 implement（第 %d 轮）" % acc_rounds,
                              report=res.report)
                if acc_rounds > MAX_ACCEPTANCE_ROUNDS:
                    await self._blocked("acceptance",
                                        "验收走查打回 %d 轮超限（上限 %d）"
                                        % (acc_rounds, MAX_ACCEPTANCE_ROUNDS))
                    continue
                self._log("acceptance 打回 → implement（第 %d 轮）" % acc_rounds)
                impl_done = False
                # t260901-04: an automatic send-back after a failed acceptance must land
                # a state='rework' timeline record — the workbench rework banner consumes
                # only state=rework, so without it the user never sees why.
                phase = self._auto_rework("implement", "验收走查打回（第 %d 轮）" % acc_rounds,
                                          who="workflow", fallback="acceptance")
                continue

            # 4) merge_check (programmatic, no agent)
            if phase == "merge_check":
                self._enter("merge_check")
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
                                   # t260921-09：建票「本票无文件改动」声明（meta 链
                                   # client.py ticket-start → meta.no_file_changes）
                                   # 透传给 merge_check 的整票零 commit 全局闸豁免
                                   no_file_changes=bool(self.meta.get("no_file_changes"))),
                    start_to_close_timeout=MERGE_CHECK_TO, retry_policy=RETRY)
                mc = raw if isinstance(raw, MergeCheckResult) else MergeCheckResult(
                    green=bool(raw.get("green")), checks=list(raw.get("checks") or []),
                    error=str(raw.get("error") or ""),
                    conflict=bool(raw.get("conflict")),
                    conflict_files=[str(x) for x in (raw.get("conflict_files") or [])],
                    merge_tree_excerpt=str(raw.get("merge_tree_excerpt") or ""))
                # t260912-03：merge_check 自愈 settle 的授权消费留痕（键在场才记）
                self._record_authz_uses(
                    "；".join(str(c.get("detail") or "") for c in mc.checks), "merge_check")
                self.gate_runs.append({
                    "stage": "merge_check", "label": "merge_check（程序化检查）",
                    "green": mc.green,
                    "red_count": len([c for c in mc.checks if not c.get("green")]),
                    "exit_code": 0, "checks": mc.checks,
                    "conflict": mc.conflict, "conflict_files": mc.conflict_files})
                if mc.green:
                    conflict_rounds = 0
                    prev_conflict_files = []
                    self._finish("merge_check", by="merge_check",
                                 evidence="；".join(c.get("item", "") for c in mc.checks))
                    self._handoff("merge_check", "合并检查四项全绿")
                    phase = "merge"
                    continue
                # 260927 ⑥：逐条带出该红的**处置**（宿主实报：旧文案只有首红的处置，
                # 于是「脏工作区红」被读成「预演冲突不会自动消解」）。
                red = "；".join(
                    "%s: %s%s" % (c.get("item"), c.get("detail"),
                                  ("｜处置：%s" % c.get("next_action")) if c.get("next_action") else "")
                    for c in mc.checks if not c.get("green"))
                # t260826-01 conflict auto-resolution loop: only a merge dry-run conflict
                # red (mc.conflict) skips blocked and automatically sends work back to
                # implement for resolution (reusing the rework loop, no signal needed);
                # every other red stays blocked waiting for a human.
                if not mc.conflict:
                    # t260915-01 ②（A4）：非冲突红转 blocked——首红项既有结论结构化
                    # 紧邻 _blocked 写入（当前受阻明细；非 blocked 期由清点①②清空）。
                    # 260927 ⑥：同时逐条结构化全部红 + 本轮路由结论（纯加法）。
                    self._pin_merge_red_detail(
                        mc.checks,
                        disposition="本轮=非冲突红 → blocked 等人；逐条处置见 reds")
                    await self._blocked("merge_check", "merge_check 红灯：%s" % (red or mc.error))
                    continue
                # ---- conflict-class reds: round counting + loop protection (the blocked
                #      wording anchors are grep-stable) ----
                conflict_rounds += 1
                files_sig = sorted(mc.conflict_files)
                files_txt = "、".join(files_sig)[:200]
                if conflict_rounds > MAX_CONFLICT_ROUNDS:
                    # t260915-01 ②（A4）：conflict 类转人工的红——首红项（rehearsal）
                    # /conflict_files 结构化，紧邻 _blocked（C6 口径：消解常态路径不写）
                    self._pin_merge_red_detail(
                        mc.checks, mc.conflict_files,
                        disposition="本轮=冲突类红，消解 %d 轮未收敛（上限 %d）→ 转人工处置"
                                    % (conflict_rounds - 1, MAX_CONFLICT_ROUNDS))
                    await self._blocked(
                        "merge_check",
                        "冲突消解 %d 轮未收敛（上限 %d），转人工处置：冲突文件 %s"
                        % (conflict_rounds - 1, MAX_CONFLICT_ROUNDS, files_txt))
                    continue
                if prev_conflict_files and files_sig == prev_conflict_files:
                    self._pin_merge_red_detail(
                        mc.checks, mc.conflict_files,
                        disposition="本轮=同批文件连续 2 轮相同冲突（第 %d 轮）→ 转人工处置"
                                    % conflict_rounds)
                    await self._blocked(
                        "merge_check",
                        "同批文件反复冲突（连续 2 轮集合相同，第 %d 轮），转人工处置：%s"
                        % (conflict_rounds, files_txt))
                    continue
                prev_conflict_files = files_sig
                self._log("merge_check 检出 merge 预演冲突（第 %d/%d 轮），自动打回 implement 消解：%s"
                          % (conflict_rounds, MAX_CONFLICT_ROUNDS, files_txt))
                self._handoff("merge_check", "冲突自动消解第 %d 轮：%s"
                              % (conflict_rounds, files_txt))
                # (1) the worker runs merge to leave the conflict scene in place (an agent
                #     sandbox cannot write a real .git)
                praw = await workflow.execute_activity(
                    prepare_conflict_resolution,
                    ConflictPrepArgs(ticket_id=self.ticket_id,
                                     worktree=str(self.meta.get("worktree") or ""),
                                     branch=str(self.meta.get("branch") or ""),
                                     base_ref="main"),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                prep = praw if isinstance(praw, ConflictPrepResult) else ConflictPrepResult(
                    ok=bool(praw.get("ok")),
                    conflict_files=[str(x) for x in (praw.get("conflict_files") or [])],
                    merge_output=str(praw.get("merge_output") or ""),
                    already_clean=bool(praw.get("already_clean")),
                    error=str(praw.get("error") or ""))
                if not prep.ok:
                    await self._blocked("merge_check", "冲突消解准备失败（第 %d 轮）：%s"
                                        % (conflict_rounds, prep.error or "未知"))
                    continue
                if prep.already_clean:
                    self._log("冲突消解 prep：merge 零冲突（竞态兜底），直接回 merge_check 重验")
                    continue
                # (2) the agent resolves the conflict markers (round markers, kept apart
                #     from feature-development and send-back rework rounds)
                solve_ctx = (
                    "【冲突消解轮 gen%d/上限%d】本轮不是功能开发：merge_check 检出 merge 预演冲突，"
                    "worker 已在泳道跑过 git merge main，以下文件留有冲突标记"
                    "（<<<<<<< 泳道 / ======= / >>>>>>> main）：\n%s\n"
                    "merge 输出摘要（ours=泳道 / theirs=main）：\n%s\n"
                    "任务：逐个文件解掉冲突标记，保持两边语义（通常是两边都保留的纯文本贴近，"
                    "t260825-03 同款）；只动冲突文件，不做无关改动；**不要 git commit**"
                    "（你交付结果文件后 worker 会代落盘合并提交）。解完写结果文件交付。"
                    % (conflict_rounds, MAX_CONFLICT_ROUNDS,
                       "\n".join("- %s" % f for f in prep.conflict_files),
                       (prep.merge_output or mc.merge_tree_excerpt or "（无输出）")[:1200]))
                try:
                    res = await self._run_agent_step("implement", solve_ctx)
                except Exception as e:
                    await self._blocked("implement", format_agent_stage_failure(
                        self.ticket_id, "implement", e, gen=self._gen("implement")))
                    continue
                prev_ctx = ""
                if res.status != "ok":
                    # t260917-08（review M3）：前缀变体一并路由——轮次前缀保留，
                    # 后半经 _agent_failed_why 单点路由（env 归因不缺、轮次上下文不丢）
                    # t260922-18：构造抽 _conflict_failed_note 单点（源码锁字面量/
                    # 调用计数恒 2/5；本站文案逐字不回归）
                    await self._blocked("implement", self._conflict_failed_note(
                        res, "冲突消解第 %d 轮：%s", conflict_rounds))
                    continue
                # (3) the worker commits the merge on the agent's behalf (verifying no
                #     unresolved files remain; the worktree is necessarily dirty during
                #     this window and merge_check is not run — prep→implement→settle→
                #     back to merge_check is strictly serial)
                sraw = await workflow.execute_activity(
                    settle_conflict_resolution,
                    ConflictSettleArgs(ticket_id=self.ticket_id,
                                       worktree=str(self.meta.get("worktree") or ""),
                                       branch=str(self.meta.get("branch") or ""),
                                       base_ref="main",
                                       round_no=conflict_rounds),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                sres = sraw if isinstance(sraw, ConflictSettleResult) else ConflictSettleResult(
                    ok=bool(sraw.get("ok")), commit=str(sraw.get("commit") or ""),
                    remaining_files=[str(x) for x in (sraw.get("remaining_files") or [])],
                    error=str(sraw.get("error") or ""))
                if not sres.ok:
                    why = ("仍有未解冲突文件：%s" % "、".join(sres.remaining_files[:10])
                           ) if sres.remaining_files else (sres.error or "未知")
                    # The worktree is in a "merge in progress" state here (MERGE_HEAD
                    # present) — a retry_qc would make merge_check block again on a
                    # "dirty worktree" red (a diagnostic mismatch), so the message gives
                    # handling instructions directly
                    await self._blocked(
                        "merge_check",
                        "冲突消解第 %d 轮未收敛（worker 代落盘校验未过），转人工处置：%s。"
                        "工作区现为合并进行中态——人工解冲突后发 rework 回 implement 续解，"
                        "或泳道内 git merge --abort 复位后发 retry_qc 重验"
                        % (conflict_rounds, why))
                    continue
                self._log("冲突消解第 %d 轮落盘 %s（%d 个文件），回 merge_check 重验"
                          % (conflict_rounds, sres.commit, len(prep.conflict_files)))
                self._handoff("implement", "冲突消解第 %d 轮落盘 %s"
                              % (conflict_rounds, sres.commit))
                # (4) the resolution goes straight back to merge_check for re-verification
                #     (the mechanical gate re-checks the worktree and the dry run)
                phase = "merge_check"
                continue

            # 5) merge (human gate → approve signature → the merge activity really merges)
            if phase == "merge":
                st = self._step("merge")
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
                self._log("merge 人审挂起，等 sign signal（merge_check 已全绿）")
                self._mark("merge", "awaiting-human", "等人签字：sign(gate=merge)")
                # t260928-13：人门是无限期等待，先冲账再挂起（事件账本 flush 点）
                await self._ledger_flush()
                await workflow.wait_condition(
                    lambda: ("merge" in self._sigs) or (self._rework is not None))
                if self._rework is not None:
                    continue  # unified stage-skip at the top of the main loop
                sig = self._sigs.pop("merge")
                self.signatures["merge"] = {"who": sig.who, "decision": sig.decision,
                                            "note": sig.note, "at": self._now_iso()}
                if sig.decision != "approve":
                    self._rework = ReworkRequest(
                        who=sig.who, target_stage="implement",
                        note="人在 merge 打回：%s（签字人 %s）" % (sig.note, sig.who))
                    continue
                # Approved signature → real merge
                self.meta["stage_state"] = "running"
                self._mark("merge", "running", "人审通过（%s），执行 merge" % sig.who)
                # t260910-14: the pre-run-next-ticket step retired — merge proceeds straight to
                # the merge activity after the signature.
                # t260902-02 M1-3 three-step close: merge only books (defer_teardown);
                # archiving (archive_ticket) and tearing down the lane (teardown_lane)
                # follow as separate steps — a fail-closed successful archive is the
                # precondition for tearing down (the stage report must not be lost with it).
                archive_on = workflow.patched(ARCHIVE_PATCH_ID)
                raw = await workflow.execute_activity(
                    merge,
                    MergeArgs(ticket_id=self.ticket_id,
                              worktree=str(self.meta.get("worktree") or ""),
                              branch=str(self.meta.get("branch") or ""),
                              base_ref=str(self.meta.get("base_ref") or ""),
                              defer_teardown=archive_on,
                              # 保险丝B 输入（t260910-03）：票面写集，merge 逐仓
                              # squash 前验「多仓写集 × 逐仓物化」。空=在途旧票
                              # 兼容（保险丝不触发），见 shared.MergeArgs 注释。
                              write_set=list(self.meta.get("write_set") or [])),
                    start_to_close_timeout=MERGE_TO, retry_policy=RETRY)
                mr = raw if isinstance(raw, MergeResult) else MergeResult(
                    ok=bool(raw.get("ok")), action=str(raw.get("action") or ""),
                    merge_commit=str(raw.get("merge_commit") or ""),
                    error=str(raw.get("error") or ""),
                    # KI-048 (t260911-05): the dict-deserialization state (this
                    # isinstance branch exists for exactly that) must back-fill the
                    # new classification fields too — otherwise the blocked text's
                    # point-named file list is lost on the workflow side and the
                    # ticket face goes blind (review_plan R3)
                    reason=str(raw.get("reason") or ""),
                    files=[str(x) for x in (raw.get("files") or [])])
                if not mr.ok and mr.action in ("dirty", "failed"):
                    # KI-048: a main-workspace dirt rejection ("dirty") is git's
                    # local-change protection, NOT a conflict — the verified lane
                    # code is fine, so auto-bouncing it for re-verification would
                    # silently consume the human sign-off and churn the ticket
                    # (t260904-14). Turn blocked for a human with a plain-language
                    # reason: which file / what / what to do. "failed" (infra/merge
                    # faults incl. fuse B) also blocks for a human — an unclassified
                    # fault must not idle the conflict-resolution loop either.
                    # The receipt's human phrase (mr.error) and the structured
                    # detail share the same _classify_main_dirty source of truth.
                    self.meta["blocked_detail"] = {
                        "reason_code": mr.reason or "merge_fault",
                        "files": list(mr.files)[:20],
                        "next_action": ("在 main 提交或暂存（git stash）这些改动，"
                                        "或票面说明后发 retry_qc 重验；引擎不自动 stash/提交")
                                       if mr.action == "dirty" else
                                       "合并执行故障（非冲突），人工处置后发 retry_qc 重验",
                    }
                    self._touch()
                    note = ("merge 未收口（%s/%s）： %s"
                            % (mr.action, mr.reason or "merge_fault",
                               (mr.error or "未知")[:400]))
                    self._log(note)
                    await self._blocked("merge", note)
                    continue
                if not mr.ok:
                    # Merge failure (typically a conflict caused by another lane reaching
                    # main first while we waited for the signature) — automatically send
                    # back to merge_check to re-verify the four items rather than blocking
                    # empty-handed: a red check blocks for a human naturally, a green check
                    # returns to the merge human gate for a fresh signature. Every round
                    # needs a human signature, so there is no infinite-loop risk. It goes
                    # through _auto_rework for the record (not by setting self._rework —
                    # setting it would make the main loop run _apply_rework a second time
                    # and land two timeline entries for one send-back, t260901-04).
                    # (Post-KI-048 this branch is conflict-only: dirty/failed split
                    # off above, per the failure-classification protocol.)
                    note = "merge 失败（%s）自动打回重验：%s" \
                           % (mr.action, (mr.error or "未知")[:300])
                    self._log(note)
                    phase = self._auto_rework("merge_check", note, who="workflow",
                                              fallback="merge")
                    continue
                if archive_on:
                    # archive_ticket: fail-closed — a failed archive means the report
                    # would be lost with the teardown, so go blocked and keep the lane
                    # (no bare raise: a workflow task retrying on an exception never
                    # reaches a terminal state, only blocked has an exit).
                    try:
                        ares = await workflow.execute_activity(
                            archive_ticket,
                            ArchiveArgs(ticket_id=self.ticket_id,
                                        project_key=str(self.meta.get("project") or ""),
                                        worktree=str(self.meta.get("worktree") or ""),
                                        meta=dict(self.meta)),
                            start_to_close_timeout=SHORT, retry_policy=RETRY)
                    except Exception as e:
                        await self._blocked(
                            "merge",
                            "工单数据归档失败（fail-closed，泳道保留不拆）：%s: %s%s"
                            % (type(e).__name__, str(e)[:400],
                               shared.exception_chain_note(e)))
                        continue
                    if not isinstance(ares, ArchiveResult) or not ares.ok:
                        await self._blocked(
                            "merge",
                            "工单数据归档回执异常（fail-closed，泳道保留不拆）：%s"
                            % ((getattr(ares, "error", "") or repr(ares))[:400]))
                        continue
                    self._log("工单数据出仓归档完成：%s"
                              % (getattr(ares, "archive_path", "") or "（路径未知）"))
                    # teardown_lane: tear down the lane (a cleanup failure only warns in
                    # the receipt; lane leftovers are reclaimable garbage, the data itself
                    # is already listed in archive.json, so closing the ticket is not
                    # blocked).
                    try:
                        tr = await workflow.execute_activity(
                            teardown_lane,
                            MergeArgs(ticket_id=self.ticket_id,
                                      worktree=str(self.meta.get("worktree") or ""),
                                      branch=str(self.meta.get("branch") or ""),
                                      # 拆道逐仓化（t260913-05）：meta.repo_worktrees 是
                                      # 明细真源，递给 teardown 逐仓三清——盘上清单镜像
                                      # 已随部分拆除消失（Temporal 重试）时，靠它仍能点
                                      # 名成员仓，绝不回落单仓锚留静默残留。payload 兼容：
                                      # 在途旧票无此键 → 空列表 → teardown 回落清单/单仓。
                                      repo_worktrees=list(self.meta.get("repo_worktrees") or [])),
                            start_to_close_timeout=SHORT, retry_policy=RETRY)
                    except Exception as e:
                        await self._blocked(
                            "merge",
                            "泳道拆除故障（本体已归档，泳道残留待人工）：%s: %s%s"
                            % (type(e).__name__, str(e)[:400],
                               shared.exception_chain_note(e)))
                        continue
                    if not isinstance(tr, MergeResult) or not tr.ok:
                        await self._blocked(
                            "merge",
                            "泳道拆除回执异常（本体已归档，泳道残留待人工）：%s"
                            % ((getattr(tr, "error", "") or repr(tr))[:400]))
                        continue
                    if tr.error:
                        self._log("泳道拆除告警（残留可回收，本体已归档）：%s"
                                  % tr.error)
                self._finish("merge", by=sig.who,
                             evidence="merge 落账 %s（人审 %s：%s）"
                                      % (mr.merge_commit, sig.who, sig.note))
                self._handoff("merge", "合并完成 %s" % mr.merge_commit)
                phase = "done"
                continue

            if not workflow.patched(UNKNOWN_PHASE_BLOCK_PATCH_ID):
                raise ValueError("未知阶段 %r" % phase)  # unreachable (the step chain is closed)
            # 260930（宿主令·nusuyou 需求⑥）：未知相位**绝不 raise**——本文件自己写着「主循环
            # 是裸 while True，抛出去=打断工作流实例」，而 raise 的后果就是票面 status=None、
            # 快照/show/query 全不可读（t260929-28 实案，票作废不可恢复）。改成 blocked：
            # 可查、可唤醒（retry_qc/rework）、原因具名（点名合法相位词表），把「不可恢复坏态」
            # 降成「等人处置」。相位夹到人门再 continue（_blocked 内部已 wait_condition，
            # 不会空转）。
            await self._blocked(
                REWORK_PHASE_FALLBACK,
                "内部相位解析出未知值 %r（合法相位=%s）——已停为人审（不再让工作流任务失败）；"
                "请用 rework(to_stage=<规范段名>) 复位，或 retry_qc 重驱"
                % (phase, "、".join(sorted(PHASE_MAIN_CHAIN - {"done"}))))
            phase = REWORK_PHASE_FALLBACK
            continue

        # Close out
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("merge 落账，工单收口（closed）")
        self._mark("merge", "closed", "workflow 完成")
        # t260928-13：收口前最后冲账——正常完单零 pending（行为验收口径）
        await self._ledger_flush()
        return self._snapshot()

    # ---------- signals: human-gate signature / rework / retry_qc ----------
    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """Human-gate signature (dev-lane has exactly one human gate, merge).

        t260912-03：本信号面也是**人授权例外通道的唯一入口**——带 authorize 载荷的
        sign 走授权 intake 分支（任意态可投：blocked/awaiting/running 均可，授权在
        下一轮 settle/超限判定被消费）；不带 authorize 的签字＝既有 merge 人门语义，
        逐字节不变。
        t260913-01：client op=authorize 发 sign 时 gate=AUTHZ_SIGNAL_GATE_MARKER——
        authorize 缺失但 gate=标记 ⇒ 载荷在传输/反序列化一跳丢失（旧 worker 的旧
        Signature 类解码时被 temporalio 静默丢弃），refused 点名「载荷解析失败」，
        绝不静默回落普通签字路径；marker 是保留值，普通签字路径逐字节不动。"""
        if getattr(sig, "authorize", None) is not None:
            self._intake_authorization(sig.authorize)
            return
        if str(getattr(sig, "gate", "") or "") == AUTHZ_SIGNAL_GATE_MARKER:
            self.refused.append(
                {"who": sig.who, "want": "sign(authorize)",
                 "why": "authorize 载荷解析失败：gate 标记在场但载荷为空（传输/反序列化"
                        "一跳丢失——疑似该票 worker 代码过期，重启该票专属 worker 后重试）；"
                        "不按普通签字处理"})
            self._log("人授权拒收（%s）：authorize 载荷解析失败（gate 标记在场但载荷为空）"
                      % (sig.who or "?"))
            return
        # t260915-12 跨项目闸（第二道，先于人门语义检查）：盖章值 vs 本票项目——
        # 不符无旗=refused 不落签字（跨项目拒收优先于「非人审等待中」，两类拒收不混）；
        # undeclared 哨兵/越权旗=记名放行（meta['cross_project_uses'] + timeline）。
        if not self._cross_project_gate(str(getattr(sig, "caller_project", "") or ""),
                                        str(getattr(sig, "cross_project_note", "") or ""),
                                        "sign", str(sig.who or ""), "sign"):
            return
        stage = str(self.meta.get("stage") or "")
        if stage != "merge" or self.meta.get("stage_state") != "awaiting-human":
            self.refused.append({"who": sig.who, "want": "sign(%s)" % sig.gate,
                                 "why": "当前步 %s 非人审等待中，签字无效" % stage})
            return
        if sig.gate and sig.gate != "merge":
            self.refused.append({"who": sig.who, "want": "sign(%s)" % sig.gate,
                                 "why": "gate 与当前等待步 merge 不符"})
            return
        self._sigs["merge"] = sig

    # ---------- 人授权例外通道（t260912-03）：签发 / 生效过滤 / 消费留痕 ----------
    def _intake_authorization(self, auth) -> None:
        """sign 面 authorize 载荷的 intake（任意态可投）：校验不过=refused 点名、不进
        事件历史（host_ruling/pause 同款双形态）；通过=append meta['authorizations']
        （kind/who/scope/reason/issued/expires/uses）+ 时间线签发事件 + log 记名。

        issued 由 workflow.now() 盖写（不信任调用方）；反自签（agent 角色名/-agent 后缀）
        与上限（who/reason/scope 条数与长度、expires 上限）在 authz_gates 单一实现。"""
        now = self._now_epoch()
        err = authz_gates.validate_authorization(auth, now, self.ticket_id)
        who = str(getattr(auth, "who", "") or (auth.get("who") if isinstance(auth, dict) else "") or "")
        if err:
            self.refused.append({"who": who, "want": "sign(authorize)",
                                 "why": err})
            self._log("人授权拒收（%s）：%s" % (who or "?", err))
            return
        rec = authz_gates.authorization_record(auth, now)
        self.meta.setdefault("authorizations", []).append(rec)
        note = ("人授权签发（%s）：kind=%s scope=%s 到期=%s 理由=%s"
                % (rec["who"], rec["kind"], "、".join(rec["scope"]),
                   authz_gates.fmt_ts(rec["expires"]), rec["reason"]))
        self.timeline.append({"at": self._now_iso(),
                              "stage": str(self.meta.get("stage") or ""),
                              "state": "authorized", "reason": note})
        self._log(note)
        self._touch()

    def _active_authz(self, kind: str) -> List[Dict[str, Any]]:
        """本票生效中的授权条目（kind 筛选；arbitration_verdict 另按票号筛 scope）。"""
        return active_authorizations(self.meta.get("authorizations"), self._now_epoch(),
                                     kind=kind, ticket_id=self.ticket_id)

    def _protected_authz_records(self) -> List[Dict[str, Any]]:
        """受保护闸 args 面：生效中的 protected_path 授权结构化记录（C1：带 who/issued/
        reason，activity 据此记名点名与归因）。"""
        return [dict(it) for it in self._active_authz(AUTH_PROTECTED_PATH)]

    def _arbitration_authz(self) -> Optional[Dict[str, Any]]:
        """生效中的「接受本判决」授权（最新签发者胜）——仲裁超限判定点的消费面。"""
        items = self._active_authz(AUTH_ARBITRATION_VERDICT)
        return items[-1] if items else None

    def _append_authz_use(self, rec: Dict[str, Any], stage: str, detail: str) -> None:
        """消费留痕（不可变历史的一部分：meta 变更随 workflow 事件落账）。"""
        rec.setdefault("uses", []).append(
            {"ts": self._now_epoch(), "stage": stage, "detail": detail})

    def _record_authz_uses(self, text: str, stage: str) -> None:
        """解析回执里的机读键 path_gate_authz_used=<who>@<issued>:<files> → 落 uses。
        只在键在场（=真发生豁免）时记——无受保护命中/未命中授权的回执没有键，不记。"""
        items = parse_authz_used(text)
        if not items:
            return
        for it in items:
            for rec in (self.meta.get("authorizations") or []):
                if not isinstance(rec, dict):
                    continue
                if str(rec.get("who") or "") == it["who"] \
                        and str(int(rec.get("issued") or 0)) == it["issued"]:
                    self._append_authz_use(rec, stage, "受保护路径豁免：%s" % it["files"])
                    self._log("人授权被使用（%s @ %s）：受保护路径 %s 放行落盘（段 %s）"
                              % (it["who"], it["issued"], it["files"], stage))

    @workflow.signal
    def rework(self, req: ReworkRequest) -> None:
        """Send back for a re-run: the target step re-enters (gen+1 → a fresh result
        file, the agent genuinely re-runs)."""
        # t260915-12 跨项目闸（第二道）：同 sign 口径（先于受理，拒收不置 self._rework）。
        if not self._cross_project_gate(str(getattr(req, "caller_project", "") or ""),
                                        str(getattr(req, "cross_project_note", "") or ""),
                                        "rework", str(req.who or ""), "rework"):
            return
        self._rework = req
        self._log("rework 请求：%s → %s（%s）"
                  % (req.note, req.target_stage or "缺省目标", req.who))

    @workflow.signal
    def retry_qc(self, who: str) -> None:
        """Request a re-run of the current step after a blocked."""
        self._retry_token += 1
        self.timeline.append(
            {"at": self._now_iso(), "stage": str(self.meta.get("stage") or ""),
             "state": "retry-requested",
             "reason": "%s 请求重跑（第 %d 次）" % (who, self._retry_token)})

    @workflow.signal
    def host_ruling(self, req: HostRulingRequest) -> None:
        """Host ruling injection (KI-053): the official channel for human opinions,
        sendable in any state (blocked included). A valid ruling is appended to
        meta['host_rulings'] (consumed by build_stage_prompt's injection) + _log; it does
        not automatically wake a blocked — the host sends the ruling and then retry_qc,
        and the next prompt picks it up.
        Two rejection shapes (recorded in refused, observable via snapshot): who/note
        empty or whitespace-only, and note over HOST_RULING_NOTE_INPUT_LIMIT (an intake
        gate keeping oversized payloads out of the event history)."""
        who = str(req.who or "").strip()
        note = str(req.note or "").strip()
        if not who or not note:
            self.refused.append({"who": who, "want": "host_ruling",
                                 "why": "who/note 均必填非空（空/纯空白拒收）"})
            return
        # t260915-12 跨项目闸（第二道）：intake 通过后、落账前的项目归属校验。
        if not self._cross_project_gate(str(getattr(req, "caller_project", "") or ""),
                                        str(getattr(req, "cross_project_note", "") or ""),
                                        "host_ruling", who, "host_ruling"):
            return
        if len(note) > HOST_RULING_NOTE_INPUT_LIMIT:
            self.refused.append({"who": who, "want": "host_ruling",
                                 "why": "note 超限（%d > %d 字符），不进事件历史——"
                                        "拆条后重发" % (len(note), HOST_RULING_NOTE_INPUT_LIMIT)})
            return
        self.meta.setdefault("host_rulings", []).append(
            {"ts": self._now_iso(), "who": who, "note": note})
        # The _log record only carries the head of the note (300-char truncation + a
        # marker) — the full text's source of truth is meta['host_rulings']; the log does
        # not carry large payloads twice (same family of trade-off as the intake gate).
        log_note = note if len(note) <= 300 else note[:300] + "…（截断，全文见 host_rulings）"
        self._log("宿主裁决注入（%s）：%s" % (who, log_note))
        self._touch()

    # ---------- update: status maintenance (same name and payload as base.py, client.py serves both) ----------
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

        与 base.py 同名 handler 逐行同形（家族拷贝惯例）；真值表 UT 对两个类各钉一遍。
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

    # ---------- query: read-only snapshot (same keys as base.py, consumed transparently by the workbench/ticket.py) ----------
    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        stage = str(self.meta.get("stage") or "")
        sdef: Optional[Stage] = None
        for s in self.STAGES:
            if s.id == stage:
                sdef = s
                break
        return {
            "engine": ENGINE_V2,
            "ticket_id": self.ticket_id,
            "template_id": self.TEMPLATE_ID,
            "workflow_class": type(self).__name__,
            **self._pause_snapshot(),
            "stage": stage,
            "stage_name": sdef.name if sdef else "",
            "stage_acceptance": list(sdef.acceptance) if sdef else [],
            "stage_state": self.meta.get("stage_state"),
            "status": self.meta.get("status"),
            "role": self.meta.get("role"),
            "workspace": self.meta.get("workspace"),
            "revision_count": 0,
            "last_advance_stage": None,
            "temporal_engine_version": self.meta.get("temporal_engine_version"),
            "acceptance": self.meta.get("acceptance"),
            "checks": self.meta.get("checks"),
            "handoffs": self.meta.get("handoffs"),
            "pending": self.meta.get("pending"),
            "signatures": self.signatures,
            "gate_runs": self.gate_runs,
            "refused": self.refused,
            "timeline": self.timeline,
            # t260928-13 [R-merge]：事件账本迁移标记（[{i,seq,run}]；timeline 条目
            # 本身零标记——票面形状逐字不变）。空表=无标记（未启用/老票），增量键。
            "ledger_marks": self._ledger_marks or [],
            "results": self.results,
            "human_context": self.human_context,
            "retry_count": self._retry_token,
            # KI-048 (t260911-05): top-level blocked face — blocked_reason = the last
            # _blocked why (plain language, same _classify_main_dirty source), 
            # blocked_detail = the structured {reason_code, files, next_action} the
            # workflow pins when a merge fails dirty/failed. Empty/absent = never
            # blocked (the status card on the UI side renders nothing, zero intrusion
            # for legacy tickets).
            "blocked_reason": str(self.meta.get("blocked_reason") or ""),
            "blocked_detail": self.meta.get("blocked_detail"),
            # t260915-01 ③：段→第几轮（gen）读数（门内新段；拷贝=查询只读，不暴露
            # 内部计数器）。并行相位=meta.parallel_stages/parallel_phase（随上方
            # meta 键上台面）+ timeline 条目的 gen/phase 键。R1 纪律：此处只读
            # _detail_face_on 缓存位——@query 内禁止 SDK 的门判定调用（只读约束）。
            **({"gens": dict(self._gens)}
               if getattr(self, "_detail_face_on", False) else {}),
            # t260915-05 ④：模板拓扑导出（门内 additive 键=旧实例重放零新键；纯函数
            # 查表零 IO；查询体只读缓存位，不触 SDK 门判定——R1 同纪律）。消费双层：
            # 快照有则用快照＝旧票渲染时点拓扑（mock ④「渲染时点快照的拓扑，不追新」），
            # 无则回落模板级导出（workflow.py list topology 键）；None=未声明模板，
            # 渲染器回落线性呈现，绝不猜拓扑。
            **({"topology": template_topology.export_template_topology(self.TEMPLATE_ID)}
               if getattr(self, "_detail_face_on", False) else {}),
            "meta": dict(self.meta),
        }

    # ---------- query: sign 信号面指纹（t260913-01） ----------
    @workflow.query
    def sign_face(self) -> Dict[str, Any]:
        """本 worker 进程所跑代码的 sign 信号面指纹（shared.sign_face_fingerprint 单一
        实现，query 时在 worker 进程内现算）。旧 worker（早于 t260913-01 的代码）没有
        本 query ⇒ 客户端收到「expected but not found」= 结构性陈旧判别；字段集漂移 ⇒
        客户端比对 mismatch。纯计算零状态访问（重放安全），authorize 投递前由 CLI
        先验，缺失/漂移一律拒发。"""
        return sign_face_fingerprint()

    def _snapshot(self) -> Dict[str, Any]:
        return self.snapshot()
