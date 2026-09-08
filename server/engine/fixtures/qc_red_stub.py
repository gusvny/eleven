"""红灯 fixture：印一份与 `admin.py call qc_run` **同契约**的 JSON，但 green=false。

为什么要 fixture：现库 qc_run(scope=260627) 是全绿的，要演示「红灯卡住」不能去改
真实内容数据（内容归编辑，POC 零碰）。所以只替换 activity 要执行的**命令**，
activity 里判绿的代码一字不改——保证演示的是真实判据，不是埋在业务里的假分支。
"""

import json
import sys

payload = {
    "ok": True,
    "result": {
        "scope": "260627",
        "scopes": ["260627"],
        "green": False,
        "red_count": 2,
        "checks": [
            {
                "scope": "260627",
                "check": "注词一字不差",
                "level": "red",
                "count": 1,
                "items": [{"ku": "260627-ku-07", "detail": "（fixture）注词「示例」不在正文"}],
            },
            {
                "scope": "260627",
                "check": "禁词扫描",
                "level": "red",
                "count": 1,
                "items": [{"ku": "260627-ku-12", "detail": "（fixture）正文出现禁词「课堂」"}],
            },
            {"scope": "260627", "check": "字符串卡残留", "level": "green", "count": 0, "items": []},
            {"scope": "260627", "check": "器物文出典", "level": "green", "count": 0, "items": []},
        ],
    },
    "run_id": "fixture-red",
}
json.dump(payload, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
