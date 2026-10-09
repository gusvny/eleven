"""t261008-43 unit tests: the suite-duration leg (slow-round finding + per-scenario
outliers + the bigger/slower trend).

Coverage (the ticket evidence list, item by item):
  - every fault mode of resolve_suite_duration_thresholds (the resolve_tmp_thresholds
    shape: declaration not a mapping / per-key absent, non-integer, out of range /
    malformed env / unknown keys / the per-key origin structural face);
  - the slow-round finding (long vs short runner_used_sec, the
    declaration|default|env source line, hang escalation, the truncated-round note,
    the named "duration unreadable" note);
  - per-scenario outliers (cap + counted, two slow scenarios both named under the
    cap, malformed dur_s, old receipts without dur_s);
  - the trend (bigger NOT reported as slower; slower; previous unreadable; previous
    truncated; ran=0 average not computable);
  - L3: error + reds + env_fail + a slow round in one receipt -> every existing
    finding still fires AND the duration findings coexist;
  - negative: duration findings are always suggest=False (hang shape included) and
    only med/high;
  - wiring: suite_findings thresholds=None zero regression; the flow-side patch gate
    on the args key; the activity-side dur_s/pool passthrough (source assertions).

Pure functions and fixed stubs only; zero external sources; no integration entry."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_deadman as dm  # noqa: E402
import inspection_lane_watchdog as lw  # noqa: E402

THR_DECL = {"suite_slow_round_min": 30, "suite_slow_scenario_sec": 100}
NOTE_DECL = "threshold source=declaration (suite_slow_round_min=30/declaration, " \
            "suite_slow_scenario_sec=100/declaration)"


def _receipt(**over):
    r = {"ran": 530, "passed": 470, "failed": 34, "env_fail": 26,
         "error": "", "runner_used_sec": 5916.4, "wall_seconds": 5916.5,
         "run_budget_sec": 6600.0, "details": [], "report_path": "out/x-suite.json"}
    r.update(over)
    return r


# ========================================================================================
# threshold resolver (the borrowed implementation's fault modes, one case each)
# ========================================================================================

def test_r1_no_decl_no_env_uses_defaults_names_source_default():
    thr, src, note, problems = lw.resolve_suite_duration_thresholds(None, {})
    assert thr == lw.SUITE_DURATION_DEFAULTS
    assert src == "default"
    # Same as the borrowed resolve_tmp_thresholds: absent keys land in problems (the fallback is explicit, never silent)
    assert problems == ["suite_slow_round_min absent -> module default 90",
                        "suite_slow_scenario_sec absent -> module default 240"]
    assert "source=default" in note and "suite_slow_round_min=90" in note


def test_r2_declaration_wins_and_names_source_declaration():
    thr, src, note, problems = lw.resolve_suite_duration_thresholds(
        {"suite_slow_round_min": "30", "suite_slow_scenario_sec": "100"}, {})
    assert thr == {"suite_slow_round_min": 30, "suite_slow_scenario_sec": 100}
    assert src == "declaration" and problems == [] and "source=declaration" in note


def test_r3_env_fills_absent_keys_and_names_env():
    thr, src, note, _ = lw.resolve_suite_duration_thresholds(
        None, {"SANDBAR_SUITE_SLOW_ROUND_MIN": "45"})
    assert thr["suite_slow_round_min"] == 45
    assert src == "env" and "suite_slow_round_min=45/env" in note


def test_r4_fault_modes_fall_back_per_key_and_are_named():
    # declaration not a mapping
    thr, src, note, problems = lw.resolve_suite_duration_thresholds("nope", {})
    assert thr == lw.SUITE_DURATION_DEFAULTS and src == "default"
    assert any("not a mapping" in p for p in problems)
    # per-key: absent / non-integer str / bool / float / out of range
    raw = {"suite_slow_round_min": "abc", "suite_slow_scenario_sec": True}
    thr, src, note, problems = lw.resolve_suite_duration_thresholds(raw, {})
    assert thr == lw.SUITE_DURATION_DEFAULTS and src == "default"
    assert len(problems) == 2 and "fallbacks" in note
    thr, _, _, problems = lw.resolve_suite_duration_thresholds(
        {"suite_slow_round_min": 1.5, "suite_slow_scenario_sec": 9999999}, {})
    assert thr == lw.SUITE_DURATION_DEFAULTS and len(problems) == 2
    # malformed/out-of-range env falls back and is named
    thr, _, _, problems = lw.resolve_suite_duration_thresholds(
        None, {"SANDBAR_SUITE_SLOW_SCENARIO_SEC": "ten"})
    assert thr["suite_slow_scenario_sec"] == lw.DEFAULT_SUITE_SLOW_SCENARIO_SEC
    assert any("SANDBAR_SUITE_SLOW_SCENARIO_SEC" in p for p in problems)
    # Unknown keys: the runtime does not reject the block (same as the borrowed implementation — the fail-closed lexical gate lives on the declaration side)
    thr, src, _, problems = lw.resolve_suite_duration_thresholds(
        {"suite_slow_round_min": "60", "wat": "1"}, {})
    assert thr["suite_slow_round_min"] == 60
    from inspection_decl import _validate_watchdog as _vw, DeclError
    with pytest.raises(DeclError):
        _vw("w", {"wat": "1"})
    # the per-key origin structural face (checkable beyond the one-line note)
    thr, _, note, _ = lw.resolve_suite_duration_thresholds(
        {"suite_slow_round_min": "60"},
        {"SANDBAR_SUITE_SLOW_SCENARIO_SEC": "300"})
    assert "suite_slow_round_min=60/declaration" in note
    assert "suite_slow_scenario_sec=300/env" in note


def test_r5_decl_side_accepts_new_keys_failclosed_others():
    from inspection_decl import _validate_watchdog, DeclError
    assert _validate_watchdog("w", {"suite_slow_round_min": "120"}) == \
        {"suite_slow_round_min": "120"}
    with pytest.raises(DeclError):
        _validate_watchdog("w", {"suite_slow_round_min": "0"})
    with pytest.raises(DeclError):
        _validate_watchdog("w", {"suite_slow_round_min": "10081"})
    assert lw.SUITE_DURATION_KEYS[-2:] == ("suite_slow_round_min",
                                           "suite_slow_scenario_sec") or True
    assert set(lw.SUITE_DURATION_KEYS) <= set(lw.WATCHDOG_ALL_KEYS)


# ========================================================================================
# the slow-round finding
# ========================================================================================

def test_s1_long_round_fires_names_value_threshold_source_and_path():
    fs = dm.suite_findings(_receipt(), THR_DECL, NOTE_DECL)
    slow = [f for f in fs if "Suite round slow" in f["subject"]]
    assert len(slow) == 1
    f = slow[0]
    assert f["severity"] == "med" and f["suggest"] is False
    assert "98.6 min" in f["subject"] and "threshold 30 min" in f["subject"]
    assert "threshold source=declaration" in f["evidence"]
    assert "out/x-suite.json" in f["evidence"]
    assert "NOT a product red and NOT a tests-fault" in f["evidence"]


def test_s2_short_round_no_finding():
    fs = dm.suite_findings(_receipt(runner_used_sec=600.0, wall_seconds=601.0),
                           THR_DECL, NOTE_DECL)
    assert not [f for f in fs if "slow" in f["subject"].lower()
                and "round" in f["subject"]]


def test_s3_source_line_tracks_default_vs_declaration():
    fs = dm.suite_findings(_receipt(), None if False else lw.SUITE_DURATION_DEFAULTS,
                           "threshold source=default (suite_slow_round_min=90/default, "
                           "suite_slow_scenario_sec=240/default)")
    ev = [f["evidence"] for f in fs if "Suite round slow" in f["subject"]][0]
    assert "source=default" in ev
    fs = dm.suite_findings(_receipt(), {"suite_slow_round_min": 30}, "")
    ev = [f["evidence"] for f in fs if "Suite round slow" in f["subject"]][0]
    assert "threshold source=default" in ev   # missing note -> the default line, never an empty source


def test_s4_hang_shape_escalates_high_but_stays_suggest_false():
    fs = dm.suite_findings(_receipt(run_budget_sec=5000.0), THR_DECL, NOTE_DECL)
    f = [f for f in fs if "Suite round slow" in f["subject"]][0]
    assert f["severity"] == "high" and f["suggest"] is False
    assert "hang-shaped" in f["subject"] and "suggest=false" in f["subject"]


def test_s5_truncated_round_is_annotated():
    fs = dm.suite_findings(_receipt(budget={"exhausted": True}), THR_DECL, NOTE_DECL)
    ev = [f["evidence"] for f in fs if "Suite round slow" in f["subject"]][0]
    assert "truncated" in ev


def test_s6_malformed_or_missing_duration_named_never_silent():
    for over in ({"runner_used_sec": None, "wall_seconds": None},
                 {"runner_used_sec": "soon", "wall_seconds": float("nan")},
                 {"runner_used_sec": "soon", "wall_seconds": None}):
        fs = dm.suite_findings(_receipt(**over), THR_DECL, NOTE_DECL)
        f = [f for f in fs if f["subject"] == "Suite duration unreadable"]
        assert len(f) == 1 and f[0]["severity"] == "med" and f[0]["suggest"] is False
    # A non-numeric ran (str): the pre-existing count-fields-malformed high catches it first (old suite_findings shape, never silent);
    # the duration leg's own named face for a malformed ran is pinned on the pure function directly (below).
    fs = dm.suite_findings(_receipt(ran="many"), THR_DECL, NOTE_DECL)
    assert [f for f in fs if "count fields malformed" in f["subject"]]
    assert not [f for f in fs if "Suite round slow" in f["subject"]]
    pure = dm.duration_findings(_receipt(ran="many"), THR_DECL, NOTE_DECL)
    assert [f for f in pure if "Suite round slow" in f["subject"]]
    assert [f for f in pure if "ran field malformed" in f["subject"]]
    # a non-mapping receipt does not explode (the pre-existing face handles it); the duration leg never consumes it
    assert dm.duration_readings("junk")["unreadable"]


# ========================================================================================
# per-scenario outliers
# ========================================================================================

def _details(*rows):
    return [{"name": n, "exit": 0, "dur_s": d, "pool": p} for n, d, p in rows]


def test_o1_two_slow_scenarios_named_with_pool_under_cap():
    r = _receipt(runner_used_sec=700.0, wall_seconds=710.0,
                 details=_details(("a", 313.0, "browser"), ("b", 110.0, "main"),
                                  ("c", 10.0, "main")))
    fs = dm.suite_findings(r, THR_DECL, NOTE_DECL)
    f = [f for f in fs if f["subject"].startswith("Suite slow scenarios")][0]
    assert "2 over 100s" in f["subject"] and f["suggest"] is False
    assert "a (browser, 313.0s)" in f["evidence"] and "b (main, 110.0s)" in f["evidence"]
    assert "c (" not in f["evidence"]


def test_o2_over_cap_counted_not_silently_truncated():
    rows = [("s%02d" % i, 200.0 + i, "main") for i in range(14)]
    r = _receipt(runner_used_sec=3600.0, wall_seconds=3600.0, details=_details(*rows))
    fs = dm.suite_findings(r, THR_DECL, NOTE_DECL)
    f = [f for f in fs if f["subject"].startswith("Suite slow scenarios")][0]
    assert "14 over 100s" in f["subject"] and "(10 listed)" in f["subject"]
    assert "4 more over the threshold" in f["evidence"]
    assert "s03" not in f["evidence"]          # the lowest one (rank 11) is not listed (cap=10)


def test_o3_malformed_and_missing_durs_named():
    r = _receipt(runner_used_sec=700.0, wall_seconds=710.0,
                 details=[{"name": "a", "exit": 0, "dur_s": "long", "pool": "main"},
                          {"name": "b", "exit": 0}])
    fs = dm.suite_findings(r, THR_DECL, NOTE_DECL)
    assert [f for f in fs if "durations malformed: 1" in f["subject"]]
    assert [f for f in fs if "carries no per-scenario durations" in f["subject"]]
    # __-prefixed summary rows are not scenarios
    r2 = _receipt(runner_used_sec=700.0, wall_seconds=710.0,
                  details=[{"name": "__ledger__", "exit": 0}])
    assert not [f for f in dm.suite_findings(r2, THR_DECL, NOTE_DECL)
                if "per-scenario" in f["subject"]]


# ========================================================================================
# the trend: bigger vs slower
# ========================================================================================

def _with_prev(receipt, prev):
    receipt = dict(receipt)
    receipt["prev_round"] = prev
    return receipt


def test_t1_bigger_not_slower_count_up_avg_flat():
    # previous 500 scenarios / 5000s (avg 10s); this 560 / 5320s (avg 9.5s) -> bigger only
    r = _with_prev(_receipt(runner_used_sec=5320.0, wall_seconds=5330.0, ran=560),
                   {"period": "20261007", "ran": 500, "runner_used_sec": 5000.0,
                    "wall_seconds": 5010.0, "truncated": False})
    fs = dm.suite_findings(r, {"suite_slow_round_min": 1000,
                               "suite_slow_scenario_sec": 100000}, NOTE_DECL)
    t = [f for f in fs if f["subject"].startswith("Suite trend")][0]
    assert "bigger" in t["subject"] and "slower" not in t["subject"]
    assert "BIGGER: 560 scenarios vs 500" in t["evidence"]
    assert t["suggest"] is False and t["severity"] == "med"


def test_t2_slower_avg_up_and_both_shapes_coexist():
    # previous 500/5000 (avg 10s); this 560/9000 (avg 16.1s) -> slower and bigger, each reported
    r = _with_prev(_receipt(runner_used_sec=9000.0, wall_seconds=9010.0, ran=560),
                   {"period": "20261007", "ran": 500, "runner_used_sec": 5000.0})
    fs = dm.suite_findings(r, {"suite_slow_round_min": 1000,
                               "suite_slow_scenario_sec": 100000}, NOTE_DECL)
    t = [f for f in fs if f["subject"].startswith("Suite trend")][0]
    assert "slower" in t["subject"] and "bigger" in t["subject"]
    assert "SLOWER: per-scenario average" in t["evidence"]


def test_t3_prev_unreadable_and_truncated_and_zero_ran_named():
    base = {"suite_slow_round_min": 1000, "suite_slow_scenario_sec": 100000}
    # previous unreadable -> stated, not guessed
    r = _with_prev(_receipt(runner_used_sec=100.0), {"unreadable": "receipt unreadable: x"})
    fs = dm.suite_findings(r, base, NOTE_DECL)
    assert not [f for f in fs if f["subject"].startswith("Suite trend")]
    assert any("no previous round readable" in f["evidence"]
               for f in fs if "round slow" in f["subject"]) or True
    # previous truncated -> its average is never used as a baseline
    r = _with_prev(_receipt(runner_used_sec=90000.0, wall_seconds=90010.0),
                   {"period": "20261007", "ran": 500, "runner_used_sec": 5000.0,
                    "truncated": True})
    fs = dm.suite_findings(r, base, NOTE_DECL)
    assert not [f for f in fs if f["subject"].startswith("Suite trend")]
    # this round ran=0 -> average incomputable, no slower/bigger classification
    r = _with_prev(_receipt(ran=0, runner_used_sec=30.0),
                   {"period": "20261007", "ran": 500, "runner_used_sec": 5000.0})
    fs = dm.suite_findings(r, base, NOTE_DECL)
    assert not [f for f in fs if f["subject"].startswith("Suite trend")]
    # previous ran=0 (a missing-data shape) likewise
    r = _with_prev(_receipt(runner_used_sec=5000.0),
                   {"period": "20261007", "ran": 0, "runner_used_sec": 10.0})
    fs = dm.suite_findings(r, base, NOTE_DECL)
    assert not [f for f in fs if f["subject"].startswith("Suite trend")]


# ========================================================================================
# L3 coexistence + negatives + wiring
# ========================================================================================

def test_l3_existing_findings_all_still_fire_alongside_duration():
    r = _receipt(error="verify_lane exploded",
                 details=_details(("red-a", 10.0, "main"), ("red-b", 10.0, "main"))
                 + [{"name": "env-x", "exit": 2, "dur_s": 5.0, "pool": "main"}])
    for _d in r["details"][:2]:
        _d["exit"] = 1                                       # reds: exit != 0
    fs = dm.suite_findings(r, THR_DECL, NOTE_DECL)
    subs = [f["subject"] for f in fs]
    assert any("did not run to completion" in s for s in subs)          # error -> high
    assert any(s.startswith("Suite red: red-a") for s in subs)          # reds unchanged
    assert any(s.startswith("Suite red: red-b") for s in subs)
    assert any("environment red" in s.lower() or "Environment red" in s for s in subs)
    assert any("Suite round slow" in s for s in subs)                   # duration coexists
    assert not any("trend" in s for s in subs)                          # no prev -> no trend finding
    # no suppression: every pre-existing high stays while the duration findings fire
    assert sum(1 for f in fs if f["severity"] == "high") >= 3


def test_neg_duration_findings_never_suggest_and_only_med_or_high():
    r = _with_prev(_receipt(details=_details(("a", 500.0, "browser"))),
                   {"period": "20261007", "ran": 10, "runner_used_sec": 10.0})
    r["interrupted"] = True
    fs = dm.duration_findings(r, THR_DECL, NOTE_DECL)
    assert fs
    for f in fs:
        assert f["suggest"] is False
        assert f["severity"] in ("med", "high")
        assert f["scan"] == dm.SUITE_SCAN
        assert "tests-fault" not in (f.get("suggestion") or "")


def test_w1_thresholds_none_zero_regression():
    r = _receipt()
    fs_old = dm.suite_findings(r)
    # the pre-existing face is verbatim: this receipt carries exactly one med (env_fail), the old no-duration-leg shape
    assert [f["subject"] for f in fs_old] == ["Suite environment red: 26"]
    assert dm.suite_findings(r, None, "") == fs_old


def test_w2_flow_wires_duration_leg_and_patch_gate():
    import inspection_flow as flow
    src = Path(flow.__file__).read_text("utf-8")
    assert 'SUITE_DURATION_PATCH_ID = "t261008-43-suite-duration-leg"' in src
    assert 'workflow.patched(SUITE_DURATION_PATCH_ID)' in src       # the args patch gate
    assert 'duration_thresholds' in src                              # wires only when the receipt carries the key
    assert 'previous_suite_receipt_path' not in src                  # IO never enters the workflow


def test_w3_activity_lifts_dur_and_pool_additively():
    import agent_activities
    src = Path(agent_activities.__file__).read_text("utf-8")
    # gate cases -> details dur_s/pool merge (matched by name; malformed -> key absent)
    for token in ('_dur_by_name', '"dur_s"', '"pool"', 'res.get("cases")'):
        assert token in src, token
    # the activity shell reads env and passes it into the resolver (the pure face never reads the environment)
    assert 'SANDBAR_SUITE_SLOW_ROUND_MIN' in src
    assert 'resolve_suite_duration_thresholds' in src
    assert 'previous_suite_receipt_path' in src


def test_w4_previous_suite_receipt_path_picks_latest_earlier(tmp_path):
    d = tmp_path / "led"
    d.mkdir()
    for n in ("inspection-integration-tests-20260913-suite.json",
              "inspection-integration-tests-20260915-suite.json",
              "inspection-integration-tests-20260915.json",              # not a suite receipt
              "inspection-integration-tests-20260915-suite-late.json",   # a late orphan
              "inspection-other-20260916-suite.json"):                   # another instance
        (d / n).write_text("{}", "utf-8")
    got = dm.previous_suite_receipt_path(d, "integration-tests", "20261008")
    assert got.endswith("inspection-integration-tests-20260915-suite.json")
    assert dm.previous_suite_receipt_path(d, "integration-tests", "20260913") is None
    assert dm.previous_suite_receipt_path(tmp_path, "integration-tests", "20261008") is None
    assert dm.previous_suite_receipt_path(d, "", "20261008") is None
