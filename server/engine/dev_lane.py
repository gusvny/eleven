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
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from base import TicketCrossProjectMixin, TicketPauseMixin
    import authz_gates
    import path_gates  # t260915-01 ②：闸拒绝结构化明细的构造/校形（纯函数零 IO）
    # t260915-05：模板拓扑导出面（纯数据零 IO；mock ④「引擎按模板导出 stage 图」，
    # 渲染器只认节点+边+kind——KI-019 线性近似泳道图的真拓扑承载）。
    import template_topology
    from agent_activities import (
        arbitrate,
        acceptance_walkthrough,
        archive_ticket,
        merge,
        merge_check,
        prepare_conflict_resolution,
        prepare_human_gate,
        prepare_ui_evidence,
        prepare_workspace,
        run_integration_tests,
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
        MAX_TESTS_FAULT_ROUNDS,
        TICKET_STATUSES,
        AUTH_ARBITRATION_VERDICT,
        AUTH_PROTECTED_PATH,
        AUTHZ_SIGNAL_GATE_MARKER,
        AgentStageArgs,
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
        arbitration_cap_route,
        build_stage_prompt,
        build_workspace_prep,
        format_agent_stage_failure,
        integration_route,
        is_ui_write_set,
        lane_workspace_gate_error,
        normalize_files_changed,
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
    )

SHORT = timedelta(minutes=2)
MERGE_CHECK_TO = timedelta(minutes=20)   # merge_check includes the in-lane verify_lane
                                         # (tsc/smoke, can take minutes)
