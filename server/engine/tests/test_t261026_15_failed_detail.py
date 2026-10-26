#!/usr/bin/env python3
"""t261026-15 — the run header's additive ``failed_detail`` field (validator
truth tables over the real integration/scenario_ledger.py).

Covers (acceptance lines 2+3, the store half):
- the additive-optional precedent (t261011-25 prelude pair): absent key = a
  valid header, no version bump, unknown-field refusal untouched;
- a well-formed failed_detail on a red header validates and round-trips the
  persisted line (_dumps / read back from the file);
- the shape matrix, one fact per refusal: non-dict / empty map on green /
  non-str or empty case key / entry not exactly {evidence, dur_s} / empty
  evidence / evidence over the 1200-char bound / dur_s bool, string, negative;
- the reserved ``__truncated__`` key is lawful ONLY as the counted truncation
  marker (a real case riding that name refuses: collision guard, review
  comment 2);
- failed_detail on a GREEN header refuses (failed_detail_on_green) — a green
  round never carries per-case tails (acceptance line 2);
- a red header WITHOUT the key stays valid (honest absence is lawful — writers
  predating the field).

Whole battery pure over the module face; zero docker, zero network, zero
real ~/.sandbar contact (the one persistence case pins
SANDBAR_SCENARIO_LEDGER_DIR at a tmp dir). This file never executes an
integration entry (developer-stage enforcement list honoured).
"""
import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MOD = REPO / "integration" / "scenario_ledger.py"

_spec = importlib.util.spec_from_file_location("sl_t261026_15_under_test", MOD)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)

COMMIT = "ab" * 20
FP = "cd" * 32


def base_header(cases=None, verdict=None):
    counts = cases or {"ran": 1, "passed": 0, "failed": 1, "env_failed": 0}
    return {
        "v": sl.RUN_HEADER_V,
        "id": "run-" + "0" * 26,
        "repos": [{"repo": "sandbar", "revision": COMMIT}],
        "suite": "full",
        "source": "lane:test-line",
        "env_fp": FP,
        "conc_width": 1,
        "pool": "",
        "started_at": 1_800_000_000_000,
        "duration_s": 1.5,
        "cases": counts,
        "verdict": verdict or sl.run_verdict(counts),
    }


GOOD_DETAIL = {
    "t260904-04-stale-cache-heal-journey": {
        "evidence": "FAIL [t260904-04-stale-cache-heal-journey] exit=1\n"
                    "    assert refreshed == 1, observed 0",
        "dur_s": 12.3,
    }
}


# ---------------- absence stays valid (no version bump) ----------------

def test_absent_key_is_valid_on_red_and_green():
    red = base_header()
    clean, why = sl.validate_run_header(red)
    assert why is None and clean is not None
    green = base_header({"ran": 1, "passed": 1, "failed": 0, "env_failed": 0})
    clean, why = sl.validate_run_header(green)
    assert why is None and clean is not None


def test_unknown_field_refusal_untouched():
    hdr = base_header()
    hdr["some_future_key"] = 1
    clean, why = sl.validate_run_header(hdr)
    assert clean is None and why == "unknown_fields:some_future_key"


def test_constants_and_bounds_exist():
    assert sl.DETAIL_TAIL_CHARS == 1200
    assert sl.DETAIL_MAX_CASES == 20
    assert sl.DETAIL_TRUNCATED_KEY == "__truncated__"
    assert sl.RUN_HEADER_OPTIONAL_DETAIL_FIELDS == ("failed_detail",)
    assert sl.RUN_HEADER_V == "run-ledger-v1"   # no version bump


# ---------------- well-formed detail ----------------

def test_wellformed_detail_on_red_validates_and_roundtrips():
    hdr = base_header()
    hdr["failed_detail"] = GOOD_DETAIL
    clean, why = sl.validate_run_header(hdr)
    assert why is None
    assert clean["failed_detail"] == GOOD_DETAIL
    # persisted-line round trip through the real dump face
    line = sl._dumps(clean)
    assert json.loads(line)["failed_detail"] == GOOD_DETAIL


def test_marker_entry_validates():
    hdr = base_header()
    hdr["failed_detail"] = {"__truncated__": {
        "evidence": "3 more failing case tails omitted (bound 20)",
        "dur_s": None}}
    clean, why = sl.validate_run_header(hdr)
    assert why is None and clean is not None


def test_red_without_key_stays_valid():
    hdr = base_header()
    hdr["failed_names"] = ["x"]      # extra keys are refused, so use none
    clean, why = sl.validate_run_header(hdr)
    assert why == "unknown_fields:failed_names"   # relayed key stays runner-side
    clean, why = sl.validate_run_header(base_header())
    assert why is None   # plain red without detail: honest absence


