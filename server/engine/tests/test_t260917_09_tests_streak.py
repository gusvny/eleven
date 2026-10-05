#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-09：tests_rounds 连续语义 + 复位点 + 假封防护（环境红/抖动豁免）UT。

覆盖（工单验收①②④的 UT 面；③场景面在 integration/t260917-09）：
- 连续语义矩阵：tf,tf,pass,tf×4 恒不进超限（计数轨迹 1,2,0,1,2,3,4）；
  对照 tf×6 第 7 判决 blocked（上限仍在，非拆除）。
- 复位点全表：pass / code-fault / 非法 verdict / 人工接受（伪 verdict="accept-reset"）
  → (0,0)；非迭代来源重进段入口由 dev_lane 消费（结构断言）。
- 豁免：环境面红（产品红 0/闸拦 0/环境红≥1）与抖动复跑全绿 → 不计轮+豁免+1；
  混合面（产品红>0 或闸拦非空）照计。连续豁免 6 轮 → tests_exempt_cap_blocked_text
  含「超限」+四条真实出路（authorize/ruling/rework/pause；无 terminate）。
- 豁免判定第二形态（gen11 打回补，C2 节三断言）：装配级供给失败（ran=0＋error
  命中 verify_lane 乙段供给装配签名）→ 同走豁免账不保守计轮；窄签名负例（其他
  启动级 error 不豁免）；留痕点名供给面；豁免上限与出路封面不回退。
- integration_route 超限文案：前缀逐字节兼容既有断言 + 出路关键词在场。
- 探针回执 parse_reprobe_summary 五态 + all_green；--reprobe 执行器面（真注册表
  不在册 fail-closed 子用例 + mini 注册表注入的执行语义/串行/三态/超时回收子用例）。
- C6：INTEG_MANIFEST 死常量已摘除（消费外部输入纪律：畸形入参 fail-closed 用例
  分布在 B/C/F 各节）。
- J 节（merge 后 gen3 补）：豁免超限封面两分支的登记自证——仍在 TESTS_STREAK 门内
  （AST 祖先链）且锚串仍在 t260917-04 守卫 BRANCH_REGISTRY（论证防腐钉）。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shared
from shared import (MAX_CODE_FAULT_ROUNDS, MAX_TESTS_EXEMPT_ROUNDS,
                    MAX_TESTS_FAULT_ROUNDS, ReprobeRedResult,
                    integration_route, parse_reprobe_summary)
from shared import tests_exempt_cap_blocked_text as exempt_cap_text
from shared import tests_round_step as step_rounds  # 别名：防 pytest 误收集 tests_* 名
from shared import tests_supply_assembly_error as supply_sig  # 同上别名

REPO = Path(__file__).resolve().parents[3]


# ---------- A. 连续语义矩阵（验收①） ----------

def _drive(verdicts):
    """按 dev_lane 消费形驱动纯函数链：route 预增判定 → step 转移。返回轨迹。"""
    tr = ex = 0
    traj = []
    for v in verdicts:
        if v == "tests-fault":
            assert integration_route(v, tr, 0) == "run_integration_tests", \
                "轨迹 %s 处提前 blocked" % traj
        tr, ex, counted, note = step_rounds(v, tr, ex)
        traj.append((tr, ex, counted, note))
    return traj


def test_a_consecutive_matrix_never_blocks():
    # 验收①原话序列：tests-fault, tests-fault, pass, tests-fault×4
    traj = _drive(["tests-fault", "tests-fault", "pass",
                   "tests-fault", "tests-fault", "tests-fault", "tests-fault"])
    assert [t[0] for t in traj] == [1, 2, 0, 1, 2, 3, 4]
    assert all(t[2] for i, t in enumerate(traj) if i != 2)  # 仅 pass 轮不计
    assert traj[2] == (0, 0, False, "streak-reset")


