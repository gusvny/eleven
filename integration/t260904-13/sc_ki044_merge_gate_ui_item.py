#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-13 场景②：merge_check 3.6 UI 证据闸输出契约（KI-044 闸面，灰盒 L2）。

intent（守护的用户可感知行为/合同）：
- 3.6 闸判定源退役声明口径：merge_check 的 UI 截图项不再吃 is_ui_write_set(args.write_set)
  （KI-044：声明口径粒度越粗关卡越弱，t260904-05 全绿直过的根因面），换共享判定辅助
  _ui_diff_paths（与 ui_evidence 段同一源——定稿「两处调用同一源」的闸侧兑现）；
- 闸判定复用第 3 项已解析的泳道基线 wl_base（merge-base 锚泳道仓，不回落 main 字面
  ——t260901-18 假阳性教训不随本票回潮）；
- gate 记录留痕承诺：命中 UI 路径写进 check detail（「按 diff 判定：命中 N 个」形态，
  事后可查判定依据）；红灯处置指引（capture.mjs）不丢——截图缺失的用户出路仍在台面；
- diff 层故障 fail-closed：git 失败该项红并带错误信息，不存在静默跳过路径（KI-046
  同族「验证承诺静默蒸发」的堵洞面）；
- 回放兼容：MergeCheckArgs.write_set 字段保留（旧 RUNNING 实例历史回放不破 Args 形状）；
- 自测资产契约锁不失位：selfcheck 旧源码锁（锁 is_ui_write_set(args.write_set) 字面）
  必须随判定源退役，新判定源/patched 门锁在场——防「改了代码忘改锁」的假绿网。

与相邻场景 intent 分界：sc_ki044_ui_diff_judgement 守判定源谓词契约与 activity 回执
（真仓驱动），sc_ki044_lane_patchgate_wiring 守 dev_lane 编排接线；本场景守 merge_check
闸项输出合同（temporalio 泳道不可用 → 源码契约锁，t260901-16 t05 同族落地形态；
t05 锁 diff base 各归各位，本场景锁 UI 判定源与闸文案——不同面）。

实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import re
import sys

from lib_ki044 import REPO, summary

sys.path.insert(0, str(REPO / "server" / "dsh" / "temporal-poc"))
import shared  # noqa: E402

POC = REPO / "server" / "dsh" / "temporal-poc"
ag = (POC / "agent_activities.py").read_text("utf-8")
sc = (POC / "selfcheck_ui_acceptance.py").read_text("utf-8")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def gate36_section(src):
    """提取 merge_check 函数体 3.6 段（# 3.6 注释锚 → 下一个顶格编号注释锚）。"""
    m = re.search(r"async def merge_check\(.*?\n(?=@activity\.defn|\Z)", src, re.S)
    if not m:
        return ""
    body = m.group(0)
    g = re.search(r"# 3\.6 UI 证据闸.*?(?=\n    # 4\. |\n    # 4\.5 |\Z)", body, re.S)
    return g.group(0) if g else ""


sec36 = gate36_section(ag)

# ---- G0 夹具自检 ----
check("G0a 底座可判（merge_check 函数体提取成功）", "async def merge_check(" in ag)
check("G0b 3.6 段锚提取成功", "3.6" in sec36 or sec36 != "")
check("G0c 共享 dataclass 面 import 正常（MergeCheckArgs 可查）",
      hasattr(shared, "MergeCheckArgs"))

# ---- G1 判定源退役+换装 ----
check("G1a 3.6 段判定源走共享辅助 _ui_diff_paths（同源承诺闸侧兑现）",
      "_ui_diff_paths(" in sec36)
check("G1b 3.6 段不再以 is_ui_write_set(args.write_set) 为判定源（声明口径退役）",
      "is_ui_write_set(args.write_set)" not in sec36)

# ---- G2 基线复用 ----
check("G2 闸判定复用泳道基线 wl_base（merge-base 锚泳道仓不回落 main 字面）",
      "wl_base" in sec36)

# ---- G3 gate 记录留痕+红灯处置指引 ----
check("G3a 命中路径写进 check detail（按 diff 判定，事后可查）",
      "按 diff 判定" in sec36)
check("G3b 红灯处置指引保留（capture.mjs 出路仍在台面）",
      "capture.mjs" in sec36)

# ---- G4 diff 故障 fail-closed（红不静默）----
check("G4 git 层失败 → 该项红并带错误信息（无静默 SKIP 路径）",
      "err" in sec36 and ("green" in sec36 or "红" in sec36),
      "3.6 段缺 err→红 结构")

# ---- G5 回放兼容：Args.write_set 字段保留 ----
import dataclasses  # noqa: E402

fields5 = {f.name for f in dataclasses.fields(shared.MergeCheckArgs)}
check("G5 MergeCheckArgs.write_set 字段保留（旧实例历史回放不破形状）",
      "write_set" in fields5, "fields=%s" % sorted(fields5))

# ---- G6 自测资产契约锁不失位（防改码忘改锁的假绿网）----
check("G6a selfcheck 旧源码锁退役（is_ui_write_set(args.write_set) 字面锁移除）",
      '"is_ui_write_set(args.write_set)" in src' not in sc)
check("G6b selfcheck 新判定源锁在场（_ui_diff_paths 锁）",
      "_ui_diff_paths" in sc)
check("G6c selfcheck patched 门锁在场（UI_DIFF_PATCH_ID）",
      "UI_DIFF_PATCH_ID" in sc)

sys.exit(summary(passed, failed))
