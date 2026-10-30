#!/usr/bin/env python3
"""t261024-40 L1: the own-scenario face threading (SANDBAR_SCENARIO_OWN).

The incident: a ticket whose own scenario sat in a cheap pool could be peeled
out of its gate run by the pool exclusion / the known-red roster skip, ending
in a ran=0 receipt with no green face — the anchor starved and the ticket
could never land. The fix, end to end:

  dev_lane (gate) --IntegrationRunArgs.own_names--> agent_activities (activity)
  --SANDBAR_SCENARIO_OWN--> integration/run_scenarios.py (runner exemption,
  pinned by integration/tests/test_t260922_12_only_scenarios.py and
  test_t261022_expected_pool_knownred.py — not re-asserted here).

This battery pins the ENGINE half: the args field default (replay safety),
the env injection, the receipt echo, the query-strip face, the gate call
shape, and the closing run's own face. Source locks follow the
test_t260923_targeted_rerun precedent; dataclass defaults are unit-tested
directly.

t261030-33 (arbitration): carrying the own list was not enough. Two closing
runs declared the ticket's own scenarios (own_names) while the POINTED list
held the fast set alone; the runner's own face keeps an already-pointed name
and never adds one, so the closing proof never ran and the coverage check
voided the pass. The closing pointed list is now the union (one pure function,
gated by a new patch id so old histories replay unchanged), and the drive test
below asserts the activity args the engine really sends.
"""
import asyncio
import datetime
import os
import sys
import unittest
from dataclasses import fields
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)

sys.path.insert(0, ENGINE)
import dev_lane  # noqa: E402
import shared  # noqa: E402

OWN_ENV = "SANDBAR_SCENARIO_OWN"


class ArgsDefault(unittest.TestCase):
    def test_own_names_default_empty_old_payloads_decode(self):
        fs = {f.name: f for f in fields(shared.IntegrationRunArgs)}
        self.assertIn("own_names", fs)
        self.assertEqual(fs["own_names"].default_factory(), [],
                         "defaulted: old payloads and replays decode unchanged")

    def test_old_construction_still_valid(self):
        a = shared.IntegrationRunArgs(ticket_id="t", worktree="/w")
        self.assertEqual(a.only_names, [])
        self.assertEqual(a.own_names, [])


class WiringLocks(unittest.TestCase):
    def test_activity_injects_and_echoes_the_own_face(self):
        act = open(os.path.join(ENGINE, "agent_activities.py"),
                   encoding="utf-8").read()
        # injection (same mode as SANDBAR_SCENARIO_ONLY; empty = no env = zero drift)
        self.assertIn('_extra_env["%s"] = ",".join(own_names)' % OWN_ENV, act)
        self.assertIn("own_names=list(getattr(args, \"own_names\", None) or [])",
                      act)
        # receipt echo (additive dynamic attribute)
        self.assertIn("out.own_names = list(own_names)", act)
        # the declaration query strip face pops the knob so the query can
        # never silently narrow its own registry view
        self.assertIn('"%s"' % OWN_ENV, act)

    def test_gate_carries_own_and_closing_does_not(self):
        # t261025-02 caliber change (KI-355): the closing run now CARRIES the
        # own face behind its own patch id — a ticket's own proof obligation
        # does not retire at closing. The declared-caliber change is pinned in
        # test_t261025_02_own_gate_run.py; this lock keeps the un-patched
        # replay shape (no own list where history has none).
        dev = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
        # single-writer builder accepts the own face (defaulted)
        self.assertIn("def _integ_run_args(self, only_names=(), own_names=()):",
                      dev)
        self.assertIn("own_names=list(own_names or []))", dev)
        # gate main run carries the derived own face
        self.assertIn("own_names=_own_face_names)", dev)
        self.assertIn('_own_face_names = []', dev)
        # the closing run passes an own list ONLY behind the t261025-02 patch
        # id — an un-patched replay passes none (the historical byte shape)
        closing = dev[dev.index("async def _closing_full_run"):
                      dev.index("async def _closing_full_run") + 5000]
        self.assertIn("T261025_02_OWN_CLOSING_PATCH_ID", closing)
        self.assertIn("own_names=_closing_own", closing)

    def test_planner_folds_the_derivation_note(self):
        dev = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
        self.assertIn("def scoped_feedback_plan(own_names, prev_red_names=(), "
                      "derivation_note=\"\")", dev)
        # the gate caller passes the own-set evidence (query error + counts)
        self.assertIn("derivation_note=(\n", dev)
        self.assertIn("expected-source=integration/", dev)


NOW = datetime.datetime(2026, 10, 30, 12, 0, 0)
_NOOP = lambda *a, **k: None  # noqa: E731