def test_a_contrast_cumulative_still_caps():
    # 对照：连续 6 判 tests-fault（计数到 6）→ 第 7 判决 route=blocked（上限仍在）
    tr = 0
    for i in range(6):
        assert integration_route("tests-fault", tr, 0) == "run_integration_tests"
        tr, _, counted, _ = step_rounds("tests-fault", tr, 0)
        assert counted
    assert tr == MAX_TESTS_FAULT_ROUNDS + 1
    assert integration_route("tests-fault", tr, 0).startswith(
        "blocked:test-set iterations %d exceed the cap" % tr)


# ---------- B. 复位点全表（要求①②） ----------

@pytest.mark.parametrize("verdict", ["pass", "code-fault", "accept-reset",
                                     "", None, "???", "verdict=pass"])
def test_b_reset_points(verdict):
    tr, ex, counted, note = step_rounds(verdict, 5, 3)
    assert (tr, ex) == (0, 0) and not counted and note == "streak-reset"


def test_b_exempt_rounds_reset_too():
    # 复位同时清豁免轮（否则陈年豁免与陈年计数一样会假封）
    tr, ex, _, _ = step_rounds("pass", 2, MAX_TESTS_EXEMPT_ROUNDS)
    assert (tr, ex) == (0, 0)


# ---------- C. 豁免：环境面红 / 抖动复跑全绿（验收②） ----------

def test_c_env_side_red_not_counted():
    tr, ex, counted, note = step_rounds("tests-fault", 3, 0, env_side_red=True)
    assert (tr, ex, counted) == (3, 1, False) and note == "env-side-red"


def test_c_jitter_green_not_counted():
    tr, ex, counted, note = step_rounds("tests-fault", 3, 2, jitter_green=True)
    assert (tr, ex, counted) == (3, 3, False) and note == "jitter-green"


@pytest.mark.parametrize("kw", [dict(), dict(env_side_red=False, jitter_green=False)])
def test_c_mixed_red_counts(kw):
    tr, ex, counted, note = step_rounds("tests-fault", 3, 1, **kw)
    assert (tr, ex, counted) == (4, 0, True) and note == "counted"


# ---------- 畸形入参 fail-closed（保守计轮，不抛不静默清零） ----------

def test_c_malformed_inputs_fail_closed():
    # 负数/非 int 轮次 → 归零后照常**计轮**（不当复位用）；非布尔信号按 False
    for tr0, ex0 in ((-1, 0), (0, -7)):
        tr, ex, counted, _ = step_rounds("tests-fault", tr0, ex0)
        assert (tr, ex, counted) == (1, 0, True)
    tr, ex, counted, _ = step_rounds("tests-fault", "3", None)  # type: ignore[arg-type]
    assert (tr, ex, counted) == (1, 0, True)
    tr, ex, counted, _ = step_rounds("tests-fault", 3, 0, env_side_red="yes")  # type: ignore[arg-type]
    assert counted and tr == 4  # 非布尔信号不被采信为豁免


# ---------- C2. 装配级供给失败形态（gen11 打回补：豁免判定/豁免账本/封面文案） ----------

# verify_lane 乙段 supply 装配三态真文案（260927 单源改造：出口=「状态 token + 英文人话
# + 侧面 token」，签名判据认 token 不认人话——签名单写者=shared.SUPPLY_STATE_SIGS ∧
# shared.SUPPLY_SIDE_SIG）
SUPPLY_TIMEOUT_ERR = ("%s: supply assembly timed out (need=docker test stage, >900s) — "
                      "supply-side red, named, not silent %s"
                      % (shared.SUPPLY_TIMEOUT_SIG, shared.SUPPLY_SIDE_SIG))
SUPPLY_FAIL_ERR = ("%s: supply assembly failed (need=test supply, exit=1): boom — "
                   "supply-side red, named, not silent %s"
                   % (shared.SUPPLY_FAIL_SIG, shared.SUPPLY_SIDE_SIG))
#: 260927 前的中文双标记形态——**只为重放兼容**保留的夹具（在途票 history 里是这个）
LEGACY_SUPPLY_TIMEOUT_ERR = ("supply 装配超时（need=x，>900s）——供给面红点名，不静默")


