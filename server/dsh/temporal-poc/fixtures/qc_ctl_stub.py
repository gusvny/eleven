"""控制文件门 fixture：读环境变量 SUYOU_GATE_CTL 指向的文件——内容含 "green" 则印绿灯
JSON（同 qc_run 契约），否则印红灯。自测用：先在控制文件写 red 演示「脚本门红→blocked」，
再改写 green + retry_qc signal 演示「重跑放行」，判绿代码一字不改。
"""
import json
import os
import sys

ctl = os.environ.get("SUYOU_GATE_CTL") or ""
green = False
try:
    with open(ctl, "r", encoding="utf-8") as f:
        green = "green" in f.read()
except OSError:
    green = False

payload = {
    "ok": True,
    "result": {
        "scope": "selfcheck-ctl",
        "scopes": ["selfcheck-ctl"],
        "green": green,
        "red_count": 0 if green else 1,
        "checks": [
            {"scope": "selfcheck-ctl", "check": "控制文件门",
             "level": "green" if green else "red",
             "count": 0 if green else 1,
             "items": [] if green else [{"ku": "-", "detail": "控制文件非 green"}]},
        ],
    },
    "run_id": "fixture-ctl",
}
json.dump(payload, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
