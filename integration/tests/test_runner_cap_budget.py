#!/usr/bin/env python3
"""Unit battery for the executor cap guard's WAIT-BUDGET face (t261021-10).

Measured fault (261023): the machine-global executor cap (8) was saturated by
SIBLING lanes' normal verification — every alive registration named a foreign
tree — so this lane's merge_check reded 3 engine tests and two gate close-out
rounds with `REFUSED [__executor__]`, pure supply contention, zero product red.
Repair = the budget face the arbitration named ("cap keying or budget"): at cap,
poll for a free slot up to `SANDBAR_INTEG_RUNNER_WAIT_SEC` (default 120s) before
refusing; budget exhausted while still full = named refusal, so the storm-guard
semantics survive (a storm stays at cap). The refusal SHAPE is byte-pinned by
test_t261001_refusal_shape.py and is not changed here.

Offline seconds, zero docker/Temporal; the registry is injected into a tmp dir
via the declared `SANDBAR_INTEG_RUNNER_REG_DIR` knob — never the real /tmp one.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"


def _load_rs(env):
    spec = importlib.util.spec_from_file_location(
        "rs_cap_budget", str(INTEG / "run_scenarios.py"))
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    return rs


def _sleeper():
    p = subprocess.Popen(["sleep", "60"])
    return p


class TestRunnerCapWaitBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="runner-cap-budget-")
        self.reg = os.path.join(self.tmp, "reg")
        os.makedirs(self.reg)
        # The guard reads os.environ at call time (declared knobs are process env),
        # so the injection must land in the real env and be restored after.
        self._saved = {k: os.environ.get(k) for k in
                       ("SANDBAR_INTEG_RUNNER_REG_DIR", "SANDBAR_INTEG_RUNNER_CAP",
                        "SANDBAR_INTEG_RUNNER_WAIT_SEC")}
        os.environ["SANDBAR_INTEG_RUNNER_REG_DIR"] = self.reg
        os.environ["SANDBAR_INTEG_RUNNER_CAP"] = "1"
        os.environ.pop("SANDBAR_INTEG_RUNNER_WAIT_SEC", None)
        self.env = os.environ
        self.rs = _load_rs(self.env)

    def tearDown(self):
        for name in os.listdir(self.reg):
            try:
                os.remove(os.path.join(self.reg, name))
            except OSError:
                pass
        os.rmdir(self.reg)
        os.rmdir(self.tmp)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _register(self, pid):
        fp = os.path.join(self.reg, "run-%d" % pid)
        with open(fp, "w", encoding="utf-8") as f:
            f.write('{"pid": %d, "tree": "elsewhere", "ts": %f}' % (pid, time.time()))
        return fp

    def test_under_cap_registers_and_returns_true(self):
        self.rs._RUNNER_WAIT_POLL_SEC = 0.05
        self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "0"
        self.assertTrue(self.rs._runner_cap_guard())
        self.assertTrue(os.path.exists(os.path.join(self.reg, "run-%d" % os.getpid())))

    def test_at_cap_zero_budget_refuses_named_immediately(self):
        p = _sleeper()
        try:
            self._register(p.pid)
            self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "0"
            t0 = time.monotonic()
            ok = self.rs._runner_cap_guard()
            self.assertLess(time.monotonic() - t0, 5)  # no wait when budget 0
            self.assertFalse(ok)
            # registration must NOT have been created on refusal
            self.assertFalse(os.path.exists(
                os.path.join(self.reg, "run-%d" % os.getpid())))
        finally:
            p.kill()
            p.wait(timeout=10)

    def test_slot_freed_during_budget_is_admitted(self):
        p = _sleeper()
        try:
            fp = self._register(p.pid)
            self.rs._RUNNER_WAIT_POLL_SEC = 0.2
            self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "30"
            result = {}

            def free_soon():
                time.sleep(0.5)
                p.kill()
                p.wait(timeout=10)
                try:
                    os.remove(fp)
                except OSError:
                    pass
            th = threading.Thread(target=free_soon)
            th.start()
            result["ok"] = self.rs._runner_cap_guard()
            th.join(timeout=30)
            self.assertTrue(result["ok"], "a freed slot inside the budget must admit")
            self.assertTrue(os.path.exists(
                os.path.join(self.reg, "run-%d" % os.getpid())))
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)

    def test_budget_exhausted_still_full_refuses_and_names_knob(self):
        p = _sleeper()
        try:
            self._register(p.pid)
            self.rs._RUNNER_WAIT_POLL_SEC = 0.2
            self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "0.5"
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = self.rs._runner_cap_guard()
            self.assertFalse(ok)  # still full at budget end -> refuse
            out = buf.getvalue()
            self.assertIn("REFUSED [__executor__]", out)
            self.assertIn("SANDBAR_INTEG_RUNNER_WAIT_SEC", out)
            # shape face: no LINE starts with the scenario-shaped `FAIL [` prefix
            # (the refusal prose may mention `FAIL [` — test_t261001_refusal_shape
            # pins the same line-start face).
            self.assertFalse([ln for ln in out.splitlines()
                              if ln.startswith("FAIL [")])
        finally:
            p.kill()
            p.wait(timeout=10)

    def test_malformed_budget_reads_as_zero(self):
        p = _sleeper()
        try:
            self._register(p.pid)
            self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "soon"
            t0 = time.monotonic()
            self.assertFalse(self.rs._runner_cap_guard())  # fail-closed, no guess
            self.assertLess(time.monotonic() - t0, 5)
        finally:
            p.kill()
            p.wait(timeout=10)

    def test_stale_and_dead_entries_never_count(self):
        # stale: alive pid but >6h old mtime; dead: fresh mtime, dead pid.
        fp = self._register(os.getpid())  # alive, but stale
        os.utime(fp, (time.time() - 7 * 3600,) * 2)
        self._register(2 ** 22)           # almost surely a dead pid
        self.env["SANDBAR_INTEG_RUNNER_WAIT_SEC"] = "0"
        self.assertTrue(self.rs._runner_cap_guard())


if __name__ == "__main__":
    unittest.main()
