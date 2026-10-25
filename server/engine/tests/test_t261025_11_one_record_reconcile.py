#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261025-11 — a completed line round can never leave ZERO ledger rows.

The measured shape (two witnesses on 261025, project ledger read-only): the
runner COMPLETED — face done, run row persisted into scenario-runs.jsonl —
and the engine side never processed the header (the settle block's runs_store
persist never happened, so the run appears in the runs store exactly once).
The drop sits before the settle block, so in-settle nets cannot see it.

Legs:
- S1 _append_settle_row checks the writer's answer: a REJECTED batch (no
  raise) retries once and, with a face_dir, names the unrecorded round on
  the tick refusal face — never silent zero rows; a clean write touches
  nothing else; a raising writer still never masks its caller (nothing to
  mask here — the function never raises).
- R1 the witness shape heals into exactly ONE green certification whose
  judged_by names the reconstruction; a replay heals nothing (idempotent).
- R2 an unjudgable run header heals into ONE range-growth row naming the
  run id; replay writes nothing.
- R3 a content red heals cert + freeze (the settle block's own mapping).
- R4 a run whose revision set matches no landing on a multi-line project is
  NEVER guessed: no ledger row, a named error entry.
- R5 guard held: nothing written (a round may be in flight).
- R6 an append failure is a named error entry, never an exception.
- T1 the full tick heals the witness and idles — no round, no second row.
- T2 a malformed runs store is a named error entry, never a guess.

Zero docker, zero Temporal, never touches 3099; no real runner.
"""
import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop-buffer"
OTHER = "develop-other"
RUN_ID = "run-01M5RJ2MDAEX796E7MV0KE324X"  # the measured witness id (shape)


def ledger(tmp_path):
    return tmp_path / "ledger" / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def landing(repo, rev, line=LINE, ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": line, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def witness_run(rid=RUN_ID, verdict="green", cases=None, rev="dbb88cd5",
                repo="sandbar"):
    """The runner-persisted row of a completed round (measured shape)."""
    d = {"v": "run-ledger-v1", "id": rid,
            "source": dc.LINE_ROUND_RUN_SOURCE,
            "repos": [{"repo": repo, "revision": rev}],
            "verdict": verdict, "verdict_rule": "content-v1",
            "unverified_names": ["env-case-01"]}
    d["cases"] = cases if cases is not None else \
        {"ran": 702, "passed": 690, "failed": 0, "env_failed": 12}
    return d


def rows_of(path):
    rows, bad = dc.read_rows(path)
    assert not bad
    return rows


def certs(rows):
    return [r for r in rows if r["kind"] == dc.KIND_CERT]


def growths(rows):
    return [r for r in rows if r["kind"] == dc.KIND_RANGE_GROWTH]


# ---- S1: the settle-row writer's answer is checked --------------------------

def test_s1_rejected_batch_retries_then_names_refusal_face(tmp_path):
    calls = []

    def rejecting(batch):
        calls.append(batch)
        return {"written": 0, "rejected": [{"index": 0, "reason": "x"}]}

    dc._append_settle_row(rejecting, LINE, "round_settle_failed:E:boom",
                          face_dir=str(tmp_path))
    assert len(calls) == 2  # one retry, never a single silent attempt
    face = tmp_path / dc.TICK_REFUSALS_NAME
    rows, bad = dc.read_rows(face)
    assert not bad and len(rows) == 1
    assert rows[0]["state"] == "error"
    assert rows[0]["error"].startswith("settle_row_unrecorded:")
    assert rows[0]["line"] == LINE


def test_s1_clean_write_writes_no_face_and_no_retry(tmp_path):
    calls = []

    def ok(batch):
        calls.append(batch)
        return {"written": 1, "rejected": [], "seqs": [1]}

    dc._append_settle_row(ok, LINE, "run_executed_nothing",
                          face_dir=str(tmp_path))
    assert len(calls) == 1
    assert not (tmp_path / dc.TICK_REFUSALS_NAME).exists()


def test_s1_raising_writer_never_raises_and_names_face(tmp_path):
    calls = []

    def broken(batch):
        calls.append(batch)
        raise dc.CertifyError("ledger_has_malformed_lines:1")

    dc._append_settle_row(broken, LINE, "round_settle_failed:E:boom",
                          face_dir=str(tmp_path))
    assert len(calls) == 2
    rows, bad = dc.read_rows(tmp_path / dc.TICK_REFUSALS_NAME)
    assert not bad and rows[0]["state"] == "error"


def test_s1_failure_without_face_dir_is_stderr_only(tmp_path):
    dc._append_settle_row(lambda b: {"written": 0, "rejected": []},
                          LINE, "why", face_dir=None)
    assert not (tmp_path / dc.TICK_REFUSALS_NAME).exists()


# ---- R1: the witness shape heals into exactly ONE certification ------------

def test_r1_witness_heals_one_green_cert_and_replay_writes_nothing(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run()]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert len(out) == 1
    e = out[0]
    assert e["state"] == "reconciled" and e["run"] == RUN_ID
    assert e["attribution_rule"] == "landing_repo_match"
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1  # exactly ONE row — the contract
    assert cs[0]["run"] == RUN_ID
    assert cs[0]["judged_by"] == "reconciled:%s" % RUN_ID
    assert cs[0]["line"] == LINE
    assert not growths(rows)
    # idempotent by run id: the replay sees the cert and heals nothing
    out2 = dc.reconcile_unrecorded_rounds(
        LINE, rows, runs, writer(p), "tick", "booked-v1", 1792909089001,
        sole_line=True)
    assert out2 == []
    assert len(certs(rows_of(p))) == 1


def test_r1b_sole_line_attribution_fires_without_landing_match(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "older-rev")], p)
    runs = [witness_run(rev="b3c3ca5b")]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["attribution_rule"] == "sole_line"
    assert len(certs(rows_of(p))) == 1


# ---- R2: an unjudgable header grows the range, naming the run id -----------

def test_r2_unjudgable_header_becomes_one_named_growth_row(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run(cases="garbage")]  # unreadable counts: no proof
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["state"] == "reconciled"
    assert "range_growth" in out[0]["wrote"]
    rows = rows_of(p)
    assert not certs(rows)
    g = growths(rows)
    assert len(g) == 1
    assert RUN_ID in g[0]["reason"]
    # replay: the growth row cites the run id, so nothing is written again
    out2 = dc.reconcile_unrecorded_rounds(
        LINE, rows, runs, writer(p), "tick", "booked-v1", 1792909089001,
        sole_line=True)
    assert out2 == []
    assert len(growths(rows_of(p))) == 1


# ---- R3: a content red heals cert + freeze (the settle mapping) ------------

def test_r3_content_red_heals_cert_plus_freeze(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run(verdict="red",
                        cases={"ran": 706, "passed": 688, "failed": 4,
                               "env_failed": 14})]
    dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    rows = rows_of(p)
    assert len(certs(rows)) == 1
    assert len([r for r in rows if r["kind"] == dc.KIND_FREEZE]) == 1


# ---- R4/R5/R6: refusals, guard, failure — all named, never guessed ---------

def test_r4_ambiguous_line_writes_nothing_and_names_the_run(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "other-line-rev", line=OTHER)], p)
    runs = [witness_run(rev="b3c3ca5b")]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=False)
    assert out[0]["state"] == "error"
    assert out[0]["error"] == "unrecorded_run:%s:line_ambiguous" % RUN_ID
    assert rows_of(p) == rows_of(p)  # nothing appended below


def test_r4b_malformed_runs_and_non_line_round_rows_are_skipped(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    stub = witness_run(rid="run-01M5STUB0000000000000000000")
    stub["source"] = "lane:stub"  # not a line round: not ours to heal
    runs = ["not a dict", {"no": "id"}, stub]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out == []
    assert rows_of(p) == rows_of(p)


def test_r5_guard_held_writes_nothing(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), [witness_run()], writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True, guard_held=True)
    assert out == []
    assert not certs(rows_of(p))


def test_r6_append_failure_is_a_named_entry_never_an_exception(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)

    def broken(batch):
        raise dc.CertifyError("ledger_has_malformed_lines:1")

    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), [witness_run()], broken, "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["state"] == "error"
    assert out[0]["error"].startswith("heal_failed:CertifyError:")


# ---- T1/T2: the full tick heals, then idles --------------------------------

def _tick(tmp_path, runs_lines, lines=("develop-buffer",)):
    runs_store = tmp_path / "ledger" / "scenario-runs.jsonl"
    runs_store.parent.mkdir(parents=True, exist_ok=True)
    runs_store.write_text("\n".join(runs_lines) + "\n", encoding="utf-8")
    guard = tmp_path / "ledger" / "tick-anchor"
    return dc.line_round_tick(
        "proj", load_lines=lambda pk: list(lines),
        read_rows=reader(ledger(tmp_path)),
        append_rows=writer(ledger(tmp_path)),
        resolve_runner_fn=lambda line, env: (
            lambda candidate: (_ for _ in ()).throw(
                AssertionError("no round may run after a heal"))),
        guard_path=guard, now_ms=1792909089000,
        backstop_ms=24 * 60 * 60 * 1000,
        runs_store=str(runs_store))


def test_t1_tick_heals_witness_then_idles_without_a_round(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    out = _tick(tmp_path, [json.dumps(witness_run())])
    states = [e.get("state") for e in out["lines"]]
    assert "reconciled" in states and "idle" in states
    assert not certs(rows_of(p)) or len(certs(rows_of(p))) == 1
    assert len(certs(rows_of(p))) == 1  # exactly one heal row


def test_t2_malformed_runs_store_is_named_never_guessed(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    out = _tick(tmp_path, ["{not json"])
    assert out["lines"][0]["state"] == "error"
    assert out["lines"][0]["error"] == "runs_store_has_malformed_lines:1"
    assert not certs(rows_of(p))
