#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261030-25 (KI-429) — the ledger-side reachability net.

The incident: between 12:00 and 12:16 a test fixture wrote six ``run-*``
directories into the REAL projects root, each ``ran=1 pass=1 fail=0`` and each
citing a revision that is NOT a git object in this repo
(``git cat-file -t 4a994ea9`` -> "Not a valid object name"). The tick-entry
reconciliation then booked them: 36 certification rows and 7 freeze episodes
at one instant, and the develop-buffer line was frozen on a revision that
never existed here. Nothing in the ledger asked whether the repository could
produce the revision it was certifying. This battery is that question.

Legs (all on injected seams — temp git repos, temp ledgers; zero docker, zero
Temporal, zero network, never touches 3099):

- G1 ``revision_reachable`` is the git question: a commit object answers True,
  a fabricated sha answers False, a missing tree answers False.
- G2 ``unreachable_candidates`` NAMES what it refuses: the unreachable
  revision with its repo, a repository the project never declared
  (``repo_not_resolvable``), and a malformed member — judged, never skipped.
- G3 ``unreachable_refusal`` names the check, the repo@revision and the caller.
- R1 THE INCIDENT: a run row citing a fabricated revision heals into NO
  certification and NO freeze — one named refusal row carries the revision and
  the caller, and a replay writes nothing more.
- R2 TEETH UNCHANGED (green): the same fixture with a REAL revision still
  mints exactly one certification and opens no freeze.
- R3 TEETH UNCHANGED (red): the same fixture with a REAL revision and a
  content red still mints the certification AND opens exactly one freeze.
- R4 the settle path refuses too: a round whose candidate revision is not a
  git object writes no certification and no freeze.
- R5 the refusal is only about reachability: a candidate set whose revision is
  a real commit in the line worktree is not refused (both outcomes above).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop-buffer"
REPO = "sandbar"
FAKE_REV = "4a994ea9eed31cd728a495d83a24603255c3550b"  # the measured witness
RUN_ID = "run-01M65CXTPHMG7KD0KPE2BS5VG0"              # the measured witness


# ---- fixtures --------------------------------------------------------------

def git(argv, cwd):
    subprocess.run(["git"] + argv, cwd=str(cwd), check=True,
                   capture_output=True)


