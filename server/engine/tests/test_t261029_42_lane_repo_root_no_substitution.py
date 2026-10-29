#!/usr/bin/env python3
"""The lane repo resolver never substitutes a repository the caller did not name
(ticket t261029-42, KI-414).

`agent_activities._lane_repo_root(wt)` had two arms: `<repo>/.lane/<id>` (or the old
`.worktrees`) answered `<repo>`, and EVERY other path answered REPO_ROOT — the
checkout the engine process happens to live in. So a caller that named a repository
outside the convention had its git queries run against a different repository.
Measured on integration/t260925-04's fixture repo (`<tmp>/lane1`, branch `lane`):
`rev-parse --verify lane^{commit}` failed against the engine repo, the changed-file
list came back empty and the case reported 11 content failures.

The battery, from the outside (the public face of the resolver + the queries it is
for), never from the shape of the implementation:

  A  a worktree under `<repo>/.lane/<id>` (and the old `.worktrees` name) still
     resolves to that repo — the convention keeps its old answer;
  B  a DIFFERENT git repository outside the convention resolves to THAT repository,
     never REPO_ROOT — a plain repo, a linked worktree of it, and the single-scope
     list `_lane_scopes` builds on top of it (the join point the incident ran
     through), each carried all the way to a real git query in the named repo;
  C  a path outside the convention that is not a git repo root is a NAMED refusal
     (the path and both checks in the text), never REPO_ROOT — a plain directory, a
     path that does not exist, and a subdirectory of a real repo (it is refused, not
     guessed upward);
  D  a source lock: no return path of the function yields REPO_ROOT, the refusal is
     a raised error, and a behavioural sentinel proves REPO_ROOT is never the answer
     even when the process sits in a repo of its own;
  E  the dependency-symlink decision of the one call site that used to compare the
     resolver's answer against REPO_ROOT still links a lane of the ENGINE repo
     wherever that lane lives, and links nothing into a foreign lane.

Fixtures are real `git init` + `git worktree add` repos under temp dirs, seconds
scale. Nothing here touches the production store, the console on 3099, Temporal or
the network; each case asserts its own temp tree is the only thing it made.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_activities as aa  # noqa: E402

ENGINE = Path(__file__).resolve().parents[1]
SOURCE = ENGINE / "agent_activities.py"


# ---------- real-git fixtures (temp dirs only) ----------

def _git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, "git %s failed (%s): %s" % (
        " ".join(args), cwd, (proc.stderr or proc.stdout).strip()[:400])
    return (proc.stdout or "").strip()


def _init_repo(path: Path) -> Path:
    """A real repo with one commit on `main` — the minimum for `worktree add`."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "unit@example.test")
    _git(path, "config", "user.name", "unit")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "base.txt").write_text("base\n", "utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "base")
    return path


def _branch_tip(repo: Path, branch: str) -> str:
    """The query KI-414 is about: does the caller's branch resolve in the repo?"""
    return _git(repo, "rev-parse", "--verify", "%s^{commit}" % branch)


# ---------- A: the convention keeps its old answer ----------

def test_a_convention_worktree_resolves_to_its_repo(tmp_path):
    """<repo>/.lane/<id> -> <repo>, even though the lane is itself a git repo root."""
    repo = _init_repo(tmp_path / "proj")
    lane = repo / ".lane" / "t1"
    _git(repo, "worktree", "add", "-b", "lane/t1", str(lane))

    assert aa._lane_repo_root(lane) == repo
    # the answer is the project repo, not the lane tree and not the engine checkout
    assert aa._lane_repo_root(lane) != lane
    assert aa._lane_repo_root(lane) != aa.REPO_ROOT


def test_a_old_worktrees_name_still_resolves_to_its_repo(tmp_path):
    """The pre-260903 name `.worktrees` answers the same way (in-flight lanes)."""
    repo = _init_repo(tmp_path / "proj")
    lane = repo / ".worktrees" / "t2"
    _git(repo, "worktree", "add", "-b", "lane/t2", str(lane))

    assert aa._lane_repo_root(lane) == repo


def test_a_convention_path_wins_over_being_a_repo(tmp_path):
    """A lane under the convention belongs to its project repo, not to itself.

    The discriminator has to be the convention first: the lane IS a git repo root,
    so an order-blind "is it a repo?" would return the lane instead of its repo and
    every diff/settle anchor would move one level down."""
    repo = _init_repo(tmp_path / "proj")
    lane = repo / ".lane" / "t3"
    _git(repo, "worktree", "add", "-b", "lane/t3", str(lane))
    assert (lane / ".git").exists()          # it is a repo root ...
    assert aa._lane_repo_root(lane) == repo  # ... and still answers its repo


# ---------- B: a foreign repo answers as itself ----------

def test_b_foreign_repo_outside_the_convention_resolves_to_itself(tmp_path):
    """KI-414's exact shape: a plain repo at `<tmp>/lane1`, branch `lane`."""
    repo = _init_repo(tmp_path / "lane1")
    _git(repo, "checkout", "-b", "lane")
    (repo / "change.txt").write_text("change\n", "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "touch change.txt")

    resolved = aa._lane_repo_root(repo)
    assert resolved == repo, "a foreign repo must answer as itself, got %s" % resolved
    assert resolved != aa.REPO_ROOT
    # and the query the resolver exists for now lands in the repo the caller named:
    tip = _branch_tip(resolved, "lane")
    assert tip == _git(repo, "rev-parse", "HEAD")


def test_b_foreign_linked_worktree_resolves_to_itself(tmp_path):
    """A worktree of someone else's repo (custom path, .git is a gitfile) -> itself."""
    repo = _init_repo(tmp_path / "foreign")
    lane = tmp_path / "custom-tree" / "wt-a"
    _git(repo, "worktree", "add", "-b", "lane/wt-a", str(lane))

    assert aa._lane_repo_root(lane) == lane
    assert aa._lane_repo_root(lane) != aa.REPO_ROOT
    assert _branch_tip(aa._lane_repo_root(lane), "lane/wt-a") == _git(lane, "rev-parse", "HEAD")


def test_b_lane_scopes_anchor_the_caller_s_repo_not_repo_root(tmp_path):
    """The single-scope list the incident ran through carries the caller's repo.

    `_lane_scopes` is the one entry point settle/changed_files/merge_check use; its
    single-repo scope is where REPO_ROOT leaked into the git queries (t260925-04's
    empty changed-file list)."""
    repo = _init_repo(tmp_path / "lane4")
    _git(repo, "checkout", "-b", "lane")

    scopes = aa._lane_scopes(repo)
    assert len(scopes) == 1
    assert Path(scopes[0]["repo"]) == repo
    assert Path(scopes[0]["repo"]) != aa.REPO_ROOT
    assert Path(scopes[0]["tree"]) == repo


# ---------- C: anything else is refused by name ----------

def test_c_non_repo_outside_the_convention_is_a_named_refusal(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    with pytest.raises(RuntimeError) as exc:
        aa._lane_repo_root(plain)
    text = str(exc.value)
    assert str(plain) in text, "the refusal must name the path it was given: %r" % text
    assert "not under .lane/.worktrees" in text
    assert "is not a git repo root" in text


def test_c_missing_path_is_refused_not_guessed(tmp_path):
    """A lane directory that does not exist yet is refused by name, not REPO_ROOT.

    (prepare_workspace resolves after the create/reuse decision, and it turns this
    refusal into the ordinary failed receipt — see test_e and the audit note.)"""
    gone = tmp_path / "gone" / "lane"
    with pytest.raises(RuntimeError) as exc:
        aa._lane_repo_root(gone)
    assert str(gone) in str(exc.value)
    assert "is not a git repo root" in str(exc.value)


def test_c_subdirectory_of_a_repo_is_refused_not_guessed_upward(tmp_path):
    """A nested path is refused: walking up to the toplevel would be a second guess."""
    repo = _init_repo(tmp_path / "repo")
    nested = repo / "server" / "engine"
    nested.mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc:
        aa._lane_repo_root(nested)
    assert str(nested) in str(exc.value)


# ---------- D: source lock — no return path yields REPO_ROOT ----------

def _return_paths() -> list:
    """(returns, raises) of the real `_lane_repo_root` in the production source."""
    tree = ast.parse(SOURCE.read_text("utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_lane_repo_root"), None)
    assert func is not None, "_lane_repo_root is absent from %s" % SOURCE
    returns = [n for n in ast.walk(func) if isinstance(n, ast.Return)]
    raises = [n for n in ast.walk(func) if isinstance(n, ast.Raise)]
    return returns, raises


def test_d_no_return_path_yields_repo_root():
    """The source lock: REPO_ROOT is not a value this function may answer with.

    Two arms are allowed — the convention's repo, and the passed path itself. The
    third (REPO_ROOT) is what KI-414 measured; it must not come back."""
    returns, raises = _return_paths()
    assert returns, "_lane_repo_root must still return something"

    yielded = []
    for node in returns:
        assert node.value is not None
        text = ast.unparse(node.value)
        yielded.append(text)
        assert "REPO_ROOT" not in text, "a return path yields REPO_ROOT: %r" % text
    # the allowed set is exactly the two named answers (a new arm must be a decision)
    assert sorted(yielded) == ["cwd", "cwd.parent.parent"], yielded
    # and the refusal is a raise (it reaches the caller as a failed check)
    assert raises, "the no-answer arm must raise a named refusal, not return a value"
    texts = [ast.unparse(n.exc) for n in raises if n.exc is not None]
    assert texts, "the refusal must carry a message"
    assert any("not under .lane/.worktrees" in t and "is not a git repo root" in t
               for t in texts), texts


def test_d_repo_root_sentinel_is_never_the_answer(tmp_path, monkeypatch):
    """Behavioural twin of the source lock: point REPO_ROOT at a live repo.

    Even with the process sitting in a repository of its own, no path outside the
    convention may be answered with that repository."""
    sentinel = _init_repo(tmp_path / "engine-checkout")
    foreign = _init_repo(tmp_path / "someone-else")
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    monkeypatch.setattr(aa, "REPO_ROOT", sentinel)

    assert aa._lane_repo_root(foreign) == foreign
    assert aa._lane_repo_root(foreign) != sentinel
    with pytest.raises(RuntimeError):
        aa._lane_repo_root(plain)
    # the convention still answers its own repo, not the sentinel
    lane = foreign / ".lane" / "t9"
    _git(foreign, "worktree", "add", "-b", "lane/t9", str(lane))
    assert aa._lane_repo_root(lane) == foreign


# ---------- E: the dependency-symlink call site ----------

def test_e_engine_repo_lane_still_gets_deps_wherever_it_lives(tmp_path, monkeypatch):
    """A lane of the ENGINE repo keeps its dependency symlinks (old behaviour).

    `_ensure_lane_deps` used to ask only "did the resolver answer REPO_ROOT?"; after
    the fix a custom-path lane of the engine repo answers as itself, so the question
    gained a second, honest arm — "is this lane a registered worktree of the engine
    repo?". A convention lane and a custom-path lane of the engine repo both get the
    links; a lane of a foreign repo gets none."""
    engine = _init_repo(tmp_path / "engine")
    # a tracked file under the dependency directory's parent, so the lane's checkout
    # has the directory the symlink lives in (a worktree carries tracked files only)
    (engine / "server" / "engine").mkdir(parents=True)
    (engine / "server" / "engine" / "keep.txt").write_text("keep\n", "utf-8")
    _git(engine, "add", "-A")
    _git(engine, "commit", "-m", "engine layout")
    (engine / "server" / "engine" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(aa, "REPO_ROOT", engine)

    convention_lane = engine / ".lane" / "t1"
    _git(engine, "worktree", "add", "-b", "lane/t1", str(convention_lane))
    action = aa._ensure_lane_deps(convention_lane)
    assert action == "+deps:server/engine/.venv", action
    assert (convention_lane / "server" / "engine" / ".venv").is_symlink()

    custom_lane = tmp_path / "custom" / "t2"
    _git(engine, "worktree", "add", "-b", "lane/t2", str(custom_lane))
    action = aa._ensure_lane_deps(custom_lane)
    assert action == "+deps:server/engine/.venv", action

    foreign = _init_repo(tmp_path / "foreign")
    foreign_lane = foreign / ".lane" / "t3"
    _git(foreign, "worktree", "add", "-b", "lane/t3", str(foreign_lane))
    assert aa._ensure_lane_deps(foreign_lane) == ""
    assert not (foreign_lane / "server").exists()
