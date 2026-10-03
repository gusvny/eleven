#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_verdict_face.py — 逐拍唤醒判定状态面（t261003-15，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=「人只看 watchdog status API 就能回答『这一拍为什么没醒/醒了』」
——t261003-10 实案里答案只能去翻 executor 会话日志）：
- A 无新账行的一拍：verdict 在场且显式不醒（woke=false、reason 非空点名原因、
  considered=0）——「没醒」必须自己显式说话，绝不缺席装没事；
- B 真唤醒的一拍：verdict=woke=true、considered≥1、reason 非空；
- C 被疑似自规则压制的一拍：verdict=woke=false、considered≥1、reason 非空
  （压制也必须可从 API 复盘，t260929-04 观测面的逐拍补全）；
- D additive-only：既有 wakes 行键集恰=panel-contract 承诺集
  {at,ticket,dedupe_key,mode,accepted} 一个不改，wakes 历史照旧——新键只增不删。

intent 分工：status 键集/时间戳/溯源契约归 t260928-28-watchdog-status-surface
（本条不断言全键集，只锁 verdict 键的存在性与语义）；verdict 记录器内部
真值表归 developer L1；唤醒行为本身归 t261003-15-wake-decision-bypass。
三态：node 缺席=ENV_FAIL exit 2；实现未落地（verdict 键缺席）=FAIL exit 1
点名（TDD 红属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t261003-15/sc_wake_verdict_face.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "t260929-04"))
from lib_wake_harness import (  # noqa: E402
    WAKE_KEYS, WakeHarness, ok, ledger_row,
)


def verdict_of(h, proj):
    return (h.cmd("status", project=proj).get("status") or {}).get("last_wake_verdict")


def main():
    h = WakeHarness()
    h.start()
    try:
        proj = "p1"
        sid = "executor-" + proj
        h.cmd("start", project=proj, config=h.fixture_config(proj),
              now="2026-09-28T10:00:00+08:00")

        # A 无新账行的一拍：verdict 显式「不醒+原因」，不缺席
        h.cmd("tick", seconds=0)
        v = verdict_of(h, proj)
        ok(isinstance(v, dict) and v.get("woke") is False and v.get("considered") == 0
           and str(v.get("reason") or ""),
           "A 无新行一拍 verdict=显式不醒（woke=false/considered=0/reason 非空）", v)

        # B 真唤醒的一拍：verdict=woke=true、considered≥1
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-w", 1, "running", stage="implement"))
        ok(h.drain(proj) == 1, "setup 常规唤醒发生", None)
        v = verdict_of(h, proj)
        ok(isinstance(v, dict) and v.get("woke") is True
           and isinstance(v.get("considered"), int) and v["considered"] >= 1
           and str(v.get("reason") or ""),
           "B 唤醒一拍 verdict=woke=true/considered≥1/reason 非空", v)
        h.control_frame(sid, [])

        # C 被疑似自规则压制的一拍：verdict 也必须点名（不静默吞）
        h.cmd("append_ledger", project=proj,
              row=ledger_row(proj, "t-w", 2, "running", stage="review"))
        ok(h.drain(proj) == 0, "setup 压制发生（简报后首迁移）", None)
        v = verdict_of(h, proj)
        ok(isinstance(v, dict) and v.get("woke") is False
           and isinstance(v.get("considered"), int) and v["considered"] >= 1
           and str(v.get("reason") or ""),
           "C 压制一拍 verdict=woke=false/considered≥1/reason 点名原因", v)

        # D additive-only：wakes 行键集恰=panel-contract 承诺集，一个不改
        st = h.cmd("status", project=proj)["status"]
        bad = [w for w in (st.get("wakes") or []) if set(w) != WAKE_KEYS]
        ok(not bad, "D wakes 行键集恰=承诺集（additive-only 不破面板契约）",
           [sorted(w) for w in bad][:2])
    finally:
        h.finish()


if __name__ == "__main__":
    main()
