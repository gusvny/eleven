"""宿主 260930 直修（无票）：worker 重启唯一性守卫（pidfile 单槽 + `--replace`）。

intent（守护的用户可感知行为）：**重启后同队列只可能有一颗 worker 在轮询**。

为什么（宿主实报，四次撞到）：两颗 worker 在同一队列上并存 3~5 秒时，谁先领到
workflow task 就谁执行 ⇒ 真票 t260930-09 第 4 轮出现「票面文案是旧格式 + 票面 ran=0
而泳道报告 ran=13」这种**无法归因到确定代码版本**的结果。daemon 档原先只单 fork、
不读也不回收已有 worker，第二个启动只会静默改写 pidfile。

覆盖口径：
- 纯函数矩阵：`read_pidfile_state` 四态（absent/malformed/stale/live）+
  `guard_single_worker` 三态 × {缺省拒绝 / --replace 接管 / 旁车指向他仓=不代杀}；
- 真进程面（真 worker.py 子进程 + 真 pidfile）：活 pid 拒绝启动（退出码 2 + 具名 stderr +
  **pidfile 内容不被改写** + 旧进程仍活着）、陈旧 pidfile 正常接管、`--replace` 先 TERM
  旧 worker（见到它真退出）再起新的且 pidfile 指向新 pid、超时路径报错且**不 KILL**。
- 零 Temporal 依赖：daemon 子进程连不上 TARGET_HOST 就在 connect 处死掉，但**守卫与
  pidfile 写入都发生在 connect 之前**——正是被测面；因此本 UT 无台可跑、秒级。

分工（防重复）：`test_t260904_02_worker_meta.py` 守归属指纹 meta 的形状/四态/接线；
`integration/t260905-02/sc_console_duplicate_guard.py` 守 console 侧 supervisor 的双
console 防重与工单 worker 抢注。本文件守的是**worker 进程自己的启动唯一性**（新面）。
"""

import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import worker  # noqa: E402

WORKER_PY = str(Path(worker.__file__).resolve())


def _spawn_sleeper(ignore_term=False) -> int:
    """起一个**脱离本进程树的孩子**（双 fork，归 init 收养）当「假旧 worker」，返回 pid。

    为什么必须脱离：本进程的子进程被 SIGTERM 杀掉后会是**僵尸**，而僵尸的 `kill(pid,0)`
    仍然成功——那测的就不是守卫本身了（守卫的 pid_alive 有僵尸修正，但 macOS 上非自家
    子进程查不到状态）。这里构造**生产同形**：旧 worker 归 init 收养、退出即被收割。
    默认收 SIGTERM 即退；ignore_term=吞掉它（测 --replace 超时路）。

    pid 经临时文件回传（不走管道：孙进程持有管道会让父进程读到 EOF 前一直等）。"""
    handle, pidfile = tempfile.mkstemp(prefix="fake-worker-pid-")
    os.close(handle)
    os.unlink(pidfile)
    code = ("import os, signal, sys, time\n"
            "pidfile = %r\n"
            "if os.fork() > 0:\n"
            "    os._exit(0)\n"
            "open(pidfile, 'w').write(str(os.getpid()))\n"
            % pidfile
            + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
            + "while True: time.sleep(0.2)\n")
    subprocess.run([sys.executable, "-c", code], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=60)
    t0 = time.time()
    while time.time() - t0 < 20:
        try:
            raw = Path(pidfile).read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        if raw.isdigit():
            os.unlink(pidfile)
            return int(raw)
        time.sleep(0.1)
    raise AssertionError("假旧 worker 没起来（pid 文件 %s 未落）" % pidfile)


def _alive(pid: int) -> bool:
    return worker.pid_alive(pid)


