"""t260925-21 单测：developer/integration 角色 report 内容一律英文（宿主令 260925）。

覆盖口径（=create_plan 方案 UT-(a)..UT-(e)）：
  a. build_stage_prompt：developer 与 integration 段的 prompt 含
     ROLE_REPORT_ENGLISH_CLAUSE（英文纪律句）。
  b. 其它角色（ops/product-operation/artist 等）prompt 不含该句——260925 令只覆盖
     developer/integration，其它角色 prompt 零变化。
  c. dev_lane.FLOW_BRIEF 六个角色段（create_plan/review_plan/implement/
     design_integration_tests/arbitrate/acceptance_walkthrough）各含该句——
     守住「单源常量、六段共用」，防后续加段漂移。
  d. charter 双纪律在场且次序正确：260904 回复中文条在前、260925 报告英文条紧随
     其后（读 server/session_charter.md 真文件，锚定条目开头文案）。
  e. 畸形输入边角：role 为空串/未知值/None 时 build_stage_prompt 不注入该句且不抛
     （岗位纪律：外部输入畸形用例）。

UT 全程禁网络/真 Temporal/真 git；charter 断言读 worktree 内文件（固定路径桩）。
运行：`python3 -m pytest server/engine/tests/test_t260925_21_report_language.py -q`。
"""
from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import Stage, build_stage_prompt  # noqa: E402

CLAUSE = shared.ROLE_REPORT_ENGLISH_CLAUSE
assert CLAUSE, "常量不得为空"

META = {"title": "t", "workspace": {"path": "/tmp/x", "type": "worktree"}}
HANDOFFS = []

# dev-lane 六个角色段 → 期望角色（与 DevLaneWorkflow.STAGES 对齐）
DEVLANE_STAGE_ROLES = {
    "create_plan": "developer",
    "review_plan": "integration",
    "implement": "developer",
    "design_integration_tests": "integration",
    "arbitrate": "integration",
    "acceptance_walkthrough": "integration",
}


def _mk_prompt(role, stage_id="create_plan", name="做方案"):
    st = Stage(id=stage_id, name=name, role=role, next="", parts=("agent",))
    return build_stage_prompt("t-x", META, st, HANDOFFS, "rf.json", 1, "")


# ---------- a. developer / integration 段注入 ----------

def test_build_stage_prompt_developer_role_has_clause():
    assert CLAUSE in _mk_prompt("developer")


def test_build_stage_prompt_integration_role_has_clause():
    assert CLAUSE in _mk_prompt("integration", stage_id="arbitrate", name="仲裁")


def test_each_devlane_stage_role_prompt_has_clause():
    for sid, role in DEVLANE_STAGE_ROLES.items():
        assert CLAUSE in _mk_prompt(role, stage_id=sid), sid


# ---------- b. 其它角色零变化 ----------

def test_other_roles_do_not_get_clause():
    for role in ("ops", "product-operation", "artist", "qa"):
        assert CLAUSE not in _mk_prompt(role), role


# ---------- c. FLOW_BRIEF 六段各有该句 ----------

def test_flow_brief_six_entries_have_clause():
    for sid in DEVLANE_STAGE_ROLES:
        assert sid in dev_lane.FLOW_BRIEF, sid
        assert CLAUSE in dev_lane.FLOW_BRIEF[sid], sid


# ---------- d. charter 双纪律在场且次序正确 ----------

def _charter_text() -> str:
    # worktree 内真源路径（server/session_charter.md 相对泳道根=仓库根）
    root = POC.parent.parent
    return (root / "server" / "session_charter.md").read_text(encoding="utf-8")


def test_charter_has_both_rules_in_order():
    text = _charter_text()
    i_cn = text.index("260904 宿主令")
    i_en = text.index("260925 宿主令")
    assert i_cn < i_en, "回复中文条（260904）须在报告英文条（260925）之前"
    # 英文条必须显式点名英文与中文回复并存
    en_block = text[i_en:i_en + 300]
    assert "英文" in en_block
    assert "平实中文" in en_block


# ---------- e. 畸形 role 边角 ----------

def test_malformed_role_no_clause_no_crash():
    for bad in ("", "Developer", "unknown", None):
        assert CLAUSE not in _mk_prompt(bad), bad
