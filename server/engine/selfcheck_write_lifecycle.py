#!/usr/bin/env python3
"""selfcheck_write_lifecycle.py —— 写集生命周期 + 审读判据机械化自测（t260829-07）。

直跑：server/engine/.venv/bin/python selfcheck_write_lifecycle.py
（同 selfcheck_ui_acceptance 制式：shared 纯函数直测 + workflow/activity 侧源码锁；
agent_activities/dev_lane 依赖 temporalio，不在自测环境导入，相关行为用源码锁断言。）

覆盖（对应方案 v3 验收口径 1/3/4/5）：
  A. 建票写集校验 validate_write_set_args：
     空写集拒收（文案含两条出路）/ 空集+声明放行记 no_file_changes /
     非法条目拒收 / 非串与 None 容错 / 正常清单放行。
  B. 写集跟随方案 refresh_write_set：
     并集（不替换）/ 保序去重 / added 增量 / 畸形条目拒条不拒次（dropped）/
     空初始写集（方案定稿即建护栏）/ 全 None 容错 / 初始写集同样过滤。
  C. 机械复核判定 review_gate_verdict 三态互斥（报错精确性）：
     git 查询失败 → 跳过不打回（禁止断言「未落盘」）/ 真 0 commit → 打回 /
     no_file_changes 票 0 commit → 不打回 / 截图路径异常 → 跳过 /
     目录真 0 png + UI 票 → 打回 / 非 UI 票无 png → 不打回 / 正常 → 双空。
  D. TicketInput.no_file_changes 字段（默认 False 不破坏既有）。
  E. 源码锁：dev_lane 刷新门与机械闸插入点、patched 布尔门、agent_activities
     verify_review_gate 三态回执（git_error/-1 哨兵、路径不存在=0 png）与注册。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shared import (
    TicketInput,
    refresh_write_set,
    review_gate_verdict,
    validate_write_set_args,
)

PASS = 0
FAIL = 0


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title: str) -> None:
    print("\n%s" % title)


# ---------- A. 建票写集校验 ----------
section("A validate_write_set_args 建票校验")
okr, flags, err = validate_write_set_args([], False)
ok(not okr and flags == {}, "空写集且无声明 → 拒收")
ok("write_set" in err and "allow_empty_write_set" in err, "拒收文案含两条出路")
okr, flags, err = validate_write_set_args([], True)
ok(okr and flags.get("no_file_changes") is True and err == "", "空集+声明 → 放行并记 no_file_changes")
okr, flags, err = validate_write_set_args(["a/b.py"], False)
ok(okr and flags.get("no_file_changes") is False, "正常清单 → 放行")
okr, _, err = validate_write_set_args(["/abs/x.py"], False)
ok(not okr and "非法条目" in err, "绝对路径条目 → 拒收建票")
okr, _, err = validate_write_set_args(["../up.py"], False)
ok(not okr, "'..' 越界条目 → 拒收建票")
ok(validate_write_set_args(None, True)[0], "None 写集 + 声明 → 放行（容错）")
ok(not validate_write_set_args([None, 123], False)[0], "非串元素 → 拒收（建票口不静默清洗）")
ok(not validate_write_set_args(["  "], False)[0], "纯空白条目 → 拒收")
ok(validate_write_set_args(["  app/src/main.ts  "], False)[0], "首尾空白容忍")

# ---------- B. 写集跟随方案 ----------
section("B refresh_write_set 写集刷新")
merged, added, dropped = refresh_write_set(["a.py", "b.py"], ["b.py", "c.py", "d.py"])
ok(merged == ["a.py", "b.py", "c.py", "d.py"], "并集保序（初始在前）")
ok(added == ["c.py", "d.py"], "added = 方案新增")
ok(dropped == [], "合法输入无丢弃")
merged, added, dropped = refresh_write_set(["a.py"], ["a.py", "/bad", None, "../x", 42])
ok(merged == ["a.py"], "畸形条目不污染 merged（拒条不拒次）")
ok(dropped == ["/bad", "../x", "42"], "畸形条目进 dropped（None 静默略过）")
merged, added, dropped = refresh_write_set([], ["x.py", "x.py"])
ok(merged == ["x.py"] and added == ["x.py"], "空初始写集：方案定稿即建护栏（去重）")
ok(refresh_write_set(None, None) == ([], [], []), "全 None 容错")
merged, _, _ = refresh_write_set([" p.py ", "q.py"], ["p.py"])
ok(merged == ["p.py", "q.py"], "strip 归一去重")
merged, _, _ = refresh_write_set(["/initial-bad"], ["ok.py"])
ok(merged == ["ok.py"], "初始写集同样过滤（兜底）")

# ---------- C. 机械复核判定三态 ----------
section("C review_gate_verdict 机械复核三态（报错精确性）")
rework, note = review_gate_verdict("git rev-list 失败：boom", -1, "", -1, False, True)
ok(rework == "" and "git 查询失败" in note, "git 异常 → 跳过不打回（不断言「未落盘」）")
ok("未落盘" not in note, "git 异常文案不含「未落盘」断言")
rework, note = review_gate_verdict("", 0, "", 0, False, False)
ok(rework == "机械复核：实现未落盘（泳道 0 commit）", "真 0 commit → 打回「实现未落盘」")
rework, note = review_gate_verdict("", 0, "", 0, True, False)
ok(rework == "" and note == "", "no_file_changes 票 0 commit → 不打回")
rework, note = review_gate_verdict("", 3, "screenshots 是文件", -1, False, True)
ok(rework == "" and "截图路径异常" in note, "截图路径异常 → 跳过（不说「证据缺失」）")
rework, note = review_gate_verdict("", 3, "", 0, False, True)
ok(rework == "机械复核：UI 证据缺失（screenshots 无 png）", "目录真 0 png + UI 票 → 打回")
rework, _ = review_gate_verdict("", 3, "", 0, False, False)
ok(rework == "", "非 UI 票无 png → 不打回")
rework, note = review_gate_verdict("", 3, "", 2, False, True)
ok(rework == "" and note == "", "正常（有 commit 有图）→ 双空")
rework, note = review_gate_verdict("", 0, "", 5, False, False)
ok(rework == "机械复核：实现未落盘（泳道 0 commit）", "a 闸优先于 b 闸（0 commit 先拦）")

# ---------- D. TicketInput 字段 ----------
section("D TicketInput.no_file_changes")
inp = TicketInput(ticket_id="t", template_id="dev-lane")
ok(inp.no_file_changes is False, "默认 False（既有调用点不破坏）")
ok(TicketInput(ticket_id="t", template_id="dev-lane", no_file_changes=True).no_file_changes is True,
   "显式置真可透传")

# ---------- E. 源码锁 ----------
section("E 源码锁（workflow/activity 侧接线）")
dl = (Path(__file__).parent / "dev_lane.py").read_text(encoding="utf-8")
aa = (Path(__file__).parent / "agent_activities.py").read_text(encoding="utf-8")
ok('workflow.patched(REFRESH_WRITE_SET_PATCH_ID)' in dl, "写集刷新挂 patched 布尔门")
ok('workflow.patched(REVIEW_GATE_PATCH_ID)' in dl, "机械复核挂 patched 布尔门")
ok('REFRESH_WRITE_SET_PATCH_ID = "dev-lane-refresh-write-set"' in dl
   and 'REVIEW_GATE_PATCH_ID = "dev-lane-review-gate"' in dl, "两个新 PATCH_ID 声明")
ok('PATCH_ID = "dev-lane-v1"' in dl, "不 bump 既有 DevLaneWorkflow.PATCH_ID")
ok('review_gate_verdict(' in dl and 'refresh_write_set(' in dl, "dev_lane 调用两个纯函数")
ok('(self.results.get("create_plan") or {}).get("files_changed")' in dl,
   "写集刷新数据源 = create_plan 回执 files_changed")
ok('写集刷新跳过：create_plan 回执无 files_changed' in dl, "files_changed 缺失 → 跳过+留痕")
ok('授权扩展：+%s' in dl, "新增文件记 timeline「授权扩展」")
ok('"no_file_changes": bool(getattr(inp, "no_file_changes", False))' in dl, "meta 透传 no_file_changes")
ok("async def verify_review_gate" in aa, "verify_review_gate activity 已定义")
ok("res.png_count = -1" in aa, "路径异常 png_count=-1 哨兵（禁用 0 表达「查不了」）")
import dataclasses as _dc
_gd = {f.name: f.default for f in _dc.fields(__import__("shared").ReviewGateResult)}
ok(_gd.get("lane_commits") == -1 and _gd.get("png_count") == -1,
   "ReviewGateResult 默认 -1 哨兵（git 失败早退路径也非 0）")
ok("目录不存在 = 没拍，等价 0 png" in aa, "screenshots 不存在 = 等价 0 png")
ok("shots_path_error" in aa, "路径异常独立字段（与真 0 png 可区分）")
ok("verify_review_gate" in aa.split("ALL_AGENT_ACTIVITIES")[1], "verify_review_gate 已注册 worker")
ok("capture-lane.mjs" in aa, "prepare_ui_evidence 改跑 capture-lane（隔离台）")
ok("降级" in aa and "capture.mjs" in aa, "capture-lane 失败软降级回退 capture.mjs")
ok('validate_write_set_args' in (Path(__file__).parent / "client.py").read_text(encoding="utf-8"),
   "client.py 建票口接 validate_write_set_args")

print("\n结果：%d 绿 / %d 红" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
