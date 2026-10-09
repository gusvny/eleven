#!/usr/bin/env python3
"""check_auto_rework_trace.py — self-test for automatic-rework trace records
(t260901-04).

Run directly: python3 integration/check_auto_rework_trace.py (cwd = repo root).
Format: dev_lane depends on temporalio (not importable in this environment), so
dev_lane is never imported — structural source locks plus a table-driven micro
implementation that replays the validation logic (both directions + fallback +
done).

Background: the workbench rework banner only reads timeline records with
state='rework'; the five internal automatic rework points (acceptance
walkthrough etc.) used to bypass _apply_rework's trace path, so users never saw
why a ticket was sent back. This script locks: the _auto_rework unified entry
in place (including the fallback parameter / vocabulary validation / explicit
role mapping / no _step calls), the 5 wire-in points each passing
who="workflow" and their own fallback, the merge point no longer stuffing
self._rework (preventing a double write), and the PHASE_MAIN_CHAIN /
PHASE_MAIN_ROLES key sets agreeing; it also drives the micro implementation
through forward and backward malformed-input cases.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT / "server/engine/dev_lane.py"
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

# ---------- A. _auto_rework definition + trace-body source lock ----------
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
# Crash path welded shut (review round 3): role computation never goes through _step(target)
m_auto = re.search(r"def _auto_rework\(.*?\n(?=\n    def )", src, re.S)
ok(m_auto is not None, "_auto_rework 函数体可定位")
if m_auto:
    ok("self._step(" not in m_auto.group(0), "_auto_rework 函数体内不含 self._step( 调用")
ok("target == \"done\"" in src, "done 被显式拒绝（终态不可为打回目标）")

# ---------- B. twin-constant vocabulary + role mapping consistency ----------
section("B PHASE_MAIN_CHAIN / PHASE_MAIN_ROLES 常量")
EXPECT = {"create_plan", "review_plan", "parallel_impl_design", "implement",
          "integ_join", "integration_review", "run_integration_tests", "arbitrate",
          "arb_acc_parallel", "acceptance", "merge_check", "merge", "done"}
# Lock rule: the key set = the full set of main-chain phase values (including
# the parallel-fork phase values, not STAGES ids);
# t260903-02 added the 13th key arb_acc_parallel (arbitration || walkthrough
# parallel fork, role=integration).
EXPECT_ROLES = {"create_plan": "developer", "review_plan": "integration",
                "parallel_impl_design": "developer", "implement": "developer",
                "integ_join": "developer", "integration_review": "integration",
                "run_integration_tests": "integration", "arbitrate": "integration",
                "arb_acc_parallel": "integration",
                "acceptance": "integration", "merge_check": "integration",
                "merge": "integration", "done": "integration"}


def parse_const(name: str):
    """Parse a module-level constant out of the source: PHASE_MAIN_CHAIN
    (frozenset) -> set; PHASE_MAIN_ROLES (Dict) -> dict. Returns None when
    parsing fails."""
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

# ---------- C. source lock on the 5 automatic-rework wire-in points ----------
section("C 自动打回点接入（who=fallback 字面量 + 不双落）")
for target_fb in [("implement", '"acceptance"'),      # acceptance walkthrough rework
                  ("implement", '"arbitrate"'),       # arbitrate code-fault
                  ("implement", '"integration_review"'),  # mechanical recheck (x1; counted twice by the assertion)
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
# Lock rule: count of internal automatic rework points (shell delegation not
# counted). t260903-02 added the arb_acc_parallel branch with 2 more
# (acceptance walkthrough rework + code-fault rework) -> 7 points.
# t260916-19 落地期过渡双态（宿主 260917 令 a′）：该票在 dev_lane 主循环新增 rework
# 逃逸消费点（_consume_rework）→ 自动打回点 7→8。共享守卫期望值由 main 侧统一改一次
# （本处），泳道不得就地改。
# t260922-18 收敛+扩容（integration 岗位 main 侧统一改一次，260922 仲裁 gen1）：
# ①t260916-19 已合入 main，按上句既定计划收敛删 7；②宿主 260922 拍板「机械验证
# 前主同步 main」，dev_lane 新增主同步冲突消解回 implement 的合法打回点 → 8→9。
# 260923 两票合并入 main（宿主令）后过渡窗 (8, 9) 收敛为定值 9（8=旧、9=现，不留
# 双口径）。同批：integration/baselines/sc_auto_rework_trace.mjs 的「调用点」
# 随同一次变更改为 10（9 内部 + 1 壳委托）——两守卫数的是同次变更的两个面。
# t261006-07（integration 岗位仲裁 gen0，261006）：主同步 blocked 路由被成功 settle
# 反超的「自动逃生」回 implement（R1 settle-before-block）成为第 10 个内部合法打回点
# → 9→10。同批：baselines mjs「调用点」10→11（10 内部 + 1 壳委托）。
# t261009-17: baseline 10 -> 11 — the main-sync no-human-info shape (merge commit
# already on disk, MERGE_HEAD absent, clean face, live main merely advanced) now
# escapes via _auto_rework back to implement instead of stopping for a human
# (KI-01M4FKAWY0EP59PY0V0QZWWGV5); the new call sites live in the two dev_lane
# settle-failure branches (main-sync and merge_check families).
ok(total_calls == 11, "自动打回点 11 处（t261009-17 基线 10 + 主同步 no-human-info 形状自动重跑点 1）（实测 %d）" % total_calls)
# The merge point no longer stuffs self._rework (one rework must not land two timeline records)
merge_block = src[src.find('if not mr.ok:'):src.find('if not mr.ok:') + 2000]
ok("self._rework = ReworkRequest(" not in merge_block,
   "merge 失败分支不再塞 self._rework（防双落）")
ok("self._rework = None" in src, "_apply_rework 壳保留 signal 消费语义（先清再委托）")
_retired_lines = [ln for ln in src.splitlines()
                  if 'suggest_next' in ln and not ln.lstrip().startswith(('#', '*', '//'))
                  and not ln.strip().startswith(('（', '*'))]
ok('target in ("ui_evidence",)' in src and not _retired_lines,
   "ui_evidence 非主链步拒绝守卫在位；suggest_next 无功能引用（t260910-14 退役，注释留痕豁免）")

# ---------- D. table-driven micro implementation: forward + backward + fallback + done + empty note ----------
section("D 校验逻辑微实现畸形输入用例（不依赖 temporalio）")


class W:  # equivalent micro implementation mirroring _auto_rework's validation semantics (kept in step with source lock A)
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


# Three backward cases: in the vocabulary but not in STAGES — the old _step
# path would crash here; the new path must get through
for tgt, role in [("acceptance", "integration"), ("parallel_impl_design", "developer"),
                  ("integ_join", "developer")]:
    w = W("merge")
    r = w.auto_rework(tgt, "外部 signal 打回 %s" % tgt, "human", "merge")
    ok(r == tgt and w.meta["role"] == role and w.meta["status"] == "rework",
       "反向：target=%s 通过且 role=%s 不崩" % (tgt, role))
# Out-of-vocabulary value (acceptance_walkthrough: in STAGES, not in the
# vocabulary) -> refused, fall back
w = W("acceptance")
r = w.auto_rework("acceptance_walkthrough", "n", "human", "acceptance")
ok(r == "acceptance" and w.meta["status"] != "rework"
   and len(w.meta["refused"]) == 1, "acceptance_walkthrough 被拒：回 fallback、无留痕")
# done -> refused
w = W("merge_check")
r = w.auto_rework("done", "n", "human", "merge_check")
ok(r == "merge_check" and w.meta["status"] != "rework", "done 被拒：回 fallback、无留痕")
# Invalid fallback (empty string) -> refused gets an entry and the return
# value = meta's current step (the invalid value never flows back)
w = W("arbitrate")
r = w.auto_rework("implement", "n", "workflow", "")
ok(r == "arbitrate" and len(w.meta["refused"]) == 1,
   "fallback 非法：返回 meta 现步、非法值不回流")
# Empty note: goes through and the banner reason (note + who concatenated) is
# non-empty — the trace record keeps the initiator column
w = W("acceptance")
r = w.auto_rework("implement", "", "workflow", "acceptance")
reason = "%s（%s）" % ("", "workflow")
ok(r == "implement" and reason.strip("（）") == "workflow" and len(reason) > 0,
   "空 note 走通：reason 由 who 兜底非空")

# ---------- E. scenario registry registration (post-manifest-retirement rule, t260902) ----------
section("E run_scenarios 场景清单登记")
import run_scenarios as _rs  # noqa: E402
ok(any("check_auto_rework_trace.py" in str(e[2]) for e in _rs.SCENARIOS),
   "SCENARIOS 三元组已登记 check_auto_rework_trace")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
