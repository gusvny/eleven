#!/usr/bin/env python3
"""Unit battery for the L25 wait-bound lint core + the lint --rules selector
(t261011-22). Pure faces only — no git, no subprocess, no repo writes.

Covers the borrowed-implementation fault modes declared in
integration/lib_wait_bound.py's ledger (review discipline): malformed diff
text is TOTAL, context/deleted lines are never judged, the SANCTIONED-WAIT
escape is reachable on the same line or the line above, and every defect
names WHICH pattern matched.
"""
import io
import sys
import unittest
from pathlib import Path

INTEG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INTEG))

import lib_wait_bound as wb  # noqa: E402
import lint_tests  # noqa: E402  (module import is safe: side effects are the
# PYC tmpdir with its atexit reclaim and the lib_fault_injection import)


def _diff(*lines):
    return "\n".join(lines) + "\n"


def _added(diff_text):
    return [(p, n, name) for p, n, name, _t in wb.added_wait_defects(diff_text)]


class WaitBoundTruthTable(unittest.TestCase):
    def test_deadline_literal_red(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+SCEN = make(deadline=600)"  # SANCTIONED-WAIT: unit fixture line, never executed
                  )
        self.assertEqual(_added(d), [("integration/x/sc_a.py", 1, "deadline")])

    def test_timeout_literal_red(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+r = subprocess.run(cmd, timeout=1200)"  # SANCTIONED-WAIT: unit fixture line, never executed
                  )
        self.assertEqual(_added(d), [("integration/x/sc_a.py", 1, "timeout")])

    def test_sleep_literal_red(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+    time.sleep(30)"  # SANCTIONED-WAIT: unit fixture line, never executed
                  )
        self.assertEqual(_added(d), [("integration/x/sc_a.py", 1, "sleep")])

    def test_small_bounds_clean(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+wait_bound_ms=1000; deadline=60; timeout=99; sleep(9)")
        self.assertEqual(_added(d), [])

    def test_sanction_same_line(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+r = run(cmd, timeout=300)  # SANCTIONED-WAIT: child hard-kill ceiling")
        self.assertEqual(_added(d), [])

    def test_sanction_previous_line(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+# SANCTIONED-WAIT: quoted fixture constant, never slept to",
                  "+doc = 'the old code used timeout=1200 here'")
        self.assertEqual(_added(d), [])

    def test_context_and_deleted_lines_never_judged(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1,3 +1,3 @@",
                  # SANCTIONED-WAIT: battery fixture string, judged only in synthetic diffs
                  " old = deadline=600 stays",
                  # SANCTIONED-WAIT: battery fixture string, judged only in synthetic diffs
                  "-removed = timeout=900",
                  "+clean = 1")
        self.assertEqual(_added(d), [])

    def test_out_of_scope_paths_never_judged(self):
        d = _diff("+++ b/server/engine/tests/test_x.py", "@@ -1 +1 @@",
                  "+wait(deadline=600)"  # SANCTIONED-WAIT: battery fixture string, judged only in synthetic diffs
                  )
        self.assertEqual(_added(d), [])

    def test_defect_line_names_which_pattern_and_the_line(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                  "+poll(deadline=600)"  # SANCTIONED-WAIT: unit fixture line, never executed
                  )
        items = list(wb.added_wait_defects(d))
        self.assertEqual(len(items), 1)
        path, lineno, name, text = items[0]
        self.assertEqual((path, lineno, name), ("integration/x/sc_a.py", 1, "deadline"))
        self.assertIn("deadline=600", text)  # SANCTIONED-WAIT: unit fixture line, never executed

    def test_malformed_diff_text_is_total(self):
        for bad in ("", None, "not a diff at all", "+++ b/\n@@ +@+\n+++",
                    _diff("+++ b/integration/x/sc_a.py", "@@ -1 +1 @@",
                          "+deadline=600"  # SANCTIONED-WAIT: unit fixture line, never executed
                          )):
            try:
                list(wb.added_wait_defects(bad))
            except Exception as e:  # noqa: BLE001 — the face under test
                self.fail("added_wait_defects raised on %r: %s" % (bad, e))

    def test_line_numbering_across_hunks(self):
        d = _diff("+++ b/integration/x/sc_a.py", "@@ -10 +10 @@", "+a=1",
                  "@@ -90 +90 @@",
                  "+deadline=600"  # SANCTIONED-WAIT: unit fixture line, never executed
                  )
        self.assertEqual(_added(d), [("integration/x/sc_a.py", 90, "deadline")])


class SanctionShape(unittest.TestCase):
    def test_sanction_without_reason_still_sanctions_shape_only(self):
        # shape-only rule: the marker's presence is mechanical; the truth of
        # the reason text is a human review row, never judged here.
        self.assertTrue(wb.sanctioned("x = timeout=600  # SANCTIONED-WAIT:"))
        self.assertFalse(wb.sanctioned("x = timeout=600"))
        self.assertFalse(wb.sanctioned(None, None))
        self.assertTrue(wb.sanctioned(None, "# SANCTIONED-WAIT: above"))

    def test_hits_total_on_none(self):
        self.assertEqual(wb.wait_bound_hits(None), [])


class RulesSelector(unittest.TestCase):
    def test_valid_subset_sorted_deduped(self):
        self.assertEqual(lint_tests.parse_rules_arg(["--rules=L17,L16,L17"]),
                         (["L16", "L17"], []))

    def test_no_flag_means_full_battery(self):
        self.assertEqual(lint_tests.parse_rules_arg(["--lf", "x"]), (None, []))

    def test_unknown_rule_is_a_named_error(self):
        ids, bad = lint_tests.parse_rules_arg(["--rules=L16,L99"])
        self.assertIsNone(ids)
        self.assertTrue(any("L99" in b for b in bad))

    def test_empty_value_and_empty_item_are_named_errors(self):
        self.assertIsNone(lint_tests.parse_rules_arg(["--rules="])[0])
        _, bad = lint_tests.parse_rules_arg(["--rules=L16,,L17"])
        self.assertTrue(any("empty item" in b for b in bad))

    def test_repeated_flag_is_a_named_error(self):
        _, bad = lint_tests.parse_rules_arg(["--rules=L16", "--rules=L17"])
        self.assertTrue(any("repeated" in b for b in bad))

    def test_dispatch_table_declares_the_planted_rules(self):
        for rid in ("L16", "L17", "L18"):
            self.assertIn(rid, lint_tests.RULES)
        self.assertIn("L25", lint_tests.RULES)


if __name__ == "__main__":
    unittest.main()
