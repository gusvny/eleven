#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_docker 租约语义专项 UT（t260910-12；与 test_stage_docker.py 分工：
彼=CLI 编排面 + 假 docker shim 全流程，本=租约原语/hold 七路终态/满员闸的
白盒电池——全部真进程/真 flock，零 docker 依赖）。

锁根纪律：本文件一律隔离锁根（SANDBAR_STAGE_LOCK_DIR → tempfile）——租约
原语测试会写垃圾租约文件，绝不能落生产共享状态面（~/.sandbar 降级根），
否则会干扰真台判活。flock 语义与锁根位置无关，隔离不影响互斥真实性。

覆盖面：
- 回收判据四象限（过期×holder 生死）+ 旧格式=死（R7）+ 畸形记录安全回收；
- lease_reusable 语义：复用必须心跳新鲜（过期+pid 活 = pid 复用族，不可复用）；
- write_lease 并发原子性（多线程写读无半文件）；
- holder pid 入口校验（空/0/负/非 int 拒收——记空=回到 R1）；
- 满员闸：占位即计数、并发不超售（真线程 flock 竞争）、超时红带
  holder pid+票号清单（R2 格式）、释放即入位；
- hold 七路终态：①release ②downing ③锚死 ③'起台孤儿 ④写失败语义面
  ⑤信号 ⑥超帽 + 预租约等待期锚死/起台者死自退；
- pid_alive 真进程两态自证（防恒真）。

跑法：python3 integration/tests/test_stage_lease.py（stdlib-only，秒级，无 docker）。
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INTEG = HERE.parent
STAGE = INTEG / "stage_docker.py"
sys.path.insert(0, str(INTEG))

import stage_docker as sd  # noqa: E402


class LeaseTestBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lease-ut-")
        self._saved = {k: os.environ.get(k) for k in (
            "SANDBAR_STAGE_LOCK_DIR", "SANDBAR_STAGE_HEARTBEAT_S",
            "SANDBAR_STAGE_LEASE_TTL_S", "SANDBAR_STAGE_MAX_STAGES",
            "SANDBAR_STAGE_MAX_HOLD_S", "SANDBAR_STAGE_HOLD_WAIT_S")}
        os.environ["SANDBAR_STAGE_LOCK_DIR"] = self.root
        sd._LOCK_ROOT_CACHE = None   # 隔离根生效（本进程内）

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sd._LOCK_ROOT_CACHE = None

    def put_lease(self, project, **over):
        lease = sd.new_lease(project, holder_pid=over.pop("holder_pid", os.getpid()),
                             services=over.pop("services", ["dsh"]), **over)
        lease.update(over)
        sd.write_lease(project, lease)
        return lease