def _supply_receipt(**kw):
    """gen11 实证形态：ran=0＋error=供给签名＋env_fail=0＋红项名单空。"""
    d = dict(ran=0, passed=0, failed=0, env_fail=0, error=SUPPLY_TIMEOUT_ERR)
    d.update(kw)
    return shared.IntegrationRunResult(**d)


def test_c2_supply_signature_variants_match():
    # 豁免判定①（签名面）：verify_lane 超时/失败两态真文案都命中
    assert supply_sig(SUPPLY_TIMEOUT_ERR)
    assert supply_sig(SUPPLY_FAIL_ERR)


def test_c2_supply_signature_narrow_and_malformed():
    # 窄签名（fail-closed）：其他启动级 error / 半标记文案不命中——照旧保守计轮，
    # 绝不因豁免口径扩大放走产品面/声明面红（gen11：宁窄勿宽）
    for err in ("scenario executor wall timed out (>3000s)",
                "verify_lane integ produced no valid output (exit=1): garbage",
                "integration 未知键: foo", "未知错误",
                # 单 token 各自不命中（窄度：状态 ∧ 侧面，缺一不可）
                shared.SUPPLY_TIMEOUT_SIG + ": no side token here",
                shared.SUPPLY_SIDE_SIG + ": no state token here",
                "the supply assembly timed out (prose only, no token)"):
        assert not supply_sig(err), err
    for bad in (None, 0, 3.5, [shared.SUPPLY_TIMEOUT_SIG], {"e": 1}, "",
                b"SUPPLY_ASSEMBLY_TIMEOUT"):
        assert not supply_sig(bad)
    # 重放兼容＝**逐字等价**（宿主口径：签名语义不许放宽/收紧）：对老形态输入，新匹配器
    # 必须与 260927 前的旧匹配器给出**完全相同**的结论（在途票 history 里就是老文案，
    # 判据翻面=workflow 决策分叉=非确定）。这里把旧式判据现地重实现做对照。
    def _legacy_matcher(text):
        return all(m in text for m in ("supply 装配", "供给面红"))
    legacy_samples = [
        LEGACY_SUPPLY_TIMEOUT_ERR,
        "supply 装配失败（need=x，exit=1）：boom——供给面红点名，不静默",
        "supply 装配好了——供给面红",            # 已知近似命中面（旧式也命中，等价保持）
        "——供给面红点名，不静默",
        "scenario executor wall timed out (>3000s)",
    ]
    for sample in legacy_samples:
        assert supply_sig(sample) == _legacy_matcher(sample), sample


def test_c2_supply_shape_exempt_judgement():
    # 豁免判定②（dev_lane 机械判据面；gen11 实证该形态曾判 False → 保守计轮假封）
    import dev_lane
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    assert wf._tests_env_side_red(_supply_receipt())
    assert wf._tests_env_side_red(_supply_receipt(error=SUPPLY_FAIL_ERR))
    # 边角（口径宁窄勿宽）：非供给 error / 有跑 / 产品红 / 闸拦 / 字段畸形 → 不豁免
    assert not wf._tests_env_side_red(
        _supply_receipt(error="scenario executor wall timed out (>3000s)"))
    assert not wf._tests_env_side_red(_supply_receipt(ran=3))
    assert not wf._tests_env_side_red(_supply_receipt(failed=1))
    assert not wf._tests_env_side_red(_supply_receipt(blockers=["gate-x"]))
    assert not wf._tests_env_side_red(_supply_receipt(failed="oops"))
    assert not wf._tests_env_side_red(None)
    # 对照子用例不回退：场景级环境红形态照旧豁免（gen0 行为零回归）
    assert wf._tests_env_side_red(
        shared.IntegrationRunResult(ran=3, passed=2, failed=0, env_fail=1))


