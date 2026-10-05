"""light-lane 单测（宿主令 260930 直修，无票）：段/门声明、拓扑导出面、闸判词与 blocked 契约、注册面。

覆盖口径（=宿主定案 devlane-lite §4.1 的可机械判面）：
  A. 段声明与「不含被排除段」：LIGHT STAGES 恰为五段（implement/ui_evidence/
     run_integration_tests/merge_check/merge）——**首段=implement**，**ui_evidence 是条件段**
     （宿主 260930 第二轮裁定加回；仅 UI 票）。审方案 / 集测设计 / 仲裁 / 验收走查四段与
     **create_plan** 不在表内（轻道不写方案），create_plan 也**不在可返工目标**里；段级
     kind 投影与人门标记正确；拓扑 optional 注记**恰为 ui_evidence 一条**。
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
    assert ids == ["implement", "ui_evidence", "run_integration_tests",
                   "merge_check", "merge"]
    for gone in list(EXCLUDED_STAGES) + ["create_plan"]:
        assert gone not in ids, "轻道段链不得含被排除段 %s" % gone
    # 首段=建票推导取 role 的那一段（client.py/ticket.py 的 stage0 消费面）——
    # 宿主 260930 删 create_plan 后首段就是 implement（role 仍是 developer：建票面
    # 的 stage0.role 推导因此不变）
    assert light_lane.LightLaneWorkflow.STAGES[0].id == "implement"
    assert light_lane.LightLaneWorkflow.STAGES[0].role == "developer"


def test_stage_kinds_roles_and_human_marker():
    by_id = {s.id: s for s in light_lane.LightLaneWorkflow.STAGES}
    assert by_id["implement"].kind == "agent" and by_id["implement"].role == "developer"
    assert by_id["ui_evidence"].kind == "agent" and by_id["ui_evidence"].role == "developer"
    assert by_id["ui_evidence"].parts == ("script",), "UI 证据=脚本段（无 agent 无 LLM）"
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


def test_ui_evidence_stage_is_back_and_ordered_before_the_gate():
    """宿主 260930 第二轮：ui_evidence 段加回，且段序=implement→ui_evidence→机器闸。

    声明面/拓扑面/源码面三处**正向**断言 + 段序正向断言（上一轮那三条「永不出现」的
    负断言按裁定反转——见 e2e 的两条分支：非 UI 票零出现、UI 票真跑）。"""
    ids = [st.id for st in light_lane.LightLaneWorkflow.STAGES]
    assert "ui_evidence" in ids
    impl = next(st for st in light_lane.LightLaneWorkflow.STAGES if st.id == "implement")
    assert impl.next == "ui_evidence", "implement 的下一段=UI 证据条件段"
    ui = next(st for st in light_lane.LightLaneWorkflow.STAGES if st.id == "ui_evidence")
    assert ui.next == "run_integration_tests", "UI 证据之后才进机器闸（段序）"
    topo = tt.export_template_topology("light-lane")
    assert "ui_evidence" in {n["id"] for n in topo["nodes"]}
    assert {n["id"]: n.get("optional") for n in topo["nodes"]}.get("ui_evidence") \
        == tt.OPT_UI_TICKETS, "条件段注记必须在（UI 票才跑）"
    src = _light_src()
    assert 'Stage(id="ui_evidence"' in src
    assert "_ui_evidence_step()" in src


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
    # 口径改写（宿主 260930 第二轮）：本道**能**产证据（条件段），红=这次没产生/没挂上
    assert "This lane CAN produce that evidence" in text
    assert "ui_evidence conditional stage" in text
    assert "rework(to_stage=implement)" in text and "retry_qc" in text
    assert "open a full-lane ticket" not in text, "旧口径（另开全车道票=唯一出路）已作废"
    assert "server/plugins/workbench/src/client/a.ts" in text
    assert "results.ui_evidence" in text
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
    assert "the merge check is red" in text2 and "retry_qc" in text2
    # 票面纪律（宿主 260930）：merge 阻断面同样是**一屏摘要**（行数/字数/无机器清单片段）
    for _t in (text, text2):
        assert len(_t.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES, _t
        assert len(_t) <= light_lane.LightLaneWorkflow.FACE_MAX_CHARS, len(_t)
        assert _bulk_name_fragments(_t) == [], _bulk_name_fragments(_t)
        assert "Outcome:" in _t and "Details: blocked_detail" in _t


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
    # 宿主 260930 第二轮：**条件段 ui_evidence 加回**——拓扑里恰有这一条 optional 注记
    # （与 dev-lane 同一条口径），且节点在位
    optional = {n["id"]: n["optional"] for n in topo["nodes"] if n.get("optional")}
    assert optional == {"ui_evidence": tt.OPT_UI_TICKETS}, optional
    assert "ui_evidence" in {n["id"] for n in topo["nodes"]}
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
    for gone in list(EXCLUDED_STAGES) + ["create_plan"]:
        assert gone not in node_ids
    assert "ui_evidence" in node_ids, "UI 证据条件段须在拓扑里（宿主 260930 第二轮）"
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
    assert "await self._ui_evidence_step()" in src, \
        "UI 证据条件段必须走 dev-lane 的同一个 helper（不新写逻辑）"
    assert 'Stage(id="ui_evidence"' in src, "轻道必须声明 ui_evidence 条件段"
    # 判据/截图实现只许有一份（dev_lane 的 helper）——判据=**调用/入参形态**，注释里的
    # 名词不算（口径说明要能提这些名字，见头注）
    for forbid in ("UiEvidenceArgs(", "prepare_ui_evidence(", "prepare_ui_evidence,",
                   "ui_changed_paths"):
        assert forbid not in src, "轻道不得重复接线截图面（命中 %r）" % forbid
    assert "lane_workspace_gate_error(" not in src, "工作空间准备体不得重抄"
    assert "UiChangedPathsArgs(" not in src, "UI 票判定体不得重抄"
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
    # 轻道契约句点名「没有」的那几段（免得 agent 等一个不存在的段）；UI 证据**是条件段**，
    # 现在反向点名「UI 票才有」（宿主 260930 第二轮），不再列进「没有」里
    for gone in ("方案段", "方案复审", "集测设计", "仲裁", "验收走查"):
        assert gone in light_lane.LIGHT_LANE_PRELUDE
    assert "ui_evidence" in light_lane.LIGHT_LANE_PRELUDE
    assert "UI 票才有" in light_lane.LIGHT_LANE_PRELUDE


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
# E. blocked 契约（宿主 260930 改口径后）：**票面=给人看的摘要**，机器清单进明细
# ======================================================================
# 宿主 260930 实报：阻断面是一大坨机器清单（收窄面 200+ 名、全量违例表、逐名归因表），
# 人找不到「我该做什么」。新口径的机械判据（一个字不放宽）：
#   ① blocked_reason 行数 ≤ FACE_MAX_LINES、字数 ≤ FACE_MAX_CHARS；
#   ② 「逗号分隔 ≥6 项且总长 >400」的机器清单片段**不得**出现在 blocked_reason，
#      但**必须**出现在 blocked_detail（全量仍在，消费方/审计面不丢）；
#   ③ 本票的账最多 5 名 + 「(+N more)」；④ 存量红/环境红只给计数（不列名）。

def _bulk_name_fragments(text):
    """机械判据：逗号分隔 ≥6 项、且该片段总长 >400 的片段（= 机器清单内联）。"""
    out = []
    for m in re.finditer(r"[^\s,;]+(?:\s*,\s*[^\s,;]+){5,}", str(text or "")):
        frag = m.group(0)
        if len(frag) > 400:
            out.append(frag)
    return out


def test_bulk_fragment_detector_has_teeth():
    """变异自证：检测器对「旧形态」（全量名单内联）必须报出来，否则锁是摆设。"""
    old_style = "Complete violation set (15): %s" % ", ".join(T260930_09_VIOLATIONS)
    assert _bulk_name_fragments(old_style), "检测器漏报旧形态=本锁无牙"
    assert not _bulk_name_fragments("Counts: 115 ran / 101 passed; account: a, b, c.")


def test_blocked_face_is_a_summary_and_detail_carries_every_violation():
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta", "sc_gamma"]
    ir = _ir_red(names, blockers=list(names), excluded_pools=["engine"], excluded_count=7,
                 only_names=["sc_alpha"])
    text = wf._light_gate_blocked_text(ir, ["sc_alpha"], "gate round 2 of this attempt")
    # ① 行数/字数上限（票面=一屏摘要）
    assert len(text.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES, text
    assert len(text) <= light_lane.LightLaneWorkflow.FACE_MAX_CHARS, len(text)
    # ② 机器清单片段不得内联
    assert _bulk_name_fragments(text) == [], _bulk_name_fragments(text)
    # ③ 本票的账（可行动）：≤5 名时逐个在票面
    for n in names:
        assert n in text, "可行动面漏了 %s" % n
    assert "Fix (this ticket's account): sc_alpha, sc_beta, sc_gamma" in text
    assert "3 ran / 0 passed / 3 failed / 0 env-red" in text
    # ④ 计数 + 指针 + 出路（票面只给这些）
    for ptr in ("results.run_integration_tests", "out/integration-report-*.json",
                "blocked_detail"):
        assert ptr in text, ptr
    assert "retry_qc" in text and "rework(to_stage=implement)" in text
    assert "dev-lane" in text                                  # 别的道=开全道票
    assert "no arbitration" in text and "no automatic re-run" in text
    assert "Why red:" in text and "a human decides" in text
    assert "narrowed to 1 entry" in text                        # 跑面只给计数
    assert "engine" in text and "7 entries" in text             # 跳过池只给计数
    # 全量违规集与逐名归因**仍在明细里**（票面瘦身 ≠ 数据丢失）
    d = wf._light_gate_blocked_detail(ir, ["sc_alpha"], "light_gate_red", "r1")
    assert d["violations"] == names and d["violations_complete"] is True
    _attr = d["attribution"]
    assert _attr["main_red_too"] == [] and _attr["lane_only"] == []
    assert sorted(_attr["unknown"]) == sorted(names), "无基线答案=unknown（保守口径）"


def test_blocked_face_caps_the_account_list_at_five_names():
    """本票的账 >5 名 → 票面只列 5 个 + (+N more)；全量在明细里（机械判据）。"""
    wf = _mk_wf()
    names = ["sc_n%d" % i for i in range(9)]
    ir = _ir_red(names, blockers=list(names))
    text = wf._light_gate_blocked_text(ir, [], "gate round 3")
    assert "(+4 more)" in text, text
    assert "sc_n4" in text and "sc_n5" not in text, "第 6 名起只能以计数形式出现"
    assert len(text.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES
    assert _bulk_name_fragments(text) == []
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "gate round 3")
    assert d["violations"] == names      # 全量在明细里（票面规则不吞数据）
    dump = json.dumps(d, ensure_ascii=False)
    for n in names:
        assert n in dump, "明细面丢了红名 %s" % n


def test_blocked_face_says_none_of_the_reds_are_the_ticket_account():
    """blockers 空（红全是存量/他因）→ 明写「none of the reds are this ticket's account」。"""
    wf = _mk_wf()
    ir = _ir_red(["sc_x", "sc_y"], blockers=[])
    ir.live_baseline_red = ["sc_x", "sc_y"]
    text = wf._light_gate_blocked_text(ir, [], "gate round 1")
    assert "none of the reds are this ticket's account" in text
    assert "Recorded, not blocking: 2 pre-existing on main" in text
    # 存量红**不列名**（只给计数）
    assert "sc_x" not in text and "sc_y" not in text


