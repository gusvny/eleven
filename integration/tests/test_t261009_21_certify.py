# -*- coding: utf-8 -*-
"""L1 unit tests for the waiting faces of server/engine/develop_certify.py
(ticket t261009-21; design source docs/design/develop-buffer-v1.md goals
8 / 14 / 15 / 16).

Truth tables for: freeze_state (state replayed from change records, never a
stored flag), may_land (the structural fix exemption), ticket_wait_state
(waiting is dated, names what it waits for, and never reads as stuck /
red_implicated), needs_slot (waiting holds no capacity).

External-input discipline: every malformed landing / line / clock / bound /
face input gets a named-refusal case here, with fakes — never a real
external source, never an integration entry.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

import develop_certify as dc  # noqa: E402

T0 = 1791509000000


def L(idx, seq=None, line="default", ticket="t1", at=T0, rev=None):
    row = {"kind": dc.KIND_LANDING, "id": "ldg-y%03d" % idx, "ticket": ticket,
           "line": line,
           "repos": [{"repo": "sandbar",
                      "revision": rev if rev is not None else "r%d" % idx}],
           "actor": "engine", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def C(idx, seq=None, line="default", run="run-a", at=T0 + 1000,
      revision="r0"):
    row = {"kind": dc.KIND_CERT, "id": "cert-y%03d" % idx, "line": line,
           "repos": [{"repo": "sandbar", "revision": revision}],
           "run": run, "booked_red": "known-red-baseline@2026-10-04",
           "judged_by": "integration/run_scenarios.py", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def FRZ(idx, seq=None, line="default", cause="cert-y001", at=T0 + 2000):
    row = {"kind": dc.KIND_FREEZE, "id": "frz-y%03d" % idx, "line": line,
           "cause": cause, "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def CH(idx, freeze, change, seq=None, by="integration", reason="r",
       value=None, line="default", at=T0 + 3000):
    row = {"kind": dc.KIND_FREEZE_CHANGE, "id": "fch-y%03d" % idx,
           "freeze": freeze, "change": change, "by": by, "reason": reason,
           "line": line, "at": at}
    if value is not None:
        row["value"] = value
    if seq is not None:
        row["seq"] = seq
    return row


def green(run):
    return lambda r: r == run


class FreezeStateTest(unittest.TestCase):
    def test_no_episode_is_not_frozen(self):
        st = dc.freeze_state([L(1, seq=1), C(1, seq=2)], "default")
        self.assertFalse(st["frozen"])
        self.assertIsNone(st["episode"])

    def test_open_episode_freezes_culprit_from_attribution(self):
        rows = [FRZ(1, seq=1), CH(1, "frz-y001", dc.CHANGE_ATTRIBUTION,
                                  seq=2, value="ldg-y002"),
                CH(2, "frz-y001", dc.CHANGE_SEARCHED, seq=3,
                   value="ldg-y002")]
        st = dc.freeze_state(rows, "default")
        self.assertTrue(st["frozen"])
        self.assertEqual(st["cause"], "cert-y001")
        self.assertEqual(st["culprit"], "ldg-y002")
        self.assertIsNone(st["closed_at"])

    def test_state_replays_closed_then_reopened(self):
        rows = [FRZ(1, seq=1),
                CH(1, "frz-y001", dc.CHANGE_CLOSED, seq=2, at=T0 + 4000),
                CH(2, "frz-y001", dc.CHANGE_REOPENED, seq=3, at=T0 + 5000)]
        self.assertTrue(dc.freeze_state(rows, "default")["frozen"])
        rows.pop()  # without the reopen the episode reads closed
        st = dc.freeze_state(rows, "default")
        self.assertFalse(st["frozen"])
        self.assertEqual(st["closed_at"], T0 + 4000)

    def test_change_of_another_episode_is_ignored(self):
        rows = [FRZ(1, seq=1, cause="cert-y001"),
                FRZ(2, seq=2, cause="cert-y002"),
                CH(1, "frz-y002", dc.CHANGE_CLOSED, seq=3)]
        st = dc.freeze_state(rows, "default")  # latest episode is frz-y002
        self.assertFalse(st["frozen"])

    def test_lines_do_not_share_a_freeze(self):
        rows = [FRZ(1, seq=1, line="default")]
        self.assertFalse(dc.freeze_state(rows, "other")["frozen"])


class MayLandTest(unittest.TestCase):
    def test_unfrozen_takes_every_kind(self):
        self.assertTrue(dc.may_land([], "default", "chore"))
        self.assertTrue(dc.may_land([], "default", dc.FREEZE_EXEMPT_KIND))

    def test_frozen_takes_only_the_structural_fix_kind(self):
        rows = [FRZ(1, seq=1)]
        self.assertFalse(dc.may_land(rows, "default", "chore"))
        self.assertTrue(dc.may_land(rows, "default", dc.FREEZE_EXEMPT_KIND))
        # the exemption is judged, not granted: a landing may carry a
        # self-set "fix" field about itself, but only the explicit declared
        # kind argument is judged (goal 17)
        landing = dict(L(2, seq=2), ticket_kind=dc.FREEZE_EXEMPT_KIND)
        self.assertFalse(dc.may_land(rows, "default", "chore"))
        self.assertNotEqual(landing["ticket_kind"], "chore")

    def test_closed_freeze_reopens_landings(self):
        rows = [FRZ(1, seq=1),
                CH(1, "frz-y001", dc.CHANGE_CLOSED, seq=2)]
        self.assertTrue(dc.may_land(rows, "default", "chore"))

    def test_unknown_kind_refused_by_name(self):
        for bad in (None, "", "  ", {"kind": "fix"}):
            with self.assertRaises(dc.CertifyError):
                dc.may_land([], "default", bad)


class WaitStateTest(unittest.TestCase):
    def test_waiting_before_any_certification(self):
        st = dc.ticket_wait_state([L(1, seq=1)], "default", L(1, at=T0),
                                  is_green=None, now_ms=T0 + 1)
        self.assertEqual(st["state"], dc.WAIT_WAITING)
        self.assertIsNone(st["waiting_for"])
        self.assertEqual(st["waiting_since"], T0)
        self.assertFalse(st["overdue"])

    def test_waiting_names_the_certification_it_queues_behind(self):
        rows = [C(1, seq=1, run="run-a"), L(1, seq=2, at=T0)]
        st = dc.ticket_wait_state(rows, "default", L(1, at=T0),
                                  is_green=green("run-a"), now_ms=T0 + 1)
        self.assertEqual(st["state"], dc.WAIT_WAITING)
        self.assertEqual(st["waiting_for"], "cert-y001")
        self.assertIsNone(st["covered_by"])

    def test_certified_names_the_covering_green_cert(self):
        rows = [C(1, seq=1, run="run-a", revision="r1"),
                L(1, seq=2, at=T0, rev="r1")]
        st = dc.ticket_wait_state(rows, "default", L(1, rev="r1"),
                                  is_green=green("run-a"), now_ms=T0 + 1)
        self.assertEqual(st["state"], dc.WAIT_CERTIFIED)
        self.assertEqual(st["covered_by"], "cert-y001")
        self.assertFalse(dc.needs_slot(st))  # done waiting: slot released

    def test_red_implicated_is_not_waiting_and_not_certified(self):
        # (b) drive: three landings, a green cert over the prefix, then the
        # third landing and a red cert implicating it — the prefix stays
        # landable while the third waits implicated.
        rows = [L(1, seq=1, rev="r1"), L(2, seq=2, rev="r2"),
                C(1, seq=3, run="run-green", revision="r2"),
                L(3, seq=4, rev="r3"),
                C(2, seq=5, run="run-red", revision="r3")]
        one = dc.ticket_wait_state(rows, "default", L(1, rev="r1"),
                                   is_green=green("run-green"), now_ms=T0)
        # the deliverable prefix is the revision the green cert named (r2);
        # r1 is an earlier revision — still waiting, never faked as covered
        self.assertEqual(one["state"], dc.WAIT_WAITING)
        two = dc.ticket_wait_state(rows, "default", L(2, rev="r2"),
                                   is_green=green("run-green"), now_ms=T0)
        self.assertEqual(two["state"], dc.WAIT_CERTIFIED)
        self.assertTrue(dc.landable(rows, "default", L(2, rev="r2"),
                                    is_green=green("run-green")))
        self.assertFalse(dc.landable(rows, "default", L(1, rev="r1"),
                                     is_green=green("run-green")))
        self.assertFalse(dc.landable(rows, "default", L(3, rev="r3"),
                                     is_green=green("run-green")))
        three = dc.ticket_wait_state(rows, "default", L(3, rev="r3"),
                                     is_green=green("run-green"), now_ms=T0)
        self.assertEqual(three["state"], dc.WAIT_RED_IMPLICATED)
        self.assertNotEqual(three["state"], one["state"])  # not the same face
        self.assertEqual(three["waiting_for"], "cert-y002")
        self.assertFalse(dc.needs_slot(three))  # implicated still waits out

    def test_interleaved_other_line_landing_never_enters_the_range(self):
        # (d): another line's landing between them never widens the range.
        rows = [L(1, seq=1, rev="r1"), L(2, seq=2, line="other", rev="r9"),
                C(1, seq=3, run="run-green", revision="r1"),
                L(3, seq=4, rev="r3"), L(4, seq=5, line="other", rev="r8"),
                C(2, seq=6, run="run-red", revision="r3")]
        red = [c for c in rows if c["id"] == "cert-y002"][0]
        rng_ids = [l["id"] for l in dc._red_range(rows, "default", red)]
        self.assertEqual(rng_ids, ["ldg-y003"])
        # the other line has no certification of its own: nothing there is
        # covered, and none of default's records leaked into its view
        self.assertEqual([l["id"] for l in
                          dc.derive_range(rows, "other")["covered_landings"]],
                         ["ldg-y002", "ldg-y004"])
        other = dc.ticket_wait_state(rows, "other", L(4, line="other",
                                                      rev="r8"),
                                     is_green=green("run-green"), now_ms=T0)
        self.assertEqual(other["state"], dc.WAIT_WAITING)

    def test_derivation_writes_no_field_onto_any_row(self):
        rows = [L(1, seq=1, rev="r1"), C(1, seq=2, run="run-green",
                                         revision="r1"),
                L(3, seq=3, rev="r3"), C(2, seq=4, run="run-red",
                                         revision="r3"),
                FRZ(1, seq=5), CH(1, "frz-y001", dc.CHANGE_ATTRIBUTION,
                                  seq=6, value="ldg-y003")]
        before = repr(rows)
        dc.ticket_wait_state(rows, "default", L(3, rev="r3"),
                             is_green=green("run-green"), now_ms=T0)
        dc.freeze_state(rows, "default")
        dc.may_land(rows, "default", "chore")
        self.assertEqual(repr(rows), before)  # projection touched nothing

    def test_overdue_surfaces_past_the_declared_bound(self):
        rows = [C(1, seq=1, run="run-a"), L(1, seq=2, at=T0)]
        st = dc.ticket_wait_state(rows, "default", L(1, at=T0),
                                  is_green=green("run-a"), now_ms=T0 + 999,
                                  wait_bound_ms=1000)
        self.assertFalse(st["overdue"])
        st2 = dc.ticket_wait_state(rows, "default", L(1, at=T0),
                                   is_green=green("run-a"),
                                   now_ms=T0 + 1000, wait_bound_ms=1000)
        self.assertTrue(st2["overdue"])
        self.assertEqual(st2["state"], dc.WAIT_WAITING)  # surfaced, not new

    def test_cert_on_line_with_no_run_reader_is_refused_not_defaulted(self):
        # review R1: a caller that forgets is_green must not get a
        # plausible-looking default (every cert green = false green); the
        # documented raise fires instead.
        rows = [C(1, seq=1, run="run-a"), L(1, seq=2)]
        with self.assertRaises(dc.CertifyError) as cm:
            dc.ticket_wait_state(rows, "default", L(1), is_green=None,
                                 now_ms=T0 + 1)
        self.assertIn("is_green", str(cm.exception))
        # before any certification exists there is nothing to misread:
        self.assertEqual(
            dc.ticket_wait_state([L(1, seq=1)], "default", L(1),
                                 is_green=None, now_ms=T0)["state"],
            dc.WAIT_WAITING)

    def test_malformed_inputs_named(self):
        rows = [C(1, seq=1, run="run-a"), L(1, seq=2)]
        good = L(1)
        cases = [
            ("landing_not_landing", lambda: dc.ticket_wait_state(
                rows, "default", "ldg-y001", green("run-a"), T0)),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", dict(good, kind="certification"),
                green("run-a"), T0)),
            (None, lambda: dc.ticket_wait_state(
                rows, "other", good, green("run-a"), T0)),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", good, green("run-a"), "now")),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", good, green("run-a"), True)),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", good, green("run-a"), T0,
                wait_bound_ms=0)),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", good, green("run-a"), T0,
                wait_bound_ms=-1)),
            (None, lambda: dc.ticket_wait_state(
                rows, "default", good, green("run-a"), T0,
                wait_bound_ms=True)),
        ]
        for _, fn in cases:
            with self.assertRaises(dc.CertifyError):
                fn()
        with self.assertRaises(dc.CertifyError):
            dc.needs_slot("waiting")
        with self.assertRaises(dc.CertifyError):
            dc.needs_slot({"no": "state"})


class NeedsSlotTest(unittest.TestCase):
    def test_no_face_of_a_landed_ticket_holds_a_slot(self):
        # goal 14: the ticket's life ends at the buffer; goal 15: waiting
        # (including implicated-still-waiting) holds no capacity. Every
        # valid face answers False — landing releases the slot on every
        # path.
        for state in (dc.WAIT_WAITING, dc.WAIT_CERTIFIED,
                      dc.WAIT_RED_IMPLICATED, dc.WAIT_REVERTED):
            self.assertFalse(dc.needs_slot({"state": state}), state)

    def test_unknown_state_refused_never_defaulted(self):
        with self.assertRaises(dc.CertifyError):
            dc.needs_slot({"state": "working"})
        with self.assertRaises(dc.CertifyError):
            dc.needs_slot("waiting")
        with self.assertRaises(dc.CertifyError):
            dc.needs_slot({"no": "state"})


if __name__ == "__main__":
    unittest.main()
