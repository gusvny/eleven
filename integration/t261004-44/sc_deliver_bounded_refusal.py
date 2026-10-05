#!/usr/bin/env python3
"""sc_deliver_bounded_refusal.py — t261004-44 KI-197 scenario (grey-box L3, offline
seconds, zero docker/Temporal, never touches 3099/7233).

Intent (user-perceivable): the deliver caller can always tell "this face is dead" from
"slow" — an unknown workflow class on the running worker is an immediate named refusal
(rc != 0, names the class and the worker's registered set), a wedged engine is a bounded
refusal, never a hang; and the refusal survives its own audit-append failing.

Steps (contract per ticket B + plan D1/D2 + review conditions C1/C2/C3):
  D1 fingerprint face, class absent -> immediate refusal, workflow never started.
  D2 fingerprint face, class present -> happy path unaffected (stale-safe fast path,
     never a false refusal).
  D3 no fingerprint file, engine never answers -> bounded refusal within
     SANDBAR_DELIVER_TIMEOUT_S, workflow handle cancelled (no zombie inherits the bucket),
     refusal names the class and the timed-out wait (degradation named, never silent).
  D4 the duplicate-id fallback receipt await (client.py 'already started' branch) is
     inside the SAME bounded wait (review C1 — today that second bare result() hangs).
  E5 the refusal is fail-open over its own audit-ledger append (review C2): append raises
     -> caller still gets the named refusal, rc != 0.

TDD note: red expected before the implement stage lands (faces absent = FAIL named, not
crash, so the pre-implement round reads as the TDD signal it is).
"""
import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.getcwd()
ENGINE = os.path.join(REPO, "server", "engine")
FAILS = []


def fail(msg):
    print("FAIL " + msg)
    FAILS.append(msg)


def find_fingerprint_face():
    """Locate the worker registration fingerprint face on the engine modules (the
    worker/client shared contract, plan D1 — landed as server/engine/worker_registry.py).
    Discovery is by symbol name so the scenario stays binding-light."""
    import worker_registry  # noqa: PLC0415
    import shared  # noqa: PLC0415
    import client  # noqa: PLC0415
    for mod in (worker_registry, client, shared):
        for name in dir(mod):
            if "FINGERPRINT" not in name.upper():
                continue
            obj = getattr(mod, name)
            if callable(obj):
                try:
                    p = obj({})
                    if isinstance(p, str):
                        return p
                except TypeError:
                    try:
                        p = obj()
                        if isinstance(p, str):
                            return p
                    except Exception:
                        pass
            elif isinstance(obj, str):
                return obj
    return None


class StubHandle:
    def __init__(self, hang=False, receipt=None):
        self.hang = hang
        self.receipt = receipt or {"delivered": True}
        self.cancelled = False
        self._ev = None

    def _event(self):
        # Created lazily inside the running loop (asyncio.Event binds its loop at
        # construction on py3.9 — constructing it outside a loop crashes there).
        if self._ev is None:
            self._ev = asyncio.Event()
        return self._ev

    async def result(self):
        if self.hang:
            await self._event().wait()
        return self.receipt

    async def cancel(self, *a, **k):
        self.cancelled = True
        self._event().set()
        return True


class StubClient:
    """Stands in for the Temporal transport; records every workflow-start attempt."""

    def __init__(self, handle=None, already_started=False):
        self.handle = handle or StubHandle()
        self.start_calls = []
        self.already_started = already_started

    async def start_workflow(self, cls, payload, id=None, task_queue=None):  # noqa: A002
        self.start_calls.append({"cls": cls, "id": id})
        if self.already_started:
            raise Exception("Workflow execution already started: ExecutionAlreadyStarted")
        return self.handle

    def get_workflow_handle(self, wf_id):
        return self.handle


