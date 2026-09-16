"""t260915-20 单测：巡检分项目建模（声明项目身份 + 起票 ProjectKey SA + repo_root
按项目注册表解析 + 无主守卫 + sign 闸项目面）。

覆盖（对应方案 §2.9）：
  - decl：实例身份必填（enabled+disabled 两腿）/形状/未知键仍拒/计数源 project_key
    不受影响/身份×计数源双键并存不串键/负腿事由次序（校验链位次钉死）；
  - shared.resolve_project_root：空 key/未知 key/env SANDBAR_PROJECTS_DIR 注册表根/
    resolve_epics_dir 复用回归；
  - trigger.resolve_repo_root 三腿 precedence + _schedule_action builder 纯面
    （payload 含 project_key/repo_root、typed_search_attributes 含 ProjectKey）；
  - watcher 串键回归钉（身份 A≠计数源 B → 归 A）；
  - flow：无主守卫两腿、sign target 解析链三腿、input 缺省兼容（老 payload 解码安全）；
  - 真源 inspection.yaml 迁移自检（四实例全带身份=sandbar）。
全程禁网络/真 Temporal；temporalio 类型只走 builder 纯构造（venv 内可跑）。
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl  # noqa: E402
import inspection_flow as flow  # noqa: E402

VALID = """
schema: v1
instances:
  - id: inst-a
    enabled: true
    project_key: proj-a
    schedule:
      kind: cron
      cron: 0 9 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: inst-b
    enabled: false
    project_key: proj-b
    schedule:
      kind: cron
      cron: 0 10 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


# ---------- decl：实例级身份必填（fail-closed） ----------

