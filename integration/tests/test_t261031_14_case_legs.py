#!/usr/bin/env python3
"""t261031-14 — the structured failing-leg face of a run record's detail
(unit battery over the real integration/run_scenarios.py + scenario_ledger.py).

Covers (KI-439, the gap the ticket closes: a red case's retained evidence was
its log tail, so a round booked "SUMMARY pass=17 fail=12" and not one red leg
could be named from the record):
- the parser accepts the leg-row shapes this tree ACTUALLY prints (measured,
  not invented): `  FAIL <leg> — <reason>`, `  FAIL <leg>`, `  FAIL <leg>: <r>`,
  `[FAIL] <leg> — <r>`, column-0 `FAIL <text>`, `  ENV_FAIL <leg> — <r>`, and
  pytest's `FAILED <nodeid> - <r>`;
- a colon inside the leg name survives when the row also carries the em dash
  (the measured `P5/dark edited block: thread survives ...` label);
- the runner's own case verdict (`FAIL [<case>] exit=1 (12.3s)`) is NOT a leg
  row;
- NAMED outcomes on unusable input: `unrecognized` (no leg row, no agreeing
  summary) and `summary_only` (the SUMMARY counts fails, no leg row named
  them) — neither is a clean-looking empty list;
- the env shape: `env_fail` with its reason line, and no leg list;
- bounds: DETAIL_LEG_MAX legs, bounded name/reason/note, counted
  `legs_omitted`; malformed input never raises;
- the builder merges the pre-extracted block, falls back to the tail, keeps
  the t261026-15 pair untouched, and the result validates against the store;
- the store refuses the dishonest shapes BY NAME (empty parsed legs, legs on a
  non-parsed outcome, a missing note, an over-long leg, an unknown outcome,
  orphan leg keys) and keeps refusing an unrelated extra key.

Pure functions only (the modules are loaded via importlib, no entry is
executed — the developer-stage enforcement list is honoured); zero docker,
zero network, zero real ~/.sandbar contact.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load("rs_t261031_14_under_test", "integration/run_scenarios.py")
sl = _load("sl_t261031_14_under_test", "integration/scenario_ledger.py")

CASE = "t261022-14-review-panel-face"
COMMIT = "ab" * 20
FP = "cd" * 32

#: The measured incident shapes (t261022-14's own record() rows).
OUT = "\n".join([
    "dark matrix start",
    "  ok P1/dark md-click opens reviewer",
    "  ok P2/dark added blocks marked — added blocks: 3",
    "  FAIL P3/dark four block kinds persist to lane file — done=2 expected=4",
    "  FAIL P5/dark edited block: thread survives or is outdated — "
    "outdated=0 stillVisible=false",
    "  FAIL P9/dark rail collapse control",
    "[FAIL] inner-battery-completed — crashed before SUMMARY",
    "FAIL driver error: no such file",
    "  ENV_FAIL P10/dark capture — timeout 30000ms",
    "FAILED integration/tests/test_x.py::test_y - AssertionError: 1 != 2",
    "SUMMARY pass=17 fail=12 env_fail=0 na=0",
]) + "\n"


def red_spec(name=CASE, evidence=""):
    return {"name": name, "suite": "full", "status": "fail",
            "cause": "self", "reason": "assert_mismatch", "dur_s": 12.3,
            "attempt": 1, "started": "", "git_sha": "",
            "evidence": evidence, "artifacts": []}


def env_spec(name="env-case", evidence=""):
    return {"name": name, "suite": "full", "status": "not-checked",
            "cause": "external", "reason": "other", "dur_s": 3.0,
            "attempt": 1, "started": "", "git_sha": "",
            "evidence": evidence, "artifacts": []}


def green_spec(name="green-case"):
    c = red_spec(name)
    c["status"] = "pass"
    return c


def base_header(cases=None):
    counts = cases or {"ran": 1, "passed": 0, "failed": 1, "env_failed": 0}
    return {"v": sl.RUN_HEADER_V, "id": "run-" + "0" * 26,
            "repos": [{"repo": "sandbar", "revision": COMMIT}],
            "suite": "full", "source": "lane:test-line", "env_fp": FP,
            "conc_width": 1, "pool": "", "started_at": 1_800_000_000_000,
            "duration_s": 1.5, "cases": counts,
            "verdict": sl.run_verdict(counts)}


# ---------------- the leg-row shapes this tree prints ----------------

def test_measured_leg_rows_are_named():
    block = rs.parse_case_legs(OUT)
    assert block["legs_parse"] == "parsed"
    legs = {row["leg"]: row["reason"] for row in block["legs"]}
    assert legs["P3/dark four block kinds persist to lane file"] == \
        "done=2 expected=4"
    # a colon INSIDE the leg name must not be taken as the separator
    assert legs["P5/dark edited block: thread survives or is outdated"] == \
        "outdated=0 stillVisible=false"
    assert legs["P9/dark rail collapse control"]          # no reason text
    assert "inner-battery-completed" in legs              # [FAIL] row
    assert "driver error" in legs                         # column-0 FAIL row
    assert "P10/dark capture" in legs                     # ENV_FAIL leg row
    assert legs["P10/dark capture"].startswith("env: ")   # its cause is kept
    assert "integration/tests/test_x.py::test_y" in legs  # pytest row


def test_ok_rows_are_not_legs():
    block = rs.parse_case_legs("  ok P1/dark opens\n  ok P2/dark marks\n")
    assert block["legs_parse"] == "unrecognized"
    assert "legs" not in block


def test_summary_agreement_note():
    block = rs.parse_case_legs(OUT)          # 7 legs vs the SUMMARY's fail=12
    assert "fail=12" in block["legs_note"]


def test_runner_case_verdict_is_never_a_leg_row():
    out = ("FAIL [%s] exit=1 (12.3s)\n"
           "    assert healed == 1, observed 0\n" % CASE)
    block = rs.parse_case_legs(out)
    assert block["legs_parse"] == "unrecognized"
    assert "legs" not in block


# ---------------- named outcomes, never an empty list ----------------

@pytest.mark.parametrize("out,motive", [
    ("", "empty output"),
    (None, "not a string at all"),
    ("total nonsense\nno leg row here\n", "prose only"),
])
def test_unparseable_output_is_named(out, motive):
    block = rs.parse_case_legs(out)
    assert block["legs_parse"] == "unrecognized", motive
    assert isinstance(block["legs_note"], str) and block["legs_note"].strip()
    assert "legs" not in block


def test_summary_only_names_the_count_it_cannot_name_the_legs():
    block = rs.parse_case_legs("  ok a\n" * 5 +
                               "SUMMARY pass=17 fail=12 env_fail=0 na=0\n")
    assert block["legs_parse"] == "summary_only"
    assert "fail=12" in block["legs_note"]
    assert "legs" not in block


def test_env_shape_carries_its_reason_line():
    block = rs.parse_case_legs(
        "[ENV_FAIL] stage console unavailable: spawn ENOENT\n", env_like=True)
    assert block["legs_parse"] == "env_fail"
    assert "stage console unavailable" in block["legs_note"]
    assert "legs" not in block


def test_env_without_an_env_row_is_still_named():
    block = rs.parse_case_legs("traceback ...\nlast line\n", env_like=True)
    assert block["legs_parse"] == "env_fail"
    assert "no ENV_FAIL row" in block["legs_note"]


# ---------------- bounds ----------------

def test_leg_list_is_bounded_and_counts_what_it_omitted():
    out = "\n".join("  FAIL leg-%02d — reason %02d" % (i, i)
                    for i in range(sl.DETAIL_LEG_MAX + 6))
    block = rs.parse_case_legs(out)
    assert len(block["legs"]) == sl.DETAIL_LEG_MAX
    assert block["legs_omitted"] == 6


def test_name_and_reason_and_note_stay_bounded():
    out = ("  FAIL %s — %s\n" % ("L" * 400, "R" * 400)) + "x\n"
    block = rs.parse_case_legs(out)
    assert len(block["legs"][0]["leg"]) <= sl.DETAIL_LEG_NAME_CHARS
    assert len(block["legs"][0]["reason"]) <= sl.DETAIL_LEG_REASON_CHARS
    long_note = rs.parse_case_legs("x\n")["legs_note"]
    assert len(long_note) <= sl.DETAIL_LEG_NOTE_CHARS


def test_duplicate_leg_rows_collapse_to_one_entry():
    out = ("  FAIL leg-a\n"
           "  FAIL leg-a — the real reason\n")
    block = rs.parse_case_legs(out)
    assert len(block["legs"]) == 1
    assert block["legs"][0]["reason"] == "the real reason"


# ---------------- the builder merges the block ----------------

def test_builder_merges_the_pre_extracted_block():
    out = ("  FAIL leg-a — reason a\n" + "  ok noise\n" * 40
           + "SUMMARY pass=40 fail=1 env_fail=0 na=0\n")
    detail = rs.build_failed_detail(
        [red_spec()], [{"name": CASE, "tail": out[-1200:], "dur_s": 12.3,
                        "legs": rs.parse_case_legs(out)}])
    entry = detail[CASE]
    assert entry["legs_parse"] == "parsed"
    assert entry["legs"] == [{"leg": "leg-a", "reason": "reason a"}]
    assert entry["evidence"] == out[-1200:].strip()   # the tail still rides


def test_builder_falls_back_to_the_tail_when_no_block_was_measured():
    tail = "  FAIL leg-b — reason b\n"
    detail = rs.build_failed_detail([red_spec()],
                                    [{"name": CASE, "tail": tail}])
    assert detail[CASE]["legs"] == [{"leg": "leg-b", "reason": "reason b"}]


def test_builder_names_an_unreadable_tail():
    detail = rs.build_failed_detail([red_spec(evidence="prose only")], [])
    entry = detail[CASE]
    assert entry["legs_parse"] == "unrecognized"
    assert entry["legs_note"].strip()
    assert "legs" not in entry


def test_builder_keeps_the_t261026_15_pair_intact():
    detail = rs.build_failed_detail([red_spec()],
                                    [{"name": CASE, "tail": "  FAIL a — b\n"}])
    assert {"evidence", "dur_s"} <= set(detail[CASE])


def test_green_round_still_builds_nothing():
    assert rs.build_failed_detail(
        [green_spec()], [{"name": "green-case", "tail": "  ok a\n",
                          "legs": rs.parse_case_legs("  ok a\n")}]) == {}


def test_env_entry_rides_only_beside_a_content_red():
    specs = [env_spec()]
    timings = [{"name": "env-case", "tail": "  ENV_FAIL x — y\n",
                "legs": rs.parse_case_legs("  ENV_FAIL x — y\n",
                                           env_like=True)}]
    assert rs.build_failed_detail(specs, timings) == {}
    specs2 = [red_spec(), env_spec()]
    timings2 = [{"name": CASE, "tail": "  FAIL a — b\n",
                 "legs": rs.parse_case_legs("  FAIL a — b\n")},
                {"name": "env-case", "tail": "  ENV_FAIL x — y\n",
                 "legs": rs.parse_case_legs("  ENV_FAIL x — y\n",
                                            env_like=True)}]
    detail = rs.build_failed_detail(specs2, timings2)
    assert detail["env-case"]["legs_parse"] == "env_fail"
    assert detail[CASE]["legs_parse"] == "parsed"


def test_malformed_blocks_are_skipped_never_half_written():
    for block in (None, 3, "x", {}, {"legs_parse": "nope"},
                  {"legs_parse": "parsed", "legs": []}):
        detail = rs.build_failed_detail(
            [red_spec()], [{"name": CASE, "tail": "  FAIL a — b\n",
                            "legs": block}])
        entry = detail[CASE]
        # the fallback parse of the tail stands in: never a half shape
        assert entry["legs_parse"] == "parsed"
        assert entry["legs"] == [{"leg": "a", "reason": "b"}]


# ---------------- builder and store cannot drift apart ----------------

def _detail_from_out(out):
    return rs.build_failed_detail(
        [red_spec()], [{"name": CASE, "tail": out[-1200:],
                        "legs": rs.parse_case_legs(out)}])


@pytest.mark.parametrize("out", [
    OUT,
    "total nonsense\n",
    "SUMMARY pass=17 fail=12 env_fail=0 na=0\n  ok a\n",
    "\n".join("  FAIL leg-%02d — r" % i for i in range(30)),
])
def test_built_detail_validates_against_the_store(out):
    hdr = base_header()
    hdr["failed_detail"] = _detail_from_out(out)
    clean, why = sl.validate_run_header(hdr)
    assert why is None, why
    assert clean["failed_detail"][CASE]["legs_parse"] in \
        ("parsed", "summary_only", "unrecognized")


def _d(entry):
    return {CASE: entry}


@pytest.mark.parametrize("detail,why", [
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed"}),
     "failed_detail_legs_empty:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed", "legs": []}),
     "failed_detail_legs_empty:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "nope",
         "legs_note": "y"}), "failed_detail_legs_parse_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "unrecognized",
         "legs": [{"leg": "a", "reason": "b"}], "legs_note": "y"}),
     "failed_detail_legs_for_unparsed:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "unrecognized"}),
     "failed_detail_legs_note_missing:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "env_fail",
         "legs_note": "  "}), "failed_detail_legs_note_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs": []}),
     "failed_detail_legs_orphan:%s:legs" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a"}]}), "failed_detail_leg_row_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a", "reason": "b", "extra": 1}]}),
     "failed_detail_leg_row_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": " ", "reason": "b"}]}),
     "failed_detail_leg_name_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a", "reason": ""}]}),
     "failed_detail_leg_reason_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a" * (sl.DETAIL_LEG_NAME_CHARS + 1),
                   "reason": "b"}]}),
     "failed_detail_leg_name_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a", "reason": "b"}],
         "legs_omitted": True}), "failed_detail_legs_omitted_invalid:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "l%d" % i, "reason": "b"}
                  for i in range(sl.DETAIL_LEG_MAX + 1)]}),
     "failed_detail_legs_too_many:%s" % CASE),
    (_d({"evidence": "x", "dur_s": None, "legs_parse": "parsed",
         "legs": [{"leg": "a", "reason": "b"}], "extra": 1}),
     "failed_detail_entry_invalid:%s" % CASE),
])
def test_store_refuses_the_dishonest_shapes_by_name(detail, why):
    hdr = base_header()
    hdr["failed_detail"] = detail
    clean, got = sl.validate_run_header(hdr)
    assert clean is None and got == why


def test_store_accepts_the_lawful_shapes():
    for entry in (
            {"evidence": "x", "dur_s": None,
             "legs_parse": "parsed",
             "legs": [{"leg": "a", "reason": "b"}], "legs_omitted": 2},
            {"evidence": "x", "dur_s": None, "legs_parse": "unrecognized",
             "legs_note": "no leg row in 3 lines"},
            {"evidence": "x", "dur_s": None, "legs_parse": "env_fail",
             "legs_note": "playwright-core not resolvable"},
            {"evidence": "x", "dur_s": None},          # the t261026-15 shape
    ):
        hdr = base_header()
        hdr["failed_detail"] = _d(entry)
        clean, why = sl.validate_run_header(hdr)
        assert why is None, (entry, why)


def test_leg_parse_outcome_vocabulary_is_closed():
    assert sl.DETAIL_LEG_PARSE_OUTCOMES == ("parsed", "summary_only",
                                           "unrecognized", "env_fail")
    assert sl.DETAIL_ENTRY_OPTIONAL_LEG_FIELDS == (
        "legs_parse", "legs", "legs_note", "legs_omitted")
    assert sl.DETAIL_LEG_MAX == 16
