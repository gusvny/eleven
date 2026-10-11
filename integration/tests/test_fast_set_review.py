#!/usr/bin/env python3
"""t261011-11 developer L1 battery: the fast-set patrol's pure core.

Under test (integration/run_scenarios.py, loaded by path): the verdict
ledger row contract (exact shape, fail-closed append, append-only bytes),
the mean+max cost stats, the judged-round view with its named degradation,
the per-member flag truth tables (over-budget-share / red-in-round /
no-catch-in-window / must-lose-membership:booked / :browser-pool /
recorded-remove), the registry-derived coverage gap, and the review face's
output + exit-code contract over fixtures (monkeypatched preflight).

Offline seconds; zero docker/browser; never touches 3099; no integration
entry is executed and the real scenario/verdict ledgers are never written
(temp paths only).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "rs_t261011_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def row(member="m-a", verdict="keep", **over):
    r = {"at": "2026-10-11T00:00:00Z", "member": member, "verdict": verdict,
         "cost_s": 0.5, "evidence": "mean 0.5s, caught nothing in window",
         "who": "integration patrol"}
    r.update(over)
    return r


def srow(scenario="m-a", wall_s=1.0, verdict="pass", run=None, **over):
    r = {"scenario": scenario, "wall_s": wall_s, "verdict": verdict}
    if run is not None:
        r["run"] = run
    r.update(over)
    return r


def entry(name, pool="ro", *tail):
    opt = pool if pool != "main" else None
    lst = [name, "spec text", "cmd", opt]
    lst.extend(tail)
    return tuple(lst)


# ---- verdict ledger row contract -------------------------------------------

def test_row_shape_accepted_then_read_back(tmp_path):
    p = tmp_path / "v.jsonl"
    rs.fast_set_review_append(row(), path=str(p))
    rows, bad = rs.fast_set_review_rows(path=str(p))
    assert bad == []
    assert len(rows) == 1 and rows[0]["member"] == "m-a"
    assert rows[0]["verdict"] == "keep" and rows[0]["who"] == "integration patrol"


@pytest.mark.parametrize("mutate", [
    {"at": ""}, {"at": 5}, {"member": ""}, {"verdict": "trim"},
    {"verdict": ""}, {"cost_s": -1}, {"cost_s": True}, {"cost_s": "0.5"},
    {"evidence": ""}, {"who": None},
])
def test_malformed_row_refused_named_nothing_written(tmp_path, mutate):
    p = tmp_path / "v.jsonl"
    bad = row(**mutate)
    with pytest.raises(ValueError) as ei:
        rs.fast_set_review_append(bad, path=str(p))
    assert "REFUSED [__fast_set__]" in str(ei.value)
    # the offending field is named, not a generic refusal
    assert list(mutate)[0] in str(ei.value)
    assert not p.exists()  # nothing written on refusal


def test_missing_field_named_individually(tmp_path):
    p = tmp_path / "v.jsonl"
    r = row()
    del r["evidence"]
    with pytest.raises(ValueError) as ei:
        rs.fast_set_review_append(r, path=str(p))
    assert "evidence" in str(ei.value)
    assert not p.exists()


def test_append_only_existing_bytes_never_rewritten(tmp_path):
    p = tmp_path / "v.jsonl"
    rs.fast_set_review_append(row(), path=str(p))
    before = p.read_bytes()
    rs.fast_set_review_append(row(verdict="remove"), path=str(p))
    after = p.read_bytes()
    assert after.startswith(before)  # pure append, old rows untouched
    rows, _ = rs.fast_set_review_rows(path=str(p))
    assert [r["verdict"] for r in rows] == ["keep", "remove"]


def test_later_row_wins_as_correction(tmp_path):
    rows, _ = rs.fast_set_review_rows(path=str(
        (lambda p: (rs.fast_set_review_append(row(), path=str(p)),
                    rs.fast_set_review_append(row(verdict="remove"),
                                              path=str(p)),
                    p)[2])(tmp_path / "v.jsonl")))
    assert rs.fast_set_review_verdicts(rows)["m-a"]["verdict"] == "remove"


def test_reader_absent_file_is_empty_not_error(tmp_path):
    rows, bad = rs.fast_set_review_rows(path=str(tmp_path / "nope.jsonl"))
    assert rows == [] and bad == []


def test_reader_malformed_lines_named_readable_rows_stay(tmp_path):
    p = tmp_path / "v.jsonl"
    p.write_text("not json\n" + json.dumps(row()) + "\n[1,2]\n",
                 encoding="utf-8")
    rows, bad = rs.fast_set_review_rows(path=str(p))
    assert len(rows) == 1 and len(bad) == 2
    assert bad[0].startswith("not json")


def test_reader_directory_and_unreadable_named(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    rows, bad = rs.fast_set_review_rows(path=str(d))
    assert rows == [] and bad and "directory" in bad[0]


# ---- cost stats: mean AND max, no-measurement named -------------------------

def test_stats_mean_max_runs(tmp_path):
    stats, bad = rs.fast_set_cost_stats(
        [srow(wall_s=1.0), srow(wall_s=3.0), srow(wall_s=2.0)], ["m-a"])
    assert bad == 0
    assert stats["m-a"] == {"mean_s": 2.0, "max_s": 3.0, "runs": 3}


def test_stats_unmeasured_is_none_never_zero():
    stats, _ = rs.fast_set_cost_stats([], ["m-a"])
    assert stats["m-a"] is None


def test_stats_malformed_rows_counted():
    stats, bad = rs.fast_set_cost_stats(
        ["junk", srow(), {"scenario": "m-a", "wall_s": -1},
         {"scenario": "m-a", "wall_s": True}], ["m-a"])
    assert bad == 3 and stats["m-a"]["mean_s"] == 1.0


def test_fast_set_costs_delegates_mean():
    costs, bad = rs.fast_set_costs([srow(wall_s=2.0), srow(wall_s=4.0)],
                                   ["m-a"])
    assert costs == {"m-a": 3.0} and bad == 0


# ---- judged-round view: named degradation -----------------------------------

def test_rounds_distinct_runs_ordered():
    v = rs.fast_set_review_rounds(
        [srow(run="r1"), srow(run="r2"), srow(run="r1"), srow(run="r3")])
    assert v["rounds"] == ["r1", "r2", "r3"] and v["note"] == ""


def test_rounds_empty_ledger_degrades_named():
    v = rs.fast_set_review_rounds([])
    assert v["rounds"] == [] and "no judged rounds" in v["note"]


def test_rounds_runless_legacy_rows_named_never_fabricated():
    v = rs.fast_set_review_rounds([srow(), srow(wall_s=2.0)])
    assert v["rounds"] == [] and v["unrunned_rows"] == 2
    assert "run-less legacy row(s)" in v["note"]


# ---- flag core truth tables --------------------------------------------------

def _flags(rows, member_entries, booked=frozenset(), verdict_rows=(),
           width=rs.FAST_SET_CONC_WIDTH):
    stats, _ = rs.fast_set_cost_stats(rows, [e[0] for e in member_entries])
    return rs.fast_set_review(member_entries, stats, booked,
                              rs.fast_set_review_verdicts(list(verdict_rows)),
                              rs.fast_set_review_rounds(rows),
                              rs.fast_set_member_red_runs(
                                  rows, {e[0] for e in member_entries}),
                              width=width)["members"]


def test_over_budget_share_boundary():
    budget = rs.FAST_SET_MEMBER_BUDGET_S
    rows = [srow(wall_s=budget)]  # exactly at the share: no flag
    f = _flags(rows, [entry("m-a")])
    assert not any("over-budget-share" in x for x in f["m-a"])
    rows = [srow(wall_s=budget + 0.01)]
    f = _flags(rows, [entry("m-a")])
    assert any("over-budget-share" in x and "declared" in x for x in f["m-a"])


def test_unmeasured_member_never_carries_over_budget():
    f = _flags([], [entry("m-a")])
    assert not any("over-budget-share" in x for x in f["m-a"])
    assert not any("no-catch-in-window" in x for x in f["m-a"])  # no rounds


def test_red_in_round_names_clause_judgement_not_automatic_catch():
    rows = [srow(verdict="fail", run="r1")]
    f = _flags(rows, [entry("m-a")])
    red = [x for x in f["m-a"] if x.startswith("red-in-round")]
    assert red and "fast-catch clause" in red[0] and "judge the match" in red[0]
    assert not any("no-catch-in-window" in x for x in f["m-a"])


def test_no_catch_in_window_within_declared_window():
    rows = [srow(run="r%d" % i) for i in range(rs.FAST_SET_CATCH_WINDOW_ROUNDS)]
    f = _flags(rows, [entry("m-a")])
    assert any("no-catch-in-window" in x and
               str(rs.FAST_SET_CATCH_WINDOW_ROUNDS) in x for x in f["m-a"])


def test_red_inside_window_suppresses_no_catch_flag():
    rows = [srow(run="r%d" % i) for i in range(19)]
    rows.append(srow(verdict="fail", run="r20"))
    f = _flags(rows, [entry("m-a")])
    assert not any("no-catch-in-window" in x for x in f["m-a"])
    assert any("red-in-round" in x for x in f["m-a"])


def test_no_rounds_window_not_judged_named():
    f = _flags([srow()], [entry("m-a")])  # run-less rows: no judged rounds
    assert not any("no-catch-in-window" in x for x in f["m-a"])


def test_must_lose_booked_and_browser_pool():
    f = _flags([], [entry("m-a"), entry("m-b", pool="browser")],
               booked={"m-a"})
    assert any("must-lose-membership:booked" in x and
               "known-red roster" in x for x in f["m-a"])
    assert any("must-lose-membership:browser-pool" in x for x in f["m-b"])


def test_recorded_remove_flag():
    f = _flags([], [entry("m-a")], verdict_rows=[row(verdict="remove")])
    assert any("recorded-remove" in x and "REMOVE" in x for x in f["m-a"])
    f = _flags([], [entry("m-a")], verdict_rows=[row(verdict="keep")])
    assert not any("recorded-remove" in x for x in f["m-a"])


# ---- coverage gap from the registry's own grouping --------------------------

def test_uncovered_pools_registry_derived():
    F = rs.FAST_SET_MARKER
    reg = [entry("a", "ro", F), entry("b", "main"),
           entry("c", "browser", F)]
    assert rs.fast_set_uncovered_pools(registry=reg) == ["main"]
    reg.append(entry("d", "main", F))
    assert rs.fast_set_uncovered_pools(registry=reg) == []


# ---- declared constants: derived, never a second hand number ----------------

def test_member_budget_share_derives_from_budget_and_width():
    assert rs.FAST_SET_CONC_WIDTH > 0
    assert rs.FAST_SET_MEMBER_BUDGET_S == round(
        rs.FAST_SET_BUDGET_MIN * 60 / rs.FAST_SET_CONC_WIDTH)


def test_cadence_and_window_are_declared_positive_ints():
    assert rs.FAST_SET_REVIEW_CADENCE_DAYS > 0
    assert rs.FAST_SET_CATCH_WINDOW_ROUNDS > 0


def test_declaration_comment_carries_cadence_and_four_triggers():
    src = (REPO / "integration" / "run_scenarios.py").read_text(encoding="utf-8")
    for needle in ("FAST_SET_REVIEW_CADENCE_DAYS", "(a) MISS",
                   "(b) RED-IN-ROUND", "(c) BUDGET BREACH",
                   "(d) GUARD FIRES", "never an auto-trim"):
        assert needle in src, needle


def test_verdict_ledger_not_gitignored():
    gi = REPO / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    assert "fast-set-review" not in text


# ---- the ONE face: output + exit contract over fixtures ---------------------

class _FakeSL:
    """Scenario-ledger stand-in (never the real ledger on disk)."""
    def __init__(self, rows):
        self._rows = rows

    def read_rows(self, path=None):
        return list(self._rows), 0


def _run_face(monkeypatch, capsys, members, sl_rows, booked=frozenset(),
              roster_err="", vrows=(), errors=()):
    monkeypatch.setattr(rs, "fast_set_preflight",
                        lambda: (members, list(errors)))
    monkeypatch.setattr(rs, "read_known_red_roster_strict",
                        lambda root: (list(booked), roster_err))
    monkeypatch.setitem(sys.modules, "scenario_ledger", _FakeSL(sl_rows))
    monkeypatch.setattr(rs, "fast_set_review_rows", lambda path=None:
                        (list(vrows), 0))
    rc = rs.print_fast_set_review()
    return rc, capsys.readouterr().out


def test_face_happy_path_prints_table_declarations_verdict(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    members = [entry("m-a", "ro", "serial"),
               entry("m-b", "main", rs.FAST_SET_MARKER)]
    sl_rows = [srow("m-a", wall_s=1.0, run="r1"),
               srow("m-b", wall_s=4.0, run="r1"),
               srow("m-b", wall_s=6.0, run="r2")]
    vrows = [row(member="m-b", verdict="keep")]
    rc, out = _run_face(monkeypatch, capsys, members, sl_rows, vrows=vrows)
    assert rc == 0
    line = [l for l in out.splitlines() if l.startswith("FAST_SET_REVIEW ")]
    assert line and "cadence_days=%d" % rs.FAST_SET_REVIEW_CADENCE_DAYS in line[0]
    assert "width=%d" % rs.FAST_SET_CONC_WIDTH in line[0]
    assert "member_budget_s=%d" % rs.FAST_SET_MEMBER_BUDGET_S in line[0]
    a = [l for l in out.splitlines() if "member m-a " in l][0]
    assert "mean=1.00s" in a and "verdict=none" in a and "fast-catch:" in a
    b = [l for l in out.splitlines() if "member m-b " in l][0]
    assert "mean=" in b and "max=6.0" in b and "runs=2" in b
    assert "verdict=keep" in b and "integration patrol" in b
    assert "FAST_SET_REVIEW_ESTIMATE" in out
    # main pool has scenarios (m-b) but no fast member -> coverage gap named
    assert "FAST_SET_REVIEW_UNCOVERED" in out and "main" in out
    assert "FAST_SET_REVIEW_NO_VERDICTS" not in out


def test_face_names_must_lose_and_refuses_nonzero(monkeypatch, capsys):
    members = [entry("m-a", pool="browser")]
    rc, out = _run_face(monkeypatch, capsys, members, [], booked={"m-a"})
    assert rc == 2
    assert "must LOSE membership" in out
    assert "must-lose-membership:booked" in out
    assert "must-lose-membership:browser-pool" in out


def test_face_guard_errors_refuse_named(monkeypatch, capsys):
    rc, out = _run_face(monkeypatch, capsys, [entry("m-a")], [],
                        errors=["[m-a] fast member has no fast-catch"])
    assert rc == 2 and "fast-catch" in out and "REFUSED [__fast_set__]" in out


def test_face_empty_ledgers_named_never_fabricated(monkeypatch, capsys):
    rc, out = _run_face(monkeypatch, capsys, [entry("m-a")], [])
    assert rc == 0
    assert "no measured cost" in out
    assert "FAST_SET_REVIEW_NO_VERDICTS" in out
    assert "no judged rounds" in out  # window degradation named


def test_face_budget_breach_named_signal_not_trim(monkeypatch, capsys):
    big = rs.FAST_SET_MEMBER_BUDGET_S * 40
    members = [entry("m-a"), entry("m-b"), entry("m-c")]
    sl_rows = [srow(n, wall_s=big, run="r1") for n in ("m-a", "m-b", "m-c")]
    rc, out = _run_face(monkeypatch, capsys, members, sl_rows)
    assert rc == 0
    br = [l for l in out.splitlines() if l.startswith(
        "FAST_SET_REVIEW_BUDGET_BREACH")]
    assert br and "never an auto-trim" in br[0]


def test_face_malformed_scenario_rows_warned(monkeypatch, capsys):
    monkeypatch.setattr(rs, "fast_set_preflight",
                        lambda: ([entry("m-a")], []))
    monkeypatch.setattr(rs, "read_known_red_roster_strict",
                        lambda root: ([], ""))
    monkeypatch.setitem(sys.modules, "scenario_ledger",
                        _FakeSL(["junk row"]))
    monkeypatch.setattr(rs, "fast_set_review_rows", lambda path=None: ([], 0))
    rc = rs.print_fast_set_review()
    out = capsys.readouterr().out
    assert rc == 0 and "FAST_SET_REVIEW_LEDGER_WARN" in out


def test_face_roster_absent_not_double_refused(monkeypatch, capsys):
    # roster absent (挂账册不在场) is preflight's own named error already;
    # the face must not duplicate it.
    rc, out = _run_face(monkeypatch, capsys, [entry("m-a")], [],
                        roster_err="挂账册不在场：/x/y.json")
    assert out.count("挂账册不在场") == 0
    assert rc == 0