def test_blocked_text_reports_full_round_and_absent_reuse_face():
    wf = _mk_wf()
    text = wf._light_gate_blocked_text(_ir_red(["sc_x"]), [], "gate round 1")
    assert "full registry (not narrowed)" in text
    # 老回执无复用块：如实记「没搬到」，不冒充「零复用」（保守方向）
    assert "reuse/known-red: n/a (old receipt)" in text
    assert "expected" not in text


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
    # 显式指针键（宿主 260930：一键找到全量机器清单）
    assert d["report_path"] == "out/integration-report-*.json"
    assert d["receipt_ref"] == "results.run_integration_tests"
    assert d["detail_ref"] == "blocked_detail"
    # 可 JSON 序列化（票面/控制台机读契约）
    json.dumps(d, ensure_ascii=False)


def test_blocked_detail_evidence_is_counts_and_pointer_not_the_full_face():
    """宿主 260930：`evidence` 字段里的收窄面/全表改成计数 + 指针（现在是全表）。"""
    wf = _mk_wf()
    names = ["sc_n%d" % i for i in range(12)]
    ir = _ir_red(names, blockers=list(names), only_names=list(names),
                 excluded_pools=["engine"], excluded_count=40)
    d = wf._light_gate_blocked_detail(ir, list(names), "light_gate_red",
                                      "gate round 2 of this attempt")
    ev = d["evidence"]
    assert len(ev) <= 600
    assert "counts: 12 ran / 0 passed / 12 failed / 0 env-red" in ev
    assert "narrowed entr" in ev and "pools skipped" in ev
    assert "out/integration-report-*.json" in ev
    assert "sc_n0" not in ev and "sc_n11" not in ev, "逐条名单不许内联进 evidence"
    assert _bulk_name_fragments(ev) == []
    # 全表仍在同块的结构化面上
    assert d["violations"] == names and d["round"]["narrowed"] == names


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
    # 票面只给计数：复用/在册红的**名字**不许内联
    assert "reused=5 of expected=8" in text
    assert "known-red excluded: 2" in text
    assert "sc_r1" not in text and "sc_k1" not in text, "复用/在册红名单进了票面"
    assert _bulk_name_fragments(text) == []


