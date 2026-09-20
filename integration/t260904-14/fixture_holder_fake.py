# fixture_holder_fake.py —— t260904-14 真票子用例的「占位 DevLaneWorkflow」（260908）。
#
# 为什么存在：remove 在飞闸（projects.py 闸3）要按 ProjectKey 列出在飞票并报名号。
# ticket-list 对 RUNNING 的票发快照 query（client.py _meta_of）：真 workflow 无
# worker 时 query 空等 8s×2 重试≈18s，贴脸超过 remove 票号通道的 20s 子进程预算
# （实锤：闸3 报「ticket-list 子进程超时」而非票号）。本假 workflow 由
# fixture_holder_worker.py 装载常驻：run 挂起等待（票保持 RUNNING），类上无
# query handler——query 立刻失败（不再空等），ticket-list 秒回降级行，行内
# exec_status=RUNNING + id 齐全，闸3 得以报名号拒摘。
#
# 本模块必须保持「干净模块」（只有 temporalio import + 类定义）——temporalio
# 沙箱校验 @workflow.defn 类时会重执行定义模块（integration/t260902-02 同案）。

from temporalio import workflow


@workflow.defn(name="DevLaneWorkflow")
class FixtureHolder:
    """占位工单 workflow：什么都不做，挂 30 分钟（场景寿命远短于此）。"""

    @workflow.run
    async def run(self, inp) -> dict:
        await workflow.wait_condition(lambda: False, timeout=1800)
        return {"engine": "template-as-code-v2", "meta": {}}
