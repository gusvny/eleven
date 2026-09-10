#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 负向重放夹具生成器——路②（fixtures/README 备选）：生产 COMPLETED 票只读导出。

背景：路①（退役前代码×docker 隔离台×桩）因宿主机 docker 网络地址池耗尽
（all predefined address pools have been fully subnetted，32 网络；在飞他票台面
不可清理）受阻，按 README 备选路②从生产台只读导出。

只读口径（与 replay_check 场景同级）：temporalio SDK connect → get_workflow_handle
→ fetch_history，零 signal/update/写动作；COMPLETED 票永不重放，导出纯读。
宿主令⑤约束面=「迁移与验证」（机器级写+spawn 冒烟）——本脚本不含任何此类动作。

择票：t260910-06 / t260910-09 / t260910-10（宿主实测三次收口被 suggest_next 顶后
各约 4 分钟的三张票=退役前收口、history 含 suggestion 活动命令）。取第一张自证
成功者落 fixtures/history_with_suggest_next.json。

用法：server/engine/.venv/bin/python integration/t260910-14/fixtures/export_prod_history.py
退出：0=夹具已落且自证含 prepare_epic_next 活动命令；1=全部候选票不可用。
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(HERE, "history_with_suggest_next.json")
HOST = os.environ.get("SANDBAR_TARGET_HOST") or "127.0.0.1:7233"
NS = os.environ.get("SANDBAR_NAMESPACE") or "default"
CANDIDATES = ["t260910-06", "t260910-09", "t260910-10"]


async def fetch(client, tid):
    h = client.get_workflow_handle(tid)
    desc = await h.describe()
    status = desc.status.name if desc.status is not None else "?"
    if status != "COMPLETED":
        return None, "%s 状态=%s（非 COMPLETED，跳过）" % (tid, status)
    history = await h.fetch_history()
    return json.loads(history.to_json()), "%s 状态=COMPLETED events=%d" % (tid, len(history.events))


async def main():
    from temporalio.client import Client
    client = await Client.connect(HOST, namespace=NS)
    print("PASS 生产台只读连接（%s ns=%s）" % (HOST, NS))
    for tid in CANDIDATES:
        try:
            data, note = await fetch(client, tid)
        except Exception as e:
            print("FAIL %s 不可达：%s" % (tid, str(e)[:200]))
            continue
        print("PASS " + note)
        if data is None:
            continue
        text = json.dumps(data, ensure_ascii=False)
        has_epic = "prepare_epic_next" in text
        has_sched = "Scheduled" in text
        print("PASS 自证：%s 含 prepare_epic_next=%s 含调度事件=%s"
              % (tid, has_epic, has_sched))
        if not (has_epic and has_sched):
            continue
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print("PASS 夹具已落 %s（%d 字节，源=%s 生产 COMPLETED 导出）"
              % (os.path.relpath(OUT, REPO), os.path.getsize(OUT), tid))
        return 0
    print("FAIL 三张候选票均不可用（不落夹具=场景腿三保持显式红点名）")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
