#!/usr/bin/env python3
"""T03 判得准 + 非 ASCII 文件名不误判：写集外恰报两条、中文名原样出现在红项里。

用户视角：白名单不只「不误报」，还要「不漏报」——泳道改了写集外的
server/feature.py 与 server/界面文案.txt、声明写集只有 docs/ 时，
恰好报这两条越界，中文名不被 quotepath 转义成匹配不上的乱码。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import build_lane_repo, call_verify_lane, result_of, red_details, shutil, summary

fails = []
repo, anchor = build_lane_repo()
try:
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "main", "require_base": True,
        "write_set": ["docs/"],
    })
    res = result_of(payload)
    if res.get("green"):
        fails.append("写集=docs/ 而泳道改的是 server/，期望红，实际 green")
    oob = [d for d in red_details(res) if "越界写" in d]
    if len(oob) != 2:
        fails.append("期望恰 2 条越界写，实际 %d 条: %s" % (len(oob), oob))
    joined = "\n".join(oob)
    for f in ("server/feature.py", "server/界面文案.txt"):
        if f not in joined:
            fails.append("越界项缺 %s（非 ASCII 名被转义或漏判）" % f)
finally:
    shutil.rmtree(repo, ignore_errors=True)

for f in fails:
    print("FAIL:", f)
sys.exit(summary(0 if fails else 1, len(fails)))
