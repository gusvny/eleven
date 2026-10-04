#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_ki123_create_face_template_visibility.py — KI-123：create 面对外置模板类面的可见性与点名拒收（t260926-03，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为，KI-123 三条要求 + 工单验收口径）：
- E1 类面对 create 面可见（要求①）：项目注册根（SANDBAR_PROJECTS_DIR）声明
  workflow_modules 指向**真形状**模块（@workflow.defn + temporalio + STAGES +
  PATCH_ID/TEMPLATE_ID 全，非夹具 stand-in 钉面——root=None 真语义）→
  client.py 公开 op `template-faces`（引擎 venv 现算）回执 class_available
  含该 id、rejections 空、declared_projects>=1（回执契约键在位）；
- E2 P0 正向可达：同一真实声明路径下 `ticket.py create workflow=<外置id>` 在
  **无 Temporal 的离线台**上越过模板闸——失败点是 Temporal 阶段（文案含
  Temporal），**不再是**「可用：dev-lane」裸拒收（修前面就是这句=silent no-op）；
- E3 拒收必须点名（要求②）：项目模块 import 不存在的名字 → create 该 id 被拒，
  文案带 check（加载失败）+ detail（缺什么：ModuleNotFoundError: ...），
  不许裸「可用：dev-lane」装死；
- E4 未声明点名：项目无 workflow_modules 声明 → create 未知 id 的拒收点名
  「未登记/未声明」类原因（与 E3 的「加载失败」不同形），非裸拒收；
- E5 畸形注册根 fail-closed（外部输入畸形纪律）：project.yaml 非法 → 拒收点名
  注册根解析原因，不静默回落内置面（裸「可用：dev-lane」=装死=红）；
- E6 内置面不受扰：dev-lane 建票离线失败仍是 Temporal 阶段（内置快路径零扰动，
  不被外置模板闸拖下水误拒）。

灰盒声明：只断公开 CLI 面（client.py template-faces 回执键、ticket.py create
报错语义锚），不锚全句措辞（KI-051）、不锚内部函数名；拒因断言用松锚关键词
（「加载失败」是 project_templates 既有 check 词表、'Temporal' 是 spawn 通道
既有文案词）。与 t260924-04 sc_project_template_ticket_journey（ticket-start
全链旅程、独占台分钟级）intent 不同面：本场景只打 create 面可见性/拒收点名，
零 docker 秒级。

三态：引擎 venv（temporalio 可导入）缺席 = ENV_FAIL exit 2；断言破面 = exit 1。
实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。
Run directly: python3 integration/t260926-03/sc_ki123_create_face_template_visibility.py（cwd=仓根）。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
ENGINE = REPO / "server" / "engine"
TICKET = REPO / "server" / "tools" / "ticket.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title):
    print("\n%s" % title)


def engine_py() -> str | None:
    """引擎 venv 解释器（temporalio 面依赖）；无 venv 回落链 = 环境面。"""
    # 260928 清残留：删 M2 搬迁前旧布局回落候选（路径已不存在；见 sc_engine_layout 守卫）。
    for p in (ENGINE / ".venv" / "bin" / "python",):
        if p.exists():
            return str(p)
    return None


def has_temporalio(py: str) -> bool:
    try:
        return subprocess.run([py, "-c", "import temporalio"], capture_output=True,
                              timeout=60).returncode == 0
    except Exception:
        return False


LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")
# t261004-26（-0023）：调用方身份同属「绝不继承」面——继承的 SANDBAR_CALLER_PROJECT
# 会让跨项目闸抢在断言面之前拒收。清理后再由各 spawn 按票面自身 project 显式声明。
LANE_MARKERS = LANE_MARKERS + ("SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC")

EXT_ID = "ki123-real-flow"

GOOD_MODULE = '''"""ki123-real-flow — t260926-03 集成夹具：项目声明的外置模板（真形状）。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "%s"


@workflow.defn
class Ki123RealFlow(TicketWorkflowBase):
    STAGES = (
        Stage(id="k_one", name="KI123段一", role="developer", next="k_two",
              acceptance=("段一完成",)),
        Stage(id="k_two", name="KI123段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "ki123-real-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "KI123 真实声明流"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "t260926-03 真实声明路径夹具"

    @workflow.run
    async def run(self, inp: TicketInput):
        return await self._main(inp)
''' % EXT_ID