class LeaseCriteriaTest(LeaseTestBase):
    def test_reclaim_quadrants(self):
        """回收判据唯一化：过期 AND holder 不存在 才死；其余三象限全活。"""
        alive = lambda pid: pid == 111          # noqa: E731 可注入探活
        fresh = sd.new_lease("p", holder_pid=111, services=[], ttl=90)
        self.assertFalse(sd.lease_dead(fresh, now=0, alive=alive))
        fresh_pid_dead = sd.new_lease("p", holder_pid=222, services=[], ttl=90)
        self.assertFalse(sd.lease_dead(fresh_pid_dead, now=0, alive=alive),
                         "心跳新鲜 + holder 死 → 活（判据是合取，不是或）")
        expired_alive = sd.new_lease("p", holder_pid=111, services=[], ttl=1)
        expired_alive["heartbeat_ts"] = 0
        self.assertFalse(sd.lease_dead(expired_alive, now=99, alive=alive),
                         "过期 + pid 活（复用族）→ 不回收（宁可占死档位）")
        expired_dead = sd.new_lease("p", holder_pid=222, services=[], ttl=1)
        expired_dead["heartbeat_ts"] = 0
        self.assertTrue(sd.lease_dead(expired_dead, now=99, alive=alive),
                        "过期 AND holder 不存在 → 唯一回收判据")

    def test_legacy_and_malformed_are_dead(self):
        """R7：旧格式（无 lease_id/heartbeat）= 过期死；畸形 JSON = 死且回收。"""
        legacy = {"project": "lg", "ports": {"console": 21001}, "ts": 1}
        self.assertTrue(sd.lease_dead(legacy))
        p = sd.lease_path("bad")
        p.write_text("{截断的 json...", encoding="utf-8")
        self.assertIsNone(sd.read_lease("bad"))
        live = sd.enumerate_leases()
        self.assertNotIn("bad", live)
        self.assertFalse(p.exists(), "畸形记录就地回收")

    def test_reusable_requires_fresh_heartbeat(self):
        """R3：复用主信号=up + 心跳新鲜 + holder 活。过期+pid 活=复用族，
        不可复用（下游诚实红），绝不静默续用。"""
        lease = sd.new_lease("p", holder_pid=os.getpid(), services=[], ttl=90)
        lease["state"] = "up"
        self.assertTrue(sd.lease_reusable(lease, now=lease["heartbeat_ts"] + 1))
        lease["heartbeat_ts"] = 0
        self.assertFalse(sd.lease_reusable(lease, now=99),
                         "过期 + pid 活 ≠ 可复用（疑似 pid 复用/僵死）")
        booting = sd.new_lease("p", holder_pid=os.getpid(), services=[], ttl=90)
        self.assertFalse(sd.lease_reusable(booting), "booting 态不可复用")

    def test_holder_pid_validation(self):
        for bad in (None, 0, -1, "3", 3.5, True, ""):
            with self.assertRaises(sd.StageError):
                sd.validate_holder_pid(bad), bad
        self.assertEqual(sd.validate_holder_pid(42), 42)

    def test_concurrent_lease_writes_never_torn(self):
        """原子写纪律：8 线程×40 次写同一租约，读者全程只见完整 JSON。"""
        sd.write_lease("rw", sd.new_lease("rw", holder_pid=os.getpid(),
                                          services=[], ttl=90))
        stop = {"flag": False}
        torn = {"n": 0}

        def reader():
            while not stop["flag"]:
                st = sd.read_lease("rw")
                if st is None:
                    torn["n"] += 1

        def writer(i):
            for j in range(40):
                lease = sd.read_lease("rw") or sd.new_lease(
                    "rw", holder_pid=os.getpid(), services=[], ttl=90)
                lease["heartbeat_ts"] = time.time()
                lease["seq"] = i * 1000 + j
                sd.write_lease("rw", lease)

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        ts = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for x in ts:
            x.start()
        for x in ts:
            x.join()
        stop["flag"] = True
        rt.join(timeout=2)
        self.assertEqual(torn["n"], 0, "并发写期间读者见到的半文件次数")

    def test_pid_alive_two_states(self):
        self.assertTrue(sd.pid_alive(os.getpid()), "自身必活（防恒假）")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertTrue(sd.pid_alive(child.pid))
        finally:
            child.kill()
            child.wait(timeout=10)
        deadline = time.time() + 5
        while time.time() < deadline and sd.pid_alive(child.pid):
            time.sleep(0.1)
        self.assertFalse(sd.pid_alive(child.pid), "被杀进程必判死（防恒真）")


class CapacityGateTest(LeaseTestBase):
    def test_placeholder_counts_and_release_admits(self):
        os.environ["SANDBAR_STAGE_MAX_STAGES"] = "1"
        first = sd.new_lease("cap1", holder_pid=os.getpid(), services=[], ttl=90)
        sd.capacity_acquire("cap1", first, timeout=2)   # 第一路占位
        self.assertTrue(sd.lease_path("cap1").exists())
        second = sd.new_lease("cap2", holder_pid=os.getpid(), services=[], ttl=90)
        with self.assertRaises(sd.StageError) as ctx:
            sd.capacity_acquire("cap2", second, timeout=1.5)
        self.assertIn("满员", str(ctx.exception))
        # 超时红带 R2 清单：holder pid + 票号 + lease_id + 起租时刻
        self.assertIn("pid=%d" % os.getpid(), str(ctx.exception))
        self.assertIn("cap1", str(ctx.exception))
        self.assertIn("lease=", str(ctx.exception))
        # 释放即入位：占位租约被回收后（cap1 过期死），cap2 立即可入
        sd.release_lease("cap1")
        sd.capacity_acquire("cap2", second, timeout=2)
        self.assertTrue(sd.lease_path("cap2").exists())

    def test_concurrent_claim_no_oversell(self):
        """R4：数+占位同一把全局锁——N 线程同抢容量 1 的闸，恰一个入位。"""
        os.environ["SANDBAR_STAGE_MAX_STAGES"] = "1"
        won, lost = {"n": 0}, {"n": 0}

        def entrant(i):
            lease = sd.new_lease("cap-x%d" % i, holder_pid=os.getpid(),
                                 services=[], ttl=90)
            try:
                sd.capacity_acquire("cap-x%d" % i, lease, timeout=1.0)
                won["n"] += 1
            except sd.StageError:
                lost["n"] += 1

        ts = [threading.Thread(target=entrant, args=(i,)) for i in range(6)]
        for x in ts:
            x.start()
        for x in ts:
            x.join()
        self.assertEqual(won["n"], 1, "容量 1 恰售 1（实得 %d）" % won["n"])
        self.assertEqual(lost["n"], 5, "落选者诚实排队超时红，绝不硬挤")


