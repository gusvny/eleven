"""dev-lane —— developer 系工单的唯一 workflow（260824 用户拍板，取代 code-lane/build-workbench）。

与六模版 stage 机的差别：**不发明"阶段"抽象，workflow 直接编排 activity**（步名=activity 名）：

    prepare_workspace（代码，无 agent）
      → create_plan（developer：出方案，不动代码）
        ⇄ review_plan（integration：写 review comments + 通过/打回；打回 → 回 create_plan）
      → 【并行分叉】implement（developer：代码+单测）∥ design_integration_tests
        （integration：按方案设计/迭代集成测试集，仓库 integration/ 目录，
          与 implement 并行；测试集不向 developer prompt 引导）
      → 汇合（settle_lane 统一代落盘：实现+测试集同 commit）→ ui_evidence（UI 票隔离台实拍）
      → run_integration_tests（机械，零 LLM：按项目声明场景执行器跑）
      → arbitrate（integration 三态仲裁：pass / tests-fault 迭代测试集重跑 / code-fault
                   集成测试报告打回 implement；各上限 5 轮，超限 blocked 交人）
      → acceptance（integration 用户视角走查新功能 → 验收报告，供人审门查阅）
      → merge_check（代码，无 agent：泳道有 commit / 工作区干净 / 泳道内 verify_lane 绿 /
                     merge-tree 预演无冲突——t260824-01「全绿但交付为零」漏的检查全在这里；
                     t260826-01 冲突自动消解回路：仅预演冲突红 → 自动打回 implement 解冲突
                     （worker 代跑 merge 留现场、agent 解标记、worker 代落盘），不转 blocked；
                     其它红灯维持 blocked 等人）
      → merge（人审门：挂起等 sign；签字通过 → merge activity 真合并 → 泳道清理 → closed；
                M1-3 起新票 = 三段收口 merge 只落账 → archive_ticket 出仓 → teardown_lane 拆泳道，
                归档 fail-closed 成功是拆泳道的前提）

打回循环的上下文继承：回 create_plan/implement 时把上一轮的 review comments 与上次产出
注入 prompt（previous_context，t260824-01 机制）——返工不是从零开始。
循环上限：方案审 MAX_REVIEW_ROUNDS / 集成测试仲裁与验收各见 shared 常量，超限转 blocked 等人判读。

确定性纪律同 base.py：本文件零 IO、零随机、零 wall-clock（只有 workflow.now()），
一切副作用在 activity。STAGES 类属性只是**展示/校验元数据**（yaml 生成、create 推导、
工单台泳道图），编排逻辑在下边 run() 里直写，与 STAGES 顺序一一对应。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
from datetime import timedelta
from typing import Any, Dict, List, Optional


def _sandbar_version() -> str:
    """自报 sandbar 版本（契约⑧-4）：读仓根 VERSION，缺失/脏 fail-closed 上抛。

    与 base.py 同款惰性 import（version.py 在 server/ 下）；legacy 键
    temporal_engine_version（int）原值保留不迁移，两键并存。
    """
    server_dir = str(pathlib.Path(__file__).resolve().parents[2])
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    import version as _version
    return _version.sandbar_version()


from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agent_activities import (
        arbitrate,
        acceptance_walkthrough,
        archive_ticket,
        merge,
        merge_check,
        prepare_conflict_resolution,
        prepare_epic_next,
        prepare_human_gate,
        prepare_ui_evidence,
        prepare_workspace,
        run_integration_tests,
        settle_conflict_resolution,
        settle_lane,
        suggest_next,
        teardown_lane,
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
        TEMPLATE_CLASS_NAMES,
        TEMPLATE_DISPLAY_NAMES,
        TICKET_STATUSES,
        AgentStageArgs,
        ConflictPrepArgs,
        ConflictPrepResult,
        ConflictSettleArgs,
        ConflictSettleResult,
        EpicNextPrepArgs,
        GateResult,
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
        UiEvidenceArgs,
        UiEvidenceResult,
        WorkspacePrep,
        WorkspacePrepResult,
        UI_EVIDENCE_DIR,
        agent_log_for,
        build_stage_prompt,
        build_suggest_next_prompt,
        integration_route,
        is_ui_write_set,
        lane_workspace_gate_error,
        parse_arbitration_summary,
        parse_review_plan_verdict,
        refresh_write_set,
        review_gate_verdict,
        review_plan_route,
        result_file_for,
        stage_workspace,
    )

SHORT = timedelta(minutes=2)
MERGE_CHECK_TO = timedelta(minutes=20)   # merge_check 含泳道内 verify_lane（tsc/smoke，可能数分钟）
MERGE_TO = timedelta(minutes=5)
AGENT_TO = timedelta(hours=6)
HEARTBEAT_TO = timedelta(minutes=3)
SUGGEST_NEXT_TO = timedelta(minutes=12)  # 预跑下一单：integration 实跑 1~5 分钟，软失败封顶
INTEG_RUN_TO = timedelta(minutes=60)     # 机械集成测试：场景执行器批量跑，批量封顶
RETRY = RetryPolicy(maximum_attempts=3)  # 只对基础设施故障生效；业务结论走 StageResult.status
# 预跑重试=1（t260828-08 定稿）：软失败路径 activity 自己返回 failed，不靠 Temporal 重试
SUGGEST_RETRY = RetryPolicy(maximum_attempts=1)
# 布尔 patch 门（workflows.py:236 WORKER_RECONCILE_PATCH_ID 同构先例）：挂起中旧 workflow
# 重放安全；新增门不 bump DevLaneWorkflow.PATCH_ID。
SUGGEST_NEXT_PATCH_ID = "dev-lane-suggest-next"
# t260831-02 集成测试机制（用户拍板的并行开发 ∥ 测试设计 → 机械测试 → 仲裁循环 → 验收走查）：
# 同构布尔门：挂起中旧 workflow 重放不走新分支；不 bump PATCH_ID。
INTEG_LOOP_PATCH_ID = "dev-lane-integration-tests"
# t260828-09 UI 验收机制：prepare_ui_evidence 新步 + merge_check UI 证据闸 + 看图审读钩子。
# 同构布尔门：挂起中旧 workflow 重放不走新分支；不 bump PATCH_ID。
UI_EVIDENCE_PATCH_ID = "dev-lane-ui-evidence"
# t260829-07 写集生命周期：方案定稿后写集跟随方案刷新（并集），空初始写集票由此
# 在方案定稿后获得护栏。同构布尔门：挂起中旧 workflow 重放不走新分支；不 bump PATCH_ID。
REFRESH_WRITE_SET_PATCH_ID = "dev-lane-refresh-write-set"
# t260829-07 审读判据机械化：integration_review ok 后 verify_review_gate 机械复核
# （泳道 0 commit / UI 票截图缺失 → 强制打回；git/路径异常 → 跳过不打回）。
# 同构布尔门：挂起中旧 workflow 重放不走新分支；不 bump PATCH_ID。
REVIEW_GATE_PATCH_ID = "dev-lane-review-gate"
# KI-003 stage 转换突变串让路点（_breathe 内 workflow.patched 消费）：旧在跑票
# 重放旧 history 无此 marker → 不让路，保重放确定。
BREATHE_PATCH_ID = "ki003-breathe-v1"
# M1-3（t260902-02）完结工单数据出仓归档：三段收口 merge（只落账）→archive_ticket
# （出仓）→teardown_lane（拆泳道）。同构布尔门：挂起中旧 workflow 重放不走新分支
# （旧代码 merge 后内联清理语义不变——activity 侧另有 MergeArgs.defer_teardown 负载
# 兼容手段兜底 activity 行为版本，两侧不双写）。archive_ticket 在 merge 之后、
# teardown_lane 之前——归档成功是拆泳道「stage 报告不随拆丢失」的前提（fail-closed）。
ARCHIVE_PATCH_ID = "dev-lane-archive-ticket"

# t260903-02 泳道提速③：review_plan 第三态「附条件放行」——verdict=conditional 轻微
# 瑕疵不改打回级，修改意见直通 implement（previous_context 注入），跳过方案重做+复审；
# 打回级（reject）仍走既有打回环；裁定权由后续人审门（merge）兜底。同构布尔门：
# 挂起中旧 workflow 重放走旧 ok/failed 二态分支，不 bump PATCH_ID。
REVIEW_CONDITIONAL_PATCH_ID = "dev-lane-review-conditional-v1"
# t260903-02 泳道提速②：arbitrate ∥ acceptance_walkthrough 并行分叉——两者吃同一份
# 机械测试结果、视角不同（技术仲裁 vs 用户走查）、无数据依赖，gather 并行省一段串行。
# 同构布尔门：挂起中旧 workflow 重放走旧串行 arbitrate→acceptance 分支，不 bump PATCH_ID。
ARB_ACC_PARALLEL_PATCH_ID = "dev-lane-arb-acc-parallel-v1"
# prepare_ui_evidence activity 超时：必须**明显大于** activity 内子进程超时
# （agent_activities.UI_CAPTURE_TIMEOUT_SEC=120s），否则 Temporal 先杀 activity，
# 子进程自己的超时回收路径走不到（review 意见：超时叠超时）。
UI_EVIDENCE_TO = timedelta(seconds=180)

# MAX_REVIEW_ROUNDS 迁至 shared.py（t260903-02：review_plan_route 纯函数需同源消费），
# 经下方 import 注入；本地不再定义。
MAX_CONFLICT_ROUNDS = 3  # 冲突自动消解轮数上限（t260826-01），超限/同批文件反复冲突转 blocked 交人

# t260901-04：打回 target/fallback 合法词表（_auto_rework 校验用，显式列值——
# 与 STAGES id 词表不一致是既有事实：acceptance/parallel_impl_design/integ_join
# 是 phase 值但不是 STAGES id；acceptance_walkthrough/ui_evidence/suggest_next/
# design_integration_tests 是 STAGES id 但不是 phase 值。此词表只服务打回校验，
# 勿从 STAGES 推导、勿复用他处）。
PHASE_MAIN_CHAIN = frozenset({
    "create_plan", "review_plan", "parallel_impl_design", "implement",
    "integ_join", "integration_review", "run_integration_tests", "arbitrate",
    "arb_acc_parallel", "acceptance", "merge_check", "merge", "done"})
# phase 主链步 → 角色映射（_auto_rework 留痕写 meta['role'] 用；与 PHASE_MAIN_CHAIN
# 同源维护——键集合必须一致，自测锁逐键核对。不走 _step(target)：词表∩¬STAGES 的
# 三个值（acceptance/parallel_impl_design/integ_join）会让 _step raise「未知步骤」
# 把 workflow 卡死（t260901-04 review 第 3 轮）。角色归属：STAGES 同名步照抄其 role；
# parallel_impl_design/integ_join 是实现侧聚合/汇合落盘 → developer；
# acceptance 对应 STAGES 的 acceptance_walkthrough → integration。
PHASE_MAIN_ROLES: Dict[str, str] = {
    "create_plan": "developer", "review_plan": "integration",
    "parallel_impl_design": "developer", "implement": "developer",
    "integ_join": "developer", "integration_review": "integration",
    "run_integration_tests": "integration", "arbitrate": "integration",
    "arb_acc_parallel": "integration",
    "acceptance": "integration", "merge_check": "integration",
    "merge": "integration", "done": "integration"}


def set_parallel_stages(meta: Dict[str, Any], stages: List[str]) -> None:
    """并行分叉期把活跃边列表写进 meta['parallel_stages']（KI-024 收口，t260903-04）。

    语义与口径（工单正文 + review_plan C4/C5 裁定，勿自由发挥）：
      - 双显真源=本列表；meta['stage'] 单字段**保持原样不动**（并行期仍是后写者赢，
        向后兼容：旧工单台/旧票消费路径零回归）。
      - 清洗：只收 STAGES id 词表内的字符串 id（phase 值如 parallel_impl_design
        不是 STAGES id，写进去 UI 不认）；畸形条目丢弃；去重保序。
      - 空列表（或清洗后为空）→ **删键**而不是留空列表：UI 把「键缺失 ∨ 空列表」
        同样视为「当前无并行」，回落既有 timeline 启发式（t260901-05 口径逐字节
        保持）。离开并行期（汇合/rework 离场）必须显式清，防陈旧列表把已完成边
        永久钉在 ▶。
      - 纯内存函数（无 activity/timer/信号），重放安全；DevLaneWorkflow.STAGES
        运行期取值（本函数定义在类前，调用发生在类定义后）。
    """
    valid_ids = {s.id for s in DevLaneWorkflow.STAGES}
    cleaned: List[str] = []
    for s in (stages if isinstance(stages, list) else []):
        if isinstance(s, str) and s in valid_ids and s not in cleaned:
            cleaned.append(s)
    if cleaned:
        meta["parallel_stages"] = cleaned
    else:
        meta.pop("parallel_stages", None)

# 各步的派活契约补述（接在 build_stage_prompt 通用指令后）。
# review 两步的判定约定：status ok=通过 / failed=打回，review comments 写进 summary。
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
        "（.suyou/screenshots/，ui-check/capture.mjs 产出）或说明为何无视觉差异。"),
    "design_integration_tests": (
        # t260902-12：用例设计依据第三项=组件对外契约与行为规格（草案修订四「方案」为旧口径残留，以修订二为准）
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


# 旧链步定义（仅存量 workflow 重放可达——t260831-02 集成测试机制退役了
# integration_review 步，但其历史重放仍需 _step 可解析，否则 NonDeterminism
# 致 workflow task 永久 failed（t260831-02 实测）。新执行流不经过它。）
_LEGACY_STEPS: Dict[str, Stage] = {
    "integration_review": Stage(
        id="integration_review", name="集成审读", role="integration",
        next="merge_check", parts=("agent",),
        desc="（已退役——仅存量 workflow 重放可达；新链把关=集成测试+仲裁+验收走查）"),
}


def _prompt_next_no(prompt: str) -> int:
    """prompt 顶层编号最大值 +1（FLOW_BRIEF 补述接尾用）。

    顶层条目「N. 」不缩进；注入的 previous_context（打回意见原文）逐行缩进 3 空格，
    不会误配。previous_context 注入后通用指令尾号会到 9，硬编码 9 会撞号。"""
    nums = [int(m) for m in re.findall(r"^(\d+)\.", prompt, re.M)]
    return (max(nums) + 1) if nums else 1


@workflow.defn
class DevLaneWorkflow:
    """developer 系工单唯一 workflow（dev-lane）。activity 直编排，无 stage 机。

    STAGES 仅作元数据（yaml 快照/create 推导/工单台展示）；快照键与
    TicketWorkflowBase 同形（stage/stage_state/checks/handoffs/timeline…），
    工单台与 ticket.py 无感消费。"""

    PATCH_ID = "dev-lane-v1"
    TEMPLATE_ID = "dev-lane"
    TEMPLATE_NAME = "开发泳道"
    TEMPLATE_LANE = "worktree"
    TEMPLATE_WORKSPACE_DIR = False
    TEMPLATE_DESC = ("开发泳道（developer 系唯一流程）：prepare_workspace→create_plan⇄review_plan"
                     "→implement∥design_integration_tests→汇合（ui_evidence/UI 票）"
                     "→run_integration_tests→arbitrate→acceptance_walkthrough"
                     "→merge_check（程序化）→merge（人审）")
    # 展示/推导元数据（真源编排=run()；顺序与 run 一致）。
    # parts=执行主体组合声明（agent🤖/script⚙️/human👤，静态声明，工单台徽标用）：
    # implement=agent+worker settle 代落盘+自测/verify 脚本门；merge=人签字+merge 落账
    # +泳道清理脚本；merge_check=纯程序化。引擎管道件（结果文件轮询等）不计。
    STAGES = (
        Stage(id="create_plan", name="做方案", role="developer", next="review_plan",
              desc="读需求出实现方案：改动文件清单、步骤、验收口径；不动代码",
              parts=("agent",),
              acceptance=("方案落结果文件（改动清单+步骤+验收口径）",)),
        Stage(id="review_plan", name="审方案", role="integration", next="implement",
              desc="审读方案写 review comments：通过 ok / 打回 failed+修改意见",
              parts=("agent",),
              acceptance=("review comments 落结果文件", "通过/打回结论明确")),
        # implement 与 design_integration_tests 真实并行（asyncio.gather，见 run() 的
        # parallel_impl_design 段；展示链按线性近似排相邻，汇合点统一代落盘）。
        Stage(id="implement", name="实现", role="developer", next="design_integration_tests",
              desc="按方案开发：写集白名单内；commit 由 worker 代落盘（agent 沙箱写不了真 .git）；"
                   "与 design_integration_tests 并行分叉，两边齐活后汇合统一落盘",
              parts=("agent", "script"),
              acceptance=("写集白名单内", "改动落写集文件（worker 代落盘 commit）", "相关 smoke/自测全绿")),
        # ---- t260831-02 集成测试机制（用户拍板：并行开发 ∥ 测试设计 → 机械测试 → 仲裁循环 → 验收走查）----
        Stage(id="design_integration_tests", name="设计集成测试", role="integration", next="ui_evidence",
              desc="按方案评估测试需求：从用户场景出发设计/迭代集成测试集（仓库 integration/ 目录，"
                   "并登记进场景清单），覆盖并发与边界故障面；与 implement 并行，测试集不向 developer 引导",
              parts=("agent",),
              acceptance=("测试集落 integration/ 目录（并登记进场景清单）", "场景覆盖与故障面清单落结果文件")),
        # t260828-09 UI 截图证据：仅展示元数据（仅 UI 票、在实现∥测试设计汇合落盘后、
        # 机械测试前由 run() 内联执行；非 UI 票本步被跳过（汇合直达 run_integration_tests）；截图缺失
        # 由 merge_check 证据闸兜底）。
        Stage(id="ui_evidence", name="UI截图证据", role="developer", next="run_integration_tests",
              desc="UI 票实现落盘后 worker 代跑 ui-check/capture-lane.mjs 隔离台，截控制台"
                   "各视图落 .suyou/screenshots/（软失败不拦主链，闸兜底）",
              parts=("script",),
              acceptance=("UI 票 .suyou/screenshots/ 有截图（merge_check 证据闸机械查）",)),
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
                   "走查发现代码问题 → 打回 implement（上限 %d 轮）" % MAX_ACCEPTANCE_ROUNDS,
              parts=("agent", "script"),
              acceptance=("验收报告落结果文件（逐场景结论）",)),
        Stage(id="merge_check", name="合并检查", role="integration", next="merge", agent=False,
              desc="程序化检查（无 agent）：泳道有 commit、工作区干净、泳道内 verify_lane 绿、merge-tree 无冲突；"
                   "仅预演冲突红 → 自动打回 implement 消解（上限 %d 轮），其它红灯 blocked 等人" % MAX_CONFLICT_ROUNDS,
              parts=("script",),
              acceptance=("泳道分支有 commit", "工作区干净（无未提交改动）",
                          "泳道内 verify_lane code 绿灯",
                          "merge 预演无冲突（冲突则自动消解 %d 轮内收敛）" % MAX_CONFLICT_ROUNDS)),
        Stage(id="merge", name="合并（人审）", role="integration", next="suggest_next", exit="human",
              desc="人审签字后执行 merge：合 main + 泳道清理（拆 worktree、删分支）；"
                   "合并失败（如签字期间他道先进 main 冲突）自动打回 merge_check 重验",
              parts=("human", "script"),
              acceptance=("人审签字", "merge 落账 + 泳道清理")),
        # t260828-08 预跑下一单：仅展示元数据（工单台进展卡渲染 self.results["suggest_next"]），
        # 不在 phase 主链——merge 分支内联执行（签字 approve 后、merge activity 前，见 run()）。
        Stage(id="suggest_next", name="预跑下一单", role="integration", next="",
              desc="关联立项的工单签字通过后、merge 落账前，复用 integration 会话预跑"
                   "「下一单建议」并落缓存（软失败不阻塞 merge 收口）；立项已无事可做时"
                   "给出可结项结论，工单台「继续执行」秒回 + 「确认结项」动作",
              parts=("agent",),
              acceptance=("建议落缓存 .suyou/epic-next/<代号>/pre.json（或软失败留痕）",)),
    )

    def __init__(self) -> None:
        self.ticket_id: str = ""
        self.meta: Dict[str, Any] = {}
        self.results: Dict[str, Dict[str, Any]] = {}      # activity 名 → StageResult 摘要
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self._sigs: Dict[str, Signature] = {}
        self._rework: Optional[ReworkRequest] = None
        self._retry_token: int = 0
        self._gens: Dict[str, int] = {}                   # activity 名 → 进入次数
        self.gate_runs: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.human_context: Dict[str, Any] = {}
        self.engine_version: int = ENGINE_VERSION_V2

    # ---------- 内部：时间/日志 ----------
    def _now_epoch(self) -> int:
        return int(workflow.now().timestamp())

    def _now_iso(self) -> str:
        return workflow.now().isoformat(timespec="seconds")

    def _log(self, note: str, status: Optional[str] = None) -> None:
        self.meta.setdefault("log", []).append(
            {"ts": self._now_epoch(), "status": status or self.meta.get("status", ""), "note": note})

    def _mark(self, step: str, state: str, reason: str = "") -> None:
        self.timeline.append(
            {"at": self._now_iso(), "stage": step, "state": state, "reason": reason})
        workflow.logger.info("[%s] %s/%s %s", self.ticket_id, step, state, reason)

    def _touch(self) -> None:
        self.meta["updated"] = self._now_epoch()

    async def _breathe(self) -> None:
        """stage 转换突变串让路点（KI-003）。本类独立于 TicketWorkflowBase（注释同形
        不继承），故自带 _breathe；形态与取舍清单见 base.py 同名方法（④在跑旧票
        重放兼容：patched 分支 + 0 长 timer，t260901-23 实现段以 replay_check 在跑票
        实测收口；实现期曾把方法只加在 base 上——本类不继承，self._breathe 直接
        AttributeError 炸 workflow task，replay_check 当场抓获）。"""
        if not workflow.patched(BREATHE_PATCH_ID):
            return  # 旧 history 重放：无 marker，不让路，保重放确定
        await asyncio.sleep(0)  # 0 长 timer：让出事件循环且自带唤回事件

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

    # ---------- 初始化 ----------
    def _init(self, inp: TicketInput) -> None:
        self.ticket_id = inp.ticket_id
        workflow.patched(self.PATCH_ID)
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
                "user_request": inp.user_request, "spec": inp.spec, "body": inp.body,
                "created": inp.created or self._now_epoch(),
            },
            "temporal_engine_version": self.engine_version,
            "sandbar_version": _sandbar_version(),
            "engine": ENGINE_V2,
            "log": [{"ts": self._now_epoch(), "status": "dispatched",
                     "note": "工单创建（dev-lane：activity 直编排，步=%s）"
                             % [s.id for s in self.STAGES]}],
        }
        self._mark("create_plan", "awaiting", "adopt dev-lane（步=%s）"
                   % [s.id for s in self.STAGES])

    # ---------- 步骤进入（meta/记账三件套） ----------
    def _enter(self, step_id: str) -> None:
        st = self._step(step_id)
        self._gens[step_id] = self._gen(step_id) + 1
        self.meta["stage"] = step_id
        self.meta["role"] = st.role
        self.meta["status"] = "dispatched"
        self.meta["stage_state"] = "running"
        self.meta["acceptance"] = list(st.acceptance)
        self._touch()
        self._mark(step_id, "running", "进入本步（第 %d 次）" % self._gen(step_id))

    def _finish(self, step_id: str, by: str, evidence: str) -> None:
        for c in self.meta.setdefault("checks", {}).setdefault(step_id, []):
            c["done"], c["by"] = True, by
            if evidence:
                c["evidence"] = evidence
        # t260901-08 追加范围：终态留痕。三个故障模式取舍（承 t260901-04 _mark 先例）：
        # ①回放安全——_mark 是纯内存 append（timeline+logger），无 activity/timer/信号等
        #   history 命令，RUNNING 实例重放不破确定性；
        # ②旧票回落——存量票历史无 done 条目，工单台 lane-states 自然回落现有 inRun
        #   启发式（07 误亮只对有留痕的新票根治，不追改存量数据）；
        # ③重跑语义——rework/retry 重进时 _enter 的 running 追加在 done 之后，
        #   timeline 最新态正确回到 running，重跑完成再落新 done。
        self._mark(step_id, "done", by + (("：" + evidence) if evidence else ""))
        self._touch()

    def _handoff(self, step_id: str, summary: str,
                 artifacts: Optional[List[str]] = None, report: str = "") -> None:
        self.meta.setdefault("handoffs", []).append({
            "stage": step_id, "agent_id": "", "summary": summary, "report": report,
            "artifacts": list(artifacts or []), "ts": self._now_epoch(),
            "engine_version": self.engine_version})

    def _refresh_write_set_after_plan(self) -> None:
        """方案定稿（含 t260903-02 附条件放行）后的写集刷新（t260829-07 机制，原 review_plan
        ok 分支内联代码原样上移——selfcheck_write_lifecycle E 段字符串在场锁依赖原文）。"""
        # t260829-07 写集生命周期：方案定稿即刷新写集（并集，纯函数，
        # 清单来自 create_plan 回执——已入 workflow 历史，确定性 OK）。
        if workflow.patched(REFRESH_WRITE_SET_PATCH_ID):
            plan_files = (self.results.get("create_plan") or {}).get("files_changed")
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

    # ---------- blocked 等待（retry_qc 重跑本步 / rework 跳步） ----------
    async def _blocked(self, step_id: str, why: str) -> None:
        self.meta["stage_state"] = "blocked"
        self._touch()
        self._log("%s → blocked，等 retry_qc 重跑或 rework 打回" % why)
        self._mark(step_id, "blocked", why)
        token = self._retry_token
        await workflow.wait_condition(
            lambda: self._retry_token > token or self._rework is not None)
        # 醒来由主循环看 self._rework / 重跑本步

    # ---------- agent 步 ----------
    async def _run_agent_step(self, step_id: str, previous_context: str = "",
                              settle: bool = True) -> Optional[StageResult]:
        """跑一个 agent activity（名=步名）。返回 None=基础设施故障（调用方转 blocked）。
        settle=False：并行分叉期跳过尾部代落盘（统一落盘由汇合点 settle_lane 承担）。"""
        st = self._step(step_id)
        gen = self._gen(step_id)
        self._enter(step_id)
        ws = stage_workspace(self.meta.get("workspace"), self.ticket_id)
        rfile = result_file_for(self.ticket_id, step_id, gen, ws)
        # gen 是 0 基（_enter 前取值）：prompt 里的「第 N 次进本段」用人话 1 基；
        # 文件名/args.gen 仍 0 基（结果文件 gen0 起，幂等锚点与磁盘命名连续性）
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
            skip_settle=not settle)
        raw = await workflow.execute_activity(
            step_id, args,
            start_to_close_timeout=AGENT_TO, heartbeat_timeout=HEARTBEAT_TO,
            retry_policy=RETRY)
        res = raw if isinstance(raw, StageResult) else StageResult(
            status=str(raw.get("status") or "ok"),
            summary=str(raw.get("summary") or ""),
            report=str(raw.get("report") or ""),
            deliverables=[str(x) for x in (raw.get("deliverables") or [])],
            files_changed=[str(x) for x in (raw.get("files_changed") or [])],
            evidence=str(raw.get("evidence") or ""))
        self.results[step_id] = {
            "status": res.status, "summary": res.summary, "report": res.report,
            "deliverables": list(res.deliverables),
            "files_changed": list(res.files_changed),
            "evidence": res.evidence, "gen": gen}
        # KI-003：stage 转换突变串让路点——results 记账与调用方后续 _finish/_handoff/
        # refresh_write_set 突变簇之间让出事件循环，排队的 snapshot query 不再被
        # 整段同步突变串噎到超时（工单台左栏转换窗只剩 id 的根因）。
        await self._breathe()
        return res

    # ---------- t260828-08：merge 落账前预跑立项下一单建议 ----------
    async def _suggest_epic_next(self, epic: str) -> None:
        """prepare_epic_next → build_suggest_next_prompt → suggest_next 三连。
        软失败总则：档案不可读/建议不合规/超时/基础设施故障一律 _log + _handoff 留痕，
        不抛不阻塞——merge 照常收口（activity retry_policy=SUGGEST_RETRY=1 次不重试）。"""
        self._mark("suggest_next", "running",
                   "merge 签字通过，预跑立项 %s 下一单建议（integration 会话复用）" % epic)
        try:
            prep = await workflow.execute_activity(
                prepare_epic_next,
                EpicNextPrepArgs(ticket_id=self.ticket_id, epic=epic),
                start_to_close_timeout=SHORT, retry_policy=SUGGEST_RETRY)
            if not prep.exists:
                self._log("预跑跳过：立项单 %s 档案不可读（merge 照常收口）" % epic)
                self._handoff("suggest_next", "预跑跳过：%s 档案不可读" % epic)
                return
            ws = stage_workspace(self.meta.get("workspace"), self.ticket_id)
            rfile = result_file_for(self.ticket_id, "suggest_next", 0, ws)
            rows_text = json.dumps(prep.tickets, ensure_ascii=False, indent=1) \
                if prep.tickets else "（本立项暂无关联工单）"
            prompt = build_suggest_next_prompt(
                code=epic, epic_markdown=prep.epic_markdown, tickets_summary=rows_text,
                workflows=[{"id": tid, "name": TEMPLATE_DISPLAY_NAMES.get(tid, tid)}
                           for tid in sorted(TEMPLATE_CLASS_NAMES)],
                result_path=rfile)
            res = await workflow.execute_activity(
                suggest_next,
                AgentStageArgs(
                    ticket_id=self.ticket_id, stage_id="suggest_next", role="integration",
                    prompt=prompt, workspace=ws, result_file=rfile,
                    log_file=agent_log_for(self.ticket_id, "suggest_next", 0, ws),
                    gen=0, epic=epic, state_key=prep.state_key),
                start_to_close_timeout=SUGGEST_NEXT_TO, retry_policy=SUGGEST_RETRY)
            self.results["suggest_next"] = {
                "status": res.status, "summary": res.summary, "report": res.report,
                "deliverables": list(res.deliverables), "files_changed": list(res.files_changed),
                "evidence": res.evidence, "gen": 0}
            if res.status == "ok":
                self._log("预跑下一单完成：%s" % res.summary)
                self._handoff("suggest_next", res.summary)
            else:
                self._log("预跑下一单软失败（merge 照常收口）：%s" % res.summary)
                self._handoff("suggest_next", "预跑软失败：%s" % res.summary[:120])
        except Exception as e:  # 超时/基础设施故障：软失败留痕，不阻塞 merge 收口
            self._log("预跑下一单异常软失败（merge 照常收口）：%s" % str(e)[:300])
            self._handoff("suggest_next", "预跑异常软失败：%s" % str(e)[:120])

    # ---------- rework ----------
    def _auto_rework(self, target: str, note: str, who: str, fallback: str) -> str:
        """内部/统一打回落步：校验 target/fallback ∈ PHASE_MAIN_CHAIN（done 除外）。
        通过 → meta 五件套（stage/role/status='rework'/stage_state='awaiting'/
        last_rework_note）+ _touch + _log + _mark(target,'rework')，返回 target；
        拒绝 → refused 记账 + log，返回 fallback（fallback 也非法时退 meta 现值——
        绝不让非法值回流给主循环的局部 phase，防「未知阶段」主循环 :1279 抛错）。
        role 走 PHASE_MAIN_ROLES 显式映射，**不经 _step(target)**（词表∩¬STAGES 三值
        会让 _step raise 把 workflow 卡死）。"""
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
        """外部 rework signal 落步：先消费 signal（拒绝也消费），再委托
        _auto_rework（留痕逻辑单源）。返回目标步 id（非法目标 → 拒绝留痕，停原步）。"""
        req = self._rework
        self._rework = None
        target = req.target_stage or fallback
        if target in ("suggest_next", "ui_evidence"):
            # 预跑下一单/UI 截图证据都不是 phase 主链步（分别在 merge 分支内联、
            # implement 分支内联执行），不接受打回——否则 phase 变量落到无编排的
            # 步上会让主循环抛「未知阶段」
            self.refused.append({"who": req.who, "want": "rework(%s)" % target,
                                 "why": "%s 非主链步，不接受 rework" % target})
            self._log("rework 拒绝：%s 非主链步（%s）" % (target, req.who))
            return fallback
        return self._auto_rework(target, req.note, req.who, fallback)

    # ---------- 主流程（activity 直编排） ----------
    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        self._init(inp)

        # 1) prepare_workspace（代码，无 agent；失败 → blocked 等 retry/rework）
        while True:
            # 泳道字段闸（t260824-04/-10/-11）：创建链路已在 ticket-start 单点校验，
            # 这里兜「旧 payload/未来新入口」绕过——lane=worktree 字段不齐即按失败
            # 回执走 blocked，不放给 activity 静默跳主树/临时目录。
            gate = lane_workspace_gate_error(self.meta)
            if gate:
                raw = WorkspacePrepResult(ok=False, kind="config", action="rejected",
                                          path="", error=gate)
            else:
                prep = WorkspacePrep(
                    ticket_id=self.ticket_id,
                    workspace=self.meta.get("workspace"),
                    branch=str(self.meta.get("branch") or ""),
                    base_ref=str(self.meta.get("base_ref") or ""))
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
                self._apply_rework("create_plan")  # 目标步由主循环接管

        phase = str(self.meta.get("stage") or "create_plan")
        plan_rounds = 0
        impl_rounds = 0
        impl_done = False                         # 并行分叉：implement 边完成态
        design_done = False                       # 并行分叉：design_integration_tests 边完成态
        code_rounds = 0                           # arbitrate code-fault 打回 developer 累计
        tests_rounds = 0                          # arbitrate tests-fault 测试集迭代累计
        acc_rounds = 0                            # 验收走查打回累计
        arb_format_rounds = 0                     # 仲裁输出缺 verdict= 标记的连续次数
        # t260903-02 泳道提速②：arbitrate ∥ acceptance_walkthrough 并行分叉的内存态。
        # 不变式：进入 run_integration_tests 段即全部单点重置（每轮机械测试产出即重仲裁、
        # 重走查）——覆盖 rework / tests-fault / code-fault 全部回路，不在散分支补置位。
        arb_done = False                          # 仲裁边完成态
        acc_done = False                          # 走查边完成态
        arb_res = None                            # 仲裁边 StageResult（边界齐后判定）
        acc_res = None                            # 走查边 StageResult（pass 时消费）
        design_ctx = ""                           # design_integration_tests 的注入上下文
        arb_ctx = ""                              # run_integration_tests 产出的测试结果注入
        ui_ctx = ""  # t260828-09：UI 截图证据（汇合点产出，acceptance 消费）
        conflict_rounds = 0                       # t260826-01：冲突自动消解轮数（上限 MAX_CONFLICT_ROUNDS）
        prev_conflict_files: List[str] = []       # 上一轮冲突文件（排序后集合比较，review M6）
        prev_ctx = ""
        ui_ctx = ""   # t260828-09：UI 截图证据清单（汇合点产出，acceptance 走查消费）

        while phase != "done":
            if self._rework is not None:
                fb = "implement" if phase == "parallel_impl_design" else phase
                # KI-024：rework 离开并行期（目标是串行段）必须清 parallel_stages——
                # 否则陈旧列表会把已离场的边永久钉在 UI ▶（离开并行期的两条路径之一，
                # 另一条是汇合点清；等待期口径见各并行分支失败边的写死注释）。
                if phase in ("parallel_impl_design", "arb_acc_parallel"):
                    set_parallel_stages(self.meta, [])
                phase = self._apply_rework(fb)
                # KI-003：rework 记账突变串（_auto_rework 的 _log/_mark/_touch）后
                # 让路一次，排队中的 snapshot query 能看到 rework 后的最新态。
                await self._breathe()
                prev_ctx = str(self.meta.get("last_rework_note") or "")
                if phase == "implement":
                    impl_done = False  # 重新实现：汇合点会重新统一落盘
                continue

            # 2) create_plan ⇄ review_plan
            if phase == "create_plan":
                try:
                    res = await self._run_agent_step("create_plan", prev_ctx)
                except Exception as e:
                    await self._blocked("create_plan", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
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
                    await self._blocked("review_plan", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
                    continue
                # t260903-02 泳道提速③：三态路由（附条件放行 verdict=conditional 不改
                # 打回级，意见直通 implement）；未 patched 重放走旧 ok/failed 二态。
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
                        # 附条件放行：修改意见注入 implement（复用 previous_context 通道，
                        # 文案与打回可区分）；不回 create_plan、不复审、不计打回轮数。
                        self._log("review_plan 附条件放行（意见直通 implement）")
                        prev_ctx = ("【附条件放行·implement 执行项】review 意见"
                                    "（轻微瑕疵不改打回级，按条件执行）：\n%s"
                                    % (res.report or res.summary or "")).strip()
                    # t260829-07 写集生命周期：方案定稿（含附条件放行）即刷新写集。
                    # 可达性 guard：本分支只在 review_plan 放行时执行；create_plan
                    # blocked 直接转 blocked 离开主循环，不会带病走到这里。
                    if workflow.patched(REFRESH_WRITE_SET_PATCH_ID):
                        self._refresh_write_set_after_plan()
                    if workflow.patched(INTEG_LOOP_PATCH_ID):
                        # 新链：并行分叉（implement ∥ design_integration_tests）
                        impl_done = False
                        design_done = False
                        design_ctx = ""
                        phase = "parallel_impl_design"
                        # KI-003：_finish/_handoff/refresh_write_set 大突变簇尾部
                        # 再让路一次，转换窗被切成两半，query 排队不撞 8s。
                        await self._breathe()
                        continue
                    phase = "implement"
                    continue
                # 打回：review comments 注入下一轮 create_plan（comments 在 report 分条，
                # 旧结果文件无 report 回落 summary——通道换了，意见不能丢）
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

            # 3) implement（developer 代码+单测）——并行分叉的 developer 边 / 打回重跑单边
            if phase == "implement":
                try:
                    res = await self._run_agent_step("implement", prev_ctx, settle=False)
                except Exception as e:
                    await self._blocked("implement", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
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
                    # ---- 旧链尾（仅存量 workflow 重放可达，t260831-02 等）----
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
                                ui_ctx = "【UI 截图证据（.suyou/screenshots/，审读必看）】\n" + \
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

            # 3.0) 旧链尾：integration_review（仅存量 workflow 重放可达；新链走并行分叉，
            #      把关职责由集成测试+仲裁+验收走查替代——t260831-02 用户拍板）
            if phase == "integration_review":
                try:
                    res = await self._run_agent_step("integration_review",
                                                     (prev_ctx + "\n" + ui_ctx).strip())
                except Exception as e:
                    await self._blocked("integration_review", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
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
                            gate_rework, gate_note = review_gate_verdict(
                                g.git_error, g.lane_commits, g.shots_path_error, g.png_count,
                                bool(self.meta.get("no_file_changes")),
                                is_ui_write_set(list(self.meta.get("write_set") or [])))
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
                    await self._blocked("implement", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
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

            # 3.0) 汇合：统一代落盘（skip_settle 的两边一次收口，实现+测试集同 commit）
            #      → UI 证据（UI 票）→ 机械集成测试。t260831-02 用户拍板机制。
            if phase == "integ_join":
                sraw = await workflow.execute_activity(
                    settle_lane,
                    SettleLaneArgs(ticket_id=self.ticket_id,
                                   worktree=str(self.meta.get("worktree") or ""),
                                   stage_id="implement", gen=impl_rounds),
                    start_to_close_timeout=SHORT, retry_policy=RETRY)
                s = sraw if isinstance(sraw, SettleLaneResult) else SettleLaneResult(
                    note=str(sraw.get("note") or ""),
                    lane_commits=int(sraw.get("lane_commits") or -1))
                self._log("汇合统一落盘：%s（泳道 commit 数 %s）"
                          % (s.note or "干净", s.lane_commits))
                # UI 证据（UI 票）：落盘后、机械测试前由 worker 代跑隔离台（软失败闸兜底）
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
                            ui_ctx = "【UI 截图证据（.suyou/screenshots/，验收必看）】\n" + \
                                "\n".join("- %s" % ln for ln in (ui.shot_lines or ui.shots))
                        else:
                            ui_ctx = "【UI 截图证据缺失】%s（验收按「无截图证据」如实记录）" % ui.detail
                        self._log("prepare_ui_evidence：%s" % (ui.detail or ("ok" if ui.ok else "failed")))
                    except Exception as e:  # 基础设施故障：留痕不拦主链，merge_check 闸兜底
                        ui_ctx = "【UI 截图证据缺失】activity 故障：%s: %s" % (type(e).__name__, e)
                        self._log("prepare_ui_evidence 故障（不拦主链，merge_check 闸兜底）：%s" % str(e)[:200])
                phase = "run_integration_tests"
                continue

            # 3.1) 并行分叉：implement（developer 代码+单测）∥ design_integration_tests
            #      （integration 测试集设计，仓库 integration/ 目录）——t260831-02 用户拍板。
            #      缺失边重跑：完成态记入内存，blocked 醒来后只补失败边（activity 幂等）。
            if phase == "parallel_impl_design":
                pend = []
                if not impl_done:
                    pend.append("implement")
                if not design_done:
                    pend.append("design_integration_tests")
                if pend:
                    # KI-024：分叉期活跃边列表进 meta（工单台双显真源；单 stage 字段不动）。
                    set_parallel_stages(self.meta, pend)
                    try:
                        rs = await asyncio.gather(*[
                            self._run_agent_step(
                                n, prev_ctx if n == "implement" else design_ctx,
                                settle=False) for n in pend],
                            return_exceptions=True)
                    except Exception as e:  # gather 本身不应抛（return_exceptions），防御
                        await self._blocked("parallel_impl_design", "并行分叉异常：%s" % e)
                        continue
                    failed = False
                    for name, r in zip(pend, rs):
                        if isinstance(r, Exception):
                            failed = True
                            # KI-024/review C4（等待期口径，写死）：摘除失败边——列表只剩
                            # 仍待补的边，UI 不把待重做边亮成 ▶；失败边本体由 timeline
                            # blocked 条目显 ✗（_blocked 内 _mark）。
                            set_parallel_stages(
                                self.meta, [n for n in pend if n != name])
                            await self._blocked(name, "agent 活动故障（已重试）：%s: %s"
                                                % (type(r).__name__, r))
                            break  # _blocked 内部等 retry_qc/rework；醒来后重算 pend 只补失败边
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
                # KI-024：两边齐活=离开并行期，删 parallel_stages（UI 回落既有启发式；
                # 后续 integ_join/settle 是单点串行段，无双显语义）。
                set_parallel_stages(self.meta, [])
                phase = "integ_join"
                continue

            # 3.2) 机械集成测试（零 LLM）：跑项目声明场景执行器 integration/run_scenarios.py
            if phase == "run_integration_tests":
                self._enter("run_integration_tests")
                # t260903-02 ②：内存态单点重置（不变式：每轮机械测试产出即重仲裁、
                # 重走查）——覆盖 rework / tests-fault / code-fault 全部回路收敛路径，
                # 不在散分支补置位（防消费打回前的陈旧走查结果）。
                arb_done = False
                acc_done = False
                arb_res = None
                acc_res = None
                # 前置机械检查：泳道落盘（统一 settle 后必有；no_file_changes 票豁免）
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
                                           worktree=str(self.meta.get("worktree") or "")),
                        start_to_close_timeout=INTEG_RUN_TO, retry_policy=RETRY)
                    ir = rraw if isinstance(rraw, IntegrationRunResult) else IntegrationRunResult(
                        ran=int(rraw.get("ran") or 0), passed=int(rraw.get("passed") or 0),
                        failed=int(rraw.get("failed") or 0),
                        details=[dict(d) for d in (rraw.get("details") or [])],
                        error=str(rraw.get("error") or ""))
                except Exception as e:
                    ir = IntegrationRunResult(error="集成测试 activity 故障：%s: %s"
                                              % (type(e).__name__, e))
                self.results["run_integration_tests"] = {
                    "status": "failed" if (ir.error or ir.failed) else "ok",
                    "summary": "集成测试：%d 跑 / %d 过 / %d 败%s"
                               % (ir.ran, ir.passed, ir.failed,
                                  ("｜" + ir.error) if ir.error else ""),
                    "report": "", "deliverables": [], "files_changed": [],
                    "evidence": json.dumps(ir.details, ensure_ascii=False)[:4000], "gen": 0}
                self._finish("run_integration_tests", by="run_integration_tests",
                             evidence="；".join("%s:%s" % (d.get("name"),
                                                    "过" if d.get("exit") == 0 else "败")
                                                for d in ir.details))
                self._handoff("run_integration_tests",
                              "集成测试 %d 跑 / %d 过 / %d 败%s"
                              % (ir.ran, ir.passed, ir.failed,
                                 ("｜" + ir.error) if ir.error else ""))
                # t260901-19：预算 6000→4000，且尾保（[-4000:]）——details 在 JSON 尾部，
                # 头部切片会把失败明细挤掉；尾保保住失败明细
                _arb_json = json.dumps({"ran": ir.ran, "passed": ir.passed,
                                        "failed": ir.failed, "error": ir.error,
                                        "details": ir.details}, ensure_ascii=False)
                arb_ctx = ("【机械集成测试结果】\n%s\n【测试集】仓库 integration/ 目录"
                           "（integration/ 场景文件与清单为准；你是其作者，tests-fault 时直接迭代它）"
                           % _arb_json[-4000:])
                # t260903-02 ②：走查边与仲裁吃同一份测试结果（用户走查视角独立，
                # 不预设测试全过），UI 走查实证一并注入。
                acc_ctx = ("【机械集成测试结果】\n%s\n" % _arb_json[-4000:]) + \
                    (("【UI 截图/走查实证（.suyou/screenshots/）】\n%s\n" % ui_ctx)
                     if ui_ctx else "")
                if workflow.patched(ARB_ACC_PARALLEL_PATCH_ID):
                    # 提速②：仲裁 ∥ 验收走查并行分叉（无数据依赖，省一段串行）
                    phase = "arb_acc_parallel"
                else:
                    phase = "arbitrate"
                continue

            # 3.3) 仲裁（integration 三态：pass / tests-fault / code-fault）
            if phase == "arbitrate":
                try:
                    res = await self._run_agent_step("arbitrate", arb_ctx)
                except Exception as e:
                    await self._blocked("arbitrate", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
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
                route = integration_route(verdict, tests_rounds, code_rounds)
                if verdict == "pass":
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("arbitrate", "仲裁通过：" + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    phase = "acceptance"
                    continue
                if route.startswith("blocked:"):
                    await self._blocked("arbitrate", route.split(":", 1)[1])
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

            # 3.3.1) t260903-02 泳道提速②：arbitrate ∥ acceptance_walkthrough 并行分叉。
            #      两者吃同一份机械测试结果、视角不同、无数据依赖，gather 省一段串行。
            #      边名一律 STAGES id（arbitrate/acceptance_walkthrough，_step 可解析）；
            #      arb_acc_parallel 只是 phase 值做主循环分发（已入 PHASE_MAIN_CHAIN/ROLES）。
            #      时序：gather 齐 → 单点 settle_lane（tests-fault 测试集改动先落账再重跑）
            #      → arbitrate verdict 判定 → 路由。
            if phase == "arb_acc_parallel":
                pend = []
                if not arb_done:
                    pend.append("arbitrate")
                if not acc_done:
                    pend.append("acceptance_walkthrough")
                if pend:
                    # KI-024：分叉期活跃边列表进 meta（工单台双显真源；单 stage 字段不动）。
                    set_parallel_stages(self.meta, pend)
                    try:
                        rs = await asyncio.gather(*[
                            self._run_agent_step(
                                n, arb_ctx if n == "arbitrate" else acc_ctx,
                                settle=False) for n in pend],
                            return_exceptions=True)
                    except Exception as e:  # gather 本身不应抛（return_exceptions），防御
                        await self._blocked("arb_acc_parallel", "并行分叉异常：%s" % e)
                        continue
                    failed = False
                    for name, r in zip(pend, rs):
                        if isinstance(r, Exception):
                            failed = True
                            # KI-024/review C4（等待期口径，写死）：摘除失败边，同
                            # parallel_impl_design 分支（失败边由 timeline blocked 显 ✗）。
                            set_parallel_stages(
                                self.meta, [n for n in pend if n != name])
                            await self._blocked(name, "agent 活动故障（已重试）：%s: %s"
                                                % (type(r).__name__, r))
                            break  # _blocked 内部等 retry_qc/rework；醒来后重算 pend 只补失败边
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
                # KI-024：两边齐活=离开并行期，删 parallel_stages（后续 verdict 判定/
                # 格式纠正重跑 arbitrate 边都是单边串行，无双显语义；路由回
                # run_integration_tests 也该回到单显）。
                set_parallel_stages(self.meta, [])
                # 单点 settle：先落账（tests-fault 的测试集改动必须先进 commit 再重跑机械
                # 测试，否则重跑跑在未落账状态、blocked 时工作区留脏），再判 verdict。
                try:
                    sraw = await workflow.execute_activity(
                        settle_lane,
                        SettleLaneArgs(ticket_id=self.ticket_id,
                                       worktree=str(self.meta.get("worktree") or ""),
                                       stage_id="arbitrate", gen=tests_rounds),
                        start_to_close_timeout=SHORT, retry_policy=RETRY)
                    s = sraw if isinstance(sraw, SettleLaneResult) else SettleLaneResult(
                        note=str(sraw.get("note") or ""),
                        lane_commits=int(sraw.get("lane_commits") or -1))
                    self._log("并行分叉统一落盘：%s（泳道 commit 数 %s）"
                              % (s.note or "干净", s.lane_commits))
                except Exception as e:  # 落盘故障：留痕不拦主链，run 前置 0 commit 检查兜底
                    self._log("settle_lane 故障（不拦主链）：%s: %s" % (type(e).__name__, e))
                verdict = parse_arbitration_summary(arb_res.summary)
                if not verdict:
                    arb_format_rounds += 1
                    if arb_format_rounds > 2:
                        await self._blocked("arbitrate",
                                            "仲裁结论 %d 次缺 verdict= 标记（契约：summary 含 "
                                            "verdict=pass|tests-fault|code-fault）" % arb_format_rounds)
                        continue
                    # 格式纠正只重跑 arbitrate 边（走查成本高且与格式无关，结果留内存）；
                    # 该边 settle=True：纠正前可能有测试集改动需落盘。
                    arb_done = False
                    arb_res = None
                    arb_ctx = ("【格式纠正】你的上一份结论缺少 verdict= 标记。请严格输出三态之一："
                               "verdict=pass / verdict=tests-fault / verdict=code-fault，并重判。")
                    pend = ["arbitrate"]
                    try:
                        rraw = await self._run_agent_step("arbitrate", arb_ctx, settle=True)
                    except Exception as e:
                        await self._blocked("arbitrate", "agent 活动故障（已重试）：%s: %s"
                                            % (type(e).__name__, e))
                        continue
                    arb_done = True
                    arb_res = rraw
                    verdict = parse_arbitration_summary(arb_res.summary)
                    if not verdict:
                        continue  # 下一轮循环再计格式纠正（外层分支入口重判）
                arb_ctx = ""
                route = integration_route(verdict, tests_rounds, code_rounds)
                if verdict == "pass":
                    self._finish("arbitrate", by="integration-agent",
                                 evidence=arb_res.evidence or arb_res.summary)
                    self._handoff("arbitrate", "仲裁通过：" + (arb_res.summary or ""),
                                  artifacts=arb_res.deliverables, report=arb_res.report)
                    # 消费并行走查结果（verdict=pass 才有效；非 pass 已在下方作废）
                    if acc_res is not None and acc_res.status == "ok":
                        self._finish("acceptance_walkthrough", by="integration-agent",
                                     evidence=acc_res.evidence or acc_res.summary)
                        self._handoff("acceptance", "验收报告：" + (acc_res.summary or ""),
                                      artifacts=acc_res.deliverables, report=acc_res.report)
                        phase = "merge_check"
                        # KI-003：判定+消费大突变簇尾部让路一次（query 排队不撞 8s）
                        await self._breathe()
                        continue
                    if acc_res is not None:
                        # 走查边报失败：既有验收打回回路（与旧 acceptance 分支同口径）
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
                    # 走查边缺失（异常重跑留痕）：回落旧串行验收补走
                    phase = "acceptance"
                    continue
                if route.startswith("blocked:"):
                    await self._blocked("arbitrate", route.split(":", 1)[1])
                    continue
                # 非 pass：本轮并行走查结果作废（回路收敛后 run_integration_tests 入口
                # 单点重置会重走查）——留痕可检索，不静默丢弃。
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

            # 3.4) 验收走查（integration 以用户视角走查 → 验收报告，供人审门查阅）
            if phase == "acceptance":
                acc_ctx = (("【UI 截图/走查实证（.suyou/screenshots/）】\n%s\n" % ui_ctx) if ui_ctx else "")
                try:
                    res = await self._run_agent_step("acceptance_walkthrough", acc_ctx)
                except Exception as e:
                    await self._blocked("acceptance", "agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
                    continue
                if res.status == "ok":
                    self._finish("acceptance_walkthrough", by="integration-agent",
                                 evidence=res.evidence or res.summary)
                    self._handoff("acceptance", "验收报告：" + (res.summary or ""),
                                  artifacts=res.deliverables, report=res.report)
                    phase = "merge_check"
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
                # t260901-04：验收失败自动打回必须落 state='rework' timeline 记录，
                # 工单台打回横幅只消费 state=rework——不走留痕用户就看不到打回原因。
                phase = self._auto_rework("implement", "验收走查打回（第 %d 轮）" % acc_rounds,
                                          who="workflow", fallback="acceptance")
                continue

            # 4) merge_check（程序化，无 agent）
            if phase == "merge_check":
                self._enter("merge_check")
                raw = await workflow.execute_activity(
                    merge_check,
                    MergeCheckArgs(ticket_id=self.ticket_id,
                                   worktree=str(self.meta.get("worktree") or ""),
                                   branch=str(self.meta.get("branch") or ""),
                                   base_ref=str(self.meta.get("base_ref") or ""),
                                   write_set=list(self.meta.get("write_set") or [])),
                    start_to_close_timeout=MERGE_CHECK_TO, retry_policy=RETRY)
                mc = raw if isinstance(raw, MergeCheckResult) else MergeCheckResult(
                    green=bool(raw.get("green")), checks=list(raw.get("checks") or []),
                    error=str(raw.get("error") or ""),
                    conflict=bool(raw.get("conflict")),
                    conflict_files=[str(x) for x in (raw.get("conflict_files") or [])],
                    merge_tree_excerpt=str(raw.get("merge_tree_excerpt") or ""))
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
                # t260826-01 冲突自动消解回路：仅 merge 预演冲突红（mc.conflict）→
                # 不转 blocked，自动打回 implement 消解（复用 rework 回路的内部机制，
                # 不等人发 signal）；其它红灯维持既有行为 blocked 等人。
                if not mc.conflict:
                    await self._blocked("merge_check", "merge_check 红灯：%s" % (red or mc.error))
                    continue
                # ---- 冲突类红灯：轮数计数 + 防死循环（S3：blocked 文案锚点统一可 grep）----
                conflict_rounds += 1
                files_sig = sorted(mc.conflict_files)
                files_txt = "、".join(files_sig)[:200]
                if conflict_rounds > MAX_CONFLICT_ROUNDS:
                    await self._blocked(
                        "merge_check",
                        "冲突消解 %d 轮未收敛（上限 %d），转人工处置：冲突文件 %s"
                        % (conflict_rounds - 1, MAX_CONFLICT_ROUNDS, files_txt))
                    continue
                if prev_conflict_files and files_sig == prev_conflict_files:
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
                # ① worker 代跑 merge 留冲突现场（agent 沙箱写不了真 .git）
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
                # ② agent 解冲突标记（S4：轮次标记，与功能开发/打回返工轮区分开）
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
                    await self._blocked("implement", "冲突消解轮 agent 活动故障（已重试）：%s: %s"
                                        % (type(e).__name__, e))
                    continue
                prev_ctx = ""
                if res.status != "ok":
                    await self._blocked("implement", "冲突消解第 %d 轮 agent 报失败：%s"
                                        % (conflict_rounds, (res.summary or res.status)[:200]))
                    continue
                # ③ worker 代落盘合并提交（校验无未解残留；此时段工作区必脏、不跑
                #    merge_check——prep→implement→settle→回 merge_check 严格串行，S2）
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
                    # C2：此时工作区是「合并进行中」态（MERGE_HEAD 在场）——retry_qc 会让
                    # merge_check 以「工作区脏」红灯再次 blocked（诊断口径错位），文案
                    # 直接给处置指引
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
                # ④ 消解成果直接回 merge_check 重验（integration_review 已随
                #    t260831-02 集成测试机制退场；机械闸复核工作区/预演）
                phase = "merge_check"
                continue

            # 5) merge（人审门 → 签字通过 → merge activity 真合并）
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
                    continue  # 主循环顶部统一跳步
                sig = self._sigs.pop("merge")
                self.signatures["merge"] = {"who": sig.who, "decision": sig.decision,
                                            "note": sig.note, "at": self._now_iso()}
                if sig.decision != "approve":
                    self._rework = ReworkRequest(
                        who=sig.who, target_stage="implement",
                        note="人在 merge 打回：%s（签字人 %s）" % (sig.note, sig.who))
                    continue
                # 签字通过 → 真合并
                self.meta["stage_state"] = "running"
                self._mark("merge", "running", "人审通过（%s），执行 merge" % sig.who)
                # t260828-08 预跑下一单：必须在 merge activity **之前**——merge 内部
                # 落账后即拆 worktree（连同本地 .dsh/会话存储），只有此刻 integration
                # 会话上下文仍健在，DSH_HEADLESS_SESSION 会话复用才成立。
                if workflow.patched(SUGGEST_NEXT_PATCH_ID) and str(self.meta.get("epic") or ""):
                    await self._suggest_epic_next(str(self.meta.get("epic")))
                # M1-3（t260902-02）三段收口：merge 只落账（defer_teardown），
                # 归档（archive_ticket）与拆泳道（teardown_lane）随后分列——归档
                # fail-closed 成功是拆泳道的前提（stage 报告不随拆丢失）。
                archive_on = workflow.patched(ARCHIVE_PATCH_ID)
                raw = await workflow.execute_activity(
                    merge,
                    MergeArgs(ticket_id=self.ticket_id,
                              worktree=str(self.meta.get("worktree") or ""),
                              branch=str(self.meta.get("branch") or ""),
                              base_ref=str(self.meta.get("base_ref") or ""),
                              defer_teardown=archive_on),
                    start_to_close_timeout=MERGE_TO, retry_policy=RETRY)
                mr = raw if isinstance(raw, MergeResult) else MergeResult(
                    ok=bool(raw.get("ok")), action=str(raw.get("action") or ""),
                    merge_commit=str(raw.get("merge_commit") or ""),
                    error=str(raw.get("error") or ""))
                if not mr.ok:
                    # 合并失败（典型：签字等待期间别的泳道先进 main 造成冲突）——
                    # 自动打回 merge_check 重验四项（260824 用户拍板），不转 blocked
                    # 空等人：检查红（冲突未解）自然 blocked 等人处置；检查绿回到
                    # merge 人审门重新签字。每轮都要人签字，无死循环风险。
                    # t260901-04：直接走 _auto_rework 留痕（不再塞 self._rework——
                    # 塞值会被主循环再走一次 _apply_rework，同一次打回落两条 timeline）。
                    note = "merge 失败（%s）自动打回重验：%s" \
                           % (mr.action, (mr.error or "未知")[:300])
                    self._log(note)
                    phase = self._auto_rework("merge_check", note, who="workflow",
                                              fallback="merge")
                    continue
                if archive_on:
                    # archive_ticket：fail-closed——activity 抛错（归档失败=报告
                    # 会随拆丢失）即转 blocked、泳道保留（不裸抛：workflow task
                    # 异常重试无终态，blocked 才有出口）。
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
                    # teardown_lane：拆泳道（清理失败只 warn 回执，泳道残留为可
                    # 回收垃圾，本体已进 archive.json 清单，不阻塞工单收口）。
                    try:
                        tr = await workflow.execute_activity(
                            teardown_lane,
                            MergeArgs(ticket_id=self.ticket_id,
                                      worktree=str(self.meta.get("worktree") or ""),
                                      branch=str(self.meta.get("branch") or "")),
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

            raise ValueError("未知阶段 %r" % phase)  # 到不了这里（步链封闭）

        # 收口
        self.meta["status"] = "closed"
        self.meta["stage_state"] = "awaiting"
        self._touch()
        self._log("merge 落账，工单收口（closed）")
        self._mark("merge", "closed", "workflow 完成")
        return self._snapshot()

    # ---------- signal：人门签字 / rework / retry_qc ----------
    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """人门签字（dev-lane 只有 merge 一道人门）。"""
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

    @workflow.signal
    def rework(self, req: ReworkRequest) -> None:
        """打回重跑：目标步重进（gen+1 → 结果文件换新，agent 真重跑）。"""
        self._rework = req
        self._log("rework 请求：%s → %s（%s）"
                  % (req.note, req.target_stage or "缺省目标", req.who))

    @workflow.signal
    def retry_qc(self, who: str) -> None:
        """blocked 后请求重跑本步。"""
        self._retry_token += 1
        self.timeline.append(
            {"at": self._now_iso(), "stage": str(self.meta.get("stage") or ""),
             "state": "retry-requested",
             "reason": "%s 请求重跑（第 %d 次）" % (who, self._retry_token)})

    # ---------- update：状态维护（与 base.py 同名同载荷，client.py 通吃） ----------
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

    # ---------- query：只读快照（键与 base.py 同形，工单台/ticket.py 无感消费） ----------
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
            "meta": dict(self.meta),
        }

    def _snapshot(self) -> Dict[str, Any]:
        return self.snapshot()