# 加载即炸形态 = KI-123 现场拒因族（import 不存在的名字 → ModuleNotFoundError）
BROKEN_MODULE = '''from temporalio import workflow
from ki123_nonexistent_pkg import ki123_missing_symbol

TEMPLATE_ID = "ki123-broken-flow"


@workflow.defn
class Ki123BrokenFlow:
    @workflow.run
    async def run(self, inp):
        return inp
'''

BARE_OLD_REFUSAL = "create 需要 workflow（模板 id，可用：dev-lane）"


def clean_env(root: pathlib.Path, caller=None) -> dict:
    env = dict(os.environ)
    for m in LANE_MARKERS:
        env.pop(m, None)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    if caller:
        env["SANDBAR_CALLER_PROJECT"] = caller      # 显式声明，先剥后注入（t261004-26）
    return env


def make_project(root: pathlib.Path, key: str, modules: dict | None) -> pathlib.Path:
    """注册根条目（契约①a schema v1 格式，t260924-04 测试夹具同款形状）。"""
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    paths = ""
    if modules:
        paths = "paths:\n  workflow_modules: %s\n" % ",".join(
            "mods/%s" % m for m in modules)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: KI123测试项目\n"
        "    dirs:\n      - %s\n%s" % (key, pd, paths), "utf-8")
    if modules:
        (pd / "mods").mkdir(exist_ok=True)
        for fname, body in modules.items():
            (pd / "mods" / fname).write_text(body, "utf-8")
    return pd


def run_faces(epy: str, root: pathlib.Path, payload: str = "{}"):
    try:
        caller = (json.loads(payload) or {}).get("project")
    except ValueError:
        caller = None
    return subprocess.run(
        [epy, str(ENGINE / "client.py"), "template-faces", payload],
        cwd=str(REPO), env=clean_env(root, caller=caller), capture_output=True,
        text=True, timeout=300)


def run_create(root: pathlib.Path, workflow: str, key: str):
    payload = json.dumps({"op": "create", "project": key, "workflow": workflow,
                          "title": "ki123 offline probe"}, ensure_ascii=False)
    return subprocess.run([sys.executable, str(TICKET), payload],
                          cwd=str(REPO), env=clean_env(root, caller=key),
                          capture_output=True, text=True, timeout=300)


