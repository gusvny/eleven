"""t260926-03 KI-123——create 面可见性：项目模板类面回归杆（单测面）。

背景（票面原文）：ticket.py create workflow=content-studio 被拒 `available: dev-lane`；
同进程名面已列出 content-studio，类面却 accepted=[] rejections=[]（既不收也不拒的
静默空转），项目模板的票建不出来。

覆盖五杆：
  1. 真实声明路径类面可见：临时 per-key 注册根（SANDBAR_PROJECTS_DIR env 注入，
     走 root=None 真语义 load_projects_registry + perkey_projects_root +
     project_paths，**非** root 参数钉面/夹具 stand-in）× 真形状模块（temporalio
     @workflow.defn + STAGES）→ client.py template-faces（引擎侧权威面）回执
     class_available 含该 id。
  2. create 正向可达（review 第 1 轮打回补杆）：同一真实路径回执喂 ticket.py 新闸
     `_template_gate_verdict` → verdict=pass（_create 越过模板闸继续往下走）；
     加分杆：_create 直调（依赖全 stub）越过模板闸走到铸号位。
  3. 拒收点名：模块 import 不存在的名字 → 回执 rejections 带模块路径+缺什么；
     闸文案含 check/detail，不再裸「可用：dev-lane」。
  4. 畸形输入 fail-closed：回执缺键/类型错/ok:false/子进程异常 → 全部点名，
     绝不静默回落内置面。
  5. 内置快路径：dev-lane 不 spawn 权威面（stub 计数=0）。

事件循环内类面回归（KI-123 实录根因之一）：cmd_template_faces 在 asyncio.run 内
现算类面，sandbox 预校验的嵌套 loop 不得误判好模板（t260926-03 修）。

夹具全部本地桩/临时目录，不依赖任何外部真源；无 temporalio 的解释器上真实类面杆
显式 skip 并注明（不是造假通过）。
"""
import asyncio
import json
import os
import pathlib
import subprocess
import sys

import pytest

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent
REPO = ENGINE_DIR.parent.parent
GOOD_TMPL = '''TEMPLATE_ID = "{tid}"
TEMPLATE_NAME = "{{disp}}"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class {cls}(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="一", role="developer", next="s2", acceptance=("a",)),
              Stage(id="s2", name="二", role="integration", next="", acceptance=("b",)))
    PATCH_ID = "{{patch}}"
    TEMPLATE_ID = "{tid}"
    TEMPLATE_NAME = "{{disp}}"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''

BAD_TMPL = '''TEMPLATE_ID = "{tid}"
import no_such_module_xyz  # 顶部 import 即炸：类面「加载失败」拒收点名面
from temporalio import workflow

@workflow.defn
class BrokenTpl:
    pass
