"""t261011-24 — a develop-line landing is a SQUASH commit (host order 261011,
unit tests; zero Temporal server / zero model / zero network; real `git init`
fixture repos in tmp_path, isolated delivery ledger via
SANDBAR_DELIVERY_LEDGER_DIR).

Contract under test (create_plan gen1, review_plan gen1 pass):
  - the line reads as ONE commit per ticket, like main: each landing adds
    exactly one single-parent commit (no merge commits, no lane step history);
  - the commit message names the landing (ticket id + destination line) and
    the landing record's revision is exactly the new line HEAD;
  - the ancestry gate stays fail-closed and first (covered further in
    test_t261009_28_landing_delivery_ledger.py — not duplicated here);
  - the three-step conflict cleanup is the shared recipe's job: a squash
    conflict restores the line worktree (no unmerged residue), refuses by
    name, writes no record, and an idempotent retry after the fix lands;
  - the KI-213 recovery face is re-scoped for squash: lane content already on
    the line + missing record → record the CURRENT HEAD, no empty commit;
  - the race branch is split: the core reports refused_unstarted, the landing
    names its own fault (not main's dirty wording);
  - the gitlink gate rides in the shared core: a nested repo in the lane diff
    is a loud refusal on the line too (t260916-20).
Malformed-input discipline: fixed fixture strings / monkeypatched seams, never
an external source.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[2] / "server" / "engine"
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import shared  # noqa: E402


# ------------------------------------------------------------------ fixtures

def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "main.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _lane_commit(repo: Path, fname: str, text: str, msg: str, branch="lane") -> str:
    _git("checkout", "-B", branch, "main", cwd=repo)
    (repo / fname).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    return tmp_path


def _declare(project="proj", line_id="buffer"):
    decl = [{"line_id": line_id, "scope": "epic x", "owner": "integration",
             "repositories": [{"name": "r", "branch": "develop"}],
             "extra_scenarios": [], "version": 1}]
    d = shared.develop_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")


def _line_and_repo(env):
    _declare()
    return dl.load_line("proj", "buffer"), _init_repo(env / "repo")


def _landing_rows(project="proj"):
    rows, bad = dc.read_rows(dc.ledger_path(project))
    assert not bad, bad
    return dc._of_kind(rows, dc.KIND_LANDING)


def _line_commits(repo: Path, n: int):
    """The line branch's tip commits: (sha, parents, subject)."""
    out = _git("rev-list", "--parents", "-%d" % n, "develop", cwd=repo).stdout
    rows = []
    for ln in out.strip().splitlines():
        parts = ln.split()
        rows.append((parts[0], parts[1:], ))
    subj = {r[0]: _git("log", "-1", "--format=%s", r[0], cwd=repo).stdout.strip()
            for r in rows}
    return [(sha, parents, subj[sha]) for sha, parents in rows]


# ------------------------------------------------------- one commit per ticket

def test_landing_is_one_single_parent_commit(env):
    """Host order 261011: the line history is one commit per ticket — no merge
    commits, the lane's small-step history stays out of the line."""
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "step1.txt", "1\n", "lane step 1")
    _lane_commit(repo, "step2.txt", "2\n", "lane step 2")  # two lane steps...
    res = dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert res.ok
    _lane_commit(repo, "step3.txt", "3\n", "lane step 3", branch="lane2")
    res2 = dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert res2.ok
    commits = _line_commits(repo, 3)  # base + exactly two landing commits
    assert len(commits) == 3
    for sha, parents, subject in commits[:-1]:  # newest first; base is last
        assert len(parents) == 1, "landing must be a single-parent commit: %s" % subject
        assert subject.startswith("landing t")
        assert "onto line buffer (r): rev " in subject
    # property 3: the record's revision IS the new line HEAD
    head = _git("rev-parse", "develop", cwd=repo).stdout.strip()
    assert res2.revisions["r"] == head
    assert _landing_rows()[-1]["repos"] == [{"repo": "r", "revision": head}]


def test_landing_commit_carries_the_lane_content(env):
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    assert dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine").ok
    wt = shared.develop_dir("proj") / "wt" / "r"
    assert (wt / "feat.txt").read_text(encoding="utf-8") == "one\n"


# ------------------------------------------------- conflict + idempotent retry

