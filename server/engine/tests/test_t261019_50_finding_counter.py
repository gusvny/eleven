# -*- coding: utf-8 -*-
"""261019: the walkthrough send-back cap counts REPEATS, not rounds.

Measured on t261019-32: eight send-backs, each a DIFFERENT real defect (a nested
`work_done` payload, a missing fixture concurrency declaration, a module-level
reference to a class attribute, a sign payload that blanked the signer and walked
past the no-self-sign gate). Every round moved the ticket forward; the counter
treated them as one loop and stopped at the cap of two, so progress was punished.

The cap's intent is "no infinite bouncing on one finding". Counting the finding
keeps that intent and lets progress accumulate:

  * a send-back whose finding DIFFERS from the previous one resets the counter;
  * the same finding twice in a row still reaches the cap;
  * the digest ignores round numbers and gen markers, so re-wording the same
    finding as "round 5" vs "round 6" is still the same finding;
  * an empty report yields no digest (the counter then behaves as before).

Patch-guarded: an in-flight history keeps its recorded counter semantics.
"""
import os

import dev_lane as dl

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")


class _Res:
    def __init__(self, report="", summary=""):
        self.report = report
        self.summary = summary


def _sig(report="", summary=""):
    # the helper only reads the object's text; the workflow instance is not needed
    return dl.DevLaneWorkflow._acc_finding_sig(None, _Res(report, summary))


def test_different_findings_have_different_digests():
    a = _sig("Verdict: FAILED - the payload is nested")
    b = _sig("Verdict: FAILED - the fixture declares no concurrency limit")
    assert a and b and a != b


def test_the_same_finding_reworded_as_a_later_round_is_the_same_finding():
    a = _sig("## Acceptance walkthrough round 3 - the payload is nested")
    b = _sig("## Acceptance walkthrough round 6 - the payload is nested")
    assert a == b, "a round number is not a new finding"


def test_gen_markers_do_not_fake_a_new_finding():
    assert _sig("gen3: the class attribute is unreachable") == \
        _sig("gen5: the class attribute is unreachable")


def test_whitespace_is_normalised():
    assert _sig("Verdict: FAILED\n\n  the payload is   nested") == \
        _sig("Verdict: FAILED the payload is nested")


def test_an_empty_report_yields_no_digest():
    assert _sig("") == "" and _sig("   ") == ""


def test_the_counter_resets_only_on_a_new_finding():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("workflow.patched(ACC_FINDING_PATCH_ID)")
    window = src[i:i + 700]
    assert "_sig != _prev_sig" in window and "acc_rounds = 0" in window, \
        "a new finding must reset the bounce counter"
    assert 'self.meta["acc_finding_sig"] = _sig' in window, \
        "the previous finding has to be remembered across rounds"


def test_it_is_patch_guarded():
    assert 'ACC_FINDING_PATCH_ID = "dev-lane-acceptance-finding-counter-v1"' in \
        open(DEV_LANE_PY, encoding="utf-8").read()