def _no_identity(enabled: str) -> str:
    return ("""
schema: v1
instances:
  - id: nopk-inst
    enabled: %s
    schedule:
      kind: cron
      cron: 0 7 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % enabled)


def test_identity_required_enabled_instance():
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(_no_identity("true"))
    msg = str(ei.value)
    assert "nopk-inst" in msg and "project_key" in msg


def test_identity_required_disabled_placeholder_too():
    # 占位豁免惯例（schedule.source/n 只在 enabled 必填）不适用身份字段：
    # 无身份的占位实例=无主票预定席
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(_no_identity("false"))
    msg = str(ei.value)
    assert "nopk-inst" in msg and "project_key" in msg


def test_identity_shape_rejected_names_instance():
    text = VALID.replace("project_key: proj-a", "project_key: Bad_Key", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    msg = str(ei.value)
    assert "inst-a" in msg and "project_key" in msg


def test_identity_lands_in_instance_and_spec():
    d = decl.parse_decl_text(VALID)
    assert d.instance("inst-a").instance_project_key == "proj-a"
    assert d.instance("inst-b").instance_project_key == "proj-b"
    specs = {s["instance_id"]: s for s in decl.build_schedule_specs(d)}
    # specs 只含启用实例（既有语义不变），身份键与 instance_id 一一同位
    assert set(specs) == {"inst-a"}
    assert specs["inst-a"]["instance_project_key"] == "proj-a"


def test_count_source_key_untouched_by_identity():
    # 计数 kind 双键并存：schedule.project_key=计数源（B）、实例 project_key=身份（A）
    # → specs 两键各归各位不串键（R2 串键教训的解析面回归钉）
    text = (VALID.replace("      cron: 0 9 * * 1",
                          "      cron: 0 9 * * 1\n      n: 20\n"
                          "      source: archive-dir\n      project_key: count-src-b", 1)
            .replace("kind: cron", "kind: race-first", 1))
    d = decl.parse_decl_text(text)
    it = d.instance("inst-a")
    assert it.kind == "race-first"
    assert it.instance_project_key == "proj-a"          # 身份归身份
    assert it.project_key == "count-src-b"              # 计数源归计数源
    spec = {s["instance_id"]: s for s in decl.build_schedule_specs(d)}["inst-a"]
    assert spec["instance_project_key"] == "proj-a"
    assert spec["project_key"] == "count-src-b"


def test_cron_identity_and_no_count_key_mixup():
    # cron 实例（无计数面）：身份在位、计数源键为空——两键语义互不污染
    d = decl.parse_decl_text(VALID)
    it = d.instance("inst-a")
    assert it.instance_project_key == "proj-a" and it.project_key == ""


def test_error_order_identity_checked_last():
    # 负腿事由次序钉位：project_key 校验在字段链**最后**——既有事由照旧先爆，
    # 断言语义零偷换（R4）
    base = _no_identity("true")
    # ① 缺身份 + 缺计数 source（计数 kind）→ 报 source 不报身份
    t1 = base.replace("kind: cron\n      cron: 0 7 * * *", "kind: every-n-tickets\n      n: 20")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(t1)
    assert "source" in str(ei.value) and "project_key（实例级项目身份" not in str(ei.value)
    # ② 缺身份 + 未知 kind → 报 kind
    t2 = base.replace("kind: cron", "kind: lunar-phase")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(t2)
    assert "lunar-phase" in str(ei.value)
    # ③ 缺身份 + 未知实例字段 → 报未知实例字段
    t3 = base.replace("    enabled: true", "    enabled: true\n    face: test")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(t3)
    assert "未知实例字段" in str(ei.value)


def test_real_decl_all_instances_have_identity():
    # 迁移④：真源四实例显式归属 sandbar（enabled 与否都不豁免）
    # t260916-02：真源声明迁仓根 <repo>/inspection.yaml（路径换，断言照旧=零回归锚）
    d = decl.load_inspection_decl(POC.parent.parent / "inspection.yaml")
    for it in d.instances:
        assert it.instance_project_key == "sandbar", it.id
    specs = decl.build_schedule_specs(d)
    assert all(s["instance_project_key"] == "sandbar" for s in specs)


# ---------- 注册表夹具（shared per-key 条目，env 注入） ----------

def _write_registry_entry(root: Path, key: str, home: Path) -> Path:
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    f = d / "project.yaml"
    f.write_text("\n".join([
        "# t260915-20 单测夹具注册条目", "schema: v1", "project:",
        "  - key: %s" % key, "    name: Fixture %s" % key, "    dirs:",
        "      - %s" % home,
    ]) + "\n", encoding="utf-8")
    return f


@pytest.fixture()
def fixture_registry(tmp_path, monkeypatch):
    reg = tmp_path / "projects"
    reg.mkdir()
    homes = {"proj-a": tmp_path / "home-a", "proj-b": tmp_path / "home-b"}
    for k, h in homes.items():
        h.mkdir()
        _write_registry_entry(reg, k, h)
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    return {"root": reg, "homes": homes}


# ---------- shared.resolve_project_root ----------

def test_resolve_project_root_empty_key_raises(fixture_registry):
    # 比先例 resolve_epics_dir 更严：**无空 key 回落腿**（静默回落引擎仓=本票要杀的族）
    from shared import resolve_project_root
    with pytest.raises(ValueError, match="项目身份为空"):
        resolve_project_root("")
    with pytest.raises(ValueError, match="项目身份为空"):
        resolve_project_root(None)


def test_resolve_project_root_unknown_key_names_registry(fixture_registry):
    from shared import resolve_project_root
    with pytest.raises(ValueError) as ei:
        resolve_project_root("ghost-key")
    msg = str(ei.value)
    assert "ghost-key" in msg and "proj-a" in msg   # 点名未知 key 与在册清单


def test_resolve_project_root_resolves_dirs0(fixture_registry):
    from shared import resolve_project_root
    got = resolve_project_root("proj-a")
    assert str(got) == str(fixture_registry["homes"]["proj-a"])


def test_resolve_project_root_env_read_fresh(fixture_registry, monkeypatch, tmp_path):
    # 注册表根每次现读（registry_root 先例）：env 改指新根立即生效
    from shared import resolve_project_root
    reg2 = tmp_path / "projects2"
    home2 = tmp_path / "home-c"
    home2.mkdir()
    _write_registry_entry(reg2, "proj-c", home2)
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg2))
    assert str(resolve_project_root("proj-c")) == str(home2)


def test_resolve_epics_dir_regression_via_shared_resolver(fixture_registry, monkeypatch):
    # resolve_epics_dir 重构为消费 resolve_project_root：key 面同一 dirs[0] 取法；
    # env/空 key 回落腿行为不变（t260907-07 既有钉住）
    from shared import resolve_epics_dir, EPICS_DIR
    monkeypatch.delenv("SANDBAR_EPICS_DIR", raising=False)
    assert str(resolve_epics_dir("proj-a")) == \
        str(fixture_registry["homes"]["proj-a"] / "notes" / "epics")
    assert resolve_epics_dir("") == EPICS_DIR          # 空 key 引擎锚回落腿（epic 侧既有语义）
    monkeypatch.setenv("SANDBAR_EPICS_DIR", "/tmp/epics-override")
    assert str(resolve_epics_dir("proj-a")) == "/tmp/epics-override"


# ---------- trigger：resolve_repo_root 三腿 + _schedule_action builder ----------

SPEC = {"instance_id": "inst-a", "workflow": "InspectionPeriodicWorkflow",
        "scan_face": "doc", "cron": "0 9 * * 1", "n": 0, "source": "",
        "project_key": "", "instance_project_key": "proj-a",
        "suite": "", "tz": "", "template": "inspection-lite", "overlap": "SKIP"}


def test_resolve_repo_root_explicit_leg_wins():
    from inspection_trigger import resolve_repo_root
    assert resolve_repo_root(SPEC, "/explicit/root") == "/explicit/root"
    # explicit 优先于身份解析（隔离台/运维旁路，不触注册表）


def test_resolve_repo_root_identity_leg_uses_registry(fixture_registry):
    from inspection_trigger import resolve_repo_root
    assert resolve_repo_root(dict(SPEC), "") == \
        str(fixture_registry["homes"]["proj-a"])


def test_resolve_repo_root_identity_leg_unknown_key_named(fixture_registry):
    from inspection_trigger import resolve_repo_root
    bad = dict(SPEC, instance_project_key="ghost-key")
    with pytest.raises(ValueError) as ei:
        resolve_repo_root(bad, "")
    assert "ghost-key" in str(ei.value)


def test_resolve_repo_root_defense_leg_raises():
    # ③ 防御腿：解析层已必填身份，正常不可达；可达即旁路绕过声明面——绝不静默回落
    from inspection_trigger import resolve_repo_root
    with pytest.raises(ValueError, match="无项目身份"):
        resolve_repo_root({"instance_id": "x", "instance_project_key": ""}, "")


def test_schedule_action_builder_payload_and_sa():
    # t260916-02：action 改指 spawner（InspectionPeriodicSpawnWorkflow，id=
    # inspection-spawn-<实例>）——Schedule 的静态参数铸不了「起票瞬间分配」的 t 形号，
    # 期号/票号/声明决议全部延迟到起票时刻（spawn_inspection_period activity）。
    from inspection_trigger import _schedule_action
    action = _schedule_action(dict(SPEC), "tq-1", "/explicit/root")
    assert action.id == "inspection-spawn-inst-a"
    assert action.task_queue == "tq-1"
    assert len(action.args) == 1
    inp = action.args[0]
    assert inp.instance_id == "inst-a"
    assert inp.face == "doc"                       # 声明透传（t260913-02 语义不变）
    assert inp.repo_root == "/explicit/root"       # explicit 腿
    assert inp.project_key == "proj-a"             # payload 显式填身份（R3）
    assert getattr(inp, "period", "") == ""        # spawner 输入无期号（起票时刻铸取）
    assert getattr(inp, "decl_path", "x") == ""    # cron 形态不钉路径（改声明即改行为）
    pairs = {p.key.name: p.value for p in action.typed_search_attributes}
    assert pairs.get("ProjectKey") == "proj-a"     # SA 盖章（R1/R2 核心）


def test_schedule_action_builder_registry_repo_root(fixture_registry):
    # 不带 --repo-root 的调度（现役三实例的常规形态）→ repo_root 落注册表主目录，
    # 不再是空（空=worker 缺省回落引擎仓，正是本票要杀的静默用错仓）
    from inspection_trigger import _schedule_action
    action = _schedule_action(dict(SPEC), "tq-1", "")
    assert action.args[0].repo_root == str(fixture_registry["homes"]["proj-a"])


# ---------- flow/activities 装配面：守卫/闸/缺省兼容/串键 ----------

def test_inspection_input_project_key_default_safe():
    # 老 history 重放安全：不带新键构造=缺省空（face 同款纪律）
    inp = flow.InspectionPeriodicInput(instance_id="i", period="20260915")
    assert inp.project_key == ""


def test_watcher_input_identity_default_and_distinct_fields():
    inp = flow.InspectionWatcherInput(instance_id="i", n=5, project_key="count-src")
    assert inp.instance_project_key == ""          # 缺省空=旧 payload 解码安全
    # 两字段并存且语义独立：project_key=计数源、instance_project_key=身份
    inp2 = flow.InspectionWatcherInput(instance_id="i", n=5,
                                       project_key="count-src",
                                       instance_project_key="inst-id")
    assert inp2.project_key == "count-src" and inp2.instance_project_key == "inst-id"


def test_watcher_identity_key_wins_over_count_source():
    # R2 串键回归钉：args 同时混入身份键与计数源键 → 只认身份键（A≠B → 归 A）
    import activities
    mixed = {"instance_id": "i", "instance_project_key": "inst-a",
             "project_key": "count-b"}
    assert activities.inspection_period_identity(mixed) == "inst-a"
    # 旧 watcher payload（无身份键）→ 空（过渡窗：票面空 project，双空撞守卫=blocked）
    assert activities.inspection_period_identity({"instance_id": "i"}) == ""


def test_unowned_guard_reason_legs():
    reason = flow.unowned_guard_reason("", "")
    assert "无项目身份" in reason and "schedule-up" in reason   # blocked 点名+处置入口
    assert flow.unowned_guard_reason("proj-a", "") == ""        # 有身份 → 放行
    assert flow.unowned_guard_reason("", "/repo") == ""         # 有 repo_root（解析链走过）→ 放行


def test_sign_target_project_chain():
    assert flow.sign_target_project("sa-p", "payload-p") == "sa-p"   # SA 优先
    assert flow.sign_target_project("", "payload-p") == "payload-p"  # payload 回退
    assert flow.sign_target_project("", "") == ""                    # 双空=现状恒放行


def test_project_patch_id_distinct_and_set():
    # 版本门独立：PROJECT_PATCH_ID 与 SUITE_PATCH_ID 是两个标记（老 history 两向安全）
    assert flow.PROJECT_PATCH_ID and flow.PROJECT_PATCH_ID != flow.SUITE_PATCH_ID


# ---------- 运维通道回执面（decl 子命令离线） ----------

def test_decl_receipt_reports_identity_fields():
    # C1：decl 回执（纯解析面）列 spec 含 instance_project_key——注册表 IO 值不在此面
    import json
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_trigger.py"), "decl",
         "--decl-path", str(POC.parent.parent / "inspection.yaml")],
        capture_output=True, text=True, timeout=60, cwd=str(POC))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    for inst in payload["result"]["instances"]:
        assert inst["instance_project_key"] == "sandbar", inst["id"]
    for spec in payload["result"]["schedule_specs"]:
        assert spec["instance_project_key"] == "sandbar", spec["instance_id"]
