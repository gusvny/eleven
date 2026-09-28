#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_reconcile_board_truth.py — 对账=第一公民：看板为真源×缺行留痕×降级显式（t260928-28，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为，工单 scope 2/3 + 设计稿需求 12「不静默降级」）：
- A 启动即全量对账：夹具账本缺一行而看板（可见性列表桩）有对应状态 → tick 过
  节拍后 reconcile 报 mismatch 且 mismatches 点名到票——「看板是真源、账本是
  派生投影」；
- B 缺 N 行本身是 alertable event：差额 N 落一条专属 alert（ledger_missing_rows
  族），N 变化重响、N 不变冷却内不重响——「曾缺失 N 条」被记进账而非只修不记
  （工单 scope 2 原话 + 验收演示 §7.3）；
- C 看板真源不依赖 worker 在线：board 桩是可见性列表（无任何在线 worker 信号）
  仍可完成对账——「绝不要求某票 worker 在线」承诺；
- D 对账失败=显式 degraded：board 桩故障（超时）→ reconcile.state=degraded
  带 reason+since，绝不渲染成 ok/all-fine；恢复后回非 degraded；
- E mismatch 以看板为准：账本推演状态落后于看板 → mismatches 里 board_state 是
  看板状态，同时 mismatch 自身可见（修正与留痕并行）；补齐账本后回 ok。

夹具行形状=真实 event-ledger-v1（v/ts/idem/stage/stage_state，见
lib_watchdog_harness.ledger_row）——仲裁 gen0 教训：夹具行形状错会被 tailer
正确地计为 malformed，对账无输入而全假红。
灰盒声明：board=夹具可见性行列表（harness 协议 board_set），账本=tmp 真文件；
断言只锚 status.reconcile 契约键（state/reason/since/mismatches）与 alerts。
intent 分工：与 liveness/self-lock 场景不同面（彼守判活与自锁，本条守对账与
缺行留痕）；developer L1 守对账纯函数真值表。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属
预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260928-28/sc_watchdog_reconcile_board_truth.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_watchdog_harness import Harness, ledger_row, ok  # noqa: E402


def missing_rows_alerts(st):
    return [a for a in (st.get("alerts") or []) if "missing_rows" in str(a.get("key", ""))]


def main():
    h = Harness()
    h.start()
    try:
        # 看板桩：t-1 已到 integ；账本只写到 review_plan（缺后续行）
        h.cmd("board_set", rows=[{"ticket": "t-1", "stage_state": "integ"},
                                 {"ticket": "t-2", "stage_state": "review_plan"}])
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 1, "review_plan", stage="review_plan"))
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-2", 1, "review_plan", stage="review_plan"))

        # A 启动即全量：重启（内存水位全弃）后 mismatch 点名到票
        h.cmd("start", project="p1", config=h.fixture_config("p1"),
              now="2026-09-28T10:00:00+08:00")
        h.cmd("tick", seconds=65)  # 过一个缺省对账节拍
        st = h.cmd("status", project="p1")["status"]
        rec = st["reconcile"]
        ok(rec.get("state") == "mismatch", "A 全量对账逮到账本落后看板", rec)
        mm = rec.get("mismatches") or []
        ok(any(m.get("ticket") == "t-1" and m.get("board_state") == "integ" for m in mm),
           "A/E mismatch 点名到 t-1 且以看板状态呈现", mm)
        ok(bool(missing_rows_alerts(st)), "B 缺 N 行落专属 alert", missing_rows_alerts(st))

        # B N 不变冷却内不重响
        n1 = len(missing_rows_alerts(st))
        h.cmd("tick", seconds=65)
        st = h.cmd("status", project="p1")["status"]
        n2 = len(missing_rows_alerts(st))
        ok(n2 == n1, "B N 不变冷却内不重响", (n1, n2))

        # E 补齐路径：把缺的行补进账本 → mismatch 消除回 ok
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 2, "integ", stage="integ"))
        h.cmd("tick", seconds=65)
        rec = h.cmd("status", project="p1")["status"]["reconcile"]
        ok(rec.get("state") == "ok", "E 补齐后对账回 ok", rec)

        # C 看板真源零 worker 依赖：换 board（仍是无 worker 信号的可见性列表）→ 新 mismatch 被逮
        h.cmd("board_set", rows=[{"ticket": "t-1", "stage_state": "release"},
                                 {"ticket": "t-2", "stage_state": "review_plan"}])
        h.cmd("tick", seconds=65)
        rec = h.cmd("status", project="p1")["status"]["reconcile"]
        ok(rec.get("state") == "mismatch"
           and any(m.get("board_state") == "release" for m in (rec.get("mismatches") or [])),
           "C 纯可见性列表即真源（零 worker 在线依赖）且以看板为准", rec)

        # D 对账失败=显式 degraded，绝不 all-fine；恢复后回非 degraded
        h.cmd("board_fail", mode="timeout")
        h.cmd("tick", seconds=65)
        rec = h.cmd("status", project="p1")["status"]["reconcile"]
        ok(rec.get("state") == "degraded" and rec.get("reason") is not None
           and rec.get("since") is not None,
           "D 对账失败=degraded+reason+since", rec)
        h.cmd("board_fail", mode="off")
        h.cmd("tick", seconds=65)
        rec = h.cmd("status", project="p1")["status"]["reconcile"]
        ok(rec.get("state") in ("ok", "mismatch"), "D 恢复后不再 degraded", rec)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
