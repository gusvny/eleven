#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-17 (KI-01M4FKAWY0EP59PY0V0QZWWGV5): a moved main ref must not hand
a green ticket to a human.

Live incident (2026-10-09, seven hits across six tickets, four within one minute
of an integration-session commit to main): a lane's main-sync settle fails with
"main is NOT an ancestor of HEAD" while MERGE_HEAD does not exist, unmerged
entries = 0, dirty files = 0 and no marker residue — the merge commit was made,
the tree is clean, nothing needs resolving, and the only unmet measurement is
that the live main ref moved past the main the lane merged in. Each hit stopped
a green ticket with a "resolution did not converge" story that was not true and
needed a human send-back to move again.

Locked here layer by layer:
  F1 the incident shape converges: judge against the revision the lane actually
     merged (the merge commit's second parent), so main@X merged + main@Y live
     reports ok=True + already_settled=True like the KI-213 settled face.
  F2 the residue scan stays coherent: it runs against the merged base, so
     integration-session files that arrived on main after the merge are never
     swept into the marker check (review condition 2).
  F3 human-actionable shapes still stop: a merged base outside main history, a
     genuinely absent merge commit, unmerged entries, residue and a missing
     worktree each fail closed with the measured facts.
  F4 the rerun predicate (dev_lane.settle_shape_needs_rerun): True only on the
     no-human-info shape, anchored on the stable measured-facts tokens — a copy
     drift degrades to the blocked path (fail-safe: block, never spin).
  F5 text discipline: both blocked sites name the failed measurement; the old
     "worker-side commit verification failed" framing is gone; the t261009-15
     quiet-baseline half and the KI-213 cap text are untouched.

Run: server/engine/.venv/bin/python -B -m pytest \\
      server/engine/tests/test_t261009_17_moved_main_settle.py -q
"""
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _ok_git(repo: Path, *args: str) -> str:
    p = _git(repo, *args)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


def _commit_file(repo: Path, name: str, text: str, msg: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _ok_git(repo, "add", "-A")
    _ok_git(repo, "commit", "-m", msg)


@pytest.fixture()
def merged_lane(tmp_path: Path) -> Path:
    """Real repo in the incident precondition shape: the lane already landed a
    merge commit whose second parent is main's tip X; main has NOT moved yet."""
    r = tmp_path / "repo"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    _commit_file(r, "f.txt", "base\n", "base")
    default = _ok_git(r, "rev-parse", "--abbrev-ref", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    _commit_file(r, "f.txt", "lane side\n", "lane change")
    _ok_git(r, "checkout", default)
    _commit_file(r, "f.txt", "main side\n", "main change")
    _ok_git(r, "checkout", "lane")
    assert _git(r, "merge", default).returncode != 0, "fixture produced no conflict"
    (r / "f.txt").write_text("lane side\nmain side\n", encoding="utf-8")
    res = _settle(r)
    assert res.ok, res.error  # fresh settle lands the commit (already_settled=False)
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0
    return r


def _main_branch(repo: Path) -> str:
    """The repo's default branch name (the one that is not `lane`)."""
    names = [ln.strip() for ln in
             _ok_git(repo, "branch", "--format=%(refname:short)").splitlines()
             if ln.strip() and ln.strip() != "lane" and ln.strip() != "stray"]
    assert names, "no main-like branch found"
    return names[0]


def _advance_main(repo: Path) -> str:
    """The integration-session face: main moves past what the lane merged."""
    default = _ok_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _ok_git(repo, "checkout", default)
    _commit_file(repo, "later.txt", "integration session\n", "main moves on")
    _ok_git(repo, "checkout", "lane")
    return _ok_git(repo, "rev-parse", "--short", default + "@{0}")


def _settle(repo: Path, base_ref: str = "main"):
    import asyncio
    from shared import ConflictSettleArgs
    return asyncio.run(aa.settle_conflict_resolution(
        ConflictSettleArgs(ticket_id="t261009-17", worktree=str(repo),
                           branch="lane", base_ref=base_ref, round_no=1)))


def _measure(repo: Path, base_ref: str = "main"):
    return aa._measure_merged_face(Path(repo), base_ref)


# ---------------- F1: the incident shape converges ----------------

def test_moved_main_still_converges(merged_lane):
    """main@X merged, main moves to Y -> the settle judge reports the merge
    commit settled instead of 'main is NOT an ancestor of HEAD'."""
    r = merged_lane
    _advance_main(r)
    res = _settle(r)
    assert res.ok is True, ("a moved main must not read as a settle failure "
                            "(KI-01M4FKAWY0EP59PY0V0QZWWGV5 root cause): %s"
                            % res.error)
    assert res.already_settled is True
    assert res.commit == _ok_git(r, "rev-parse", "--short", "HEAD")


def test_moved_main_probe_names_merged_base(merged_lane):
    """The probe's judgement base is the merge commit's second parent, and the
    facts string says so when the clean face is NOT enough (merged base outside
    main history is covered in F3) — here the success path is the assertion."""
    r = merged_lane
    _advance_main(r)
    second_parent = _ok_git(r, "rev-list", "--parents", "-n", "1", "HEAD").split()[1]
    live_main = _ok_git(r, "rev-parse", "main")
    assert second_parent != live_main, "fixture precondition: main has moved"
    res = _measure(r)
    assert res.ok and res.already_settled, res.error


def test_probe_is_idempotent_across_replays(merged_lane):
    """Replay safety: calling the probe twice on the same disk state gives the
    same verdict (it re-reads the same commit, no seam state)."""
    r = merged_lane
    _advance_main(r)
    a = _measure(r)
    b = _measure(r)
    assert (a.ok, a.already_settled, a.commit) == (b.ok, b.already_settled, b.commit)


# ---------------- F2: the residue scan stays coherent ----------------

def test_residue_scan_uses_merged_base_not_live_main(merged_lane):
    """A marker-shaped line in a file that arrived on main AFTER the merge must
    not be swept into the residue check (review condition 2): scanning the live
    ref would re-create the same false stop this ticket removes."""
    r = merged_lane
    mainbr = _main_branch(r)
    _ok_git(r, "checkout", mainbr)
    _commit_file(r, "doc.md", "a note about git\n=======\nmarkers\n", "main moves on")
    _ok_git(r, "checkout", "lane")
    res = _measure(r)
    assert res.ok and res.already_settled, res.error


# ---------------- F3: human-actionable shapes still stop ----------------

def test_merged_base_outside_main_history_stops(tmp_path):
    """The lane's merge commit carries a second parent outside main history
    while live main is NOT an ancestor of HEAD either: the merged-base route
    must not fire; the failure keeps the measured facts and stays
    human-actionable (the lane merged something that was never main)."""
    r = tmp_path / "repo5"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    _commit_file(r, "f.txt", "base\n", "base")
    base = _ok_git(r, "rev-parse", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    _commit_file(r, "lane.txt", "lane\n", "lane change")
    _ok_git(r, "checkout", "-b", "stray", base)
    _commit_file(r, "stray.txt", "off-main work\n", "stray commit")
    _ok_git(r, "checkout", "lane")
    _ok_git(r, "merge", "--no-ff", "-m", "merge stray", "stray")
    _ok_git(r, "checkout", "main")
    _commit_file(r, "main.txt", "main\n", "main moves on")
    _ok_git(r, "checkout", "lane")
    parents = _ok_git(r, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3, "fixture precondition: two-parent merge commit"
    assert _git(r, "merge-base", "--is-ancestor", parents[2], "main").returncode != 0, \
        "fixture precondition: the second parent is outside main history"
    res = _measure(r)
    assert res.ok is False
    assert "NOT an ancestor" in res.error
    assert "unmerged entries: 0" in res.error
    assert "marker residue: none" in res.error


def test_genuinely_absent_merge_commit_stops(tmp_path):
    """HEAD is not a merge commit and main is not its ancestor: fail closed
    with the measured facts — no invented verdict."""
    r = tmp_path / "repo2"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    _commit_file(r, "f.txt", "base\n", "base")
    _ok_git(r, "checkout", "-b", "lane")
    _ok_git(r, "checkout", "main")
    _commit_file(r, "g.txt", "main only\n", "main moves on")
    _ok_git(r, "checkout", "lane")
    res = _measure(r)
    assert res.ok is False
    assert "NOT an ancestor" in res.error
    assert "unmerged entries: 0" in res.error


def test_unmerged_entries_stop(tmp_path):
    """A real mid-merge face (UU entries): fails closed, human-actionable."""
    r = tmp_path / "repo3"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    _commit_file(r, "f.txt", "base\n", "base")
    default = _ok_git(r, "rev-parse", "--abbrev-ref", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    _commit_file(r, "f.txt", "lane side\n", "lane change")
    _ok_git(r, "checkout", default)
    _commit_file(r, "f.txt", "main side\n", "main change")
    _ok_git(r, "checkout", "lane")
    assert _git(r, "merge", default).returncode != 0
    res = _measure(r)
    assert res.ok is False
    assert "MERGE_HEAD does not exist" in res.error


def test_missing_worktree_fails_closed(tmp_path):
    """KI-213 malformed-input gate kept: a nonexistent worktree gets the named
    receipt, never an exception."""
    res = _measure(tmp_path / "nope")
    assert res.ok is False
    assert "does not exist" in res.error


def test_octopus_merge_second_parent_judged(tmp_path):
    """Edge: an octopus merge commit (>2 parents) — the second parent (a main
    commit) is the judged merged base and the clean face converges."""
    r = tmp_path / "repo4"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    _commit_file(r, "f.txt", "base\n", "base")
    base = _ok_git(r, "rev-parse", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    _commit_file(r, "lane.txt", "lane\n", "lane change")
    _ok_git(r, "checkout", "main")
    _commit_file(r, "main.txt", "main\n", "main change")
    _ok_git(r, "checkout", "-b", "other", base)
    _commit_file(r, "other.txt", "other\n", "other change")
    _ok_git(r, "checkout", "lane")
    _ok_git(r, "merge", "main", "other", "-m", "octopus")
    _ok_git(r, "checkout", "main")
    _commit_file(r, "main.txt", "main\nnewer\n", "main moves on")
    _ok_git(r, "checkout", "lane")
    parents = _ok_git(r, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) >= 3, "fixture precondition: octopus merge commit"
    res = _measure(r)
    assert res.ok and res.already_settled, res.error


# ---------------- F4: the rerun predicate ----------------

def test_predicate_true_only_on_no_human_info_shape():
    e = ("no merge in progress (MERGE_HEAD does not exist); cannot record a "
         "merge commit; measured: main is NOT an ancestor of HEAD; unmerged "
         "entries: 0; dirty files: 0; marker residue: none")
    assert dev_lane.settle_shape_needs_rerun(e) is True


def test_predicate_false_on_human_actionable_shapes():
    prefix = "no merge in progress (MERGE_HEAD does not exist); cannot record a merge commit; "
    cases = [
        prefix + "measured: main is NOT an ancestor of HEAD; unmerged entries: 2; "
                 "dirty files: 0; marker residue: none",
        prefix + "measured: main is NOT an ancestor of HEAD; unmerged entries: 0; "
                 "dirty files: 3; marker residue: none",
        prefix + "measured: main is NOT an ancestor of HEAD; unmerged entries: 0; "
                 "dirty files: 0; marker residue: f.txt, g.txt",
        prefix + "measured: main is NOT an ancestor of HEAD; unmerged entries: 0; "
                 "dirty files: -1; marker residue: none",  # status probe failed
        prefix + "measured: worktree /x does not exist",
        "",                                       # empty error
        "MERGE_HEAD still present after the reset (merge state not cleared)",
    ]
    for e in cases:
        assert dev_lane.settle_shape_needs_rerun(e) is False, e


def test_predicate_copy_drift_degrades_to_block():
    """Review condition 3 pin: if the settle copy drifts (token wording
    changes), the predicate stops matching — the failure degrades to today's
    blocked path (stop), never to a silent infinite rerun."""
    drifted = ("no merge in progress (MERGE_HEAD does not exist); cannot record "
               "a merge commit; measured facts: main moved; pending merges=0; "
               "worktree tidy; markers absent")
    assert dev_lane.settle_shape_needs_rerun(drifted) is False


# ---------------- F5: text discipline / source locks ----------------

def test_blocked_sites_carry_precise_copy():
    """Both blocked sites name the failed measurement; the old framing that
    reads as if the lane did something wrong is gone."""
    src = (POC / "dev_lane.py").read_text("utf-8")
    assert src.count("measured an unresolved state") == 2
    assert "worker-side commit verification failed" not in src
    assert src.count("settle_shape_needs_rerun(") == 3  # 1 def + 2 call sites


def test_prior_halves_untouched():
    """t261009-15's quiet-baseline half and the KI-213 cap text stay intact."""
    lane_src = (POC / "dev_lane.py").read_text("utf-8")
    assert "def quiet_baseline_covered(" in lane_src
    shared_src = (POC / "shared.py").read_text("utf-8")
    assert ("blocked:main-sync conflict resolution did not converge in %d rounds"
            in shared_src)
    aa_src = (POC / "agent_activities.py").read_text("utf-8")
    assert "no merge in progress (MERGE_HEAD does not exist)" in aa_src
