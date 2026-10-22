#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_project_template_gate.py — 项目外置工作流模板：登记即加载＋逐模板隔离拒收（t260924-04 场景①）。

intent（用户可感知行为，登记于 run_scenarios.py SCENARIOS）：
- A2 零登记零漂移：项目未声明 workflow_modules → 引擎模板可用面恰 {dev-lane}、
  拒收清单为空（「不声明=零行为变化」做成默认态）；
- A3a 撞名 id：项目模板撞内置 id（dev-lane）→ 结构化拒收点名「检查失败项＋占用方＋
  来件方（项目/模块）」，注册表不被后到覆盖（dev-lane 仍指内置类）、不静默改名；
- A3b 畸形：类缺 STAGES / STAGES 形态不合 → 拒收点名缺什么/哪不合，不注册；
- A3c 加载失败＋隔离：模块 import 抛错 → 拒收点名「模块加载失败＋文件＋异常」，
  同项目另一好模板照常注册、另一项目完全不受扰（坏不拖好）；
- 补丁标识纪律：项目模板 PATCH_ID 撞引擎内置补丁标识集 → 拒收点名双方值；
  带 <项目key>- 前缀的 PATCH_ID 正常注册（引擎集动态收集，不写死）；
- 夹具门语义不动：SANDBAR_FIXTURE_TEMPLATES 未设时夹具模板不可见；设了且项目模板
  撞夹具 id → 夹具先占、项目模板拒收点名（内置∪夹具先占，项目后到）；
- 同门同源：登记成功的外置 id 同时出现在 shared.TEMPLATE_CLASS_NAMES /
  TEMPLATE_DISPLAY_NAMES 与 workflows_v2.TEMPLATE_CLASSES / ALL_WORKFLOWS_V2；
- 加载口文档面：加载口文档在册且含确定性规约/演进两纪律/生效粒度写实关键词；
  建票入口（ticket.py）未知模板文案带拒收明细语义锚。

灰盒声明：经子进程探针只读公开真源表（shared/workflows_v2/project_templates 的
公开属性），拒收记录按 JSON 全文语义锚匹配（不锚字段名/文案全句，KI-051 纪律）；
不 import 引擎内部私有结构、不触 3099、零网络零真 Temporal。

三态（README §执行契约）：探针所需引擎解释器缺 temporalio＝ENV_FAIL exit 2；
断言破面＝exit 1。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
from lib_gate import Fail, poc_python, require_bench  # noqa: E402
sys.path.insert(0, INTEG)
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit）

ENGINE = os.path.join(REPO, "server", "engine")
LOAD_DOC = os.path.join(REPO, "docs", "design", "project-external-workflow-template-loader-v1.md")
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")

# 语义锚（不锚字段名与全句文案，KI-051：锚语义优先）
COLLIDE_ANCHORS = ("撞名", "dev-lane")          # 检查失败项 + 占用方
MALFORMED_ANCHORS = ("STAGES",)                  # 缺什么
LOADFAIL_ANCHORS = ("加载失败",)                 # 哪类检查
PATCH_ANCHORS = ("补丁", "dev-lane-review-gate")  # 检查项 + 双方之一
GOOD_ID = "projx-good"
GOOD_MODULE = '''"""好模板夹具：最小两段外置模板（clean-module：只 import + 类定义）。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "projx-good"


@workflow.defn
class ProjxGoodWorkflow(TicketWorkflowBase):
    STAGES = (
        Stage(id="p_one", name="段一", role="developer", next="p_two",
              acceptance=("段一完成",)),
        Stage(id="p_two", name="段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "projx-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "projx 好模板"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "t260924-04 集成夹具"

    @workflow.run
    async def run(self, inp: TicketInput):
        return await self._main(inp)
'''
COLLIDE_MODULE = GOOD_MODULE.replace('TEMPLATE_ID = "projx-good"',
                                     'TEMPLATE_ID = "dev-lane"') \
    .replace("ProjxGoodWorkflow", "ProjxCollideWorkflow") \
    .replace("projx 好模板", "projx 撞名夹具")
