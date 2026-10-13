# -*- coding: utf-8 -*-
"""t260930-01 台账绿行复用（L1 单元层，被测=integration/run_scenarios.py 的复用面）。

分层（intent 分工，防重复）：本文件只锁**纯函数判据与前置检查**——四键全等才可复用、
畸形行不炸、fail-closed 三态各带具名理由、全复用轮的自洽算术。端到端（真跑两轮看
INTEG_REUSE 行与闸回执）归 L3 场景 `t260930-01-ledger-reuse-round`；闸侧
`ran + reused == expected` 与回执面的组装行为归 `server/engine/tests/
test_260930_01_gate_reuse_completeness.py`（同票另文件）。

跑法：`server/engine/.venv/bin/python -m pytest server/engine/tests -q`（缺 venv 用任一
装 pytest 的解释器）。全程 stdlib + 临时目录夹具：零 docker、零 Temporal、零控制台
（红线：永不接触 3099）、零真账——`SANDBAR_SCENARIO_LEDGER_DIR` 指向临时目录。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]   # server/engine/tests → 仓根


def _rs():
    """按文件位装载被测执行器（不 import，避免 sys.path 侧效应污染同会话其他测试）。"""
    spec = importlib.util.spec_from_file_location(
        "_rs_under_test_t260930_01", REPO / "integration" / "run_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RS = _rs()
#: 真指纹（与执行器/闸/台账行同算法的现场值）。测试里凡「四键全等」的基准行一律钉
#: 真值——用假指纹造行只能测「两边都假」，测不出判据真的拿账行在比。
ENV_FP = RS._fp_mod.env_fingerprint(RS._env_fp_parts())["value"]

#: 一条「四键全等且绿」的基准行（各子用例只改动其中一维）。
GOOD = {
    "ts": "2026-09-30T10:00:00+08:00",
    "commit": "a" * 40,
    "env_fp": ENV_FP,
    "conc_width": 4,
    "pool": "ro",
    "scenario": "t-scn",
    "verdict": "pass",
    "wall_s": 1.5,
    "source": "lane:t260930-01",
    "ticket": "t260930-01",
}
COMMIT = "a" * 40
WIDTH = 4


def _row(**over):
    r = dict(GOOD)
    r.update(over)
    return r


# ---------------- A. 四键全等才可复用 ----------------

def test_a1_all_four_keys_equal_is_reusable():
    assert RS.reusable_names([_row()], COMMIT, ENV_FP, WIDTH) == ["t-scn"]


def test_a2_each_single_key_mismatch_blocks_reuse():
    """四键各差一维都不得复用（commit 精确相等：祖先/别的提交都不算）。"""
    assert RS.reusable_names([_row(commit="c" * 40)], COMMIT, ENV_FP, WIDTH) == []
    assert RS.reusable_names([_row(env_fp="d" * 64)], COMMIT, ENV_FP, WIDTH) == []
    assert RS.reusable_names([_row(conc_width=1)], COMMIT, ENV_FP, WIDTH) == []
    # 名字维度：本轮在册面里没有这条时，它不构成可复用（candidates 面）
    assert RS.reusable_names([_row(scenario="other")], COMMIT, ENV_FP, WIDTH,
                             candidates={"t-scn"}) == []


def test_a3_non_pass_verdicts_are_not_reusable():
    for v in ("fail", "env_fail", "skip"):
        assert RS.reusable_names([_row(verdict=v)], COMMIT, ENV_FP, WIDTH) == []


def test_a4_candidates_filter_and_sorted_dedup():
    rows = [_row(scenario="z"), _row(scenario="a"), _row(scenario="a"),
            _row(scenario="not-this-round")]
    assert RS.reusable_names(rows, COMMIT, ENV_FP, WIDTH) == ["a", "not-this-round", "z"]
    assert RS.reusable_names(rows, COMMIT, ENV_FP, WIDTH,
                             candidates={"z", "a"}) == ["a", "z"]


# ---------------- B. 畸形行：跳过、绝不炸 ----------------

@pytest.mark.parametrize("bad", [
    None, "not-a-dict", 42, [],
    {"scenario": "t-scn"},                                   # 缺 commit/env_fp/width/verdict
    {"scenario": "t-scn", "commit": COMMIT, "env_fp": ENV_FP, "conc_width": WIDTH},
    _row(commit=None), _row(env_fp=None), _row(conc_width=None),
    _row(verdict=None),
    _row(scenario=""),                                       # 空名不构成证据
    _row(scenario=None),
    _row(conc_width="4"),                                    # 宽度是字符串（类型错）
    _row(conc_width=True),                                   # bool 不是整数宽
    _row(conc_width=4.0),
    _row(conc_width=0),
])
def test_b1_malformed_rows_are_ignored_without_raising(bad):
    assert RS.reusable_names([bad], COMMIT, ENV_FP, WIDTH) == []


def test_b2_malformed_rows_do_not_hide_the_good_one():
    rows = [None, "junk", _row(scenario=""), _row()]
    assert RS.reusable_names(rows, COMMIT, ENV_FP, WIDTH) == ["t-scn"]


def test_b3_none_or_empty_rows_yield_empty():
    assert RS.reusable_names(None, COMMIT, ENV_FP, WIDTH) == []
    assert RS.reusable_names([], COMMIT, ENV_FP, WIDTH) == []


# ---------------- C. 名单面（打印上限） ----------------

def test_c1_short_list_is_printed_verbatim():
    assert RS._reuse_names_face(["a", "b"]) == "a,b"


def test_c2_over_cap_is_truncated_with_ellipsis_and_total():
    names = ["n%02d" % i for i in range(RS.REUSE_PRINT_CAP + 5)]
    face = RS._reuse_names_face(names)
    assert face.startswith("n00,n01,")
    assert face.endswith("…（共 %d 条）" % len(names))
    assert "n%02d" % (RS.REUSE_PRINT_CAP) not in face   # 第 21 条起不打印


def test_c3_exactly_at_cap_is_not_truncated():
    names = ["n%02d" % i for i in range(RS.REUSE_PRINT_CAP)]
    assert RS._reuse_names_face(names) == ",".join(names)


# ---------------- D. 树状态判定（真 git，临时仓） ----------------

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=60)


def _repo(tmp_path):
    r = tmp_path / "tree"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "ut@example.invalid")
    _git(r, "config", "user.name", "ut")
    (r / "f.txt").write_text("x\n", encoding="utf-8")
    _git(r, "add", "f.txt")
    _git(r, "commit", "-q", "-m", "base")
    return r


def test_d1_clean_tree_reports_head_and_not_dirty(tmp_path):
    r = _repo(tmp_path)
    head, dirty = RS._tree_state(str(r))
    assert head == _git(r, "rev-parse", "HEAD").stdout.strip()
    assert len(head) == 40 and dirty is False


def test_d2_dirty_tree_is_detected(tmp_path):
    r = _repo(tmp_path)
    (r / "f.txt").write_text("changed\n", encoding="utf-8")
    _, dirty = RS._tree_state(str(r))
    assert dirty is True


def test_d3_untracked_file_counts_as_dirty(tmp_path):
    """未跟踪件同样是「HEAD 描述不了这棵树」——复用不得由旧绿顶替它。"""
    r = _repo(tmp_path)
    (r / "new.txt").write_text("n\n", encoding="utf-8")
    assert RS._tree_state(str(r))[1] is True


def test_d4_non_repo_fails_closed(tmp_path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    head, dirty = RS._tree_state(str(d))
    assert head == "" and dirty is True


# ---------------- E. 前置检查三态（复用面 fail-closed 各带具名理由） ----------------

@pytest.fixture
def clean_repo(tmp_path):
    return _repo(tmp_path)


def _write_ledger(dir_, rows):
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / "scenario-results.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def _plan(monkeypatch, repo, ledger_dir, candidates, width=WIDTH, env_fp=None):
    monkeypatch.setenv("SANDBAR_SCENARIO_LEDGER_DIR", str(ledger_dir))
    return RS._reuse_plan(candidates, width, str(repo), env_fp_value=env_fp or ENV_FP)


def _row_head(repo):
    """临时仓的头部 sha（判据第一键的真值来源）。"""
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_e1_clean_tree_with_matching_green_row_reuses(clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is True and plan["names"] == ["t-scn"]
    assert plan["disabled_reason"] is None
    assert plan["git_head"] == _git(clean_repo, "rev-parse", "HEAD").stdout.strip()


def test_e2_commit_mismatch_means_no_reuse(clean_repo, tmp_path, monkeypatch):
    """账里的绿行必须落在**当前 HEAD 这个提交**上：老提交（祖先）不算。"""
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit="f" * 40)])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is True and plan["names"] == []
    # 零命中不是「禁用」：disabled_reason 空、zero_reason 具名（两态可分辨，防
    # 「每轮都自称被禁用」的假降级信号）
    assert plan["disabled_reason"] is None
    assert plan["zero_reason"]


def test_e3_env_fp_mismatch_means_no_reuse(clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(env_fp="e" * 64)])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is True and plan["names"] == []


def test_e4_width_mismatch_means_no_reuse(clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(conc_width=1)])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"], width=4)
    assert plan["enabled"] is True and plan["names"] == []


def test_e5_dirty_tree_disables_reuse_with_named_reason(clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    (clean_repo / "f.txt").write_text("dirty\n", encoding="utf-8")
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is False and plan["names"] == []
    assert "脏" in plan["disabled_reason"] and plan["disabled_reason"]


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "OFF", "False", "No"])
def test_e6_kill_switch_disables_reuse(value, clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.setenv("SANDBAR_LEDGER_REUSE", value)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is False and plan["names"] == []
    assert RS.LEDGER_REUSE_ENV in plan["disabled_reason"]


@pytest.mark.parametrize("value", ["0", "off", "false", "no"])
def test_e6_kill_switch_disables_reuse_but_keeps_git_head(value, clean_repo, tmp_path, monkeypatch):
    """261013 regression (the run_id_missing_from_summary chain): the kill switch
    disables REUSE but must NOT strip the HEAD identity — git_head is also the
    end-of-round run record's commit key. Pre-fix order resolved git_head only
    AFTER the reuse-off early return, so every line round (which pins REUSE=0)
    wrote no run record and the runner refused the round."""
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.setenv("SANDBAR_LEDGER_REUSE", value)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is False and plan["names"] == []
    assert RS.LEDGER_REUSE_ENV in plan["disabled_reason"]
    # the fix: the identity is resolved even when reuse is off
    assert plan["git_head"] == _git(clean_repo, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize("value", ["1", "on", "true", "yes", "anything", ""])
def test_e7_other_values_leave_reuse_enabled(value, clean_repo, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.setenv("SANDBAR_LEDGER_REUSE", value)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["enabled"] is True and plan["names"] == ["t-scn"]


def test_e8_absent_ledger_is_empty_account_not_silent(clean_repo, tmp_path, monkeypatch):
    """主账缺席=空账（新机器）：开着但零命中，且理由显式说明「缺席=空账」。"""
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, tmp_path / "no-such-dir", ["t-scn"])
    assert plan["enabled"] is True and plan["names"] == []
    assert plan["disabled_reason"] is None
    assert plan["zero_reason"] and "空账" in plan["zero_reason"]


def test_e9_undeterminable_fingerprint_disables_reuse(clean_repo, tmp_path, monkeypatch):
    """指纹判不出（协议库缺席的形态，以显式值模拟）=关，理由点名指纹。"""
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(commit=_row_head(clean_repo))])
    monkeypatch.setenv("SANDBAR_SCENARIO_LEDGER_DIR", str(ledger))
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    saved = RS._fp_mod
    try:
        RS._fp_mod = None
        plan = RS._reuse_plan(["t-scn"], WIDTH, str(clean_repo))
    finally:
        RS._fp_mod = saved
    assert plan["enabled"] is False and plan["names"] == []
    assert "指纹" in plan["disabled_reason"]


def test_e10_non_repo_tree_disables_reuse_with_named_reason(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row()])   # 树判不出来时账行内容无关（fail-closed）
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    nope = tmp_path / "plain"
    nope.mkdir()
    plan = _plan(monkeypatch, nope, ledger, ["t-scn"])
    assert plan["enabled"] is False and plan["names"] == []
    assert "HEAD" in plan["disabled_reason"]


def test_e11_candidates_scope_is_this_rounds_register(clean_repo, tmp_path, monkeypatch):
    """只在本轮在册面里取名（账里有他人绿行不构成复用）。"""
    ledger = tmp_path / "ledger"
    _write_ledger(ledger, [_row(scenario="not-registered",
                              commit=_row_head(clean_repo))])
    monkeypatch.delenv("SANDBAR_LEDGER_REUSE", raising=False)
    plan = _plan(monkeypatch, clean_repo, ledger, ["t-scn"])
    assert plan["names"] == []


# ---------------- F. 汇总行/执行器面薄读（防回归：键与算术） ----------------

def test_f1_summary_line_carries_reused_plus_arithmetic():
    """内置假表跑一轮 main()：全没复用（假场景名不在账里）→ reused=0 键在场、
    SCENARIOS 行带 ` reused=0`、expected 仍是本轮在册数（additive 契约）。"""
    import contextlib
    import io
    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="t260930ut-") as td:
        scen = []
        for i, script in enumerate(("print('a')\n", "print('b')\n")):
            p = Path(td) / ("s%d.py" % i)
            p.write_text(script, encoding="utf-8")
            scen.append(("t260930-ut-%d" % i, "假场景（UT 注入）",
                         "python3 %s" % p, "serial"))
        saved = RS.SCENARIOS
        saved_sweep, saved_hyg = RS._sweep_residue_stages, RS._docker_hygiene
        saved_pre, saved_tear = RS.batch_preboot, RS.batch_teardown
        cwd = os.getcwd()
        env_saved = {k: os.environ.get(k) for k in
                     ("SANDBAR_SCENARIO_LEDGER_DIR", "SANDBAR_SCENARIO_ONLY")}
        buf = io.StringIO()
        try:
            RS.SCENARIOS = scen
            RS._sweep_residue_stages = lambda: None
            RS._docker_hygiene = lambda: None
            RS.batch_preboot = lambda consumers: True
            RS.batch_teardown = lambda: None
            os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(
                Path(td) / "empty-ledger")
            os.environ.pop("SANDBAR_SCENARIO_ONLY", None)
            os.chdir(td)
            with contextlib.redirect_stdout(buf):
                rc = RS.main()
        finally:
            RS.SCENARIOS = saved
            RS._sweep_residue_stages, RS._docker_hygiene = saved_sweep, saved_hyg
            RS.batch_preboot, RS.batch_teardown = saved_pre, saved_tear
            os.chdir(cwd)
            for k, v in env_saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        out = buf.getvalue()
    assert rc == 0, out[-2000:]
    summary = None
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            summary = json.loads(ln[len("INTEG_SUMMARY "):])
    assert summary is not None, out[-2000:]
    assert summary["reused"] == 0 and summary["expected"] == 2
    assert summary["ran"] == summary["expected"]          # ran + reused == expected
    scenarios_line = [ln for ln in out.splitlines() if ln.startswith("SCENARIOS ran=")]
    assert scenarios_line and scenarios_line[0].endswith(" reused=0")


def test_f2_fully_reused_round_arithmetic_and_loud_line(tmp_path, monkeypatch):
    """全复用轮：ran=0/reused=expected、rc=0、INTEG_REUSE 行在场、规范行零条、
    报告 JSON 带全名单（**本轮一条都不跑**仍要给正常绿回执）。

    树面用**临时真 git 仓**（`_REPO_ROOT` 注入）——本用例不得因开发树脏而红。
    """
    import contextlib
    import io
    import os

    td_path = tmp_path / "fixture"
    td_path.mkdir()
    scratch = _repo(tmp_path)                    # 干净的真 git 仓（HEAD 可判、树干净）
    ledger_dir = td_path / "ledger"
    scen = []
    for i in range(2):
        p = td_path / ("s%d.py" % i)
        p.write_text("print('should not run')\n", encoding="utf-8")
        scen.append(("t260930-ut-reuse-%d" % i, "假场景（UT 注入）",
                     "python3 %s" % p, "serial"))
    # 先算本轮会用的指纹（与执行器同算法），再造两行同 commit+同指纹+同宽绿行
    # ——**精确复刻**判据四键（账行不是猜出来的，是按同一算法算出来的）。
    env_fp = RS._fp_mod.env_fingerprint(RS._env_fp_parts())["value"]
    head = _git(scratch, "rev-parse", "HEAD").stdout.strip()
    _write_ledger(ledger_dir, [
        _row(scenario=n, commit=head, env_fp=env_fp, conc_width=4)
        for n, _i, _c, _p in scen])

    saved = RS.SCENARIOS
    saved_sweep, saved_hyg = RS._sweep_residue_stages, RS._docker_hygiene
    saved_pre, saved_tear = RS.batch_preboot, RS.batch_teardown
    saved_root = RS._REPO_ROOT
    cwd = os.getcwd()
    env_saved = {k: os.environ.get(k) for k in
                 ("SANDBAR_SCENARIO_LEDGER_DIR", "SANDBAR_SCENARIO_ONLY",
                  "SANDBAR_LEDGER_REUSE", "SANDBAR_POOL_CONC")}
    buf = io.StringIO()
    try:
        RS.SCENARIOS = scen
        RS._REPO_ROOT = str(scratch)
        RS._sweep_residue_stages = lambda: None
        RS._docker_hygiene = lambda: None
        RS.batch_preboot = lambda consumers: True
        RS.batch_teardown = lambda: None
        os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(ledger_dir)
        os.environ.pop("SANDBAR_SCENARIO_ONLY", None)
        os.environ.pop("SANDBAR_LEDGER_REUSE", None)
        os.environ["SANDBAR_POOL_CONC"] = "4"
        os.chdir(td_path)
        with contextlib.redirect_stdout(buf):
            rc = RS.main()
        report = sorted(Path("out").glob("integration-report-*.json"))
        report = [td_path / r for r in report]   # 钉成绝对路径（出块后 cwd 已还原）
    finally:
        RS.SCENARIOS = saved
        RS._REPO_ROOT = saved_root
        RS._sweep_residue_stages, RS._docker_hygiene = saved_sweep, saved_hyg
        RS.batch_preboot, RS.batch_teardown = saved_pre, saved_tear
        os.chdir(cwd)
        for k, v in env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    out = buf.getvalue()
    assert rc == 0, out[-2000:]
    assert "INTEG_REUSE 复用台账绿行 2 条" in out
    assert "PASS [" not in out                      # 一条都没实跑
    assert "FAIL [" not in out
    summary = None
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            summary = json.loads(ln[len("INTEG_SUMMARY "):])
    assert summary is not None
    assert (summary["ran"], summary["reused"], summary["expected"]) == (0, 2, 2)
    scenarios_line = [ln for ln in out.splitlines() if ln.startswith("SCENARIOS ran=")]
    assert scenarios_line[0].startswith("SCENARIOS ran=0 ") \
        and scenarios_line[0].endswith(" reused=2")
    # 报告 JSON 带复用计数 + **全名单**（stdout 名单有上限，报告没有）
    assert report, "报告 JSON 未落档"
    doc = json.loads(report[-1].read_text(encoding="utf-8"))
    assert doc["reused"] == 2
    assert sorted(doc["reused_names"]) == sorted(n for n, _i, _c, _p in scen)


# ---------------- G. 闸侧判据（verify_lane 的复用面，纯函数） ----------------

def _vl():
    spec = importlib.util.spec_from_file_location(
        "_vl_under_test_t260930_01", REPO / "server" / "tools" / "verify_lane.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VL = _vl()


def test_g1_reuse_counts_absent_key_is_old_runner():
    """老执行器（无 reused 键）→ (0, None, False)：闸走改前路径，逐字节同改前。"""
    assert VL._parse_reuse_counts(None) == (0, None, False)
    assert VL._parse_reuse_counts({"ran": 3, "expected": 3}) == (0, None, False)


def test_g2_reuse_counts_present_and_malformed():
    assert VL._parse_reuse_counts(
        {"ran": 0, "expected": 2, "reused": 2, "reused_names": ["a", "b"]}) \
        == (2, ["a", "b"], True)
    # 键在场但读不懂：had_key 仍 True（不许静默当「没这特性」），计数 0
    for bad in ("2", -1, True, None, 1.0):
        n, names, had = VL._parse_reuse_counts({"reused": bad, "expected": 2})
        assert (n, names, had) == (0, None, True)
    assert VL._parse_reuse_counts({"reused": 2, "reused_names": "a,b"}) == (2, None, True)


def test_g3_reuse_accounted_truth_table():
    """全复用轮的「可交代」判据：expected==reused + 专行在场 + 未截断。"""
    full = ([True, False],)      # 专行在场、未截断
    assert VL._reuse_accounted(0, 5, [False, False]) is True      # 非全复用轮恒 True
    assert VL._reuse_accounted(3, 3, [True, False]) is True
    assert VL._reuse_accounted(3, 3, [True, True]) is True        # 截断由汇总名单兜底
    assert VL._reuse_accounted(3, 4, [True, False]) is False      # 数不上账
    assert VL._reuse_accounted(3, None, [True, False]) is False   # 没在册数
    assert VL._reuse_accounted(3, 3, [False, False]) is False     # 没有响亮专行


def test_g4_zero_signal_accepts_a_fully_reused_round():
    """`ran=0` + 汇总 `reused=N>0`：parser 必须放它进闸的判定面（否则全复用轮
    永远到不了 `ran + reused == expected` 判据——KI-116 拆掉的逃逸口是「零信号
    静默绿」，不是「有交代的复用」）。"""
    out = ("INTEG_REUSE 复用台账绿行 2 条（同 commit 同环境指纹同宽，未实跑）：a,b\n"
           "SCENARIOS ran=0 pass=0 fail=0 env_fail=0 na=0 (1s) reused=2\n"
           'INTEG_SUMMARY {"ran": 0, "pass": 0, "fail": 0, "not_checked": 0,'
           ' "expected": 2, "reused": 2}\n')
    ran, passed, failed, env_failed, scen, err = VL._parse_integ_run(out, 0)
    assert (ran, passed, failed, env_failed, scen, err) == (0, 0, 0, 0, [], None)


def test_g5_zero_signal_still_red_for_a_truly_idle_executor():
    """空转执行器（无行、无规范行、汇总 ran=0 且无 reused）照旧显式红。"""
    out = ('SCENARIOS ran=0 pass=0 fail=0 env_fail=0 na=0 (0s) reused=0\n'
           'INTEG_SUMMARY {"ran": 0, "pass": 0, "fail": 0, "not_checked": 0,'
           ' "expected": 0, "reused": 0}\n')
    _r, _p, _f, _e, _s, err = VL._parse_integ_run(out, 0)
    assert err and "zero scenario signal" in err
    # 而**跑红**的非零退出仍不被复用面洗白
    _r, _p, _f, _e, _s, err2 = VL._parse_integ_run("", 1)
    assert err2 and "no result" in err2


def test_g6_reuse_line_names_parsing_and_truncation_marker():
    names, head = [], [False, False]
    VL._track_reuse_lines(
        "INTEG_REUSE 复用台账绿行 2 条（同 commit 同环境指纹同宽，未实跑）：a,b",
        names, head)
    assert names == ["a", "b"] and head == [True, False]
    names, head = [], [False, False]
    VL._track_reuse_lines(
        "INTEG_REUSE 复用台账绿行 30 条（同 commit 同环境指纹同宽，未实跑）："
        "n0,n1…（共 30 条）", names, head)
    assert names == ["n0", "n1"] and head == [True, True]
