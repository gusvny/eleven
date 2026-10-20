# -*- coding: utf-8 -*-
"""261020: an "identical face" stop must record the world it measured.

The stop asserts "a full rerun cannot produce new information". That is a claim
about the measurement environment — and the engine code is part of that
environment: a fix landed between rounds changes what the next round measures.
Measured cost of not recording it: t261019-28 sat stopped for 15+ hours across
several engine fixes, classified judgement (human-only), because nothing on the
record could tell a reader that the world had moved.

Coverage: the workflow writes the stamp clause into the stop reason (from the
receipt's own code stamp, pure and replay-safe); the pure staleness check fires
only when the marker, a recorded stamp and a DIFFERENT current stamp are all
present (fail-closed on each missing piece); a same-stamp stop stays as it is.
"""
import os

import shared
import dev_lane as dl

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")
STOP = ("3 consecutive rounds with a byte-identical gate measurement face (same gate "
        "blockers / named env-red / counts / failure detail / baseline ref): this "
        "ticket's write set and red face are unchanged, so a full rerun cannot produce "
        "new information. Route to human review")


class _Receipt:
    def __init__(self, stamp_line):
        self.code_stamp = {"stamp_line": stamp_line} if stamp_line else {}


def test_the_stop_records_the_stamp_it_measured_under():
    clause = dl._stamp_clause(_Receipt("path_gates@A dev_lane@B"))
    assert "measured under code stamp path_gates@A dev_lane@B" in clause
    assert "premise is stale" in clause, \
        "the reader must be told what to do with the stamp"


def test_no_stamp_reads_as_unknown_never_as_same():
    assert dl._stamp_clause(_Receipt("")) == ""
    assert dl._stamp_clause(object()) == ""


def test_staleness_fires_when_the_code_moved():
    text = STOP + " (measured under code stamp stamp-A — if the engine code has moved since, this stop's premise is stale and a rerun is informative)"
    assert shared.identical_face_stop_is_stale(text, "stamp-A") is False
    assert shared.identical_face_stop_is_stale(text, "stamp-B") is True


def test_staleness_is_fail_closed_on_every_missing_piece():
    text = STOP + " (measured under code stamp stamp-A — ...)"
    assert shared.identical_face_stop_is_stale(text, "") is False, "no current stamp"
    assert shared.identical_face_stop_is_stale(STOP, "stamp-B") is False, "no recorded stamp"
    assert shared.identical_face_stop_is_stale("plain block text", "stamp-B") is False


def test_the_workflow_appends_the_clause():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("byte-identical gate measurement face")
    window = src[i:i + 900]
    assert "_stamp_clause(cur_integ)" in window, \
        "the stop's own reason must carry the stamp, not a side record a reader may miss"
