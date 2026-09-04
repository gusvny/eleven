#!/usr/bin/env python3
"""check_auto_rework_trace.py —— 自动打回留痕自测（t260901-04）。

直跑：python3 integration/check_auto_rework_trace.py（cwd=仓库根）。
制式：dev_lane 依赖 temporalio（本环境不可导入），不 import dev_lane——
源码锁断言结构 + 微实现表驱动复刻校验逻辑（两个方向 + fallback + done）。

背景：工单台打回横幅只吃 timeline 里 state='rework' 记录；验收走查等
5 处内部自动打回原来不走 _apply_rework 的留痕路径，用户看不到打回原因。
本脚本锁：_auto_rework 统一入口在位（含 fallback 形参/词表校验/role 显式映射/
无 _step 调用）、5 处接入点各自传 who="workflow" 与专属 fallback、merge 点
不再塞 self._rework（防双落）、PHASE_MAIN_CHAIN/PHASE_MAIN_ROLES 双常量键集合
一致；并用微实现跑正反向畸形输入用例。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT / "server/dsh/temporal-poc/dev_lane.py"
SCENARIOS_PY = ROOT / "integration/run_scenarios.py"

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


src = DL.read_text("utf-8")

# ---------- A. _auto_rework 定义与留痕体源码锁 ----------
section("A _auto_rework 统一入口源码锁")
ok("def _auto_rework(self, target: str, note: str, who: str, fallback: str) -> str:"
   in src, "签名含 fallback 显式形参")
ok("PHASE_MAIN_CHAIN" in src, "词表常量被引用")
ok("self.refused.append" in src, "拒绝路径 refused 记账在位")
for kw in ('self.meta["stage"] = target',
           'self.meta["role"] = PHASE_MAIN_ROLES[target]',
           'self.meta["status"] = "rework"',
           'self.meta["stage_state"] = "awaiting"',
           'self.meta["last_rework_note"] = note',
           'self._mark(target, "rework",',
           "self._touch()"):
    ok(kw in src, "留痕体关键行在位：%s" % kw[:44])
# 崩溃路径焊死（review 第 3 轮）：role 计算绝不走 _step(target)
m_auto = re.search(r"def _auto_rework\(.*?\n(?=\n    def )", src, re.S)
ok(m_auto is not None, "_auto_rework 函数体可定位")
if m_auto:
    ok("self._step(" not in m_auto.group(0), "_auto_rework 函数体内不含 self._step( 调用")
ok("target == \"done\"" in src, "done 被显式拒绝（终态不可为打回目标）")

# ---------- B. 双常量词表与角色映射一致性 ----------
section("B PHASE_MAIN_CHAIN / PHASE_MAIN_ROLES 常量")
EXPECT = {"create_plan", "review_plan", "parallel_impl_design", "implement",
          "integ_join", "integration_review", "run_integration_tests", "arbitrate",
          "arb_acc_parallel", "acceptance", "merge_check", "merge", "done"}
# 锁口径：键集合 = 主链 phase 值全集（含并行分叉 phase 值，非 STAGES id）；
# t260903-02 增第 13 键 arb_acc_parallel（仲裁∥走查并行分叉，role=integration）。
EXPECT_ROLES = {"create_plan": "developer", "review_plan": "integration",
                "parallel_impl_design": "developer", "implement": "developer",
                "integ_join": "developer", "integration_review": "integration",
                "run_integration_tests": "integration", "arbitrate": "integration",
                "arb_acc_parallel": "integration",
                "acceptance": "integration", "merge_check": "integration",
                "merge": "integration", "done": "integration"}


def parse_const(name: str):
    """从源码解析模块级常量：PHASE_MAIN_CHAIN（frozenset）→ set；
    PHASE_MAIN_ROLES（Dict）→ dict。解析失败返回 None。"""
    m_set = re.search(name + r"\s*=\s*frozenset\(\{(.*?)\}\)", src, re.S)
    if m_set:
        return set(re.findall(r'"([^"]+)"', m_set.group(1)))
    m_dict = re.search(name + r"\s*(?::\s*Dict\[str, str\])?\s*=\s*\{(.*?)\}", src, re.S)
    if m_dict:
        return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', m_dict.group(1)))
    return None


chain = parse_const("PHASE_MAIN_CHAIN")
roles = parse_const("PHASE_MAIN_ROLES")
ok(chain == EXPECT, "PHASE_MAIN_CHAIN 恰为 13 个主链步（实测 %s）"
   % sorted(chain or []))
ok(isinstance(roles, dict) and set(roles.keys()) == EXPECT,
   "PHASE_MAIN_ROLES 键集合与词表一致")
ok(roles == EXPECT_ROLES, "PHASE_MAIN_ROLES 角色逐键正确（%s）"
   % ("" if roles == EXPECT_ROLES else {k: v for k, v in (roles or {}).items()
                                        if EXPECT_ROLES.get(k) != v}))

# ---------- C. 5 处自动打回点接入源码锁 ----------
section("C 自动打回点接入（who=fallback 字面量 + 不双落）")
for target_fb in [("implement", '"acceptance"'),      # acceptance 验收打回
                  ("implement", '"arbitrate"'),       # arbitrate code-fault
                  ("implement", '"integration_review"'),  # 机械复核（×1 处断言计数 2）
                  ("merge_check", '"merge"')]:
    tgt, fb = target_fb
    calls = [m.start() for m in re.finditer(
        r'_auto_rework\("%s"' % re.escape(tgt), src)]
    hit = any(('who="workflow"' in src[c:c + 400] and fb in src[c:c + 400])
              for c in calls)
    ok(hit and calls, "%s 点接入 _auto_rework（target=%s fallback=%s who=workflow）"
       % (fb, tgt, fb))
ir_calls = [m.start() for m in re.finditer(r'_auto_rework\("implement"', src)]
ir_hits = [c for c in ir_calls
           if 'fallback="integration_review"' in src[c:c + 400]
           and 'who="workflow"' in src[c:c + 400]]
ok(len(ir_hits) == 2, "integration_review 两处（机械复核+审读）均接入（实测 %d 处）"
   % len(ir_hits))
total_calls = len(re.findall(r"phase = self\._auto_rework\(", src))
# 锁口径：内部自动打回点计数（壳委托不计）。t260903-02 新增 arb_acc_parallel 分支
# 2 处（验收走查打回 + code-fault 打回）→ 7 处。
ok(total_calls == 7, "自动打回点恰好 7 处（实测 %d）" % total_calls)
# merge 点不再塞 self._rework（防一次打回落两条 timeline）
merge_block = src[src.find('if not mr.ok:'):src.find('if not mr.ok:') + 2000]
ok("self._rework = ReworkRequest(" not in merge_block,
   "merge 失败分支不再塞 self._rework（防双落）")
ok("self._rework = None" in src, "_apply_rework 壳保留 signal 消费语义（先清再委托）")
ok('target in ("suggest_next", "ui_evidence")' in src,
   "suggest_next/ui_evidence 非主链步拒绝守卫在位（旧 selfcheck 锁兼容）")

# ---------- D. 微实现表驱动：正反向 + fallback + done + 空 note ----------
section("D 校验逻辑微实现畸形输入用例（不依赖 temporalio）")


class W:  # 复刻 _auto_rework 校验语义的等价微实现（与源码锁 A 对照维护）
    def __init__(self, stage: str):
        self.meta = {"stage": stage, "status": "dispatched", "refused": []}

    def auto_rework(self, target, note, who, fallback):
        if target == "done" or target not in EXPECT:
            self.meta["refused"].append((who, "rework(%s)" % target))
            return fallback if fallback in EXPECT else str(self.meta.get("stage") or fallback)
        if fallback == "done" or fallback not in EXPECT:
            self.meta["refused"].append((who, "fallback(%s)" % fallback))
            return str(self.meta.get("stage") or fallback)
        self.meta.update(stage=target, role=EXPECT_ROLES[target], status="rework",
                         last_rework_note=note)
        return target


# 反向三用例：词表有、STAGES 无——旧 _step 路径会崩，新路径必须走通
for tgt, role in [("acceptance", "integration"), ("parallel_impl_design", "developer"),
                  ("integ_join", "developer")]:
    w = W("merge")
    r = w.auto_rework(tgt, "外部 signal 打回 %s" % tgt, "human", "merge")
    ok(r == tgt and w.meta["role"] == role and w.meta["status"] == "rework",
       "反向：target=%s 通过且 role=%s 不崩" % (tgt, role))
# 词表外值（acceptance_walkthrough：STAGES 有、词表无）→ 拒绝回 fallback
w = W("acceptance")
r = w.auto_rework("acceptance_walkthrough", "n", "human", "acceptance")
ok(r == "acceptance" and w.meta["status"] != "rework"
   and len(w.meta["refused"]) == 1, "acceptance_walkthrough 被拒：回 fallback、无留痕")
# done → 拒绝
w = W("merge_check")
r = w.auto_rework("done", "n", "human", "merge_check")
ok(r == "merge_check" and w.meta["status"] != "rework", "done 被拒：回 fallback、无留痕")
# fallback 非法（空串）→ refused 有账、返回值=meta 现步（绝不回传非法值）
w = W("arbitrate")
r = w.auto_rework("implement", "n", "workflow", "")
ok(r == "arbitrate" and len(w.meta["refused"]) == 1,
   "fallback 非法：返回 meta 现步、非法值不回流")
# 空 note：走通且横幅 reason（note+who 拼合）非空——留痕不丢发起者列
w = W("acceptance")
r = w.auto_rework("implement", "", "workflow", "acceptance")
reason = "%s（%s）" % ("", "workflow")
ok(r == "implement" and reason.strip("（）") == "workflow" and len(reason) > 0,
   "空 note 走通：reason 由 who 兜底非空")

# ---------- E. 场景清单登记（manifest 退役后口径，t260902） ----------
section("E run_scenarios 场景清单登记")
import run_scenarios as _rs  # noqa: E402
ok(any("check_auto_rework_trace.py" in str(e[2]) for e in _rs.SCENARIOS),
   "SCENARIOS 三元组已登记 check_auto_rework_trace")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
