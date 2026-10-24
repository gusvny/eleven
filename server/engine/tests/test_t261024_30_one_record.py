#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261024-30 — every terminal round leaves exactly ONE named record.

The bug being closed: on the silent-end day, four rounds carried a terminal
face.json whose verdict was red (the face's env rule: env_fail>0 ⇒ red)
while the run's content counts were failed=0 (the record's content rule ⇒
green) — and the delivery ledger held NO row at all: no certification, no
freeze, no range_growth, no abort. Another four rounds had a run row and no
round directory. A round that ends with no row is the bug.

Legs:
- A  env-red face + content-clean run ⇒ exactly ONE green certification
  citing the run; the entry names the env-unverified count; the persisted
  run header (read back from the SAME runs store the engine reads) names
  the rule it used (verdict_rule) and the unverified count. Replay of the
  observed old shape against the new code: same single record, never zero.
- B  a round that dies INSIDE the settle block (the cert append fails)
  leaves exactly ONE named row — kind=range_growth, reason naming the
  exception — and the original error still surfaces.
- B2 the guard's own append failing too: the original exception is never
  masked, and the row-write failure is loud on stderr.
- C  abort × settle: in the settle window the runner registry is empty, so
  the abort face writes NOTHING and the settle path is the one writer —
  exactly one row, whichever face you look at.
- D  baseline cannot be established: regressions come from the CONTENT set,
  never from names that are also unverified (env-only guilt).

Zero docker, zero Temporal, never touches 3099; the runner is a stub.
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


# ---- shared harness (borrowed shape from test_t261016_01_baseline_reuse) ----

