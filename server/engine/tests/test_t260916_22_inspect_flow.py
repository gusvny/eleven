"""t260916-22：inspect 段 workflow 接线单测（inspection_flow.py / inspection_decl.py）。

覆盖（方案 §4 步骤3 验证清单）：
- 超时双闸不等式：inspect 段 start_to_close ≥ 声明预算 + 复核余量（活动内部
  deadline=预算−margin 必须先于 Temporal 硬杀——SUITE_TO 纪律同款）；
- STAGES 新段序：scan 退役、inspect 接位（setup→suite→inspect→report→close，
  仍 5 段、setup 起 close 收、suite_only 恰 setup+suite）；
- 轨道分派结构锁：run=薄分派（双版本门），新命令全部在 INSPECT_PATCH_ID 门后；
- build_ticket_face 扩展：建议门三条件（verified && confidence≥0.6 && severity≥med）
  逐条子用例 + legacy 发现（无 verified 键）原门逐字节不变 + 新字段透传 + 摘要排除
  recurring/压制；
- FindingVerdict 载荷校验纯函数（gate/who/verdict 词表/finding-id/载荷类型）；
- decl 预算三键（max_findings/inspect_timeout_min/inspect_profile）：正用例解析 +
  plan["inspect"] 透传 + 反用例越域点名 + WIRED_FACES↔PROFILE_FACES 同集锁。
"""
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl  # noqa: E402
import inspection_flow as flow  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import template_topology as tt  # noqa: E402

STAGES = flow.InspectionPeriodicWorkflow.STAGES


# ---------- 超时双闸不等式 ----------

def test_inspect_timeout_deadline_inequality():
    """内部 deadline=预算−60s 必须先于 Temporal start_to_close=预算+120s：
    活动先超时收进程组、回执「agent 未完成」，Temporal 只兜底（SUITE_TO 同款纪律）。"""
    from inspection_inspect import INSPECT_DEADLINE_MARGIN_SEC
    for budget in (30 * 60, 60 * 60, 60.0):
        to = flow.inspect_start_to_close(budget)
        assert to.total_seconds() >= budget + INSPECT_DEADLINE_MARGIN_SEC, budget
        internal = budget - INSPECT_DEADLINE_MARGIN_SEC
        assert to.total_seconds() > internal, "Temporal 必须晚于内部 deadline"
    assert flow.inspect_start_to_close(1800) == timedelta(seconds=1920)
    assert flow.INSPECT_TO_EXTRA_SEC == 120.0


# ---------- STAGES 新段序 ----------

def test_stages_shape_and_new_order():
    ids = [s.id for s in STAGES]
    assert ids == ["setup", "suite", "inspect", "report", "close"]
    assert ids[0] == "setup" and ids[-1] == "close"
    assert "scan" not in ids, "scan 段退役（t260916-22）"
    by = {s.id: s for s in STAGES}
    assert by["inspect"].name == "巡检审查" and by["inspect"].next == "report"
    assert by["suite"].next == "inspect" and by["setup"].next == "suite"
    assert {s.id for s in STAGES if s.suite_only} == {"setup", "suite"}
    assert by["close"].exit == "human"
    # 展示面导出同步（同源锁的引擎半边）
    topo = tt.export_template_topology("inspection-lite")
    assert [n["id"] for n in topo["nodes"]] == ids
    assert by["inspect"].name in {n["label"] for n in topo["nodes"]}


def test_dispatch_gate_structure():
    """run=薄分派：双版本门决定轨道；老在途票（INSPECT 门未开）必须落 legacy 轨。"""
    import inspect as _inspect
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow.run)
    assert "workflow.patched(SUITE_PATCH_ID)" in src
    assert "workflow.patched(INSPECT_PATCH_ID)" in src
    assert "self._run_inspect_period_flow" in src
    assert "_run_legacy_period_flow" in src
    idx_inspect = src.index("_run_inspect_period_flow")
    idx_guard = src.index("workflow.patched(INSPECT_PATCH_ID)")
    assert idx_guard < idx_inspect, "分派门必须先于新轨道调用"
    legacy_src = _inspect.getsource(flow._run_legacy_period_flow)
    assert '"run_inspection_scan"' in legacy_src, "旧轨道保留 scan 活动（replay 用）"
    new_src = _inspect.getsource(flow.InspectionPeriodicWorkflow._run_inspect_period_flow)
    assert '"run_inspection_scan"' not in new_src, "新轨道零静态扫描活动调用（退役断言）"
    assert '"run_inspection_inspect"' in new_src
    assert '"verify_inspection_findings"' in new_src
    assert 'workflow.patched(INSPECT_PATCH_ID)' not in new_src, "新轨道整体在门后，不重复判门"


