#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_decision_state_bypass.py — 决策态唤醒旁路（t261003-15，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「票进入需要人或执行器拍板的状态时，执行器一定被叫醒，
绝不被自喂排除规则吞掉」——t261003-10 实案：票 blocked 45 分钟无人知晓）：
- A 已被简报点名的票 T 依次进入 blocked / refused / awaiting-human 三个决策态
  → 每次都产出唤醒（idem 规则①与疑似自规则②都不得吞决策态行）；
- B 对照分支（工单要求场景 b）：同一张已被简报点名的票，简报后的**第一个常规**
  迁移 → 仍被压制（旁路是选择性的，不掀翻自喂排除）；
- C 决策唤醒之后环路重新有界：决策简报被消化后，同票下一个常规首迁移
  → 再次被压制（旁路不解绑排除环）；
- D 零发现周期行照旧被过滤（t261003-04 零发现行不回潮——旁路不得把
  '0 tickets, 0 pending' 巡检行放行成唤醒）；
- E 红线级周期（self_lock 判定在拍）对已简报票的常规迁移 → 照常唤醒（红线级
  本就旁路压制；执行器自己卡死自己在等时的信号绝不静默）。注：stall 红线拍
  遇新账行时判活按「账本新行=进展」翻回 advancing（liveness 语义，非本票面），
  红线旁路的可达真面是 self_lock 拍——本条锚 self_lock。

intent 分工：splitLoopRows 旁路真值表与 DECISION_STAGE_STATES 漂移锁归
developer L1（watchdog tests）；t260929-04-wake-self-wake-loop 锁自喂环路的
一般形状（首迁移压制/第二跳恢复/未简报票照醒），本条只锁「决策态恒旁路」
这一新契约面与其边界（B/C/D/E），不互替。
三态：node 缺席=ENV_FAIL exit 2；harness/实现未落地=FAIL exit 1 点名
（TDD 红属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t261003-15/sc_wake_decision_state_bypass.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "t260929-04"))
from lib_wake_harness import (  # noqa: E402
    WakeHarness, ok, ledger_row,
)


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        h.cmd("start", project=proj, config=h.fixture_config(proj),
              now="2026-09-28T10:00:00+08:00")

        def brief_ticket(ticket, seq):
            """简报点名票 T 并把队列消化干净（建立 briefed 集合，模拟 t261003-10 的 21:12 简报）。"""
            h.cmd("append_ledger", project=proj,
                  row=ledger_row(proj, ticket, seq, "running", stage="implement"))
            ok(h.drain(proj) == 1, "setup 简报点名 %s" % ticket, None)
            h.control_frame(sid, [])

        # A 已简报票进入决策态 → 恒旁路唤醒（t261003-10 病灶主面）
        # blocked（真实落地态：引擎保护路径拒绝/段失败都落 blocked）
        brief_ticket("t-blk", 1)
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-blk", 2, "blocked", stage="implement",
                             reason="protected-path refusal"))
        ok(h.drain(proj) == 1, "A1 简报过的票落 blocked=唤醒（idem/疑似自都不得吞）", None)
        h.control_frame(sid, [])
        # awaiting-human（签字门：等人拍板）
        brief_ticket("t-hum", 1)
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-hum", 2, "awaiting-human", stage="arbitrate",
                             reason="等人签字"))
        ok(h.drain(proj) == 1, "A2 简报过的票落 awaiting-human=唤醒", None)
        h.control_frame(sid, [])
        # refused（工单点名的决策态字面量——防御性覆盖）
        brief_ticket("t-rfs", 1)
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-rfs", 2, "refused", stage="merge",
                             reason="gate refused"))
        ok(h.drain(proj) == 1, "A3 简报过的票落 refused=唤醒", None)
        h.control_frame(sid, [])

        # B 对照（工单场景 b）：简报后的第一个常规迁移仍被压制
        brief_ticket("t-rt", 1)
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-rt", 2, "running", stage="review"))
        ok(h.drain(proj) == 0, "B 简报后的第一个常规迁移=仍压制（旁路是选择性的）", None)

        # C 决策唤醒之后环路重新有界：下一个常规首迁移再被压制
        #    （t-blk 的 blocked 已被决策简报点名并消化；下一个非常规迁移照旧吃规则②）
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-blk", 3, "running", stage="implement"))
        ok(h.drain(proj) == 0, "C 决策简报后的常规首迁移=再压制（旁路不解绑排除环）", None)

        # D 零发现周期行照旧过滤（t261003-04 不回潮——旁路不得放行零发现行）
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-scan", 1, "done", stage="scan",
                             reason="Scan report: 0 tickets, 0 pending (nothing to do)"))
        ok(h.drain(proj) == 0, "D 零发现周期行=仍过滤（决策旁路不扩大化到周期行）", None)

        # E 红线级周期（self_lock 在拍）已简报票常规迁移=照常唤醒（红线信号不静默）
        brief_ticket("t-red", 1)
        h.cmd("session_face_set",
              pending=[{"id": "ap-1", "raised_by_executor": True, "kind": "approval"}])
        h.cmd("tick", seconds=60)
        ok(any(a.get("rule") == "self_lock" for a in
               (h.cmd("status", project=proj)["status"].get("alerts") or [])),
           "E0 self_lock 红线判定在拍（前置自证）", None)
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-red", 2, "running", stage="review"))
        ok(h.drain(proj) == 1, "E 红线级周期（self_lock）已简报票常规迁移=照常唤醒", None)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
