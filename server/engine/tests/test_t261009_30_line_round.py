#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-30 — the line round (T2.3): the full suite runs once per tick on
the line's head, event-driven with a scheduled backstop, and records its
certification (develop-buffer-v1 goals 6/7; host order 261009 chaining).

White-box over server/engine/develop_certify.py's new round face
(``run_line_round`` + ``guard_held`` / ``candidate_set`` /
``refuse_delivered_checkout``), on injected seams (fake runner, real tmp
delivery ledger through the module's own read/append faces). Zero docker,
zero Temporal, never touches 3099. The suite itself is never executed here:
the runner is a stub, per the ticket's own constraint that the integration
gate runs the real suite.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop"


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


def green_header(ran=10):
    return {"id": dc.mint_id("run"), "cases": {"ran": ran, "failed": 0,
                                               "env_failed": 0}}


def red_header(failed=3):
    return {"id": dc.mint_id("run"), "cases": {"ran": 10, "failed": failed,
                                               "env_failed": 0}}


def guard_path(tmp_path):
    return tmp_path / "ledger" / "guard-anchor.json"


def seed(path, *rows):
    if rows:
        dc.append_rows(list(rows), path)


def green_run_reader(_run_id):
    return True


# ---- R1: a green round certifies the head; the faces follow -----------------

def test_r1_green_round_grows_prefix_and_answers_landable(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    seen = []
    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            lambda c: (seen.append(c), green_header())[1],
                            reader(p), writer(p), "round-engine", "booked-v1")
    assert out["end"]["state"] == dc.END_IDLE  # nothing left waiting
    assert len(out["rounds"]) == 1
    r = out["rounds"][0]
    assert r["state"] == dc.STATE_CERTIFIED and r["verdict"] == "green"
    # the runner was pointed at the line's head, once
    assert seen == [[{"repo": "sandbar", "revision": "rev1"}]]
    rows, bad = dc.read_rows(p)
    assert not bad
    rng = dc.derive_range(rows, LINE)
    assert rng["covered_landings"] == []  # the range is closed
    assert rng["certified_prefix"] == [{"repo": "sandbar", "revision": "rev1"}]
    # goal 7 mechanically: the waiting ticket's landing is covered
    ldg = [x for x in rows if x["kind"] == "landing"][0]
    face = dc.ticket_wait_state(rows, LINE, ldg, green_run_reader, 999)
    assert face["state"] == dc.WAIT_CERTIFIED and face["covered_by"] == r["cert"]
    assert dc.landable(rows, LINE, ldg, is_green=green_run_reader) is True


def test_r1b_candidate_set_takes_head_per_repo_in_seq_order():
    ls = [landing("a", "old"), landing("b", "b1"), landing("a", "new")]
    assert dc.candidate_set(ls) == [{"repo": "a", "revision": "new"},
                                    {"repo": "b", "revision": "b1"}]


# ---- R2: a red implicating content opens the freeze; exemption structural --

def test_r2_red_opens_freeze_and_derives_culprit(tmp_path):
    p = ledger(tmp_path)
    ldg = landing("sandbar", "bad")
    seed(p, ldg)
    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            lambda c: red_header(), reader(p), writer(p),
                            "round-engine", "booked-v1")
    r = out["rounds"][0]
    assert r["state"] == dc.STATE_RED and r["verdict"] == "red"
    rows, _ = dc.read_rows(p)
    st = dc.freeze_state(rows, LINE)
    assert st["frozen"] is True and st["cause"] == r["cert"]
    # the ladder's first step is the flake discriminator: rerun the SAME
    # candidate once before any search (goal 9) — the freeze is open, the
    # culprit is NOT yet named, the exemption is already structural.
    assert r["next"] == "rerun"
    assert st["culprit"] is None
    # t261009-63: the exemption is derived from a `repairs` relation, never
    # from the kind alone — a frozen line refuses the kind-only fix BY NAME,
    # and every other declared kind still answers False.
    with pytest.raises(dc.CertifyError, match="freeze_repair_relation_missing"):
        dc.may_land(rows, LINE, "fix")
    assert dc.may_land(rows, LINE, "chore") is False


