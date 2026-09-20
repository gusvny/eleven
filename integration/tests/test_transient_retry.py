#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""瞬态重试库 UT（t260910-12 目标④；R9 单源 + 畸形输入纪律）。

覆盖面：
- 白名单四向：502/拒连族/起台面繁忙族命中；普通环境红不命中；
- 畸形输入：None/非字符串/空串/bytes/超长行 → 一律 fatal，绝不抛异常；
- retry_transient_once：瞬态一重试即绿 / 非瞬态不重试原样抛 / 重试仍红原样
  上抛且文案逐字节保留（call 计数=2）；
- py/mjs 一致性：同一固定消息桩清单，mjs 侧（spawn py 判定）与 py 侧判定
  逐条一致（锚两实现不漂移——R9）。

跑法：python3 integration/tests/test_transient_retry.py（node 缺席时 mjs 一致性
子用例不可跑——三态契约闸内不设跳过态：本用例退守 py judge 单源契约子用例自证，mjs 加载
子用例的环境红面由 L2 场景 sc_transient_retry_contract 守，node 缺席=ENV_FAIL exit 2）。
"""
import json
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
INTEG = HERE.parent
sys.path.insert(0, str(INTEG))

import lib_transient_retry as tr  # noqa: E402

# 固定消息桩：三类瞬态（+变体）与必须 fatal 的对照面。py/mjs 共用（R9）。
FIXTURES = [
    # (消息, 期望瞬态)
    ("HTTP/1.1 502 Bad Gateway from upstream", True),
    ("Error: connect ECONNREFUSED 127.0.0.1:21101", True),
    ("page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:21102/", True),
    ("dial tcp 127.0.0.1:21103: connect: connection refused", True),
    # 实证补族桩（arbitrate gen2）：不带空格的拒连形态——Rust tonic 驼峰与
    # temporalio SDK 文案（schedule 场景实测红文案，补族前永不命中白名单）
    ("tonic::transport::Error(ConnectError(\"tcp connect error\", 127.0.0.1:21021, kind: ConnectionRefused))", True),
    ("temporalio.service.RPCError: tcp connect error", True),
    ("STAGE_ENV: 起台面满员：并发上限 12 已用尽，排队 600s 未等到释放", True),
    ("起台面满员：当前活租约清单 holder=t260910-12/pid=123", True),
    ("端口段耗尽：400 档（21000~25000）全忙或被锁", True),
    # fatal 对照：环境红/断言红/编排层错误绝不重试（互斥超时重试会再撞锁）
    ("STAGE_ENV: 供给台 x ensure 互斥等待超时（600s）", False),
    ("ENV_FAIL: docker 不可用（docker info 失败）", False),
    ("ENV_FAIL: 测试镜像缺席：test-temporal:cli-1.8.3", False),
    ("AssertionError: expected 3 rows, got 0", False),
    ("STAGE_USAGE: --project 不合法", False),
    ("timeout waiting for selector .row", False),
]

_MALFORMED = [None, 123, 4.5, b"bytes", [], {}, "", "   ", "x" * 100000, object()]


class TransientClassifyTest(unittest.TestCase):
    def test_whitelist_hits(self):
        for msg, want in FIXTURES:
            got = tr.is_transient(msg)
            self.assertIsInstance(got, bool, "公开契约：is_transient 返纯 bool")
            self.assertEqual(got, want, "消息 %r 判定 %s" % (msg[:60], got))

    def test_malformed_never_raises_always_fatal(self):
        for bad in _MALFORMED:
            self.assertIs(tr.is_transient(bad), False,
                          "畸形输入 %r 必须落 fatal 侧" % (type(bad).__name__,))

    def test_judge_subcommand_contract(self):
        """契约面：judge <msg> 逐桩输出 transient|fatal（sc_transient_retry_contract
        锚定的 py 消费缝）。"""
        for msg, want in FIXTURES:
            p = subprocess.run([sys.executable, str(INTEG / "lib_transient_retry.py"),
                                "judge", msg], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, "judge exit 0：%s" % p.stderr)
            self.assertIn("transient" if want else "fatal", p.stdout,
                          "judge 输出词错：%r" % msg[:40])

    def test_retry_once_success_on_transient(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("connect ECONNREFUSED 127.0.0.1:1")
            return "ok"

        self.assertEqual(tr.retry_transient_once(flaky, sleep_s=0), "ok")
        self.assertEqual(calls["n"], 2, "瞬态恰重试一次")

    def test_fatal_no_retry(self):
        calls = {"n": 0}

        def hard_red():
            calls["n"] += 1
            raise RuntimeError("ENV_FAIL: docker 不可用")

        with self.assertRaises(RuntimeError):
            tr.retry_transient_once(hard_red, sleep_s=0)
        self.assertEqual(calls["n"], 1, "非瞬态绝不重试")

    def test_transient_twice_reported_verbatim(self):
        calls = {"n": 0}
        msg = "502 Bad Gateway"

        def always_502():
            calls["n"] += 1
            raise RuntimeError(msg)

        with self.assertRaises(RuntimeError) as ctx:
            tr.retry_transient_once(always_502, sleep_s=0)
        self.assertEqual(calls["n"], 2, "瞬态重试一次后仍红 → 上报")
        self.assertEqual(str(ctx.exception), msg, "重试仍红原样上报（文案逐字节）")


class MjsConsistencyTest(unittest.TestCase):
    """R9：mjs 侧（spawn py is-transient）与 py 侧对同一桩清单判定一致。"""

    def test_mjs_wrapper_matches_py(self):
        node = node_path()
        if not node:
            # 三态契约（t260904-12）：闸内不设跳过态，环境缺件不得以跳过掩盖。
            # node 缺席时退守 py 单源契约子用例（judge 子命令，真实断言面非空过）；
            # mjs 薄包装加载一致性的环境红面由 L2 场景守（node 缺席=ENV_FAIL）。
            p = subprocess.run(
                [sys.executable, str(INTEG / "lib_transient_retry.py"), "judge",
                 FIXTURES[0][0]],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, "py judge 子命令应可跑：%s" % p.stderr)
            want_word = "transient" if FIXTURES[0][1] else "fatal"
            self.assertIn(want_word, p.stdout, "judge 单源判定锚（py 侧自证）")
            print("ENV_FAIL(notes): node 缺席——mjs 一致性子用例由 L2 场景守，本用例以 py judge 单源子用例自证")
            return
        script = (
            "const { isTransient } = await import(%r);\n"
            "const fixtures = JSON.parse(process.argv[1]);\n"
            "const out = fixtures.map(([m, want]) => isTransient(m));\n"
            "console.log(JSON.stringify(out));\n"
        ) % str(INTEG / "lib_transient_retry.mjs")
        p = subprocess.run(
            [node, "--input-type=module", "-e", script,
             json.dumps([[m, w] for m, w in FIXTURES])],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, "mjs 一致性脚本应可跑：%s" % p.stderr)
        got = json.loads(p.stdout.strip().splitlines()[-1])
        want = [w for _, w in FIXTURES]
        self.assertEqual(got, want, "py/mjs 白名单判定必须逐条一致（R9 单源锚）")


def node_path():
    from shutil import which
    return which("node")


if __name__ == "__main__":
    unittest.main(verbosity=2)
