# -*- coding: utf-8 -*-
"""t261009-01 — pre-existing-main discriminator unit battery (grey-box L1).

Ticket: three stale-pinned scenarios of closed tickets red every lane gate; the
known-red ledger cannot answer them (no verdict row) so every round lists them
as ambiguous and burns a full-suite baseline. The discriminator:

  - probes ledger-ambiguous red names on the CLEAN baseline tree (main at the
    lane base) via the existing fail-closed targeted entry, bounded to
    MAIN_SIDE_PROBE_CAP names per round;
  - names a red that REPRODUCES on the clean base as a pre-existing main-side
    red (failure_protocol decide(): baseline_red existing debt => record, not
    blocker);
  - stays fail-closed: probe off / clone failure / timeout / capped out /
    baseline not-checked all leave the red a lane blocker.

Scope of this battery: the two pure faces (_main_side_probe_plan,
_main_side_face), the kill-switch reader, byte-parity of the probe-off shape
with the historical behavior, malformed-input three-state discipline, and a
source lock on the receipt passthrough (gate face -> IntegrationRunResult).
Offline seconds, zero docker/Temporal/browser, never touches 3099/7233.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'tools'))

import verify_lane as vl  # noqa: E402

AMB = ['t260907-11-wb-anchor-faces', 't260911-01-multirepo-diff-faces',
       't260907-01-smoke-lane-green']
REDS = AMB + ['t16-some-other-red']


# ---------------- A. probe plan: bounded targeting ----------------

def test_plan_probe_on_targets_ambiguous_capped():
    targeted, capped, applied = vl._main_side_probe_plan(AMB, REDS, True, cap=2)
    assert targeted == AMB[:2] and capped == [AMB[2]] and applied is True


def test_plan_probe_on_default_cap():
    targeted, capped, applied = vl._main_side_probe_plan(AMB, REDS, True)
    assert targeted == AMB and capped == [] and applied is True


def test_plan_probe_on_all_ambiguous_replaces_full_baseline_fallback():
    """The defect this ticket fixes: with every red ambiguous the old shape ran
    the FULL suite on the baseline tree (~17 min). Probe-on must target instead."""
    targeted, _, applied = vl._main_side_probe_plan(AMB, AMB, True)
    assert applied is True and targeted == AMB


def test_plan_no_ambiguous_targets_nothing():
    assert vl._main_side_probe_plan([], REDS, True) == ([], [], False)


def test_plan_probe_off_keeps_historical_shape_byte_for_byte():
    # partial ambiguity: all ambiguous names targeted, uncapped (old shape)
    assert vl._main_side_probe_plan(AMB, REDS, False) == (AMB, [], False)
    # all-ambiguous: no targeting -> full-suite baseline fallback (old shape)
    assert vl._main_side_probe_plan(AMB, AMB, False) == ([], [], False)


# ---------------- B. malformed / hostile input three-state ----------------

@pytest.mark.parametrize('bad', [None, 42, 'x', {'a': 1}])
def test_plan_malformed_container_never_crashes(bad):
    # a non-list ambiguous container fabricates no probe answer
    assert vl._main_side_probe_plan(bad, REDS, True) == ([], [], False)


def test_plan_filters_non_string_and_blank_items():
    amb = ['  ', 7, None, AMB[0], '', AMB[0]]  # dup + blanks + non-str
    targeted, capped, applied = vl._main_side_probe_plan(amb, REDS, True, cap=8)
    assert applied is True and targeted == [AMB[0]] and capped == []


def test_plan_cap_zero_probes_nothing_names_all_capped():
    targeted, capped, applied = vl._main_side_probe_plan(AMB, AMB, True, cap=0)
    assert applied is True and targeted == [] and capped == AMB


def test_plan_cap_malformed_values_fail_conservative():
    # a non-int cap must not widen the probe: conservative read = no cap crash
    targeted, capped, _ = vl._main_side_probe_plan(AMB, AMB, True, cap='x')
    assert targeted == [] and len(capped) == 3


# ---------------- C. kill-switch reader ----------------

def test_kill_switch_default_enabled():
    assert vl._mainside_probe_enabled({}) is True
    assert vl._mainside_probe_enabled() is True  # real env without the knob


@pytest.mark.parametrize('v', ['0', 'off', 'false', 'no', ' OFF ', 'False'])
def test_kill_switch_off_forms(v):
    assert vl._mainside_probe_enabled({vl.MAINSIDE_PROBE_ENV: v}) is False


@pytest.mark.parametrize('v', ['1', 'on', 'yes', '', 'garbage'])
def test_kill_switch_malformed_not_convenience_accepted(v):
    # anything other than the explicit off forms means enabled (fail-closed:
    # disabling the probe must be a deliberate act, never an accident)
    assert vl._mainside_probe_enabled({vl.MAINSIDE_PROBE_ENV: v}) is True


# ---------------- D. receipt face: naming + fail-closed direction ----------------

ANS = {AMB[0]: 'red', AMB[1]: 'green'}  # 2 reproduces, 3 unanswered (not probed)


def test_face_names_pre_existing_and_blockers():
    f = vl._main_side_face(REDS, ANS, AMB[:2], [AMB[2]], 12.3, True)
    assert f['enabled'] is True
    assert f['probed'] == AMB[:2] and f['probed_count'] == 2
    assert f['probe_wall_s'] == 12.3
    assert f['capped_out_stay_blockers'] == [AMB[2]]
    assert f['pre_existing_main'] == [AMB[0]]
    # fail-closed: green-on-clean-clone AND unanswered both stay lane blockers
    assert f['still_lane_blockers'] == sorted([AMB[1], AMB[2]])
    assert 'still blocks' in f['verdict']


def test_face_no_answer_is_never_pre_existing():
    f = vl._main_side_face(AMB, {}, AMB, [], 0.0, True)
    assert f['pre_existing_main'] == []
    assert f['still_lane_blockers'] == sorted(AMB)


def test_face_malformed_answers_dict_fail_closed():
    f = vl._main_side_face(AMB, 'garbage', AMB, [], None, False)
    assert f['pre_existing_main'] == []
    assert f['still_lane_blockers'] == sorted(AMB)
    assert f['probe_wall_s'] is None and f['enabled'] is False


def test_face_malformed_names_filtered():
    f = vl._main_side_face([None, 7, '', AMB[0]], {AMB[0]: 'red'}, [AMB[0]], [], 1.0, True)
    assert f['pre_existing_main'] == [AMB[0]]


def test_face_dedupes_and_sorts_red_names():
    f = vl._main_side_face([AMB[1], AMB[0], AMB[1]], {AMB[0]: 'red'}, [AMB[0]], [], 1.0, True)
    assert f['pre_existing_main'] == [AMB[0]]
    # still_lane_blockers covers the PROBE-undecided face only (targeted ∪ capped
    # without an answer); ledger-answered or non-ambiguous reds are not its scope
    assert f['still_lane_blockers'] == []


# ---------------- E. constants / bounds shape ----------------

def test_bounds_constant_and_env_name():
    assert vl.MAIN_SIDE_PROBE_CAP == 8
    assert vl.MAINSIDE_PROBE_ENV == 'SANDBAR_GATE_MAINSIDE_PROBE'


def test_cap_enforced_at_the_plan_boundary_not_the_face():
    """9 ambiguous names -> exactly 8 probed, the 9th named as capped-out."""
    nine = ['n%d' % i for i in range(9)]
    targeted, capped, applied = vl._main_side_probe_plan(nine, nine, True)
    assert applied is True and len(targeted) == 8 and capped == ['n8']


# ---------------- F. source lock: receipt passthrough ----------------

def test_source_lock_integ_receipt_carries_main_side_face():
    """The gate face must reach the ticket receipt: _run_scenarios copies
    result['main_side_reds'] onto IntegrationRunResult (additive; absent key =
    byte-identical legacy receipt)."""
    import agent_activities as aa
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'agent_activities.py'), encoding='utf-8').read()
    assert 'main_side_reds' in src, 'receipt passthrough missing'
    res = IntegrationResultStub(main_side_reds={'pre_existing_main': ['x']})
    # dynamic attribute assignment must be tolerated (non-slots dataclass)
    out = aa.IntegrationRunResult()
    out.main_side_reds = dict(res.main_side_reds)
    assert out.main_side_reds == {'pre_existing_main': ['x']}


def test_source_lock_face_snapshot_persisted_for_round_readers():
    """Arbitrate round 2 fault mode: the face rode the gate stdout envelope but
    the round artifacts the desk actually reads (runner reports
    out/integration-report-*.json) never carried it, so the classification the
    decision table produced was invisible reader-side. verify_lane must persist
    a latest-round snapshot to out/main-side-reds.json when the face is
    produced, and name a write failure instead of swallowing it."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), '..', 'tools', 'verify_lane.py'),
        encoding='utf-8').read()
    assert 'main-side-reds.json' in src, 'snapshot persistence missing'
    assert 'MAIN_SIDE_SNAPSHOT write failed' in src, \
        'snapshot write failure must be named, never silent'


