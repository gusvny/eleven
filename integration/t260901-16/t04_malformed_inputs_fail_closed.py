#!/usr/bin/env python3
"""T04 畸形输入三态：base 不存在 / base 空 + require_base / 零写集。

用户视角：合并闸吃到的 base_ref 可能被分支清理删掉、可能没登记、
工单可能声明零写集——三种畸形输入都必须 fail-closed 红、报错说清
「哪个检查失败」，不许崩、不许静默放行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import build_lane_repo, call_verify_lane, result_of, red_details, shutil, summary

fails = []
repo, anchor = build_lane_repo()
try:
    # a) base 指向不存在的 ref：不崩，红且报「git diff 失败」（不是含糊的「未产出结果」）
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "no-such-ref-t26090116", "require_base": True,
        "write_set": ["server/"],
    })
    res = result_of(payload)
    if res.get("green"):
        fails.append("a) base 不存在期望红，实际 green")
    if rc != 0:
        fails.append("a) 工具应不崩（CLI 退出码 0），实际 %d" % rc)
    if not any("git diff 失败" in d for d in red_details(res)):
        fails.append("a) 红项应写明 git diff 失败: %s" % red_details(res))

    # b) base 空字符串 + require_base：fail-closed「base_ref 未登记」
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "", "require_base": True, "write_set": ["server/"],
    })
    res = result_of(payload)
    if res.get("green"):
        fails.append("b) base 空 + require_base 期望红，实际 green")
    if not any("base_ref 未登记" in d for d in red_details(res)):
        fails.append("b) 红项应写明 base_ref 未登记: %s" % red_details(res))

    # c) 零写集（空列表）：泳道有任何 diff 文件即红
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "main", "require_base": True, "write_set": [],
    })
    res = result_of(payload)
    if res.get("green"):
        fails.append("c) 零写集 + 泳道有改动期望红，实际 green")
finally:
    shutil.rmtree(repo, ignore_errors=True)

for f in fails:
    print("FAIL:", f)
sys.exit(summary(0 if fails else 1, len(fails)))
