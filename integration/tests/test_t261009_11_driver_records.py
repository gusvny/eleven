#!/usr/bin/env python3
"""t261009-11 driver-side run records — unit battery (developer L1).

Pure helpers only; no integration entry is executed (the enforcement list is
honoured — the gate runs the suites):

runner side (integration/run_scenarios.py):
- ledger_owner_is_gate / ledger_run_source: owner flag + source fallback chain
  (channel env > SANDBAR_TICKET_ID as lane:<ticket> > empty = skip);
- run_record_skip_reason: the named-skip matrix (narrowed round, gate-owned
  round, missing source, missing commit, missing env fingerprint) — never a
  guessed identity, never a silent skip;
- build_run_rows: verdict mapping + run stamping + ticket riding the lane:
  prefix;
- build_run_header: shape v, repos, mechanical verdict, integer-ms started_at;
- write_run_record end to end on an isolated ledger dir: happy path lands rows
  + one header with matching counts; gate-owned / narrowed / missing-key rounds
  write nothing and name the skip; a store refusal is loud and never raises.

gate side (server/tools/verify_lane.py):
- _ledger_supports_runs: real lane-tree library = True; a stub without the API
  = False (old-tree degradation, named);
- _run_counts_from_cases / _run_header: counts mapping and header shape with
  the verdict computed by the store's roll-up (never by hand);
- _ledger_rows_from_cases(run_id=...): rows gain `run`; omitted id = legacy
  shape (old-tree path);
- _run_header_write: happy receipt; counts-mismatch refusal folded loudly.

Whole file isolated via SANDBAR_SCENARIO_LEDGER_DIR on a tmp dir; zero docker,
zero network, zero real ~/.sandbar contact.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec_rs = importlib.util.spec_from_file_location(
    "rs_t611_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec_rs)
_spec_rs.loader.exec_module(rs)

_spec_vl = importlib.util.spec_from_file_location(
    "vl_t611_under_test", REPO / "server" / "tools" / "verify_lane.py")
vl = importlib.util.module_from_spec(_spec_vl)
_spec_vl.loader.exec_module(vl)

MOD = REPO / "integration" / "scenario_ledger.py"
_spec_sl = importlib.util.spec_from_file_location("sl_t611_under_test", MOD)
sl = importlib.util.module_from_spec(_spec_sl)
_spec_sl.loader.exec_module(sl)

FP = "ab" * 32
SHA = "cd" * 20
CASES = [
    {"name": "s1", "suite": "main", "status": "pass", "dur_s": 1.0},
    {"name": "s2", "suite": "ro", "status": "fail", "dur_s": 2.0},
    {"name": "s3", "suite": "engine", "status": "not-checked", "dur_s": None},
]


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(sl.LEDGER_DIR_ENV, str(d))
    return d


@pytest.fixture(autouse=True)
def clean_driver_env(monkeypatch):
    for k in (rs.LEDGER_OWNER_ENV, "SANDBAR_INTEG_LEDGER_SOURCE",
              "SANDBAR_TICKET_ID"):
        monkeypatch.delenv(k, raising=False)


# ---------------- runner: owner + source ----------------

def test_owner_flag_gate_only():
    assert rs.ledger_owner_is_gate(env="gate") is True
    assert rs.ledger_owner_is_gate(env="GATE ") is True
    for v in ("", None, "runner", "self", "0"):
        assert rs.ledger_owner_is_gate(env=v) is False


def test_run_source_fallback_chain(monkeypatch):
    assert rs.ledger_run_source(
        env={"SANDBAR_INTEG_LEDGER_SOURCE": "inspection"}) == "inspection"
    assert rs.ledger_run_source(env={"SANDBAR_TICKET_ID": "t-1"}) == "lane:t-1"
    assert rs.ledger_run_source(env={"SANDBAR_INTEG_LEDGER_SOURCE": "lane:t-2",
                                     "SANDBAR_TICKET_ID": "t-1"}) == "lane:t-2"
    assert rs.ledger_run_source(env={}) == ""


# ---------------- runner: skip matrix ----------------

def test_skip_matrix_narrowed_first():
    why = rs.run_record_skip_reason(True, SHA, FP, "inspection")
    assert why and "narrowed" in why


def test_skip_matrix_gate_owned(monkeypatch):
    monkeypatch.setenv(rs.LEDGER_OWNER_ENV, "gate")
    why = rs.run_record_skip_reason(False, SHA, FP, "inspection")
    assert why and rs.LEDGER_OWNER_ENV in why


def test_skip_matrix_missing_identity_pieces():
    assert "source" in rs.run_record_skip_reason(False, SHA, FP, "")
    assert "HEAD" in rs.run_record_skip_reason(False, "", FP, "inspection")
    assert "fingerprint" in rs.run_record_skip_reason(False, SHA, "",
                                                      "inspection")
    assert rs.run_record_skip_reason(False, SHA, FP, "inspection") is None


# ---------------- runner: row/header builders ----------------

def test_build_run_rows_stamps_and_maps():
    rows = rs.build_run_rows(CASES, "run-" + "A" * 26, SHA, FP, 3, "lane:t-9")
    assert [r["verdict"] for r in rows] == ["pass", "fail", "env_fail"]
    assert all(r["run"] == "run-" + "A" * 26 for r in rows)
    assert all(r["ticket"] == "t-9" and r["source"] == "lane:t-9"
               for r in rows)
    assert [r["pool"] for r in rows] == ["main", "ro", "engine"]
    assert all(r["commit"] == SHA and r["env_fp"] == FP
               and r["conc_width"] == 3 for r in rows)


def test_build_run_rows_empty_source_no_ticket():
    rows = rs.build_run_rows(CASES[:1], "run-" + "A" * 26, SHA, FP, 1,
                             "inspection")
    assert rows[0]["ticket"] == "" and rows[0]["source"] == "inspection"


def test_build_run_header_shape_and_mechanical_verdict():
    hdr = rs.build_run_header("run-" + "A" * 26, SHA, FP, 3, "main:3,ro:3",
                              "inspection", 1791506200000, 12.5,
                              {"ran": 2, "passed": 2, "failed": 0,
                               "env_failed": 0})
    clean, why = sl.validate_run_header(hdr)
    assert clean is not None, why
    assert hdr["v"] == sl.RUN_HEADER_V
    assert hdr["verdict"] == "green"
    hdr_bad = dict(hdr, cases={"ran": 1, "passed": 0, "failed": 1,
                               "env_failed": 0}, verdict="green")
    clean, why = sl.validate_run_header(hdr_bad)
    assert clean is None and why.startswith("verdict_not_rollup")


# ---------------- runner: the driver write ----------------

def test_write_run_record_happy_path(ledger_home, monkeypatch):
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    counts = {"ran": 3, "passed": 1, "failed": 1, "env_failed": 1}
    rid, face = rs.write_run_record(
        CASES, counts, 12.5, 1791506200000, SHA, FP, 3, "main:3,ro:3,engine:3",
        narrowed=False)
    assert rid and rid.startswith("run-")
    assert face["rows_written"] == 3 and face["header_written"] == 1
    rows, bad = sl.read_rows()
    assert bad == [] and all(r["run"] == rid for r in rows)
    headers, hbad = sl.read_runs()
    assert hbad == [] and len(headers) == 1
    hdr = headers[0]
    assert hdr["id"] == rid and hdr["suite"] == "full"
    assert hdr["cases"] == counts and hdr["verdict"] == "red"
    # counts derivable from the rows: a recount reproduces the header
    recount, legacy = sl.derive_counts(rows, rid)
    assert recount == counts and legacy == 0
    # the consumer face works end to end
    assert len(sl.require_run_rows(rid)) == 3


def test_write_run_record_skips_are_named_and_write_nothing(
        ledger_home, monkeypatch):
    monkeypatch.setenv(rs.LEDGER_OWNER_ENV, "gate")
    rid, face = rs.write_run_record(
        CASES, {"ran": 3, "passed": 3, "failed": 0, "env_failed": 0}, 1.0,
        1791506200000, SHA, FP, 3, "main:3", narrowed=False)
    assert rid is None and "gate-owned" in face["skipped"]
    assert sl.read_rows()[0] == [] and sl.read_runs()[0] == []


def test_write_run_record_narrowed_round_writes_nothing(
        ledger_home, monkeypatch):
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    rid, face = rs.write_run_record(
        CASES, {"ran": 3, "passed": 3, "failed": 0, "env_failed": 0}, 1.0,
        1791506200000, SHA, FP, 3, "main:3", narrowed=True)
    assert rid is None and "narrowed" in face["skipped"]
    assert sl.read_rows()[0] == [] and sl.read_runs()[0] == []


def test_write_run_record_missing_commit_skips(ledger_home, monkeypatch):
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    rid, face = rs.write_run_record(
        CASES, {"ran": 3, "passed": 3, "failed": 0, "env_failed": 0}, 1.0,
        1791506200000, "", FP, 3, "main:3", narrowed=False)
    assert rid is None and "HEAD" in face["skipped"]
    assert sl.read_rows()[0] == []


def test_write_run_record_store_failure_is_loud_not_fatal(
        ledger_home, monkeypatch):
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    def _boom():
        raise RuntimeError("ledger unloadable")
    monkeypatch.setattr(rs, "_reuse_ledger_module", _boom)
    rid, face = rs.write_run_record(
        CASES, {"ran": 3, "passed": 3, "failed": 0, "env_failed": 0}, 1.0,
        1791506200000, SHA, FP, 3, "main:3", narrowed=False)
    assert rid is None and "RuntimeError" in face.get("error", "")
    assert sl.read_runs()[0] == []


def test_write_run_record_rows_rejected_means_no_header(
        ledger_home, monkeypatch):
    monkeypatch.setenv("SANDBAR_TICKET_ID", "t-1")
    # a case whose row shape the store refuses (empty scenario name) → rows
    # incomplete → the header is NOT written (interrupted run is visible as a
    # state, never invented)
    cases = [dict(CASES[0]), {"name": "", "suite": "main", "status": "pass",
                              "dur_s": 1.0}]
    rid, face = rs.write_run_record(
        cases, {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0}, 1.0,
        1791506200000, SHA, FP, 3, "main:3", narrowed=False)
    assert rid
    assert face["rows_written"] == 1 and "rows incomplete" in face["header"]
    assert sl.read_runs()[0] == []
    face2 = sl.rows_for_run(rid)
    assert face2["state"] == "interrupted"


# ---------------- gate: helpers ----------------

def test_gate_supports_runs_probe(tmp_path):
    assert vl._ledger_supports_runs(sl) is True
    class _Stub:
        pass
    assert vl._ledger_supports_runs(_Stub) is False
    class _Half:
        mint_run_id = staticmethod(lambda: "run-x")
    assert vl._ledger_supports_runs(_Half) is False


def test_gate_counts_mapping():
    assert vl._run_counts_from_cases(CASES) == {
        "ran": 3, "passed": 1, "failed": 1, "env_failed": 1}
    assert vl._run_counts_from_cases([]) == {
        "ran": 0, "passed": 0, "failed": 0, "env_failed": 0}


def test_gate_run_header_shape(tmp_path):
    (tmp_path / "integration").mkdir()
    (tmp_path / "integration" / "scenario_ledger.py").write_bytes(
        MOD.read_bytes())
    mod, why = vl._ledger_module(tmp_path)
    assert mod is not None
    hdr = vl._run_header(mod, "run-" + "B" * 26, SHA, FP, 4, "main:4",
                         "lane:t-1", 1791506200000, 9.0, CASES)
    clean, cwhy = mod.validate_run_header(hdr)
    assert clean is not None, cwhy
    assert hdr["v"] == mod.RUN_HEADER_V
    assert hdr["repos"] == [{"repo": "sandbar", "revision": SHA}]
    assert hdr["verdict"] == "red"   # mechanical: a fail is present
    assert hdr["started_at"] == 1791506200000
    assert isinstance(hdr["started_at"], int)


def test_gate_rows_stamped_with_run_id():
    rid = "run-" + "C" * 26
    rows = vl._ledger_rows_from_cases(CASES, SHA, FP, 4, "lane:t-9", run_id=rid)
    assert all(r["run"] == rid for r in rows)
    rows_legacy = vl._ledger_rows_from_cases(CASES, SHA, FP, 4, "lane:t-9")
    assert all("run" not in r for r in rows_legacy)


def test_gate_header_write_happy_and_refusal(ledger_home, tmp_path):
    (tmp_path / "integration").mkdir()
    (tmp_path / "integration" / "scenario_ledger.py").write_bytes(
        MOD.read_bytes())
    mod, _why = vl._ledger_module(tmp_path)
    rid = mod.mint_run_id()
    rows = vl._ledger_rows_from_cases(CASES, SHA, FP, 4, "lane:t-9", run_id=rid)
    assert mod.append_records(rows)["written"] == 3
    hdr = vl._run_header(mod, rid, SHA, FP, 4, "main:4", "lane:t-9",
                         1791506200000, 9.0, CASES)
    face = vl._run_header_write(mod, hdr)
    assert face == {"written": 1, "id": rid}
    # tampered counts: the store refuses before the header lands (a fresh id —
    # the same id would hit the duplicate refusal first, which is the cheap
    # insurance, not the count check under test here)
    hdr_lie = dict(hdr, id=mod.mint_run_id(),
                   cases={"ran": 9, "passed": 9, "failed": 0,
                          "env_failed": 0}, verdict="green")
    face2 = vl._run_header_write(mod, hdr_lie)
    assert face2["written"] == 0
    assert face2["rejected"][0]["reason"].startswith("counts_mismatch")


def test_gate_header_write_store_crash_folds_loudly(ledger_home, monkeypatch):
    class _Boom:
        def append_run_header(self, hdr):
            raise OSError("disk gone")
    face = vl._run_header_write(_Boom(), {"id": "run-x"})
    assert face["written"] == 0 and "OSError" in face["error"]
