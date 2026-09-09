# -*- coding: utf-8 -*-
"""In-process mock LLM endpoint (t260904-12 part B gen4 #3) — zero third-party
dependencies, stdlib only.

Consumer-aligned surface (shape read off the consumer's code, not invented):
- the only consumer inside integration = t260902-07/tests/sc_test_credential_probe.py:
  it sends an OpenAI-style request body to `POST <base>/chat/completions`,
  `{"model": <str>, "messages": [{"role","content"}, ...], "max_tokens": int}`,
  with an `Authorization: Bearer <key>` header;
  its response assertions only require HTTP 200 and a payload containing
  `glm-5.3-flash` or `content`.
  So this mock's "normal" reply is the minimal OpenAI chat.completion face:
  `{"id","object":"chat.completion","model":<echo>,
    "choices":[{"index":0,"message":{"role":"assistant","content":<line>},
                "finish_reason":"stop"}]}`.
- replies with a different fixed line per the **model field in the request
  body** (the response model field echoes the request value), so a consumer
  can assert "asked for model X, got model X back".

Behavior injection (for scenario malformed-input legs):
- ok (default): 200 + a valid chat.completion JSON body;
- mode=bad_json: 200 + broken JSON bytes (malformed reply — the consumer must
  go explicitly red, never silently green);
- mode=http_500: HTTP 500 + a text body;
- mode=timeout: hangs for `delay` seconds before replying (the consumer hits
  it with a shorter timeout -> an explicit red on timeout).
The mode can be overridden per request via the query string `?mock_mode=...`
or the `X-Mock-LLM-Mode` header; the service-level default comes from
start(mode=...).

Lifecycle: start() brings up a ThreadingHTTPServer bound to 127.0.0.1:0
(kernel-assigned port) plus a daemon thread running serve_forever; stop() is
idempotent (shutdown -> server_close -> thread join), so a caller can put it
in a finally block and get full terminal-state reclamation; `with` syntax
also works.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fixed reply line per model (model field -> content); unknown models fall
# back to _DEFAULT_LINE.
_DEFAULT_LINE = "好（mock）"
MODEL_LINES = {
    "glm-5.3-flash": "好（mock glm-5.3-flash）",
    "glm-5.3": "好（mock glm-5.3）",
}


class _Handler(BaseHTTPRequestHandler):
    """Single-endpoint handler: path and method details are ignored; only the
    body's model field and the mode injection matter."""

    server_version = "SandbarMockLLM/1"

    def log_message(self, fmt, *args):  # silent: scenario stdout only fits the assertion ledger
        pass

    # ---- response helpers ----
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

    # ---- every method takes the same path ----
    def _handle(self):
        mode = getattr(self.server, "mock_mode", "ok")
        # per-request override: query string first, then the request header
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
            model = ""  # malformed body: don't crash the service, reply as unknown model (the mock itself must stay stable)

        if mode == "http_500":
            self._send_raw(500, "mock injected 500")
            return
        if mode == "bad_json":
            self._send_raw(200, "{not json from mock", "application/json")
            return
        if mode == "timeout":
            delay = float(getattr(self.server, "mock_delay", 5.0))
            # wait on the interrupt event: stop() wakes us immediately instead
            # of leaving the thread hanging
            ev = getattr(self.server, "mock_stop_event", None)
            if ev is not None:
                ev.wait(delay)
            else:
                return  # no event object = cannot hang safely; reply now (no unreclaimable path)
            if ev.is_set():
                return  # service already stopped: the connection closes with shutdown, don't write
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
    """In-process mock LLM endpoint for scenarios. Usage:

        mock = MockLLMEndpoint().start()
        try:
            ... urllib hitting mock.base_url + "/chat/completions" ...
        finally:
            mock.stop()
        # or with MockLLMEndpoint() as mock: ...
    """

    def __init__(self, mode="ok", delay=5.0):
        self._mode = mode
        self._delay = delay
        self._httpd = None
        self._thread = None
        self._stop_event = threading.Event()

    # ---- attributes ----
    @property
    def base_url(self):
        if self._httpd is None:
            raise RuntimeError("mock 未启动（先 start()）")
        return "http://127.0.0.1:%d" % self._httpd.server_address[1]

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # ---- lifecycle ----
    def start(self):
        """Bind 127.0.0.1:0 and start the server thread. A repeated start is
        idempotent (returns as-is when already running)."""
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
        """Idempotent teardown: shutdown -> server_close -> join. Safe to call
        freely from a finally block."""
        httpd, thread = self._httpd, self._thread
        self._stop_event.set()          # wake the timeout-hung handler first
        if httpd is not None:
            httpd.shutdown()            # stop the serve_forever loop (idempotent-safe)
        if thread is not None:
            thread.join(timeout=10)
        if httpd is not None:
            httpd.server_close()        # close the listening fd
        self._httpd = None
        self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()
        return False
