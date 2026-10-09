"""260930 单测（宿主令·nusuyou 需求说明第六条 / KI-099 实案）：未知相位**绝不打断工作流实例**。

实案（nusuyou t260929-28，260929 夜）：验收段 agent 挂死后，操作员先 `retry_qc`（幂等不解），
再 `rework to_stage=acceptance_walkthrough` —— **被拒收**，而拒收回执**自己推荐**了
「可用别名 `to_stage=acceptance`」；照它改成 `acceptance` 后回执 `delivered: true`，随后票面
`dev_lane.py ValueError: 未知阶段 ''`、`status=None`，连 `show`/`query` 都查不到
（`Workflow Task in failed state`）——**票作废，不可恢复**。

两段病根（本修法各锁一条）：
  ① 相位解析可能返回**空值**：`_auto_rework` 的拒绝返回是 `str(meta["stage"] or fallback)`
     —— meta 现步为空串且 fallback 非法时就是空串；旧路径（`_apply_rework`，patched 未激活的
     在飞票）把它交回主循环。
  ② 主循环尾对未知相位 `raise`（注释自称 unreachable）——而本文件自己写着「主循环是裸
     while True，抛出去=打断工作流实例」⇒ 票面 status=None、快照/查票全不可读。
  修法：① 相位兜底 `_safe_phase`（候选逐个验，全非法 ⇒ arbitrate 人门 + 响亮留痕）；
        ② 主循环尾改 `_blocked`（可查/可唤醒/原因具名，点名合法相位词表）；
        ③ 拒收提示只列 `REWORK_ADMISSIBLE_PHASES`（**词表里能打的才在提示里推**——
           编排内部相位不再出现在提示里，防「照提示操作即踩雷」）。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260930_unknown_phase_hardening.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane as dl  # noqa: E402


@pytest.fixture()
def new_history(monkeypatch):
    """新历史：patched 恒 True（老历史的逐字不变由源码锁钉，见末尾）。"""
    monkeypatch.setattr(dl, "workflow",
                        SimpleNamespace(patched=lambda _id: True))
    return True


class _Stub:
    """只带 `_auto_rework`/`_safe_phase` 需要的记账面（不触碰 workflow 命令面）。"""

    _auto_rework = dl.DevLaneWorkflow._auto_rework
    _safe_phase = dl.DevLaneWorkflow._safe_phase

    def __init__(self, stage: str = "arbitrate", role: str = "integration"):
        self.meta = {"stage": stage, "status": "blocked", "role": role}
        self.refused = []

    def _log(self, _m):
        pass

    def _mark(self, *_a):
        pass

    def _touch(self):
        pass

    def _persist_stage_memo(self, stage, note=""):
        # KI-227 (t261008-29): the rework path now persists the stage into the
        # Temporal memo. This white-box stub models the accounting surface only —
        # record the call so the surface under test stays exercisable without a
        # workflow runtime (one-line recorder, per the arbitrate's preferred fix).
        self.stage_memo_calls = getattr(self, "stage_memo_calls", [])
        self.stage_memo_calls.append((stage, note))


# ---------------- ①相位兜底 ----------------

def test_safe_phase_picks_the_first_legal_candidate(new_history):
    s = _Stub()
    assert s._safe_phase("", "implement") == "implement"
    assert s._safe_phase("run_integration_tests", "implement") == "run_integration_tests"
    assert s.refused == [], "有合法候选就不该留夹相位痕"


@pytest.mark.parametrize("cands", [("", ""), ("", "unknown_phase"), ("done", ""),
                                   (None, ""), ("done", "unknown_phase")])
def test_safe_phase_never_returns_empty_or_unknown(new_history, cands):
    """空串/未知/done 一律不放过——旧的空串相位正是「票作废」的入口。"""
    s = _Stub()
    got = s._safe_phase(*cands)
    assert got == dl.REWORK_PHASE_FALLBACK
    assert got in dl.PHASE_MAIN_CHAIN and got != "done"
    assert s.refused and "phase-clamp" in s.refused[0]["want"], "夹相位必须留痕（不许静默）"


def test_auto_rework_never_hands_back_an_empty_phase(new_history):
    """复现路径：meta 现步为空串 + fallback 非法 ⇒ 必须夹到合法相位（旧行为=空串 ⇒ 主循环 raise）。"""
    s = _Stub(stage="")
    got = s._auto_rework("未知步", "note", "who", "")
    assert got == dl.REWORK_PHASE_FALLBACK, "旧行为返回空串，那会打断工作流实例"
    assert s.refused, "拒绝 + 夹相位都要记账"
    # 既有设计（不是本修法引入）：**合法目标 + 非法 fallback** 走 fallback 拒收分支、停在现步
    # ——现步为空串时就是那条会产出空相位的路，故必须被夹到合法值（下面这条即其回归锁）。
    s2 = _Stub(stage="")
    assert s2._auto_rework("implement", "note", "who", "") == dl.REWORK_PHASE_FALLBACK
    s3 = _Stub(stage="arbitrate")
    assert s3._auto_rework("implement", "note", "who", "") == "arbitrate", \
        "现步合法时就停在现步（旧语义逐字保留）"
    s4 = _Stub(stage="arbitrate")
    assert s4._auto_rework("implement", "note", "who", "arbitrate") == "implement", \
        "目标与 fallback 都合法 ⇒ 照旧直达目标"


# ---------------- ③提示词表 ----------------

def test_admissible_vocabulary_is_a_subset_and_excludes_internal_phases(new_history):
    assert dl.REWORK_ADMISSIBLE_PHASES <= (dl.PHASE_MAIN_CHAIN - {"done"}), \
        "提示词表不得超出相位词表（推一个打不了的值＝把人往坑里带）"
    assert "done" not in dl.REWORK_ADMISSIBLE_PHASES
    # 编排内部相位（并行叉两条边与汇合点）不进提示：从外部直接落进去只有半套上下文
    for internal in ("parallel_impl_design", "arb_acc_parallel", "integ_join",
                     "integration_review"):
        assert internal not in dl.REWORK_ADMISSIBLE_PHASES, internal
    # 常用可打回面必须在（对齐 nusuyou 侧的需要：验收/仲裁/实现/集测）
    for usable in ("implement", "acceptance", "arbitrate", "run_integration_tests"):
        assert usable in dl.REWORK_ADMISSIBLE_PHASES, usable


# ---------------- ②主循环尾与老路径（源码锁） ----------------

def test_loop_tail_blocks_instead_of_raising_behind_the_gate():
    src = Path(dl.__file__).read_text("utf-8")
    assert dl.UNKNOWN_PHASE_BLOCK_PATCH_ID == "t260930-unknown-phase-block"
    seg = src.split('if not workflow.patched(UNKNOWN_PHASE_BLOCK_PATCH_ID):', 1)
    assert len(seg) == 2, "主循环尾必须挂门"
    body = seg[1].split('# Close out', 1)[0]          # 门开后的这段就是新行为
    # 老历史（门关）逐字保留 raise；门开后不得再有 raise
    assert body.count('raise ValueError("unknown phase') == 1, "the gate-closed branch keeps its single raise"
    after_gate = body.split('raise ValueError("unknown phase', 1)[1]
    import re as _re
    pre_block = after_gate.split("await self._blocked(", 1)[0]
    assert not _re.search(r"^\s*raise\b", pre_block, _re.M), \
        "门开后（blocked 之前）不许再有 raise 语句（注释里提「raise」不算）"
    assert "await self._blocked(" in after_gate, \
        "门开后必须走 blocked（可查/可唤醒），而不是打断工作流实例"
    assert "no longer fails" in after_gate and "retry_qc" in after_gate, \
        "the blocked copy must name \"the workflow task no longer fails\" and give a way out (copy anglicized in t261008-47)"
    assert "phase = REWORK_PHASE_FALLBACK" in after_gate, "相位夹到人门再回主循环"
    assert "continue" in after_gate


def test_old_paths_are_verbatim_for_old_histories():
    """门关（老在途票）⇒ `_auto_rework` 的两条返回与旧写法逐字相同（重放零行为变化）。"""
    src = Path(dl.__file__).read_text("utf-8")
    assert src.count("workflow.patched(UNKNOWN_PHASE_BLOCK_PATCH_ID)") == 3, \
        "两处相位兜底 + 主循环尾各一门"
    assert 'return fallback if fallback in PHASE_MAIN_CHAIN else \\' in src
    assert 'str(self.meta.get("stage") or fallback)' in src
    assert src.count('return str(self.meta.get("stage") or fallback)') == 1


def test_hint_uses_the_admissible_vocabulary():
    src = Path(dl.__file__).read_text("utf-8")
    idx = src.index("integration/ 段可用别名")
    hint = src[max(0, idx - 120):idx + 320]
    assert "REWORK_ADMISSIBLE_PHASES" in hint, \
        "拒收提示必须只列可打回相位（防「照提示操作即踩雷」）"