def test_legacy_scan_call_sites_only_in_legacy():
    """退役验收：全 flow 模块内 run_inspection_scan 活动调用点只在 legacy 轨道函数。"""
    import re as _re
    flow_src = (POC / "inspection_flow.py").read_text(encoding="utf-8")
    calls = [m.start() for m in _re.finditer(r'"run_inspection_scan"', flow_src)]
    legacy = flow_src.index("async def _run_legacy_period_flow")
    assert calls and all(p > legacy for p in calls), \
        "run_inspection_scan 调用点必须全部位于文件尾 legacy 函数内（退役摘除）"


# ---------- build_ticket_face：建议门/透传/摘要 ----------

def _agent_finding(**kw):
    f = {"id": "aa11bb22", "scan": "agent", "subject": "守卫断言失效 a.py:12",
         "severity": "med", "confidence": 0.8, "verified": "verified",
         "evidence": [{"path": "a.py", "line": 12, "quote": "assert old_fn()"}],
         "why": "断言对象不存在", "suggestion": "改断言"}
    f.update(kw)
    return f


def test_face_agent_suggestion_gate_three_conditions():
    scan = {"findings": [
        _agent_finding(),                                            # med/verified/0.8 → 建议
        _agent_finding(id="b2", verified="unverified",
                       unverified_reasons=["a.py:99 行号越界"]),      # 复核不过 → 不建议
        _agent_finding(id="b3", confidence=0.59),                    # 置信不达阈 → 不建议
        _agent_finding(id="b4", severity="low"),                     # low → 不建议
        _agent_finding(id="b5", severity="high", confidence=1.0),    # high/1.0 → 建议
    ], "summary": {"high": 1, "med": 1, "low": 1}, "heartbeat": False,
        "meta": {"base_dir": "/tmp/x"}}
    face = flow.build_ticket_face("t1", "inst", "20260916", scan)
    titles = [s["title"] for s in face["suggested_fix_tickets"]]
    assert len(titles) == 2 and all("aa11bb22" not in t for t in titles)
    assert any("med" in t or "a.py:12" in t for t in titles)
    assert len(face["findings"]) == 5, "不建议的发现仍在票面（点名不静默丢）"
    unv = [f for f in face["findings"] if f.get("verified") == "unverified"]
    assert unv and unv[0]["unverified_reasons"]
    # 新字段透传
    assert face["scan_meta"] == {"base_dir": "/tmp/x"}
    assert face["findings"][0]["confidence"] == 0.8


def test_face_suppressed_and_recurring_excluded_from_summary_and_gate():
    # verify 活动的 summary 口径=summarize_counts（core UT 已锁）；此处锁 face 不破坏
    # 该口径（透传保持），且 extra 追加触发重计时同样排除 recurring/压制。
    fs = [_agent_finding(),
          _agent_finding(id="old1", recurring=True, severity="high"),
          _agent_finding(id="fake1", suppressed=True, verdict="false-positive",
                         severity="high")]
    scan = {"findings": fs, "summary": ins.summarize_counts(fs), "heartbeat": True}
    face = flow.build_ticket_face("t1", "inst", "20260916", scan)
    assert face["summary"] == {"high": 0, "med": 1, "low": 0}, "recurring/压制不进摘要"
    assert face["heartbeat"] is True
    gates = [s["title"] for s in face["suggested_fix_tickets"]]
    assert len(gates) == 1 and "a.py:12" in gates[0], \
        "只有新 med 发现进建议；recurring/假报压制的高危不重复开票"
    # extra 追加（套件红）→ 触发 build_ticket_face 重计，口径一致
    extra = [{"scan": "suite", "subject": "套件红", "severity": "high", "suggest": False}]
    face2 = flow.build_ticket_face("t1", "inst", "20260916", scan,
                                   extra_findings=extra)
    assert face2["summary"] == {"high": 1, "med": 1, "low": 0}


def test_face_legacy_findings_gate_byte_identical():
    """legacy 静态扫描发现（无 verified 键）原门不变：severity≥med+suggest 即建议，
    suggest=False 不建议；缺 verified 时不做置信门（旧发现无此字段）。"""
    legacy_ok = {"scan": "test", "subject": "旧发现A", "severity": "med",
                 "suggest": True, "evidence": "a.py:3"}
    legacy_nosuggest = {"scan": "test", "subject": "旧发现B", "severity": "high",
                        "suggest": False, "evidence": "a.py:4"}
    legacy_low = {"scan": "test", "subject": "旧发现C", "severity": "low",
                  "evidence": "a.py:5"}
    scan = {"findings": [legacy_ok, legacy_nosuggest, legacy_low],
            "summary": {"high": 1, "med": 1, "low": 1}, "heartbeat": True}
    face = flow.build_ticket_face("t1", "inst", "20260916", scan)
    assert [s["title"] for s in face["suggested_fix_tickets"]] == ["修:test 旧发现A"]
    assert face["heartbeat"] is True


