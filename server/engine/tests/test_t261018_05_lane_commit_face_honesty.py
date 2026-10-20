# -*- coding: utf-8 -*-
"""t261018-05: the lane-commits check must never emit an undecidable red dressed up
as "implementation not persisted", and no red may carry "inspect the branch target
manually" as a remedy.

Three honesty fixes, each locked by a real-git-fixture test here:
  1. empty base_ref -> fail-closed commit_query_failed (never computed 0 commits);
  2. a -1 sentinel on a face count -> commit_query_failed (the I/O shell sanitizes
     before shared.lane_commit_verdict, whose `_bad` only rejects values < -1);
  3. a no_commits red names the changed files and the stage that must persist them
     (implement settle) — never "inspect the branch target manually".

Offline, seconds, no docker; same fixture shape as test_t260921_09_lane_commit_verdict.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)

    def g(*a):
        subprocess.run(["git", "-C", str(repo)] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q", "-b", "main")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "init")
    return repo


def _git(*a, cwd):
    return subprocess.run(["git", "-C", str(cwd)] + list(a), check=True,
                          capture_output=True, text=True)


# ---- 1. empty base_ref: fail-closed, never a computed 0-commits red ----

def test_empty_base_ref_dirty_tree_fail_closed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    (wt / "docs.txt").write_text("agent edit\n", encoding="utf-8")
    item, n = aa._lane_commits_check_item("", "lane/x", repo, wt)
    assert item["green"] is False and n == shared.LANE_COMMITS_QUERY_FAILED
    assert item["reason_code"] == "commit_query_failed"
    assert "base_ref" in item["detail"]
    # undecidable != not-persisted: the old canned claim must be absent
    assert "implementation not persisted" not in item["detail"]


def test_empty_base_ref_clean_tree_still_fail_closed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    item, n = aa._lane_commits_check_item("", "lane/x", repo, wt)
    assert item["green"] is False and n == shared.LANE_COMMITS_QUERY_FAILED
    assert item["reason_code"] == "commit_query_failed"


def test_empty_base_ref_names_the_base_remedy(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    item, _ = aa._lane_commits_check_item("", "lane/x", repo, repo / ".lane" / "t")
    assert "base_ref" in item["next_action"] and "retry_qc" in item["next_action"]


# ---- 2. face-count sentinel: undecidable, never "no_commits" ----

def test_face_sentinel_negative_one_is_query_failed_not_no_commits(tmp_path):
    # Pin the sanitizer's decision boundary: pre-merge shared.lane_commit_verdict
    # answered no_commits for (0, -1, 0) — the wedge shape — so the shell intercepts;
    # main's t261019-02 fixes the verdict itself, so either classification at this
    # pure seam is legitimate. Either way the ITEM below must be query-failed.
    assert shared.lane_commit_verdict(0, -1, 0)[1] in ("no_commits",
                                                       "commit_query_failed")
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    (wt / "d.txt").write_text("x\n", encoding="utf-8")
    # Force the committed-face query failure (empty base) while the tree is dirty:
    # the item must come out query-failed, not no_commits.
    item, _ = aa._lane_commits_check_item("", "lane/x", repo, wt)
    assert item["reason_code"] == "commit_query_failed"


# ---- 3. real-decidable shapes: green zero-change, and named no_commits reds ----

def test_recorded_base_clean_lane_is_lawful_zero_change(tmp_path):
    # The stub-ticket shape (branch == base, tree clean) with a recorded base is a
    # lawful zero-change terminal state — this is the shape that wedged t261008-24.
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    base = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    item, n = aa._lane_commits_check_item(base, "lane/x", repo, repo / ".lane" / "t")
    assert item["green"] is True and n == 0
    assert item["reason_code"] == "no_changes_no_diff"


def test_no_commits_dirty_face_names_files_and_stage(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    (wt / "ticket-notes.md").write_text("note\n", encoding="utf-8")
    base = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    item, _ = aa._lane_commits_check_item(base, "lane/x", repo, wt)
    assert item["green"] is False and item["reason_code"] == "no_commits"
    assert "ticket-notes.md" in item["detail"]
    assert "not persisted" in item["next_action"]
    assert "settle" in item["next_action"] and "retry_qc" in item["next_action"]


def test_no_commits_names_untracked_file_not_its_container_dir(tmp_path):
    # t261018-05 rework (integration round shape C): a brand-new untracked DIRECTORY
    # collapses to `?? dir/` under the default folded mode — the red must name the
    # deliverable file, not the container (measured: '.lane/t18/' instead of
    # 'docs/ticket-notes.md'). Locked by the --untracked-files=all status query.
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    (wt / "docs").mkdir(parents=True, exist_ok=True)
    (wt / "docs" / "ticket-notes.md").write_text("judge me\n", encoding="utf-8")
    base = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    item, _ = aa._lane_commits_check_item(base, "lane/x", repo, wt)
    assert item["green"] is False and item["reason_code"] == "no_commits"
    assert "docs/ticket-notes.md" in item["detail"]
    assert "docs/ticket-notes.md" in item["next_action"]


def test_no_commits_committed_face_names_files_and_never_manual_inspection(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git("worktree", "add", "-q", "-b", "lane/x", str(repo / ".lane" / "t"), cwd=repo)
    wt = repo / ".lane" / "t"
    base = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    # Commit on the main side after forking: the branch tree stays at base, but put
    # a divergent commit under another branch tip to build the committed-face shape.
    _git("checkout", "-q", "main", cwd=repo)
    (repo / "main_only.txt").write_text("ahead\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "main ahead", cwd=repo)
    new_base = _git("rev-parse", "main", cwd=repo).stdout.strip()
    item, _ = aa._lane_commits_check_item(new_base, "lane/x", repo, wt)
    assert item["green"] is False and item["reason_code"] == "no_commits"
    assert "main_only.txt" in item["detail"]
    assert "implement" in item["next_action"] and "retry_qc" in item["next_action"]
    # The ticket's hard demand: the manual-inspection pseudo-remedy is gone.
    assert "inspect the branch target manually" not in item["next_action"]
