# -*- coding: utf-8 -*-
"""t260915-18 stage 面巡检电池：扫描器纯函数（fake runner 注入，零 docker）+
声明面接线（R2：新实例解析 + 既有实例零变化）+ activities face=stage 分派。

畸形输入用例（工程惯例）：回执空/非 JSON/rc≠0/ok≠true/CLI 缺席——全部桩化
复现，不靠真外部源。
"""
import json
import logging
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import activities  # noqa: E402
import inspection_decl as decl  # noqa: E402
import inspection_scan_stage as st  # noqa: E402
from inspection_scan import ScanError  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent.parent          # 扫描器入参=仓根（inventory CLI 在 <repo>/integration）


def ok_runner(receipt, rc=0):
    return lambda cmd, cap: (rc, json.dumps(receipt, ensure_ascii=False) + "\n", "")


def receipt(containers=3, projects=2, leases=2, orphans=0, max_stages=100,
            out_of_domain=None, stages=None):
    if stages is None:
        stages = [{"project": "ui-shot-x-g0", "working_dir": "/tmp/r/server",
                   "orphan": False, "holder_ticket": "t1/gen0", "holder_pid": 1,
                   "anchor_pid": 2, "owner_root": "/tmp/r", "heartbeat_age_s": 3,
                   "age_s": 100, "names": ["a-temporal"], "containers": 1}
                  for _ in range(max(leases, 1))]
        for i in range(orphans):
            stages.append({"project": "orphan-%d" % i, "working_dir": "/tmp/r/server",
                           "orphan": True, "holder_ticket": None, "holder_pid": None,
                           "anchor_pid": None, "owner_root": None,
                           "heartbeat_age_s": None, "age_s": 3600 * (i + 1),
                           "names": ["o-temporal"], "containers": 1})
    return {"ok": True,
            "capacity": {"containers": containers, "projects": projects,
                         "leases": leases, "orphans": orphans,
                         "max_stages": max_stages,
                         "out_of_domain_projects": len(out_of_domain or [])},
            "stages": stages, "out_of_domain": out_of_domain or []}


def faces(result):
    return {(f["scan"], f["subject"]): f for f in result["findings"]}


# ---- 扫描器 ------------------------------------------------------------------

def test_missing_repo_fails_closed(tmp_path):
    with pytest.raises(ScanError):
        st.run_stage_face_scan(tmp_path / "nope")


def test_healthy_heartbeat_true():
    r = st.run_stage_face_scan(REPO, runner=ok_runner(receipt()))
    assert r["face"] == "stage" and r["heartbeat"] is True
    assert r["findings"] == [] and r["summary"] == {"high": 0, "med": 0, "low": 0}
    assert r["meta"]["checked"] is True


def test_orphans_named_med():
    r = st.run_stage_face_scan(REPO, runner=ok_runner(receipt(orphans=3)))
    f = faces(r)[("stage-inventory", "S11 孤儿容器")]
    assert f["severity"] == "med"
    assert "孤儿台 3 只" in f["evidence"]
    assert "sweep --dry-run" in f["suggestion"], "开票建议必须导向复核而非直接拆"
    assert r["heartbeat"] is False


def test_near_fuse_high():
    r = st.run_stage_face_scan(REPO, runner=ok_runner(receipt(containers=85)))
    assert ("stage-inventory", "S12 容量逼近闸") in faces(r)
    r2 = st.run_stage_face_scan(REPO, runner=ok_runner(receipt(containers=79)))
    assert ("stage-inventory", "S12 容量逼近闸") not in faces(r2), "阈值下不报"


def test_at_fuse_high_mutually_exclusive():
    r = st.run_stage_face_scan(REPO, runner=ok_runner(receipt(containers=100)))
    fl = faces(r)
    assert ("stage-inventory", "S13 容量撞闸") in fl
    assert ("stage-inventory", "S12 容量逼近闸") not in fl, "撞闸不双报"


def test_out_of_domain_low_only():
    r = st.run_stage_face_scan(REPO, runner=ok_runner(
        receipt(out_of_domain=[{"project": "someone-elses", "working_dir": "/opt/x"}])))
    f = faces(r)[("stage-inventory", "S15 域外容器在册")]
    assert f["severity"] == "low" and "someone-elses" in f["evidence"]


@pytest.mark.parametrize("runner", [
    lambda cmd, cap: (2, "", "ENV_FAIL: docker 不可用"),        # docker 缺席 rc=2
    lambda cmd, cap: (1, "", "boom"),                           # 未知 rc
    lambda cmd, cap: (0, "", ""),                               # 空回执
    lambda cmd, cap: (0, "not json at all", ""),                # 非 JSON 回执
    lambda cmd, cap: (0, json.dumps({"ok": False, "error": "docker 不可用"}), ""),
    lambda cmd, cap: (_ for _ in ()).throw(TimeoutError("超上限")),
    lambda cmd, cap: (_ for _ in ()).throw(FileNotFoundError("CLI 缺席")),
])
def test_unchecked_is_loud_not_green(runner):
    r = st.run_stage_face_scan(REPO, runner=runner)
    assert r["heartbeat"] is False, "未检查绝不假绿"
    assert r["meta"]["checked"] is False
    f = faces(r)[("stage-inventory", "S14 未检查")]
    assert f["severity"] == "med" and f["evidence"].strip()


