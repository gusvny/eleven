#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261026-19 — the freeze judge reads the receipt.

Five freezes in one day on the develop-buffer line (2026-10-26), each opened
by a single red whose own receipt names no failing assertion and which
re-runs green on the same tree: ``should_freeze`` keyed on the relative
new-regression COUNT, so a round-only flake landed in that count exactly
like a real regression. The rule under test, fail-closed:

- a new regression is CONTENT GUILT only when its recorded receipt names a
  failing assertion;
- a red whose receipt names no assertion is ROUND-ONLY: named and counted on
  the round's face, never green, and it opens no freeze;
- three consecutive round-only reds of the SAME case escalate to a freeze
  naming the case (the case is sick, not the revision);
- a receipt that cannot be parsed at all is content guilt (the old
  behaviour); env_fail never freezes; a real assertion red still freezes
  immediately.

White-box over develop_certify's classification seam plus settle-block
journeys on the same injected fixtures as test_t261009_30_line_round.py
(fake runner, real tmp delivery ledger). The receipt source itself
(``fail_receipts`` in integration/line_round_runner.py) is exercised from a
fixture log — the integration entry points are never executed here.
"""

import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop"
CASE = "t261009-22-lane-map-mock-chrome"


def ledger(tmp_path):
    return tmp_path / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def guard_path(tmp_path):
    return tmp_path / "ledger" / "guard-anchor.json"


def landing(repo, rev, ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": LINE, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def red_header(receipt=None, names=(CASE,), run_id=None):
    """The measured incident shape: one content-side fail, its receipt
    carrying whatever the suite recorded (default: NOTHING — no assertion
    named anywhere, the 718578ef shape)."""
    return {"id": run_id or dc.mint_id("run"),
            "verdict": "red",
            "cases": {"ran": 10, "failed": len(names), "env_failed": 0},
            "failed_names": list(names),
            "fail_receipts": receipt if receipt is not None
            else {CASE: {}}}


def rel_env(tmp_path, monkeypatch):
    """Isolated project store + the line worktree's main tip; the tip is
    what the fake runner keys the baseline answer on."""
    projects = tmp_path / "projects"
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    repo = projects / "sandbar" / "data" / "develop" / "wt" / "sandbar"
    make_git_repo(repo)
    return repo_tip(repo)


def round_once(tmp_path, header, trigger="change", at=1, runs_store=None,
               main_tip=None):
    """One run_line_round over a fresh landing (relative caliber, isolated
    project store — call rel_env once per test first); returns
    (entry, rows). The fake runner answers the line revision with
    ``header`` and the baseline (main tip) with a green header, so the
    round's new_regressions are exactly the header's failed_names."""
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "rev-%d" % at, at=at)], p)

    def runner(cand):
        if main_tip is not None and cand[0]["revision"] == main_tip:
            return {"id": dc.mint_id("run"),
                    "cases": {"ran": 10, "failed": 0, "env_failed": 0},
                    "failed_names": []}
        return header

    out = dc.run_line_round(LINE, trigger, guard_path(tmp_path),
                            runner, reader(p), writer(p),
                            "round-engine", "booked-v1",
                            project="sandbar", roster={"entries": []},
                            runs_store=runs_store)
    rows, _ = dc.read_rows(p)
    return out["rounds"][0], rows


# ---- the pure truth tables ---------------------------------------------------

class TestClassifyRedCase:
    def test_assertion_reason_is_content_guilt(self):
        assert dc.classify_red_case(
            {"reason": "assert_mismatch",
             "evidence": "FAIL [t-x] expected 3 got 4"}) == dc.CONTENT_GUILT

    def test_assertion_error_line_is_content_guilt(self):
        assert dc.classify_red_case(
            {"evidence": "Traceback (most recent call last): "
                         "AssertionError"}) == dc.CONTENT_GUILT

    def test_empty_receipt_is_round_only(self):
        # the measured shape: the receipt exists and names NOTHING
        assert dc.classify_red_case({}) == dc.ROUND_ONLY

    def test_env_reason_without_assertion_is_round_only(self):
        assert dc.classify_red_case(
            {"reason": "connect_refused",
             "evidence": "ENV_FAIL no bench on 7233"}) == dc.ROUND_ONLY

    def test_missing_receipt_is_content_guilt(self):
        assert dc.classify_red_case(None) == dc.CONTENT_GUILT

    def test_unparseable_receipt_is_content_guilt(self):
        # JSON-parseable garbage: the row exists but its fields are not
        # strings the judge can read — fail closed to the old behaviour
        assert dc.classify_red_case({"reason": ["fail"],
                                     "evidence": {"tail": "x"}}) \
            == dc.CONTENT_GUILT
        assert dc.classify_red_case("not a dict") == dc.CONTENT_GUILT


class TestClassifyNewRegressions:
    def test_legacy_header_without_receipts_fails_closed(self):
        out = dc.classify_new_regressions({"id": "run-x"}, [CASE])
        assert out == {CASE: dc.CONTENT_GUILT}

    def test_non_dict_header_fails_closed(self):
        assert dc.classify_new_regressions(None, [CASE]) \
            == {CASE: dc.CONTENT_GUILT}

    def test_name_missing_from_map_is_content_guilt(self):
        out = dc.classify_new_regressions(
            {"fail_receipts": {CASE: {}}}, [CASE, "other-case"])
        assert out["other-case"] == dc.CONTENT_GUILT
        assert out[CASE] == dc.ROUND_ONLY

    def test_malformed_map_fails_closed(self):
        out = dc.classify_new_regressions({"fail_receipts": "junk"}, [CASE])
        assert out == {CASE: dc.CONTENT_GUILT}


class TestRoundOnlyEscalation:
    def test_three_consecutive_same_case(self):
        ro = [{CASE: dc.ROUND_ONLY}] * 3
        assert dc.round_only_escalation(ro, CASE) == (3, 0)

    def test_two_do_not_escalate(self):
        assert dc.round_only_escalation([{CASE: dc.ROUND_ONLY}] * 2, CASE) \
            == (2, 0)

    def test_content_round_resets_the_streak(self):
        hist = [{CASE: dc.ROUND_ONLY}, {CASE: dc.CONTENT_GUILT},
                {CASE: dc.ROUND_ONLY}]
        assert dc.round_only_escalation(hist, CASE) == (1, 0)

    def test_interleaved_other_case_does_not_count(self):
        hist = [{CASE: dc.ROUND_ONLY}, {"other": dc.ROUND_ONLY},
                {CASE: dc.ROUND_ONLY}]
        assert dc.round_only_escalation(hist, CASE) == (1, 0)

    def test_uncountable_stops_and_is_counted(self):
        # a legacy round whose classification cannot be read back ends the
        # scan: the short streak is reported with its uncountable count
        hist = [{CASE: dc.ROUND_ONLY}, None, {CASE: dc.ROUND_ONLY}]
        assert dc.round_only_escalation(hist, CASE) == (1, 1)


# ---- the settle-block journeys ------------------------------------------------

def make_git_repo(path):
    """A minimal repo with one commit on main, as the line worktree the
    baseline's main-tip resolution needs (the t261009-30 fixture shape)."""
    import subprocess
    path.mkdir(parents=True)

    def g(*a):
        subprocess.run(["git"] + list(a), cwd=str(path), check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "it@t261026")
    g("config", "user.name", "it")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "m0")


