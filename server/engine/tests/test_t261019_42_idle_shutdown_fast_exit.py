"""Unit tests for the t261019-42 fast idle-exit shutdown path (worker.py).

Incident: on 261019 a worker whose roll-call said "nothing in flight" lingered
for the full 30-minute graceful window after TERM (twice), because the guard
registry is blind to short activities (merge_check, inspection, lane, executor)
while the SDK holds shutdown until ITS running-activity set drains.

Fix under test:
  1. idle_shutdown_deadline_sec — env parser, fault tolerance identical to
     graceful_shutdown_timeout_sec ("0" = fast path off).
  2. sdk_running_activity_count — guarded private-attr introspection; None on
     any unreadable shape (callers treat None as NOT idle, fail-safe).
  3. _graceful_shutdown gating — the deadline race fires ONLY when all three
     faces are empty (registry, spawns, sdk count); the 261019 incident shape
     (registry empty, SDK busy) keeps the FULL grace window; the epilogue
     (outcome ledger + spawn reap receipt) runs in every branch.

Zero real Temporal, zero network, zero model: worker stubs are plain objects;
module collaborators are monkeypatched. Malformed env values are the mandatory
hostile-input cases (stubbed, not external).
"""

import asyncio
import logging
import os
import time
import types

import pytest

import worker


# ---------- helpers ----------

class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())

    def texts(self):
        return list(self.records)

    def clear(self):
        self.records = []


def _fake_worker(sdk_running=0, settle_after=0.0, introspectable=True):
    """A stand-in for temporalio Worker: knows its running-activity count and
    lets shutdown() take `settle_after` seconds (0.0 = instant, None = hang)."""
    w = types.SimpleNamespace()
    if introspectable:
        w._activity_worker = types.SimpleNamespace(
            _running_activities=list(range(sdk_running)))
    else:
        # a shape the introspection cannot read (e.g. SDK upgrade)
        w._activity_worker = object()
    # The Event is created lazily inside shutdown(): a bare asyncio.Event() at
    # builder time binds get_event_loop() outside any loop, which RAISES on
    # py3.9 when a previous suite test left no current loop (the full-session
    # flake this file shipped with).
    released = None

    async def shutdown():
        nonlocal released
        if released is None:
            released = asyncio.Event()
        if settle_after is None:
            await released.wait()  # hangs until the test releases it
        else:
            await asyncio.sleep(settle_after)

    w._shutdown = shutdown
    w.shutdown = shutdown

    def _release():
        if released is not None:
            released.set()

    w._release = _release
    return w


@pytest.fixture
def patched(monkeypatch):
    """Stub every module collaborator _graceful_shutdown touches; snapshots are
    empty (the idle baseline) — individual tests flip faces via set_inflight /
    set_spawns."""
    state = {"inflight": [], "spawns": [], "reaped": False, "outcomes": []}
    monkeypatch.setattr(worker, "mark_meta_draining", lambda p: None)
    monkeypatch.setattr(worker, "inflight_stage_snapshot", lambda: state["inflight"])
    monkeypatch.setattr(worker, "owned_spawn_snapshot", lambda: state["spawns"])
    monkeypatch.setattr(worker, "recent_stage_outcomes", lambda: state["outcomes"])

    async def fake_reap():
        state["reaped"] = True
        return {"owned": 0, "reclaimed": 0, "leftover": []}

    monkeypatch.setattr(worker, "reap_owned_spawns", fake_reap)

    def set_inflight(entries):
        state["inflight"] = entries

    def set_spawns(entries):
        state["spawns"] = entries
    return types.SimpleNamespace(state=state, set_inflight=set_inflight,
                                 set_spawns=set_spawns)


@pytest.fixture
def capture():
    cap = _LogCapture()
    logger = logging.getLogger()
    old_level = logger.level
    logger.addHandler(cap)
    logger.setLevel(logging.DEBUG)
    yield cap
    logger.removeHandler(cap)
    logger.setLevel(old_level)


async def _run_shutdown(workers, **kw):
    await worker._graceful_shutdown(workers, [], None, **kw)


# ---------- parser: idle_shutdown_deadline_sec ----------

def test_deadline_parser_default(monkeypatch):
    monkeypatch.delenv(worker.IDLE_SHUTDOWN_ENV, raising=False)
    assert worker.idle_shutdown_deadline_sec() == worker.IDLE_SHUTDOWN_DEFAULT_SEC


@pytest.mark.parametrize("raw,expect", [
    ("", worker.IDLE_SHUTDOWN_DEFAULT_SEC),      # blank → default
    ("   ", worker.IDLE_SHUTDOWN_DEFAULT_SEC),   # whitespace-only → default
    ("2", 2.0),                                  # valid override
    ("0", 0.0),                                  # explicit fast-path OFF
    ("abc", worker.IDLE_SHUTDOWN_DEFAULT_SEC),   # malformed → default
    ("nan", worker.IDLE_SHUTDOWN_DEFAULT_SEC),   # NaN → default
    ("inf", worker.IDLE_SHUTDOWN_DEFAULT_SEC),   # Inf → default
    ("-1", worker.IDLE_SHUTDOWN_DEFAULT_SEC),    # negative → default (never means "off")
])
def test_deadline_parser_matrix(monkeypatch, raw, expect):
    monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, raw)
    assert worker.idle_shutdown_deadline_sec() == expect


