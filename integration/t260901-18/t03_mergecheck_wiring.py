#!/usr/bin/env python3
"""t03 merge_check 真实接线（端到端 activity 层），夹具树版。

用户场景保护：merge_check 第 3 项喂给白名单判定的 base，必须是当前
merge-base(main, 泳道分支)，不再是工单 create 时钉死的 base_ref——
这是 KI-010 修复的接线本体。本用例真跑泳道内的 merge_check activity：
真 git、真分支、真 merge-base 计算，只拦下它发给 verify_lane 的那一发
子进程并记录真实 payload（verify_lane 判定本身由 t01 真跑覆盖）。

t261016-11 (host order 261016, requirement 1): the old version passed
worktree=str(lane root); once t261012-09 landed the foreign-repair inside the
face (allow_commit=True), the case committed an engine repair INTO the tree
under test, deleting 1160 lines of landed line content while leaving the
importer - a whole round of false reds. The case now runs in a one-shot
fixture repo: real activity, real git, real merge-base, but the tree under
test is a tempfile clone. It also asserts the REAL lane tree is byte-identical
before/after and that no engine-authored commit exists anywhere. Red on
pre-fix code (payload base == pinned base_ref); green after.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import (ok, finish, import_engine, VerifyLaneCapture, lane_root,
                    git, make_repo, commit, mkdtemp, rmtree, write_verify_yaml,
                    tree_snapshot, assert_tree_untouched)


def main() -> int:
    aa, MergeCheckArgs = import_engine()
    root = lane_root()

    # t261016-11 1: snapshot of the tree under test; must be identical after
    snap_before = tree_snapshot(root)

    # One-shot fixture repo: main carries two commits, the ticket lane forks
    # at c1 and adds a real write-set file - merge-base(main, lane) = c1 and
    # the pinned base_ref = c0, the same old-vs-new distinguishable shape the
    # real-lane version had.
    tmp = mkdtemp()
    try:
        repo = make_repo(tmp)
        (repo / "seed.txt").write_text("c0\n", "utf-8")
        c0 = commit(repo, "c0 base")
        (repo / "seed2.txt").write_text("c1\n", "utf-8")
        c1 = commit(repo, "c1 base")
        git(repo, "checkout", "-q", "-b", "lane/it-t03", c1)
        (repo / "own").mkdir()
        (repo / "own" / "work.txt").write_text("ticket's own write\n", "utf-8")
        commit(repo, "c2 lane work")
        git(repo, "checkout", "-q", "main")
        (repo / "main-side.txt").write_text("main's own work\n", "utf-8")
        commit(repo, "c3 main work")
        git(repo, "checkout", "-q", "lane/it-t03")

        branch = "lane/it-t03"
        mb = git(repo, "merge-base", "main", branch).stdout.strip()
        ok(bool(mb) and mb == c1, "merge-base(main, %s) exists (=c1)" % branch)
        base_ref = c0
        ok(base_ref != mb, "the pinned base_ref differs from the merge-base")
        write_verify_yaml(repo)
        commit(repo, "c4 fixture verify.yaml")  # committed: the worktree must stay clean

        # REPO_ROOT override (t04-B / t05-E pattern): every git operation inside
        # merge_check must target the FIXTURE, never the real lane tree
        saved_repo_root = aa.REPO_ROOT
        aa.REPO_ROOT = repo

        args = MergeCheckArgs(ticket_id="t260901-18-it",
                              worktree=str(repo), branch=branch,
                              base_ref=base_ref,
                              write_set=["own/work.txt"])

        with VerifyLaneCapture(aa) as cap:
            res = asyncio.run(aa.merge_check(args))
    finally:
        aa.REPO_ROOT = saved_repo_root

    ok(cap.payload is not None, "merge_check 第 3 项确实调用了 verify_lane（接线存在）")
    if cap.payload:
        ok(cap.payload.get("base") == mb,
           "喂给白名单的 base == merge-base(main, %s)（修复本体）" % branch)
        ok(cap.payload.get("base") != base_ref,
           "喂给白名单的 base 不再是钉死的 base_ref（KI-010 不复发）")
        ok(cap.payload.get("require_base") is True, "require_base=true 保持（fail-closed 语义不松）")
        ok(cap.payload.get("write_set") == ["own/work.txt"],
           "工单 write_set 原样透传")

    items = [c.get("item", "") for c in res.checks]
    ok(any("verify_lane" in it for it in items),
       "merge-base 成功路径走「泳道内 verify_lane code 绿灯」项（非 fail-closed 项）")
    # 261012 (KI-01M4PX56PCD): anchor the machine key, not the copy. This is the
    # reverse assertion; its positive control is t04 (same construct on the
    # failure path: the item IS present there), so a silent weakening is caught.
    ok(not any(c.get("reason_code") == "merge_base_failed" for c in res.checks),
       "the merge-base success path does not fire the fail-closed red item")

    # t261016-11 1: zero writes to the real tree + no engine-authored commit
    assert_tree_untouched(snap_before, tree_snapshot(root), "t03")
    # probe the FIXTURE repo, not the runner tree: at HEAD the root history
    # carries inherited incident commits (the afccced main-sync pulled the
    # measured bb73e620 lineage) that this run did not write — a root probe is
    # a false positive on history the case never produced.
    log = git(repo, "log", "--all", "--author=sandbar-engine",
              "--grep=engine repair", "--oneline", "-n", "1")
    ok(not (log.stdout or "").strip(),
       "no engine-repair commit authored by this run (probed on the fixture repo)")
    rmtree(tmp)  # after the probe: the fixture must be readable until judged

    return finish()


if __name__ == "__main__":
    sys.exit(main())
