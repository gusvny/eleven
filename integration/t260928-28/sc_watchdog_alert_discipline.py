#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_alert_discipline.py — 两出口纪律×重启不重播×夜间口径×开关（t260928-28，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为，工单 scope 6/7/8 + 宿主原话「一声就够，别烦我」「提醒也是可配置的」）：
- A 两出口不混装：状态迁移事件 → wake 出口（队列投递，回执 accepted=true 被夹具
  会话桩记录）；需要人的事件 → alert 出口（alerts 落账 + notify 位）；
- B 唤醒节律三层：同 idem 重投不重发（账本侧去重）；上一份简报未消化（队列占
  用）不重发；已消化后**新事件**才再醒——「不丢消息」与「不重复唤醒」双向可判
  定，且新事件不被旧冷却错压；
- C 重启不重播：制造 stall alert → restart（原配置全量重建）→ 12h 冷却窗内同
  key 不重播、不补投递——去重态从 alerts 账重放重建（工单 scope 7 原话）；
- D 夜间口径：注入时钟进夜间窗 → 非红线静音（night_muted=true，记录仍在）、
  红线级照常发声（例外面）；
- E 未答复的 alert 永不自动变成决定：收割全部投递，断言无任何「代签/代决定」
  形状（wake 只能是简报通知形状）；
- F 开关与未声明：alerts.enabled=false → 强触判据不发声；总闸 enabled=false →
  status 显式 stopped 非消失；未声明项目零行为 declared:false。

夹具行形状=真实 event-ledger-v1（v/ts/idem/stage/stage_state，见
lib_watchdog_harness.ledger_row）——仲裁 gen0 教训：夹具行形状错会被 tailer
正确地计为 malformed，wake 永不触发而全假红。
灰盒声明：全部经 harness 协议驱动，断言锚 delivered_wakes/alerts/notify 公开
面。intent 分工：与 reconcile/liveness 场景不同面（本条守出口纪律与提醒节律）；
developer L1 守 alert-rules 纯函数真值表（夜间窗/冷却/跨午夜）。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属
预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260928-28/sc_watchdog_alert_discipline.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_watchdog_harness import Harness, ledger_row, ok  # noqa: E402


def main():
    h = Harness()
    h.start()
    try:
        # A 状态迁移 → wake 出口（队列投递、accepted 回执）
        h.cmd("start", project="p1", config=h.fixture_config("p1"),
              now="2026-09-28T10:00:00+08:00")
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=5)
        wakes = h.cmd("delivered_wakes")["wakes"]
        ok(len(wakes) >= 1 and wakes[0].get("mode") == "queue"
           and wakes[0].get("accepted") is True,
           "A wake=队列投递且回执 accepted", wakes)
        notify = h.cmd("status", project="p1")["status"]["notify"]
        ok(isinstance(notify.get("beep"), bool), "A notify.beep 面板消费位在位", notify)

        # B1 上一份简报未消化（队列占用）→ 新事件也不重发
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 2, "implement", stage="implement"))
        h.cmd("tick", seconds=65)
        ok(len(h.cmd("delivered_wakes")["wakes"]) == 0,
           "B1 队列占用期不重发（不丢消息且不轰炸）")

        # B2 已消化后，新事件才再醒
        h.cmd("session_digest", all_pending=True)
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-2", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=65)
        wakes = h.cmd("delivered_wakes")["wakes"]
        ok(len(wakes) == 1, "B2 已消化后新事件再醒（新事件不被旧冷却错压）", wakes)

        # B3 同 idem 重投（at-least-once）不重发
        h.cmd("session_digest", all_pending=True)
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-2", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=65)
        ok(len(h.cmd("delivered_wakes")["wakes"]) == 0, "B3 同 idem 重投不重发")

        # C 制造 stall alert → restart（原配置）→ 12h 冷却窗内不重播
        h.cmd("session_progress", stop=True)
        h.cmd("tick", seconds=16 * 60)
        st = h.cmd("status", project="p1")["status"]
        alerts_before = st["alerts"]
        ok(any("stall" in str(a.get("key", "")) for a in alerts_before),
           "C 停摆 alert 已落账", alerts_before)
        h.cmd("restart")  # 无参=全部实例原配置重启（重启不重播语义的载体）
        h.cmd("tick", seconds=65)
        st = h.cmd("status", project="p1")["status"]
        ok(len(st["alerts"]) == len(alerts_before),
           "C 重启后 12h 冷却窗内不重播旧 alert", (len(alerts_before), len(st["alerts"])))
        ok(len(h.cmd("delivered_wakes")["wakes"]) == 0, "C 重启后不补投递")

        # D 夜间口径：跳进夜间窗
        h.cmd("clock_set", now="2026-09-28T23:30:00+08:00")
        r_mute = h.cmd("force_alert", kind="reconcile_note")   # 非红线级
        ok(r_mute.get("spoken") is False and (r_mute.get("rec") or {}).get("night_muted") is True,
           "D 夜间窗内非红线静音但记录仍在", r_mute)
        r_red = h.cmd("force_alert", kind="self_lock")          # 红线级例外
        ok(r_red.get("spoken") is True, "D 红线级夜间照常发声（例外面）", r_red)

        # E 未答复的 alert 永不自动变成决定
        wakes_all = h.cmd("delivered_wakes")["wakes"]
        ok(all(not w.get("decision") for w in wakes_all),
           "E 投递面无任何代签/代决定形状（升级不阻塞、不代答）", wakes_all)

        # F 开关与未声明
        cfg_no_alerts = h.fixture_config("p1", {"alerts": {"enabled": False}})
        h.cmd("restart", project="p1", config=cfg_no_alerts)
        r = h.cmd("force_alert", kind="stall")
        ok(r.get("spoken") is False, "F alerts.enabled=false 不发声（其余不受扰）", r)
        cfg_off = h.fixture_config("p1", {"enabled": False})
        h.cmd("restart", project="p1", config=cfg_off)
        st = h.cmd("status", project="p1")["status"]
        ok(st.get("enabled") is False, "F 总闸关=显式 stopped 非消失", st)
        r = h.cmd("status", project="undeclared-proj")
        ok(r["status"].get("declared") is False, "F 未声明项目零行为显式 declared:false", r)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
