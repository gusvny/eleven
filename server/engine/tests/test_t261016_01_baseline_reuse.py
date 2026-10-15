#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-01 — named main-baseline reuse across main tips.

The baseline cache is keyed on main's EXACT tip, so every main advance used
to force a full baseline suite run (~27 min on sandbar) even when the judged
surface (the whole tree the suite runs against, minus declared prose/state
excludes) did not change. This file proves the new behavior end to end:

  - a main advance that CANNOT touch the judged surface reuses the nearest
    ancestor's baseline, the baseline suite does NOT run, and the round
    record NAMES the reuse (source/tips/note) — silent reuse is impossible;
  - a main advance that CAN touch the judged surface (suite OR product code)
    forces a rebuild judged at the NEW tip;
  - every ambiguity (non-ancestor tip, malformed cache, git failure,
    filename/body mismatch, ambiguous candidates) fails closed to a rebuild.

White-box over server/engine/develop_certify.py on injected seams (stub
runner, real tmp git repos for the main-tip resolution and the ancestor /
surface-diff git calls). Zero docker, zero Temporal, never touches 3099; the
integration suite itself is never executed here.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop"
REPO = "sandbar"


# ---- seams -------------------------------------------------------------------

def ledger(tmp_path):
    return tmp_path / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def guard_path(tmp_path):
    return tmp_path / "ledger" / "guard-anchor.json"


def landing(repo, rev, at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": "t1",
            "line": LINE, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def header(failed_names):
    return {"id": dc.mint_id("run"),
            "cases": {"ran": 10, "failed": len(failed_names),
                      "env_failed": 0},
            "failed_names": list(failed_names)}


def git(path, *args):
    p = subprocess.run(["git", "-C", str(path)] + list(args), check=True,
                       capture_output=True, text=True)
    return (p.stdout or "").strip()


def commit(path, relpath, text, msg):
    f = path / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, "utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-qm", msg)
    return git(path, "rev-parse", "refs/heads/main")


def setup(tmp_path, monkeypatch):
    """Isolated project store + a real git repo as the line worktree, with
    one commit on main."""
    projects = tmp_path / "projects"
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    repo = projects / REPO / "data" / "develop" / "wt" / REPO
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "it@t")
    git(repo, "config", "user.name", "it")
    tip0 = commit(repo, "a.txt", "a\n", "m0")
    return repo, tip0


def run_round(tmp_path, runner, roster=None):
    p = ledger(tmp_path)
    dc.append_rows([landing(REPO, "rev1")], p)
    return dc.run_line_round(
        LINE, "change", guard_path(tmp_path), runner, reader(p), writer(p),
        "round-engine", "booked-v1", project=REPO,
        roster=roster or {"entries": []})


def rel_of(out):
    return out["rounds"][0]["relative"]["per_repo"][REPO]


# ---- R1: named reuse after a main commit off the judged surface --------------

