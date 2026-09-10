"""fixture_two_step —— 测试夹具两段模板（工单 t260908-01）。

Why this exists: 段间暂停的「通用性」验收需要一个**非 dev-lane** 的模板做行为
断言（派发规格拍板④：实现落 base 通用层，换一个 workflow 模板同样生效）。本类
是 TicketWorkflowBase 的最小两段子类（fx_step_one → fx_step_two，两个 agent 段，
配 SANDBAR_AGENT_STUB=1 桩大脑零模型调用），注册走 SANDBAR_FIXTURE_TEMPLATES=1
环境门（workflows_v2 / shared.TEMPLATE_CLASS_NAMES 同款同门）——生产板与收窄
守卫（sc_template_face_narrowing 的默认面断言）永不见本模板。

Clean-module 约束（fixture_ticket_fake.py 头注同款，t260902-02 同案）：temporalio
sandbox 会重执行定义模块做校验——本模块只允许 import + 类定义，零模块级 IO
（pathlib/subprocess/open 一律禁止）。
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "fixture-two-step"


@workflow.defn
class FixtureTwoStepWorkflow(TicketWorkflowBase):
    """最小两段夹具模板：一切机制（含段间暂停门）继承自 TicketWorkflowBase /
    TicketPauseMixin，零私有逻辑——它本身就是「新模板接线 ≤N 行即行为生效」的
    活证物。"""

    STAGES = (
        Stage(id="fx_step_one", name="夹具段一", role="developer", next="fx_step_two",
              acceptance=("段一完成",)),
        Stage(id="fx_step_two", name="夹具段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "fixture-two-step-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "夹具两段"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "测试夹具两段模板（仅 SANDBAR_FIXTURE_TEMPLATES=1 下注册）"

    @workflow.run
    async def run(self, inp: TicketInput):
        # temporalio 继承约束（base.py 头注已证 1.18.2）：@workflow.run 必须定义在
        # 子类上——薄壳转发 _main。
        return await self._main(inp)
