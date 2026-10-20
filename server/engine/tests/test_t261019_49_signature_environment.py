# -*- coding: utf-8 -*-
"""261019: "two identical faces" must mean two real measurements, in one world.

The anti-churn guard stops a ticket when two consecutive gate rounds produced a
byte-identical measurement face, on the premise that a rerun cannot produce new
information. Two measured ways that premise broke:

  * t261019-44: the two "rounds" were the SAME reused receipt — the only red had
    been fixed and committed inside the ticket's own fixture, and the guard
    still asserted "a rerun cannot produce new information" about a run that
    never happened;
  * the engine's own code stamp (and the lane revision) are part of the
    measurement environment: a fix landed between rounds or a fresh worker
    legitimately changes what the next round measures, so a face recorded under
    a different stamp must not tie.

Coverage: a reused receipt contributes no signature (the existing "" contract
means "do not stop", fail-safe); a different code stamp breaks the tie; a
different lane head breaks the tie; identical measurements in an identical
environment still tie (the guard keeps its teeth); a malformed receipt still
yields "" rather than a false tie.
"""
import shared


def _receipt(**kw):
    r = {"blockers": ["sc-api"], "env_red": ["sc-env"],
         "ran": 12, "passed": 10, "failed": 1, "env_fail": 1,
         "affiliation_confidence": "high", "baseline_ref": "main@abc",
         "details": [{"name": "sc-api", "exit": 1}],
         "code_stamp": {"stamp_line": "stamp-A"},
         "revision": "lane-head-1"}
    r.update(kw)
    return r


def test_identical_measurements_still_tie():
    assert shared.gate_round_signature(_receipt()) == \
        shared.gate_round_signature(_receipt()), "the guard must keep its teeth"


def test_a_reused_receipt_never_counts_as_a_second_round():
    assert shared.gate_round_signature(_receipt(reuse={"reused": True})) == "", \
        "a reused receipt measured nothing new; counting it fabricates a tie"
    assert shared.gate_round_signature(_receipt(reuse={"all_reused": True})) == ""


def test_a_different_code_stamp_breaks_the_tie():
    a = shared.gate_round_signature(_receipt())
    b = shared.gate_round_signature(_receipt(code_stamp={"stamp_line": "stamp-B"}))
    assert a != b, "a fix landed between rounds changes what the next round measures"


def test_a_different_lane_head_breaks_the_tie():
    a = shared.gate_round_signature(_receipt())
    b = shared.gate_round_signature(_receipt(revision="lane-head-2"))
    assert a != b, "a new lane commit is a new face, not the same one"


def test_the_head_key_variants_are_honoured():
    base = shared.gate_round_signature(_receipt(revision=""))
    for key in ("head", "lane_sha", "head_sha"):
        assert shared.gate_round_signature(_receipt(revision="", **{key: "other"})) != base, key


def test_a_measured_change_still_breaks_the_tie():
    a = shared.gate_round_signature(_receipt())
    b = shared.gate_round_signature(_receipt(blockers=["sc-api", "sc-new"]))
    assert a != b


def test_a_malformed_receipt_yields_no_signature():
    assert shared.gate_round_signature(None) == ""
    assert shared.gate_round_signature({"blockers": "nope", "env_red": []}) == ""