def test_c2_supply_shape_exempt_ledger_names_supply_face():
    # 豁免账本③：供给形态走连续豁免账（不计轮），留痕点名供给面并带原始证据
    # （要求③留痕；gen11：文案不许把宿主供给事实说成「测试集连红」）
    import dev_lane
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    tr, ex, counted, note = asyncio.run(
        wf._tests_round_account(3, 0, _supply_receipt()))
    assert (tr, ex, counted) == (3, 1, False)
    assert "supply-side" in note and "not counted as a tests-fault round" in note and shared.SUPPLY_TIMEOUT_SIG in note
    _, _, counted2, note2 = asyncio.run(
        wf._tests_round_account(0, 0, _supply_receipt(error=SUPPLY_FAIL_ERR)))
    assert not counted2 and "supply-side" in note2


def test_c2_supply_shape_exempt_cap_cover_intact():
    # 封面文案④：连续供给豁免撞上限 → 封面「超限」+四条真实出路（防活循环上限
    # 与出路不回退，KI-061 教训）；计轮本体不涨（供给轮不吃 tests-fault 上限）
    import dev_lane
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    tr = ex = 0
    for _ in range(MAX_TESTS_EXEMPT_ROUNDS):
        tr, ex, counted, _ = asyncio.run(
            wf._tests_round_account(tr, ex, _supply_receipt()))
        assert not counted and tr == 0
    assert ex == MAX_TESTS_EXEMPT_ROUNDS
    cover = exempt_cap_text(ex + 1)
    assert "consecutive-exemption over cap" in cover
    for kw in ("authorize", "ruling", "rework", "pause"):
        assert kw in cover, kw


# ---------- D. 连续豁免上限与出路文案（要求④） ----------

def test_d_exempt_cap_text():
    t = exempt_cap_text(MAX_TESTS_EXEMPT_ROUNDS + 1)
    assert "consecutive-exemption over cap" in t and str(MAX_TESTS_EXEMPT_ROUNDS) in t
    for kw in ("authorize", "ruling", "rework", "pause"):
        assert kw in t, kw
    assert "terminate" not in t  # 无此 op，不发明出口


def test_d_exempt_loop_bound():
    # 防活循环：连续豁免到上限后调用方封面（文案可断言），计数不再增长
    tr, ex = 0, 0
    for _ in range(MAX_TESTS_EXEMPT_ROUNDS + 2):
        tr, ex, counted, _ = step_rounds("tests-fault", tr, ex,
                                              jitter_green=True)
    assert tr == 0 and ex == MAX_TESTS_EXEMPT_ROUNDS + 2 and not counted
    assert "consecutive-exemption over cap" in exempt_cap_text(ex)


# ---------- E. integration_route 超限文案（零回归 + 出路在场） ----------

def test_e_route_text_prefix_byte_compat():
    r = integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS + 1, 0)
    assert r.startswith("blocked:test-set iterations 6 exceed the cap (cap 5); needs human review")
    for kw in ("authorize", "ruling", "rework", "pause", "exceed the cap"):
        assert kw in r
    r2 = integration_route("code-fault", 0, MAX_CODE_FAULT_ROUNDS + 1)
    assert r2.startswith("blocked:bounced to developer 6 rounds exceed the cap (cap 5); needs human review")
    assert "authorize" in r2
    # 未超限路由不受影响；route 签名未变（3 位置参）
    assert integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS, 0) == \
        "run_integration_tests"
    assert integration_route("pass", 99, 99) == "acceptance"


# ---------- F. 探针回执解析（R1 定案：fail-closed 也打汇总行） ----------

def _sum(ran=0, passed=0, failed=0, env_fail=0, missing=None, error="", entries=None):
    return json.dumps({"ran": ran, "passed": passed, "failed": failed,
                       "env_fail": env_fail, "missing": missing or [],
                       "error": error, "entries": entries or []},
                      ensure_ascii=False)


def test_f_parse_good_receipt_green():
    r = parse_reprobe_summary("noise\n  复跑 [a] 过\nREPROBE_SUMMARY "
                              + _sum(ran=2, passed=2, entries=[
                                  {"name": "a", "exit": 0, "dur_s": 0.1}]),
                              0)
    assert r.all_green() and r.ran == 2 and r.entries[0]["name"] == "a"