def repo_tip(path):
    import subprocess
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "refs/heads/main"],
        check=True, capture_output=True, text=True).stdout.strip()


def test_round_only_red_never_freezes_and_is_named(tmp_path, monkeypatch):
    main_tip = rel_env(tmp_path, monkeypatch)
    """The 718578ef shape: one red, receipt names no assertion -> the round
    stays red, the case is NAMED and COUNTED on the face, NO freeze opens,
    and the entry says why."""
    entry, rows = round_once(tmp_path, red_header(), main_tip=main_tip)
    assert entry["state"] == dc.STATE_RED and entry["verdict"] == "red"
    assert entry["round_only"] == [CASE]
    assert entry["round_only_count"] == 1
    assert entry["next"] == "round_only_no_freeze"
    assert "no failing assertion" in entry["note"]
    assert dc.freeze_state(rows, LINE)["frozen"] is False
    assert not [x for x in rows if x["kind"] == dc.KIND_FREEZE]
    # never silently green: a red cert is booked, it cites the run
    certs = [x for x in rows if x["kind"] == dc.KIND_CERT]
    assert len(certs) == 1 and certs[0]["run"] == entry["run"]


def test_real_assertion_red_still_freezes_immediately(tmp_path, monkeypatch):
    main_tip = rel_env(tmp_path, monkeypatch)
    """Spec item 4: a receipt that names a failing assertion changes nothing
    — the freeze opens on the first red, exactly as before."""
    entry, rows = round_once(
        tmp_path,
        red_header({CASE: {"reason": "assert_mismatch",
                           "evidence": "AssertionError: expected 3 got 4"}}),
        main_tip=main_tip)
    assert entry["state"] == dc.STATE_RED
    assert "round_only" not in entry
    st = dc.freeze_state(rows, LINE)
    assert st["frozen"] is True and st["cause"] == entry["cert"]


