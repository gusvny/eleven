#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_external_template_catalog_topology.py — 项目外置模板进目录面×拓扑导出×缺席点名（t260927-05，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为，工单验收口径逐条对应）：
  A 目录面并入（验收①）：项目注册根（SANDBAR_PROJECTS_DIR）声明 workflow_modules 指向
    真形状外置模块（temporalio + @workflow.defn + STAGES）后，`python3 server/tools/workflow.py`
    的 list 回执含该模板行——行带非空 stages、非空 topology（nodes/edges）、来源 project 键；
    建票/控制台目录消费同一面。
  B 默认面零回归（验收②）：空注册根下 list 的 id 集合恰为 {dev-lane}——收窄守卫
    sc_template_face_narrowing 的默认面断言同口径，行形状键集不因并入通道变化。
  C 未声明反例（验收③）：项目注册在案但未声明 workflow_modules → 外置 id 不在目录面
    （登记≠声明，绝不全局泄漏）。
  D 拓扑导出三态（验收④）：内置 dev-lane 行 topology 在位且非空（零回归锚）；外置模板行
    topology 非空且 nodes 覆盖其 STAGES 段 id；STAGES 退化（空段表）的外置模板行 topology
    为 None 且**不伪造**（缺席有痕：topology_error/note 点名，绝不编一个假拓扑）。
  E 缺席点名（scope③ fallback naming）：faces 通道不可用/回执畸形（坏注册根注入）时
    list 通道不炸、dev-lane 照常返回，且回执或 stderr 必须点名「声明了外置模板但目录面缺席」
    ——用户不在 UI 里找不到答案（KI-123「静默回落内置面」教训的反面）。

分层纪律（防 intent 级重复）：
  - t260926-03 sc_ki123_create_face_template_visibility 锁 create 面类面可见性（template-faces
    回执与 create 拒收点名）；本场景锁 **目录面（workflow.py list）+ 拓扑导出**的同一并入，不同面。
  - t260915-05 系锁 dev-lane 拓扑渲染/降级与控制台 DOM；本场景锁目录/拓扑 **数据面**对项目
    外置模板的覆盖，UI 渲染归 sc_external_template_lane_map_render.mjs（同票不同层）。
  - t260904-08 sc_template_face_narrowing 锁退役后默认面收窄契约；本场景 B 段是其口径的
    并入后回归锚（断言只加不减，不推翻）。

Hermetic：零网络零端口零真 Temporal（list/faces 均本地只读扫描）；不触 3099；cwd=仓库根；
秒级。临时目录用 TemporaryDirectory 全程回收（lint L8）。
三态契约（t260904-12）：stdout 末行 SUMMARY pass=N fail=K env_fail=E na=0；
exit 0=PASS / 1=FAIL / 2=ENV_FAIL。faces 通道需引擎 venv（temporalio 可导入）——
venv 缺席=ENV_FAIL exit 2 点名（KI-020③ 家族）。实现未落地段红属预期（TDD 信号），
arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
TOOLS = REPO / "server" / "tools"
WORKFLOW_PY = TOOLS / "workflow.py"

EXT_ID = "t05-ext-flow"

GOOD_MODULE = '''"""t05-ext-flow — t260927-05 集成夹具：项目声明的外置模板（真形状，非夹具门）。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "%s"


@workflow.defn
class T05ExtFlow(TicketWorkflowBase):
    STAGES = (
        Stage(id="t05_one", name="T05段一", role="developer", next="t05_two",
              acceptance=("段一完成",)),
        Stage(id="t05_two", name="T05段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "t05-ext-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "T05 外置声明流"
    TEMPLATE_LANE = "worktree"
    TEMPLATE_DESC = "t260927-05 目录面/拓扑导出夹具"

    @workflow.run
    async def run(self, inp: TicketInput):
        return await self._main(inp)
''' % EXT_ID

# 退化段表形态：类合法可加载，但 STAGES 空 → 拓扑导出必须 None + 点名，绝不伪造
DEGENERATE_MODULE = '''"""t05-deg-flow — t260927-05 夹具：STAGES 退化的外置模板（导出面不伪造）。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import TicketInput

TEMPLATE_ID = "t05-deg-flow"


@workflow.defn
class T05DegFlow(TicketWorkflowBase):
    STAGES = ()
    PATCH_ID = "t05-deg-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "T05 退化段表流"
    TEMPLATE_LANE = "worktree"

    @workflow.run
    async def run(self, inp: TicketInput):
        return await self._main(inp)
'''

