"""t261006-08 worker shutdown / activity cancellation must reclaim the process tree
it started (261006 08:32 incident: an inspection suite ran orphaned for 64 min
after Temporal had already failed the activity).

UT scope (zero network / zero Temporal / zero real suites, conftest discipline):
  - agent_activities.reap_spawn_group: TERM→bounded wait→KILL escalation, idempotent
    on an exited proc, ESRCH/EPERM fallback to the direct child, other OSError
    propagates, group-escape is a NAMED boundary (documented on the helper);
  - the owned-spawn registry: register-after-success, idempotent re-registration,
    unregister, immutable snapshot;
  - run_handover_leg's three terminal states: CANCELLED → reaped then re-raised
    (cancel semantics never swallowed), TIMEOUT → reaped AND the old receipt text
    preserved verbatim, normal → unregistered; empty command spawns nothing;
  - reap_owned_spawns: receipt {owned, reclaimed, leftover}, a pid that resists
    KILL lands in leftover (never silently absorbed), registry empties (second
    call owned=0), one raising group does not block the others;
  - worker._graceful_shutdown: runs AFTER the SDK drain on BOTH the graceful path
    and the grace-expiry path (same epilogue), logs the per-child roll-call lines
    and the machine-checkable `shutdown-reclaim receipt:` line (R2/R3 faces).
"""
import asyncio
import errno
import inspect
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import agent_activities  # noqa: E402
import worker  # noqa: E402
from agent_activities import (  # noqa: E402
    owned_spawn_snapshot,
    reap_owned_spawns,
    reap_spawn_group,
    register_owned_spawn,
    run_handover_leg,
    unregister_owned_spawn,
)


class StubProc:
    """Asyncio-subprocess-Process stand-in: no real OS resources anywhere."""

    def __init__(self, pid: int, exit_on_wait: bool = True, rc: int = 0,
                 term_resist: bool = False):
        self.pid = pid
        self.returncode = None
        self._exit_on_wait = exit_on_wait
        self._rc = rc
        self._term_resist = term_resist
        self.signals: list = []
        self.waits = 0

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        if sig == 15 and not self._term_resist:
            self.returncode = self._rc   # TERM takes a well-behaved stub down
        elif sig == 9 and self._exit_on_wait:  # KILL always takes the stub down
            self.returncode = -9

    async def wait(self):
        self.waits += 1
        if self._exit_on_wait:
            if self.returncode is None:
                self.returncode = self._rc
            return self.returncode
        await asyncio.sleep(3600)  # resists everything short of the test ending


@pytest.fixture(autouse=True)
def _clear_registry():
    agent_activities._OWNED_SPAWNS.clear()
    yield
    agent_activities._OWNED_SPAWNS.clear()


@pytest.fixture
def group_calls(monkeypatch):
    """Capture killpg calls; getpgid is the identity (session-isolated stubs)."""
    calls: list = []

    def _killpg(pgid, sig):
        calls.append((pgid, sig))

    monkeypatch.setattr(agent_activities.os, "killpg", _killpg)
    monkeypatch.setattr(agent_activities.os, "getpgid", lambda pid: pid)
    # shrink the reap waits globally: real defaults (15s+5s) are production capacity,
    # not something a stub-backed test needs to prove
    real = agent_activities.reap_spawn_group

    async def _fast(proc, tag="", term_timeout=0.01, kill_timeout=0.01):
        return await real(proc, tag=tag, term_timeout=term_timeout,
                          kill_timeout=kill_timeout)

    monkeypatch.setattr(agent_activities, "reap_spawn_group", _fast)
    return calls


# ---- reap_spawn_group ----

def test_reap_spawn_group_term_is_enough(group_calls):
    async def _go():
        p = StubProc(101)
        note = await reap_spawn_group(p, tag="x")
        assert group_calls == [(101, 15)]  # one SIGTERM, no escalation
        assert "process group" in note and "rc=0" in note
    asyncio.run(_go())


def test_reap_spawn_group_escalates_to_kill(group_calls):
    async def _go():
        p = StubProc(102, exit_on_wait=False)
        note = await reap_spawn_group(p, tag="x", term_timeout=0.01, kill_timeout=0.01)
        assert [sig for _, sig in group_calls] == [15, 9]
        assert "escalating to kill" in note and "giving up" in note  # even KILL resisted → named
    asyncio.run(_go())


def test_reap_spawn_group_idempotent_on_exited(group_calls):
    async def _go():
        p = StubProc(103)
        p.returncode = 0
        assert await reap_spawn_group(p, tag="x") == ""
        assert group_calls == [] and p.signals == []
    asyncio.run(_go())


def test_reap_spawn_group_esrch_falls_back_to_child(monkeypatch, group_calls):
    async def _go():
        p = StubProc(104)

        def _boom(pgid, sig):
            raise OSError(errno.ESRCH, "no such group")

        monkeypatch.setattr(agent_activities.os, "killpg", _boom)
        await reap_spawn_group(p, tag="x")
        assert p.signals == [15]  # direct-child fallback fired, no raise
    asyncio.run(_go())


