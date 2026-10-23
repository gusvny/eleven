#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261012-02 L1 battery: a hung case must not eat the round (developer stage).

The 261011 measured defect: the runner spawned each case with
``subprocess.run(..., capture_output=True, timeout=CMD_TIMEOUT)``; CPython's
run() kills only the direct /bin/sh child on timeout and then re-calls
communicate() with NO timeout, so a grandchild holding the inherited pipe
write end kept the 900s per-case budget from ever firing (the round's only
exit was the outer 3600s cap; one hang cost ~1h of machine time).

This battery pins, over REAL child processes (own sessions, offline seconds,
zero docker/Temporal/port/console, never touches 3099):

- A  the timeout red lands within CMD_TIMEOUT + grace, ALWAYS (wall-clock
     assertion, tiny injected budget — the injection point is the module
     constant, review comment 3), and the whole process group dies with it;
- B  zero live descendants survive ANY terminal state (normal / red /
     timeout / detached setsid grandchild);
- C  the timeout verdict names the group kill, and the captured output files
     still feed the evidence tail (diagnostics not regressed vs pipes);
- D  the hung-twice guard skips a repeat scheduling BY NAME (declared
     defensive: no in-round re-invocation path exists today);
- E  the budget ladder guard: the ensure-mutex working-peer ceiling default
     (660s) plus the kill grace stays under CMD_TIMEOUT (900s), so a
     contended stage wait's NAMED red converges inside the case budget;
