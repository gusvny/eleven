#!/usr/bin/env python3
"""t260903-02 集成场景 t03：场景锁更新不弱化（integration 设计，t260903-02）。

用户场景：本票实现会随改两把已登记的「精确锁」（方案 v3 步骤 6.5：词表 12→13 键、
_auto_rework 调用点计数）。历史教训（t260831-08 / integration/README 红线）：
把精确断言放宽成非空判定或缺环境放行是「让红灯变绿」的捷径（三态契约 §7.3 禁止）。本场景锁**更新后的锁仍是
精确匹配**、且新键随改——锁的锁。

  A. py 锁（sc_check_auto_rework_trace.py）：EXPECT 恰 13 键含 arb_acc_parallel、
     EXPECT_ROLES 含该键 role=integration、chain == EXPECT 精确匹配在、
     total_calls == 9 在、断言文案「恰为 13 个主链步」在。
  B. mjs 锁（sc_auto_rework_trace.mjs）：len == 13 在、旧 == 12 退场、
     _auto_rework findall == 10 在、键集合动态比对行仍在（未被弱化成单向检查）。

260923 A 慢性红清账补同步（宿主直修令）：下级两锁已随 23a9a29/fa51e1e 有意同步
到引擎真态，元锁当时漏改——按本场景自身契约补齐，锁只紧不松。
260923 两票合并入 main（宿主令）再随改：t260922-18 主同步消解回 implement 加
第 10 个打回点/第 11 个调用点（t261006-07 自动逃生点落地后），三锁同批收敛定值 10/11（过渡窗不留双口径）。

跑法：python3 -B integration/t260903-02/sc_lock_update_integrity.py（纯源码断言，零依赖）。
实现段（步骤 6.5）完成前运行会红。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEG = HERE.parent
PY_LOCK = (INTEG / "sc_check_auto_rework_trace.py").read_text("utf-8")
MJS_LOCK = (INTEG / "baselines" / "sc_auto_rework_trace.mjs").read_text("utf-8")

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


def section(t):
    print("\n== %s" % t)


section("A py 锁：精确匹配保持 + 第 13 键随改")
m = re.search(r"EXPECT = \{(.*?)\}", PY_LOCK, re.S)
expect = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
ok(len(expect) == 13, "EXPECT 恰 13 键（实测 %d）" % len(expect))
ok("arb_acc_parallel" in expect, "EXPECT 含 arb_acc_parallel")
ok('"arb_acc_parallel": "integration"' in PY_LOCK,
   "EXPECT_ROLES 含该键 role=integration")
ok("chain == EXPECT" in PY_LOCK, "词表断言仍是精确集合匹配（未放宽）")
# t261019-25 arbitrate gen2: 11 -> 12 — main b3d8e5e4 (261019 merge_check
# self-healing, merged at f787cc8/de73f4c) added the declaration-driven
# remediable-red _auto_rework point; the meta-lock follows the py lock it
# guards, same same-batch bump convention as t261009-17 / t261006-07.
# (conflict resolution: both sides locked the SAME value 12 — both provenances kept.)
ok("total_calls == 12" in PY_LOCK, "打回点计数锁现行 == 12 定值逐字在（仍精确匹配；"
   "t261009-17 主同步 no-human-info 形状 +1、261019 主同步 declaration-driven "
   "self-heal（ea3def75+b3d8e5e4，t261019-25 同批）再 +1，三锁同批收敛定值）")
ok("恰为 13 个主链步" in PY_LOCK, "断言文案同步（人读口径不撒谎）")
ok("total_calls in (8, 9)" not in PY_LOCK and "total_calls in (7, 8)" not in PY_LOCK
   and "total_calls == 9" not in PY_LOCK and "total_calls == 5" not in PY_LOCK
   and "total_calls == 6" not in PY_LOCK and "total_calls == 10" not in PY_LOCK,
   "旧计数 (8,9)/(7,8)、定值 9 与 5/6、上一代定值 10 已退场（不留双口径）")

section("B mjs 锁：精确匹配保持 + 计数随改")
ok("len(PHASE_MAIN_CHAIN) == 13" in MJS_LOCK, "len 锁更新为 13（仍精确 ==）")
ok(re.search(r"len\(PHASE_MAIN_CHAIN\) == 12\b", MJS_LOCK) is None,
   "旧 len 12 已退场（锚定 len(PHASE_MAIN_CHAIN) 形态，避免裸子串误伤调用点锁现行定值）")
ok(re.search(r"findall\(r'self\\._auto_rework\\\(', src\)\) == 12", MJS_LOCK) is not None,
   "_auto_rework 调用点锁更新为 12（t261009-17 基线 11 再 +1 主同步 settle-failure 点；"
   "11 = 10 内部 phase 赋值 + 1 壳委托 return——与 sc_check_auto_rework_trace.py 窄口径 11 同批收敛）")
ok(re.search(r"findall\(r'self\\._auto_rework\\\(', src\)\) == 9", MJS_LOCK) is None
   and re.search(r"findall\(r'self\\._auto_rework\\\(', src\)\) == 8", MJS_LOCK) is None
   and re.search(r"findall\(r'self\\._auto_rework\\\(', src\)\) == 10", MJS_LOCK) is None
   and re.search(r"findall\(r'self\\._auto_rework\\\(', src\)\) == 11", MJS_LOCK) is None,
   "旧调用点 11/10/9/8 已退场（不留双口径）")
ok("set(PHASE_MAIN_ROLES) == set(PHASE_MAIN_CHAIN)" in MJS_LOCK,
   "键集合动态比对仍在（未弱化成单向包含）")

print("\nt03 结果：pass=%d fail=%d" % (PASS, FAIL))
print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
