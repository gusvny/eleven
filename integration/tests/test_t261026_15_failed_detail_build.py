#!/usr/bin/env python3
"""t261026-15 — build_failed_detail / build_run_header wiring (integration
side unit battery over the real integration/run_scenarios.py helpers).

Covers (acceptance lines 1-3, the builder half):
- ACCEPTANCE 1: a planted red case's detail carries the failing assertion
  line and the observed value VERBATIM (fixed stub strings — no external
  source, no re-run);
- evidence provenance: the timings tail wins, the spec row's ``evidence`` is
  the fallback; ``dur_s`` from the timings row, else the spec row, else None
  (never a guessed 0 — review comment 3);
- ACCEPTANCE 3: the size bound — a case whose tail is megabytes contributes
  exactly the last 1200 chars, never its whole log; more than 20 reds
  truncate to the first 20 sorted names plus ONE counted ``__truncated__``
  marker whose note names the omitted count;
- the reserved-name collision guard: a real red actually named
  ``__truncated__`` is rerouted into the truncation note, never emitted as a
  case key (review comment 2);
- ACCEPTANCE 2: green spec rows build {} and ``build_run_header`` then omits
  the key entirely (absence, never an empty map);
- malformed input: non-dict rows, missing/empty names, non-str tails, bool
  dur_s are skipped by name, never raise;
- the header with the built detail validates against the real store face
  (builder and store cannot drift apart silently).

Pure functions only; the run_scenarios module is loaded via importlib (no
entry execution — developer-stage enforcement list honoured); zero docker,
zero network, zero real ~/.sandbar contact.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "integration" / "run_scenarios.py"

_spec = importlib.util.spec_from_file_location("rs_t261026_15_under_test", MOD)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

CASE = "t260904-04-stale-cache-heal-journey"
ASSERTION = "assert healed == 1, observed 0"
TAIL = ("FAIL [%s] exit=1 (12.3s)\n" % CASE
        + "    " + ASSERTION + "\n"
        + "E           assert 0 == 1\n"
        + "E            +  where 0 = healed_value")


def red_spec(name=CASE, evidence=""):
    return {"name": name, "suite": "full", "status": "fail",
            "cause": "unknown", "reason": "", "dur_s": 12.3, "attempt": 1,
            "started": "", "git_sha": "", "evidence": evidence,
            "artifacts": []}


def green_spec(name="green-case"):
    s = red_spec(name)
    s["status"] = "pass"
    return s


# ---------------- acceptance 1: verbatim assertion + observed value ----------------

def test_planted_red_carries_assertion_and_observed_value_verbatim():
    detail = rs.build_failed_detail([red_spec()], [{"name": CASE, "tail": TAIL,
                                                   "dur_s": 12.3}])
    assert set(detail) == {CASE}
    entry = detail[CASE]
    assert ASSERTION in entry["evidence"]
    assert "observed 0" in entry["evidence"]      # the observed value, verbatim
    assert entry["evidence"] == TAIL.strip()      # verbatim, only stripped
    assert entry["dur_s"] == 12.3


def test_timings_tail_wins_over_spec_evidence():
    detail = rs.build_failed_detail(
        [red_spec(evidence="spec-side evidence")],
        [{"name": CASE, "tail": "timing-side tail", "dur_s": 1.0}])
    assert detail[CASE]["evidence"] == "timing-side tail"


def test_spec_evidence_is_the_fallback_dur_from_spec_row():
    detail = rs.build_failed_detail([red_spec(evidence="spec-side evidence")],
                                    [])
    assert detail[CASE]["evidence"] == "spec-side evidence"
    assert detail[CASE]["dur_s"] == 12.3


def test_dur_s_falls_back_to_none_never_zero():
    spec = red_spec()
    spec["dur_s"] = None
    detail = rs.build_failed_detail([spec], [{"name": CASE, "tail": "t"}])
    assert detail[CASE]["dur_s"] is None
    spec2 = red_spec()
    spec2["dur_s"] = 12.3
    detail2 = rs.build_failed_detail(
        [spec2], [{"name": CASE, "tail": "t", "dur_s": True}])  # bool = no
    assert detail2[CASE]["dur_s"] == 12.3


def test_env_fail_never_enters_the_content_detail():
    spec = red_spec()
    spec["status"] = "not-checked"
    assert rs.build_failed_detail([spec], [{"name": CASE, "tail": "t"}]) == {}


def test_green_round_builds_empty_and_header_omits_the_key():
    detail = rs.build_failed_detail([green_spec()],
                                    [{"name": "green-case", "tail": "x"}])
    assert detail == {}
    hdr = rs.build_run_header(
        "run-" + "0" * 26, "ab" * 20, "cd" * 32, 1, "", "lane:t",
        1_800_000_000_000, 1.0,
        {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0},
        failed_detail=detail)
    assert "failed_detail" not in hdr


# ---------------- acceptance 3: the size bound ----------------

def test_megabyte_tail_contributes_only_the_bounded_last_chars():
    huge = ("x" * 1_000_000) + "\n" + TAIL
    detail = rs.build_failed_detail([red_spec()],
                                    [{"name": CASE, "tail": huge,
                                      "dur_s": 1.0}])
    evidence = detail[CASE]["evidence"]
    assert len(evidence) <= 1200
    assert evidence.endswith(TAIL.strip())   # the assertion survives at the end


def test_more_than_twenty_reds_truncate_with_counted_marker():
    specs, timings = [], []
    for i in range(25):
        name = "case-%02d" % i
        specs.append(red_spec(name))
        timings.append({"name": name, "tail": "tail-%02d" % i, "dur_s": 1.0})
    detail = rs.build_failed_detail(specs, timings)
    assert len(detail) == 21   # 20 cases + the marker
    assert list(detail)[:20] == sorted("case-%02d" % i for i in range(20))
    assert "case-19" in detail and "case-20" not in detail
    marker = detail["__truncated__"]
    assert "5 more failing case tails omitted (bound 20)" in marker["evidence"]
    assert marker["dur_s"] is None


def test_sorted_names_deterministic_output():
    specs = [red_spec("b"), red_spec("a")]
    timings = [{"name": "b", "tail": "tb"}, {"name": "a", "tail": "ta"}]
    assert list(rs.build_failed_detail(specs, timings)) == ["a", "b"]


def test_reserved_name_rerouted_into_truncation_note():
    specs = [red_spec("__truncated__"), red_spec("real-case")]
    timings = [{"name": "__truncated__", "tail": "oops"},
               {"name": "real-case", "tail": "fine"}]
    detail = rs.build_failed_detail(specs, timings)
    assert set(detail) == {"real-case", "__truncated__"}
    assert detail["real-case"]["evidence"] == "fine"
    assert ("1 more failing case tails omitted (bound 20)"
            in detail["__truncated__"]["evidence"])


# ---------------- malformed input battery ----------------

@pytest.mark.parametrize("specs,timings", [
    (None, None),
    ([None], [None]),
    (["nope"], [42]),
    ([{"status": "fail"}], [{"name": CASE}]),          # missing name / no tail
    ([{"name": "  ", "status": "fail"}], []),          # blank name
    ([{"name": CASE, "status": "fail", "evidence": 5}], [{"name": CASE,
                                                          "tail": 7}]),
    ([{"name": CASE, "status": "fail", "dur_s": True}], [{"name": CASE,
                                                          "tail": "t",
                                                          "dur_s": "x"}]),
])
def test_malformed_rows_skipped_never_raise(specs, timings):
    detail = rs.build_failed_detail(specs, timings)
    assert isinstance(detail, dict)
    for k, v in detail.items():
        assert set(v) == {"evidence", "dur_s"}
        assert isinstance(v["evidence"], str) and len(v["evidence"]) <= 1200


def test_bare_case_without_any_tail_is_honestly_absent():
    detail = rs.build_failed_detail([red_spec(evidence="")], [])
    assert detail == {}


# ---------------- builder and store cannot drift ----------------

def test_built_header_validates_against_the_real_store():
    spec = importlib.util.spec_from_file_location(
        "sl_t261026_15_builder_check",
        REPO / "integration" / "scenario_ledger.py")
    sl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sl)
    specs = [red_spec()] + [green_spec()]
    timings = [{"name": CASE, "tail": TAIL, "dur_s": 12.3}]
    hdr = rs.build_run_header(
        "run-" + "0" * 26, "ab" * 20, "cd" * 32, 1, "", "lane:t",
        1_800_000_000_000, 9.0,
        {"ran": 2, "passed": 1, "failed": 1, "env_failed": 0},
        failed_detail=rs.build_failed_detail(specs, timings))
    clean, why = sl.validate_run_header(hdr)
    assert why is None, why
    assert clean["failed_detail"][CASE]["evidence"] == TAIL.strip()
