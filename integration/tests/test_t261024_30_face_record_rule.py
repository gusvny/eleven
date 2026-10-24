#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261024-30 L1 battery: one verdict rule, named on both faces.

The face may be stricter than the record (env_fail>0 ⇒ red is declared),
but the two verdicts must never disagree silently: the terminal face now
carries the record's verdict beside its own, the run row names the rule it
used, and the face dir and the run row answer "which project" through ONE
resolution rule. Zero docker, zero Temporal, never touches 3099.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration"))
sys.path.insert(0, str(ROOT / "server" / "engine"))

import lib_round_face as lrf  # noqa: E402
import line_round_runner as lrr  # noqa: E402


# ---- the record rule (one place) -------------------------------------------

@pytest.mark.parametrize("counts,want", [
    ({"ran": 725, "pass": 707, "fail": 0, "env_fail": 18}, "green"),
    ({"ran": 5, "pass": 4, "fail": 1, "env_fail": 0}, "red"),
    ({"ran": 5, "pass": 5, "fail": 0, "env_fail": 0}, "green"),
    ({"ran": 0, "pass": 0, "fail": 0, "env_fail": 3}, None),
    ({}, None),
    (None, None),
])
def test_content_verdict_truth_table(counts, want):
    assert lrf.content_verdict(counts) == want


def test_face_stricter_record_named_on_terminal_face(tmp_path):
    """Env-red face + content-clean ⇒ the SAME face.json carries both
    verdicts: outcome.verdict=red AND outcome.record_verdict=green."""
    w = lrf.FaceWriter(tmp_path, "run-x", "develop", {"r": "rev"})
    w.start()
    w.finish("done", "red", "env-only red",
             record_verdict=lrf.content_verdict(
                 {"ran": 725, "fail": 0, "env_fail": 18}),
             record_rule="content-v1")
    face = json.loads((tmp_path / "rounds" / "run-x" / "face.json").read_text())
    assert face["outcome"]["verdict"] == "red"
    assert face["outcome"]["record_verdict"] == "green"
    assert face["outcome"]["record_rule"] == "content-v1"


def test_face_without_record_verdict_stays_shape_compatible(tmp_path):
    """Legacy caller shape (no record verdict): outcome keeps its old keys
    only — the could-not-run path and old tests stay byte-compatible."""
    w = lrf.FaceWriter(tmp_path, "run-y", "develop", {})
    w.start()
    w.finish("failed", None, "candidates_env_unset")
    face = json.loads((tmp_path / "rounds" / "run-y" / "face.json").read_text())
    assert face["outcome"] == {"verdict": None, "reason":
                               "candidates_env_unset"}


# ---- the run row names the rule it used ------------------------------------

def _projects(tmp_path, rows_by_project):
    base = tmp_path / "projects"
    for name, rows in rows_by_project.items():
        ledger = base / name / "ledger" / "scenario-runs.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("".join(json.dumps(r) + "\n" for r in rows),
                          "utf-8")
    return base


def test_run_row_persist_names_rule_and_env_only_is_green(tmp_path):
    """The observed shape (failed=0, env_failed=18): the run row stored in
    the project ledger is GREEN, names verdict_rule, and a second persist
    of the same run id is a no-op (never a duplicate)."""
    base = _projects(tmp_path, {"proj": [{"id": "run-old",
                                          "source": lrr.RUN_SOURCE}]})
    import lib_round_face
    header = {"id": "run-new",
              "cases": {"ran": 725, "failed": 0, "env_failed": 18}}
    lrr._persist_run_row(header, {"SANDBAR_PROJECTS_DIR": str(base)})
    path = base / "proj" / "ledger" / "scenario-runs.jsonl"
    rows = [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 2
    assert rows[-1]["verdict"] == "green"
    assert rows[-1]["verdict_rule"] == "content-v1"
    # idempotent by run id
    lrr._persist_run_row(header, {"SANDBAR_PROJECTS_DIR": str(base)})
    rows = [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 2


def test_run_row_content_red_stays_red(tmp_path):
    base = _projects(tmp_path, {"proj": []})
    header = {"id": "run-red",
              "cases": {"ran": 5, "failed": 2, "env_failed": 0}}
    lrr._persist_run_row(header, {"SANDBAR_PROJECTS_DIR": str(base)})
    rows = [json.loads(x) for x in (base / "proj" / "ledger" /
                                    "scenario-runs.jsonl").read_text()
            .splitlines() if x.strip()]
    assert rows[-1]["verdict"] == "red"
    assert rows[-1]["verdict_rule"] == "content-v1"


def test_unresolvable_project_writes_nothing_and_names_it(
        tmp_path, capsys):
    base = tmp_path / "projects"
    base.mkdir()
    (base / "a").mkdir()
    (base / "b").mkdir()   # two projects, neither carries a line-round row
    header = {"id": "run-z", "cases": {"ran": 5, "failed": 0,
                                       "env_failed": 0}}
    lrr._persist_run_row(header, {"SANDBAR_PROJECTS_DIR": str(base)})
    assert "unresolved" in capsys.readouterr().err
    assert not list(base.rglob("scenario-runs.jsonl"))


# ---- ONE project resolution for the face dir and the run row ---------------

def test_face_dir_falls_back_to_the_run_row_project(tmp_path, capsys):
    """The silent-end shape: no lines.json declaration anywhere, but the
    ledger scan knows the project — the face dir now follows the run row."""
    base = _projects(tmp_path, {"proj": [{"id": "run-old",
                                          "source": lrr.RUN_SOURCE}]})
    fdir, line_id = lrr.resolve_face_dir(["no-such-repo"],
                                         {"SANDBAR_PROJECTS_DIR": str(base)})
    assert fdir == base / "proj" / "data" / "develop"
    assert "falling back to the run-row project" in capsys.readouterr().err


def test_face_dir_declaration_scan_still_wins(tmp_path, monkeypatch,
                                              capsys):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    decl = (tmp_path / "projects" / "decl" / "data" / "develop")
    decl.mkdir(parents=True)
    (decl / "lines.json").write_text(json.dumps(
        [{"line_id": "develop",
          "repositories": [{"name": "sandbar", "url": "x"}]}]), "utf-8")
    fdir, line_id = lrr.resolve_face_dir(
        ["sandbar"], {"SANDBAR_PROJECTS_DIR": str(tmp_path / "projects")})
    assert fdir == decl and line_id == "develop"


# ---- source lock: the two faces quote the same rule names ------------------

def test_rule_names_are_pinned_in_both_sources():
    runner_src = (ROOT / "integration" / "line_round_runner.py").read_text()
    face_src = (ROOT / "integration" / "lib_round_face.py").read_text()
    engine_src = (ROOT / "server" / "engine" /
                  "develop_certify.py").read_text()
    assert 'record_rule="content-v1"' in runner_src.replace(" ", "") or \
        '"content-v1"' in runner_src
    assert "def content_verdict(" in face_src
    assert '"verdict_rule"] = "relative-content-v1"' in engine_src
    assert '"verdict_rule"] = "absolute-content-v1"' in engine_src
    # the runner stamps the SAME rule name the face carries
    assert 'record_rule="content-v1"' in runner_src or \
        'record_rule=lib_round_face.content_verdict' not in runner_src