def ledger(tmp_path):
    return tmp_path / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def landing(repo, rev, ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": LINE, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def guard_path(tmp_path):
    return tmp_path / "ledger" / "guard-anchor.json"


def env_header(ran=725, env_failed=18):
    """The observed old shape: face env-red, content clean."""
    names = ["env-case-%02d" % i for i in range(env_failed)]
    return {"id": dc.mint_id("run"),
            "cases": {"ran": ran, "failed": 0, "env_failed": env_failed},
            "failed_names": [],
            "unverified_names": names}


def git(path, *args):
    p = subprocess.run(["git", "-C", str(path)] + list(args), check=True,
                       capture_output=True, text=True)
    return (p.stdout or "").strip()


def setup(tmp_path, monkeypatch):
    """Isolated project store + a real git repo as the line worktree, one
    commit on main, and a cache-hit baseline (empty deterministic fails)."""
    projects = tmp_path / "projects"
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    repo = projects / REPO / "data" / "develop" / "wt" / REPO
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "it@t")
    git(repo, "config", "user.name", "it")
    (repo / "a.txt").write_text("a\n", "utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "m0")
    tip = git(repo, "rev-parse", "refs/heads/main")
    dc.write_baseline(REPO, REPO, tip, [], [])
    return repo, tip


def run_round(tmp_path, runner, runs_store=None, project=REPO):
    p = ledger(tmp_path)
    dc.append_rows([landing(REPO, "rev1")], p)
    return dc.run_line_round(
        LINE, "change", guard_path(tmp_path), runner, reader(p), writer(p),
        "round-engine", "booked-v1", project=project,
        roster={"entries": []}, runs_store=runs_store)


def rows_of(path):
    rows, bad = dc.read_rows(path)
    assert not bad
    return rows


# ---- A: the observed old shape replays into ONE green certification --------

def test_a_env_red_face_content_clean_writes_one_green_cert(tmp_path,
                                                            monkeypatch):
    setup(tmp_path, monkeypatch)
    h = env_header()
    out = run_round(tmp_path, lambda c: h)
    rows = rows_of(ledger(tmp_path))
    certs = [r for r in rows if r["kind"] == dc.KIND_CERT]
    # exactly one named record — and it is the certification, never zero
    assert len(certs) == 1
    assert certs[0]["run"] == h["id"]
    assert len(out["rounds"]) == 1
    entry = out["rounds"][0]
    assert entry["state"] == dc.STATE_CERTIFIED and entry["verdict"] == "green"
    # the receipt names the env-unverified count
    assert entry["relative"]["unverified"] == []
    assert h["unverified_count"] == 18
    # no freeze (content red is the only freeze key), no range growth
    assert not [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    assert not [r for r in rows if r["kind"] == dc.KIND_RANGE_GROWTH]


def test_a2_persisted_header_names_the_rule_and_count(tmp_path, monkeypatch):
    """Reader-side evidence: read the run header back from the SAME runs
    store the engine reads — the record says which rule it used."""
    setup(tmp_path, monkeypatch)
    runs = tmp_path / "projects" / REPO / "ledger" / "scenario-runs.jsonl"
    h = env_header()
    run_round(tmp_path, lambda c: h, runs_store=runs)
    lines = [json.loads(x) for x in
             runs.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["verdict"] == "green"
    assert lines[0]["verdict_rule"] == "relative-content-v1"
    assert lines[0]["unverified_count"] == 18


# ---- B: a round that dies inside the settle block still leaves ONE row -----

def test_b_settle_failure_leaves_one_named_row(tmp_path, monkeypatch,
                                               capsys):
    setup(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    dc.append_rows([landing(REPO, "rev1")], p)
    calls = {"n": 0}

    def writer_fails_on_cert(batch):
        # the cert append fails — the production symptom,
        # round_append_rejected's family; a later row write succeeds
        if batch and batch[0].get("kind") == dc.KIND_CERT:
            raise dc.CertifyError("round_append_rejected:['x']")
        return dc.append_rows(batch, p)

    with pytest.raises(dc.CertifyError):
        dc.run_line_round(LINE, "change", guard_path(tmp_path),
                          lambda c: env_header(), reader(p),
                          writer_fails_on_cert, "round-engine", "booked-v1",
                          project=REPO, roster={"entries": []})
    rows = rows_of(p)
    grown = [r for r in rows if r["kind"] == dc.KIND_RANGE_GROWTH]
    # exactly ONE named row, and it names the reason
    assert len(grown) == 1
    assert grown[0]["reason"].startswith(
        "round_settle_failed:CertifyError:round_append_rejected")


def test_b2_guard_append_also_fails_original_error_still_surfaces(
        tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    dc.append_rows([landing(REPO, "rev1")], p)

    def writer_always_fails(batch):
        # every append the round attempts fails — the cert batch AND the
        # settle guard's own row write (the review's real gap)
        raise dc.CertifyError("round_append_rejected:['x']")

    with pytest.raises(dc.CertifyError) as ei:
        dc.run_line_round(LINE, "change", guard_path(tmp_path),
                          lambda c: env_header(), reader(p),
                          writer_always_fails, "round-engine", "booked-v1",
                          project=REPO, roster={"entries": []})
    # the ORIGINAL exception surfaced, never the row-write failure
    assert "round_append_rejected" in str(ei.value)
    # the row-write failure is loud on the second face (stderr)
    assert "LINE_ROUND_SETTLE_ROW_FAILED" in capsys.readouterr().err


# ---- C: abort during the settle window writes nothing (one writer) ---------

def test_c_abort_in_settle_window_writes_nothing(tmp_path, monkeypatch,
                                                 capsys):
    setup(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    dc.append_rows([landing(REPO, "rev1")], p)
    gp = guard_path(tmp_path)
    assert dc.guard_acquire(gp, "test") is not None
    dc._INFLIGHT_TICKS["proj-x"] = {"guard_path": str(gp),
                                    "ledger": str(p), "at": 0.0}
    try:
        # settle window: the runner already returned, so the runner
        # registry is EMPTY — the abort face has no line to name and
        # writes nothing; the settle path stays the one writer.
        dc._INFLIGHT_RUNNERS.clear()
        out = dc.abort_inflight_ticks("activity_aborted",
                                      append_rows_fn=lambda b: dc.append_rows(
                                          b, p))
        assert out == []
        assert not [r for r in rows_of(p)
                    if r["kind"] == dc.KIND_RANGE_GROWTH]
        # for contrast: a round still INSIDE its runner gets exactly one
        # row per in-flight line — never two, never zero.
        dc._INFLIGHT_RUNNERS[424242] = {"proc": None, "line": LINE,
                                        "at": 0.0}
        out = dc.abort_inflight_ticks("activity_aborted",
                                      append_rows_fn=lambda b: dc.append_rows(
                                          b, p))
        assert out == [LINE]
        grown = [r for r in rows_of(p) if r["kind"] == dc.KIND_RANGE_GROWTH]
        assert len(grown) == 1
        assert grown[0]["reason"] == "activity_aborted:activity_aborted"
    finally:
        dc._INFLIGHT_TICKS.pop("proj-x", None)
        dc._INFLIGHT_RUNNERS.pop(424242, None)
        dc.guard_release(gp)


# ---- D: baseline missing — regressions come from the CONTENT set only ------

def test_d_baseline_missing_uses_content_set_not_unverified(tmp_path):
    """A repo whose main tip cannot be resolved is fail-closed red for real
    content, but a name that is ALSO unverified (env-only) never books a
    regression — content wins, and the env-only face stays green."""
    project = "proj"          # no worktree on purpose: baseline unresolvable
    candidate = [{"repo": project, "revision": "r1"}]
    header = {"id": dc.mint_id("run"),
              "cases": {"ran": 5, "failed": 0, "env_failed": 1},
              "failed_names": ["env-x"], "unverified_names": ["env-x"]}
    v, detail = dc.relative_round_verdict(project, candidate, header,
                                          lambda c: {"id": "run-x",
                                                     "cases": {}},
                                          {"entries": []})
    assert v == "green"
    assert detail["per_repo"][project]["new_regressions"] == []


def test_d2_baseline_missing_real_content_stays_red(tmp_path):
    project = "proj"
    candidate = [{"repo": project, "revision": "r1"}]
    header = {"id": dc.mint_id("run"),
              "cases": {"ran": 5, "failed": 1, "env_failed": 0},
              "failed_names": ["real-regression"], "unverified_names": []}
    v, detail = dc.relative_round_verdict(project, candidate, header,
                                          lambda c: {"id": "run-x",
                                                     "cases": {}},
                                          {"entries": []})
    assert v == "red"
    assert detail["new_regressions"] == ["real-regression"]
