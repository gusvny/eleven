"""t260915-05 模板拓扑导出面单测：导出契约结构 + 一致性锁 + snapshot 门两态。

覆盖口径（=create_plan gen1 方案步骤 1 验证面）：
  A. 导出契约结构自检：dev-lane 契约五键齐全、kind 词表、边推导性质
     （组内相邻边折叠/扇出扇入/连通性/人门唯一汇）。
  B. 一致性锁（编码真源 STAGES）：导出面节点集与逐字段（label/role/kind/parts）
     比对 DevLaneWorkflow.STAGES——STAGES 改了不改导出面，此处必红；
     optional 注记仅 ui_evidence（dev_lane.py「UI 票只跑」注释锚）。
  C. 一致性锁（真分叉）：源码锁 run() 两个 asyncio.gather 分叉的成员集合
     （parallel_impl_design / arb_acc_parallel 两 phase 块内的 pend.append 字面量）
     与导出面 groups 相等——组员写错或 run() 改分叉成员，此处必红。
  D. fixture-two-step：另一模板拓扑（线性两段、无组）——渲染器通用性对拍的
     数据面真源。
  E. 边界与畸形：未知模板 None；build_topology 对畸形声明逐条 ValueError
     （岗位说明书纪律：消费/产出面的畸形输入必测）。
  F. snapshot 门两态：门开=顶层 topology 键（additive）；门关=无键（旧实例
     重放零新键）；UT 壳未置位 getattr 防御不炸（t260915-01 同款三分支）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：主树 venv `.../engine/.venv/bin/python -m pytest server/engine/tests/test_template_topology.py -q`。
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import template_topology as tt  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

DEV_LANE_FORK_EDGES = {
    ("review_plan", "implement"), ("review_plan", "design_integration_tests"),
    ("implement", "ui_evidence"), ("design_integration_tests", "ui_evidence"),
    ("run_integration_tests", "arbitrate"), ("run_integration_tests", "acceptance_walkthrough"),
    ("arbitrate", "merge_check"), ("acceptance_walkthrough", "merge_check"),
}


def _fork_edges_as_sets(pairs):
    return {tuple(p) for p in pairs}


async def _wake_immediately(cond) -> None:
    return None


def _mk_wf(detail_face: bool = True):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（test_t260915_01 同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"stage": "create_plan", "blocked_reason": "", "blocked_detail": None}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut"
    wf._detail_face_on = detail_face
    wf.engine_version = 2
    return wf


# ---------- A. 导出契约结构 ----------

def test_export_dev_lane_contract_shape():
    topo = tt.export_template_topology("dev-lane")
    assert topo is not None
    assert topo["version"] == tt.CONTRACT_VERSION
    assert topo["template"] == "dev-lane"
    assert isinstance(topo["name"], str) and topo["name"]
    ids = [n["id"] for n in topo["nodes"]]
    assert len(ids) == len(set(ids)) == len(dev_lane.DevLaneWorkflow.STAGES)
    for n in topo["nodes"]:
        assert n["kind"] in (tt.KIND_AGENT, tt.KIND_GATE, tt.KIND_HUMAN)
        assert isinstance(n["label"], str) and n["label"]
        assert isinstance(n["parts"], list)
    # 边性质：组内相邻边折叠、扇出扇入在、链两端在、人门是唯一汇
    edges = _fork_edges_as_sets(topo["edges"])
    assert len(topo["edges"]) == len(edges), "边集无重复（链邻接边与 fork/join 边重合须去重）"
    assert ("implement", "design_integration_tests") not in edges, "组内相邻边必须折叠"
    assert ("arbitrate", "acceptance_walkthrough") not in edges, "组内相邻边必须折叠"
    assert DEV_LANE_FORK_EDGES <= edges, "两分叉的扇出/扇入边必须齐全"
    assert ("create_plan", "review_plan") in edges and ("merge_check", "merge") in edges
    outgoing = {a for a, _ in edges}
    incoming = {b for _, b in edges}
    assert incoming == set(ids) - {"create_plan"}, "除首段外人人有入边"
    sinks = set(ids) - outgoing
    assert sinks == {"merge"}, "人门 merge 必须是唯一汇（单向流）"


# ---------- B. 一致性锁：STAGES 编码真源 ----------

def test_consistency_lock_against_stages():
    topo = tt.export_template_topology("dev-lane")
    by_id = {n["id"]: n for n in topo["nodes"]}
    for st in dev_lane.DevLaneWorkflow.STAGES:
        n = by_id[st.id]
        assert n["label"] == st.name, "%s label 漂移" % st.id
        assert n["role"] == st.role, "%s role 漂移" % st.id
        assert n["kind"] == st.kind, "%s kind 与 Stage.kind 投影漂移" % st.id
        assert n["parts"] == list(st.parts), "%s parts 漂移" % st.id
    # 条件段注记：仅 ui_evidence（dev_lane.py t260828-09 注释「UI tickets only」）
    optional = {n["id"]: n.get("optional") for n in topo["nodes"] if n.get("optional")}
    assert optional == {"ui_evidence": tt.OPT_UI_TICKETS}


# ---------- C. 一致性锁：run() 真分叉成员 ----------

def _phase_block_source(phase: str) -> str:
    src = Path(dev_lane.__file__).read_text(encoding="utf-8")
    m = re.search(r'if phase == "%s":' % re.escape(phase), src)
    assert m, "run() 里找不到分叉相位 %s" % phase
    tail = src[m.end():]
    # 块边界=下一个同缩进 `if phase ==`（主相循环分派结构）
    nxt = re.search(r'\n            if phase == "', tail)
    return tail[:nxt.start()] if nxt else tail


def test_consistency_lock_real_forks():
    topo = tt.export_template_topology("dev-lane")
    groups = {g["id"]: g for g in topo["groups"]}
    assert set(groups) == {"parallel_impl_design", "arb_acc_parallel"}
    for gid, members in (("parallel_impl_design", ("implement", "design_integration_tests")),
                         ("arb_acc_parallel", ("arbitrate", "acceptance_walkthrough"))):
        assert tuple(groups[gid]["members"]) == members
        assert groups[gid]["phase"] == gid
        block = _phase_block_source(gid)
        for m in members:
            assert 'pend.append("%s")' % m in block, \
                "%s 真分叉成员漂移：run() %s 块不再 append %s" % (gid, gid, m)


# ---------- D. fixture-two-step（另一模板拓扑） ----------

def test_fixture_two_step_topology():
    sys.path.insert(0, str(POC / "fixtures"))
    import fixture_two_step  # noqa: F401  # 注册入口模块（只取 STAGES 常量比对）
    topo = tt.export_template_topology("fixture-two-step")
    assert topo is not None
    assert topo["template"] == "fixture-two-step"
    assert [n["id"] for n in topo["nodes"]] == [s.id for s in fixture_two_step.FixtureTwoStepWorkflow.STAGES]
    assert topo["groups"] == []
    assert topo["edges"] == [["fx_step_one", "fx_step_two"]], "线性模板=纯顺序边"


# ---------- E. 边界与畸形 ----------

def test_unknown_template_returns_none():
    assert tt.export_template_topology("no-such-template") is None
    assert tt.export_template_topology("") is None
    assert tt.export_template_topology(None) is None  # type: ignore[arg-type]


def test_build_topology_malformed_declarations_fail_closed():
    good = {"id": "a", "label": "甲", "role": "developer", "kind": "agent", "parts": []}
    good2 = {"id": "b", "label": "乙", "role": "integration", "kind": "gate", "parts": []}
    cases = [
        ("重复 id", [good, dict(good)], []),
        ("kind 越词表", [{**good, "kind": "magic"}], []),
        ("缺 label", [{k: v for k, v in good.items() if k != "label"}], []),
        ("组员越表", [good, good2], [{"id": "g", "members": ["a", "ghost"], "phase": "p"}]),
        ("组太小", [good, good2], [{"id": "g", "members": ["a"], "phase": "p"}]),
        ("组员不连续", [good, good2, {"id": "c", "label": "丙", "role": "ops",
                                       "kind": "agent", "parts": []}],
         [{"id": "g", "members": ["a", "c"], "phase": "p"}]),
    ]
    for label, nodes, groups in cases:
        try:
            tt.build_topology("t-ut", "夹具", nodes, groups)
        except ValueError as e:
            assert "拓扑声明非法" in str(e)
        else:
            raise AssertionError("畸形声明未 fail-closed：%s" % label)
    # 非字典节点同样拦下
    try:
        tt.build_topology("t-ut", "夹具", ["not-a-dict"], [])
    except ValueError:
        pass
    else:
        raise AssertionError("非字典节点未 fail-closed")


# ---------- F. snapshot 门两态 ----------

def test_snapshot_gate_topology_key():
    wf = _mk_wf(True)
    wf.signatures, wf.gate_runs, wf.refused, wf.human_context = {}, [], [], {}
    snap = dev_lane.DevLaneWorkflow.snapshot(wf)
    assert snap["topology"]["template"] == "dev-lane"
    assert "topology" in snap
    wf2 = _mk_wf(False)
    wf2.signatures, wf2.gate_runs, wf2.refused, wf2.human_context = {}, [], [], {}
    snap2 = dev_lane.DevLaneWorkflow.snapshot(wf2)
    assert "topology" not in snap2, "门关=旧实例重放零新键"
    wf3 = object.__new__(dev_lane.DevLaneWorkflow)  # UT 壳未置位：getattr 防御不炸
    wf3.ticket_id = "t-ut"
    wf3._gens = {}
    wf3.meta = {"blocked_reason": "", "blocked_detail": None}
    wf3.timeline = []
    wf3.signatures, wf3.gate_runs, wf3.refused, wf3.human_context = {}, [], [], {}
    wf3.results = {}
    wf3._retry_token = 0
    snap3 = dev_lane.DevLaneWorkflow.snapshot(wf3)
    assert "topology" not in snap3
