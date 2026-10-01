# -*- coding: utf-8 -*-
"""L2 回归（261001 输出形状事故）：**拒绝开跑不是场景红**——拒绝行不得长成场景名。

事故（t261001-10 第 5/6/7 轮实证，见 notes/debts/known-issues.md KI-170 附记）：
  执行器的三处「拒绝开跑」过去一律以 `FAIL [__executor__] …` 起首。闸侧
  `verify_lane._parse_integ_run` 把**任何** `FAIL [` 行当一条场景结果收——行不合
  `FAIL [名] exit=N` 形状时，名字退化成**整行**。于是那段人话（先是递归护栏说明、
  后是「点名名单含不在册条目」说明）被当成「场景名」：
    · 进 `prev_red_names` → 下一轮快反馈面里带上它；
    · 它不在册 ⇒ 执行器 `--only` fail-closed ⇒ 产出的又是同形状的一段人话；
    · 于是**每轮复读同一个不在册的名字**，票永远停在 blocked（fail-closed 本身是对的，
      被毒的是**名字的来路**）。

本文件的锁（行为锁，不锚实现细节）：
  ① 三种拒绝（深度护栏 / 并发帽 / 点名不在册）打印的**不是**场景形行（`PASS [`/`FAIL [`/
     `ENV_FAIL [` 起首），且经闸解析器解析后 `ran==0`（=闸错误，不是场景红）；
  ② 万一仍出现畸形 `FAIL [` 行（老代码/夹具树里的旧副本），解析器给它的名字必须落在
     **合成面**（`__malformed__ …`），而 `shared.targeted_rerun_plan` 按设计剔 `__` 条目 ⇒
     它不可能被当成场景名带回下一轮面；
  ③ 反向锁：**可解析**的行（含 `ENV_FAIL [名] exit=1` 这种契约畸形）名字照旧=真名，
     不许被 ② 的兜底吞掉（红照记、名字不丢）。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib_env import clean_narrowing_env  # noqa: E402  (L12：起执行器必须走清理单点)

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
RUNNER = INTEG / "run_scenarios.py"
SCENARIO_SHAPED = ("PASS [", "FAIL [", "ENV_FAIL [")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vl():
    return _load("vl_probe", REPO / "server" / "tools" / "verify_lane.py")


def _shared():
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import shared  # noqa: E402
    return shared


def _run_runner(extra_env=None, args=("--only", "no-such-scenario-for-refusal-shape-test")):
    # L12 单点：剥掉继承来的收窄旋钮再并入本电池显式声明的那一档（这条纪律本身就是
    # KI-170 的对象——电池若不走单点，它自己会成为下一代风暴的一个入口）
    env = clean_narrowing_env(extra=extra_env or {})
    r = subprocess.run([sys.executable, str(RUNNER), *args],
                       capture_output=True, text=True, env=env, cwd=str(REPO))
    return r.returncode, r.stdout + r.stderr


def test_s1_only_unknown_refusal_is_not_scenario_shaped():
    """①-a 点名不在册：拒绝行不是场景形行，且闸解析器读到的场景数=0（闸错误，不是红）。"""
    rc, out = _run_runner()
    assert rc == 2, out
    assert "REFUSED [__executor__]" in out
    assert "点名名单含不在册条目" in out
    bad = [ln for ln in out.splitlines() if ln.startswith(SCENARIO_SHAPED)]
    assert bad == [], "拒绝行不得长成场景结果行：%r" % bad[:2]
    ran, passed, failed, env_failed, scen, err = _vl()._parse_integ_run(out, rc)
    assert (ran, passed, failed, env_failed, scen) == (0, 0, 0, 0, [])
    assert err, "拒绝开跑必须落成闸错误（不可判），不是静默"


def test_s2_depth_guard_refusal_is_not_scenario_shaped():
    """①-b 深度护栏：同一形状纪律（这条在风暴现场最常出现）。"""
    rc, out = _run_runner({"INTEG_RUN_DEPTH": "4"})
    assert rc == 2, out
    assert "REFUSED [__executor__]" in out and "递归护栏" in out
    bad = [ln for ln in out.splitlines() if ln.startswith(SCENARIO_SHAPED)]
    assert bad == [], "拒绝行不得长成场景结果行：%r" % bad[:2]
    ran, _p, _f, _e, scen, _err = _vl()._parse_integ_run(out, rc)
    assert ran == 0 and scen == []


def test_s3_malformed_fail_line_name_is_synthetic_face():
    """② 畸形 `FAIL [` 行（老副本/非场景输出打进去）：红照记，名字必须落合成面。"""
    poison = ("FAIL [__executor__] 递归护栏（深度上限 4）：本进程是第 4 层执行器——"
              "场景/夹具再起执行器时层层嵌套，本层拒绝开跑。")
    ran, _p, failed, _e, scen, err = _vl()._parse_integ_run(poison + "\n", 1)
    assert (ran, failed) == (1, 1) and err is None, "畸形行不静默吞：红照记"
    name = scen[0]["name"]
    assert name.startswith("__malformed__ "), name
    assert "递归护栏" in name, "原文进名字面（诊断不丢）"
    assert scen[0]["output_tail"].strip() == poison, "原文进 output_tail"
    # 合成面按设计不进收窄面（`__` 条目在面计划里被剔；这里用真面计划函数锁行为）
    shared = _shared()
    assert shared.targeted_rerun_plan(["integration/t260910-04/"],
                                      [name, "capture-board-assert"],
                                      first_run=False) == ["capture-board-assert"]


def test_s4_parseable_lines_keep_their_real_names():
    """③ 反向锁：可解析的行名字照旧=真名（含 ENV_FAIL 带非 2 退出码的契约畸形）。"""
    ran, _p, failed, env_failed, scen, err = _vl()._parse_integ_run(
        "PASS [t1] (1.0s)\nFAIL [t2] exit=1\nENV_FAIL [t3] exit=2\nENV_FAIL [t4] exit=1\n", 1)
    # ENV_FAIL 带非 2 退出码 = 契约畸形：计 failed（不是 env_failed），名字照旧
    assert (ran, failed, env_failed) == (4, 2, 1), (ran, failed, env_failed)
    assert [s["name"] for s in scen] == ["t1", "t2", "t3", "t4"], scen
    assert err is None
    assert not any(s["name"].startswith("__malformed__") for s in scen)
