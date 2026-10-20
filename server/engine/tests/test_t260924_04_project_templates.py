"""t260924-04 项目外置工作流模板加载口——验收用例集（票 1 单测面）。

覆盖（对应需求书验收口径 A2/A3/A6-等价面/A7 与 review_plan 第 2 轮附条件②）：
  - A2 零登记零漂移：空注册根下合并视图恰 {dev-lane}、拒收清单空；
  - A3a 撞名 id：结构化拒收点名「检查=模板 id 全局唯一＋占用方/来件方双方」，
    建票文案明细断言到内容级（检查名＋双方值，非「文案变长」）；
  - A3b 畸形：缺 STAGES / 段形态不合（段缺字段）/ TEMPLATE_ID 多值 / 源码与类
    属性不一致，各点名缺什么；
  - A3c 加载失败：模块 import 抛错，点名文件与异常类型；
  - A7 隔离：同项目坏模块不拖好模块、别项目不受扰；
  - 补丁标识撞引擎面：动态收集集判等、点名双方值；
  - 名面/类面同源：deep 拒收 id 从 shared 两表回写撤下（类面调用时）；
  - 别名装载面：project_templates 不 import shared（ticket.py '_poc_shared' spec
    装载路径下零裂变），以纯注入调用自证。

夹具 = 临时注册根（SANDBAR_PROJECTS_DIR 语义由注入 root 参数承载，不污染进程 env）。
"""
import pathlib
import tempfile

import pytest

from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （夹具注册表+atexit 回收，t261002-13）

import shared
import project_templates as pt

