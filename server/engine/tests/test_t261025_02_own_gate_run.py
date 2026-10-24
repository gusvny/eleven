#!/usr/bin/env python3
"""t261025-02 L1: the gate's POOL EXCLUSION never drops the ticket's OWN
scenario (KI-355).

The incident: t261022-12 (own scenario in the ENGINE pool) and t261022-14 (own
scenario in BROWSER-FREE) stayed green-apart-from-gate and could never land —
two promoted engine fixes (t261024-40 / t261024-60) moved nothing because the
peel lives on the EXCLUSION side, in three seams the earlier tickets left
unhandled:

  D1  the unpointed expected caliber subtracted excluded pools WHOLESALE while
      the pool split KEEPS own entries -> the ran+reused==expected invariant
      self-reds exactly on tickets whose own scenario lives in engine/exclusive;
  D2  the closing run passed NO own list (the closing caliber was "the fast
      set only");
  D3  a stale LANE copy of run_scenarios.py ignores SANDBAR_SCENARIO_OWN
      entirely -> the declared own scenario is silently peeled -> ran=0 forever;
  D4  nothing anywhere asserted that the DECLARED own names actually ran.

This battery pins the pure faces (D1/D3/D4) and source-locks the wiring (D2,
the capability probe, the coverage refusal). The runner's end-to-end behavior
is owned by integration/t261025-02/sc_t261025_02_own_never_peeled.py (grey-box
L3) — not re-asserted here. Malformed-input cases are mandatory (external
inputs: env knobs, lane runner text, receipt rows).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
INTEG = os.path.dirname(os.path.dirname(ENGINE))

sys.path.insert(0, ENGINE)
import shared  # noqa: E402

sys.path.insert(0, os.path.join(INTEG, "integration"))
import run_scenarios as rs  # noqa: E402  (import builds the registry, runs nothing)


def _entry(name, pool):
    return (name, "mini fixture entry (t261025-02)",
            "python3 integration/t261025-02/fx_%s.py" % name, pool)


class ExpectedEntriesOwnCaliber(unittest.TestCase):
    """D1: the expected caliber must be the same caliber as the pool split."""

    SPEC = [_entry("own-eng", "engine"),      # own, lives in the excluded pool
            _entry("own-bf", "browser-free"),  # own, cheap pool, not excluded
            _entry("other", "engine"),         # NOT own, excluded pool
            _entry("plain", "main")]

    def test_own_in_excluded_pool_stays_in_expected(self):
        # the split keeps own-eng; expected must count it too (the incident)
        n = rs.expected_entries(self.SPEC, ["engine", "exclusive"], [],
                                own={"own-eng"})
        self.assertEqual(n, 3)  # own-eng + own-bf + plain

    def test_non_own_excluded_entries_stay_subtracted(self):
        # docker/known-red-style exclusion economy untouched for non-own cases
        n = rs.expected_entries(self.SPEC, ["engine", "exclusive"], [],
                                own=set())
        self.assertEqual(n, 2)  # own-bf + plain

    def test_default_own_empty_is_byte_identical_legacy(self):
        self.assertEqual(
            rs.expected_entries(self.SPEC, ["engine"], []),
            rs.expected_entries(self.SPEC, ["engine"], [], own=set()))
        self.assertEqual(rs.expected_entries(self.SPEC, [], []),
                         len(self.SPEC))

    def test_no_exclusion_legacy_value(self):
        self.assertEqual(rs.expected_entries(self.SPEC, [], []),
                         4)

    def test_known_red_subtraction_untouched(self):
        n = rs.expected_entries(self.SPEC, [], ["plain"], own={"own-eng"})
        self.assertEqual(n, 3)
        # an own name in the roster is not double-counted either way: the
        # split/skip site already exempts own from the roster
        n2 = rs.expected_entries(self.SPEC, [], ["own-eng"], own={"own-eng"})
        self.assertEqual(n2, 3)

    def test_never_negative(self):
        self.assertEqual(rs.expected_entries([], ["engine"], [], own={"x"}), 0)

    def test_malformed_own_items_never_raise(self):
        n = rs.expected_entries(self.SPEC, ["engine"], [],
                                own={"own-eng", "", None, 7})
        self.assertEqual(n, 3)


class OwnCoverageError(unittest.TestCase):
    """D4: declared own names must appear among the executed names."""

    def test_covered_is_empty_string(self):
        self.assertEqual(
            shared.own_coverage_error(["a", "b"], ["a", "b", "c"]), "")

    def test_missing_is_named(self):
        err = shared.own_coverage_error(["own-eng"], ["other"])
        self.assertIn("own-eng", err)
        self.assertIn("t261025-02", err)
        self.assertIn("KI-355", err)

    def test_empty_declaration_is_vacuously_covered(self):
        # docs-only / un-declared rounds keep the old behavior byte-identically
        self.assertEqual(shared.own_coverage_error([], ["x"]), "")
        self.assertEqual(shared.own_coverage_error(None, None), "")

    def test_malformed_inputs_never_raise(self):
        # executed_names given as a plain string iterates per character (a
        # declared name "a" is covered by "ab"; a multi-char name is not —
        # either way no raise, and the verdict is deterministic)
        self.assertEqual(shared.own_coverage_error([None, 7, "  ", "a"], "ab"), "")
        self.assertIn("ab", shared.own_coverage_error(["ab"], [None, "x"]))

    def test_whitespace_and_dup_names(self):
        self.assertEqual(shared.own_coverage_error([" a "], ["a"]), "")


class LaneRunnerKnobProbe(unittest.TestCase):
    """D3: a stale lane runner copy must be refused by name, but ONLY when the
    round actually declares own names (review_plan condition 1: a probe that
    fires regardless wedges every docs-only ticket on a stale lane)."""

    def test_text_with_knob_is_capable(self):
        self.assertFalse(shared.lane_runner_lacks_own_knob(
            "x = 1\n# rides " + shared.OWN_KNOB_RUNNER_MARKER + "\n"))

    def test_text_without_knob_lacks_it(self):
        self.assertTrue(shared.lane_runner_lacks_own_knob("print('hi')\n"))

    def test_unreadable_or_empty_text_never_refuses(self):
        # the round fails on its own downstream; the probe never invents a
        # second failure cause from its own blindness
        self.assertFalse(shared.lane_runner_lacks_own_knob(""))
        self.assertFalse(shared.lane_runner_lacks_own_knob(None))

    def test_malformed_input_never_raises(self):
        self.assertFalse(shared.lane_runner_lacks_own_knob(12345))


class ResultFields(unittest.TestCase):
    def test_receipt_fields_defaulted_replay_safe(self):
        r = shared.IntegrationRunResult()
        self.assertEqual(r.own_declared, [])
        self.assertEqual(r.own_missing, [])
        self.assertEqual(r.own_coverage_error, "")


class WiringLocks(unittest.TestCase):
    """Source-shape locks (test_t260923_targeted_rerun precedent)."""

    def test_activity_probe_gated_on_nonempty_declared(self):
        act = open(os.path.join(ENGINE, "agent_activities.py"),
                   encoding="utf-8").read()
        # the probe sits AFTER the own_names normalization and inside `if own_names`
        self.assertIn("if shared.lane_runner_lacks_own_knob(_runner_text):", act)
        self.assertIn('shared.OWN_KNOB_RUNNER_MARKER', act)
        self.assertIn("own_coverage_error=_probe_err)", act)

    def test_activity_coverage_compares_declared_not_derived(self):
        act = open(os.path.join(ENGINE, "agent_activities.py"),
                   encoding="utf-8").read()
        # review_plan condition 2: the coverage check reads the round's
        # DECLARED list (out.own_declared), never a re-derived set
        self.assertIn("out.own_declared = list(own_names)", act)
        self.assertIn("shared.own_coverage_error(\n            out.own_declared",
                      act)
        # a covered-less round turns the receipt into a NAMED failure
        self.assertIn("if out.own_coverage_error and not out.error:", act)

    def test_runner_call_site_passes_own_set(self):
        src = open(os.path.join(INTEG, "integration", "run_scenarios.py"),
                   encoding="utf-8").read()
        self.assertIn(
            "else expected_entries(SCENARIOS, excluded, known_red_skipped,\n"
            "                              own=own_set)", src)
        # the narrowed-empty fallback face keeps own entries too (named face
        # marker; the runner's own line copy stays CJK by the legacy-copy rule)
        self.assertIn("INTEG_OWN_KEPT", src)
        self.assertIn("fallback keeps the own scenario (named)", src)

    def test_closing_carries_own_behind_patch_id(self):
        dev = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
        self.assertIn('T261025_02_OWN_CLOSING_PATCH_ID = '
                      '"t261025-02-own-gate-run-v1"', dev)
        closing = dev[dev.index("async def _closing_full_run"):
                      dev.index("async def _closing_full_run") + 5000]
        self.assertIn("workflow.patched(T261025_02_OWN_CLOSING_PATCH_ID)",
                      closing)
        self.assertIn("own_names=_closing_own", closing)
        self.assertIn('"own": list(_closing_own)', closing)


if __name__ == "__main__":
    unittest.main()
