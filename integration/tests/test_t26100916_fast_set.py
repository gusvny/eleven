#!/usr/bin/env python3
"""t261009-16 fast global set — developer L1 pure-function battery.

Covers (review conditions 1/2/3/4 of the plan review):
- marker parse truth table: pool-slot ambiguity, duplicate marker, unknown
  trailing element, pool-less serial+fast shapes, plain entries;
- validate_fast_set: both-direction catch-dict drift, duplicate registry
  name, budget type, exclusive/browser pool refusal;
- fast_set_entries raise-face over fixture registries (fail-closed);
- fast_set_preflight: booked-red member refusal, UNREADABLE roster refused
  (never read as an empty roster), stubbed roster reader (no real file);
- fast_set_costs: malformed ledger rows counted and named, missing member
  row = None (never a fabricated 0);
- fast_set_wall_estimate: serial sums, pole-vs-sum/width arithmetic,
  unmeasured counting, width=1 degenerate;
- fast_set_mode_enabled: flag > env > off, malformed env values.

Zero docker/network/ledger-file contact: the roster reader and rows are
injected fixtures; the real tree is only read via the imported module.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))

import run_scenarios as rs  # noqa: E402


# ---- marker parse truth table ------------------------------------------------

def test_plain_entry_is_not_fast():
    assert rs.parse_fast_markers(("x", "i", "c")) == (False, [])
    assert rs.parse_fast_markers(("x", "i", "c", "ro")) == (False, [])


def test_fast_marker_in_pool_slot_is_named_error():
    is_fast, errs = rs.parse_fast_markers(("x", "i", "c", "fast"))
    assert is_fast is True
    assert any("pool slot" in e for e in errs)


def test_duplicate_fast_marker_is_named_error():
    is_fast, errs = rs.parse_fast_markers(("x", "i", "c", "ro", "fast", "fast"))
    assert is_fast is True
    assert any("duplicate fast marker" in e for e in errs)


def test_duplicate_serial_marker_is_named_error():
    _, errs = rs.parse_fast_markers(("x", "i", "c", "serial", "serial"))
    assert any("duplicate serial marker" in e for e in errs)


def test_unknown_trailing_element_is_named_error():
    _, errs = rs.parse_fast_markers(("x", "i", "c", "ro", "faste"))
    assert any("unknown trailing element" in e and "faste" in e for e in errs)


def test_poolless_serial_fast_is_legal():
    is_fast, errs = rs.parse_fast_markers(("x", "i", "c", "serial", "fast"))
    assert (is_fast, errs) == (True, [])


def test_fast_and_serial_in_either_order_is_legal():
    for shape in (("ro", "fast", "serial"), ("ro", "serial", "fast")):
        is_fast, errs = rs.parse_fast_markers(("x", "i", "c") + shape)
        assert (is_fast, errs) == (True, [])


# ---- validate_fast_set -------------------------------------------------------

def _one(name="m", *tail):
    return (name, "intent", "cmd") + tail


def test_real_registry_declares_clean():
    assert rs.validate_fast_set() == []


def test_fast_member_without_catch_is_named_error():
    reg = [_one("m", "ro", "fast")]
    errs = rs.validate_fast_set(reg)
    assert any("no fast-catch declaration" in e and "[m]" in e for e in errs)


def test_orphan_catch_key_is_named_error():
    saved = dict(rs.FAST_SET_CATCH)
    try:
        rs.FAST_SET_CATCH["ghost"] = "nothing"
        errs = rs.validate_fast_set()
        assert any("orphan" in e and "[ghost]" in e for e in errs)
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


def test_duplicate_registry_name_is_named_error():
    errs = rs.validate_fast_set([_one("m", "ro"), _one("m", "ro")])
    assert any("duplicate registry name" in e for e in errs)


@pytest.mark.parametrize("pool", ["exclusive", "browser"])
def test_exclusive_and_browser_members_refused(pool):
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH["m"] = "x"
    try:
        errs = rs.validate_fast_set([_one("m", pool, "fast")])
        assert any(pool in e for e in errs)
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


def test_budget_must_be_positive_int(monkeypatch):
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH["m"] = "x"
    try:
        monkeypatch.setattr(rs, "FAST_SET_BUDGET_MIN", 0)
        assert any("FAST_SET_BUDGET_MIN" in e
                   for e in rs.validate_fast_set([_one("m", "ro", "fast")]))
        monkeypatch.setattr(rs, "FAST_SET_BUDGET_MIN", 1.5)
        assert any("FAST_SET_BUDGET_MIN" in e
                   for e in rs.validate_fast_set([_one("m", "ro", "fast")]))
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


# ---- fast_set_entries raise face --------------------------------------------

def test_entries_on_real_registry_are_the_marked_ones():
    names = [e[0] for e in rs.fast_set_entries()]
    marked = [e[0] for e in rs.SCENARIOS
              if "fast" in e[3:]]
    assert names == marked and len(names) > 0


def test_entries_raise_on_duplicate_member_name():
    with pytest.raises(ValueError, match="duplicate member name"):
        rs.fast_set_entries([_one("a", "ro", "fast"), _one("a", "ro", "fast"),
                             _one("b", "ro")])


def test_entries_raise_on_pool_slot_marker():
    with pytest.raises(ValueError, match="pool slot"):
        rs.fast_set_entries([_one("a", "fast")])


def test_entries_raise_on_unknown_trailing_element():
    with pytest.raises(ValueError, match="unknown trailing element"):
        rs.fast_set_entries([_one("a", "ro", "faste")])


def test_entries_raise_on_duplicate_marker():
    with pytest.raises(ValueError, match="duplicate fast marker"):
        rs.fast_set_entries([_one("a", "ro", "fast", "fast")])


# ---- preflight ---------------------------------------------------------------

def _ok_roster_reader(names):
    def reader(root):
        return list(names), ""
    return reader


def test_preflight_booked_red_member_refused_by_name():
    members = [_one("m1", "ro", "fast"), _one("m2", "ro", "fast")]
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH.update({"m1": "x", "m2": "y"})
    try:
        got, errs = rs.fast_set_preflight(
            roster_reader=_ok_roster_reader(["m1"]),
            registry=[_one("m1", "ro", "fast"), _one("m2", "ro", "fast")])
        assert [e[0] for e in got] == ["m1", "m2"]
        assert len(errs) == 1 and "[m1]" in errs[0] \
            and "known-red roster" in errs[0]
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


def test_preflight_unreadable_roster_is_never_an_empty_roster():
    def reader(root):
        return [], "挂账册读取/解析失败（boom）"
    _, errs = rs.fast_set_preflight(roster_reader=reader,
                                    registry=[_one("m", "ro", "fast")])
    assert any("unreadable" in e and "boom" in e for e in errs)


def test_preflight_clean_on_fixture_registry():
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH.update({"m": "x"})
    try:
        got, errs = rs.fast_set_preflight(
            roster_reader=_ok_roster_reader([]),
            registry=[_one("m", "ro", "fast"), _one("z", "ro")])
        assert [e[0] for e in got] == ["m"] and errs == []
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


# ---- costs -------------------------------------------------------------------

def test_costs_mean_and_missing_row_is_none():
    rows = [{"scenario": "a", "wall_s": 1.0}, {"scenario": "a", "wall_s": 3.0},
            {"scenario": "b", "wall_s": 5.0}]
    costs, bad = rs.fast_set_costs(rows, ["a", "b", "zz"])
    assert costs == {"a": 2.0, "b": 5.0, "zz": None}
    assert bad == 0


def test_costs_malformed_rows_counted_never_fatal():
    rows = [{"scenario": "a", "wall_s": 2.0},
            "not-a-dict",
            {"scenario": None, "wall_s": 1.0},
            {"scenario": "a", "wall_s": -3},
            {"scenario": "a", "wall_s": True},
            {"scenario": "a"}]
    costs, bad = rs.fast_set_costs(rows, ["a"])
    assert costs == {"a": 2.0} and bad == 5


# ---- wall estimate -----------------------------------------------------------

def test_estimate_serial_sums_and_pole_vs_sum_over_width():
    entries = [("s", "i", "c", "ro", "serial", "fast"),
               ("p1", "i", "c", "ro", "fast"),
               ("p2", "i", "c", "ro", "fast")]
    costs = {"s": 30.0, "p1": 10.0, "p2": 7.0}
    est = rs.fast_set_wall_estimate(entries, costs, width=3)
    ro = est["pools"]["ro"]
    # concurrent: max(pole=10, (10+7)/3=5.67) = 10; + serial 30
    assert ro["serial_sum_s"] == 30.0 and ro["pole_s"] == 10.0
    assert ro["est_s"] == 40.0 and est["est_s"] == 40.0
    assert est["width"] == 3


def test_estimate_width_one_makes_conc_sum_the_pole_bound():
    entries = [("p1", "i", "c", "ro", "fast"), ("p2", "i", "c", "ro", "fast")]
    costs = {"p1": 10.0, "p2": 7.0}
    est = rs.fast_set_wall_estimate(entries, costs, width=1)
    assert est["pools"]["ro"]["est_s"] == 17.0


def test_estimate_unmeasured_counted_and_named():
    entries = [("p1", "i", "c", "ro", "fast"), ("p2", "i", "c", "ro", "fast")]
    est = rs.fast_set_wall_estimate(entries, {"p1": None, "p2": 4.0}, width=2)
    assert est["pools"]["ro"]["unmeasured"] == 1
    assert est["pools"]["ro"]["est_s"] == 4.0


def test_estimate_pools_run_in_parallel_max_not_sum():
    entries = [("a", "i", "c", "ro", "fast"), ("b", "i", "c", "main", "fast")]
    costs = {"a": 100.0, "b": 5.0}
    est = rs.fast_set_wall_estimate(entries, costs, width=3)
    assert est["est_s"] == 100.0


# ---- mode switch -------------------------------------------------------------

def test_mode_flag_wins_over_env():
    assert rs.fast_set_mode_enabled(False, {"SANDBAR_SCENARIO_FAST_SET": "1"}) is False
    assert rs.fast_set_mode_enabled(True, {"SANDBAR_SCENARIO_FAST_SET": ""}) is True


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("on", True), ("TRUE", True), ("yes", True),
    ("", False), ("0", False), ("off", False), ("garbage", False),
])
def test_mode_env_values(raw, expected):
    assert rs.fast_set_mode_enabled(None, {"SANDBAR_SCENARIO_FAST_SET": raw}) is expected


def test_mode_default_off():
    assert rs.fast_set_mode_enabled(None, {}) is False


# ---- strict roster reader (arbitrate gen0 rework: the booked-red refusal) -----

def _write_roster(tmp_path, entries):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps({"meta": {}, "entries": entries}), encoding="utf-8")
    return str(p)


def test_strict_reader_reads_valid_roster(tmp_path, monkeypatch):
    path = _write_roster(tmp_path, [
        {"name": "sc-a", "verdict": "booked"},
        {"name": "sc-b", "verdict": "isolated"},
        {"name": "sc-a", "verdict": "booked"},
    ])
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER", path)
    names, err = rs.read_known_red_roster_strict("/nonexistent-root")
    assert (names, err) == (["sc-a", "sc-b"], "")


def test_strict_reader_refuses_verdictless_member_entry(tmp_path, monkeypatch):
    # The arbitrated repro shape: a real member named WITHOUT a verdict.
    path = _write_roster(tmp_path, [
        {"name": "t260903-02-fork-contract", "owner": "arb",
         "retire_when": "never"}])
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER", path)
    names, err = rs.read_known_red_roster_strict("/nonexistent-root")
    assert names == [] and err != ""
    assert "t260903-02-fork-contract" in err


def test_strict_reader_refuses_non_object_and_nameless_entries(tmp_path, monkeypatch):
    path = _write_roster(tmp_path, ["not-a-dict", {"verdict": "booked"}])
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER", path)
    names, err = rs.read_known_red_roster_strict("/nonexistent-root")
    assert names == [] and "不可信" in err


def test_preflight_refuses_verdictless_member_end_to_end(tmp_path, monkeypatch):
    # Fast-set face + the repro roster: rc-face refusal naming member AND
    # roster — never a valid declaration with the booked-red member inside.
    path = _write_roster(tmp_path, [
        {"name": "m", "owner": "arb", "retire_when": "never"}])
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER", path)
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH.update({"m": "x"})
    try:
        got, errs = rs.fast_set_preflight(
            registry=[_one("m", "ro", "fast")])
        assert [e[0] for e in got] == ["m"] and len(errs) == 1
        assert "m" in errs[0] and "roster" in errs[0] and "known" in errs[0]
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


def test_preflight_refuses_properly_booked_member_by_name(tmp_path, monkeypatch):
    path = _write_roster(tmp_path, [{"name": "m", "verdict": "booked"}])
    monkeypatch.setenv("SANDBAR_KNOWN_RED_ROSTER", path)
    saved = dict(rs.FAST_SET_CATCH)
    rs.FAST_SET_CATCH.update({"m": "x"})
    try:
        _, errs = rs.fast_set_preflight(registry=[_one("m", "ro", "fast")])
        assert any("known-red roster" in e and "[m]" in e for e in errs)
    finally:
        rs.FAST_SET_CATCH.clear()
        rs.FAST_SET_CATCH.update(saved)


# ---- report landing dir declared ignored (arbitrate gen2 rework) --------------

def test_report_dir_ignore_file_created(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    assert rs._ensure_report_dir_ignored(d) is True
    assert (d / ".gitignore").read_text(encoding="utf-8") == "*\n"


def test_report_dir_ignore_idempotent(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    (d / ".gitignore").write_text("custom\n", encoding="utf-8")
    assert rs._ensure_report_dir_ignored(d) is True
    assert (d / ".gitignore").read_text(encoding="utf-8") == "custom\n", \
        "an existing declaration is never overwritten"


def test_report_dir_ignore_tolerates_unwritable(tmp_path):
    d = tmp_path / "not-a-dir"
    d.write_text("i am a file\n", encoding="utf-8")
    assert rs._ensure_report_dir_ignored(d) is False