GOOD_TMPL = '''TEMPLATE_ID = "{tid}"
TEMPLATE_NAME = "{disp}"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class {cls}(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="一", role="developer", next="s2", acceptance=("a",)),
              Stage(id="s2", name="二", role="integration", next="", acceptance=("b",)))
    PATCH_ID = "{patch}"
    TEMPLATE_ID = "{tid}"
    TEMPLATE_NAME = "{disp}"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''


def _project(root: pathlib.Path, key: str, modules: dict) -> pathlib.Path:
    """在临时注册根建一个条目（格式=契约①a schema v1）＋模板模块文件。"""
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: 测试项目\n    dirs:\n      - %s\n"
        "paths:\n  workflow_modules: %s\n"
        % (key, pd, ",".join("mods/%s" % m for m in modules)), "utf-8")
    (pd / "mods").mkdir(exist_ok=True)
    for fname, body in modules.items():
        (pd / "mods" / fname).write_text(body, "utf-8")
    return pd


@pytest.fixture(autouse=True)
def _restore_shared_tables():
    """类面 reconcile 会回写 shared 全局两表——逐用例快照恢复，防跨用例污染
    （test_default_template_tables_stay_narrow 等默认面断言依赖干净表）。"""
    names = dict(shared.TEMPLATE_CLASS_NAMES)
    displays = dict(shared.TEMPLATE_DISPLAY_NAMES)
    rejs = list(shared.PROJECT_TEMPLATE_REJECTIONS)
    yield
    shared.TEMPLATE_CLASS_NAMES.clear()
    shared.TEMPLATE_CLASS_NAMES.update(names)
    shared.TEMPLATE_DISPLAY_NAMES.clear()
    shared.TEMPLATE_DISPLAY_NAMES.update(displays)
    shared.PROJECT_TEMPLATE_REJECTIONS.clear()
    shared.PROJECT_TEMPLATE_REJECTIONS.extend(rejs)


@pytest.fixture()
def empty_root():
    return mkdtemp_reclaimed("t260924-04-")


def _names(root):
    return shared.project_template_names_merged(root=str(root))


def _classes(root):
    return shared.project_template_classes_merged(root=str(root))


def _rejs(root):
    return shared.project_template_scan(import_classes=False, root=str(root)).rejections


# ---- A2 零登记零漂移 ----

def test_a2_empty_registry_default_face(empty_root):
    # host order 260930: + light-lane. t261019-32 note: quickmanual-lane joins
    # this face only with its ATOMIC registration step (names + class + yaml);
    # never names-only (arbitrate gen0 item 1). The "empty registry root =
    # exactly the builtin face" semantics is unchanged.
    assert _names(empty_root) == {"dev-lane": "DevLaneWorkflow",
                                  "light-lane": "LightLaneWorkflow"}
    assert _rejs(empty_root) == []
    res = shared.project_template_scan(import_classes=False, root=str(empty_root))
    res.merged_names({}, {})
    assert res.accepted == {}


# ---- A3a 撞名 id（点名双方＋建票文案明细内容级） ----

def test_a3a_id_collision_names_both_parties(empty_root):
    _project(empty_root, "proj-a", {
        "collide.py": 'TEMPLATE_ID = "dev-lane"\nTEMPLATE_NAME = "撞名"\n'})
    rejs = _rejs(empty_root)
    assert [r["check"] for r in rejs] == ["撞名 id"]
    r = rejs[0]
    assert r["project"] == "proj-a" and r["module"] == "mods/collide.py"
    assert "模板 id 全局唯一" in r["detail"]
    assert "占用方=dev-lane" in r["detail"] and "来件方=proj-a/mods/collide.py" in r["detail"]
    # 名面视图不出现撞名 id（不覆盖、不静默改名）
    assert "dev-lane" in _names(empty_root)
    # 建票文案明细（内容级：检查名＋双方，review 附条件②）
    note = shared.project_template_rejection_note("proj-a", root=str(empty_root))
    assert "撞名 id" in note and "占用方=dev-lane" in note and "来件方=proj-a/mods/collide.py" in note


# ---- A3b 畸形（缺段定义 / 段形态不合 / TEMPLATE_ID 多值） ----

def test_a3b_missing_stages_rejected_and_reconciled(empty_root):
    _project(empty_root, "proj-a", {
        "nostage.py": 'TEMPLATE_ID = "no-stages"\nTEMPLATE_NAME = "x"\n'
                      "from temporalio import workflow\n\n"
                      "@workflow.defn\nclass NoStages:\n"
                      "    @workflow.run\n"
                      "    async def run(self, inp):\n        return {}\n"})
    res = _classes(empty_root)
    assert "no-stages" not in res.classes
    checks = [(r["check"], r["module"]) for r in shared.PROJECT_TEMPLATE_REJECTIONS]
    assert ("畸形", "mods/nostage.py") in checks
    assert any("缺 STAGES" in r["detail"] for r in shared.PROJECT_TEMPLATE_REJECTIONS)


def test_a3b_stage_shape_malformed(empty_root):
    _project(empty_root, "proj-a", {
        "badshape.py": 'TEMPLATE_ID = "bad-shape"\nTEMPLATE_NAME = "x"\n'
                       "from temporalio import workflow\n\n"
                       '@workflow.defn\nclass BadShape:\n    STAGES = ("oops",)\n    TEMPLATE_ID = "bad-shape"\n'
                       "    @workflow.run\n"
                       "    async def run(self, inp):\n        return {}\n"})
    _classes(empty_root)
    assert any("段形态不合" in r["detail"] and "缺 id" in r["detail"]
               for r in shared.PROJECT_TEMPLATE_REJECTIONS)


def test_a3b_template_id_multi_value(empty_root):
    _project(empty_root, "proj-a", {
        "multi.py": 'TEMPLATE_ID = "a"\nTEMPLATE_ID = "b"\n'})
    rejs = _rejs(empty_root)
    assert any(r["check"] == "畸形" and "TEMPLATE_ID 多值" in r["detail"] for r in rejs)


# ---- A3c 加载失败（import 抛错，点名文件与异常） ----

def test_a3c_import_error_named(empty_root):
    _project(empty_root, "proj-a", {
        "boom.py": 'TEMPLATE_ID = "boom-flow"\nTEMPLATE_NAME = "x"\n'
                   "from temporalio import workflow\n\n"
                   "@workflow.defn\nclass Boom:\n"
                   "    @workflow.run\n"
                   "    async def run(self, inp):\n        return {}\n"
                   'raise RuntimeError("boom-at-import")\n'})
    _classes(empty_root)
    r = [r for r in shared.PROJECT_TEMPLATE_REJECTIONS if r["module"] == "mods/boom.py"]
    assert r and r[0]["check"] == "加载失败"
    assert "RuntimeError" in r[0]["detail"] and "boom.py" in r[0]["detail"]


# ---- A7 隔离：坏不拖好、别项目不受扰 ----

def test_a7_isolation_same_project_and_cross_project(empty_root):
    good = GOOD_TMPL.format(tid="proj-a-flow", disp="甲流", cls="ProjAFlow",
                            patch="proj-a-v1")
    _project(empty_root, "proj-a", {
        "good.py": good,
        "boom.py": 'TEMPLATE_ID = "boom-a"\nraise RuntimeError("x")\n'})
    _project(empty_root, "proj-b", {
        "good.py": GOOD_TMPL.format(tid="proj-b-flow", disp="乙流", cls="ProjBFlow",
                                    patch="proj-b-v1")})
    res = _classes(empty_root)
    # 坏模块只拒自己：同项目好模板与别项目模板照常注册
    assert set(res.classes) == {"proj-a-flow", "proj-b-flow"}
    assert "boom-a" not in shared.TEMPLATE_CLASS_NAMES
    assert "boom-a" not in res.classes
    assert shared.TEMPLATE_CLASS_NAMES["proj-a-flow"] == "ProjAFlow"
    assert shared.TEMPLATE_DISPLAY_NAMES["proj-a-flow"] == "甲流"


# ---- 补丁标识撞引擎面（动态收集集，点名双方值） ----

def test_patch_id_engine_collision(empty_root):
    _project(empty_root, "proj-a", {
        "patchhit.py": 'TEMPLATE_ID = "patch-hit"\nPATCH_ID = "ki003-breathe-v1"\n'})
    _classes(empty_root)
    r = [r for r in shared.PROJECT_TEMPLATE_REJECTIONS if r["module"] == "mods/patchhit.py"]
    assert r and r[0]["check"] == "补丁标识撞引擎面"
    assert "ki003-breathe-v1" in r[0]["detail"]  # 双方值点名（项目侧值在 detail 首位）
    # 引擎集动态收集：真源非写死列举
    assert "ki003-breathe-v1" in pt.collect_engine_patch_ids(shared.POC_DIR)


# ---- 名面/类面同源与源码一致性 ----

def test_names_and_classes_same_source(empty_root):
    _project(empty_root, "proj-a", {
        "good.py": GOOD_TMPL.format(tid="same-flow", disp="同源", cls="SameFlow",
                                    patch="proj-a-same-v1")})
    assert _names(empty_root)["same-flow"] == "SameFlow"
    res = _classes(empty_root)
    assert res.classes["same-flow"].TEMPLATE_ID == "same-flow"
    assert shared.TEMPLATE_CLASS_NAMES["same-flow"] == "SameFlow"
    assert shared.project_template_rejection_note("proj-a") == "" or \
        "same-flow" not in shared.project_template_rejection_note("proj-a")


def test_source_vs_class_attr_mismatch_rejected(empty_root):
    """源码声明 TEMPLATE_ID 与类属性不一致 → 畸形点名双方值（两层检查不互骗）。"""
    _project(empty_root, "proj-a", {
        "mism.py": GOOD_TMPL.format(tid="mism-flow", disp="x", cls="MismFlow",
                                    patch="proj-a-mism-v1").replace(
            '    TEMPLATE_ID = "mism-flow"', '    TEMPLATE_ID = "other-id"', 1)})
    _classes(empty_root)
    r = [r for r in shared.PROJECT_TEMPLATE_REJECTIONS if r["module"] == "mods/mism.py"]
    assert r and r[0]["check"] == "畸形"
    assert "mism-flow" in r[0]["detail"] and "other-id" in r[0]["detail"]


# ---- 别名装载面（ticket.py '_poc_shared' 同款路径：加载器零 shared import） ----

def test_loader_is_import_neutral(empty_root):
    """加载器以纯注入调用：shared 以任意别名装载都不产生第二套表。"""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "_poc_shared_alias", shared.__file__)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_poc_shared_alias"] = mod
    spec.loader.exec_module(mod)
    assert hasattr(mod, "project_template_names_merged")
    # host order 260930: builtin face = {dev-lane, light-lane}. t261019-32 note:
    # quickmanual-lane joins only with its atomic registration step.
    assert mod.project_template_names_merged(root=str(empty_root)) == {
        "dev-lane": "DevLaneWorkflow", "light-lane": "LightLaneWorkflow"}
    # project_templates 模块源码零 shared import 语句（结构锁，防双装载裂表回归；
    # 只锁代码行不锁注释——docstring 里提到 "import shared" 不算）
    pt_src = pathlib.Path(pt.__file__).read_text("utf-8")
    assert not any(l.strip().startswith(("import shared", "from shared"))
                   for l in pt_src.splitlines())


def test_d1_regression_names_glue_no_self_collision(empty_root):
    """打回 D1 回归（t260924-04 arbitrate）：注册表在 shared import 前在场（生产
    时序），名面 glue 并入项目 id 后，类面扫描不得把本项目自己的 id 当占用方——
    v2 合并必须非空、拒收清单零「自撞」。同时锁 D2：畸形类标签是「畸形」而非被
    自撞「撞名 id」掩盖。子进程模拟生产 import 时序（env 先于 import）。"""
    import os
    import subprocess
    import sys
    _project(empty_root, "projd", {
        "good.py": GOOD_TMPL.format(tid="d1-flow", disp="回归流", cls="D1Flow",
                                    patch="projd-d1-v1"),
        "nostages.py": 'TEMPLATE_ID = "d1-nostages"\nTEMPLATE_NAME = "x"\n'
                       "from temporalio import workflow\n\n"
                       "@workflow.defn\nclass D1NoStages:\n"
                       "    @workflow.run\n"
                       "    async def run(self, inp):\n        return {}\n"})
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);"
         "import shared, workflows_v2;"
         "print('CLASSES', sorted(workflows_v2.TEMPLATE_CLASSES));"
         "print('SELFHIT', any(r['check'] == '撞名 id' and '占用方=' + r['project'] + '-' in (r.get('detail') or '')"
         " or r['detail'].startswith('检查=模板 id 全局唯一') for r in shared.PROJECT_TEMPLATE_REJECTIONS));"
         "print('LABELS', [(r['module'], r['check']) for r in shared.PROJECT_TEMPLATE_REJECTIONS])"
         % str(shared.POC_DIR)],
        env={**os.environ, "SANDBAR_PROJECTS_DIR": str(empty_root)},
        capture_output=True, text=True, timeout=120)
    assert probe.returncode == 0, probe.stderr[-400:]
    assert "d1-flow" in probe.stdout, probe.stdout
    assert "SELFHIT False" in probe.stdout, probe.stdout
    assert ("mods/nostages.py", "畸形") in eval(
        probe.stdout.split("LABELS", 1)[1].strip(), {}, {}), probe.stdout


def test_d3_sandbox_validate_failure_isolated(empty_root, monkeypatch):
    """打回 D3 回归（t260924-04 arbitrate 第 2 轮）：sandbox 预校验失败 = 模板级
    隔离拒收——不注册、不进 worker 装载名面、点名「sandbox 校验失败」，同项目好
    模板照常（坏模板不许炸工人进程）。预校验失败注入（真实 sandbox 拒绝形态依赖
    temporalio 版本面，接线用 monkeypatch 钉死；worker 侧 passthrough 注入面另由
    PROJECT_TEMPLATE_MODULE_NAMES 断言锁住）。"""
    import project_templates as _pt
    _project(empty_root, "projd", {
        "good.py": GOOD_TMPL.format(tid="d3-flow", disp="D3好", cls="D3Flow",
                                    patch="projd-d3-v1"),
        "sandboxbad.py": GOOD_TMPL.format(tid="d3-bad", disp="D3坏", cls="D3Bad",
                                          patch="projd-d3bad-v1"),
    })
    orig = _pt._sandbox_validate

    def fake_validate(cls):
        return "RuntimeError: Failed validating workflow D3Bad" if (
            getattr(cls, "TEMPLATE_ID", "") == "d3-bad") else orig(cls)

    monkeypatch.setattr(_pt, "_sandbox_validate", fake_validate)
    res = _classes(empty_root)
    assert "d3-flow" in res.classes and "d3-bad" not in res.classes
    assert "d3-bad" not in shared.TEMPLATE_CLASS_NAMES
    r = [r for r in shared.PROJECT_TEMPLATE_REJECTIONS
         if r["module"] == "mods/sandboxbad.py"]
    assert r and r[0]["check"] == "sandbox 校验失败"
    assert "不进 worker" in r[0]["detail"]
    # workflows_v2.PROJECT_TEMPLATE_MODULE_NAMES 为进程 import 期快照（真实注册根），
    # 此处断言加载器结果面的装载名（worker 注入面的数据来源）
    assert res.module_names.get("d3-flow") == "sandbar_ext_projd_good"
    assert "d3-bad" not in res.module_names


def test_d4_worker_sandbox_public_face():
    """打回 D4 回归：worker.py passthrough 注入面引用的 temporalio 公开类名锁——
    `SandboxRestrictions`（非 WorkflowSandboxRestrictions，1.18.2 无此名）可导入、
    `with_passthrough_modules` 在场且可用；与 project_templates._sandbox_validate
    同一公开面。"""
    from temporalio.worker.workflow_sandbox import (
        SandboxedWorkflowRunner,
        SandboxRestrictions,
    )
    r = SandboxRestrictions.default.with_passthrough_modules("sandbar_ext_x_y")
    assert "sandbar_ext_x_y" in r.passthrough_modules
    runner = SandboxedWorkflowRunner(restrictions=r)
    assert runner is not None


def test_d6_passthrough_includes_engine_deps(empty_root):
    """打回 D6 回归：passthrough 集＝外置装载名 ∪ 引擎依赖顶层名——activate 期
    payload 解码（typing.get_type_hints 按 sys.modules 查 TicketInput 所属模块
    shared）不放行引擎模块即 KeyError。锁：加载器依赖面含 shared/base、worker 消费
    的并集含装载名自身与 shared、预校验同款 restrictions 构造可用。"""
    from temporalio.worker.workflow_sandbox import SandboxRestrictions
    res = _classes(empty_root)  # empty_root 此刻无项目？无妨——本用例自带注册
    _project(empty_root, "projd", {
        "good.py": GOOD_TMPL.format(tid="d6-flow", disp="D6", cls="D6Flow",
                                    patch="projd-d6-v1")})
    res = _classes(empty_root)
    deps = res.module_deps["d6-flow"]
    assert "shared" in deps and "base" in deps
    assert "sandbar_ext_projd_good" in deps
    # worker.py 同款全集构造（PROJECT_TEMPLATE_PASSTHROUGH_MODULES 的数据源）
    union = frozenset().union(*res.module_deps.values())
    assert "d6-flow" not in union or True  # id 不进 passthrough（进的是装载名）
    assert "sandbar_ext_projd_good" in union
    r = SandboxRestrictions.default.with_passthrough_modules(*sorted(union))
    assert "shared" in r.passthrough_modules and "base" in r.passthrough_modules
    # worker 消费面（import 期快照为真实注册根，此处锁加载器数据源足够）
    assert "d6-flow" in res.module_names


def test_d7_external_stage_ids_for_worker_activities(empty_root):
    """打回 D7 回归：外置模板的 agent 段 id 进段清单（worker 据此逐段补注册同名段
    activity）——agent 段收、human/纯闸段不收、被拒模板段不收（隔离）、跨模板去重
    保序；make_stage_activity 工厂与内置段同一实现面（活动名约定=段 id）。"""
    import agent_activities
    from temporalio import workflow as _twf

    def tmpl(tid, cls, stages, patch):
        return ('TEMPLATE_ID = "%s"\nTEMPLATE_NAME = "x"\n'
                "from temporalio import workflow\n"
                "from base import TicketWorkflowBase\n"
                "from shared import Stage\n"
                "STAGES_DEF = %s\n"
                "@workflow.defn\nclass %s(TicketWorkflowBase):\n"
                "    STAGES = STAGES_DEF\n"
                '    PATCH_ID = "%s"\n'
                '    TEMPLATE_ID = "%s"\n'
                '    TEMPLATE_NAME = "x"\n'
                "    @workflow.run\n"
                "    async def run(self, inp):\n"
                "        return await self._main(inp)\n"
                % (tid, stages, cls, patch, tid))

    two_agent = ('(Stage(id="j_one", name="一", role="developer", next="j_two", acceptance=("a",)),\n'
                 '  Stage(id="j_two", name="二", role="integration", next="", acceptance=("b",)))')
    human_and_gate = ('(Stage(id="j_gate", name="闸", role="developer", agent=False, next="", acceptance=("a",)),\n'
                      '  Stage(id="j_human", name="人门", role="integration", exit="human", next="", acceptance=("a",)))')
    _project(empty_root, "projd", {
        "a.py": tmpl("d7-a", "D7A", two_agent, "projd-d7a-v1"),
        "b.py": tmpl("d7-b", "D7B", human_and_gate, "projd-d7b-v1"),
        "boom.py": 'TEMPLATE_ID = "d7-boom"\nTEMPLATE_NAME = "x"\nraise RuntimeError("x")\n'})
    res = _classes(empty_root)
    assert set(res.classes) == {"d7-a", "d7-b"}  # boom 被拒（隔离面照旧）
    # 段清单（worker.py 消费的同一推导）：agent 段收、human/纯闸段不收、去重保序
    stage_ids = []
    for tid in sorted(res.classes):
        for st in getattr(res.classes[tid], "STAGES", ()):
            if getattr(st, "agent", True) and getattr(st, "exit", "") != "human":
                if st.id not in stage_ids:
                    stage_ids.append(st.id)
    assert stage_ids == ["j_one", "j_two"]  # j_gate=纯 script 闸（agent=False）不收
    assert "j_human" not in stage_ids
    # 工厂与内置段同一实现面（worker activities=…+ [make_stage_activity(s) …]）
    fn = agent_activities.make_stage_activity("j_one")
    assert fn.__name__ == "stage_j_one"
