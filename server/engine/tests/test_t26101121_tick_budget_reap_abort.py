#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-21 L1 battery: the line-round tick's budget, runner reap and
abort-row faces (host order 261011, developer stage).

The 16:49 incident: the scan tick's line_round_tick_engine activity died at
its 30-minute start_to_close while line_round_runner.py kept running as an
orphan, and the delivery ledger carried NO row naming why — a dead round
was indistinguishable from no round. The three fixes pinned here:

- workflows.LINE_ROUND_TICK_BUDGET dominates CHAIN_LIMIT x
  RUNNER_TIMEOUT_S_DEFAULT (defect 1) and is the constant at the call site;
- resolve_runner spawns its own session, registers the live pid, and a
  timeout (or any unwinding exception) reaps the WHOLE process group —
  TERM first, bounded wait, KILL, bounded wait, ESRCH/EPERM tolerated
  (defect 2, the t261006-08 shape's sync twin);
- abort_inflight_ticks leaves ONE could_not_run row per in-flight line
  naming why, scoped to guards this tick holds, never releasing a guard,
  never masking the caller's exception (defect 3).

Zero network / zero Temporal / zero real suites; real child processes only,
each bounded and reaped inside the test.
"""
import pathlib
import subprocess
import sys
import time
from datetime import timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import develop_certify as dc  # noqa: E402
import workflows  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_reap(monkeypatch):
    """Shrink the reap's bounded waits: the tests' children die on TERM or
    on the first KILL; a 10 s TERM wait would only burn wall clock."""
    monkeypatch.setattr(dc, "_REAP_TERM_WAIT_S", 0.5)
    monkeypatch.setattr(dc, "_REAP_KILL_WAIT_S", 0.5)


@pytest.fixture(autouse=True)
def _clean_registries():
    """No test may leak into another's registry view (or into the atexit
    hook's face at interpreter exit)."""
    dc._INFLIGHT_RUNNERS.clear()
    dc._INFLIGHT_TICKS.clear()
    yield
    dc._INFLIGHT_RUNNERS.clear()
    dc._INFLIGHT_TICKS.clear()


IGNORANT_CHILD = (
    "python3 -c \"import signal,sys,time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print('up', flush=True); time.sleep(60)\"")


def spawn_ignorant_child():
    """A live child in its OWN session that ignores SIGTERM (the TERM-then-
    KILL escalation's honest workout)."""
    return subprocess.Popen(
        IGNORANT_CHILD, shell=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True)


# ---- defect 1: the activity budget ------------------------------------------

class TestBudget:
    def test_budget_dominates_chain_x_runner_timeout(self):
        assert workflows.LINE_ROUND_TICK_BUDGET >= timedelta(
            seconds=dc.CHAIN_LIMIT * dc.RUNNER_TIMEOUT_S_DEFAULT)

    def test_budget_is_the_constant_at_the_call_site(self):
        src = (pathlib.Path(dc.__file__).parent
               / "workflows.py").read_text(encoding="utf-8")
        assert "start_to_close_timeout=LINE_ROUND_TICK_BUDGET" in src
        assert "timedelta(minutes=30)" not in src

    def test_budget_note_declares_the_derivation(self):
        src = (pathlib.Path(dc.__file__).parent
               / "workflows.py").read_text(encoding="utf-8")
        assert "LINE_ROUND_TICK_BUDGET = timedelta(hours=5)" in src


# ---- defect 2: the runner is owned and reaped --------------------------------

class TestRunnerReap:
    def _runner_env(self, tmp):
        return {
            "SANDBAR_LINE_ROUND_RUNNER": 'echo \'{\"id\": \"run-x\"}\'',
            "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "5",
            "PATH": __import__("os").environ["PATH"],
        }

    def test_runner_success_header_and_registry_cleanup(self):
        runner = dc.resolve_runner("L1", self._runner_env(None))
        header = runner([{"repo": "sandbar", "revision": "r1"}])
        assert header["id"] == "run-x"
        assert dc._INFLIGHT_RUNNERS == {}, "registry must empty after wait"

    def test_timeout_reaps_the_whole_group(self):
        env = {
            "SANDBAR_LINE_ROUND_RUNNER": IGNORANT_CHILD,
            "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "1",
            "PATH": __import__("os").environ["PATH"],
        }
        runner = dc.resolve_runner("L1", env)
        t0 = time.monotonic()
        with pytest.raises(dc.CouldNotRun) as ei:
            runner([{"repo": "sandbar", "revision": "r1"}])
        assert "runner_timeout:1s" in str(ei.value)
        assert time.monotonic() - t0 < 5, "reap must be bounded, not 60 s"
        assert dc._INFLIGHT_RUNNERS == {}, "registry must empty after reap"

    def test_reap_runner_proc_idempotent_on_exited_proc(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        assert dc.reap_runner_proc(proc) == ""

    def test_reap_kills_a_term_ignoring_group(self):
        proc = spawn_ignorant_child()
        try:
            proc.stdout.readline()  # wait for "up"
            note = dc.reap_runner_proc(proc, tag="ut")
            assert "reaped pid=" in note
            assert proc.poll() is not None, "child must be collected"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_reap_inflight_runners_empties_the_registry(self):
        proc = spawn_ignorant_child()
        proc.stdout.readline()
        dc._INFLIGHT_RUNNERS[proc.pid] = {
            "proc": proc, "line": "L1", "at": time.time()}
        try:
            assert dc.reap_inflight_runners("ut") == [proc.pid]
            assert dc.reap_inflight_runners("ut") == [], "idempotent"
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_spawn_failure_never_registers(self):
        calls = []

        class Boom:
            def __init__(self, *a, **kw):
                calls.append(1)
                raise OSError("no such shell")

        real_popen = subprocess.Popen
        subprocess.Popen = Boom
        try:
            runner = dc.resolve_runner("L1", self._runner_env(None))
            with pytest.raises(dc.CouldNotRun) as ei:
                runner([{"repo": "sandbar", "revision": "r1"}])
            assert "runner_unreachable" in str(ei.value)
        finally:
            subprocess.Popen = real_popen
        assert dc._INFLIGHT_RUNNERS == {}, "failed spawn must not register"


# ---- defect 3: the abort row --------------------------------------------------

class TestAbortRow:
    def _held_guard(self, tmp):
        anchor = pathlib.Path(tmp) / "tick-anchor"
        anchor.parent.mkdir(parents=True, exist_ok=True)
        state = dc.guard_acquire(str(anchor), "ut")
        assert state and state["held"]
        return anchor

    def test_abort_appends_one_named_row_per_inflight_line(self, tmp_path):
        anchor = self._held_guard(tmp_path)
        dc._INFLIGHT_TICKS["proj"] = {"guard_path": str(anchor)}
        proc = spawn_ignorant_child()
        proc.stdout.readline()
        dc._INFLIGHT_RUNNERS[proc.pid] = {
            "proc": proc, "line": "L1", "at": time.time()}
        captured = []
        try:
            got = dc.abort_inflight_ticks(
                "activity_unwinding", append_rows_fn=captured.extend)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        assert got == ["L1"]
        assert len(captured) == 1
        row = captured[0]
        assert row["kind"] == dc.KIND_RANGE_GROWTH
        assert row["line"] == "L1"
        assert row["reason"] == "activity_aborted:activity_unwinding"
        # the guard is a filter, never a release target here
        assert dc.guard_held(str(anchor)), "abort must not release a guard"

    def test_abort_skips_a_context_whose_guard_is_free(self, tmp_path):
        anchor = self._held_guard(tmp_path)
        dc.guard_release(str(anchor))
        dc._INFLIGHT_TICKS["proj"] = {"guard_path": str(anchor)}
        assert dc.abort_inflight_ticks("x", append_rows_fn=lambda b: []) == []

    def test_abort_row_passes_the_real_validator(self, tmp_path):
        anchor = self._held_guard(tmp_path)
        dc._INFLIGHT_TICKS["proj"] = {"guard_path": str(anchor)}
        proc = spawn_ignorant_child()
        proc.stdout.readline()
        dc._INFLIGHT_RUNNERS[proc.pid] = {
            "proc": proc, "line": "L1", "at": time.time()}
        ledger = tmp_path / "ledger.jsonl"
        try:
            got = dc.abort_inflight_ticks(
                "activity_unwinding",
                append_rows_fn=lambda batch: dc.append_rows(batch, str(ledger)))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        assert got == ["L1"]
        rows, bad = dc.read_rows(str(ledger))
        assert bad == []
        assert rows and rows[0]["reason"].startswith("activity_aborted:")

    def test_append_failure_is_named_and_never_raises(self, tmp_path,
                                                       capsys):
        anchor = self._held_guard(tmp_path)
        dc._INFLIGHT_TICKS["proj"] = {"guard_path": str(anchor)}
        dc._INFLIGHT_RUNNERS[999999] = {
            "proc": None, "line": "L1", "at": time.time()}

        def boom(batch):
            raise OSError("disk full")

        got = dc.abort_inflight_ticks("activity_unwinding",
                                      append_rows_fn=boom)
        assert got == [], "a failed append names, never claims success"
        err = capsys.readouterr().err
        assert "LINE_ROUND_ABORT row_failed:proj" in err


# ---- the shutdown face ---------------------------------------------------------

class TestShutdownFace(TestAbortRow):
    def test_shutdown_reaps_and_appends_and_clears(self, tmp_path):
        anchor = self._held_guard(tmp_path)
        ledger = tmp_path / "ledger.jsonl"
        dc._INFLIGHT_TICKS["proj"] = {
            "guard_path": str(anchor), "ledger": str(ledger)}
        proc = spawn_ignorant_child()
        proc.stdout.readline()
        dc._INFLIGHT_RUNNERS[proc.pid] = {
            "proc": proc, "line": "L1", "at": time.time()}
        try:
            out = dc.shutdown_inflight_ticks()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        assert out["reaped"] == [proc.pid]
        assert out["appended"] == ["L1"]
        assert dc._INFLIGHT_RUNNERS == {}
        assert dc._INFLIGHT_TICKS == {}
        rows, bad = dc.read_rows(str(ledger))
        assert bad == []
        assert rows and rows[0]["reason"] == "activity_aborted:worker_shutdown"

    def test_shutdown_face_on_empty_registries_is_a_noop(self):
        out = dc.shutdown_inflight_ticks()
        assert out == {"reaped": [], "appended": []}


# ---- the activity wrapper's cancellation face ---------------------------------

class TestActivityWrapper:
    def test_wrapper_aborts_reaps_then_reraises_original(self, monkeypatch):
        import asyncio
        import activities
        calls = []
        monkeypatch.setattr(
            activities, "_line_round_tick_engine",
            lambda: (_ for _ in ()).throw(RuntimeError("tick exploded")))
        monkeypatch.setattr(
            dc, "abort_inflight_ticks",
            lambda reason, **kw: calls.append(("abort", reason)) or ["L1"])
        monkeypatch.setattr(
            dc, "reap_inflight_runners",
            lambda reason="": calls.append(("reap", reason)) or [1])
        with pytest.raises(RuntimeError) as ei:
            asyncio.run(activities.line_round_tick_engine())
        assert str(ei.value) == "tick exploded", "original exception identity"
        assert calls == [("abort", "activity_unwinding"),
                         ("reap", "activity_unwinding")], \
            "abort rows first (registry still populated), then reap"
