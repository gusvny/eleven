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
import errno
import fcntl
import json
import os
import pathlib
import shutil
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
REPO = INTEG.parent
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
    """起台保险丝（t260912-02 语义迁移：满员排队闸退役，原子不超售/占位即计数/
    释放准入三条性质保留，仅「满员」断言换成保险丝断言——票面授权的语义变更）。"""

    def test_placeholder_counts_and_release_admits(self):
        os.environ["SANDBAR_STAGE_MAX_STAGES"] = "1"
        first = sd.new_lease("cap1", holder_pid=os.getpid(), services=[], ttl=90)
        sd.capacity_acquire("cap1", first, timeout=2)   # 第一路占位
        self.assertTrue(sd.lease_path("cap1").exists())
        second = sd.new_lease("cap2", holder_pid=os.getpid(), services=[], ttl=90)
        with self.assertRaises(sd.StageError) as ctx:
            sd.capacity_acquire("cap2", second, timeout=1.5)
        msg = str(ctx.exception)
        self.assertIn("起台保险丝", msg)
        # 刹停红必须点名 env 上限与缺省差异 + R2 清单（holder pid+票号+lease_id）
        self.assertIn("SANDBAR_STAGE_MAX_STAGES=1", msg)
        self.assertIn("pid=%d" % os.getpid(), msg)
        self.assertIn("cap1", msg)
        self.assertIn("lease=", msg)
        # 负锁（防恒真）：新红文案不含「满员」——瞬态白名单按字样自动重试，
        # 失控循环的红不得被重试放大（review C1/C7）。
        self.assertNotIn("满员", msg)
        # 释放即入位：占位租约被回收后（cap1 过期死），cap2 立即可入
        sd.release_lease("cap1")
        sd.capacity_acquire("cap2", second, timeout=2)
        self.assertTrue(sd.lease_path("cap2").exists())

    def test_concurrent_claim_no_oversell(self):
        """R4：数+占位同一把全局锁——N 线程同抢额度 1，恰一个入位。"""
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
        self.assertEqual(won["n"], 1, "额度 1 恰售 1（实得 %d）" % won["n"])
        self.assertEqual(lost["n"], 5, "落选者立即刹停红，绝不硬挤")

    def test_fuse_default_is_100(self):
        """C7：缺省保险丝=100（L1 显式断言，防回落到旧值 12 或被误改）。"""
        saved = os.environ.pop("SANDBAR_STAGE_MAX_STAGES", None)
        try:
            self.assertEqual(sd.max_stages(), 100)
        finally:
            if saved is not None:
                os.environ["SANDBAR_STAGE_MAX_STAGES"] = saved

    def test_fuse_not_tripped_below_limit(self):
        """负锁（防恒真）：少量在册租约（3<缺省 100）不触闸——保险丝只在失控
        循环刹停，正常负载（含 32 台爆发+常驻台）永不触及。"""
        for i in range(3):
            lease = sd.new_lease("neg%d" % i, holder_pid=os.getpid(), services=[], ttl=90)
            sd.capacity_acquire("neg%d" % i, lease, timeout=2)
        self.assertTrue(sd.lease_path("neg2").exists())

    def test_lock_acquire_bounded_wait_kept(self):
        """C5：锁获取的有界等待不得随排队循环一起退役——capacity-0.lock 被
        长期持有时，等满预算=诚实红（不是裸阻塞 flock 永久挂起）。"""
        os.environ["SANDBAR_STAGE_MAX_STAGES"] = "100"
        lock_path = sd.lock_root() / "capacity-0.lock"
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)          # 外部持锁不放手
        try:
            lease = sd.new_lease("cap-locked", holder_pid=os.getpid(), services=[], ttl=90)
            t0 = time.time()
            with self.assertRaises(sd.StageError) as ctx:
                sd.capacity_acquire("cap-locked", lease, timeout=0.5)
            self.assertLess(time.time() - t0, 5, "有界等待必须到期即红")
            self.assertIn("锁等待超时", str(ctx.exception))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class SweepJudgeTest(LeaseTestBase):
    """残台清扫判据矩阵（t260912-02）：三判据拆 / 两阀不碰 / C4b 仅报告 /
    畸形保守 / worktree 不可得 fail-closed——全参注入，防恒真负锁齐备。"""

    def setUp(self):
        super().setUp()
        # 注入用 worktree 集：只含隔离根自身（真实仓根不在其中，判定全本地化）
        self.worktree = {os.path.realpath(self.root)}

    def mk(self, project="p", state="up", hb_age=1, holder=os.getpid(),
           owner="__unset__", anchorless=False):
        now = time.time()
        lease = sd.new_lease(project, holder_pid=holder, services=[], ttl=90)
        lease["state"] = state
        lease["heartbeat_ts"] = now - hb_age
        if anchorless:
            del lease["owner_root"]           # 旧格式：连 repo_dir 也无
        elif owner != "__unset__":
            lease["owner_root"] = owner
        return lease

    def test_crit_shapes_condemned(self):
        deleted = os.path.join(self.root, "doomed")
        os.makedirs(deleted)
        shutil.rmtree(deleted)                # 先删后判：crit_i 的前提是目录已不在
        v, why = sd.judge_residue(self.mk(owner=deleted), worktree_roots=self.worktree)
        self.assertEqual("condemn", v, why)
        self.assertTrue(why.startswith("crit_i"), why)
        # (ii) 非工作树锚（目录在）+ holder 死
        nonwt = os.path.join(self.root, "nonwt"); os.makedirs(nonwt)
        v, why = sd.judge_residue(self.mk(holder=999999, owner=nonwt),
                                  worktree_roots=self.worktree)
        self.assertEqual("condemn", v, why)
        self.assertTrue(why.startswith("crit_ii"), why)
        shutil.rmtree(nonwt)
        # (iii) 心跳陈旧超阈（holder 死；holder 活也不翻案——PID 只作辅证）。
        # 锚必须无：锚在而 worktree 集不含它时 crit_ii 抢先命中，测不到 crit_iii。
        v, why = sd.judge_residue(self.mk(hb_age=6000, holder=999999,
                                          anchorless=True),
                                  worktree_roots=self.worktree)
        self.assertEqual("condemn", v, why)
        self.assertTrue(why.startswith("crit_iii"), why)

    def test_valves_keep_healthy(self):
        """阀1 阀2 + 负锁：健康台恒 keep——谓词对健康输入永远不判拆（防恒真）。"""
        lane = os.path.join(self.root, "lane"); os.makedirs(lane)
        wt = {os.path.realpath(lane)}
        v, why = sd.judge_residue(self.mk(state="booting", owner=lane), worktree_roots=wt)
        self.assertEqual("keep", v, "阀1：%s" % why)
        v, why = sd.judge_residue(self.mk(owner=lane), worktree_roots=wt)
        self.assertEqual("keep", v, "阀2：%s" % why)

    def test_c4b_live_owner_dir_nonworktree_report_only(self):
        """C4b 负锁：活台（up+心跳新鲜+holder 活）+ owner 目录在 + 非工作树 →
        不拆（repo_dir 回落失真面，只允许 report 留行）——防误拆别泳道供给台。"""
        d = os.path.join(self.root, "tmp-tree"); os.makedirs(d)
        v, why = sd.judge_residue(self.mk(owner=d), worktree_roots=self.worktree)
        self.assertEqual("report", v, why)
        shutil.rmtree(d)

    def test_git_unavailable_fail_closed(self):
        """worktree list 不可得（None）：crit_ii 跳过，余判据照判（stale 仍拆）。"""
        d = os.path.join(self.root, "nowt"); os.makedirs(d)
        v, _ = sd.judge_residue(self.mk(hb_age=6000, holder=999999, owner=d),
                                worktree_roots=None)
        self.assertEqual(v, "condemn", "crit_iii 不受 git 缺席影响")
        v, why = sd.judge_residue(self.mk(holder=999999, owner=d), worktree_roots=None)
        self.assertEqual(v, "keep", "crit_ii 在 git 缺席时 fail-closed（%s）" % why)
        shutil.rmtree(d)

    def test_malformed_and_anchor_precedence(self):
        """畸形/无锚保守 + 锚优先级：非租约记录 keep；无任何锚的新鲜活台 keep；
        owner_root 优先于 repo_dir（新字段权威）。"""
        v, _ = sd.judge_residue({"project": "x", "ts": 1}, worktree_roots=set())
        self.assertEqual(v, "keep")
        v, why = sd.judge_residue(self.mk(anchorless=True), worktree_roots=set())
        self.assertEqual(v, "keep", "无锚活台保守不拆（%s）" % why)
        d = os.path.join(self.root, "anchor-x"); os.makedirs(d)
        lease = self.mk(owner=d)
        lease["repo_dir"] = str(REPO)         # 回落值指向真仓根（在 worktree 集）
        v, why = sd.judge_residue(lease, worktree_roots={os.path.realpath(REPO)})
        self.assertEqual(v, "report", "锚取 owner_root（非工作树）而非 repo_dir：%s" % why)
        shutil.rmtree(d)

    def test_sweep_full_cycle_tears_down_and_releases(self):
        """sweep_stages 全链（真锁根真租约，docker 腿注入为 no-op）：判拆项走
        teardown 并逐条点名；保留/报告项租约原地不动；dry_run 不落任何动作。"""
        deleted = os.path.join(self.root, "gone-lane")
        sd.write_lease("res1", self.mk("res1", owner=deleted))   # 目录从未存在=crit_i
        sd.write_lease("ok1", self.mk("ok1"))

        def teardown(proj):                   # 桩模仿真 do_down 完整终态：拆面+释放
            sd.release_lease(proj)
            return {"residue": []}
        rpt = sd.sweep_stages(worktree_roots=self.worktree, do_down_fn=teardown)
        self.assertIn("res1", [c["project"] for c in rpt["condemned"]])
        self.assertNotIn("ok1", [c["project"] for c in rpt["condemned"]])
        self.assertNotIn("ok1", [e["project"] for e in rpt["errors"]])
        self.assertFalse(sd.lease_path("res1").exists(), "判拆项租约一并释放")
        self.assertTrue(sd.lease_path("ok1").exists(), "保留/报告项租约原封不动")
        # dry_run：判拆但不落任何动作
        sd.write_lease("res2", self.mk("res2",
                                       owner=os.path.join(self.root, "never-was")))
        rpt2 = sd.sweep_stages(dry_run=True, worktree_roots=self.worktree,
                               do_down_fn=teardown)
        hit = [c for c in rpt2["condemned"] if c["project"] == "res2"]
        self.assertTrue(hit and hit[0].get("dry_run"))
        self.assertTrue(sd.lease_path("res2").exists(), "dry-run 不拆不释放")

    def test_working_dir_probe_upgrades_legacy(self):
        """旧格式租约（无 owner_root，repo_dir 回落到存在的 tmp 树）+ working_dir
        探针：真工作目录已删 → crit_i 补刀判拆（260912 存量残台主路径）；仍在 →
        fail-closed 只报告。"""
        d = os.path.join(self.root, "tmp-tree"); os.makedirs(d)
        legacy = self.mk("legacy", anchorless=True)
        legacy["repo_dir"] = d
        sd.write_lease("legacy", legacy)
        noop = lambda proj: {"residue": []}  # noqa: E731
        dead_lane = os.path.join(self.root, "dead-lane")
        rpt = sd.sweep_stages(owner_probe=lambda p: dead_lane,
                              worktree_roots=self.worktree, do_down_fn=noop)
        hit = [c for c in rpt["condemned"] if c["project"] == "legacy"]
        self.assertTrue(hit and "crit_i" in hit[0]["why"], rpt)
        alive_lane = os.path.join(self.root, "alive-lane"); os.makedirs(alive_lane)
        sd.write_lease("legacy2", dict(legacy, project="legacy2"))
        rpt2 = sd.sweep_stages(owner_probe=lambda p: alive_lane,
                               worktree_roots=self.worktree, do_down_fn=noop)
        self.assertIn("legacy2", [c["project"] for c in rpt2["report_only"]], rpt2)
        self.assertTrue(sd.lease_path("legacy2").exists())


