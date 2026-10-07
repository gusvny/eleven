#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261007-06 (KI-213): a settled merge must not stay blocked on a false
"merging state" text.

Live incident (2026-10-07 night, seven hits across four tickets): the join-settle
path lands the merge commit through the shared sync core `_settle_merge_core`,
consuming MERGE_HEAD; the branch-side `settle_conflict_resolution` then reads
"no merge in progress (MERGE_HEAD does not exist)" and dev_lane.py blocks the
ticket with "The worktree is in a merging state." — an assertion never read from
git, steering the reader toward rework (a wasted round) or `--abort` (which
destroys a correct commit already on disk).

Locked here layer by layer:
  F1 the incident sequence: resolve -> join settles (MERGE_HEAD consumed) ->
     settle_conflict_resolution returns ok=True + already_settled=True with the
     landed commit (the workflow's existing success path takes over, no block).
  F2 fail-closed counter-cases: the probe never fakes a settled verdict —
     main NOT an ancestor of HEAD / dirty face / marker residue each fail with
     the MEASURED facts and never a "merging state" assertion.
  F3 malformed inputs: nonexistent worktree, empty/unknown base_ref — fail
     closed with a named error, never an exception past the activity seam.
  F4 text discipline: dev_lane no longer carries the unconditional "The
     worktree is in a merging state." block text; the fail-closed block names
     the light exit (already settled -> retry_qc) when the facts show the
     commit on disk; the single add/commit site lock from t261006-07 is kept
     at full strength.

Run: server/engine/.venv/bin/python -B -m pytest \\
      server/engine/tests/test_t261007_06_already_settled_face.py -q
"""
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
from shared import ConflictSettleArgs  # noqa: E402


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _ok_git(repo: Path, *args: str) -> str:
    p = _git(repo, *args)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def mid_merge(tmp_path: Path) -> Path:
    """Real repo in the "merge in progress + one UU file" shape (main/lane both
    touched one file); main is the default branch, the lane is `lane`."""
    r = tmp_path / "repo"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    f = r / "conflict.txt"
    f.write_text("base\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "base")
    default = _ok_git(r, "rev-parse", "--abbrev-ref", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    f.write_text("lane side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "lane change")
    _ok_git(r, "checkout", default)
    f.write_text("main side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "main change")
    _ok_git(r, "checkout", "lane")
    p = _git(r, "merge", default)
    assert p.returncode != 0, "fixture produced no conflict"
    return r


def _resolve_without_add(repo: Path) -> None:
    """Resolve the conflict in the agent stance: edit the file, NEVER git add."""
    f = repo / "conflict.txt"
    f.write_text("lane side\nmain side\n", encoding="utf-8")
    st = _ok_git(repo, "status", "--porcelain")
    assert "UU" in st, "precondition: the index must stay UU (agent sandbox stance)"


def _settle(repo: Path, base_ref: str = "main"):
    import asyncio
    return asyncio.run(aa.settle_conflict_resolution(
        ConflictSettleArgs(ticket_id="t261007-06", worktree=str(repo),
                           branch="lane", base_ref=base_ref, round_no=4)))


def _join_settle(repo: Path) -> str:
    orig = aa.REPO_ROOT
    aa.REPO_ROOT = repo
    try:
        return aa._settle_worktree_lane(repo, "t261007-06", "implement", 2, face="join")
    finally:
        aa.REPO_ROOT = orig


# ---------------- F1: the incident sequence ----------------

def test_incident_sequence_reports_already_settled(mid_merge):
    """resolve -> join lands the merge commit (MERGE_HEAD consumed) -> the
    branch-side settle must NOT fail with "no merge in progress": it reports
    ok=True + already_settled=True pointing at the commit already on disk."""
    r = mid_merge
    _resolve_without_add(r)
    note = _join_settle(r)
    assert "zero residue" in note, note
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0
    head = _ok_git(r, "rev-parse", "--short", "HEAD")
    res = _settle(r)
    assert res.ok is True, ("a settled merge must not read as a settle failure "
                            "(KI-213 root cause): %s" % res.error)
    assert res.already_settled is True
    assert res.commit == head, "the receipt points at the commit already on disk"
    assert res.remaining_files == []


def test_direct_probe_on_merged_face_agrees_with_disk(mid_merge):
    """L3 disk-agreement face at L1 level: MERGE_HEAD absent, commit present,
    zero markers, parsable -> the probe's verdict agrees with the disk."""
    r = mid_merge
    _resolve_without_add(r)
    assert _join_settle(r)
    probe = aa._measure_merged_face(r, "main")
    assert probe.ok and probe.already_settled and probe.commit


# ---------------- F2: fail-closed counter-cases (measured facts, no assertion) ----------------

def test_base_not_ancestor_fails_with_measured_facts(tmp_path: Path):
    """MERGE_HEAD absent and main NOT merged into the lane (main diverged with
    its own commit): the probe fails closed and the error carries the measured
    facts — never a "merging state" claim."""
    r = tmp_path / "repo"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "base")  # init's default branch IS `main`
    _ok_git(r, "checkout", "-b", "lane")
    (r / "b.txt").write_text("b\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "lane work")
    # main moves ahead on its own file (a.txt differs, no conflict): main is now
    # NOT an ancestor of the lane HEAD and the lane does not carry it.
    _ok_git(r, "checkout", "main")
    (r / "a.txt").write_text("a-main\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "main-side change")
    _ok_git(r, "checkout", "lane")
    res = _settle(r)
    assert res.ok is False and res.already_settled is False
    assert "no merge in progress (MERGE_HEAD does not exist)" in res.error
    assert "is NOT an ancestor of HEAD" in res.error
    assert "merging state" not in res.error


def test_dirty_face_fails_closed_even_when_merged(mid_merge):
    """The merge commit is on disk but the face is dirty: NOT judged settled
    (the probe must not fake ok over an unparsable face)."""
    r = mid_merge
    _resolve_without_add(r)
    assert _join_settle(r)
    (r / "conflict.txt").write_text("dirty\n", encoding="utf-8")
    res = _settle(r)
    assert res.ok is False and res.already_settled is False
    assert "dirty files: 1" in res.error and "merging state" not in res.error


def test_marker_residue_in_face_fails_closed_naming_files(mid_merge):
    """Residue in the changed face: fail-closed, files named, never ok."""
    r = mid_merge
    _resolve_without_add(r)
    assert _join_settle(r)
    # Commit a marker-shaped line behind the probe's back, then clean the tree.
    (r / "conflict.txt").write_text("ok\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "clean face again")
    (r / "other.txt").write_text("<<<<<<< injected\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "residue committed as content")
    res = _settle(r)
    assert res.ok is False and "other.txt" in res.error
    assert "marker residue" in res.error


# ---------------- F3: malformed inputs (fail closed, never raise) ----------------

def test_nonexistent_worktree_fails_closed(tmp_path: Path):
    res = _settle(tmp_path / "does-not-exist")
    assert res.ok is False and res.already_settled is False
    assert "does not exist" in res.error


def test_empty_base_ref_defaults_to_main(mid_merge):
    """base_ref="" falls back to "main" (both workflow call sites pass main;
    an empty string must not turn into a broken git argument)."""
    r = mid_merge
    _resolve_without_add(r)
    assert _join_settle(r)
    import asyncio
    res = asyncio.run(aa.settle_conflict_resolution(
        ConflictSettleArgs(ticket_id="t261007-06", worktree=str(r),
                           branch="lane", base_ref="", round_no=4)))
    assert res.ok is True and res.already_settled is True


def test_unknown_base_ref_fails_closed(mid_merge):
    """base_ref naming a missing ref: named fail-closed error, no exception."""
    r = mid_merge
    _resolve_without_add(r)
    assert _join_settle(r)
    res = _settle(r, base_ref="no-such-ref")
    assert res.ok is False and "merging state" not in res.error


# ---------------- F4: text discipline + the single add/commit lock ----------------

def test_no_unconditional_merging_state_assertion_in_dev_lane():
    """The KI-213 block text is gone from dev_lane (the two block sites now
    quote the measured facts; the two remaining "merging state" strings live
    in the abort-failure path where the state is genuinely merging)."""
    src = Path(dev_lane.__file__).read_text("utf-8")
    assert "The worktree is in a merging state" not in src
    # The light exit is named at both settle-failure block sites, gated on the
    # measured facts (not on the old error prose).
    assert src.count("is an ancestor of HEAD") >= 4  # 2 gates + 2 message texts
    assert src.count("a single retry_qc resumes") == 2


def test_single_add_commit_site_lock_kept():
    """t261006-07's lock at full strength: `_measure_merged_face` is read-only
    (no add/commit), the core stays the single add/commit sequence, and the
    activity still routes through the core passing base_ref."""
    src = Path(aa.__file__).read_text("utf-8")
    assert src.count("def _settle_merge_core(") == 1
    assert src.count("def _measure_merged_face(") == 1
    act = src.split("async def settle_conflict_resolution(", 1)[1]
    act = act.split("def _measure_merged_face(", 1)[0]
    assert "return _settle_merge_core(wt, args.ticket_id, args.round_no,\n" \
           "                              base_ref=args.base_ref or \"main\")" in act
    assert '"add", "-A"' not in act, "the activity body must not keep a second add sequence"
    probe = src.split("def _measure_merged_face(", 1)[1].split("\n\ndef ", 1)[0]
    assert probe.count('"add"') == 0 and probe.count('"commit"') == 0, \
        "the probe is read-only by construction"
    core = src.split("def _settle_merge_core(", 1)[1].split("\n\ndef ", 1)[0]
    assert core.count('"add", "-A"') == 1, "the add sequence lives only in the shared core"
    assert "_measure_merged_face(wt, base_ref)" in core, \
        "the MERGE_HEAD-absent branch reads the disk truth, not an assertion"
