#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-13 场景①：UI 票判定源 = 泳道实际 diff × UI 前缀表（KI-044 根治面，灰盒 L2）。

intent（守护的用户可感知行为/合同）：
- UI 票判定按**泳道分支实际 diff 路径**定，不按工单写集**声明条目**定（KI-044：
  t260904-05 声明整个 server/dsh/workbench/ 父目录、实际改会话区 UI → 旧声明口径
  前缀不命中 → 判「非 UI 票」→ 合并闸无截图项全绿直过。声明口径 ≠ 实际写面）；
- 三点口径：只看 merge-base(main,lane)...lane 泳道带来的改动，main 侧他人改 UI
  不算本票 UI 面（t260901-16 白名单基线承诺在 UI 判定面的兑现）；
- 混合票（引擎+UI 同票）只按 UI 前缀命中，不扩大不缩小；
- 对外谓词对脏输入（None/非列表/非字符串/绝对路径/含 ..）不抛、按未命中处理
  ——developer L1 畸形用例随实现重写不作契约网，本条是持久契约面；
- 修复面真实性对照（t260904-04 J0 先例）：旧声明口径对 t260904-05 形态确实漏判
  （夹具自检，实现回退则本对照仍绿、判定面红——修复面对照证明修复的票真实存在）；
- activity 接线结构锁（temporalio 泳道不可用，t260901-16 t05 同族落地形态）：
  ui_changed_paths activity 锚泳道仓 merge-base（不回落 main 字面）、走共享判定
  辅助、git 失败 fail-closed 回执（err 进 detail 不静默）、进 worker 注册清单。

与相邻场景 intent 分界：sc_ki044_merge_gate_ui_item 守 merge_check 3.6 闸输出契约
（出不出项/红绿/文案），sc_ki044_lane_patchgate_wiring 守 dev_lane 编排接线与部署
兼容结构；本场景守「判定源本身」的谓词契约与 activity 回执合同。与 developer L1
（temporal-poc/tests/test_ki044_ui_changed_paths.py 纯函数白盒）intent 不同面：
本场景用真 git 仓 merge-base 三点 diff 驱动（L1 禁真 git），锚定稿口径承诺不锚内部实现。

实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import shutil
import sys

from lib_ki044 import REPO, build_lane_repo, summary

sys.path.insert(0, str(REPO / "server" / "dsh" / "temporal-poc"))
import shared  # noqa: E402  纯标准库依赖面，系统 python3 可 import

AG = REPO / "server" / "dsh" / "temporal-poc" / "agent_activities.py"

# 泳道本票改动（t260904-05 实证形态：实际改会话区 UI 产物+顺手改引擎）
LANE_FILES = {
    "server/dsh/workbench/lib/workbench.js": "// rebuilt bundle\n",
    "server/dsh/temporal-poc/shared.py": "# engine tweak\n",
}
# main 侧他人改动（泳道之外 UI 面）
MAIN_FILES = {
    "server/dsh/workbench/src/client/App.tsx": "// others' ui change\n",
}
UI_PROD = "server/dsh/workbench/lib/workbench.js"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def match_ui(paths):
    """被测承诺面（实现落地前 hasattr=False 由调用方转为 FAIL 而非崩）。"""
    return shared.match_ui_paths(paths) if hasattr(shared, "match_ui_paths") else None


