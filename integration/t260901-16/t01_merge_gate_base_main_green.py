#!/usr/bin/env python3
"""T01 合并闸主场景（t260901-14 假阳性回归）：泳道并入 main 的他人文件不判越界。

用户视角：泳道在制期间经冲突消解并入了 main（他人的 metrics 文档），
合并闸按「当前 main tip」口径精判写集 → 泳道自己的 server/ 改动在写集内，
main 侧他人文件不进差集 → 整体 green。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import build_lane_repo, call_verify_lane, result_of, shutil, summary

fails = []
repo, anchor = build_lane_repo()
try:
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "main", "require_base": True,
        "write_set": ["server/"],
    })
    if rc != 0:
        fails.append("CLI 退出码 %d != 0（工具调用本身失败）" % rc)
    res = result_of(payload)
    if not res.get("green"):
        fails.append("期望 green，实际 red_count=%s" % res.get("red_count"))
finally:
    shutil.rmtree(repo, ignore_errors=True)

for f in fails:
    print("FAIL:", f)
sys.exit(summary(0 if fails else 1, len(fails)))
