"""t260905-03 票①：巡检票骨架单测（inspection_flow 纯逻辑 + 引擎注册面）。

覆盖：期号/票号、触发参数 fail-closed、发现清单落票面（渲染数据/心跳零发现票/
开票建议携带 source_inspection）、人门签字校验（复用 Signature 语义：who 注入、
agent 不得自签、gate 匹配、decision 两值——M3）、落账覆盖写、workflow 注册与
signal/query 结构面（人门真拦的两拍证据由真链路验收①承载，此处验证逻辑面）。
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_flow as flow  # noqa: E402


# ---------- 期号/票号/触发参数 ----------

def test_period_key_format():
    assert flow.period_key(__import__("datetime").datetime(2026, 9, 5, 13, 44)) == "20260905"


def test_inspection_ticket_id_shape_and_validation():
    tid = flow.inspection_ticket_id("test-face", "20260905")
    assert tid == "inspection-test-face-20260905"
    with pytest.raises(ValueError):
        flow.inspection_ticket_id("test-face", "2026-09-05")
    with pytest.raises(ValueError):
        flow.inspection_ticket_id("", "20260905")


def test_validate_trigger_args_fail_closed():
    assert flow.validate_trigger_args("test-face", "20260905") is None
    assert flow.validate_trigger_args("Test-Face", "20260905") is not None   # 大写
    assert flow.validate_trigger_args("test-face", "20269") is not None      # 期号残
    assert flow.validate_trigger_args("test-face", "20261301") is None       # 只查形不查历（历归 trigger）


# ---------- 发现清单落票面 ----------

def _scan_result():
    return {
        "findings": [
            {"id": "guard-anchor:a1", "scan": "guard-anchor", "severity": "high",
             "subject": "sc_x ⇢ 旧文案", "evidence": "字面与组合片段双缺", "suggestion": "修锚"},
            {"id": "stale-ref:b2", "scan": "stale-ref", "severity": "med",
             "subject": "sc_y ⇢ gone.py", "evidence": "已挪", "suggestion": "改引用"},
            {"id": "duplicate:c3", "scan": "duplicate", "severity": "low",
             "subject": "dup:a × b", "evidence": "重叠", "suggestion": "合并"},
        ],
        "summary": {"high": 1, "med": 1, "low": 1},
        "heartbeat": False,
        "meta": {"scenarios": 2},
    }


def test_build_ticket_face_renders_findings_and_suggestions():
    face = flow.build_ticket_face("inspection-test-face-20260905", "test-face", "test", "20260905",
                                  _scan_result())
    assert face["kind"] == "inspection" and face["red_line"] == flow.INSPECTION_RED_LINE
    assert len(face["findings"]) == 3
    sug = face["suggested_fix_tickets"]
    assert [s["urgency"] for s in sug] == ["立即开票", "人审后定"]      # low 不立票
    assert all(s["source_inspection"] == "inspection-test-face-20260905" for s in sug)
    assert all(s["template"] == "dev-lane" for s in sug)               # 修复一律 dev-lane


def test_zero_finding_face_is_heartbeat_ticket():
    empty = {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True, "meta": {}}
    face = flow.build_ticket_face("inspection-t-f-20260905", "t", "test", "20260905", empty)
    assert face["heartbeat"] is True and face["heartbeat_note"] != ""
    assert face["suggested_fix_tickets"] == []                          # 全绿=零开票建议


def test_build_ticket_face_malformed_scan_result_rejected():
    with pytest.raises(ValueError):
        flow.build_ticket_face("t", "i", "test", "20260905", {"nope": 1})
    with pytest.raises(ValueError):
        flow.build_ticket_face("", "i", "test", "20260905", _scan_result())


# ---------- 人门签字校验（M3：复用 Signature 语义，真拦） ----------

def test_close_signature_accepts_human_approve_and_reject():
    ok_payload, err = flow.validate_close_signature(
        {"who": "宿主", "gate": flow.CLOSE_GATE_ID, "decision": "approve", "note": ""})
    assert err == "" and ok_payload["who"] == "宿主"
    ok_payload, err = flow.validate_close_signature(
        {"who": "总管", "gate": flow.CLOSE_GATE_ID, "decision": "reject", "note": "毙"})
    assert err == "" and ok_payload["decision"] == "reject"


def test_close_signature_rejects_agent_self_sign():
    _, err = flow.validate_close_signature(
        {"who": "developer", "gate": flow.CLOSE_GATE_ID, "decision": "approve"})
    assert "不得自签" in err


def test_close_signature_rejects_wrong_gate_and_decision():
    _, err = flow.validate_close_signature(
        {"who": "宿主", "gate": "approve", "decision": "approve"})
    assert "gate 不匹配" in err
    _, err = flow.validate_close_signature(
        {"who": "宿主", "gate": flow.CLOSE_GATE_ID, "decision": "maybe"})
    assert "approve/reject" in err
    _, err = flow.validate_close_signature({"who": "", "gate": flow.CLOSE_GATE_ID, "decision": "approve"})
    assert "who" in err


def test_close_signature_accepts_signature_dataclass():
    from shared import Signature
    payload, err = flow.validate_close_signature(
        Signature(who="宿主", gate=flow.CLOSE_GATE_ID, decision="approve"))
    assert err == "" and payload["decision"] == "approve"


# ---------- 落账 ----------

def test_write_inspection_report_roundtrip_and_overwrite(tmp_path):
    face = flow.build_ticket_face("inspection-t-f-20260905", "t", "test", "20260905", _scan_result())
    out = flow.write_inspection_report_impl(face, tmp_path)
    path = Path(out["path"])
    assert path.name == "inspection-t-f-20260905.json"
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "inspection"
    face["human_gate"] = {"who": "宿主", "decision": "approve"}          # 收口时再写=覆盖同文件
    flow.write_inspection_report_impl(face, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["human_gate"]["decision"] == "approve"
    with pytest.raises(ValueError):
        flow.write_inspection_report_impl({}, tmp_path)


# ---------- workflow 结构面（真链路两拍在验收①手动证据承载） ----------

def test_workflow_registered_and_gate_structured():
    from workflows import ALL_WORKFLOWS
    assert flow.InspectionPeriodicWorkflow in ALL_WORKFLOWS
    wf = flow.InspectionPeriodicWorkflow
    assert hasattr(wf, "sign") and hasattr(wf, "snapshot") and hasattr(wf, "run")
    assert flow.CLOSE_GATE_ID == "inspection-close"


def test_input_defaults_declared_workflow_name():
    inp = flow.InspectionPeriodicInput(instance_id="test-face")
    assert inp.face == "test" and inp.period == ""   # 空=workflow.now() 推期（schedule 路径）
