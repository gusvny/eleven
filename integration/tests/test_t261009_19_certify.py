# -*- coding: utf-8 -*-
"""L1 unit tests for server/engine/develop_certify.py (ticket t261009-19).

White-box truth tables for the delivery ledger (shared seq ordering space,
flock append, duplicate refusal, malformed-line loudness), the schedule
decision and guard, the certification record (cites a run, never restates),
the derived range, the bounded red ladder and the freeze records.

External-input discipline: every consumer of a run header / lane results /
ledger bytes gets malformed-input cases here, with fakes — never a real
external source, never an integration entry.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

import develop_certify as dc  # noqa: E402


def L(idx, seq=None, line="default", ticket="t1", at=1791507005123):
    row = {"kind": dc.KIND_LANDING, "id": "ldg-x%03d" % idx, "ticket": ticket,
           "line": line, "repos": [{"repo": "sandbar", "revision": "r%d" % idx}],
           "actor": "engine", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def C(idx, seq=None, line="default", run="run-a", at=1791508000000,
      revision="r0"):
    row = {"kind": dc.KIND_CERT, "id": "cert-x%03d" % idx, "line": line,
           "repos": [{"repo": "sandbar", "revision": revision}],
           "run": run, "booked_red": "known-red-baseline@2026-10-04",
           "judged_by": "integration/run_scenarios.py", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "delivery.jsonl"

    def test_append_assigns_shared_seq_and_reads_back(self):
        r = dc.append_rows([L(1), C(1), L(2)], self.path)
        self.assertEqual(r["written"], 3)
        self.assertEqual(r["seqs"], [1, 2, 3])
        rows, bad = dc.read_rows(self.path)
        self.assertEqual([x["seq"] for x in rows], [1, 2, 3])
        self.assertEqual(bad, [])
        # kinds share ONE ordering space — a landing between two certs keeps
        # its place; this is what makes the covered range derivable.
        self.assertEqual([x["kind"] for x in rows],
                         ["landing", "certification", "landing"])

    def test_duplicate_id_refused_loudly_across_and_within_batch(self):
        dc.append_rows([L(1)], self.path)
        r = dc.append_rows([L(1)], self.path)
        self.assertEqual(r["written"], 0)
        self.assertEqual(r["rejected"][0]["reason"], "duplicate_id:ldg-x001")
        r = dc.append_rows([L(2), L(2)], self.path)
        self.assertEqual(r["written"], 1)
        self.assertEqual(len(r["rejected"]), 1)

    def test_all_rejected_writes_nothing(self):
        r = dc.append_rows([{"kind": "nope"}], self.path)
        self.assertEqual(r["written"], 0)
        self.assertFalse(self.path.exists())

    def test_unknown_kind_and_bad_fields_refused_by_name(self):
        cases = [{"kind": "landing", "id": "cert-x1"},
                 {"kind": "cert", "id": "cert-y1"},
                 {"kind": dc.KIND_CERT, "id": "cert-y2", "line": "d",
                  "repos": [], "run": "run-a", "booked_red": "b",
                  "judged_by": "j", "at": 1},
                 {"kind": dc.KIND_CERT, "id": "cert-y3", "line": "d",
                  "repos": [{"repo": "s", "revision": "r"}], "run": "nonsense",
                  "booked_red": "b", "judged_by": "j", "at": 1},
                 {"kind": dc.KIND_FREEZE, "id": "frz-1", "line": "d",
                  "cause": "ldg-x001", "at": 1},
                 {"kind": dc.KIND_FREEZE_CHANGE, "freeze": "frz-1",
                  "change": "prayed", "by": "i", "reason": "r", "at": 1},
                 {"kind": dc.KIND_FREEZE_CHANGE, "freeze": "frz-1",
                  "change": dc.CHANGE_ATTRIBUTION, "by": "i", "at": 1},
                 {"kind": dc.KIND_FREEZE_CHANGE, "freeze": "frz-1",
                  "change": dc.CHANGE_CLOSED, "by": "i", "reason": "", "at": 1},
                 {"kind": dc.KIND_RANGE_GROWTH, "line": "d"},
                 {"kind": dc.KIND_LANDING, "id": "ldg-ok", "ticket": "t",
                  "line": "d", "repos": [{"repo": "s"}], "actor": "a",
                  "at": 1},
                 {"kind": dc.KIND_LANDING, "id": "ldg-ok", "ticket": "t",
                  "line": "d", "repos": [{"repo": "s", "revision": "r"}],
                  "actor": "a", "at": True},
                 ]
        for row in cases:
            clean, why = dc.validate_row(row)
            self.assertIsNone(clean, row)
            self.assertTrue(why, row)

    def test_cert_row_cannot_restate_counts(self):
        row = C(9)
        row["cases"] = {"ran": 5}
        clean, why = dc.validate_row(row)
        # counts on a certification are a schema violation: the run owns them
        self.assertIsNone(clean)
        self.assertTrue(why)

    def test_malformed_lines_reported_capped(self):
        with open(str(self.path), "w", encoding="utf-8") as fh:
            fh.write(_json(L(1, seq=1)) + "\n")
            fh.write("not json at all\n")
            fh.write("[1,2,3]\n")
            for i in range(15):
                fh.write("{broken%d\n" % i)
        rows, bad = dc.read_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(bad), 10)
        self.assertIn("not json", bad[0])

    def test_append_refuses_to_touch_ledger_with_malformed_lines(self):
        with open(str(self.path), "w", encoding="utf-8") as fh:
            fh.write("{broken\n")
        before = self.path.read_bytes()
        with self.assertRaises(dc.CertifyError):
            dc.append_rows([L(5)], self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_concurrent_appends_do_not_tie_seq(self):
        n = 8
        barrier = threading.Barrier(n)

        def work(i):
            barrier.wait()
            return dc.append_rows([L(50 + i)], self.path)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows, _ = dc.read_rows(self.path)
        seqs = sorted(x["seq"] for x in rows)
        self.assertEqual(seqs, list(range(1, n + 1)))

    def test_garbage_path_named_not_swallowed(self):
        d = Path(self.tmp) / "adir"
        d.mkdir()
        rows, bad = dc.read_rows(d)
        self.assertEqual(rows, [])
        self.assertTrue(bad and "directory" in bad[0])


def _json(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


class MintTest(unittest.TestCase):
    def test_monotonic_same_millisecond_never_ties(self):
        a = dc.mint_id("cert", at_ms=1791507005123)
        b = dc.mint_id("cert", at_ms=1791507005123)
        self.assertNotEqual(a, b)
        self.assertLess(a, b)

    def test_clock_skew_floor_keeps_order(self):
        dc.mint_id("cert", at_ms=1791507009999)
        back = dc.mint_id("cert", at_ms=1791507000001)
        self.assertLess("cert-01J", back)  # shape sanity
        # the skewed mint must still sort after the previous one
        self.assertTrue(dc._LAST_MINT["ms"] >= 1791507009999)

    def test_prefixes_are_family_readable(self):
        self.assertTrue(dc.mint_id("ldg").startswith("ldg-"))
        self.assertTrue(dc.mint_id("frz").startswith("frz-"))
        rid = dc.mint_id("cert")
        self.assertEqual(len(rid), len("cert-") + 26)


class RangeTest(unittest.TestCase):
    def test_range_derived_from_order_not_stored(self):
        rows = [L(1, seq=1), L(2, seq=2), C(1, seq=3, revision="r2"),
                L(3, seq=4), L(4, seq=5)]
        rng = dc.derive_range(rows, "default")
        self.assertEqual(rng["previous_certification"]["id"], "cert-x001")
        self.assertEqual([l["id"] for l in rng["covered_landings"]],
                         ["ldg-x003", "ldg-x004"])
        self.assertEqual(rng["certified_prefix"],
                         [{"repo": "sandbar", "revision": "r2"}])
        # a later certification closes the range and becomes the prefix
        rows.append(C(2, seq=6, run="run-b", revision="r4"))
        rng = dc.derive_range(rows, "default")
        self.assertEqual(rng["previous_certification"]["id"], "cert-x002")
        self.assertEqual(rng["covered_landings"], [])
        self.assertEqual(rng["certified_prefix"],
                         [{"repo": "sandbar", "revision": "r4"}])

    def test_never_certified_range_is_all_landings(self):
        rng = dc.derive_range([L(1, seq=1), L(2, seq=2)], "default")
        self.assertIsNone(rng["previous_certification"])
        self.assertEqual(len(rng["covered_landings"]), 2)
        self.assertIsNone(rng["certified_prefix"])

    def test_lines_do_not_leak_into_each_other(self):
        rows = [L(1, seq=1), L(2, seq=2, line="other"),
                C(1, seq=3)]
        rng = dc.derive_range(rows, "default")
        self.assertEqual(len(rng["covered_landings"]), 0)
        other = dc.derive_range(rows, "other")
        self.assertIsNone(other["previous_certification"])
        self.assertEqual(len(other["covered_landings"]), 1)

    def test_landable_contained_in_green_cert_only(self):
        rows = [L(1, seq=1), C(1, seq=2, revision="r1", run="run-red"),
                C(2, seq=3, revision="r2", run="run-green")]
        green_landing = dict(L(1), repos=[{"repo": "sandbar",
                                           "revision": "r2"}])
        self.assertTrue(dc.landable(rows, "default", green_landing,
                                    is_green=lambda r: r == "run-green"))
        # the only matching cert's run is red: not landable while green-only
        self.assertFalse(dc.landable(rows, "default", L(1),
                                     is_green=lambda r: r == "run-green"))
        # no run reader injected: caller says so, every cert counts
        self.assertTrue(dc.landable(rows, "default", L(1)))

    def test_landable_garbage_landing_named(self):
        with self.assertRaises(dc.CertifyError):
            dc.landable([], "default", "ldg-x001")


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_change_trigger_needs_nonempty_range(self):
        rows = [L(1, seq=1), C(1, seq=2)]
        self.assertEqual(dc.should_certify("change", rows, "default", False),
                         (False, "range_empty"))
        rows.append(L(2, seq=3))
        self.assertEqual(dc.should_certify("change", rows, "default", False),
                         (True, "range_non_empty"))

    def test_guard_held_refuses_every_trigger(self):
        rows = [L(1, seq=1)]
        self.assertEqual(dc.should_certify("change", rows, "default", True),
                         (False, "guard_held"))
        self.assertEqual(dc.should_certify("backstop", rows, "default", True,
                                           now_ms=10**13, backstop_ms=1),
                         (False, "guard_held"))

    def test_backstop_fires_on_silence_and_on_age(self):
        self.assertEqual(dc.should_certify("backstop", [], "default", False),
                         (True, "never_certified"))
        rows = [C(1, seq=1, at=1000)]
        self.assertEqual(dc.should_certify("backstop", rows, "default", False,
                                           now_ms=9000, backstop_ms=5000),
                         (True, "backstop_elapsed"))
        self.assertEqual(dc.should_certify("backstop", rows, "default", False,
                                           now_ms=2000, backstop_ms=5000),
                         (False, "backstop_not_elapsed"))

    def test_bad_inputs_named(self):
        with self.assertRaises(dc.CertifyError):
            dc.should_certify("prayer", [], "default", False)
        # backstop with a previous certification needs now_ms to judge age
        rows = [C(1, seq=1, at=1000)]
        with self.assertRaises(dc.CertifyError):
            dc.should_certify("backstop", rows, "default", False,
                              backstop_ms=1)

    def test_guard_acquire_release_round_trip(self):
        gp = Path(self.tmp) / "guard-project.jsonl"
        got = dc.guard_acquire(gp, "cert-x001")
        self.assertTrue(got["held"])
        self.assertIsNone(dc.guard_acquire(gp, "cert-x002"))  # busy
        dc.guard_release(gp)
        got2 = dc.guard_acquire(gp, "cert-x003")
        self.assertTrue(got2["held"])

    def test_corrupt_guard_is_loud_not_free(self):
        gp = Path(self.tmp) / "g.jsonl"
        gp.parent.mkdir(parents=True, exist_ok=True)
        (gp.parent / dc.GUARD_NAME).write_text("{broken", encoding="utf-8")
        with self.assertRaises(dc.CertifyError):
            dc.guard_acquire(gp, "cert-x001")


def RUN(ran=445, failed=2, env_failed=0, rid="run-abc"):
    return {"id": rid, "line": "default",
            "repos": [{"repo": "sandbar", "revision": "r1"}],
            "suite": "full", "source": "scheduled", "env_fp": "f" * 16,
            "conc_width": 3, "pool": "main:3", "started_at": 1,
            "duration_s": 21,
            "cases": {"ran": ran,
                      "passed": (ran - failed) if isinstance(ran, int) else 0,
                      "failed": failed,
                      "env_failed": env_failed},
            "verdict": "green" if (ran and not failed and not env_failed)
            else "red"}


class CertificationTest(unittest.TestCase):
    def test_record_cites_run_never_restates(self):
        row = dc.build_certification([{"repo": "sandbar", "revision": "r1"}],
                                     RUN(), "known-red-baseline@2026-10-04",
                                     "integration/run_scenarios.py",
                                     at_ms=1791508600000)
        self.assertEqual(row["kind"], dc.KIND_CERT)
        self.assertEqual(row["run"], "run-abc")
        self.assertNotIn("cases", row)
        self.assertNotIn("verdict", row)
        self.assertEqual(row["booked_red"], "known-red-baseline@2026-10-04")
        self.assertEqual(row["judged_by"], "integration/run_scenarios.py")
        clean, why = dc.validate_row(row)
        self.assertIsNotNone(clean, why)

    def test_could_not_run_missing_header(self):
        for header in (None, {}, {"id": "nonsense"}, "garbage"):
            with self.assertRaises(dc.CouldNotRun):
                dc.build_certification([], header, "b", "j")

    def test_run_that_executed_nothing_is_not_proof(self):
        with self.assertRaises(dc.CouldNotRun):
            dc.build_certification([], RUN(ran=0, failed=0), "b", "j")
        with self.assertRaises(dc.CouldNotRun):
            dc.build_certification([], RUN(ran="many", failed=0), "b", "j")

    def test_red_run_is_still_a_certification(self):
        # no verdict on the certification: a red cert is how a freeze opens
        row = dc.build_certification([{"repo": "s", "revision": "r"}],
                                     RUN(failed=3), "b", "j")
        self.assertIn("run", row)

    def test_run_verdict_rollup(self):
        self.assertEqual(dc.run_verdict({"ran": 5, "failed": 0,
                                         "env_failed": 0}), "green")
        self.assertEqual(dc.run_verdict({"ran": 0, "failed": 0,
                                         "env_failed": 0}), "red")
        self.assertEqual(dc.run_verdict({"ran": 5, "failed": 0,
                                         "env_failed": 2}), "red")


class FreezeTest(unittest.TestCase):
    def test_episode_entity_then_changes(self):
        cert = C(1)
        frz = dc.open_freeze_rows(cert, at_ms=5)[0]
        self.assertEqual(set(frz) - {"seq"}, {"kind", "id", "line", "cause",
                                              "at"})
        self.assertEqual(frz["cause"], "cert-x001")
        ch = dc.freeze_change_row(frz["id"], dc.CHANGE_ATTRIBUTION,
                                  "integration", "per-lane results named it",
                                  value="isolated: ldg-x001", at_ms=6)
        clean, why = dc.validate_row(ch)
        self.assertIsNotNone(clean, why)
        close = dc.freeze_change_row(frz["id"], dc.CHANGE_CLOSED, "t-fix",
                                     "the remedy landed and certified", at_ms=7)
        clean, why = dc.validate_row(close)
        self.assertIsNotNone(clean, why)

    def test_searched_change_carries_range(self):
        ch = dc.freeze_change_row("frz-1", dc.CHANGE_SEARCHED, "integration",
                                  "range searched, no culprit",
                                  value=dc.range_key(["ldg-b", "ldg-a"]))
        self.assertEqual(ch["value"], "ldg-a,ldg-b")
        clean, why = dc.validate_row(ch)
        self.assertIsNotNone(clean, why)

    def test_could_not_run_row_has_no_id_and_no_freeze(self):
        row = dc.could_not_run_row("default", "dead runner", at_ms=9)
        self.assertNotIn("id", row)
        clean, why = dc.validate_row(row)
        self.assertIsNotNone(clean, why)
        # an unavailable proof is not a content implication: no freeze
        self.assertFalse(dc.should_freeze(None))

    def test_freeze_only_on_content_implication(self):
        self.assertTrue(dc.should_freeze("isolated: ldg-x001"))
        self.assertTrue(dc.should_freeze(dc.BOUNDARY_VALUE))


class LadderTest(unittest.TestCase):
    def setUp(self):
        self.rows = [L(1, seq=1), L(2, seq=2),
                     C(1, seq=3, run="run-green", revision="r2")]

    def test_first_step_is_always_rerun(self):
        red = C(9, seq=4, run="run-red", revision="r4")
        self.rows.append(red)
        self.assertEqual(dc.next_red_action(self.rows, "default", red, None),
                         ("rerun", None))

    def test_lane_results_filter_names_one_landing_for_free(self):
        # rerun already recorded: a later cert on the same candidate
        rows = self.rows + [L(4, seq=4), C(9, seq=5, run="run-red",
                                           revision="r4"),
                            C(10, seq=11, run="run-red-2", revision="r4")]
        red = rows[4]
        self.assertEqual(
            dc.next_red_action(rows, "default", red, ["ldg-x004"]),
            ("isolated", rows[3]))

    def test_lane_results_without_single_hit_fall_through(self):
        red = C(9, seq=4, run="run-red", revision="r4")
        rows = self.rows + [red,
                            C(10, seq=11, run="run-red-2", revision="r4")]
        act, _ = dc.next_red_action(rows, "default", red, [])
        self.assertEqual(act, "search")
        act, _ = dc.next_red_action(rows, "default", red,
                                    ["ldg-x002", "ldg-x003"])
        self.assertEqual(act, "search")

    def test_garbage_lane_results_named(self):
        red = C(9, seq=4, run="run-red", revision="r4")
        with self.assertRaises(dc.CertifyError):
            dc.next_red_action(self.rows, "default", red, [42])
        with self.assertRaises(dc.CertifyError):
            dc.next_red_action(self.rows, "default", "not-a-cert", None)

    def test_range_of_one_is_isolated_by_arithmetic(self):
        rows = [L(1, seq=1), C(1, seq=2, revision="r1"), L(2, seq=3),
                C(9, seq=4, run="run-red", revision="r4"),
                C(10, seq=5, run="run-red-2", revision="r4")]
        act, hit = dc.next_red_action(rows, "default", rows[3], [])
        self.assertEqual(act, "isolated")
        self.assertEqual(hit["id"], "ldg-x002")

    def test_already_searched_range_refused(self):
        rows = [L(1, seq=1), C(1, seq=2, revision="r1"),
                L(2, seq=3), L(3, seq=4),
                C(9, seq=5, run="run-red", revision="r4"),
                C(10, seq=6, run="run-red-2", revision="r4")]
        red = rows[4]
        key = dc.range_key(["ldg-x002", "ldg-x003"])
        ch = dc.freeze_change_row("frz-1", dc.CHANGE_SEARCHED,
                                  "integration", "searched once",
                                  value=key, at_ms=99, line="default")
        ch["seq"] = 7
        rows.append(ch)
        with self.assertRaises(dc.AlreadySearchedError):
            dc.next_red_action(rows, "default", red, [])

    def test_boundary_outcome_is_sayable(self):
        self.assertEqual(dc.BOUNDARY_VALUE,
                         "boundary, culprit not isolated")


class ScenarioParityTest(unittest.TestCase):
    """Leg-equivalent smoke of the two delivered scenarios (pytest face —
    the sc_*.py entries themselves are executed by the integration gate,
    never in-segment)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.led = Path(self.tmp) / "delivery.jsonl"

    def test_certify_once_journey(self):
        rows0, bad = dc.read_rows(self.led)
        self.assertEqual((rows0, bad), ([], []))
        dc.append_rows([L(1)], self.led)
        rows0, _ = dc.read_rows(self.led)
        self.assertEqual(dc.should_certify("change", rows0, "default", False),
                         (True, "range_non_empty"))
        self.assertIsNotNone(dc.guard_acquire(self.led, "t"))
        self.assertEqual(dc.should_certify("change", rows0, "default", True),
                         (False, "guard_held"))
        self.assertIsNone(dc.guard_acquire(self.led, "second"))
        dc.guard_release(self.led)
        cert = dc.build_certification(
            [{"repo": "sandbar", "revision": "r1"}],
            RUN(rid="run-" + "a" * 26), "inv-x", "judge", at_ms=5)
        rec = dc.append_rows([cert], self.led)
        self.assertEqual(rec["written"], 1)
        rows, _ = dc.read_rows(self.led)
        cert_disk = [r for r in rows if r["kind"] == dc.KIND_CERT][0]
        self.assertEqual(cert_disk["run"], "run-" + "a" * 26)
        self.assertEqual(cert_disk["repos"],
                         [{"repo": "sandbar", "revision": "r1"}])
        thief = dict(cert_disk)
        thief["id"] = "cert-" + "Z" * 26
        thief["verdict"] = "green"
        w = dc.append_rows([thief], self.led)
        self.assertEqual(w["written"], 0)
        self.assertIn("restates", w["rejected"][0]["reason"])
        # red cert later: green prefix stays landable (goal 8)
        red = dc.build_certification(
            [{"repo": "sandbar", "revision": "r2"}],
            RUN(failed=1, rid="run-" + "b" * 26), "inv-x", "judge", at_ms=6)
        dc.append_rows([red], self.led)
        rows2, _ = dc.read_rows(self.led)
        self.assertTrue(dc.landable(rows2, "default", L(1),
                                    is_green=lambda r: r == "run-" + "a" * 26))

    def test_red_bounded_journey(self):
        red = C(10, seq=10, revision="r1")
        rows = [L(1, seq=1), L(2, seq=2), L(3, seq=3), red]
        self.assertEqual(dc.next_red_action(rows, "default", red, None),
                         ("rerun", None))
        rerun = dict(red, id="cert-0011", seq=11, run="run-" + "1" * 26)
        act = dc.next_red_action(rows + [rerun], "default", red, ["ldg-x001"])
        self.assertEqual((act[0], act[1]["id"]), ("isolated", "ldg-x001"))
        solo = [L(2, seq=2)]
        solo_red = C(12, seq=3, revision="r2")
        act = dc.next_red_action(
            solo + [solo_red, dict(solo_red, id="cert-0013", seq=4)],
            "default", solo_red, None)
        self.assertEqual((act[0], act[1]["id"]), ("isolated", "ldg-x002"))
        multi = [L(2, seq=2), L(3, seq=3)]
        red_m = C(14, seq=14, revision="r3")
        act = dc.next_red_action(
            multi + [red_m, dict(red_m, id="cert-0015", seq=15)],
            "default", red_m, None)
        self.assertEqual(act, ("search", multi))
        searched = dc.freeze_change_row("frz-" + "0" * 26, "searched", "i",
                                        "searched once",
                                        value=dc.range_key(
                                            ["ldg-x003", "ldg-x002"]),
                                        line="default")
        searched["seq"] = 20
        with self.assertRaises(dc.AlreadySearchedError):
            dc.next_red_action(multi + [red_m,
                                        dict(red_m, id="cert-0015", seq=15),
                                        searched], "default", red_m, None)
        ep = dc.open_freeze_rows(red_m)[0]
        self.assertTrue(str(ep["id"]).startswith("frz-"))
        self.assertNotIn("culprit", ep)
        growth = dc.could_not_run_row("default", "env:runner dead", at_ms=99)
        clean, why = dc.validate_row(growth)
        self.assertIsNotNone(clean, why)
        rec = dc.append_rows([growth], self.led)
        self.assertEqual(rec["written"], 1)
        rows_g, bad_g = dc.read_rows(self.led)
        self.assertEqual(bad_g, [])
        self.assertTrue(any(r["kind"] == dc.KIND_RANGE_GROWTH
                            for r in rows_g))
        self.assertFalse(any(r["kind"] == dc.KIND_FREEZE for r in rows_g))


if __name__ == "__main__":
    unittest.main()
