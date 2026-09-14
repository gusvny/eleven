#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260913-01：集成测试道「预算对」不变量守卫（L1 单测，纯常量关系，零 IO）。

intent：机械集测 activity 的两层预算是**一对**——外层 `dev_lane.INTEG_RUN_TO`
（start_to_close_timeout）与内层 `agent_activities.BATCH_TIMEOUT_SEC + 300`
（subprocess wait_for 守卫）。内层必须严格小于外层，否则内层那条结构化超时回报
（`IntegrationRunResult(error="场景执行器整体超时（>Ns）")`）是**死代码**：套件只会
被 Temporal 硬杀成 `Activity task timed out`（ran=0、无归因），并且
`RETRY(maximum_attempts=3)` 会把每次硬杀再重试 3 轮——实测 260913 连续两轮 0 跑无归因
（外层 60min / 内层 5400+300=95min）。

本用例只锁这对常量关系与默认值上界（不锚实现细节）：任一侧被改动而另一侧没跟上，
立即红并点名该查哪一侧。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_activities  # noqa: E402
import dev_lane  # noqa: E402

GUARD_SEC = 300          # agent_activities._run_scenarios 的 wait_for 余量
DEFAULT_UPPER = 3300     # 内层守卫上限（= BATCH_TIMEOUT_SEC + GUARD_SEC）默认不得超此值


def test_inner_budget_fits_inside_activity_timeout():
    inner = agent_activities.BATCH_TIMEOUT_SEC + GUARD_SEC
    outer = dev_lane.INTEG_RUN_TO.total_seconds()
    assert inner < outer, (
        "集成道预算对失衡：内层守卫 %ds（BATCH_TIMEOUT_SEC=%d + %d）不小于外层 "
        "INTEG_RUN_TO=%ds —— 内层结构化超时回报等不到，只剩 Temporal 硬杀 + 3 次重试。"
        "改一侧必查另一侧（agent_activities.BATCH_TIMEOUT_SEC / dev_lane.INTEG_RUN_TO）"
        % (inner, agent_activities.BATCH_TIMEOUT_SEC, GUARD_SEC, outer))


def test_default_inner_budget_not_widened():
    """默认（无 env 覆盖）下内层守卫上限不得被悄悄放大——放大即把硬杀窗口推回去。"""
    if os.environ.get("SANDBAR_INTEG_BATCH_TIMEOUT_SEC"):
        return  # 运维显式覆盖的现场不锁（覆盖须同时抬外层，由上一用例兜住）
    assert agent_activities.BATCH_TIMEOUT_SEC + GUARD_SEC <= DEFAULT_UPPER, (
        "BATCH_TIMEOUT_SEC 默认值被放大到 %ds（守卫上限 %ds > 约定 %ds）——"
        "正常套件约 25min，超过 55min 的窗口应交给结构化回报而不是延长白烧"
        % (agent_activities.BATCH_TIMEOUT_SEC,
           agent_activities.BATCH_TIMEOUT_SEC + GUARD_SEC, DEFAULT_UPPER))
