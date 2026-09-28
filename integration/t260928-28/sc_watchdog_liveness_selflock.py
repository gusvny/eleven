#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_liveness_selflock.py — 判活三态×进展驱动停摆×自锁即时报（t260928-28，灰盒 L3，离线秒级零 docker，注入时钟）。

intent（用户可感知行为，工单 scope 4/5 + 设计稿验收「等自己不等超时」）：
- A 守望者自身心跳显式：last_beat/age_seconds/alive 三件在位且随 tick 前进——
  「守望者死了」面板可判（不静默降级的第 9 条的三态之一）；
- B 引擎存活显式：engine.online 带时间戳与 detail（探针桩故障→显式 down，不
  假绿）；
- C 停摆判定是进展驱动不是裸钟：executor 会话有进展信号（账本新行）时即使
  超过 stall_minutes 也不报 stalled；停掉进展信号、注入时钟推过阈值（15min
  缺省）→ stalled alert 落账且状态带 last_progress_at 与证据；
- D 自锁即时报：执行器会话 pending 的 approval 是它自己发的 → self_lock.state=
  waiting_on_itself 立即可见（tick 1 秒内，不等 stall 超时），且指向对应请求；
- E 待办面读不到=显式 unknown：self_lock.state=unknown+reason，绝不冒充
  none（「没有 X」断言纪律的反面教材锁）；
- F 墙钟跳变不误报：注入时钟一次性前跳大步（休眠恢复形态）但有进展 → 不误报
  stalled（KI-138 家族「数据过期」与「它卡住」两种现象分开报）。

灰盒声明：会话面/待办交互面全部走 harness 夹具桩（session_face_set /
session_progress 协议），断言只锚 status.liveness/self_lock 公开契约键。
intent 分工：与 reconcile 场景（对账/缺行）不同面；developer L1 守 liveness
纯函数真值表（注入时钟单测）。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属
预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260928-28/sc_watchdog_liveness_selflock.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_watchdog_harness import Harness, ledger_row, ok  # noqa: E402


def row(project, ticket, seq):
    # 真实 event-ledger-v1 行形状（仲裁 gen0 教训：夹具形状错=tailer 正确判 malformed）
    return ledger_row(project, ticket, seq, "implement", stage="implement")


def main():
    h = Harness()
    h.start()
    try:
        h.cmd("session_face_set", pending=[])
        h.cmd("start", project="p1", config=h.fixture_config("p1"),
              now="2026-09-28T10:00:00+08:00")

        # A 心跳显式且随 tick 前进
        hb1 = h.cmd("status", project="p1")["status"]["heartbeat"]
        ok("last_beat" in hb1 and "age_seconds" in hb1 and "alive" in hb1,
           "A 心跳三件在位", hb1)
        h.cmd("tick", seconds=10)
        hb2 = h.cmd("status", project="p1")["status"]["heartbeat"]
        ok(hb2["age_seconds"] >= hb1["age_seconds"], "A 心跳随注入时钟前进", (hb1, hb2))

        # B 引擎存活显式：探针桩在位=online 可答；桩故障=显式 down
        eng = h.cmd("status", project="p1")["status"]["liveness"]["engine"]
        ok("online" in eng and "checked_at" in eng, "B 引擎存活显式带时间戳", eng)
        h.cmd("engine_fail", on=True)
        h.cmd("tick", seconds=5)
        eng = h.cmd("status", project="p1")["status"]["liveness"]["engine"]
        ok(eng.get("online") is False and bool(eng.get("detail")),
           "B 探针故障=显式 down+detail（不假绿）", eng)
        h.cmd("engine_fail", on=False)

        # C 进展驱动停摆：有账本新行=有进展，超 15min 也不报 stalled
        h.cmd("append_ledger", project="p1", row=row("p1", "t-1", 1))
        h.cmd("tick", seconds=16 * 60)
        ex = h.cmd("status", project="p1")["status"]["liveness"]["executor"]
        ok(ex.get("state") != "stalled", "C 有进展信号不报 stalled（进展驱动非裸钟）", ex)

        # C2 停掉进展信号 → 推过阈值 → stalled 带证据与 last_progress_at
        h.cmd("session_progress", stop=True)
        h.cmd("tick", seconds=16 * 60)
        ex = h.cmd("status", project="p1")["status"]["liveness"]["executor"]
        ok(ex.get("state") == "stalled" and bool(ex.get("last_progress_at")),
           "C2 无信号过阈值=stalled 带 last_progress_at", ex)
        stall_alerts = [a for a in h.cmd("status", project="p1")["status"]["alerts"]
                        if "stall" in str(a.get("key", ""))]
        ok(bool(stall_alerts), "C2 停摆升级为 alert", stall_alerts)

        # D 自锁即时报：pending 的 approval 是执行器自己发的
        h.cmd("session_face_set",
              pending=[{"id": "ap-1", "raised_by_executor": True, "kind": "approval"}])
        h.cmd("tick", seconds=1)
        sl = h.cmd("status", project="p1")["status"]["self_lock"]
        ok(sl.get("state") == "waiting_on_itself", "D 自锁即时报（不等超时）", sl)
        ok(bool(sl.get("since")), "D 自锁状态带时间戳", sl)

        # E 待办面读不到=显式 unknown + reason，不冒充 none
        h.cmd("session_face_set", unreadable=True, reason="face probe stub down")
        h.cmd("tick", seconds=1)
        sl = h.cmd("status", project="p1")["status"]["self_lock"]
        ok(sl.get("state") == "unknown" and bool(sl.get("reason")),
           "E 读不到待办面=unknown+reason（绝不假 none）", sl)
        h.cmd("session_face_set", unreadable=False, pending=[])

        # F 墙钟大步前跳（休眠恢复）但有进展 → 不误报 stalled
        h.cmd("append_ledger", project="p1", row=row("p1", "t-1", 2))
        h.cmd("tick", seconds=3 * 3600)
        ex = h.cmd("status", project="p1")["status"]["liveness"]["executor"]
        ok(ex.get("state") != "stalled", "F 墙钟跳变但有进展不误报（休眠恢复形态）", ex)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
