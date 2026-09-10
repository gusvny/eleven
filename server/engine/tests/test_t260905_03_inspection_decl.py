"""t260905-03 票①：巡检声明解析/校验单测（inspection_decl + trigger 离线面）。

覆盖：正常两实例位解析；行为级 specs 只含启用实例（M1 解析级证据）；未接线 kind
fail-closed（M2，报错点名已接线清单）；畸形输入逐形态（根/键/值/子集文法）；
default_decl_path env 覆盖；inspection_trigger import 级用例（M5）+ decl 子命令离线跑。
全程禁网络/真 Temporal；纯标准库（decl 解析器零依赖）。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl  # noqa: E402

VALID = """
# 注释行与空行应被忽略

schema: v1
instances:
  - id: test-face
    face: test
    enabled: true
    schedule:
      kind: cron
      cron: 0 9 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: doc-face
    face: doc
    enabled: false
    schedule:
      kind: cron
      cron: 0 10 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


# ---------- 正常面 ----------

def test_parse_valid_two_instances():
    d = decl.parse_decl_text(VALID)
    assert [i.id for i in d.instances] == ["test-face", "doc-face"]
    assert d.instances[0].enabled is True and d.instances[1].enabled is False
    assert d.instances[0].cron == "0 9 * * 1"


def test_schedule_specs_only_enabled_instances():
    """行为级（M1 解析级半边）：禁用实例产出为零——触发面只认 specs。"""
    d = decl.parse_decl_text(VALID)
    specs = decl.build_schedule_specs(d)
    assert [s["instance_id"] for s in specs] == ["test-face"]
    assert specs[0]["overlap"] == "SKIP" and specs[0]["cron"] == "0 9 * * 1"


def test_real_decl_file_loads_and_test_face_enabled():
    d = decl.load_inspection_decl(POC / "inspection.yaml")
    assert d.schema == "v1"
    assert d.instance("test-face").enabled is True
    assert d.instance("doc-face").enabled is False
    assert [s["instance_id"] for s in decl.build_schedule_specs(d)] == ["test-face"]


