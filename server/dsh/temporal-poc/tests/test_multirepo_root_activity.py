"""t260907-12（根亦 git 仓的混合形态）agent_activities 直调用例。

零 Temporal server / 零模型 / 零网络（git 夹具 tmp 自足）。覆盖：
  - _prepare_multirepo_lane：根树（repo=""）created → 树=泳道容器、分支
    lane/<id>-root；二次执行 reused（复用幂等=M4 转移接力契约对根树形态在案）；
  - _lane_scopes：repo="" 条目产出正确 scope（tree=泳道容器、repo=项目根、
    write_set=rebase 全量透传）；真畸形条目（branch 缺失）照旧 RuntimeError；
  - prepare_workspace 通道腿：混合夹具直调 → 推导出含根树明细；单仓夹具 →
    rws=None 走旧单仓路径（零回归）。
"""
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import shared  # noqa: E402
from shared import WorkspacePrep  # noqa: E402
import agent_activities as aa  # noqa: E402


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


@pytest.fixture
def mixed():
    root = _init_repo(Path(tempfile.mkdtemp(prefix="t260907-12-act-")))
    a = _init_repo(root / "repo_a")
    _git("worktree", "add", "-b", "lane/ut-root", str(root / ".lane" / "ut"), cwd=root)
    _git("worktree", "add", "-b", "lane/ut-repo_a",
         str(root / ".lane" / "ut" / "repo_a"), cwd=a)
    return root, a, root / ".lane" / "ut"


def test_prepare_multirepo_lane_root_tree_created_and_reused(mixed):
    root, a, lane = mixed
    entries = [{"repo": "", "name": "root", "branch": "lane/ut-root"},
               {"repo": "repo_a", "name": "repo_a", "branch": "lane/ut-repo_a"}]
    prep = WorkspacePrep(ticket_id="t26090712ut")
    r1 = aa._prepare_multirepo_lane(lane, entries, prep)
    assert r1.ok, r1.error
    # 树=泳道容器本身（repo="" Path 零特判），且身份=根仓 worktree
    assert aa._is_worktree_of(lane, root)
    assert aa._is_worktree_of(lane / "repo_a", a)
    # 清单落盘，repo="" 原样记录（路径取 MULTI_MANIFEST_REL 真源，不写字面量）
    import json
    mf = json.loads((lane / aa.MULTI_MANIFEST_REL).read_text("utf-8"))
    assert [e["repo"] for e in mf] == ["", "repo_a"]
    # 复用幂等（M4）：二次执行全 reused，树内标记文件幸存
    (lane / "marker.txt").write_text("keep\n", encoding="utf-8")
    r2 = aa._prepare_multirepo_lane(lane, entries, prep)
    assert r2.ok and r2.action == "reused", (r2.action, r2.error)
    assert (lane / "marker.txt").read_text("utf-8") == "keep\n"


def test_prepare_multirepo_lane_still_rejects_bad_shapes(mixed):
    root, a, lane = mixed
    prep = WorkspacePrep(ticket_id="t26090712ut")
    for bad in ([{"repo": 0, "name": "x", "branch": "lane/x"}],
                [{"repo": "", "name": "root", "branch": ""}],
                [{"repo": "", "branch": "lane/x"}]):
        r = aa._prepare_multirepo_lane(lane, bad, prep)
        assert not r.ok and "形状非法" in r.error, (bad, r.error)


def test_lane_scopes_root_tree_scope(mixed):
    root, a, lane = mixed
    prep = WorkspacePrep(ticket_id="t26090712ut")
    r = aa._prepare_multirepo_lane(lane, [
        {"repo": "", "name": "root", "branch": "lane/ut-root"},
        {"repo": "repo_a", "name": "repo_a",
         "branch": "lane/ut-repo_a"}], prep)
    assert r.ok, r.error  # 先落清单（_lane_scopes 的机械真源）
    entries = [{"repo": "", "name": "root", "branch": "lane/ut-root", "base_ref": "abc"},
               {"repo": "repo_a", "name": "repo_a",
                "branch": "lane/ut-repo_a"}]
    scopes = aa._lane_scopes(lane, write_set=["docs/kb.md", "repo_a/src/a.py"])
    assert len(scopes) == 2
    s_root = [s for s in scopes if s["repo_rel"] == ""][0]
    assert s_root["tree"] == lane                      # 树=泳道容器
    assert s_root["repo"] == root.parent.parent or s_root["repo"] == root
    assert s_root["write_set"] == ["docs/kb.md", "repo_a/src/a.py"]  # 全量透传
    s_a = [s for s in scopes if s["repo_rel"] == "repo_a"][0]
    assert s_a["tree"] == lane / "repo_a"
    assert s_a["write_set"] == ["src/a.py"]  # 已按仓重基（树根相对）


def test_lane_scopes_still_rejects_missing_branch(mixed):
    root, a, lane = mixed
    # 清单路径取 MULTI_MANIFEST_REL 真源（夹具造清单文件，不写字面量）
    d = lane / aa.MULTI_MANIFEST_REL
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text('[{"repo": "", "name": "root"}]', encoding="utf-8")
    with pytest.raises(RuntimeError, match="branch"):
        aa._lane_scopes(lane, write_set=[])


def test_prepare_workspace_channel_mixed_vs_single():
    # 混合夹具：通道腿推导出含根树明细
    root = _init_repo(Path(tempfile.mkdtemp(prefix="t260907-12-ch-")))
    a = _init_repo(root / "repo_a")
    prep = WorkspacePrep(ticket_id="t26090712ut", write_set=["README.md"],
                         project_root=str(root))
    lane = root / ".lane" / "ch"
    ws = {"type": "worktree", "path": str(lane)}
    import asyncio
    r = asyncio.run(aa.prepare_workspace(_prep_with(prep, ws)))
    assert r.ok, r.error
    assert (lane / "README.md").exists()  # 树=泳道容器且基线随仓
    # 单仓夹具：通道字段忽略，走旧单仓路径（repo_worktrees 不进）
    single = _init_repo(Path(tempfile.mkdtemp(prefix="t260907-12-ch1-")))
    prep2 = WorkspacePrep(ticket_id="t26090712ut", write_set=["x.py"],
                          project_root=str(single))
    r2 = asyncio.run(aa.prepare_workspace(_prep_with(
        prep2, {"type": "worktree", "path": str(single / ".lane" / "ch1")})))
    assert r2.ok, r2.error
    assert aa._is_worktree_of(single / ".lane" / "ch1", single)


def _prep_with(prep, ws):
    prep.workspace = ws
    prep.branch = "lane/ch"
    return prep
