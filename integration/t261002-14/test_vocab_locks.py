#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261002-14 词表/断言助手单测（pytest，纯函数+夹具文本，零外部源）。

锁三件事：
  A. integration/lib_env.narrowing_lock_report —— 双语言收窄旋钮清单互锁：
     真文件绿、单侧独改必被抓（py 侧独改 / mjs 侧独改各一档）、畸形字面量
     fail-closed（两侧各一档）、乱序也算漂移；
  B. server/engine/executor_grants.grant_ops_lock_report —— 授权词表三面互锁：
     真三面绿、任一侧独改必被抓、别名 'reject'→'send-back' 归一不误报、
     单侧新词点名、仅乱序点名、字面量缺席 fail-closed；
  C. integration/lib_result.ScenarioCheck —— 共享断言助手的计数/措辞/退出码契约
     （ok/na/finish/env_fail；detail 截断；全 N/A=红）。

畸形输入用例全用**夹具文本**复现（不靠真外部源），消费外部输入的纪律照守。
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

import lib_env  # noqa: E402
import executor_grants as eg  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


PY_SRC = _read("integration/lib_env.py")
MJS_SRC = _read("integration/lib_env.mjs")
ENGINE_SRC = _read("server/engine/executor_grants.py")
DECL_SRC = _read("server/plugins/executor-panel/src/host/executor-grants.ts")
FIXED_SRC = _read("server/plugins/executor-panel/src/host/grants.ts")


# ---------------------------------------------------------------- A. narrowing lock

def test_a_real_files_are_locked():
    """真两面：逐元素相同=空报告。"""
    assert lib_env.narrowing_lock_report(PY_SRC, MJS_SRC) == []


def test_a_py_side_only_edit_is_caught():
    """夹具漂移：py 侧独改（追加一个前缀）必被抓，且点名 py 侧。"""
    drifted = PY_SRC.replace('"SANDBAR_SUPPLY_",', '"SANDBAR_SUPPLY_",\n    "SANDBAR_SNEAKY_",', 1)
    assert drifted != PY_SRC  # 夹具自证：替换必须真命中
    rep = lib_env.narrowing_lock_report(drifted, MJS_SRC)
    assert any("SANDBAR_SNEAKY_" in ln and "py=" in ln for ln in rep), rep


def test_a_mjs_side_only_edit_is_caught():
    """夹具漂移：mjs 侧独改（追加一个具名旋钮）必被抓，且点名 mjs 侧。"""
    drifted = MJS_SRC.replace("'SANDBAR_UNDECLARED_POLICY',",
                              "'SANDBAR_UNDECLARED_POLICY', 'SANDBAR_SNEAKY_NAME',", 1)
    assert drifted != MJS_SRC
    rep = lib_env.narrowing_lock_report(PY_SRC, drifted)
    assert any("SANDBAR_SNEAKY_NAME" in ln and "mjs=" in ln for ln in rep), rep


def test_a_mjs_side_only_removal_is_caught():
    """夹具漂移：mjs 侧独删一条=py 侧出现 <absent> 对齐差，必被抓。"""
    drifted = MJS_SRC.replace(" 'SANDBAR_GATE_',", "", 1)
    assert drifted != MJS_SRC
    rep = lib_env.narrowing_lock_report(PY_SRC, drifted)
    assert any("prefixes[" in ln and "<absent>" in ln for ln in rep), rep


def test_a_py_malformed_literal_is_fail_closed():
    """畸形：py 侧清单改成 list（非 tuple）→ 报告行，绝不空报假绿。"""
    malformed = PY_SRC.replace("NARROWING_ENV_NAMES = (", "NARROWING_ENV_NAMES = [", 1)
    # 把对应闭括号也换成 )（保持语法可解析，只破「tuple 形态」判据）
    idx = malformed.find("NARROWING_ENV_NAMES = [")
    close = malformed.find(")\n", idx)
    malformed = malformed[:close] + "]" + malformed[close + 1:]
    rep = lib_env.narrowing_lock_report(malformed, MJS_SRC)
    assert any("py-side names literal not extractable" in ln for ln in rep), rep


def test_a_mjs_malformed_literal_is_fail_closed():
    """畸形：mjs 侧常量改名（提不出）→ 报告行，绝不空报假绿。"""
    malformed = MJS_SRC.replace("NARROWING_NAMES", "NARROWING_NAMES_V2")
    rep = lib_env.narrowing_lock_report(PY_SRC, malformed)
    assert any("mjs-side names literal not extractable" in ln for ln in rep), rep


def test_a_order_only_drift_is_reported():
    """仅乱序（同集合不同序）也必须被点名，不当等价集放行。"""
    drifted = MJS_SRC.replace(
        "'SANDBAR_POOL_CONC', 'SANDBAR_CONC_POOLS',",
        "'SANDBAR_CONC_POOLS', 'SANDBAR_POOL_CONC',", 1)
    assert drifted != MJS_SRC
    rep = lib_env.narrowing_lock_report(PY_SRC, drifted)
    assert any("names[0] drift" in ln for ln in rep), rep


# ---------------------------------------------------------------- B. grant ops lock

def test_b_real_three_sides_are_locked():
    """真三面（含 'reject'↔'send-back' 别名归一）：空报告。"""
    assert eg.grant_ops_lock_report(ENGINE_SRC, DECL_SRC, FIXED_SRC) == []