def test_default_decl_path_env_override(monkeypatch, tmp_path):
    p = tmp_path / "decl.yaml"
    p.write_text(VALID, encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECTION_DECL", str(p))
    assert decl.default_decl_path() == p
    assert decl.load_inspection_decl().instance("test-face") is not None


# ---------- M2：未接线 kind ----------

def test_enabled_instance_unwired_kind_rejected_names_wired():
    text = VALID.replace("kind: cron\n      cron: 0 9 * * 1", "kind: every-n-tickets\n      n: 20", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    msg = str(ei.value)
    assert "every-n-tickets" in msg and "cron" in msg  # 点名未接线 kind 与已接线清单


def test_disabled_instance_unwired_kind_allowed_as_placeholder():
    text = VALID.replace("kind: cron\n      cron: 0 10 * * 1", "kind: race-first\n      n: 20")
    d = decl.parse_decl_text(text)
    assert d.instance("doc-face").kind == "race-first"
    # 禁用实例不触发，占位合法；启用实例照常出 spec
    assert [s["instance_id"] for s in decl.build_schedule_specs(d)] == ["test-face"]


def test_unknown_kind_rejected_names_known():
    text = VALID.replace("kind: cron", "kind: lunar-phase", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "lunar-phase" in str(ei.value) and "every-n-tickets" in str(ei.value)


def test_unknown_workflow_rejected():
    text = VALID.replace("workflow: InspectionPeriodicWorkflow", "workflow: NoSuchWorkflow", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "InspectionPeriodicWorkflow" in str(ei.value)


# ---------- 畸形输入逐形态（fail-closed，绝无缺省回落） ----------

def _reject(text_or_obj, frag=None):
    with pytest.raises(decl.DeclError) as ei:
        if isinstance(text_or_obj, str):
            decl.parse_decl_text(text_or_obj)
        else:
            decl.decl_from_mapping(text_or_obj)
    if frag:
        assert frag in str(ei.value), "报错应点名 %r，got %r" % (frag, str(ei.value))


def test_malformed_roots():
    _reject("foo\n", "无法识别的行形态")                                # 非 key 行
    _reject("not a mapping at all: [\n", "键非法")                     # 键含空格
    _reject({"schema": "v1"}, "instances")
    _reject({"schema": "v2", "instances": []}, "schema")
    _reject({"schema": "v1", "instances": []}, "非空列表")
    _reject({"schema": "v1", "instances": "x"}, "列表")
    _reject({"schema": "v1", "instances": [], "extra": 1}, "未知顶层键")
    _reject([], "根必须是映射")


def _instance(**over):
    base = {"id": "test-face", "face": "test", "enabled": "true",
            "schedule": {"kind": "cron", "cron": "0 9 * * 1"},
            "workflow": "InspectionPeriodicWorkflow", "template": "inspection-lite"}
    base.update(over)
    return {"schema": "v1", "instances": [base]}


def test_malformed_instance_fields():
    _reject(_instance(id=None), "id")
    _reject(_instance(id="Bad_Slug"), "slug")
    _reject(_instance(face=None), "face")
    _reject(_instance(enabled="yes"), "enabled")
    _reject(_instance(schedule=None), "schedule")
    _reject(_instance(schedule={"kind": "cron"}), "cron")
    _reject(_instance(schedule={"kind": "cron", "cron": "0 9"}), "cron")
    _reject(_instance(schedule={"kind": "cron", "cron": "0 9 * * 99"}), "cron")
    _reject(_instance(schedule={"kind": "cron", "cron": "0 9 * * 1", "oops": 1}), "未知字段")
    _reject(_instance(workflow=None), "workflow")
    _reject(_instance(template=None), "template")
    _reject(_instance(extra=1), "未知实例字段")
    _reject(_instance(schedule={"kind": "every-n-tickets"}), "n")


def test_malformed_subset_grammar():
    _reject("schema: v1\n\tinstances: []", "tab")                    # tab 缩进
    _reject("schema: v1\nfoo\n", "无法识别的行形态")                   # 非 key 行
    _reject("schema: v1\nschema: v1", "键重复")                       # 顶层键重复
    _reject("schema: v1\ninstances:\n    - id: a\n      id: b", "键重复")  # 实例键重复
    _reject("schema: v1\ninstances:", "开了子结构但无内容")            # 开键无内容
    _reject("schema: v1\ninstances:\n  - id: a\n   enabled: true", "缩进")  # 续键缩进非法


def test_duplicate_instance_ids_rejected():
    d = decl.decl_from_mapping(_instance())
    dup = {"schema": "v1", "instances": [d.instances and None, None]}  # 占位不走向此路
    text = VALID  # 两实例 id 不同，合法
    decl.parse_decl_text(text)
    clone = decl.decl_from_mapping(_instance())
    both = {"schema": "v1", "instances": [_instance()["instances"][0], _instance()["instances"][0]]}
    _reject(both, "id 重复")


# ---------- M5：trigger 入口 import 级 + decl 子命令离线 ----------

def test_inspection_trigger_import_level():
    import inspection_trigger  # noqa: F401——新入口至少被 import 编译（无单测 import 则永不编译）


def test_trigger_decl_op_offline_real_file():
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_trigger.py"), "decl"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    ids = [i["id"] for i in payload["result"]["instances"]]
    # t260910-09 票②：新增 mechanism-face/simplify-face 占位实例（enabled=false 不进 schedule_specs）
    assert ids == ["test-face", "doc-face", "mechanism-face", "simplify-face"]
    assert [s["instance_id"] for s in payload["result"]["schedule_specs"]] == ["test-face"]


def test_trigger_decl_op_malformed_file_single_line_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: v9\ninstances: []\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_trigger.py"), "decl", "--decl-path", str(bad)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False and "schema" in payload["error"]


def test_enabled_spec_helper_offline_gates():
    """触发面 fail-closed 先于网络：未启用实例/未声明实例/畸形期号都就地拒绝。"""
    from inspection_trigger import _enabled_spec, _valid_period
    spec = _enabled_spec(POC / "inspection.yaml", "test-face")
    assert spec["workflow"] == "InspectionPeriodicWorkflow"
    with pytest.raises(ValueError, match="未启用"):
        _enabled_spec(POC / "inspection.yaml", "doc-face")
    with pytest.raises(ValueError, match="未在声明"):
        _enabled_spec(POC / "inspection.yaml", "nope")
    assert _valid_period("20260905") is None
    assert _valid_period("2026-09-05") is not None
    assert _valid_period("20261399") is not None  # 非真实日历日


# ---- M5：inspection_trigger import 级用例（顶层零三方依赖即可装载；py-compile 预案作废）----

def test_trigger_module_imports_without_third_party():
    """运维通道 CLI 顶层只准依赖 stdlib+inspection_decl：被 import 即证装载面干净。"""
    import inspection_trigger  # noqa: F401


def test_trigger_valid_period_rejects_impossible_dates():
    import inspection_trigger as trig
    assert trig._valid_period("20260906") is None            # 合法日历日 → None
    for bad in ("20261301", "20260230", "2026091", "2026090a", ""):
        err = trig._valid_period(bad)
        assert err, bad   # 真实日历日 fail-closed：非法/不存在的日子都要报错串


def test_trigger_subcommands_wired():
    import inspection_trigger as trig
    parser = trig.build_parser() if hasattr(trig, "build_parser") else None
    if parser is None:
        import inspection_trigger as t2
        assert hasattr(t2, "cmd_trigger") and hasattr(t2, "cmd_sign") \
            and hasattr(t2, "cmd_decl") and hasattr(t2, "cmd_describe") \
            and hasattr(t2, "cmd_schedule_up")
