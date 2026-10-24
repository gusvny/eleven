#!/usr/bin/env python3
"""t261024-60 L1: the ticket's OWN scenarios never enter the ledger-reuse face.

Incident (measured on the live lanes, promoted head 61a64f58): the t260930-01
green-row reuse plan consumed the pointed OWN scenarios (t261022-12
`ran=0 reused=2`, t261022-14 `ran=0 reused=3` repeatedly) — a green ledger row
is a scheduling optimization, but for the ticket's own proof obligation it
acted as a drop reason: nothing ran, KI-220 minted no green face on the current
head, and every landing was refused.

Covers:
- A the helper truth table: own names move reuse -> own_rerun (they run for
  real), non-own reuse semantics byte-identical; the UNCHANGED-HEAD re-run row
  (same seeded green row, second call) stays deterministic — the helper is pure,
  so the second call returns the same split and the own name still runs;
- B the ran+reused==expected invariant after the split: own names count in
  `ran`, never in `reused`, never both;
- C empty/absent own set = the old behavior byte-identically (reused unchanged,
  own_rerun empty);
- D source locks: the run-path call site actually applies the split (reuse
  names are post-filtered), the stderr face (INTEG_OWN_RERUN, parseable, never
  `FAIL [`-prefixed) and the additive only_plan.own_rerun key are wired;
- E malformed ledger rows stay outside this change: reusable_names skips them
  (pre-existing discipline), and own_exempt_reuse never invents names.

Pure-function battery over the real module (importlib load, registry build only,
nothing runs) plus source locks — zero docker/Temporal/browser/3099/7233.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "rs_own_reuse_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


# ---------- A: the helper truth table (incl. the unchanged-head re-run) ------

def test_own_names_move_from_reuse_to_own_rerun():
    reused, own_rerun = rs.own_exempt_reuse(
        ["own-a", "plain-b", "own-c"], {"own-a", "own-c"})
    assert reused == ["plain-b"]
    assert own_rerun == ["own-a", "own-c"]      # sorted, named, never dropped


def test_unchanged_head_second_call_is_deterministic():
    # the flip-flop shape: same green row, same head+env_fp — the second gate
    # round must split identically, so the own scenario runs AGAIN (for real)
    # instead of being reused away like the live incident rounds.
    first = rs.own_exempt_reuse(["own-a", "plain-b"], {"own-a"})
    second = rs.own_exempt_reuse(["own-a", "plain-b"], {"own-a"})
    assert first == second == (["plain-b"], ["own-a"])


def test_non_string_names_are_coerced_not_crashed():
    reused, own_rerun = rs.own_exempt_reuse([1, "own-2"], {"own-2"})
    assert reused == ["1"]
    assert own_rerun == ["own-2"]


def test_none_inputs_behave_as_empty():
    assert rs.own_exempt_reuse(None, None) == ([], [])


# ---------- B: the ran + reused == expected invariant ------------------------

def test_invariant_ran_plus_reused_equals_expected():
    # expected = the pointed registry before reuse removal (single-point, the
    # t260930-01 rule). After the split: reused entries leave the registry,
    # own_rerun entries STAY (they run) => ran = expected - reused, i.e.
    # ran + reused == expected, and own_rerun is a subset of ran — never
    # double-counted as reused.
    expected = ["own-a", "plain-b", "plain-c"]
    reused, own_rerun = rs.own_exempt_reuse(expected, {"own-a"})
    ran = [n for n in expected if n not in reused]
    assert len(ran) + len(reused) == len(expected)
    assert set(own_rerun) <= set(ran)
    assert not (set(own_rerun) & set(reused))


# ---------- C: empty own set = byte-identical old behavior -------------------

def test_empty_own_set_keeps_old_semantics():
    names = ["a", "b"]
    assert rs.own_exempt_reuse(names, set()) == (names, [])
    assert rs.own_exempt_reuse(names, None) == (names, [])


# ---------- D: source locks — the run path applies the split -----------------

def _src():
    return (REPO / "integration" / "run_scenarios.py").read_text(encoding="utf-8")


def test_call_site_applies_the_split():
    src = _src()
    assert '_reuse["names"], own_rerun = own_exempt_reuse(_reuse["names"], own_set)' in src


def test_stderr_face_named_and_parseable():
    src = _src()
    assert "INTEG_OWN_RERUN" in src
    # output shape is contract (t261001-10): the face must never start with
    # `FAIL [` and must name the count + the names on one flushable line.
    lines = src.splitlines()
    idx = [i for i, ln in enumerate(lines)
           if "INTEG_OWN_RERUN" in ln and "print(" in ln][0]
    stmt = "\n".join(lines[idx:idx + 5])   # the print spans two source lines
    assert "FAIL [" not in stmt
    # the printed face carries the count and the names via own_rerun
    assert "len(own_rerun)" in stmt


def test_receipt_carries_the_additive_own_rerun_key():
    src = _src()
    assert '"own_rerun": list(own_rerun)' in src


# ---------- E: malformed-ledger discipline untouched -------------------------

def test_reusable_names_still_skips_malformed_rows():
    # pre-existing discipline (t260930-01): malformed rows are skipped per row,
    # never crash the plan; own_exempt_reuse sits strictly AFTER that read.
    rows = [
        {"scenario": "own-a", "commit": "h", "env_fp": "f", "conc_width": 1,
         "verdict": "pass"},                      # well-formed green row
        {"garbage": True},                        # malformed -> skipped
        {"scenario": "own-a", "commit": "h", "env_fp": "f", "conc_width": 1,
         "verdict": "fail"},                      # non-green -> not reusable
        "not-a-dict",                             # junk row -> skipped
    ]
    try:
        names = rs.reusable_names(rows, "h", "f", 1, candidates={"own-a"})
    except Exception as e:  # noqa: BLE001 - a raise must at least be named here
        pytest.fail("reusable_names raised on a malformed row: %r" % (e,))
    assert names == ["own-a"]
    reused, own_rerun = rs.own_exempt_reuse(names, {"own-a"})
    assert reused == [] and own_rerun == ["own-a"]
