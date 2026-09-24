"""t260925-01 票：巡检模式两键（mode / docs_root）声明面单测。

覆盖（方案步1；A6 验收 UT 面）：
  - 缺省回落：未声明 mode/docs_root 的实例 = report + docs（现状零行为，逐字段锚定）；
  - 词表闸：mode 词表外 fail-closed 点名（report/produce）；
  - 词法闸：docs_root 绝对路径/空/尾斜杠/.. 段逐形态 fail-closed 点名；
  - 消费面：build_schedule_specs 与 _plan_from_decl payload 带上两键（additive 键，
    老消费者忽略）；
  - 兼容红线：既有声明文本解析结果与两键无关（不因新键出现而漂移）。
全程纯标准库，禁网络/真 Temporal。
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl  # noqa: E402

BASE = """
schema: v1
instances:
  - id: doc-produce
    enabled: true
    project_key: sandbar
    scan_face: doc
    schedule:
      kind: cron
      cron: 0 8 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
    mode: produce
    docs_root: knowledge
"""


def _one(text: str) -> decl.InstanceSpec:
    d = decl.parse_decl_text(text)
    assert len(d.instances) == 1
    return d.instances[0]


# ---------- 缺省回落（A6：未声明=零行为变化） ----------

def test_defaults_report_and_docs():
    it = _one(BASE.replace("    mode: produce\n", "").replace("    docs_root: knowledge\n", ""))
    assert it.mode == "report" and it.docs_root == "docs"


def test_engine_default_docs_root_constant():
    assert decl.DEFAULT_DOCS_ROOT == "docs" and decl.DEFAULT_MODE == "report"
    assert decl.WIRED_MODES == ("report", "produce")


# ---------- mode 词表闸 ----------

@pytest.mark.parametrize("bad", ["sync", "PRODUCE", "report produce"])
def test_mode_out_of_vocabulary_fail_closed(bad):
    with pytest.raises(decl.DeclError) as ei:
        _one(BASE.replace("mode: produce", "mode: %s" % bad))
    assert "mode" in str(ei.value) and "produce" in str(ei.value)


def test_mode_empty_value_fail_closed():
    """mode: （空值）在 YAML 子集里是开子结构形态——同样 fail-closed，不猜。"""
    with pytest.raises(decl.DeclError):
        _one(BASE.replace("mode: produce", "mode:"))


# ---------- docs_root 词法闸 ----------

@pytest.mark.parametrize("bad", ["/abs/docs", "docs/", "", "./docs", "docs/../etc"])
def test_docs_root_malformed_fail_closed(bad):
    text = BASE.replace("docs_root: knowledge", "docs_root: %s" % bad)
    with pytest.raises(decl.DeclError) as ei:
        _one(text)
    assert "docs_root" in str(ei.value)


def test_docs_root_dotdot_segment_named():
    with pytest.raises(decl.DeclError) as ei:
        _one(BASE.replace("docs_root: knowledge", "docs_root: docs/../secrets"))
    assert ".." in str(ei.value)


def test_docs_root_valid_relative_forms():
    for ok in ("docs", "knowledge/base", "doc.pages-1"):
        assert decl.validate_docs_root("t", ok) == ok


# ---------- 消费面 payload（additive 键） ----------

def test_specs_and_plan_carry_mode_keys():
    d = decl.parse_decl_text(BASE)
    spec = decl.build_schedule_specs(d)[0]
    assert spec["mode"] == "produce" and spec["docs_root"] == "knowledge"
    plan = decl._plan_from_decl(d, "doc-produce")
    assert plan["mode"] == "produce" and plan["docs_root"] == "knowledge"


def test_plan_defaults_when_undeclared():
    d = decl.parse_decl_text(BASE.replace("    mode: produce\n", "")
                             .replace("    docs_root: knowledge\n", ""))
    plan = decl._plan_from_decl(d, "doc-produce")
    assert plan["mode"] == "report" and plan["docs_root"] == "docs"


# ---------- 兼容：既有声明零漂移 ----------

def test_legacy_declaration_untouched():
    legacy = """
schema: v1
instances:
  - id: integration-tests
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 9 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""
    it = _one(legacy)
    assert it.mode == "report" and it.docs_root == "docs"
