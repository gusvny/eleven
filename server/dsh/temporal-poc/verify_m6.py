#!/usr/bin/env python3
"""M6 闭环验证（t260821-m6-scan-expand）：一张真实工单走「巡检→报告→可签建议」。

前置（专属 task queue 隔离验证，不干扰共享队列上的真实 worker（LEGACY 旧队列隔离验证））：
    SANDBAR_TASK_QUEUE=sandbar-m6-verify .venv/bin/python worker.py --daemon \
        --pidfile data/worker-m6.pid --logfile data/worker-m6.log

跑法：
    SANDBAR_TASK_QUEUE=sandbar-m6-verify .venv/bin/python verify_m6.py

断言（写死当下真实工单地形，环境变了就要改）：
  - 巡检 workflow 完成，返回 pending_decision ≥ 1 且报告文件落盘；
  - 报告含真实人门工单 t260820-hanshu-l0（final-review/awaiting-human）且建议=可签；
  - 报告含真实 settled 工单 t260821-11 且建议=待补（验收未勾齐）；
  - 红线声明在报告里。
sign 动作不在本脚本——红线：签字只能人。报告给出「可签」即闭环到验收点。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from temporalio.client import Client

from shared import NAMESPACE, SCAN_DIR, SCAN_RED_LINE, TARGET_HOST, TASK_QUEUE
from workflows import DispatcherScanWorkflow

VERIFY_WF_ID = "dispatcher-scan-m6-verify"
ASSERT_HUMAN = "t260820-hanshu-l0"   # 真实人门工单：final-review 待人签
ASSERT_SETTLED = "t260821-11"        # 真实 settled 工单：验收未勾齐


async def main() -> int:
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    handle = await client.start_workflow(
        DispatcherScanWorkflow.run, id=VERIFY_WF_ID, task_queue=TASK_QUEUE)
    print("① 巡检 workflow 已起：id=%s run=%s（queue=%s）"
          % (handle.id, (handle.result_run_id or "")[:8], TASK_QUEUE))
    result = await handle.result()
    print("② 巡检完成，返回：")
    print("   " + json.dumps(result, ensure_ascii=False, indent=1).replace("\n", "\n   "))

    fails = []
    if not isinstance(result.get("pending_decision"), int) or result["pending_decision"] < 1:
        fails.append("pending_decision < 1")

    path = Path(str(result.get("report_path") or ""))
    if not path.exists():
        fails.append("报告文件不存在：%s" % path)
        data = {}
    else:
        data = json.loads(path.read_text("utf-8"))
        print("③ 报告落盘 %s（%d 字节；SCAN_DIR=%s）" % (path, path.stat().st_size, SCAN_DIR))

    items = {it.get("ticket_id"): it for it in (data.get("items") or [])}
    human = items.get(ASSERT_HUMAN)
    if human is None:
        fails.append("报告缺真实人门工单 %s" % ASSERT_HUMAN)
    else:
        print("④ 人门工单 %s：stage=%s/%s 停留 %.1fh 验收 %d/%d 脚本门=%s(%s) pending=%d → 建议【%s】"
              % (ASSERT_HUMAN, human["stage"], human["stage_state"], human["dwell_hours"],
                 human["acceptance_done"], human["acceptance_total"],
                 human["gate_label"] or "无", human["gate_green"], human["pending_count"],
                 human["suggestion"]))
        print("   理由：" + "；".join(human["reasons"]))
        if human["suggestion"] != "可签":
            fails.append("%s 建议应为「可签」，实得 %s" % (ASSERT_HUMAN, human["suggestion"]))
    settled = items.get(ASSERT_SETTLED)
    if settled is None:
        fails.append("报告缺真实 settled 工单 %s" % ASSERT_SETTLED)
    else:
        print("⑤ settled 工单 %s：验收 %d/%d → 建议【%s】（%s）"
              % (ASSERT_SETTLED, settled["acceptance_done"], settled["acceptance_total"],
                 settled["suggestion"], "；".join(settled["reasons"])))
        if settled["suggestion"] != "待补":
            fails.append("%s 建议应为「待补」，实得 %s" % (ASSERT_SETTLED, settled["suggestion"]))
    if data.get("red_line") != SCAN_RED_LINE:
        fails.append("红线声明不在报告里")

    print("⑥ 三档计数：%s" % json.dumps(data.get("summary"), ensure_ascii=False))
    print("⑦ 闭环到此为止：报告已给出「可签」建议；sign 签字只能人（不在本脚本）。")

    if fails:
        print("\n红灯 %d 项：" % len(fails))
        for f in fails:
            print("  - %s" % f)
        return 1
    print("\n全绿：巡检→报告→可签建议 闭环成立。")
    # 清理自身产生的 workflow
    try:
        h = client.get_workflow_handle(VERIFY_WF_ID)
        await h.terminate(reason='verify_m6 自测完成，自动清理')
        print("已清理 workflow: %s" % VERIFY_WF_ID)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
