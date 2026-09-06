"""t260905-01 收口两问（沉淀触发器+反向同步闸）纯函数单测。

被测：agent_activities.parse_doc_gate / register_pending_doc_sync / apply_doc_gate。
全桩：固定 dict / 临时目录，零 agent、零网络、零 git（conftest UT 纪律）。
覆盖：正常两态、未答（absent 按问拆，C1）、畸形 JSON/类型错/超长截断（钩子②
畸形输入必带）、torn jsonl 行、去重键含 actual（R5 latest-wins）、写失败降级、
status 不改（不阻塞）、apply_doc_gate 防御兜底（R1 取舍表③）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_activities import (  # noqa: E402
    DOC_GATE_TRANSFER_NOTE,
    PENDING_DOC_SYNC_NAME,
    apply_doc_gate,
    parse_doc_gate,
    register_pending_doc_sync,
)
from shared import StageResult  # noqa: E402


def _res(**kw):
    base = dict(status="ok", summary="s", report="R", deliverables=[],
                files_changed=[], evidence="E")
    base.update(kw)
    return StageResult(**base)


CONFLICT = {"doc": "docs/design/x.md", "claim": "引擎只有串行链",
            "actual": "dev_lane 已并行分叉"}


# ---------- parse_doc_gate ----------

def test_parse_both_answered_ok():
    pg = parse_doc_gate({
        "doc_sediment": {"want": True, "target": "docs/design/a.md", "reason": "新契约"},
        "doc_conflicts": [CONFLICT],
    })
    assert pg["sediment"] == {"want": True, "target": "docs/design/a.md", "reason": "新契约"}
    assert not pg["sediment_absent"] and not pg["sediment_malformed"]
    assert pg["conflicts"] == [CONFLICT]
    assert not pg["conflicts_absent"] and not pg["conflicts_malformed"]


def test_parse_absent_split_per_question_c1():
    """沉淀答了、矛盾没答——absent 按问拆，互不污染（review C1）。"""
    pg = parse_doc_gate({"doc_sediment": {"want": False, "reason": "无"}})
    assert pg["sediment"]["want"] is False
    assert pg["sediment_absent"] is False
    assert pg["conflicts"] == [] and pg["conflicts_absent"] is True


def test_parse_all_absent():
    pg = parse_doc_gate({})
    assert pg["sediment_absent"] and pg["conflicts_absent"]
    assert pg["sediment"] is None and pg["conflicts"] == []


def test_parse_malformed_types():
    pg = parse_doc_gate({"doc_sediment": "是的要沉淀", "doc_conflicts": {"doc": "x"}})
    assert pg["sediment"] is None and "不是对象" in pg["sediment_malformed"]
    assert pg["conflicts"] == [] and "不是列表" in pg["conflicts_malformed"]


def test_parse_sediment_want_not_bool():
    pg = parse_doc_gate({"doc_sediment": {"want": "true", "target": "t"}})
    assert pg["sediment"] is None and "非布尔" in pg["sediment_malformed"]


def test_parse_conflict_missing_fields_quarantined():
    pg = parse_doc_gate({"doc_conflicts": [CONFLICT, {"doc": "只给一"}, "垃圾", None]})
    assert pg["conflicts"] == [CONFLICT]
    assert "3 条畸形" in pg["conflicts_malformed"]  # 4 条里 3 条畸形


def test_parse_conflict_overlong_truncated():
    items = [dict(CONFLICT, doc="d%d" % i) for i in range(60)]
    pg = parse_doc_gate({"doc_conflicts": items})
    assert len(pg["conflicts"]) == 50
    assert "截断" in pg["conflicts_malformed"]


def test_parse_non_dict_input():
    assert parse_doc_gate(None)["sediment_absent"]
    assert parse_doc_gate([1])["conflicts_absent"]


# ---------- register_pending_doc_sync ----------

def test_register_appends_and_dedups(tmp_path):
    r1 = register_pending_doc_sync(tmp_path, "t1", [CONFLICT])
    assert r1["registered"] == 1 and r1["path"] == str(tmp_path / ".suyou/doc-gate" / PENDING_DOC_SYNC_NAME)
    rows = [json.loads(x) for x in (tmp_path / ".suyou/doc-gate" / PENDING_DOC_SYNC_NAME)
            .read_text().splitlines()]
    assert rows[0]["ticket"] == "t1" and rows[0]["doc"] == CONFLICT["doc"]
    assert "registered_at" in rows[0]
    # 同键重跑（Temporal 重试/rework 重入）=去重
    r2 = register_pending_doc_sync(tmp_path, "t1", [CONFLICT])
    assert r2["registered"] == 0


def test_register_key_includes_actual_r5(tmp_path):
    """actual 演进 = 新条目（latest-wins，append-only 不删旧）。"""
    d = tmp_path
    register_pending_doc_sync(d, "t1", [CONFLICT])
    evolved = dict(CONFLICT, actual="现实变了")
    r = register_pending_doc_sync(d, "t1", [evolved])
    assert r["registered"] == 1
    lines = (d / ".suyou/doc-gate" / PENDING_DOC_SYNC_NAME).read_text().splitlines()
    assert len(lines) == 2


def test_register_tolerates_torn_lines(tmp_path):
    f = tmp_path / ".suyou/doc-gate" / PENDING_DOC_SYNC_NAME
    f.parent.mkdir(parents=True)
    good = json.dumps({"ticket": "t1", **CONFLICT}, ensure_ascii=False)
    f.write_text('{"ticket": "t1", "doc": "半截\n' + good + "\n垃圾行\n\n")
    r = register_pending_doc_sync(tmp_path, "t1", [CONFLICT])
    assert r["registered"] == 0  # 好 + 畸形行都被去重扫描正确消费，零抛
    assert r["error"] == ""


def test_register_write_failure_degrades(tmp_path, monkeypatch):
    """写失败降级不抛（权限面）：目录替换为文件让 mkdir 必败。"""
    (tmp_path / ".suyou").write_text("占位，mkdir 会撞")
    r = register_pending_doc_sync(tmp_path, "t1", [CONFLICT])
    assert r["registered"] == 0 and r["error"]


def test_register_empty_conflicts_noop(tmp_path):
    r = register_pending_doc_sync(tmp_path, "t1", [])
    assert r == {"registered": 0, "path": "", "error": ""}


# ---------- apply_doc_gate ----------

def _write_rfile(tmp_path, payload):
    f = tmp_path / "result.json"
    f.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
                 "utf-8")
    return f


def test_apply_ok_assembles_receipt(tmp_path):
    res = _res()
    f = _write_rfile(tmp_path, {"status": "ok", "summary": "s",
                                "doc_sediment": {"want": True, "target": "docs/a.md", "reason": "r"},
                                "doc_conflicts": [CONFLICT]})
    out = apply_doc_gate(res, f, tmp_path, "t1")
    assert out.status == "ok"  # status 永不改（不阻塞）
    assert "收口两问" in out.report and CONFLICT["claim"] in out.report  # 条目本体全量
    assert DOC_GATE_TRANSFER_NOTE in out.report  # 转正纪律句（R3）
    assert "[doc-gate]" in out.evidence and "registered=1" in out.evidence
    assert any(x.endswith(PENDING_DOC_SYNC_NAME) for x in out.deliverables)


def test_apply_unanswered_still_recorded(tmp_path):
    """验收①核心：未答也是一条记录，不阻塞。"""
    f = _write_rfile(tmp_path, {"status": "ok", "summary": "s"})
    out = apply_doc_gate(_res(), f, tmp_path, "t1")
    assert out.status == "ok"
    assert out.report.count("未答") == 2  # 两问分别留痕（C1 按问拆）
    assert "absent" in out.evidence


def test_apply_malformed_json_degrades(tmp_path):
    f = _write_rfile(tmp_path, "{not-json")
    out = apply_doc_gate(_res(), f, tmp_path, "t1")
    assert out.status == "ok" and out.report.count("未答") == 2


def test_apply_no_contradiction_no_debt_note(tmp_path):
    f = _write_rfile(tmp_path, {"doc_sediment": {"want": False, "reason": "无"},
                                "doc_conflicts": []})
    out = apply_doc_gate(_res(), f, tmp_path, "t1")
    assert "未发现 docs 矛盾" in out.report
    assert DOC_GATE_TRANSFER_NOTE not in out.report  # 无矛盾不带转正句
    assert out.deliverables == []


def test_apply_failed_round_still_registers_c2(tmp_path):
    """C2 明示口径：failed 轮同样拼装登记（打回轮矛盾同样是债条目）。"""
    f = _write_rfile(tmp_path, {"status": "failed", "summary": "走查红",
                                "doc_conflicts": [CONFLICT]})
    out = apply_doc_gate(_res(status="failed"), f, tmp_path, "t1")
    assert out.status == "failed"
    assert "registered=1" in out.evidence and CONFLICT["claim"] in out.report


def test_apply_defensive_fallback(tmp_path, monkeypatch):
    """防御兜底：判读内部任何异常都只软降级留痕，不阻断收口（R1 取舍表③）。"""
    f = _write_rfile(tmp_path, {"doc_conflicts": [CONFLICT]})
    monkeypatch.setattr("agent_activities.register_pending_doc_sync",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("炸了")))
    out = apply_doc_gate(_res(), f, tmp_path, "t1")
    assert out.status == "ok" and "判读异常软降级" in out.evidence


def test_apply_dedup_across_reruns(tmp_path):
    f = _write_rfile(tmp_path, {"doc_conflicts": [CONFLICT]})
    r1 = apply_doc_gate(_res(), f, tmp_path, "t1")
    r2 = apply_doc_gate(_res(), f, tmp_path, "t1")  # Temporal 重试整段重执行
    assert "registered=1" in r1.evidence and "registered=0" in r2.evidence
