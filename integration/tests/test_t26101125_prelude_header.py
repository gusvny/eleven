#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-25 prelude-on-the-receipt — unit battery.

Covers:
- ``scenario_ledger.validate_run_header``: the additive OPTIONAL prelude pair
  (``prelude_s`` / ``prelude_legs``) — absent = valid (legacy headers stay
  readable, byte-for-byte the same accept set as before); present = measured
  (number >= 0, bool excluded); malformed = named refusal (negative, bool,
  string, legs not an object, legs entry malformed, unknown extra key still
  refused);
- ``run_scenarios.build_run_header``: the pair rides onto the header only when
  measured; an unmeasured call produces a header IDENTICAL in keys to the
  pre-ticket shape (absence, never a fabricated 0); legs are sanitized
  (non-numeric/negative legs dropped, valid ones rounded);
- a valid header with the pair round-trips the store's validator (the clean
  copy keeps the values verbatim).

Offline seconds, zero docker/Temporal/network, temp ledger dir only. This file
never executes an integration entry (developer-stage enforcement honoured).
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sl = _load("sl_t1125_under_test", "integration/scenario_ledger.py")
rs = _load("rs_t1125_under_test", "integration/run_scenarios.py")

COMMIT = "ab" * 20
FP = "cd" * 32
AT_MS = 1791506200000


def _base_header():
    counts = {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0}
    return rs.build_run_header(
        "run-test0000000000000000000", COMMIT, FP, 3, "", "baseline",
        AT_MS, 12.5, counts)


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(sl.LEDGER_DIR_ENV, str(d))
    return d


# ---- the pre-ticket shape is untouched: no pair, fully valid ----

def test_header_without_prelude_valid_and_key_identical():
    hdr = _base_header()
    clean, why = sl.validate_run_header(hdr)
    assert why is None
    assert "prelude_s" not in clean
    assert "prelude_legs" not in clean
    assert set(clean) == set(sl.RUN_HEADER_FIELDS)


# ---- present-and-measured = valid, values survive the clean copy ----

def test_header_with_prelude_pair_valid():
    hdr = _base_header()
    hdr["prelude_s"] = 31.42
    hdr["prelude_legs"] = {"stage_sweep_s": 1.5, "docker_hygiene_s": 0.25,
                           "batch_preboot_s": 29.67}
    clean, why = sl.validate_run_header(hdr)
    assert why is None, why
    assert clean["prelude_s"] == 31.42
    assert clean["prelude_legs"]["batch_preboot_s"] == 29.67


def test_header_with_prelude_s_only_valid():
    hdr = _base_header()
    hdr["prelude_s"] = 0
    clean, why = sl.validate_run_header(hdr)
    assert why is None, why
    assert clean["prelude_s"] == 0


# ---- malformed pair = named refusal (the malformed-input matrix) ----

@pytest.mark.parametrize("bad", [-0.5, -1, True, False, "3.0", None, [3.0]])
def test_bad_prelude_s_refused_by_name(bad):
    hdr = _base_header()
    hdr["prelude_s"] = bad
    clean, why = sl.validate_run_header(hdr)
    assert clean is None
    assert why == "prelude_s_not_nonnegative_number"


def test_legs_not_object_refused():
    hdr = _base_header()
    hdr["prelude_legs"] = [1, 2]
    clean, why = sl.validate_run_header(hdr)
    assert clean is None
    assert why == "prelude_legs_not_object"


@pytest.mark.parametrize("legs", [{"s": -1}, {"s": True}, {"s": "x"},
                                  {1: 2.0}, {"s": None}])
def test_bad_leg_entry_refused_by_name(legs):
    hdr = _base_header()
    hdr["prelude_legs"] = legs
    clean, why = sl.validate_run_header(hdr)
    assert clean is None
    assert why.startswith("prelude_legs_entry_invalid")


def test_unknown_extra_key_still_refused():
    hdr = _base_header()
    hdr["something_else"] = 1
    clean, why = sl.validate_run_header(hdr)
    assert clean is None
    assert why.startswith("unknown_fields:")


# ---- builder: measured rides, unmeasured stays absent, legs sanitized ----

def test_builder_carries_measured_prelude():
    hdr = rs.build_run_header(
        "run-test0000000000000000000", COMMIT, FP, 3, "", "baseline",
        AT_MS, 12.5, {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0},
        prelude_s=30.123456,
        prelude_legs={"stage_sweep_s": 1.23456, "docker_hygiene_s": 0.5,
                      "batch_preboot_s": 28.4, "junk": "x", "neg": -1.0,
                      "flag": True})
    assert hdr["prelude_s"] == 30.123
    assert hdr["prelude_legs"] == {"stage_sweep_s": 1.235,
                                   "docker_hygiene_s": 0.5,
                                   "batch_preboot_s": 28.4}
    clean, why = sl.validate_run_header(hdr)
    assert why is None, why


def test_builder_without_prelude_matches_legacy_keys():
    hdr = _base_header()
    assert "prelude_s" not in hdr and "prelude_legs" not in hdr
    clean, why = sl.validate_run_header(hdr)
    assert why is None and set(clean) == set(sl.RUN_HEADER_FIELDS)


# ---- full store round-trip on a temp ledger (legacy headers still read) ----

def test_store_round_trip_with_and_without_pair(tmp_path):
    run_a = "run-aaaaaaaaaaaaaaaaaaaaaaaaaa"
    run_b = "run-bbbbbbbbbbbbbbbbbbbbbbbbbb"
    rows = [
        {"ts": "2026-06-09T00:00:00+00:00", "commit": COMMIT, "env_fp": FP,
         "conc_width": 3, "pool": "ro", "scenario": "s1", "verdict": "pass",
         "wall_s": 1.0, "source": "baseline", "ticket": "", "run": run_a},
        {"ts": "2026-06-09T00:00:01+00:00", "commit": COMMIT, "env_fp": FP,
         "conc_width": 3, "pool": "ro", "scenario": "s2", "verdict": "pass",
         "wall_s": 1.0, "source": "baseline", "ticket": "", "run": run_b},
    ]
    counts = {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0}
    hdr_a = rs.build_run_header(run_a, COMMIT, FP, 3, "", "baseline",
                                AT_MS, 12.5, counts)
    h2 = rs.build_run_header(run_b, COMMIT, FP, 3, "", "baseline",
                             AT_MS, 12.5, counts)
    h2["prelude_s"] = 9.0
    h2["prelude_legs"] = {"stage_sweep_s": 9.0}
    rr = sl.append_records(rows)
    assert rr.get("written") == 2, rr
    for h in (hdr_a, h2):
        res = sl.append_run_header(dict(h))
        assert res.get("written") == 1, res
    back, bad = sl.read_runs(path=sl.runs_path())
    assert not bad, bad
    assert len(back) == 2
    assert "prelude_s" not in back[0]
    assert back[1]["prelude_s"] == 9.0
    assert back[1]["prelude_legs"] == {"stage_sweep_s": 9.0}