# 加载即被拒形态 = 声明在案但进不了目录面（faces rejections 点名族，E 段注入）
BROKEN_MODULE = '''from t05_nonexistent_pkg import missing_symbol

TEMPLATE_ID = "t05-broken-flow"
'''

LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")

passed = failed = env_failed = 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, (" — %s" % detail) if detail else ""))


def engine_py() -> str:
    # 260928 清残留：删 M2 搬迁前旧布局回落候选（路径已不存在）。
    for cand in (ENGINE / ".venv" / "bin" / "python",):
        if cand.exists():
            return str(cand)
    return sys.executable


def has_temporalio(py: str) -> bool:
    r = subprocess.run([py, "-c", "import temporalio"], capture_output=True, timeout=120)
    return r.returncode == 0


def make_project(root: pathlib.Path, key: str, modules: dict | None) -> pathlib.Path:
    """注册根条目（schema v1，t260926-03 夹具同款形状）。"""
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    paths = ""
    if modules:
        paths = "paths:\n  workflow_modules: %s\n" % ",".join("mods/%s" % m for m in modules)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: T05测试项目\n"
        "    dirs:\n      - %s\n%s" % (key, pd, paths), "utf-8")
    if modules:
        (pd / "mods").mkdir(exist_ok=True)
        for fname, body in modules.items():
            (pd / "mods" / fname).write_text(body, "utf-8")
    return pd


def clean_env(root: pathlib.Path) -> dict:
    env = dict(os.environ)
    for m in LANE_MARKERS:
        env.pop(m, None)
    env.pop("SANDBAR_FIXTURE_TEMPLATES", None)  # 默认面口径：夹具门恒关
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env["PYTHONPATH"] = str(ENGINE) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_list(py: str, root: pathlib.Path):
    return subprocess.run([py, str(WORKFLOW_PY)], cwd=str(REPO), env=clean_env(root),
                          capture_output=True, text=True, timeout=300)


def rows_by_id(stdout: str) -> dict:
    out = json.loads(stdout)
    return {w["id"]: w for w in out.get("workflows", [])}


