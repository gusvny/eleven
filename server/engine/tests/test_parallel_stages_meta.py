"""set_parallel_stages 单元测试（KI-024 收口，t260903-04）。

被测对象：dev_lane.set_parallel_stages —— 并行分叉期 meta['parallel_stages'] 的
唯一写入口（引擎两处并行分支共用）。锁的口径（工单正文 + review_plan C4/C5）：

  1. 正常分叉：STAGES id 列表原样入 meta（保序）；
  2. 空列表 / 清洗后为空 → 删键（UI 回落既有启发式，不留陈旧列表）；
  3. 畸形输入必拒：非列表、None、非字符串元素、模板外 id（phase 值
     parallel_impl_design/integ_join 是词表∩¬STAGES 的典型畸形源）、重复 id 去重；
  4. 单 stage 字段不动（向后兼容：后写者赢语义保持，双显真源=列表）；
  5. 覆盖既有 meta 键（重复写入=覆盖，等待期摘边重写依赖此语义）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：主树 venv 解释器 `.../engine/.venv/bin/python -m pytest
server/engine/tests/test_parallel_stages_meta.py -q`（worktree 无 .venv）。
"""
import pytest

import dev_lane
from dev_lane import set_parallel_stages

STAGE_IDS = {s.id for s in dev_lane.DevLaneWorkflow.STAGES}


def test_normal_fork_writes_list_in_order():
    meta = {"stage": "design_integration_tests"}  # 后写者赢的现状字段（不动它）
    set_parallel_stages(meta, ["implement", "design_integration_tests"])
    assert meta["parallel_stages"] == ["implement", "design_integration_tests"]
    assert meta["stage"] == "design_integration_tests"  # 单 stage 字段保持原样


def test_empty_list_deletes_key():
    meta = {"parallel_stages": ["implement"]}
    set_parallel_stages(meta, [])
    assert "parallel_stages" not in meta  # 删键而非空列表（UI 回落启发式的信号）


def test_clear_is_idempotent_on_missing_key():
    meta = {}
    set_parallel_stages(meta, [])  # 不存在也不抛（离开并行期统一清）
    assert "parallel_stages" not in meta


@pytest.mark.parametrize("bad", [
    None,                       # 非列表
    "implement",                # 裸字符串（非列表）
    {"parallel_stages": 1},     # dict 之类可迭代非列表
    [123],                      # 非字符串元素
    [None],                     # None 元素
    ["parallel_impl_design"],   # phase 值（词表∩¬STAGES，典型畸形源）
    ["integ_join"],             # 同上
    ["implement", "no_such_stage"],  # 混入模板外 id → 只留合法的
    ["no_such_stage"],          # 全非法 → 等价清空
])
def test_malformed_inputs_rejected(bad):
    meta = {}
    set_parallel_stages(meta, bad)
    if isinstance(bad, list):
        kept = [s for s in bad if isinstance(s, str) and s in STAGE_IDS]
    else:
        kept = []
    if kept:
        assert meta["parallel_stages"] == kept
    else:
        assert "parallel_stages" not in meta


def test_dedupe_keeps_first_occurrence_order():
    meta = {}
    set_parallel_stages(meta, ["arbitrate", "acceptance_walkthrough", "arbitrate"])
    assert meta["parallel_stages"] == ["arbitrate", "acceptance_walkthrough"]


def test_rewrite_overwrites_previous_list():
    # 等待期摘失败边（review C4 写死口径）依赖覆盖语义：gather 前双边 → 失败后单边
    meta = {}
    set_parallel_stages(meta, ["arbitrate", "acceptance_walkthrough"])
    set_parallel_stages(meta, ["acceptance_walkthrough"])
    assert meta["parallel_stages"] == ["acceptance_walkthrough"]


def test_wordlist_is_real_stage_ids_not_phase_values():
    # 锁词表口径：本函数的合法集=STAGES id，绝不含 phase 专用值
    for phase_only in ("parallel_impl_design", "integ_join", "arb_acc_parallel",
                       "acceptance", "integration_review"):
        assert phase_only not in STAGE_IDS
