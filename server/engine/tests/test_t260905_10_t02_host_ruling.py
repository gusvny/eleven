"""t260905-10 面① 单元测试：宿主裁决注入通道（KI-053）。

覆盖（方案 gen1 + review D2/D3 口径）：
  - build_stage_prompt 注入面：无裁决不出节（段号维持既有 5/6/7 零回归）；
    有裁决出节且后续段号顺延；排序**旧→新**（D3 钉死）；只消费末 5 条；
    note 超 1200 截断带「…（截断）」标记（不静默切断）；小节预算硬上界 ≤6.6KB；
    畸形条目（非 dict/缺键）不炸；arbitrate 机械段 prompt 同样消费。
  - DevLaneWorkflow.host_ruling signal：合法 → append meta['host_rulings']（ts/who/note）
    + 事件历史留痕；who/note 空·纯空白 → 拒收进 refused；note 超 intake 上限
    （D2）→ 拒收点名，不进事件历史。

UT 零 Temporal 运行时（stub dev_lane.workflow）/零网络/零 git。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import (  # noqa: E402
    HOST_RULING_NOTE_INPUT_LIMIT,
    HOST_RULING_NOTE_LIMIT,
    HostRulingRequest,
    Stage,
    build_stage_prompt,
)

ST = Stage(id="arbitrate", name="集成测试仲裁", role="integration",
           acceptance=("仲裁三态",))
ST_IMPL = Stage(id="implement", name="实现", role="developer",
                acceptance=("改动落在写集内",))
HANDOFFS = [{"stage": "implement", "summary": "实现自测全绿"}]
RFILE = "/tmp/ut/stage_arbitrate_gen0.json"

HOST_RULING_BUDGET = 6600  # 5×(1200+行头~80)+小节框架（方案 R2 取舍③）


def _prompt(rulings=None, stage=ST, handoffs=HANDOFFS, prev_ctx=""):
    meta = {"title": "ut"}
    if rulings is not None:
        meta["host_rulings"] = rulings
    return build_stage_prompt("t-ut", meta, stage, handoffs, RFILE, 0, prev_ctx)


def _mk_wf():
    """免 Temporal 运行时的 DevLaneWorkflow 壳（t260904-18 同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: __import__("datetime").datetime(2026, 9, 7, 0, 0, 0))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    wf.refused = []
    return wf


def _signal_ruling(wf, who, note):
    fn = dev_lane.DevLaneWorkflow.__dict__["host_ruling"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, HostRulingRequest(who=who, note=note))


# ---------- build_stage_prompt 注入面 ----------


def test_no_rulings_keeps_legacy_numbering():
    """无裁决：不出节，段号维持既有 5（前段交接）/6（上次运行上下文）——零回归。"""
    p = _prompt(rulings=None, prev_ctx="【方案审读打回】x")
    assert "宿主裁决注入" not in p
    assert "5. 前段交接" in p
    assert "6. 上次运行上下文" in p


def test_rulings_section_and_renumbering():
    """有裁决：出节在验收清单之后；交接/上次运行上下文段号顺延。"""
    p = _prompt(rulings=[{"ts": "T1", "who": "宿主", "note": "先跑测试再改文档"}],
                prev_ctx="【打回】x")
    assert "5. 宿主裁决注入" in p
    assert "先跑测试再改文档" in p
    assert "6. 前段交接" in p
    assert "7. 上次运行上下文" in p


def test_rulings_order_old_to_new():
    """排序口径钉死（D3）：旧→新，末尾最新。"""
    p = _prompt(rulings=[{"ts": "T1", "who": "h", "note": "AAA旧"},
                         {"ts": "T2", "who": "h", "note": "BBB中"},
                         {"ts": "T3", "who": "h", "note": "CCC新"}])
    assert p.index("AAA旧") < p.index("BBB中") < p.index("CCC新")


