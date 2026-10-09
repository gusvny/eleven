#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_docker 工作对端争用等待 UT（t261008-46；与 test_stage_docker.py /
test_stage_lease.py 分工：彼=CLI 编排面/租约原语，本=两个「等工作对端」窗口
的两层上界——ensure 互斥 flock 与 booting 翻面等待。全部真进程/真 flock，
零 docker 依赖，秒级）。

背景（工单原文）：供给台 ensure 互斥预算 120s 被真实起台例常打穿 → 闸零执行
靠手工重试。修法=两层上界：对端有进度（心跳新鲜+持有者活）允许等到工作对端
上限（SANDBAR_STAGE_WORKING_PEER_CEILING_S，缺省 660s=对方健康窗 600s+宽限）；
无进度（心跳停更/持有者亡）仍按基础预算（SANDBAR_STAGE_WAIT_BUDGET_S 缺省
120s）快速诚实红。守卫面：
- A0 无争用路径不变（立得锁，旋钮零代价）；
- A1 预租约窗（持锁者活但租约未写）→ 骑到上限才红，红文案点名上限旋钮；
- A2 工作对端按时交付 → 不红，等待者拿锁继续；
- B1 booting 有进度骑满基础预算后翻面 → 复用不红；
- B2 无进度两态（心跳停更 / 心跳新鲜但持有者亡）→ 基础预算快速红，文案点名
  基础预算旋钮（报错精确纪律：命中哪条界文案就点名哪条）；
- B3 上限旋钮畸形（非数/≤0）→ 回退缺省不崩；
- B4 平窗不漏：daemon 探针等基础预算窗不受上限旋钮影响（cap 纯函数 +
  wait_budget_s 与上限旋钮正交）。

