#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261024-70 — the line round inherits the ambient environment, and a
refused round is NAMED on disk.

Unit truth table (tmp fixtures, zero Temporal, zero network, zero
integration entry — UT discipline):

  face         | input                                   | expected
  -------------+-----------------------------------------+------------------
  env inherit  | tick, env=None, ambient runner var set  | seam env carries
               | (monkeypatched os.environ)              | the ambient value
  overlay wins | ambient value + roster overlay injected | overlay shadows
               |                                         | the ambient value
  forced path  | line_round_run_now, ambient var set     | seam env carries
               |                                         | the ambient value
  refusal face | resolving seam answers None             | one runner_missing
               |                                         | row on the face file
  face silent  | the round runs clean                    | no refusal row,
               |                                         | no ledger refusal row
  malformed    | entry with a non-serializable note      | tick survives, no
               |                                         | crash, face intact
  early-return | entries keyed by bare error, no state   | no face row written

The roster keeps coming from the CANDIDATE tree (t261024-50 test stays the
green witness); this file only pins the env base and the refusal face.
"""
import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

PROJECT = "proj"
LINE = "buffer"
RUNNER_VAR = dc.RUNNER_CMD_ENV


def ledger(tmp_path):
    return tmp_path / "ledger" / "delivery.jsonl"


def landing(at=1, line=LINE):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": "t1",
            "line": line, "repos": [{"repo": "r", "revision": "a%d" % at}],
            "actor": "test", "at": at}


def capturing(captured):
    def _resolve(line, env):
        captured.append((line, env))
        return None  # runner_missing ends the entry before any round runs
    return _resolve


def test_tick_env_inherits_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv(RUNNER_VAR, "/ambient/runner/python")
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    captured = []
    out = dc.line_round_tick(
        PROJECT, load_lines=lambda k: {LINE: object()},
        read_rows=lambda: dc.read_rows(p),
        append_rows=lambda b: dc.append_rows(b, p),
        resolve_runner_fn=capturing(captured),
        guard_path=str(tmp_path / "ledger" / "tick-anchor"),
        now_ms=10_000, backstop_ms=1, env=None)
    assert out["lines"][0]["state"] == "runner_missing"
    line, env = captured[0]
    assert line == LINE
    assert env[RUNNER_VAR] == "/ambient/runner/python"  # the 02:00 defect


def test_tick_env_overlay_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(RUNNER_VAR, "/ambient/runner/python")
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    captured = []
    dc.line_round_tick(
        PROJECT, load_lines=lambda k: {LINE: object()},
        read_rows=lambda: dc.read_rows(p),
        append_rows=lambda b: dc.append_rows(b, p),
        resolve_runner_fn=capturing(captured),
        guard_path=str(tmp_path / "ledger" / "tick-anchor"),
        now_ms=10_000, backstop_ms=1,
        env={dc.RUNNER_TIMEOUT_ENV: "42"})
    _, env = captured[0]
    assert env[dc.RUNNER_TIMEOUT_ENV] == "42"     # injected key present
    assert env[RUNNER_VAR] == "/ambient/runner/python"  # ambient survives


def test_run_now_env_inherits_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv(RUNNER_VAR, "/ambient/runner/python")
    import develop_line
    monkeypatch.setattr(develop_line, "load_lines",
                        lambda k: {LINE: object()})
    # the roster read is t261024-50's face; stub it to keep this file's
    # scope on the env base alone (the candidate-tree read has its own test).
    monkeypatch.setattr(dc, "_line_roster_for_round",
                        lambda project, line: ({}, None, ""))
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    captured = []
    real_resolve = dc.resolve_runner
    dc.resolve_runner = capturing(captured)
    try:
        out = dc.line_round_run_now(PROJECT)
    finally:
        dc.resolve_runner = real_resolve
    assert out["lines"][0]["state"] == "runner_missing"
    _, env = captured[0]
    assert env[RUNNER_VAR] == "/ambient/runner/python"


def test_ambient_roster_never_shadows_candidate_overlay(tmp_path,
                                                        monkeypatch):
    # t261024-70 rework (arbitrate gen0 E1): with the full worker env as the
    # ambient base, a stray ambient SANDBAR_KNOWN_RED_ROSTER must LOSE to
    # the candidate-tree worktree overlay — the roster overlay wins.
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER",
                       "/ambient/roster/loses.json")
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    captured = []
    wt_file = tmp_path / "wt" / "known-red-baseline.json"
    monkeypatch.setattr(dc, "_line_roster_for_round",
                        lambda project, line: ({}, wt_file, ""))
    dc.line_round_tick(
        PROJECT, load_lines=lambda k: {LINE: object()},
        read_rows=lambda: dc.read_rows(p),
        append_rows=lambda b: dc.append_rows(b, p),
        resolve_runner_fn=capturing(captured),
        guard_path=str(tmp_path / "ledger" / "tick-anchor"),
        now_ms=10_000, backstop_ms=1, env=None)
    _, env = captured[0]
    assert env["SANDBAR_KNOWN_RED_ROSTER"] == str(wt_file)


# ---- the refusal face --------------------------------------------------------

def _face(tmp_path):
    return tmp_path / "ledger" / dc.TICK_REFUSALS_NAME


def _stub_activity(tmp_path, monkeypatch):
    """Point the production activity body at tmp fixtures: ledger under
    tmp, declared line from a stub, inert roster, absent runner."""
    monkeypatch.setenv(RUNNER_VAR, "/ambient/runner/python")
    import develop_line
    monkeypatch.setattr(develop_line, "load_lines",
                        lambda k: {LINE: object()})
    monkeypatch.setattr(dc, "ledger_path",
                        lambda project, ledger_dir=None: ledger(tmp_path))
    monkeypatch.setattr(dc, "_line_roster_for_round",
                        lambda project, line: ({}, None, ""))
    monkeypatch.setattr(dc, "resolve_runner", capturing([]))


def test_runner_missing_writes_named_face_row(tmp_path, monkeypatch):
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    _stub_activity(tmp_path, monkeypatch)
    out = dc.line_round_tick_activity(PROJECT)
    assert out["lines"][0]["state"] == "runner_missing"
    rows = [json.loads(l) for l in
            _face(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["line"] == LINE
    assert row["state"] == "runner_missing"
    assert row["project"] == PROJECT
    assert row["at"]  # the named refusal is timestamped
    # the refusal is a FACE row, never a delivery-ledger row
    ledger_rows, _ = dc.read_rows(p)
    assert not any(r.get("state") == "runner_missing" for r in ledger_rows)


def test_clean_round_writes_no_refusal_row(tmp_path, monkeypatch):
    monkeypatch.setenv(RUNNER_VAR, "/ambient/runner/python")
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    out = dc.line_round_tick(
        PROJECT, load_lines=lambda k: {LINE: object()},
        read_rows=lambda: dc.read_rows(p),
        append_rows=lambda b: dc.append_rows(b, p),
        resolve_runner_fn=lambda line, env: (lambda cands: {
            "id": "run-x", "cases": {"ran": 1, "failed": 0, "env_failed": 0},
            "failed_names": []}),
        guard_path=str(tmp_path / "ledger" / "tick-anchor"),
        now_ms=10_000, backstop_ms=1, env=None)
    assert any("rounds" in e for e in out["lines"])
    assert not _face(tmp_path).exists()


def test_recorder_skips_early_return_shapes(tmp_path):
    # whole-tick early returns (declaration unreadable, malformed ledger)
    # come back as entries keyed by a bare "error" with no "state" — the
    # recorder must neither crash on them nor write half-rows.
    dc.record_tick_refusals(
        tmp_path / "ledger",
        [{"error": "line_declaration_unreadable:OSError"},
         {"line": LINE, "state": "idle", "reason": "backstop_not_elapsed"}],
        PROJECT)
    assert not _face(tmp_path).exists()


def test_recorder_survives_non_serializable_note(tmp_path):
    face = tmp_path / "ledger"
    face.mkdir(parents=True)
    dc.record_tick_refusals(
        face,
        [{"line": LINE, "state": "runner_missing",
          "note": object()}],  # a malformed producer input, not a dict value
        PROJECT)
    rows = [json.loads(l) for l in
            (face / dc.TICK_REFUSALS_NAME).read_text(
                encoding="utf-8").splitlines()]
    assert rows[0]["state"] == "runner_missing"  # the named part survives


def test_recorder_makes_missing_parent_dir(tmp_path):
    # t261024-70 rework (design defect 2): a refusal on a line whose ledger
    # directory does not exist yet must not vanish — the recorder creates
    # the parent instead of swallowing the OSError.
    face = tmp_path / "ledger" / "nested"
    dc.record_tick_refusals(
        face, [{"line": LINE, "state": "runner_missing"}], PROJECT)
    rows = [json.loads(l) for l in
            (face / dc.TICK_REFUSALS_NAME).read_text(
                encoding="utf-8").splitlines()]
    assert rows[0]["state"] == "runner_missing"


def test_recorder_survives_unwritable_dir(tmp_path):
    blocker = tmp_path / "ledger"
    blocker.write_text("not a directory\n", encoding="utf-8")
    dc.record_tick_refusals(
        blocker,  # open() on a path through a file raises OSError
        [{"line": LINE, "state": "runner_missing"}], PROJECT)
    assert blocker.read_text(encoding="utf-8") == "not a directory\n"
