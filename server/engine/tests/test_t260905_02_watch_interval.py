"""t260905-02 UT：worker watch 轮询间隔旋钮（SANDBAR_WATCH_INTERVAL_SEC）。

- watch_interval_sec 纯函数：缺省/有效值/下限钳制/畸形全态（空白、非数值、
  NaN、±Inf、<=0、1e999 溢出 Inf）回落缺省；
- 命名红线（宿主令 260904，新 env 不扩 SANDBAR_* 存量）：源码零 SANDBAR_WATCH_INTERVAL；
- 接线锁：run_worker 里 sleep 消费的是旋钮产物（改名/挪位即红——逻辑面由纯函数
  UT 覆盖，接线面沿 test_t260904_02_worker_meta 源级钉点惯例）。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import worker  # noqa: E402

WORKER_SRC = Path(worker.__file__).read_text(encoding="utf-8")

DEF = worker.WATCH_INTERVAL_DEFAULT_SEC
MIN = worker.WATCH_INTERVAL_MIN_SEC


class WatchIntervalSecTest(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(worker.watch_interval_sec(""), DEF)
        self.assertEqual(worker.watch_interval_sec("   "), DEF)
        self.assertEqual(worker.watch_interval_sec(None, ), DEF)  # env 路径在 test_env_path 覆盖

    def test_valid_values_pass_through(self):
        self.assertEqual(worker.watch_interval_sec("2.5"), 2.5)
        self.assertEqual(worker.watch_interval_sec("3"), 3.0)
        self.assertEqual(worker.watch_interval_sec(" 4 "), 4.0)   # 空白容忍
        self.assertEqual(worker.watch_interval_sec("1e3"), 1000.0)

    def test_below_min_clamped(self):
        self.assertEqual(worker.watch_interval_sec("0.5"), MIN)
        self.assertEqual(worker.watch_interval_sec(str(MIN)), MIN)

    def test_malformed_fall_back_to_default(self):
        for bad in ("abc", "NaN", "nan", "inf", "-inf", "Infinity", "0", "-0",
                    "-3", "0x10", "1,5", "30s", "1e999"):
            self.assertEqual(worker.watch_interval_sec(bad), DEF,
                             "畸形值 %r 应回落缺省" % bad)

    def test_env_path(self):
        old = os.environ.get("SANDBAR_WATCH_INTERVAL_SEC")
        try:
            os.environ["SANDBAR_WATCH_INTERVAL_SEC"] = "2"
            self.assertEqual(worker.watch_interval_sec(), 2.0)
            os.environ["SANDBAR_WATCH_INTERVAL_SEC"] = "junk"
            self.assertEqual(worker.watch_interval_sec(), DEF)
            os.environ.pop("SANDBAR_WATCH_INTERVAL_SEC")
            self.assertEqual(worker.watch_interval_sec(), DEF)
        finally:
            if old is None:
                os.environ.pop("SANDBAR_WATCH_INTERVAL_SEC", None)
            else:
                os.environ["SANDBAR_WATCH_INTERVAL_SEC"] = old

    def test_wiring_watch_loop_consumes_knob(self):
        # 接线锁：_watch 的 sleep 消费旋钮产物（旧形态 asyncio.sleep(30) 字面量即漏改）。
        self.assertIn("watch_interval = watch_interval_sec()", WORKER_SRC)
        self.assertIn("await asyncio.sleep(watch_interval)", WORKER_SRC)
        self.assertNotIn("await asyncio.sleep(30)", WORKER_SRC)


if __name__ == "__main__":
    unittest.main()