NO_STAGES_MODULE = GOOD_MODULE.replace("ProjxGoodWorkflow", "ProjxNoStagesWorkflow") \
    .replace('TEMPLATE_ID = "projx-good"', 'TEMPLATE_ID = "projx-nostages"')
import re as _re
# 缺 STAGES：整块删除段定义（非贪婪到段块收尾「    ）」，避免半删造成语法错——
# 语法错会被归为「加载失败」而非「缺 STAGES」，畸形归因就失真了。
NO_STAGES_MODULE = _re.sub(r"    STAGES = \(.*?\n    \)\n", "",
                           GOOD_MODULE.replace(
                               "ProjxGoodWorkflow", "ProjxNoStagesWorkflow").replace(
                               'TEMPLATE_ID = "projx-good"',
                               'TEMPLATE_ID = "projx-nostages"'),
                           flags=_re.S)
BAD_SHAPE_MODULE = GOOD_MODULE.replace("ProjxGoodWorkflow", "ProjxBadShapeWorkflow") \
    .replace('TEMPLATE_ID = "projx-good"', 'TEMPLATE_ID = "projx-badshape"') \
    .replace('STAGES = (', 'STAGES = ("not-a-stage", #"').replace(
        'Stage(id="p_one"', ')  #\n        Stage(id="p_one"')
BROKEN_MODULE = '''from temporalio import workflow\nTEMPLATE_ID = "projx-broken"\n@workflow.defn\nclass ProjxBrokenWorkflow:\n    @workflow.run\n    async def run(self, inp):\n        return inp\nraise RuntimeError("t260924-04 夹具：模块加载即炸")\n'''
BAD_PATCH_MODULE = GOOD_MODULE.replace("ProjxGoodWorkflow", "ProjxBadPatchWorkflow") \
    .replace('TEMPLATE_ID = "projx-good"', 'TEMPLATE_ID = "projx-badpatch"') \
    .replace('PATCH_ID = "projx-v1"', 'PATCH_ID = "dev-lane-review-gate"')
FIXTURE_COLLIDE_MODULE = GOOD_MODULE.replace("ProjxGoodWorkflow", "ProjxFixCollideWorkflow") \
    .replace('TEMPLATE_ID = "projx-good"', 'TEMPLATE_ID = "fixture-two-step"')

PROBE = r'''#!/usr/bin/env python3
"""t260924-04 场景①只读探针：登记 face + 拒收清单 + （PROBE_FULL=1 时）v2 合并面。

读面次序契约：PROBE_FULL=1 时**先 import workflows_v2（触发类面合并与 reconcile
回写）再快照 shared 两表**——名面 glue 先并入、类面深检撤下，次序反了会把「待撤
下」的 id 误读成已注册（tests-fault 实录：arbitrate gen0 修正）。"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.environ["PROBE_ENGINE"])
import shared  # noqa: E402
try:
    import project_templates as _pt  # noqa: E402
except Exception:
    _pt = None
if os.environ.get("PROBE_FULL") == "1":
    import workflows_v2  # noqa: E402


def ser(r):
    if isinstance(r, dict):
        return {k: str(v) for k, v in r.items()}
    try:
        return dataclasses.asdict(r)
    except Exception:
        return {"repr": str(r)}


rej = getattr(shared, "PROJECT_TEMPLATE_REJECTIONS", None)
if rej is None and _pt is not None:
    rej = getattr(_pt, "PROJECT_TEMPLATE_REJECTIONS", [])
out = {
    "names": dict(shared.TEMPLATE_CLASS_NAMES),
    "display": sorted(shared.TEMPLATE_DISPLAY_NAMES),
    "rejections": [ser(r) for r in (rej or [])],
}
if os.environ.get("PROBE_FULL") == "1":
    out["classes"] = sorted(workflows_v2.TEMPLATE_CLASSES)
    out["all_wf"] = sorted(c.__name__ for c in workflows_v2.ALL_WORKFLOWS_V2)
print(json.dumps(out, ensure_ascii=False))
'''


