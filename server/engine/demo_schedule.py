"""Demo C：Temporal Schedule 定时触发 dispatcher 巡检 + workflow-id 单例 dedup。

看点：
  1. Schedule（间隔 15s，overlap=SKIP）触发 DispatcherScanWorkflow —— 巡检本身也是
     一个有历史、可重放、可暂停的 workflow，不是一条 cron 里的 shell；
  2. 巡检 activity 只读跑 `admin.py call ticket {"op":"list"}`，回报工单分布与卡住清单；
  3. 单例：同一个 workflow id 再 start 一次 → 服务端直接拒（WorkflowAlreadyStarted），
     这就是「一张提案只能有一条在跑的流水线」的天然锁，不需要自己写 lockfile。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    WorkflowFailureError,
)
from temporalio.service import RPCError

from demo_common import connect, jdump, say
from shared import (
    DISPATCHER_WF_ID,
    SCHEDULE_ID,
    TASK_QUEUE,
    PipelineInput,
    QcRequest,
    pipeline_wf_id,
)
from workflows import ContentPipelineWorkflow, DispatcherScanWorkflow


async def demo_schedule(client) -> None:
    say("=" * 78)
    say("Demo C-1｜Schedule 定时触发 dispatcher 巡检")
    say("=" * 78)

    # 幂等：先删当前 ID 的旧 schedule（本走廊是共享 SCHEDULE_ID 的唯一在树创建点）
    try:
        await client.get_schedule_handle(SCHEDULE_ID).delete()
        say(f"[清场] 删除旧 schedule {SCHEDULE_ID}")
    except RPCError:
        pass

    try:
        handle = await client.create_schedule(
            SCHEDULE_ID,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    DispatcherScanWorkflow.run,
                    id=DISPATCHER_WF_ID,
                    task_queue=TASK_QUEUE,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(seconds=15))]
                ),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
    except ScheduleAlreadyRunningError:
        handle = client.get_schedule_handle(SCHEDULE_ID)
    say(f"\n① 建好 schedule id={SCHEDULE_ID}：每 15s 一次，overlap=SKIP（上轮未完则跳过本轮）")

    say("② 立刻手动 trigger 一次（不等 15s）")
    await handle.trigger()
    await asyncio.sleep(3)

    desc = await handle.describe()
    say(f"③ schedule 状态：num_actions={desc.info.num_actions} "
        f"running={[e.workflow_id for e in desc.info.running_actions]}")
    for act in desc.info.recent_actions[-3:]:
        wfe = act.action.first_execution_run_id if hasattr(act.action, "first_execution_run_id") else ""
        say(f"   触发于 {act.scheduled_at.isoformat(timespec='seconds')} → "
            f"workflow_id={act.action.workflow_id} run={wfe[:8]}")

    # 取最近一次触发的巡检结果
    last = desc.info.recent_actions[-1]
    scan_handle = client.get_workflow_handle(
        last.action.workflow_id, run_id=last.action.first_execution_run_id
    )
    result = await scan_handle.result()
    say("\n④ 巡检结果（只读 admin.py call ticket op=list）：")
    say("   " + jdump(result).replace("\n", "\n   "))

    say("\n⑤ 等一个自然周期（~16s）看它自己再触发一次……")
    await asyncio.sleep(17)
    desc = await handle.describe()
    say(f"   num_actions={desc.info.num_actions}（应 ≥2：1 次手动 trigger + ≥1 次定时）")
    say(f"   最近触发：{[a.scheduled_at.isoformat(timespec='seconds') for a in desc.info.recent_actions[-3:]]}")

    say("\n⑥ 暂停 schedule（人可随时按停，不用改 crontab）")
    await handle.pause(note="POC demo 结束，先暂停")
    desc = await handle.describe()
    say(f"   paused={desc.schedule.state.paused} note={desc.schedule.state.note}")
    say("   （彻底清掉：.venv/bin/python -c \"...delete()\" 或 bin/temporal schedule delete --schedule-id "
        f"{SCHEDULE_ID}）")


async def demo_dedup(client) -> None:
    say("\n" + "=" * 78)
    say("Demo C-2｜workflow-id 单例 dedup")
    say("=" * 78)

    wf_id = pipeline_wf_id("p260821-dedup")
    handle = await client.start_workflow(
        ContentPipelineWorkflow.run,
        PipelineInput(proposal_id="p260821-dedup", title="单例测试", qc=QcRequest(scope="260627")),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    say(f"\n① 第一次 start id={wf_id} → run_id={handle.result_run_id[:8]}（挂在 approve 人门）")

    say("② 第二次 start 同一个 id（模拟第二个 agent/第二次调度重复派活）：")
    try:
        await client.start_workflow(
            ContentPipelineWorkflow.run,
            PipelineInput(proposal_id="p260821-dedup", title="重复派活", qc=QcRequest(scope="260627")),
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        say("   ✗ 竟然起来了——单例假设不成立（不该出现）")
    except Exception as e:  # temporalio.client.WorkflowAlreadyStartedError
        say(f"   ✅ 被服务端拒绝：{type(e).__name__}: {e}")

    say("③ 清场：终止这条单例测试流水线")
    await handle.terminate(reason="dedup demo 结束")
    say("\nDemo C 结束：调度=可观测的 workflow，单例=id 即锁。")


async def main() -> None:
    client = await connect()
    await demo_schedule(client)
    await demo_dedup(client)


if __name__ == "__main__":
    asyncio.run(main())
