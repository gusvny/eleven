#!/usr/bin/env python3
"""t260922-12 执行器「只跑点名」旋钮机械自证（integration/run_scenarios.py）。

覆盖（票据④的执行器半边；池排除口径与场景判定零改动的机械锁）：
- A 点名生效：假表三条点名一条 → ran/expected=1、点名行原文、其余条目零行；
- B 缺省零分支：无 env/CLI 点名 → 无点名行、SUMMARY 无 only_scenarios 键
  （缺省路径与改前逐键全等锚，借 t260913-03 验收 B 先例）；
- C 名单含不在册条目 → 一条都未跑 rc=2、FAIL 点名、假脚本零执行（marker 缺席）、
  卫生/批台钩子零触达（fail-closed 在任何 docker 面之前返回）；
- D expected 不变式：点名轮 ran==expected==点名∩非排除池；
- E 与池排除叠加：点名两条其中一条属被排除池 → 只跑 1 条并点名归属；
- F env 注入路：main() 无参时读 SANDBAR_SCENARIO_ONLY（闸定点复跑的注入面）；
- G 解析面：strip/去空/去重保序；空串/None=空名单=全量。

注入式电池（假表+假脚本落临时目录；SCENARIOS try/finally 还原；sweep/hygiene/
批台钩子置空）——零 docker 零端口零控制台，秒级；零真注册表条目被执行。
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ONLY_ENV = "SANDBAR_SCENARIO_ONLY"

_spec = importlib.util.spec_from_file_location(
    "rs_only_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


@contextlib.contextmanager
def _env_stub(extra):
    saved = {k: os.environ.get(k) for k in extra}
    for k, v in extra.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Harness:
    """注入假场景表跑 main()（模式借 t260913-03 电池 drive()）。"""

    def __init__(self):
        self.preboot_calls = []

    def drive(self, entries, only_kw=None, only_env="__unset__", exclude=None):
        """only_kw=main() 关键字路（None=不传=读 env）；only_env=env 注入路
        （__unset__ 哨兵=清除该键，测缺省零分支）。"""
        with tempfile.TemporaryDirectory(prefix="t922only-") as td:
            td_path = Path(td)
            table, markers = [], {}
            for i, (name, pool, script) in enumerate(entries):
                p = td_path / ("s%d.py" % i)
                marker = td_path / ("marker-%s" % name)
                # 执行即留痕：脚本末尾写 marker（「真跑了」的机械证据面）
                p.write_text("from pathlib import Path\n"
                             "Path(%r).write_text('ran')\n" % str(marker))
                item = (name, "假场景（t260922-12 注入）", "python3 %s" % p)
                if pool:
                    item = item + (pool,)
                table.append(item)
                markers[name] = marker
            saved = (rs.SCENARIOS, rs._sweep_residue_stages, rs._docker_hygiene)
            saved_pre = (rs.batch_preboot, rs.batch_teardown) \
                if hasattr(rs, "batch_preboot") else None
            rs.SCENARIOS = table
            rs._sweep_residue_stages = lambda: None
            rs._docker_hygiene = lambda: None
            if saved_pre:
                rs.batch_preboot = lambda consumers: (self.preboot_calls.append(1), True)[1]
                rs.batch_teardown = lambda: None
            env = {"SANDBAR_POOL_CONC": "1", "SANDBAR_CONC_POOLS": ""}
            env[ONLY_ENV] = None if only_env == "__unset__" else only_env
            if exclude is not None:
                env["SANDBAR_SCENARIO_EXCLUDE_POOLS"] = exclude
            cwd_saved = os.getcwd()
            buf = io.StringIO()
            try:
                os.chdir(td)
                with _env_stub(env):
                    with contextlib.redirect_stdout(buf):
                        rc = rs.main(only_scenarios=only_kw)
            finally:
                (rs.SCENARIOS, rs._sweep_residue_stages, rs._docker_hygiene) = saved
                if saved_pre:
                    rs.batch_preboot, rs.batch_teardown = saved_pre
                os.chdir(cwd_saved)
            out = buf.getvalue()
            ran_markers = sorted(n for n, m in markers.items() if m.exists())
            return rc, out, ran_markers


def summary_of(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


TRIO = [("t922-a", None, "print('a')"),
        ("t922-b", "ro", "print('b')"),
        ("t922-c", "engine", "print('c')")]


@pytest.fixture()
def h():
    return Harness()


# ---------------- A 点名生效 ----------------

def test_a_only_named_runs(h):
    rc, out, ran = h.drive(TRIO, only_kw="t922-b")
    assert rc == 0 and ran == ["t922-b"]
    assert "本轮只跑点名 1 条（点名=t922-b）" in out
    assert "PASS [t922-b]" in out and "PASS [t922-a]" not in out
    s = summary_of(out)
    assert s["ran"] == 1 and s["expected"] == 1
    assert s["only_scenarios"] == ["t922-b"]


# ---------------- B 缺省零分支 ----------------

def test_b_default_path_has_no_only_trace(h):
    rc, out, ran = h.drive(TRIO, only_kw=None)
    assert rc == 0 and sorted(ran) == ["t922-a", "t922-b", "t922-c"]
    assert "只跑点名" not in out and "点名 [" not in out
    s = summary_of(out)
    assert "only_scenarios" not in s and s["expected"] == 3


# ---------------- C 名单含不在册条目 → 一条不跑 ----------------

def test_c_unknown_name_fails_closed(h):
    rc, out, ran = h.drive(TRIO, only_kw="t922-a,no-such-scenario")
    assert rc == 2 and ran == [], "一条都未跑"
    assert "点名名单含不在册条目：no-such-scenario" in out
    assert "ONLY_SUMMARY" in out and '"missing"' in out
    assert "SCENARIOS ran=0" in out
    assert h.preboot_calls == [], "fail-closed 必须先于批台/卫生钩子"


def test_c2_empty_explicit_only_is_full_run(h):
    rc, out, ran = h.drive(TRIO, only_kw="")
    assert rc == 0 and len(ran) == 3, "空名单=全量（与未指定同效）"


# ---------------- D/E expected 不变式与池排除叠加 ----------------

def test_e_only_plus_exclude_pool(h):
    rc, out, ran = h.drive(TRIO, only_kw="t922-a,t922-c", exclude="engine")
    assert rc == 0 and ran == ["t922-a"]
    assert "其中 1 条属被排除池未跑" in out
    s = summary_of(out)
    assert s["ran"] == 1 and s["expected"] == 1
    assert s["only_scenarios"] == ["t922-a", "t922-c"]


def test_d_expected_counts_named_not_registry(h):
    rc, out, ran = h.drive(TRIO, only_kw="t922-a,t922-b")
    s = summary_of(out)
    assert s["expected"] == 2 and s["ran"] == 2


# ---------------- F env 注入路（闸定点复跑的注入面） ----------------

def test_f_env_injection_path(h):
    """main() 无关键字时读 SANDBAR_SCENARIO_ONLY（verify.yaml cmd 零改动的注入缝）。"""
    rc, out, ran = h.drive(TRIO, only_kw=None, only_env="t922-c")
    assert rc == 0 and ran == ["t922-c"]
    assert "本轮只跑点名 1 条（点名=t922-c）" in out
    s = summary_of(out)
    assert s["only_scenarios"] == ["t922-c"]


# ---------------- G 解析面 ----------------

def test_g_parse_only_scenarios():
    assert rs.parse_only_scenarios(" a , b ,a,, ") == ["a", "b"]
    assert rs.parse_only_scenarios("") == []
    assert rs.parse_only_scenarios(None) == []
    assert rs.parse_only_scenarios("x") == ["x"]