def _wait_dead(pid: int, timeout=15.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class PidfileStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="worker-guard-"))
        self.pf = self.tmp / "worker.pid"
        self.procs = []

    def tearDown(self):
        for pid in self.procs:
            _kill(pid)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_four_states(self):
        # absent
        self.assertEqual(worker.read_pidfile_state(str(self.pf))["state"], "absent")
        # malformed（脏值：非数字 / 空 / 负 / 0）→ 陈旧可接管，但留痕
        for bad in ("abc", "", "  ", "-3", "0", "1.5"):
            self.pf.write_text(bad, encoding="utf-8")
            st = worker.read_pidfile_state(str(self.pf))
            self.assertEqual(st["state"], "malformed", bad)
            self.assertIn("按陈旧接管", st["detail"])
        # stale（合法 pid 但已不在）
        self.pf.write_text("999999", encoding="utf-8")
        st = worker.read_pidfile_state(str(self.pf))
        self.assertEqual(st["state"], "stale")
        self.assertEqual(st["pid"], 999999)
        self.assertIn("已不在", st["detail"])
        # live（真活进程）
        pid = _spawn_sleeper()
        self.procs.append(pid)
        self.pf.write_text(str(pid), encoding="utf-8")
        st = worker.read_pidfile_state(str(self.pf))
        self.assertEqual(st["state"], "live")
        self.assertEqual(st["pid"], pid)
        self.assertTrue(worker.pid_alive(pid))

    def test_guard_refuses_live_without_replace_and_names_it(self):
        pid = _spawn_sleeper()
        self.procs.append(pid)
        self.pf.write_text(str(pid), encoding="utf-8")
        msg = worker.guard_single_worker(str(self.pf))
        self.assertTrue(msg, "活 pid 未给 --replace：必须拒绝启动")
        for frag in (str(pid), str(self.pf), "--replace", "kill -TERM %d" % pid):
            self.assertIn(frag, msg, frag)
        self.assertTrue(_alive(pid), "拒绝路径不得对旧 worker 动手（只读判定）")

    def test_guard_takes_over_stale_and_malformed(self):
        log = StringIO()
        handler = logging.StreamHandler(log)
        root = logging.getLogger()
        old_level, old_handlers = root.level, list(root.handlers)
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            self.pf.write_text("999999", encoding="utf-8")
            self.assertIsNone(worker.guard_single_worker(str(self.pf)))
            self.assertIn("陈旧已接管", log.getvalue())
            log.truncate(0)
            log.seek(0)
            self.pf.write_text("not-a-pid", encoding="utf-8")
            self.assertIsNone(worker.guard_single_worker(str(self.pf)))
            self.assertIn("陈旧已接管", log.getvalue())
            log.truncate(0)
            log.seek(0)
            self.pf.unlink()
            self.assertIsNone(worker.guard_single_worker(str(self.pf)))
            self.assertIn("首启放行", log.getvalue())
        finally:
            root.handlers, root.level = old_handlers, old_level

    def test_guard_replace_stops_old_then_allows(self):
        pid = _spawn_sleeper()
        self.procs.append(pid)
        self.pf.write_text(str(pid), encoding="utf-8")
        self.assertIsNone(worker.guard_single_worker(str(self.pf), replace=True))
        self.assertTrue(_wait_dead(pid), "--replace 路径没有真停旧 worker")

    def test_guard_replace_refuses_foreign_repo_without_killing(self):
        pid = _spawn_sleeper()
        self.procs.append(pid)
        self.pf.write_text(str(pid), encoding="utf-8")
        Path(str(self.pf) + ".meta").write_text(
            '{"version": 2, "pid": %d, "repo_root": "/tmp/some-other-repo", "ts": %d}'
            % (pid, int(time.time())), encoding="utf-8")
        msg = worker.guard_single_worker(str(self.pf), replace=True)
        self.assertTrue(msg, "旁车指向他仓时 --replace 必须拒绝（不代杀他人进程）")
        self.assertIn("另一个仓", msg)
        self.assertIn("/tmp/some-other-repo", msg)
        self.assertTrue(_alive(pid), "拒绝路径不得杀掉他仓进程")

    def test_guard_replace_timeout_reports_and_never_kills(self):
        pid = _spawn_sleeper(ignore_term=True)
        self.procs.append(pid)
        self.pf.write_text(str(pid), encoding="utf-8")
        saved = worker.REPLACE_WAIT_SEC
        worker.REPLACE_WAIT_SEC = 0.6
        try:
            msg = worker.guard_single_worker(str(self.pf), replace=True)
        finally:
            worker.REPLACE_WAIT_SEC = saved
        self.assertTrue(msg, "超时路径必须报错（不放行）")
        self.assertIn(str(pid), msg)
        self.assertIn("不 KILL", msg)
        self.assertTrue(_alive(pid), "超时路径绝不许静默 KILL")
        _kill(pid)


