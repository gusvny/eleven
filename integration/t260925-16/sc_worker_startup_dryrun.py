#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_worker_startup_dryrun.py — KI-121 集成场景：外置模板段 id 撞引擎活动名时，工人启动面 fail-loud 点名、不裸崩（t260925-16 场景①）。

背景（KI-121 实证机制，与票面「双导入」假说不同）：外置模板的段 id（如事故版
nusuyou content_studio 的 `ai-review`）撞引擎为历史回放保留的退役活动名
（agent_activities 的 propose/process/ai-review/publish），同名活动被组装两份，
temporalio 注册期抛裸 ValueError → 中央工人起不来、共享队列无 poller。

intent（用户可感知行为，登记于 run_scenarios.py SCENARIOS）：
- A1 干净声明可启动：项目声明 cs- 前缀段 id 的外置模板 → 工人启动 dry-run
  绿（exit 0 + 一行 JSON 摘要），组合注册表零同名活动；
- A2 撞名声明 fail-loud：段 id 撞引擎活动名 → dry-run 红（exit 1）且文案点名
  活动名＋双方来源（引擎侧 agent_activities × 来件项目/模块）——永不再是
  temporalio 裸 ValueError（裸崩无名点）也不静默放行；
- A3 加载期拒收：撞名模板在加载口即被整模板拒收、拒收记录点名双方；同项目
  兄弟好模板照常注册（坏不拖好）；组合注册表因此零重复（防线下移到加载期，
  不靠注册期崩）；
- A4 模块身份面：引擎模块（agent_activities）在加载前后保持单一 sys.modules
  身份；拒收后无项目侧半态模块残留（坏模块不留注册垃圾）；
- A5 幂等：dry-run 连跑两遍判定一致（可作巡检/闸反复执行的机械探针）。

灰盒声明：只触公开面（dry-run CLI 的 exit code/stdout 摘要、shared/workflows_v2
公开真源表、temporalio 活动定义名），不锚内部函数名/私有结构；语义锚匹配文案
不锚全句（KI-051 纪律）。零 docker、零 Temporal server、零 3099。

三态（README §执行契约）：引擎解释器缺 temporalio=ENV_FAIL exit 2；dry-run
入口缺失=FAIL exit 1（TDD 期红属预期，arbitrate/merge 期必须绿）；断言破面=exit 1。
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

ENGINE = os.path.join(REPO, "server", "engine")
# 本票交付的公开入口：工人启动 dry-run CLI（方案定名，缺失=被测面未交付）
DRYRUN_CANDIDATES = ("worker_dryrun.py",)

GOOD_PROJECT_KEY = "projclean"
GOOD_MODULE = '''"""干净外置模板夹具：段 id 全部带项目前缀，不撞引擎活动名。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "projclean-good"


@workflow.defn
class ProjcleanGoodWorkflow(TicketWorkflowBase):
    STAGES = (
        Stage(id="pc-brief", name="段一", role="developer", next="pc-done",
              acceptance=("段一完成",)),
        Stage(id="pc-done", name="段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "projclean-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "projclean 干净模板"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "t260925-16 集成夹具（干净）"

    @workflow.run
    async def run(self, inp: TicketInput):
        return await self._main(inp)
'''
# 事故形态复刻：段 id 无前缀，撞 agent_activities 退役段 ai-review
COLLIDE_MODULE = GOOD_MODULE.replace('TEMPLATE_ID = "projclean-good"',
                                     'TEMPLATE_ID = "projcollide-bad"') \
    .replace("ProjcleanGoodWorkflow", "ProjcollideBadWorkflow") \
    .replace("projclean 干净模板", "projcollide 撞名夹具") \
    .replace('Stage(id="pc-brief"', 'Stage(id="ai-review"')

PROBE = r'''#!/usr/bin/env python3
"""t260925-16 只读探针：组合活动名重复面＋撞名拒收面＋模块身份面。"""
import dataclasses
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.environ["PROBE_ENGINE"])
import shared  # noqa: E402
import project_templates as _pt  # noqa: E402
import workflows_v2  # noqa: E402  # 触发类面合并（真源表回写在 import 期）


def ser(r):
    if isinstance(r, dict):
        return {k: str(v) for k, v in r.items()}
    try:
        return dataclasses.asdict(r)
    except Exception:
        return {"repr": str(r)}


rej = getattr(shared, "PROJECT_TEMPLATE_REJECTIONS", None)
if rej is None:
    rej = getattr(_pt, "PROJECT_TEMPLATE_REJECTIONS", [])
try:
    composed = (workflows_v2.ALL_ACTIVITIES + workflows_v2.ALL_AGENT_ACTIVITIES
                + [workflows_v2.make_stage_activity(s)
                   for s in workflows_v2.PROJECT_TEMPLATE_STAGE_IDS])
    names = Counter(a.__temporal_activity_definition.name for a in composed)
    dups = sorted(n for n, c in names.items() if c > 1)
    compose_err = ""
except Exception as exc:  # 组装面炸=行为事实，如实上报交判定器断言
    dups, compose_err = None, "%s: %s" % (type(exc).__name__, exc)

out = {
    "names": dict(shared.TEMPLATE_CLASS_NAMES),
    "rejections": [ser(r) for r in (rej or [])],
    "stage_ids": sorted(workflows_v2.PROJECT_TEMPLATE_STAGE_IDS),
    "dup_activity_names": dups,
    "compose_err": compose_err,
    "agent_activities_mods": sorted(
        m for m in sys.modules if m == "agent_activities"),
    "ext_mods_leftover": sorted(
        m for m in sys.modules if m.startswith("sandbar_ext_")
        and "collide" in m),
}
print(json.dumps(out, ensure_ascii=False))
'''


