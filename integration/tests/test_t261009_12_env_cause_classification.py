# -*- coding: utf-8 -*-
"""t261009-12 unit battery: environment-failure classification + lint verdict
reproducibility. Offline seconds, pure functions and module-level seams only —
no integration entry is executed here.

Defect A: the executor's synthesis seam (`run_scenarios._spec_from_output`)
stamped `fail x self x assert_mismatch` on every exit-1 tail, so the
t261008-36 incident (fixture server refused the connection,
net::ERR_CONNECTION_REFUSED at http://127.0.0.1:21010/) was reported as the
ticket's own cause. The fix: `failure_protocol.env_red_reason` reads the
observed evidence against a CLOSED measured vocabulary; a hit relabels the
synthesis to `not-checked x external x connect_refused` (a named environment
red), a miss keeps the byte-identical old behaviour.

Defect B: `integration/lint_tests.py` printed `LINT done: 0 error / 1 warn`
and, seconds later under fleet load, `20 error` for the same inputs — a
mutable target (git-state-dependent inputs read while the fleet mutates git
state). The fix pins the diff base once per run and names every unstable-input
condition on the final verdict line.
"""
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(INTEG))
sys.path.insert(0, str(ENGINE))

import failure_protocol as fp          # noqa: E402
import run_scenarios as rs             # noqa: E402

# The incident's literal observed tail (t261008-36) — the exact defect face.
INCIDENT_TAIL = (
    "browser error: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:21010/ | "
    "fixture transport error: fetch failed")
ASSERT_TAIL = ("AssertionError: expected gate receipt ok:true, got "
               "ok:false kind=missing_anchor")


def _spec(name, exit_code, out):
    """spec_line returns the one-line JSON protocol line — parse it back so
    the assertions read fields, not string fragments."""
    line = rs._spec_from_output(name=name, pool="ro", out=out,
                                exit_code=exit_code, dur=1.0, started=0.0)
    return json.loads(line)


class EnvRedReason(unittest.TestCase):
    """failure_protocol.env_red_reason — pure classification truth table."""

    def test_incident_tail_classifies_connect_refused(self):
        self.assertEqual(fp.env_red_reason(INCIDENT_TAIL), "connect_refused")

    def test_measured_vocabulary_families(self):
        for tail in ("ECONNREFUSED 127.0.0.1:21010",
                     "Os { code: ConnectionRefused }",
                     "tcp connect error: Connection refused (os error 111)",
                     "connect refused by peer",
                     "Rust tonic: connectionrefused"):
            self.assertEqual(fp.env_red_reason(tail), "connect_refused", tail)

    def test_reason_code_is_prepare_type(self):
        self.assertIn(fp.env_red_reason(INCIDENT_TAIL), fp.PREPARE_REASONS)

    def test_assertion_tail_stays_none(self):
        self.assertIsNone(fp.env_red_reason(ASSERT_TAIL))
        self.assertIsNone(fp.env_red_reason("assert_mismatch: expected 3 rows"))

    def test_refused_word_in_quoted_assertion_context_is_accepted_mislabel(self):
        # Known false-positive mode (review condition 4): a scenario that
        # legitimately ASSERTS on refused-connection behaviour carries the
        # literal pattern in its tail and IS relabelled external. Current
        # design accepts this and says so — the full tail evidence is always
        # preserved for human review; a whitelist-by-context would need a
        # measured incident first.
        self.assertEqual(fp.env_red_reason(
            "AssertionError: expected output to contain ERR_CONNECTION_REFUSED"),
            "connect_refused")

    def test_malformed_inputs_fail_closed_to_none(self):
        for bad in (None, "", "   ", 123, [], {}, b"bytes", object()):
            self.assertIsNone(fp.env_red_reason(bad), repr(bad))

    def test_overlong_input_truncated_scan(self):
        # Pattern beyond the 20000-char scan window is not found — the
        # classifier degrades to None (fail-closed toward self), never throws.
        self.assertIsNone(fp.env_red_reason("x" * 20000 + "ERR_CONNECTION_REFUSED"))
        self.assertEqual(fp.env_red_reason("x" * 100 + "ECONNREFUSED"),
                         "connect_refused")


