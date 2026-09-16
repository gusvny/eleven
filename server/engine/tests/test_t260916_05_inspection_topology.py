"""t260916-05 巡检模板拓扑：导出契约 + 一致性锁 + 源码锁 + 变异自证 + snapshot 门。

覆盖口径（=create_plan 方案步骤 1 验证面 + review gen1 意见 1/4）：
  A. 导出契约形状：inspection-lite 五节点线性、无组、close=唯一汇（人门）、
     optional 恰为 setup+suite（套件档条件段，值=OPT_SUITE_TIER）。
  B. 一致性锁（编码真源 STAGES）：导出面与 InspectionPeriodicWorkflow.STAGES 逐字段
     比对（id 序/label==name/kind 投影/parts/optional↔suite_only/next==声明序邻接）
     ——STAGES 改了不改导出面，此处必红（test_template_topology.py B 段同款）。
  C. 源码锁（review 意见 1 收窄作用域）：段位标签字面量全集只在
     **InspectionPeriodicWorkflow 类块内**收集（同文件 InspectionTicketCountWatcher
     Workflow 另有 _enter("poll"/"trigger")，不限类=锁恒红或诱把 watcher 段塞进声明）；
     收集面含 `_enter("<id>"` 与 `_blocked(...)` 第 4 参段位标签（guard 只经 _blocked
     出现——只锁 _enter 则 PRE_FLOW_STAGES 防漏声明落空）。全集==STAGES∪PRE_FLOW_
     STAGES（双向：声明必被 flow 使用、flow 标签必已声明）。另锁套件档短路形态：
     `_enter("suite"` 与 `_setup_lane(` 调用都在 `if run_suite:` 块内。
  D. 变异自证腿：B/C 锁体因子成纯函数——真实对→[]；改 name/加段/翻转 suite_only/
     变 kind/断 next 链/混入未声明标签 → 问题清单非空（锁有牙齿，不改文件）。
  E. 边界：未知模板 None 不回归；dev-lane/fixture-two-step 声明零扰动；
     declared_templates 含 inspection-lite。
  F. snapshot 门两态：_patched=True→topology 键在且 template=inspection-lite；
     False→无键（旧实例重放零新键）；UT 壳缺 _patched 位→getattr 防御不炸零键。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：engine venv `python -m pytest server/engine/tests/test_t260916_05_inspection_topology.py -q`。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_flow as inf  # noqa: E402
import template_topology as tt  # noqa: E402

FLOW_SRC = (POC / "inspection_flow.py").read_text(encoding="utf-8")

STAGES = inf.InspectionPeriodicWorkflow.STAGES
DECL_IDS = [s.id for s in STAGES]


# ---------------------------------------------------------------------------
# 锁体（纯函数）：真实对返回 []；任何漂移返回人读问题清单。D 腿直接喂变异对。
# ---------------------------------------------------------------------------

def lock_problems(stages, topo) -> list:
    """B 段逐字段锁的纯函数体（t260916-05 D 腿变异自证的载体）。"""
    problems: list = []
    ids = [s.id for s in stages]
    if len(ids) != len(set(ids)):
        problems.append("声明 id 重复: %r" % ids)
    by_id = {n["id"]: n for n in topo["nodes"]}
    for i, st in enumerate(stages):
        n = by_id.get(st.id)
        if n is None:
            problems.append("导出面缺声明段节点: %s" % st.id)
            continue
        if n["label"] != st.name:
            problems.append("%s label 漂移: %r != %r" % (st.id, n["label"], st.name))
        if n["kind"] != st.kind:
            problems.append("%s kind 与声明投影漂移: %r != %r" % (st.id, n["kind"], st.kind))
        if n["parts"] != list(st.parts):
            problems.append("%s parts 漂移: %r != %r" % (st.id, n["parts"], list(st.parts)))
        want_opt = tt.OPT_SUITE_TIER if st.suite_only else None
        if n.get("optional") != want_opt:
            problems.append("%s optional↔suite_only 漂移: %r != %r"
                            % (st.id, n.get("optional"), want_opt))
        # next==声明序邻接（末段空=收口）
        want_next = ids[i + 1] if i + 1 < len(ids) else ""
        if st.next != want_next:
            problems.append("%s next 漂移: %r != %r（声明序邻接）" % (st.id, st.next, want_next))
    # 导出面不得有声明外节点
    for n in topo["nodes"]:
        if n["id"] not in ids:
            problems.append("导出面多出声明外节点: %s" % n["id"])
    # 边=声明序邻接链（巡检线性、无组）
    want_edges = [[ids[i], ids[i + 1]] for i in range(len(ids) - 1)]
    if topo["edges"] != want_edges:
        problems.append("边集漂移: %r != %r（声明序邻接链）" % (topo["edges"], want_edges))
    if topo["groups"]:
        problems.append("巡检无并行组，groups 必空: %r" % (topo["groups"],))
    return problems


def source_label_problems(src_block: str, declared: set) -> list:
    """C 段源码锁的纯函数体：段位标签字面量全集 vs 声明词表。"""
    problems: list = []
    labels: set = set()
    for m in re.finditer(r'_enter\(\s*"([a-z_]+)"', src_block):
        labels.add(m.group(1))
    # `_blocked(...)` 第 4 参段位标签（调用实参跨行：先折叠空白再取前 4 个逗参）
    for m in re.finditer(r"\._blocked\(", src_block):
        tail = re.sub(r"\s+", " ", src_block[m.end():m.end() + 300])
        bm = re.match(r'([^,]+),([^,]+),([^,]+),\s*"([a-z_]+)"', tail)
        if bm:
            labels.add(bm.group(4))
        else:
            problems.append("_blocked 调用第 4 参未解析出段位字面量: %s…" % tail[:80])
    for extra in sorted(labels - declared):
        problems.append("flow 段位标签未声明: %r（须入 STAGES 或 PRE_FLOW_STAGES）" % extra)
    for missing in sorted(declared - labels):
        problems.append("声明段在 flow 调用点缺席: %r（声明与实现脱钩）" % missing)
    return problems


# ---------------------------------------------------------------------------
# 源码块提取
# ---------------------------------------------------------------------------

def _workflow_class_block() -> str:
    """InspectionPeriodicWorkflow 类块源码（review 意见 1：锁的作用域）——
    从 `class InspectionPeriodicWorkflow` 起到下一个顶层类/decorator 止。"""
    starts = [m.start() for m in re.finditer(r"^class \w+", FLOW_SRC, re.M)]
    m = re.search(r"^class InspectionPeriodicWorkflow\b", FLOW_SRC, re.M)
    assert m, "找不到 InspectionPeriodicWorkflow 类定义"
    later = [p for p in starts if p > m.start()]
    end = min(later) if later else len(FLOW_SRC)
    return FLOW_SRC[m.start():end]


def _run_suite_blocks(block: str) -> list:
    """类块内全部 `if run_suite:` 守卫块的 (start, end) 字符跨度（缩进回退即块终）。"""
    spans = []
    for m in re.finditer(r"^([ ]*)if run_suite:\s*$", block, re.M):
        indent = len(m.group(1))
        rest = block[m.end():]
        stop = re.search(r"^[ ]{0,%d}\S" % indent, rest, re.M)
        end = m.end() + (stop.start() if stop else len(rest))
        spans.append((m.end(), end))
    return spans


def _occurrence_in_any(block: str, needle: str, spans: list) -> bool:
    """block 内 needle 的每次出现是否都落在某跨度内（按字符偏移判定）。"""
    for m in re.finditer(re.escape(needle), block):
        if not any(s <= m.start() < e for s, e in spans):
            return False
    return True


# ---------------------------------------------------------------------------
# A. 导出契约形状
# ---------------------------------------------------------------------------

def test_export_inspection_contract_shape():
    topo = tt.export_template_topology("inspection-lite")
    assert topo is not None
    assert topo["version"] == tt.CONTRACT_VERSION
    assert topo["template"] == "inspection-lite"
    assert topo["name"] == "巡检"
    ids = [n["id"] for n in topo["nodes"]]
    assert ids == DECL_IDS, "节点序=声明序"
    assert topo["groups"] == [], "巡检线性链，无并行组"
    # 边=声明序线性链
    assert topo["edges"] == [[DECL_IDS[i], DECL_IDS[i + 1]] for i in range(len(DECL_IDS) - 1)]
    # 人门=唯一汇
    outgoing = {a for a, _ in topo["edges"]}
    sinks = set(ids) - outgoing
    assert sinks == {"close"}, "close（人审收口）必须是唯一汇（单向流）"
    # 套件档条件段：恰 setup+suite 挂注记，值单点
    optional = {n["id"]: n.get("optional") for n in topo["nodes"] if n.get("optional")}
    assert optional == {"setup": tt.OPT_SUITE_TIER, "suite": tt.OPT_SUITE_TIER}
    # kind 投影：close=human，其余 gate（巡检无 agent 段）
    kinds = {n["id"]: n["kind"] for n in topo["nodes"]}
    assert kinds == {"setup": "gate", "scan": "gate", "suite": "gate",
                     "report": "gate", "close": "human"}


# ---------------------------------------------------------------------------
# B. 一致性锁：STAGES 编码真源 ↔ 导出面
# ---------------------------------------------------------------------------

def test_consistency_lock_against_stages():
    topo = tt.export_template_topology("inspection-lite")
    assert lock_problems(STAGES, topo) == [], "真实对必须零问题（锁误报即锁坏）"
    # 独立锚：suite_only 声明与 optional 注记逐段对齐（不复用锁体，双写互核）
    by_id = {n["id"]: n for n in topo["nodes"]}
    for st in STAGES:
        assert (by_id[st.id].get("optional") == tt.OPT_SUITE_TIER) == st.suite_only


# ---------------------------------------------------------------------------
# C. 源码锁：类块作用域 + _enter/_blocked 标签全集 + 套件档短路形态
# ---------------------------------------------------------------------------

def test_source_lock_labels_scoped_to_workflow_class():
    """review 意见 1：字面量只在 InspectionPeriodicWorkflow 类块内收集——watcher 类的
    poll/trigger 不得混入；全集双向==STAGES∪PRE_FLOW_STAGES。"""
    block = _workflow_class_block()
    assert '_enter("poll"' not in block and '_enter("trigger"' not in block, \
        "watcher 的 _enter 字面量不得出现在本类块（作用域收窄失效）"
    watcher_block = FLOW_SRC[FLOW_SRC.index("class InspectionTicketCountWatcherWorkflow"):]
    assert '_enter("poll"' in watcher_block, "锚点自检：watcher 类确实带 poll 字面量"
    declared = set(DECL_IDS) | set(inf.PRE_FLOW_STAGES)
    assert source_label_problems(block, declared) == []


def test_source_lock_collects_blocked_labels_too():
    """_blocked 第 4 参段位标签必须被收集（guard 只经 _blocked 出现；只锁 _enter 则
    PRE_FLOW_STAGES 的防漏声明落空——review 意见 1 后半）。"""
    block = _workflow_class_block()
    collected = set(re.findall(r'_enter\(\s*"([a-z_]+)"', block))
    for m in re.finditer(r"\._blocked\(", block):
        tail = re.sub(r"\s+", " ", block[m.end():m.end() + 300])
        bm = re.match(r'([^,]+),([^,]+),([^,]+),\s*"([a-z_]+)"', tail)
        assert bm, "_blocked 调用解析失败: %s…" % tail[:80]
        collected.add(bm.group(4))
    assert "guard" in collected, "guard 必须经由 _blocked 调用被收集进全集"
    assert collected == set(DECL_IDS) | set(inf.PRE_FLOW_STAGES)


def test_source_lock_suite_tier_short_circuit():
    """套件档短路形态（suite_only=True 的源码实证）：`_enter("suite"` 与
    `_setup_lane(` 调用每次出现都在 `if run_suite:` 块内——档位关=段不存在。"""
    block = _workflow_class_block()
    blocks = _run_suite_blocks(block)
    assert len(blocks) >= 2, "run() 至少两处 if run_suite: 守卫（搭道/跑套件）"
    for needle in ('_enter("suite"', "._setup_lane("):
        assert _occurrence_in_any(block, needle, blocks), \
            "%s 出现在 if run_suite: 守卫之外（套件档短路形态被破坏）" % needle
    # 反向自证：必经段 scan 不得被锁进守卫块（守卫块提取没有吞掉整段 run()）
    assert not _occurrence_in_any(block, '_enter("scan"', blocks), \
        "scan 是必经段，不得位于 if run_suite: 块内（块提取口径自检）"


# ---------------------------------------------------------------------------
# D. 变异自证腿（锁有牙齿：改声明不改展示面 → 红）
# ---------------------------------------------------------------------------

def _mutated_stages(**changes):
    """按字段变异声明副本（frozen dataclass → dataclasses.replace 语义）。"""
    import dataclasses
    stages = list(STAGES)
    idx, field = changes.pop("idx"), changes.pop("field")
    stages[idx] = dataclasses.replace(stages[idx], **{field: changes["value"]})
    return stages


def _dropped_stage():
    """变异：声明多一段（展示面未登记）。"""
    return list(STAGES) + [inf.InspectionStage(id="ghost", name="幽灵段", next="",
                                               parts=("script",))]


def test_mutation_legs_lock_turns_red():
    topo = tt.export_template_topology("inspection-lite")
    cases = [
        ("改 name", _mutated_stages(idx=1, field="name", value="改过的扫描")),
        ("变 kind（close 降为程序段）", _mutated_stages(idx=4, field="exit", value="")),
        ("翻 suite_only（setup 变必经）", _mutated_stages(idx=0, field="suite_only", value=False)),
        ("断 next 链", _mutated_stages(idx=2, field="next", value="close")),
        ("改 parts", _mutated_stages(idx=3, field="parts", value=("agent",))),
        ("声明多段", _dropped_stage()),
    ]
    for label, stages in cases:
        problems = lock_problems(stages, topo)
        assert problems, "变异腿未红（锁无牙）：%s" % label
    # C 锁变异：混入未声明标签（如 watcher 的 poll）→ 红
    block = _workflow_class_block()
    assert source_label_problems(block + '\n        self._enter("poll", "running", "x")\n',
                                 set(DECL_IDS) | set(inf.PRE_FLOW_STAGES)), \
        "源码锁变异腿未红（混入未声明标签必须被点名）"


# ---------------------------------------------------------------------------
# E. 边界与既有模板零扰动
# ---------------------------------------------------------------------------

def test_registry_boundaries():
    assert "inspection-lite" in tt.declared_templates()
    # 未知模板 None（既有契约不回归）
    assert tt.export_template_topology("no-such-template") is None
    assert tt.export_template_topology("") is None
    assert tt.export_template_topology(None) is None  # type: ignore[arg-type]
    # dev-lane / fixture-two-step 声明零扰动（各自锁在 test_template_topology.py）
    dev = tt.export_template_topology("dev-lane")
    assert dev is not None and [n["id"] for n in dev["nodes"]][0] == "create_plan"
    fx = tt.export_template_topology("fixture-two-step")
    assert fx is not None and [n["id"] for n in fx["nodes"]] == ["fx_step_one", "fx_step_two"]


# ---------------------------------------------------------------------------
# F. snapshot 门两态（additive 键纪律）
# ---------------------------------------------------------------------------

def _mk_wf(patched: bool):
    """免 Temporal 运行时的 InspectionPeriodicWorkflow 壳（t260915-01/_mk_wf 同款）。"""
    inf.workflow = SimpleNamespace(  # type: ignore[attr-defined]
        info=lambda: SimpleNamespace(workflow_id="inspection-ut-20260916"))
    wf = object.__new__(inf.InspectionPeriodicWorkflow)
    wf.stage = "scan"
    wf.stage_state = "running"
    wf.status = "running"
    wf.decision = ""
    wf.face = {"ticket_id": "inspection-ut-20260916"}
    wf.timeline = []
    wf._gate_err = ""
    wf._patched = patched
    wf._input = None
    return wf


def test_snapshot_gate_topology_key():
    snap = _mk_wf(True).snapshot()
    assert isinstance(snap.get("topology"), dict), "门开=快照带 topology 键"
    assert snap["topology"]["template"] == "inspection-lite"
    assert [n["id"] for n in snap["topology"]["nodes"]] == DECL_IDS
    snap2 = _mk_wf(False).snapshot()
    assert "topology" not in snap2, "门关=旧实例重放零新键（additive 纪律）"


def test_snapshot_shell_without_patched_attr_does_not_explode():
    """UT 壳/异常形态缺 _patched 位：getattr 防御取 False → 零键不炸（R1 同纪律）。"""
    inf.workflow = SimpleNamespace(  # type: ignore[attr-defined]
        info=lambda: SimpleNamespace(workflow_id="inspection-ut-20260916"))
    wf = object.__new__(inf.InspectionPeriodicWorkflow)
    wf.stage = ""
    wf.stage_state = "running"
    wf.status = "running"
    wf.decision = ""
    wf.face = {}
    wf.timeline = []
    wf._gate_err = ""
    wf._input = None
    snap = wf.snapshot()
    assert "topology" not in snap