def test_deadline_parser_explicit_arg_wins(monkeypatch):
    monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "9")
    assert worker.idle_shutdown_deadline_sec("3") == 3.0


# ---------- introspection: sdk_running_activity_count ----------

def test_introspection_counts_and_degrades():
    assert worker.sdk_running_activity_count(
        _fake_worker(sdk_running=3)) == 3
    assert worker.sdk_running_activity_count(_fake_worker()) == 0
    # unreadable private shape → None (fail-safe: NOT idle), never a raise
    assert worker.sdk_running_activity_count(
        _fake_worker(introspectable=False)) is None
    assert worker.sdk_running_activity_count(object()) is None


# ---------- gating in _graceful_shutdown ----------

def test_idle_worker_settles_fast_no_warning(patched, capture, monkeypatch):
    async def _go():
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "5")
        w = _fake_worker()
        t0 = time.monotonic()
        await _run_shutdown([w])
        assert time.monotonic() - t0 < 4  # no deadline race needed, instant settle
        assert not any("fast idle exit fired" in t for t in capture.texts())
        assert any("fast idle exit armed" in t for t in capture.texts())
        assert patched.state["reaped"] is True  # epilogue ran


    asyncio.run(_go())

def test_idle_but_sdk_hangs_deadline_forces_exit(patched, capture, monkeypatch):
    async def _go():
        """The fast path's reason to exist: proven idle on all three faces, yet the
        SDK shutdown does not settle — the wait is cancelled, the named warning
        fires, and the epilogue (spawn reap) still runs (R3)."""
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.2")
        w = _fake_worker(settle_after=None)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(_run_shutdown([w]), timeout=5)
        finally:
            w._release()  # full-terminal-state hygiene: release the stub
        assert time.monotonic() - t0 < 4  # exited at the deadline, not after a hang
        assert any("fast idle exit fired" in t for t in capture.texts())
        assert patched.state["reaped"] is True  # epilogue ran in the timeout branch too


    asyncio.run(_go())

def test_incident_shape_registry_empty_sdk_busy_keeps_full_grace(
        patched, capture, monkeypatch):
    async def _go():
        """261019 regression anchor (review R2): the guard registry says nothing is
        in flight but the SDK is waiting on an unregistered short activity. The fast
        path must NOT engage — the shutdown runs to its own settle, no forced exit,
        whatever the deadline says."""
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.05")  # would fire instantly if gated wrong
        w = _fake_worker(sdk_running=1, settle_after=0.3)
        await _run_shutdown([w])
        assert not any("fast idle exit armed" in t for t in capture.texts())
        assert not any("fast idle exit fired" in t for t in capture.texts())
        assert any("sdk_running_activities=1" in t for t in capture.texts())
        assert patched.state["reaped"] is True


    asyncio.run(_go())

def test_registry_nonempty_keeps_full_grace(patched, capture, monkeypatch):
    async def _go():
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.05")
        patched.set_inflight([{"ticket": "t1", "stage": "s", "gen": 1, "attempt": 1,
                               "started_monotonic": time.monotonic()}])
        w = _fake_worker(settle_after=0.1)
        await _run_shutdown([w])
        assert not any("fast idle exit armed" in t for t in capture.texts())
        assert patched.state["reaped"] is True


    asyncio.run(_go())

def test_introspection_unavailable_is_not_idle(patched, capture, monkeypatch):
    async def _go():
        """Fail-safe face: when the SDK count cannot be read, the worker is treated
        as NOT idle even if the registry looks empty — worst case is today's slow
        shutdown, never a wrong fast cut (review R1)."""
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.05")
        w = _fake_worker(introspectable=False, settle_after=0.1)
        await _run_shutdown([w])
        assert not any("fast idle exit armed" in t for t in capture.texts())
        assert any("introspection unavailable" in t for t in capture.texts())


    asyncio.run(_go())

def test_spawns_nonempty_is_not_idle(patched, capture, monkeypatch):
    async def _go():
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.05")
        patched.set_spawns([{"tag": "x", "pid": 123,
                             "started_monotonic": time.monotonic()}])
        w = _fake_worker(settle_after=0.1)
        await _run_shutdown([w])
        assert not any("fast idle exit armed" in t for t in capture.texts())


    asyncio.run(_go())

def test_deadline_zero_disables_fast_path(patched, capture, monkeypatch):
    async def _go():
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0")
        w = _fake_worker(settle_after=None)
        task = asyncio.ensure_future(_run_shutdown([w]))
        await asyncio.sleep(0.3)
        assert not task.done()  # still waiting on the stub: no 10s/0s race engaged
        assert not any("fast idle exit armed" in t for t in capture.texts())
        w._release()
        await asyncio.wait_for(task, timeout=5)


    asyncio.run(_go())

def test_multiworker_deadline_wraps_whole_gather(patched, capture, monkeypatch):
    async def _go():
        """R3: one deadline for the whole shutdown phase, not per worker — two
        workers, one hanging, forces the exit at the shared deadline."""
        monkeypatch.setenv(worker.IDLE_SHUTDOWN_ENV, "0.2")
        fast = _fake_worker()
        slow = _fake_worker(settle_after=None)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(_run_shutdown([fast, slow]), timeout=5)
        finally:
            slow._release()
        assert time.monotonic() - t0 < 4
        assert any("fast idle exit fired" in t for t in capture.texts())
        assert patched.state["reaped"] is True
    asyncio.run(_go())