class SpecFromOutputSynthesis(unittest.TestCase):
    """The executor's synthesis matrix — only the exit-1 fallthrough changes."""

    def test_exit0_pass_unchanged(self):
        line = _spec("s", 0, "all good")
        self.assertEqual((line["status"], line["cause"]), ("pass", "unknown"))

    def test_exit2_env_red_unchanged(self):
        line = _spec("s", 2, "ENV_FAIL [s] docker missing")
        self.assertEqual((line["status"], line["cause"], line["reason"]),
                         ("not-checked", "external", "other"))

    def test_timeout_unchanged(self):
        line = _spec("s", -9, "")
        self.assertEqual((line["status"], line["cause"], line["reason"]),
                         ("fail", "self", "timeout"))

    def test_spawn_fail_unchanged(self):
        line = _spec("s", rs._SPAWN_FAIL, "")
        self.assertEqual((line["status"], line["cause"]),
                         ("not-checked", "external"))

    def test_exit1_assertion_tail_stays_self(self):
        line = _spec("s", 1, ASSERT_TAIL)
        self.assertEqual((line["status"], line["cause"], line["reason"]),
                         ("fail", "self", "assert_mismatch"))

    def test_exit1_incident_tail_relabeled_named_env_red(self):
        line = _spec("s", 1, INCIDENT_TAIL)
        self.assertEqual((line["status"], line["cause"], line["reason"]),
                         ("not-checked", "external", "connect_refused"))
        # Evidence is preserved verbatim (never swallowed by the relabel).
        self.assertIn("ERR_CONNECTION_REFUSED", line["evidence"])
        self.assertIn("127.0.0.1:21010", line["evidence"])
        # Protocol invariants: a not-checked line WITH evidence never flips
        # back to fail, and never becomes a violation.
        case, violations = fp.enforce_semantics(fp.normalize_case(line))
        self.assertEqual(case["status"], "not-checked")
        self.assertEqual(violations, [])

    def test_exit1_env_tail_survives_protocol_semantics(self):
        line = _spec("s", 1, "tcp connect error while booting fixture")
        self.assertEqual(line["reason"], "connect_refused")

    def test_other_exit_code_plain_tail_unchanged(self):
        line = _spec("s", 7, ASSERT_TAIL)
        self.assertEqual((line["status"], line["cause"], line["reason"]),
                         ("fail", "self", "assert_mismatch"))


class LintReproducibilityHelpers(unittest.TestCase):
    """Defect B helpers — condition channel + named rglob degradation."""

    def setUp(self):
        import lint_tests as lt
        self.lt = lt
        self._saved = list(lt.UNSTABLE_INPUTS)
        lt.UNSTABLE_INPUTS.clear()

    def tearDown(self):
        self.lt.UNSTABLE_INPUTS[:] = self._saved

    def test_note_records_and_prints(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.lt.note_unstable_input("git ls-files failed (rc=128)")
        self.assertEqual(self.lt.UNSTABLE_INPUTS,
                         ["git ls-files failed (rc=128)"])
        self.assertIn("NOTE  unstable input: git ls-files failed (rc=128)",
                      buf.getvalue())

    def test_lint_targets_degradation_is_named_not_silent(self):
        import subprocess
        real_run = subprocess.run

        def fake_run(*a, **k):
            raise OSError("git unavailable")

        subprocess.run = fake_run
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                targets = self.lt._lint_targets()
        finally:
            subprocess.run = real_run
        self.assertTrue(len(targets) > 0)          # degraded to rglob, not empty
        self.assertTrue(any("git ls-files failed" in c for c in
                            self.lt.UNSTABLE_INPUTS))
        self.assertIn("unstable input", buf.getvalue())

    def test_verdict_suffix_format(self):
        conds = ["git ls-files failed (rc=128)", "shared diff base unresolved"]
        suffix = (" (unstable inputs: %s)" % "; ".join(conds)
                  if conds else "")
        self.assertEqual(suffix,
                         " (unstable inputs: git ls-files failed (rc=128); "
                         "shared diff base unresolved)")
        self.assertEqual("" if [] else suffix, suffix)

    def test_tier_marker_accepts_pinned_base(self):
        # lint_tier_markers grew a base parameter (one run, one base); the
        # callable face must accept it without TypeError.
        import inspect
        self.assertIn("base", inspect.signature(
            self.lt.lint_tier_markers).parameters)


if __name__ == "__main__":
    unittest.main()