def test_run_face_absent_marks_are_honest():
    """缺席面必须**具名原因**（260930：真票 t260930-09 的 "absent" 说不清是没注入还是没搬到）。"""
    wf = _mk_wf()
    face = wf._light_run_face(_ir(), [])
    assert isinstance(face["reuse"], str) and "absent" in face["reuse"]
    kr = face["known_red"]
    assert isinstance(kr, dict), kr
    assert kr["available"] is False and kr["names"] == [] and kr["skipped"] == 0
    assert "injected" in kr, "缺席时必须把「注入事实」与「没搬到」分开点名"
    assert "carried no such block" in kr["reason"]
    # 在场（新回执）→ 原样带出（含 injected 事实）
    wf2 = _mk_wf()
    ir2 = _ir()
    ir2.known_red = {"injected": True, "skipped": 2, "names": ["kd_a", "kd_b"], "note": "n"}
    face2 = wf2._light_run_face(ir2, [])
    assert face2["known_red"]["injected"] is True and face2["known_red"]["skipped"] == 2
    assert face2["known_red"]["names"] == ["kd_a", "kd_b"]


def test_face_note_counts_what_was_not_run_and_points_at_the_receipt():
    """票面注记（轻道自产那半）：少跑面只给**计数 + 指针**——名单不进票面。"""
    wf = _mk_wf()
    assert wf._light_face_note(_ir(), []) == "", "全量且无少跑面=不加注记"
    ir = _ir_red(["sc_a"], only_names=["sc_a", "sc_b"], excluded_pools=["engine"],
                 excluded_count=4)
    ir.reuse = {"reused": 2, "expected": 5}
    ir.known_red = {"skipped": 1, "names": ["sc_k"]}
    note = wf._light_face_note(ir, ["sc_a", "sc_b"])
    assert "narrowed to 2 entries (list in the receipt)" in note
    assert "pools skipped: engine (4 entries)" in note
    assert "ledger reuse: reused=2 of expected=5 (not executed)" in note
    assert "known-red entries excluded: 1" in note
    assert "sc_a" not in note and "sc_b" not in note and "sc_k" not in note, \
        "少跑面的名单进了票面注记（宿主 260930：票面只给计数）"
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
# F2. UI 证据条件段：两态（UI 票落痕 / 非 UI 票零痕迹）
# ======================================================================

def test_ui_evidence_stage_records_only_for_ui_tickets():
    """条件判据两态：helper 只在 UI 票上写回执 → 只有 UI 票落段痕。

    判据来源=dev_lane._ui_evidence_step 的产物（本类不重写判据）；这两条断言就是
    「非 UI 票零痕迹 / UI 票真落痕」的单元面。"""
    # 非 UI 票：没有回执 → 零条目零记账（返回 False）
    wf = _mk_wf(meta={"checks": {"ui_evidence": [{"item": "x", "done": False, "by": ""}]},
                      "handoffs": [], "stage": "implement"})
    assert wf._light_record_ui_evidence(wf._now_epoch()) is False
    assert wf.timeline == [] and wf.meta["handoffs"] == []
    assert wf.meta["checks"]["ui_evidence"][0]["done"] is False

    # UI 票：helper 写了回执 → running（终态痕迹，带真时长）+ done + 段验收勾选 + 交接
    wf2 = _mk_wf(meta={"checks": {"ui_evidence": [{"item": "shots", "done": False, "by": ""}]},
                       "handoffs": [], "stage": "implement", "role": "developer"})
    wf2.results["ui_evidence"] = {
        "status": "ok", "summary": "[stub] 假截图两张", "report": "",
        "deliverables": ["console-default.png"], "files_changed": [],
        "evidence": "【UI 票判定（diff 源）】命中 1 个 UI 路径", "gen": 0}
    assert wf2._light_record_ui_evidence(wf2._now_epoch() - 3) is True
    states = [(e["stage"], e["state"]) for e in wf2.timeline]
    assert states == [("ui_evidence", "running"), ("ui_evidence", "done")], states
    assert "terminal trace" in wf2.timeline[0]["reason"]
    assert "real duration 3s" in wf2.timeline[0]["reason"], wf2.timeline[0]["reason"]
    assert wf2.meta["checks"]["ui_evidence"][0]["done"] is True
    assert wf2.meta["checks"]["ui_evidence"][0]["by"] == "ui-capture"
    assert wf2.meta["handoffs"][-1]["stage"] == "ui_evidence"
    assert wf2.meta["handoffs"][-1]["artifacts"] == ["console-default.png"]