def test_r2b_after_rerun_the_ladder_isolates(tmp_path):
    p = ledger(tmp_path)
    ldg = landing("sandbar", "bad")
    seed(p, ldg)
    out1 = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                             lambda c: red_header(), reader(p), writer(p),
                             "round-engine", "booked-v1")
    assert out1["rounds"][0]["next"] == "rerun"
    rows, _ = dc.read_rows(p)
    reds = [x for x in rows if x["kind"] == "certification"]
    # the rerun round records a later certification over the SAME candidate;
    # the wiring caller raises it (the range is closed by the red cert), the
    # ladder face judged here directly: a single-landing range isolates.
    dc.append_rows([{"kind": "certification", "id": dc.mint_id("cert"),
                     "line": LINE, "repos": [{"repo": "sandbar",
                                              "revision": "bad"}],
                     "run": dc.mint_id("run"), "booked_red": "booked-v1",
                     "judged_by": "round-engine", "at": 3}], p)
    rows, _ = dc.read_rows(p)
    action, target = dc.next_red_action(rows, LINE, reds[0], None)
    assert action == "isolated" and target["id"] == ldg["id"]
    assert dc.freeze_state(rows, LINE)["frozen"] is True


# ---- R3: could-not-run grows the range, never a freeze (goal 24) ------------

@pytest.mark.parametrize("bad_header", [None, "not a dict",
                                        {"id": "not-run", "cases": {}},
                                        {"id": dc.mint_id("run"),
                                         "cases": {"ran": 0}}])
def test_r3_could_not_run_grows_range(tmp_path, bad_header):
    p = ledger(tmp_path)
    ldg = landing("sandbar", "r1")
    seed(p, ldg)
    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            lambda c: bad_header, reader(p), writer(p),
                            "round-engine", "booked-v1")
    r = out["rounds"][0]
    assert r["state"] == dc.STATE_GREW
    rows, _ = dc.read_rows(p)
    kinds = {x["kind"] for x in rows}
    assert "certification" not in kinds and "freeze" not in kinds
    assert "range_growth" in kinds
    # the landing is still waiting — it was never judged red
    face = dc.ticket_wait_state(rows, LINE, ldg, green_run_reader, 999)
    assert face["state"] == dc.WAIT_WAITING


# ---- R4: a round asked for while one runs joins the next one ---------------

