"""ProofreadWorkflow —— proofread 审读（M11 v2 模版即代码，t260822-m11）。

stage 链直译自 workflows/proofread.yaml（真源=本类，yaml 是生成快照）：
  review(product-operation/审校分工, agent, fanout=1) → report(integration, agent)
"""

from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared import Stage, TicketInput

from base import TicketWorkflowBase


@workflow.defn
class ProofreadWorkflow(TicketWorkflowBase):
    PATCH_ID = "proofread-v4"
    TEMPLATE_ID = "proofread"
    TEMPLATE_NAME = "审读"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "审读（独立交叉）：审读→分流（blocker/major→返工单，minor→挂 pending）"

    STAGES = (
        Stage(id="review", name="审读", role="product-operation", next="report", fanout=1,
              desc="分工=proofread（dispatch_product_operation_proofread 实例，zai/glm-5.2，"
                   "deny=[write,edit]）；可扇出多审读 agent，只读不改业务文件",
              parts=("agent",),
              acceptance=("只读不改业务文件",
                          "报告含 severity/位置/铁律条款")),
        Stage(id="report", name="分流", role="integration", next="",
              desc="blocker/major→开返工单（回 content-pipeline process 或 dev-lane implement），"
                   "minor→挂 pending",
              parts=("agent",),
              acceptance=("blocker/major→开返工单（回 content-pipeline process 或 dev-lane implement）",
                          "minor→挂 pending")),
    )

    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        return await self._main(inp)
