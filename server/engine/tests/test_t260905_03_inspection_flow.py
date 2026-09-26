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


def test_validate_period_key_and_ledger_name_shape():
    """t260916-02：铸号迁起票侧（inspection_ticketing 铸 t 形号），workflow 体只留
    期号形状闸；台账文件名按实例+期派生（键名约定，不是票号——旧实现恰好同名，
    老票重放逐字节不变）。"""
    flow.validate_period_key("integration-tests", "20260905")   # 合法不抛
    flow.validate_period_key("integration-tests", "20260905-3")
    with pytest.raises(ValueError):
        flow.validate_period_key("integration-tests", "2026-09-05")
    with pytest.raises(ValueError):
        flow.validate_period_key("", "20260905")
    assert flow.inspection_ledger_name(
        "integration-tests", "20260905") == "inspection-integration-tests-20260905.json"
    with pytest.raises(ValueError):
        flow.inspection_ledger_name("integration-tests", "bad")


def test_validate_trigger_args_fail_closed():
    assert flow.validate_trigger_args("integration-tests", "20260905") is None
    assert flow.validate_trigger_args("Test-Face", "20260905") is not None   # 大写
    assert flow.validate_trigger_args("integration-tests", "20269") is not None      # 期号残
    assert flow.validate_trigger_args("integration-tests", "20261301") is None       # 只查形不查历（历归 trigger）


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
    face = flow.build_ticket_face("inspection-integration-tests-20260905", "integration-tests", "20260905",
                                  _scan_result())
    assert face["kind"] == "inspection" and face["red_line"] == flow.INSPECTION_RED_LINE
    assert len(face["findings"]) == 3
    assert "face" not in face  # 报告形状已无 face 键（t260910-11 除名，防与 self.face 撞名）
    sug = face["suggested_fix_tickets"]
    assert [s["urgency"] for s in sug] == ["open now", "after human review"]   # low 不立票
    assert all(s["source_inspection"] == "inspection-integration-tests-20260905" for s in sug)
    assert all(s["template"] == "dev-lane" for s in sug)               # 修复一律 dev-lane


def test_zero_finding_face_is_heartbeat_ticket():
    empty = {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True, "meta": {}}
    face = flow.build_ticket_face("inspection-t-f-20260905", "t", "20260905", empty)
    assert face["heartbeat"] is True and face["heartbeat_note"] != ""
    assert face["suggested_fix_tickets"] == []                          # 全绿=零开票建议


def test_build_ticket_face_malformed_scan_result_rejected():
    with pytest.raises(ValueError):
        flow.build_ticket_face("t", "i", "20260905", {"nope": 1})
    with pytest.raises(ValueError):
        flow.build_ticket_face("", "i", "20260905", _scan_result())


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
    # t260916-02：落账文件名=实例+期键名（不是票号——票号已 t 形化，id 任意都不影响
    # 文件名；同票重跑覆盖同文件）
    face = flow.build_ticket_face("t060905-01", "t", "20260905", _scan_result())
    out = flow.write_inspection_report_impl(face, tmp_path)
    path = Path(out["path"])
    assert path.name == "inspection-t-20260905.json"
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "inspection"
    face["human_gate"] = {"who": "宿主", "decision": "approve"}          # 收口时再写=覆盖同文件
    flow.write_inspection_report_impl(face, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["human_gate"]["decision"] == "approve"
    with pytest.raises(ValueError):
        flow.write_inspection_report_impl({}, tmp_path)
    with pytest.raises(ValueError):
        # 缺期号 face（畸形票面）显式拒收——不落半截文件名
        flow.write_inspection_report_impl({"instance_id": "t"}, tmp_path)


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


def test_inspection_periodic_input_face_default_locked():
    """兼容红线（t260910-11）：声明 face 除名后，workflow 输入结构保留 face 并给默认值，
    历史重放（无 face 或缺字段）解码不报错。"""
    inp = flow.InspectionPeriodicInput(instance_id="integration-tests")
    assert inp.face == "test"
    inp2 = flow.InspectionPeriodicInput(instance_id="i", face="legacy-value")
    assert inp2.face == "legacy-value"


# ---------- t260910-11：ticket 查询回执纯函数（工单详情同构） ----------

def test_ticket_receipt_maps_snapshot_shape():
    import inspection_trigger as trig
    snap = {"id": "inspection-i-20260910", "kind": "inspection", "stage": "close",
            "stage_state": "awaiting-human", "status": "running", "decision": "",
            "face": {"summary": {"high": 1, "med": 2, "low": 0}, "heartbeat": False,
                     "findings": [{"id": "f1", "scan": "stale-ref", "severity": "high",
                                   "subject": "x" * 200, "evidence": "e"},
                                  "非 dict 条目降级",
                                  {"id": "f2", "scan": "s", "severity": "med", "subject": "y"}],
                     "red_line": "R", "report_path": "/p.json", "human_gate": {"who": "h"}},
            "timeline": [1, 2, 3]}
    out = trig.ticket_receipt(snap, "inspection-i-20260910")
    assert out["stage"] == "close" and out["status"] == "running"
    assert out["face"]["summary"] == {"high": 1, "med": 2, "low": 0}
    assert out["face"]["findings_total"] == 3
    assert len(out["face"]["findings_brief"]) == 2          # 非 dict 条目降级
    assert len(out["face"]["findings_brief"][0]["subject"]) == 80  # 摘要截断
    assert out["timeline_len"] == 3 and out["human_gate"] == {"who": "h"}


def test_ticket_receipt_malformed_snapshot_degrades_not_crashes():
    """畸形快照（缺键/错型）不崩、不编造（畸形≠缺省：如实出空值）。"""
    import inspection_trigger as trig
    for snap in ({}, {"face": "not-a-dict"}, {"face": {"findings": "nope"}},
                 {"timeline": "x"}, {"face": {"findings": [None, 42]}}):
        out = trig.ticket_receipt(snap, "inspection-t-20260910")
        assert out["id"] == "inspection-t-20260910"        # 票号兜底自填
        assert isinstance(out["face"], dict) and isinstance(out["face"]["findings_brief"], list)
        assert out["timeline_len"] == 0