跑法：python3 integration/tests/test_stage_mutex_wait.py（stdlib-only，秒级）。
"""
import fcntl
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INTEG = HERE.parent
sys.path.insert(0, str(INTEG))

import stage_docker as sd  # noqa: E402

BASE_S = "2"      # 基础预算旋钮注入值（秒）
CEIL_S = "5"      # 工作对端上限旋钮注入值（秒）


class _IsolatedRootCase(unittest.TestCase):
    """每个用例独立锁根 + 注入小旋钮（环境变量在调用点即时读取）。"""

    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="t26100846-mutex-")
        self._old = {}
        for k, v in (("SANDBAR_STAGE_LOCK_DIR", self._root),
                     ("SANDBAR_STAGE_WAIT_BUDGET_S", BASE_S),
                     ("SANDBAR_STAGE_WORKING_PEER_CEILING_S", CEIL_S)):
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        self._old_cache = sd._LOCK_ROOT_CACHE
        sd._LOCK_ROOT_CACHE = None   # 隔离锁根必须生效：清全局缓存（白盒，同 test_stage_lease 纪律）
        self._children = []

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sd._LOCK_ROOT_CACHE = self._old_cache
        for p in self._children:
            p.kill()
            p.wait()
        shutil.rmtree(self._root, ignore_errors=True)

    # -- fixtures ----------------------------------------------------------
    def sleeper(self, secs=30):
        p = subprocess.Popen([sys.executable, "-c",
                              "import time;time.sleep(%d)" % secs])
        self._children.append(p)
        return p

    def holder_child(self, lock_name, hold_s):
        """真 flock 持有者子进程：确认「已持锁」后再返回（Popen 后台持有，
        hold_s 秒后自然退出=对端按时交付；到点不退出由 tearDown kill 回收）。"""
        path = os.path.join(self._root, lock_name)
        p = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent("""
                import fcntl, os, sys, time
                fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                print("held", flush=True)
                time.sleep(float(sys.argv[2]))
            """), path, str(hold_s)],
            stdout=subprocess.PIPE, text=True)
        self._children.append(p)
        line = p.stdout.readline().strip()
        self.assertEqual(line, "held",
                         "持锁者子进程未确认上锁（fixture 失效，宁红不假绿）")
        return p

    def working_holder_child(self, lock_name, project, hold_s):
        """工作对端子进程：持锁 + 写 booting 租约 + 周期续跳心跳（0.5s）——
        「观察到的进度」fixture（verify gen3 语义：进度=签名变化，非静态新鲜）。"""
        path = os.path.join(self._root, lock_name)
        p = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent("""
                import fcntl, os, sys, time
                sys.path.insert(0, sys.argv[3])
                os.environ["SANDBAR_STAGE_LOCK_DIR"] = sys.argv[4]
                import stage_docker as sd
                fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                lease = sd.new_lease(sys.argv[2], os.getpid(), ["temporal"])
                sd.write_lease(sys.argv[2], lease)
                print("held", flush=True)
                end = time.time() + float(sys.argv[5])
                while time.time() < end:
                    time.sleep(0.5)
                    lease = sd.read_lease(sys.argv[2])
                    if not isinstance(lease, dict):
                        break
                    lease["heartbeat_ts"] = time.time()
                    sd.write_lease(sys.argv[2], lease)
            """), path, project, str(INTEG), self._root, str(hold_s)],
            stdout=subprocess.PIPE, text=True)
        self._children.append(p)
        self.addCleanup(self._cleanup_working_holder, p, project)
        line = p.stdout.readline().strip()
        self.assertEqual(line, "held",
                         "工作对端子进程未确认持锁+写租约（fixture 失效，宁红不假绿）")
        return p

    def _cleanup_working_holder(self, p, project):
        if p.poll() is None:
            p.kill()
            p.wait()
        sd.release_lease(project)

    def own_lock(self, project):
        """测试进程自己先持住 ensure 互斥锁（_wait_booting 的进出场约定）。"""
        fd = os.open(str(pathlib.Path(self._root) /
                         ("ensure-%s.lock" % project)),
                     os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)
        return fd

    def booting_lease(self, project, pid, fresh=True, holder_alive=True):
        lease = sd.new_lease(project, pid, ["temporal"])
        if not fresh:
            lease["heartbeat_ts"] = time.time() - 999
        if not holder_alive:
            lease["holder"]["pid"] = 2**22   # 不存在的 pid（macOS/Linux 均不占用）
        sd.write_lease(project, lease)
        return lease


class EnsureMutexFlockWindowTest(_IsolatedRootCase):
    """A0/A1/A2：ensure-<project>.lock 获取窗的两层上界。"""

    def test_a0_uncontended_acquires_immediately(self):
        fd = os.open(os.path.join(self._root, "ensure-t26100846-a0.lock"),
                     os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        t0 = time.time()
        sd._wait_ensure_mutex("t26100846-a0", fd, timeout=600)
        self.assertLess(time.time() - t0, 1.0,
                        "无争用路径必须立得锁（旋钮零代价回归锚）")

    def test_a1_renewing_holder_rides_to_ceiling_then_named_red(self):
        proj = "t26100846-a1"
        fd = os.open(os.path.join(self._root, "ensure-%s.lock" % proj),
                     os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        self.sleeper(1)   # 占住 wait 预算面无关；真持锁者（写租约+续跳）：
        self.working_holder_child("ensure-%s.lock" % proj, proj, hold_s=20)
        t0 = time.time()
        with self.assertRaises(sd.StageError) as cm:
            sd._wait_ensure_mutex(proj, fd, timeout=600)
        wall = time.time() - t0
        self.assertEqual(cm.exception.kind, "env", "诚实环境红，非 usage/assertion")
        self.assertIn("工作对端上限", str(cm.exception))
        self.assertIn(sd.WORKING_PEER_CEILING_ENV, str(cm.exception),
                      "红文案必须点名命中的界（报错精确纪律）")
        self.assertGreaterEqual(wall, 4.0, "必须骑过 120s 基础预算语义（此处注入 2s）")
        self.assertLessEqual(wall, 10.0, "上限仍是有界红，不硬等")

    def test_a1b_bare_lock_holder_bails_fast_at_base(self):
        """t260920-01 旧契约回归锚：持锁者无租约（无进度）→ 基础预算诚实红，
        文案保留「ensure 互斥等待超时…等待预算」守卫短语（verify gen3）。"""
        proj = "t26100846-a1b"
        fd = os.open(os.path.join(self._root, "ensure-%s.lock" % proj),
                     os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        self.holder_child("ensure-%s.lock" % proj, hold_s=20)
        t0 = time.time()
        with self.assertRaises(sd.StageError) as cm:
            sd._wait_ensure_mutex(proj, fd, timeout=600)
        wall = time.time() - t0
        self.assertEqual(cm.exception.kind, "env")
        msg = str(cm.exception)
        self.assertIn("ensure 互斥等待超时", msg, "旧契约守卫短语必须保留")
        self.assertIn("等待预算", msg)
        self.assertIn("SANDBAR_STAGE_WAIT_BUDGET_S", msg,
                      "基础预算红必须点名基础预算旋钮（与上限红可辨）")
        self.assertGreaterEqual(wall, 1.5)
        self.assertLess(wall, 4.5, "无进度必须快速红（不硬等上限）")

    def test_a2_working_holder_delivers_no_red(self):
        proj = "t26100846-a2"
        fd = os.open(os.path.join(self._root, "ensure-%s.lock" % proj),
                     os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        self.working_holder_child("ensure-%s.lock" % proj, proj, hold_s=3)
        t0 = time.time()
        sd._wait_ensure_mutex(proj, fd, timeout=600)   # 对端 3s 后释放=按时交付
        wall = time.time() - t0
        self.assertGreaterEqual(wall, 2.0, "确实等过基础预算窗（原语义这里已红）")
        self.assertLess(wall, 10.0, "对端交付后立即拿锁")

    def test_caller_timeout_still_authoritative(self):
        proj = "t26100846-a3"
        fd = os.open(os.path.join(self._root, "ensure-%s.lock" % proj),
                     os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        self.holder_child("ensure-%s.lock" % proj, hold_s=20)
        t0 = time.time()
        with self.assertRaises(sd.StageError):
            sd._wait_ensure_mutex(proj, fd, timeout=1.0)
        self.assertLess(time.time() - t0, 4.0,
                        "调用方自己的 timeout 恒是权威上界（min 语义）")


class BootingWaitWindowTest(_IsolatedRootCase):
    """B1/B2：state=booting 翻面等待窗的两层上界。"""

    def test_b1_renewing_booting_rides_past_base_then_reuses(self):
        proj = "t26100846-b1"
        pid = self.sleeper().pid
        self.booting_lease(proj, pid, fresh=True)
        fd = self.own_lock(proj)
        deadline = time.time() + 600
        stop = threading.Event()

        def renew_then_flip():
            # 进度 fixture：hold 分支式周期续跳（0.5s），3.5s 后翻 up
            while not stop.is_set() and time.time() - t0 < 3.5:
                time.sleep(0.5)
                lease = sd.read_lease(proj)
                if not isinstance(lease, dict):
                    return
                lease["heartbeat_ts"] = time.time()
                sd.write_lease(proj, lease)
            lease = sd.read_lease(proj)
            if isinstance(lease, dict):
                lease["state"] = "up"
                lease["heartbeat_ts"] = time.time()
                sd.write_lease(proj, lease)

        t0 = time.time()
        t = threading.Thread(target=renew_then_flip)
        t.start()
        self.addCleanup(t.join, 10)
        self.addCleanup(stop.set)
        st = sd._wait_booting(proj, fd, deadline)
        wall = time.time() - t0
        self.assertEqual(st.get("state"), "up", "翻面后返回新租约（复用面）")
        self.assertGreaterEqual(wall, 3.0,
                                "必须骑过基础预算（2s）——原语义这里已诚实红")

    def test_b2a_stale_heartbeat_bails_fast_at_base(self):
        proj = "t26100846-b2a"
        pid = self.sleeper().pid
        self.booting_lease(proj, pid, fresh=False, holder_alive=True)
        fd = self.own_lock(proj)
        t0 = time.time()
        with self.assertRaises(sd.StageError) as cm:
            sd._wait_booting(proj, fd, deadline=time.time() + 600)
        wall = time.time() - t0
        self.assertEqual(cm.exception.kind, "env")
        self.assertIn("超预算", str(cm.exception))
        self.assertIn("SANDBAR_STAGE_WAIT_BUDGET_S", str(cm.exception),
                      "基础预算红必须点名基础预算旋钮（与上限红可辨）")
        self.assertLess(wall, 4.5, "无进度必须快速红（不骑尸体）")

    def test_b2b_fresh_heartbeat_dead_holder_bails_fast_at_base(self):
        proj = "t26100846-b2b"
        self.booting_lease(proj, pid=2**22, fresh=True, holder_alive=False)
        fd = self.own_lock(proj)
        t0 = time.time()
        with self.assertRaises(sd.StageError) as cm:
            sd._wait_booting(proj, fd, deadline=time.time() + 600)
        self.assertLess(time.time() - t0, 4.5)
        self.assertIn("超预算", str(cm.exception))

    def test_b2c_lease_vanishes_returns_for_caller_verdict(self):
        proj = "t26100846-b2c"
        pid = self.sleeper().pid
        self.booting_lease(proj, pid, fresh=True)
        sd.release_lease(proj)
        fd = self.own_lock(proj)
        st = sd._wait_booting(proj, fd, deadline=time.time() + 600)
        self.assertIsNone(st, "租约消失=立即返回，交调用方回锁终判（原语义保持）")


class KnobAndFlatWindowTest(_IsolatedRootCase):
    """B3/B4：旋钮畸形回退 + 平窗与上限旋钮正交。"""

    def test_b3_malformed_ceiling_falls_back_to_default(self):
        self.sleeper(1)
        for bad in ("abc", "", "0", "-3"):
            os.environ[sd.WORKING_PEER_CEILING_ENV] = bad
            self.assertEqual(sd.working_peer_ceiling_s(),
                             sd.DEFAULT_WORKING_PEER_CEILING_S,
                             "畸形值 %r 必须回退缺省（不崩不静默零）" % bad)

    def test_b4_daemon_budget_orthogonal_to_ceiling(self):
        self.sleeper(1)
        os.environ[sd.WORKING_PEER_CEILING_ENV] = "5000"
        self.assertEqual(sd.wait_budget_s(), float(BASE_S),
                         "基础预算窗（daemon 探针等）不受上限旋钮影响")
        self.assertEqual(sd.contention_wait_cap(10**6),
                         max(float(BASE_S), 5000.0),
                         "工作对端窗 cap = min(timeout, max(base, ceiling))")
        self.assertEqual(sd.contention_wait_cap(3.0), 3.0,
                         "调用方 timeout 恒是权威上界")
        self.assertTrue(sd.booting_progressing({"state": "booting"}) is False,
                        "畸形租约=无进度（fail-closed）")


if __name__ == "__main__":
    unittest.main()

    def test_b2d_static_fresh_lease_is_not_progress(self):
        """verify gen3 契约锚：一次性写入、从未续跳的新鲜 booting 租约=无进度
        （进度=观察到的签名变化，非静态新鲜）→ 基础预算诚实红。"""
        proj = "t26100846-b2d"
        pid = self.sleeper().pid
        self.booting_lease(proj, pid, fresh=True, holder_alive=True)
        fd = self.own_lock(proj)
        t0 = time.time()
        with self.assertRaises(sd.StageError) as cm:
            sd._wait_booting(proj, fd, deadline=time.time() + 600)
        wall = time.time() - t0
        self.assertEqual(cm.exception.kind, "env")
        self.assertIn("booting 等待超预算", str(cm.exception),
                      "t260920-01 旧契约守卫短语必须保留")
        self.assertIn("不硬等也不并发再起", str(cm.exception))
        self.assertLess(wall, 4.5, "无进度必须快速红（不硬等上限）")
