"""t260910-09 票②：face 分派缝 + 巡检票面形状单测（inspection_flow / activities 契约）。

锁四个行为级点（方案 D6/C4 + 验收 3/4）：
  - 分派真值表：face=test→run_test_face_scan、face=mechanism/simplify→新面、
    缺省=test（既有调用零变化）、未知面→ScanError 点名已接线清单（fail-closed）；
  - InspectionPeriodicInput.face 透传：activity args 含 face（源码序锁，flow 不再
    写死测试面——C4 时间线文案同锁）；
  - build_ticket_face 对新面 result 通用消费：票面六键形状不变（UI 巡检行不破坏）、
    med/high 自动生成 suggested_fix_tickets 且 source_inspection=本巡检票号；
  - 零发现心跳语义不变：heartbeat=true + heartbeat_note 心跳文案。
纯函数层测试，不碰真 Temporal。
"""
import ast
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_scan_ms as ms  # noqa: E402
from inspection_flow import InspectionPeriodicInput, build_ticket_face  # noqa: E402

FLOW_SRC = (POC / "inspection_flow.py").read_text(encoding="utf-8")
ACT_SRC = (POC / "activities.py").read_text(encoding="utf-8")


def make_repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    (d / "server" / "engine").mkdir(parents=True)
    (d / "integration").mkdir(parents=True)
    (d / "server" / "engine" / "m.py").write_text("def zombie():\n    return 1\n", encoding="utf-8")
    # test 面扫描需要场景清单（ScanError「场景清单缺位」的 fail-closed 前提）
    (d / "integration" / "run_scenarios.py").write_text("SCENARIOS = []\n", encoding="utf-8")
    return d


# ---------- 分派真值表 ----------

def test_dispatch_known_faces(tmp_path):
    root = make_repo(tmp_path)
    r = ms.run_face_scan("mechanism", root)
    assert r["face"] == "mechanism" and r["summary"]["med"] >= 1   # zombie 必被机制面抓到
    r2 = ms.run_face_scan("simplify", root)                        # simplify 面可跑且形状齐
    assert r2["face"] == "simplify" and "heartbeat" in r2


def test_dispatch_unknown_face_names_wired(tmp_path):
    with pytest.raises(ms.ScanError) as ei:
        ms.run_face_scan("nope", tmp_path)
    msg = str(ei.value)
    assert "nope" in msg and "mechanism" in msg and "simplify" in msg


def test_activity_default_face_is_test_and_dispatch_wiring():
    """activities 源码序锁：face 缺省 test；test 走 run_test_face_scan；mechanism/simplify
    走 run_face_scan；未接线面走回落分支并写 face_fallback 标注（rework r2 语义）。"""
    assert 'str(args.get("face") or "test")' in ACT_SRC
    assert 'if face == "test":' in ACT_SRC
    assert 'elif face in ("mechanism", "simplify"):' in ACT_SRC
    assert "run_test_face_scan(root" in ACT_SRC and "run_face_scan(face, root)" in ACT_SRC
    assert "face_fallback" in ACT_SRC


def test_activity_unwired_face_falls_back_to_test_with_annotation(tmp_path):
    """分派行为锁（arbitrate code-fault 260910 修复面）：face=doc（票① 声明在案未接线
    面）回落 test 面扫描 ok:true——doc-face 零发现心跳票语义保持；回落绝不静默：
    meta.face_fallback 点名请求面与已接线清单。"""
    import asyncio

    import activities  # noqa: E402  # 需 temporalio（venv 解释器）

    root = make_repo(tmp_path)
    for req in ("doc", "bogus-face"):
        r = asyncio.run(activities.run_inspection_scan({"repo_root": str(root), "face": req}))
        assert r["ok"] is True, r
        res = r["result"]
        assert res["face"] == "test"
        note = str(res["meta"].get("face_fallback") or "")
        assert req in note and "mechanism" in note and "simplify" in note, note


def test_activity_wired_faces_dispatch(tmp_path):
    """分派行为锁：缺省/无键=test（零变化半边）；face=mechanism 走新面。"""
    import asyncio

    import activities  # noqa: E402

    root = make_repo(tmp_path)
    r0 = asyncio.run(activities.run_inspection_scan({"repo_root": str(root)}))
    assert r0["ok"] is True and r0["result"]["face"] == "test"
    assert "face_fallback" not in r0["result"]["meta"]
    r1 = asyncio.run(activities.run_inspection_scan({"repo_root": str(root), "face": "mechanism"}))
    assert r1["ok"] is True and r1["result"]["face"] == "mechanism"


def test_flow_passes_face_into_activity_args_and_timeline():
    """flow 源码序锁：activity args 带 face 键；时间线文案含 face 值（C4，不再写死「测试面」）。"""
    assert '"face": inp.face' in FLOW_SRC
    assert '"%s 面扫描（实例 %s 期 %s）" % (inp.face' in FLOW_SRC
    assert "测试面扫描（实例" not in FLOW_SRC


def test_periodic_input_default_face_is_test():
    assert InspectionPeriodicInput(instance_id="x").face == "test"


# ---------- 票面形状（UI 巡检行消费不破坏）----------

def _mechanism_result() -> dict:
    return {
        "face": "mechanism",
        "findings": [{
            "id": "dead-mechanism:abc1234567",
            "scan": "dead-mechanism",
            "severity": "med",
            "subject": "dead:zombie (server/engine/m.py)",
            "evidence": "dead-man 嫌疑——三面全零。m.py:1 定义；场景引用 0 次（搜 0 个场景文件）；引用点 0 处",
            "suggestion": "人审；退役走 dev-lane 工单（引用来源巡检票）",
        }],
        "summary": {"high": 0, "med": 1, "low": 0},
        "heartbeat": False,
        "meta": {"candidates": 1, "red_line": "巡检只出报告与开票建议，绝不直接改码"},
    }


def test_build_ticket_face_consumes_mechanism_result_generically():
    face = build_ticket_face("inspection-mechanism-face-20260910", "mechanism-face",
                             "mechanism", "20260910", _mechanism_result())
    assert face["kind"] == "inspection" and face["face"] == "mechanism"
    assert face["heartbeat"] is False and face["summary"]["med"] == 1
    assert face["findings"][0]["id"] == "dead-mechanism:abc1234567"
    sugg = face["suggested_fix_tickets"]
    assert len(sugg) == 1 and sugg[0]["source_inspection"] == "inspection-mechanism-face-20260910"
    assert sugg[0]["template"] == "dev-lane"


def test_build_ticket_face_heartbeat_zero_finding_semantics():
    """零发现 → heartbeat=true + 心跳文案 + 零开票建议（心跳票语义与票①逐字段一致）。"""
    result = {"face": "simplify", "findings": [],
              "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True, "meta": {}}
    face = build_ticket_face("inspection-simplify-face-20260910", "simplify-face",
                             "simplify", "20260910", result)
    assert face["heartbeat"] is True
    assert "心跳" in face["heartbeat_note"]
    assert face["suggested_fix_tickets"] == []


def test_build_ticket_face_malformed_result_fails_closed():
    from inspection_flow import INSPECTION_RED_LINE
    with pytest.raises(ValueError):
        build_ticket_face("t", "i", "mechanism", "20260910", {"findings": "not-a-list"})