def test_face_suite_still_composes_heartbeat():
    scan = {"findings": [], "summary": {"high": 0, "med": 0, "low": 0},
            "heartbeat": True}
    suite = {"ran": 3, "passed": 2, "failed": 1, "env_fail": 0, "details": []}
    face = flow.build_ticket_face("t1", "inst", "20260916", scan, suite=suite)
    assert face["heartbeat"] is False, "套件红=不是心跳期（t260913-02 口径不变）"
    assert face["suite"] == suite


# ---------- FindingVerdict 载荷校验 ----------

def test_verdict_payload_validation():
    ok_payload, err = flow.validate_finding_verdict_payload(flow.FindingVerdict(
        finding_id="aa11bb22", verdict="假报", who="宿主", note="误报"))
    assert err == "" and ok_payload["verdict"] == "false-positive"
    d, e = flow.validate_finding_verdict_payload({"finding_id": "x", "verdict": "待修",
                                                  "who": "宿主", "gate": "inspection-close"})
    assert e == "" and d["verdict"] == "to-fix"
    for sig, why in [
        (flow.FindingVerdict(finding_id="x", verdict="to-fix", who=""), "who"),
        (flow.FindingVerdict(finding_id="x", verdict="to-fix", who="d" * 65), "超长"),
        (flow.FindingVerdict(finding_id="x", verdict="to-fix", who="developer"), "agent"),
        (flow.FindingVerdict(finding_id="x", verdict="to-fix", who="宿主",
                             gate="other-gate"), "gate"),
        (flow.FindingVerdict(finding_id="", verdict="to-fix", who="宿主"), "finding-id"),
        (flow.FindingVerdict(finding_id="x", verdict="maybe", who="宿主"), "越域"),
        ("not-a-payload", "类型"),
    ]:
        _, err = flow.validate_finding_verdict_payload(sig)
        assert why in err, (sig, err)


# ---------- decl 预算三键 ----------

_DECL_HEAD = """schema: v1
instances:
  - id: budget-inst
    enabled: true
    project_key: proj
    scan_face: doc
    suite: full
    tz: Asia/Shanghai
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
    schedule:
      kind: cron
      cron: 30 7 * * *
"""


def _decl_text(extra: str) -> str:
    return _DECL_HEAD + extra


def test_decl_budget_keys_parse_and_plan_passthrough(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text("    max_findings: 25\n    inspect_timeout_min: 45\n"
                            "    inspect_profile: simplify\n"), encoding="utf-8")
    d = decl.load_inspection_decl(p)
    it = d.instance("budget-inst")
    assert (it.max_findings, it.inspect_timeout_min, it.inspect_profile) == (25, 45, "simplify")
    plan = decl._plan_from_decl(d, "budget-inst")
    assert plan["inspect"] == {"max_findings": 25, "timeout_min": 45,
                               "profile": "simplify"}


def test_decl_budget_keys_defaults(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(""), encoding="utf-8")
    d = decl.load_inspection_decl(p)
    it = d.instance("budget-inst")
    assert it.max_findings == ins.DEFAULT_MAX_FINDINGS
    assert it.inspect_timeout_min == ins.DEFAULT_INSPECT_TIMEOUT_MIN
    assert it.inspect_profile == ""        # 空=回落 scan_face（consume 侧）


@pytest.mark.parametrize("extra, why", [
    ("    max_findings: 0\n", "max_findings"),
    ("    max_findings: 10001\n", "max_findings"),
    ("    max_findings: many\n", "max_findings"),
    ("    inspect_timeout_min: 0\n", "inspect_timeout_min"),
    ("    inspect_timeout_min: 721\n", "inspect_timeout_min"),
    ("    inspect_profile: typo\n", "inspect_profile"),
])
def test_decl_budget_keys_negative_named(tmp_path, extra, why):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(extra), encoding="utf-8")
    with pytest.raises(decl.DeclError, match=why):
        decl.load_inspection_decl(p)


def test_decl_legacy_decl_without_budget_keys_still_loads():
    """老声明（无三键）零回归：解析不炸、缺省值就位（兼容红线）。"""
    d = decl.parse_decl_text(_decl_text(""), "ut")
    it = d.instance("budget-inst")
    assert it.inspect_profile == "" and it.max_findings >= 1


def test_wired_faces_profile_faces_locked():
    """双词表同集锁的显式重申（decl import 时也自锁，这里锁语义）：扩面两表同扩。"""
    assert set(decl.WIRED_FACES) == set(ins.PROFILE_FACES)
