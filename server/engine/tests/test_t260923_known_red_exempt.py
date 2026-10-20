#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression rod for the zero-new-red caliber (host direct-fix order 260923, no ticket).

Background (integration round slimming proposal, final:
notes/discussions/260923-integration-round-slimming-proposal.md): an empty gate blocker set
means the red face is all pre-existing baseline debt or an external-environment record face
(the decide face records it without blocking the ticket) - zero new red - but the arbitrator
may still judge tests-fault and rerun known reds. A known-red rerun never turns green; it only
burns rounds until the iteration cap hands the ticket to a human. This file pins three layers:

- known-red exemption face: tests_round_step gains a third exempt shape (the round is not
  counted, the consecutive exempt rounds are); malformed inputs still fail closed (counted, never
  undercounted); the note priority is env-side-red > jitter-green > known-red.
- The hand-over-to-human trigger must never be zeroed (host regression rod): when the known-red
  exempt rounds are exhausted the independent MAX_TESTS_EXEMPT_ROUNDS cap still routes the ticket
  to a human (all four exits present); a tests-fault count that reaches its cap still blocks - the
  exemption face never swallows the "a human sees this" trigger.
- Structural lock (against regressing into "rerun known reds and burn rounds"): the dev_lane
  wiring (the known_red= argument) and the arbitration wording anchors (zero-new-red judged pass
  plus the ban on rerunning known reds) are in place; the tests_round_step signature is present.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from shared import (MAX_TESTS_EXEMPT_ROUNDS, MAX_TESTS_FAULT_ROUNDS,
                    integration_route)
from shared import tests_exempt_cap_blocked_text as exempt_cap_text
from shared import tests_round_step as step_rounds  # 别名：防 pytest 误收集 tests_* 名


def test_known_red_exempt_not_counted():
    nr, ne, counted, note = step_rounds("tests-fault", 3, 1, known_red=True)
    assert nr == 3            # 不计轮
    assert ne == 2            # 连续豁免轮 +1
    assert counted is False
    assert note == "known-red"


def test_known_red_failclosed_nonbool_counts():
    for bad in ("yes", 1, 0, None, [], {}):
        nr, ne, counted, note = step_rounds("tests-fault", 3, 1, known_red=bad)
        assert (nr, ne, counted) == (4, 0, True), (bad, nr, ne, counted)
        assert note == "counted"


def test_known_red_note_precedence():
    # 环境面 > 抖动 > 已知红：注记只报最具体者，判定面任一命中即豁免
    _, ne, counted, note = step_rounds(
        "tests-fault", 0, 0, env_side_red=True, jitter_green=True, known_red=True)
    assert (ne, counted, note) == (1, False, "env-side-red")
    _, ne, counted, note = step_rounds(
        "tests-fault", 0, 0, jitter_green=True, known_red=True)
    assert (ne, counted, note) == (1, False, "jitter-green")
    # 混合面：已知红豁免要求 blockers 显式为空（调用方断言），纯函数面不看红名——
    # 计轮面不变式：非豁免信号照计
    nr, ne, counted, _ = step_rounds("tests-fault", 0, 0)
    assert (nr, ne, counted) == (1, 0, True)


def test_human_trigger_never_zero_exempt_cap():
    """转人工触发不许归零（已知红豁免车道）：豁免耗尽照样封盖见人。"""
    rounds, exempts = 0, 0
    for _ in range(MAX_TESTS_EXEMPT_ROUNDS):
        rounds, exempts, counted, _n = step_rounds(
            "tests-fault", rounds, exempts, known_red=True)
        assert counted is False
    assert exempts == MAX_TESTS_EXEMPT_ROUNDS
    text = exempt_cap_text(exempts)
    assert "consecutive-exemption over cap" in text
    for op in ("authorize", "ruling", "rework", "pause"):
        assert op in text          # 四条真实出路（ticket.py 在册 op，无 terminate）


def test_human_trigger_never_zero_tests_cap():
    """对照子用例：真问题车道的转人工触发不因新增豁免面而弱化。"""
    rounds, exempts = 0, 0
    for _ in range(MAX_TESTS_FAULT_ROUNDS + 1):
        rounds, exempts, counted, _n = step_rounds("tests-fault", rounds, exempts)
        assert counted is True
    route = integration_route("tests-fault", rounds, 0)
    assert route.startswith("blocked:")
    assert "exceed the cap" in route
    for op in ("authorize", "ruling", "rework", "pause"):
        assert op in route


def test_wiring_and_prompt_anchors():
    """结构锁：dev_lane 接线与仲裁判词锚在位（防回退成重跑已知红烧轮次）。"""
    params = inspect.signature(step_rounds.__wrapped__
                               if hasattr(step_rounds, "__wrapped__")
                               else step_rounds).parameters
    assert "known_red" in params
    dev = (Path(__file__).resolve().parents[1] / "dev_lane.py").read_text(
        encoding="utf-8")
    assert "known_red=known_red" in dev
    assert "闸 blockers 显式为空" in dev
    assert "零新增红" in dev
    assert "禁止以「重跑一轮等它绿」当收敛手段" in dev
