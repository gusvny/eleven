#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D 两层复跑 + 爆炸半径（260923 宿主直修令，不开票）回归棒。

口径（集成轮次瘦身提案·定稿 D）：中间轮定点复跑只作快反馈（上一轮红项面），
放行只认收口全量跑；写集命中共享基座禁定点恒全跑；首轮恒全跑。本文件钉四层：
- blast_radius 矩阵：共享基座命中/空写集/畸形入参=shared（保守恒全量）；
  票面局部改动=localized。
- targeted_rerun_plan 矩阵：首轮/共享基座/无上轮红名/畸形名单=[]（=全量语义）；
  正常=上轮红名（去重、剔 __ 合成条目）。
- **转人工触发不许归零**（宿主回归棒复证）：tests-fault 计满上限照样 blocked，
  双上限机制不因本改动弱化。
- 结构锁：dev_lane 收口拦截/patched 门/only_names 接线在位；agent_activities
  SANDBAR_SCENARIO_ONLY 注入与跑面回显在位；仲裁判词锚在位。
"""
from __future__ import annotations

from pathlib import Path

from shared import (MAX_TESTS_FAULT_ROUNDS, blast_radius, integration_route,
                    targeted_rerun_plan)
from shared import tests_round_step as step_rounds  # 别名：防 pytest 误收集 tests_* 名

_ENGINE = Path(__file__).resolve().parents[1]


def test_blast_radius_shared_hits():
    for ws in (["server/engine/dev_lane.py"],
               ["server/tools/verify_lane.py"],
               ["integration/run_scenarios.py"],
               ["integration/lib_env.py"],
               ["integration/tests/test_x.py"],
               ["verify.yaml"],
               ["./server/engine/shared.py"],
               ["app/foo.py", "server/engine/dev_lane.py"]):
        assert blast_radius(ws) == "shared", ws


def test_blast_radius_localized_and_conservative():
    assert blast_radius(["integration/t260922-18/sc_x.py"]) == "localized"
    assert blast_radius(["app/web/src/foo.ts", "notes/x.md"]) == "localized"
    # 保守方向：空/畸形=shared（恒全量，宁可慢不可窄）
    assert blast_radius([]) == "shared"
    assert blast_radius(None) == "shared"
    assert blast_radius("server/engine/x.py") == "shared"
    assert blast_radius([None, "", "  "]) == "shared"
    assert blast_radius([123, None]) == "shared"


def test_targeted_plan_matrix():
    ws_loc = ["integration/t260922-18/sc_x.py"]
    ws_sh = ["server/engine/shared.py"]
    # 全量语义=[]
    assert targeted_rerun_plan(ws_loc, ["a"], first_run=True) == []
    assert targeted_rerun_plan(ws_sh, ["a"]) == []
    assert targeted_rerun_plan(ws_loc, []) == []
    assert targeted_rerun_plan(ws_loc, None) == []
    assert targeted_rerun_plan(ws_loc, "a") == []
    # 定点面=上轮红名（去重、剔 __ 合成条目与空串，保序）
    assert targeted_rerun_plan(ws_loc, ["b", "a", "b", "__gate_blockers__",
                                        "", "  ", 7, "a"]) == ["b", "a"]


def test_human_trigger_rod_caps_intact():
    """转人工触发不许归零：D 不许弱化双上限的任一触发。"""
    rounds, exempts = 0, 0
    for _ in range(MAX_TESTS_FAULT_ROUNDS + 1):
        rounds, exempts, counted, _n = step_rounds("tests-fault", rounds, exempts)
        assert counted is True
    route = integration_route("tests-fault", rounds, 0)
    assert route.startswith("blocked:") and "超限" in route


def test_wiring_structural_locks():
    dev = (_ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    act = (_ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    # patch 门 + 收口拦截（双支）+ 入参接线（单写者方法）+ 簿记
    assert "TARGETED_RERUN_PATCH_ID" in dev
    assert dev.count("收口全量跑有新增红") == 2        # 串行/平行两支各一处
    assert "self._integ_run_args(run_only)" in dev
    assert "only_names=list(only_names or [])" in dev   # 构造单写者（唯一真站同源）
    assert "last_run_only = list(run_only)" in dev
    assert "targeted_rerun_plan(" in dev
    assert "await self._closing_full_run()" in dev
    # 活动侧：SANDBAR_SCENARIO_ONLY 注入 + 跑面回显（少跑必须可见）
    assert 'SANDBAR_SCENARIO_ONLY' in act
    assert "out.only_names = list(only_names)" in act
    # 仲裁判词锚（定点面不是条目丢失；放行只认收口全量跑）
    assert "放行只认收口全量跑" in dev
    assert "不是条目丢失" in dev


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
