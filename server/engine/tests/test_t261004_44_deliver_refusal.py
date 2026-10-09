# -*- coding: utf-8 -*-
"""t261004-44 / KI-197 -- the bounded wait and named refusal of deliver (unit face).

Contract: with a stale worker (does not know ExecutorDeliveryWorkflow), deliver must
exit non-zero with a named refusal (class name + registered set + the failed check
name) and never hang; an absent fingerprint = explicit degradation to the bounded
wait; a bounded-wait timeout = cancel the remote zombie + named refusal + audit row
(fail-open, review C2). All io injected (env / stub client / temp dirs); zero real
Temporal, zero real ~/.sandbar.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worker_registry  # noqa: E402


class FingerprintFaceTests(unittest.TestCase):
    """worker_registry: write / read / check faces (with malformed-input rows -- mandatory for anything consuming an external file)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sub", "worker-registry.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_then_read_roundtrip(self) -> None:
        doc = worker_registry.write_fingerprint(
            self.path, ["A", "ExecutorDeliveryWorkflow"], pid=4242, now_ms=1_000,
            code_fingerprint="sha-ki227", activity_names=["act_a"])
        # t261008-29 (KI-227): fingerprint bumped to v2 — the doc now also carries
        # the code identity and the activity registry.
        self.assertEqual(doc["version"], worker_registry.FINGERPRINT_VERSION)
        self.assertEqual(doc["code_fingerprint"], "sha-ki227")
        self.assertEqual(doc["activities"], ["act_a"])
        self.assertTrue(doc["activity_fingerprint"])
        self.assertEqual(doc["registered"], ["A", "ExecutorDeliveryWorkflow"])
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(err)
        assert got is not None
        self.assertEqual(got["pid"], 4242)

    def test_read_absent_is_named(self) -> None:
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertEqual(err, "absent")

    def test_read_malformed_is_named_not_crash(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json at all")
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertTrue(str(err).startswith("malformed"))

    def test_read_wrong_shape_is_malformed(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 99, "registered": "nope"}, f)
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertTrue(str(err).startswith("malformed"))

    def test_check_class_absent_refuses_with_registered_set(self) -> None:
        doc = worker_registry.write_fingerprint(
            self.path, ["ContentPipelineWorkflow"], pid=1, now_ms=2)
        got, _ = worker_registry.read_fingerprint(self.path)
        chk = worker_registry.delivery_registration_check(got)
        self.assertFalse(chk["ok"])
        self.assertEqual(chk["workflow_class"], "ExecutorDeliveryWorkflow")
        self.assertEqual(chk["registered"], ["ContentPipelineWorkflow"])

    def test_check_class_present_passes_even_if_doc_is_stale(self) -> None:
        """Review C3: a stale fingerprint (old pid / old code) does NOT change the verdict --
        it is not a health certificate; listed = proceed, the staleness risk is carried
        by the bounded wait."""
        got = {"version": 1, "pid": 6, "started_at_ms": 1,
               "code_fingerprint": "old", "registered": ["ExecutorDeliveryWorkflow"]}
        chk = worker_registry.delivery_registration_check(got)
        self.assertTrue(chk["ok"])

    def test_check_absent_doc_degrades_named(self) -> None:
        chk = worker_registry.delivery_registration_check(None)
        self.assertTrue(chk["ok"])
        self.assertIn("fingerprint absent", chk["degraded"])


class DeliverTimeoutTests(unittest.TestCase):
    def test_default_and_floor(self) -> None:
        import client
        self.assertEqual(client.DELIVER_TIMEOUT_DEFAULT_S, 60.0)
        self.assertEqual(client.deliver_timeout_sec({}), 60.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "0.5"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "abc"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "-3"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "7"}), 7.0)


class _NeverWorkflow:
    """Stub workflow handle: result() never returns (replays "the worker does not know the class => infinite retry")."""

    async def result(self) -> "NoReturn":  # type: ignore[name-defined]
        await asyncio.sleep(3600)

    async def cancel(self) -> None:
        self.cancelled = True  # type: ignore[attr-defined]
        return None


