"""service 编排单测：认领谓词三态、data/worker.pid 回落、retention fail-closed。

外部源桩口径：本沙箱禁 spawn `ps`（真实宿主/集成执行环境不受限），故进程信息
经「自报桩」复现——stub 进程把 argv 面（ps command 面）与本进程 getppid() 周期
写进报告文件，单测将其接进 runtime.proc_cmdline/proc_ppid 边界。真孤儿路径仍用
「中间父退场」真实复现（报告里的 ppid 会真实变成 1）。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from installer import runtime  # noqa: E402
from installer import service  # noqa: E402
from installer.runtime import InstallPaths  # noqa: E402

STUB_SRC = """\
import os, signal, sys, time
report = os.environ["SANDBAR_STUB_REPORT"]
face = os.environ["SANDBAR_STUB_FACE"]
def h(*a):
    sys.exit(0)
signal.signal(signal.SIGTERM, h)
while True:
    try:
        with open(report, "w") as f:
            f.write("%d\\n%s\\n" % (os.getppid(), face))
    except OSError:
        pass
    time.sleep(0.05)
"""


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sandbar-ut-svc-"))
        self.root = self.tmp / "repo"
        self.poc = self.root / "server" / "engine"
        (self.poc / "data").mkdir(parents=True)
        (self.poc / "worker.py").write_text("# stub\n", encoding="utf-8")
        self.home = self.tmp / "home"
        self.paths = InstallPaths(root=str(self.root), home=str(self.home),
                                  server_port=17333, ui_port=18233)
        self.procs = []
        self._patches = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill(); p.wait(timeout=5)
        for pt in self._patches:
            pt.stop()

    def patch_proc_info(self, report: pathlib.Path):
        """把自报桩接进 runtime 边界（argv 面 + ppid）。"""
        def fake_cmdline(pid):
            try:
                lines = report.read_text(encoding="utf-8").splitlines()
                return lines[1].strip() if len(lines) > 1 else None
            except (OSError, IndexError):
                return None

        def fake_ppid(pid):
            try:
                return int(report.read_text(encoding="utf-8").splitlines()[0])
            except (OSError, ValueError, IndexError):
                return None

        self._patches.append(mock.patch.object(runtime, "proc_cmdline", fake_cmdline))
        self._patches.append(mock.patch.object(runtime, "proc_ppid", fake_ppid))
        self._patches[0].start()
        self._patches[1].start()

    def spawn_report_stub(self, face_args):
        """拉起自报桩；返回 (Popen, report路径)。face_args=ps 应看到的 argv 面。"""
        self._seq = getattr(self, "_seq", 0) + 1
        report = self.tmp / ("stub-report-%d" % self._seq)
        src = self.tmp / ("stub-%d.py" % self._seq)
        src.write_text(STUB_SRC, encoding="utf-8")
        env = {**os.environ,
               "SANDBAR_STUB_REPORT": str(report),
               "SANDBAR_STUB_FACE": " ".join(face_args)}
        p = subprocess.Popen([sys.executable, str(src)], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        deadline = time.time() + 5
        while time.time() < deadline:
            if report.exists():
                break
            time.sleep(0.05)
        return p, report

    def wait_report_ppid(self, report: pathlib.Path, want: int, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if int(report.read_text(encoding="utf-8").splitlines()[0]) == want:
                    return True
            except (OSError, ValueError, IndexError):
                pass
            time.sleep(0.1)
        return False


START_DEV_FACE = ["temporal", "server", "start-dev", "--data", "__HOME__"]


class SurfaceMatchTest(Env):
    def test_match_startdev_our_home(self):
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", str(self.paths.home)])
        self.patch_proc_info(rep)
        ok, why = service.surface_match(self.paths, p.pid)
        self.assertTrue(ok, why)
        self.assertIn("home", why)

    def test_match_startdev_our_datavol(self):
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--db-filename", str(self.paths.db_path)])
        self.patch_proc_info(rep)
        ok, _ = service.surface_match(self.paths, p.pid)
        self.assertTrue(ok)

    def test_mismatch_cmdline(self):
        p, rep = self.spawn_report_stub(["python", "listen.py"])
        self.patch_proc_info(rep)
        ok, why = service.surface_match(self.paths, p.pid)
        self.assertFalse(ok)
        self.assertIn("start-dev", why)

    def test_mismatch_datavol(self):
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", "/somewhere/else"])
        self.patch_proc_info(rep)
        ok, why = service.surface_match(self.paths, p.pid)
        self.assertFalse(ok)
        self.assertIn("数据卷", why)


class ClaimVerdictTest(Env):
    def test_sibling_alive_parent_no_claim(self):
        """父进程（本测试进程）仍在=supervisor 面：不认领，报「父进程仍在/归属」。"""
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", str(self.paths.home)])
        self.patch_proc_info(rep)
        ok, why = service.claim_verdict(self.paths, p.pid)
        self.assertFalse(ok)
        self.assertIn("父进程", why)
        self.assertIn("supervisor", why)
        self.assertIn("归属", why)

    def test_true_orphan_claim(self):
        """中间父退场→真孤儿（ppid=1，桩自报真实值）：谓词全中才认领（V1）。"""
        inter_src = (
            "import os,subprocess,sys,time\n"
            "env = dict(os.environ)\n"
            "child = subprocess.Popen([sys.executable, %r], env=env,\n"
            "                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "time.sleep(3600)\n" % str(self.tmp / "orphan-stub.py"))
        stub_src = STUB_SRC
        (self.tmp / "orphan-stub.py").write_text(stub_src, encoding="utf-8")
        report = self.tmp / "orphan-report"
        env = {**os.environ, "SANDBAR_STUB_REPORT": str(report),
               "SANDBAR_STUB_FACE": " ".join(
                   ["temporal", "server", "start-dev", "--data", str(self.paths.home)])}
        inter = subprocess.Popen([sys.executable, "-c", inter_src], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(inter)
        deadline = time.time() + 5
        while time.time() < deadline and not report.exists():
            time.sleep(0.05)
        self.assertTrue(report.exists(), "孤儿 stub 未就绪")
        # 杀掉中间父：stub 被收养（ppid→1，真实内核语义，非桩造数据）
        inter.kill(); inter.wait(timeout=5)
        self.assertTrue(self.wait_report_ppid(report, 1), "stub 应被收养（ppid=1）")
        self.patch_proc_info(report)
        # 谓词检的 pid 用报告进程自身？桩退场后 pid 换代——直接以桩孙进程为对象：
        # 这里报告文件即该 stub 的自报；claim_verdict 需要活 pid——用当前活进程占位，
        # 因 proc_cmdline/proc_ppid 已被桩接管，pid 仅作键值。
        placeholder = os.getpid()
        ok, why = service.claim_verdict(self.paths, placeholder)
        self.assertTrue(ok, why)


class WorkerFallbackTest(Env):
    def test_fallback_claim(self):
        """§2-#7：安装器 pidfile 缺失+data/worker.pid 指向活 worker→认领（只写安装器 pidfile）。"""
        p, rep = self.spawn_report_stub(["python", "worker.py", str(self.poc)])
        self.patch_proc_info(rep)
        (self.poc / "data" / "worker.pid").write_text(str(p.pid), encoding="utf-8")
        logs = []
        pid = service.resolve_worker_pid(self.paths, logs.append)
        self.assertEqual(pid, p.pid)
        self.assertEqual(runtime.read_pid(self.paths.worker_pidfile), p.pid)
        self.assertTrue(any("认领" in ln for ln in logs))

    def test_fallback_mismatch_no_claim(self):
        p, rep = self.spawn_report_stub(["python", "unrelated.py", str(self.poc)])
        self.patch_proc_info(rep)
        (self.poc / "data" / "worker.pid").write_text(str(p.pid), encoding="utf-8")
        logs = []
        self.assertIsNone(service.resolve_worker_pid(self.paths, logs.append))
        self.assertIsNone(runtime.read_pid(self.paths.worker_pidfile))
        self.assertTrue(any("不认领" in ln for ln in logs))

    def test_fallback_stale_hint(self):
        p, _ = self.spawn_report_stub(["python", "worker.py", str(self.poc)])
        p.kill(); p.wait(timeout=5)
        (self.poc / "data" / "worker.pid").write_text(str(p.pid), encoding="utf-8")
        logs = []
        self.assertIsNone(service.resolve_worker_pid(self.paths, logs.append))
        self.assertTrue(any("陈旧" in ln for ln in logs))
        # data/worker.pid 不被安装器代删（两写禁止）
        self.assertTrue((self.poc / "data" / "worker.pid").exists())


