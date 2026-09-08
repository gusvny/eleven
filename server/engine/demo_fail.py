"""Demo B：机器门红灯 → workflow 卡住不推进（失败路径）。

看点：
  1. 同一个 activity、同一段判绿代码，只把命令指向 fixtures/qc_red_stub.py（红灯契约）；
  2. 红灯后 stage 停在 machine-qc/blocked——**既不失败也不跳过**，就是不动；
  3. agent 喊「我修好了」（retry_qc）只是请求**重跑脚本**，脚本还红就还是卡；
  4. 历史里查不到 ai_review_stub / publish_dry_run 被调度过——下游一步没走。
"""

from __future__ import annotations

import asyncio
import sys

from demo_common import connect, history_lines, jdump, say, terminate_if_running, wait_for
from shared import (
    POC_DIR,
    TASK_QUEUE,
    PipelineInput,
    QcRequest,
    Signature,
    pipeline_wf_id,
)
from workflows import ContentPipelineWorkflow

PROPOSAL = "p260821-red"
RED_STUB = str(POC_DIR / "fixtures" / "qc_red_stub.py")


async def main() -> None:
    client = await connect()
    wf_id = pipeline_wf_id(PROPOSAL)
    killed = await terminate_if_running(client, wf_id)
    if killed:
        say(f"[清场] 终止上一次 running 实例 run_id={killed}")

    say("=" * 78)
    say("Demo B｜机器门红灯 → 卡住不推进")
    say("=" * 78)

    handle = await client.start_workflow(
        ContentPipelineWorkflow.run,
        PipelineInput(
            proposal_id=PROPOSAL,
            title="POC 演示提案：故意红灯",
            qc=QcRequest(
                scope="260627",
                cmd=[sys.executable, RED_STUB],
                label="红灯 fixture（同 qc_run 契约）",
            ),
        ),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    say(f"\n① 启动 id={wf_id}")

    await wait_for(
        handle,
        lambda s: s["stage"] == "approve" and s["stage_state"] == "awaiting-human",
        "停在 approve",
    )
    await handle.signal(
        ContentPipelineWorkflow.sign,
        Signature(who="用户（人）", gate="approve", decision="approve", note="立项通过"),
    )
    say("② 人签 approve → 进加工 → 机器门")

    snap = await wait_for(
        handle,
        lambda s: s["stage"] == "machine-qc" and s["stage_state"] == "blocked",
        "机器门红灯卡住",
        timeout=120,
    )
    say("\n③ 机器门红灯，停住：")
    say(f'   stage={snap["stage"]} state={snap["stage_state"]}')
    say(f'   blocked_reason={snap["blocked_reason"]}')
    say("   " + jdump(snap["qc_runs"]).replace("\n", "\n   "))

    say("\n④ 静置 6s，确认它不会自己往下走（也不会失败退出）：")
    await asyncio.sleep(6)
    snap = await handle.query("snapshot")
    desc = await handle.describe()
    say(f'   6s 后 stage={snap["stage"]}/{snap["stage_state"]}，execution status={desc.status.name}')

    say("\n⑤ agent 喊「修好了」→ retry_qc（脚本仍红）：")
    await handle.signal(ContentPipelineWorkflow.retry_qc, "developer-agent")
    snap = await wait_for(
        handle,
        lambda s: len(s["qc_runs"]) >= 2 and s["stage_state"] == "blocked",
        "第二次机器门仍红",
        timeout=120,
    )
    say(f'   → 机器门跑了 {len(snap["qc_runs"])} 次，仍 red_count={snap["qc_runs"][-1]["red_count"]}，stage 还是 {snap["stage"]}/{snap["stage_state"]}')

    lines = await history_lines(handle)
    downstream = [l for l in lines if "ai_review_stub" in l or "publish_dry_run" in l]
    say("\n⑥ 下游是否被调度过（应为空）：" + (jdump(downstream) if downstream else "无 —— 一步没走 ✅"))

    say("\n⑦ 历史（可见 machine_qc 被调度两次、无下游 activity）：")
    for line in lines:
        say("   " + line)

    say("\n⑧ 保留为 running 状态（不 terminate）——去 UI http://127.0.0.1:8233 可看到它一直挂在机器门。")
    say("   真实修法：编辑修数据 → 再 retry_qc；脚本转绿才会自动往下走。")
    say("\nDemo B 结束：红灯不是失败，是**闸门关着**。")


if __name__ == "__main__":
    asyncio.run(main())
