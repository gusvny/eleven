# -*- coding: utf-8 -*-
"""261020: a certification-wait timeout is an EVIDENCE stop, not a human one.

Measured (t261019-41): the ticket landed on the line, then waited the whole
bound — 96 polls x 300 s — because no certification round ran at all (the
line-round guard had leaked `held`, so the schedule never certified anything).
When the window expired the ticket stopped "for a human", although the ONLY
missing thing was a round: the records could disprove the stop the moment one
ran. The stop-tier classifier now reads that shape as evidence-tier, which is
what lets a retry_qc lift it instead of a person.

Coverage: the classifier answers evidence/cert_wait for the wait-timeout text
(both wordings), keeps judgement for a genuine tie, and the workflow's block
text no longer claims the schedule "is not built yet" (it exists; it simply did
not run).
"""
import os

import shared

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")


def test_wait_timeout_is_evidence_tier():
    text = ("no certification covered this landing within 96 polls x 300s "
            "(certification wait timed out; the line-round schedule certifies "
            "the derived range on its next tick) — stopped named, liftable by "
            "retry_qc once a round certifies the landing")
    tier, kind = shared.classify_stop_tier(text)
    assert tier == shared.STOP_TIER_EVIDENCE and kind == "cert_wait"


def test_the_short_wording_also_classifies():
    tier, kind = shared.classify_stop_tier(
        "certification wait exhausted after 12 polls")
    assert tier == shared.STOP_TIER_EVIDENCE and kind == "cert_wait"


def test_judgement_shapes_still_win():
    tier, _ = shared.classify_stop_tier(
        "two consecutive rounds with a byte-identical gate measurement face")
    assert tier == shared.STOP_TIER_JUDGEMENT


def test_unmatched_text_is_still_judgement():
    assert shared.classify_stop_tier("something else entirely")[0] == \
        shared.STOP_TIER_JUDGEMENT


def test_the_block_text_no_longer_says_the_schedule_is_unbuilt():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("no certification covered this landing within")
    window = src[i:i + 400]
    assert "not built" not in window, \
        "the schedule exists; a stale 'not built yet' wording misdirects the operator"
    assert "retry_qc" in window
