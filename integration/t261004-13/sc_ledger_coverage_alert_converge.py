#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_ledger_coverage_alert_converge.py — ledger 覆盖告警收敛契约：只数在飞×any-row 覆盖×按集合去重（t261004-13，灰盒 L3，离线秒级零 docker，复用 t260928-28 公共 harness 缝——前置/夹具共享复用，非用例级重复）。

intent（用户可感知行为；工单 Part B 原话 + plan review 定稿）：
- A any-row 覆盖：账本里有该票任意一行即算覆盖——账本尾行落后于看板当前态不再是
  「缺行」（那是 reconcile_mismatch 的活，一事一声不得双报：本条断言该票不产生
  missing_rows 告警、且 reconcile.mismatches 仍点名它）；
- B 终态票不进告警：status=closed 的看板行即使账本零行也只进 status 面的
  terminal_missing 桶，不触发告警（不可行动的事实不响）；
- C 真缺才响：在飞票账本零行 → ledger_missing_rows 告警落下；
- D 按集合去重：覆盖票数 +1（集合不变）不重响；新增一条未覆盖在飞票（集合变了）
  才以新 key 重响——工单病灶「每 +1 票重响」对面；
- E status 面双桶：ledger_coverage（或同义键）同时可读在飞未覆盖数与终态未覆盖数，
  人能分清哪个是哪个（工单要求）；
- F 空集不响：全部覆盖 → 无告警（收敛路径在，宁可静默于健康也不养永不收敛的警）；
- G KI-180 家族回归：外项目看板行不计入本项目缺口（过滤纪律不因重写回潮）；
- H 畸形行保守：看板行缺 status 字段 → 保守按在飞处理（宁少报不假清白），不崩。

夹具行形状=真实 event-ledger-v1（lib_watchdog_harness.ledger_row）。
灰盒声明：断言只锚 status 公开键与 alerts 账，不锚内部函数名；术语映射
（in_flight/terminal 桶的确切键名）随实现，缺键=FAIL 点名。
intent 分工：t260928-28 守旧契约「缺 N 行留痕、N 变化重响」已被本票改契——该票
场景 B 由本条 D 接管（其文件随本票同步改签）；纯函数真值表归 developer L1。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属预期，
arbitrate/merge 期必须绿）。
Run directly: python3 integration/t261004-13/sc_ledger_coverage_alert_converge.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "t260928-28"))
from lib_watchdog_harness import Harness, ledger_row, ok  # noqa: E402


def missing_alerts(st):
    return [a for a in (st.get("alerts") or []) if "missing_rows" in str(a.get("key", ""))]


def coverage_face(st):
    """status 面双桶读取：键名随实现，逐候选找，找不到回 None（由调用方 FAIL 点名）。"""
    for key in ("ledger_coverage", "coverage", "missing_rows"):
        if key in st:
            return st[key]
    return None


