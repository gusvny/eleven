"""Lane vocabulary gate (t261008-26, KI-226): one vocabulary, fail-closed on both
sides, zero disturbance for legitimate non-worktree tickets. Pure functions, no
disk access."""
import pytest

from shared import (LANE_MAIN, LANES, LANE_WORKTREE, WS_DIR_BASE,
                    derive_lane_workspace, lane_workspace_gate_error)

GOOD_WT_WS = {"type": "worktree", "path": "/p/.lane/t26100826"}
GOOD_WT_META = {"lane": LANE_WORKTREE, "workspace": GOOD_WT_WS,
                "worktree": "/p/.lane/t26100826", "branch": "lane/t26100826"}


# ---------- L1: creation side (derive_lane_workspace) ----------

@pytest.mark.parametrize("bad_lane", [
    "land",        # the incident value: eight tickets silently degraded
    "wt",          # convenience spelling must NOT be widened in
    "Worktree",    # case mismatch
    " worktree",   # whitespace
    "main-tree",
])
def test_unknown_lane_rejected_at_creation(bad_lane):
    with pytest.raises(ValueError, match="unknown lane"):
        derive_lane_workspace("t26100826", LANE_WORKTREE, lane=bad_lane)


def test_unknown_lane_rejected_even_when_template_lane_matches():
    # review condition 1: the check is unconditional on the RESOLVED lane — a
    # payload cannot drag in an off-vocabulary template lane to bypass the gate.
    with pytest.raises(ValueError, match="land"):
        derive_lane_workspace("t26100826", "land", lane="land")


@pytest.mark.parametrize("template_lane", [LANE_WORKTREE, LANE_MAIN])
def test_empty_explicit_lane_falls_back_to_template(template_lane):
    lane, ws, worktree, branch = derive_lane_workspace(
        "t26100826", template_lane, lane="")
    assert lane == template_lane
    if template_lane == LANE_WORKTREE:
        assert worktree and ws["path"] == worktree and branch
    else:
        assert ws is None and worktree == "" and branch == ""


def test_vocabulary_is_exactly_main_and_worktree():
    assert LANES == ("main", "worktree")
    assert LANE_MAIN == "main" and LANE_WORKTREE == "worktree"


def test_worktree_lane_never_derives_an_empty_worktree():
    # KI-226 outcome 5: lane=worktree with an empty worktree is refused. The normal
    # refusal face is the workspace shape check (empty path = malformed); the tail
    # check inside derive backstops any derivation bug leaving worktree empty.
    with pytest.raises(ValueError):
        derive_lane_workspace("t1", LANE_WORKTREE,
                              workspace={"type": "worktree", "path": ""})


# ---------- L1: workflow side (lane_workspace_gate_error) ----------

@pytest.mark.parametrize("bad_lane", ["land", "wt", "Worktree", " worktree", "main-tree"])
def test_gate_rejects_unrecognised_lane(bad_lane):
    err = lane_workspace_gate_error(dict(GOOD_WT_META, lane=bad_lane))
    assert err and bad_lane.strip("'\" ") in err


@pytest.mark.parametrize("meta", [
    # no-lane workflow (content-studio): unchanged, passes
    {},
    {"lane": ""},
    # main-lane ticket: unchanged, passes
    {"lane": LANE_MAIN},
    # dir-workspace ticket (template declares workspace=dir): unchanged, passes
    {"lane": LANE_MAIN, "workspace": {"type": "dir", "path": WS_DIR_BASE + "/t1"}},
    # full worktree shape: passes
    GOOD_WT_META,
    # multi-repo shape: passes (existing repo_worktrees logic untouched)
    dict(GOOD_WT_META, repo_worktrees=[
        {"repo": "a", "name": "a", "branch": "lane/t-a"},
        {"repo": "b", "name": "b", "branch": "lane/t-b"}]),
])
def test_gate_passes_every_legitimate_shape(meta):
    assert lane_workspace_gate_error(meta) == ""


# ---------- existing shape checks still fire (none removed) ----------

@pytest.mark.parametrize("meta", [
    # lane=worktree with no workspace registered
    {"lane": LANE_WORKTREE},
    # worktree field empty
    dict(GOOD_WT_META, worktree=""),
    # workspace.path and worktree disagree
    dict(GOOD_WT_META, worktree="/p/.lane/other"),
    # branch missing
    dict(GOOD_WT_META, branch=""),
    # repo_worktrees malformed (note: an empty TOP-LEVEL list is the documented
    # single-repo default and passes — t260908-02; only a non-list or malformed
    # entry refuses)
    dict(GOOD_WT_META, repo_worktrees="x"),
    dict(GOOD_WT_META, repo_worktrees=[{"repo": "a"}]),
])
def test_gate_keeps_all_existing_shape_checks(meta):
    assert lane_workspace_gate_error(meta) != ""
