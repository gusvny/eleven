#!/usr/bin/env python3
"""Unit tests for the period-x-face coverage projection (t261009-49,
KI-01M4GGFXPAHDGSQ9767VMB5NGM).

Truth source = plan gen1 (approved): five states (produced / blocked / failed /
not_run / unreadable), the blocked shell never reads produced (R2 regression pin,
t261002-12 shape), row population = one row per declared instance per period (R3),
fail-loud degradation for unreadable ledgers / missing or malformed / raising attempt
readers. All inputs are fixed stub files — no external sources.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspection_aggregate as agg  # noqa: E402

INST = "integration-tests"
FACE = "test"


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="coverage-test-")

    # ---- fixtures ----

    def ledger(self, period, doc):
        (Path(self.dir) / ("inspection-%s-%s.json" % (INST, period))).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def served(self, period, findings=None):
        self.ledger(period, {"ticket_id": "t260101-01", "kind": "inspection",
                             "instance_id": INST, "period": period,
                             "findings": findings or [], "summary": {}})

    def rows(self, periods, attempts=None):
        cov = agg.face_coverage(INST, FACE, self.dir, periods, attempts)
        return cov, {r["period"]: r for r in cov["rows"]}

    # ---- state: produced ----

    def test_produced_all_green_and_with_findings(self):
        # An all-green served ledger IS a produced result (heartbeat proof).
        self.served("20261008")
        self.served("20261009", [{"id": "F1", "severity": "high", "scan": "dup",
                                  "subject": "s", "evidence": "e", "suggestion": "f"}])
        cov, by = self.rows(["20261008", "20261009"])
        self.assertEqual(by["20261008"]["result"], "produced")
        self.assertEqual(by["20261009"]["result"], "produced")
        self.assertEqual(cov["produced_nothing"], [])
        # last_ok_period = newest strictly-earlier produced period.
        self.assertEqual(by["20261009"]["last_ok_period"], "20261008")

    # ---- state: blocked (R2 regression pin, t261002-12 shape) ----

    def test_blocked_shell_never_reads_produced(self):
        # Readable doc + matching ticket_id + non-empty blocked_reason + zero served
        # findings = the blocked shell: ran but produced nothing.
        self.ledger("20261008", {"ticket_id": "t261002-12", "findings": [],
                                 "blocked_reason": "inspect stage refused the report"})
        cov, by = self.rows(["20261008"])
        self.assertEqual(by["20261008"]["result"], "blocked")
        self.assertEqual(by["20261008"]["last_ok_period"], "never")
        self.assertEqual(by["20261008"]["attempts"][0]["ticket_id"], "t261002-12")
        self.assertEqual([r["result"] for r in cov["produced_nothing"]], ["blocked"])

    def test_blocked_shell_after_a_produced_period_carries_last_ok(self):
        self.served("20261007")
        self.ledger("20261008", {"ticket_id": "t261002-12", "findings": [],
                                 "blocked_reason": "refused"})
        _, by = self.rows(["20261007", "20261008"])
        self.assertEqual(by["20261008"]["result"], "blocked")
        self.assertEqual(by["20261008"]["last_ok_period"], "20261007")

    # ---- state: failed vs not_run (different facts, different rows) ----

    def test_failed_three_attempts_versus_not_run_zero_attempts(self):
        def attempts(period):
            return [{"ticket_id": "t260918-01", "state": "FAILED", "blocked_reason": ""},
                    {"ticket_id": "t260919-01", "state": "FAILED", "blocked_reason": ""},
                    {"ticket_id": "t261008-09", "state": "TIMED_OUT", "blocked_reason": ""}]
        covf, byf = self.rows(["20260918"], attempts)
        self.assertEqual(byf["20260918"]["result"], "failed")
        self.assertEqual(len(byf["20260918"]["attempts"]), 3)
        self.assertFalse(byf["20260918"]["attempts_unavailable"])

        covn, byn = self.rows(["20260918"], None)
        self.assertEqual(byn["20260918"]["result"], "not_run")
        self.assertTrue(byn["20260918"]["attempts_unavailable"])
        self.assertFalse(covn["attempts_available"])
        self.assertTrue(covf["attempts_available"])
        # Zero-attempt and three-failed-attempts must not read the same.
        self.assertNotEqual(byf["20260918"]["result"], byn["20260918"]["result"])

    def test_never_is_explicit(self):
        _, by = self.rows(["20261008"], lambda p: [{"ticket_id": "t1", "state": "FAILED",
                                                    "blocked_reason": ""}])
        self.assertEqual(by["20261008"]["last_ok_period"], "never")

    # ---- state: unreadable (fail loud, never silent green) ----

    def test_unreadable_ledger_named(self):
        (Path(self.dir) / ("inspection-%s-20261008.json" % INST)).write_text("{not json", encoding="utf-8")
        _, by = self.rows(["20261008"])
        self.assertEqual(by["20261008"]["result"], "unreadable")

    def test_non_dict_ledger_named(self):
        (Path(self.dir) / ("inspection-%s-20261008.json" % INST)).write_text("[1,2]", encoding="utf-8")
        _, by = self.rows(["20261008"])
        self.assertEqual(by["20261008"]["result"], "unreadable")

    def test_served_shape_bar_doc_without_findings_list_named_unreadable(self):
        # A dict without a findings list and without blocked_reason is malformed on
        # this face too (same bar as read_period_ledgers) — never produced.
        self.ledger("20261008", {"ticket_id": "t1", "summary": {}})
        _, by = self.rows(["20261008"])
        self.assertEqual(by["20261008"]["result"], "unreadable")

    # ---- attempt-reader fault modes ----

    def test_raising_reader_degrades_named(self):
        def attempts(period):
            raise RuntimeError("boom")
        cov, by = self.rows(["20261008"], attempts)
        self.assertEqual(by["20261008"]["result"], "not_run")
        self.assertTrue(any("RuntimeError: boom" in e for e in cov["attempts_reader_errors"]))

    def test_malformed_attempt_entries_counted_never_fabricated(self):
        cov, by = self.rows(["20261008"], lambda p: ["garbage", 42,
                                                     {"ticket_id": "t1", "state": "FAILED"}])
        self.assertEqual(by["20261008"]["result"], "failed")
        self.assertEqual(len(by["20261008"]["attempts"]), 1)
        self.assertEqual(cov["malformed_attempt_rows"], 2)

    def test_non_list_reader_return_counts_one_malformed(self):
        cov, by = self.rows(["20261008"], lambda p: "not-a-list")
        self.assertEqual(by["20261008"]["result"], "not_run")
        self.assertEqual(cov["malformed_attempt_rows"], 1)

    def test_attempt_cap_truncates_with_counted_overflow(self):
        n = agg.COVERAGE_ATTEMPT_CAP + 3
        cov, by = self.rows(["20261008"],
                            lambda p: [{"ticket_id": "t%d" % i, "state": "FAILED",
                                        "blocked_reason": ""} for i in range(n)])
        self.assertEqual(len(by["20261008"]["attempts"]), agg.COVERAGE_ATTEMPT_CAP)
        self.assertEqual(by["20261008"]["attempts_truncated"], 3)

    # ---- row population rule (R3): one row per declared instance per period ----

    def test_one_row_per_period_sorted_ascending_and_deduped(self):
        self.served("20261008")
        cov, _ = self.rows(["20261008", "20261008", "20261007"])
        self.assertEqual([r["period"] for r in cov["rows"]], ["20261007", "20261008"])

    def test_face_none_when_not_supplied_never_invented(self):
        cov = agg.face_coverage(INST, "", self.dir, ["20261008"])
        self.assertIsNone(cov["rows"][0]["face"])
        self.assertIsNone(cov["face"])

    def test_bucket_periods_sort_after_plain_date(self):
        def attempts(p):
            return [{"ticket_id": "t1", "state": "FAILED", "blocked_reason": ""}]
        cov, by = self.rows(["20261008", "20261008-2"], attempts)
        self.assertEqual([r["period"] for r in cov["rows"]], ["20261008", "20261008-2"])
        self.assertEqual(by["20261008-2"]["last_ok_period"], "never")

    # ---- build_aggregate wiring: the coverage section rides the aggregate report ----

    def test_build_aggregate_carries_coverage_section(self):
        self.served("20261006")
        self.served("20261008")
        rep = agg.build_aggregate(INST, self.dir, declared_face=FACE)
        cov = rep["coverage"]
        self.assertEqual(cov["kind"], "inspection-coverage")
        self.assertEqual([r["period"] for r in cov["rows"]][-1], "20261008")
        self.assertTrue(all(r["result"] == "produced" for r in cov["rows"]))
        self.assertEqual(cov["face"], FACE)
        # The section is a projection: droppable, cited by nothing — the aggregate
        # report keeps its own kind and no new ledger file is involved.
        self.assertEqual(rep["kind"], "inspection-aggregate")

    def test_build_aggregate_unreadable_ledger_in_window_is_a_named_row(self):
        self.served("20261001")
        (Path(self.dir) / ("inspection-%s-20261007.json" % INST)).write_text("{broken", encoding="utf-8")
        rep = agg.build_aggregate(INST, self.dir, declared_face=FACE)
        results = {r["period"]: r["result"] for r in rep["coverage"]["rows"]}
        self.assertEqual(results.get("20261007"), "unreadable")

    def test_build_aggregate_default_face_none_and_backwards_compatible(self):
        self.served("20261008")
        rep = agg.build_aggregate(INST, self.dir)
        self.assertIsNone(rep["coverage"]["face"])
        self.assertFalse(rep["coverage"]["attempts_available"])


if __name__ == "__main__":
    unittest.main()