class RetentionTest(Env):
    def setUp(self):
        super().setUp()
        fake = self.tmp / "fake-temporal"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import os,sys\n"
            "args=sys.argv[1:]\n"
            "if 'update' in args:\n"
            "    sys.exit(1 if os.environ.get('FAKE_RETENTION_FAIL') else 0)\n"
            "if 'describe' in args:\n"
            "    print('Retention Period: 876000h'); sys.exit(0)\n"
            "sys.exit(2)\n", encoding="utf-8")
        os.chmod(fake, 0o755)
        self.paths._temporal_bin = fake

    def test_ok(self):
        with mock.patch("installer.service.time.sleep", lambda *_: None):
            self.assertTrue(service.correct_retention(self.paths, lambda *_: None))

    def test_fail_closed(self):
        os.environ["FAKE_RETENTION_FAIL"] = "1"
        try:
            with mock.patch("installer.service.time.sleep", lambda *_: None):
                logs = []
                self.assertFalse(service.correct_retention(self.paths, logs.append))
            self.assertTrue(any("校正" in ln for ln in logs))
        finally:
            os.environ.pop("FAKE_RETENTION_FAIL", None)


class AdoptServerTest(Env):
    def test_adopt_writes_pidfile(self):
        """up 侧纳管：谓词命中的在跑 server 记进 pidfile（只记录不杀）。"""
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", str(self.paths.home)])
        self.patch_proc_info(rep)
        with mock.patch.object(runtime, "find_port_pids", return_value=[p.pid]):
            pid = service.adopt_running_server(self.paths, lambda *_: None)
        self.assertEqual(pid, p.pid)
        self.assertEqual(runtime.read_pid(self.paths.server_pidfile), p.pid)
        self.assertTrue(p.poll() is None)  # 只记录，不动进程

    def test_adopt_reject_mismatch(self):
        p, rep = self.spawn_report_stub(["python", "something-else"])
        self.patch_proc_info(rep)
        with mock.patch.object(runtime, "find_port_pids", return_value=[p.pid]):
            with self.assertRaises(service.FailClosed) as ctx:
                service.adopt_running_server(self.paths, lambda *_: None)
        self.assertIn("不满足纳管谓词", str(ctx.exception))
        self.assertTrue(p.poll() is None)  # 不误杀