class _StubClient:
    """Stub Temporal client: raises or hangs per script."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.handle = _NeverWorkflow()
        self.started = 0

    async def start_workflow(self, wf_class, payload, id=None, task_queue=None):  # noqa: A002
        self.started += 1
        if self.mode == "already-started":
            raise RuntimeError("Workflow execution already started: " + str(id))
        if self.mode == "never":
            await asyncio.sleep(3600)
        raise RuntimeError("unexpected mode %s" % self.mode)

    def get_workflow_handle(self, wf_id: str) -> "_NeverWorkflow":
        return self.handle


class DeliverBoundedTests(unittest.TestCase):
    """_deliver_bounded: must raise TimeoutError, never truly hang for 3600s."""

    def test_bounded_wait_times_out(self) -> None:
        import client
        stub = _StubClient("never")
        async def run() -> None:
            t0 = time.monotonic()
            with self.assertRaises(asyncio.TimeoutError):
                await client._deliver_bounded(stub, "wf-1", {}, 0.15)
            self.assertLess(time.monotonic() - t0, 5.0)
        asyncio.run(run())

    def test_success_returns_receipt(self) -> None:
        import client
        class _Ok(_StubClient):
            async def start_workflow(self, wf_class, payload, id=None, task_queue=None):  # noqa: A002
                class _H:
                    async def result(self):
                        return {"ok": True}
                return _H()
        receipt = asyncio.run(client._deliver_bounded(_Ok("ok"), "wf-2", {}, 5))
        self.assertEqual(receipt, {"ok": True})

    def test_cancel_failure_is_named_not_fatal(self) -> None:
        import client
        class _Bad(_StubClient):
            def get_workflow_handle(self, wf_id):
                class _H:
                    async def cancel(self):
                        raise RuntimeError("handle gone")
                return _H()
        note = asyncio.run(client._cancel_deliver_workflow(_Bad("x"), "wf-3"))
        self.assertIsNotNone(note)
        self.assertIn("cancel failed", note)


class DeliverRegistrationRefusalTests(unittest.TestCase):
    """The pre-flight fingerprint check of cmd_deliver (env points at a temp fingerprint file; no state leaks between tests)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_key = "SANDBAR_WORKER_REGISTRY_FINGERPRINT"
        self.saved = os.environ.get(self.env_key)
        self.path = os.path.join(self.tmp.name, "wr.json")
        os.environ[self.env_key] = self.path

    def tearDown(self) -> None:
        if self.saved is None:
            os.environ.pop(self.env_key, None)
        else:
            os.environ[self.env_key] = self.saved
        self.tmp.cleanup()

    def test_refusal_text_names_class_and_registered_set(self) -> None:
        import client
        worker_registry.write_fingerprint(
            self.path, ["ContentPipelineWorkflow"], pid=9, now_ms=5)
        msg = client._deliver_registration_refusal()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("ExecutorDeliveryWorkflow", msg)
        self.assertIn("ContentPipelineWorkflow", msg)
        self.assertIn("worker-registration-fingerprint", msg)
        self.assertIn("pid 9", msg)

    def test_class_present_passes(self) -> None:
        import client
        worker_registry.write_fingerprint(
            self.path, ["ExecutorDeliveryWorkflow"], pid=9, now_ms=5)
        self.assertIsNone(client._deliver_registration_refusal())

    def test_fingerprint_absent_degrades_to_bounded_wait(self) -> None:
        import client
        self.assertIsNone(client._deliver_registration_refusal())


class RecordDeliverRefusalTests(unittest.TestCase):
    """Audit row fail-open (review C2): a raising append_audit never withholds the refusal; the failure is named."""

    def test_append_failure_is_named(self) -> None:
        import client
        import executor_grants
        orig = executor_grants.append_audit
        def boom(key, row):
            raise RuntimeError("disk full")
        executor_grants.append_audit = boom
        try:
            note = client._record_deliver_refusal("proj", "sess-1", "request",
                                                  "delivery-deadline", "why")
        finally:
            executor_grants.append_audit = orig
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("audit row not filed", note)
        self.assertIn("RuntimeError", note)

    def test_row_shape_and_landing(self) -> None:
        import client
        import executor_grants
        with tempfile.TemporaryDirectory() as td:
            saved = dict(os.environ)
            os.environ["SANDBAR_PROJECTS_DIR"] = td
            try:
                importlib.reload(executor_grants)
                note = client._record_deliver_refusal("proj", "sess-1", "request",
                                                      "delivery-deadline", "why")
                self.assertIsNone(note)
                path = os.path.join(td, "proj", executor_grants.AUDIT_FILE)
                with open(path, "r", encoding="utf-8") as f:
                    row = json.loads(f.readline())
                self.assertEqual(row["kind"], "deliver_refused")
                self.assertEqual(row["who"], "sess-1")
                self.assertEqual(row["face"], "request")
                self.assertEqual(row["workflow_class"], "ExecutorDeliveryWorkflow")
            finally:
                os.environ.clear()
                os.environ.update(saved)
                importlib.reload(executor_grants)


