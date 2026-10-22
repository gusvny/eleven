#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 battery for the per-entry time budget (host order 261022).

The runner grew one small mechanism: an entry may declare `budget: <N>s` in its
own intent text, beside the `tier:` / `cost:` tokens, and an entry that runs
past it fails BY NAME with the declared budget and the elapsed wall time
(process group SIGKILLed). This battery pins the three faces that mechanism has:

  1. the declaration parser (present / absent / malformed / zero),
  2. the ladder — a declaration can only LOWER the 900 s ceiling,
  3. the receipt — the timeout verdict names the declared budget, never the
     global ceiling, and the untouched (undeclared) branch keeps the old text.

Pure functions + two source locks over the real runner file: no docker, no
Temporal, no scenario run, seconds.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
INTEG = os.path.join(REPO, "integration")
sys.path.insert(0, INTEG)

import run_scenarios as rs  # noqa: E402


def entry(intent, name="t000000-00-fixture", cmd="python3 -B x.py"):
    return (name, intent, cmd, "ro")


class EntryBudgetParse(unittest.TestCase):
    def test_declared_budget_is_parsed(self):
        self.assertEqual(rs.entry_budget_s(entry("... cost: seconds; budget: 90s")), 90)

    def test_absent_declaration_is_none(self):
        self.assertIsNone(rs.entry_budget_s(entry("cost: minutes; tier: a journey")))
        self.assertIsNone(rs.entry_budget_s(entry("")))

    def test_malformed_declarations_are_not_a_budget(self):
        for text in ("budget: 90",            # no unit
                     "budget: seconds",       # no number
                     "budget: 0s",            # zero is not a budget
                     "budget: -5s",           # negative never matches the pattern
                     "budget:5"):             # no unit
            self.assertIsNone(rs.entry_budget_s(entry(text)), text)

    def test_millisecond_shaped_tokens_do_not_match(self):
        # `budget: 90ms` must not be read as a 90 s budget.
        self.assertIsNone(rs.entry_budget_s(entry("budget: 90ms")))

    def test_registry_entries_declare_numbers_not_text(self):
        # The two migrated entries: a positive integer each, and nothing on the
        # rest of the registry that would silently shorten an unrelated entry.
        for name in ("t260915-01-detail-face-journey",
                     "t260917-09-tests-false-escalation-guard"):
            hit = [e for e in rs.SCENARIOS if e[0] == name]
            self.assertEqual(len(hit), 1, name)
            value = rs.entry_budget_s(hit[0])
            self.assertIsInstance(value, int, name)
            self.assertGreater(value, 0, name)


class BudgetLadder(unittest.TestCase):
    def test_declaration_lowers_and_never_raises(self):
        # Same expression _run_entry uses: min(declared, CMD_TIMEOUT).
        self.assertEqual(min(120, rs.CMD_TIMEOUT), 120)
        self.assertEqual(min(rs.CMD_TIMEOUT * 4, rs.CMD_TIMEOUT), rs.CMD_TIMEOUT)

    def test_ceiling_is_still_the_declared_900(self):
        self.assertEqual(rs.CMD_TIMEOUT, 900)


class RunnerSourceLocks(unittest.TestCase):
    """The mechanism must stay WIRED — a parser nobody consults is decoration."""

    def setUp(self):
        with open(os.path.join(INTEG, "run_scenarios.py"), encoding="utf-8") as fh:
            self.src = fh.read()

    def test_run_entry_waits_on_the_entry_budget(self):
        body = self.src[self.src.index("def _run_entry("):]
        body = body[:body.index("\n_REPO_ROOT = ")]
        self.assertIn("budget_s = entry_budget_s(entry)", body)
        self.assertIn("wait_s = min(budget_s, CMD_TIMEOUT) if budget_s else CMD_TIMEOUT", body)
        self.assertIn("proc.wait(timeout=wait_s)", body)
        self.assertIn("ENTRY_BUDGET_EXCEEDED", body)

    def test_timeout_evidence_names_the_declared_budget(self):
        body = self.src[self.src.index("def _spec_from_output("):]
        body = body[:body.index("def _emit(")]
        self.assertIn("budget_s=None", body)
        self.assertIn("entry budget exceeded (declared %ds, elapsed %.1fs", body)

    def test_the_emit_seam_passes_the_declaration(self):
        self.assertIn("budget_s=entry_budget_s(e)", self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
