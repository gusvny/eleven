"""绿灯 fixture：印一份与 `admin.py call qc_run` 同契约的 JSON，green=true。

自测用（不依赖真实内容数据）：脚本门判绿代码一字不改，只换命令指向本 fixture。
"""
import json
import sys

payload = {
    "ok": True,
    "result": {
        "scope": "selfcheck",
        "scopes": ["selfcheck"],
        "green": True,
        "red_count": 0,
        "checks": [
            {"scope": "selfcheck", "check": "注词一字不差", "level": "green", "count": 0, "items": []},
            {"scope": "selfcheck", "check": "禁词扫描", "level": "green", "count": 0, "items": []},
            {"scope": "selfcheck", "check": "字符串卡残留", "level": "green", "count": 0, "items": []},
            {"scope": "selfcheck", "check": "器物文出典", "level": "green", "count": 0, "items": []},
        ],
    },
    "run_id": "fixture-green",
}
json.dump(payload, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
