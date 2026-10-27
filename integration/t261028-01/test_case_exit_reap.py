#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261028-05 (KI-377) L1 battery: a scenario case must not outlive itself.

The measured defect (ticket user_request): two `ki067_park_stub.py` processes
were still alive 25 and 52 minutes after their case had exited, each holding a
full agent session; machine memory climbed across the night until a forced
restart, and only a manual kill reclaimed the load. The case's own process GROUP
was already swept (t261012-02), so the leak is the class that escapes a group
signal: the engine spawns agent children with start_new_session=True
(server/engine/agent_activities.py), i.e. in a session of their own.

What this battery pins, over REAL spawned child processes (own sessions, offline
seconds, no docker / no Temporal / no network, never touches the console on
3099):

- A  a child that is still alive when its case ends is reaped, and the case row
     carries a NAMED receipt that counts it (requirement 1);
- A2 the leak shape specifically: an agent child that DETACHED into its own
     session (start_new_session=True) while its owning parent is still in the
     case's group - the group signal cannot reach it, the ppid-descendant
     closure can, and a same-group child is reaped by the group face;
- B  the timeout terminal path reaps too (named timeout red, no live child);
- C  the runner's OWN SIGTERM is a terminal path: in-flight cases are reaped and
     the shutdown line names them;
- D  the orphan sweep: DRY-RUN by default, never touches a child whose parent is
     ALIVE (hard negative rod), reaps a true orphan once the parent is gone;
- E  an invalid sweep target is a NAMED error (exit 2, no traceback), including
     `--apply` without `--sweep-orphans` and an unknown flag;
- F  requirement 2: a case that still holds a live descendant can never report
     green - it is a named product red (white-box: a real process cannot survive
     SIGKILL, so the survivor set is injected).