def test_ui_evidence_record_is_ordered_after_implement_before_the_gate():
    """段序：落痕两条必须排在 implement/done 之后（机器闸 `_enter` 之前由 run() 保证）。"""
    wf = _mk_wf(meta={"checks": {"ui_evidence": [{"item": "shots", "done": False, "by": ""}]},
                      "handoffs": [], "stage": "implement", "role": "developer"})
    wf._mark("implement", "done", "developer-agent：实现完成")
    wf.results["ui_evidence"] = {"status": "ok", "summary": "shots", "report": "",
                                 "deliverables": ["a.png"], "files_changed": [],
                                 "evidence": "", "gen": 0}
    wf._light_record_ui_evidence(wf._now_epoch())
    seq = [(e["stage"], e["state"]) for e in wf.timeline]
    assert seq == [("implement", "done"), ("ui_evidence", "running"), ("ui_evidence", "done")], seq


# ======================================================================
# F3. t260930-09 真票形态夹具：环境红不可具名 / 在册红豁免面 / 逐名归因
# ======================================================================
# 数据真源（260930 实况，从该票 snapshot 的 blocked_detail 原样抄下）：
#   闸轮：ran=115 / passed=100 / failed=13 / env_fail=2（6m08s）；violations 15 名；
#   环境红具名通道 env_red=[]（闸具名通道在场但空）→ 这 2 条**不可具名**；
#   round.known_red="absent: the receipt carried no such block"（那时还没搬这一块）。
T260930_09_VIOLATIONS = [
    "t260905-03-decl-gate",
    "capture-chat-active",
    "t260913-03-executor-pool-exclude-l1",
    "t260913-03-pool-exclude-no-false-green",
    "t260913-03-pool-exclude-force-assets",
    "t260913-03-pool-exclude-switch-forms",
    "capture-chat-e2e",
    "lane-parallel-dom",
    "t260904-06-spec-card-dom",
    "t260915-08-board-ui",
    "t260915-05-detail-lane-map-dom",
    "t260916-04-lane-map-everblocked-dom",
    "t260916-05-inspection-detail-lane-map-dom",
    "t260916-25-stage-console-selfcheck-red",
    "t260929-03-executor-panel-page",
]
T260930_09_BLOCKERS = [
    "t260913-03-executor-pool-exclude-l1",
    "t260913-03-pool-exclude-no-false-green",
    "t260913-03-pool-exclude-force-assets",
    "t260913-03-pool-exclude-switch-forms",
    "t260916-25-stage-console-selfcheck-red",
    "t260929-03-executor-panel-page",
]


def _t260930_09_ir():
    """t260930-09 真票回执夹具：15 名违规（其中 2 条是**不可具名**的环境红行）、
    基线逐名答案只覆盖 1 条（capture-chat-active 基线绿 = lane-only）。"""
    det = [{"name": n, "cmd": "", "exit": 1, "output_tail": ""}
           for n in T260930_09_VIOLATIONS]
    return shared.IntegrationRunResult(
        ran=115, passed=100, failed=13, env_fail=2, details=det, error="",
        blockers=list(T260930_09_BLOCKERS), env_red=[],          # 闸具名通道在场但空
        env_red_names=[],                                        # 执行器侧也没名单
        live_baseline_red=[], live_baseline_green=["capture-chat-active"],
        live_baseline_source=("in-round gate baseline (1 answered name(s), ref=abc1234)"),
        baseline_ref="abc1234",
        only_names=list(T260930_09_VIOLATIONS), excluded_pools=["engine", "exclusive"],
        excluded_count=82)


def test_t260930_09_env_red_unnamable_is_named_explicitly():
    """缺陷①回归：env_fail>0 而两路具名通道都拿不出名字 → 必须**显式点名不可具名**。"""
    wf = _mk_wf()
    ir = _t260930_09_ir()
    face = wf._light_env_red_face(ir)
    assert face["count"] == 2 and face["gate"] == [] and face["runner"] == []
    assert face["state"] == light_lane.ENV_RED_UNNAMEABLE
    detail = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "gate round 1")
    assert detail["env_red_state"] == "unnameable"
    assert detail["env_red_count"] == 2
    assert "present but empty" in detail["env_red_note"]
    assert detail["env_red_note"], "不可具名的原因必须落在结构化面上（不许空串）"
    assert "NOT NAMEABLE" in detail["env_red_face_note"]      # 可读句子留明细面
    text = wf._light_gate_blocked_text(ir, [], "gate round 1")
    assert "Environment red(s): 2 NOT NAMEABLE" in text
    assert "no name, no exemption" in text
    # 票面=短句；全文（「the gate's named channel … present but empty」）在明细 env_red_note 里
    assert "gate channel present but empty" in text
    assert "the gate's named channel" in detail["env_red_note"]
    # 不可具名的环境红是**判红原因**（不是「已记录、不阻断」）
    assert "not nameable (no name, no exemption)" in text
    assert "Recorded, not blocking" not in text
    # 有名字的一路（执行器侧）→ named，且票面只给计数（名字在明细的 env_red_runner 里）
    ir2 = _t260930_09_ir()
    ir2.env_red_names = ["sc_env_a"]
    face2 = wf._light_env_red_face(ir2)
    assert face2["state"] == light_lane.ENV_RED_NAMED and face2["runner"] == ["sc_env_a"]
    text2 = wf._light_gate_blocked_text(ir2, [], "gate round 1")
    assert "2 environment red(s)" in text2 and "NOT NAMEABLE" not in text2
    d2 = wf._light_gate_blocked_detail(ir2, [], "light_gate_red", "gate round 1")
    assert "sc_env_a" in d2["env_red_runner"] or "sc_env_a" in d2["env_red_face_note"]
    # 无环境红 → none（票面不加环境红那段）
    ir3 = _t260930_09_ir()
    ir3.env_fail = 0
    assert wf._light_env_red_face(ir3)["state"] == light_lane.ENV_RED_NONE
    assert "Environment red" not in wf._light_gate_blocked_text(ir3, [], "r1")


