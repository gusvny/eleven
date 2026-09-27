#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主同步的事故形态回归（t260922-18，灰盒 L2/L3，真 git 临时仓直调注入，秒级零 docker）。

intent（登记于 run_scenarios.py SCENARIOS）：泳道验证前「worker 并 main 进泳道」
成为每轮机械验证前的例行动作后，两类既有事故形态必须在该动作上不复发（用户可
感知终态，非活动回执字段形状）：

- KI-090 形态①（main 历史污染借合并复发）：main 曾误提交 `.sandbar/` 类状态路径
  后又清账删除，分叉点早于清账删除的泳道收到这次删除 → 主同步自动合并成功：
  merge commit 落盘（双亲）、泳道工作区 porcelain 净、该路径从泳道 tracked 清空
  ——不再出现「待删 tracked 文件挂脏工作区拖红验证」的复发形态；
- KI-090 形态②的一般面（modify/delete 相撞）：泳道侧改过某路径 + main 删除 →
  主同步留冲突现场（conflict_files 点名该文件），按既有消解约定去掉文件后
  settle `add -A` 代提交自愈 → 工作区净、路径清空（引擎可自解，不需要人工清
  写集外账）；
- KI-082 基点追平（老票落后 main 的清偿面）：分叉点落后 main 多个提交的泳道经
  主同步后 merge-base(main, HEAD)==main tip（验证树基点=main tip，不再「每轮集测
  在旧基线上跑」）；紧接第二次同步 HEAD 逐字节不动（已追平=幂等零动作，不产生
  新提交）。

分界（防 intent 级重复）：
- developer UT（server/engine/tests/test_t260922_18_main_sync.py）锚活动回执的
  新键形状（up_to_date/target_sha/lane_head）与纯函数矩阵；本场景断言落在 git
  可观测系统终态（工作区/树/基点/幂等），直调活动只是注入手段，不锚任何新回执键
  （浅绑定：回执形状重构不破本场景）；
- selfcheck_conflict_resolution（developer 侧自检）守既有 merge_check 冲突回路
  闭环；本条守主同步动作上的事故形态终态，不重放其决策矩阵；
- t260922-12 场景族守结果台账采信边界；本条不触台账断言。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
git 缺失 = ENV_FAIL exit 2（本场景全部子用例依赖真 git，无 stdlib 替代）。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_main_sync_fixture import (
    branch_tip, commit_files, drop_branch, git, git_ok, head, is_ancestor,
    ls_files, make_lane, make_repo, merge_base, parent_count, porcelain,
)

# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接（同 t260916-20 手法）。
import os
os.environ.setdefault("SANDBAR_TARGET_HOST", "127.0.0.1:9")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "engine"))

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def prep(lane):
    """直调真活动（注入手段）：worker 视角在泳道跑 git merge main。"""
    import agent_activities as aa
    from shared import ConflictPrepArgs
    import asyncio
    return asyncio.run(aa.prepare_conflict_resolution(ConflictPrepArgs(
        ticket_id="t260922-18-sc", worktree=str(lane), branch="lane/t260922-18-sc",
        base_ref="main")))


def settle(lane, round_no=1):
    import agent_activities as aa
    from shared import ConflictSettleArgs
    import asyncio
    return asyncio.run(aa.settle_conflict_resolution(ConflictSettleArgs(
        ticket_id="t260922-18-sc", worktree=str(lane), branch="lane/t260922-18-sc",
        base_ref="main", round_no=round_no)))


POLLUTED = ".sandbar/routes-migration-x/README.md"


