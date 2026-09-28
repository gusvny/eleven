#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_tail_dedupe_rotation.py — 账本跟读×去重×轮转不丢行（t260928-28，灰盒 L2/L3，离线秒级零 docker）。

intent（用户可感知行为，工单 scope 1 + 宿主原话「基于状态变化 notify」）：
- A 增量跟读：账本 append 新行后 tick → status.ledger.rows_seen 前进、last_row_at
  更新——「读到了什么」面板可见；
- B at-least-once 去重：同一幂等键行重投 → 不产生第二条消费（dupes_skipped 计数
  前进）——「同一件事不响两次」的账本侧根；
- C 轮转不丢行：活动账 rename 归档 + 新活动账继续 append → tick 后新行仍被
  跟到（归档侧尾巴不静默丢失）；归档序号缺口显式上报，绝不「看起来都在」；
- D 畸形行三态：坏 JSON/半行截断 → 跳过 + 计数（malformed_rows 前进）+ 进程
  不崩、后续合法行照常被消费——外部输入畸形纪律；
- E worth-waking 过滤：非状态迁移行（纯 kind 话注记，无 stage/stage_state）不
  触发 wake——宿主明拒的「每行都醒」傻轮询不复发（delivered_wakes 不因噪声行
  增长）。

夹具行形状=真实 event-ledger-v1（v/ts/idem/stage/stage_state，见
lib_watchdog_harness.ledger_row）——仲裁 gen0 教训：夹具行形状错会被 tailer
正确地计为 malformed，下游全假红。
灰盒声明：只经 harness 协议 append/rotate/tick/status，不 import 插件内部。
intent 分工：developer L1 守 tailer 纯函数真值表（fixture JSONL 单测），本场景
锁「真文件、跨轮转、跨 tick」的时序行为半；与 t260928-13 event-ledger 场景
intent 不同面（彼守引擎写面/派生投影，本条守望者消费面）。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属
预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260928-28/sc_watchdog_tail_dedupe_rotation.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_watchdog_harness import Harness, ledger_row, noise_row, ok  # noqa: E402


def main():
    h = Harness()
    h.start()
    try:
        h.cmd("start", project="p1", config=h.fixture_config("p1"),
              now="2026-09-28T10:00:00+08:00")
        base = h.cmd("status", project="p1")["status"]["ledger"]

        # A 增量跟读：append 状态迁移行 → tick → rows_seen 前进
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=5)
        led = h.cmd("status", project="p1")["status"]["ledger"]
        ok(led["rows_seen"] > base["rows_seen"], "A 新行被增量跟到", led)
        ok(bool(led.get("last_row_at")), "A last_row_at 更新", led)

        # B at-least-once 去重：同 idem 重投不二次消费
        dup_before = led["dupes_skipped"]
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-1", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=5)
        led = h.cmd("status", project="p1")["status"]["ledger"]
        ok(led["dupes_skipped"] > dup_before, "B 重投行被去重计数", led)
        h.cmd("delivered_wakes")  # 排水面：清掉 A/B 的合法投递，E 的空断言才纯净

        # C 轮转不丢行：rotate 后新账 append → 仍跟到
        h.cmd("rotate_ledger", project="p1")
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-2", 1, "implement", stage="implement"))
        h.cmd("tick", seconds=5)
        led = h.cmd("status", project="p1")["status"]["ledger"]
        ok(led["rows_seen"] >= 2, "C 轮转后新活动账行仍被跟到（t-1+t-2 去重后恰 2）", led)
        # C2 归档缺口显式上报：造一个归档序号跳号再 tick
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-3", 1, "review_plan", stage="review_plan"),
              skip_archive_no=2)
        h.cmd("tick", seconds=5)
        st = h.cmd("status", project="p1")["status"]
        ok(bool(st["ledger"].get("gaps_seen") or st["alerts"]),
           "C2 归档缺口显式上报（不静默）", st["ledger"])

        # D 畸形行：坏 JSON / 半行（未知 schema 形状归 developer L1；此处打协议级畸形）
        bad_before = led["malformed_rows"]
        h.cmd("append_ledger", project="p1", raw="{not json")
        h.cmd("append_ledger", project="p1", raw='{"v": "event-ledger-v1", "tic')  # 半行
        h.cmd("tick", seconds=5)
        led = h.cmd("status", project="p1")["status"]["ledger"]
        ok(led["malformed_rows"] > bad_before, "D 畸形行被跳过并计数", led)
        ok(led["rows_seen"] >= 2, "D 合法行在畸形行之后照常被消费（行数不因畸形倒退）", led)

        # E 非状态迁移行不唤醒（傻轮询红线）
        h.cmd("append_ledger", project="p1", row=noise_row("p1", "t-1", 2))
        h.cmd("tick", seconds=5)
        wakes_e = h.cmd("delivered_wakes")["wakes"]
        ok(len(wakes_e) == 0, "E 噪声行不触发 wake（宿主拒绝的每行轮询不复发）", wakes_e)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