def test_t260930_09_known_red_face_transport_and_injection_are_separated():
    """缺陷②回归：注入事实与运输事实分开点名（两态：在场 / 缺席且具名原因）。"""
    wf = _mk_wf()
    # 在场（verify_lane/agent_activities 260930 起搬运）：计数上票面，名单在明细
    ir = _t260930_09_ir()
    ir.known_red = {"injected": True, "skipped": 2, "names": ["kd_a", "kd_b"],
                    "note": "未跑 ≠ 判绿", "injection": "SANDBAR_KNOWN_RED_EXCLUDE=1"}
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "r1")
    assert d["round"]["known_red"]["skipped"] == 2
    assert d["round"]["known_red"]["injected"] is True
    assert d["round"]["known_red"]["names"] == ["kd_a", "kd_b"]
    text = wf._light_gate_blocked_text(ir, [], "r1")
    assert "known-red excluded: 2" in text
    assert "kd_a" not in text, "在册红名单进了票面（宿主 260930：只给计数）"
    # 「在场但本轮没豁免任何条」也要说清（不是「不可得」）
    ir3 = _t260930_09_ir()
    ir3.known_red = {"injected": True, "skipped": 0, "names": [], "note": ""}
    text3 = wf._light_gate_blocked_text(ir3, [], "r1")
    assert "known-red excluded: 0" in text3
    # 缺席（老回执）：不说「absent」了事——点名「没搬到」+ 注入未知
    ir2 = _t260930_09_ir()
    d2 = wf._light_gate_blocked_detail(ir2, [], "light_gate_red", "r1")
    kr2 = d2["round"]["known_red"]
    assert kr2["available"] is False and kr2["injected"] == "unknown"
    assert "carried no such block" in kr2["reason"]
    text2 = wf._light_gate_blocked_text(ir2, [], "r1")
    assert "reuse/known-red: n/a (old receipt)" in text2


def test_t260930_09_attribution_three_labels_and_unknown_is_conservative():
    """缺陷③回归：三态标注（lane-only / main-red-too / unknown）+ unknown 的保守方向。

    判据不许放宽：unknown 既不当 main 绿读（不给豁免），也不当放行读（仍 blocked）。
    票面口径（宿主 260930）：归因表**逐名进 blocked_detail.attribution**，票面只给计数。"""
    wf = _mk_wf()
    ir = _t260930_09_ir()
    ir.live_baseline_red = ["t260905-03-decl-gate"]          # 存量：main 也红
    ir.live_baseline_green = ["capture-chat-active"]         # 本票的账：main 绿
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "gate round 1")
    attr = d["attribution"]
    assert attr["lane_only"] == ["capture-chat-active"]
    assert attr["main_red_too"] == ["t260905-03-decl-gate"]
    assert len(attr["unknown"]) == len(T260930_09_VIOLATIONS) - 2
    assert set(attr["lane_only"]) | set(attr["main_red_too"]) | set(attr["unknown"]) \
        == set(T260930_09_VIOLATIONS), "归因必须覆盖**每一个**红名（不漏项）"
    assert attr["baseline_ref"] == "abc1234" and "in-round gate baseline" in attr["source"]
    assert "NEVER read as main-green" in attr["rule"]
    assert "NEVER as a landing permit" in attr["rule"]
    assert "main-red-too" in attr["note"] and "unknown" in attr["note"]  # 明细可读计数句
    text = wf._light_gate_blocked_text(ir, [], "gate round 1")
    # 票面：计数 + 判断据，逐名归因表不内联
    assert "1 pre-existing on main" in text
    assert "13 red(s) with no baseline answer" in text
    # 票面=短句；保守口径全文（NEVER read as main-green / NEVER as a landing permit）在明细 rule 里
    assert "unknown is NOT main-green" in text
    assert "NEVER as a landing permit" in attr["rule"]
    assert "t260905-03-decl-gate" not in text, "存量红逐名进了票面（只许计数）"
    # 本票的账=闸拦名单 − main-red-too（可行动面 ≤5 名）
    assert "Fix (this ticket's account):" in text
    # 拦名单 6 个 → 票面只列 ≤5 名 + 「(+N more)」（N=没列出的条数，机械复算不信自报）
    _shown = [n for n in T260930_09_BLOCKERS if n in text]
    assert 1 <= len(_shown) <= light_lane.LightLaneWorkflow.FACE_NAME_LIMIT, _shown
    assert "(+%d more)" % (len(T260930_09_BLOCKERS) - len(_shown)) in text
    assert "capture-chat-active" not in text, "非拦名单的红不许当「本票的账」列出"
    for n in T260930_09_VIOLATIONS:                          # 逐名归因仍在明细面
        assert n in json.dumps(d, ensure_ascii=False)
    # 保守方向：baseline 完全不可得 → 全部 unknown（=本票的账），一个都不许标成 main-red-too
    ir2 = _t260930_09_ir()
    ir2.live_baseline_green = []
    attr2 = wf._light_gate_attribution(ir2, T260930_09_VIOLATIONS)
    assert attr2["lane_only"] == [] and attr2["main_red_too"] == []
    assert len(attr2["unknown"]) == len(T260930_09_VIOLATIONS)
    # 两路都有该名时绿优先（保守：仍是本票的账）
    ir3 = _t260930_09_ir()
    ir3.live_baseline_green = ["capture-chat-active"]
    ir3.live_baseline_red = ["capture-chat-active"]
    assert wf._light_gate_attribution(ir3, ["capture-chat-active"])["lane_only"] \
        == ["capture-chat-active"]