async def run_deliver(monkey, env_overrides):
    client = monkey["client"]
    # Deliberate-test caller identity (L12: strip-then-inject, never inherited): the
    # scenario drives the deliver face past the caller gate so the refusal under test
    # is the delivery-face refusal, not the identity gate's.
    env = {
        "SANDBAR_CALLER_PROJECT": "sc-deliver-proj",
        "DSH_SESSION_ID": "session-sc44-deliver",
        "SANDBAR_CALLER_IDENTITY_SRC": "sc-fixture",
        "SANDBAR_PROJECTS_DIR": monkey["tmp"],
    }
    env.update(env_overrides)
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return await client.cmd_deliver({"face": "request", "body": {"note": "sc"}})
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    if not os.path.isdir(ENGINE):
        print("ENV_FAIL: engine tree missing: " + ENGINE)
        return 2
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)
    try:
        client = importlib.import_module("client")
        shared = importlib.import_module("shared")
    except Exception as e:  # noqa: BLE001
        print(f"ENV_FAIL: engine modules unimportable: {type(e).__name__}: {e}")
        return 2

    tmp = tempfile.mkdtemp(prefix="sc-deliver-")
    # Redirect HOME before face discovery: the fingerprint face derives from the
    # instance home (~/.sandbar), and expanduser honors $HOME — the scenario must
    # never read or write the real instance root.
    os.environ["HOME"] = tmp
    # Seed the caller's project registry under the redirected projects root, plus the
    # executor-grants declaration that names the fixture session (the caller gate must
    # pass so the refusal under test is the delivery-face refusal, not the gate's).
    os.makedirs(os.path.join(tmp, "sc-deliver-proj"), exist_ok=True)
    with open(os.path.join(tmp, "sc-deliver-proj", "project.yaml"), "w") as f:
        f.write("name: sc-deliver-proj\ndirs:\n  - %s\n" % tmp)
    with open(os.path.join(tmp, "sc-deliver-proj", "executor-grants.json"), "w") as f:
        json.dump({"version": 1, "executor_sessions": ["session-sc44-deliver"],
                   "grants": {}, "updated_by": "sc-fixture", "updated_at": int(time.time() * 1000)}, f)
    fp = os.path.join(tmp, "worker-registry.json")
    monkey = {"client": client, "shared": shared, "tmp": tmp, "orig_connect": client._connect,
              "fp_env": {"SANDBAR_WORKER_REGISTRY_FINGERPRINT": fp}}
    try:
        # ── D1: fingerprint face present, class ABSENT -> immediate named refusal ──
        fp_path = find_fingerprint_face()
        if not fp_path:
            fail("D0 worker registration fingerprint face not discoverable on client/shared "
                 "(plan D1 not landed; without it deliver cannot tell 'class absent' from 'slow')")
        else:
            with open(fp, "w") as f:
                json.dump({"version": 1, "pid": os.getpid(), "started_at_ms": int(time.time() * 1000),
                           "registered": ["SomeOtherWorkflow", "SecondWorkflow"]}, f)
            stub = StubClient()
            client._connect = lambda: _async_stub(stub)
            r = asyncio.run(run_deliver(monkey, {**monkey["fp_env"], "SANDBAR_DELIVER_TIMEOUT_S": "5"}))
            if r.get("ok") is not False:
                fail(f"D1 class-absent did not refuse: {str(r)[:200]}")
            else:
                text = str(r.get("error", ""))
                if "ExecutorDeliveryWorkflow" not in text:
                    fail("D1 refusal does not name the missing workflow class (review B5): " + text[:200])
                if "SomeOtherWorkflow" not in text:
                    fail("D1 refusal does not name the worker's registered set: " + text[:200])
            if stub.start_calls:
                fail("D1 workflow was STARTED despite the class-absent fingerprint (refusal must precede the start)")

        # ── D2: class present -> happy path unaffected ──
        if fp_path:
            with open(fp, "w") as f:
                json.dump({"version": 1, "pid": os.getpid(), "started_at_ms": int(time.time() * 1000),
                           "registered": ["ExecutorDeliveryWorkflow", "Other"]}, f)
            handle = StubHandle(receipt={"delivered": True, "face": "request"})
            stub = StubClient(handle=handle)
            client._connect = lambda: _async_stub(stub)
            r = asyncio.run(run_deliver(monkey, {**monkey["fp_env"], "SANDBAR_DELIVER_TIMEOUT_S": "5"}))
            if r.get("ok") is not True:
                fail(f"D2 class-present path broke the happy path: {str(r)[:200]}")

        # ── D3: no fingerprint, engine never answers -> bounded refusal + cancel ──
        handle = StubHandle(hang=True)
        stub = StubClient(handle=handle)
        client._connect = lambda: _async_stub(stub)
        t0 = time.monotonic()
        r = asyncio.run(run_deliver(monkey, {"SANDBAR_WORKER_REGISTRY_FINGERPRINT": os.path.join(tmp, "absent-registry.json"), "SANDBAR_DELIVER_TIMEOUT_S": "5"}))
        wall = time.monotonic() - t0
        if wall > 30:
            fail(f"D3 deliver hung: {wall:.1f}s wall (bounded wait absent or not applied)")
        if r.get("ok") is not False:
            fail(f"D3 wedged engine returned neither receipt nor refusal: {str(r)[:200]}")
        else:
            text = str(r.get("error", ""))
            if "ExecutorDeliveryWorkflow" not in text:
                fail("D3 timeout refusal does not name the class: " + text[:200])
            if "fingerprint" not in text.lower():
                fail("D3 fingerprint-absent degradation not named in the refusal (named, never silent): " + text[:200])
        if not handle.cancelled:
            fail("D3 wedged workflow handle was not cancelled (zombie inherits the bucket forever)")

        # ── D4: duplicate-id fallback receipt is bounded too (review C1) ──
        handle = StubHandle(hang=True)
        stub = StubClient(handle=handle, already_started=True)
        client._connect = lambda: _async_stub(stub)
        t0 = time.monotonic()
        r = asyncio.run(run_deliver(monkey, {"SANDBAR_WORKER_REGISTRY_FINGERPRINT": os.path.join(tmp, "absent-registry.json"), "SANDBAR_DELIVER_TIMEOUT_S": "5"}))
        wall = time.monotonic() - t0
        if wall > 30:
            fail(f"D4 duplicate-id fallback hung: {wall:.1f}s wall — the 'already started' "
                 "result() await is outside the bounded wait (review C1)")
        if r.get("ok") is not False or "ExecutorDeliveryWorkflow" not in str(r.get("error", "")):
            fail(f"D4 fallback path returned neither named refusal nor receipt: {str(r)[:200]}")
        if not handle.cancelled:
            fail("D4 fallback handle not cancelled on timeout")

        # ── E5: the refusal is fail-open over its own audit-ledger append (review C2) ──
        # Injection point is the audit append itself (executor_grants.append_audit) —
        # the record wrapper IS the fail-open seam under test; patching it would be
        # patching the property, not exercising it.
        eg = getattr(client, "executor_grants", None)
        if eg is None or not hasattr(eg, "append_audit"):
            fail("E0 deliver-refused audit append face not discoverable on client (plan D1/D2 "
                 "ledger row not landed; the watchdog cannot see refusals without it)")
        else:
            target = eg.append_audit

            def boom(*a, **k):
                raise OSError("sc: ledger append injected failure")
            handle = StubHandle(hang=True)
            stub = StubClient(handle=handle)
            client._connect = lambda: _async_stub(stub)
            eg.append_audit = boom
            try:
                r = asyncio.run(run_deliver(monkey, {"SANDBAR_WORKER_REGISTRY_FINGERPRINT": os.path.join(tmp, "absent-registry.json"), "SANDBAR_DELIVER_TIMEOUT_S": "5"}))
            finally:
                eg.append_audit = target
            if r.get("ok") is not False or "ExecutorDeliveryWorkflow" not in str(r.get("error", "")):
                fail(f"E5 audit-append failure blocked or mangled the caller's refusal: {str(r)[:200]}")
            elif "audit" not in str(r.get("error", "")).lower():
                fail("E5 audit-append failure not named in the refusal text (named, never silent): "
                     + str(r.get("error", ""))[:200])
    finally:
        client._connect = monkey["orig_connect"]
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"SC_DELIVER_BOUNDED_REFUSAL fails={len(FAILS)}")
    return 0 if not FAILS else 1


async def _async_stub(stub):
    return stub


if __name__ == "__main__":
    raise SystemExit(main())
