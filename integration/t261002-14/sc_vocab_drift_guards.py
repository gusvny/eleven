#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_vocab_drift_guards.py —— t261002-14 三张防漂移锁 + watchdog 点名票号（integration 岗位资产）

intent（验证什么）
    t261001-08 巡检实证了三处「已经漂过一次、还会再漂」的重复面，本场景把它们锁成
    用户可感知的契约（不是替 developer 复核实现）：
      A  ok() 助手去重：三个消费场景里不再留逐字副本，共享助手在 lib_result 单点在场；
      B  收窄旋钮词表的**跨语言锁**：python 侧与 mjs 侧任一侧单独改动都必须红
         （t261001-08 的原话：no mechanical lock —— 曾经漂过）；
      C  授予操作词表的**三面锁**：引擎 py / 面板 grants.ts / executor-grants.ts 三面
         任一面单独漂移（改名/丢词/别名漂移/次序漂移/字面量写坏）都必须红；
         旧 drift test 只断言 python 侧，等于没有锁；
      D  lane/watchdog 的 unreadable 发现**必须在 subject 里点名票号**：
         「1 unreadable ticket(s) — permanent」藏住主语已经第二次让人工追号
         （t261001-08 实锤：五个候选票单独读都正常，是清单面缺口而非坏票）。

high-level steps（如何到达并断言）
    A  读三个具名场景文件：`def ok(` 零命中；lib_result 的共享助手可导入。
    B  真 lib_env.py × 真 lib_env.mjs → 报告空（锁住）；合成漂移：只改 py 侧 → 红、
       只改 mjs 侧 → 红、任一侧字面量写坏 → 红（fail-closed，绝不空报告假绿）。
    C  真三面源码 → 报告空；合成漂移：引擎侧丢词 → 红、面板别名漂移 → 红、
       executor-grants.ts 次序漂移 → 红、任一面字面量写坏 → 红。
    D  夹具 meta（真票号前缀的 detail 行，与 activities.py 的写入格式同形）：
       permanent subject 含票号、transient subject 含票号、12 条超帽 → 最多 10 个票号
       + `+N more`、畸形 detail 行 → subject 结构完好、不伪造票号（无 None/nan 字样）；
       老回执单行形态 subject 保持逐字契约（重放确定性，只锁不点名这一形不动）。
    末行 `SUMMARY pass=N fail=M env_fail=K na=J`；fail>0 → exit 1；
    被测文件缺席（判据面不在）→ ENV_FAIL exit 2；文件在但守卫函数缺席 → FAIL
    （=本票交付物缺席，是断言红不是环境红）。

intent 分工（防 intent 级重复，与既有资产不互替）
    · 守卫纯函数的真值表矩阵与解析器细节 → developer L1（随本票交付的两个 lock 测试
      文件），本场景不重测每条解析分支；
    · 引擎授权闸语义（谁能做什么）归 executor-authority-gate；词表**内容本身**是设计稿
      决定，本场景只锁「三面一致」这层漂移契约；
    · watchdog 三族发现的判定语义归 t261001-05 家族 L1；本条只锁 unreadable 发现的
      **subject 点名形状**。
    零 docker、零 Temporal、零端口、零浏览器；不触 3099/7233；零临时文件（全内存合成
    漂移，无 mkdtemp 面）。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(INTEG))

passed = failed = env_failed = na = 0


def ok(cond, label, detail=""):
    global passed, failed
    # 注：本文件不在 t261002-14 (a) 项点名的三个消费场景之列；待共享助手定稿后可换用，
    # 但保留本地极简断言不构成该票要除名的重复面。
    if cond:
        passed += 1
        print("  ok  %s" % label, flush=True)
    else:
        failed += 1
        print("  FAIL %s %s" % (label, str(detail)[:600]), flush=True)
    return bool(cond)


def env_face(label, detail=""):
    global env_failed
    env_failed += 1
    print("  ENV_FAIL %s %s" % (label, str(detail)[:300]), flush=True)


def read_or_envfail(path):
    if not path.is_file():
        env_face("file missing", str(path))
        return None
    return path.read_text(encoding="utf-8")


