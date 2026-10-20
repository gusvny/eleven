# -*- coding: utf-8 -*-
"""261019: a conflicted line landing re-merges itself instead of parking.

The refusal text already names the remedy — "the lane re-merges the line and
lands again" — and the gate phase is exactly the thing that re-syncs the line.
Until now the stage treated it as a human stop, so a ticket that merely lost a
race with a sibling landing sat blocked until somebody fired retry_qc:
measured twice in one night (t261019-42, t261019-45, both refused right after
another landing moved the line under them).

Coverage: the discriminator (only the conflict shape is routed; every other
landing refusal keeps its human stop), the wiring anchors (patch-guarded,
bounded, routed through the ONE rework entry to the phase that re-syncs), and
the over-bound case (a real conflict still reaches a human, named).
"""
import os

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")


def _src():
    return open(DEV_LANE_PY, encoding="utf-8").read()


def _branch():
    s = _src()
    i = s.index("workflow.patched(LANDING_CONFLICT_PATCH_ID)")
    return s[i:i + 2000]


def test_only_the_conflict_shape_is_routed():
    b = _branch()
    assert '"conflicts in repository" in _err' in b, \
        "the discriminator must be the conflict refusal, never a phase-level guess"


def test_other_refusals_keep_their_human_stop():
    s = _src()
    i = s.index("workflow.patched(LANDING_CONFLICT_PATCH_ID)")
    after = s[i:i + 2600]
    assert 'await self._blocked("merge", "develop-buffer landing refused: %s"' in after, \
        "a drifted checkout / undeclared line / duplicate landing still blocks"


def test_routing_goes_to_the_gate_that_resyncs_the_line():
    b = _branch()
    assert 'self._auto_rework(' in b and '"merge_check"' in b, \
        "the re-merge has one home: the gate phase that syncs the line"
    assert 'fallback="merge_check"' in b


def test_it_is_patch_guarded():
    assert 'LANDING_CONFLICT_PATCH_ID = "dev-lane-landing-conflict-rewind-v1"' in _src(), \
        "an older history recorded the block-on-a-human path and must replay it"


def test_it_is_bounded_and_names_the_over_bound_case():
    b = _branch()
    assert "self._landing_conflict_rounds <= MAX_LANDING_CONFLICT_ROUNDS" in b
    assert "still conflicted after %d automatic" in b, \
        "over the bound a real conflict is blocked BY NAME, never looped"
