"""light-lane 单测（宿主令 260930 直修，无票）：段/门声明、拓扑导出面、闸判词与 blocked 契约、注册面。

覆盖口径（=宿主定案 devlane-lite §4.1 的可机械判面）：
  A. 段声明与「不含被排除段」：LIGHT STAGES 恰为四段（implement/run_integration_tests/
     merge_check/merge）——**首段=implement**。审方案 / 集测设计 / 仲裁 / 验收走查四段
     **不在表内**，**create_plan 与 ui_evidence 也不在表内**（宿主 260930 两道裁定：
     轻道不写方案、不产 UI 证据——段声明/派单面/时间线三处都不许出现这两段），且
     create_plan 同时**不在可返工目标**里；段级 kind 投影与人门标记正确；
     **无条件段**（拓扑 optional 注记必须为空）。
  B. 拓扑导出面一致性锁：template_topology light-lane 节点逐字段（label/role/kind/
     parts/optional）等于 STAGES 投影，边=纯线性链，无并行组——「STAGES 改了不改导出面，
     此处必红」；并带变异自证（锁有牙）。
  C. 复用面源码锁（本票的要点）：轻道**不重抄**既有泳道的段体——工作空间准备 / UI 证据
     走 dev_lane 的共用 helper，机器闸入参走 _integ_run_args 单写者、收口跑走
     _closing_full_run；轻道自己的段链只调这些入口。
  D. 闸判词（纯函数）：green/red 三态边界——error 非空=红、产品红=红、env_fail>0 而
     具名通道缺席=红（无具名即无豁免）、具名环境红全覆盖=绿；畸形计数保守判红。
  E. blocked 契约：blocked 文案与结构化明细带**完整**违规集（三个红名全在，绝不样本）、
     计数、闸回执指针、具名出路清单；跑面（定点/跳过池/复用/在册红）如实带出；
     老回执缺复用块=如实记 absent。
  F. rework 词表：轻道没有的段（arbitrate/review_plan/…）→ 显式拒收 + refused 记录；
     合法目标 → 落点相位与 meta 记账。
  G. 出路改写（宿主 260930）：`write_set_missing` 的共享出路提示指向 create_plan，轻道
     在**自己的阻断面收敛点**改写它（不碰 path_gates 共享串）——轻道票面不含 create_plan
     （正向），dev-lane 的提示**逐字等于改前**（负向锁，字面量断言）。
  H. 注册面与 SDK 定义：workflows_v2 两表各含轻道；shared 两表/段门表按 (模板, 段) 键
     含轻道机器闸；`@workflow.defn` 门（本类显式重新装饰）后类型名=类名、run=自己那份、
     信号/查询/更新继承自 dev-lane；**父类定义一字不动**；yaml 快照在册且过子集解析。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：仓库根 `server/engine/.venv/bin/python -m pytest server/engine/tests/test_light_lane_lane.py -q`。
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import light_lane  # noqa: E402
import path_gates  # noqa: E402
import shared  # noqa: E402
import template_topology as tt  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

#: CJK 统一表意文字（票面英文纪律的机械判据；标点/破折号不算）
_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _has_cjk(s: str) -> bool:
    return bool(_CJK.search(str(s or "")))

#: 被排除的段（轻道**定义**上不存在；出现即本票失效）
EXCLUDED_STAGES = ("review_plan", "design_integration_tests", "arbitrate",
                   "acceptance_walkthrough")


async def _wake_immediately(cond) -> None:
    return None


@pytest.fixture(autouse=True)
def _workflow_shells():
    """两个模块的 workflow 名面同钉（dev_lane._log/_now_epoch 解析的是 dev_lane
    命名空间里的 workflow；test_event_ledger.py:379-388 同款纪律），用例后还原。"""
    saved = (dev_lane.workflow, light_lane.workflow)
    shell = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    dev_lane.workflow = shell
    light_lane.workflow = shell
    yield
    dev_lane.workflow, light_lane.workflow = saved


def _mk_wf(detail_face: bool = True, meta=None, gens=None):
    """免 Temporal 运行时的 LightLaneWorkflow 壳（test_t260915_01 / _t260916_05 同款）。"""
    wf = object.__new__(light_lane.LightLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = dict(gens or {})
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut-light"
    wf._detail_face_on = detail_face
    wf.refused = []
    wf.engine_version = 2
    return wf


def _ir(**kw):
    """IntegrationRunResult 壳：默认全绿，按需覆盖。"""
    base = dict(ran=3, passed=3, failed=0, env_fail=0, details=[], error="")
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _ir_red(names, **kw):
    det = [{"name": n, "cmd": "", "exit": 1, "output_tail": ""} for n in names]
    kw.setdefault("ran", len(names))
    kw.setdefault("passed", 0)
    kw.setdefault("failed", len(names))
    return _ir(details=det, **kw)


# ======================================================================
# A. 段声明 + 被排除段不在表内
# ======================================================================

def test_stage_declaration_is_the_short_walk():
    ids = [s.id for s in light_lane.LightLaneWorkflow.STAGES]
    assert ids == ["implement", "run_integration_tests", "merge_check", "merge"]
    for gone in list(EXCLUDED_STAGES) + ["create_plan", "ui_evidence"]:
        assert gone not in ids, "轻道段链不得含被排除段 %s" % gone
    # 首段=建票推导取 role 的那一段（client.py/ticket.py 的 stage0 消费面）——
    # 宿主 260930 删 create_plan 后首段就是 implement（role 仍是 developer：建票面
    # 的 stage0.role 推导因此不变）
    assert light_lane.LightLaneWorkflow.STAGES[0].id == "implement"
    assert light_lane.LightLaneWorkflow.STAGES[0].role == "developer"


def test_stage_kinds_roles_and_human_marker():
    by_id = {s.id: s for s in light_lane.LightLaneWorkflow.STAGES}
    assert by_id["implement"].kind == "agent" and by_id["implement"].role == "developer"
    assert by_id["run_integration_tests"].kind == "gate"
    assert by_id["merge_check"].kind == "gate"
    assert by_id["merge"].kind == "human"
    assert by_id["merge"].exit == "human"
    assert by_id["merge"].next == ""
    # 链序自洽：每段 next 指向下一段（末段空）
    ids = [s.id for s in light_lane.LightLaneWorkflow.STAGES]
    for i, s in enumerate(light_lane.LightLaneWorkflow.STAGES[:-1]):
        assert s.next == ids[i + 1], "%s.next 与段序漂移" % s.id
    # parts 声明齐全（gen_workflows_doc 的机械门）
    for s in light_lane.LightLaneWorkflow.STAGES:
        assert s.parts, "%s 缺 parts 执行主体声明" % s.id


def test_template_identity_and_english_face():
    assert light_lane.LightLaneWorkflow.TEMPLATE_ID == "light-lane"
    assert light_lane.LightLaneWorkflow.TEMPLATE_NAME == "Light Lane"   # 控制台英文显示名
    assert light_lane.LightLaneWorkflow.TEMPLATE_LANE == "worktree"
    assert light_lane.LightLaneWorkflow.PATH_GATE is True
    # 票面文字（acceptance 进 meta.checks）全英文（CLAUDE.md 规则 6）：判据=零 CJK
    for s in light_lane.LightLaneWorkflow.STAGES:
        for item in s.acceptance:
            assert not _has_cjk(item), \
                "%s 的 acceptance 含中文字符（票面文字须英文）：%r" % (s.id, item)


def test_gate_table_is_keyed_by_template_and_stage():
    gate = light_lane.LIGHT_LANE_GATES[("light-lane", "run_integration_tests")]
    assert gate.tool == "verify_lane" and gate.args == {"lane": "integ"}
    # 同一 (模板, 段) 键在 shared 通用表里也在册（声明面单源）
    assert shared.default_gate_for("light-lane", "run_integration_tests").tool == "verify_lane"
    assert shared.default_gate_for("light-lane", "merge") is None
    # 段声明带的门就是表里那一条
    st = next(s for s in light_lane.LightLaneWorkflow.STAGES
              if s.id == "run_integration_tests")
    assert st.gate is light_lane.LIGHT_LANE_GATES[("light-lane", "run_integration_tests")]


def test_human_gate_is_only_merge():
    humans = [s.id for s in light_lane.LightLaneWorkflow.STAGES if s.exit == "human"]
    assert humans == ["merge"], "轻道唯一人门=merge"


def test_ui_evidence_is_absent_everywhere_in_the_lane():
    """宿主 260930 裁定：**任何轻道票都不跑 ui_evidence**。

    三处负断言（声明面/拓扑面/源码面）+ 段序自洽（implement 的下一段就是机器闸）：
    段链里没有它、拓扑里没有它（连 optional 注记都不许有）、源码里不声明也不接线。"""
    ids = [st.id for st in light_lane.LightLaneWorkflow.STAGES]
    assert "ui_evidence" not in ids
    impl = next(st for st in light_lane.LightLaneWorkflow.STAGES if st.id == "implement")
    assert impl.next == "run_integration_tests", \
        "implement 的下一段必须是机器闸（ui_evidence 段已被裁定删除）"
    topo = tt.export_template_topology("light-lane")
    assert "ui_evidence" not in {n["id"] for n in topo["nodes"]}
    src = _light_src()
    assert 'Stage(id="ui_evidence"' not in src
    assert "_ui_evidence_step()" not in src


def test_ui_surface_change_is_named_and_actionable_at_merge_check():
    """轻道不产 UI 证据的**连带后果**必须具名且可行动：

    merge_check 的 3.6 UI 证据闸（reason_code=ui_evidence_missing）是模板无关的**全车道
    纪律**——改到 UI 路径的轻道票会被它挡住。阻断文案必须：①点名这是全车道纪律；
    ②说明轻道不产截图（结构性不可满足，不许把「补截图」当轻道出路）；③给可行动出路=
    另开全车道票 / 人裁定豁免；④带上命中的 UI 文件清单。"""
    wf = _mk_wf()
    mc = SimpleNamespace(
        green=False, error="",
        checks=[{"item": "泳道分支有 commit", "green": True},
                {"item": "UI 截图证据（.sandbar/screenshots/）", "green": False,
                 "id": "ui_evidence", "reason_code": light_lane.LightLaneWorkflow.UI_EVIDENCE_RED,
                 "detail": "命中 2 个 UI 路径", "files": ["server/plugins/workbench/src/client/a.ts",
                                                          "server/plugins/workbench/src/client/b.ts"],
                 "next_action": "泳道内产出截图证据（server/ui-check/capture.mjs）后发 retry_qc"}],
        conflict=False, conflict_files=[])
    text = wf._light_merge_blocked_text(mc, "UI 截图证据（.sandbar/screenshots/）: 命中 2 个 UI 路径")
    assert light_lane.LightLaneWorkflow.UI_EVIDENCE_RED == "ui_evidence_missing"
    assert "ui_evidence_missing" in text
    assert "full-lane discipline" in text and "template-independent" in text
    assert "The light lane does not produce UI evidence" in text
    assert "open a full-lane ticket (template dev-lane)" in text
    assert "human rule an exemption" in text
    assert "server/plugins/workbench/src/client/a.ts" in text
    assert "do not expect retry_qc to clear this item" in text
    # 英文面判定只落**轻道自产那一段**：回执逐条红里的 item/detail 是 merge_check 的既有
    # 引擎数据（中文，属「数据不译」），原样透传不算票面文案漂移。
    assert not _has_cjk(text.split("UI-surface change detected", 1)[1]), \
        "轻道自产的 UI 闸专段必须英文"
    # 非 UI 红的常规文案不变（专段只在命中该 reason_code 时出现）
    mc2 = SimpleNamespace(green=False, error="",
                          checks=[{"item": "工作区干净（无未提交改动）", "green": False,
                                   "reason_code": "merge_dirty", "files": ["x.py"]}],
                          conflict=False, conflict_files=[])
    text2 = wf._light_merge_blocked_text(mc2, "工作区干净（无未提交改动）: 红")
    assert "UI-surface change detected" not in text2
    assert "Merge check is red" in text2 and "retry_qc" in text2


# ======================================================================
# B. 拓扑导出面一致性锁（+ 变异自证）
# ======================================================================

def _lock_problems(nodes, stages):
    """纯函数锁体：不一致→问题清单（空=绿）。变异自证靠它，锁才「有牙」。"""
    problems = []
    if [n["id"] for n in nodes] != [s.id for s in stages]:
        problems.append("节点集/顺序与 STAGES 漂移")
        return problems
    for n, s in zip(nodes, stages):
        if n["label"] != s.name:
            problems.append("%s label 漂移" % s.id)
        if n["role"] != s.role:
            problems.append("%s role 漂移" % s.id)
        if n["kind"] != s.kind:
            problems.append("%s kind 漂移" % s.id)
        if list(n["parts"]) != list(s.parts):
            problems.append("%s parts 漂移" % s.id)
    return problems


def test_topology_lock_against_stages():
    topo = tt.export_template_topology("light-lane")
    assert topo is not None and topo["template"] == "light-lane"
    assert topo["version"] == tt.CONTRACT_VERSION
    assert _lock_problems(topo["nodes"], light_lane.LightLaneWorkflow.STAGES) == []
    # 宿主 260930：轻道**无条件段**——拓扑里不得有 ui_evidence 幽灵节点，也不得有
    # 任何 optional 注记
    optional = {n["id"]: n["optional"] for n in topo["nodes"] if n.get("optional")}
    assert optional == {}, "轻道拓扑不得带条件段注记（实得 %r）" % optional
    assert "ui_evidence" not in {n["id"] for n in topo["nodes"]}
    # 轻道无并行分叉：组为空、边=纯线性链
    assert topo["groups"] == []
    ids = [s.id for s in light_lane.LightLaneWorkflow.STAGES]
    assert topo["edges"] == [[ids[i], ids[i + 1]] for i in range(len(ids) - 1)]
    # 人门标记：唯一汇
    sinks = [n["id"] for n in topo["nodes"] if n["kind"] == tt.KIND_HUMAN]
    assert sinks == ["merge"]


def test_topology_lock_has_teeth():
    """变异自证：改一处（name/role/exit/parts/顺序/多段）锁必红。"""
    topo = tt.export_template_topology("light-lane")
    stages = light_lane.LightLaneWorkflow.STAGES
    ok = [dict(n) for n in topo["nodes"]]
    assert _lock_problems(ok, stages) == []           # 自证绿

    mut_name = [dict(n) for n in ok]
    mut_name[0]["label"] = "改了名"
    assert _lock_problems(mut_name, stages) != []

    mut_kind = [dict(n) for n in ok]
    mut_kind[3]["kind"] = tt.KIND_AGENT
    assert _lock_problems(mut_kind, stages) != []

    mut_parts = [dict(n) for n in ok]
    mut_parts[1]["parts"] = []
    assert _lock_problems(mut_parts, stages) != []

    swapped = [dict(n) for n in ok]
    swapped[0], swapped[1] = swapped[1], swapped[0]
    assert _lock_problems(swapped, stages) != []

    extra = [dict(n) for n in ok] + [{"id": "ghost", "label": "幽灵",
                                      "role": "developer", "kind": tt.KIND_AGENT,
                                      "parts": []}]
    assert _lock_problems(extra, stages) != []


def test_excluded_stages_absent_from_stage_graph():
    """被排除段（含 ui_evidence——宿主 260930 裁定轻道不产 UI 证据）在**声明面与拓扑面**
    都不存在（控制台泳道图由拓扑推导）。"""
    topo = tt.export_template_topology("light-lane")
    node_ids = {n["id"] for n in topo["nodes"]}
    for gone in list(EXCLUDED_STAGES) + ["create_plan", "ui_evidence"]:
        assert gone not in node_ids
    # dev-lane 那一面不受影响（零行为变化锚）
    dev = tt.export_template_topology("dev-lane")
    assert {n["id"] for n in dev["nodes"]} >= {"review_plan", "arbitrate",
                                              "acceptance_walkthrough"}


# ======================================================================
# C. 复用面源码锁（不重抄既有泳道的段体）
# ======================================================================

def _light_src() -> str:
    return Path(light_lane.__file__).read_text(encoding="utf-8")


def test_reuse_source_locks():
    src = _light_src()
    # 工作空间准备 / UI 证据：走 dev-lane 的共用 helper（不自己再写一遍）
    assert "await self._prepare_workspace_step()" in src
    assert "_ui_evidence_step()" not in src, "轻道不产 UI 证据：不得调截图 helper"
    assert 'Stage(id="ui_evidence"' not in src, "轻道不得声明 ui_evidence 段"
    assert "UiEvidenceArgs(" not in src and "prepare_ui_evidence" not in src, \
        "轻道不得接线截图活动/入参（UI 面改动走全车道）"
    assert "lane_workspace_gate_error(" not in src, "工作空间准备体不得重抄"
    assert "UiChangedPathsArgs(" not in src, "UI 票判定体不得重抄"
    assert "prepare_ui_evidence," not in src, "UI 证据活动不得在轻道里重复接线"
    assert "build_workspace_prep(" not in src, "工作空间构造点不得重抄"
    # agent 段：走父类 _run_agent_step（settle/回执归一/债表全在那边）
    assert "self._run_agent_step(step_id" in src
    # 机器闸：入参单写者 + 收口跑单写者（两处都不自己拼 IntegrationRunArgs）
    assert "self._integ_run_args(run_only)" in src
    assert "IntegrationRunArgs(" not in src, "闸入参必须走 _integ_run_args 单写者"
    assert "await self._closing_full_run()" in src
    # 闸判词的单写者：红名单/具名环境红都读父类纯函数，不另开一份
    assert "self._tests_red_names(" in src
    assert "self._tests_env_red_names(" in src
    assert "self._handover_debt_clear()" in src


def test_reuse_agent_step_template_is_parent_method():
    assert light_lane.LightLaneWorkflow._run_agent_step is dev_lane.DevLaneWorkflow._run_agent_step
    assert light_lane.LightLaneWorkflow._prepare_workspace_step \
        is dev_lane.DevLaneWorkflow._prepare_workspace_step
    # 宿主 260930：轻道不产 UI 证据——UI 证据 helper 仍留给 dev-lane（那里照旧），
    # 但轻道不调；这里是「谁负责产证据」的分工锚
    assert hasattr(dev_lane.DevLaneWorkflow, "_ui_evidence_step")
    assert light_lane.LightLaneWorkflow._blocked is dev_lane.DevLaneWorkflow._blocked
    assert light_lane.LightLaneWorkflow.snapshot is dev_lane.DevLaneWorkflow.snapshot
    # 段补述来源被轻道覆写（自己的补述表），dev-lane 那份不动
    assert light_lane.LightLaneWorkflow.FLOW_BRIEF_SET is light_lane.LIGHT_FLOW_BRIEF
    assert dev_lane.DevLaneWorkflow.FLOW_BRIEF_SET is dev_lane.FLOW_BRIEF


def test_light_flow_brief_reuses_discipline_clauses():
    """段补述=轻道前缀 + dev-lane 同段正文（纪律条文同源，绝不各写一份）。

    轻道唯一 agent 段=implement（宿主 260930 删 create_plan）：补述表里**只能有
    implement**——多出 create_plan 键就等于给一个不存在的段备了文案。"""
    assert set(light_lane.LIGHT_FLOW_BRIEF) == {"implement"}
    sid = "implement"
    assert light_lane.LIGHT_FLOW_BRIEF[sid].startswith(light_lane.LIGHT_LANE_PRELUDE)
    assert dev_lane.FLOW_BRIEF[sid] in light_lane.LIGHT_FLOW_BRIEF[sid]
    # 轻道契约句点名「没有」的那几段（免得 agent 等一个不存在的段）
    for gone in ("方案段", "方案复审", "集测设计", "仲裁", "验收走查", "UI 证据"):
        assert gone in light_lane.LIGHT_LANE_PRELUDE


def test_create_plan_is_gone_and_not_a_rework_target():
    """宿主 260930：轻道删 create_plan 段——段链/补述/可返工目标三处一起摘干净，
    且打回它必须**具名拒收**（不静默、不落到未知相位）。"""
    ids = [st.id for st in light_lane.LightLaneWorkflow.STAGES]
    assert "create_plan" not in ids
    assert "create_plan" not in light_lane.LIGHT_FLOW_BRIEF
    assert "create_plan" not in light_lane.LIGHT_REWORK_TARGETS
    src = _light_src()
    assert 'Stage(id="create_plan"' not in src
    assert '"_light_agent_step("create_plan"' not in src
    assert "_refresh_write_set_after_plan()" not in src, \
        "轻道没有方案回执可读——不得调写集随方案刷新"
    wf = _mk_wf(meta={"stage": "implement"})
    wf._rework = _rework_req("create_plan", note="send it back to planning")
    landing, refusal = wf._consume_light_rework("run_integration_tests")
    assert landing == "" and "not a light-lane stage" in refusal
    assert "implement" in refusal and "create_plan" in refusal
    assert wf.refused[-1]["want"] == "rework(create_plan)"
    # 合法目标照常可打回（回落目标=首段 implement）
    wf2 = _mk_wf(meta={"stage": "merge_check"})
    wf2._rework = _rework_req("implement", note="repair")
    landing2, refusal2 = wf2._consume_light_rework("merge_check")
    assert landing2 == "implement" and refusal2 == ""


# ======================================================================
# D. 闸判词（纯函数边界）
# ======================================================================

def test_gate_verdict_red_on_error():
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir(error="verify_lane integ produced no valid output")) == "red"
    assert wf._light_gate_verdict(None) == "red"


def test_gate_verdict_red_on_product_reds():
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir_red(["sc_a", "sc_b"])) == "red"
    # 闸拦名单（blockers）也要算红——即使 details 里没有失败条目
    assert wf._light_gate_verdict(_ir(failed=1, blockers=["sc_blocked"])) == "red"


def test_gate_verdict_green_when_all_green():
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir()) == "green"
    assert wf._light_gate_verdict(_ir(ran=0, passed=0)) == "green"


def test_gate_verdict_env_red_without_named_channel_is_red():
    """无具名即无豁免：env_fail>0 而具名通道缺席/为空 → 保守判红。"""
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir(env_fail=2)) == "red"
    assert wf._light_gate_verdict(_ir(env_fail=2, env_red=[])) == "red"
    # 具名通道在场且盖住全部环境红 → 不拦（票面点名即可）
    assert wf._light_gate_verdict(_ir(env_fail=2, env_red=["sc_env_a", "sc_env_b"])) == "green"


def test_gate_verdict_product_red_wins_over_named_env():
    wf = _mk_wf()
    ir = _ir_red(["sc_real"], env_fail=1, env_red=["sc_env_a"])
    assert wf._light_gate_verdict(ir) == "red"


def test_gate_verdict_malformed_counts_fail_closed():
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir(failed="not-a-number")) == "red"
    assert wf._light_gate_verdict(_ir(env_fail="??")) == "red"


def test_red_names_are_the_complete_set_and_split():
    wf = _mk_wf()
    ir = _ir(details=[{"name": "sc_a", "exit": 1}, {"name": "sc_b", "exit": 1},
                      {"name": "sc_c", "exit": 1}, {"name": "sc_ok", "exit": 0},
                      {"name": "__pool_exclude__", "exit": 1}],
             ran=4, passed=1, failed=3, env_fail=1, env_red=["sc_env_a"],
             blockers=["sc_block"])
    # 产品红（3 条 reds）∪ 闸拦 ∪ 具名环境红；合成条目与绿条目不入
    assert wf._light_red_names(ir) == ["sc_a", "sc_b", "sc_c", "sc_block", "sc_env_a"]
    assert wf._light_gate_has_product_red(ir) is True
    # 纯环境轮：无产品红
    env_only = _ir(ran=1, passed=0, failed=0, env_fail=1, env_red=["sc_env_a"])
    assert wf._light_gate_has_product_red(env_only) is False


# ======================================================================
# E. blocked 契约：完整违规集 + 跑面 + 出路
# ======================================================================

def test_blocked_text_names_every_violation_never_a_sample():
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta", "sc_gamma"]
    ir = _ir_red(names, excluded_pools=["engine"], excluded_count=7,
                 only_names=["sc_alpha"])
    text = wf._light_gate_blocked_text(ir, ["sc_alpha"], "gate round 2 of this attempt")
    for n in names:
        assert n in text, "blocked 文案漏了违规项 %s（样本化=本票要治的病）" % n
    assert "Complete violation set (3)" in text
    assert "3 ran / 0 passed / 3 failed / 0 env-red" in text
    assert "results.run_integration_tests" in text            # 闸回执指针
    assert "out/integration-report-*.json" in text
    assert "retry_qc" in text and "rework(to_stage=implement)" in text
    assert "dev-lane" in text                                  # 别的道=开全道票
    assert "no arbitration" in text and "no automatic re-run" in text
    assert "narrowed to sc_alpha" in text                       # 跑面如实（本轮收窄）
    assert "engine" in text and "7 entries" in text             # 跳过池如实


def test_blocked_text_reports_full_round_and_absent_reuse_face():
    wf = _mk_wf()
    text = wf._light_gate_blocked_text(_ir_red(["sc_x"]), [], "gate round 1")
    assert "full registry (not narrowed)" in text
    # 老回执无复用块：如实记 absent，不冒充「零复用」（保守方向）
    assert "reuse" not in text.lower() or "expected" not in text


def test_blocked_detail_carries_complete_violation_set():
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta", "sc_gamma"]
    ir = _ir_red(names, blockers=[], env_red=["sc_env_a"], env_fail=1,
                 only_names=["sc_alpha", "sc_beta"])
    d = wf._light_gate_blocked_detail(ir, ["sc_alpha", "sc_beta"],
                                      "light_gate_red", "gate round 2")
    assert d["violations"] == names + ["sc_env_a"]
    assert d["violations_complete"] is True
    assert d["counts"] == {"ran": 3, "passed": 0, "failed": 3, "env_fail": 1}
    assert d["env_red"] == ["sc_env_a"] and d["env_red_channel_ok"] is True
    assert d["round"]["narrowed"] == ["sc_alpha", "sc_beta"]
    assert d["round"]["requested_only_names"] == ["sc_alpha", "sc_beta"]
    assert d["receipt"] == "results.run_integration_tests"
    assert len(d["remedies"]) == 3
    assert d["check_id"] == "run_integration_tests" and d["red"] is True
    # 可 JSON 序列化（票面/控制台机读契约）
    json.dumps(d, ensure_ascii=False)


def test_blocked_detail_reuse_face_carried_when_present():
    wf = _mk_wf()
    ir = _ir_red(["sc_x"])
    ir.reuse = {"reused": 5, "expected": 8, "names": ["sc_r1"], "accounted": True}
    ir.known_red = {"skipped": 2, "names": ["sc_k1", "sc_k2"]}
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "round 1")
    assert d["round"]["reuse"]["reused"] == 5
    assert d["round"]["reuse"]["expected"] == 8
    assert d["round"]["known_red"]["names"] == ["sc_k1", "sc_k2"]
    text = wf._light_gate_blocked_text(ir, [], "round 1")
    assert "reused=5 of expected=8" in text and "sc_r1" in text
    assert "sc_k1" in text


def test_run_face_absent_marks_are_honest():
    wf = _mk_wf()
    face = wf._light_run_face(_ir(), [])
    assert isinstance(face["reuse"], str) and "absent" in face["reuse"]
    assert isinstance(face["known_red"], str) and "absent" in face["known_red"]


def test_face_note_names_what_was_not_run():
    """票面注记（轻道自产那半）：少跑面必须可见——定点面/跳过池/台账复用三块。"""
    wf = _mk_wf()
    assert wf._light_face_note(_ir(), []) == "", "全量且无少跑面=不加注记"
    ir = _ir_red(["sc_a"], only_names=["sc_a", "sc_b"], excluded_pools=["engine"],
                 excluded_count=4)
    ir.reuse = {"reused": 2, "expected": 5}
    ir.known_red = {"skipped": 1, "names": ["sc_k"]}
    note = wf._light_face_note(ir, ["sc_a", "sc_b"])
    assert "narrowed to 2 entries (sc_a, sc_b)" in note
    assert "declared pools skipped: engine (4 entries)" in note
    assert "ledger reuse: reused=2 of expected=5 (not executed)" in note
    assert "known-red entries excluded: 1" in note
    assert not _has_cjk(note)


def test_gate_receipt_shape_is_the_console_face():
    """rec回执上台面（console/results 消费）：summary/evidence/gen 三键形状稳定。"""
    wf = _mk_wf()
    ir = _ir(details=[{"name": "sc_a", "exit": 1, "output_tail": "boom"}],
             ran=1, passed=0, failed=1)
    rec = wf._light_gate_receipt(ir, gen=2)
    assert rec["status"] == "failed" and rec["gen"] == 2
    assert rec["summary"].startswith("integration gate:")
    assert "sc_a" in rec["evidence"]
    rec2 = wf._light_gate_receipt(_ir(), gen=3, closing=True)
    assert rec2["status"] == "ok" and rec2["summary"].startswith("closing full run:")


def test_blocked_face_text_has_no_chinese():
    """票面文字纪律（CLAUDE.md 规则 6）：轻道自产 blocked 文案零 CJK。"""
    wf = _mk_wf()
    ir = _ir_red(["sc_a", "sc_b"], env_fail=1, env_red=["sc_env"])
    text = wf._light_gate_blocked_text(ir, ["sc_a"], "gate round 2")
    assert not _has_cjk(text), "blocked 文案含中文：%r" % text[:200]


# ======================================================================
# F. rework 词表（轻道没有的段=显式拒收）
# ======================================================================

def _rework_req(target, note="n", who="human"):
    return SimpleNamespace(target_stage=target, note=note, who=who,
                           caller_project="", cross_project_note="")


def test_rework_rejects_stages_this_lane_does_not_have():
    wf = _mk_wf()
    for gone in ("create_plan", "review_plan", "design_integration_tests", "arbitrate",
                 "acceptance_walkthrough"):
        wf._rework = _rework_req(gone)
        landing, refusal = wf._consume_light_rework("run_integration_tests")
        assert landing == "" and "not a light-lane stage" in refusal, gone
        assert wf._rework is None, "信号必须先消费（拒收也不残留）"
        assert wf.refused and wf.refused[-1]["want"] == "rework(%s)" % gone
    # 未知值同样拒收
    wf._rework = _rework_req("no_such_stage")
    landing, refusal = wf._consume_light_rework("merge")
    assert landing == "" and refusal


def test_rework_admits_light_stages_and_records_landing():
    wf = _mk_wf(meta={"stage": "run_integration_tests", "role": "integration"})
    wf._rework = _rework_req("implement", note="repair the reds")
    landing, refusal = wf._consume_light_rework("run_integration_tests")
    assert refusal == "" and landing == "implement"
    assert wf.meta["stage"] == "implement"
    assert wf.meta["last_rework_note"] == "repair the reds"
    assert wf.meta["status"] == "rework"
    assert wf.timeline and wf.timeline[-1]["stage"] == "implement"


# ======================================================================
# G. 出路改写：轻道票面不含 create_plan；dev-lane 逐字不变
# ======================================================================

#: 改前原文（真源=server/engine/path_gates.py `_NEXT_ACTION_HINTS["write_set_missing"]`，
#: 字面量照抄）。dev-lane 的负向锁就钉在这串字上：**它一个字都不许变**。
DEV_LANE_WRITE_SET_HINT_BEFORE = "工单写集为空/缺失——回 create_plan 补结构化回执后再实现"


def _gate_refusal_res(reason_code="write_set_missing", next_action=None):
    """闸拒绝回执壳（字段形状照 path_gates.gate_red_detail 的产出）。"""
    return SimpleNamespace(
        status="failed",
        summary="阶段路径闸拒绝落盘（path_gate_reason=write_set_missing）：段 implement 无写集可判",
        gate_refusal={"check_id": "path_gate@implement", "item": "段×允许面路径闸",
                      "red": True, "reason_code": reason_code,
                      "files": ["LIGHT_LANE_PROBE.md"],
                      "next_action": next_action or path_gates.next_action_hint(reason_code)},
        evidence="", files_changed=[], deliverables=[])


def _dev_lane_shell():
    """dev-lane 壳（验「共享串没被动」用；不跑 __init__）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: True, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"blocked_detail": None}
    wf.ticket_id = "t-ut-dev"
    wf._detail_face_on = True
    return wf


