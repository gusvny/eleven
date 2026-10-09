#!/usr/bin/env python3
"""t261009-11 run records — unit battery for integration/scenario_ledger.py.

Covers (ticket + ledger-record-models-v1 §A):
- run id minting: `run-` + ULID shape self-implemented from stdlib primitives
  (time + secrets, Crockford base32) — 48-bit ms timestamp + 80 random bits;
  uniqueness, time order, monotonic tie within one process;
- case rows gain `run`: closed schema grows 10 -> 11; write side requires it,
  readers tolerate its absence (legacy rows stay readable, never rewritten);
- header closed-schema truth table incl. the mandatory malformed-input matrix;
- mechanical verdict roll-up (green iff ran>0 and failed==0 and env_failed==0;
  `ran: 0` is never a proof — a zero-row header is refused at the write face);
- counts are checked against the rows before a header lands (mismatch or a run
  with zero rows in the ledger = named refusal, zero bytes written);
- duplicate run id refused loudly;
- rows_for_run states: headered / interrupted (rows but no header — a state to
  see, never a summary to invent) / unknown; legacy rows counted, never folded;
- require_run_rows fails loudly (named, never a guess);
- the 90-day rollup round-trips row dicts, so `run` survives month files;
- `runs` CLI: listing, and the exit-2 named refusal when a run id is missing.

Whole file isolated via SANDBAR_SCENARIO_LEDGER_DIR on a tmp dir; zero docker,
zero network, zero real ~/.sandbar contact. This file never executes an
integration entry (developer-stage enforcement list honoured).
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "integration" / "scenario_ledger.py"

_spec = importlib.util.spec_from_file_location("sl_t611_under_test", MOD)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)

COMMIT = "ab" * 20
FP = "cd" * 32
_AT_MS = 1791506200000  # 2026-06-09-ish; any fixed ms instant works


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(sl.LEDGER_DIR_ENV, str(d))
    # reset the minter's monotonic floor: tests mint explicit instants, and
    # the floor must not bump a deliberate past timestamp to wall-clock now
    sl._LAST_MINT["ms"] = -1
    sl._LAST_MINT["tail"] = 0
    return d


_CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
_UNSET = object()


def crock_int(s):
    """Decode a Crockford-base32 body back to an int (test-side mirror of the
    minter's alphabet — int(x, 32) uses a different digit table)."""
    n = 0
    for ch in s:
        n = (n << 5) | "0123456789ABCDEFGHJKMNPQRSTVWXYZ".index(ch)
    return n


def mk_row(run=_UNSET, **over):
    row = {"ts": "2026-09-21T08:00:00+00:00", "commit": COMMIT, "env_fp": FP,
           "conc_width": 4, "pool": "main", "scenario": "s1",
           "verdict": "pass", "wall_s": 1.0, "source": "inspection",
           "ticket": ""}
    if run is not _UNSET:
        row["run"] = run  # an explicit None stays an explicit (dirty) value
    row.update(over)
    return row


def mk_header(run=None, **over):
    hdr = {"v": sl.RUN_HEADER_V, "id": run or sl.mint_run_id(),
           "repos": [{"repo": "sandbar", "revision": "9f3c2a1b"}],
           "suite": "full", "source": "inspection", "env_fp": FP,
           "conc_width": 4, "pool": "main:3", "started_at": _AT_MS,
           "duration_s": 2.5,
           "cases": {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0},
           "verdict": "green"}
    hdr.update(over)
    return hdr


def seed_rows(rid, verdicts=("pass",)):
    rows = [mk_row(rid, scenario="s%d" % i, verdict=v, source="inspection")
            for i, v in enumerate(verdicts)]
    rcpt = sl.append_records(rows)
    assert rcpt["written"] == len(rows), rcpt
    return rows


# ---------------- minting ----------------

def test_mint_shape_and_uniqueness():
    ids = {sl.mint_run_id() for _ in range(200)}
    assert len(ids) == 200
    for rid in ids:
        assert rid.startswith("run-")
        body = rid[4:]
        assert len(body) == 26
        assert set(body) <= _CROCKFORD


def test_mint_carries_time_and_orders():
    a = sl.mint_run_id(at_ms=_AT_MS)
    b = sl.mint_run_id(at_ms=_AT_MS + 1)
    # lexicographic order IS time order (the design's ULID property)
    assert a < b
    assert crock_int(a[4:14]) == _AT_MS
    assert crock_int(b[4:14]) == _AT_MS + 1


def test_mint_monotonic_same_millisecond_within_process():
    a = sl.mint_run_id(at_ms=_AT_MS)
    b = sl.mint_run_id(at_ms=_AT_MS)
    assert a != b and a < b
    # same-ms ties increment, not re-randomise into the past
    c = sl.mint_run_id(at_ms=_AT_MS)
    assert b < c


# ---------------- case rows gain `run` ----------------

def test_row_validation_requires_run():
    clean, why = sl.validate_row(mk_row(run="run-" + "A" * 26))
    assert clean is not None and why is None
    for bad in (None, "", "banana", "run-", 7):
        clean, why = sl.validate_row(mk_row(run=bad))
        assert clean is None and why.startswith("run_not_run_id"), why
    row = mk_row()  # missing key entirely
    clean, why = sl.validate_row(row)
    assert clean is None and why == "missing_fields:run"


def test_readers_tolerate_legacy_rows_without_run(ledger_home):
    """Old rows stay readable: no run id = legacy, never rewritten, never
    silently folded into any run."""
    legacy = mk_row()  # no run key at all
    # write the legacy row through the file face (the write validator would
    # refuse it today — legacy rows are read, not written)
    with open(str(sl.ledger_path()), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy) + "\n")
    rows, bad = sl.read_rows()
    assert bad == [] and len(rows) == 1 and "run" not in rows[0]
    counts, legacy_n = sl.derive_counts(rows, sl.mint_run_id())
    assert legacy_n == 1 and counts == {k: 0 for k in sl.RUN_CASE_FIELDS}