- F  spawn-face OSError still lands a named verdict and never leaks fds;
- G  source lock: the case spawn carries start_new_session=True with
     stdout/stderr on files (never capture_output pipes), and the stage
     hold leg keeps DEVNULL stdout + own session (nothing a case spawns
     inherits the runner's faces).
"""
import importlib.util
import inspect
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"

sys.path.insert(0, str(INTEG))
import run_scenarios as rs  # noqa: E402


def _load_stage_docker():
    spec = importlib.util.spec_from_file_location(
        "stage_docker_t26101202", INTEG / "stage_docker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entry(name, cmd):
    # entry shape: (name, pool_hint, cmd, pool) — pool_of only reads index 3.
    return (name, None, cmd, "main")


def _alive(marker):
    r = subprocess.run(["pgrep", "-f", marker],
                       capture_output=True, text=True, timeout=10)
    return [ln for ln in r.stdout.split() if ln.strip()]


TINY_BUDGET = 2
TINY_GRACE = 3


class TimeoutReapsGroup(unittest.TestCase):
    def setUp(self):
        self._old_budget, self._old_grace = rs.CMD_TIMEOUT, rs._KILL_GRACE_S
        self._old_hung = set(rs._HUNG_THIS_ROUND)
        rs.CMD_TIMEOUT = TINY_BUDGET
        rs._KILL_GRACE_S = TINY_GRACE

    def tearDown(self):
        rs.CMD_TIMEOUT, rs._KILL_GRACE_S = self._old_budget, self._old_grace
        rs._HUNG_THIS_ROUND.clear()
        rs._HUNG_THIS_ROUND.update(self._old_hung)

    def test_a_timeout_red_within_budget_and_group_dead(self):
        """Review comment 3: the injection point is the module constant, and
        the budget-plus-margin contract is asserted on the wall clock, not
        assumed."""
        marker = "t26101202-marker-A"
        cmd = "sleep 30 & echo started-%s; sleep 30" % marker
        t0 = time.monotonic()
        name, rc, tail, dur, _t0, full = rs._run_entry(
            _entry("t26101202-case-A", cmd))
        wall = time.monotonic() - t0
        self.assertEqual(name, "t26101202-case-A")
        self.assertEqual(rc, -9)
        self.assertLessEqual(
            wall, TINY_BUDGET + TINY_GRACE + 5,
            "timeout red must land within budget+margin, always (measured %.1fs)"
            % wall)
        # the whole group is gone, not only the direct /bin/sh child
        deadline = time.monotonic() + 5
        while _alive(marker) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(_alive(marker), [],
                         "grandchildren survived the case timeout: %s"
                         % _alive(marker))
        self.assertIn("started-%s" % marker, full,
                      "pre-timeout output must survive as evidence")

    def test_b_normal_and_red_leave_zero_descendants(self):
        """Arbitrate gen0 legs B/C: a case that BACKGROUNDS a grandchild and
        then exits 0 (or red) must leave the grandchild dead when _run_entry
        returns — the group sweep runs on EVERY terminal path, not only the
        timeout branch (the pid-51249 orphan class from the ticket body)."""
        for label, cmd, want_rc, marker in (
                ("normal", "sleep 31 & echo ok; exit 0", 0, "sleep 31"),
                ("red", "sleep 32 & echo bad >&2; exit 7", 7, "sleep 32"),
        ):
            with self.subTest(state=label):
                name, rc, tail, dur, _t0, full = rs._run_entry(
                    _entry("t26101202-case-B-" + label, cmd))
                self.assertEqual(rc, want_rc)
                deadline = time.monotonic() + 5
                while _alive(marker) and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertEqual(_alive(marker), [],
                                 "%s case left live descendants" % label)

    def test_b2_detached_setsid_grandchild_never_raises(self):
        """Malformed/harsh shape (test F in the plan): the case detaches a
        setsid grandchild outside the group — the reap must not raise, the
        verdict must land, and the runner must survive."""
        marker = "t26101202-marker-B2"
        name, rc, tail, dur, _t0, full = rs._run_entry(
            _entry("t26101202-case-B2",
                   "setsid sleep 30 & echo detached; sleep 30 # %s" % marker))
        self.assertEqual(rc, -9)
        # the detached grandchild is outside the group by design — kill it so
        # the test machine is clean, but the runner itself never raised.
        subprocess.run(["pkill", "-f", "sleep 30 # %s" % marker],
                       capture_output=True, timeout=10)
        self.assertEqual(_alive(marker), [])

    def test_c_timeout_verdict_names_group_kill(self):
        name, rc, tail, dur, _t0, full = rs._run_entry(
            _entry("t26101202-case-C", "sleep 30"))
        self.assertEqual(rc, -9)
        self.assertIn("SIGKILL", tail)
        self.assertIn(str(TINY_BUDGET), tail,
                      "verdict names the budget that actually fired")

    def test_d_hung_twice_guard_skips_by_name(self):
        """Declared defensive (review comment 2): the executor schedules each
        entry once per round and reprobe is a separate process, so no in-round
        re-invocation path exists today — the guard is kept because the ticket
        requires a named skip if such a path ever exists. This test keeps the
        guard honest: it fires BY NAME, never silently, never as a pass."""
        rs._HUNG_THIS_ROUND.add("t26101202-case-D")
        name, rc, tail, dur, _t0, full = rs._run_entry(
            _entry("t26101202-case-D", "echo should-not-run"))
        self.assertEqual(name, "t26101202-case-D")
        self.assertEqual(rc, 1, "a hung-twice deferral is a named fail, never a pass")
        self.assertIn("hung-twice guard", tail)
        self.assertIn("already timed out", tail)
        self.assertEqual(full, "")

    def test_e_budget_ladder_ceiling_under_case_budget(self):
        # this test judges the REAL ladder, so undo setUp's tiny injection
        rs.CMD_TIMEOUT, rs._KILL_GRACE_S = self._old_budget, self._old_grace
        sd = _load_stage_docker()
        ceiling = sd.DEFAULT_WORKING_PEER_CEILING_S
        self.assertLess(ceiling + rs._KILL_GRACE_S, rs.CMD_TIMEOUT,
                        "ensure-mutex named red (default ceiling %.0fs) must "
                        "converge inside the case budget (%ds)" %
                        (ceiling, rs.CMD_TIMEOUT))
        self.assertEqual(rs.CMD_TIMEOUT, 900,
                         "CMD_TIMEOUT is the ceiling — a silent global cut is "
                         "NOT the fix (t260910-08 legitimately needs 378s)")

    def test_f_spawn_oserror_named_verdict_no_leak(self):
        real_popen = subprocess.Popen

        def boom(*a, **kw):
            raise OSError(24, "Too many open files")

        rs.subprocess.Popen = boom
        try:
            name, rc, tail, dur, _t0, full = rs._run_entry(
                _entry("t26101202-case-F", "echo hi"))
        finally:
            rs.subprocess.Popen = real_popen
        self.assertEqual(name, "t26101202-case-F")
        self.assertEqual(rc, rs._SPAWN_FAIL)
        self.assertIn("OSError", tail)
        self.assertEqual(full, "")

    def test_g_source_lock_session_and_no_pipes(self):
        src = inspect.getsource(rs._run_entry)
        self.assertIn("start_new_session=True", src)
        self.assertNotIn("capture_output", src,
                         "case output must never ride a pipe the runner waits on")
        self.assertIn("os.killpg", src)
        self.assertIn("proc.wait(timeout=CMD_TIMEOUT)", src,
                      "wait() is the honest primitive once no pipes exist "
                      "(review comment 1)")
        hold_src = (INTEG / "stage_docker.py").read_text(encoding="utf-8")
        self.assertIn("stdout=subprocess.DEVNULL", hold_src)
        self.assertIn("start_new_session=True", hold_src,
                      "the stage hold leg must not inherit the case's faces")


if __name__ == "__main__":
    unittest.main()