def test_inventory_command_shape():
    seen = {}

    def runner(cmd, cap):
        seen["cmd"], seen["cap"] = list(cmd), cap
        return 0, json.dumps(receipt()), ""

    st.run_stage_face_scan(REPO, runner=runner)
    assert seen["cmd"][-1] == "inventory"
    assert seen["cmd"][1].endswith(str(Path("integration") / "stage_docker.py"))
    assert seen["cmd"][0] == sys.executable
    assert seen["cap"] == st.INVENTORY_TIMEOUT_S


# ---- 声明面（R2：新实例解析 + 既有实例零变化） --------------------------------

def test_wired_faces_contains_stage():
    assert "stage" in decl.WIRED_FACES


def test_real_decl_parses_and_existing_instances_unchanged():
    d = decl.load_inspection_decl(ENGINE / "inspection.yaml")
    by_id = {i.id: i for i in d.instances}
    # 既有实例零变化（字段快照锚，R2）
    it = by_id["integration-tests"]
    assert it.enabled is True and it.cron == "30 7 * * *" and it.kind == "cron"
    assert it.suite == "full" and it.tz == "Asia/Shanghai"
    assert it.scan_face == "test", "票①实例不声明面（缺省 test 归一）"
    ds = by_id["docs-sync"]
    assert ds.scan_face == "doc" and ds.enabled is True and ds.cron == "0 10 * * 1"
    assert by_id["mechanism-face"].enabled is False
    assert by_id["simplify-face"].scan_face == "simplify"
    assert by_id["simplify-face"].enabled is True
    # 新实例（t260915-18）
    sc = by_id["stage-capacity"]
    assert sc.enabled is False, "占位不调度（启用按宿主节奏）"
    assert sc.scan_face == "stage"
    assert sc.kind == "cron" and sc.cron == "30 8 * * 1"
    assert sc.workflow == "InspectionPeriodicWorkflow"
    assert sc.template == "inspection-lite"
    assert sc.tz == "Asia/Shanghai"
    assert len(d.instances) == 5


def test_enabled_stage_instance_passes_unwired_face_still_rejected():
    enabled = ("schema: v1\n"
               "instances:\n"
               "  - id: stage-on\n"
               "    enabled: true\n"
               "    scan_face: stage\n"
               "    schedule:\n"
               "      kind: cron\n"
               "      cron: 30 8 * * 1\n"
               "    workflow: InspectionPeriodicWorkflow\n"
               "    template: inspection-lite\n")
    d = decl.parse_decl_text(enabled)
    assert d.instances[0].scan_face == "stage"
    unwired = enabled.replace("scan_face: stage", "scan_face: voice")
    with pytest.raises(decl.DeclError, match="voice"):
        decl.parse_decl_text(unwired), "词表外启用面仍 fail-closed"


# ---- activities face=stage 分派 ------------------------------------------------

class _FakeActivity:
    logger = logging.getLogger("ut-activity")


def test_activities_stage_face_dispatch(monkeypatch):
    captured = {}

    def fake_scan(root):
        captured["root"] = root
        return {"face": "stage", "findings": [], "summary": {"high": 0, "med": 0, "low": 0},
                "heartbeat": True, "meta": {"checked": True}}

    monkeypatch.setattr(activities, "activity", _FakeActivity)
    monkeypatch.setattr(st, "run_stage_face_scan", fake_scan)
    import asyncio
    out = asyncio.run(activities.run_inspection_scan(
        {"face": "stage", "repo_root": str(REPO)}))
    assert out["ok"] is True and out["result"]["face"] == "stage"
    assert captured["root"] == REPO


def test_activities_fallback_text_names_stage(monkeypatch):
    got = {}

    def fake_test_scan(root, sp=None):
        got["called"] = True
        return {"face": "test", "findings": [], "summary": {},
                "heartbeat": True, "meta": {}}

    import inspection_scan
    monkeypatch.setattr(activities, "activity", _FakeActivity)
    # 函数内 lazy import → 补丁打在真源模块的属性上（activities 侧无该名绑定）
    monkeypatch.setattr(inspection_scan, "run_test_face_scan", fake_test_scan)
    import asyncio
    out = asyncio.run(activities.run_inspection_scan(
        {"face": "voice", "repo_root": str(REPO)}))
    assert out["ok"] is True
    assert "voice" in out["result"]["meta"]["face_fallback"]
    assert "stage" in out["result"]["meta"]["face_fallback"], "fallback 名单收窄后须点名 stage"
    assert got["called"], "回落 test 面"