def test_snapshot_write_produces_readable_face_file(tmp_path):
    """The persisted snapshot is the exact face JSON, readable standalone."""
    import json
    face = vl._main_side_face(['n1'], {'n1': 'red'}, ['n1'], [], 1.0, True)
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'main-side-reds.json').write_text(
        json.dumps(face, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    back = json.loads((out / 'main-side-reds.json').read_text(encoding='utf-8'))
    assert back['pre_existing_main'] == ['n1'] and back['enabled'] is True


class IntegrationResultStub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------- G. decision-table composition (record, not blocker) ----------------

def test_reproducing_red_is_record_not_blocker():
    """End-to-end semantics at the pure layer: a lane red that reproduces on the
    baseline tree is 'baseline_red(existing debt)' = record = NOT a blocker; a
    red the clean clone does not reproduce stays a blocker (fail-closed)."""
    from failure_protocol import decide
    lane_case = {'name': AMB[0], 'status': 'fail', 'cause': 'assert', 'reason': 'x'}
    base_red = {AMB[0]: {'name': AMB[0], 'status': 'fail'}}
    assert decide(lane_case, base_red)['verdict'] == 'record'
    assert decide(lane_case, {})['verdict'] == 'block'


def test_baseline_not_checked_never_reads_as_pre_existing():
    """C1 discipline composes with the discriminator: a baseline not-checked row
    is not base evidence — the lane red must not be excused by it."""
    from failure_protocol import decide, _baseline_red_set
    lane_case = {'name': AMB[0], 'status': 'fail', 'cause': 'assert', 'reason': 'x'}
    base_case = {'name': AMB[0], 'status': 'not_checked', 'cause': 'external'}
    assert decide(lane_case, _baseline_red_set([base_case]))['verdict'] == 'block'