def test_squash_conflict_restores_worktree_and_retry_lands(env):
    """The shared three-step cleanup: after a squash conflict the line worktree
    shows no unmerged residue and no record exists; once the lane re-merges the
    line and the conflict is gone, the retry lands cleanly (Temporal
    timeout-retry shape — the cleanup is idempotent)."""
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "first.txt", "one\n", "first lane work")
    assert dl.land_ticket(line, "proj", {"r": repo}, "t0", "engine").ok
    _git("checkout", "-B", "lane", "main", cwd=repo)
    (repo / "conflict.txt").write_text("lane side\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "lane side", cwd=repo)
    wt = shared.develop_dir("proj") / "wt" / "r"
    _git("checkout", "-q", "develop", cwd=wt)
    (wt / "conflict.txt").write_text("line side\n", encoding="utf-8")
    _git("add", "-A", cwd=wt)
    _git("commit", "-m", "line side", cwd=wt)
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert "conflict" in str(ei.value)
    assert _landing_rows()[-1]["ticket"] == "t0"  # no record for the refused one
    assert _git("status", "--porcelain", cwd=wt).stdout.strip() == ""
    assert _git("ls-files", "-u", cwd=wt).stdout.strip() == ""
    # retry after the lane re-merges the line: lands cleanly, one commit
    _git("checkout", "-q", "lane", cwd=repo)
    _git("merge", "--no-edit", "-X", "ours", "develop", cwd=repo)
    res = dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert res.ok and "landed at" in res.faces["r"]
    assert len(_line_commits(repo, 3)) == 3  # base + t0 + t2, nothing else


# ----------------------------------------------------- KI-213 recovery (squash)

def test_staged_empty_recovery_records_current_head(env):
    """Crash-after-commit-before-record, squash shape: the lane content is
    already on the line but no landing row exists. The retry must append the
    missing record naming the CURRENT line HEAD and produce no empty commit."""
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    assert dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine").ok
    head = _git("rev-parse", "develop", cwd=repo).stdout.strip()
    # simulate the crash: erase the landing row (fixed fixture rewrite)
    path = dc.ledger_path("proj")
    rows, _ = dc.read_rows(path)
    kept = [r for r in rows if r.get("kind") != dc.KIND_LANDING]
    path.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    res = dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert res.ok
    rows2 = _landing_rows()
    assert len(rows2) == 1 and rows2[0]["ticket"] == "t1"
    assert rows2[0]["repos"] == [{"repo": "r", "revision": head}]
    assert res.revisions["r"] == head  # no new commit, HEAD unchanged
    assert any("recovered" in f for f in res.faces.values())
    commits = _line_commits(repo, 2)
    assert len(commits) == 2  # base + the original landing commit, nothing added


# ------------------------------------------------------- race branch (split)

def test_race_dirt_between_assert_and_merge_is_a_named_landing_fault(env,
                                                                     monkeypatch):
    """The core reports refused_unstarted; the landing names ITS OWN fault —
    never main's dirty wording. Line head unmoved, no record."""
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    wt = shared.develop_dir("proj") / "wt" / "r"
    real_git = dl._git
    injected = {"done": False}

    def racing_git(args, cwd, timeout=30):
        p = real_git(args, cwd, timeout=timeout)
        # after the engine-owned cleanliness assert reads clean, drop dirt that
        # overlaps the merge surface — the merge will then refuse to start
        if (not injected["done"] and list(args) == ["status", "--porcelain"]
                and Path(str(cwd)).resolve() == wt.resolve()):
            injected["done"] = True
            (wt / "feat.txt").write_text("dirty\n", encoding="utf-8")
        return p

    monkeypatch.setattr(dl, "_git", racing_git)
    head_before = _git("rev-parse", "main", cwd=repo).stdout.strip()
    # the line branch is seeded at main during the refused landing, and stays there
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "refused to start" in str(ei.value)
    # not main's dirty classification (the race wording belongs to _squash_merge)
    assert "race exit" not in str(ei.value)
    assert "line worktree dirt" in str(ei.value)
    assert _git("rev-parse", "develop", cwd=repo).stdout.strip() == head_before
    assert _landing_rows() == []


# --------------------------------------------------- gitlink gate in the core

def test_gitlink_in_lane_diff_refused_at_the_core(env):
    """t260916-20 carried into the shared core: a squash moves in-tree entries
    only, so a nested repo in the diff is a loud refusal on ANY destination."""
    line, repo = _line_and_repo(env)
    _git("checkout", "-B", "lane", "main", cwd=repo)  # the gitlink lands on the lane
    nested = repo / "nested"
    nested.mkdir()
    _git("init", "-q", "-b", "main", cwd=nested)
    _git("config", "user.email", "ut@example.com", cwd=nested)
    _git("config", "user.name", "ut", cwd=nested)
    (nested / "inner.txt").write_text("inner\n", encoding="utf-8")
    _git("add", "-A", cwd=nested)
    _git("commit", "-m", "nested base", cwd=nested)
    _git("add", "nested", cwd=repo)  # stages the gitlink (mode 160000)
    _git("commit", "-m", "add nested repo", cwd=repo)
    sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    develop = env / "line-wt"
    _git("worktree", "add", "-b", "develop", str(develop), "main", cwd=repo)
    out = aa._squash_merge_core(develop, sha)
    assert out.status == "failed" and out.reason == "gitlink_present"
    assert out.files, "the refusal must name the gitlink paths"


def test_unresolvable_revision_never_lands(env):
    """Malformed input: a lane sha the line worktree cannot resolve must fail
    closed in the core (merge refused), never land something else."""
    line, repo = _line_and_repo(env)
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    develop = env / "line-wt"
    _git("worktree", "add", "-b", "develop", str(develop), "main", cwd=repo)
    out = aa._squash_merge_core(repo, "0" * 40)
    assert out.status in ("refused_unstarted", "failed")
    assert _landing_rows() == []