def main() -> int:
    epy = engine_py()
    if not epy or not has_temporalio(epy):
        print("ENV_FAIL: 引擎 venv（temporalio 可导入）缺席——类面深检无解释器可用")
        return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t260926-03-"))
    try:
        # ---- 真实声明路径夹具（要求③：project registry + workflow_modules 声明）----
        # 根隔离：健康路径（E1/E2/E6）注册根只含健康声明（回执 rejections 应空）；
        # 故障路径（E3/E4）另根，防坏声明污染健康回执断言。
        root = tmp / "projects"
        root.mkdir()
        make_project(root, "ki123p", {"real_flow.py": GOOD_MODULE})
        root_flt = tmp / "projects-fault"
        root_flt.mkdir()
        make_project(root_flt, "ki123p", {"real_flow.py": GOOD_MODULE})
        make_project(root_flt, "ki123broken", {"broken.py": BROKEN_MODULE})
        make_project(root_flt, "ki123nodecl", None)  # 无 workflow_modules 声明
        badroot = tmp / "badreg"
        badroot.mkdir()
        (badroot / "ki123bad").mkdir()
        (badroot / "ki123bad" / "project.yaml").write_text(
            "schema: v1\nproject: [ { key: :::. ", "utf-8")

        section("E1 类面对 create 面可见（公开 op，真实声明路径现算）")
        r1 = run_faces(epy, root)
        ok(r1.returncode == 0, "template-faces op 退出码 0（本地只读，无需 Temporal 在线）")
        try:
            shell = json.loads(r1.stdout)
            receipt = shell.get("result") if isinstance(shell, dict) else None
            ok(isinstance(shell, dict) and shell.get("ok") is True
               and isinstance(receipt, dict),
               "template-faces 回执 ok=true（结构化 JSON，result 为对象）")
            available = receipt.get("class_available")
            ok(isinstance(available, list) and EXT_ID in available,
               "class_available 含真实声明的 %s（修前 create 面看不到）" % EXT_ID)
            ok(receipt.get("rejections") == [],
               "健康声明路径 rejections=[]（不是 accepted/rejections 双空的 silent no-op）")
            ok(receipt.get("declared_projects", 0) >= 1,
               "declared_projects>=1（声明枚举可判别，非空转没扫）")
            for k in ("names", "builtin"):
                ok(k in receipt, "回执契约键 %s 在位" % k)
        except (json.JSONDecodeError, AttributeError):
            ok(False, "template-faces 回执为结构化 JSON：%r" % (r1.stdout or r1.stderr)[:200])

        section("E2 P0 正向可达：create 越过模板闸且模板定义可装载（全链可建票）")
        r2 = run_create(root, EXT_ID, "ki123p")
        out2 = (r2.stdout or "") + (r2.stderr or "")
        ok(BARE_OLD_REFUSAL not in out2 and "可用：dev-lane" not in out2,
           "外置 id 建票不再是「可用：dev-lane」裸拒收（修前=KI-123 现场）")
        ok("模板不存在" not in out2,
           "create 模板闸放行后模板定义可装载（不含「模板不存在: …/<id>.yaml」——"
           "项目声明模板无 server/workflows 快照=建票仍走不通，KI-123 残余缺陷锚）")
        ok("Temporal" in out2 or "模板不存在" in out2,
           "闸后失败点可判别（离线台=Temporal 阶段；或快照缺失=残余缺陷显形）")

        section("E3 拒收点名：坏模块 check+detail（不许装死）")
        r3 = run_create(root_flt, "ki123-broken-flow", "ki123broken")
        out3 = (r3.stdout or "") + (r3.stderr or "")
        ok(r3.returncode != 0, "坏模板 id 建票被拒（fail-closed）")
        ok("加载失败" in out3, "拒收文案点名 check=加载失败（project_templates 既有检查词）")
        ok("ModuleNotFoundError" in out3 or "ki123_nonexistent_pkg" in out3,
           "拒收文案点名缺什么（ModuleNotFoundError/缺失包名）")
        ok(not (BARE_OLD_REFUSAL in out3 and "加载失败" not in out3),
           "拒收不是裸「可用：dev-lane」装死")

        section("E4 未声明点名：项目无 workflow_modules 声明")
        r4 = run_create(root_flt, "ki123-never-declared", "ki123nodecl")
        out4 = (r4.stdout or "") + (r4.stderr or "")
        ok(r4.returncode != 0, "未声明 id 建票被拒（fail-closed）")
        ok(("声明" in out4) or ("登记" in out4) or ("未扫到" in out4),
           "拒收点名「未登记/未声明」类原因（与 E3 加载失败不同形）")
        ok(BARE_OLD_REFUSAL not in out4, "非裸「可用：dev-lane」静默回落内置面")

        section("E5 畸形注册根 fail-closed（外部输入畸形纪律）")
        r5 = run_create(badroot, "ki123-whatever", "ki123bad")
        out5 = (r5.stdout or "") + (r5.stderr or "")
        ok(r5.returncode != 0, "畸形注册根下建票被拒（fail-closed）")
        ok(BARE_OLD_REFUSAL not in out5, "畸形注册根不静默回落裸内置拒收（点名原因）")
        ok(("解析" in out5) or ("失败" in out5) or ("注册" in out5) or ("加载" in out5),
           "拒收点名注册根原因（解析/失败/注册类关键词）")

        section("E6 内置面不受扰：dev-lane 快路径")
        r6 = run_create(root, "dev-lane", "ki123p")
        out6 = (r6.stdout or "") + (r6.stderr or "")
        ok("可用：dev-lane" not in out6, "内置 dev-lane 不被外置模板闸误拒")
        ok("Temporal" in out6, "内置面离线失败点仍是 Temporal 阶段（快路径语义不变）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n== summary: pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
