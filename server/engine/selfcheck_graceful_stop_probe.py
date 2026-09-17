"""selfcheck_graceful_stop_probe — 优雅停 selfcheck 的探针桩模块（t260916-29）。

ProbeWorkflow + guarded_probe 的可导入承载：temporalio workflow 沙箱只重导入 defn
所属模块（ki061 selfcheck 用 dev_lane 同理），__main__ 主脚本不被沙箱触碰——所以
桩独立成模块，且顶层仅「imports + defn」（dev_lane 同款纪律），import 面包在
imports_passed_through 内（agent_activities/shared 与生产同源）。

零 IO 零进程零模型：活动本体是内存 stub，真实守卫
（agent_activities.worker_termination_guard）包裹与生产四个长活动汇聚点同款。
"""

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import agent_activities
    from agent_activities import worker_termination_guard
    from shared import (
        classify_worker_termination,
        format_agent_stage_failure,
        retry_once_on_worker_termination,
    )

# 主脚本跨进程读写（activity 侧计数/放行事件；工作流体内绝不触碰——确定性纪律）
CTRL = {"calls": {}, "entered": {}, "release": {}}


@workflow.defn
class ProbeWorkflow:
    """最小探针工作流：plain=直跑；classify=捕异常走归因/文案；retry=走重跑兜底门。"""

    @workflow.run
    async def run(self, inp: dict) -> dict:
        def once():
            return workflow.execute_activity(
                "guarded_probe", {"ticket": inp["ticket"], "stage": inp["stage"]},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1))

        if inp["mode"] == "classify":
            try:
                res = await once()
                return {"status": "ok", "res": res}
            except Exception as e:
                return {"status": "failed",
                        "classified": classify_worker_termination(e),
                        "text": format_agent_stage_failure(inp["ticket"], inp["stage"], e)}
        if inp["mode"] == "retry":
            try:
                res = await retry_once_on_worker_termination(
                    once, gate=workflow.patched("t26091629-selfcheck-retry-probe"))
                return {"status": "ok", "res": res}
            except Exception as e:
                return {"status": "failed", "text": str(e)}
        res = await once()
        return {"status": "ok", "res": res}


@activity.defn
async def guarded_probe(args: dict) -> dict:
    """stub agent 活动：首跑挂起等放行（等 SIGTERM 面救场），次跑直接成功。
    本体包 agent_activities.worker_termination_guard（与生产四个长活动汇聚点同款）。"""
    ticket = args["ticket"]
    n = CTRL["calls"].get(ticket, 0) + 1
    CTRL["calls"][ticket] = n
    if n >= 2:
        return {"ok": True, "attempt": n}
    async with worker_termination_guard(ticket, args["stage"], 0):
        CTRL["entered"][ticket] = True
        ev = CTRL["release"].get(ticket)
        if ev is not None:
            try:
                await asyncio_wait_for(ev)
            except TimeoutError:
                return {"ok": False, "error": "release 未到（测试护栏超时）", "attempt": n}
        return {"ok": True, "attempt": n}


async def asyncio_wait_for(ev, timeout_s: float = 25.0):
    """activity 侧不受沙箱限制，直接用 asyncio；包一层便于桩内单点替换。"""
    import asyncio
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        raise TimeoutError("release wait 护栏超时")


# agent_activities 引用保持可读（静态检查面）
_ = agent_activities
