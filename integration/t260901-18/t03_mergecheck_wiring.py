#!/usr/bin/env python3
"""t03 merge_check 真实接线（端到端 activity 层）。

用户场景保护：merge_check 第 3 项喂给白名单判定的 base，必须是当前
merge-base(main, 泳道分支)，不再是工单 create 时钉死的 base_ref——
这是 KI-010 修复的接线本体。本用例真跑泳道内的 merge_check activity：
真 git、真分支、真 merge-base 计算，只拦下它发给 verify_lane 的那一发
子进程并记录真实 payload（verify_lane 判定本身由 t01 真跑覆盖）。

预修复代码上本用例必红（payload base == 钉死 base_ref）；修复后必绿。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import ok, finish, import_engine, VerifyLaneCapture, lane_root, git


def main() -> int:
    aa, MergeCheckArgs = import_engine()
    root = lane_root()
    p = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    ok(p.returncode == 0, "当前泳道分支可解析")
    branch = p.stdout.strip()

    mb = git(root, "merge-base", "main", branch).stdout.strip()
    ok(bool(mb), "main × %s 的 merge-base 存在（%s…）" % (branch, mb[:7]))

    # 钉死 base_ref 取比 merge-base 早的提交，保证新旧口径可区分
    q = git(root, "rev-parse", mb + "~2")
    ok(q.returncode == 0, "取到早于 merge-base 的钉死 base_ref")
    base_ref = q.stdout.strip()
    ok(base_ref != mb, "对照有效：钉死 base_ref ≠ merge-base")

    args = MergeCheckArgs(ticket_id="t260901-18-it",
                          worktree=str(root), branch=branch,
                          base_ref=base_ref,
                          write_set=["server/dsh/temporal-poc/agent_activities.py"])

    with VerifyLaneCapture(aa) as cap:
        res = asyncio.run(aa.merge_check(args))

    ok(cap.payload is not None, "merge_check 第 3 项确实调用了 verify_lane（接线存在）")
    if cap.payload:
        ok(cap.payload.get("base") == mb,
           "喂给白名单的 base == merge-base(main, %s)（修复本体）" % branch)
        ok(cap.payload.get("base") != base_ref,
           "喂给白名单的 base 不再是钉死的 base_ref（KI-010 不复发）")
        ok(cap.payload.get("require_base") is True, "require_base=true 保持（fail-closed 语义不松）")
        ok(cap.payload.get("write_set") == ["server/dsh/temporal-poc/agent_activities.py"],
           "工单 write_set 原样透传")

    items = [c.get("item", "") for c in res.checks]
    ok(any("verify_lane" in it for it in items),
       "merge-base 成功路径走「泳道内 verify_lane code 绿灯」项（非 fail-closed 项）")
    ok(not any(it.startswith("写集白名单基线") for it in items),
       "merge-base 成功路径未触发 fail-closed 红项")

    return finish()


if __name__ == "__main__":
    sys.exit(main())
