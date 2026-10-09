#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-20 场景：settle 重跑早退分支的 replay-safe 契约（灰盒 L2/L3，离线
秒级，零 docker 零 Temporal 零 3099，隔离内存面零生产写入）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
7993697a（t261009-17）在 dev_lane 的两处 settle 面（主同步 settle 与冲突消解
settle）各加了一条**无 patched 门**的"零人工信息形态 ⇒ 重跑"早退分支。修复前
开出的 run（实证 t261008-47，KI-01M4G97W99WVN2B2VS2BYT6C9X）在历史里该位置
记录的是旧路的命令（blocked 停给人）；换码重放时同一位置走进新分支、调度出与
history 不同的命令 ⇒ 确定性 [TMPRL1100] ⇒ 工作流任务永久 failed，票冻结
（同族实证：KI-201/KI-203 → t261005-14/-15，KI-212 → t261006-19）。
修复=SETTLE_RERUN_PATCH_ID 门（t261009-20）：marker=False（守卫前 history）
⇒ 旧路逐字重放（skip == 历史重放），marker=True ⇒ 重跑语义照常。本场景锁的
用户可感知契约：

- R1 守卫完备（本票点名回归，守卫落地前红=TDD 信号）：dev_lane 中
  settle_shape_needs_rerun 的**每一处**路由位都落在含
  workflow.patched(SETTLE_RERUN_PATCH_ID) 的判定罩内——未来新增第三处路由位
  不罩、或摘掉任一处罩 = 红（家族面：同族事故全部源于"改命令流不罩"）。
- R2 路由语义不被守卫改写：两处站点的判定仍含 `not sres.ok` 与
  `_conflict_rounds < MAX_CONFLICT_ROUNDS` 两臂——守卫只加历史感知，不许
  顺口吃掉失败臂或轮上限臂（ticket 要求「不改路由决策本身」的机械面）。
- R3 marker 纪律：SETTLE_RERUN_PATCH_ID 常量在位，其字面值在全文件
  *_PATCH_ID 族里唯一（复用 id 会污染布尔门族——同 KI-201 修法的教训）。
- R4 畸形/外部输入兜底（三态钩，兼守旧 history 的重放安全方向）：空 error、
  纯垃圾文本、人可行动形态（unmerged entries>0）、copy 漂移形态——谓词一律
  False ⇒ 无论 marker 真假，重跑分支都不可达，blocked 旧路仍是唯一出口
  （fail-safe 方向：宁停给人，绝不空转/绝不为畸形输入改写命令流）。

intent 级分工（防重复）：t261005-14/-15 独占 CL-1 并发闸族；t261006-19 独占
冲突计数复位族（COUNTER_RESET_PATCH_ID）；t260917-04/t260908-01 各守自家
patch 族；本条独有面 = **settle 重跑路由族**（SETTLE_RERUN_PATCH_ID 门）。
developer L1（test_t261009_20_settle_rerun_guard.py，白盒随实现）锁单类形状、
守卫真值表与静态锁细节；谓词本身（settle_shape_needs_rerun）的真值表在 L1
（t261009-17 F4），本条只取其「畸形输入 ⇒ 重跑不可达」的重放安全方向。
真实 Temporal 全 history Replayer 回放与 t261008-47 修复后的 live 复活证明归
integration 岗在真票上人工办（ticket boundary：本票各段不做集成跑、不做 live
验收项），不在本条（离线零 docker）。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（闸内无 SKIP）。引擎模块
（dev_lane/shared）不可导入=ENV_FAIL 点名。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t261004-32"))
sys.path.insert(0, str(HERE.parents[1] / "server" / "engine"))

from lib_t26100432 import check, env_fail, summary  # noqa: E402

DEV_LANE_SRC = HERE.parents[1] / "server" / "engine" / "dev_lane.py"

