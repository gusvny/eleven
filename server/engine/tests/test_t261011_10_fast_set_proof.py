"""t261011-10 L1: the develop-buffer proof-plan decision face (pure functions).

`fast_proof_plan` unions the round's own scenarios with the declared fast set;
every degradation is a NAMED warning; both-sources-empty is a named REFUSAL —
never the full suite (ticket required outcome 3). `fast_budget_verdict` turns
the round's wall clock into a named stewardship signal — never an auto-trim.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dev_lane as dl  # noqa: E402


def _fast(members, budget=2, error="", refusals=()):
    return {"members": list(members), "budget_min": budget,
            "error": error, "refusals": list(refusals)}


def _as_result(d):
    # FastSetDeclarationResult-shaped object face (attribute access path)
    class R:
        pass
    r = R()
    r.members = d["members"]
    r.budget_min = d["budget_min"]
    r.error = d["error"]
    r.refusals = d["refusals"]
    r.wall_s = 0.0
    return r


def test_union_sorted_dedup():
    p = dl.fast_proof_plan(["sc-b", "sc-a", "sc-a"], _fast(["fast-1", "sc-a"]))
    assert p.run_only == ["fast-1", "sc-a", "sc-b"]
    assert p.warning == ""
    assert p.blocked_reason == ""
    assert p.fast_members == ["fast-1", "sc-a"]
    assert p.budget_min == 2


def test_fast_refused_is_not_an_empty_set():
    p = dl.fast_proof_plan(["own-1"],
                           _fast([], error="REFUSED: booked-red member"))
    assert p.run_only == ["own-1"]
    assert "fast set unavailable" in p.warning
    assert "REFUSED" in p.warning
    assert p.blocked_reason == ""


def test_fast_errored_names_the_error():
    p = dl.fast_proof_plan(["own-1"], _fast([], error="query timed out (60s)"))
    assert p.run_only == ["own-1"]
    assert "timed out" in p.warning


def test_declared_empty_set_is_legitimate_with_named_warning():
    p = dl.fast_proof_plan(["own-1"], _fast([]))
    assert p.run_only == ["own-1"]
    assert "declared fast set is empty" in p.warning


def test_own_empty_runs_fast_only_WITH_named_reduction():
    # arbitrate fault 1: an own-absent round proves the fast set alone and
    # the reduction is NAMED — never a quiet fast-only round.
    p = dl.fast_proof_plan([], _fast(["fast-1", "fast-2"]))
    assert p.run_only == ["fast-1", "fast-2"]
    assert p.warning
    assert "own scenarios absent" in p.warning
    assert "never substitutes" in p.warning
    assert p.blocked_reason == ""


def test_own_set_parser_happy_and_refusal():
    import develop_line as dlp
    out = ("OWN_SET_DECLARATION members=2 ticket=t261011-10\n"
           "  member t261011-10-a pool=ro\n"
           "  member t261011-10-b pool=ro\n")
    d = dlp.parse_own_set_declaration(out, "t261011-10")
    assert d.members == ["t261011-10-a", "t261011-10-b"]
    assert d.ticket_id == "t261011-10"
    assert d.refusals == []
    bad = "REFUSED [__own_set__] malformed ticket id 'X/Y'\n"
    r = dlp.parse_own_set_declaration(bad)
    assert r.members == [] and r.refusals


def test_both_empty_is_named_refusal_never_full_suite():
    p = dl.fast_proof_plan([], _fast([], error="lane runner unreadable"))
    assert p.run_only == []
    assert p.blocked_reason
    assert "proof-plan empty" in p.blocked_reason
    assert "lane runner unreadable" in p.blocked_reason
    assert "never a lane fallback" in p.blocked_reason


def test_both_empty_declared_clean_still_refuses():
    p = dl.fast_proof_plan([], _fast([]))
    assert p.run_only == []
    assert "declared empty" in p.blocked_reason


def test_object_shaped_fast_result():
    p = dl.fast_proof_plan(["own-1"], _as_result(_fast(["fast-1"])))
    assert p.run_only == ["fast-1", "own-1"]


def test_none_fast_result_treated_as_unavailable():
    p = dl.fast_proof_plan(["own-1"], None)
    assert p.run_only == ["own-1"]
    assert "fast set unavailable" in p.warning


def test_budget_verdict_boundaries():
    # exactly at budget = no breach (headroom, not a target)
    breach, note = dl.fast_budget_verdict(120.0, 2)
    assert breach is False and note == ""
    breach, note = dl.fast_budget_verdict(120.1, 2)
    assert breach is True and "breached" in note and "stewardship" in note
    # non-numeric / non-positive budget: no verdict, never a crash
    assert dl.fast_budget_verdict("x", 2) == (False, "")
    assert dl.fast_budget_verdict(10.0, 0) == (False, "")
    assert dl.fast_budget_verdict(None, None) == (False, "")