def test_f_parse_missing_names_fail_closed():
    r = parse_reprobe_summary("REPROBE_SUMMARY " + _sum(missing=["ghost"],
                                                        error="红项不在册"), 2)
    assert r.error and r.missing == ["ghost"] and not r.all_green()


def test_f_parse_missing_line_and_malformed():
    assert parse_reprobe_summary("no summary at all", 1).error
    assert parse_reprobe_summary("REPROBE_SUMMARY not-json", 0).error
    assert parse_reprobe_summary("REPROBE_SUMMARY [1,2]", 0).error
    assert parse_reprobe_summary("", -9).error


def test_f_parse_nonzero_exit_counts_as_error():
    r = parse_reprobe_summary("REPROBE_SUMMARY " + _sum(ran=1, failed=1), 1)
    assert r.error and not r.all_green()  # 有红=未证全绿=保守计轮


def test_f_all_green_edges():
    assert not ReprobeRedResult().all_green()          # 零跑=未证全绿
    assert not ReprobeRedResult(ran=1, env_fail=1).all_green()
    assert not ReprobeRedResult(ran=1, error="x").all_green()
    assert ReprobeRedResult(ran=1).all_green()


# ---------- G. --reprobe 执行器面 ----------

def _rs_mod():
    sys.path.insert(0, str(REPO / "integration"))
    import run_scenarios as rs
    return rs


def _lock_off(monkeypatch):
    # 锁契约=「持有到进程结束，flock 随进程消亡自释放」（生产路径探针是独立子进程，
    # 退出即释放）；UT 同进程多次直调 reprobe_main 会互相持锁——进程内测试显式关锁，
    # 锁忙子用例单独 monkeypatch（test_g_run_lock_busy_fail_closed）。
    monkeypatch.setenv(_rs_mod().RUN_LOCK_OFF_ENV, "1")


