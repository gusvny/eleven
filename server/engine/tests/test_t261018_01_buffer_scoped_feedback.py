"""t261018-01 L1: the develop-buffer scoped-feedback and closing-face planners
(host order 261016: only the fast set, never a full run; feedback = change-
scoped only; the full fast set runs once, at closing).

`scoped_feedback_plan` = own scenarios ∪ last-round red names; zero scenarios
= the registered supply-side refusal (KI-01M551AR1XT01W9DNR2AN88B52). 
`closing_face_plan` = the declared fast set ONLY; every unavailable shape is a
named error. Neither planner has a branch that can produce a full-suite
caliber — the property test pins that structurally.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dev_lane as dl  # noqa: E402


# ---------- scoped_feedback_plan ----------

def test_scoped_union_sorted_dedup():
    p = dl.scoped_feedback_plan(["sc-b", "sc-a", "sc-a"], ["sc-c", "sc-a"])
    assert p.run_only == ["sc-a", "sc-b", "sc-c"]
    assert p.blocked_reason == ""


def test_scoped_prev_reds_only():
    p = dl.scoped_feedback_plan([], ["red-1", "red-2"])
    assert p.run_only == ["red-1", "red-2"]
    assert p.blocked_reason == ""


def test_scoped_both_empty_is_named_supply_refusal():
    p = dl.scoped_feedback_plan([], [])
    assert p.run_only == []
    assert "KI-01M551AR1XT01W9DNR2AN88B52" in p.blocked_reason
    assert "refused" in p.blocked_reason


def test_scoped_never_mentions_full_suite_as_fallback():
    p = dl.scoped_feedback_plan([], [])
    assert "never a lane fallback" in p.blocked_reason


def test_scoped_malformed_inputs_never_raise():
    for own, reds in [(None, None), (["", "  "], [None, 7, "ok"]),
                      ([], [" x ", "x"])]:
        p = dl.scoped_feedback_plan(own, reds)
        assert isinstance(p.run_only, list)
    # whitespace names are stripped, dup after strip collapses
    p = dl.scoped_feedback_plan([" x "], ["x"])
    assert p.run_only == ["x"]


def test_scoped_default_prev_reds():
    # prev_red_names is optional (round-1 docs-only shape)
    p = dl.scoped_feedback_plan([])
    assert p.blocked_reason != ""


# ---------- closing_face_plan ----------

def test_closing_members_only():
    p = dl.closing_face_plan(["fast-2", "fast-1", "fast-2"])
    assert p.run_only == ["fast-1", "fast-2"]
    assert p.error == ""


def test_closing_error_named_never_full():
    p = dl.closing_face_plan(["fast-1"], fast_error="query timed out (60s)")
    assert p.run_only == []
    assert "closing face unavailable" in p.error
    assert "timed out" in p.error
    assert "never a lane fallback" in p.error


def test_closing_empty_set_is_named_refusal():
    p = dl.closing_face_plan([])
    assert p.run_only == []
    assert "closing face empty" in p.error


def test_closing_whitespace_and_none_members():
    p = dl.closing_face_plan(["", "  ", None, "fast-1"])
    assert p.run_only == ["fast-1"]
    p2 = dl.closing_face_plan([None, "  "])
    assert p2.run_only == [] and p2.error != ""


def test_closing_dict_and_object_shapes():
    p = dl.closing_face_plan({"members": ["a"]})
    assert p.run_only == ["a"]
    class R:
        members = ["b"]
    p2 = dl.closing_face_plan(R())
    assert p2.run_only == ["b"]


def test_closing_long_error_truncated():
    p = dl.closing_face_plan([], fast_error="x" * 500)
    assert len(p.error) < 400


# ---------- structural property: no planner can produce a full caliber ----------

def test_property_no_full_suite_caliber():
    # Every combination of planner inputs yields either a non-empty scoped
    # member list or a named refusal — never an "empty means everything"
    # shape (run_only==[] without a reason).
    for own in ([], ["own-1"]):
        for reds in ([], ["red-1"]):
            fp = dl.scoped_feedback_plan(own, reds)
            assert fp.run_only or fp.blocked_reason
    for members in ([], ["f1"], ["f1", "f2"]):
        for err in ("", "boom"):
            cp = dl.closing_face_plan(members, err)
            assert cp.run_only or cp.error
    # and the closing face NEVER carries a non-fast name
    cp = dl.closing_face_plan(["f1"])
    assert all(n.startswith("f") for n in cp.run_only)


# ---------- patch id ----------

def test_patch_id_is_ticket_scoped():
    assert dl.DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID == \
        "t261018-01-buffer-scoped-feedback-v1"
    # distinct from the t261011-10 id (KI-061: separate replay gates)
    assert dl.DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID != \
        dl.DEV_BUFFER_FAST_PROOF_PATCH_ID