class HoldLegTest(LeaseTestBase):
    """hold 腿七路终态：真进程真锁根，PATH 剥离 docker（hold 的孤儿回收腿在
    UT 环境走「docker 不可用 → 释放租约交人工」分支，语义等价且零 docker）。"""

    def hold_env(self, **extra):
        e = {"PATH": "/usr/bin:/bin",   # 无 docker：hold 的 do_down 走诚实失败分支
             "SANDBAR_STAGE_LOCK_DIR": self.root,
             "SANDBAR_STAGE_HEARTBEAT_S": "0.3",
             "SANDBAR_STAGE_LEASE_TTL_S": "90"}
        e.update({k: str(v) for k, v in extra.items()})
        e.update({k: v for k, v in os.environ.items()
                  if k in ("SANDBAR_STAGE_HOLD_WAIT_S",)})
        return e

    def spawn_hold(self, project, anchor_pid, lease_id="lease-x", keep=False):
        argv = [sys.executable, str(STAGE), "hold", "--project", project,
                "--anchor-pid", str(anchor_pid), "--lease-id", lease_id]
        if keep:
            argv.append("--keep")
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=open(str(pathlib.Path(self.root, "hold-%s.log" % project)), "ab"),
            env=self.hold_env())
        pidfile = pathlib.Path(self.root, "holder-%s.pid" % project)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if int(pidfile.read_text().strip()) == proc.pid:
                    return proc
            except (OSError, ValueError):
                pass
            if proc.poll() is not None:
                self.fail("hold 启动即退 rc=%s" % proc.returncode)
            time.sleep(0.05)
        self.fail("hold pid 文件未就绪")

    def anchor_child(self):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    def read_lease(self, project):
        return json.loads(pathlib.Path(self.root, "project-%s.json" % project).read_text())

    def write_lease(self, project, lease):
        pathlib.Path(self.root, "project-%s.json" % project).write_text(
            json.dumps(lease), encoding="utf-8")

    def test_heartbeat_and_release_exit(self):
        """①正常收割：unlink 租约 → hold exit 0 且不补写（R6）。此前心跳在走。"""
        anchor = self.anchor_child()
        try:
            hold = self.spawn_hold("h1", anchor.pid)
            lease = sd.new_lease("h1", holder_pid=hold.pid, services=[], ttl=90,
                                 lease_id="lease-x")
            lease["state"] = "up"
            self.write_lease("h1", lease)
            hb0 = self.read_lease("h1")["heartbeat_ts"]
            time.sleep(1.2)
            hb1 = self.read_lease("h1")["heartbeat_ts"]
            self.assertGreater(hb1, hb0, "心跳必须推进（hold 腿=心跳宿主）")
            sd.release_lease("h1")   # down 的最后一步
            self.assertEqual(hold.wait(timeout=8), 0, "租约消失 → ① exit 0")
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_downing_state_exit_without_write(self):
        """②downing：读-校验-写前校验（R1'b）→ exit 0 且绝不把 downing 覆盖回 up。"""
        anchor = self.anchor_child()
        try:
            hold = self.spawn_hold("h2", anchor.pid)
            lease = sd.new_lease("h2", holder_pid=hold.pid, services=[], ttl=90,
                                 lease_id="lease-x")
            lease["state"] = "downing"
            self.write_lease("h2", lease)
            self.assertEqual(hold.wait(timeout=8), 0)
            self.assertEqual(self.read_lease("h2")["state"], "downing",
                             "hold 不得覆盖 downing（写前二次校验）")
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_keep_hold_survives_anchor_death(self):
        """③ keep 例外（arbitrate 打回修复）：常驻基建台（--keep，verify.yaml
        supply 语义「闸后有意常驻不拆」）的锚=短命调用方 shell——锚死≠弃台，
        hold 继续心跳守台；租约 keep 标随读改写透传；显式 down/⑥帽/⑦崩仍收口。
        对照 test_anchor_death_orphan_reclaim（非 keep 锚死=回收）。"""
        anchor = self.anchor_child()
        hold = None
        try:
            hold = self.spawn_hold("hk", anchor.pid, keep=True)
            lease = sd.new_lease("hk", holder_pid=hold.pid, services=[], ttl=90,
                                 lease_id="lease-x")
            lease["keep"] = True
            lease["state"] = "up"
            self.write_lease("hk", lease)
            time.sleep(0.8)
            hb0 = sd.read_lease("hk")["heartbeat_ts"]
            anchor.kill(); anchor.wait(timeout=10)
            time.sleep(1.5)   # ≥2 拍心跳：锚死窗内必须持续推进且不回收
            self.assertTrue(hold.poll() is None, "keep hold 锚死后必须存活守台")
            lease2 = sd.read_lease("hk")
            self.assertIsNotNone(lease2, "keep 台租约必须还在（不被锚死回收）")
            self.assertEqual(lease2.get("state"), "up", "keep 台不因锚死降态")
            self.assertGreater(lease2["heartbeat_ts"], hb0, "keep hold 心跳持续推进")
            self.assertTrue(lease2.get("keep"), "keep 标随心跳读改写透传")
        finally:
            if hold is not None and hold.poll() is None:
                hold.terminate(); hold.wait(timeout=10)   # ⑤：down 收割同款
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_anchor_death_orphan_reclaim(self):
        """③锚死：调用方树消失 → 回收孤儿台（UT 无 docker → 释放租约交人工）
        + exit 0。验收②「持有者被杀→回收且不影响他人」的加速腿。"""
        anchor = self.anchor_child()
        try:
            hold = self.spawn_hold("h3", anchor.pid)
            lease = sd.new_lease("h3", holder_pid=hold.pid, services=[], ttl=90,
                                 lease_id="lease-x")
            lease["state"] = "up"
            self.write_lease("h3", lease)
            time.sleep(0.8)   # 至少一拍心跳，证明确实在持有
            anchor.kill(); anchor.wait(timeout=10)
            self.assertEqual(hold.wait(timeout=10), 0, "锚死 → exit 0")
            self.assertFalse(sd.lease_path("h3").exists(), "孤儿台租约必须释放")
            log = pathlib.Path(self.root, "hold-h3.log").read_text()
            self.assertIn("锚", log, "回收动作留痕（hold-h3.log）")
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_max_hold_cap_exit(self):
        """⑥超帽：锚 pid 复用误活的损害上限——超 MAX_HOLD_S 诚实自退（rc 6）
        + stderr 留痕（含 C2 提示），台交判死回收，绝不静默续命。"""
        anchor = self.anchor_child()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(STAGE), "hold", "--project", "h4",
                 "--anchor-pid", str(anchor.pid), "--lease-id", "lease-x"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=self.hold_env(SANDBAR_STAGE_MAX_HOLD_S="0.5"))
            pidfile = pathlib.Path(self.root, "holder-h4.pid")
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    if int(pidfile.read_text().strip()) == proc.pid:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            lease = sd.new_lease("h4", holder_pid=proc.pid, services=[], ttl=90,
                                  lease_id="lease-x")
            lease["state"] = "up"
            self.write_lease("h4", lease)
            rc = proc.wait(timeout=15)
            self.assertEqual(rc, 6, "超帽自退 rc=6")
            log = proc.stderr.read().decode("utf-8", "replace")
            self.assertIn("STAGE_HOLD_CAP", log)
            self.assertIn("SANDBAR_STAGE_MAX_HOLD_S", log, "C2：留痕点名调小 env/显式 down")
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_signal_exit_130(self):
        """⑤SIGTERM：exit 130、不拆台（拆台责任在调用方/down 收割）。"""
        anchor = self.anchor_child()
        try:
            hold = self.spawn_hold("h5", anchor.pid)
            lease = sd.new_lease("h5", holder_pid=hold.pid, services=[], ttl=90,
                                 lease_id="lease-x")
            lease["state"] = "up"
            self.write_lease("h5", lease)
            time.sleep(0.5)
            hold.send_signal(signal.SIGTERM)
            self.assertEqual(hold.wait(timeout=8), 130)
            self.assertTrue(sd.lease_path("h5").exists(), "信号退出不拆台不释放")
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_pre_lease_anchor_death_silent_exit(self):
        """预租约期锚死：租约未落、无可清理 → 静默 exit 0，绝不为死树起租。"""
        anchor = self.anchor_child()
        try:
            hold = self.spawn_hold("h6", anchor.pid)
            time.sleep(0.3)
            anchor.kill(); anchor.wait(timeout=10)
            self.assertEqual(hold.wait(timeout=8), 0)
            self.assertFalse(sd.lease_path("h6").exists())
        finally:
            try:
                anchor.kill(); anchor.wait(timeout=10)
            except (ProcessLookupError, OSError):
                pass

    def test_pre_lease_booter_death_bounded_exit(self):
        """预租约期起台者死（hold 的原始父进程）：有界自退 rc≠0 留痕——起台
        失败零泄漏悬挂 hold（R1'a）。经中间进程拉起后即死来构造。"""
        spawner = textwrap.dedent("""
            import os, subprocess, sys
            proc = subprocess.Popen(
                [sys.executable, %r, "hold", "--project", "h7",
                 "--anchor-pid", str(os.getpid()), "--lease-id", "lease-x"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            print(proc.pid)
        """) % str(STAGE)
        inter = subprocess.Popen([sys.executable, "-c", spawner],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env=self.hold_env())
        hold_pid = int(inter.stdout.read().split()[0])
        inter.wait(timeout=10)   # 中间进程（=起台者）即死，hold 被 detach 存活
        hold = subprocess.Popen(["true"])   # 占位对象无实义，直接轮询 pid 文件/进程
        del hold
        deadline = time.time() + 15
        exited = False
        while time.time() < deadline:
            try:
                os.kill(hold_pid, 0)
            except ProcessLookupError:
                exited = True
                break
            time.sleep(0.2)
        self.assertTrue(exited, "起台者死后 hold 必有界自退（不悬挂）")
        self.assertFalse(sd.lease_path("h7").exists(), "自退路径绝不起租")

    def test_booting_orphan_reclaim(self):
        """③'起台孤儿：租约 booting + 起台者死 → 起台永不可完成 → 回收+释放。
        无此腿则死起台者的 booting 租约被人 hold 无限心跳，等待者永远等。"""
        spawner = textwrap.dedent("""
            import json, os, pathlib, subprocess, sys, time
            root = %r
            proc = subprocess.Popen(
                [sys.executable, %r, "hold", "--project", "h8",
                 "--anchor-pid", str(%d), "--lease-id", "lease-x"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=open(root + "/hold-h8.log", "ab"),
                start_new_session=True, env=dict(os.environ))
            pidfile = pathlib.Path(root, "holder-h8.pid")
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    if int(pidfile.read_text().strip()) == proc.pid:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            now = time.time()
            lease = {"lease_id": "lease-x", "project": "h8",
                     "holder": {"ticket": "t", "pid": proc.pid},
                     "anchor_pid": %d, "state": "booting", "services": [],
                     "ports": {}, "ts": now, "heartbeat_ts": now, "ttl_sec": 90}
            pathlib.Path(root, "project-h8.json").write_text(json.dumps(lease))
            print(proc.pid)
        """) % (self.root, str(STAGE), os.getppid(), os.getpid())
        inter = subprocess.Popen([sys.executable, "-c", spawner],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env=self.hold_env())
        hold_pid = int(inter.stdout.read().split()[0])
        inter.wait(timeout=10)   # 起台者交租约后即死 = 起台孤儿形态
        deadline = time.time() + 15
        released = False
        while time.time() < deadline:
            if not sd.lease_path("h8").exists():
                released = True
                break
            time.sleep(0.2)
        self.assertTrue(released, "起台孤儿的租约必须被 hold 回收释放")
        log = pathlib.Path(self.root, "hold-h8.log").read_text()
        self.assertIn("起台孤儿", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
