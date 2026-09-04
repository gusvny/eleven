#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench 槽位库 UT（t260904-02 acceptance 打回轮补强）：故障面行为断言。

- 满槽排队：槽被占时 acquire_slot(deadline_s=1) 抛 BenchBusy 且文案含「槽满」
  （工单正文「满槽排队不假红」的行为断言——此前仅实现与内核 flock 背书）；
- 槽根受限（P1 打回点）：~/.sandbar 不可写→明示降级平台临时区；env 指路根
  不可写→MissingAsset 点名旋钮；锁文件不可建→MissingAsset 不裸 traceback。
- 生产守卫 fail-closed 红绿（快速回归锚）。

跑法（无自动跑点，手工口径）：python3 integration/tests/test_bench.py
（stdlib-only，与真 temporalite 无关，秒级）。
"""
import os
import pathlib
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bench  # noqa: E402


class ProdGuardTest(unittest.TestCase):
    def test_prod_ports_rejected(self):
        for host in ("127.0.0.1:7233", "localhost:8233", "7233"):
            with self.assertRaises(bench.ProductionGuardError):
                bench.assert_not_production(host)

    def test_slot_base_ok_and_empty_rejected(self):
        self.assertEqual(bench.assert_not_production("127.0.0.1:19101"), "127.0.0.1:19101")
        with self.assertRaises(bench.ProductionGuardError):
            bench.assert_not_production("")


class BusyQueueTest(unittest.TestCase):
    """满槽排队：同进程第二 OFD flock 必败（内核语义），deadline 内抛 BenchBusy。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bench-ut-busy-")
        os.environ["SANDBAR_TEST_BENCH_DIR"] = self.tmp
        os.environ["SANDBAR_TEST_BENCH_SLOTS"] = "1"
        bench._BENCH_ROOT_CACHE = None

    def tearDown(self):
        bench._BENCH_ROOT_CACHE = None
        del os.environ["SANDBAR_TEST_BENCH_DIR"]
        del os.environ["SANDBAR_TEST_BENCH_SLOTS"]

    def test_busy_raises_benchbusy_with_wanli(self):
        s = bench.acquire_slot(deadline_s=5)
        try:
            with self.assertRaises(bench.BenchBusy) as cm:
                bench.acquire_slot(deadline_s=1)
            self.assertIn("槽满", str(cm.exception))
        finally:
            s.stop()
            s.release()

    def test_reacquire_after_release(self):
        s = bench.acquire_slot(deadline_s=5)
        s.stop()
        s.release()
        s2 = bench.acquire_slot(deadline_s=5)  # 释放后立即可复抢
        self.assertEqual(s2.index, s.index)
        s2.stop()
        s2.release()


class RootDegradeTest(unittest.TestCase):
    """P1：槽根可用性真探测（写+删探针文件），不可写=明示降级/可辨异常。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bench-ut-root-")
        bench._BENCH_ROOT_CACHE = None
        self._saved = {k: os.environ.get(k) for k in ("SANDBAR_TEST_BENCH_DIR", "HOME")}
        os.environ.pop("SANDBAR_TEST_BENCH_DIR", None)

    def tearDown(self):
        bench._BENCH_ROOT_CACHE = None
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for p in pathlib.Path(self.tmp).rglob("*"):
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass

    def _unwritable_dir(self):
        d = pathlib.Path(self.tmp) / "readonly-root"
        d.mkdir(parents=True)
        os.chmod(d, 0o555)  # 目录在、不可写文件=P1 假通形态
        return d

    def test_existing_but_unwritable_dir_degrades(self):
        # HOME 桩到只读根：bench_root 应回落平台临时区（明示降级），不再裸 PermissionError
        readonly = self._unwritable_dir()
        os.environ["HOME"] = str(readonly)
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            root = bench.bench_root()
        self.assertNotEqual(root, readonly / ".sandbar" / "test-benches")
        self.assertIn("明示降级", err.getvalue())
        self.assertIn("SANDBAR_TEST_BENCH_DIR", err.getvalue())  # 旋钮指路在场

    def test_env_root_unwritable_named_error(self):
        os.environ["SANDBAR_TEST_BENCH_DIR"] = str(self._unwritable_dir())
        with self.assertRaises(bench.MissingAsset) as cm:
            bench.bench_root()
        self.assertIn("SANDBAR_TEST_BENCH_DIR", str(cm.exception))
        self.assertIn("不可写", str(cm.exception))

    def test_try_lock_unwritable_classified(self):
        s = bench.Slot(pathlib.Path(self._unwritable_dir()), 1)
        with self.assertRaises(bench.MissingAsset) as cm:
            s.try_lock()
        self.assertIn("SANDBAR_TEST_BENCH_DIR", str(cm.exception))  # 可辨，非裸 traceback


if __name__ == "__main__":
    unittest.main()
