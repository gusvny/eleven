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
from light_lane import LightLaneWorkflow
from shared import FIXTURE_TEMPLATES_ENV

# 宿主令 260930（devlane-lite §4.1，直修无票）：**轻道是独立 workflow 类**——注册就是本表
# 加一行；两条道共用真正干活的活动面，轻道只带自己那条短段链（详见 light_lane.py 头注）。
TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
    "light-lane": LightLaneWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
    LightLaneWorkflow,
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
import shared  # noqa: E402  （名面两表回写撤下面用；与 project_templates 同门同源）

# 活动注册表源面在本模块再导出（t260925-16）：组合判据单源——场景探针/闸面按
# workflows_v2 命名空间消费组合面（ALL_ACTIVITIES + ALL_AGENT_ACTIVITIES +
# make_stage_activity(段 id)），不另抄一份清单。worker.py 仍从各自模块直取。
from activities import ALL_ACTIVITIES  # noqa: E402  F401（再导出面）
from agent_activities import (  # noqa: E402  F401（再导出面）
    ALL_AGENT_ACTIVITIES,
    make_stage_activity,
)

_PT_CLASSES = project_template_classes_merged()


def _engine_activity_name_sources():
    """引擎已注册活动名 → 来源模块（KI-121 判据面）。名字按 temporalio 注册定义名
    取（@activity.defn 可显式改名，Python 函数名不可作判据）。导入失败向上抛，
    由 _filter_activity_name_collisions 转结构化拒收（fail-closed，不静默跳过）。"""
    names = {}
    for a in list(ALL_ACTIVITIES) + list(ALL_AGENT_ACTIVITIES):
        d = getattr(a, "__temporal_activity_definition", None)
        n = getattr(d, "name", None) or getattr(a, "__name__", "")
        if n:
            names.setdefault(n, getattr(a, "__module__", "?"))
    return names


def _act_name_rej(project, module, tid, sid, check, detail):
    """活动名撞车面的结构化拒收记录（键面与 project_templates._rej 同形，多
    template/stage 两个定位键；汇入 PROJECT_TEMPLATE_REJECTIONS → 建票文案可见）。"""
    return {"project": project, "module": module, "template": tid,
            "stage": sid, "check": check, "detail": detail}


def _filter_activity_name_collisions(res) -> None:
    """外置模板 agent 段 id 撞引擎注册活动名 → 模板级拒收（KI-121，t260925-16）。

    事故实案：nusuyou content-studio 首版段 id `ai-review` 与引擎为历史回放保留的
    退役段活动（agent_activities.AGENT_STAGE_IDS）同名 → worker 组装注册表时同名
    活动定义两份，temporalio 注册期裸 ValueError，中央工人起不来。此处把冲突前移到
    加载期：撞名模板整体拒收（classes/module_names/module_deps/accepted 全撤），
    拒收记录点名「活动名 × 引擎来源 × 来件模板」进建票文案——高声、不静默、不崩栈。
    检查不可用（引擎活动注册表导入失败）= fail-closed 全部外置模板拒收，不静默放行。"""
    withdraw = []
    try:
        engine = _engine_activity_name_sources()
    except Exception as e:
        res.rejections.append(_act_name_rej(
            "", "", "", None, "活动名唯一性检查不可用",
            "引擎活动注册表导入失败（fail-closed，外置模板全部拒收）：%s: %s"
            % (type(e).__name__, str(e)[:160])))
        engine = {}
        withdraw = sorted(res.classes)
        for tid in withdraw:
            acc = res.accepted.get(tid, {})
            res.rejections.append(_act_name_rej(
                acc.get("project", ""), acc.get("module", ""), tid, None,
                "活动名唯一性检查不可用", "模板 %s 因上条原因一并拒收" % tid))
    else:
        for tid in sorted(res.classes):
            cls = res.classes[tid]
            acc = res.accepted.get(tid, {})
            for st in getattr(cls, "STAGES", ()):
                # 只收 agent 段判撞（human 门/script 闸不消费同名段 activity，与
                # PROJECT_TEMPLATE_STAGE_IDS 收集口径一致）
                if not (getattr(st, "agent", True) and getattr(st, "exit", "") != "human"):
                    continue
                sid = getattr(st, "id", "")
                if sid in engine:
                    res.rejections.append(_act_name_rej(
                        acc.get("project", ""), acc.get("module", ""), tid, sid,
                        "活动名撞引擎注册面",
                        "活动名 %s 已被引擎注册（%s）× 来件模板 %s（%s/%s）——外置段 id "
                        "不得与引擎注册活动同名（同名=活动双注册，工人注册期崩，KI-121）"
                        % (sid, engine[sid], tid, acc.get("project", ""), acc.get("module", ""))))
                    withdraw.append(tid)
                    break
    if not withdraw:
        return
    import sys
    for tid in withdraw:
        res.accepted.pop(tid, None)
        res.classes.pop(tid, None)
        # 装载名一并下册（全终态回收）：撞名拒收的半态模块不留 sys.modules——
        # 留着=下次同装载名按「同文件复用」走身份去重面，残骸漂进后续进程态。
        sys.modules.pop(res.module_names.get(tid, ""), None)
        res.module_names.pop(tid, None)
        res.module_deps.pop(tid, None)
    # 名面回写撤下（reconcile 语义：非内置 id 一并从 shared 两表撤）——内置键=当前
    # 两表键减本轮撤下面（shared 侧 reconcile 已跑过一次，此处只补撤）。
    res.reconcile(shared.TEMPLATE_CLASS_NAMES, shared.TEMPLATE_DISPLAY_NAMES,
                  builtin_keys=set(shared.TEMPLATE_CLASS_NAMES) - set(withdraw))


_filter_activity_name_collisions(_PT_CLASSES)
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
