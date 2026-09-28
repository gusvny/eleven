#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_self_wake_loop.py — 自醒环路排除（t260929-04 新故障面，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「executor 不会被自己的动作喂出无限自醒」，且不误吞外部进展）：
- A 简报含票 T 后，T 的**第一个新 stage_key 迁移**（executor 自己的签名/修复回写）
  → 零唤醒，且 presumed_self_rows 计数在 status 高声留痕（不是静默吞）；
- B 同票 T 的**第二个新 stage_key** → 恢复唤醒（排除只吞一跳，外部多步进展不被
  永久吞掉——排除规则的有界性锚）；
- C 同窗内**另一张票 U** 的迁移 → 立即唤醒（排除不扩大化到没简报过的票）；
- D 简报过的票 V 下一窗自写 → 至多 1 次唤醒、其后一次迁移被排除（非简报票的
  有界环路锚，review C1 条：单跳即断，不无限自喂）；
- E 红线出口（stalled 判定）在排除窗内照常走 alert 面——排除门只压账本驱动的
  wake 出口，**永不拦叫人出口**（两出口纪律）。

intent 分工：developer L1（splitLoopRows 纯函数真值表 + loop 单测）守规则内部；
本场景锁**环路形状输入的端到端行为**（喂账→泵 tick→数投递）。与 t260928-28 各条
intent 不同面（彼无排除概念）。
三态：node 缺席=ENV_FAIL exit 2；harness 新协议未落地=FAIL exit 1 点名（TDD 红
属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-04/sc_wake_self_wake_loop.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_wake_harness import (  # noqa: E402
    WakeHarness, ok, ledger_row, summary_and_exit,
)


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        h.cmd("start", project=proj, config=h.fixture_config(proj),
              now="2026-09-28T10:00:00+08:00")

        # setup：简报含票 t-a → 建立 briefed 集合并消化
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-a", 1, "done"))
        ok(h.drain(proj) == 1, "setup 简报含票 t-a", None)
        h.control_frame(sid, [])

        # A executor 自己回写 t-a 的下一个 stage_key → 零唤醒 + 高声留痕
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-a", 2, "review", stage="review"))
        ok(h.drain(proj) == 0, "A 自写下一 stage_key=零唤醒", None)
        st = h.cmd("status", project=proj)["status"]
        ok(st.get("presumed_self_rows") == 1 and st.get("presumed_self_detail"),
           "A presumed_self 计数+明细在 status 高声留痕", (st.get("presumed_self_rows"), st.get("presumed_self_detail")))

        # B t-a 第二个新 stage_key → 恢复唤醒（排除有界，不永久吞外部进展）
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-a", 3, "done", stage="review"))
        ok(h.drain(proj) == 1, "B 第二个新 stage_key=恢复唤醒", None)
        h.control_frame(sid, [])

        # C 另一张票 t-u 同窗迁移 → 立即唤醒（排除不扩大化）
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-u", 1, "done"))
        ok(h.drain(proj) == 1, "C 未简报票迁移=立即唤醒", None)

        # D 简报过的票 t-v 下一次迁移自写：至多 1 次唤醒、其后被排除（单跳断环）
        h.control_frame(sid, [])
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-v", 1, "done"))
        ok(h.drain(proj) == 1, "D1 非简报票首迁移=1 次唤醒（环路单跳界内）", None)
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-v", 2, "review", stage="review"))
        ok(h.drain(proj) == 0, "D2 简报过的票下一迁移=零唤醒（环到此断）", None)

        # E 排除窗内红线出口照常：停摆判定 → stall alert（叫人出口永不被排除门拦）
        h.cmd("session_progress", stop=True)
        h.cmd("tick", seconds=16 * 60)
        st = h.cmd("status", project=proj)["status"]
        alerts = st.get("alerts") or []
        ok(any(a.get("rule") == "stall" for a in alerts),
           "E 排除窗内 stalled 照常落 stall alert（叫人出口不被拦）", [a.get("rule") for a in alerts])
    finally:
        h.finish()


if __name__ == "__main__":
    main()