def write_project(root, key, modules):
    """写项目注册条目（project.yaml paths.workflow_modules）＋模块文件。"""
    pdir = os.path.join(root, key)
    mods_dir = os.path.join(pdir, "wf_mods")
    os.makedirs(mods_dir, exist_ok=True)
    rels = []
    for rel, text in modules:
        with open(os.path.join(pdir, rel), "w", encoding="utf-8") as f:
            f.write(text)
        rels.append(rel)
    with open(os.path.join(pdir, "project.yaml"), "w", encoding="utf-8") as f:
        f.write("# fixture-local registry（t260925-16 场景①）\n"
                "schema: v1\nproject:\n  - key: %s\n    name: %s\n"
                "    dirs:\n      - %s\n"
                "paths:\n  workflow_modules: %s\n"
                % (key, key, pdir, ",".join(rels)))
    return root


def find_dryrun(fail):
    for name in DRYRUN_CANDIDATES:
        p = os.path.join(ENGINE, name)
        if os.path.isfile(p):
            return p
    fail.bail("工人启动 dry-run 入口未交付（找过 %s 于 %s）——KI-121 修法③未落地"
              % (", ".join(DRYRUN_CANDIDATES), ENGINE), 1)


def run_dryrun(py, dryrun, registry):
    env = dict(os.environ)
    env.pop("SANDBAR_FIXTURE_TEMPLATES", None)
    env["SANDBAR_PROJECTS_DIR"] = registry
    env["PYTHONPYCACHEPREFIX"] = os.path.join(tempfile.gettempdir(), "t26092516-pyc")
    p = subprocess.run([py, "-B", dryrun], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_probe(py, registry):
    env = dict(os.environ)
    env.pop("SANDBAR_FIXTURE_TEMPLATES", None)
    env["SANDBAR_PROJECTS_DIR"] = registry
    env["PROBE_ENGINE"] = ENGINE
    env["PYTHONPYCACHEPREFIX"] = os.path.join(tempfile.gettempdir(), "t26092516-pyc")
    probe = os.path.join(tempfile.mkdtemp(prefix="t26092516-probe-"), "probe.py")
    with open(probe, "w", encoding="utf-8") as f:
        f.write(PROBE)
    p = subprocess.run([py, probe], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=180)
    out = (p.stdout or "") + (p.stderr or "")
    for ln in p.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return p.returncode, json.loads(ln)
            except Exception:
                continue
    return p.returncode, {"_raw": out[-400:]}


def parse_summary(out):
    """dry-run 绿态应打一行 JSON 摘要；找首个 { 行。"""
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return None


def main():
    fail = Fail("t260925-16 场景①：外置模板段 id 撞引擎活动名 → 工人启动面 fail-loud 点名不裸崩")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26092516-scene-")

    # ---- 环境门：解释器缺 temporalio=ENV_FAIL exit 2，不假绿 ----
    env_probe = os.path.join(tmp, "envprobe")
    os.makedirs(env_probe)
    rc, data = run_probe(py, env_probe)
    raw = json.dumps(data, ensure_ascii=False)
    if "temporalio" in raw and data.get("dup_activity_names") is None:
        fail.bail("ENV_FAIL: 引擎解释器缺 temporalio（%s）——场景无法执行" % py, 2)
    if rc != 0:
        fail.bail("只读探针不可跑（rc=%s raw尾=%s）——引擎装配面或环境异常" % (rc, raw[-200:]), 1)

    dryrun = find_dryrun(fail)

    # ---- A1 干净声明可启动：dry-run 绿＋组合注册表零同名 ----
    reg_good = write_project(os.path.join(tmp, "regGood"), GOOD_PROJECT_KEY,
                             [("good.py", GOOD_MODULE)])
    rc, out = run_dryrun(py, dryrun, reg_good)
    fail.check(rc == 0, "A1 干净声明：dry-run exit 0（实得 rc=%s 尾=%s）" % (rc, out[-200:]))
    summary = parse_summary(out)
    fail.check(summary is not None, "A1 干净声明：stdout 含一行 JSON 摘要（可机器消费）")
    _, pdata = run_probe(py, reg_good)
    fail.check(pdata.get("dup_activity_names") == [],
               "A1 组合注册表零同名活动（实得 %r / compose_err=%r）"
               % (pdata.get("dup_activity_names"), pdata.get("compose_err")))
    fail.check(GOOD_PROJECT_KEY + "-good" in (pdata.get("names") or {}),
               "A1 干净模板正常注册进可用面（实得 %r)" % (sorted(pdata.get("names") or {}),))

    # ---- A2 撞名声明 fail-loud：红且点名双方，非 temporalio 裸崩 ----
    reg_bad = write_project(os.path.join(tmp, "regBad"), "projcollide",
                            [("collide.py", COLLIDE_MODULE)])
    rc, out = run_dryrun(py, dryrun, reg_bad)
    summary = parse_summary(out)  # A2 重取本轮输出（原稿沿用 A1 的绿态 summary 变量，判定面失真）
    fail.check(rc == 1, "A2 撞名声明：dry-run exit 1（实得 rc=%s）——不静默放行" % rc)
    blob = out
    fail.check("ai-review" in blob, "A2 文案点名撞名活动名 ai-review")
    fail.check("agent_activities" in blob,
               "A2 文案点名引擎侧来源 agent_activities（裸 ValueError 不会带）")
    fail.check(("projcollide" in blob and "collide.py" in blob) or "collide" in blob,
               "A2 文案点名来件方（项目/模块）")
    fail.check(summary is None,
               "A2 红态不打绿态 JSON 摘要（机器判定面不被污染）")

    # ---- A3 加载期拒收：整模板拒收点名双方＋坏不拖好＋组合面零重复 ----
    reg_mix = write_project(os.path.join(tmp, "regMix"), "projmix",
                            [("collide.py", COLLIDE_MODULE.replace(
                                "projcollide", "projmix")),
                             ("good2.py", GOOD_MODULE.replace(
                                 "projclean", "projmix").replace(
                                 "ProjcleanGoodWorkflow", "ProjmixGood2Workflow"))])
    rc2, pdata2 = run_probe(py, reg_mix)
    blob2 = json.dumps(pdata2, ensure_ascii=False)
    fail.check("projmix-bad" not in (pdata2.get("names") or {}),
               "A3 撞名模板整模板不注册（实得 %r)" % (sorted(pdata2.get("names") or {}),))
    fail.check("ai-review" in blob2 and "projmix" in blob2,
               "A3 拒收记录点名活动名＋来件方（实得拒收面 %r)"
               % (pdata2.get("rejections"),))
    fail.check("agent_activities" in blob2,
               "A3 拒收记录点名引擎侧占用方（不静默）")
    fail.check("projmix-good" in (pdata2.get("names") or {}),
               "A3 同项目兄弟好模板照常注册（坏不拖好）")
    fail.check(pdata2.get("dup_activity_names") == [] and pdata2.get("compose_err") == "",
               "A3 撞名被加载期拦下后，组合注册表零重复零异常（防线下移，实得 dups=%r err=%r）"
               % (pdata2.get("dup_activity_names"), pdata2.get("compose_err")))

    # ---- A4 模块身份面：单一身份＋拒收无半态残留 ----
    fail.check(pdata2.get("agent_activities_mods") == ["agent_activities"],
               "A4 agent_activities 在加载后保持单一 sys.modules 身份（实得 %r)"
               % (pdata2.get("agent_activities_mods"),))
    fail.check(pdata2.get("ext_mods_leftover") == [],
               "A4 撞名拒收后无项目侧半态模块残留（实得 %r)"
               % (pdata2.get("ext_mods_leftover"),))

    # ---- A5 幂等：连跑两遍判定一致 ----
    rc_b1, _ = run_dryrun(py, dryrun, reg_good)
    rc_b2, _ = run_dryrun(py, dryrun, reg_good)
    fail.check(rc_b1 == 0 and rc_b2 == 0,
               "A5 干净声明 dry-run 连跑两遍恒绿（%s/%s)" % (rc_b1, rc_b2))
    rc_c1, _ = run_dryrun(py, dryrun, reg_bad)
    rc_c2, _ = run_dryrun(py, dryrun, reg_bad)
    fail.check(rc_c1 == 1 and rc_c2 == 1,
               "A5 撞名声明 dry-run 连跑两遍恒红（%s/%s)" % (rc_c1, rc_c2))

    fail.finish()


if __name__ == "__main__":
    main()