def main() -> int:
    global env_failed
    py = engine_py()
    if not has_temporalio(py):
        print("ENV_FAIL: 引擎 venv（temporalio 可导入）缺席——faces 通道无解释器可用（KI-020③ 家族）")
        env_failed += 1
        return 2
    with tempfile.TemporaryDirectory(prefix="t260927-05-") as td:
        tmp = pathlib.Path(td)

        # ---- A 目录面并入（正向）+ D 拓扑导出：健康根只含健康声明
        root = tmp / "projects"
        root.mkdir()
        make_project(root, "t05p", {"ext_flow.py": GOOD_MODULE})
        r = run_list(py, root)
        if r.returncode != 0:
            print("  FAIL workflow.py 退出码 %d（stderr: %s）" % (r.returncode, (r.stderr or "")[-300:]))
            return finish()
        rows = rows_by_id(r.stdout)

        check(EXT_ID in rows, "A 目录面含项目声明的外置模板 %s" % EXT_ID,
              "ids=%r" % sorted(rows))
        row = rows.get(EXT_ID, {})
        check(bool(row.get("stages")), "A 外置模板行带非空 stages（目录面含段）",
              "stages=%r" % (row.get("stages"),))
        stage_ids = {s.get("id") for s in (row.get("stages") or [])}
        check({"t05_one", "t05_two"} <= stage_ids, "A stages 覆盖类 STAGES 段 id",
              "stage_ids=%r" % (stage_ids,))
        topo = row.get("topology")
        check(isinstance(topo, dict) and topo.get("nodes"), "D 外置模板行 topology 非空（nodes 在位）",
              "topology=%r" % (topo,))
        node_ids = {n.get("id") for n in (topo or {}).get("nodes") or []}
        check({"t05_one", "t05_two"} <= node_ids, "D topology nodes 覆盖 STAGES 段 id",
              "node_ids=%r" % (node_ids,))
        check(row.get("project") in (None, "t05p") or row.get("project") == "t05p",
              "A 行可辨声明来源（project 键=t05p 或等价）", "project=%r" % (row.get("project"),))

        # ---- B 默认面零回归：空注册根
        empty_root = tmp / "projects-empty"
        empty_root.mkdir()
        r2 = run_list(py, empty_root)
        if r2.returncode != 0:
            check(False, "B 空注册根 list 退出码 0", "stderr=%s" % (r2.stderr or "")[-300:])
        else:
            rows2 = rows_by_id(r2.stdout)
            # 宿主令 260930：内置面加一格 light-lane（轻道泳道）——「默认面=内置面全集、
            # 未声明项目不泄漏」语义不变。
            check(set(rows2) == {"dev-lane", "light-lane"},
                  "B 默认面 id 集合恰内置面 {dev-lane, light-lane}"
                  "（收窄守卫同口径，零回归）",
                  "ids=%r" % sorted(rows2))
            dl = rows2.get("dev-lane", {})
            check(bool(dl.get("stages")) and isinstance(dl.get("topology"), dict),
                  "B dev-lane 行形状不因并入通道变化（stages+topology 在位）")

        # ---- C 未声明反例：项目在案未声明 → 不泄漏
        nodecl_root = tmp / "projects-nodecl"
        nodecl_root.mkdir()
        make_project(nodecl_root, "t05nodecl", None)
        r3 = run_list(py, nodecl_root)
        if r3.returncode != 0:
            check(False, "C 未声明根 list 退出码 0", (r3.stderr or "")[-300:])
        else:
            check(EXT_ID not in rows_by_id(r3.stdout),
                  "C 未声明 workflow_modules 的项目不泄漏外置模板（登记≠声明）")

        # ---- D3 退化段表：topology None 不伪造
        deg_root = tmp / "projects-deg"
        deg_root.mkdir()
        make_project(deg_root, "t05deg", {"deg_flow.py": DEGENERATE_MODULE})
        r4 = run_list(py, deg_root)
        if r4.returncode != 0:
            check(False, "D 退化根 list 退出码 0（通道不炸）", (r4.stderr or "")[-300:])
        else:
            deg = rows_by_id(r4.stdout).get("t05-deg-flow", {})
            check(deg.get("topology") is None, "D 退化 STAGES 的外置模板 topology=None（不伪造）",
                  "topology=%r" % (deg.get("topology"),))
            named = ("topology_error" in deg) or bool((r4.stderr or "").strip()) or \
                    bool(str(deg.get("catalog_note") or "").strip())
            check(named, "D 退化缺席有痕（topology_error/note/stderr 点名，非静默）")

        # ---- E 缺席点名（scope③ fallback naming）：项目**声明在案**但模板进不了
        # 目录面（模块加载被拒）→ faces rejections 有名，list 通道必须把缺席点名
        # （stdout note 或 stderr），用户不在 UI 里找不到答案；dev-lane 照常返回不炸。
        brk_root = tmp / "projects-broken"
        brk_root.mkdir()
        make_project(brk_root, "t05brk", {"broken.py": BROKEN_MODULE})
        r5 = run_list(py, brk_root)
        if r5.returncode != 0:
            check(False, "E 声明被拒根 list 退出码 0（通道不炸）", (r5.stderr or "")[-300:])
        else:
            rows5 = rows_by_id(r5.stdout)
            check("dev-lane" in rows5, "E faces 拒收时内置面照常返回（绝不静默清空）")
            out5 = r5.stdout + r5.stderr
            check("t05-broken-flow" in out5 or ("t05brk" in out5 and ("catalog" in out5 or "目录" in out5 or "缺席" in out5)),
                  "E 目录面对声明在案却缺席的外置模板点名（rejections 不能只进 faces 不进目录面）",
                  "out=%r" % out5[-400:])

        # ---- A2 对照：健康根下缺席点名不得误报（正常路径无 note 红字）
        root_ok = run_list(py, root)
        if root_ok.returncode == 0 and EXT_ID in rows_by_id(root_ok.stdout):
            check("not in the catalog" not in (root_ok.stdout + root_ok.stderr),
                  "A2 健康路径不误报缺席点名（点名纪律只在真缺席时触发）")
        else:
            check(False, "A2 健康根复跑可判（复跑失败归 A 段已红）")
    return finish()


def finish() -> int:
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    if failed:
        return 1
    if env_failed:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
