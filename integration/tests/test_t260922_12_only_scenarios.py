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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
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

    def drive(self, entries, only_kw=None, only_env="__unset__", exclude=None,
              known_red=False, roster_names=()):
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
            if known_red:
                # 夹具册子（booked）落临时目录，经 SANDBAR_KNOWN_RED_ROSTER 路径缝投喂
                roster = td_path / "known-red.json"
                # 册子 schema（真源=run_scenarios.known_red_names）：{"entries":[{name,verdict}]}
                roster.write_text(json.dumps(
                    {"meta": {"v": 1},
                     "entries": [{"name": n, "verdict": "booked", "home": "lane"}
                                 for n in roster_names]}), encoding="utf-8")
                env["SANDBAR_KNOWN_RED_EXCLUDE"] = "1"
                env["SANDBAR_KNOWN_RED_ROSTER"] = str(roster)
            cwd_saved = os.getcwd()
            buf = io.StringIO()
            try:
                os.chdir(td)
                # 260930 次序：先剥继承旋钮，再上夹具显式档
                with no_narrowing_env():
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

def test_h_empty_narrowed_face_falls_back_to_full_registry(h):
    """宿主 260930 实报（真票 t260930-14 第 4 轮）：**收窄面被清空 = 面不可判，不是产品红**。

    形态（与真票同形）：点名面 = 上轮红名（本例 a、b 两条，且**两条都在挂账册里**）⇒ 点名面
    扣完为空。改前=「一轮零场景」→ 闸判红 → 票 blocked；改后=**回落全量注册面**
    （全量 − 在册豁免 = 剩下那些照跑）并具名。
    判据：①回落面真跑（marker 齐）；②`INTEG_NARROWED_EMPTY` 具名行在文、说清「扣完为空 →
    全量」；③汇总 `ran == expected > 0`（**绝不许出现 0 ran**）；④回执带具名键。"""
    rc, out, ran = h.drive(TRIO, only_env="t922-a,t922-b", known_red=True,
                           roster_names=["t922-a", "t922-b"])
    assert rc == 0, out[-400:]
    assert ran == ["t922-c"], "收窄面清空后必须回落全量：未被豁免的那条要真跑（实得 %r）" % ran
    assert "INTEG_NARROWED_EMPTY" in out, "必须具名（不许静默跑全量）"
    assert "回落**全量注册面**" in out and "未跑 ≠ 判绿" in out
    summ = summary_of(out)
    assert summ and summ.get("ran") == 1 and summ.get("expected") == 1, summ
    assert summ.get("narrowed_face_empty") is True, "回执要带具名键（消费方可判）"
    assert summ.get("known_red_skipped") == 2, "豁免计数照实（去哪了要说得清）"


def test_h1_vacuous_face_is_named_not_a_product_red(h):
    """退化形态（全员在册/被排除）：回落面**也为空** ⇒ 具名「面真空」，与启动级零信号分开。

    这一档跑不了任何东西（没有更宽的面可用）——它必须**具名**，让闸侧/人把「有意豁免」
    与「执行器起不来/零信号」分开；**未跑 ≠ 判绿**在此照旧（0 ran 永远不是绿）。"""
    names = [e[0] for e in TRIO]
    rc, out, ran = h.drive(TRIO, only_env=",".join(names), known_red=True, roster_names=names)
    assert rc == 0, out[-400:]
    assert ran == [], "面真空：确实没有任何条目可跑"
    assert "INTEG_NARROWED_EMPTY" in out and "INTEG_FACE_VACUOUS" in out, out[-500:]
    assert "不是产品红" in out and "未跑 ≠ 判绿" in out
    summ = summary_of(out)
    assert summ and summ.get("ran") == 0 and summ.get("expected") == 0, summ
    assert summ.get("face_vacuous") is True and summ.get("narrowed_face_empty") is True, summ


def test_h2_partial_narrowing_still_narrows(h):
    """负锁：点名面**部分**在册 ⇒ 仍然只跑剩下的那条（回落只在**空**时才发生）。"""
    rc, out, ran = h.drive(TRIO, only_env="t922-a,t922-b", known_red=True,
                           roster_names=["t922-a"])
    assert rc == 0, out[-400:]
    assert ran == ["t922-b"], "只跑未被豁免的那条（实得 %r）" % ran
    assert "INTEG_NARROWED_EMPTY" not in out
    summ = summary_of(out)
    assert summ and summ.get("ran") == 1 and summ.get("expected") == 1, summ


#: 四条假场景（比 TRIO 多一条）：用来把「回落轮的豁免面按全量面重算」与「按旧窄面算」分开——
#: 三条册子不够（豁免全册 ⇒ 面真空），必须留下第四条真跑，两种口径才有可分辨的 ran 差。
QUAD = TRIO + [("t922-d", None, "print('d')")]


def test_h3_fallback_recomputes_the_exemption_scope_on_the_wide_face(h):
    """回落轮的**在册豁免口径跟着面一起重算**（integration 复核发现，与 A/B 同源）。

    豁免纪律本就是「按**本轮的面**取册子交集」（改宽之前的 `_kr_in_round`）。回落把面从
    「点名 2 条」换成「全量 4 条」之后，若仍沿用旧窄面算出的 2 条，则：
      ① 册子里第 3 条（t922-c）在回落轮被**原样再跑一遍**——「在册红不进每轮路径」这条纪律
         在回落轮上单独失效（既烧一整轮的时间，又把在册红再红一遍）；
      ② 回执里「本轮跳过在册红 N 条」与真实面不符（说 2 实为 3）。
    判据：回落轮只跑真正不在册的那条（t922-d），豁免计数=3。"""
    rc, out, ran = h.drive(QUAD, only_env="t922-a,t922-b", known_red=True,
                           roster_names=["t922-a", "t922-b", "t922-c"])
    assert rc == 0, out[-400:]
    assert ran == ["t922-d"], ("回落轮必须重算豁免面：册内三条都不该跑（实得 %r）" % ran)
    assert "INTEG_NARROWED_EMPTY" in out and "回落轮的豁免面按**全量面**重算" in out
    summ = summary_of(out)
    assert summ and summ.get("ran") == 1 and summ.get("expected") == 1, summ
    assert summ.get("known_red_skipped") == 3, summ
    assert summ.get("narrowed_face_empty") is True, summ


def test_g_parse_only_scenarios():
    assert rs.parse_only_scenarios(" a , b ,a,, ") == ["a", "b"]
    assert rs.parse_only_scenarios("") == []
    assert rs.parse_only_scenarios(None) == []
    assert rs.parse_only_scenarios("x") == ["x"]
