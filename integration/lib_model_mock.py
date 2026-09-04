# -*- coding: utf-8 -*-
"""进程内 mock LLM 端点（t260904-12 乙段 gen4 #3）——零第三方依赖，stdlib only。

消费面对齐（读了消费方代码才定的形状，不凭空造）：
- 唯一 integration 内消费方 = t260902-07/tests/sc_test_credential_probe.py：
  它向 `POST <base>/chat/completions` 发 OpenAI 风格请求体
  `{"model": <str>, "messages": [{"role","content"}, ...], "max_tokens": int}`，
  带 `Authorization: Bearer <key>` 头；
  回执断言只要求 HTTP 200 且 payload 含 `glm-5.3-flash` 或 `content` 字样。
  故本 mock 的「正常」回执取 OpenAI chat.completion 最小面：
  `{"id","object":"chat.completion","model":<echo>,
    "choices":[{"index":0,"message":{"role":"assistant","content":<台词>},
                "finish_reason":"stop"}]}`。
- 按**请求体里的 model 字段**回不同固定台词（回执 model 字段回显请求值），
  便于消费方断言「请求哪个模型、回哪个模型」。

行为注入（供场景畸形输入腿）：
- 正常（缺省）：200 + 合法 chat.completion JSON；
- mode=bad_json：200 + 坏 JSON 字节（畸形回执——消费方必须显式红，不得静默过）；
- mode=http_500：HTTP 500 + 文本体；
- mode=timeout：挂起 delay 秒后才回（消费方以更短超时打它 → 超时显式红）。
mode 经查询串 `?mock_mode=...` 或请求头 `X-Mock-LLM-Mode` 逐请求覆盖，
服务级缺省由 start(mode=...) 设定。

生命周期：start() 起 ThreadingHTTPServer 绑 127.0.0.1:0（内核分配端口）+
守护线程 serve_forever；stop() 幂等（shutdown → server_close → thread join），
调用方把它放进 finally 即可全终态回收；也支持 with 语法。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 各模型的固定台词（model 字段 → content）；未知模型回落 _DEFAULT_LINE。
_DEFAULT_LINE = "好（mock）"
MODEL_LINES = {
    "glm-5.3-flash": "好（mock glm-5.3-flash）",
    "glm-5.3": "好（mock glm-5.3）",
}


class _Handler(BaseHTTPRequestHandler):
    """单端点 handler：忽略路径与 method 细节，只认 body 的 model 字段与 mode 注入。"""

    server_version = "SandbarMockLLM/1"

    def log_message(self, fmt, *args):  # 静默：场景 stdout 只装得下断言账本
        pass

    # ---- 响应工具 ----
    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code, text, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 各 method 都走同一处理 ----
    def _handle(self):
        mode = getattr(self.server, "mock_mode", "ok")
        # 逐请求覆盖：查询串优先，其次请求头
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
        else:
            qs = ""
        for kv in qs.split("&"):
            if kv.startswith("mock_mode="):
                mode = kv.split("=", 1)[1] or mode
        hmode = self.headers.get("X-Mock-LLM-Mode")
        if hmode:
            mode = hmode

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        model = ""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
            if isinstance(req, dict):
                model = req.get("model") if isinstance(req.get("model"), str) else ""
        except (ValueError, UnicodeDecodeError):
            model = ""  # 畸形请求体：不炸服务，按未知模型回（mock 本身要稳）

        if mode == "http_500":
            self._send_raw(500, "mock injected 500")
            return
        if mode == "bad_json":
            self._send_raw(200, "{not json from mock", "application/json")
            return
        if mode == "timeout":
            delay = float(getattr(self.server, "mock_delay", 5.0))
            # 用中断事件等：stop() 时能立刻醒来，不吊线程
            ev = getattr(self.server, "mock_stop_event", None)
            if ev is not None:
                ev.wait(delay)
            else:
                return  # 无事件对象=无法安全挂起，直接回（不制造不可回收路径）
            if ev.is_set():
                return  # 服务已被 stop：连接随 shutdown 收尾，不再写
        content = MODEL_LINES.get(model, _DEFAULT_LINE)
        self._send_json(200, {
            "id": "chatcmpl-mock-1",
            "object": "chat.completion",
            "model": model or "mock-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        })

    do_GET = do_POST = do_PUT = do_DELETE = _handle


class MockLLMEndpoint:
    """场景进程内 mock LLM 端点。用法：

        mock = MockLLMEndpoint().start()
        try:
            ... urllib 打 mock.base_url + "/chat/completions" ...
        finally:
            mock.stop()
        # 或 with MockLLMEndpoint() as mock: ...
    """

    def __init__(self, mode="ok", delay=5.0):
        self._mode = mode
        self._delay = delay
        self._httpd = None
        self._thread = None
        self._stop_event = threading.Event()

    # ---- 属性 ----
    @property
    def base_url(self):
        if self._httpd is None:
            raise RuntimeError("mock 未启动（先 start()）")
        return "http://127.0.0.1:%d" % self._httpd.server_address[1]

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # ---- 生命周期 ----
    def start(self):
        """绑定 127.0.0.1:0 起服务线程。重复 start 幂等（已跑就原样返回）。"""
        if self.running:
            return self
        self._stop_event.clear()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.mock_mode = self._mode
        self._httpd.mock_delay = self._delay
        self._httpd.mock_stop_event = self._stop_event
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="mock-llm-endpoint", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """幂等回收：shutdown → server_close → join。finally 里随便调。"""
        httpd, thread = self._httpd, self._thread
        self._stop_event.set()          # 先唤醒 timeout 挂起的 handler
        if httpd is not None:
            httpd.shutdown()            # 停 serve_forever 循环（幂等安全）
        if thread is not None:
            thread.join(timeout=10)
        if httpd is not None:
            httpd.server_close()        # 关监听 fd
        self._httpd = None
        self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()
        return False
