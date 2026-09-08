"""Demo A：完整走通一次 content-pipeline（人门 signal + 真脚本机器门）。

看点：
  1. 起来就停在 approve 人门 —— 没人签字，谁也推不动；
  2. agent 试图 force_stage 直接改成 publish → 被拒，请求留痕，状态不动；
  3. machine-qc 跑的是真实 `server/admin.py call qc_run {"scope":"260627"}`；
  4. final-review 先打回一次 → 自动回加工重跑机器门 → 再签才发布；
  5. 末尾打印不可变事件历史（signal/activity 逐条有据）。
"""

from __future__ import annotations

import asyncio

from demo_common import connect, history_lines, jdump, say, terminate_if_running, wait_for
from shared import PipelineInput, QcRequest, Signature, StageAttempt, TASK_QUEUE, pipeline_wf_id
from workflows import ContentPipelineWorkflow

PROPOSAL = "p260821-green"


async def main() -> None:
    client = await connect()
    wf_id = pipeline_wf_id(PROPOSAL)
    killed = await terminate_if_running(client, wf_id)
    if killed:
        say(f"[清场] 终止上一次 running 实例 run_id={killed}")

    say("=" * 78)
    say("Demo A｜content-pipeline 全流程（人门 signal + 真 qc_run）")
    say("=" * 78)

    handle = await client.start_workflow(
        ContentPipelineWorkflow.run,
        PipelineInput(
            proposal_id=PROPOSAL,
            title="POC 演示提案：260627 复检后发布",
            qc=QcRequest(scope="260627", label="真脚本 qc_run(260627)"),
        ),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    say(f"\n① 已启动 workflow id={wf_id}\n   run_id={handle.result_run_id}")

    snap = await wait_for(
        handle,
        lambda s: s["stage"] == "approve" and s["stage_state"] == "awaiting-human",
        "停在 approve 人门",
    )
    say("\n② 自动停在人门（无超时挂起，等 signal）：")
    say(f'   stage={snap["stage"]} state={snap["stage_state"]}')
    say(f'   blocked_reason={snap["blocked_reason"]}')

    say("\n③ 【越权测试】agent 直接要求把状态改成 publish + 拿非人门签字：")
    await handle.signal(
        ContentPipelineWorkflow.force_stage,
        StageAttempt(who="developer-agent", want_stage="publish", accepted=False, reason="想跳过所有门"),
    )
    await handle.signal(
        ContentPipelineWorkflow.sign,
        Signature(who="developer-agent", gate="process", decision="approve", note="自签加工段"),
    )
    await asyncio.sleep(1.0)
    snap = await handle.query("snapshot")
    say(f'   → stage 仍是 {snap["stage"]}（一动不动），被拒记录：')
    say("   " + jdump(snap["refused_attempts"]).replace("\n", "\n   "))

    say("\n④ 人签字（gate=approve）：")
    await handle.signal(
        ContentPipelineWorkflow.sign,
        Signature(who="用户（人）", gate="approve", decision="approve", note="立项通过"),
    )

    snap = await wait_for(
        handle,
        lambda s: s["stage"] == "final-review" and s["stage_state"] == "awaiting-human",
        "机器门过 → 停在终审人门",
        timeout=180,
    )
    say("   → 加工 + 机器门自动跑完，停在终审。机器门实测输出：")
    say("   " + jdump(snap["qc_runs"]).replace("\n", "\n   "))

    say("\n⑤ 人终审先打回一次（decision=reject）→ 应自动回加工并重跑机器门：")
    await handle.signal(
        ContentPipelineWorkflow.sign,
        Signature(who="用户（人）", gate="final-review", decision="reject", note="某章标题口吻要改"),
    )
    snap = await wait_for(
        handle,
        lambda s: s["revisions"] == 1
        and s["stage"] == "final-review"
        and s["stage_state"] == "awaiting-human",
        "第 2 轮跑回终审",
        timeout=180,
    )
    say(f'   → revisions={snap["revisions"]}，机器门跑了 {len(snap["qc_runs"])} 次（每轮加工后必跑）')

    say("\n⑥ 人终审通过 → 发布段（POC dry-run，零写入）：")
    await handle.signal(
        ContentPipelineWorkflow.sign,
        Signature(who="用户（人）", gate="final-review", decision="approve", note="终审通过，可发布"),
    )
    final = await handle.result()
    say("   result=" + str(final["result"]))
    say("\n⑦ 段落时间线（workflow 自己推的，没有第二个写入方）：")
    for row in final["timeline"]:
        say(f'   {row["at"]}  {row["stage"]:<13} {row["state"]:<14} {row["reason"]}')

    say("\n⑧ 不可变事件历史（服务端持久化，agent 无法编辑/删除）：")
    for line in await history_lines(handle):
        say("   " + line)

    say("\nDemo A 结束：人门只有人能开，机器门只有脚本能开，状态只有 workflow 能推。")


if __name__ == "__main__":
    asyncio.run(main())