def test_reap_spawn_group_other_oserror_propagates(monkeypatch, group_calls):
    async def _go():
        p = StubProc(105)

        def _boom(pgid, sig):
            raise OSError(errno.EACCES, "weird")

        monkeypatch.setattr(agent_activities.os, "killpg", _boom)
        with pytest.raises(OSError) as ei:
            await reap_spawn_group(p, tag="x")
        assert ei.value.errno == errno.EACCES
    asyncio.run(_go())


def test_group_escape_boundary_is_named():
    async def _go():
        # the reviewer's dispositioned residual must not go silent: the helper's own
        # docstring names it and points at the sweeper net
        doc = inspect.getdoc(reap_spawn_group)
        assert "group escape" in doc and "sweep_tmp_fixtures" in doc
    asyncio.run(_go())


# ---- registry ----

def test_registry_register_snapshot_unregister():
    async def _go():
        p = StubProc(201)
        register_owned_spawn(p, tag="t")
        register_owned_spawn(p, tag="t")  # duplicate registration is a no-op
        snap = owned_spawn_snapshot()
        assert [e["pid"] for e in snap] == [201]
        snap[0]["pid"] = 999  # mutating the copy must not touch the registry
        assert owned_spawn_snapshot()[0]["pid"] == 201
        unregister_owned_spawn(p)
        assert owned_spawn_snapshot() == []
    asyncio.run(_go())


def test_registry_register_without_pid_is_a_noop():
    async def _go():
        register_owned_spawn(object(), tag="t")  # no pid attr → never guessed into the book
        assert owned_spawn_snapshot() == []
    asyncio.run(_go())


# ---- run_handover_leg: cancel / timeout / empty ----

def test_handover_leg_cancel_reaps_then_reraises(monkeypatch, group_calls):
    async def _go():
        p = StubProc(301)

        async def _fake_exec(*a, **kw):
            register_owned_spawn(p, tag="handover-leg")
            return p

        monkeypatch.setattr(agent_activities.asyncio, "create_subprocess_exec",
                            _fake_exec)

        async def _communicate():
            raise asyncio.CancelledError()

        p.communicate = _communicate
        with pytest.raises(asyncio.CancelledError):
            await run_handover_leg({"name": "n", "cmd": "true"}, cwd=pathlib.Path("."))
        assert group_calls == [(301, 15)]    # the tree was reaped on the cancel path
        assert owned_spawn_snapshot() == []  # and the book is clean
    asyncio.run(_go())


def test_handover_leg_timeout_keeps_old_receipt(monkeypatch, group_calls):
    async def _go():
        p = StubProc(302, exit_on_wait=False, term_resist=True)

        async def _fake_exec(*a, **kw):
            register_owned_spawn(p, tag="handover-leg")
            return p

        monkeypatch.setattr(agent_activities.asyncio, "create_subprocess_exec", _fake_exec)

        async def _communicate():
            await asyncio.sleep(3600)

        p.communicate = _communicate
        out = await run_handover_leg({"name": "n", "cmd": "true"}, cwd=pathlib.Path("."),
                                     timeout=0.01)
        # old receipt CONTRACT kept: wall-clock value + group-reap wording. The
        # TimeoutError leg keeps the pinned CJK text verbatim (t260917-08 UTs);
        # the py3.9 race leg (expiry surfaced as CancelledError) carries the
        # English twin — this stub always takes the TimeoutError leg.
        cjk = "\u79fb\u4ea4\u547d\u4ee4\u8d85\u65f6"  # legacy receipt (escaped: copy gate)
        grp = "\u8fdb\u7a0b\u7ec4"
        assert out["output_tail"].startswith(cjk + "（>0s")
        assert grp in out["output_tail"]
        assert [sig for _, sig in group_calls] == [15, 9]  # TERM then KILL escalation
        assert owned_spawn_snapshot() == []
    asyncio.run(_go())


def test_handover_leg_empty_cmd_spawns_nothing(monkeypatch, group_calls):
    async def _go():
        async def _no_exec(*a, **kw):
            raise AssertionError("empty command must never spawn")

        monkeypatch.setattr(agent_activities.asyncio, "create_subprocess_exec", _no_exec)
        out = await run_handover_leg({"name": "n", "cmd": "  "}, cwd=pathlib.Path("."))
        assert out["exit"] is None and owned_spawn_snapshot() == []
    asyncio.run(_go())


# ---- reap_owned_spawns (the worker-epilogue face) ----

def test_reap_owned_spawns_receipt_and_leftover(group_calls):
    async def _go():
        ok = StubProc(401)
        stubborn = StubProc(402, exit_on_wait=False, term_resist=True)
        register_owned_spawn(ok, tag="a")
        register_owned_spawn(stubborn, tag="b")
        receipt = await reap_owned_spawns()
        assert receipt == {"owned": 2, "reclaimed": 1, "leftover": [402]}
        assert owned_spawn_snapshot() == []  # registry empties as we go …
        again = await reap_owned_spawns()    # … so a second call is owned=0 (idempotent)
        assert again == {"owned": 0, "reclaimed": 0, "leftover": []}
    asyncio.run(_go())