def write_project(root, key, modules, fixture_env=False):
    """写一个项目注册条目（project.yaml paths.workflow_modules）＋其模块文件。

    返回 (registry_dir, 模块相对路径 CSV)。modules=[(relpath, 文本), ...]。"""
    pdir = os.path.join(root, key)
    mods_dir = os.path.join(pdir, "wf_mods")
    os.makedirs(mods_dir, exist_ok=True)
    rels = []
    for rel, text in modules:
        with open(os.path.join(pdir, rel), "w", encoding="utf-8") as f:
            f.write(text)
        rels.append(rel)
    with open(os.path.join(pdir, "project.yaml"), "w", encoding="utf-8") as f:
        f.write("# fixture-local registry（t260924-04 场景①）\n"
                "schema: v1\nproject:\n  - key: %s\n    name: %s\n"
                "    dirs:\n      - %s\n"
                "paths:\n  workflow_modules: %s\n"
                % (key, key, pdir, ",".join(rels)))
    return root, ",".join(rels)


def run_probe(py, registry, full=False, fixture_env=False):
    """子进程只读探针。返回 (rc, out)。解释器缺 temporalio（full 时）由调用方判 ENV_FAIL。"""
    env = dict(os.environ)
    env.pop("SANDBAR_FIXTURE_TEMPLATES", None)
    env["SANDBAR_PROJECTS_DIR"] = registry
    env["PROBE_ENGINE"] = ENGINE
    env["PYTHONPYCACHEPREFIX"] = os.path.join(tempfile.gettempdir(), "t26092404-pyc")
    if full:
        env["PROBE_FULL"] = "1"
    if fixture_env:
        env["SANDBAR_FIXTURE_TEMPLATES"] = "1"
    probe = os.path.join(str(mkdtemp_reclaimed("t26092404-probe-")), "probe.py")
    with open(probe, "w", encoding="utf-8") as f:
        f.write(PROBE)
    p = subprocess.run([py, probe], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_probe(out):
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


def main():
    fail = Fail("t260924-04 场景①：项目外置模板登记即加载＋逐模板隔离拒收")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = str(mkdtemp_reclaimed("t26092404-gate-"))

    # ---- 探针环境可用性（temporalio 缺=ENV_FAIL exit 2，绝不 exit 0 假绿）----
    rc, out = run_probe(py, os.path.join(tmp, "empty-registry-probe"), full=True)
    if rc != 0 and "temporalio" in out:
        fail.bail("ENV_FAIL: 引擎解释器缺 temporalio（%s）——合并面子用例无法执行" % py, 2)
    if rc != 0:
        fail.bail("探针本身不可跑（rc=%s out尾=%s）——加载口/探针契约未交付或环境异常"
                  % (rc, out[-200:]), 1)

    # ---- L0 自证红绿（探针判定器本身会红绿，非恒绿桩）----
    good_registry = os.path.join(tmp, "regA")
    write_project(good_registry, "projx", [("good.py", GOOD_MODULE)])
    base = parse_probe(run_probe(py, good_registry, full=True)[1])
    empty = parse_probe(run_probe(py, os.path.join(tmp, "empty2"))[1])
    fail.check(base.get("names") != empty.get("names"),
               "L0 自证红：登记项目与空注册表的可用面实况不同（探针非恒绿桩）")
    fail.check(GOOD_ID in (base.get("names") or {}),
               "L0 自证绿：好模板 id 进入可用面（实得 %r)" % (base.get("names"),))

    # ---- A2 零登记零漂移 ----
    empty = parse_probe(run_probe(py, os.path.join(tmp, "emptyA"), full=True)[1])
    # 宿主令 260930：内置面加一格 light-lane（轻道泳道，宿主定案）——「空注册根=恰为
    # 内置面全集、零外置漂移」的语义不变；退役模板复活仍必红。
    # 261022: quickmanual-lane registered (host order 261022) => builtin face is three.
    fail.check(empty.get("names") == {"dev-lane": "DevLaneWorkflow",
                                      "light-lane": "LightLaneWorkflow",
                                      "quickmanual-lane": "QuickmanualLaneWorkflow"},
               "A2 零登记：可用面恰 {dev-lane, light-lane, quickmanual-lane}（实得 %r）"
               % (empty.get("names"),))
    fail.check(sorted(empty.get("display") or []) == ["dev-lane", "light-lane", "quickmanual-lane"],
               "A2 零登记：展示名恰 {dev-lane, light-lane}（实得 %r）"
               % (empty.get("display"),))
    fail.check(empty.get("rejections") == [],
               "A2 零登记：拒收清单为空（实得 %r）" % (empty.get("rejections"),))
    # all_wf keeps the two legacy v2 classes: quickmanual registers on the template
    # face and the legacy worker list, never twice (two classes of one name break the
    # replayer's whole-set validation).
    fail.check(sorted(empty.get("classes") or []) == ["dev-lane", "light-lane", "quickmanual-lane"]
               and sorted(empty.get("all_wf") or [])
               == ["DevLaneWorkflow", "LightLaneWorkflow"],
               "A2 零登记：v2 合并面恰内置两模板（实得 classes=%r all=%r）"
               % (empty.get("classes"), empty.get("all_wf")))

    # ---- A3a 撞名 id：点名双方、不覆盖、不静默改名 ----
    reg_c = os.path.join(tmp, "regC")
    write_project(reg_c, "projc", [("collide.py", COLLIDE_MODULE)])
    rc, out = run_probe(py, reg_c, full=True)
    c = parse_probe(out)
    blob = json.dumps(c, ensure_ascii=False)
    fail.check(all(a in blob for a in COLLIDE_ANCHORS),
               "A3a 拒收点名检查项＋占用方 dev-lane（blob 含锚）")
    fail.check("projc" in blob and "collide.py" in blob,
               "A3a 拒收点名来件方（项目/模块）")
    fail.check(c.get("names", {}).get("dev-lane") == "DevLaneWorkflow",
               "A3a 不后到覆盖：dev-lane 仍指内置类")
    fail.check(GOOD_ID not in c.get("names", {}),
               "A3a 不静默改名：撞名来件未以改名形式混入可用面")

    # ---- A3b 畸形：缺 STAGES / 形态不合 ----
    reg_d = os.path.join(tmp, "regD")
    write_project(reg_d, "projd", [("nostages.py", NO_STAGES_MODULE),
                                   ("badshape.py", BAD_SHAPE_MODULE)])
    d = parse_probe(run_probe(py, reg_d, full=True)[1])
    blob = json.dumps(d, ensure_ascii=False)
    fail.check("projx-nostages" not in d.get("names", {})
               and "projx-badshape" not in d.get("names", {}),
               "A3b 畸形模板不注册（实得 %r)" % (sorted(d.get("names", {})),))
    fail.check("STAGES" in blob, "A3b 缺 STAGES 点名缺什么")
    fail.check(all(a in blob for a in ("projd",)),
               "A3b 点名来件项目")

    # ---- A3c 加载失败＋逐模板隔离（坏不拖好、别项目不受扰）----
    reg_e = os.path.join(tmp, "regE")
    write_project(reg_e, "proje", [("broken.py", BROKEN_MODULE),
                                   ("good2.py", GOOD_MODULE.replace(
                                       'TEMPLATE_ID = "projx-good"',
                                       'TEMPLATE_ID = "proje-good2"').replace(
                                       "ProjxGoodWorkflow", "ProjeGood2Workflow"))])
    e = parse_probe(run_probe(py, reg_e, full=True)[1])
    blob = json.dumps(e, ensure_ascii=False)
    fail.check("proje-good2" in e.get("names", {}),
               "A3c 同项目好模板照常注册（坏不拖好）")
    fail.check(all(a in blob for a in LOADFAIL_ANCHORS) and "broken.py" in blob,
               "A3c 拒收点名「加载失败＋模块文件」")
    fail.check("RuntimeError" in blob or "异常" in blob or "错误" in blob,
               "A3c 点名异常（类型或语义）")
    reg_f = os.path.join(tmp, "regF")
    write_project(reg_f, "projf", [("fine.py", GOOD_MODULE.replace(
        'TEMPLATE_ID = "projx-good"', 'TEMPLATE_ID = "projf-fine"').replace(
        "ProjxGoodWorkflow", "ProjfFineWorkflow"))])
    f_ = parse_probe(run_probe(py, reg_f, full=True)[1])
    fail.check("projf-fine" in f_.get("names", {}),
               "A3c 别项目（坏项目之外）不受扰，自身登记照常生效")

    # ---- 补丁标识纪律：撞引擎集拒收点名双方；项目前缀放行 ----
    reg_g = os.path.join(tmp, "regG")
    write_project(reg_g, "projg", [("badpatch.py", BAD_PATCH_MODULE)])
    g = parse_probe(run_probe(py, reg_g, full=True)[1])
    blob = json.dumps(g, ensure_ascii=False)
    fail.check("projx-badpatch" not in g.get("names", {}),
               "补丁标识撞引擎集：该模板不注册")
    fail.check(all(a in blob for a in PATCH_ANCHORS),
               "补丁标识拒收点名检查项＋引擎侧标识值")
    fail.check("projx-v1" not in json.dumps(base.get("rejections") or [], ensure_ascii=False),
               "项目前缀 PATCH_ID（projx-v1）不被引擎集误拒（L0 注册面零拒收）")

    # ---- 夹具门语义不动＋撞夹具 id：夹具先占、项目后到拒收 ----
    nf = parse_probe(run_probe(py, good_registry, full=True, fixture_env=False)[1])
    fail.check("fixture-two-step" not in nf.get("names", {}),
               "夹具门未设 env：夹具模板不可见（语义不动）")
    wf = parse_probe(run_probe(py, good_registry, full=True, fixture_env=True)[1])
    fail.check("fixture-two-step" in wf.get("names", {}),
               "夹具门 env=1：夹具模板在册（t260908-01 语义保持）")
    reg_h = os.path.join(tmp, "regH")
    write_project(reg_h, "projh", [("fixcollide.py", FIXTURE_COLLIDE_MODULE)])
    h = parse_probe(run_probe(py, reg_h, full=True, fixture_env=True)[1])
    blob = json.dumps(h, ensure_ascii=False)
    fail.check(all(a in blob for a in ("fixture-two-step", "projh")),
               "撞夹具 id：拒收点名双方（夹具先占、项目后到）")
    fail.check(h.get("names", {}).get("fixture-two-step") == "FixtureTwoStepWorkflow",
               "撞夹具 id：夹具注册不被覆盖")

    # ---- 同门同源：外置 id 四表同现、类名一致 ----
    # 宿主令 260930：内置面 = {dev-lane, light-lane}（轻道登记令）——「外置 id 与内置
    # 四表同现」的语义不变，期望里补上新增的内置 id。
    fail.check(sorted(base.get("display") or [])
               == sorted(["dev-lane", "light-lane", "quickmanual-lane", GOOD_ID]),
               "同门：TEMPLATE_DISPLAY_NAMES 含外置 id（实得 %r）"
               % (base.get("display"),))
    fail.check(GOOD_ID in base.get("classes", []),
               "同源：workflows_v2.TEMPLATE_CLASSES 含外置 id")
    fail.check("ProjxGoodWorkflow" in base.get("all_wf", []),
               "同源：ALL_WORKFLOWS_V2 含外置类")

    # ---- 加载口文档面（确定性规约/演进两纪律/生效粒度写实）----
    if not os.path.isfile(LOAD_DOC):
        fail.check(False, "加载口文档在册：%s" % LOAD_DOC)
    else:
        doc = open(LOAD_DOC, encoding="utf-8").read()
        # 260928（docs 英文化）：文档锚改英文字面（判据不变=条款仍在文档里）
        for anchor, label in (("Determinism", "确定性编码规约"),
                              ("new template id", "段序变更=新 id 并存"),
                              ("workflow.patched", "分支变更=补丁标记"),
                              ("project", "补丁标识带项目前缀"),
                              ("restart", "生效粒度写实")):
            fail.check(anchor in doc, "加载口文档含%s（锚 %r）" % (label, anchor))

    # ---- 建票入口文案面：ticket.py 未知模板文案带可用面/拒收语义锚 ----
    tp = open(TICKET_PY, encoding="utf-8").read()
    fail.check("拒收" in tp or "rejections" in tp.lower(),
               "ticket.py 建票入口接拒收明细（语义锚在场）")

    fail.finish()


if __name__ == "__main__":
    main()
