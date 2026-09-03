"""derive_lane_workspace 缺一补一与形态错拒收（t260902-10，纯函数，不查盘）。"""
import pytest

from shared import derive_lane_workspace, LANE_WORKTREE, WS_DIR_BASE

WS = {"type": "worktree", "path": ".worktrees/t260902-10"}  # 旧名显式路径=兼容面（保持钉住）


def test_all_missing_uses_default_paths():
    lane, ws, worktree, branch = derive_lane_workspace("t260902-10", LANE_WORKTREE)
    assert lane == LANE_WORKTREE
    assert ws == {"type": "worktree", "path": worktree}
    assert worktree.startswith(".lane/t") and "t260902-10" in worktree  # 260903 宿主令改名
    assert branch == "lane/" + worktree.rsplit("/", 1)[-1]


def test_explicit_workspace_only_fills_worktree():
    lane, ws, worktree, branch = derive_lane_workspace("t1", LANE_WORKTREE, workspace=WS)
    assert worktree == WS["path"]
    assert ws == WS
    assert branch == "lane/t260902-10"  # branch 缺省=lane/<泳道目录名>


def test_explicit_worktree_only_fills_workspace():
    _, ws, worktree, _ = derive_lane_workspace("t1", LANE_WORKTREE, worktree=".worktrees/x")
    assert worktree == ".worktrees/x"
    assert ws == {"type": "worktree", "path": ".worktrees/x"}


def test_consistent_both_ok_and_explicit_branch_kept():
    _, ws, worktree, branch = derive_lane_workspace(
        "t1", LANE_WORKTREE, lane=LANE_WORKTREE, workspace=WS,
        worktree=".worktrees/t260902-10", branch="lane/custom")
    assert worktree == ".worktrees/t260902-10" and branch == "lane/custom" and ws == WS


@pytest.mark.parametrize("kwargs", [
    # lane=worktree 但 workspace.type 是 dir：不给静默降级的机会
    dict(workspace={"type": "dir", "path": "x"}),
    # workspace.path 与 worktree 两字段不一致（两张皮必出事故）
    dict(workspace=WS, worktree=".worktrees/other"),
])
def test_worktree_lane_shape_errors(kwargs):
    with pytest.raises(ValueError):
        derive_lane_workspace("t1", LANE_WORKTREE, **kwargs)


@pytest.mark.parametrize("bad_ws", [
    "not-a-dict", 42, {},                       # 非 dict / 空 dict
    {"type": "bogus", "path": "x"},             # type 非法
    {"type": "worktree"},                       # 缺 path
    {"type": "worktree", "path": ""},           # path 空
])
def test_workspace_malformed_rejected(bad_ws):
    with pytest.raises(ValueError):
        derive_lane_workspace("t1", LANE_WORKTREE, workspace=bad_ws)


def test_dir_lane_default_workspace():
    lane, ws, _, _ = derive_lane_workspace("t9", "dev", workspace=None, template_workspace_dir=True)
    assert lane == "dev" and ws == {"type": "dir", "path": WS_DIR_BASE + "/t9"}


def test_dir_lane_without_flag_keeps_none():
    _, ws, _, _ = derive_lane_workspace("t9", "dev")
    assert ws is None
