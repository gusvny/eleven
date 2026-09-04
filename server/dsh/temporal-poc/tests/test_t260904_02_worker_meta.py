"""t260904-02 B 面 UT：worker 归属指纹（meta 写/读/清 + worker.py 接线）。

- shared.write_worker_meta / read_worker_meta_state：往返、realpath 规范化、
  四态（ok/missing/malformed/read_error）、畸形形状；
- worker.py 接线（源级钉点，沿 test_t260901_21_i02 spawn_wiring 惯例——接线面
  改名/挪位即红，逻辑面由上面纯函数 UT 覆盖）：
  - ticket 模式读 SUYOU_WORKER_META；daemon 模式写 <pidfile>.meta；前台不写；
  - 起跑早写（Client.connect 前）+ 优雅退 best-effort 清理。
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402
import worker  # noqa: E402

WORKER_SRC = Path(worker.__file__).read_text(encoding="utf-8")


class MetaRoundTripTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="t260904-02-meta-"))

    def test_roundtrip(self):
        p = self.tmp / "worker-t1.meta"
        payload = shared.write_worker_meta(str(p), repo_root="/tmp", pid=4242)
        self.assertEqual(payload["pid"], 4242)
        meta, state, detail = shared.read_worker_meta_state(str(p))
        self.assertEqual(state, "ok")
        self.assertEqual(detail, "")
        self.assertEqual(meta["pid"], 4242)
        self.assertEqual(meta["repo_root"], os.path.realpath("/tmp"))

    def test_payload_realpath(self):
        payload = shared.worker_meta_payload(repo_root="/etc", pid=1)
        self.assertEqual(payload["repo_root"], os.path.realpath("/etc"))
        self.assertEqual(payload["version"], shared.WORKER_META_VERSION)
        self.assertIsInstance(payload["ts"], int)   # 字段名=工单场景契约（ts 非 started_at）

    def test_missing(self):
        meta, state, detail = shared.read_worker_meta_state(str(self.tmp / "nope.meta"))
        self.assertIsNone(meta)
        self.assertEqual(state, "missing")
        self.assertIn("文件不存在", detail)

    def test_malformed_json(self):
        p = self.tmp / "bad.meta"
        p.write_text("{oops", encoding="utf-8")
        _, state, detail = shared.read_worker_meta_state(str(p))
        self.assertEqual(state, "malformed")
        self.assertIn("JSON", detail)

    def test_malformed_shapes(self):
        for bad in (
            '{"pid": 1}',                                  # 缺 repo_root
            '{"pid": 1, "repo_root": ""}',                 # 空 repo_root
            '{"pid": "1", "repo_root": "/x"}',             # pid 字符串
            '{"pid": 1.5, "repo_root": "/x"}',             # pid 浮点
            '[]',                                          # 顶层数组
            '"str"',                                       # 顶层字符串
            '{"pid": true, "repo_root": "/x"}',            # pid bool
        ):
            p = self.tmp / "shape.meta"
            p.write_text(bad, encoding="utf-8")
            meta, state, detail = shared.read_worker_meta_state(str(p))
            self.assertEqual(state, "malformed", bad)
            self.assertIsNone(meta, bad)

    def test_read_error(self):
        # 目录当文件读 → OSError（非 FileNotFoundError）→ read_error 态
        d = self.tmp / "adir.meta"
        d.mkdir()
        _, state, detail = shared.read_worker_meta_state(str(d))
        self.assertEqual(state, "read_error")
        self.assertIn("Error", detail)  # IsADirectoryError 等

    def test_write_overwrites_atomically(self):
        p = self.tmp / "worker-t2.meta"
        shared.write_worker_meta(str(p), repo_root="/tmp", pid=1)
        shared.write_worker_meta(str(p), repo_root="/tmp", pid=2)
        meta, state, _ = shared.read_worker_meta_state(str(p))
        self.assertEqual(state, "ok")
        self.assertEqual(meta["pid"], 2)
        leftovers = [x.name for x in self.tmp.iterdir() if ".tmp." in x.name]
        self.assertEqual(leftovers, [], "原子写不留 tmp 残渣")


class WorkerWiringTest(unittest.TestCase):
    """worker.py 接线源检：meta 路径决策 + 起跑早写 + 退出清理。"""

    def test_meta_path_modes(self):
        import argparse
        # 环境隔离（t260904-09 implement 打回轮发现）：本测试由工单泳道内跑时，
        # supervisor 注入的 SUYOU_WORKER_META 会被「前台=不写」分支读到而误红——
        # 用例自有 env 语义，先清场再断言（非放宽：随后的专属模式分支自设该 env）。
        os.environ.pop("SUYOU_WORKER_META", None)
        args = argparse.Namespace(daemon=False, pidfile="/x/worker.pid", logfile="/x/l")
        self.assertEqual(worker.worker_meta_path(args), "")  # 前台=不写

        args.daemon = True
        self.assertEqual(worker.worker_meta_path(args), "/x/worker.pid.meta")  # daemon 旁车

        os.environ["SUYOU_WORKER_META"] = "/y/worker-t9.meta"
        try:
            self.assertEqual(worker.worker_meta_path(args), "/y/worker-t9.meta")  # ticket 模式 env 指路
        finally:
            del os.environ["SUYOU_WORKER_META"]

    def test_source_wiring_anchors(self):
        # 起跑早写（run_worker 内、真调用 Client.connect( 之前；用带括号形态锚，
        # 跳过注释里的同名提及）
        self.assertIn("write_worker_meta", WORKER_SRC)
        run_body = WORKER_SRC.split("async def run_worker")[1].split("async def")[0]
        connect_idx = run_body.find("Client.connect(")
        meta_idx = run_body.find("write_worker_meta(")
        self.assertTrue(0 <= meta_idx < connect_idx,
                        "meta 写在 Client.connect 前（worker 一活起来 ensure 就能读到归属）")
        # 优雅退清理（main 的 finally）
        main_body = WORKER_SRC.split("def main")[1]
        self.assertIn("finally:", main_body)
        self.assertIn("unlink", main_body)
        # ticket 模式 env 名钉住（node.ts spawn 侧同名字符串互指）
        self.assertIn("SUYOU_WORKER_META", WORKER_SRC)


if __name__ == "__main__":
    unittest.main()