def test_shared_hint_is_untouched_and_dev_lane_face_is_verbatim():
    """负向锁：共享提示串与 dev-lane 票面**逐字等于改前**（这条裁定只对轻道生效）。"""
    assert path_gates._NEXT_ACTION_HINTS["write_set_missing"] == DEV_LANE_WRITE_SET_HINT_BEFORE
    assert path_gates.next_action_hint("write_set_missing") == DEV_LANE_WRITE_SET_HINT_BEFORE
    wf = _dev_lane_shell()
    dev_lane.DevLaneWorkflow._pin_agent_refusal(wf, _gate_refusal_res())
    d = wf.meta["blocked_detail"]
    assert d["next_action"] == DEV_LANE_WRITE_SET_HINT_BEFORE, \
        "dev-lane 的出路提示被改动（应逐字不变）"
    assert "next_action_rewritten_from" not in d


def test_light_lane_face_does_not_point_at_create_plan():
    """正向要求：轻道票在 write_set_missing 红上的出路**不含** create_plan。"""
    wf = _mk_wf(meta={"blocked_detail": None, "stage": "implement"})
    wf._pin_agent_refusal(_gate_refusal_res())
    d = wf.meta["blocked_detail"]
    assert "create_plan" not in str(d.get("next_action") or "")
    assert d["next_action"] == light_lane.LIGHT_NEUTRAL_NEXT_ACTION
    assert d["next_action_rewritten_from"] == DEV_LANE_WRITE_SET_HINT_BEFORE, \
        "改写原文必须留痕（不静默丢）"
    assert d["reason_code"] == "write_set_missing" and d["files"] == ["LIGHT_LANE_PROBE.md"]
    # 幂等：再跑一次不叠加、不换新文
    wf._pin_agent_refusal(_gate_refusal_res())
    assert wf.meta["blocked_detail"]["next_action"] == light_lane.LIGHT_NEUTRAL_NEXT_ACTION
    # 与该 reason_code 无关的出路一字不动
    wf2 = _mk_wf(meta={"blocked_detail": None})
    wf2._pin_agent_refusal(_gate_refusal_res("protected_path"))
    na2 = wf2.meta["blocked_detail"]["next_action"]
    assert na2 == path_gates.next_action_hint("protected_path") and "create_plan" not in na2


