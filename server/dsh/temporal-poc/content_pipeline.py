"""ContentPipelineTicketWorkflow —— content-pipeline 内容加工（M11 v2 模版即代码）。

stage 链直译自 workflows/content-pipeline.yaml（真源=本类，yaml 是生成快照）：
  propose(product-operation, agent) → approve(人门：立项只能人)
  → process(product-operation, agent) → machine-qc(纯脚本门 qc_run all)
  → ai-review(product-operation/审校分工, agent, revision_to=process 修订回路≤2)
  → final-review(人门：终审只能人) → publish(integration, agent+脚本门 verify_lane content)

类名说明：步1 的 ContentPipelineWorkflow 类名已被在跑实例占用（workflow type 名进历史不可改），
v2 类用新名 ContentPipelineTicketWorkflow；TEMPLATE_CLASS_NAMES 映射表是唯一真源。
"""

from __future__ import annotations

from typing import Any, Dict

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from shared import GateSpec, Stage, TicketInput

from base import TicketWorkflowBase


@workflow.defn
class ContentPipelineTicketWorkflow(TicketWorkflowBase):
    PATCH_ID = "content-pipeline-v4"
    TEMPLATE_ID = "content-pipeline"
    TEMPLATE_NAME = "内容加工"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "内容加工（提案制）：提案→立项(人)→加工→机器QC→AI审校⇄修订≤2→终审(人)→发布闸门"

    # 修订回路（A4.2）：rework 落 ai-review 记一轮，>2 超限回 approve 立项
    REVISION_STAGE = "ai-review"
    REVISION_LIMIT = 2
    REVISION_OVERFLOW = "approve"

    STAGES = (
        Stage(id="propose", name="提案", role="product-operation", next="approve",
              desc="提案文件落 pipeline/proposals/<id>.md，状态机=提案",
              parts=("agent",),
              acceptance=("提案文件落 pipeline/proposals/<id>.md",
                          "状态=提案，机器QC 清单列明")),
        Stage(id="approve", name="立项", role="integration", next="process", exit="human",
              desc="「立项只能人」不可让渡红线：提案头部 状态=提案→立项 由人改",
              parts=("human",),
              acceptance=("提案头部 状态=立项（人改）",)),
        Stage(id="process", name="加工", role="product-operation", next="machine-qc",
              desc="四件套/拓源产物落位，merge 语义防 append 翻倍；动数据先备份",
              parts=("agent",),
              acceptance=("动数据前备份先落 /tmp/",
                          "四件套/拓源产物落位",
                          "lint_residue 零残留",
                          "禁词零命中")),
        Stage(id="machine-qc", name="机器QC", role="product-operation", next="ai-review",
              desc="按提案 §3 机器 QC 清单逐项脚本全绿（引提案不另立清单）",
              agent=False,
              parts=("script",),
              acceptance=("按提案 §3 机器 QC 清单逐项脚本全绿（逐字校验/字数对齐等）",),
              gate=GateSpec(stage="machine-qc", tool="qc_run",
                            args={"scope": "all"}, label="qc_run all")),
        Stage(id="ai-review", name="AI审校（异模型交叉）", role="product-operation",
              next="final-review", fanout=1, revision_to="process",
              desc="分工=proofread（zai/glm-5.2 审校家，只判不改）；可扇出多审读 agent；"
                   "docs 类文档审校意见落 docs/reviews 制式（review_store.py save）",
              parts=("agent",),
              acceptance=("报告=severity+位置+铁律条款",
                          "审校意见落 docs/reviews 制式（python3 server/dsh/knowledge/review_store.py save），"
                          "返工指令随报告产出（review_store.py rework 一键复制）",
                          "revision_count ≤ 2（超限 rework to_stage=approve 回立项）")),
        Stage(id="final-review", name="终审", role="integration", next="publish",
              exit="human",
              desc="出口条件=human：只能人签字（提案 §6）",
              parts=("human",),
              acceptance=("提案 §6 终审签字（机械读提案文件）",)),
        Stage(id="publish", name="发布闸门", role="integration", next="",
              desc="发布链重跑全绿，build_shelf 终装 + books.json 书集格式校验",
              parts=("agent", "script"),
              acceptance=("发布链重跑全绿（verify_lane content 道）",
                          "build_shelf 终装 + books.json 书集格式校验（中途态检测）"),
              gate=GateSpec(stage="publish", tool="verify_lane",
                            args={"lane": "content", "scope": "auto"},
                            label="verify_lane content")),
    )

    @workflow.run
    async def run(self, inp: TicketInput) -> Dict[str, Any]:
        return await self._main(inp)
