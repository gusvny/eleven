# -*- coding: utf-8 -*-
"""261019: merge_check self-heals a MECHANICAL red by declaration, not by code.

Why this shape: the first cut hardcoded one red class; the review asked the
obvious next question — "what if another project wants a different red routed
back?" So the split is now:
  * the ENGINE owns the closed registry of reds whose remedy is a mechanical,
    idempotent act (path_gates.REMEDIABLE_RED_CODES) — only it knows a red is
    machine-actionable;
  * the PROJECT opts in per red code, naming the stage and the round bound, in
    its own `server/merge-checks.yaml` under `merge_check_auto_rework:`.
A red neither side names keeps blocking for a human; a project that declares
nothing is byte-unchanged (sandbar is the only project with this file today).

Coverage:
- the policy parser's truth table: absent / valid / defaulted stage+rounds /
  unknown red code / foreign stage / non-positive or non-integer rounds /
  over-ceiling clamp / unparseable line inside the section / line before the
  first entry — each named a refusal, never a silent skip;
- the planner: fires only when EVERY red of the round is opted in and they
  share one target stage; a sole-red remedy refuses to batch; the note carries
  the gate's own measurement plus the registry's remedy text;
- the wiring: the receipt carries the decision as data (the workflow has no
  file IO), the workflow branch sits behind a patch marker (a history that
  recorded the old "block on a human" path must replay it — KI-061), routes
  through the ONE rework entry and is bounded with a named block over the bound.

No Temporal, no network, no git: parsers and planner are pure; the activity /
workflow wiring is asserted on source anchors.
"""
import os

import path_gates as pg
import dev_lane as dl
import shared

HERE = os.path.dirname(__file__)
DEV_LANE_PY = os.path.join(HERE, "..", "dev_lane.py")
AGENT_PY = os.path.join(HERE, "..", "agent_activities.py")

VALID = ("merge_check_auto_rework:\n"
         "  - code: bundle_stale\n")


def _red(**kw):
    item = {"id": "bundle_freshness", "green": False,
            "reason_code": "bundle_stale",
            "files": ["server/x/src/", "server/x/lib/"],
            "detail": "rebuilt via declared entry in a temp copy: committed "
                      "bundle differs from what this lane's src produces (stale): a.js"}
    item.update(kw)
    return item


# ---------- the policy parser ----------

def test_absent_section_means_no_policy():
    assert pg.parse_auto_rework_policy("") == ({}, "")
    assert pg.parse_auto_rework_policy("bundle_pairs:\n  - src: a/\n    out: b/\n") == ({}, "")


def test_valid_section_uses_the_registry_defaults():
    policy, diag = pg.parse_auto_rework_policy(VALID)
    assert diag == ""
    spec = pg.REMEDIABLE_RED_CODES["bundle_stale"]
    assert policy == {"bundle_stale": {"stage": spec["stage"],
                                       "max_rounds": spec["max_rounds"]}}


def test_explicit_stage_and_rounds_are_honoured():
    text = VALID + "    stage: implement\n    max_rounds: 1\n"
    policy, diag = pg.parse_auto_rework_policy(text)
    assert diag == "" and policy["bundle_stale"]["max_rounds"] == 1


def test_over_ceiling_rounds_are_clamped_not_honoured():
    text = VALID + "    max_rounds: 99\n"
    policy, diag = pg.parse_auto_rework_policy(text)
    assert diag == ""
    assert policy["bundle_stale"]["max_rounds"] == pg.AUTO_REWORK_MAX_ROUNDS_CEILING


def test_unknown_red_code_is_refused_by_name():
    policy, diag = pg.parse_auto_rework_policy("merge_check_auto_rework:\n  - code: typo\n")
    assert policy == {} and "typo" in diag and "no mechanical remedy" in diag


def test_foreign_stage_is_refused_by_name():
    policy, diag = pg.parse_auto_rework_policy(VALID + "    stage: design\n")
    assert policy == {} and "outside the rework vocabulary" in diag and "design" in diag


def test_bad_rounds_are_refused_by_name():
    for bad in ("0", "-1", "two"):
        policy, diag = pg.parse_auto_rework_policy(VALID + "    max_rounds: %s\n" % bad)
        assert policy == {} and "max_rounds" in diag, bad


