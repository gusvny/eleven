#!/usr/bin/env python3
"""t261031-23 (KI-442) L1: the quickmanual gate round POINTS the ticket's own
scenario names, so a round that declares an own scenario also runs it.

The measured defect (t261031-06, blocked again on t261031-14): the ticket
delivered a new registered scenario and its gate round recorded

  own-scenario coverage failure (t261025-02): declared own scenario(s)
  t261031-06-refusal-survives-remount did NOT run this round

while the round ran exactly 1 case — the declared scope — and the receipt
carried `own_source.derived=[<that name>]`. `_quick_gate_round` passed the own
names through `_integ_run_args(own_names=...)` only: the runner's own face keeps
and exempts an own name, it never ADDS one to the run list. So the own proof
obligation was declared and never run, and the coverage check voided the pass.
The develop-buffer closing run had the same defect and was fixed by pointing
`closing_pointed_names(run_only, own_names)` (t261030-33); this battery pins the
same rule on the quickmanual path.

Coverage map (one case group per ticket requirement):
  A. THE UNION (pure): `dev_lane.quick_gate_pointed_names` — the declared scope
     ∪ the own names, order-stable, de-duplicated, blank/None never entering,
     an empty own set returning the declared scope unchanged;
  B. THE MODES: a scenario plan with one declared name and one derived name
     yields BOTH; check/battery plans keep their check scope and append the own
     name; the reserved full-gate plan points nothing (the full round stays
     full);
  C. THE ROUND (the real `_quick_gate_round`, activity transport stubbed): the
     `IntegrationRunArgs` the engine really sends carries the union on the
     pointed face AND the own names on the exemption face, an empty own set is
     byte-identical to the declared-only round, and an un-patched replay sends
     the declared scope alone (the recorded byte shape);
  D. THE RECEIPT: `own_source` and the new `pointed` key agree — every derived
     own name is pointed, so `shared.own_coverage_error` books NO violation on
     that receipt while the declared-only list books the incident's exact
     failure;
  E. SOURCE LOCKS: one union writer (the quickmanual helper calls
     `closing_pointed_names`; there is no second union loop), and the union sits
     behind its own `workflow.patched` id.

Offline, no Temporal, no docker, no browser, never touches 3099/7233, no case
runs. Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_23_own_pointed_gate.py -q
"""
from __future__ import annotations

import asyncio
import datetime
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))

import dev_lane  # noqa: E402
import shared  # noqa: E402

#: The declared scope of the incident round (the ticket's evidence declaration).
_NOW = datetime.datetime(2026, 10, 31, 12, 0, 0)

DECLARED = "t261011-15-dismiss-prompt-visible-long-list"
#: The derived own scenario of the incident round (registered by the ticket it
#: belonged to; the name is carried verbatim from the blocked receipt).
OWN = "t261031-06-refusal-survives-remount"


def _wf():
    """The quickmanual shell without a Temporal runtime (the round and the
    receipt are derivations over the activity result and the resolved plan)."""
    wf = object.__new__(dev_lane.QuickmanualLaneWorkflow)
    wf.ticket_id = "t261031-23-ut"
    wf.meta = {"worktree": "/tmp/t261031-23", "stage": "run_integration_tests",
               "workspace": {}, "base_ref": "deadbeef", "log": []}
    wf.gate_runs = []
    wf.results = {}
    wf._detail_face_on = False
    wf._gens = {}
    return wf


class _StubWorkflow:
    """The activity shell of the round: records the args, returns one result."""

    def __init__(self, result, union_patched=True):
        self.result = result
        self.calls = []
        self.union_patched = union_patched

    def patched(self, pid, *a, **k):
        # every other engine gate is on; THIS ticket's gate is the knob
        if pid == dev_lane.QUICK_OWN_POINTED_PATCH_ID:
            return self.union_patched
        return True

    def now(self):
        return _NOW

    async def execute_activity(self, _fn, args, **_kw):
        self.calls.append((_fn, args))
        return self.result


