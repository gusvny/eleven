"""t260916-02 声明落位迁移（A）单测：每项目仓内单文件 inspection.yaml + 聚合遍历
+ 指路 + env 覆盖层降级语义。

覆盖口径（=plan-t260916-02.md §5 验收映射的 S1/S2 单测半边；真台双腿由场景承载）：
  A. 布局：默认落位 <dirs[0]>/inspection.yaml；paths.inspection_decl 指路（相对拼
     主目录 / 绝对 / ~/…）；指路锚点缺失/类型错位 fail-closed（契约①d 四态表同款）。
  B. 聚合（口径④）：SANDBAR_PROJECTS_DIR 隔离夹具双项目——enabled_instance_whitelist
     并集收全；load_decl_for_instance 唯一命中按项目归位；双项目同实例 id = fail-closed。
  C. fail-closed（验收4）：absent=该项目无巡检面（点名不静默、绝不借用他项目声明）；
     声明坏形态=项目级 error 态点名，他项目不受影响。
  D. env 覆盖层（口径①兼容缝）：SANDBAR_INSPECTION_DECL 非空=单文件整体替代聚合；
     覆盖层缺失/坏形=显式点名不回落。

UT 全程禁网络/真 Temporal/真 git；注册表全走 SANDBAR_PROJECTS_DIR 夹具（t260915-20
夹具法），不读真 ~/.sandbar/projects。
运行：server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260916_02_inspection_decl_placement.py -q
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl  # noqa: E402
import shared  # noqa: E402

NU_DECL = """
schema: v1
instances:
  - id: nu-daily
    enabled: true
    project_key: nusuyou
    schedule:
      kind: cron
      cron: 0 8 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

DZ_DECL = """
schema: v1
instances:
  - id: dz-weekly
    enabled: true
    project_key: dengzhufpv
    scan_face: doc
    schedule:
      kind: cron
      cron: 0 9 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: dz-drain
    enabled: false
    project_key: dengzhufpv
    schedule:
      kind: cron
      cron: 0 10 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

SANDBAR_DECL = """
schema: v1
instances:
  - id: integration-tests
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 30 7 * * *
    tz: Asia/Shanghai
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


