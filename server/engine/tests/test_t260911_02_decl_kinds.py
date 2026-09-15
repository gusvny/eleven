"""t260911-02 单测：声明扩展（计数 kind 接线 + scan_face + 新 schedule 字段）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_decl as decl

VALID = """schema: v1
instances:
  - id: cron-face
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 9 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: count-face
    enabled: true
    project_key: sandbar
    schedule:
      kind: every-n-tickets
      n: 20
      source: archive-dir
      project_key: sandbar
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


def test_wired_kinds_now_include_count_kinds():
    assert set(decl.WIRED_KINDS) == {"cron", "every-n-tickets", "race-first"}
    assert set(decl.KNOWN_KINDS) == set(decl.WIRED_KINDS)


def test_count_kind_spec_carries_source_key_face():
    specs = decl.build_schedule_specs(decl.parse_decl_text(VALID))
    by_id = {s["instance_id"]: s for s in specs}
    s = by_id["count-face"]
    assert s["source"] == "archive-dir" and s["project_key"] == "sandbar" and s["n"] == 20
    assert s["scan_face"] == "test"          # 缺省 test（票① 行为兼容）
    assert s["overlap"] == "SKIP"            # overlap 语义沿用


def test_declared_scan_face_carries_into_spec():
    text = VALID.replace("  - id: cron-face\n    enabled: true\n    project_key: sandbar\n    schedule:",
                         "  - id: cron-face\n    enabled: true\n    project_key: sandbar\n    scan_face: doc\n    schedule:", 1)
    specs = decl.build_schedule_specs(decl.parse_decl_text(text))
    assert {s["instance_id"]: s["scan_face"] for s in specs}["cron-face"] == "doc"


def test_scan_face_must_be_wired():
    text = VALID.replace("    enabled: true\n    project_key: sandbar\n    schedule:",
                         "    enabled: true\n    project_key: sandbar\n    scan_face: mood\n    schedule:", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "scan_face" in str(ei.value)


def test_count_kind_requires_source_when_enabled():
    text = VALID.replace("      source: archive-dir\n", "")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "source" in str(ei.value)


def test_count_kind_source_lexicon_checked_even_disabled():
    text = VALID.replace("source: archive-dir", "source: vibes")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "archive-dir" in str(ei.value)


def test_project_key_lexicon_blocks_traversal():
    # 锚定 schedule 作用域（6 空格）=计数源 project_key 词法；实例级身份词法
    # 由 t260915-20 测试面（test_identity_shape_rejected_names_instance）另行钉住
    text = VALID.replace("      project_key: sandbar", "      project_key: ../../etc")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "project_key" in str(ei.value)


def test_cron_instance_rejects_count_only_fields():
    text = VALID.replace("      cron: 0 9 * * 1", "      cron: 0 9 * * 1\n      n: 5")
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "n" in str(ei.value)


def test_unknown_kind_still_fail_closed():
    text = VALID.replace("kind: cron", "kind: lunar-phase", 1)
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(text)
    assert "lunar-phase" in str(ei.value)


def test_race_first_with_cron_and_count_fields_valid():
    text = VALID.replace(
        "kind: every-n-tickets\n      n: 20\n      source: archive-dir\n      project_key: sandbar",
        "kind: race-first\n      cron: 0 9 * * 1\n      n: 20\n"
        "      source: archive-dir\n      project_key: sandbar")
    d = decl.parse_decl_text(text)
    assert d.instance("count-face").kind == "race-first"
    assert d.instance("count-face").cron == "0 9 * * 1"
