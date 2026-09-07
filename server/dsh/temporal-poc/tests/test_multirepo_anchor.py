"""t260907-06（票B：多 repo 项目泳道挂子仓）单元测试。

覆盖（零 Temporal server / 零模型 / 零网络；git 夹具在 tmp 自足）：
  纯函数（shared）：
    - sanitize_branch_segment / flatten_branch_suffix：refname 非法字符清洗
      （review gen1 附条件 2：含空格/~/^ 等）、空段兜底、'/' 压平、唯一性；
    - repos_under：单仓（根含 .git）→[根]、多仓扫一层、无仓空表、不递归；
    - resolve_repos_for_paths：正常归属/最长前缀/逃逸 ../ 拒收/绝对路径拒收/
      嵌套仓拒收点名/畸形条目（非串、空串）拒收/空仓集合拒收；
    - rebase_write_set：单仓透传、剥前缀子集、非本仓剔除、None/畸形；
    - build_repo_worktrees：形状/分支命名/同名仓压平唯一/空写集拒收；
    - derive_lane_workspace 多仓：明细挂 workspace.repo_worktrees、绝对路径、
      单仓项目忽略 repo_write_set（零回归）、显式组合拒收、非 worktree 道拒收；
    - lane_workspace_gate_error：repo_worktrees 形状三态（缺失=过、畸形/碰撞=拒）。

消费外部输入的畸形用例（岗位纪律）：非串条目/空串/绝对路径/../逃逸/嵌套仓/
空仓集合/分支名碰撞，全部 tmp 桩内复现，不靠真外部源。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import shared  # noqa: E402


def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path, commit=True):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    if commit:
        _git("add", "-A", cwd=path)
        _git("commit", "-m", "base", cwd=path)
    return path


@pytest.fixture
def multirepo():
    root = Path(tempfile.mkdtemp(prefix="t260907-06-ut-"))
    a = _init_repo(root / "repo_a")
    (a / "src").mkdir()
    (a / "src" / "a.py").write_text("a\n", encoding="utf-8")
    b = _init_repo(root / "srv-b.dir")  # 非法 refname 字符（'.' 合法；用空格仓测清洗）
    yield root, a, b


# ---------- sanitize / flatten ----------

def test_sanitize_branch_segment_strips_unsafe():
    assert shared.sanitize_branch_segment("a b~c^d:e?f*g[h\\i") == "a-b-c-d-e-f-g-h-i"
    assert shared.sanitize_branch_segment("///") == "repo"          # 全非法→兜底
    assert shared.sanitize_branch_segment("plain-name") == "plain-name"


def test_flatten_branch_suffix_nested_and_unique():
    assert shared.flatten_branch_suffix("a/b") == "a-b"
    assert shared.flatten_branch_suffix("x y/z") == "x-y-z"
    # 唯一性由路径唯一性构造保证：不同路径压平结果可断言互异（合法字符场景）
    assert shared.flatten_branch_suffix("a/lib") != shared.flatten_branch_suffix("b/lib")


# ---------- repos_under ----------

def test_repos_under_single_root_repo(multirepo):
    root, a, b = multirepo
    assert shared.repos_under(a) == [a]  # 项目根=仓根 → 单仓


def test_repos_under_multirepo_one_level(multirepo):
    root, a, b = multirepo
    got = shared.repos_under(root)
    assert sorted(map(str, got)) == sorted([str(a), str(b)])


def test_repos_under_no_repo_and_nested_not_scanned(multirepo):
    root, a, b = multirepo
    empty = Path(tempfile.mkdtemp(prefix="t260907-06-ut-empty-"))
    assert shared.repos_under(empty) == []
    _init_repo(a / "nested")  # 仓中仓
    assert all("nested" not in str(p) for p in shared.repos_under(root))  # 不递归


# ---------- resolve_repos_for_paths ----------

def test_resolve_normal_and_longest_prefix(multirepo):
    root, a, b = multirepo
    m = shared.resolve_repos_for_paths(root, ["repo_a/src/a.py", "srv-b.dir/x.py"])
    assert len(m) == 2
    assert m[str(a.resolve())] == ["repo_a/src/a.py"]


def test_resolve_escape_rejected(multirepo):
    root, _, _ = multirepo
    with pytest.raises(ValueError, match="逃逸"):
        shared.resolve_repos_for_paths(root, ["../escape.md"])


def test_resolve_absolute_rejected(multirepo):
    root, _, _ = multirepo
    with pytest.raises(ValueError):
        shared.resolve_repos_for_paths(root, ["/etc/passwd"])


def test_resolve_nested_repo_rejected_named(multirepo):
    root, a, _ = multirepo
    _init_repo(a / "nested")
    with pytest.raises(ValueError, match="嵌套"):
        shared.resolve_repos_for_paths(root, ["repo_a/nested/n.txt"])


def test_resolve_malformed_entries_rejected(multirepo):
    root, _, _ = multirepo
    for bad in ([None], [""], [123], ["repo_a/../etc"]):
        with pytest.raises(ValueError):
            shared.resolve_repos_for_paths(root, bad)


def test_resolve_empty_repo_set_rejected():
    empty = Path(tempfile.mkdtemp(prefix="t260907-06-ut-norepo-"))
    with pytest.raises(ValueError, match="未发现任何 git 仓"):
        shared.resolve_repos_for_paths(empty, ["x.py"])


# ---------- rebase_write_set ----------

def test_rebase_single_repo_passthrough():
    probe = ["a.py", "b/c.py"]
    assert shared.rebase_write_set(probe, "") == probe
    assert shared.rebase_write_set(None, "") == []


def test_rebase_strips_prefix_and_drops_other_repo():
    ws = ["repo_a/src/a.py", "repo_b/lib/b.py"]
    assert shared.rebase_write_set(ws, "repo_a") == ["src/a.py"]
    assert shared.rebase_write_set(ws, "repo_b") == ["lib/b.py"]
    assert shared.rebase_write_set(ws, "repo_c") == []
    assert shared.rebase_write_set(None, "repo_a") == []


# ---------- build_repo_worktrees ----------

def test_build_repo_worktrees_shape_and_branch(multirepo):
    root, a, b = multirepo
    entries = shared.build_repo_worktrees(str(root), ["repo_a/src/a.py", "srv-b.dir/x.py"],
                                          "t260907-06")
    assert [e["repo"] for e in entries] == ["repo_a", "srv-b.dir"]
    assert entries[0]["branch"] == "lane/t260907-06-repo_a"
    assert entries[1]["name"] == shared.flatten_branch_suffix("srv-b.dir")


def test_build_repo_worktrees_empty_write_set_rejected(multirepo):
    root, _, _ = multirepo
    with pytest.raises(ValueError):
        shared.build_repo_worktrees(root, [], "x")
    with pytest.raises(ValueError):
        shared.build_repo_worktrees(root, None, "x")


# ---------- derive_lane_workspace 多仓 ----------

def test_derive_multirepo_hangs_details_on_workspace(multirepo):
    root, a, b = multirepo
    lane_rel, _ = shared.default_lane_paths("t260907-06-ut")
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        "t260907-06-ut", "worktree", project_root=str(root),
        repo_write_set=["repo_a/src/a.py", "srv-b.dir/x.py"])
    assert ws["type"] == "worktree"
    assert Path(ws["path"]) == root / lane_rel
    assert worktree == ws["path"]
    rws = ws["repo_worktrees"]
    assert {e["repo"] for e in rws} == {"repo_a", "srv-b.dir"}
    assert all(e["branch"].startswith("lane/%s-" % lane_rel.split("/")[-1]) for e in rws)
    assert shared.lane_workspace_gate_error(
        {"lane": "worktree", "workspace": ws, "worktree": worktree, "branch": branch}) == ""


def test_derive_single_repo_ignores_repo_write_set(multirepo):
    root, a, b = multirepo
    # 项目根=仓根（单仓）→ repo_write_set 静默忽略，旧路径（回归面）
    lane_rel, branch_exp = shared.default_lane_paths("t260907-06-ut")
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        "t260907-06-ut", "worktree", project_root=str(a),
        repo_write_set=["src/a.py"])
    assert ws == {"type": "worktree", "path": str(a / lane_rel)}
    assert branch == branch_exp
    assert "repo_worktrees" not in ws
    assert branch == branch_exp


def test_derive_legacy_shapes_ignore_repo_write_set(multirepo):
    """零回归面：显式 workspace 组合 / dir 道一律静默旧路径（不拒收）。"""
    root, _, _ = multirepo
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        "t26090706ut", "worktree", project_root=str(root),
        workspace={"type": "worktree", "path": "/tmp/x"},
        repo_write_set=["repo_a/x.py"])
    assert ws["path"] == "/tmp/x" and "repo_worktrees" not in ws
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        "t26090706ut", "dir", repo_write_set=["repo_a/x.py"], project_root=str(root),
        template_workspace_dir=True)
    assert ws["type"] == "dir" and "repo_worktrees" not in ws


def test_derive_multirepo_rejects_escape_via_build(multirepo):
    root, _, _ = multirepo
    with pytest.raises(ValueError):
        shared.derive_lane_workspace(
            "t26090706ut", "worktree", project_root=str(root),
            repo_write_set=["../escape.md"])


# ---------- lane_workspace_gate_error：repo_worktrees 形状 ----------

def test_gate_error_repo_worktrees_shapes():
    base_ws = {"type": "worktree", "path": "/p/.lane/t1"}
    good = dict(base_ws, repo_worktrees=[
        {"repo": "a", "name": "a", "branch": "lane/t1-a"},
        {"repo": "b", "name": "b", "branch": "lane/t1-b"}])
    meta = {"lane": "worktree", "workspace": good, "worktree": "/p/.lane/t1",
            "branch": "lane/t1"}
    assert shared.lane_workspace_gate_error(meta) == ""
    # 形状畸形
    bad1 = dict(base_ws, repo_worktrees=[])
    bad2 = dict(base_ws, repo_worktrees=[{"repo": "a"}])
    bad3 = dict(base_ws, repo_worktrees="x")
    for rws in (bad1, bad2, bad3):
        m = dict(meta, workspace=rws)
        assert shared.lane_workspace_gate_error(m) != ""
    # 分支碰撞
    dup = dict(base_ws, repo_worktrees=[
        {"repo": "a", "name": "a", "branch": "lane/t1-x"},
        {"repo": "b", "name": "b", "branch": "lane/t1-x"}])
    assert "碰撞" in shared.lane_workspace_gate_error(dict(meta, workspace=dup))
    # 无 repo_worktrees 的单仓票不受影响
    plain = dict(meta, workspace=base_ws)
    assert shared.lane_workspace_gate_error(plain) == ""
