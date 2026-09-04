#!/usr/bin/env python3
"""T02 根因存在性锁定 + base 口径分工证明。

用户视角：t260901-14 里「建票 base_ref → red=2」必须先复现为真（红例不是凭空
捏造）；再证明口径修正的两个要素缺一不可——
  a. 三点 + 旧 base_ref 仍红：merge-base(锚点, lane)=锚点本身，三点救不了，
     证明「base 必须换成当前 main」是修正的必要条件（不是光改三点就行）；
  b. base=当前 main tip + 三点 → green：main 侧他人文件不进差集。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import build_lane_repo, call_verify_lane, result_of, _git, shutil, summary

fails = []
repo, anchor = build_lane_repo()
try:
    # 根因存在性：旧两点口径（建票 base_ref..lane）把他人 metrics 文档也计进来
    two_dot = _git("-c", "core.quotepath=false", "diff", "--name-only",
                   "%s..lane" % anchor, cwd=repo).splitlines()
    for f in ("docs/metrics-面板.md", "docs/metrics-api.md", "server/feature.py"):
        if f not in two_dot:
            fails.append("两点旧口径差集缺 %s（根因场景未复现，夹具失效）" % f)

    # a. 三点 + 旧 base_ref 仍含 main 侧文件 → 光改三点不够，base 必须换当前 main
    three_dot_old = _git("-c", "core.quotepath=false", "diff", "--name-only",
                         "%s...lane" % anchor, cwd=repo).splitlines()
    if "docs/metrics-面板.md" not in three_dot_old:
        fails.append("三点+旧 base_ref 差集缺 metrics 文档（预期仍红，实测不含？）")

    # b. 新口径：base=当前 main tip → 三点差集只含泳道本票改动 → green
    rc, payload = call_verify_lane({
        "lane": "code", "path": str(repo),
        "base": "main", "require_base": True,
        "write_set": ["server/"],
    })
    if rc != 0:
        fails.append("CLI 退出码 %d != 0" % rc)
    res = result_of(payload)
    if not res.get("green"):
        fails.append("base=当前 main 期望 green，实际 red_count=%s" % res.get("red_count"))
finally:
    shutil.rmtree(repo, ignore_errors=True)

for f in fails:
    print("FAIL:", f)
sys.exit(summary(0 if fails else 1, len(fails)))
