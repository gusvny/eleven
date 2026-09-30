#!/usr/bin/env python3
"""Shared helper for three-state scenario verdicts (t260904-12: no SKIP inside
the integration gate, final ruling section 7.3).

Scenario-level states are only PASS / FAIL / ENV_FAIL / N/A (leg-level); the
exit-code contract:
  0 = all green; 1 = some FAIL (product red, including all-legs N/A — nothing
      to verify is a scenario design/coverage problem, fix the scenario rather
      than the environment);
  2 = some ENV_FAIL (environment red: nothing got verified, the cause belongs
      to the environment, and the SUMMARY/output names what is missing).

Discipline (against a SKIP-hole comeback):
- a missing environment (dependency, test stage, credentials, playwright, ...)
  always goes through env_fail(), never exit 0;
- na() is only for legs conditioned on **system state** (not on the test
  environment, e.g. "with this feature flag absent the leg has no object");
  a scenario whose legs are all N/A is product red per the contract (exit 1) —
  fail_if_all_na() below is where that verdict is enforced;
- malformed/exception paths are equally not allowed to go silently green:
  prefer an explicit FAIL red.

mjs-side equivalent = integration/t260904-05/lib_browser.mjs makeResults()
(same state vocabulary pass/fail/env_fail/na + summarize() with the same
exit-code priority).
"""
import os
import sys

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV_FAIL = 2


def env_fail(reason):
    """Missing environment: print what exactly is absent, exit 2 (ENV_FAIL,
    environment red). Never exit 0."""
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


def na(reason):
    """A leg conditioned on system state has no object (not a missing
    environment). Only emits the marker; whether the scenario is all-N/A is
    judged uniformly by fail_if_all_na() over the scenario's leg table."""
    print("N/A: %s" % reason)


def fail_if_all_na(total_legs, na_legs, scenario=""):
    """A scenario whose legs are all N/A is red (product red, exit 1): having
    nothing to verify is a scenario design/coverage problem.
    total_legs = total legs in the scenario; na_legs = how many are N/A."""
    if total_legs > 0 and na_legs >= total_legs:
        print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）%s" % scenario)
        sys.exit(1)


# ======================================================================================
# 260930（真票 t260930-09 实况；宿主令「继承的收窄旋钮必须清零」）：窄化旋钮的单点清理
# ======================================================================================
# 病根：泳道轮的闸环境里带着**本轮收窄面**（SANDBAR_SCENARIO_ONLY=<改动面>，引擎
# t260930 起默认走面计划收窄）。场景/夹具自己再起执行器或闸时，**子进程继承**了它 →
# 内层被收窄成不含夹具点名的面 → 断言成片红（实测 5 条：t260913-03-* ×4 +
# t260916-25-stage-console-selfcheck-red）。与票的改动无关。
#
# 纪律（本函数即纪律的机械化身）：**被测面必须由夹具显式声明，绝不继承外层泳道轮的
# 收窄/策略旋钮**。清理=先剥再注入：调用方要用哪一档，自己在 extra 里写明。
NARROWING_ENV_PREFIXES = (
    "SANDBAR_SCENARIO_",   # 收窄面（ONLY）/池排除/台账目录…
    "SANDBAR_INTEG_",      # 跑锁路径、台账来源、允许并发、批次预算…
    "SANDBAR_KNOWN_RED_",  # 在册红豁免开关与名册路径
    "SANDBAR_GATE_",       # 基线开关及其依赖软链
    "SANDBAR_SUPPLY_",     # 供给段预算/等待上限
)
#: **具名**的台面收窄注入（引擎每轮往执行器 env 里塞的那两个；t260923 C 自愈清扫半径）。
#: 为什么**不**用 `SANDBAR_STAGE_` 前缀（260930 修正）：该前缀下有**共享缝**——
#: `SANDBAR_STAGE_BATCH`（批台名，run_scenarios 注入给批消费者条目，消费缝
#: lib_gate/with_stage.sh 据此走共享台 ns）与 `SANDBAR_STAGE_*`（夹具自己的等待/租约
#: 旋钮）。一句话清掉会把「共享/夹具声明的档」一起剥掉=改了被测面（如
#: t260921-06/run_inner_runner.py 的调用方明确注入 BATCH 的语义）。收窄面只清
#: 「引擎每轮注入的收窄件」，**不是**整族台面旋钮。
NARROWING_ENV_NAMES = (
    "SANDBAR_POOL_CONC",                     # 并发宽度（进环境指纹、影响判定宽度）
    "SANDBAR_CONC_POOLS",                    # 池并发声明
    "SANDBAR_UNDECLARED_POLICY",             # 调用方身份策略（影响引擎写操作闸）
    "SANDBAR_STAGE_SWEEP_ORPHANS",           # 引擎每轮注入：挂点孤儿清扫总闸
    "SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX",     # 引擎每轮注入：清扫半径前缀
)


def narrow_env_names() -> tuple:
    """被清理的旋钮名全集（前缀 + 具名）——守卫/自证/文档共用一份。"""
    return (NARROWING_ENV_PREFIXES, NARROWING_ENV_NAMES)


def inherited_narrowing_knobs(env=None) -> dict:
    """env 里**还带着**的收窄旋钮（诊断/守卫自证用；空 dict = 干净）。"""
    src = os.environ if env is None else env
    out = {}
    for k, v in src.items():
        if k in NARROWING_ENV_NAMES or k.startswith(NARROWING_ENV_PREFIXES):
            out[k] = v
    return out


def clean_narrowing_env(extra=None, base=None) -> dict:
    """副本 env：剥掉**继承来的窄化/策略旋钮**，再并入调用方显式声明的 extra。

    所有「场景/夹具自己起执行器或闸」的地方都必须走这里（守卫=integration/lint_tests.py
    L12）：子进程只该看见夹具自己声明的那一档，绝不继承外层泳道轮的收窄面。"""
    env = dict(os.environ if base is None else base)
    for k in list(env):
        if k in NARROWING_ENV_NAMES or k.startswith(NARROWING_ENV_PREFIXES):
            env.pop(k, None)
    for k, v in (extra or {}).items():
        env[str(k)] = str(v)
    return env


class no_narrowing_env:
    """上下文管理器：**进程内**调用执行器/闸时（`rs.main()` / `verify_lane.run()`），
    临时把继承来的收窄旋钮从 os.environ 摘掉，退出时原样恢复。

    为什么需要：进程内调用读的是本进程 env，`clean_narrowing_env` 那种「传给子进程」的
    写法对它无效。用法：`with no_narrowing_env(): rc = rs.main()`。"""

    def __init__(self, extra=None):
        self.extra = dict(extra or {})
        self._saved = {}
        self._added = []

    def __enter__(self):
        for k in list(os.environ):
            if k in NARROWING_ENV_NAMES or k.startswith(NARROWING_ENV_PREFIXES):
                self._saved[k] = os.environ.pop(k)
        for k, v in self.extra.items():
            os.environ[str(k)] = str(v)
            self._added.append(str(k))
        return self

    def __exit__(self, *exc):
        for k in self._added:
            os.environ.pop(k, None)
        os.environ.update(self._saved)
        return False