def test_verdict_consumes_gate_attribution_not_raw_violations():
    """t260930-09 判定缺陷回归（本条的判词面）：轻道必须**照闸的归因结论**判，不按 violations。

    green ⟺ ① blockers 空 ② 无 unknown（每个产品红都有基线答案）③ env_fail 必须具名。
    任一不成立 → red（现状口径不变）。"""
    wf = _mk_wf()
    # ① blockers 空 + 全有基线答案（全是 main-red-too）→ **绿**，且逐名记录在案
    ir = _t260930_09_ir()
    ir.blockers = []
    ir.live_baseline_red = list(T260930_09_VIOLATIONS)      # main 也红（存量）
    ir.live_baseline_green = []
    ir.env_fail = 0
    assert wf._light_gate_verdict(ir) == "green", "①+②+③ 全成立必须判绿"
    rec = wf._light_recorded_pre_existing(ir)
    assert rec["count"] == len(T260930_09_VIOLATIONS) and rec["names"] == T260930_09_VIOLATIONS
    assert rec["baseline_ref"] == "abc1234"
    assert "in-round gate baseline" in rec["source"], rec["source"]
    assert "recorded, not blocking" in rec["note"] and "NOT a silent skip" in rec["note"]
    receipt = wf._light_gate_receipt(ir, gen=0)
    assert receipt["recorded_pre_existing"]["count"] == len(T260930_09_VIOLATIONS)
    assert "recorded (main-red-too, not blocking)" in receipt["summary"]
    assert receipt["blockers"] == [] and len(receipt["violations"]) == len(T260930_09_VIOLATIONS)
    # ② 有 unknown（基线没答案）→ **仍红**（不许当绿）
    ir2 = _t260930_09_ir()
    ir2.blockers = []
    ir2.env_fail = 0
    ir2.live_baseline_red = [T260930_09_VIOLATIONS[0]]
    ir2.live_baseline_green = [T260930_09_VIOLATIONS[1]]
    assert wf._light_gate_verdict(ir2) == "red", "有不可归因的红必须红"
    assert wf._light_recorded_pre_existing(ir2)["names"] == [T260930_09_VIOLATIONS[0]]
    # ③ blockers 非空 → 红（本票的账照旧拦），即使全有基线答案
    ir3 = _t260930_09_ir()
    ir3.live_baseline_red = list(T260930_09_VIOLATIONS)
    ir3.live_baseline_green = []
    ir3.env_fail = 0
    assert ir3.blockers and wf._light_gate_verdict(ir3) == "red"
    # ③' env_fail>0 且不可具名 → 红
    ir4 = _t260930_09_ir()
    ir4.blockers = []
    ir4.live_baseline_red = list(T260930_09_VIOLATIONS)
    ir4.live_baseline_green = []
    assert wf._light_gate_verdict(ir4) == "red", "unnameable 环境红仍判红"
    # 真票当轮形状（blockers=6）→ 红（这就是「修后那轮仍是红」的依据）
    assert wf._light_gate_verdict(_t260930_09_ir()) == "red"


def test_verdict_shape_guards_stay_conservative():
    """形状守卫（不许因判据改写而放走畸形回执）：计数读不懂 / 有计数无名单 ⇒ 红。"""
    wf = _mk_wf()
    assert wf._light_gate_verdict(_ir(failed="not-a-number")) == "red"
    assert wf._light_gate_verdict(_ir(env_fail="??")) == "red"
    assert wf._light_gate_verdict(_ir(failed=2)) == "red", "有失败计数却零红名=名单不可信"


def test_t260930_09_rendered_face_example(capsys=None):
    """把真票数据渲染出来的阻断面打出来（人工可读的证据面；断言钉「一屏摘要」口径）。

    宿主 260930 要这串原文拿给人看：≤10 行、≤1200 字、无机器清单片段、全量仍在明细里。"""
    wf = _mk_wf()
    ir = _t260930_09_ir()
    ir.live_baseline_red = ["t260905-03-decl-gate"]
    ir.live_baseline_green = ["capture-chat-active"]
    text = wf._light_gate_blocked_text(ir, [], "gate round 1 of this attempt")
    print("\n===== t260930-09 阻断面（真数据渲染，宿主口径）=====\n" + text + "\n")
    assert "115 ran / 100 passed / 13 failed / 2 env-red" in text
    assert "Fix (this ticket's account):" in text
    assert len(text.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES
    assert len(text) <= light_lane.LightLaneWorkflow.FACE_MAX_CHARS
    assert _bulk_name_fragments(text) == []
    # 15 名全量 + 6 名拦名单 + 逐名归因：一条不丢，全在结构化明细里
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red",
                                      "gate round 1 of this attempt")
    dump = json.dumps(d, ensure_ascii=False)
    for n in T260930_09_VIOLATIONS:
        assert n in dump, "设备面丢了红名 %s" % n
    assert d["blockers"] == T260930_09_BLOCKERS


# ======================================================================
# F4. 闸前主同步（宿主 260930 直修，根因级）：同一 helper / 同一同位点 / 只此一份
# ======================================================================
# 病根：闸在**泳道自己的 worktree** 里跑集成命令，泳道=开票那刻的 main 快照 ⇒ 开票后落进
# main 的修复不在泳道里 ⇒ 闸把「main 的账」判成 lane-only（本票的账）。修法=照全车道既有
# 机制走：闸相位入口（0-commit 前置检查之后、跑闸之前）把 main 并进泳道一次。

