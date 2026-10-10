# -*- coding: utf-8 -*-
"""t261009-55 UT: the read face survives a poller gap BY NAME.

Covers client._augment_read_failure_receipt / _orphan_window_note with stub handles
(no Temporal, no network) — the ticket/detail degrade contract:

- the receipt's kind/wording are byte-identical (the t260919-02 face discipline:
  add keys, never change semantics or the HTTP level);
- the face gains a `durable` block: describe status, memo-sourced last stage +
  last known time (the engine's own durable store — authoritative for "where was
  this ticket last seen", never for the stage decision), and the
  unavailable(<named cause> @ queue=<q> ticket=<tid>) label distinguishing
  no_poller from query_timeout;
- the orphan window is named (spec 4): the STARTED-task start_to_close (499s)
  wait is stated, the timeout value itself untouched;
- malformed inputs (memo raises, memo missing, junk history shapes, wrong kind)
  degrade honestly — never a half-made face, never a raised test-visible error.
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import client  # noqa: E402

TID = "t26100955-read"
QUEUE = "sandbar-ticket-t26100955-read"


class _Status:
    name = "RUNNING"


class _Desc:
    status = _Status()

    def __init__(self, memo=None, raise_attr=False, raise_err=False):
        self._memo = memo
        self._raise_attr = raise_attr
        self._raise_err = raise_err

    async def memo(self):
        if self._raise_attr:
            raise AttributeError("no memo face")
        if self._raise_err:
            raise RuntimeError("memo decode failed")
        return self._memo


def _no_poller_receipt():
    class _Exc(Exception):
        pass
    face = {"ticket": TID, "queue": QUEUE, "available": True, "live_pollers": 0,
            "stale_history": 0, "unverifiable": 0, "note": "proven zero"}
    return client._classify_snapshot_failure(_Exc("timeout"), TID, QUEUE, face)


def _transient_receipt():
    return client._err("query_timeout: jitter", client.KIND_TRANSIENT)


class OrphanWindowNoteTest(unittest.TestCase):
    def test_names_platform_wait_and_timeout(self):
        note = client._orphan_window_note("no_poller")
        self.assertIn("orphan window", note)
        self.assertIn("start_to_close_timeout", note)
        self.assertIn("499s", note)
        self.assertIn("waiting on the platform, not stuck", note)
        self.assertIn("cause=no_poller", note)


class AugmentReceiptTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_no_poller_receipt_gains_durable_face(self):
        receipt = _no_poller_receipt()
        memo = {"sandbar_stage": "review_plan",
                "sandbar_stage_history": [{"ts": 1700000100, "stage": "review_plan", "note": ""}]}
        out = self._run(client._augment_read_failure_receipt(
            receipt, TID, None, _Desc(memo)))
        # kind + wording byte-identical
        self.assertEqual(out, receipt)                      # augmented IN PLACE
        self.assertEqual(out["kind"], "no_poller")
        dur = out["face"]["durable"]
        self.assertEqual(dur["status"], "RUNNING")
        self.assertEqual(dur["last_stage"], "review_plan")
        self.assertTrue(dur["last_stage_available"])
        self.assertEqual(dur["updated_ts"], 1700000100)
        self.assertTrue(dur["updated"])
        self.assertIn("unavailable(no_poller", dur["unavailable"])
        self.assertIn(QUEUE, dur["unavailable"])
        self.assertIn(TID, dur["unavailable"])
        self.assertIn("499s", dur["orphan_window_note"])
        # the structured poller face survives next to the durable block
        self.assertEqual(out["face"]["live_pollers"], 0)

    def test_query_timeout_labels_its_own_cause(self):
        out = self._run(client._augment_read_failure_receipt(
            _transient_receipt(), TID, None, _Desc(None)))
        self.assertEqual(out["kind"], "transient")
        dur = out["face"]["durable"]
        self.assertIn("unavailable(query_timeout", dur["unavailable"])
        self.assertIn("499s", dur["orphan_window_note"])
        self.assertFalse(dur["last_stage_available"])
        self.assertIn("durable_note", dur)   # honest "nothing durable readable"
        self.assertEqual(dur["updated_ts"], 0)
        self.assertEqual(dur["updated"], "")

    def test_memo_failures_degrade_without_guessing(self):
        for desc in (_Desc(raise_attr=True), _Desc(raise_err=True), _Desc(None)):
            out = self._run(client._augment_read_failure_receipt(
                _transient_receipt(), TID, None, desc))
            dur = out["face"]["durable"]
            self.assertFalse(dur["last_stage_available"], desc)
            self.assertEqual(dur["last_stage"], None)
            self.assertEqual(dur["updated_ts"], 0)
            self.assertTrue(dur["last_stage_note"])   # named why, never a guess

    def test_junk_history_shapes_fail_closed(self):
        for hist in ({}, ["x"], [{"ts": "NaN"}], [{"ts": None}], [{"nope": 1}]):
            memo = {"sandbar_stage": "s", "sandbar_stage_history": hist}
            out = self._run(client._augment_read_failure_receipt(
                _transient_receipt(), TID, None, _Desc(memo)))
            self.assertEqual(out["face"]["durable"]["updated_ts"], 0, hist)

    def test_other_kinds_untouched(self):
        receipt = client._err("boom", client.KIND_INTERNAL)
        out = self._run(client._augment_read_failure_receipt(receipt, TID, None, _Desc(None)))
        self.assertNotIn("face", out)

    def test_desc_exploding_leaves_receipt_usable(self):
        class _Boom:
            status = None
            def __getattr__(self, name):
                raise RuntimeError("describe exploded")
        out = self._run(client._augment_read_failure_receipt(
            _transient_receipt(), TID, None, _Boom()))
        self.assertEqual(out["kind"], "transient")   # receipt untouched, no raise


if __name__ == "__main__":
    unittest.main()
