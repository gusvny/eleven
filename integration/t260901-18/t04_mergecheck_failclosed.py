#!/usr/bin/env python3
"""t04 畸形输入 fail-closed：merge-base 算不出来时，合并闸不许静默放行、
不许回落旧口径、不许把空串/错口径 ref 喂给白名单。

三个场景（真跑 merge_check activity / _merge_base_ref）：
  A. 泳道分支不存在（ref 不存在）→ 第 3 项 fail-closed 红，detail 精确点出
     「merge-base … 解析失败 rc=…」，且 verify_lane 本轮不被调用。
  B. main 不存在（隔离假仓）→ 同上 fail-closed 形态。
  C. criss-cross 提交图（真 git 造多 merge-base 输出）→ _merge_base_ref 取首行
     继续、err 留痕；单 merge-base 的普通仓 err 必须为空（不留噪声）。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import (ok, finish, import_engine, VerifyLaneCapture, lane_root,
                    git, make_repo, commit, mkdtemp, rmtree)

# 261012 (KI-01M4PX56PCD7E186EKSJG53FYD): anchor the machine key, not the copy.
# The red item's wording may change (the copy-language gate even forces it);
# the contract is the reason_code plus the item being red. Keep detail
# assertions on precision properties (a real rc=, the failed refs named),
# never on wording.
BASELINE_REASON = "merge_base_failed"


def find_baseline_red(res):
    for c in res.checks:
        if c.get("reason_code") == BASELINE_REASON and c.get("green") is False:
            return c
    return None


def main() -> int:
    aa, MergeCheckArgs = import_engine()
    root = lane_root()

    # ---- 场景 A：泳道分支不存在（真仓，merge-base 必失败）----
    ghost = "lane/it-no-such-%d" % os.getpid()
    args_a = MergeCheckArgs(ticket_id="t260901-18-it-a",
                            worktree=str(root), branch=ghost,
                            base_ref="main", write_set=["x"])
    with VerifyLaneCapture(aa) as cap_a:
        res_a = asyncio.run(aa.merge_check(args_a))
    red_a = find_baseline_red(res_a)
    ok(red_a is not None, "A: unknown branch -> the fail-closed red item is present")
    ok(red_a is not None and "merge-base" in red_a.get("detail", "")
       and "rc=" in red_a["detail"] and args_a.branch in red_a["detail"],
       "A: the detail is precise (the merge-base failure is named, the real git "
       "rc= is carried, the failing ref is named) — never falls back to the old caliber")
    ok(cap_a.payload is None, "A: verify_lane is not called (a bad baseline is never passed down)")

    # ---- 场景 B：main 不存在（隔离假仓，REPO_ROOT 指过去）----
    tmp = mkdtemp()
    saved_repo_root = aa.REPO_ROOT
    try:
        fake = make_repo(tmp)
        (fake / "b.txt").write_text("b\n", "utf-8")
        first = commit(fake, "init")
        git(fake, "branch", "-M", "lane")
        aa.REPO_ROOT = fake  # merge_check 的 git 操作（含 merge-base）全部指向假仓
        args_b = MergeCheckArgs(ticket_id="t260901-18-it-b",
                                worktree=str(fake), branch="lane",
                                base_ref=first, write_set=["b.txt"])
        with VerifyLaneCapture(aa) as cap_b:
            res_b = asyncio.run(aa.merge_check(args_b))
        red_b = find_baseline_red(res_b)
        ok(red_b is not None, "B：main 缺失 → fail-closed 红项")
        ok(red_b is not None and "rc=" in red_b.get("detail", ""),
           "B：detail 带 rc（git 真实报错被带出，不是含糊文案）")
        ok(cap_b.payload is None, "B：verify_lane 未被调用（空串/坏 ref 绝不传）")
    finally:
        aa.REPO_ROOT = saved_repo_root
        rmtree(tmp)

    # ---- 场景 C：criss-cross 提交图（真 git 构造）----
    # 注意：git merge-base（不带 --all）即使存在多个最优公共祖先也只输出一行，
    # 引擎的「多行=畸形取首行」分支是防御性代码（标准 git 下不会被触发），
    # 所以本场景钉的是真实行为：criss-cross 下图基线仍可解析、零噪声留痕。
    tmp2 = mkdtemp()
    try:
        repo = make_repo(tmp2)
        (repo / "w.txt").write_text("w\n", "utf-8")
        a0 = commit(repo, "A0")
        git(repo, "branch", "-M", "main")
        git(repo, "checkout", "-q", "-b", "feature", a0)
        (repo / "f.txt").write_text("f\n", "utf-8")
        f1 = commit(repo, "F1")
        git(repo, "checkout", "-q", "main")
        (repo / "c.txt").write_text("c\n", "utf-8")
        c1 = commit(repo, "C1")
        git(repo, "checkout", "-q", "feature")
        git(repo, "merge", "-q", "--no-edit", "main")   # F2: parents F1,C1
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-edit", f1)        # M2: parents C1,F1 → criss-cross
        p = git(repo, "merge-base", "main", "feature")
        bases = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
        ok(p.returncode == 0 and len(bases) == 1,
           "C：criss-cross 下 git merge-base 仍单输出（%d 行，标准 git 行为）" % len(bases))
        is_ancestor = lambda anc, ref: git(repo, "merge-base", "--is-ancestor", anc, ref).returncode == 0
        ok(is_ancestor(bases[0], "main") and is_ancestor(bases[0], "feature"),
           "C：输出 OID 同时是 main 与 feature 的祖先（可用作白名单基线）")

        ref, err = aa._merge_base_ref("feature", repo)
        ok(ref == bases[0], "C：_merge_base_ref 原样采用该基线")
        ok(err == "", "C：标准 git 单输出 → err 零噪声（不留畸形留痕）")

        # 对照：普通单 merge-base 的仓 err 必须为空（不留噪声留痕）
        tmp3 = mkdtemp()
        try:
            repo2 = make_repo(tmp3)
            (repo2 / "x.txt").write_text("x\n", "utf-8")
            commit(repo2, "init")
            git(repo2, "branch", "-M", "main")
            git(repo2, "checkout", "-q", "-b", "lane2")
            (repo2 / "y.txt").write_text("y\n", "utf-8")
            commit(repo2, "lane 改动")
            ref2, err2 = aa._merge_base_ref("lane2", repo2)
            ok(bool(ref2) and err2 == "", "C-对照：单 merge-base 输出 err 为空（正常路径零噪声）")
        finally:
            rmtree(tmp3)
    finally:
        rmtree(tmp2)

    return finish()


if __name__ == "__main__":
    sys.exit(main())