class ClosingPointedUnion(unittest.TestCase):
    """The closing POINTED list = the declared fast set ∪ the ticket's own scenarios.

    The drive test uses the REAL `_closing_full_run` with only the activity
    transport and the clock stubbed: the assertion reads the IntegrationRunArgs
    the engine really sends, so a future edit that stops pointing the own names
    fails here (the t261024-40 lock pinned only the own_names= argument, which is
    exactly why the gap stayed invisible for two closing attempts).
    """

    def _drive(self, own_members, union_patched=True, own_patched=True):
        calls = []

        class _Stub:
            def patched(self, pid):
                # every other gate is on; the two closing gates are the knobs
                if pid == dev_lane.OWN_CLOSING_UNION_PATCH_ID:
                    return union_patched
                if pid == dev_lane.T261025_02_OWN_CLOSING_PATCH_ID:
                    return own_patched
                return True

            def now(self):
                return NOW

            logger = SimpleNamespace(info=_NOOP, warning=_NOOP, warn=_NOOP)

            def upsert_memo(self, *a, **k):
                pass

            def sleep(self, *a, **k):
                pass

            async def execute_activity(self, name, args, **kw):
                calls.append((name, args))
                if name is dev_lane.fast_set_declaration:
                    return SimpleNamespace(members=["fast-a", "fast-b"],
                                           own_members=list(own_members), error="")
                return shared.IntegrationRunResult(
                    ran=2, passed=2, failed=0, env_fail=0, details=[], error="")

        old = dev_lane.workflow
        dev_lane.workflow = _Stub()
        try:
            wf = object.__new__(dev_lane.DevLaneWorkflow)
            wf.meta = {"lane_version": "develop-buffer-v1", "worktree": "/tmp/wt",
                       "log": [], "stage": "run_integration_tests",
                       "write_set": ["server/engine/dev_lane.py"], "handoffs": []}
            wf.ticket_id = "t-ut"
            wf._gens = {"run_integration_tests": 1}
            wf.timeline = []
            asyncio.run(wf._closing_full_run())
        finally:
            dev_lane.workflow = old
        run_args = [a for n, a in calls if n is dev_lane.run_integration_tests]
        self.assertEqual(len(run_args), 1, "exactly one closing activity call")
        return run_args[0], (wf.meta.get("closing_run_face") or {})

    def test_closing_points_the_own_names_too(self):
        args, _face = self._drive(["own-1", "own-2"])
        self.assertEqual(args.only_names, ["fast-a", "fast-b", "own-1", "own-2"],
                         "the own proof obligation must be POINTED, not declared only")
        self.assertEqual(args.own_names, ["own-1", "own-2"])

    def test_the_face_records_what_was_pointed(self):
        _args, face = self._drive(["own-1"])
        self.assertEqual(face["own"], ["own-1"])
        self.assertEqual(face["pointed"], ["fast-a", "fast-b", "own-1"],
                         "the face must say whether the own proof was pointed")
        self.assertEqual(face["members"], ["fast-a", "fast-b"])

    def test_closing_does_not_duplicate_an_own_name_already_pointed(self):
        args, _face = self._drive(["own-1", "fast-a"])
        self.assertEqual(args.only_names, ["fast-a", "fast-b", "own-1"])

    def test_unpatched_replay_passes_the_fast_set_alone(self):
        # an in-flight history evaluates the new gate un-patched: the recorded
        # byte shape (fast set only) must come back
        args, _face = self._drive(["own-1"], union_patched=False)
        self.assertEqual(args.only_names, ["fast-a", "fast-b"])
        self.assertEqual(args.own_names, ["own-1"])

    def test_history_without_the_own_gate_keeps_both_faces_empty(self):
        args, _face = self._drive(["own-1"], own_patched=False)
        self.assertEqual(args.only_names, ["fast-a", "fast-b"])
        self.assertEqual(args.own_names, [])


class ClosingPureUnion(unittest.TestCase):
    """The one pure function behind the closing list (order-stable, dedup, blank-safe)."""

    def test_union_keeps_order_and_dedups(self):
        self.assertEqual(dev_lane.closing_pointed_names(["a", "b"], ["b", "c"]),
                         ["a", "b", "c"])

    def test_union_tolerates_malformed_input(self):
        self.assertEqual(dev_lane.closing_pointed_names(None, None), [])
        self.assertEqual(dev_lane.closing_pointed_names([" a ", "", None], ["  ", "b"]),
                         ["a", "b"])

    def test_the_closing_call_uses_the_union_behind_its_own_gate(self):
        dev = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
        _start = dev.index("async def _closing_full_run")
        _rest = dev[_start + 10:]
        _end = min([_rest.index(mark) for mark in ("\n    async def ", "\n    def ")
                    if mark in _rest] or [len(_rest)])
        closing = dev[_start:_start + 10 + _end]
        self.assertIn("OWN_CLOSING_UNION_PATCH_ID", closing)
        self.assertIn("closing_pointed_names(_cplan.run_only, _closing_own)", closing)
        self.assertIn("self._integ_run_args(_closing_only, own_names=_closing_own)",
                      closing)


if __name__ == "__main__":
    unittest.main()
