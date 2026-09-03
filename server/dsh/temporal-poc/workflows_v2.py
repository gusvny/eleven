"""workflows_v2 —— v2 模版 workflow 类汇总（模版即代码）。

260824 起 developer 系只有 dev-lane 一个流程（DevLaneWorkflow，activity 直编排：
create_plan⇄review_plan→implement⇄integration_review→merge_check→merge 人审），
旧 code-lane / build-workbench 两模版已删除（存量工单全部 closed，无 replay 负担）。
其余四模版（content-pipeline/proofread/regression/cleanup）仍走 base.py stage 机。

TEMPLATE_CLASSES：模板 id → workflow 类（client.py ticket-start 选类真源，
类名与 shared.TEMPLATE_CLASS_NAMES 一致——两处由 selfcheck 交叉断言防漂移）。
"""

from __future__ import annotations

from cleanup import CleanupWorkflow
from content_pipeline import ContentPipelineTicketWorkflow
from dev_lane import DevLaneWorkflow
from proofread import ProofreadWorkflow
from regression import RegressionWorkflow

TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
    "content-pipeline": ContentPipelineTicketWorkflow,
    "proofread": ProofreadWorkflow,
    "regression": RegressionWorkflow,
    "cleanup": CleanupWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
    ContentPipelineTicketWorkflow,
    ProofreadWorkflow,
    RegressionWorkflow,
    CleanupWorkflow,
]
