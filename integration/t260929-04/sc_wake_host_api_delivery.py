#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_host_api_delivery.py — wake 投递走真宿主 API（t260929-04，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「最后一跳接通」：executor 会话真的收到排队简报，且丢不了、
不静默失败）：
- A 值得醒的状态迁移行 → 经 sessionController.prompt 投递：delivered 恰 1 条，
  mode='queue'、sessionId=声明 executor_session、content 非空人话简报点名票号、
  requestId 以 watchdog- 前缀（client-minted 可判定锚）；status.wakes 行键恰为
  panel-contract 承诺集 {at, ticket, dedupe_key, mode, accepted}（一个不改）且
  accepted=true；
- B 红线级（self-lock 判定驱动 level=redline）→ mode='steer'（redline-only steer
  纪律随票保持；stalled 只走 alert 出口，归 t260928-28 判活面）；
- C 宿主 sessionController 缺席（headless 形态桩注入）→ 零成功投递 + wake_failed
  alert 点名不可用原因（两出口分工）——绝不「不醒=没事」的静默，守望者不崩；
- D prompt 桩恢复 → 故障不粘滞，后续 tick 照常投递。

intent 分工：developer L1 守 prompt 请求形状纯函数；本场景锁协议投递面×回执×
显式失败三态。与 t260928-28 五条 intent 不同面（彼锁读账/判活/对账/叫人纪律）。
三态：node 缺席=ENV_FAIL exit 2；harness 新协议未落地=FAIL exit 1 点名（TDD 红
属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-04/sc_wake_host_api_delivery.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_wake_harness import (  # noqa: E402
    WakeHarness, WAKE_KEYS, ok, ledger_row, summary_and_exit,
)


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        h.cmd("start", project=proj, config=h.fixture_config(proj),
              now="2026-09-28T10:00:00+08:00")

        # A 真投递面：状态迁移行 → queue 模式简报落地 + 契约键集恰在
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-1", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1, "A 恰一条投递", d)
        if d:
            w = d[0]
            ok(w.get("mode") == "queue", "A mode=queue（排队不丢）", w)
            ok(w.get("session") == sid, "A 投给声明的 executor_session", w)
            ok(str(w.get("requestId", "")).startswith("watchdog-"), "A requestId=watchdog- 前缀（client-minted）", w)
            ok("t-1" in str(w.get("content")), "A 简报点名票号（人话可读）", str(w)[:200])
        st = h.cmd("status", project=proj)["status"]
        wakes = st.get("wakes") or []
        ok(len(wakes) == 1 and set(wakes[0]) == WAKE_KEYS and wakes[0]["accepted"] is True,
           "A status.wakes 键集恰=契约承诺且 accepted=true", wakes)

        # B 红线级：self-lock（等自己发的 approval）→ level=redline → steer，新票行仍醒
        #（先标记 A 的简报已消化：镜像播种为空 = 我们的项不在队列。
        #  注：账本新行本身=推进信号，stalled 与「本轮有新行」不同现——账本驱动 steer
        #  的红线路径=self_lock 判定；stalled 只走 alert 出口，归 t260928-28 判活面。）
        h.control_seed({sid: []})
        h.cmd("session_face_set", pending=[{"id": "req-1", "raised_by_executor": True}])
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-r", 1, "done"))
        d = h.pump(proj, seconds=16 * 60)
        ok(len(d) == 1 and d[0].get("mode") == "steer", "B 红线级（self-lock）驱动 steer 且迁移照醒", d[:1])
        h.cmd("session_face_set", pending=[])

        # C 宿主 sessionController 缺席 → wake_failed alert 点名（不静默），守望者不崩
        #（契约：wakes 契约行记 accepted 的唤醒；被拒投递走 alert 面点名——两出口分工）
        h.cmd("session_stub_set", present=False)
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-2", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 0, "C 缺宿主面=零成功投递", d)
        st = h.cmd("status", project=proj)["status"]
        alerts = st.get("alerts") or []
        wf = [a for a in alerts if a.get("rule") == "wake_failed"]
        ok(wf and "不可用" in str(wf[-1].get("detail", "")),
           "C wake_failed alert 点名不可用原因", wf[-1:] or alerts[-3:])
        ok(h.proc.poll() is None, "C 守望者不崩（显式失败非致命）", st.get("last_error"))

        # D 恢复宿主面 → 故障不粘滞
        h.cmd("session_stub_set", present=True, prompt_result={"accepted": True})
        h.cmd("append_ledger", project=proj, row=ledger_row(proj, "t-4", 1, "done"))
        d = h.pump(proj)
        ok(len(d) == 1 and d[0].get("mode") == "queue", "D 故障不粘滞（恢复后照常 queue 投递）", d[:1])
    finally:
        h.finish()


if __name__ == "__main__":
    main()