def test_reap_owned_spawns_one_raising_group_blocks_nothing(monkeypatch, group_calls):
    async def _go():
        ok = StubProc(403)
        bad = StubProc(404)
        register_owned_spawn(bad, tag="bad")
        register_owned_spawn(ok, tag="ok")

        real = agent_activities.reap_spawn_group

        async def _flaky(proc, tag="", **kw):
            if proc.pid == 404:
                raise RuntimeError("boom")
            return await real(proc, tag=tag, **kw)

        monkeypatch.setattr(agent_activities, "reap_spawn_group", _flaky)
        receipt = await reap_owned_spawns()
        # the group whose reap RAISED is counted leftover (never silently absorbed);
        # the healthy group is still reaped — one bad group blocks nothing
        assert receipt["owned"] == 2 and receipt["reclaimed"] == 1
        assert receipt["leftover"] == [404]
    asyncio.run(_go())


# ---- real-process injection (the incident shape, unit-sized): a session-isolated
# `sleep` tree outlives a bounded wait that expired, and the group is reclaimed;
# also reproduces the py3.9 wait_for race (timeout surfacing as CancelledError)
# and pins the wall-clock disambiguation on a REAL process ----

def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def test_real_leg_timeout_reaps_group_and_keeps_receipt():
    import tempfile
    out = asyncio.run(run_handover_leg(
        {"name": "slow-leg", "cmd": "/bin/sleep 30"},
        cwd=pathlib.Path(tempfile.gettempdir()), timeout=0.5))
    # either leg of the py3.9 wait_for race: same contract, two wordings
    cjk_to = "\u8d85\u65f6"      # the legacy CJK receipt wording, escaped for the copy gate
    cjk_grp = "\u8fdb\u7a0b\u7ec4"
    assert ("timed out" in out["output_tail"]) or (cjk_to in out["output_tail"])
    assert ("process group" in out["output_tail"]) or (cjk_grp in out["output_tail"])
    assert owned_spawn_snapshot() == []            # the book is clean after the leg
    import subprocess as _sp
    r = _sp.run(["/usr/bin/env", "bash", "-c",
                 "ps -eo command | grep -c '[s]leep 30'"], capture_output=True)
    assert int((r.stdout or b"0").split()[-1] or b"0") == 0  # nothing orphaned


def test_real_leg_early_cancel_reraises_and_reaps():
    import tempfile

    async def _go():
        task = asyncio.ensure_future(run_handover_leg(
            {"name": "slow-leg", "cmd": "/bin/sleep 30"},
            cwd=pathlib.Path(tempfile.gettempdir()), timeout=60))
        await asyncio.sleep(0.5)   # let the shell + sleep actually start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)
        assert owned_spawn_snapshot() == []
        # no orphan: no process of ours still runs a sleep 30 spawned by the leg
        import subprocess as _sp
        r = _sp.run(["/usr/bin/env", "bash", "-c",
                     "ps -eo pgid,command | grep -c '[s]leep 30'"],
                    capture_output=True)
        assert int((r.stdout or b"0").split()[-1] or b"0") == 0

    asyncio.run(asyncio.wait_for(_go(), timeout=20))


# ---- worker._graceful_shutdown: roll-call + receipt on the real epilogue ----

def test_graceful_shutdown_rollcall_and_receipt(caplog, group_calls, monkeypatch):
    async def _go():
        p = StubProc(501)
        register_owned_spawn(p, tag="integ-chain")

        class _W:
            async def shutdown(self):
                pass

        caplog.set_level("INFO")
        with caplog.at_level("INFO"):
            await worker._graceful_shutdown([_W()], [], None)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert ("shutdown roll-call: owned child process group "
                "tag=integ-chain pid=501") in text                            # R2
        assert "shutdown-reclaim receipt: owned=1 reclaimed=1 leftover=[]" in text  # R3
        assert group_calls == [(501, 15)]  # TERM was enough for the stub
    asyncio.run(_go())


def test_graceful_shutdown_leftover_is_named_not_absorbed(caplog, group_calls):
    async def _go():
        p = StubProc(502, exit_on_wait=False, term_resist=True)
        register_owned_spawn(p, tag="integ-chain")

        class _W:
            async def shutdown(self):
                pass

        # small reap timeouts: the stub resists everything, keep the test fast
        caplog.set_level("INFO")
        with caplog.at_level("INFO"):
            await worker._graceful_shutdown([_W()], [], None)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "shutdown-reclaim receipt: owned=1 reclaimed=0 leftover=[502]" in text
        assert "group-escape" in text  # the named boundary surfaces in the warning
    asyncio.run(_go())


def test_shutdown_epilogue_wiring_anchor():
    async def _go():
        # tripwire: the receipt call must stay in _graceful_shutdown (AFTER Worker.shutdown
        # → covers both the graceful drain and the grace-expiry path)
        src = inspect.getsource(worker._graceful_shutdown)
        assert "reap_owned_spawns" in src and "shutdown-reclaim receipt" in src
    asyncio.run(_go())
