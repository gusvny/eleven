#!/usr/bin/env python3
"""M6 自测（t260821-m6-scan-expand）：巡检扩权纯逻辑 + 报告落盘，**零碰真实工单**。

覆盖（全部离线，不需要 Temporal server / worker）：
  A. is_pending_decision 过滤口径（settled / awaiting-human 进；closed / running 出）；
  B. build_scan_item 建议规则：人门→可签 / 验收未齐→待补 / 脚本门红→待补 /
     全勾+绿→可签 / 停留超阈→疑似卡死（含人门久候）/ 停留取 max(updated,log,pending)；
  C. gate_from_log 兜底（log 里「脚本门…红灯」→绿=False）；
  D. scan_tickets_report_impl（假 list/show/gate 通道）：过滤+排序+summary；
     未归档清单（epic-linkage）：无 epic 的在途工单进清单，有 epic / closed 不进；
  E. write_scan_report（ActivityEnvironment 真跑 activity）：落盘 <日期>.json、
     红线声明在报告里、同日重跑覆盖单文件、unfiled 清单落盘带出。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

POC = Path(__file__).resolve().parent

# ---- 0) 临时目录（必须先于 shared import 设 env）----
TMP = Path(tempfile.mkdtemp(prefix="sandbar-selfcheck-m6-"))
os.environ["SANDBAR_SCAN_DIR"] = str(TMP / "scan")

from temporalio.testing import ActivityEnvironment  # noqa: E402

from activities import scan_tickets_report_impl, write_scan_report  # noqa: E402
from shared import (  # noqa: E402
    SCAN_RED_LINE,
    ScanReport,
    build_scan_item,
    gate_from_log,
    is_pending_decision,
    scan_summary,
)

from selfcheck_common import Selfcheck  # noqa: E402  t261001-04：ok/section 收敛到唯一定义，输出格式逐字不变

_rep = Selfcheck(track_failures=True, section_fmt="\n== %s")
ok = _rep.ok
section = _rep.section


NOW = 1_800_000_000  # 固定参照时间（自测不依赖 wall-clock）


def tk(**kw) -> dict:
    base = {"id": "t-x", "title": "测试工单", "status": "settled", "stage": "verify",
            "stage_state": "awaiting", "updated": NOW - 3600, "acceptance": [],
            "checks": {}, "pending": [], "log": []}
    base.update(kw)
    return base


# ---- A. 过滤口径 ----
section("A is_pending_decision 过滤口径")
ok(is_pending_decision(tk(status="settled")) is True, "settled → 待决")
ok(is_pending_decision(tk(status="rework", stage_state="awaiting-human")) is True,
   "rework+awaiting-human → 待决（人门不论 status）")
ok(is_pending_decision(tk(status="closed", stage_state="awaiting-human")) is False,
   "closed 一律出（即使 stage_state 残留 awaiting-human）")
ok(is_pending_decision(tk(status="dispatched", stage_state="running")) is False,
   "running 在跑 → 不出（不打扰）")
ok(is_pending_decision(tk(status="verified", stage_state="awaiting")) is False,
   "verified/awaiting（段间待命）→ 不出")

# ---- B. 建议规则 ----
section("B build_scan_item 建议规则")

it = build_scan_item(tk(status="rework", stage="final-review", stage_state="awaiting-human",
                        pending=[{"ts": NOW - 600, "note": "待审批"}]),
                     now_ts=NOW)
ok(it.suggestion == "可签" and any("人门" in r for r in it.reasons), "人门挂起 → 可签")
ok(it.pending_count == 1 and any("pending" in r for r in it.reasons), "pending 条数进条目")

it = build_scan_item(tk(acceptance=["a", "b", "c"],
                        checks={"verify": [{"item": "a", "done": True}, {"item": "b", "done": False}]}),
                     now_ts=NOW)
ok(it.suggestion == "待补" and it.acceptance_done == 1 and it.acceptance_total == 3,
   "验收 1/3 未齐 → 待补")
ok(any("1/3" in r for r in it.reasons), "待补理由带勾选率")

it = build_scan_item(tk(acceptance=["a"], checks={"verify": [{"item": "a", "done": True}]}),
                     gate_label="verify_lane code", gate_green=False, now_ts=NOW)
ok(it.suggestion == "待补" and any("红灯" in r for r in it.reasons), "脚本门红 → 待补")

it = build_scan_item(tk(acceptance=["a"], checks={"verify": [{"item": "a", "done": True}]}),
                     gate_label="verify_lane code", gate_green=True, now_ts=NOW)
ok(it.suggestion == "可签" and any("绿灯" in r for r in it.reasons), "验收全勾+脚本门绿 → 可签")

it = build_scan_item(tk(), now_ts=NOW)
ok(it.suggestion == "可签" and any("无验收清单" in r for r in it.reasons),
   "settled 无验收清单 → 可签（可验收收口）")

it = build_scan_item(tk(acceptance=["a"],
                        checks={"verify": [{"item": "a", "done": False},
                                           {"item": "孤儿旧记录", "done": True}]}),
                     now_ts=NOW)
ok(it.acceptance_done == 0 and it.acceptance_total == 1 and it.suggestion == "待补",
   "孤儿 check（item 不在验收清单）不计入勾选率")

it = build_scan_item(tk(status="rework", stage_state="awaiting-human",
                        updated=NOW - 50 * 3600),
                     now_ts=NOW, stuck_hours=48)
ok(it.suggestion == "疑似卡死" and abs(it.dwell_hours - 50.0) < 0.05,
   "停留 50h ≥ 48h → 疑似卡死（人门久候也算）")
ok(it.dwell_hours == 50.0, "停留时长=updated 起算 50.0h")

it = build_scan_item(tk(updated=NOW - 100 * 3600,
                        log=[{"ts": NOW - 2 * 3600, "note": "投影刷新"}],
                        pending=[{"ts": NOW - 10 * 3600, "note": "x"}]),
                     now_ts=NOW, stuck_hours=48)
ok(abs(it.dwell_hours - 2.0) < 0.05, "停留取 max(updated/log/pending)=2.0h → 不判卡死")

# ---- C. gate_from_log 兜底 ----
section("C gate_from_log 兜底")
g = gate_from_log(tk(log=[{"ts": 1, "note": "脚本门 verify_lane code 红灯 2 项 → 不推进"}]))
ok(g["green"] is False and g["source"] == "log", "log 红灯记录 → green=False")
g = gate_from_log(tk(log=[{"ts": 1, "note": "advance: develop → verify（handoff 已记）"}]))
ok(g["green"] is None and g["source"] == "无脚本门记录", "无脚本门记录 → None")

# ---- D+E. 同一事件循环内跑（python3.9 的 asyncio.run 关循环后 Event 拿不到 loop）----


async def _impl_case() -> ScanReport:
    tickets = [
        {"id": "t-closed", "status": "closed", "stage_state": "awaiting", "title": "关"},
        {"id": "t-running", "status": "dispatched", "stage_state": "running", "title": "跑",
         "epic": "epic-linkage"},
        {"id": "t-stuck", "status": "settled", "stage_state": "awaiting", "title": "卡"},
        {"id": "t-human", "status": "rework", "stage_state": "awaiting-human", "title": "签",
         "epic": "epic-linkage"},
        {"id": "t-fill", "status": "settled", "stage_state": "awaiting", "title": "补"},
    ]
    shows = {
        "t-stuck": {"ok": True, "result": tk(id="t-stuck", updated=NOW - 99 * 3600)},
        "t-human": {"ok": True, "result": tk(id="t-human", status="rework",
                                             stage_state="awaiting-human")},
        "t-fill": {"ok": True, "result": tk(id="t-fill", acceptance=["a"],
                                            checks={"verify": [{"item": "a", "done": False}]})},
    }

    async def list_fn():
        return {"ok": True, "result": {"tickets": tickets}}

    async def show_fn(tid):
        return shows[tid]

    async def gate_fn(tid):
        return {"label": "", "green": None, "source": "temporal 不可达（test）"}

    return await scan_tickets_report_impl(NOW, 48.0, list_fn, show_fn, gate_fn)


# ---- D+E. 同一事件循环内跑（python3.9 的 asyncio.run 关循环后 Event 拿不到 loop）----
async def _async_checks() -> ScanReport:
    rep = await _impl_case()
    section("D scan_tickets_report_impl 过滤+排序+summary")
    ok(rep.total_tickets == 5 and rep.by_status.get("closed") == 1, "总数与分布统计保留")
    ok([i.ticket_id for i in rep.items] == ["t-stuck", "t-fill", "t-human"],
       "过滤 closed/running + 排序 疑似卡死→待补→可签")
    ok(rep.summary == {"疑似卡死": 1, "待补": 1, "可签": 1}, "summary 三档计数")
    ok("脚本门" in "".join(rep.items[0].reasons),
       "temporal 不可达 → log 兜底理由进条目")
    # 未归档清单（epic-linkage 验收标准 3）：无 epic 的在途工单进清单
    ok(rep.unfiled == ["t-fill", "t-stuck"],
       "未归档清单：无 epic 在途工单进清单（sorted，实际 %s）" % rep.unfiled)
    ok("t-running" not in rep.unfiled and "t-human" not in rep.unfiled,
       "有 epic 的工单不进未归档清单（在跑/待决同口径）")
    ok("t-closed" not in rep.unfiled, "closed 工单不进未归档清单（历史不增殖噪音）")

    section("E write_scan_report 落盘（ActivityEnvironment 真跑 activity）")
    env = ActivityEnvironment()
    written = await env.run(write_scan_report, rep)
    path = Path(written["path"])
    expect_name = time.strftime("%Y-%m-%d", time.localtime()) + ".json"
    ok(path.name == expect_name and path.parent == TMP / "scan",
       "落盘 <日期>.json 于 SANDBAR_SCAN_DIR")
    ok(path.exists() and written["bytes"] > 0, "文件非空")
    data = json.loads(path.read_text("utf-8"))
    ok(data["red_line"] == SCAN_RED_LINE, "红线声明落进报告")
    ok(data["pending_decision_count"] == 3 and len(data["items"]) == 3, "items 全量落盘")
    ok(data["items"][0]["ticket_id"] == "t-stuck"
       and data["items"][0]["suggestion"] == "疑似卡死", "首条=疑似卡死（排序落盘一致）")
    ok(isinstance(data["items"][0]["dwell_hours"], float), "停留时长字段在")
    ok(data.get("unfiled") == rep.unfiled == ["t-fill", "t-stuck"],
       "未归档清单随报告落盘（unfiled 键，值与内存一致）")
    written2 = await env.run(write_scan_report, rep)
    ok(len(list((TMP / "scan").glob("*.json"))) == 1 and written2["file"] == written["file"],
       "同日重跑覆盖单文件（不增殖）")
    return rep


asyncio.run(_async_checks())

print("\n%d passed, %d failed" % (_rep.passes, _rep.fails))
if _rep.failures:
    print("_rep.failures:", file=sys.stderr)
    for f in _rep.failures:
        print("  - %s" % f, file=sys.stderr)
sys.exit(0 if _rep.fails == 0 else 1)