def test_unparseable_line_inside_the_section_is_refused():
    policy, diag = pg.parse_auto_rework_policy(VALID + "    whatever: 1\n")
    assert policy == {} and "unparseable line" in diag


def test_line_before_the_first_entry_is_refused():
    policy, diag = pg.parse_auto_rework_policy(
        "merge_check_auto_rework:\n    stage: implement\n")
    assert policy == {} and "before the first" in diag


def test_non_string_input_is_refused():
    policy, diag = pg.parse_auto_rework_policy(None)
    assert policy == {} and "not a string" in diag


# ---------- the planner ----------

def _policy():
    return pg.parse_auto_rework_policy(VALID)[0]


def test_planner_fires_on_the_single_opted_in_red():
    plan = pg.auto_rework_plan([_red()], _policy())
    assert plan["stage"] == "implement" and plan["code"] == "bundle_stale"
    assert "server/x/src/" in plan["note"] and "server/x/lib/" in plan["note"]
    assert "rebuilt via declared entry" in plan["note"], \
        "the note must carry what the gate measured, not just a verdict word"


def test_planner_is_silent_without_a_policy():
    assert pg.auto_rework_plan([_red()], {}) is None


def test_planner_is_silent_when_the_red_is_not_opted_in():
    policy = _policy()
    other = _red(reason_code="out_of_set")
    assert pg.auto_rework_plan([other], policy) is None


def test_planner_batches_opted_in_codes_sharing_one_target():
    # 261019: opt-in is the project's explicit statement that a class is the
    # lane's to fix, so two opted-in codes with the same stage route together -
    # the guard against masking is the per-code opt-in itself, plus the rule
    # that EVERY red must be covered.
    policy = _policy()
    plan = pg.auto_rework_plan([_red(), _red(files=["a/src/", "a/out/"])], policy)
    assert plan["stage"] == "implement" and plan["code"] == "bundle_stale"


def test_planner_refuses_a_batch_with_an_unopted_red():
    policy = _policy()
    mixed = [_red(), {"id": "worktree_clean", "green": False,
                      "reason_code": "workspace_dirty"}]
    assert pg.auto_rework_plan(mixed, policy) is None, \
        "an un-opted-in red in the round must keep the human path"


def test_planner_is_silent_on_a_green_round():
    assert pg.auto_rework_plan([{"id": "bundle_freshness", "green": True}], _policy()) is None


def test_planner_carries_the_registered_remedy_text():
    plan = pg.auto_rework_plan([_red()], _policy())
    assert "merge-checks.yaml" in plan["note"]
    assert "commit the paired out prefix" in plan["note"]


# ---------- the wiring ----------

def test_receipt_carries_the_decision_as_data():
    assert "auto_rework" in shared.MergeCheckResult.__dataclass_fields__, \
        "the workflow has no file IO: the policy must be resolved in the activity " \
        "and handed over as a plain field"


def test_activity_resolves_the_policy_fail_closed():
    src = open(AGENT_PY, encoding="utf-8").read()
    assert "parse_auto_rework_policy(" in src and "auto_rework_plan(" in src
    assert "auto_rework=_auto_rework" in src
    assert "auto_rework_policy_unreadable" in src, \
        "a malformed declaration must show up as a named red, never vanish"


def test_branch_is_patch_guarded_and_bounded():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    assert 'AUTO_REWORK_PATCH_ID = "dev-lane-merge-check-auto-rework-v1"' in src
    assert "workflow.patched(AUTO_REWORK_PATCH_ID)" in src, \
        "a history recorded while such a red parked on a human must replay the " \
        "block path (KI-061)"
    assert "self._auto_rework_rounds <= _cap" in src
    assert dl.AUTO_REWORK_MAX_ROUNDS_CEILING >= 1


def test_auto_route_uses_the_one_rework_entry():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("workflow.patched(AUTO_REWORK_PATCH_ID)")
    window = src[i:i + 2600]
    assert "self._auto_rework(" in window, \
        "routing must go through the single rework entry, never a hand-rolled phase set"
    assert 'fallback="merge_check"' in window


def test_over_bound_blocks_by_name():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("workflow.patched(AUTO_REWORK_PATCH_ID)")
    window = src[i:i + 3000]
    assert "did not clear after" in window and "await self._blocked(" in window