# ---------------- the shape matrix (one fact per refusal) ----------------

@pytest.mark.parametrize("detail,why", [
    (None, "failed_detail_not_object"),
    ([], "failed_detail_not_object"),
    ("x", "failed_detail_not_object"),
    ({}, "failed_detail_not_object"),
    ({"": {"evidence": "x", "dur_s": None}}, "failed_detail_key_invalid"),
    ({"  ": {"evidence": "x", "dur_s": None}}, "failed_detail_key_invalid"),
    ({"case": "x"}, "failed_detail_entry_invalid:case"),
    ({"case": {"evidence": "x"}}, "failed_detail_entry_invalid:case"),
    ({"case": {"evidence": "x", "dur_s": None, "extra": 1}},
     "failed_detail_entry_invalid:case"),
    ({"case": {"evidence": "  ", "dur_s": None}},
     "failed_detail_evidence_invalid:case"),
    ({"case": {"evidence": "x" * 1201, "dur_s": None}},
     "failed_detail_evidence_invalid:case"),
    ({"case": {"evidence": "x", "dur_s": True}},
     "failed_detail_dur_s_invalid:case"),
    ({"case": {"evidence": "x", "dur_s": "3"}},
     "failed_detail_dur_s_invalid:case"),
    ({"case": {"evidence": "x", "dur_s": -1}},
     "failed_detail_dur_s_invalid:case"),
    ({"__truncated__": {"evidence": "assert real case", "dur_s": None}},
     "failed_detail_reserved_key:__truncated__"),
])
def test_malformed_detail_refused_by_name(detail, why):
    hdr = base_header()
    hdr["failed_detail"] = detail
    clean, got = sl.validate_run_header(hdr)
    assert clean is None and got == why


def test_evidence_at_exact_bound_is_valid():
    hdr = base_header()
    hdr["failed_detail"] = {"case": {"evidence": "x" * 1200, "dur_s": None}}
    clean, why = sl.validate_run_header(hdr)
    assert why is None and clean is not None


# ---------------- green never carries tails (acceptance line 2) ----------------

def test_failed_detail_on_green_refused():
    hdr = base_header({"ran": 1, "passed": 1, "failed": 0, "env_failed": 0})
    hdr["failed_detail"] = GOOD_DETAIL
    clean, why = sl.validate_run_header(hdr)
    assert clean is None and why == "failed_detail_on_green"


def test_env_only_round_may_not_carry_content_detail():
    # failed == 0 means content green: the detail face is content-red only
    hdr = base_header({"ran": 2, "passed": 1, "failed": 0, "env_failed": 1})
    hdr["failed_detail"] = GOOD_DETAIL
    clean, why = sl.validate_run_header(hdr)
    assert clean is None and why == "failed_detail_on_green"


# ---------------- one persistence leg through the write face ----------------

def test_append_run_header_persists_detail_to_the_file():
    with tempfile.TemporaryDirectory() as td:
        old = os.environ.get(sl.LEDGER_DIR_ENV)
        os.environ[sl.LEDGER_DIR_ENV] = td
        try:
            rows = [{
                "ts": "2026-06-01T00:00:00+00:00", "commit": COMMIT,
                "env_fp": FP, "conc_width": 1, "pool": "",
                "scenario": "t260904-04-stale-cache-heal-journey",
                "verdict": "fail", "wall_s": 12.3, "source": "lane:test-line",
                "ticket": "test-line", "run": base_header()["id"],
            }]
            r = sl.append_records(rows)
            assert r["written"] == 1, r
            hdr = base_header()
            hdr["failed_detail"] = GOOD_DETAIL
            hr = sl.append_run_header(hdr)
            assert hr["written"] == 1, hr
            # reader-side: the FILE carries the detail verbatim
            headers, bad = sl.read_runs(sl.runs_path())
            assert not bad
            assert headers[0]["failed_detail"] == GOOD_DETAIL
            # and a green header with the key is refused at the write face too
            green = base_header({"ran": 1, "passed": 1, "failed": 0,
                                 "env_failed": 0})
            green["id"] = "run-" + "1" * 26
            green["failed_detail"] = GOOD_DETAIL
            rows2 = [dict(rows[0], scenario="other", verdict="pass",
                          run=green["id"])]
            assert sl.append_records(rows2)["written"] == 1
            hr2 = sl.append_run_header(green)
            assert hr2["written"] == 0
            assert hr2["rejected"][0]["reason"] == "failed_detail_on_green"
        finally:
            if old is None:
                os.environ.pop(sl.LEDGER_DIR_ENV, None)
            else:
                os.environ[sl.LEDGER_DIR_ENV] = old
