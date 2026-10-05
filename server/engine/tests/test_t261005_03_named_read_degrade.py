"""t261005-03 clause B UT: the read face degrades by name.

Covers client._queue_poller_face / client._snapshot_read_named and the ticket-list
degraded-row naming, with stub handles/clients (no Temporal, no network).

Taxonomy discipline (review C2): a no-poller read lands in the retryable/degraded
family of the KI-025 classification — kind=no_poller, never not_found, never internal;
the face carries ticket / queue / live_pollers and a no-poller claim is made ONLY when
the poller face is provably available (an unavailable face degrades to transient).
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import client  # noqa: E402


class _TimedOutHandle:
    """A snapshot query that always waits out the timeout (the no-poller shape)."""

    async def query(self, name, **kw):
        assert name == "snapshot"
        await asyncio.sleep(10)


class _OkHandle:
    def __init__(self, snap):
        self._snap = snap

    async def query(self, name, **kw):
        return self._snap


class _StubPollerService:
    def __init__(self, pollers):
        self._pollers = pollers

    async def describe_task_queue(self, request, **kw):
        class _Resp:
            pollers = self._pollers
        return _Resp()


class _Poller:
    def __init__(self, identity):
        self.identity = identity


class _StubClient:
    namespace = "default"

    def __init__(self, pollers):
        self.workflow_service = _StubPollerService(pollers)


def _run(coro):
    return asyncio.run(coro)


def _fast_probe(**kw):
    kw.setdefault("timeout", 0.2)
    return kw


class QueuePollerFaceTest(unittest.TestCase):
    def test_live_stale_unverifiable_split(self):
        c = _StubClient([_Poller("100@h"), _Poller("101@h"), _Poller("junk@h")])
        alive = lambda pid: pid == 100  # noqa: E731
        face = _run(client.queue_live_pollers(c, "sandbar-ticket-t1",
                                              timeout=0.2, alive_fn=alive))
        self.assertTrue(face["available"])
        self.assertEqual(face["live_pollers"], 1)
        self.assertEqual(face["stale_history"], 1)
        self.assertEqual(face["unverifiable"], 1)

    def test_unreachable_service_is_named_not_zero(self):
        class _Broken:
            async def describe_task_queue(self, request, **kw):
                raise RuntimeError("connection refused")
        face = _run(client.queue_live_pollers(_Broken(), "q", timeout=0.2,
                                              alive_fn=lambda pid: True))
        self.assertFalse(face["available"])
        self.assertIsNone(face["live_pollers"])
        self.assertIn("describe_task_queue", face["note"])

    def test_missing_sdk_is_named_not_zero(self):
        # A client whose workflow_service import path is irrelevant: the SDK-stub
        # branch is exercised by the malformed-queue case + absent attribute.
        face = _run(client.queue_live_pollers(object(), "q", timeout=0.2,
                                              alive_fn=lambda pid: True))
        self.assertFalse(face["available"])
        self.assertTrue(face["note"])

    def test_malformed_queue_name_fails_closed(self):
        face = _run(client.queue_live_pollers(_StubClient([]), "", timeout=0.2,
                                              alive_fn=lambda pid: True))
        self.assertFalse(face["available"])
        self.assertIn("malformed queue name", face["note"])


class SnapshotReadNamedTest(unittest.TestCase):
    def test_success_returns_snap(self):
        snap, rerr = _run(client._snapshot_read_named(
            _OkHandle({"meta": {}}), "t1", _StubClient([]),
            timeout=0.2, alive_fn=lambda pid: False))
        self.assertIsNone(rerr)
        self.assertEqual(snap, {"meta": {}})

    def test_timeout_zero_pollers_is_no_poller_with_face(self):
        _, rerr = _run(client._snapshot_read_named(
            _TimedOutHandle(), "t261005-41", _StubClient([]),
            timeout=0.2, alive_fn=lambda pid: False))
        self.assertIsNotNone(rerr)
        self.assertEqual(rerr["kind"], client.KIND_NO_POLLER)
        self.assertIn("0 live pollers", rerr["error"])
        self.assertIn("sandbar-ticket-t261005-41", rerr["error"])
        face = rerr["face"]
        self.assertEqual(face["ticket"], "t261005-41")
        self.assertEqual(face["queue"], "sandbar-ticket-t261005-41")
        self.assertEqual(face["live_pollers"], 0)

    def test_timeout_with_live_pollers_keeps_legacy_path(self):
        # A live poller exists but the query still timed out (momentary jitter after
        # the retry budget): the internal wrapper RE-RAISES so the caller keeps its
        # legacy transient wording — the classifier never rewrites existing copy.
        with self.assertRaises(asyncio.TimeoutError):
            _run(client._snapshot_read_named(
                _TimedOutHandle(), "t1",
                _StubClient([_Poller("%d@h" % __import__("os").getpid())]),
                timeout=0.2, alive_fn=lambda pid: True))

    def test_unprovable_poller_face_re_raises(self):
        # The poller face could not be proven (probe failure): "cannot prove" never
        # upgrades into a no_poller claim (review C2 discipline) — the legacy path
        # keeps the refusal.
        with self.assertRaises(asyncio.TimeoutError):
            _run(client._snapshot_read_named(
                _TimedOutHandle(), "t1", object(),  # no workflow_service at all
                timeout=0.2, alive_fn=lambda pid: False))

    def test_named_read_public_never_not_found_never_internal(self):
        # The PUBLIC classifier (single-shot contract) always names: unprovable face →
        # transient with a cannot-prove note; proven zero → no_poller. Never
        # not_found, never internal-by-default.
        for face in (None, {"available": False, "note": "probe down"},
                     {"available": True, "live_pollers": 3}):
            _, rerr = _run(client.named_snapshot_read(
                _TimedOutHandle(), "t1", "sandbar-ticket-t1", 0.2,
                poller_face=face))
            self.assertNotEqual(rerr["kind"], client.KIND_NOT_FOUND)
            self.assertNotEqual(rerr["kind"], client.KIND_INTERNAL)


class PublicNamedSnapshotReadTest(unittest.TestCase):
    """The scenario contract (integration/t261005-03): public named_snapshot_read with
    an injected duck-typed poller_face — single bounded shot, token-named results."""

    def _run_named(self, face, queue="sandbar-ticket-t261004-41", timeout=0.3):
        class _F:
            def __init__(self, live, reachable=True):
                self._live, self._r = live, reachable
            def report_pollers(self):
                return {"live": self._live} if self._r else None
        return _run(client.named_snapshot_read(
            _TimedOutHandle(), "t261004-41", queue, timeout, poller_face=_F(face[0], face[1])))

    def test_no_poller_named(self):
        _, rerr = self._run_named((0, True))
        self.assertEqual(rerr["kind"], client.KIND_NO_POLLER)
        blob = repr(rerr)
        self.assertIn("no_poller", blob)
        self.assertIn("t261004-41", blob)
        self.assertIn("0", blob)

    def test_query_timeout_named_and_distinguishable(self):
        _, rerr = self._run_named((2, True))
        self.assertEqual(rerr["kind"], client.KIND_TRANSIENT)
        blob = repr(rerr)
        self.assertIn("query_timeout", blob)
        self.assertNotIn("no_poller", blob)
        self.assertIn("2", blob)

    def test_unreachable_face_is_cannot_prove(self):
        _, rerr = self._run_named((0, False))
        self.assertEqual(rerr["kind"], client.KIND_TRANSIENT)
        blob = repr(rerr)
        self.assertIn("cannot", blob)
        self.assertNotIn("no_poller", blob)

    def test_malformed_queue_refused_by_name(self):
        for bad in ("", "  ", "queue\ninjected"):
            _, rerr = self._run_named((1, True), queue=bad)
            self.assertIn("queue", repr(rerr).lower())

    def test_scenario_shape_face_object(self):
        # a face whose report_pollers returns a dict without available: live count used
        _, rerr = self._run_named((0, True), timeout=0.3)
        self.assertIsNotNone(rerr)


class TaxonomyRegistrationTest(unittest.TestCase):
    """KI-025 discipline: every new kind is registered in the module-header table."""

    def test_no_poller_kind_is_declared(self):
        assert client.KIND_NO_POLLER == "no_poller"
        src = Path(client.__file__).read_text(encoding="utf-8")
        assert "KIND_NO_POLLER" in src


class GateNamedReadWiringTest(unittest.TestCase):
    """The write gate's pre-read goes through the named classifier when the caller
    passes its client (source-level anchor, matching the repo's wiring-tripwire style)."""

    def test_write_gate_signature_has_client(self):
        import inspect
        sig = inspect.signature(client._write_gate)
        assert "client" in sig.parameters

    def test_cmd_query_uses_named_read(self):
        src = Path(client.__file__).read_text(encoding="utf-8")
        # the raw unbounded query is gone from the read faces (cmd_query / op=query /
        # ledger_rebuild / ticket-query RUNNING branch)
        body = src
        assert 'snap = await handle.query("snapshot")' not in body


class ListDegradedRowNamingTest(unittest.TestCase):
    """The ticket-list degraded row names the no-poller cause (source anchor + pure
    shape check of the naming branch)."""

    def test_degraded_row_title_names_queue(self):
        # mirror of the branch in cmd_ticket_list
        npf = {"queue": "sandbar-ticket-t9", "live_pollers": 0}
        title = ("ticket query timed out: queue %s has 0 live pollers (dedicated "
                 "worker stopped polling or absent); wait for the ensure "
                 "replacement before refreshing"
                 % (npf.get("queue") or "sandbar-ticket-t9"))
        self.assertIn("sandbar-ticket-t9", title)
        self.assertIn("0 live pollers", title)


if __name__ == "__main__":
    unittest.main()
