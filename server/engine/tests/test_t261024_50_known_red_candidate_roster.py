# -*- coding: utf-8 -*-
"""t261024-50 — the known-red book reads from the CANDIDATE tree.

L1 unit truth table over a REAL git fixture (tmp-local repos, zero Temporal,
zero network, zero integration entry — UT discipline):

  face        | input                                          | expected
  ------------+------------------------------------------------+-----------
  roster read | booking committed on the LINE branch only      | round roster
              | (main untouched)                               | carries the name
  verdict     | same booking                                   | merge-base(main,
              |                                                | line tip) == main
              |                                                | (fast-forward holds)
  fail-closed | book on the line is non-JSON                   | CertifyError
              |                                                | known_red_roster_
              |                                                | unreadable:<repo>
  fail-closed | book on the line is not an object              | named CertifyError
  inert       | no declared repo carries the book              | {} (legal empty)
  ambiguous   | TWO declared repos carry the book              | known_red_roster_
              |                                                | ambiguous
  env face    | carrier worktree file present                  | injected env points
              |                                                | at the worktree copy
  env face    | branch tip carries the book, worktree file     | (None, named note)
              | deleted                                        | roster_env_not_
              |                                                | injected:worktree_
              |                                                | file_absent
  tick wiring | scheduled tick with a capturing runner seam    | env carries the
              |                                                | worktree path; note
              |                                                | surfaces on the entry

Fault-mode honesty: every non-dict/malformed input face is exercised against
the real git show subprocess, not a stub, and the git-show failure path is
exercised through a corrupt document (the same rc!=0 branch).
"""
import json
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import develop_certify as dc  # noqa: E402
import shared  # noqa: E402

PROJECT = "proj"
LINE = "buffer"
BOOK_REL = "integration/known-red-baseline.json"
GOOD_BOOK = {"meta": {"policy": "shrink-only"},
             "entries": [{"name": "old_red", "verdict": "booked",
                          "owner": "integration", "retire_when": "never"}]}


def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s"
                             % (" ".join(args), p.stderr.strip()))
    return p


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "base", cwd=path)
    return path


def _commit_file(repo: Path, fname: str, text: str, msg: str) -> str:
    repo.joinpath(fname).parent.mkdir(parents=True, exist_ok=True)
    repo.joinpath(fname).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _book_text(entries, extra_meta=None):
    meta = {"policy": "shrink-only"}
    if extra_meta:
        meta.update(extra_meta)
    return json.dumps({"meta": meta, "entries": entries}, indent=1)


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    """One project, one line of two repos; rA's line branch carries the
    book, main does not; worktrees live at the develop wt/ (production
    shape) and ARE the line checkouts; a declared line names both repos."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    dev = shared.develop_dir(PROJECT)
    wt_root = dev / "wt"
    wt_root.mkdir(parents=True)
    repos, wts = {}, {}
    for name in ("rA", "rB"):
        repo = _init_repo(tmp_path / name)
        _git("worktree", "add", "-b", "line/x", str(wt_root / name),
             "main", cwd=repo)
        repos[name] = repo
        wts[name] = wt_root / name
    _commit_file(wts["rA"], BOOK_REL,
                 _book_text([{"name": "old_red", "verdict": "booked"}]),
                 "seed book on the line")
    (dev / "lines.json").write_text(json.dumps([
        {"line_id": LINE, "scope": "epic", "owner": "integration",
         "repositories": [{"name": "rA", "branch": "line/x"},
                          {"name": "rB", "branch": "line/x"}],
         "extra_scenarios": [], "version": 1}]), encoding="utf-8")
    return {"tmp": tmp_path, "repos": repos, "wts": wts, "dev": dev,
            "wt_root": wt_root}


def _book_a_booking(proj, text):
    """A booking committed on rA's LINE branch only — main never moves."""
    return _commit_file(proj["wts"]["rA"], BOOK_REL, text,
                        "book flaky_red on the line")


# ------------------------------------------------- acceptance 1: no FF break

def test_line_side_booking_keeps_fast_forward(proj):
    main_sha = _git("rev-parse", "refs/heads/main",
                    cwd=proj["repos"]["rA"]).stdout.strip()
    _book_a_booking(proj, _book_text([
        {"name": "old_red", "verdict": "booked"},
        {"name": "flaky_red", "verdict": "booked"}]))
    repo = proj["repos"]["rA"]
    # the booking lives ONLY on the line branch
    assert _git("rev-parse", "refs/heads/main", cwd=repo).stdout.strip() \
        == main_sha
    tip = _git("rev-parse", "refs/heads/line/x", cwd=repo).stdout.strip()
    mb = _git("merge-base", "refs/heads/main", tip, cwd=repo).stdout.strip()
    assert mb == main_sha, "line-side booking keeps main an ancestor"
    assert "flaky_red" in _git("show", "%s:%s" % ("line/x", BOOK_REL),
                               cwd=repo).stdout


# ------------------------------------------- acceptance 2: round sees booking