LIGHT_SRC = (POC / "light_lane.py").read_text("utf-8")
DEV_SRC = (POC / "dev_lane.py").read_text("utf-8")


def _light_gate_phase_block():
    src = LIGHT_SRC
    start = src.index('if phase == "run_integration_tests":')
    end = src.index('if phase == "merge_check":', start)
    return src[start:end]


def _dev_sync_helper_block():
    src = DEV_SRC
    start = src.index("async def _main_sync_before_gate(")
    end = src.index("    @workflow.run", start)
    return src[start:end]


def test_light_lane_syncs_main_before_the_gate_via_the_shared_helper():
    """① 轻道闸前确实调**同一个** helper，且排在 0-commit 前置检查之后、跑闸之前。"""
    block = _light_gate_phase_block()
    i_gate = block.index("verify_review_gate")
    i_sync = block.index("self._main_sync_before_gate(")
    i_run = block.index("self._light_gate_round(")
    assert i_gate < i_sync < i_run, "闸前主同步的同位点错了（判据/必重跑纪律会破）"
    assert "workflow.patched(LIGHT_MAIN_SYNC_PATCH_ID)" in block, \
        "在飞老实例重放旧轮必须走旧路径（新门），不许无条件加命令"
    assert "texts=self.LIGHT_MAIN_SYNC_TEXTS" in block, "轻道票面英文档没接上"
    assert light_lane.LIGHT_MAIN_SYNC_PATCH_ID == "light-lane-main-sync-v1"
    assert "async def _main_sync_before_gate" in DEV_SRC, "共享机制不在（dev-lane 那份）"
    # 机制由 helper 给：轻道侧只做「回填计数/落点相位/stop 处置」
    for frag in ('conflict_rounds = int(_ms.get("conflict_rounds") or 0)',
                 'prev_conflict_files = list(_ms.get("prev_conflict_files") or [])',
                 'if _ms.get("stop"):'):
        assert frag in block, frag


def test_light_lane_narrowed_face_empty_is_patch_gated_and_vocab_sourced():
    """空收窄面回落（宿主 260930 实报，真票 t260930-14 第 4 轮）的**重放兼容**结构锁。

    本修法给 `_light_gate_plan` 里新增了一次活动调用（读挂账册的名册活动）。在飞老实例
    （历史里已有 4 个闸轮、没有本标记）重放旧轮时，无门 ⇒ 多出一条 ScheduleActivityTask
    命令 ⇒ 与历史逐条对不上 ⇒ NonDeterminismError（票直接卡死，t260917-04 是同款事故）：
    `workflow.patched()`=False ⇒ 旧命令序列逐字不变；追平历史之后的新一轮 =True ⇒ 真走回落。

    另一条锁：豁免词表必须取 `shared.KNOWN_RED_VERDICTS`（唯一真源）——写死字面量会在词表
    演进时静默错位成「引擎说面没空、执行器照豁免」= 又回到跑 0 条。"""
    src = LIGHT_SRC
    fn = src.index("async def _light_gate_plan(")
    body = src[fn:src.index("\n    async def ", fn + 10)]
    i_patch = body.index("workflow.patched(LIGHT_NARROWED_FACE_PATCH_ID)")
    i_roster = body.index("await self._booked_red_names()")
    assert i_patch < i_roster, "名册活动调用必须在门内（门外的活动调用=重放加命令）"
    # 门内：缩进必须比 `if workflow.patched(...)` 那一行更深（结构锁，不用 AST 也用不着）
    line = body[:i_roster].rsplit("\n", 1)[-1]
    gate_line = body[:i_patch].rsplit("\n", 1)[-1]
    assert len(line) - len(line.lstrip()) > len(gate_line) - len(gate_line.lstrip()), \
        "名册活动调用不在 patched 门内（缩进不更深）"
    assert src.count("await self._booked_red_names()") == 1, "调用点只此一处"
    assert light_lane.LIGHT_NARROWED_FACE_PATCH_ID == "light-lane-narrowed-face-empty-v1"
    assert "shared.KNOWN_RED_VERDICTS" in src, \
        "豁免词表要取唯一真源（shared.KNOWN_RED_VERDICTS），不许写死字面量"
    assert '"booked", "isolated"' not in src and "'booked', 'isolated'" not in src


def test_light_lane_gate_rounds_enter_gate_runs_and_face_says_who_verified():
    """261001 补的两件面（宿主令：每轮报要能读到「谁验的」；闸轮要有账）：

    ① `gate_runs` 里必须有**机器闸**那一条（此前轻道只在 merge_check 处 append ⇒ 闸轮在这本账上是
       空的，泳道图/回执面看不到这一轮跑了几条、绿不绿、窄面多少、豁免多少）；键族与 dev_lane 的
       消费面同形（stage/label/green/red_count/counts/exit_code），并带轻道自己的窄面/豁免计数。
    ② 人面（blocked_reason）必须带「谁验的」一行，且**单点复用** shared.worker_verified_line
       （不许在轻道里另写一份文案，否则两处会漂移）；不可得时那一行也具名（不出现无主语「验过了」）。
    两条都是纯内存追加/纯文本，**不新增命令** ⇒ 不需要 workflow.patched 门。"""
    body = LIGHT_SRC[LIGHT_SRC.index("async def run("):]
    gate_block = body[body.index("_light_gate_round("):body.index("verdict = self._light_gate_verdict")]
    assert 'self.gate_runs.append({' in gate_block, "机器闸轮没有进 gate_runs"
    for frag in ('"stage": "run_integration_tests"', '"green": self._light_gate_verdict(ir) == "green"',
                 '"red_count": len(self._light_red_names(ir))', '"counts":', '"narrowed":',
                 '"known_red_skipped":'):
        assert frag in gate_block, "闸轮账缺键：%s" % frag
    assert 'self.gate_runs.append({' in LIGHT_SRC[LIGHT_SRC.index("async def _light_merge_check"):][:2000], \
        "merge_check 那一处既有账被动了"
    # 人面：一行「谁验的」，单点复用 shared 的文案函数
    face = LIGHT_SRC[LIGHT_SRC.index("def _light_gate_blocked_text"):LIGHT_SRC.index("def _light_gate_blocked_detail")]
    assert 'shared.worker_verified_line(' in face, "人面没有「谁验的」一行（或没走单点）"
    assert "lines.append(_vf)" in face, "具名行没有上台面"
    assert light_lane.LightLaneWorkflow.FACE_MAX_LINES >= 9
    assert light_lane.LightLaneWorkflow.FACE_MAX_CHARS >= 1200


