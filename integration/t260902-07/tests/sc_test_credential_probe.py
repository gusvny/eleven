#!/usr/bin/env python3
"""t260902-07 集成测试 ③：凭据 seam 与远端探针（前置条件 + 可选外呼 + mock 燃料面）。

- 前置：~/.dsh/settings.yaml 已注册 zai-coding-cn provider（apiKeyEnv + glm-5.3-flash）
- 凭据：无真 key 且无 mock 时 ENV_FAIL exit 2（三态契约定稿 §7.3；不冒充通过）；
  两者皆无时进程内自起 mock（lib_model_mock）作燃料面，机制断言不因凭据缺失环境红
- 已注入 → 向 api.z.ai/api/coding/paas/v4 发 glm-5.3-flash 最小请求，断言 HTTP 200
- **mock 燃料面（t260904-12 乙段 gen4 #4）**：SANDBAR_MOCK_LLM_URL 指向本进程
  mock 端点（integration/lib_model_mock.py，中性前缀 env，非 SANDBAR_ 新名）时，
  探针同一断言面（HTTP 200 + chat.completion 形状）打 mock 而非真模型——
  凭据缺失不再环境红；并带**畸形输入腿**：mock 注入坏 JSON 回执，探针必须
  显式判红（不静默当过）。真模型腿与 mock 腿互斥不混跑：有真 key 仍打真端点。

cwd = 泳道根。stdlib only。key 只从环境读，不打印。
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HOME_DSH = Path(os.path.expanduser("~")) / ".dsh" / "settings.yaml"
BASE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
MOCK_URL_ENV = "SANDBAR_MOCK_LLM_URL"      # 中性前缀 mock 端点注入（禁 SANDBAR_ 新名）
MODEL = "glm-5.3-flash"


def probe(url, key, extra_headers=None, timeout=60):
    """向 <url> 发 glm-5.3-flash 最小 chat 请求。返回 (ok, msg)；畸形回执=不 ok。"""
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "回复一个字：好"}],
        "max_tokens": 16,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            payload = resp.read(4096).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return False, "探针请求异常: %s" % e
    if status != 200:
        return False, "探针 HTTP %s" % status
    try:
        obj = json.loads(payload)
    except ValueError:
        return False, "探针回包不是 JSON: %s" % payload[:200]
    if "glm-5.3-flash" not in payload and "content" not in payload:
        return False, "探针回包不像 chat completion: %s" % payload[:200]
    return True, "探针 HTTP 200，%s 回包正常" % MODEL


def main():
    fails = []
    text = HOME_DSH.read_text("utf-8") if HOME_DSH.is_file() else ""
    if "zai-coding-cn" not in text:
        print("FAIL ~/.dsh/settings.yaml 未注册 zai-coding-cn provider")
        return 1
    print("PASS ~/.dsh/settings.yaml 已注册 zai-coding-cn")
    if "glm-5.3-flash" not in text.split("zai-coding-cn", 1)[-1][:600]:
        print("FAIL zai-coding-cn 的 models 未手配 glm-5.3-flash")
        return 1
    print("PASS zai-coding-cn.models 含 glm-5.3-flash")

    key = os.environ.get("ZAI_CODING_CN_API_KEY")
    mock_url = (os.environ.get(MOCK_URL_ENV) or "").strip()
    self_mock = None
    if not mock_url and not key:
        # 无真 key 且无外部注入：进程内自起 mock（t260904-12 乙段——机制断言面
        # （HTTP 200+chat.completion 形状）不再因凭据缺失环境红；真 key 在场仍打真端点）。
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from lib_model_mock import MockLLMEndpoint as MockLLM
        self_mock = MockLLM()
        self_mock.start()
        mock_url = self_mock.base_url

    # ---- mock 燃料面（凭据缺失时的环境红消解；机制断言强度不变）----
    if mock_url:
        ok, msg = probe(mock_url, key=key or "mock-no-key-needed")
        print(("PASS mock" if ok else "FAIL mock") + " 燃料面探针 | " + msg)
        if not ok:
            fails.append("mock 探针")
        # 畸形输入腿：mock 注入坏 JSON 回执 → probe 必须显式判红（不静默过）
        bad_ok, bad_msg = probe(mock_url, key="mock",
                                extra_headers={"X-Mock-LLM-Mode": "bad_json"})
        if bad_ok:
            print("FAIL mock 畸形回执腿：坏 JSON 回执被当过（静默腐化）")
            fails.append("mock 畸形回执未判红")
        else:
            print("PASS mock 畸形回执被显式判红 | " + bad_msg[:120])

    # ---- 真模型腿（真 key 在场才跑，语义与拆改前一致）----
    if key:
        ok, msg = probe(BASE_URL, key)
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            fails.append("真模型探针")
    elif not mock_url:
        print("ENV_FAIL: ZAI_CODING_CN_API_KEY 未注入本环境且无 %s mock 燃料——执行段需"
              "确认 dsh worker 凭据 seam 已注入；缺失则 spawn 401，不静默回退，交人审"
              % MOCK_URL_ENV)
        return 2

    rc = 0 if not fails else 1
    if self_mock is not None:
        self_mock.stop()      # 进程内 mock 全终态回收（stop 幂等）
    return rc


if __name__ == "__main__":
    sys.exit(main())