Fixture shape (all legs): case (sh) -> holder (same process group, outlives the
case's own exit) -> agent (its own session). That is the real KI-377 shape: the
engine's worker keeps the group, the agent child detaches from it.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"

sys.path.insert(0, str(INTEG))
import run_scenarios as rs  # noqa: E402

AGENT_SLEEP_S = 180      # the leaking child never gets this far in a green run
HOLDER_SLEEP_S = 180
TINY_BUDGET_S = 2        # injected CMD_TIMEOUT for the timeout leg
POLL_S = 0.05


def _alive(pid):
    return rs._pid_alive(int(pid))


def _wait_dead(pids, timeout=10):
    """Bounded poll: every pid must be gone (ESRCH = dead) by the deadline."""
    deadline = time.time() + timeout
    left = {int(p) for p in pids}
    while left and time.time() < deadline:
        left = {p for p in left if _alive(p)}
        if left:
            time.sleep(POLL_S)
    return sorted(left)


def _wait_file(path, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            text = Path(path).read_text().strip()
        except OSError:
            text = ""
        if text:
            return int(text.split()[0])
        time.sleep(POLL_S)
    raise AssertionError("fixture never reported a pid at %s" % path)


class CaseTree:
    """A case shape that leaves a live agent session behind (KI-377).

    case (sh -c) -> holder  : same process group, still alive when the case ends
        holder  -> agent    : start_new_session=True, i.e. its own group AND its
                              own session - unreachable by any group signal, the
                              real engine spawn shape.
    Every pid a leg needs is written to its own file, so the assertions never
    depend on timing or on a machine-wide count.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.agent_pid_file = self.root / "agent.pid"
        self.holder_pid_file = self.root / "holder.pid"
        self.agent_script = self.root / "ki067_park_stub.py"
        self.agent_sid_file = self.root / "agent.sid"
        # The agent reports its OWN session id: sid == its own pid proves it is a
        # session leader, i.e. no group signal from the case can ever reach it.
        self.agent_script.write_text(
            "import os, time\n"
            "open(%r, 'w').write(str(os.getsid(0)))\n"
            "time.sleep(%d)\n" % (str(self.agent_sid_file), AGENT_SLEEP_S),
            encoding="utf-8")
        self.holder_script = self.root / "holder.py"
        self.holder_script.write_text(
            "import subprocess, sys, time\n"
            "# the engine's agent spawn shape: its OWN session (KI-377's leak)\n"
            "a = subprocess.Popen([sys.executable, sys.argv[1]],\n"
            "                     start_new_session=True)\n"
            "open(sys.argv[2], 'w').write(str(a.pid))\n"
            "time.sleep(%d)\n" % HOLDER_SLEEP_S, encoding="utf-8")
        self.case_script = self.root / "case.py"
        self.case_script.write_text(
            "import os, subprocess, sys, time\n"
            "holder, agent, agent_pid, holder_pid, linger = sys.argv[1:6]\n"
            "h = subprocess.Popen([sys.executable, holder, agent, agent_pid])\n"
            "open(holder_pid, 'w').write(str(h.pid))\n"
            "# wait for the agent to exist (bounded), then end the CASE while the\n"
            "# holder - and through it the detached agent - is still alive.\n"
            "deadline = time.time() + 10\n"
            "while time.time() < deadline and not os.path.exists(agent_pid):\n"
            "    time.sleep(0.02)\n"
            "time.sleep(float(linger))\n"
            "print('case-ended')\n", encoding="utf-8")

    def case_cmd(self, linger_s=0.0):
        return "%s %s %s %s %s %s %s" % (
            sys.executable, self.case_script, self.holder_script,
            self.agent_script, self.agent_pid_file, self.holder_pid_file,
            linger_s)

    def pids(self):
        """(agent, holder) as the fixture reported them (bounded wait)."""
        agent = _wait_file(self.agent_pid_file)
        holder = _wait_file(self.holder_pid_file)
        return agent, holder

    def reap_children(self):
        """Best-effort cleanup for a leg that fails before the reap runs."""
        for path in (self.agent_pid_file, self.holder_pid_file):
            try:
                pid = int(Path(path).read_text().strip())
            except (OSError, ValueError):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def pids_or_empty(self):
        """Whatever pid files exist, without waiting for a fixture to report."""
        out = []
        for path in (self.agent_pid_file, self.holder_pid_file):
            try:
                out.append(int(Path(path).read_text().strip()))
            except (OSError, ValueError):
                continue
        return out


class CaseExitReap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t261028-01-reap-")
        self.case = CaseTree(self.tmp)
        self.extra_pids = []   # fixture processes a leg spawned itself
        self._old_budget = rs.CMD_TIMEOUT
        self._old_hung = set(rs._HUNG_THIS_ROUND)

    def tearDown(self):
        # This battery must not leave a descendant behind either (it exists to
        # stop exactly that), so the cleanup is asserted, not just attempted.
        self.case.reap_children()
        for pid in self.extra_pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass
        left = _wait_dead(self.case.pids_or_empty() + self.extra_pids, timeout=5)
        rs.CMD_TIMEOUT = self._old_budget
        rs._HUNG_THIS_ROUND.clear()
        rs._HUNG_THIS_ROUND.update(self._old_hung)
        with rs._CASE_LOCK:
            rs._LIVE_CASES.clear()
            rs._REAP_RECEIPTS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertEqual(left, [], "the battery leaked live processes: %s" % left)

    def _entry(self, name, cmd):
        # entry shape: (name, intent, cmd, pool) — pool_of only reads index 3.
        return (name, "t261028-05 fixture", cmd, "main")

    # ---- A: pass terminal path -------------------------------------------------
    def test_a_child_alive_after_case_end_is_reaped_and_the_receipt_names_it(self):
        name = "t26102801-case-a"
        _name, rc, tail, _dur, _t0, full = rs._run_entry(
            self._entry(name, self.case.case_cmd()))
        agent, holder = self.case.pids()
        self.assertEqual(rc, 0, "the case itself passed; tail=%r" % (tail,))
        self.assertIn("case-ended", full)
        receipt = rs.case_receipt(name)
        self.assertIn("reaped", receipt,
                      "the case row must carry a NAMED receipt, got %r" % receipt)
        self.assertNotIn("SURVIVED", receipt)
        self.assertGreaterEqual(int(receipt.split()[1]), 2,
                                "the receipt must count both the holder and the "
                                "detached agent it reaped: %r" % receipt)
        self.assertEqual(_wait_dead([agent, holder]), [],
                         "a live agent session outlived its case (KI-377)")

    def test_a2_the_detached_agent_is_the_half_a_group_signal_cannot_reach(self):
        """The leak shape itself: the agent sits in its OWN session, so killpg on
        the case's group never reaches it - the ppid closure does. Proven from
        the reader side: the agent's session id is not the case's, and it dies
        anyway."""
        name = "t26102801-case-a2"
        _n, rc, _tail, _d, _t0, _full = rs._run_entry(
            self._entry(name, self.case.case_cmd()))
        agent, holder = self.case.pids()
        self.assertEqual(rc, 0)
        sid = int(_wait_file(self.case.agent_sid_file))
        self.assertEqual(sid, agent,
                         "the fixture agent must be a session leader (its own "
                         "session = the KI-377 shape); got sid=%d pid=%d"
                         % (sid, agent))
        receipt = rs.case_receipt(name)
        self.assertIn("reaped", receipt)
        self.assertEqual(_wait_dead([agent, holder]), [],
                         "the detached agent (own session) survived the reap")

    # ---- B: timeout terminal path ---------------------------------------------
    def test_b_timeout_path_reaps_the_whole_case_tree(self):
        rs.CMD_TIMEOUT = TINY_BUDGET_S
        name = "t26102801-case-b"
        t0 = time.monotonic()
        _n, rc, tail, _d, _t0, full = rs._run_entry(
            self._entry(name, self.case.case_cmd(linger_s=120)))
        wall = time.monotonic() - t0
        agent, holder = self.case.pids()
        self.assertEqual(rc, -9, "a hung case is a named timeout red")
        self.assertLessEqual(
            wall, TINY_BUDGET_S + rs._REAP_TERM_GRACE_S + rs._KILL_GRACE_S + 10,
            "the timeout red must land within the ladder (measured %.1fs)" % wall)
        receipt = rs.case_receipt(name)
        self.assertIn("reaped", receipt,
                      "the timeout path carries the same named receipt: %r"
                      % receipt)
        self.assertEqual(_wait_dead([agent, holder]), [],
                         "a timed-out case left a live agent session behind")

    # ---- C: the runner's own SIGTERM ------------------------------------------
    def _sigterm_driver(self):
        """A child that plays the runner: same install entry point, then one real
        case in flight. SIGTERM lands on the driver exactly as it lands on the
        runner process."""
        return (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import run_scenarios as rs\n"
            "rs._install_case_signal_reap()\n"
            "rs._run_entry((%r, 'fixture', sys.argv[1], 'main'))\n"
            "print('DRIVER-NOT-INTERRUPTED', flush=True)\n"
            % (str(INTEG), "t26102801-case-c"))

    def test_c_sigterm_to_the_runner_reaps_in_flight_cases(self):
        out = Path(self.tmp) / "driver.log"
        log = open(out, "wb")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", self._sigterm_driver(),
                 self.case.case_cmd(linger_s=120)],
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=str(ROOT))
            agent, holder = self.case.pids()   # the case is in flight now
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                self.fail("the runner ignored SIGTERM with a case in flight")
        finally:
            log.close()
        text = out.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 128 + int(signal.SIGTERM),
                         "the shutdown path exits by signal code; log=%r" % text)
        self.assertIn("INTEG_RUNNER_SIGNAL SIGTERM", text)
        self.assertIn("reaped", text,
                      "the shutdown line must name what it reaped: %r" % text)
        self.assertNotIn("DRIVER-NOT-INTERRUPTED", text)
        self.assertEqual(_wait_dead([agent, holder]), [],
                         "a case's agent session outlived the runner's SIGTERM")

    def test_c2_the_wiring_installs_the_handler_on_the_cli_run_path(self):
        """Source lock: the handler is installed by _cli (the runner process),
        never by main() - main() also runs in-process inside the gate, whose
        SIGTERM contract is not this ticket's to replace."""
        cli_src = rs.__dict__["_cli"].__code__.co_consts  # noqa: F841  (exists)
        import inspect
        self.assertIn("_install_case_signal_reap()", inspect.getsource(rs._cli))
        self.assertNotIn("_install_case_signal_reap()",
                         inspect.getsource(rs.main))

    # ---- D: the orphan sweep --------------------------------------------------
    def _live_parent_with_child(self, child_args=()):
        """A parent that is ALIVE and holds an agent-family child (the shape the
        negative rod must spare)."""
        parent_pid = Path(self.tmp) / "parent.pid"
        parent = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys\n"
             "child = subprocess.Popen([sys.executable] + sys.argv[1:])\n"
             "open(sys.argv[-1] + '.pids', 'w').write(str(child.pid))\n"
             "import time; time.sleep(%d)\n" % 120,
             str(self.case.agent_script)] + list(child_args) + [str(parent_pid)],
            start_new_session=True)
        child = _wait_file(str(parent_pid) + ".pids")
        return parent, child

    def test_d_sweep_spares_a_child_whose_parent_is_alive(self):
        parent, child = self._live_parent_with_child()
        try:
            lines = []
            code = rs.sweep_orphans(
                apply=False, families={"ki067_park_stub": str(self.case.agent_script)},
                out=lines.append)
            self.assertEqual(code, 0)
            report = "\n".join(lines)
            self.assertNotIn("pid=%d " % child, report,
                             "a child whose parent is ALIVE must never be listed "
                             "as an orphan: %r" % report)
            summary = json.loads(
                [ln for ln in lines if ln.startswith("SWEEP_SUMMARY ")][0]
                [len("SWEEP_SUMMARY "):])
            self.assertGreaterEqual(summary["kept_live_parent"], 1,
                                    "the live-parent child must be counted as kept")
            # and the same under --apply: the rod is about SIGNALS, not listing
            lines2 = []
            rs.sweep_orphans(
                apply=True, families={"ki067_park_stub": str(self.case.agent_script)},
                out=lines2.append)
            self.assertTrue(_alive(child),
                            "the sweep killed a child whose parent is alive")
        finally:
            self.extra_pids.append(child)
            parent.kill()
            parent.wait(timeout=10)
            try:
                os.kill(int(child), signal.SIGKILL)
            except OSError:
                pass

    def test_d3_a_console_shaped_process_is_never_touched(self):
        """The never-touch guard (requirement 3's hard floor): a family-shaped
        process whose command carries the console port is refused even when it is
        a true orphan - the sweep is not allowed to reach the operation face."""
        parent, child = self._live_parent_with_child(child_args=("3099",))
        self.extra_pids.append(child)
        parent.kill()
        parent.wait(timeout=10)
        lines = []
        rs.sweep_orphans(apply=True,
                         families={"ki067_park_stub": str(self.case.agent_script)},
                         out=lines.append)
        report = "\n".join(lines)
        self.assertNotIn("pid=%d " % child, report,
                         "a 3099-carrying process must never be listed: %r" % report)
        self.assertTrue(_alive(child),
                        "the sweep touched a console-shaped process")

    def test_d2_sweep_reaps_a_true_orphan_in_apply_mode(self):
        parent, child = self._live_parent_with_child()
        self.extra_pids.append(child)
        parent.kill()
        parent.wait(timeout=10)
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                table, err = rs._sweep_snapshot()
                self.assertEqual(err, "")
                if int(child) in table and table[int(child)][0] in (1, parent.pid):
                    if table[int(child)][0] == 1:
                        break
                time.sleep(POLL_S)
            # dry-run first: it must NOT signal
            lines = []
            rs.sweep_orphans(apply=False,
                             families={"ki067_park_stub": str(self.case.agent_script)},
                             out=lines.append)
            self.assertIn("pid=%d " % child, "\n".join(lines),
                          "a true orphan must be named in the report")
            self.assertIn("action=would-reap", "\n".join(lines),
                          "dry-run is the default: it reports, it does not signal")
            self.assertTrue(_alive(child), "a dry-run must not signal anything")
            # apply: TERM then KILL
            lines2 = []
            code = rs.sweep_orphans(
                apply=True, families={"ki067_park_stub": str(self.case.agent_script)},
                out=lines2.append)
            self.assertEqual(code, 0, "\n".join(lines2))
            self.assertIn("pid=%d " % child, "\n".join(lines2))
            self.assertIn("action=reaped", "\n".join(lines2))
            self.assertEqual(_wait_dead([child]), [], "the orphan survived")
        finally:
            self.case.reap_children()
            try:
                os.kill(int(child), signal.SIGKILL)
            except OSError:
                pass

    # ---- E: an invalid sweep target is a NAMED error --------------------------
    def test_e_invalid_sweep_target_is_a_named_error_not_a_traceback(self):
        lines = []
        code = rs.sweep_orphans(targets=["no-such-family"], out=lines.append)
        self.assertEqual(code, 2)
        report = "\n".join(lines)
        self.assertIn("unknown sweep target", report)
        self.assertIn("no-such-family", report)
        self.assertIn("ki067_park_stub", report,
                      "the refusal must list the known families")
        self.assertEqual(rs._cli(["--sweep-orphans", "no-such-family"]), 2)
        self.assertEqual(rs._cli(["--apply"]), 2,
                         "--apply without --sweep-orphans is refused by name")
        self.assertEqual(rs._cli(["--sweep-orphans", "--no-such-flag"]), 2)
        self.assertEqual(rs._cli(["--sweep-orphans"]), 0,
                         "the bare sweep is a dry-run report (exit 0)")

    # ---- F: never green while holding a live descendant ----------------------
    def test_f_a_case_holding_a_live_descendant_is_a_named_red(self):
        """White-box by necessity: no real process survives SIGKILL, so the
        survivor set is injected - the judgement under test is what the runner
        does with it (the run's verdict must never be green)."""
        real = rs._reap_case_tree
        try:
            rs._reap_case_tree = (
                lambda leader, proc=None, tree=None, group_termed=False: (
                    "reaped 1 descendant; 1 SURVIVED: 99999", {99999}))
            name = "t26102801-case-f"
            _n, rc, tail, _d, _t0, full = rs._run_entry(
                self._entry(name, "echo case-pass"))
        finally:
            rs._reap_case_tree = real
        self.assertEqual(rc, rs._LIVE_DESCENDANTS,
                         "a live descendant is a product red, never a green")
        self.assertNotIn(rc, (0, 2, rs._SPAWN_FAIL),
                         "the code must land as a product red for the row writer")
        self.assertIn("LIVE_DESCENDANTS_AFTER_REAP", tail)
        self.assertIn("99999", tail)
        self.assertIn("LIVE_DESCENDANTS_AFTER_REAP", full)


if __name__ == "__main__":
    unittest.main(verbosity=2)
