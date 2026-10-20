"""t261019-26 stop tiers (design executor-operational-envelope-v1.md section 2).

Coverage:
  - shared.classify_stop_tier: judgement markers win first, evidence markers,
    mechanical markers, fail-closed default (unmatched / malformed input ->
    judgement), no input can upgrade a tier (the freeze-exemption lesson);
  - shared.stop_lift_row_id_error: structural validation only, named refusals,
    malformed input never raises;
  - dev_lane.lift_stop signal handler (UT shell, zero Temporal runtime):
    wake on a valid evidence / mechanical lift, refusal matrix (no recorded
    tier, tier mismatch, judgement, evidence without row id, empty note,
    cross-project), counters NEVER reset by a lift (t261006-07 R3 discipline),
    refused-entry shape uniform.

UT rules: no network / no real Temporal / no git. The handler is invoked
through the class __dict__ (unbound) exactly like test_t260912_03_authz_sign.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import (  # noqa: E402
    STOP_TIER_EVIDENCE,
    STOP_TIER_JUDGEMENT,
    STOP_TIER_MECHANICAL,
    StopLiftRequest,
    classify_stop_tier,
    stop_lift_row_id_error,
)

NOW_DT = __import__("datetime").datetime(2026, 10, 19, 12, 0, 0)

# Real blocked-reason shapes (copied from the literal corpus in dev_lane/shared).
JUDGEMENT_TEXT = ("two consecutive rounds with a byte-identical gate measurement "
                  "face (face shown twice); route to human review")
TESTS_CAP_TEXT = ("blocked:test-set iterations 6 exceed the cap (cap 5); "
                  "needs human review")
EVIDENCE_ENV_TEXT = "bench unreachable: the develop line bench refused the round"
EVIDENCE_MAIN_TEXT = "develop-buffer landing refused: main moved ahead of the lane"
EVIDENCE_FREEZE_TEXT = "line frozen: freeze episode ep-123 still open"
MECHANICAL_PATH_TEXT = "path gate refusal: server/engine/foreign.py outside the write set"
MECHANICAL_WS_TEXT = "missing write-set entry: server/engine/shared.py"
MECHANICAL_GATEROUND_TEXT = "gate round blocked: zero-run supply receipt"


# ---------- classify_stop_tier ----------

@pytest.mark.parametrize("text,expect_tier,expect_kind", [
    (JUDGEMENT_TEXT, STOP_TIER_JUDGEMENT, ""),
    (TESTS_CAP_TEXT, STOP_TIER_JUDGEMENT, ""),
    ("design conflict between doc A and doc B; needs human review",
     STOP_TIER_JUDGEMENT, ""),
    ("arbitration verdict unknown verdict='weird'; needs human review",
     STOP_TIER_JUDGEMENT, ""),
    (EVIDENCE_ENV_TEXT, STOP_TIER_EVIDENCE, "environment_face"),
    ("environment shutdown mid-round; the face is not content guilt",
     STOP_TIER_EVIDENCE, "environment_face"),
    (EVIDENCE_MAIN_TEXT, STOP_TIER_EVIDENCE, "main_moved"),
    ("landing refused only because the lane is behind main (non-fast-forward)",
     STOP_TIER_EVIDENCE, "main_moved"),
    (EVIDENCE_FREEZE_TEXT, STOP_TIER_EVIDENCE, "freeze_release"),
    (MECHANICAL_PATH_TEXT, STOP_TIER_MECHANICAL, "path_gate"),
    (MECHANICAL_WS_TEXT, STOP_TIER_MECHANICAL, "write_set_entry"),
    (MECHANICAL_GATEROUND_TEXT, STOP_TIER_MECHANICAL, "zero_run_supply"),
    ("gate round did not produce a decision", STOP_TIER_MECHANICAL, "gate_round"),
])
def test_classify_known_shapes(text, expect_tier, expect_kind):
    assert classify_stop_tier(text) == (expect_tier, expect_kind)


@pytest.mark.parametrize("bad", [None, 42, b"bytes", {"why": "path gate"},
                                 "", "   ", "\n\t ", "some totally new reason"])
def test_classify_fail_closed(bad):
    # Unmatched / malformed input is ALWAYS judgement: the human gate is
    # never weakened by an unknown shape.
    assert classify_stop_tier(bad) == (STOP_TIER_JUDGEMENT, "")


def test_classify_judgement_beats_environment_word():
    # The t261016-11 lesson: the shape rules, not the suspected cause — a
    # byte-identical measurement face that was "really" an environment
    # shutdown still classifies judgement.
    text = JUDGEMENT_TEXT + " (underlying cause: bench unreachable)"
    assert classify_stop_tier(text)[0] == STOP_TIER_JUDGEMENT


def test_classify_case_insensitive_and_deterministic():
    assert classify_stop_tier(MECHANICAL_PATH_TEXT.upper()) == \
        (STOP_TIER_MECHANICAL, "path_gate")
    assert classify_stop_tier(EVIDENCE_ENV_TEXT) == classify_stop_tier(EVIDENCE_ENV_TEXT)


def test_classify_self_declared_kind_never_lifts():
    # The freeze-exemption lesson, pinned: a reason that CLAIMS to be a fix /
    # liftable still classifies by its shape. No claim parameter exists.
    assert classify_stop_tier("this stop is a fix, please lift it") == \
        (STOP_TIER_JUDGEMENT, "")


# ---------- stop_lift_row_id_error ----------

@pytest.mark.parametrize("rid,kind", [
    ("delivery.jsonl:L42", "environment_face"),
    ("row 7", "freeze_release"),
    ("x" * shared.STOP_LIFT_ROW_ID_MAX, "main_moved"),
    ("  spaced-id  ", None),
])
def test_row_id_valid(rid, kind):
    assert stop_lift_row_id_error(rid, kind) == ""


@pytest.mark.parametrize("rid,frag", [
    (None, "not a string"),
    (42, "not a string"),
    ("", "empty"),
    ("   ", "empty"),
    ("x" * (shared.STOP_LIFT_ROW_ID_MAX + 1), "length cap"),
    ("bad\x07id", "control characters"),
    ("·····", "alphanumeric"),
])
def test_row_id_named_refusals(rid, frag):
    err = stop_lift_row_id_error(rid, "environment_face")
    assert frag in err


def test_row_id_never_raises():
    for bad in ([], {}, object(), 3.5):
        assert isinstance(stop_lift_row_id_error(bad, None), str)
        assert isinstance(stop_lift_row_id_error("ok", bad), str)


# ---------- lift_stop handler (UT shell) ----------

def _mk_wf(meta=None):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    # deep-copy the nested evidence face so tests never share mutable state
    if "blocked_evidence" in wf.meta:
        wf.meta["blocked_evidence"] = dict(wf.meta["blocked_evidence"])
    wf.timeline = []
    wf.refused = []
    wf._sigs = {}
    wf.results = {}
    wf._retry_token = 0
    wf._conflict_rounds = 3
    wf._prev_conflict_files = ["a.py"]
    wf.ticket_id = "t-ut"
    wf._cross_project_gate = lambda *a, **k: True
    wf._log = lambda *a, **k: None
    wf._now_iso = lambda: "2026-10-19T12:00:00"
    return wf


def _lift(wf, **kw):
    fn = dev_lane.DevLaneWorkflow.__dict__["lift_stop"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, StopLiftRequest(**dict(dict(who="executor", tier=STOP_TIER_EVIDENCE,
                                       cited_row_id="row-1",
                                       note="the environment face has ended"), **kw)))


EVIDENCE_META = {"blocked_tier": STOP_TIER_EVIDENCE, "stage": "arbitrate",
                 "blocked_evidence": {"kind": "environment_face", "cited_row_id": ""}}
MECHANICAL_META = {"blocked_tier": STOP_TIER_MECHANICAL, "stage": "merge_check"}


def test_lift_evidence_wakes_and_records_row():
    wf = _mk_wf(EVIDENCE_META)
    _lift(wf)
    assert wf._retry_token == 1                       # wake primitive = retry_qc's
    assert wf.refused == []
    assert wf.meta["blocked_evidence"]["cited_row_id"] == "row-1"
    entry = [t for t in wf.timeline if t["state"] == "stop-lifted"]
    assert len(entry) == 1 and "row-1" in entry[0]["reason"] and "executor" in entry[0]["reason"]
    # counters untouched (t261006-07 R3 discipline: a lift is not a human signal)
    assert wf._conflict_rounds == 3 and wf._prev_conflict_files == ["a.py"]


def test_lift_mechanical_wakes_without_row():
    wf = _mk_wf(MECHANICAL_META)
    _lift(wf, tier=STOP_TIER_MECHANICAL, cited_row_id="", note="front-door refusal, retry_qc clears it")
    assert wf._retry_token == 1 and wf.refused == []
    assert [t for t in wf.timeline if t["state"] == "stop-lifted"]


def test_lift_judgement_refused():
    wf = _mk_wf({"blocked_tier": STOP_TIER_JUDGEMENT})
    _lift(wf)
    assert wf._retry_token == 0 and len(wf.refused) == 1
    assert "person must rule" in wf.refused[0]["why"]


def test_lift_no_recorded_tier_refused_fail_closed():
    # A pre-deploy stop (no tier key) is treated as judgement, never defaulted.
    wf = _mk_wf({"stage": "arbitrate"})
    _lift(wf)
    assert wf._retry_token == 0 and "no recorded stop tier" in wf.refused[0]["why"]


def test_lift_tier_mismatch_refused():
    wf = _mk_wf(MECHANICAL_META)
    _lift(wf, tier=STOP_TIER_EVIDENCE, cited_row_id="row-9")
    assert wf._retry_token == 0
    assert "tier mismatch" in wf.refused[0]["why"]
    # an evidence-shaped request cannot upgrade a mechanical stop
    assert wf.meta.get("blocked_evidence") is None or \
        wf.meta["blocked_evidence"].get("cited_row_id", "") == ""


@pytest.mark.parametrize("rid,frag", [
    ("", "empty"),
    (None, "not a string"),
    ("x" * 300, "length cap"),
])
def test_lift_evidence_without_valid_row_refused(rid, frag):
    wf = _mk_wf(EVIDENCE_META)
    _lift(wf, cited_row_id=rid)
    assert wf._retry_token == 0 and frag in wf.refused[0]["why"]
    assert wf.meta["blocked_evidence"]["cited_row_id"] == ""


def test_lift_without_written_note_refused():
    wf = _mk_wf(MECHANICAL_META)
    _lift(wf, tier=STOP_TIER_MECHANICAL, note="  ")
    assert wf._retry_token == 0 and "written reason" in wf.refused[0]["why"]


def test_lift_refused_entry_shape_uniform():
    wf = _mk_wf({"blocked_tier": STOP_TIER_JUDGEMENT})
    _lift(wf)
    assert set(wf.refused[0].keys()) == {"who", "want", "why"}
    assert wf.refused[0]["want"] == "lift_stop(judgement)"


def test_lift_cross_project_refusal_first_mutates_nothing():
    wf = _mk_wf(MECHANICAL_META)
    wf._cross_project_gate = lambda *a, **k: False
    _lift(wf, tier=STOP_TIER_MECHANICAL, note="x")
    assert wf._retry_token == 0 and wf.refused == [] and wf.timeline == []