def test_light_lane_has_no_second_main_sync_implementation():
    """③ 结构锁：轻道不得出现第二份主同步实现（会话/活动/消解回路都只在 helper 里）。"""
    assert "async def _main_sync_before_gate" not in LIGHT_SRC, \
        "轻道自己写了一份主同步（宿主令：照既有机制走，不许另造）"
    for frag in ("prepare_conflict_resolution", "settle_conflict_resolution",
                 "main_sync_conflict_route", "ConflictPrepArgs", "ConflictSettleArgs"):
        assert frag not in LIGHT_SRC, "轻道侧出现主同步机制碎片：%s" % frag
    # 同步入口只此一处（=调共享 helper）；「git merge main」只允许作为**提示词文本**出现
    # （agent 上下文里描述 worker 已做过什么），不允许作为命令执行面出现——命令执行面
    # （subprocess/git 调用）在 activity 里，轻道侧连 subprocess 都不 import。
    # 源码面出现次数=调用点数（t261002-10 起为 2：闸相位入口 + merge_check 相位入口，
    # 都调同一条共享 helper——轻道不做第二份实现，只加调用点）
    assert LIGHT_SRC.count("await self._main_sync_before_gate(") == 2
    assert "subprocess" not in LIGHT_SRC
    assert "os.system" not in LIGHT_SRC
    # 「不自造打回」：主同步的落点相位由 helper 的既有回路给——轻道闸相位块里零 _auto_rework
    # 调用（`_auto_rework` 在本类另有合法出现：信号 rework 的落点校验，见 _consume_light_rework）
    assert "_auto_rework(" not in _light_gate_phase_block()


def test_dev_lane_sync_command_sequence_is_verbatim_after_extraction():
    """② 抽 helper 的纪律：命令序列/入参/等待点逐字不变（dev-lane 行为零变化）。"""
    h = _dev_sync_helper_block()
    for lit in ("prepare_conflict_resolution,", "ConflictPrepArgs(ticket_id=self.ticket_id,",
                'base_ref="main"', "start_to_close_timeout=SHORT, retry_policy=RETRY",
                "settle_conflict_resolution,", "ConflictSettleArgs(ticket_id=self.ticket_id,",
                "round_no=conflict_rounds)", "MAX_CONFLICT_ROUNDS",
                "main_sync_conflict_route(",
                # t261002-10：blocked 点名改走 step_id 参数（缺省仍=闸相位原值，
                # merge_check 入口传 "merge_check"——字面量被参数化，锚随语义更新）
                "fallback=step_id"):
        assert lit in h, "抽块丢了原命令序列字面量：%s" % lit
    # 调用点仍是唯一同位点 + 计时面照旧累计（t260925-12）
    block = DEV_SRC[DEV_SRC.index('if phase == "run_integration_tests":'):
                    DEV_SRC.index("# 3.3) arbitration")]
    assert block.count("self._main_sync_before_gate(") == 1
    assert 'gate_sync_s += float(_ms.get("sync_s") or 0.0)' in block
    # 旧内联块不残留（抽完只此一处）
    assert "praw = await workflow.execute_activity(" not in block


def test_light_lane_sync_texts_cover_every_hook_in_english():
    """轻道票面英文（规则 6）：helper 里每个文案钩子键都要有英文覆写档，不漏键。"""
    T = light_lane.LightLaneWorkflow.LIGHT_MAIN_SYNC_TEXTS
    hooks = set(re.findall(r'\b(?:_abort_)?text\("([a-z_]+)"', DEV_SRC))
    assert hooks, "文案钩子一个都没扫到（钩子形态变了？）"
    missing = sorted(hooks - set(T))
    assert not missing, "轻道英文档缺键（漏键=票面回落中文）：%s" % missing
    for k, v in T.items():
        assert str(v).strip(), k
        assert not _has_cjk(v), "轻道主同步文案含中文：%s=%r" % (k, str(v)[:60])
    # defaults (both lanes) = dev-lane hook defaults (t261004-36 translated; pinned verbatim in English)
    assert "main sync failed (hand over to a human" in DEV_SRC
    assert "main-sync conflict resolution completed (round %d)" in DEV_SRC


# ======================================================================
# G. 出路改写：轻道票面不含 create_plan；dev-lane 逐字不变
# ======================================================================

#: 改前原文（真源=server/engine/path_gates.py `_NEXT_ACTION_HINTS["write_set_missing"]`，
#: 字面量照抄）。dev-lane 的负向锁就钉在这串字上：**它一个字都不许变**。
DEV_LANE_WRITE_SET_HINT_BEFORE = ("Ticket write set is empty/missing — return to "
    "create_plan to restore the structured receipt before implementing")


def _gate_refusal_res(reason_code="write_set_missing", next_action=None):
    """闸拒绝回执壳（字段形状照 path_gates.gate_red_detail 的产出）。"""
    return SimpleNamespace(
        status="failed",
        summary="阶段路径闸拒绝落盘（path_gate_reason=write_set_missing）：段 implement 无写集可判",
        gate_refusal={"check_id": "path_gate@implement", "item": "Stage × allowed-face path gate",
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
        {"id": "path_gate", "item": "Stage × allowed-face path gate", "green": False, "detail": "write set missing",
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
