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
shape, and the closing run carrying NO own face (the closing contract is the
fast set). Source locks follow the test_t260923_targeted_rerun precedent;
dataclass defaults are unit-tested directly.
"""
import os
import sys
import unittest
from dataclasses import fields

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)

sys.path.insert(0, ENGINE)
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


if __name__ == "__main__":
    unittest.main()
