#!/usr/bin/env python3
"""T05 合并闸口径接线锁：merge_check 四处 diff base 各归各位。

merge_check 是 Temporal activity（worktree 无 temporalio 环境跑不了整体），
本用例对其源码做结构断言，锁住 t260901-16 的接线约定：
  第 3 项 verify_lane 的 base 用当前 main 口径（不许再传建票钉死的 args.base_ref）；
  第 3.5 项 bundle_pairs diff 用 main...branch 三点；
  第 1 项「泳道有 commit」保持 base_ref..branch（防快进后误判 0 commit）。
  （t260904-13 KI-044 增第四处：3.6 UI 证据闸判定走 _ui_diff_paths 的
  <merge-base>...lane 三点 diff——由 selfcheck_ui_acceptance B 段源码锁与
  tests/test_ki044_ui_changed_paths.py 装配级用例把守，本文件不重复锁。）
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import REPO, summary

fails = []
src = (REPO / "server" / "engine" / "agent_activities.py").read_text("utf-8")
# t260907-06 票B 逐树重构：四门语义锚迁入 _merge_check_one_scope（merge_check 只剩
# 作用域循环+聚合）——本锁的定位范围随之覆盖两函数并集（锁语义不锁实现位置）。
_m1 = re.search(r"async def merge_check\(.*?\n(?=@activity\.defn|\Z)", src, re.S)
_m2 = re.search(r"async def _merge_check_one_scope\(.*?\n\n\ndef _scope_dirs", src, re.S)
if not (_m1 or _m2):
    fails.append("找不到 merge_check/核心函数体")
else:
    # t260921-09 三态化：第 1 项判定+差异面查询迁入 _lane_commits_check_item（base 仍取
    # sc["base_ref"]，语义锚不变）——本锁定位范围随之并入该函数（锁语义不锁实现位置）。
    _m3 = re.search(r"def _lane_commits_check_item\(.*?\n\n\nasync def _merge_check_one_scope", src, re.S)
    body = (_m1.group(0) if _m1 else "") + "\n" + (_m2.group(0) if _m2 else "") \
        + "\n" + (_m3.group(0) if _m3 else "")
    # 第 1 项：泳道有 commit，仍用 base_ref..branch（args 单仓 / sc 多仓 core / 辅助函数
    # 局部参数 base_ref 同义——t260921-09 后判定在辅助函数内，base 由调用点从 sc 注入）
    if not re.search(r'"%s\.\.%s" % \((args\.base_ref|sc\["base_ref"\]|base_ref), (args\.branch|sc\["branch"\]|branch)\)', body):
        fails.append("第1项「泳道有 commit」应保持 base_ref..branch（快进防误判）")
    # 第 1 项调用点完整性（t260921-09 三态化后新增）：辅助函数的 base 必须来自
    # sc["base_ref"]（票面钉死的 base，不回落 main——快进误判防线不撤）
    if not re.search(r'_lane_commits_check_item\(\s*str\(sc\.get\("base_ref"\) or ""\)', body):
        fails.append('第1项判定项调用点应传 sc["base_ref"]（t260921-09 三态化后防回落 main）')
    # 第 3 项：verify_lane 的 base 不再是 args.base_ref
    vm = re.search(r'"base":\s*([^,\n]+),\s*"require_base"', body)
    if not vm:
        fails.append("找不到 verify_lane 调用的 base 参数")
    elif "args.base_ref" in vm.group(1) or 'sc["base_ref"]' in vm.group(1):
        fails.append("第3项 verify_lane base 仍传 args.base_ref（假阳性根因未修）")
    elif not re.search(r'["\']main["\']|diff_base|wl_base', vm.group(1)):
        # wl_base = t260901-18 侧解法（merge-base(main, branch) sha，_merge_base_ref
        # 产出、fail-closed），随 main 并入本泳道——与本票字面 main + verify_lane
        # 三点口径是两层独立防线，任一单独回退都不复活假阳性，兼容并存
        fails.append("第3项 verify_lane base=%r，应为 main/wl_base 口径" % vm.group(1))
    # 第 3 项接线完整性（t260901-18 侧解法随合并带入）：base 须来自 _merge_base_ref
    # 且解析失败 fail-closed 红
    if "wl_base, wl_err = _merge_base_ref(" not in body:
        fails.append("第3项缺 _merge_base_ref 基线解析（t260901-18 fail-closed 口径）")
    if "写集白名单基线" not in body:
        fails.append("第3项缺 merge-base 失败红 item（fail-closed）")
    # 第 3.5 项：bundle_pairs 用 main...branch 三点
    if not re.search(r'git",\s*"diff",\s*"--name-only",\s*["\']main\.\.\.%s["\']\s*%\s*(args\.branch|sc\[.branch.\])', body):
        if not re.search(r"main\.\.\.%s['\"]\s*%\s*(args\.branch|sc\[.branch.\])", body):
            fails.append("第3.5项 bundle_pairs diff 应为 main...%s 三点口径")

for f in fails:
    print("FAIL:", f)
sys.exit(summary(0 if fails else 1, len(fails)))