class NetAllocTest(LeaseTestBase):
    """受管网段分配（t260912-02 病灶三）：表内/随机不序列/排除在册与 daemon/
    保留槽排除/畸形 base 拒收/表耗尽红——daemon 集经 monkeypatch 注入，零 docker。"""

    def test_slots_shape_and_reserved_excluded(self):
        slots = sd.net_table()
        self.assertEqual(len(slots), 256)
        self.assertTrue(all(s.startswith("10.213.") and s.endswith(".0/24") for s in slots))
        self.assertEqual(sd.NET_BASE_DEFAULT, "10.213.0.0/16")
        reserved = set(slots[-sd.NET_RESERVED_TAIL:])
        self.assertEqual(reserved, {"10.213.255.0/24"})
        orig = sd.daemon_subnets
        sd.daemon_subnets = lambda: set()
        try:
            free, used_by = sd.net_free_slots()
            self.assertNotIn("10.213.255.0/24", free, "保留槽不在可分配集")
            self.assertIn("10.213.255.0/24", " ".join(used_by), "保留槽在占用明细里点名")
            pick = sd.alloc_subnet("p1")
            self.assertIn(pick, free)
        finally:
            sd.daemon_subnets = orig

    def test_excludes_leased_and_daemon(self):
        lease = sd.new_lease("netuser", holder_pid=os.getpid(), services=[], ttl=90)
        lease["subnet"] = "10.213.3.0/24"
        sd.write_lease("netuser", lease)
        daemon = {"10.213.5.0/24", "172.17.0.0/16"}
        orig = sd.daemon_subnets
        sd.daemon_subnets = lambda: daemon
        try:
            for i in range(20):
                pick = sd.alloc_subnet("p2")
                self.assertNotEqual(pick, "10.213.3.0/24", "在册租约占用必被排除")
                self.assertFalse(sd._subnet_overlap(pick, daemon),
                                 "daemon 网段重叠必被排除（%s）" % pick)
        finally:
            sd.daemon_subnets = orig

    def test_random_not_sequential(self):
        """随机选槽（同批不序列、网段随台不同不可猜）：连取 8 槽不得全等于同一
        槽（恒等概率 ~10^-17，防「分配器退化为取最小」的恒真面）。"""
        orig = sd.daemon_subnets
        sd.daemon_subnets = lambda: set()
        try:
            picks = [sd.alloc_subnet("r%d" % i) for i in range(8)]
        finally:
            sd.daemon_subnets = orig
        self.assertFalse(all(p == picks[0] for p in picks),
                         "随机面退化：8 连全同槽 %s" % picks)

    def test_malformed_base_rejected(self):
        saved = os.environ.pop("SANDBAR_STAGE_NET_BASE", None)
        try:
            for bad in ("nonsense", "10.213.0.0/24", "10.213/16", "999.1.1.1/16", ""):
                os.environ["SANDBAR_STAGE_NET_BASE"] = bad
                with self.assertRaises(sd.StageError) as ctx:
                    sd.net_base()
                self.assertEqual(ctx.exception.kind, "usage")
            os.environ.pop("SANDBAR_STAGE_NET_BASE", None)
            self.assertEqual(sd.net_base(), sd.NET_BASE_DEFAULT, "缺失=缺省（三态）")
        finally:
            if saved is not None:
                os.environ["SANDBAR_STAGE_NET_BASE"] = saved

    def test_subnet_overlap_semantics(self):
        self.assertTrue(sd._subnet_overlap("10.213.3.0/24", {"10.213.0.0/16"}))
        self.assertTrue(sd._subnet_overlap("10.213.0.0/16", {"10.213.3.0/24"}))
        self.assertFalse(sd._subnet_overlap("10.213.3.0/24", {"10.214.3.0/24"}))
        self.assertFalse(sd._subnet_overlap("10.213.3.0/24", {"not-a-cidr"}))

    def test_exhaustion_red_names_remaining_and_occupants(self):
        """表耗尽=诚实 env 红且点名剩余槽数+占用者清单（C8）。"""
        orig = sd.daemon_subnets
        sd.daemon_subnets = lambda: set()
        leases = []
        try:
            slots = sd.net_table()
            for i, s in enumerate(slots[:-sd.NET_RESERVED_TAIL]):
                lease = sd.new_lease("full%d" % i, holder_pid=os.getpid(),
                                     services=[], ttl=90)
                lease["subnet"] = s
                sd.write_lease("full%d" % i, lease)
                leases.append("full%d" % i)
            with self.assertRaises(sd.StageError) as ctx:
                sd.alloc_subnet("p9")
            self.assertEqual(ctx.exception.kind, "env")
            self.assertIn("可分配槽 0", str(ctx.exception))
            self.assertIn("占用明细", str(ctx.exception))
            self.assertIn("10.213.255.0/24", str(ctx.exception))
        finally:
            sd.daemon_subnets = orig
            for p in leases:
                sd.release_lease(p)


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