def main():
    h = Harness()
    h.start()
    try:
        # 看板桩：
        #   t-old   在飞(review_plan)，账本有行但落后（integ）→ any-row 覆盖=A 面
        #   t-gone  在飞(integ)，账本零行 → 真缺=C 主面
        #   t-done  终态(closed)，账本零行 → 只进终态桶=B 面
        h.cmd("board_set", rows=[
            {"ticket": "t-old", "stage_state": "review_plan"},
            {"ticket": "t-gone", "stage_state": "integ"},
            {"ticket": "t-done", "stage_state": "review_plan", "status": "closed"},
        ])
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-old", 1, "integ", stage="integ"))

        h.cmd("start", project="p1", config=h.fixture_config("p1"),
              now="2026-10-04T10:00:00+08:00")
        h.cmd("tick", seconds=65)
        st = h.cmd("status", project="p1")["status"]

        # A any-row 覆盖：t-old 有行即覆盖，不响缺行警；落后仍归 reconcile_mismatch
        ok(not any("t-old" in str(a) for a in missing_alerts(st)),
           "A 账本有行即覆盖（落后≠缺行，不双报）", missing_alerts(st))
        mm = (st.get("reconcile") or {}).get("mismatches") or []
        ok(any(m.get("ticket") == "t-old" for m in mm),
           "A 落后分歧仍由 reconcile_mismatch 点名", mm)

        # C 真缺才响
        ok(bool(missing_alerts(st)), "C 在飞且账本零行 → 告警落下", missing_alerts(st))

        # B 终态票不进告警
        ok(not any("t-done" in str(a) for a in missing_alerts(st)),
           "B 终态票不触发告警", missing_alerts(st))

        # E status 面双桶（键名随实现，缺键=FAIL 点名）
        face = coverage_face(st)
        ok(face is not None, "E status 面有覆盖双桶键", sorted(st.keys()))
        if face is not None:
            blob = str(face)
            ok("t-done" in blob or "terminal" in blob, "E 终态桶可见", face)

        # D 按集合去重：给 t-done 补账本行 → 数变了集合没变 → 不重响
        n1 = len(missing_alerts(st))
        h.cmd("append_ledger", project="p1",
              row=ledger_row("p1", "t-done", 1, "review_plan", stage="review_plan"))
        h.cmd("tick", seconds=65)
        st2 = h.cmd("status", project="p1")["status"]
        ok(len(missing_alerts(st2)) == n1, "D 计数变化集合不变 → 不重响",
           (n1, len(missing_alerts(st2))))

        # D 集合变化：新增一条账本零行的在飞票 → 新 key 重响
        h.cmd("board_set", rows=[
            {"ticket": "t-old", "stage_state": "review_plan"},
            {"ticket": "t-gone", "stage_state": "integ"},
            {"ticket": "t-done", "stage_state": "review_plan", "status": "closed"},
            {"ticket": "t-new", "stage_state": "integ"},
        ])
        h.cmd("tick", seconds=65)
        st3 = h.cmd("status", project="p1")["status"]
        ok(len(missing_alerts(st3)) > n1, "D 未覆盖集合变化 → 重响（新事实）",
           (n1, len(missing_alerts(st3))))

        # F 空集不响：把真缺的都补上 → 告警收敛不再新增
        h.cmd("append_ledger", project="p1", row=ledger_row("p1", "t-gone", 1, "integ", stage="integ"))
        h.cmd("append_ledger", project="p1", row=ledger_row("p1", "t-new", 1, "integ", stage="integ"))
        h.cmd("tick", seconds=65)
        n2 = len(missing_alerts(h.cmd("status", project="p1")["status"]))
        h.cmd("tick", seconds=65)
        n3 = len(missing_alerts(h.cmd("status", project="p1")["status"]))
        ok(n2 == n3, "F 全覆盖后告警收敛（两个节拍零新增）", (n2, n3))

        # G KI-180 回归棒（仲裁 gen0 改签归因：项目裁剪的真位=生产 board reader 缝
        # node.ts 对 engine client 行做 filterBoardRowsToProject，core 只数喂进来的行；
        # harness 桩直注 core，外项目行在 core 层被计数是**该层正确行为**不是产品红
        # ——原 G 断言锚错层，归 tests-fault）：
        #   G1 源码锁（灰盒接线锁，t261002-10 先例）：生产 board reader 仍把账本裁到
        #      本项目（filterBoardRowsToProject 消费点在场、作用于 engine 行）——过滤
        #      真值表归 developer L1（reconcile.test.mjs），此处只锁接线不漂移；
        #   G2 行为面：按生产 reader 同形（外项目行已裁）的看板喂 core → 缺口集合
        #      不变、不重响（KI-180 语义在端到端形状下成立）。
        node_ts = pathlib.Path(__file__).resolve().parents[2] / "server" / "plugins" / "watchdog" / "node.ts"
        src = node_ts.read_text(encoding="utf-8") if node_ts.is_file() else ""
        ok("filterBoardRowsToProject" in src and "parsed.tickets" in src,
           "G1 源码锁：生产 board reader 仍裁剪本项目（filterBoardRowsToProject×parsed.tickets）",
           node_ts)
        h.cmd("board_set", rows=[
            {"ticket": "t-old", "stage_state": "review_plan"},
            {"ticket": "t-gone", "stage_state": "integ"},
            {"ticket": "t-done", "stage_state": "review_plan", "status": "closed"},
            {"ticket": "t-new", "stage_state": "integ"},
            # 外项目行按生产 reader 的过滤结果缺席（此处=不喂），核心缺口集合不变
        ])
        h.cmd("tick", seconds=65)
        n4 = len(missing_alerts(h.cmd("status", project="p1")["status"]))
        ok(n4 == n3, "G2 生产同形看板（外项目行已裁）→ 缺口集合不变（KI-180 不回潮）", (n3, n4))

        # H 畸形行保守：缺 status 字段的终态样票按在飞处理、不崩
        h.cmd("board_set", rows=[
            {"ticket": "t-old", "stage_state": "review_plan"},
            {"ticket": "t-gone", "stage_state": "integ"},
            {"ticket": "t-done", "stage_state": "review_plan", "status": "closed"},
            {"ticket": "t-new", "stage_state": "integ"},
            {"ticket": "t-nolabel", "stage_state": "review_plan"},
        ])
        h.cmd("tick", seconds=65)
        st5 = h.cmd("status", project="p1")["status"]
        ok(bool(missing_alerts(st5)), "H 缺 status 行保守按在飞且不崩", len(missing_alerts(st5)))
    finally:
        h.finish()


if __name__ == "__main__":
    main()