def test_derive_counts_by_run_and_verdict(ledger_home):
    rid = sl.mint_run_id()
    other = sl.mint_run_id()
    sl.append_records([
        mk_row(rid, scenario="a", verdict="pass"),
        mk_row(rid, scenario="b", verdict="fail"),
        mk_row(rid, scenario="c", verdict="env_fail"),
        mk_row(other, scenario="d", verdict="pass"),
    ])
    counts, legacy = sl.derive_counts(sl.read_rows()[0], rid)
    assert counts == {"ran": 3, "passed": 1, "failed": 1, "env_failed": 1}
    assert legacy == 0


# ---------------- mechanical verdict ----------------

@pytest.mark.parametrize("counts,want", [
    ({"ran": 5, "passed": 5, "failed": 0, "env_failed": 0}, "green"),
    ({"ran": 5, "passed": 4, "failed": 1, "env_failed": 0}, "red"),
    ({"ran": 5, "passed": 4, "failed": 0, "env_failed": 1}, "red"),
    ({"ran": 0, "passed": 0, "failed": 0, "env_failed": 0}, "red"),
])
def test_run_verdict_mechanical_rollup(counts, want):
    assert sl.run_verdict(counts) == want


# ---------------- header validation (truth table) ----------------

def test_header_validation_ok_roundtrip():
    clean, why = sl.validate_run_header(mk_header())
    assert clean is not None and why is None


@pytest.mark.parametrize("over,frag", [
    ({"id": "banana"}, "id_not_run_id"),
    ({"id": 7}, "id_not_run_id"),
    ({"repos": []}, "repos_not_nonempty_list"),
    ({"repos": "sandbar"}, "repos_not_nonempty_list"),
    ({"repos": [{"repo": "sandbar"}]}, "repos_entry_invalid"),
    ({"repos": [{"repo": "", "revision": "x"}]}, "repos_entry_invalid"),
    ({"suite": "nightly"}, "suite_invalid"),
    ({"suite": ""}, "suite_invalid"),
    ({"source": "manual"}, "source_invalid"),
    ({"source": "lane:"}, "source_invalid"),
    ({"env_fp": "zz" * 32}, "env_fp_not_sha256"),
    ({"env_fp": "cd" * 31}, "env_fp_not_sha256"),
    ({"conc_width": 0}, "conc_width_not_positive_int"),
    ({"conc_width": True}, "conc_width_not_positive_int"),
    ({"conc_width": "4"}, "conc_width_not_positive_int"),
    ({"pool": 3}, "pool_not_str"),
    ({"started_at": 0}, "started_at_not_positive_int_ms"),
    ({"started_at": -1}, "started_at_not_positive_int_ms"),
    ({"started_at": "1791506200000"}, "started_at_not_positive_int_ms"),
    ({"started_at": 1791506200000.5}, "started_at_not_positive_int_ms"),
    ({"duration_s": -0.1}, "duration_s_not_nonnegative_number"),
    ({"duration_s": "2.5"}, "duration_s_not_nonnegative_number"),
    ({"cases": {"ran": 1, "passed": 1}}, "cases_not_exact_counts"),
    ({"cases": {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0, "x": 1}},
     "cases_not_exact_counts"),
    ({"cases": {"ran": -1, "passed": 0, "failed": 0, "env_failed": 0}},
     "cases_ran_not_nonnegative_int"),
    ({"cases": {"ran": 2, "passed": 1, "failed": 0, "env_failed": 0}},
     "cases_ran_not_sum_of_outcomes"),
    ({"verdict": "pass"}, "verdict_not_rollup"),
    ({"verdict": "fail"}, "verdict_not_rollup"),
    ({"v": "run-ledger-v2"}, "v_invalid"),
    ({"v": None}, "v_invalid"),
    ({"extra": 1}, "unknown_fields"),
])
def test_header_validation_rejects_malformed(over, frag):
    hdr = mk_header(**over)
    clean, why = sl.validate_run_header(hdr)
    assert clean is None and frag in why, why


