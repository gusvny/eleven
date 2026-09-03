"""RegressionWorkflow —— regression 回归验收（M11 v2 模版即代码，t260822-m11）。

stage 链直译自 workflows/regression.yaml（真源=本类，yaml 是生成快照）：
  regress(product-operation/验证分工, agent+脚本门 verify_lane code) → report(integration, agent)
"""

from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared import GateSpec, Stage, TicketInput

from base import TicketWorkflowBase


@workflow.defn
class RegressionWorkflow(TicketWorkflowBase):
    PATCH_ID = "regression-v4"
    TEMPLATE_ID = "regression"
    TEMPLATE_NAME = "回归验收"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "回归验收（波收口）：独立回归→结论"

    STAGES = (
        Stage(id="regress", name="独立回归（分工=qa，dispatch_product_operation_qa 实例，zai/glm-5.2）",
              role="product-operation", next="report",
              desc="verify_lane all 全绿，全套 smoke 独立复跑，diff 写集白名单复核",
              parts=("agent", "script"),
              acceptance=("verify_lane all 全绿",
                          "全套 smoke 独立复跑",
                          "diff 写集白名单复核"),
              gate=GateSpec(stage="regress", tool="verify_lane",
                            args={"lane": "code"}, label="verify_lane code")),
        Stage(id="report", name="结论", role="integration", next="",
              desc="红项逐条列 ku/文件+原因",
              parts=("agent",),
              acceptance=("红项逐条列 ku/文件+原因",)),
    )

    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        return await self._main(inp)