def main() -> int:
    if not git_ok():
        print("ENV_FAIL: git 缺失，事故形态子用例全部不可验（exit 2）")
        return 2
    td = tempfile.mkdtemp(prefix="t26092218-shapes-")

    print("== 形态① KI-090：main 清账删除经主同步自动合入，工作区净不再挂脏")
    repo1 = make_repo(td + "/r1")
    poll_c = commit_files(repo1, {POLLUTED: "stale state\n"}, "误提交状态目录")
    wipe_c = commit_files(repo1, {POLLUTED: None}, "清账删除状态目录")
    lane1 = make_lane(repo1, "t260922-18-shapes-a", base=poll_c)  # 分叉点早于清账删除
    ok(POLLUTED in " ".join(ls_files(lane1, ".sandbar/")),
       "① 前提：老泳道仍 tracked 该路径（KI-090 现场形态）")
    r = prep(lane1)
    ok(r.ok, "① 主同步自动合并成功（ok=True）", r.error)
    ok(not porcelain(lane1).strip(), "① 泳道工作区 porcelain 净（待删文件不再挂脏）",
       porcelain(lane1)[:200])
    ok(not ls_files(lane1, ".sandbar/"), "① 该路径从泳道 tracked 清空（删除合入泳道历史）")
    ok(is_ancestor(wipe_c, head(lane1), lane1), "① main 清账提交进入泳道历史")
    ok(head(lane1) != poll_c, "① 泳道 HEAD 已前进（快进或合并皆可：泳道无票提交时合法快进）")

    print("== 形态② modify/delete 相撞 → 冲突现场 → 消解 settle 自愈（中性路径）")
    # 注：用中性路径锁「冲突子回路自愈」的一般承诺面。`.sandbar/` 特例不在此锁：
    # settle_conflict_resolution 的 _SETTLE_RESET_PATHS=(".dsh", ".suyou", ".sandbar")  # naming-compat（引擎常量原文引用，非读侧旧名）
    # 会把 `.sandbar/` 下暂存变更回退（协调目录永不入库的既定防），该特例形态经
    # 消解回路不可自愈——已作为新故障线索上报结果文件（KI-090 处置方向②未实施
    # +主同步扩大暴露面），本场景只定位不修复。
    NOTE = "docs/legacy-note.md"
    repo2 = make_repo(td + "/r2")
    poll_c2 = commit_files(repo2, {NOTE: "legacy text\n"}, "旧历史提交普通路径")
    lane2 = make_lane(repo2, "t260922-18-shapes-b", base=poll_c2)
    commit_files(lane2, {NOTE: "lane touched it\n"}, "泳道侧改过该路径")
    commit_files(repo2, {NOTE: None}, "main 侧删除该路径")
    r2 = prep(lane2)
    ok(r2.ok and NOTE in (r2.conflict_files or []),
       "② modify/delete 留冲突现场且点名该文件", str(r2.conflict_files))
    # 消解=agent 只编辑工作区（unlink），不写 .git（真实分工：agent 无 git 元数据权）
    (Path(lane2) / NOTE).unlink()
    s2 = settle(lane2)
    ok(s2.ok, "② settle 代提交自愈（ok=True）", s2.error)
    ok(not porcelain(lane2).strip(), "② 消解落盘后工作区净")
    ok(not ls_files(lane2, NOTE), "② 路径清空（无残留 tracked 污染）")

    print("== 形态③ KI-082：落后 main 多提交的老泳道经主同步基点追平+幂等")
    repo3 = make_repo(td + "/r3")
    base_c = branch_tip(repo3)
    lane3 = make_lane(repo3, "t260922-18-shapes-c", base=base_c)
    commit_files(lane3, {"ticket_change.md": "票改动\n"}, "老票自己的改动（分叉成真）")
    tip0 = None
    for i in range(3):
        tip0 = commit_files(repo3, {"main_advance_%d.md" % i: "v%d\n" % i},
                            "main 第 %d 步前进" % (i + 1))
    before = head(lane3)
    ok(merge_base("main", before, lane3) == base_c,
       "③ 前提：泳道分叉点=旧基点（落后 main 3 提交，KI-082 现场）")
    r3 = prep(lane3)
    ok(r3.ok, "③ 主同步成功", r3.error)
    after = head(lane3)
    ok(merge_base("main", after, lane3) == tip0,
       "③ 基点追平：merge-base(main, HEAD)==main tip（验证树不再落旧基线）")
    ok(not porcelain(lane3).strip(), "③ 追平后工作区净")
    r3b = prep(lane3)
    ok(r3b.ok and head(lane3) == after,
       "③ 二次同步幂等：HEAD 逐字节不动（已追平=零动作零新提交）")
    ok(parent_count(head(lane3), lane3) == 2,
       "③ 追平以双亲 merge commit 落盘（票提交+main tip）")

    print("== 红线：夹具自检（防假绿）")
    ok(not porcelain(make_repo(td + "/r4")).strip(), "红线：干净夹具仓 porcelain 净（夹具自身无误）")
    drop_branch(repo3)
    ok(branch_tip(repo3) == "", "红线：drop_branch 生效（main 不可达构造可用）")

    print("PASS=%d FAIL=%d" % (pass_n, fail_n), file=sys.stderr)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