def line_tree(tmp_path, monkeypatch, name=REPO):
    """A projects root whose project declares one line worktree that is a REAL
    git repository with one commit. Returns (projects_root, project_name,
    head_sha). The tree is what ``line_repo_dir`` resolves and what the guard
    asks, so the projects root is injected (SANDBAR_PROJECTS_DIR — the same
    seam the engine reads) rather than assumed."""
    projects = tmp_path / "projects"
    develop = projects / "sandbar" / "data" / "develop"
    dive = develop / "wt" / name
    dive.mkdir(parents=True)
    git(["init", "-q", "-b", "main", "."], dive)
    git(["config", "user.email", "t@example.invalid"], dive)
    git(["config", "user.name", "t"], dive)
    (dive / "file.txt").write_text("one\n", encoding="utf-8")
    git(["add", "-A"], dive)
    git(["commit", "-qm", "one"], dive)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(dive),
                          check=True, capture_output=True,
                          text=True).stdout.strip()
    (develop / "lines.json").write_text(
        '[{"line_id": "%s", "repositories": [{"name": "%s", '
        '"branch": "main"}]}]\n' % (LINE, name), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    return projects, "sandbar", head


def ledger(tmp_path):
    return tmp_path / "ledger" / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def run_row(revision, verdict="green", failed_names=None, rid=RUN_ID):
    return {"v": "run-ledger-v1", "id": rid,
            "source": dc.LINE_ROUND_RUN_SOURCE,
            "repos": [{"repo": REPO, "revision": revision}],
            "verdict": verdict, "verdict_rule": "content-v1",
            "cases": {"ran": 2, "passed": 2 if verdict == "green" else 1,
                      "failed": 0 if verdict == "green" else 1,
                      "env_failed": 0},
            "failed_names": failed_names or [],
            "fail_receipts": {"case-b": {"reason": "assert_mismatch",
                                         "evidence": "AssertionError: x"}}
            if verdict == "red" else {}}


def rows_of(path):
    rows, bad = dc.read_rows(path)
    assert not bad
    return rows


def certs(rows):
    return [r for r in rows if r.get("kind") == dc.KIND_CERT]


def freezes(rows):
    return [r for r in rows if r.get("kind") == dc.KIND_FREEZE]


def growths(rows):
    return [r for r in rows if r.get("kind") == dc.KIND_RANGE_GROWTH]


def heal(project, path, runs_rows, sole_line=True):
    return dc.reconcile_unrecorded_rounds(
        LINE, rows_of(path), runs_rows, writer(path), "dispatcher-scan",
        "scan-default-v1", 1793332801440, sole_line=sole_line,
        project=project)


# ---- G1: the git question ---------------------------------------------------

def test_g1_a_commit_object_is_reachable(tmp_path, monkeypatch):
    _, _project, head = line_tree(tmp_path, monkeypatch)
    dive = tmp_path / "projects" / "sandbar" / "data" / "develop" / "wt" / REPO
    assert dc.revision_reachable(dive, head) is True


def test_g1_a_fabricated_sha_is_not_reachable(tmp_path, monkeypatch):
    line_tree(tmp_path, monkeypatch)
    dive = tmp_path / "projects" / "sandbar" / "data" / "develop" / "wt" / REPO
    # the measured witness: `git cat-file -t 4a994ea9` -> Not a valid object
    assert dc.revision_reachable(dive, FAKE_REV) is False


def test_g1_missing_tree_and_garbage_answer_false(tmp_path, monkeypatch):
    assert dc.revision_reachable(None, FAKE_REV) is False
    assert dc.revision_reachable(tmp_path / "nope", FAKE_REV) is False
    assert dc.revision_reachable(tmp_path, "") is False
    assert dc.revision_reachable(tmp_path, "   ") is False


def test_g1_a_blob_sha_is_not_a_commit(tmp_path, monkeypatch):
    """Reachability means a COMMIT (the ledger hands it to a checkout): a
    blob object with the same content answers False."""
    _, _project, head = line_tree(tmp_path, monkeypatch)
    dive = tmp_path / "projects" / "sandbar" / "data" / "develop" / "wt" / REPO
    blob = subprocess.run(["git", "rev-parse", "%s:file.txt" % head],
                          cwd=str(dive), check=True, capture_output=True,
                          text=True).stdout.strip()
    assert dc.revision_reachable(dive, blob) is False


# ---- G2: the guard names what it refuses ------------------------------------

def test_g2_names_the_unreachable_revision(tmp_path, monkeypatch):
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    blocked = dc.unreachable_candidates(
        [{"repo": REPO, "revision": FAKE_REV}], project)
    assert blocked == [{"repo": REPO, "revision": FAKE_REV,
                        "why": dc.REVISION_UNREACHABLE}]


def test_g2_undeclared_repository_is_named_not_guessed(tmp_path, monkeypatch):
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    blocked = dc.unreachable_candidates(
        [{"repo": "src", "revision": FAKE_REV}], "sandbar")
    assert blocked and blocked[0]["why"] == "repo_not_resolvable"
    assert blocked[0]["repo"] == "src"


def test_g2_malformed_member_is_judged_never_skipped(tmp_path, monkeypatch):
    line_tree(tmp_path, monkeypatch)
    blocked = dc.unreachable_candidates(
        ["not-a-dict", {"repo": REPO}, {"repo": "", "revision": "x"}],
        "sandbar")
    assert len(blocked) == 3
    assert all(b["why"] == "candidate_malformed" for b in blocked)


def test_g2_reachable_set_passes_clean(tmp_path, monkeypatch):
    _, project, head = line_tree(tmp_path, monkeypatch)
    assert dc.unreachable_candidates(
        [{"repo": REPO, "revision": head}], project) == []


def test_g3_refusal_names_check_revision_and_caller(tmp_path, monkeypatch):
    line_tree(tmp_path, monkeypatch)
    blocked = dc.unreachable_candidates(
        [{"repo": REPO, "revision": FAKE_REV}], "sandbar")
    text = dc.unreachable_refusal(blocked, "reconciled:%s" % RUN_ID)
    assert text == ("certification_refused:revision_not_a_git_object:"
                    "%s@%s:caller=reconciled:%s" % (REPO, FAKE_REV, RUN_ID))


# ---- R1: THE INCIDENT -------------------------------------------------------

def test_r1_fabricated_run_mints_no_cert_and_no_freeze(tmp_path, monkeypatch):
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    entries = heal(project, p, [run_row(FAKE_REV)])
    rows = rows_of(p)
    assert certs(rows) == []            # no certification row
    assert freezes(rows) == []          # no freeze
    growth = growths(rows)
    assert len(growth) == 1             # one named refusal, nothing else
    reason = growth[0]["reason"]
    assert reason.startswith("unrecorded_round_refused:")
    assert dc.REVISION_UNREACHABLE in reason
    assert FAKE_REV in reason and REPO in reason
    assert ("caller=reconciled:%s" % RUN_ID) in reason
    assert entries and entries[0]["state"] == "error"
    assert entries[0]["run"] == RUN_ID
    assert dc.REVISION_UNREACHABLE in entries[0]["error"]


def test_r1_replay_writes_nothing_more(tmp_path, monkeypatch):
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    heal(project, p, [run_row(FAKE_REV)])
    before = len(rows_of(p))
    entries = heal(project, p, [run_row(FAKE_REV)])
    assert len(rows_of(p)) == before    # idempotent: the refusal is recorded
    assert entries == []                # and never replayed


def test_r1_a_malformed_candidate_set_never_certifies(tmp_path, monkeypatch):
    """A run row whose revision set is not a well-formed set of {repo,
    revision} pairs never certifies either — it takes the existing
    unjudgable-header branch (one range-growth row, no freeze). The guard's
    own malformed name is covered by G2."""
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    bad = run_row(FAKE_REV)
    bad["repos"] = [{"repo": REPO, "revision": ""}]
    entries = heal(project, p, [bad])
    rows = rows_of(p)
    assert certs(rows) == [] and freezes(rows) == []
    assert "header_unjudgable" in growths(rows)[0]["reason"]
    assert entries == [] or entries[0]["state"] == "reconciled"


# ---- R2/R3: teeth unchanged -------------------------------------------------

def test_r2_a_real_green_round_still_certifies(tmp_path, monkeypatch):
    _, project, head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    entries = heal(project, p, [run_row(head)])
    rows = rows_of(p)
    assert len(certs(rows)) == 1
    assert freezes(rows) == []
    assert certs(rows)[0]["repos"] == [{"repo": REPO, "revision": head}]
    assert entries[0]["state"] == "reconciled"


def test_r3_a_real_red_round_still_freezes(tmp_path, monkeypatch):
    _, project, head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    heal(project, p, [run_row(head, verdict="red",
                                  failed_names=["case-b"])])
    rows = rows_of(p)
    assert len(certs(rows)) == 1
    frz = freezes(rows)
    assert len(frz) == 1                # a real red still freezes the line
    assert frz[0]["cause"] == certs(rows)[0]["id"]


# ---- R4: where the net lives, and why --------------------------------------

def test_r4_the_net_lives_on_the_reconciliation_path(tmp_path, monkeypatch):
    """Scope, stated as a test (t261030-25): the settle path hands the
    candidate to the round's own runner, which CHECKOUTS that revision in a
    tree of its own — an unreachable revision dies there as a named
    could-not-run (no header, no certification), so the settle path cannot
    mint over one and the net does not re-judge what the engine just resolved
    from the line worktree. The data-driven path, where a certification is
    minted from a run ROW the engine never drove, is the one that fabricated
    production state — and that is where the net refuses (R1)."""
    projects, project, _head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    dc.append_rows([{"kind": "landing", "id": dc.mint_id("ldg", 1),
                     "ticket": "t1", "line": LINE,
                     "repos": [{"repo": REPO, "revision": FAKE_REV}],
                     "actor": "test", "at": 1}], p)
    # the same fabricated set is refused by the net when it arrives as DATA
    entries = heal(project, p, [run_row(FAKE_REV)])
    rows = rows_of(p)
    assert certs(rows) == [] and freezes(rows) == []
    assert entries and entries[0]["state"] == "error"
    assert dc.REVISION_UNREACHABLE in entries[0]["error"]


# ---- R5: the guard is about reachability only -------------------------------

def test_r5_no_blocked_candidates_no_behaviour_change(tmp_path, monkeypatch):
    _, project, head = line_tree(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    assert dc.unreachable_candidates([{"repo": REPO, "revision": head}],
                                    project) == []
    heal(project, p, [run_row(head)])
    rows = rows_of(p)
    assert len(certs(rows)) == 1 and freezes(rows) == []