def load_module(path, name):
    """按文件路径加载模块（路径带连字符目录，不能普通 import）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    # ---------- 被测面在场性（缺席=ENV_FAIL，判据面不在） ----------
    srcs = {}
    for key, path in [
        ("lib_env_py", INTEG / "lib_env.py"),
        ("lib_env_mjs", INTEG / "lib_env.mjs"),
        ("engine_grants", ENGINE / "executor_grants.py"),
        ("panel_fixed", REPO / "server/plugins/executor-panel/src/host/grants.ts"),
        ("panel_decl", REPO / "server/plugins/executor-panel/src/host/executor-grants.ts"),
        ("watchdog", ENGINE / "inspection_lane_watchdog.py"),
        ("lib_result", INTEG / "lib_result.py"),
    ]:
        srcs[key] = read_or_envfail(path)
    if env_failed:
        finish()
    for name in ["t260930-01/sc_known_red_round_exempt.py",
                 "t260930-01/sc_ledger_reuse_round.py",
                 "t260930-02/sc_surface_plan_query.py"]:
        srcs["sc:" + name] = read_or_envfail(INTEG / name)
    if env_failed:
        finish()

    # ---------- A ok() 去重（验收 a：no verbatim copies left） ----------
    for name in ["t260930-01/sc_known_red_round_exempt.py",
                 "t260930-01/sc_ledger_reuse_round.py",
                 "t260930-02/sc_surface_plan_query.py"]:
        body = srcs["sc:" + name]
        ok(not re.search(r"^def ok\(", body, re.M),
           "A no local ok() copy in %s" % name,
           "verbatim def ok( still present — acceptance (a) not honored")
    try:
        lib_result = load_module(INTEG / "lib_result.py", "lib_result_check")
        ok(hasattr(lib_result, "ScenarioCheck"),
           "A shared assertion helper importable from lib_result",
           "lib_result.ScenarioCheck absent — the one shared helper is the acceptance face")
    except Exception as e:  # noqa: BLE001
        ok(False, "A shared assertion helper importable from lib_result", repr(e)[:300])

    # ---------- B 收窄旋钮词表跨语言锁（验收 b：either list edited alone fails） ----------
    try:
        lib_env = load_module(INTEG / "lib_env.py", "lib_env_check")
        fn_b = getattr(lib_env, "narrowing_lock_report", None)
        ok(callable(fn_b), "B narrowing_lock_report present in lib_env",
           "guard function absent — deliverable missing (FAIL, not ENV_FAIL)")
        if callable(fn_b):
            ok(fn_b(srcs["lib_env_py"], srcs["lib_env_mjs"]) == [],
               "B real lib_env.py × lib_env.mjs locked (empty report)",
               str(fn_b(srcs["lib_env_py"], srcs["lib_env_mjs"]))[:400])
            # 漂移样本在运行时拼接（"SANDBAR_" + "Supply_"），不落小写连续字面量——
            # 命名普查（test_census_env_literal_shape）把源内形如 SANDBAR_<小写> 的
            # 静态字面量判红（t261002-14 gen1 merge_check 实红）；守卫判据不变：
            # 单侧独改仍必被抓。
            drift = "SANDBAR_" + "Supply_"
            py_only = srcs["lib_env_py"].replace("SANDBAR_SUPPLY_", drift)
            ok(fn_b(py_only, srcs["lib_env_mjs"]) != [],
               "B py-side edited alone → red")
            mjs_only = srcs["lib_env_mjs"].replace("SANDBAR_SUPPLY_", drift)
            ok(fn_b(srcs["lib_env_py"], mjs_only) != [],
               "B mjs-side edited alone → red")
            bad_py = re.sub(r"NARROWING_ENV_NAMES = \([^)]*\)",
                            "NARROWING_ENV_NAMES = (", srcs["lib_env_py"], flags=re.S)
            ok(fn_b(bad_py, srcs["lib_env_mjs"]) != [],
               "B malformed py literal → fail-closed red (never silent green)")
            bad_mjs = re.sub(r"const NARROWING_NAMES = \[[^\]]*\]",
                             "const NARROWING_NAMES = [", srcs["lib_env_mjs"], flags=re.S)
            ok(fn_b(srcs["lib_env_py"], bad_mjs) != [],
               "B malformed mjs literal → fail-closed red (never silent green)")
    except Exception as e:  # noqa: BLE001
        ok(False, "B narrowing lock exercised", repr(e)[:300])

    # ---------- C 授予操作词表三面锁（验收 c：covers all three sides） ----------
    try:
        if ENGINE not in [Path(p) for p in sys.path]:
            sys.path.insert(0, str(ENGINE))
        eg = load_module(ENGINE / "executor_grants.py", "executor_grants_check")
        fn_c = getattr(eg, "grant_ops_lock_report", None)
        ok(callable(fn_c), "C grant_ops_lock_report present in executor_grants",
           "guard function absent — deliverable missing (FAIL, not ENV_FAIL)")
        if callable(fn_c):
            trio = (srcs["engine_grants"], srcs["panel_decl"], srcs["panel_fixed"])
            ok(fn_c(*trio) == [], "C real three-side sources locked (empty report)",
               str(fn_c(*trio))[:400])
            e_drop = srcs["engine_grants"].replace('"send-back"', '"sent-back"')
            ok(fn_c(e_drop, srcs["panel_decl"], srcs["panel_fixed"]) != [],
               "C engine side renamed alone → red")
            alias_drift = srcs["panel_fixed"].replace("'reject'", "'returned'")
            ok(fn_c(srcs["engine_grants"], srcs["panel_decl"], alias_drift) != [],
               "C panel alias ('reject') drifts alone → red")
            decl_reorder = srcs["panel_decl"].replace(
                "['sign', 'send-back', 'rerun', 'open-ticket', 'pause-resume', 'cleanup']",
                "['send-back', 'sign', 'rerun', 'open-ticket', 'pause-resume', 'cleanup']")
            ok(decl_reorder != srcs["panel_decl"] and
               fn_c(srcs["engine_grants"], decl_reorder, srcs["panel_fixed"]) != [],
               "C executor-grants.ts order-only drift → red (declared order is contract)")
            bad_decl = srcs["panel_decl"].replace(
                "export const GRANT_OPS =", "export const GRANT_OPS broken =")
            ok(fn_c(srcs["engine_grants"], bad_decl, srcs["panel_fixed"]) != [],
               "C malformed TS literal → fail-closed red (never silent green)")
            # 旧 drift test 只看 python 侧的病根本身也要被点名：python 侧自身的词表
            # 与设计稿原文（'send-back' 别名映射注释）在场性由 C 的真三面绿覆盖。
    except Exception as e:  # noqa: BLE001
        ok(False, "C grant-op lock exercised", repr(e)[:300])

    # ---------- D watchdog unreadable 发现点名票号（验收 d） ----------
    try:
        lw = load_module(ENGINE / "inspection_lane_watchdog.py",
                         "inspection_lane_watchdog_check")
        fn_d = lw.unreadable_finding_specs
        perm_line = "t260925-01: snapshot query failed: Exception: Workflow Task in failed state"
        specs = fn_d({"unreadable": [perm_line],
                      "unreadable_transient": [],
                      "unreadable_permanent": [perm_line]})
        perm = [s for s in specs if "permanent" in s["subject"]]
        ok(len(specs) == 1 and perm and "t260925-01" in perm[0]["subject"],
           "D permanent finding subject names the ticket id",
           "subject=%r" % (perm[0]["subject"] if perm else None))
        t_line = "t260925-12: snapshot query failed after 1 retry: TimeoutError"
        specs = fn_d({"unreadable": [t_line],
                      "unreadable_transient": [t_line],
                      "unreadable_permanent": []})
        trans = [s for s in specs if "transient" in s["subject"]]
        ok(trans and "t260925-12" in trans[0]["subject"],
           "D transient finding subject names the ticket id",
           "subject=%r" % (trans[0]["subject"] if trans else None))
        ids = ["t26%03d-01" % i for i in range(12)]
        lines = ["%s: snapshot query failed: Exception: x" % i for i in ids]
        specs = fn_d({"unreadable": lines, "unreadable_transient": [],
                      "unreadable_permanent": lines})
        subj = specs[0]["subject"]
        named = sum(1 for i in ids if i in subj)
        cap = getattr(lw, "UNREADABLE_LIST_CAP", 10)
        ok(named <= cap and "+2 more" in subj,
           "D cap overflow: <=%d ids named + '+N more' suffix" % cap,
           "named=%d subject=%r" % (named, subj[:300]))
        junk = "this line has no ticket id at all"
        specs = fn_d({"unreadable": [junk], "unreadable_transient": [],
                      "unreadable_permanent": [junk]})
        subj = specs[0]["subject"] if specs else ""
        ok(subj.startswith("Lane/watchdog sweep:") and
           "None" not in subj and "nan" not in subj,
           "D malformed detail → well-formed subject, no fabricated id",
           "subject=%r" % subj[:300])
        old = fn_d({"unreadable": [perm_line]})  # 老回执：分类键缺失
        ok(len(old) == 1 and old[0]["subject"] ==
           "Lane/watchdog sweep had 1 unreadable ticket(s)",
           "D old-receipt single-line subject keeps verbatim contract (replay determinism)",
           str(old)[:300])
    except Exception as e:  # noqa: BLE001
        ok(False, "D watchdog naming exercised", repr(e)[:300])

    finish()


def finish():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (passed, failed, env_failed, na), flush=True)
    if env_failed:
        sys.exit(2)
    if failed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