MERGE_TO = timedelta(minutes=5)
AGENT_TO = timedelta(hours=6)
HEARTBEAT_TO = timedelta(minutes=3)
# 机械集成测试条目的活动超时（配对不变量，t260913-01 仲裁修 + t260913-02 实测合流）：
# 本值必须 > agent_activities.BATCH_TIMEOUT_SEC + 300s（内层 wait_for 守卫），否则内层
# 的结构化超时回报永远等不到、只剩 Temporal 硬杀 + 3 次重试（260913 两轮 0 跑无归因；
# t260913-02 gen1 亦实测同形态）。单测 test_t260913_01_integ_budget_pair.py 机械锁住
# 「内层 < 外层」与内层缺省上界；一改必查另一侧。
# 两端各自的实测依据：内层缺省收紧为 3000+300=3300s≈55min（t260913-01：正常套件
# ≈25min，超窗交结构化回报；exclude_pools 后每票集测实测 wall 179.5s ≪ 60min）；
# 外层 60min 在此口径下余量充足。**全集（含 engine+exclusive 重池）的长墙钟口径不在
# 本值**——那走每日巡检的 `inspection_flow.SUITE_TO=120min`（恒全跑、不经池排除，
# 已按同一不等式钉住 > 5700s），两条预算各守各的面。
INTEG_RUN_TO = timedelta(minutes=60)
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
# t260916-28: a failed StageResult carrying a lane_dsh_* gate_refusal（spawn 前的
# 泳道 .dsh 自洽预检拒绝）必须在全部 agent 段消费点直落 blocked「agent 报失败」——
# arbitrate 的 verdict 循环、acceptance 打回循环与 parallel_impl_design 汇合边的
# 既有处理会把它误读成「缺 verdict= 标记」/「走查发现代码问题」/无声吞成假完成。
# Same-shaped boolean gate (see the first PATCH_ID note).
LANE_DSH_BLOCK_PATCH_ID = "dev-lane-lane-dsh-block-v1"
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
        "逼分解成为想过的选择而非习惯模子；review_plan 可据此追问切法合理性。"),
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
        "方案涉及消费外部输入 → 验收必须含畸形输入用例，缺→打回。"),
    "implement": (
        "按已通过方案实现。硬性纪律：写集白名单内；**不要自己 git commit**"
        "（沙箱写不了真 .git，你交付结果文件后 worker 会确定性代落盘）；"
        "相关 smoke/自测跑绿，证据写进 evidence。"
        "本票改动以 UT 交付行为断言（落项目声明的测试目录），verify code 道跑绿。"
        "UI 票（写集命中 UI 口径）交付证据须含改动前后截图"
        "（.sandbar/screenshots/，ui-check/capture.mjs 产出）或说明为何无视觉差异。"),
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
        "ENV_FAIL（exit 2）不写 SKIP（exit 0）；N/A 仅给系统状态条件腿，全腿 N/A=场景红。"
        "落盘后先跑 python3 integration/lint_tests.py（秒级静态检查：语法/import/清单/intent），"
        "红则先修再交结果文件——不要把静态错误拖到套件执行时才暴露。"
        "结果文件 status=failed 仅限你无法产出测试集的极端情况。"),
    "arbitrate": (
        "你是 integration 仲裁。机械集成测试已跑完，结果见上下文。三态判定（summary "
        "**必须以 verdict= 开头标明**，如「verdict=code-fault …」）："
        "verdict=pass 全部通过 → 进入验收；"
        "verdict=tests-fault 测试集自身问题（环境/前提/断言错）→ **你直接迭代 integration/ 里的"
        "测试集修正**（改动随本步落盘），summary 写清改了什么、为什么是测试的问题；"
        "verdict=code-fault 实现问题 → report 写**集成测试报告**（失败场景、复现要点、"
        "期望 vs 实际），打回 developer 修改。除三态外不许发明其它结论。"
        "归因纪律（t260904-12 三态判据）：先固定问句「环境面还是产品面？」——"
        "ENV_FAIL（exit 2，缺环境）归 tests-fault 供给面：修复=补测试环境/供给声明"
        "（乙段 verify.yaml supply），绝不把环境红记成代码问题；FAIL（exit 1）归产品。"
        "乙段（verify_lane env_fail 计数）落地前环境红以 err/退出码形态出现，按输出尾段"
        "归因。窗口期（供给声明未落地）UI 票过闸只走 break-glass 人显式签字留痕，"
        "不许以「环境面」口头豁免放行。"
        "发现新故障模式在结果文件上报（描述+定位+复现），不直接写已知问题清单——登记由 integration 岗位统一做。"
        "打回轮回审查令：若本轮回打中单测（UT）或集成测试文件发生任何变更（含你自己的 tests-fault 迭代），"
        "逐条核对变更是否弱化了断言/收窄了覆盖面——测试改动必须让契约更准而非让红灯变绿，"
        "summary 单列「测试资产变更审查」小节列出每处测试变更与理由。"),
    "acceptance_walkthrough": (
        "你是 integration 验收。本步与仲裁（arbitrate）**并行**执行：机械集成测试结果已随"
        "上下文注入（与仲裁同源），走查以**用户视角**独立进行，不预设「测试已全部通过」——"
        "你只管从用户场景走查并写验收报告（供人类最终合并审查）。重点审查项：对照打回轮次，若期间 UT/集成测试文件有变更，逐处核实变更意图（契约精确化 vs 绿灯捷径），在报告设「测试资产变更审查」小节；发现可疑弱化即 status=failed。走查实证（隔离台截图/DOM 断言输出）已注入上下文：逐场景"
        "给出结论与证据引用；发现代码问题 → status=failed + report 写明问题（会打回 "
        "developer）；一切正常 → status=ok + report=验收报告全文。报告面向不熟悉本工单的人。"
        "（仲裁若判 tests-fault/code-fault，本轮走查结果会作废、回路收敛后重新走查——不必"
        "在报告里替仲裁下结论。）"),
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
class DevLaneWorkflow(TicketPauseMixin, TicketCrossProjectMixin):
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
    TEMPLATE_LANE = "worktree"
    TEMPLATE_WORKSPACE_DIR = False
    TEMPLATE_DESC = ("开发泳道（developer 系唯一流程）：prepare_workspace→create_plan⇄review_plan"
                     "→implement∥design_integration_tests→汇合（ui_evidence/UI 票）"
                     "→run_integration_tests→arbitrate→acceptance_walkthrough"
                     "→merge_check（程序化）→merge（人审）")
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
              desc="程序化（无 agent）：跑项目声明场景执行器 integration/run_scenarios.py（cwd=泳道），"
                   "结果 JSON 交仲裁判定；前置检查泳道落盘（0 commit = 实现未落盘 → blocked）",
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
                          "merge 预演无冲突（冲突则自动消解 %d 轮内收敛）" % MAX_CONFLICT_ROUNDS)),
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
        first = self.STAGES[0]
        acc = list(first.acceptance) + [x for x in inp.acceptance_extra
                                        if x not in first.acceptance]
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
            "acceptance": acc,
            "checks": {s.id: [{"item": it, "done": False, "by": ""} for it in s.acceptance]
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
                     "note": "工单创建（dev-lane：activity 直编排，步=%s）"
                             % [s.id for s in self.STAGES]}],
        }
        self._mark("create_plan", "awaiting", "adopt dev-lane（步=%s）"
                   % [s.id for s in self.STAGES])

    # ---------- step entry (the meta/ledger trio) ----------
    def _enter(self, step_id: str) -> None:
        st = self._step(step_id)
        self._gens[step_id] = self._gen(step_id) + 1
        self.meta["stage"] = step_id
        self.meta["role"] = st.role
        self.meta["status"] = "dispatched"
        self.meta["stage_state"] = "running"
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
                self._log("【红灯】写集刷新被拒：create_plan 回执 %s（KI-049：空/畸形"
                          "回执=写集刷新静默 no-op 根因）——写集保持初始 %d 条零污染；"
                          "处置：rework 回 create_plan 重交结构化回执"
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

    async def _block_agent_failed(self, step_id: str, res: Any) -> None:
        """agent 报失败（业务裁决失败）在非 generic 站点的统一 blocked 落点
        （t260916-28）：文案与 generic 站既有两分同款「agent 报失败：」；结构化
        明细已由 _pin_agent_refusal 在 _run_agent_step 单点钉上 meta.blocked_detail，
        此处不重复写。"""
        await self._blocked(step_id, "agent 报失败：%s"
                            % (str(getattr(res, "summary", "") or "")
                               or str(getattr(res, "status", "") or "")))

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

    def _pin_merge_red_detail(self, checks: Any, fallback_files: Any = None) -> None:
        """merge_check 红灯的结构化明细（A4）：取首红项的既有结论（id/item/
        reason_code/files/next_action/detail）结构化写 blocked_detail——只做「已有
        结论结构化」，红绿判定与文案零改动。无红项时回落 fallback_files（conflict
        类的 conflict_files，D4 已逐文件在 checks 里，此处是畸形兜底）。三处调用点
        全部紧邻 _blocked（非 blocked 期由清点①②清空，R2 生命周期）。"""
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
        safe = path_gates.sanitize_gate_refusal(detail)
        if safe:
            self.meta["blocked_detail"] = safe

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
        brief = FLOW_BRIEF.get(step_id)
        if brief:
            prompt += "\n%d. 本步契约（dev-lane 流程约定）：%s" % (_prompt_next_no(prompt), brief)
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
            res = StageResult(
                status=str(raw.get("status") or "ok"),
                summary=str(raw.get("summary") or ""),
                report=str(raw.get("report") or ""),
                deliverables=[str(x) for x in (raw.get("deliverables") or [])],
                files_changed=_fc,
                files_changed_shape=_fc_shape,
                evidence=str(raw.get("evidence") or ""),
                # t260915-01 ②：结构化闸拒绝明细随回执（缺省 None=老回执/在途重放安全）
                gate_refusal=raw.get("gate_refusal"))
        self.results[step_id] = {
            "status": res.status, "summary": res.summary, "report": res.report,
            "deliverables": list(res.deliverables),
            "files_changed": list(res.files_changed),
            "files_changed_shape": res.files_changed_shape,
            "evidence": res.evidence, "gen": gen}
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
            return fallback if fallback in PHASE_MAIN_CHAIN else \
                str(self.meta.get("stage") or fallback)
        if fallback == "done" or fallback not in PHASE_MAIN_CHAIN:
            self.refused.append({"who": who,
                                 "want": "rework(%s) fallback(%s)" % (target, fallback),
                                 "why": "fallback 不在打回词表（纯防呆，字面量不应出现）"})
            self._log("rework 拒绝：fallback %r 非法，停 meta 现步（%s）" % (fallback, who))
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

    # ---------- main flow (direct activity orchestration) ----------
    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)

        # 1) prepare_workspace (code, no agent; failure → blocked waiting for retry/rework)
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
            self.meta["workspace_prep"] = {"ok": res.ok, "kind": res.kind, "action": res.action,
                                           "path": res.path, "error": res.error}
            self._touch()
            if res.ok:
                self._mark("workspace", "ready",
                           "prepare_workspace: %s/%s" % (res.kind, res.action))
                break
            await self._blocked("workspace", "工作空间准备失败：%s" % (res.error or "未知"))
            if self._rework is not None:
                self._apply_rework("create_plan")  # target stage is taken over by the main loop

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
        tests_rounds = 0                          # arbitrate tests-fault suite iterations, cumulative
        acc_rounds = 0                            # acceptance-walkthrough send-backs, cumulative
        arb_format_rounds = 0                     # consecutive arbitrate outputs missing the verdict= marker
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
            if self._rework is not None:
                fb = "implement" if phase == "parallel_impl_design" else phase
                # KI-024: a rework leaving a parallel period (target is a serial section)
                # must clear parallel_stages — otherwise the stale list pins edges that
                # already left on UI ▶ forever (one of two clearing paths, the other is
                # at the join point; the waiting-period contract is spelled out in the
                # failure-edge comments of each parallel branch).
                if phase in ("parallel_impl_design", "arb_acc_parallel"):
                    set_parallel_stages(self.meta, [])
                phase = self._apply_rework(fb)
                # KI-003: yield once after the rework bookkeeping burst (_auto_rework's
                # _log/_mark/_touch) so a queued snapshot query sees the post-rework state.
                await self._breathe()
                prev_ctx = str(self.meta.get("last_rework_note") or "")
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
                    await self._blocked("create_plan", "agent 报失败：%s" % (res.summary or res.status))
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
                    await self._blocked("implement", "agent 报失败：%s" % (res.summary or res.status))
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
                            ui_ctx = "【UI 截图证据缺失】activity 故障：%s: %s" % (type(e).__name__, e)
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
                    await self._blocked("implement", "agent 报失败：%s" % (res.summary or res.status))
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
                    await self._blocked("implement", s.error)
                    continue
                self._log("汇合统一落盘：%s（泳道 commit 数 %s）"
                          % (s.note or "干净", s.lane_commits))
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
                            ui_judge_note = ("ui_changed_paths 故障 fail-closed：%s: %s"
                                             % (type(e).__name__, e))
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
                        ui_ctx = "【UI 截图证据缺失】activity 故障：%s: %s" % (type(e).__name__, e)
                        self._log("prepare_ui_evidence 故障（不拦主链，merge_check 闸兜底）：%s" % str(e)[:200])
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
                # Pre-check, mechanical: the lane has been committed (guaranteed after
                # the unified settle; tickets with no_file_changes are exempt)
                if workflow.patched(REVIEW_GATE_PATCH_ID) and not self.meta.get("no_file_changes"):
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
                                "实现未落盘（泳道 0 commit）——实现步产物缺失，"
                                "发 rework 回 implement 或排查实现步")
                            continue
                    except Exception as e:
                        self._log("落盘前置检查故障（不拦主链）：%s: %s" % (type(e).__name__, e))
                try:
                    rraw = await workflow.execute_activity(
                        run_integration_tests,
                        IntegrationRunArgs(ticket_id=self.ticket_id,
                                           worktree=str(self.meta.get("worktree") or ""),
                                           attempt=self._gen("run_integration_tests") + 1,
                                           # t260913-03：每票段唯一 true 站（策略面只在
                                           # 调用点显式置位；write_set 供例外腿求交）
                                           write_set=list(self.meta.get("write_set") or []),
                                           apply_skip_pools=True),
                        start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
                    ir = rraw if isinstance(rraw, IntegrationRunResult) else IntegrationRunResult(
                        ran=int(rraw.get("ran") or 0), passed=int(rraw.get("passed") or 0),
                        failed=int(rraw.get("failed") or 0),
                        env_fail=int(rraw.get("env_fail") or 0),
                        details=[dict(d) for d in (rraw.get("details") or [])],
                        error=str(rraw.get("error") or ""))
                except Exception as e:
                    ir = IntegrationRunResult(error="集成测试 activity 故障：%s: %s"
                                              % (type(e).__name__, e))
                # t260904-12: the headline carries the environment-red dimension — a
                # mixed suite can no longer tell a fake "all green" story.
                # t260913-03: the exclusion face is named on the ticket face.
                # 宿主 260914 口径：例外腿已撤除——每票段一律跳过声明池，票面只报跳过面；
                # 旧口径命中面（forced_by）只作迁移期留痕，不再出现在票面注记里。
                _pe_note = ""
                if ir.excluded_pools:
                    _pe_note = "｜本轮跳过池=%s（少 %d 条）" % (
                        "、".join(ir.excluded_pools), ir.excluded_count)
                self.results["run_integration_tests"] = {
                    "status": "failed" if (ir.error or ir.failed or ir.env_fail) else "ok",
                    "summary": "集成测试：%d 跑 / %d 过 / %d 败 / %d 环境红%s%s"
                               % (ir.ran, ir.passed, ir.failed, ir.env_fail,
                                  ("｜" + ir.error) if ir.error else "", _pe_note),
                    "report": "", "deliverables": [], "files_changed": [],
                    "evidence": json.dumps(ir.details, ensure_ascii=False)[:4000], "gen": 0}
                self._finish("run_integration_tests", by="run_integration_tests",
                             evidence="；".join("%s:%s" % (d.get("name"),
                                                    "过" if d.get("exit") == 0 else "败")
                                                for d in ir.details))
                self._handoff("run_integration_tests",
                              "集成测试 %d 跑 / %d 过 / %d 败 / %d 环境红%s%s"
                              % (ir.ran, ir.passed, ir.failed, ir.env_fail,
                                 ("｜" + ir.error) if ir.error else "", _pe_note))
                # t260901-19: budget 6000→4000 with tail-keeping ([-4000:]) — details sit
                # at the end of the JSON, so a head slice would squeeze out the failure
                # details; keeping the tail keeps them
                _arb_json = json.dumps({"ran": ir.ran, "passed": ir.passed,
                                        "failed": ir.failed, "error": ir.error,
                                        "details": ir.details}, ensure_ascii=False)
                arb_ctx = ("【机械集成测试结果】\n%s\n【测试集】仓库 integration/ 目录"
                           "（integration/ 场景文件与清单为准；你是其作者，tests-fault 时直接迭代它）"
                           % _arb_json[-4000:])
                # t260903-02 (2): the walkthrough edge consumes the same test result as
                # the arbitration (the user-view walkthrough is independent and does not
                # assume all tests passed); the UI walkthrough evidence is injected too.
                acc_ctx = ("【机械集成测试结果】\n%s\n" % _arb_json[-4000:]) + \
                    (("【UI 截图/走查实证（.sandbar/screenshots/）】\n%s\n" % ui_ctx)
                     if ui_ctx else "")
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
                    self._append_authz_use(
                        arb_authz, "arbitrate",
                        "接受仲裁判决：verdict=%s（%s）→ acceptance_walkthrough"
                        % (verdict, cap_reason))
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff(
                        "arbitrate",
                        "仲裁超限经人授权接受判决 → acceptance_walkthrough：verdict=%s，%s"
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
                    if await self._blocked_over_limit(route.split(":", 1)[1]):
                        arb_done = False
                        arb_res = None
                    continue
                if verdict == "tests-fault":
                    tests_rounds += 1
                    self._handoff("arbitrate", "测试集迭代（第 %d 轮）：%s"
                                  % (tests_rounds, (res.summary or "")[:120]), report=res.report)
                    self._log("tests-fault → 重跑集成测试（第 %d 轮）" % tests_rounds)
                    phase = "run_integration_tests"
                    continue
                code_rounds += 1
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
                        await self._blocked("arbitrate", s.error)
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
                if verdict == "pass" or authz_advance:
                    if authz_advance:
                        reason_txt = integration_route(verdict, tests_rounds,
                                                       code_rounds).split(":", 1)[-1]
                        self._append_authz_use(
                            arb_authz, "arbitrate",
                            "接受仲裁判决：verdict=%s（%s）→ acceptance_walkthrough"
                            % (verdict, reason_txt))
                        arb_note = (
                            "仲裁超限经人授权接受判决 → acceptance_walkthrough：verdict=%s，%s"
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
                    tests_rounds += 1
                    self._handoff("arbitrate", "测试集迭代（第 %d 轮）：%s"
                                  % (tests_rounds, (arb_res.summary or "")[:120]),
                                  report=arb_res.report)
                    self._log("tests-fault → 重跑集成测试（第 %d 轮）" % tests_rounds)
                    phase = "run_integration_tests"
                    continue
                code_rounds += 1
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
                                   authorizations=self._protected_authz_records()),
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
                red = "；".join("%s: %s" % (c.get("item"), c.get("detail"))
                                for c in mc.checks if not c.get("green"))
                # t260826-01 conflict auto-resolution loop: only a merge dry-run conflict
                # red (mc.conflict) skips blocked and automatically sends work back to
                # implement for resolution (reusing the rework loop, no signal needed);
                # every other red stays blocked waiting for a human.
                if not mc.conflict:
                    # t260915-01 ②（A4）：非冲突红转 blocked——首红项既有结论结构化
                    # 紧邻 _blocked 写入（当前受阻明细；非 blocked 期由清点①②清空）。
                    self._pin_merge_red_detail(mc.checks)
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
                    self._pin_merge_red_detail(mc.checks, mc.conflict_files)
                    await self._blocked(
                        "merge_check",
                        "冲突消解 %d 轮未收敛（上限 %d），转人工处置：冲突文件 %s"
                        % (conflict_rounds - 1, MAX_CONFLICT_ROUNDS, files_txt))
                    continue
                if prev_conflict_files and files_sig == prev_conflict_files:
                    self._pin_merge_red_detail(mc.checks, mc.conflict_files)
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
                    await self._blocked("implement", "冲突消解第 %d 轮 agent 报失败：%s"
                                        % (conflict_rounds, (res.summary or res.status)[:200]))
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
                            "工单数据归档失败（fail-closed，泳道保留不拆）：%s: %s"
                            % (type(e).__name__, str(e)[:400]))
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
                            "泳道拆除故障（本体已归档，泳道残留待人工）：%s: %s"
                            % (type(e).__name__, str(e)[:400]))
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

            raise ValueError("未知阶段 %r" % phase)  # unreachable (the step chain is closed)

        # Close out
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("merge 落账，工单收口（closed）")
        self._mark("merge", "closed", "workflow 完成")
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
