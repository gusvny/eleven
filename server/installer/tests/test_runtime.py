"""runtime 低层件单测：pidfile 三态、存活分态、停机升级（stub 进程复现）。"""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from installer import runtime  # noqa: E402


def _write(path, body, mode=0o644):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    os.chmod(p, mode)
    return p


def _spawn_sleep(secs=30):
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(%d)" % secs],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.15)  # 等进程真正起来
    return p


class ReadPidTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-")
        self.pf = os.path.join(self.tmp, "x.pid")

    def test_roundtrip(self):
        runtime.write_pid(self.pf, 4242)
        self.assertEqual(runtime.read_pid(self.pf), 4242)

    def test_missing_none(self):
        self.assertIsNone(runtime.read_pid(self.pf))

    def test_dirty_none_and_selfclean(self):
        _write(self.pf, "not-a-pid\n")
        self.assertIsNone(runtime.read_pid(self.pf))
        self.assertFalse(os.path.exists(self.pf))  # 脏值自清（§2-#2）

    def test_dirty_empty_and_negative(self):
        _write(self.pf, "\n")
        self.assertIsNone(runtime.read_pid(self.pf))
        _write(self.pf, "-3\n")
        self.assertIsNone(runtime.read_pid(self.pf))

    def test_stale_selfclean(self):
        p = _spawn_sleep()
        p.terminate(); p.wait(timeout=5)
        _write(self.pf, str(p.pid))
        self.assertIsNone(runtime.live_pid(self.pf))          # 陈旧→None
        self.assertFalse(os.path.exists(self.pf))             # 陈旧自清
        _write(self.pf, str(p.pid))
        self.assertEqual(runtime.pid_state(p.pid), runtime.DEAD)  # ESRCH=死

    def test_live_pid_alive(self):
        p = _spawn_sleep(3)
        try:
            _write(self.pf, str(p.pid))
            self.assertEqual(runtime.live_pid(self.pf), p.pid)
            self.assertEqual(runtime.pid_state(p.pid), runtime.ALIVE)
        finally:
            p.terminate(); p.wait(timeout=5)

    def test_eperm_state(self):
        with mock.patch("os.kill", side_effect=PermissionError(1, "no")):
            self.assertEqual(runtime.pid_state(12345), runtime.EPERM)
            _write(self.pf, "12345")
            self.assertEqual(runtime.live_pid(self.pf), 12345)  # EPERM=还在，不判死


class PortProbeTest(unittest.TestCase):
    def test_closed_port_false_fast(self):
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
        s.close()
        t0 = time.monotonic()
        self.assertFalse(runtime.port_open(free_port, timeout=0.4))
        self.assertLess(time.monotonic() - t0, 3.0)

    def test_listening_port_true(self):
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(runtime.port_open(port, timeout=0.8))
        finally:
            srv.close()

    def test_wait_until(self):
        self.assertTrue(runtime.wait_until(lambda: True, 0.5))
        t0 = time.monotonic()
        self.assertFalse(runtime.wait_until(lambda: False, 0.4))
        self.assertGreaterEqual(time.monotonic() - t0, 0.3)


class StopProcessTest(unittest.TestCase):
    def _spawn(self, body):
        tmp = tempfile.mkdtemp(prefix="sandbar-ut-stop-")
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        log = os.path.join(tmp, "stub.log")
        return runtime.spawn_detached([sys.executable, "-c", body], tmp, log), tmp

    def test_term_graceful(self):
        stamp = tempfile.mktemp(prefix="stamp-")
        src = ("import signal,sys,time,os\n"
               "def h(*a):\n"
               "    open(os.environ['S'],'w').write('t')\n"
               "    sys.exit(0)\n"
               "signal.signal(signal.SIGTERM,h)\n"
               "time.sleep(30)\n")
        old = os.environ.get("S")
        os.environ["S"] = stamp
        try:
            p, _ = self._spawn(src)
            time.sleep(0.2)
            outcome = runtime.stop_process(p.pid, "stub", term_timeout=3, log=lambda *_: None)
            self.assertEqual(outcome, "stopped")
            self.assertTrue(os.path.exists(stamp))
        finally:
            if old is None:
                os.environ.pop("S", None)
            else:
                os.environ["S"] = old

    def test_kill_escalation(self):
        src = ("import signal,time\n"
               "signal.signal(signal.SIGTERM, lambda *a: None)\n"  # 无视 TERM
               "time.sleep(30)\n")
        p, _ = self._spawn(src)
        time.sleep(0.2)
        logs = []
        outcome = runtime.stop_process(p.pid, "stub", term_timeout=0.5, log=logs.append)
        self.assertEqual(outcome, "killed")
        self.assertTrue(any("SIGKILL" in ln for ln in logs))  # 强杀显式声明

    def test_eperm_reported(self):
        with mock.patch("os.kill", side_effect=PermissionError(1, "no")):
            logs = []
            outcome = runtime.stop_process(99999, "stub", term_timeout=0.2, log=logs.append)
            self.assertEqual(outcome, "eperm")
            self.assertTrue(any("权限不足" in ln for ln in logs))

    def test_already_dead(self):
        p = _spawn_sleep()
        p.kill(); p.wait(timeout=5)
        self.assertEqual(
            runtime.stop_process(p.pid, "stub", term_timeout=0.2, log=lambda *_: None),
            "stopped")

    def test_zombie_child_reaped_not_misjudged(self):
        """本进程拉起的孩子退出后若成 zombie，stop_process 不得误判「杀不掉」。"""
        src = "import signal,sys,time\nsignal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\ntime.sleep(30)\n"
        p, _ = self._spawn(src)
        time.sleep(0.2)
        runtime.send_signal(p.pid, signal.SIGTERM)  # 让它退（父侧不 wait→zombie）
        time.sleep(0.2)
        outcome = runtime.stop_process(p.pid, "stub", term_timeout=1, log=lambda *_: None)
        self.assertEqual(outcome, "stopped")
        self.assertIsNotNone(p.poll())          # 已被回收（waitpid 语义达成）
        self.assertNotIn(p, runtime._SPAWNED)   # 注册表已清（只断言本测试的孩子）


class ProcInfoTest(unittest.TestCase):
    def _ps_available(self):
        return runtime.proc_cmdline(os.getpid()) is not None

    def test_cmdline_and_ppid_of_self_child(self):
        if not self._ps_available():
            self.skipTest("本沙箱禁 spawn ps 且无 /proc——argv 面由自报桩测试覆盖"
                          "（test_service.py），真实 ps 面归集成场景")
        p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(5)",
                              "标记参数xyz"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            cmd = runtime.proc_cmdline(p.pid)
            self.assertIn("标记参数xyz", cmd)
            self.assertEqual(runtime.proc_ppid(p.pid), os.getpid())
        finally:
            p.terminate(); p.wait(timeout=5)

    def test_dead_pid_none(self):
        self.assertIsNone(runtime.proc_ppid(0))  # pid 0 恒读不到（防御面）


if __name__ == "__main__":
    unittest.main()