def test_round_roster_reads_line_tip_booking_without_main_commit(proj):
    before = dc._known_red_roster(PROJECT, LINE)
    assert "flaky_red" not in json.dumps(before)
    _book_a_booking(proj, _book_text([
        {"name": "old_red", "verdict": "booked"},
        {"name": "flaky_red", "verdict": "booked"}]))
    roster = dc._known_red_roster(PROJECT, LINE)
    names = {e.get("name") for e in roster.get("entries", [])
             if isinstance(e, dict)}
    assert {"old_red", "flaky_red"} <= names
    # ledger fields ride along untouched
    assert roster["meta"]["policy"] == "shrink-only"


# ------------------------------------------------- acceptance 3: fail closed

def test_unreadable_book_is_a_named_error_not_empty(proj):
    _book_a_booking(proj, "{not json at all")
    with pytest.raises(dc.CertifyError, match="known_red_roster_unreadable:rA"):
        dc._known_red_roster(PROJECT, LINE)


def test_non_object_book_is_a_named_error(proj):
    _book_a_booking(proj, "[1, 2, 3]")
    with pytest.raises(dc.CertifyError,
                       match="known_red_roster_unreadable:rA:document_not_object"):
        dc._known_red_roster(PROJECT, LINE)


def test_book_absent_everywhere_is_legal_empty(proj):
    # remove the book on the line branch: git show then reports it absent
    (proj["wts"]["rA"] / BOOK_REL).unlink()
    _git("add", "-A", cwd=proj["wts"]["rA"])
    _git("commit", "-qm", "retract the last row", cwd=proj["wts"]["rA"])
    assert dc._known_red_roster(PROJECT, LINE) == {}
    path, note = dc.known_red_roster_worktree_file(PROJECT, LINE)
    assert path is None and note == ""


def test_two_carriers_are_named_ambiguous(proj):
    _commit_file(proj["wts"]["rB"], BOOK_REL,
                 _book_text([{"name": "b_red", "verdict": "booked"}]),
                 "seed book on rB's line too")
    with pytest.raises(dc.CertifyError, match="known_red_roster_ambiguous"):
        dc._known_red_roster(PROJECT, LINE)


def test_unknown_line_is_named(proj):
    src, why = dc.known_red_roster_source(PROJECT, "no-such-line")
    assert src is None and "no-such-line" in why


# ------------------------------------------------------- env injection faces

def test_worktree_file_is_the_injected_path(proj):
    path, note = dc.known_red_roster_worktree_file(PROJECT, LINE)
    assert note == ""
    assert path == proj["wt_root"] / "rA" / BOOK_REL
    assert path.is_file()


def test_missing_worktree_file_is_named_not_silent(proj):
    (proj["wt_root"] / "rA" / BOOK_REL).unlink()
    path, note = dc.known_red_roster_worktree_file(PROJECT, LINE)
    assert path is None
    assert note == "roster_env_not_injected:worktree_file_absent:rA"
    # the engine-side read (branch tip) stays fresh — only the env copy lags
    roster = dc._known_red_roster(PROJECT, LINE)
    assert roster["entries"][0]["name"] == "old_red"


def test_tick_injects_worktree_path_and_surfaces_note(proj):
    """The scheduled tick points the child runner at the worktree copy and
    carries a worktree-file-absent note on the entry when the two faces
    diverge (review conditions 1+2)."""
    seen = {}

    def capturing_runner(line, env):
        seen["env"] = dict(env or {})
        return None  # runner_missing ends the entry before any round runs

    rows = []
    with mock.patch.object(dc, "should_certify",
                           return_value=(True, "range_non_empty")):
        res = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: (rows, []), append_rows=lambda b: None,
            resolve_runner_fn=capturing_runner, guard_path="/tmp/unused",
            now_ms=1)
    entry = res["lines"][0]
    assert entry["state"] == "runner_missing"
    injected = seen["env"].get("SANDBAR_KNOWN_RED_ROSTER")
    assert injected == str(proj["wt_root"] / "rA" / BOOK_REL)
    assert "note" not in entry

    (proj["wt_root"] / "rA" / BOOK_REL).unlink()
    seen.clear()
    with mock.patch.object(dc, "should_certify",
                           return_value=(True, "range_non_empty")):
        res = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: (rows, []), append_rows=lambda b: None,
            resolve_runner_fn=capturing_runner, guard_path="/tmp/unused",
            now_ms=1)
    entry = res["lines"][0]
    assert "SANDBAR_KNOWN_RED_ROSTER" not in seen["env"]
    assert entry.get("note") == \
        "roster_env_not_injected:worktree_file_absent:rA"


def test_tick_named_error_on_unreadable_book(proj):
    _book_a_booking(proj, "%%% \n broken")
    with mock.patch.object(dc, "should_certify",
                           return_value=(True, "range_non_empty")):
        res = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: ([], []), append_rows=lambda b: None,
            resolve_runner_fn=lambda line, env: None,
            guard_path="/tmp/unused", now_ms=1)
    entry = res["lines"][0]
    assert entry["state"] == "error"
    assert "known_red_roster_unreadable:rA" in entry["error"]
