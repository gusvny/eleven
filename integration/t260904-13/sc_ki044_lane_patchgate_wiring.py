#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-13 场景③：dev_lane UI 判定源接线与部署兼容结构（KI-044 编排面，灰盒 L3）。

intent（守护的用户可感知行为/合同）：
- 部署兼容承诺（用户可感知=挂起中的存量工单不因引擎升级而断）：dev_lane 主链 UI 判定
  换新 activity 前**必须**套 workflow.patched 兼容门——新实例走 diff 判定新路径，挂起中
  存量实例重放走旧布尔判定分支（命令序列与旧历史严格一致）。patch id 是历史标记键，
  **值一旦上线不可改**（改名=存量实例对新 id 无历史标记而误走新分支=重放断裂），
  本场景把值钉死为契约；
- 冻结承诺：旧链尾（仅存量重放可达的代码路径）不引入新 activity 命令——存量重放面
  恒定，给死代码加新命令=平白制造破面；
- 新路径接线完整：ui_changed_paths 的入参取 meta 的 worktree/branch/base_ref
  （泳道锚定三件套，缺一=activity 在错误仓上跑 diff）；
- 旧口径分支保留：patched 假分支保留 is_ui_write_set 布尔判定（存量重放走到该点时
  与旧历史命令序列一致）。

与相邻场景 intent 分界：sc_ki044_ui_diff_judgement 守判定源谓词/activity 回执、
sc_ki044_merge_gate_ui_item 守 merge_check 闸输出合同；本场景守 dev_lane **编排层**
patched 门结构（Temporal 历史确定性的部署承诺）。与 t260901-16 t05/t18（merge_check
diff base 各归各位）不同面；与 developer selfcheck（锁字面随实现重写、不作契约网）
不同深度——本场景锁 patch id 值、门结构顺序、冻结计数这些**不可随重构漂移**的约定。

temporalio 泳道不可用 → 源码契约结构锁（t260901-16 t05 同族落地形态），宽容正则
不锚行号。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import re
import sys

from lib_ki044 import REPO, summary

dl = (REPO / "server" / "dsh" / "temporal-poc" / "dev_lane.py").read_text("utf-8")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


# ---- W1 patch id 常量：值钉死（历史标记键，改名=存量实例重放断裂） ----
m1 = re.search(r'UI_DIFF_PATCH_ID\s*=\s*"(dev-lane-ui-diff-v1)"', dl)
check("W1 UI_DIFF_PATCH_ID 常量在场且值为 dev-lane-ui-diff-v1（值不可随重构改）",
      m1 is not None,
      "patch id 一旦上线即历史标记键，改名即破存量重放")

# ---- W2 主链兼容门结构：patched 门→新命令→旧口径分支并存 ----
pos = dl.find("workflow.patched(UI_DIFF_PATCH_ID)")
check("W2a 主链 patched(UI_DIFF_PATCH_ID) 门在场", pos >= 0)
if pos >= 0:
    tail = dl[pos:]
    check("W2b 门后接新命令 execute_activity(ui_changed_paths)（新实例路径）",
          re.search(r"execute_activity\(\s*ui_changed_paths\b", tail) is not None)
    check("W2c 门后保留旧口径布尔判定 is_ui_write_set（存量重放分支，命令序列与旧历史一致）",
          "is_ui_write_set(" in tail)
    check("W2d 新路径入参取 meta 泳道三件套（worktree/branch/base_ref）",
          all(k in tail[:4000] for k in ("worktree=", "branch=", "base_ref=")),
          "ui_changed_paths 入参缺泳道锚字段")
else:
    check("W2b 门后接新命令 execute_activity(ui_changed_paths)（新实例路径）", False)
    check("W2c 门后保留旧口径布尔判定 is_ui_write_set（存量重放分支，命令序列与旧历史一致）", False)
    check("W2d 新路径入参取 meta 泳道三件套（worktree/branch/base_ref）", False)

# ---- W3 冻结承诺：新 activity 命令在 dev_lane 全文恰出现一次（旧链尾不得引入） ----
calls = re.findall(r"execute_activity\(\s*ui_changed_paths\b", dl)
check("W3 ui_changed_paths 编排命令恰 1 处（主链新路径；旧链尾冻结不引入新命令）",
      len(calls) == 1, "出现 %d 处" % len(calls))

# ---- W4 门控顺序：patch 门定义先于新命令（防「无门裸调」与门后置漂移） ----
call = re.search(r"execute_activity\(\s*ui_changed_paths\b", dl)
gate = dl.find("workflow.patched(UI_DIFF_PATCH_ID)")
check("W4 patch 门先于新命令出现（门控形状：先定门、后发命令；不复用 UI_EVIDENCE_PATCH_ID"
      "——「已 patch 证据未 patch diff 源」的存量实例重放破面）",
      call is not None and gate >= 0 and gate < call.start(),
      "call=%s gate=%s" % (bool(call), gate))

sys.exit(summary(passed, failed))