'''


def _load_ticket_mod():
    """spec 装载 server/tools/ticket.py（与真实调用同源；不依赖包结构）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ticket_under_test", REPO / "server" / "tools" / "ticket.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ticket_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _project(root: pathlib.Path, key: str, modules: dict) -> pathlib.Path:
    """临时 per-key 注册项目：project.yaml 声明 workflow_modules + 模块文件落盘。"""
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


def _template_faces_via_subprocess(root: pathlib.Path):
    """真实端到端杆：引擎 venv 子进程直调 client.py template-faces（该 op 不连
    Temporal——TEMPORAL_ADDRESS 指不可达端口即证 OPS 分发前置无连接检查）。"""
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env["TEMPORAL_ADDRESS"] = "127.0.0.1:1"  # 不可达端口：连了即红
    env.setdefault("PYTHONPYCACHEPREFIX", str(ENGINE_DIR / ".sandbar_pycache"))
    py = ENGINE_DIR / ".venv" / "bin" / "python"
    if not py.is_file():
        pytest.skip("引擎 venv 缺失（无 temporalio，类面现算不可测）")
    proc = subprocess.run([str(py), "client.py", "template-faces", "{}"],
                          cwd=str(ENGINE_DIR), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, "template-faces 非零退出：%s" % (proc.stderr[-400:],)
    out = json.loads(proc.stdout)
    assert out.get("ok"), out
    return out["result"]


def _faces_via_cmd_in_loop(root: pathlib.Path):
    """同回执但走 asyncio.run（client.py main 真实包裹形态）——事件循环内类面回归。"""
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    import importlib.util
    spec = importlib.util.spec_from_file_location("_client_under_test",
                                                  ENGINE_DIR / "client.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_client_under_test"] = mod
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    try:
        spec.loader.exec_module(mod)
        return asyncio.run(mod.cmd_template_faces({}))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old


# ---------------------------------------------------------------------------
# 杆 1 + 杆 2 + 循环内回归：真实声明路径（项目注册表 + workflow_modules 声明）
# ---------------------------------------------------------------------------

def test_real_declared_path_faces_visible_and_create_gate_passes(tmp_path):
    pytest.importorskip("temporalio", reason="类面现算需引擎依赖（venv 面验证）")
    root = tmp_path / "projects"
    _project(root, "kix", {"cs.py": GOOD_TMPL.format(
        tid="kix-studio", cls="KixStudioWorkflow")})
    ticket = _load_ticket_mod()

    # 杆 1：真实端到端——引擎 venv 子进程权威面回执
    faces = _template_faces_via_subprocess(root)
    assert "kix-studio" in faces["class_available"], faces
    assert faces["declared_projects"] == 1
    assert faces["projects_scanned"] >= 1
    assert faces["rejections"] == []
    assert faces["projects_root"] == str(root)

    # 杆 2：同一回执喂 create 模板闸 → 正向放行（越过模板闸，不抛 ValueError）
    ok, msg = ticket._template_gate_verdict("kix-studio", faces, project_key="kix")
    assert ok, "真实声明路径被 create 模板闸误拒：%s" % msg

    # 循环内回归：asyncio.run 包裹形态下现算类面不得误判（sandbox 预校验嵌套 loop）
    loop_faces = _faces_via_cmd_in_loop(root)
    assert loop_faces.get("ok"), loop_faces
    assert "kix-studio" in loop_faces["result"]["class_available"], loop_faces


# ---------------------------------------------------------------------------
# 杆 3：拒收点名（模块 import 不存在的名字 = 加载失败，缺什么可辨）
# ---------------------------------------------------------------------------

def test_real_declared_path_rejection_is_named_not_silent(tmp_path):
    root = tmp_path / "projects"
    _project(root, "kix", {"broken.py": BAD_TMPL.format(tid="kix-broken")})
    ticket = _load_ticket_mod()
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env.setdefault("PYTHONPYCACHEPREFIX", str(ENGINE_DIR / ".sandbar_pycache"))
    py = ENGINE_DIR / ".venv" / "bin" / "python"
    if not py.is_file():
        pytest.skip("引擎 venv 缺失")
    proc = subprocess.run([str(py), "client.py", "template-faces", "{}"],
                          cwd=str(ENGINE_DIR), env=env,
                          capture_output=True, text=True, timeout=120)
    faces = json.loads(proc.stdout)["result"]
    assert faces["class_available"] == []
    rejs = [r for r in faces["rejections"] if r["project"] == "kix"]
    assert rejs and rejs[0]["check"] == "加载失败"
    assert "no_such_module_xyz" in rejs[0]["detail"], rejs
    # 闸文案点名拒因，不再裸「可用：」
    ok, msg = ticket._template_gate_verdict("kix-broken", faces, project_key="kix")
    assert not ok
    assert "拒收明细" in msg and "加载失败" in msg and "no_such_module_xyz" in msg
    assert msg.index("拒收明细") < msg.index("可用：")  # 明细段在「可用：」段之前


# ---------------------------------------------------------------------------
# 杆 2 加分杆：_create 全流程越过模板闸（依赖 stub 注入，铸号位即拦截证据）
# ---------------------------------------------------------------------------

def test_create_fullflow_passes_template_gate(tmp_path, monkeypatch):
    pytest.importorskip("temporalio")
    root = tmp_path / "projects"
    _project(root, "kix", {"cs.py": GOOD_TMPL.format(
        tid="kix-studio", cls="KixStudioWorkflow")})
    faces = _template_faces_via_subprocess(root)
    ticket = _load_ticket_mod()
    spawned = []
    monkeypatch.setattr(ticket, "_template_faces", lambda: (spawned.append(1), faces)[1])
    monkeypatch.setattr(ticket, "_project",
                        lambda key: {"key": "kix", "name": "kix", "dirs": [str(root / "kix")]})
    def _marker(prefix):
        raise RuntimeError("marker-past-template-gate")
    monkeypatch.setattr(ticket, "_uniq_v2", _marker)
    with pytest.raises(RuntimeError, match="marker-past-template-gate"):
        ticket._create({"workflow": "kix-studio", "project": "kix", "title": "T"})
    assert spawned  # 权威面被消费（非内置 → 走查询）


# ---------------------------------------------------------------------------
# 杆 4：畸形回执 / 面不可达 全 fail-closed 点名
# ---------------------------------------------------------------------------

def _mk_ticket(monkeypatch, poc):
    ticket = _load_ticket_mod()
    monkeypatch.setattr(ticket, "_poc", poc)
    return ticket


def test_malformed_faces_receipts_fail_closed(monkeypatch):
    ticket = _load_ticket_mod()
    good = {"names": {"dev-lane": "D"}, "class_available": ["x"],
            "rejections": [], "builtin": ["dev-lane"],
            "declared_projects": 1, "projects_scanned": 2,
            "projects_root": "/tmp"}
    # 基准形状可过
    ticket._validate_faces_shape(dict(good))
    cases = []
    for k in ("class_available", "names", "rejections", "builtin",
              "declared_projects", "projects_scanned"):
        d = dict(good); d.pop(k); cases.append((d, k))
    d = dict(good); d["class_available"] = "x"; cases.append((d, None))
    d = dict(good); d["rejections"] = [{"project": "p"}]; cases.append((d, None))
    for payload, key in cases:
        with pytest.raises(ValueError) as ei:
            ticket._validate_faces_shape(payload)
        assert "fail-closed" in str(ei.value)

    # 子进程异常（_poc 抛 ValueError，含 timeout/解释器缺失/非 JSON）→ 换壳点名
    def boom(sub, payload, caller=None):
        raise ValueError("Temporal 返回非 JSON: <前缀>")
    t = _mk_ticket(monkeypatch, boom)
    with pytest.raises(ValueError, match="权威模板面不可达.*template-faces 子进程故障"):
        t._template_faces()

    # ok:false → 不走 _poc_ok，点名 client 回执失败
    t = _mk_ticket(monkeypatch, lambda s, p, caller=None: {"ok": False, "error": "E1"})
    with pytest.raises(ValueError, match="权威模板面不可达.*E1"):
        t._template_faces()

    # result 非对象 → 点名
    t = _mk_ticket(monkeypatch, lambda s, p, caller=None: {"ok": True, "result": [1]})
    with pytest.raises(ValueError, match="result 非对象"):
        t._template_faces()


# ---------------------------------------------------------------------------
# 杆 5：内置快路径不 spawn 权威面；空转/未登记三态文案可判别
# ---------------------------------------------------------------------------

def test_builtin_fast_path_skips_face_query(monkeypatch):
    ticket = _load_ticket_mod()
    import shared
    assert "dev-lane" in shared.BUILTIN_TEMPLATE_KEYS
    calls = []
    def _no_spawn():
        calls.append(1)
        raise AssertionError("内置模板不得 spawn 权威面查询")
    monkeypatch.setattr(ticket, "_template_faces", _no_spawn)
    monkeypatch.setattr(ticket, "_project",
                        lambda key: {"key": "k", "name": "k", "dirs": ["/tmp"]})
    def _marker(prefix):
        raise RuntimeError("marker-past-template-gate")
    monkeypatch.setattr(ticket, "_uniq_v2", _marker)
    with pytest.raises(RuntimeError, match="marker-past-template-gate"):
        ticket._create({"workflow": "dev-lane", "project": "k", "title": "T"})
    assert not calls
    # 缺 workflow 必填文案仍 fail-fast（不 spawn）
    with pytest.raises(ValueError, match="create 需要 workflow"):
        ticket._create({"project": "k", "title": "T"})
    assert not calls


def test_gate_three_state_messages_distinguishable(tmp_path):
    ticket = _load_ticket_mod()
    scanned_zero = {"names": {"dev-lane": "D"}, "class_available": [],
                    "rejections": [], "builtin": ["dev-lane"],
                    "declared_projects": 0, "projects_scanned": 3,
                    "projects_root": str(tmp_path)}
    ok, msg = ticket._template_gate_verdict("nope", scanned_zero, project_key="p")
    assert not ok and "未发现任何 workflow_modules 声明" in msg and str(tmp_path) in msg
    declared = dict(scanned_zero, declared_projects=2, class_available=["other"])
    ok, msg = ticket._template_gate_verdict("nope", declared, project_key="p")
    assert not ok and "未在类面登记" in msg and "other" in msg


# ---------------------------------------------------------------------------
# 第 2 轮（KI-123 残余缺陷）：闸放行后创建体的模板定义消费面——外置 id 无 yaml，
# 改吃权威面 templates 视图；缺视图/lane 非法/缺段表 fail-closed 点名。
# ---------------------------------------------------------------------------

def test_faces_receipt_carries_template_view(tmp_path):
    pytest.importorskip("temporalio")
    root = tmp_path / "projects"
    _project(root, "kix", {"cs.py": GOOD_TMPL.format(
        tid="kix-studio", cls="KixStudioWorkflow")})
    faces = _template_faces_via_subprocess(root)
    tpl = faces["templates"]["kix-studio"]
    assert tpl["lane"] in ("main", "worktree")
    assert tpl["stages"] and tpl["stages"][0]["role"] == "developer"
    assert tpl["stages"][0]["acceptance"] == ["a"]
    assert tpl["stages"][1]["acceptance"] == ["b"]


def test_template_view_yaml_fallback_and_fail_closed(tmp_path):
    import importlib.util
    ticket = _load_ticket_mod()
    spec = importlib.util.spec_from_file_location(
        "_wfmod_under_test", REPO / "server" / "tools" / "workflow.py")
    wfmod = importlib.util.module_from_spec(spec)
    sys.modules["_wfmod_under_test"] = wfmod
    spec.loader.exec_module(wfmod)
    faces = {"templates": {"kix-studio": {
        "name": "Kix", "lane": "worktree", "workspace_dir": False,
        "stages": [{"id": "s1", "role": "developer", "name": "一",
                    "acceptance": ["a"]}]}}}
    # 内置 dev-lane：yaml 在 → 照旧（零行为变化）
    wf = ticket._template_view("dev-lane", wfmod, None)
    assert wf["lane"] == "worktree" and wf["stages"][0]["role"]
    # 外置 id：无 yaml → 权威面视图
    wf = ticket._template_view("kix-studio", wfmod, faces)
    assert wf["lane"] == "worktree" and wf["stages"][0]["role"] == "developer"
    assert wf["stages"][0]["acceptance"] == ["a"]
    # 回执无视图 → fail-closed 点名（不再裸「模板不存在」半截）
    with pytest.raises(ValueError, match="权威模板面回执无该模板定义视图"):
        ticket._template_view("kix-studio", wfmod, {"templates": {}})
    # lane 非法 / 段表缺失 → fail-closed 点名
    bad = {"templates": {"kix-studio": {"lane": "nope", "stages": []}}}
    with pytest.raises(ValueError, match="lane 非法"):
        ticket._template_view("kix-studio", wfmod, bad)
    bad2 = {"templates": {"kix-studio": {"lane": "main", "stages": []}}}
    with pytest.raises(ValueError, match="缺最小段表"):
        ticket._template_view("kix-studio", wfmod, bad2)