if __name__ == "__main__":
    unittest.main()


class DeliverCmdRefusalTests(unittest.TestCase):
    """cmd_deliver-level L1 (stub client, zero Temporal): class absent = named refusal
    rc!=0; a hanging already-started receipt read = bounded refusal (review C1); the
    audit row is filed (C2)."""

    def _run_deliver(self, mode: str) -> "tuple[dict, list]":
        import client as client_mod
        import executor_requests
        saved_env = os.environ.get(client_mod.DELIVER_TIMEOUT_ENV)
        os.environ[client_mod.DELIVER_TIMEOUT_ENV] = "0.2"
        audit_calls: list = []
        orig_caller = executor_requests.resolve_caller
        orig_reg = getattr(client_mod, "load_projects_registry", None)
        orig_conn = client_mod._connect
        orig_audit = client_mod._record_deliver_refusal

        def fake_caller(*a, **k):
            return {"ok": True, "project": "proj", "session": "sess-1",
                    "channel": "cwd", "channel_src": "cwd"}

        client_mod.executor_requests.resolve_caller = fake_caller
        client_mod._record_deliver_refusal = (
            lambda project, who, face, check, reason: audit_calls.append(
                (project, who, face, check)) and None)
        stub = _StubClient(mode)
        client_mod._connect = lambda: _async_return(stub)
        try:
            out = asyncio.run(client_mod.cmd_deliver({"face": "request", "body": {}}))
        finally:
            executor_requests.resolve_caller = orig_caller
            client_mod._connect = orig_conn
            client_mod._record_deliver_refusal = orig_audit
            if orig_reg is not None:
                client_mod.load_projects_registry = orig_reg
            if saved_env is None:
                os.environ.pop(client_mod.DELIVER_TIMEOUT_ENV, None)
            else:
                os.environ[client_mod.DELIVER_TIMEOUT_ENV] = saved_env
        return out, audit_calls

    def test_unknown_class_refused_named_no_start(self) -> None:
        import client as client_mod
        saved = os.environ.get("SANDBAR_WORKER_REGISTRY_FINGERPRINT")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "wr.json")
            worker_registry.write_fingerprint(path, ["ContentPipelineWorkflow"],
                                              pid=3, now_ms=1)
            os.environ["SANDBAR_WORKER_REGISTRY_FINGERPRINT"] = path
            try:
                out, audit_calls = self._run_deliver("never")
            finally:
                if saved is None:
                    os.environ.pop("SANDBAR_WORKER_REGISTRY_FINGERPRINT", None)
                else:
                    os.environ["SANDBAR_WORKER_REGISTRY_FINGERPRINT"] = saved
        self.assertFalse(out["ok"])
        self.assertEqual(out["kind"], "deliver_refused")
        self.assertIn("ExecutorDeliveryWorkflow", out["error"])
        self.assertIn("ContentPipelineWorkflow", out["error"])
        self.assertIn("worker-registration-fingerprint", out["error"])
        self.assertEqual(len(audit_calls), 1)

    def test_duplicate_started_never_resolves_is_bounded_refusal(self) -> None:
        """Review C1: a hanging duplicate-started receipt read -> a bounded named refusal, not a second bare result()."""
        import time as _t
        t0 = _t.monotonic()
        out, audit_calls = self._run_deliver("already-started")
        self.assertLess(_t.monotonic() - t0, 10.0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["kind"], "deliver_refused")
        self.assertIn("delivery-deadline-first-receipt", out["error"])
        self.assertIn("ExecutorDeliveryWorkflow", out["error"])
        self.assertEqual(audit_calls, [("proj", "sess-1", "request",
                                        "delivery-deadline-first-receipt")])


def _async_return(v):
    async def _g():
        return v
    return _g()