def _ir(**kw):
    base = dict(ran=1, passed=1, failed=0, env_fail=0, error="",
                details=[{"name": DECLARED, "cmd": "", "exit": 0,
                          "output_tail": ""}])
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _run(coro):
    """Run one coroutine on a PRIVATE event loop (a battery never depends on the
    ambient loop's state or on suite order)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def main_shape_only_reason():
    """t261031-34 (KI-447): is this tree's single writer MAIN-shaped for the
    un-patched replay payload?

    The un-patched branch of `_quick_gate_round` hands the DECLARED list to
    `_integ_run_args` — the single writer. What the payload then carries is the
    WRITER's rule, and the rule differs by tree shape: main's writer forwards the
    list unchanged, while a tree carrying t261029-18's line content unions the
    ticket's own names INSIDE the writer, so the union rides every call site,
    patched or not. "The un-patched replay sends the declared scope alone" is
    therefore a claim about a MAIN-SHAPED workflow; on a line-shaped tree the same
    history already recorded the union.

    Returns "" on a main-shaped tree and the NAMED reason on a line-shaped one.
    This is a decision the gate can read (pytest prints the reason), never a silent
    skip: the behavioural claim stays pinned by
    `test_unpatched_replay_payload_is_what_the_pre_patch_branch_records` on BOTH
    shapes.
    """
    wf = _wf()
    saved = dev_lane.workflow
    dev_lane.workflow = _StubWorkflow(_ir())   # the writer reads patched()/now() only
    try:
        sent = wf._integ_run_args([DECLARED], own_names=[OWN])
    except (TypeError, AttributeError):   # an older writer: no union in the writer
        return ""
    finally:
        dev_lane.workflow = saved
    if list(getattr(sent, "only_names", []) or []) == [DECLARED]:
        return ""
    return ("main-shape-only (t261031-34, KI-447): this tree's single writer "
            "_integ_run_args unions the ticket's own names into a pointed list "
            "(t261029-18 line content), so an un-patched replay of a history "
            "recorded on THIS shape carries the union too (%r); the main-shaped "
            "payload claim is pinned by "
            "test_unpatched_replay_payload_is_what_the_pre_patch_branch_records"
            % (list(getattr(sent, "only_names", []) or []),))


def _drive(scope, result=None, union_patched=True):
    """Drive the real gate round; return the args the engine sent."""
    wf = _wf()
    stub = _StubWorkflow(result if result is not None else _ir(),
                         union_patched=union_patched)
    saved = dev_lane.workflow
    dev_lane.workflow = stub
    try:
        _run(wf._quick_gate_round(scope))
    finally:
        dev_lane.workflow = saved
    assert len(stub.calls) == 1, "exactly one gate activity call"
    return stub.calls[0][1]


def _scope(**kw):
    sc = {"mode": "scenario", "names": [DECLARED], "only_names": [DECLARED],
          "own_names": [OWN],
          "own_source": {"derived": [OWN], "declared_in_write_set": []}}
    sc.update(kw)
    return sc


# ======================================================================
# A. The union (pure)
# ======================================================================

class TestPointedUnion:
    def test_scenario_plan_yields_the_declared_name_and_the_own_name(self):
        assert dev_lane.quick_gate_pointed_names(_scope()) == [DECLARED, OWN]

    def test_union_is_order_stable_and_de_duplicated(self):
        sc = _scope(only_names=["a", "b"], own_names=["b", "c", "a", "d"])
        assert dev_lane.quick_gate_pointed_names(sc) == ["a", "b", "c", "d"]
        # the declared order first, the own order after it, each name exactly once
        assert dev_lane.quick_gate_pointed_names(
            _scope(only_names=["b", "a"], own_names=["a", "b"])) == ["b", "a"]

    def test_blank_and_none_names_never_enter(self):
        sc = _scope(only_names=[" a ", "", None, "  "],
                    own_names=["", " ", None, "b"])
        assert dev_lane.quick_gate_pointed_names(sc) == ["a", "b"]

    def test_empty_own_set_returns_the_declared_list_unchanged(self):
        sc = _scope(own_names=[], own_source={})
        assert dev_lane.quick_gate_pointed_names(sc) == [DECLARED]
        # docs-only / un-declared rounds: nothing declared, nothing owned
        assert dev_lane.quick_gate_pointed_names(None) == []
        assert dev_lane.quick_gate_pointed_names({}) == []
        assert dev_lane.quick_gate_pointed_names(_scope(only_names=[],
                                                        own_names=[])) == []

    def test_malformed_scope_answers_no_narrowing(self):
        assert dev_lane.quick_gate_pointed_names([]) == []
        assert dev_lane.quick_gate_pointed_names("scenario") == []


# ======================================================================
# B. The modes
# ======================================================================

class TestPointedByMode:
    def test_check_mode_keeps_its_check_scope_and_appends_the_own_name(self):
        sc = _scope(mode="check", names=["test"], only_names=[], check="test",
                    pytest_node="", own_names=[OWN])
        assert dev_lane.quick_gate_pointed_names(sc) == [OWN]

    def test_battery_mode_keeps_its_pytest_scope_and_appends_the_own_name(self):
        node = "server/engine/tests/test_t261031_23_own_pointed_gate.py"
        sc = _scope(mode="battery", names=[node], only_names=[], check="test",
                    pytest_node=node, own_names=[OWN])
        pointed = dev_lane.quick_gate_pointed_names(sc)
        assert pointed == [OWN]
        # the check scope rides the plan itself, never the pointed list
        self_check = dict(sc)
        assert self_check["check"] == "test"
        assert self_check["pytest_node"] == node

    def test_check_mode_without_own_names_points_nothing(self):
        sc = _scope(mode="check", names=["test"], only_names=[],
                    check="test", own_names=[])
        assert dev_lane.quick_gate_pointed_names(sc) == []

    def test_full_mode_points_nothing_so_the_full_round_stays_full(self):
        # the reserved full-gate token: "everything" ∪ the own names is still
        # everything, and pointing names here would NARROW a full round
        sc = _scope(mode="full", names=["integ"], only_names=[], check="",
                    own_names=[OWN])
        assert dev_lane.quick_gate_pointed_names(sc) == []


# ======================================================================
# C. The round (the args the engine really sends)
# ======================================================================

class TestRoundSendsUnion:
    def test_scenario_round_points_both_and_keeps_the_exemption_face(self):
        args = _drive(_scope())
        assert args.only_names == [DECLARED, OWN], (
            "the own proof obligation must be POINTED, not only exempted")
        assert args.own_names == [OWN], (
            "own names stay on the exemption face too (pool / roster / reuse)")

    def test_empty_own_set_is_the_declared_round_byte_identical(self):
        args = _drive(_scope(own_names=[], own_source={}))
        assert args.only_names == [DECLARED]
        assert args.own_names == []

    def test_un_declared_round_stays_the_full_registry_round(self):
        args = _drive(None)
        assert args.only_names == []
        assert args.own_names == []
        assert args.quick_scope == {}

    def test_check_round_keeps_its_check_scope_and_points_the_own_name(self):
        sc = _scope(mode="check", names=["test"], only_names=[], check="test",
                    own_names=[OWN])
        args = _drive(sc)
        assert args.only_names == [OWN]
        assert args.quick_scope["check"] == "test"
        assert args.quick_scope["mode"] == "check"

    def test_unpatched_replay_sends_the_declared_scope_alone(self):
        # an in-flight history evaluates the new gate un-patched: the recorded
        # byte shape (declared scope only, own face as before) must come back.
        # t261031-34 (KI-447): this payload is a MAIN-SHAPED history's record — the
        # union of a line-shaped tree lives in the single writer, not at the call
        # site. The case is NAMED-skipped on such a tree, and the behavioural
        # claim stays pinned by the shape-independent case below.
        _why = main_shape_only_reason()
        if _why:
            pytest.skip(_why)
        args = _drive(_scope(), union_patched=False)
        assert args.only_names == [DECLARED]
        assert args.own_names == [OWN]

    def test_unpatched_replay_payload_is_what_the_pre_patch_branch_records(self):
        """The behavioural claim of the un-patched arm, pinned on BOTH code shapes.

        A history recorded before this ticket's gate replays exactly the call it
        recorded: the un-patched branch hands the DECLARED list to the single
        writer and never routes through the new union helper. The payload is then
        whatever that same tree's writer makes of that list — main's writer: the
        declared scope alone; a line-shaped writer: the same union it applied when
        the history was recorded. Either way this is a replay, not a new decision.
        """
        wf = _wf()
        sent = []
        real = wf._integ_run_args

        def _spy(only_names=(), own_names=()):
            sent.append(list(only_names))
            return real(only_names, own_names=own_names)

        wf._integ_run_args = _spy
        stub = _StubWorkflow(_ir(), union_patched=False)
        saved = dev_lane.workflow
        dev_lane.workflow = stub
        try:
            _run(wf._quick_gate_round(_scope()))
            recorded = real([DECLARED], own_names=[OWN])
        finally:
            dev_lane.workflow = saved
        assert sent == [[DECLARED]], (
            "the un-patched branch must hand the DECLARED list to the writer, "
            "never the union helper's output")
        assert stub.calls[0][1].only_names == list(recorded.only_names), (
            "the payload is exactly what this tree recorded for the same call")
        assert stub.calls[0][1].own_names == [OWN]


# ======================================================================
# D. The receipt agrees with own_source
# ======================================================================

class TestReceiptAgreement:
    def test_every_derived_own_name_is_pointed_on_the_receipt(self):
        wf = _wf()
        sc = _scope()
        rec = wf._quick_gate_receipt(_ir(), 0, sc)
        assert rec["pointed"] == [DECLARED, OWN]
        assert rec["own_source"]["derived"] == [OWN]
        for name in rec["own_source"]["derived"]:
            assert name in rec["pointed"], (
                "a declared own name that is not pointed is the incident shape")

    def test_the_pointed_list_books_no_coverage_violation(self):
        wf = _wf()
        rec = wf._quick_gate_receipt(_ir(), 0, _scope())
        assert shared.own_coverage_error(rec["own_source"]["derived"],
                                         rec["pointed"]) == ""

    def test_the_old_declared_only_list_books_the_incident_violation(self):
        # the control: the pre-ticket pointed list (declared scope only) is
        # exactly what the coverage check refused
        err = shared.own_coverage_error([OWN], [DECLARED])
        assert "own-scenario coverage failure (t261025-02)" in err
        assert OWN in err

    def test_a_full_round_receipt_points_nothing(self):
        wf = _wf()
        assert wf._quick_gate_receipt(_ir(), 0, None)["pointed"] == []
        assert wf._quick_gate_receipt(_ir(), 0, {})["pointed"] == []


# ======================================================================
# E. Source locks
# ======================================================================

class TestUnionSourceLocks:
    def _src(self):
        return (ENGINE / "dev_lane.py").read_text(encoding="utf-8")

    def test_there_is_one_union_writer(self):
        src = self._src()
        assert src.count("def closing_pointed_names") == 1
        # the quickmanual helper reuses it — no second union loop
        helper = src[src.index("def quick_gate_pointed_names"):]
        helper = helper[:helper.index("\ndef ")]
        assert "closing_pointed_names(declared" in helper
        assert "own_names" in helper

    def test_the_gate_call_is_behind_its_own_patch_id(self):
        src = self._src()
        assert ('QUICK_OWN_POINTED_PATCH_ID = "quickmanual-own-pointed-union-v1"'
                in src)
        start = src.index("async def _quick_gate_round")
        body = src[start:start + 6000]
        assert "workflow.patched(QUICK_OWN_POINTED_PATCH_ID)" in body
        assert "quick_gate_pointed_names(_sc)" in body
        assert "own_names=_own" in body

    def test_the_receipt_carries_the_pointed_face(self):
        src = self._src()
        start = src.index("def _quick_gate_receipt")
        body = src[start:start + 6000]
        assert '"pointed": quick_gate_pointed_names(quick_scope)' in body