def test_legacy_header_without_receipts_still_freezes(tmp_path, monkeypatch):
    main_tip = rel_env(tmp_path, monkeypatch)
    """Spec item 3: a run record without a receipts field cannot be judged —
    fail closed to the old behaviour (content guilt, freeze opens)."""
    header = red_header()
    del header["fail_receipts"]
    entry, rows = round_once(tmp_path, header, main_tip=main_tip)
    assert entry["state"] == dc.STATE_RED
    assert "round_only" not in entry
    assert dc.freeze_state(rows, LINE)["frozen"] is True


def test_env_only_red_never_freezes_unchanged(tmp_path, monkeypatch):
    main_tip = rel_env(tmp_path, monkeypatch)
    """Spec item 4: the t261024-30 shape is untouched."""
    header = {"id": dc.mint_id("run"),
              "cases": {"ran": 10, "failed": 0, "env_failed": 4},
              "failed_names": [], "unverified_names": [CASE],
              "fail_receipts": {CASE: {"reason": "connect_refused"}}}
    entry, rows = round_once(tmp_path, header, main_tip=main_tip)
    # relative caliber: an env-only name never reaches new_regressions ->
    # the round certifies green (the 261024-30 contract), no freeze
    assert entry["verdict"] == "green"
    assert dc.freeze_state(rows, LINE)["frozen"] is False


def test_escalation_three_consecutive_round_only_reds_freeze_the_case(
        tmp_path, monkeypatch):
    """Spec item 2: the same case round-only three rounds in a row — the
    case is sick, not the revision. The freeze opens on the THIRD and names
    the case; two rounds open nothing."""
    main_tip = rel_env(tmp_path, monkeypatch)
    store = tmp_path / "runs.jsonl"
    entry2, rows2 = (None, None)
    for at in (1, 2, 3):
        entry, rows = round_once(tmp_path, red_header(), at=at,
                                 runs_store=str(store), main_tip=main_tip)
        if at < 3:
            assert dc.freeze_state(rows, LINE)["frozen"] is False
        entry2, rows2 = entry, rows
    assert entry2["verdict"] == "red"
    esc = entry2.get("escalation")
    assert esc and esc["case"] == CASE and esc["streak"] == 3
    st = dc.freeze_state(rows2, LINE)
    assert st["frozen"] is True
    # the freeze NAMES the case: the attribution change carries it
    changes = [x for x in rows2 if x["kind"] == dc.KIND_FREEZE_CHANGE
               and x.get("change") == dc.CHANGE_ATTRIBUTION
               and "round_only_escalation" in x.get("reason", "")]
    assert changes and changes[-1]["value"] == CASE


def test_escalation_streak_broken_by_a_green_round(tmp_path, monkeypatch):
    main_tip = rel_env(tmp_path, monkeypatch)
    """A round where the case passes (green) between two round-only reds
    resets the streak: two reds, a green, a red -> no escalation freeze."""
    store = tmp_path / "runs.jsonl"
    round_once(tmp_path, red_header(), at=1, runs_store=str(store), main_tip=main_tip)
    round_once(tmp_path, red_header(), at=2, runs_store=str(store), main_tip=main_tip)
    green = {"id": dc.mint_id("run"), "verdict": "green",
             "cases": {"ran": 10, "failed": 0, "env_failed": 0},
             "failed_names": []}
    round_once(tmp_path, green, at=3, runs_store=str(store), main_tip=main_tip)
    entry, rows = round_once(tmp_path, red_header(), at=4,
                             runs_store=str(store), main_tip=main_tip)
    assert "escalation" not in entry
    assert dc.freeze_state(rows, LINE)["frozen"] is False


def test_escalation_uncountable_prior_round_stops_the_streak(tmp_path, monkeypatch):
    rel_env(tmp_path, monkeypatch)
    """A prior red whose cited run record cannot be read back (or predates
    the classification) is UNCOUNTABLE: it stops the streak and is named on
    the face, so a silently short streak is visible (review comment 3)."""
    p = ledger(tmp_path)
    store = tmp_path / "runs.jsonl"
    dc.append_rows([landing("sandbar", "old-rev", at=1)], p)
    legacy_cert = {"kind": dc.KIND_CERT, "id": dc.mint_id("cert", 2),
                   "line": LINE,
                   "repos": [{"repo": "sandbar", "revision": "old-rev"}],
                   "run": "run-legacy-predates-classification",
                   "booked_red": "booked-v1", "judged_by": "round-engine",
                   "at": 2}
    dc.append_rows([legacy_cert], p)
    dc.append_rows([landing("sandbar", "new-rev", ticket="t2", at=3)], p)
    _tip = repo_tip(tmp_path / "projects" / "sandbar" / "data" /
                    "develop" / "wt" / "sandbar")

    def _runner(cand):
        if cand[0]["revision"] == _tip:
            return {"id": dc.mint_id("run"),
                    "cases": {"ran": 10, "failed": 0, "env_failed": 0},
                    "failed_names": []}
        return red_header()

    out = dc.run_line_round(LINE, "change", guard_path(tmp_path),
                            _runner, reader(p), writer(p),
                            "round-engine", "booked-v1",
                            project="sandbar", roster={"entries": []},
                            runs_store=str(store))
    entry = out["rounds"][0]
    assert "escalation" not in entry
    rows, _ = dc.read_rows(p)
    assert dc.freeze_state(rows, LINE)["frozen"] is False


