"""workflows_v2 — the registry of v2 template workflow classes (templates as code).

Since 260824 the developer side has only one flow: dev-lane (DevLaneWorkflow,
activities wired directly:
create_plan<->review_plan -> implement<->integration_review -> merge_check -> merge
with a human gate). The old code-lane / build-workbench templates are deleted (all
their tickets are closed, so replay is not a concern).
On 260904 the host ordered content-pipeline / proofread / regression / cleanup
retired. Now only dev-lane remains (standalone regression runs either directly on
the integration main side or as a dev-lane).

TEMPLATE_CLASSES: template id -> workflow class. This is the source of truth for
class selection in client.py ticket-start. Class names must match
shared.TEMPLATE_CLASS_NAMES — a selfcheck cross-asserts the two to catch drift.
"""

from __future__ import annotations

import os as _os

from dev_lane import DevLaneWorkflow
from shared import FIXTURE_TEMPLATES_ENV

TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
]

# 夹具模板环境门（工单 t260908-01，与 shared.TEMPLATE_CLASS_NAMES 同门同款）：
# SANDBAR_FIXTURE_TEMPLATES=1 时注册测试夹具模板 fixture-two-step——收窄守卫
# （sc_template_face_narrowing 的默认面断言恰为 {dev-lane}）与生产板不受影响；
# 只有测试场景起 worker 的子进程注入该 env。
if _os.environ.get(FIXTURE_TEMPLATES_ENV) == "1":
    from fixtures.fixture_two_step import FixtureTwoStepWorkflow
    TEMPLATE_CLASSES["fixture-two-step"] = FixtureTwoStepWorkflow
    ALL_WORKFLOWS_V2.append(FixtureTwoStepWorkflow)

# 项目外置工作流模板合并（t260924-04，票 1）：类面注册表。加载器（project_templates
# .scan，import_classes=True）逐项目逐模块 importlib 全量加载＋形状深检，三态拒收
# 结构化点名（撞名/畸形/加载失败），坏模块只拒自己不拖同行；深检结果经
# project_template_classes_merged 回写 shared 名面两表——引擎进程内两表恒一致，
# 既有交叉自检不破。不声明 workflow_modules 的项目 = 本段零效果（零行为变化）。
# gen_workflows_doc 按 PROJECT_TEMPLATE_IDS 显式排除（快照属项目仓，引擎仓不代生成）；
# worker.py 注册 ALL_WORKFLOWS_V2 时天然并入外置类；replay_check 的重放面同理。
from shared import project_template_classes_merged  # noqa: E402

_PT_CLASSES = project_template_classes_merged()
PROJECT_TEMPLATE_IDS = frozenset(_PT_CLASSES.classes)
# D3（t260924-04 第 2 轮打回）：外置模块的 sandbox 装载名——worker 构造 Worker 时把
# 这些名字注入 SandboxedWorkflowRunner 的 passthrough_modules（sandbox importer 按
# 名解析到外层已装载模块，不再 ModuleNotFoundError 崩工人）。worker.py 消费。
PROJECT_TEMPLATE_MODULE_NAMES = dict(_PT_CLASSES.module_names)
# D6（t260924-04 第 4 轮打回）：worker passthrough 全集＝外置装载名 ∪ 其引擎依赖
# 顶层名——activate 期 payload 解码要 typing.get_type_hints 按 `sys.modules[所属模块]`
# 查 TicketInput 等类型（模块=shared），受限 importer 对非 passthrough 名即 KeyError
# （实录 `Failed decoding arguments ← KeyError: 'shared'`）。worker.py 消费。
PROJECT_TEMPLATE_PASSTHROUGH_MODULES = frozenset().union(
    *_PT_CLASSES.module_deps.values()) if _PT_CLASSES.module_deps else frozenset()
TEMPLATE_CLASSES.update(_PT_CLASSES.classes)
ALL_WORKFLOWS_V2.extend(_PT_CLASSES.classes[tid] for tid in sorted(_PT_CLASSES.classes))

# D7（t260924-04 第 5 轮打回）：外置模板的 agent 段 id 清单（去重保序）——worker 据此
# 逐段补注册同名段 activity（agent_activities.make_stage_activity，与内置段同实现）。
# 只收 agent 段：human 门走 prepare_human_gate 通道、纯 script 闸走 script_gate，
# 均不消费同名段 activity。
_PROJECT_TEMPLATE_STAGE_IDS = []
for _tid in sorted(_PT_CLASSES.classes):
    for _st in getattr(_PT_CLASSES.classes[_tid], "STAGES", ()):
        if getattr(_st, "agent", True) and getattr(_st, "exit", "") != "human":
            if _st.id not in _PROJECT_TEMPLATE_STAGE_IDS:
                _PROJECT_TEMPLATE_STAGE_IDS.append(_st.id)
PROJECT_TEMPLATE_STAGE_IDS = tuple(_PROJECT_TEMPLATE_STAGE_IDS)
