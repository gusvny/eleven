#!/usr/bin/env python3
"""t260902-07 集成测试 ③：凭据 seam 与远端探针（前置条件 + 可选外呼）。

- 前置：~/.dsh/settings.yaml 已注册 zai-coding-cn provider（apiKeyEnv + glm-5.3-flash）
- 凭据：ZAI_CODING_CN_API_KEY 未注入 → SKIP（不冒充通过，输出指明这是执行段待办）
- 已注入 → 向 api.z.ai/api/coding/paas/v4 发 glm-5.3-flash 最小请求，断言 HTTP 200
cwd = 泳道根。stdlib only。key 只从环境读，不打印。
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HOME_DSH = Path(os.path.expanduser("~")) / ".dsh" / "settings.yaml"
BASE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"


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
    if not key:
        print("SKIP ZAI_CODING_CN_API_KEY 未注入本环境——执行段需确认 dsh worker "
              "凭据 seam 已注入；缺失则 spawn 401，不静默回退，交人审")
        return 0

    body = json.dumps({
        "model": "glm-5.3-flash",
        "messages": [{"role": "user", "content": "回复一个字：好"}],
        "max_tokens": 16,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            payload = resp.read(4096).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print("FAIL 探针请求异常: %s" % e)
        return 1
    if status != 200:
        print("FAIL 探针 HTTP %s" % status)
        return 1
    if "glm-5.3-flash" not in payload and "content" not in payload:
        print("FAIL 探针回包不像 chat completion: %s" % payload[:200])
        return 1
    print("PASS 探针 HTTP 200，glm-5.3-flash 回包正常")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
