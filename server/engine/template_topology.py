"""template_topology —— 工作流模板拓扑导出面（t260915-05，mock ④ callout F/G）。

为什么存在：workbench 泳道图的阶段链此前来自 server/workflows/*.yaml 参考快照
（workflow.py list），而 yaml 是 gen_workflows_doc.py 从 STAGES.next 线性链生成的
——dev_lane.py:437 既有注释自认「display chain 是线性近似」。真编排里 implement ∥
design_integration_tests、arbitrate ∥ acceptance_walkthrough 是两处 asyncio.gather
真并行分叉，线性链画不出来＝KI-019 根因。本模块是「引擎按模板导出 stage 图」的
承载面：节点（id/label/role/kind/parts/optional）+ 边 + 并行分叉汇合组 + 人门标记。

契约（JSON 可序列化，渲染器只认这些，零业务词）：
  {
    "version": "topology-v1",
    "template": <id>, "name": <显示名>,
    "nodes": [{"id","label","role","kind","parts":[...],"optional"?}...],
    "edges": [[from, to], ...],
    "groups": [{"id","members":[...],"phase"}...],
  }
  - kind 三值：agent（叙述段）/ gate（程序化闸）/ human（人门=虚线圈）。
    与 shared.Stage.kind 投影一致（exit=human→human；agent=False→gate；否则 agent），
    由 server/engine/tests/test_template_topology.py 一致性锁钉死。
  - edges 由「节点声明顺序 + groups」纯函数推导：组内相邻边折叠为
    fork-in→组员、组员→join-out 的扇出/扇入边——边永远不与节点顺序漂移。
  - groups.members 必须在节点声明顺序里连续（fork-join 语义）。
  - optional：条件段注记（值=给人读的短条件说明，如「仅 UI 票」），渲染器画
    虚节点+注记；缺省=必经段。
  - phase：并行相位名，与引擎 meta.parallel_phase / timeline 条目 phase 键同词表，
    渲染轮次带时按相位归组（数据面=t260915-01）。

真源与漂移防线（诚实声明）：本模块的节点声明是**导出面数据**，与 dev_lane.py
STAGES（编码真源）物理分离——原因是 tools 侧（workflow.py）的运行环境不保证
temporalio 在场，不能 import dev_lane。分离的漂移风险由一致性锁 UT 承接：
test_template_topology.py 逐字段比对导出面 ↔ DevLaneWorkflow.STAGES（id/label/
role/kind/parts），并源码锁 run() 两个真分叉的成员集合——STAGES 改了不导出面，
UT 必红。fixture-two-step 同款锁。t260916-05：inspection-lite 同范式——编码真源=
inspection_flow.InspectionPeriodicWorkflow.STAGES（含 suite_only 套件档开关），
一致性锁=tests/test_t260916_05_inspection_topology.py（逐字段+源码锁+变异自证）。

本模块零 IO、零 temporalio 依赖：workflow.py / 测试 / 渲染器 UT 都可直接 import。
不登记进 workflows 注册表、不受 SANDBAR_FIXTURE_TEMPLATES 门约束（本表只是
导出数据，不是模板注册；sc_template_face_narrowing 的默认面断言不受扰动）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

CONTRACT_VERSION = "topology-v1"

KIND_AGENT = "agent"
KIND_GATE = "gate"
KIND_HUMAN = "human"
_KINDS: Tuple[str, ...] = (KIND_AGENT, KIND_GATE, KIND_HUMAN)

# 条件段注记值：现仅 ui_evidence（dev_lane.py:456 注释自认「UI 票只跑」）。
OPT_UI_TICKETS = "仅 UI 票"
# t260916-05：巡检套件档条件段注记——setup/suite 只在声明 run_suite=full 的期出现
# （inspection_flow.py run() 两处 `if run_suite:` 守卫；阶段声明 suite_only=True）。
OPT_SUITE_TIER = "仅套件档"


def _node(node_id: str, label: str, role: str, kind: str,
          parts: Sequence[str] = (), optional: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": node_id, "label": label, "role": role,
                           "kind": kind, "parts": [str(p) for p in parts]}
    if optional:
        out["optional"] = optional
    return out


def _group(group_id: str, members: Sequence[str], phase: str) -> Dict[str, Any]:
    return {"id": group_id, "members": [str(m) for m in members], "phase": phase}


# ---------------------------------------------------------------------------
# 模板拓扑声明（导出面数据；一致性锁见 tests/test_template_topology.py）
# ---------------------------------------------------------------------------

_DEV_LANE_NODES: Tuple[Dict[str, Any], ...] = (
    _node("create_plan", "做方案", "developer", KIND_AGENT, ("agent",)),
    _node("review_plan", "审方案", "integration", KIND_AGENT, ("agent",)),
    _node("implement", "实现", "developer", KIND_AGENT, ("agent", "script")),
    _node("design_integration_tests", "设计集成测试", "integration", KIND_AGENT, ("agent",)),
    # 条件段（t260828-09）：仅 UI 票跑，非 UI 票跳过——渲染器画虚节点+注记。
    _node("ui_evidence", "UI截图证据", "developer", KIND_AGENT, ("script",), optional=OPT_UI_TICKETS),
    _node("run_integration_tests", "跑集成测试", "integration", KIND_GATE, ("script",)),
    _node("arbitrate", "仲裁", "integration", KIND_AGENT, ("agent", "script")),
    _node("acceptance_walkthrough", "验收走查", "integration", KIND_AGENT, ("agent", "script")),
    _node("merge_check", "合并检查", "integration", KIND_GATE, ("script",)),
    # 人门：exit=human（sign 信号面），渲染器画虚线圈。
    _node("merge", "合并（人审）", "integration", KIND_HUMAN, ("human", "script")),
)

# 两个真分叉（run() 内 asyncio.gather 调用点；源码锁锚 pend.append 字面量）：
# 相位名与 dev_lane 主循环 phase 分派值/ meta.parallel_phase 同词表。
_DEV_LANE_GROUPS: Tuple[Dict[str, Any], ...] = (
    _group("parallel_impl_design", ("implement", "design_integration_tests"),
           "parallel_impl_design"),
    _group("arb_acc_parallel", ("arbitrate", "acceptance_walkthrough"), "arb_acc_parallel"),
)

_FIXTURE_TWO_STEP_NODES: Tuple[Dict[str, Any], ...] = (
    _node("fx_step_one", "夹具段一", "developer", KIND_AGENT),
    _node("fx_step_two", "夹具段二", "integration", KIND_AGENT),
)

# t260916-05：巡检模板（inspection-lite）——编码真源=inspection_flow.py
# InspectionPeriodicWorkflow.STAGES（机器可读阶段声明），本表是展示面导出数据；
# 逐字段一致性锁=tests/test_t260916_05_inspection_topology.py B 段（「STAGES 改了
# 不改本表，此处必红」，dev-lane 同款范式）。线性五段、无并行组；setup/suite 为
# 套件档条件段（optional 虚节点注记，同 ui_evidence 形）；close=人门（虚线圈，
# 巡检票唯一汇）。
_INSPECTION_NODES: Tuple[Dict[str, Any], ...] = (
    _node("setup", "泳道准备", "", KIND_GATE, ("script",), optional=OPT_SUITE_TIER),
    _node("scan", "扫描", "", KIND_GATE, ("script",)),
    _node("suite", "巡检泳道套件", "", KIND_GATE, ("script",), optional=OPT_SUITE_TIER),
    _node("report", "落账", "", KIND_GATE, ("script",)),
    _node("close", "人审收口", "", KIND_HUMAN, ("human", "script")),
)

_TOPOLOGIES: Dict[str, Dict[str, Any]] = {
    "dev-lane": {"name": "开发泳道", "nodes": _DEV_LANE_NODES, "groups": _DEV_LANE_GROUPS},
    # 巡检期票模板（inspection_flow.InspectionPeriodicWorkflow；非 dev-lane 票面，
    # 工作台详情经快照 topology 键消费本导出）。
    "inspection-lite": {"name": "巡检", "nodes": _INSPECTION_NODES, "groups": ()},
    # 测试夹具模板（SANDBAR_FIXTURE_TEMPLATES=1 才注册为 workflow；这里是它的
    # 拓扑导出数据，渲染器通用性对拍=「另一 workflow 类拓扑同组件」的载体）。
    "fixture-two-step": {"name": "夹具两段", "nodes": _FIXTURE_TWO_STEP_NODES, "groups": ()},
}


# ---------------------------------------------------------------------------
# 校验与导出（纯函数）
# ---------------------------------------------------------------------------

def validate_topology(nodes: Sequence[Dict[str, Any]],
                      groups: Sequence[Dict[str, Any]]) -> List[str]:
    """结构校验，返回问题清单（空=合法）。不抛——调用方决定 fail-closed 方式。"""
    problems: List[str] = []
    seen: set = set()
    order: List[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            problems.append("节点不是对象: %r" % (n,))
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            problems.append("节点 id 缺失或非串: %r" % (nid,))
            continue
        if nid in seen:
            problems.append("节点 id 重复: %s" % nid)
            continue
        seen.add(nid)
        order.append(nid)
        if n.get("kind") not in _KINDS:
            problems.append("节点 %s kind 越词表: %r" % (nid, n.get("kind")))
        if not isinstance(n.get("label"), str) or not n.get("label"):
            problems.append("节点 %s label 缺失" % nid)
    g_of: Dict[str, str] = {}
    for g in groups:
        if not isinstance(g, dict):
            problems.append("组不是对象: %r" % (g,))
            continue
        members = g.get("members")
        if not isinstance(members, list) or len(members) < 2:
            problems.append("组 %r members 非二元以上列表" % (g.get("id"),))
            continue
        for m in members:
            if m not in seen:
                problems.append("组 %s 成员越表: %r" % (g.get("id"), m))
            elif m in g_of:
                problems.append("节点 %s 属于多个组（%s/%s）" % (m, g_of[m], g.get("id")))
            else:
                g_of[m] = str(g.get("id"))
        # 连续性：成员在节点声明顺序里必须连续
        idx = [order.index(m) for m in members if m in order]
        if len(idx) == len(members) and idx != list(range(min(idx), min(idx) + len(idx))):
            problems.append("组 %s 成员在节点顺序中不连续: %r" % (g.get("id"), members))
    return problems


def derive_edges(nodes: Sequence[Dict[str, Any]],
                 groups: Sequence[Dict[str, Any]]) -> List[List[str]]:
    """由节点声明顺序 + 组推导边：组内相邻边折叠为 fork-in→组员、组员→join-out。
    链邻接边与 fork/join 边重合时去重（保序）——边集=语义边集，无重复。"""
    order = [n["id"] for n in nodes if isinstance(n, dict) and isinstance(n.get("id"), str)]
    pos = {nid: i for i, nid in enumerate(order)}
    member_of: Dict[str, str] = {}
    for g in groups:
        for m in g.get("members", []):
            member_of[m] = g["id"]
    edges: List[List[str]] = []
    seen: set = set()

    def _add(a: str, b: str) -> None:
        key = (a, b)
        if key not in seen:
            seen.add(key)
            edges.append([a, b])

    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]
        if member_of.get(a) is not None and member_of.get(a) == member_of.get(b):
            continue  # 组内相邻边折叠（fork-join 语义）
        _add(a, b)
    for g in groups:
        members = [m for m in g.get("members", []) if m in pos]
        if not members:
            continue
        first, last = min(pos[m] for m in members), max(pos[m] for m in members)
        if first - 1 >= 0:
            fork_in = order[first - 1]
            for m in members:
                _add(fork_in, m)
        if last + 1 < len(order):
            join_out = order[last + 1]
            for m in members:
                _add(m, join_out)
    return edges


def build_topology(template_id: str, name: str,
                   nodes: Sequence[Dict[str, Any]],
                   groups: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """导出一个模板的拓扑契约。声明非法 → ValueError（fail-closed，不静默出图）。"""
    problems = validate_topology(nodes, groups)
    if problems:
        raise ValueError("拓扑声明非法（%s）：%s" % (template_id, "；".join(problems)))
    return {
        "version": CONTRACT_VERSION,
        "template": template_id,
        "name": name,
        "nodes": [dict(n) for n in nodes],
        "edges": derive_edges(nodes, groups),
        "groups": [dict(g) for g in groups],
    }


def export_template_topology(template_id: str) -> Optional[Dict[str, Any]]:
    """按模板 id 导出拓扑契约；未声明的模板返回 None（消费方回落线性呈现，
    绝不猜测拓扑）。纯函数零 IO，workflow.py / UT / snapshot 均可安全调用。"""
    decl = _TOPOLOGIES.get(str(template_id or ""))
    if decl is None:
        return None
    return build_topology(str(template_id), decl["name"], decl["nodes"], decl["groups"])


def declared_templates() -> List[str]:
    """已声明拓扑的模板 id 清单（诊断/测试用）。"""
    return sorted(_TOPOLOGIES)