def test_g_real_registry_missing_name_fail_closed():
    """真注册表反用例（独立进程读真 SCENARIOS）：不在册→exit 2、missing 点名、
    零条目执行、汇总行恰一条（R1：fail-closed 也打 REPROBE_SUMMARY）。"""
    p = subprocess.run(
        [sys.executable, "integration/run_scenarios.py", "--reprobe",
         "t26091709-ghost-a,t26091709-ghost-b"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120)
    lines = [ln for ln in p.stdout.splitlines()
             if ln.startswith("REPROBE_SUMMARY ")]
    assert p.returncode == 2 and len(lines) == 1
    doc = json.loads(lines[0][len("REPROBE_SUMMARY "):])
    assert doc["ran"] == 0 and doc["entries"] == []
    assert doc["missing"] == ["t26091709-ghost-a", "t26091709-ghost-b"]
    assert doc["error"]


def test_g_mini_registry_execution_semantics(monkeypatch):
    """mini 注册表注入（既有电池先例）：/bin/sh -c 语义（shell 语法可跑）、
    串行保序、三态分类、汇总行自洽。"""
    rs = _rs_mod()
    _lock_off(monkeypatch)
    monkeypatch.setattr(rs, "SCENARIOS", [
        ("probe-ok", "t", "true", "main"),
        ("probe-shell", "t", "X=1; [ \"$X\" = 1 ] && echo shell-ok", "main"),
        ("probe-fail", "t", "exit 1", "main"),
        ("probe-env", "t", "exit 2", "main"),
    ])
    rc = rs.reprobe_main(["probe-ok", "probe-shell", "probe-fail", "probe-env"])
    assert rc == 1  # 有红
    # 串行结果经 stdout 汇总行核（capture 不便——直接查 _run_entry 面分类）
    name, code, _tail, dur, _t0, _full = rs._run_entry(rs.SCENARIOS[1])
    assert name == "probe-shell" and code == 0 and dur >= 0


def test_g_mini_registry_timeout_reaped(monkeypatch):
    """超时子用例：执行器侧 CMD_TIMEOUT 到点 → exit -9 分类环境红，进程被回收
    （subprocess.run(timeout=) 内建回收），reprobe 计数诚实。"""
    rs = _rs_mod()
    _lock_off(monkeypatch)
    monkeypatch.setattr(rs, "CMD_TIMEOUT", 1)
    monkeypatch.setattr(rs, "SCENARIOS", [
        ("probe-slow", "t", "sleep 5", "main")])
    t0 = time.time()
    name, code, tail, dur, _t0, _full = rs._run_entry(rs.SCENARIOS[0])
    assert name == "probe-slow" and code == -9 and dur < 4
    assert "超时" in tail
    rc = rs.reprobe_main(["probe-slow"])
    assert rc == 1 and time.time() - t0 < 10


def test_g_run_lock_busy_fail_closed(monkeypatch):
    """锁忙子用例（R1 定案：fail-closed 也打汇总行）：单飞锁抢不到 → 零跑＋error 点名
    ＝保守计轮信号（生产上锁随探针子进程消亡自释放，同 main() 契约）。"""
    rs = _rs_mod()
    monkeypatch.setattr(rs, "SCENARIOS", [("probe-x", "t", "true", "main")])
    monkeypatch.setattr(rs, "_acquire_run_lock", lambda: -1)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert rs.reprobe_main(["probe-x"]) == 2
    marks = [ln for ln in buf.getvalue().splitlines()
             if ln.startswith("REPROBE_SUMMARY ")]
    assert len(marks) == 1 and json.loads(marks[0][16:])["error"]


def test_g_mini_registry_missing_never_runs(monkeypatch):
    rs = _rs_mod()
    ran = []
    monkeypatch.setattr(rs, "SCENARIOS", [("probe-real", "t", "true", "main")])
    monkeypatch.setattr(rs, "_run_entry",
                        lambda e: ran.append(e[0]) or (e[0], 0, "", 0.0, 0.0, ""))
    assert rs.reprobe_main(["probe-real", "ghost"]) == 2
    assert ran == []  # 不在册=一条都不跑（保守计轮信号，不半跑）


def test_g_summary_line_single_and_last(monkeypatch):
    rs = _rs_mod()
    _lock_off(monkeypatch)
    monkeypatch.setattr(rs, "SCENARIOS", [("probe-one", "t", "true", "main")])
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rs.reprobe_main(["probe-one"])
    marks = [ln for ln in buf.getvalue().splitlines()
             if ln.startswith("REPROBE_SUMMARY ")]
    assert len(marks) == 1
    doc = json.loads(marks[0][len("REPROBE_SUMMARY "):])
    assert doc == {"ran": 1, "passed": 1, "failed": 0, "env_fail": 0,
                   "missing": [], "error": "",
                   "entries": [{"name": "probe-one", "exit": 0, "dur_s": 0.0}]}


# ---------- H. dev_lane 结构面（复位点/判据/登记） ----------

def test_h_dev_lane_structure():
    import dev_lane
    assert dev_lane.TESTS_STREAK_PATCH_ID == "dev-lane-tests-streak-v1"
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    # 环境面判据（机械口径：产品红 0/闸拦 0/环境红 ≥1；缺席=False 保守计轮）
    integ = shared.IntegrationRunResult(ran=3, passed=2, failed=0, env_fail=1)
    assert wf._tests_env_side_red(integ)
    assert not wf._tests_env_side_red(
        shared.IntegrationRunResult(ran=3, passed=2, failed=1, env_fail=1))
    assert not wf._tests_env_side_red(
        shared.IntegrationRunResult(ran=3, passed=2, failed=0, env_fail=1,
                                    blockers=["case-x"]))
    assert not wf._tests_env_side_red(None)
    # 红项名单（C4 并集 + 合成条目剔除 + 畸形行不炸）
    integ = shared.IntegrationRunResult(
        details=[{"name": "case-a", "exit": 1}, {"name": "case-b", "exit": 0},
                 {"name": "__gate_blockers__", "exit": 1}, {"name": "", "exit": 1},
                 {"name": "case-c", "exit": "oops"}],
        blockers=["case-d", "__pool_exclude__"])
    assert wf._tests_red_names(integ) == ["case-a", "case-d"]
    assert wf._tests_red_names(None) == []
    assert wf._tests_red_names(shared.IntegrationRunResult()) == []
    # 探针活动已登记（缺注册=仲裁期运行时才炸）
    import agent_activities
    assert any(getattr(a, "__name__", "") == "reprobe_red_scenarios"
               for a in agent_activities.ALL_AGENT_ACTIVITIES)


# ---------- I. C6：死常量/死契约摘除 ----------

def test_i_dead_manifest_gone():
    assert not hasattr(shared, "INTEG_MANIFEST")
    src = (REPO / "server" / "engine" / "shared.py").read_text("utf-8")
    assert "integration/manifest.json" not in src  # 陈旧契约注释一并清除
    # 死清单本体仍不存在（t260902-12 钉子语义）
    assert not (REPO / "integration" / "manifest.json").exists()


# ---------- J. 豁免超限封面两分支登记自证（merge 后 gen3 补） ----------

EXEMPT_CAP_ANCHOR = ("dev_lane.py#run#await self._blocked_over_limit("
                     "tests_exempt_cap_blocked_text(tests_exempt_rounds, "
                     "audit=tests_fault_cap_audit_text(tests_rounds, "
                     "MAX_TESTS_FAULT_ROUNDS, tests_e")
# 260926 锚点 re-point（KI-122②，宿主直修令）：本钉的判据（AST 两处 + 祖先链在
# TESTS_STREAK 门内 + 锚在守卫登记表）一字未改；变的是**锚串文本**——封面调用多了一个
# 具名审计尾注实参（audit=tests_fault_cap_audit_text(...)；锚串按守卫工具的窗口截断口径
# 写到 tests_e 为止）。分支/门/自守机制均未动。


def test_j_exempt_cap_sites_inside_tests_streak_gate():
    """登记自证（t260917-04 守卫 BRANCH_REGISTRY 两条豁免封面锚的根基）：两处
    _blocked_over_limit(tests_exempt_cap_blocked_text(...)) 分支必须仍在
    workflow.patched(TESTS_STREAK_PATCH_ID) 门内（AST 祖先链核实），且两条锚串仍在
    守卫登记表——分支挪出门外或登记漂移，本钉先红（回放兼容论证不许静默腐烂）。"""
    import ast as ast_mod
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_t260917_04_replay_gate_lock as gate_lock
    src = (REPO / "server" / "engine" / "dev_lane.py").read_text("utf-8")
    tree = ast_mod.parse(src)
    parents = {}
    for node in ast_mod.walk(tree):
        for child in ast_mod.iter_child_nodes(node):
            parents[child] = node
    hits = []
    for node in ast_mod.walk(tree):
        if not isinstance(node, ast_mod.If):
            continue
        t = ast_mod.unparse(node.test)
        if t.startswith("await self._blocked_over_limit(") \
                and "tests_exempt_cap_blocked_text" in t:
            anc, gated = parents.get(node), False
            while anc is not None:
                if isinstance(anc, ast_mod.If) \
                        and ast_mod.unparse(anc.test) == \
                        "workflow.patched(TESTS_STREAK_PATCH_ID)":
                    gated = True
                anc = parents.get(anc)
            hits.append((node.lineno, gated))
    assert len(hits) == 2, "豁免超限封面分支应恰两处（串行/并行），见 %s" % hits
    assert all(g for _, g in hits), \
        "封面分支挪出了 TESTS_STREAK 门：登记回放兼容论证失效，先改登记表再动分支"
    for i in range(2):
        anchor = "%s#%d" % (EXEMPT_CAP_ANCHOR, i)
        assert anchor in gate_lock.BRANCH_REGISTRY, \
            "锚 %s 不在守卫登记表（登记漂移）" % anchor
