"""t260925-16 KI-121 工人启动面——活动双注册收口单测。

覆盖（对应方案四处收口 + review_plan 意见）：
  - 事故形态加载期拒收：外置模板 agent 段 id `ai-review` 撞引擎退役段注册活动
    → workflows_v2 合并期「活动名撞引擎注册面」模板级拒收，点名活动名×双方来源，
    注册表（类面/名面/段 id 面全撤）不再产出撞名段 activity；
  - 干净外置模板照常接受（cs- 前缀形态）＝外置模板特性不破（票面要求④）；
  - worker 注册前置断言 fail-loud：撞名报错点名活动名＋两个来源模块，名字按
    temporalio 注册定义名取（review 意见 3）；
  - 模块身份去重：同装载名二次扫描复用模块对象、不二次执行（需求①）；
  - 拒收路径 sys.modules 全终态回收（不留半态模块）；
  - 检查不可用=全部外置模板 fail-closed 拒收（不静默放行）；
  - worker_dryrun CLI：桩根自持（不读 ~/.sandbar、不连 server、不 Client.connect），
    干净注册根绿 / 事故形态红（review 意见 4）＝合并闸「工人可启动 dry-run」。

夹具=临时注册根（SANDBAR_PROJECTS_DIR 注入，shared.registry_root 每次现读）＋
tmp 项目目录下的桩模板模块；不依赖真 nusuyou 仓、不依赖宿主声明状态。
"""
import collections
import importlib
import json
import pathlib
import subprocess
import sys

import pytest

import shared
import project_templates as pt

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent

GOOD_TMPL = '''TEMPLATE_ID = "{tid}"
TEMPLATE_NAME = "测试模板"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class {cls}(TicketWorkflowBase):
    STAGES = (Stage(id="{stage1}", name="审校", role="integration", next="s2", acceptance=("a",)),
              Stage(id="s2", name="二", role="developer", next="", acceptance=("b",)))
    PATCH_ID = "{patch}"
    TEMPLATE_ID = "{tid}"
    TEMPLATE_NAME = "测试模板"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''

BROKEN_TMPL = 'TEMPLATE_ID = "broken-tmpl"\nimport nonexistent_module_xyz\n'


@pytest.fixture(autouse=True)
def _restore_shared_tables():
    """类面合并/reconcile 会回写 shared 全局两表——逐用例快照恢复，防跨用例污染。"""
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


def _make_project(root: pathlib.Path, key: str, modules: dict) -> pathlib.Path:
    """在临时注册根建条目（契约①a schema v1，与 test_t260924_04 同款夹具）＋桩模块。"""
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


def _reload_workflows_v2(monkeypatch, root: pathlib.Path):
    """桩根注入＋重载 workflows_v2（合并/过滤在 import 期跑——测的就是这条真链）。"""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    import workflows_v2 as wv
    return importlib.reload(wv)


# ---- ① 事故形态：段 id 撞引擎退役段注册活动 → 加载期模板级拒收 ----

def test_incident_stage_id_collision_rejected_at_load(monkeypatch, tmp_path):
    root = tmp_path / "reg"
    _make_project(root, "stubproj", {"incident_tmpl.py": GOOD_TMPL.format(
        tid="incident-tmpl", cls="IncidentTmpl", stage1="ai-review", patch="stubproj-incident-v1")})
    wv = _reload_workflows_v2(monkeypatch, root)
    # 模板整体拒收：类面/段 id 面/名面全撤
    assert "incident-tmpl" not in wv.TEMPLATE_CLASSES
    assert "incident-tmpl" not in wv.PROJECT_TEMPLATE_IDS
    assert "ai-review" not in wv.PROJECT_TEMPLATE_STAGE_IDS
    assert "incident-tmpl" not in shared.TEMPLATE_CLASS_NAMES
    # 拒收记录点名：检查名＋活动名＋引擎来源＋来件方
    hits = [r for r in shared.PROJECT_TEMPLATE_REJECTIONS
            if r.get("check") == "activity name collides with the engine registry face"]
    assert hits, shared.PROJECT_TEMPLATE_REJECTIONS
    r = hits[-1]
    assert r["stage"] == "ai-review"
    assert r["project"] == "stubproj" and r["module"] == "mods/incident_tmpl.py"
    assert "agent_activities" in r["detail"]
    # 注册面组合零撞名（真实 worker 启动路径，同源断言）
    acts = wv and __import__("worker").compose_worker_activities(wv.PROJECT_TEMPLATE_STAGE_IDS)
    names = [a.__temporal_activity_definition.name for a in acts]
    assert [n for n, c in collections.Counter(names).items() if c > 1] == []


# ---- ② 干净外置模板照常接受（特性不破）＋组合唯一 ----

def test_clean_external_template_accepted_and_composition_unique(monkeypatch, tmp_path):
    root = tmp_path / "reg"
    _make_project(root, "stubproj", {"clean_tmpl.py": GOOD_TMPL.format(
        tid="clean-tmpl", cls="CleanTmpl", stage1="cs-clean-review",
        patch="stubproj-clean-v1")})
    wv = _reload_workflows_v2(monkeypatch, root)
    assert "clean-tmpl" in wv.TEMPLATE_CLASSES
    assert "cs-clean-review" in wv.PROJECT_TEMPLATE_STAGE_IDS
    worker = __import__("worker")
    acts = worker.compose_worker_activities(wv.PROJECT_TEMPLATE_STAGE_IDS)
    names = [a.__temporal_activity_definition.name for a in acts]
    assert [n for n, c in collections.Counter(names).items() if c > 1] == []


# ---- ③ worker 注册前置断言 fail-loud 点名双方（temporalio 定义名口径） ----

def test_compose_worker_activities_raises_named_on_collision(monkeypatch):
    import worker as w

    def _fake_activity(name):
        def _fn():
            pass
        _fn.__temporal_activity_definition = type("D", (), {"name": name})()
        return _fn

    monkeypatch.setattr(w, "ALL_ACTIVITIES", [])
    monkeypatch.setattr(w, "ALL_AGENT_ACTIVITIES", [_fake_activity("zz-dup-name")])
    with pytest.raises(ValueError) as ei:
        w.compose_worker_activities(("zz-dup-name",))
    msg = str(ei.value)
    assert "zz-dup-name" in msg            # 点名活动名
    assert "agent_activities" in msg and "agent_activities" in msg  # 双方来源模块
    assert "KI-121" in msg                 # 追溯锚


def test_compose_worker_activities_green_on_clean(monkeypatch):
    import worker as w
    acts = w.compose_worker_activities(w.PROJECT_TEMPLATE_STAGE_IDS)
    names = [a.__temporal_activity_definition.name for a in acts]
    assert [n for n, c in collections.Counter(names).items() if c > 1] == []


# ---- ④ 模块身份去重：同装载名复用、不二次执行（需求①） ----

def test_module_identity_dedup_on_rescan(monkeypatch, tmp_path):
    root = tmp_path / "reg"
    _make_project(root, "stubproj", {"dedup_tmpl.py": GOOD_TMPL.format(
        tid="dedup-tmpl", cls="DedupTmpl", stage1="cs-dedup-review",
        patch="stubproj-dedup-v1")})
    mod_path = root / "stubproj" / "mods" / "dedup_tmpl.py"
    assert mod_path.is_file()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    r1 = pt.scan(shared.perkey_projects_root, lambda: ["stubproj"],
                 lambda k: shared.project_paths(k), ENGINE_DIR,
                 {}, {}, import_classes=True)
    cls1 = r1.classes["dedup-tmpl"]
    mod_name = r1.module_names["dedup-tmpl"]
    mod1 = sys.modules[mod_name]
    r2 = pt.scan(shared.perkey_projects_root, lambda: ["stubproj"],
                 lambda k: shared.project_paths(k), ENGINE_DIR,
                 {}, {}, import_classes=True)
    # 二次扫描：模块对象恒等（同装载名复用，不二次执行）、类对象恒等（同模块身份）
    assert sys.modules[mod_name] is mod1
    assert r2.classes["dedup-tmpl"] is cls1
    assert not r2.rejections, r2.rejections


# ---- ⑤ 拒收路径 sys.modules 全终态回收 ----

def test_rejection_paths_clean_sys_modules(monkeypatch, tmp_path):
    root = tmp_path / "reg"
    # ⑤a import 抛错：_load_class 内部回收
    _make_project(root, "p1", {"boom_tmpl.py": BROKEN_TMPL})
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    pt.scan(shared.perkey_projects_root, lambda: ["p1"],
            lambda k: shared.project_paths(k), ENGINE_DIR,
            {}, {}, import_classes=True)
    assert "sandbar_ext_p1_boom_tmpl" not in sys.modules
    # ⑤b 形状拒收（缺 STAGES）：scan 层回收
    no_stages = GOOD_TMPL.format(tid="ns-tmpl", cls="NsTmpl", stage1="cs-ns",
                                 patch="p2-ns-v1").replace(
        'STAGES = (Stage(id="cs-ns"', 'STAGES = None and (Stage(id="cs-ns"')
    root2 = tmp_path / "reg2"
    _make_project(root2, "p2", {"ns_tmpl.py": no_stages})
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root2))
    res = pt.scan(shared.perkey_projects_root, lambda: ["p2"],
                  lambda k: shared.project_paths(k), ENGINE_DIR,
                  {}, {}, import_classes=True)
    assert res.rejections, "缺 STAGES 应拒收"
    assert "sandbar_ext_p2_ns_tmpl" not in sys.modules


# ---- ⑥ 检查不可用 = 全部外置模板 fail-closed 拒收（不静默放行） ----

def test_unavailable_engine_face_fail_closed(monkeypatch, tmp_path):
    import workflows_v2 as wv
    monkeypatch.setattr(wv, "_engine_activity_name_sources",
                        lambda: (_ for _ in ()).throw(RuntimeError("no face")))
    res = pt.ScanResult()
    res.accepted["t1"] = {"class_name": "T1", "display": "", "project": "p", "module": "m"}
    res.classes["t1"] = type("T1", (), {"STAGES": ()})
    res.module_names["t1"] = "sandbar_ext_p_m"
    res.module_deps["t1"] = frozenset({"shared"})
    wv._filter_activity_name_collisions(res)
    assert res.classes == {} and res.accepted == {}
    checks = [r["check"] for r in res.rejections]
    assert "activity-name uniqueness check unavailable" in checks


# ---- ⑦ worker_dryrun CLI：桩根自持，绿/红两态 ----

def _run_cli(root: pathlib.Path):
    env = dict(**__import__("os").environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env.pop("SANDBAR_PROJECTS_YAML", None)
    return subprocess.run([sys.executable, str(ENGINE_DIR / "worker_dryrun.py")],
                          capture_output=True, text=True, env=env, timeout=120)


def test_dryrun_cli_green_on_empty_registry_root(tmp_path):
    rc = _run_cli(tmp_path / "empty-root")
    assert rc.returncode == 0, rc.stdout + rc.stderr
    out = json.loads(rc.stdout.strip().splitlines()[-1])
    assert out["ok"] is True


def test_dryrun_cli_red_names_collision_on_incident_shape(tmp_path):
    root = tmp_path / "reg"
    _make_project(root, "stubproj", {"incident_tmpl.py": GOOD_TMPL.format(
        tid="incident-tmpl", cls="IncidentTmpl", stage1="ai-review",
        patch="stubproj-incident-v1")})
    rc = _run_cli(root)
    assert rc.returncode == 1
    # 红态不产 JSON 摘要行（机器判定面不被污染），但点名活动名与双方来源
    assert "ai-review" in rc.stdout
    assert "agent_activities" in rc.stdout
    assert not rc.stdout.strip().startswith("{")
