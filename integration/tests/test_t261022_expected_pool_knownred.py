#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 battery: the round's expected count against pool exclusion (261022).

Real red this pins (t260913-02 went red inside every full round): the round
injects ``SANDBAR_KNOWN_RED_EXCLUDE=1``, so every nested narrowed run carries
the roster. ``expected`` used to be

    len(SCENARIOS) - len(excluded_entries) - len(known_red_skipped)

and ``known_red_skipped`` is the roster **without** the pool-exclusion face, so
entries sitting in an excluded pool were deducted twice: excluding every pool
gave ``778 - 778 - 49 = -49``. A negative expectation fails the summary self
check and turns a zero-entry narrowed round into a product red.

The face under test is the pure ``expected_entries``; no docker, no Temporal,
no scenario run, no port.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
INTEG = os.path.join(REPO, "integration")
sys.path.insert(0, INTEG)

import run_scenarios as rs  # noqa: E402


def entry(name, pool="ro"):
    return (name, "intent text", "python3 -B x.py", pool)


MINI = [entry("a1"), entry("a2"), entry("b1", "main"),
        entry("c1", "engine"), entry("c2", "engine")]
ROSTER = ["a1", "c1"]          # one in ro, one in engine


class ExpectedCounts(unittest.TestCase):
    def test_no_exclusion_keeps_the_old_number(self):
        # 全表面：唯一变化是抠掉在册红（与旧式逐字同值）
        self.assertEqual(rs.expected_entries(MINI, [], ROSTER), 3)
        self.assertEqual(rs.expected_entries(MINI, [], []), 5)

    def test_all_pools_excluded_is_zero_never_negative(self):
        pools = sorted({rs.pool_of(e) for e in MINI})
        self.assertEqual(rs.expected_entries(MINI, pools, ROSTER), 0)

    def test_roster_inside_an_excluded_pool_is_not_deducted_twice(self):
        # engine 被排除：c1 已在排除面里（5 − 2），在册红只剩 a1 扣一次 => 2
        # 旧式会得 5 − 2 − 2 = 1（c1 被扣两次）
        self.assertEqual(rs.expected_entries(MINI, ["engine"], ROSTER), 2)
        # 排除 ro：a1 在排除面里（5 − 2），在册红只剩 c1 => 2
        self.assertEqual(rs.expected_entries(MINI, ["ro"], ROSTER), 2)
        # 对照：不排除任何池时两条在册红各扣一次
        self.assertEqual(rs.expected_entries(MINI, [], ROSTER), 3)

    def test_roster_entry_in_a_surviving_pool_is_deducted_once(self):
        self.assertEqual(rs.expected_entries(MINI, ["browser"], ROSTER), 3)

    def test_result_is_never_negative(self):
        self.assertEqual(rs.expected_entries(MINI, ["ro", "main", "engine"],
                                             ROSTER + ["a2", "b1"]), 0)

    def test_roster_naming_entries_outside_the_table_is_harmless(self):
        self.assertEqual(rs.expected_entries(MINI, ["engine"], ROSTER + ["ghost"]),
                         2)


class SourceLock(unittest.TestCase):
    """The runner must use the pure face, not an inline subtraction."""

    def test_main_uses_the_pure_face(self):
        src = open(os.path.join(INTEG, "run_scenarios.py"), encoding="utf-8").read()
        # t261025-02 caliber change (KI-355): the unpointed call site threads
        # the declared own set into the same pure face (the expected caliber
        # must equal the pool-split caliber); the no-inline-subtraction lock
        # itself is unchanged.
        self.assertIn("expected_entries(SCENARIOS, excluded, known_red_skipped,\n"
                      "                              own=own_set)", src)
        self.assertNotIn(
            "len(SCENARIOS) - len(excluded_entries) - len(known_red_skipped)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class OwnKeptCountedOnce(unittest.TestCase):
    """t261024-40: own-scenario entries the runner KEEPS despite pool exclusion /
    roster skip ride the pointed-round expected path (``len(registry)``), so an
    own-kept entry is counted exactly once and the ``ran + reused == expected``
    invariant holds. The behavior face lives in
    test_t260922_12_only_scenarios.py (test_own1/test_own2: ran==expected==1);
    this file pins the source shape so the pure-face path cannot silently grow
    a second own subtraction."""

    def test_pointed_expected_is_registry_length_with_own_kept_inside(self):
        src = open(os.path.join(INTEG, "run_scenarios.py"),
                   encoding="utf-8").read()
        # the pointed-round expected stays `len(registry)` — own-kept entries are
        # IN the registry by the time this line runs
        self.assertIn("expected = len(registry) if only_names", src)
        # no second own-scenario subtraction anywhere (counted once, or not at
        # all); the pool-split face keeps the own exemption, so an own-kept
        # entry is both counted AND scheduled
        self.assertNotIn("- len(own_", src)
        self.assertIn(
            "if excluded and pool_of(e) in excluded and e[0] not in own_set:",
            src)