class OrphanResolveTest(Env):
    def test_supervisor_held_report_only(self):
        """V1 铁口径：down 遇 supervisor 持有→FailClosed 报告+不杀+不认领。"""
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", str(self.paths.home)])
        self.patch_proc_info(rep)  # ppid=本测试进程（活 supervisor）
        with mock.patch.object(runtime, "find_port_pids", return_value=[p.pid]):
            with self.assertRaises(service.FailClosed) as ctx:
                service.resolve_port_orphan(self.paths, lambda *_: None)
        msg = str(ctx.exception)
        self.assertIn("父进程", msg)
        self.assertIn("不杀", msg)
        self.assertTrue(p.poll() is None)                               # 不杀
        self.assertIsNone(runtime.read_pid(self.paths.server_pidfile))  # 不认领

    def test_true_orphan_claimed_then_stoppable(self):
        p, rep = self.spawn_report_stub(["temporal", "server", "start-dev",
                                         "--data", str(self.paths.home)])
        # 桩报告 ppid 置为 1 的口径：直接以真实收养路径覆盖（见 ClaimVerdictTest），
        # 此处用桩文件伪造孤儿面，验证 down 侧「认领→写 pidfile」全链。
        report_override = self.tmp / "orphan-face"
        report_override.write_text("1\ntemporal server start-dev --data %s\n"
                                   % self.paths.home, encoding="utf-8")
        self.patch_proc_info(report_override)
        with mock.patch.object(runtime, "find_port_pids", return_value=[p.pid]):
            pid = service.resolve_port_orphan(self.paths, lambda *_: None)
        self.assertEqual(pid, p.pid)
        self.assertEqual(runtime.read_pid(self.paths.server_pidfile), p.pid)


if __name__ == "__main__":
    unittest.main()