#: 畸形/外部输入形态集（R4）：谓词必须在每一形上判 False（重跑分支不可达）。
HOSTILE_ERRORS = [
    ("empty error", ""),
    ("pure garbage text", "\x00 total nonsense \n"),
    ("human-actionable shape (unmerged entries)", (
        "settle failed: unmerged entries: 2 (src/a.py, src/b.py), "
        "dirty files: 0, marker residue: none")),
    ("drifted copy (single token only)", (
        "no merge in progress (MERGE_HEAD does not exist)")),
    ("malformed counts (probe failed)", (
        "no merge in progress (MERGE_HEAD does not exist), "
        "unmerged entries: 0, dirty files: -1, marker residue: none")),
]


def site_conditions(src):
    """Every settle-rerun routing site, as the joined text of its ``if``
    condition (continuation lines until the colon). Returns the list of
    joined condition strings."""
    lines = src.splitlines()
    conds = []
    for i, line in enumerate(lines):
        if "if not sres.ok" in line and "settle_shape_needs_rerun" in line:
            joined = line
            j = i
            while not joined.rstrip().endswith(":") and j + 1 < len(lines):
                j += 1
                joined += " " + lines[j].strip()
            conds.append(" ".join(joined.split()))
    return conds


def main():
    try:
        import dev_lane  # noqa: F401
        import shared  # noqa: F401  (engine import face)
    except Exception as e:
        env_fail("engine modules unavailable: %s: %s" % (type(e).__name__, e))

    src = DEV_LANE_SRC.read_text(encoding="utf-8")

    # ---- R1 guard completeness over every settle-rerun routing site --------
    print("\n== R1 guard completeness: every settle-rerun site is gated")
    conds = site_conditions(src)
    check("exactly two settle-rerun routing sites in dev_lane (got %d)"
          % len(conds), len(conds) == 2)
    for k, cond in enumerate(conds, 1):
        check("site %d sits inside a workflow.patched(SETTLE_RERUN_PATCH_ID) "
              "verdict (got %r)" % (k, cond[-120:]),
              "patched(SETTLE_RERUN_PATCH_ID)" in cond)

    # ---- R2 the guard must not rewrite the routing decision ---------------
    print("\n== R2 routing arms intact beside the guard")
    for k, cond in enumerate(conds, 1):
        check("site %d keeps the settle-failure arm (not sres.ok)"
              % k, "not sres.ok" in cond)
        check("site %d keeps the conflict-round cap arm" % k,
              "_conflict_rounds < MAX_CONFLICT_ROUNDS" in cond)

    # ---- R3 marker discipline ---------------------------------------------
    print("\n== R3 marker discipline: constant present, literal unique")
    check("SETTLE_RERUN_PATCH_ID constant present",
          "SETTLE_RERUN_PATCH_ID" in src)
    ids = dict(re.findall(r'^([A-Z0-9_]*PATCH_ID)\s*=\s*"([^"]+)"', src,
                          re.MULTILINE))
    check("SETTLE_RERUN_PATCH_ID is a declared *_PATCH_ID constant (got %s)"
          % sorted(ids), "SETTLE_RERUN_PATCH_ID" in ids)
    others = [name for name, val in ids.items()
              if name != "SETTLE_RERUN_PATCH_ID"
              and val == ids.get("SETTLE_RERUN_PATCH_ID")]
    check("its literal is unique across the patch-id family (clash: %s)"
          % others, others == [])

    # ---- R4 malformed/foreign error shapes: rerun unreachable -------------
    print("\n== R4 hostile error shapes: predicate False -> blocked is the "
          "only exit")
    for label, err in HOSTILE_ERRORS:
        try:
            verdict = dev_lane.settle_shape_needs_rerun(err)
        except Exception as e:
            check("%s: predicate raises nothing (got %s: %s)"
                  % (label, type(e).__name__, e), False)
            continue
        check("%s: rerun branch unreachable (predicate False, got %r)"
              % (label, verdict), verdict is False)

    summary()


if __name__ == "__main__":
    main()