def test_rulings_only_last_five():
    """只消费末 5 条；掉出 prompt 的旧裁决兜底在 meta（本测只断言 prompt 面）。"""
    rulings = [{"ts": "T%d" % i, "who": "h", "note": "N%d" % i} for i in range(7)]
    p = _prompt(rulings=rulings)
    assert "N0" not in p and "N1" not in p          # 旧两条掉出
    for i in range(2, 7):
        assert "N%d" % i in p


def test_ruling_note_truncated_with_mark():
    """超 1200 截断加标记（不静默切断，R2 取舍①）。"""
    long_note = "X" * (HOST_RULING_NOTE_LIMIT + 300)
    p = _prompt(rulings=[{"ts": "T", "who": "h", "note": long_note}])
    assert "X" * HOST_RULING_NOTE_LIMIT in p
    assert "…（截断）" in p
    assert "X" * (HOST_RULING_NOTE_LIMIT + 10) not in p


def test_rulings_section_budget_cap():
    """预算硬上界：5 条 × 超 1200 字裁决，小节长度 ≤6.6KB（R2 取舍③）。"""
    rulings = [{"ts": "T%d" % i, "who": "h" * 40, "note": "Y" * 1500} for i in range(5)]
    p = _prompt(rulings=rulings)
    sec = p[p.index("宿主裁决注入"):p.index("前段交接")]
    assert len(sec) <= HOST_RULING_BUDGET


@pytest.mark.parametrize("bad", [None, 42, "str", {}, {"who": "只有who"}, [1, 2]])
def test_malformed_ruling_entries_no_crash(bad):
    """畸形条目（非 dict / 缺键）不炸：合法条目消费，畸形不拦全节。"""
    p = _prompt(rulings=[bad, {"ts": "T", "who": "h", "note": "正常裁决"}])
    assert "正常裁决" in p
    assert "5. 宿主裁决注入" in p


def test_arbitrate_mechanical_stage_sees_ruling():
    """验收① UT 子用例：arbitrate（只吃机械结果的段）prompt 同样可见裁决。"""
    p = _prompt(stage=ST, rulings=[{"ts": "T", "who": "宿主", "note": "仲裁意见：看 UI 证据"}])
    assert "仲裁意见：看 UI 证据" in p
    assert "宿主裁决注入" in p


# ---------- DevLaneWorkflow.host_ruling signal ----------


def test_valid_ruling_appended_and_logged():
    wf = _mk_wf()
    _signal_ruling(wf, "宿主", "先修 venv 再重跑")
    rs = wf.meta["host_rulings"]
    assert len(rs) == 1
    assert rs[0]["who"] == "宿主" and rs[0]["note"] == "先修 venv 再重跑"
    assert rs[0]["ts"]                       # 事件留痕：工作流时间戳在条目上
    assert wf.refused == []
    assert any("宿主裁决注入" in e["note"] for e in wf.meta["log"])


def test_blank_who_or_note_refused():
    for who, note in [("", "n"), ("  ", "n"), ("h", ""), ("h", "   "), ("", "  ")]:
        wf = _mk_wf()
        _signal_ruling(wf, who, note)
        assert "host_rulings" not in wf.meta or wf.meta["host_rulings"] == []
        assert len(wf.refused) == 1 and wf.refused[0]["want"] == "host_ruling"


def test_oversized_note_refused_not_in_history():
    """intake 闸（D2）：超限 note 拒收点名，不进 Temporal 事件历史。"""
    wf = _mk_wf()
    big = "Z" * (HOST_RULING_NOTE_INPUT_LIMIT + 1)
    _signal_ruling(wf, "宿主", big)
    assert "host_rulings" not in wf.meta
    assert len(wf.refused) == 1
    assert "超限" in wf.refused[0]["why"]
    assert "log" not in wf.meta              # 拒收不留痕（连日志都不进）


def test_multiple_rulings_accumulate_in_order():
    wf = _mk_wf()
    _signal_ruling(wf, "h1", "第一条")
    _signal_ruling(wf, "h2", "第二条")
    assert [r["note"] for r in wf.meta["host_rulings"]] == ["第一条", "第二条"]