def test_r4_guard_held_joins_without_running(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    gp = guard_path(tmp_path)
    held = dc.guard_acquire(gp, "another-tick")
    assert held is not None
    calls = []

    def runner(c):
        calls.append(c)
        return green_header()

    out = dc.run_line_round(LINE, "change", gp, runner, reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["end"] == {"state": dc.END_JOINED, "reason": "guard_held"}
    assert calls == [] and out["rounds"] == []
    rows, _ = dc.read_rows(p)
    assert not [x for x in rows if x["kind"] == "certification"]
    dc.guard_release(gp)
    out2 = dc.run_line_round(LINE, "change", gp, runner, reader(p),
                             writer(p), "round-engine", "booked-v1")
    assert len(out2["rounds"]) == 1 and calls


def test_r4b_corrupt_guard_is_loud_never_free(tmp_path):
    gp = guard_path(tmp_path)
    gp.parent.mkdir(parents=True, exist_ok=True)
    real = gp.parent / dc.GUARD_NAME  # the guard file the faces actually read
    real.write_text("{ not json", encoding="utf-8")
    with pytest.raises(dc.CertifyError, match="guard_unreadable"):
        dc.guard_held(gp)
    real.write_text('"just a string"', encoding="utf-8")
    with pytest.raises(dc.CertifyError, match="guard_not_object"):
        dc.guard_held(gp)


# ---- R5: rounds chain while anything waits; the bound is declared ----------

def test_r5_chain_retries_an_open_range_within_one_tick(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    n = {"i": 0}

    def runner(c):  # first attempt produces no proof; the retry does
        n["i"] += 1
        return green_header() if n["i"] > 1 else None

    out = dc.run_line_round(LINE, "change", guard_path(tmp_path), runner,
                            reader(p), writer(p), "round-engine", "booked-v1")
    # the chain: grew -> certified, one invocation, range then closed
    assert [r["state"] for r in out["rounds"]] == [dc.STATE_GREW,
                                                   dc.STATE_CERTIFIED]
    assert out["end"]["state"] == dc.END_IDLE
    rows, _ = dc.read_rows(p)
    kinds = [x["kind"] for x in rows]
    assert kinds.count("range_growth") == 1
    assert rows[-1]["repos"] == [{"repo": "sandbar", "revision": "rev1"}]


def test_r5b_next_tick_certifies_the_new_landing(tmp_path):
    p = ledger(tmp_path)
    gp = guard_path(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    run = lambda: dc.run_line_round(  # noqa: E731
        LINE, "change", gp, lambda c: green_header(), reader(p), writer(p),
        "round-engine", "booked-v1")
    assert run()["rounds"][0]["verdict"] == "green"
    # a later landing (the next trigger): the round joins the content in
    dc.append_rows([landing("sandbar", "rev2", ticket="t2", at=2)], p)
    out = run()
    assert len(out["rounds"]) == 1
    assert out["rounds"][0]["candidate"] == [{"repo": "sandbar",
                                              "revision": "rev2"}]
    assert out["end"]["state"] == dc.END_IDLE  # nothing left waiting


def test_r5c_chain_limit_exceeded_named_rows_untouched(tmp_path, monkeypatch):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    always_open = {"previous_certification": None,
                   "covered_landings": [landing("sandbar", "rev1")],
                   "certified_prefix": None}
    monkeypatch.setattr(dc, "derive_range", lambda rows, line: always_open)
    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            lambda c: green_header(), reader(p), writer(p),
                            "round-engine", "booked-v1", chain_limit=2)
    assert out["end"] == {"state": dc.END_CHAIN_LIMIT,
                          "reason": "chain_limit:2"}
    assert len(out["rounds"]) == 2
    assert dc.CHAIN_LIMIT == 4  # the declared default
    rows, _ = dc.read_rows(p)
    assert len([x for x in rows if x["kind"] == "certification"]) == 2
    with pytest.raises(dc.CertifyError, match="chain_limit_invalid"):
        dc.run_line_round(LINE, "change", guard_path(tmp_path),
                          lambda c: green_header(), reader(p), writer(p),
                          "round-engine", "booked-v1", chain_limit=0)


# ---- R6: the trigger wiring — change vs backstop ---------------------------

def test_r6_change_vs_backstop(tmp_path):
    p = ledger(tmp_path)
    gp = guard_path(tmp_path)
    noop = lambda c: green_header()  # noqa: E731
    # a quiet empty line: change refuses (nothing moved), backstop on an
    # empty range has nothing to run either — both idle, nothing runs.
    out = dc.run_line_round(LINE, "change", gp, noop, reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["end"] == {"state": dc.END_IDLE, "reason": "range_empty"}
    out = dc.run_line_round(LINE, "backstop", gp, noop, reader(p), writer(p),
                            "round-engine", "booked-v1", now_ms=10**12)
    assert out["end"]["state"] == dc.END_IDLE
    # a landing moves the line: change certifies
    seed(p, landing("sandbar", "rev1"))
    out = dc.run_line_round(LINE, "change", gp, noop, reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["rounds"] and out["rounds"][0]["verdict"] == "green"
    with pytest.raises(dc.CertifyError, match="trigger_unknown"):
        dc.run_line_round(LINE, "yolo", gp, noop, reader(p), writer(p),
                          "round-engine", "booked-v1")


# ---- R7: malformed inputs fail loud, zero rows, guard released -------------

def test_r7_malformed_ledger_line_refuses(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    with open(str(p), "a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
    calls = []
    with pytest.raises(dc.CertifyError, match="ledger_has_malformed_lines"):
        dc.run_line_round(LINE, "change", guard_path(tmp_path),
                          lambda c: calls.append(c) or green_header(),
                          reader(p), writer(p), "round-engine", "booked-v1")
    assert calls == []
    assert dc.guard_held(guard_path(tmp_path)) is False  # released on the path


def test_r7b_runner_error_still_releases_guard(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    gp = guard_path(tmp_path)

    def boom(c):
        raise RuntimeError("runner died")

    with pytest.raises(RuntimeError):
        dc.run_line_round(LINE, "change", gp, boom, reader(p), writer(p),
                          "round-engine", "booked-v1")
    assert dc.guard_held(gp) is False
    rows, _ = dc.read_rows(p)
    assert not [x for x in rows if x["kind"] in ("certification", "freeze",
                                                 "range_growth")]


# ---- R8: the delivered checkout is refused by name -------------------------

def test_r8_delivered_checkout_refusal(tmp_path):
    main = tmp_path / "main-checkout"
    main.mkdir()
    with pytest.raises(dc.CertifyError, match="tree_is_delivered_checkout"):
        dc.refuse_delivered_checkout(main, main)
    # a symlink alias does not slip through
    alias = tmp_path / "alias"
    os.symlink(main, alias)
    with pytest.raises(dc.CertifyError, match="tree_is_delivered_checkout"):
        dc.refuse_delivered_checkout(alias, main)
    # a tree of its own passes
    own = tmp_path / "round-tree"
    own.mkdir()
    dc.refuse_delivered_checkout(own, main)


def test_r8b_round_records_cite_not_restate(tmp_path):
    p = ledger(tmp_path)
    seed(p, landing("sandbar", "rev1"))
    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            lambda c: green_header(ran=7), reader(p),
                            writer(p), "round-engine", "booked-v1")
    rows, _ = dc.read_rows(p)
    cert = [x for x in rows if x["kind"] == "certification"][0]
    assert cert["run"] == out["rounds"][0]["run"]
    for stolen in ("cases", "verdict", "counts"):
        assert stolen not in cert  # the certification cites the run
    assert cert["booked_red"] == "booked-v1" and cert["judged_by"] == "round-engine"
