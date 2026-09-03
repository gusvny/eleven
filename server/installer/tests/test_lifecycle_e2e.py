"""生命周期 E2E（stub 全替身，ephemeral 端口）：up/status/幂等/down 时序/红路径。

替身：fake temporal CLI（真监听 ephemeral 端口 + TERM stamp + retention 可注入失败）、
fake worker venv python（复刻 worker.py --daemon 手法：父写 pidfile 即退，子常驻）。
全部状态写 tmp HOME，不碰 7233/8233/3099。
"""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from installer import runtime  # noqa: E402
from installer import service  # noqa: E402
from installer.runtime import InstallPaths  # noqa: E402

FAKE_TEMPORAL = """\
#!/usr/bin/env python3
import os, signal, socket, sys, time
args = sys.argv[1:]
if "server" in args:
    port = int(args[args.index("--port") + 1])
    if os.environ.get("FAKE_SERVER_EXIT"):
        sys.stderr.write("fake temporal: boom\\n"); sys.exit(1)
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(16)
    def h(*a):
        open(os.environ["SANDBAR_SERVER_STAMP"], "w").write(str(time.time()))
        sys.exit(0)
    signal.signal(signal.SIGTERM, h); signal.signal(signal.SIGINT, h)
    sys.stdout.write("ready\\n"); sys.stdout.flush()
    time.sleep(120)
if "update" in args:
    sys.exit(1 if os.environ.get("FAKE_RETENTION_FAIL") else 0)
if "describe" in args:
    print("Retention Period: 876000h"); sys.exit(0)
sys.exit(2)
"""