# ---- the heal path obeys the same rule ----------------------------------------

def _runs_rows(tmp_path, run):
    # the heal's judgable gate wants a verdict AND a valid candidate set
    run = dict(run, source=dc.LINE_ROUND_RUN_SOURCE,
               repos=[{"repo": "sandbar", "revision": "rev-h"}])
    path = tmp_path / "heal-runs.jsonl"
    path.write_text(json.dumps(run) + "\n", encoding="utf-8")
    rows, _ = dc._read_rows_path(path)
    return rows


def test_heal_round_only_red_opens_no_freeze(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "rev-h", at=1)], p)
    rows, _ = dc.read_rows(p)
    run = red_header()
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows, _runs_rows(tmp_path, run),
        writer(p), "heal", "booked-v1", None, sole_line=True,
        guard_held=False)
    assert out and out[0]["state"] == "reconciled"
    rows2, _ = dc.read_rows(p)
    assert dc.freeze_state(rows2, LINE)["frozen"] is False


def test_heal_assertion_red_still_freezes(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "rev-h", at=1)], p)
    rows, _ = dc.read_rows(p)
    run = red_header({CASE: {"reason": "assert_mismatch",
                             "evidence": "AssertionError"}})
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows, _runs_rows(tmp_path, run),
        writer(p), "heal", "booked-v1", None, sole_line=True,
        guard_held=False)
    assert out and out[0]["state"] == "reconciled"
    rows2, _ = dc.read_rows(p)
    assert dc.freeze_state(rows2, LINE)["frozen"] is True


def test_heal_legacy_run_without_receipts_fails_closed(tmp_path):
    """A healed legacy run carries names but no receipts: content guilt, the
    old behaviour (review comment 2's safe default)."""
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "rev-h", at=1)], p)
    rows, _ = dc.read_rows(p)
    run = red_header()
    del run["fail_receipts"]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows, _runs_rows(tmp_path, run),
        writer(p), "heal", "booked-v1", None, sole_line=True,
        guard_held=False)
    assert out and out[0]["state"] == "reconciled"
    rows2, _ = dc.read_rows(p)
    assert dc.freeze_state(rows2, LINE)["frozen"] is True


# ---- the receipt source (integration/line_round_runner.py) --------------------

def test_fail_receipts_reads_the_same_result_lines(tmp_path):
    """The runner lifts the per-case receipt from the SAME canonical lines
    failed_names reads. Fault modes: malformed line skipped, non-string
    fields dropped, duplicate names last-wins, passed case not lifted."""
    import importlib.util
    runner_path = ENGINE.parents[1] / "integration" / "line_round_runner.py"
    spec = importlib.util.spec_from_file_location("lrr_t261026_19",
                                                  runner_path)
    lrr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lrr)
    log = tmp_path / "suite.log"
    log.write_text("\n".join([
        json.dumps({"name": CASE, "status": "fail",
                    "reason": "assert_mismatch",
                    "evidence": "expected 3 got 4"}),
        "not json at all {",
        json.dumps({"name": "env-case", "status": "not-checked",
                    "reason": "connect_refused", "evidence": 42}),
        json.dumps({"name": "retry-case", "status": "fail",
                    "reason": "lock_busy"}),
        json.dumps({"name": "retry-case", "status": "fail",
                    "reason": "assert_mismatch",
                    "evidence": "AssertionError: boom"}),
        json.dumps({"name": "passing-case", "status": "pass",
                    "reason": "assert_mismatch"}),
        json.dumps({"status": "fail", "reason": "no name"}),
    ]) + "\n", encoding="utf-8")
    out = lrr.fail_receipts(log)
    assert out[CASE] == {"status": "fail", "reason": "assert_mismatch",
                         "evidence": "expected 3 got 4"}
    # non-string evidence dropped, string reason kept
    assert out["env-case"] == {"status": "not-checked",
                               "reason": "connect_refused"}
    # duplicate name: the LAST row wins
    assert out["retry-case"]["status"] == "fail"
    assert out["retry-case"]["reason"] == "assert_mismatch"
    assert "passing-case" not in out
    # unreadable log -> {} (fails closed content-side at the judge)
    assert lrr.fail_receipts(tmp_path / "absent.log") == {}
