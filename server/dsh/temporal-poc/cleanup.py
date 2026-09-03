"""CleanupWorkflow —— cleanup 数据清洗（M11 v2 模版即代码，t260822-m11）。

stage 链直译自 workflows/cleanup.yaml（真源=本类，yaml 是生成快照）：
  clean(product-operation, agent) → rederive(product-operation, agent)
工作空间=dir 隔离目录 /tmp/suyou-ws/<工单id>（TEMPLATE_WORKSPACE_DIR=True）。
"""

from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared import Stage, TicketInput

from base import TicketWorkflowBase


@workflow.defn
class CleanupWorkflow(TicketWorkflowBase):
    PATCH_ID = "cleanup-v4"
    TEMPLATE_ID = "cleanup"
    TEMPLATE_NAME = "数据清洗"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "数据清洗（溯源修复）：清洗→重推导（隔离目录 /tmp/suyou-ws/<工单id>）"
    TEMPLATE_WORKSPACE_DIR = True

    STAGES = (
        Stage(id="clean", name="清洗", role="product-operation", next="rederive",
              desc="clean_inline 扩展不破坏既有顺序，备份先落，lint 零残留",
              parts=("agent",),
              acceptance=("clean_inline 扩展不破坏既有顺序",
                          "备份 /tmp 先落",
                          "lint 零残留")),
        Stage(id="rederive", name="重推导（补谱/补抓/重跑生成器）", role="product-operation",
              next="",
              desc="QC 全量绿灯，其余产物字节级零扰动",
              parts=("agent",),
              acceptance=("QC 全量绿灯",
                          "其余产物字节级零扰动")),
    )

    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        return await self._main(inp)
