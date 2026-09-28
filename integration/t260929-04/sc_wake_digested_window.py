#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_digested_window.py — 已消化判定走真队列镜像（t260929-04，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「不重发它还没消化的简报」+「镜像坏了也不装死」）：
- A 未消化窗内（control 帧显示我上一份简报的 rpcId 还在队列）→ 第二个事件**零新简报**
  （设计稿「不醒它还没消化的」可判定锚）；
- B 消化后（queue 帧把我的项清空）→ 新事件照常再醒（wake 不丢：消化窗一过就恢复）；
- C 镜像流故障注入（control_fail = genuinely unreachable）→ 照发 + **点名** no-signal
  （status.queue_mirror 显式 unreadable，绝不静默假设「已消化」，也绝不卡死不再醒）；
- D 畸形/垃圾帧（缺字段/非对象/未知形状）→ 跳过且不崩、合法项照常生效（坏帧计数
  显式回执）——别人的队列输入不拦我们（按 rpcId 认领，不按深度误伤）。

intent 分工：t260928-28 alert-discipline B 锁的是旧桩队列面的「同 dedupe key 不重发」；
本条锁**真镜像数据面**（control 帧驱动认领）+ 故障/畸形态，不同 intent 面。
developer L1 守 QueueMirror 纯语义（baseline 播种/queue 替换/终态收口）。
三态：node 缺席=ENV_FAIL exit 2；harness 新协议未落地=FAIL exit 1 点名（TDD 红
属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-04/sc_wake_digested_window.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_wake_harness import (  # noqa: E402
    WakeHarness, ok, ledger_row, queued_item, summary_and_exit,
)


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        h.cmd("start", project=proj, config=h.fixture_config(proj),
              now="2026-09-28T10:00:00+08:00")

        # setup：第一份简报落地，记下 requestId（镜像里认自己的项用）
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-1", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1 and d[0].get("requestId"), "setup 恰一份带 requestId 的简报", d[:1])
        rid = d[0].get("requestId") if d else None

        # A 未消化窗：镜像显示我的项还在 → 第二事件零新简报
        h.control_seed({sid: [queued_item("q-1", rpc_id=rid)]})
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-2", 1, "done"))
        ok(len(h.pump(proj)) == 0, "A 未消化窗内第二事件=零新简报", None)

        # B 消化后：queue 帧清空我的项 → 新事件照常再醒
        h.control_frame(sid, [])
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-3", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1, "B 消化后新事件照常再醒（不丢唤醒）", d[:1])
        rid2 = d[0].get("requestId") if d else None

        # C 镜像流故障 → 照发 + status.queue_mirror 点名不可读
        h.control_fail()
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-4", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1, "C 镜像不可读=照发（不静默不丢）", d[:1])
        rid3 = d[0].get("requestId") if d else None
        st = h.cmd("status", project=proj)["status"]
        ok("unreadable" in str(st.get("queue_mirror")),
           "C queue 态不可读在 status 点名（显式 no-signal）", st.get("queue_mirror"))

        # D 畸形帧跳过 + 合法项照常认领（别人的输入不拦，我的项未消化则不重发）
        r = h.control_frame(sid, [{"garbage": True}, "not-an-object", {"type": "unknown-kind"}])
        ok(r.get("bad_items") == 3, "D 畸形项逐个计数显式回执", r)
        h.control_frame(sid, [queued_item("q-9", rpc_id=rid3)])
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-5", 1, "done"))
        ok(len(h.pump(proj)) == 0, "D 我的未消化项（rpcId 认领）→ 不重发", None)
        h.control_frame(sid, [])
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-6", 1, "done"))
        ok(len(h.pump(proj)) == 1, "D 合法项消化后 → 照常再醒", None)
        ok(h.proc.poll() is None, "D 全程守望者不崩", None)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