FAKE_VENV_PY = """\
#!/usr/bin/env python3
import os, signal, sys, time, pathlib
a = sys.argv[1:]
pidfile = a[a.index("--pidfile") + 1]
devnull = os.open(os.devnull, os.O_RDWR)
pid = os.fork()
if pid > 0:
    pathlib.Path(pidfile).write_text(str(pid))
    sys.exit(0)
os.setsid()
os.dup2(devnull, 0); os.dup2(devnull, 1); os.dup2(devnull, 2)
def h(*a):
    open(os.environ["SANDBAR_WORKER_STAMP"], "w").write(str(time.time()))
    sys.exit(0)
signal.signal(signal.SIGTERM, h); signal.signal(signal.SIGINT, h)
pathlib.Path(pidfile).write_text(str(os.getpid()))
time.sleep(120)
"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LifecycleE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-e2e-")
        self._env_backup = {k: os.environ.get(k) for k in
                            ("SANDBAR_HOME", "SANDBAR_SERVER_STAMP",
                             "SANDBAR_WORKER_STAMP", "FAKE_RETENTION_FAIL",
                             "FAKE_SERVER_EXIT")}
        os.environ.pop("SANDBAR_HOME", None)
        self.root = pathlib.Path(self.tmp) / "repo"
        self.poc = self.root / "server" / "dsh" / "temporal-poc"
        (self.poc / "data").mkdir(parents=True)
        (self.poc / "worker.py").write_text("# stub\n", encoding="utf-8")
        self.home = pathlib.Path(self.tmp) / "home"
        self.fake_bin = pathlib.Path(self.tmp) / "fake-temporal"
        self.fake_bin.write_text(FAKE_TEMPORAL, encoding="utf-8")
        os.chmod(self.fake_bin, 0o755)
        self.fake_venv = pathlib.Path(self.tmp) / "fake-venv-python"
        self.fake_venv.write_text(FAKE_VENV_PY, encoding="utf-8")
        os.chmod(self.fake_venv, 0o755)
        self.sp = free_port()
        self.up_ = free_port()
        self.paths = InstallPaths(root=str(self.root), home=str(self.home),
                                  server_port=self.sp, ui_port=self.up_,
                                  temporal_bin=str(self.fake_bin),
                                  venv_python=str(self.fake_venv))
        self.logs = []
        self._log = lambda line: self.logs.append(str(line))

    def tearDown(self):
        # 兜底回收：一切 stub 进程/端口终态清零
        runtime.clear_pidfile(self.paths.server_pidfile)
        runtime.clear_pidfile(self.paths.worker_pidfile)
        for name in ("server.pid", "worker.pid"):
            pf = self.home / "run" / name
            if pf.exists():
                try:
                    pid = int(pf.read_text().strip())
                    os.kill(pid, 9)
                except (OSError, ValueError):
                    pass
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _stamp_paths(self):
        wstamp = os.path.join(self.tmp, "worker.stamp")
        sstamp = os.path.join(self.tmp, "server.stamp")
        os.environ["SANDBAR_WORKER_STAMP"] = wstamp
        os.environ["SANDBAR_SERVER_STAMP"] = sstamp
        return wstamp, sstamp

    def _wait_file(self, path, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(path):
                return float(open(path).read().strip())
            time.sleep(0.1)
        return None

    def test_up_status_down_green_journey(self):
        wstamp, sstamp = self._stamp_paths()
        rc = service.cmd_up(self.paths, self._log)
        self.assertEqual(rc, 0, self.logs)
        self.assertTrue(runtime.port_open(self.sp), "up 后 server 端口开")
        self.assertEqual(runtime.live_pid(self.paths.server_pidfile),
                         runtime.read_pid(self.paths.server_pidfile))
        self.assertIsNotNone(runtime.read_pid(self.paths.worker_pidfile))
        # retention 已校正（日志面可见校正成功）
        self.assertTrue(any("retention=876000h" in ln for ln in self.logs))
        # status：在管面 + console 提示
        self.logs.clear()
        rc = service.cmd_status(self.paths, self._log)
        self.assertEqual(rc, 0)
        blob = "\n".join(self.logs)
        self.assertIn("运行中", blob)
        self.assertIn("console 属用户操作面", blob)
        self.assertIn("请手动起停", blob)
        # 重复 up 幂等：不重复拉起（端口仍一个监听者=同一 pid）
        pid_before = runtime.read_pid(self.paths.server_pidfile)
        rc = service.cmd_up(self.paths, self._log)
        self.assertEqual(rc, 0)
        self.assertEqual(runtime.read_pid(self.paths.server_pidfile), pid_before)
        # down：先 worker 后 server（TERM stamp 观测）+ 终态全灭
        t0 = time.time()
        rc = service.cmd_down(self.paths, self._log)
        elapsed = time.time() - t0
        self.assertEqual(rc, 0, self.logs)
        tw = self._wait_file(wstamp)
        ts = self._wait_file(sstamp)
        self.assertIsNotNone(tw, "worker 未收到 TERM")
        self.assertIsNotNone(ts, "server 未收到 TERM")
        self.assertLessEqual(tw, ts + 0.01, "红线：down 必须先 worker 后 server")
        self.assertLess(elapsed, 60)
        self.assertFalse(runtime.port_open(self.sp), "server 端口已释放")
        self.assertIsNone(runtime.read_pid(self.paths.server_pidfile))
        self.assertIsNone(runtime.read_pid(self.paths.worker_pidfile))

    def test_up_retention_fail_closed_reaps_server(self):
        os.environ["FAKE_RETENTION_FAIL"] = "1"
        with self.assertRaises(service.FailClosed) as ctx:
            service.cmd_up(self.paths, self._log)
        self.assertIn("retention", str(ctx.exception))
        # 刚拉起的 server 已被回收（全终态纪律），pidfile 清空
        self.assertFalse(runtime.port_open(self.sp, timeout=0.6))
        self.assertIsNone(runtime.read_pid(self.paths.server_pidfile))

    def test_up_server_immediate_death_fail_closed(self):
        os.environ["FAKE_SERVER_EXIT"] = "1"
        real_timeout = runtime.SERVER_START_TIMEOUT
        try:
            runtime.SERVER_START_TIMEOUT = 2.0  # 仅本测加速（保证 30s 量级纪律不被掩盖）
            with self.assertRaises(service.FailClosed) as ctx:
                service.cmd_up(self.paths, self._log)
        finally:
            runtime.SERVER_START_TIMEOUT = real_timeout
        self.assertIn("启动超时", str(ctx.exception))
        self.assertIsNone(runtime.read_pid(self.paths.server_pidfile))

    def test_worker_tooling_missing_yellow_skip(self):
        self.paths._venv_python = pathlib.Path(self.tmp) / "no-such-python"
        rc = service.cmd_up(self.paths, self._log)
        self.assertEqual(rc, 0)
        blob = "\n".join(self.logs)
        self.assertIn("[黄]", blob)               # 显式黄条，非静默
        self.assertIn("工具面缺失", blob)
        self.assertIsNone(runtime.read_pid(self.paths.worker_pidfile))
        self.assertIsNotNone(runtime.read_pid(self.paths.server_pidfile))
        rc = service.cmd_down(self.paths, self._log)
        self.assertEqual(rc, 0)

    def test_down_when_nothing_running(self):
        rc = service.cmd_down(self.paths, self._log)
        self.assertEqual(rc, 0)
        self.assertTrue(any("本就未在运行" in ln for ln in self.logs))

    def test_status_json(self):
        service.cmd_up(self.paths, self._log)
        self.logs.clear()
        rc = service.cmd_status(self.paths, self._log, as_json=True)
        self.assertEqual(rc, 0)
        import json
        facts = json.loads("\n".join(self.logs))
        self.assertEqual(facts["server"]["state"], runtime.ALIVE)
        self.assertTrue(facts["server"]["port_open"])


if __name__ == "__main__":
    unittest.main()