class DaemonStartEndToEndTest(unittest.TestCase):
    """真起 `worker.py --daemon`：守卫与 pidfile 写入都在 Temporal 连接之前 ⇒ 无需台。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="worker-guard-e2e-"))
        self.pf = self.tmp / "worker.pid"
        self.lf = self.tmp / "worker.log"
        self.procs = []

    def tearDown(self):
        for pid in self.procs:
            _kill(pid)
        # daemon 子进程不在本进程树里：按 pidfile 兜底回收（本机 daemon 归 init 收养）
        st = worker.read_pidfile_state(str(self.pf))
        if st["state"] == "live":
            _kill(int(st["pid"]))
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_daemon(self, *extra):
        env = dict(os.environ)
        env["SANDBAR_TARGET_HOST"] = "127.0.0.1:1"   # 连不上就死：被测面在 connect 之前
        env.pop("SANDBAR_WORKER_META", None)
        return subprocess.run([sys.executable, WORKER_PY, "--daemon",
                               "--pidfile", str(self.pf), "--logfile", str(self.lf)] + list(extra),
                              capture_output=True, text=True, timeout=120, env=env)

    def test_live_pid_refuses_start_and_leaves_pidfile_untouched(self):
        old = _spawn_sleeper()
        self.procs.append(old)
        self.pf.write_text(str(old), encoding="utf-8")
        r = self._run_daemon()
        self.assertEqual(r.returncode, worker.WORKER_REFUSED_EXIT,
                         "活 pid 在场时必须非零退出（实得 %r）" % r.returncode)
        self.assertIn("拒绝启动", r.stderr)
        self.assertIn(str(old), r.stderr)
        self.assertIn(str(self.pf), r.stderr)
        self.assertEqual(self.pf.read_text(encoding="utf-8").strip(), str(old),
                         "拒绝路径不得改写 pidfile（第二颗不许偷槽）")
        self.assertTrue(_alive(old), "拒绝路径不得停旧 worker")
        self.assertFalse(self.lf.exists(), "拒绝路径不该产生任何后台日志（没 fork）")

    def test_stale_pidfile_starts_normally_and_takes_over(self):
        self.pf.write_text("999999", encoding="utf-8")
        r = self._run_daemon()
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertIn("陈旧已接管", r.stderr)          # warning 级：父进程 stderr 可见
        new = self.pf.read_text(encoding="utf-8").strip()
        self.assertNotEqual(new, "999999", "陈旧值未被接管（pidfile 未重写）")
        self.assertGreater(int(new), 0)
        self.procs.append(int(new))

    def test_replace_stops_old_then_starts(self):
        old = _spawn_sleeper()
        self.procs.append(old)
        self.pf.write_text(str(old), encoding="utf-8")
        r = self._run_daemon("--replace")
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertTrue(_wait_dead(old), "--replace 未真停旧 worker")
        new = self.pf.read_text(encoding="utf-8").strip()
        self.assertNotEqual(new, str(old), "pidfile 仍指向旧 pid（新进程没起）")
        self.assertGreater(int(new), 0)
        self.procs.append(int(new))


if __name__ == "__main__":
    unittest.main()