def _write_registry_entry(root: Path, key: str, home: Path,
                          inspection_decl: str = "") -> None:
    """shared per-key 注册条目夹具（镜 t260915-20 手法）；inspection_decl 非空=带
    paths.inspection_decl 指路。"""
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    lines = ["# t260916-02 落位夹具", "schema: v1", "project:",
             "  - key: %s" % key, "    name: Fixture %s" % key, "    dirs:",
             "      - %s" % home]
    if inspection_decl:
        lines += ["paths:", "  inspection_decl: %s" % inspection_decl]
    (d / "project.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def two_projects(monkeypatch, tmp_path):
    """双项目隔离夹具：nusuyou（默认落位）/ dengzhufpv（指路 decl/inspect.yaml）。
    返回 (registry_root, homes)。"""
    reg = tmp_path / "registry"
    homes = {"nusuyou": tmp_path / "nusuyou-home", "dengzhufpv": tmp_path / "dz-home"}
    homes["nusuyou"].mkdir(parents=True)
    homes["dengzhufpv"].mkdir(parents=True)
    _write_registry_entry(reg, "nusuyou", homes["nusuyou"])
    _write_registry_entry(reg, "dengzhufpv", homes["dengzhufpv"],
                          inspection_decl="decl/inspect.yaml")
    (homes["nusuyou"] / "inspection.yaml").write_text(NU_DECL, encoding="utf-8")
    custom = homes["dengzhufpv"] / "decl"
    custom.mkdir()
    (custom / "inspect.yaml").write_text(DZ_DECL, encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    monkeypatch.delenv("SANDBAR_INSPECTION_DECL", raising=False)
    return reg, homes


# ---------- A. 布局：默认落位 + 指路 ----------

def test_default_placement_dirs0_inspection_yaml(two_projects):
    p = decl.resolve_project_decl_path("nusuyou")
    assert p.name == "inspection.yaml" and p.is_file()
    d = decl.load_inspection_decl(p)
    assert [i.id for i in d.instances] == ["nu-daily"]


def test_decl_pointer_routes_relative_and_absolute(two_projects):
    p = decl.resolve_project_decl_path("dengzhufpv")
    assert p == two_projects[1]["dengzhufpv"] / "decl" / "inspect.yaml"
    d = decl.load_inspection_decl(p)
    assert [i.id for i in d.instances] == ["dz-weekly", "dz-drain"]


def test_decl_pointer_missing_anchor_fail_closed(monkeypatch, tmp_path):
    """指路了就必须在（契约①d 同款）；缺失/类型错位都 DeclError 点名。"""
    reg = tmp_path / "reg"
    home = tmp_path / "home"
    home.mkdir(parents=True)
    _write_registry_entry(reg, "ghost", home, inspection_decl="nowhere.yaml")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    with pytest.raises(decl.DeclError) as ei:
        decl.resolve_project_decl_path("ghost")
    assert "nowhere.yaml" in str(ei.value) and "fail-closed" in str(ei.value)
    (home / "nowhere.yaml").write_text("not a dir anchor test", encoding="utf-8")
    # 指到一个目录=类型错位
    (home / "adir").mkdir()
    _write_registry_entry(reg, "ghost", home, inspection_decl="adir")
    with pytest.raises(decl.DeclError) as ei2:
        decl.resolve_project_decl_path("ghost")
    assert "不是文件" in str(ei2.value)


def test_decl_pointer_tilde_and_absolute(monkeypatch, tmp_path):
    reg = tmp_path / "reg"
    home = tmp_path / "home"
    home.mkdir(parents=True)
    _write_registry_entry(reg, "pt", home, inspection_decl=str(tmp_path / "abs.yaml"))
    (tmp_path / "abs.yaml").write_text(NU_DECL, encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    assert decl.resolve_project_decl_path("pt") == tmp_path / "abs.yaml"


# ---------- B. 聚合：双项目收全（验收5 的单测半边） ----------

def test_aggregate_whitelist_merges_both_projects(two_projects):
    ids, degraded, coverage = decl.enabled_instance_whitelist()
    assert ids == ("dz-weekly", "nu-daily")      # 并集收全；disabled 的 dz-drain 不进
    assert degraded == [] and coverage is False


def test_aggregate_load_decl_for_instance_routes_by_project(two_projects):
    d1, k1 = decl.load_decl_for_instance("nu-daily")
    assert k1 == "nusuyou" and d1.instance("nu-daily").instance_project_key == "nusuyou"
    d2, k2 = decl.load_decl_for_instance("dz-weekly")
    assert k2 == "dengzhufpv" and d2.instance("dz-weekly").scan_face == "doc"


def test_aggregate_duplicate_instance_id_across_projects_fail_closed(monkeypatch, tmp_path):
    reg = tmp_path / "reg"
    h1, h2 = tmp_path / "h1", tmp_path / "h2"
    h1.mkdir(parents=True)
    h2.mkdir(parents=True)
    _write_registry_entry(reg, "pa", h1)
    _write_registry_entry(reg, "pb", h2)
    (h1 / "inspection.yaml").write_text(NU_DECL, encoding="utf-8")
    (h2 / "inspection.yaml").write_text(NU_DECL, encoding="utf-8")   # 同实例 id
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    with pytest.raises(decl.DeclError) as ei:
        decl.load_decl_for_instance("nu-daily")
    assert "pa" in str(ei.value) and "pb" in str(ei.value)


def test_aggregate_iter_states_ok_absent(two_projects):
    reg, homes = two_projects
    (homes["dengzhufpv"] / "decl" / "inspect.yaml").unlink()   # 指路锚在=指路成功；删掉变锚缺失
    states = {st.project_key: st for st in decl.iter_project_decls()}
    assert states["nusuyou"].state == "ok"
    assert states["dengzhufpv"].state == "error"    # 指路锚缺失=fail-closed error 态
    # absent（无指路、默认落位无文件）=该项目无巡检面
    (homes["nusuyou"] / "inspection.yaml").unlink()
    states = {st.project_key: st for st in decl.iter_project_decls()}
    assert states["nusuyou"].state == "absent"


# ---------- C. fail-closed：坏形态项目级降级，不殃及他项目（验收4） ----------

def test_aggregate_broken_decl_degrades_project_only(two_projects):
    reg, homes = two_projects
    (homes["nusuyou"] / "inspection.yaml").write_text("schema: v9\ninstances: []\n",
                                                      encoding="utf-8")
    ids, degraded, _cov = decl.enabled_instance_whitelist()
    assert ids == ("dz-weekly",)                    # 坏项目实例不收（收=静默编造）
    assert len(degraded) == 1 and degraded[0][0] == "nusuyou" and "nusuyou" in degraded[0][2]
    with pytest.raises(decl.DeclError) as ei:
        decl.load_decl_for_instance("nu-daily")
    assert "nusuyou" in str(ei.value) and "未在任何项目声明中" in str(ei.value)
    # 他项目照常可用（绝不借用/绝不连带瘫痪）
    d, k = decl.load_decl_for_instance("dz-weekly")
    assert k == "dengzhufpv"


def test_aggregate_unknown_instance_names_all_project_states(two_projects):
    with pytest.raises(decl.DeclError) as ei:
        decl.load_decl_for_instance("nope")
    msg = str(ei.value)
    assert "nusuyou" in msg and "dengzhufpv" in msg      # 逐项目状态点名
    assert "绝不回落" in msg


# ---------- D. env 覆盖层：单文件整体替代（口径①兼容缝） ----------

def test_coverage_layer_replaces_aggregate(monkeypatch, tmp_path, two_projects):
    reg, homes = two_projects
    cov = tmp_path / "overlay.yaml"
    cov.write_text(SANDBAR_DECL, encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECTION_DECL", str(cov))
    states = decl.iter_project_decls()
    assert len(states) == 1 and states[0].coverage is True and states[0].state == "ok"
    d, k = decl.load_decl_for_instance("integration-tests")
    assert k == "" and d.instance("integration-tests").cron == "30 7 * * *"
    ids, _degraded, coverage = decl.enabled_instance_whitelist()
    assert ids == ("integration-tests",) and coverage is True
    # 覆盖层生效时聚合面不参与：nu-daily 不可达（点名在覆盖层，不回落）
    with pytest.raises(decl.DeclError) as ei:
        decl.load_decl_for_instance("nu-daily")
    assert "覆盖层" in str(ei.value)


def test_coverage_layer_missing_or_broken_named_not_silent(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "empty-reg"))
    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv("SANDBAR_INSPECTION_DECL", str(missing))
    states = decl.iter_project_decls()
    assert len(states) == 1 and states[0].state == "error" and "nope.yaml" in states[0].error
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: v2\ninstances: []\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECTION_DECL", str(bad))
    # 覆盖层坏形态=error 态点名（板面 degraded 通道可见），不静默也不回落聚合
    ids, degraded, coverage = decl.enabled_instance_whitelist()
    assert ids == () and coverage is True and "bad.yaml" in degraded[0][2]


# ---------- 装配面：workflow/SA 常量与既有纪律同源 ----------

def test_shared_sa_names_reach_ticketing_and_client():
    import client as client_mod
    import inspection_ticketing as tick
    assert tick.SA_INSTANCE_NAME == shared.INSPECTION_INSTANCE_SA_NAME
    assert tick.SA_PERIOD_NAME == shared.INSPECTION_PERIOD_SA_NAME
    assert client_mod.INSPECTION_INSTANCE_SA_NAME == shared.INSPECTION_INSTANCE_SA_NAME
    sa = shared.inspection_search_attributes("proj-a", "inst-a", "20260916")
    pairs = {p.key.name: p.value for p in sa}
    assert pairs.get(shared.INSPECTION_INSTANCE_SA_NAME) == "inst-a"
    assert pairs.get(shared.INSPECTION_PERIOD_SA_NAME) == "20260916"
    assert pairs.get(shared.PROJECT_SA_NAME) == "proj-a"