# ---- J0 夹具自检 + 修复面真实性对照 ----
tmp, mb, diff_paths = build_lane_repo(LANE_FILES, MAIN_FILES)
try:
    check("J0a 三点 diff 只含泳道改动（夹具自证）",
          UI_PROD in diff_paths
          and "server/dsh/workbench/src/client/App.tsx" not in diff_paths,
          "diff=%s" % diff_paths)
    check("J0b 修复面对照：旧声明口径对 t260904-05 形态漏判（粗目录声明不命中）",
          shared.is_ui_write_set(["server/dsh/workbench/"]) is False)
    check("J0c 被测承诺面在场（shared.match_ui_paths）",
          hasattr(shared, "match_ui_paths"),
          "实现未落地（落地前红属预期）")
    # ---- J1 根治面：粗声明票按实际 diff 命中 ----
    got = match_ui(diff_paths)
    check("J1 实际 diff 的 UI 路径命中（UI 产物在列、引擎文件不在）",
          got is not None and got == [UI_PROD], "got=%r" % (got,))
    # ---- J2 纯引擎票不误伤 ----
    _, _, engine_diff = build_lane_repo({"server/dsh/temporal-poc/dev_lane.py": "x\n"})
    try:
        got2 = match_ui(engine_diff)
        check("J2 纯引擎 diff → 空清单（不出截图项面）",
              got2 is not None and got2 == [], "got=%r" % (got2,))
    finally:
        shutil.rmtree(engine_diff[0], ignore_errors=True)
    # ---- J3 声明 UI 但实际无 UI diff：按实际不按声明 ----
    _, _, no_ui_diff = build_lane_repo({"server/dsh/temporal-poc/shared.py": "y\n"})
    try:
        check("J3a 对照声明口径：app/src/main.tsx 声明确实命中旧谓词（两口径真实分叉）",
              shared.is_ui_write_set(["app/src/main.tsx"]) is True)
        got3 = match_ui(no_ui_diff)
        check("J3b 声明命中≠实际命中：diff 无 UI 路径 → 判定源为空（防 or 逻辑）",
              got3 is not None and got3 == [], "got=%r" % (got3,))
    finally:
        shutil.rmtree(no_ui_diff[0], ignore_errors=True)
    # ---- J4 三点口径：main 侧他人改 UI 不算本票面 ----
    got4 = match_ui(diff_paths)
    check("J4 main 侧他人 UI 改动不在判定结果（泳道带来的才算）",
          got4 is not None
          and all("src/client/App.tsx" not in p for p in got4),
          "got=%r" % (got4,))
    # ---- J5 混合票只含 UI 路径 ----
    check("J5 混合票命中只含 UI 前缀路径（引擎文件被过滤）",
          got is not None and all(p.startswith(("server/dsh/workbench/",
                                                "server/dsh/providers/src/client/",
                                                "app/src/", "app/index.html"))
                                  for p in got),
          "got=%r" % (got,))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- J6 脏输入契约：不抛、按未命中处理 ----
for label, dirty in [
    ("None", None),
    ("非列表标量", 42),
    ("含非字符串元素", [None, 123, UI_PROD]),
    ("绝对路径", ["/etc/passwd"]),
    ("含 ..", ["server/../server/dsh/workbench/lib/workbench.js"]),
    ("空串元素", [""]),
]:
    try:
        got6 = match_ui(dirty)
        ok6 = isinstance(got6, list)  # None/非列表 → 空；其余按未命中过滤
        check("J6 脏输入不抛按未命中：%s" % label, ok6, "got=%r" % (got6,))
    except Exception as e:  # 契约：对脏输入不炸
        check("J6 脏输入不抛按未命中：%s" % label, False, "%s: %s" % (type(e).__name__, e))

# ---- A1 activity 接线结构锁（temporalio 不可用 → 源码契约锁，t05 同族） ----
ag = AG.read_text("utf-8")
check("A1a ui_changed_paths activity 已定义（@activity.defn）",
      "@activity.defn" in ag and "async def ui_changed_paths(" in ag)
check("A1b 锚泳道仓 merge-base（_merge_base_ref，不回落 main 字面）",
      "async def ui_changed_paths(" in ag
      and "_merge_base_ref(" in ag.split("async def ui_changed_paths(", 1)[-1]
      .split("@activity.defn", 1)[0])
check("A1c 走共享判定辅助 _ui_diff_paths（两处同源的单点入口）",
      "def _ui_diff_paths(" in ag)
check("A1d git 失败 fail-closed 回执（err 进 detail，不静默空）",
      "async def ui_changed_paths(" in ag
      and "err" in ag.split("async def ui_changed_paths(", 1)[-1]
      .split("@activity.defn", 1)[0]
      and "detail" in ag.split("async def ui_changed_paths(", 1)[-1]
      .split("@activity.defn", 1)[0])
check("A1e 已进 worker 注册清单 ALL_AGENT_ACTIVITIES（漏=运行时才断）",
      "ui_changed_paths" in ag.split("ALL_AGENT_ACTIVITIES", 1)[-1])

sys.exit(summary(passed, failed))