def test_light_lane_merge_red_hint_is_rewritten_too():
    """merge_check 红的结构化出路（顶层 + 逐条 reds）同样改写；非 create_plan 的不动。"""
    wf = _mk_wf(meta={"blocked_detail": None})
    checks = [
        {"id": "ui_evidence", "item": "UI 截图证据", "green": False, "detail": "缺证据",
         "reason_code": "ui_evidence_missing", "next_action": "泳道内产出截图证据后发 retry_qc"},
        {"id": "path_gate", "item": "段×允许面路径闸", "green": False, "detail": "写集缺失",
         "reason_code": "write_set_missing", "files": ["a.md"],
         "next_action": path_gates.next_action_hint("write_set_missing")},
        {"item": "泳道分支有 commit", "green": True},
    ]
    wf._pin_merge_red_detail(checks, None, disposition="light lane")
    d = wf.meta["blocked_detail"]
    assert "create_plan" not in str(d.get("next_action") or "")
    # 出路文案（现行字段）不许含 create_plan；留痕键 next_action_rewritten_from 是**审计面**，
    # 它必须保留原文（否则改写就成了静默丢证据）
    for r in (d.get("reds") or []):
        assert "create_plan" not in str(r.get("next_action") or ""), r.get("check_id")
    assert any("create_plan" in str(r.get("next_action_rewritten_from") or "")
               for r in (d.get("reds") or [])), "改写原文未留痕"
    reds = {r["check_id"]: r for r in (d.get("reds") or [])}
    assert reds["path_gate"]["next_action"] == light_lane.LIGHT_NEUTRAL_NEXT_ACTION
    assert reds["path_gate"]["next_action_rewritten_from"] == DEV_LANE_WRITE_SET_HINT_BEFORE
    assert reds["ui_evidence"]["next_action"] == "泳道内产出截图证据后发 retry_qc"
    # merge_check 阻断文案（文本面）同样不带 create_plan
    text = wf._light_merge_blocked_text(
        SimpleNamespace(checks=checks, error="", conflict=False, conflict_files=[]),
        "; ".join("%s: %s" % (c.get("item"), c.get("detail")) for c in checks if not c.get("green")))
    assert "create_plan" not in text