def test_header_validation_rejects_non_dict_and_missing_field():
    for bad in ("x", 7, [], None):
        clean, why = sl.validate_run_header(bad)
        assert clean is None and why == "header_not_dict"
    hdr = mk_header()
    hdr.pop("pool")
    clean, why = sl.validate_run_header(hdr)
    assert clean is None and why.startswith("missing_fields:")
    assert "pool" in why


def test_header_v_is_versioned_shape():
    assert sl.RUN_HEADER_V == "run-ledger-v1"
    assert "v" in sl.RUN_HEADER_FIELDS


# ---------------- append: counts checked against the rows ----------------

def test_append_header_writes_when_counts_match(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass", "fail"))
    hdr = mk_header(run=rid,
                    cases={"ran": 2, "passed": 1, "failed": 1, "env_failed": 0},
                    verdict="red")
    rcpt = sl.append_run_header(hdr)
    assert rcpt == {"written": 1, "rejected": []}
    headers, bad = sl.read_runs()
    assert bad == [] and len(headers) == 1 and headers[0]["id"] == rid


def test_append_header_refuses_count_mismatch(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass",))
    hdr = mk_header(run=rid,
                    cases={"ran": 9, "passed": 9, "failed": 0, "env_failed": 0},
                    verdict="green")
    rcpt = sl.append_run_header(hdr)
    assert rcpt["written"] == 0
    assert rcpt["rejected"][0]["reason"].startswith("counts_mismatch")
    assert sl.read_runs()[0] == [], "refused header wrote zero bytes"


def test_append_header_refuses_run_with_zero_rows(ledger_home):
    hdr = mk_header()  # no rows anywhere carry this id
    rcpt = sl.append_run_header(hdr)
    assert rcpt["written"] == 0
    assert rcpt["rejected"][0]["reason"].startswith("counts_mismatch")


def test_append_header_refuses_zero_ran_even_if_rows_agree(ledger_home):
    """`ran: 0` is never a proof: a header claiming an empty run is refused at
    the write face even when the recount agrees (it always would)."""
    hdr = mk_header(cases={"ran": 0, "passed": 0, "failed": 0, "env_failed": 0},
                    verdict="red")
    rcpt = sl.append_run_header(hdr)
    assert rcpt["written"] == 0
    assert rcpt["rejected"][0]["reason"] == "ran_zero_no_rows_never_a_proof"


def test_append_header_refuses_duplicate_run_id(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass",))
    hdr = mk_header(run=rid)
    assert sl.append_run_header(hdr)["written"] == 1
    rcpt = sl.append_run_header(mk_header(run=rid, duration_s=9.9))
    assert rcpt["written"] == 0
    assert rcpt["rejected"][0]["reason"].startswith("duplicate_run_id")
    assert len(sl.read_runs()[0]) == 1


def test_append_header_all_refused_creates_no_file(ledger_home):
    rcpt = sl.append_run_header(mk_header(id="banana"))
    assert rcpt["written"] == 0
    assert not (ledger_home / sl.RUNS_NAME).exists()


def test_append_header_malformed_matrix_refused(ledger_home):
    for over, frag in [({"suite": "x"}, "suite_invalid"),
                       ({"verdict": "pass"}, "verdict_not_rollup"),
                       ({"conc_width": 0}, "conc_width_not_positive_int")]:
        rcpt = sl.append_run_header(mk_header(**over))
        assert rcpt["written"] == 0 and frag in rcpt["rejected"][0]["reason"]


# ---------------- read faces: states ----------------

def test_rows_for_run_states(ledger_home):
    rid = sl.mint_run_id()
    assert sl.rows_for_run(rid)["state"] == "unknown"
    seed_rows(rid, verdicts=("pass",))
    face = sl.rows_for_run(rid)
    assert face["state"] == "interrupted" and face["header"] is None
    assert sl.append_run_header(mk_header(run=rid))["written"] == 1
    face = sl.rows_for_run(rid)
    assert face["state"] == "headered" and face["header"]["id"] == rid
    assert len(face["rows"]) == 1 and face["legacy_rows"] == 0


def test_rows_for_run_counts_legacy_separately(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass",))
    with open(str(sl.ledger_path()), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(mk_row()) + "\n")  # legacy row, no run key
    face = sl.rows_for_run(rid)
    assert face["state"] == "interrupted" and face["legacy_rows"] == 1
    assert all(r.get("run") == rid for r in face["rows"])


def test_rows_for_run_refuses_non_run_id():
    with pytest.raises(sl.RunRecordError):
        sl.rows_for_run("banana")


# ---------------- loud consumer ----------------

def test_require_run_rows_happy_path(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass", "pass"))
    assert sl.append_run_header(mk_header(
        run=rid, cases={"ran": 2, "passed": 2, "failed": 0, "env_failed": 0}
    ))["written"] == 1
    rows = sl.require_run_rows(rid)
    assert len(rows) == 2


def test_require_run_rows_fails_loudly_on_legacy_only_ledger(ledger_home):
    with open(str(sl.ledger_path()), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(mk_row()) + "\n")
    with pytest.raises(sl.RunRecordError) as ei:
        sl.require_run_rows(sl.mint_run_id())
    assert "no_rows_with_run_id" in str(ei.value)
    assert "legacy" in str(ei.value)


def test_require_run_rows_fails_loudly_on_interrupted_run(ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid, verdicts=("pass",))
    with pytest.raises(sl.RunRecordError) as ei:
        sl.require_run_rows(rid)
    assert "run_header_missing" in str(ei.value)


# ---------------- rollup keeps `run` ----------------

def test_rollup_month_file_round_trips_run_field(ledger_home):
    now = time.time()
    old = sl.ledger_path()
    import datetime as dt
    aged_ts = dt.datetime.fromtimestamp(
        now - 100 * 86400, dt.timezone.utc).isoformat()
    # pre-seed a fresh rollup mark so the opportunistic trigger inside append
    # does not consume the aged row before the explicit rollup under test
    mark = ledger_home / sl.ROLLUP_MARK
    mark.write_text("1\n", encoding="utf-8")
    os.utime(str(mark), (now - 3600, now - 3600))
    rid = sl.mint_run_id()
    sl.append_records([mk_row(rid, ts=aged_ts)], now=now)
    out = sl.rollup(now=now, path=old)
    assert out["rolled_up"] == 1
    month = time.strftime("%Y%m", time.localtime(now - 100 * 86400))
    mfile = ledger_home / ("scenario-results-%s.jsonl" % month)
    merged = [json.loads(x) for x in mfile.read_text().splitlines() if x]
    assert merged and merged[0]["run"] == rid


# ---------------- CLI ----------------

def test_cli_runs_list(tmp_path, ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid)
    sl.append_run_header(mk_header(run=rid))
    p = subprocess.run([sys.executable, str(MOD), "runs"], capture_output=True,
                       text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert [r["id"] for r in doc["runs"]] == [rid]


def test_cli_runs_by_id_loud_refusal(tmp_path, ledger_home):
    rid = sl.mint_run_id()  # no rows, no header
    p = subprocess.run([sys.executable, str(MOD), "runs", "--id", rid],
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 2
    assert "RUN_RECORD_ERROR" in p.stderr
    assert "no_rows_with_run_id" in p.stderr


def test_cli_runs_by_id_hit(tmp_path, ledger_home):
    rid = sl.mint_run_id()
    seed_rows(rid)
    sl.append_run_header(mk_header(run=rid))
    p = subprocess.run([sys.executable, str(MOD), "runs", "--id", rid],
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert doc["state"] == "headered" and doc["rows"] == 1


def test_cli_usage_names_runs():
    assert "runs" in sl._usage()