def test_r1_docs_only_advance_reuses_ancestor_and_names_it(tmp_path,
                                                           monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    tip1 = commit(repo, "docs/x.md", "prose\n", "docs only")
    dc.write_baseline(REPO, REPO, tip0, ["d1"], ["f1"])
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header(["d1", "f1"])

    out = run_round(tmp_path, runner)
    # the baseline suite did NOT run: only the line's own run happened
    assert calls == ["rev1"]
    assert out["rounds"][0]["verdict"] == "green"
    rel = rel_of(out)
    assert rel["baseline_source"] == "reused"
    assert rel["baseline_tip"] == tip0
    assert rel["judged_tip"] == tip1
    assert rel["note"] == ("baseline_reused:%s@%s:for:%s:surface_unchanged"
                           % (REPO, tip0[:12], tip1[:12]))
    # the reused fail set is the OLD tip's: main's debt carried, no re-key
    assert rel["carried_debt"] == ["d1"] and rel["flaky_hits"] == ["f1"]
    bl = dc.read_baseline(REPO, REPO, tip1)
    assert bl is None  # reuse never re-keys the cache


def test_r1b_round_row_carries_duration_ms(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    commit(repo, "docs/x.md", "prose\n", "docs only")
    dc.write_baseline(REPO, REPO, tip0, [], [])
    out = run_round(tmp_path, lambda c: header([]))
    row = out["rounds"][0]
    assert isinstance(row.get("duration_ms"), int) and row["duration_ms"] >= 0


# ---- R2/R7: a judged-surface commit forces a rebuild at the NEW tip ----------

@pytest.mark.parametrize("relpath,text", [
    ("integration/sc_surface.py", "x\n"),      # the suite source itself
    ("server/engine/prod_module.py", "x\n"),   # product code (review C1)
])
def test_r2_surface_commit_forces_rebuild(tmp_path, monkeypatch, relpath,
                                          text):
    repo, tip0 = setup(tmp_path, monkeypatch)
    dc.write_baseline(REPO, REPO, tip0, ["stale-debt"], [])
    tip1 = commit(repo, relpath, text, "touch the judged surface")
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        # main's NEW fail set: it no longer carries stale-debt
        return header(["fresh-debt"]) if cand[0]["revision"] == tip1 \
            else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]  # the baseline suite RAN, at the new tip
    rel = rel_of(out)
    assert rel["baseline_source"] == "rebuilt"
    assert rel["baseline_tip"] == tip1 and rel["judged_tip"] == tip1
    assert rel["note"] == "cache_built:%s@%s" % (REPO, tip1[:12])
    # the NEW tip's fail set is what judges: stale-debt must not excuse
    dc.read_baseline  # (naming read) the cache was re-written at the new tip
    bl = dc.read_baseline(REPO, REPO, tip1)
    assert bl["deterministic_fails"] == ["fresh-debt"]


def test_r3_plain_cache_hit_named_cache(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    dc.write_baseline(REPO, REPO, tip0, ["d1"], [])
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header(["d1"])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1"]
    rel = rel_of(out)
    assert rel["baseline_source"] == "cache"
    assert rel["baseline_tip"] == rel["judged_tip"] == tip0
    assert rel["note"] == "cache_hit:%s@%s" % (REPO, tip0[:12])


# ---- R4: every ambiguity fails closed to a rebuild ---------------------------

def test_r4a_non_ancestor_tip_rebuilds(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    commit(repo, "docs/x.md", "prose\n", "docs only")
    tip1 = git(repo, "rev-parse", "refs/heads/main")
    # a cached tip that is NOT an ancestor of main (fabricated sha): not
    # reusable, however clean its diff would be
    dc.write_baseline(REPO, REPO, "b" * 40, ["d1"], [])
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header(["d1"]) if cand[0]["revision"] != "rev1" else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]
    assert rel_of(out)["baseline_source"] == "rebuilt"


def test_r4b_git_failure_fails_closed(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    commit(repo, "docs/x.md", "prose\n", "docs only")
    tip1 = git(repo, "rev-parse", "refs/heads/main")
    dc.write_baseline(REPO, REPO, tip0, ["d1"], [])
    monkeypatch.setattr(dc, "_surface_unchanged",
                        lambda wt, old, new: False)  # git unreadable -> dirty
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header(["d1"]) if cand[0]["revision"] != "rev1" else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]
    assert rel_of(out)["baseline_source"] == "rebuilt"


def test_r4c_unresolvable_main_tip_named_red(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.setattr(dc, "_git_main_tip", lambda wt: "")
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1"]
    rel = rel_of(out)
    assert rel["verdict"] == "red"
    assert rel["note"] == "main_tip_unresolvable:%s" % REPO


# ---- R5: the NEWEST qualifying ancestor wins ---------------------------------

def test_r5_newest_qualifying_ancestor_wins(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    tip1 = commit(repo, "docs/a.md", "a\n", "docs 1")
    tip2 = commit(repo, "docs/b.md", "b\n", "docs 2")
    base = dc._baseline_dir(REPO)
    base.mkdir(parents=True, exist_ok=True)
    for tip, det, built in ((tip0, ["old"], 1000), (tip1, ["newer"], 2000)):
        obj = {"main_tip": tip, "deterministic_fails": det,
               "flaky": [], "built_at": built}
        (base / ("%s@%s.json" % (REPO, tip[:12]))).write_text(
            json.dumps(obj) + "\n", "utf-8")
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header(["newer"])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1"]
    rel = rel_of(out)
    assert rel["baseline_source"] == "reused"
    assert rel["baseline_tip"] == tip1      # newest qualifying, not the oldest
    assert rel["judged_tip"] == tip2
    assert rel["carried_debt"] == ["newer"]


# ---- R6/R8: malformed caches are skipped, never guessed ----------------------

def _write_cache(base_dir, repo, filename, body):
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / filename).write_text(json.dumps(body) + "\n", "utf-8")


@pytest.mark.parametrize("filename,body", [
    # body tip not a 40-hex sha
    ("sandbar@aaaaaaaaaaaaaaaa.json",
     {"main_tip": "zzz", "deterministic_fails": [], "flaky": []}),
    # body tip does not match the filename's 12-char slice
    ("sandbar@bbbbbbbbbbbb.json",
     {"main_tip": "a" * 40, "deterministic_fails": [], "flaky": []}),
    # fail sets of the wrong shape
    ("sandbar@cccccccccccc.json",
     {"main_tip": "c" * 40, "deterministic_fails": "d1", "flaky": []}),
])
def test_r6_malformed_cache_candidates_skipped(tmp_path, monkeypatch,
                                               filename, body):
    repo, tip0 = setup(tmp_path, monkeypatch)
    commit(repo, "docs/x.md", "prose\n", "docs only")
    tip1 = git(repo, "rev-parse", "refs/heads/main")
    _write_cache(dc._baseline_dir(REPO), REPO, filename, body)
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header([]) if cand[0]["revision"] != "rev1" else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]  # nothing reusable -> rebuild
    assert rel_of(out)["baseline_source"] == "rebuilt"


def test_r8_ambiguous_candidates_decided_per_body_sha(tmp_path, monkeypatch):
    """Two cached files whose FILENAME slices look interchangeable: the
    ancestor relation is decided per full body sha — the surface-clean
    ancestor is reused, the non-ancestor one never poisons the choice."""
    repo, tip0 = setup(tmp_path, monkeypatch)
    tip1 = commit(repo, "docs/x.md", "prose\n", "docs only")
    base = dc._baseline_dir(REPO)
    # honest ancestor cache under a WRONG filename (slice mismatch): skipped
    _write_cache(base, REPO, "sandbar@dddddddddddd.json",
                 {"main_tip": tip0, "deterministic_fails": ["d1"],
                  "flaky": [], "built_at": 9999})
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header([]) if cand[0]["revision"] != "rev1" else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]  # filename/body mismatch -> not reusable
    assert rel_of(out)["baseline_source"] == "rebuilt"


def test_r9_unreadable_cache_file_skipped(tmp_path, monkeypatch):
    repo, tip0 = setup(tmp_path, monkeypatch)
    commit(repo, "docs/x.md", "prose\n", "docs only")
    tip1 = git(repo, "rev-parse", "refs/heads/main")
    base = dc._baseline_dir(REPO)
    base.mkdir(parents=True, exist_ok=True)
    (base / ("%s@%s.json" % (REPO, tip0[:12]))).write_text(
        "{not json", "utf-8")
    calls = []

    def runner(cand):
        calls.append(cand[0]["revision"])
        return header([]) if cand[0]["revision"] != "rev1" else header([])

    out = run_round(tmp_path, runner)
    assert calls == ["rev1", tip1]
    assert rel_of(out)["baseline_source"] == "rebuilt"