# ======================================================================
# G. 注册面与 SDK 定义（显式重新装饰那条门）
# ======================================================================

def test_sdk_definition_is_light_lanes_own():
    from temporalio import workflow as twf
    d = twf._Definition.from_class(light_lane.LightLaneWorkflow)
    assert d.name == "LightLaneWorkflow", "workflow 类型名=类名（worker 注册面）"
    assert d.run_fn.__qualname__.endswith("LightLaneWorkflow.run")
    d0 = twf._Definition.from_class(dev_lane.DevLaneWorkflow)
    assert d0.name == "DevLaneWorkflow" and d0.run_fn.__qualname__.endswith("DevLaneWorkflow.run")
    assert d is not d0, "两条道各自的定义（父类那枚一字不动）"
    # 信号/查询/更新继承面齐全（人门/打回/重跑/裁决/暂停 + 快照 + 状态维护）
    assert {"sign", "rework", "retry_qc", "host_ruling", "pause", "resume"} <= set(d.signals)
    assert {"snapshot", "sign_face"} <= set(d.queries)
    assert "update_status" in d.updates


def test_registry_tables_contain_light_lane():
    import workflows_v2
    assert workflows_v2.TEMPLATE_CLASSES["light-lane"] is light_lane.LightLaneWorkflow
    assert light_lane.LightLaneWorkflow in workflows_v2.ALL_WORKFLOWS_V2
    assert shared.TEMPLATE_CLASS_NAMES["light-lane"] == "LightLaneWorkflow"
    assert shared.TEMPLATE_DISPLAY_NAMES["light-lane"] == "Light Lane"
    # 内置快照面（ticket.py create 的快路径判据）：轻道在其中
    assert "light-lane" in shared.BUILTIN_TEMPLATE_KEYS
    # 注册类名与名面表一致（跨表漂移=建票类选择出错）
    assert shared.TEMPLATE_CLASS_NAMES["light-lane"] == light_lane.LightLaneWorkflow.__name__


