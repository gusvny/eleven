#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_model_mock UT（t260904-12 乙段）：mock 端点回执形状与全终态回收。

- 回执对齐消费方（t260902-07 凭据探针）：POST chat/completions → 200 + OpenAI
  chat.completion 最小面，model 回显、已知模型台词、未知模型回落；
- 行为注入：bad_json / http_500 / timeout 模式（查询串与请求头两种覆盖）；
- 畸形输入：坏 JSON 请求体不炸 mock；空 body 可回；
- 生命周期：stop 幂等、二次 start、stop 后零监听残留（lsof 复核）。

跑法（手工口径，同 test_bench）：python3 integration/tests/test_lib_model_mock.py
（stdlib only，秒级）。
"""
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lib_model_mock as mm  # noqa: E402


def post(url, body=None, headers=None, timeout=5):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


class MockLLMTest(unittest.TestCase):
    def _post_chat(self, mock, model="glm-5.3-flash", **kw):
        return post(mock.base_url + "/chat/completions",
                    {"model": model,
                     "messages": [{"role": "user", "content": "回复一个字：好"}],
                     "max_tokens": 16}, **kw)

    # ---- 正常回执形状（对齐凭据探针断言面）----
    def test_ok_receipt_shape(self):
        with mm.MockLLMEndpoint() as mock:
            status, payload = self._post_chat(mock)
            self.assertEqual(status, 200)
            obj = json.loads(payload)
            self.assertEqual(obj["object"], "chat.completion")
            self.assertEqual(obj["model"], "glm-5.3-flash")   # model 回显
            choice = obj["choices"][0]
            self.assertEqual(choice["message"]["role"], "assistant")
            self.assertIn("content", choice["message"])        # 探针认 content
            self.assertIn("glm-5.3-flash", payload)            # 探针认模型名字样

    def test_known_and_unknown_model_lines(self):
        with mm.MockLLMEndpoint() as mock:
            _, p1 = self._post_chat(mock, model="glm-5.3")
            self.assertIn("mock glm-5.3", json.loads(p1)["choices"][0]["message"]["content"])
            _, p2 = self._post_chat(mock, model="never-heard-of")
            self.assertEqual(json.loads(p2)["model"], "never-heard-of")  # 仍回显
            self.assertTrue(json.loads(p2)["choices"][0]["message"]["content"])  # 回落台词非空

    # ---- 行为注入 ----
    def test_bad_json_mode(self):
        with mm.MockLLMEndpoint(mode="bad_json") as mock:
            status, payload = self._post_chat(mock)
            self.assertEqual(status, 200)
            with self.assertRaises(ValueError):
                json.loads(payload)                            # 畸形回执=消费方必须显式红

    def test_http_500_mode(self):
        with mm.MockLLMEndpoint(mode="http_500") as mock:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post_chat(mock)
            self.assertEqual(ctx.exception.code, 500)

    def test_timeout_mode_and_override(self):
        # 服务级 mode=timeout：delay 3s，消费方 0.3s 超时 → socket 超时显式红
        with mm.MockLLMEndpoint(mode="timeout", delay=3.0) as mock:
            with self.assertRaises(Exception):
                self._post_chat(mock, timeout=0.3)
            # 逐请求头覆盖回正常：同一端点两态可切
            status, payload = self._post_chat(mock, headers={"X-Mock-LLM-Mode": "ok"})
            self.assertEqual(status, 200)
            json.loads(payload)
        # 查询串覆盖
        with mm.MockLLMEndpoint() as mock:
            status, payload = post(mock.base_url + "/chat/completions?mock_mode=bad_json",
                                   {"model": "x"})
            self.assertEqual(status, 200)
            with self.assertRaises(ValueError):
                json.loads(payload)

    # ---- 畸形输入（消费外部输入的桩必带）----
    def test_malformed_request_bodies(self):
        with mm.MockLLMEndpoint() as mock:
            for raw in (b"", b"{not json", b'{"model": 42}', b"\xff\xfe garbage"):
                req = urllib.request.Request(mock.base_url + "/chat/completions",
                                             data=raw, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)         # mock 不炸，按未知模型回

    # ---- 生命周期 ----
    def test_stop_idempotent_and_restart(self):
        mock = mm.MockLLMEndpoint()
        mock.start()
        url = mock.base_url
        mock.stop()
        mock.stop()                                            # 幂等：二连 stop 不炸
        with self.assertRaises(RuntimeError):
            _ = mock.base_url                                  # 停后不再给 base_url
        mock.start()                                           # 可重启，端口重分配
        self.assertNotEqual(mock.base_url, url)                # :0 内核分配，几乎必新端口
        status, _ = self._post_chat(mock)
        self.assertEqual(status, 200)
        mock.stop()

    def test_double_start_no_second_listener(self):
        mock = mm.MockLLMEndpoint().start()
        first = mock.base_url
        mock.start()                                           # 幂等：不换端口不叠线程
        self.assertEqual(mock.base_url, first)
        mock.stop()

    def test_no_listener_residual_after_stop(self):
        mock = mm.MockLLMEndpoint().start()
        port = mock.base_url.rsplit(":", 1)[1]
        mock.stop()
        # lsof 复核：该端口无任何监听残留（全终态回收证据）
        # lsof 语义：无匹配连接 = exit 1 + 空 stdout（这是期望态，不是「工具不可用」）
        try:
            p = subprocess.run(["lsof", "-nP", "-iTCP:%s" % port, "-sTCP:LISTEN"],
                               capture_output=True, text=True)
        except FileNotFoundError:
            self.skipTest("lsof 不可用")
        residual = p.stdout.strip()
        self.assertEqual(residual, "", "mock 停后仍有监听残留：%s" % residual)
        # stop() 返回后必须已 join（线程终态）
        self.assertFalse(mock._thread is not None and mock._thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
