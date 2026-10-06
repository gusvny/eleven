#!/usr/bin/env python3
"""Unit tests for the cross-face / cross-period aggregate weekly page
(epic inspection ticket 3, t261006-14).

Truth source = the three declared rules in the inspection_aggregate.py header
(window rule / verdict winner / overdue) plus the explicit-degradation
discipline of plan gen1. All malformed inputs are reproduced with fixed stub
files — no external sources.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspection_aggregate as agg  # noqa: E402
import inspection_deadman  # noqa: E402
import inspection_trigger  # noqa: E402

INST = "agg-face"


def make_finding(fid, sev="high", subject="bad thing", scan="dup", **extra):
    f = {"id": fid, "scan": scan, "severity": sev, "subject": subject,
         "evidence": "evidence of %s" % fid, "suggestion": "fix it"}
    f.update(extra)
    return f


def make_ledger(d, period, findings, suggestions=None, ticket_id="t260901-01"):
    doc = {"ticket_id": ticket_id, "kind": "inspection", "instance_id": INST,
           "period": period, "summary": {}, "heartbeat": True,
           "findings": findings, "suggested_fix_tickets": suggestions or []}
    (Path(d) / ("inspection-%s-%s.json" % (INST, period))).write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def make_verdicts(d, period, entries):
    (Path(d) / ("inspection-%s-%s-verdicts.json" % (INST, period))).write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")


class AggregateTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="agg-test-")

    # ---- rule 1: the three-condition window ----

    def test_new_window_first_seen_and_recurring(self):
        # anchor=20261006, window_days=7 -> window = (20260929, 20261006]; 20260928 is
        # outside. First seen outside = recur -> not new; first seen inside -> new;
        # recurring at first sight -> not counted, not new.
        make_ledger(self.dir, "20260928", [make_finding("F1"), make_finding("F0")])
        make_ledger(self.dir, "20261006", [
            make_finding("F1", recurring=True),      # seen before the window -> not new
            make_finding("F2"),                      # first seen in window -> new
            make_finding("F3", recurring=True)])     # recurring in window -> not counted, not new
        page = agg.build_aggregate(INST, self.dir)
        ids = [x["id"] for x in page["new_findings"]["items"]]
        self.assertEqual(ids, ["F2"])
        self.assertEqual(page["new_findings"]["by_severity"], {"high": 1, "med": 0, "low": 0})
        self.assertEqual(page["anchor_period"], "20261006")

    def test_new_window_boundary(self):
        # window_days=7, anchor=20261006: window = (20260929, 20261006] (start exclusive).
        # Both 20260928 and 20260929 are outside; 20260930 onward is inside.
        make_ledger(self.dir, "20260928", [make_finding("OLD")])
        make_ledger(self.dir, "20260929", [make_finding("START")])
        make_ledger(self.dir, "20260930", [make_finding("EDGE")])
        make_ledger(self.dir, "20261006", [make_finding("EDGE", recurring=True),
                                           make_finding("START", recurring=True)])
        page = agg.build_aggregate(INST, self.dir, window_days=7)
        ids = [x["id"] for x in page["new_findings"]["items"]]
        self.assertEqual(ids, ["EDGE"])           # start day 20260929 excluded (exclusive)

    # ---- rule 2: cross-period verdict conflict, the newest wins ----

    def test_verdict_conflict_newest_period_wins_both_orders(self):
        for order in (["20261001", "20261006"], ["20261006", "20261001"]):
            d = self.dir + "/" + "-".join(order)
            Path(d).mkdir()
            make_ledger(d, "20261006", [make_finding("F1")])
            entries_a = [{"finding_id": "F1", "verdict": "to-fix"}]
            entries_b = [{"finding_id": "F1", "verdict": "false-positive"}]
            if order[0] == "20261001":
                make_verdicts(d, "20261001", entries_a)
                make_verdicts(d, "20261006", entries_b)
            else:
                make_verdicts(d, "20261006", entries_b)
                make_verdicts(d, "20261001", entries_a)
            page = agg.build_aggregate(INST, d)
            win = page and agg.collect_winning_verdicts(d, INST)["winners"]["F1"]
            self.assertEqual(win["verdict"], "false-positive")   # newest period wins (both orders)
            self.assertEqual(page["still_open"], [])             # adjudicated -> not open

    def test_verdict_same_period_last_entry_wins(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        make_verdicts(self.dir, "20261006", [
            {"finding_id": "F1", "verdict": "false-positive"},
            {"finding_id": "F1", "verdict": "to-fix"}])
        win = agg.collect_winning_verdicts(self.dir, INST)["winners"]["F1"]
        self.assertEqual(win["verdict"], "to-fix")
        page = agg.build_aggregate(INST, self.dir)
        self.assertEqual(len(page["still_open"]), 1)

    # ---- fixed / open / the injected ticket face ----

    def test_ticket_lookup_closed_marks_fixed(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        page = agg.build_aggregate(
            INST, self.dir,
            ticket_lookup=lambda f: {"ticket_id": "t1", "state": "COMPLETED",
                                     "closed": True} if f["id"] == "F1" else None)
        self.assertEqual([x["id"] for x in page["fixed"]], ["F1"])
        self.assertEqual(page["still_open"], [])
        self.assertTrue(page["ticket_states_available"])

    def test_ticket_lookup_no_record_conservative_open(self):
        # lookup returning None = 'no ticket record for this finding' (reader present);
        # conservatively open, never guessed fixed.
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        page = agg.build_aggregate(INST, self.dir, ticket_lookup=lambda f: None)
        self.assertEqual([x["id"] for x in page["still_open"]], ["F1"])
        self.assertTrue(page["ticket_states_available"])
        self.assertIsNone(page["still_open"][0]["ticket"])

    def test_no_reader_injected_flags_unavailable(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        page = agg.build_aggregate(INST, self.dir, ticket_lookup=None)
        self.assertFalse(page["ticket_states_available"])
        self.assertEqual([x["id"] for x in page["still_open"]], ["F1"])

    def test_raising_lookup_named_not_corrupt(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])

        def boom(f):
            raise RuntimeError("ticket store down")
        page = agg.build_aggregate(INST, self.dir, ticket_lookup=boom)
        self.assertEqual([x["id"] for x in page["still_open"]], ["F1"])  # conservatively open
        self.assertEqual(len(page["ticket_reader_errors"]), 1)
        self.assertIn("ticket store down", page["ticket_reader_errors"][0])

    # ---- rule 3: overdue (boundary: exactly at the age is NOT overdue) ----

    def test_overdue_boundary(self):
        make_ledger(self.dir, "20260930", [make_finding("F1")])
        make_ledger(self.dir, "20261006", [make_finding("F1", recurring=True)])
        page = agg.build_aggregate(INST, self.dir, overdue_days=6)
        self.assertEqual(page["overdue"], [])    # exactly 6 days = not overdue
        page = agg.build_aggregate(INST, self.dir, overdue_days=5)
        self.assertEqual([x["id"] for x in page["overdue"]], ["F1"])

    def test_overdue_excludes_adjudicated_and_ticketed(self):
        make_ledger(self.dir, "20260930", [make_finding("F1"), make_finding("F2")])
        make_verdicts(self.dir, "20260930", [{"finding_id": "F1",
                                              "verdict": "false-positive"}])
        make_ledger(self.dir, "20261006", [
            make_finding("F1", recurring=True), make_finding("F2", recurring=True)])
        page = agg.build_aggregate(
            INST, self.dir,
            ticket_lookup=lambda f: {"ticket_id": "t2", "state": "RUNNING", "closed": False}
            if f["id"] == "F2" else None)
        self.assertEqual(page["overdue"], [])    # F1 adjudicated, F2 has an open ticket: neither overdue
        self.assertEqual([x["id"] for x in page["still_open"]], ["F2"])

    def test_overdue_recurring_unknown_origin(self):
        # recurring at first sight (earlier ledger gone): real origin unknowable ->
        # conservatively aged from before the window.
        make_ledger(self.dir, "20261006", [make_finding("F1", recurring=True)])
        page = agg.build_aggregate(INST, self.dir, overdue_days=7)
        self.assertEqual([x["id"] for x in page["overdue"]], ["F1"])

    # ---- explicit degradation: missing periods / damaged files are never silent ----

    def test_missing_and_malformed_ledgers_named(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        (Path(self.dir) / ("inspection-%s-20261005.json" % INST)).write_text("{broken")
        (Path(self.dir) / ("inspection-%s-20261004.json" % INST)).write_text(
            json.dumps({"findings": "not-a-list"}))
        page = agg.build_aggregate(INST, self.dir)
        reasons = {x["period"]: x["reason"] for x in page["periods_not_available"]}
        self.assertIn("unreadable", reasons["20261005"])
        self.assertIn("malformed", reasons["20261004"])
        self.assertEqual(page["anchor_period"], "20261006")

    def test_bad_verdicts_file_named(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        (Path(self.dir) / ("inspection-%s-20261006-verdicts.json" % INST)).write_text("[")
        page = agg.build_aggregate(INST, self.dir)
        keys = [x["period"] for x in page["periods_not_available"]]
        self.assertTrue(any("verdicts" in k for k in keys))

    def test_journal_torn_tail_counted(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        with open(Path(self.dir) / "inspection-spawn.jsonl", "w") as fh:
            fh.write(json.dumps({"instance": INST, "ticket_id": "t1"}) + "\n")
            fh.write('{"instance": "%s", "tick' % INST)   # torn trailing line
        page = agg.build_aggregate(INST, self.dir)
        self.assertEqual(page["journal_note"].get("inspection-spawn.jsonl"), 1)

    def test_missing_periods_from_deadman_explains_idle(self):
        make_ledger(self.dir, "20261005", [make_finding("F1")])
        (Path(self.dir) / "inspection-spawn.jsonl").write_text(
            json.dumps({"instance": INST, "period": "20261004",
                        "decision": "skipped-no-change"}) + "\n")
        page = agg.build_aggregate(INST, self.dir, cron="0 7 * * *",
                                   lookback_days=7, grace_days=0)
        self.assertNotIn("20261004", page["missed_periods"])   # explained idle separate
        self.assertIn("20261004", page["skipped_no_change_periods"])

    def test_unparseable_cron_named_not_green(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        page = agg.build_aggregate(INST, self.dir, cron="not a cron")
        self.assertTrue(page["deadman_error"])

    # ---- explicit ordering / determinism / naming ----

    def test_ordering_determinism_and_sort(self):
        make_ledger(self.dir, "20261006", [
            make_finding("B", "low"), make_finding("A", "high"), make_finding("C", "med")])
        p1 = agg.build_aggregate(INST, self.dir)
        p2 = agg.build_aggregate(INST, self.dir)
        self.assertEqual(json.dumps(p1, sort_keys=True), json.dumps(p2, sort_keys=True))
        self.assertEqual([x["id"] for x in p1["new_findings"]["items"]], ["A", "C", "B"])
        self.assertTrue(p1["ordering"])

    def test_report_name_and_ledger_isolation(self):
        name = agg.aggregate_report_name(INST, "20261006")
        self.assertEqual(name, "aggregate-%s-20261006.json" % INST)
        self.assertIsNone(inspection_deadman.LEDGER_NAME_RE.match(name))  # never enters period-ledger accounting
        with self.assertRaises(ValueError):
            agg.aggregate_report_name("", "20261006")

    # ---- shell face (cmd_weekly): write scope = its own report; reader-side assertions ----

    def test_cmd_weekly_reads_back_report_and_write_scope(self):
        make_ledger(self.dir, "20261006", [make_finding("F1")])
        (Path(self.dir) / "inspection-spawn.jsonl").write_text("")

        class FakeInst:
            cron, tz, kind = "0 7 * * *", "", "cron"

        class FakeDecl:
            def instance(self, _):
                return FakeInst()

        orig = inspection_trigger._resolve_decl
        inspection_trigger._resolve_decl = lambda p, i: (FakeDecl(), "sandbar")
        try:
            ns = inspection_trigger.argparse.Namespace(
                instance=INST, ledger_dir=self.dir, window_days=7, overdue_days=7,
                lookback_days=7, grace_days=0, with_tickets=False, decl_path=None)
            res = inspection_trigger.cmd_weekly(ns)
        finally:
            inspection_trigger._resolve_decl = orig
        self.assertTrue(res["ok"])
        names = sorted(p.name for p in Path(self.dir).iterdir())
        report = [n for n in names if n.startswith("aggregate-")]
        self.assertEqual(report, ["aggregate-%s-20261006.json" % INST])
        # reader-side acceptance: read back from disk and assert content (writer
        # stdout is not evidence)
        doc = json.loads((Path(self.dir) / report[0]).read_text("utf-8"))
        self.assertEqual([x["id"] for x in doc["new_findings"]["items"]], ["F1"])
        self.assertEqual(doc["periods_not_available"], [])
        self.assertEqual(doc["ordering"], agg.ORDERING_NOTE)

    def test_cmd_weekly_no_ledgers_no_empty_shell(self):
        class FakeDecl:
            def instance(self, _):
                return type("I", (), {"cron": "", "tz": "", "kind": "cron"})()

        orig = inspection_trigger._resolve_decl
        inspection_trigger._resolve_decl = lambda p, i: (FakeDecl(), "")
        try:
            ns = inspection_trigger.argparse.Namespace(
                instance=INST, ledger_dir=self.dir, window_days=7, overdue_days=7,
                lookback_days=7, grace_days=0, with_tickets=False, decl_path=None)
            res = inspection_trigger.cmd_weekly(ns)
        finally:
            inspection_trigger._resolve_decl = orig
        self.assertFalse(res["ok"])
        self.assertIn("anchor period", res["error"])
        self.assertEqual(list(Path(self.dir).iterdir()), [])   # no empty-shell file


if __name__ == "__main__":
    unittest.main()