def test_yaml_snapshot_exists_and_parses():
    p = REPO / "server" / "workflows" / "light-lane.yaml"
    assert p.is_file(), "内置模板必须有参考快照（gen_workflows_doc 生成面）"
    spec = importlib.util.spec_from_file_location("_wf_tool_ut",
                                                  REPO / "server" / "tools" / "workflow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    doc = mod.load(p)
    assert doc["id"] == "light-lane"
    assert [s["id"] for s in doc["stages"]] == [s.id for s in light_lane.LightLaneWorkflow.STAGES]
    assert doc["lane"] == "worktree"


def test_declared_templates_includes_light_lane():
    assert "light-lane" in tt.declared_templates()
    assert tt.export_template_topology("light-lane") is not None


def test_snapshot_face_shows_light_lane_ticket():
    """控制台读面：snapshot 的 template_id/stage_name/topology 三键对轻道正确。"""
    wf = _mk_wf(meta={"stage": "run_integration_tests", "stage_state": "blocked",
                      "blocked_reason": "gate red", "status": "dispatched",
                      "role": "integration", "acceptance": [],
                      "checks": {}, "handoffs": [], "pending": [],
                      "temporal_engine_version": 2, "workspace": None,
                      "blocked_detail": None})
    wf.signatures, wf.gate_runs, wf.human_context = {}, [], {}
    snap = light_lane.LightLaneWorkflow.snapshot(wf)
    assert snap["template_id"] == "light-lane"
    assert snap["workflow_class"] == "LightLaneWorkflow"
    assert snap["stage_name"] == "跑集成测试"
    assert snap["blocked_reason"] == "gate red"
    assert snap["topology"]["template"] == "light-lane"