def test_b_decl_side_only_edit_is_caught():
    """夹具漂移：声明侧（executor-grants.ts）独加一词 → 点名侧与词。"""
    drifted = DECL_SRC.replace("'cleanup' as const", "'cleanup', 'sneaky-op' as const", 1)
    if drifted == DECL_SRC:  # 夹具形态自证：as const 后缀不在（数组整体 as const）
        drifted = DECL_SRC.replace("'cleanup']", "'cleanup', 'sneaky-op']", 1)
    assert drifted != DECL_SRC
    rep = eg.grant_ops_lock_report(ENGINE_SRC, drifted, FIXED_SRC)
    assert any("sneaky-op" in ln and "executor-grants.ts" in ln for ln in rep), rep


def test_b_fixed_side_only_edit_is_caught():
    """夹具漂移：显示侧（grants.ts）独改别名词 'reject'→'return' → 点名 unknown op。"""
    drifted = FIXED_SRC.replace("'reject'", "'return'", 1)
    assert drifted != FIXED_SRC
    rep = eg.grant_ops_lock_report(ENGINE_SRC, DECL_SRC, drifted)
    assert any("'return'" in ln and "unknown op" in ln for ln in rep), rep


def test_b_order_only_drift_is_reported():
    """仅乱序：声明侧两条对调 → op[i] drift 行点名。"""
    drifted = DECL_SRC.replace("'send-back', 'rerun'", "'rerun', 'send-back'", 1)
    assert drifted != DECL_SRC
    rep = eg.grant_ops_lock_report(ENGINE_SRC, drifted, FIXED_SRC)
    assert any("op[1] drift" in ln for ln in rep), rep


def test_b_missing_literal_is_fail_closed():
    """畸形：声明侧 GRANT_OPS 常量整体缺席 → fail-closed 报告行，绝不空报。"""
    rep = eg.grant_ops_lock_report(ENGINE_SRC, "export const X = 1\n", FIXED_SRC)
    assert any("executor-grants.ts GRANT_OPS literal not extractable" in ln for ln in rep)
    rep2 = eg.grant_ops_lock_report("GRANT_OPS = 42\n", DECL_SRC, FIXED_SRC)
    assert any("engine-side GRANT_OPS literal not extractable" in ln for ln in rep2)


# ---------------------------------------------------------------- C. ScenarioCheck

def test_c_ok_counts_and_output_format(capsys):
    ck = ScenarioCheck(detail_cap=400, flush=False)
    ck.ok(True, "good")
    ck.ok(False, "bad", "x" * 500)
    out = capsys.readouterr().out
    assert ck.passes == 1 and ck.fails == 1
    assert "  ok good\n" in out
    assert ("  FAIL bad | " + "x" * 400) in out          # detail 截到 cap
    assert "x" * 401 not in out
    assert "  N/A" not in out


def test_c_na_and_finish_all_na_is_red(capsys):
    ck = ScenarioCheck()
    ck.na("leg", "no object")
    with pytest.raises(SystemExit) as ei:
        ck.finish("sc-x")
    assert ei.value.code == 1                            # 全 N/A=设计/覆盖红
    out = capsys.readouterr().out
    assert "  N/A: leg（no object）" in out
    assert "FAIL [sc-x] exit=1" in out


def test_c_finish_summary_and_exit_codes(capsys):
    ck = ScenarioCheck()
    ck.ok(True, "a")
    ck.ok(False, "b")
    with pytest.raises(SystemExit) as ei:
        ck.finish("sc-y")
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "SUMMARY pass=1 fail=1 env_fail=0 na=0" in out

    ck2 = ScenarioCheck()
    ck2.ok(True, "a")
    with pytest.raises(SystemExit) as ei2:
        ck2.finish("sc-z")
    assert ei2.value.code == 0
    assert "SUMMARY pass=1 fail=0 env_fail=0 na=0" in capsys.readouterr().out


def test_c_env_fail_exits_two(capsys):
    ck = ScenarioCheck()
    with pytest.raises(SystemExit) as ei:
        ck.env_fail("sc-e", "pytest missing")
    assert ei.value.code == 2
    assert "ENV_FAIL [sc-e] exit=2" in capsys.readouterr().out


def test_a_mjs_assignment_form_broken_is_fail_closed():
    """畸形：mjs 侧声明写坏（`NAME = [` 赋值形态破坏）→ fail-closed，不子串假绿。"""
    malformed = MJS_SRC.replace("const NARROWING_PREFIXES = [", "const NARROWING_PREFIXES [", 1)
    rep = lib_env.narrowing_lock_report(PY_SRC, malformed)
    assert any("mjs-side prefixes literal not extractable" in ln for ln in rep), rep


def test_b_broken_assignment_form_is_fail_closed():
    """畸形：TS 侧声明写坏（`GRANT_OPS broken =`）→ fail-closed，不子串假绿。"""
    bad = DECL_SRC.replace("export const GRANT_OPS =", "export const GRANT_OPS broken =", 1)
    rep = eg.grant_ops_lock_report(ENGINE_SRC, bad, FIXED_SRC)
    assert any("executor-grants.ts GRANT_OPS literal not extractable" in ln for ln in rep), rep
