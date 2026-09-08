"""workflows_v2 —— v2 模版 workflow 类汇总（模版即代码）。

260824 起 developer 系只有 dev-lane 一个流程（DevLaneWorkflow，activity 直编排：
create_plan⇄review_plan→implement⇄integration_review→merge_check→merge 人审），
旧 code-lane / build-workbench 两模版已删除（存量工单全部 closed，无 replay 负担）。
260904 宿主令：content-pipeline / proofread / regression / cleanup 四模版退役，
现仅存 dev-lane（独立回归能力由 integration main 侧直跑或开 dev-lane 承担）。

TEMPLATE_CLASSES：模板 id → workflow 类（client.py ticket-start 选类真源，
类名与 shared.TEMPLATE_CLASS_NAMES 一致——两处由 selfcheck 交叉断言防漂移）。
"""

from __future__ import annotations

from dev_lane import DevLaneWorkflow

TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
]
