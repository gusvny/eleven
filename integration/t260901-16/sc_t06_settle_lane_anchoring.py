#!/usr/bin/env python3
"""T06 settle_lane 路径锚定修正锁（t260901-16 arbitrate 打回主修项）。

用户视角：并行分叉票的唯一落盘机会是汇合点 settle_lane——workflow 传的
worktree 是相对路径（如 ".worktrees/t260901-16"，相对主仓根）。修前它按
worker 进程 cwd（server/dsh/temporal-poc）解析，匹配不上已注册 worktree 后
**静默回退主树**：主树本来就干净 → 「无需代落盘」假绿，泳道产物全漏落盘
（第一轮集成测试 2 哨兵红实锤）。修正后：
  a. 相对路径按模块 REPO_ROOT 锚定（同 verify_review_gate / run_integration_tests）；
  b. 不是已注册 worktree 时 raise（拒绝回退主树），交 Temporal 重试/上层可见。
本环境无 temporalio，用桩模块导入真源码做函数级断言；REPO_ROOT 打桩为主仓根
（= 生产 worker 视角），落盘动作用 monkeypatch 拦截（本测试不产生任何 commit）。
"""
import asyncio
import logging
import sys
import types
from pathlib import Path

import subprocess
HERE = Path(__file__).resolve().parent
MAIN_ROOT = Path(subprocess.run(             # git toplevel 锚定（宿主令 t260902：
    ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],   # 主仓/泳道/任意 cwd 皆正确）
    capture_output=True, text=True).stdout.strip())
WT = MAIN_ROOT / ".worktrees" / "sc-t06-fixture"
REL = ".worktrees/sc-t06-fixture"

# 前提检测（t260903-09 仲裁补，tests-fault 迭代）：本场景的 fixture worktree 注册
# 与 settle 代落盘语义都锚定**主库** REPO_ROOT——L22-24 的 git toplevel 锚定在
# linked worktree（工单泳道）内会解析到泳道根，fixture 注册路径与 settle 校验
# 口径错乱，泳道内跑必红（t260903-09 集成道实锤：settle_lane RuntimeError
# 「不是本仓库的已注册 worktree」）。主库 .git 是目录、worktree 的 .git 是
# gitfile，据此判环境：前提不备干净 SKIP 留因（全族执行契约），主库跑时守卫
# 照旧。不在泳道内改挂主库跑——那会让测试向工作空间外落盘。
if (MAIN_ROOT / ".git").is_file():
    print("SKIP settle-lane-anchoring：cwd 是 linked worktree（工单泳道），本场景需主库环境"
          "（fixture worktree 注册与 settle 代落盘语义锚定主库 REPO_ROOT），主库跑生效")
    print("SUMMARY pass=0 skip=1 fail=0")
    sys.exit(0)

subprocess.run(["git", "-C", str(MAIN_ROOT), "worktree", "add", str(WT),
                "-b", "lane/sc-t06-fixture"], capture_output=True, text=True)
sys.path.insert(0, str(HERE))

# ---- temporalio 桩：只为 import，defn 原样透传 ----
_mod = types.ModuleType("temporalio")
_act = types.ModuleType("temporalio.activity")


def _defn(fn=None, **kw):
    def d(f):
        return f
    return d(fn) if fn else d


_act.defn = _defn
_act.logger = logging.getLogger("stub")
sys.modules["temporalio"] = _mod
sys.modules["temporalio.activity"] = _act

sys.path.insert(0, str(MAIN_ROOT / "server" / "dsh" / "temporal-poc"))
sys.path.insert(0, str(MAIN_ROOT / "server"))
sys.path.insert(0, str(MAIN_ROOT / "server" / "tools"))
import agent_activities as aa  # noqa: E402
from shared import SettleLaneArgs  # noqa: E402

fails = []

# 生产 worker 视角：模块 REPO_ROOT=主仓根，worktree 传相对主仓根的路径
_orig_root = aa.REPO_ROOT
aa.REPO_ROOT = MAIN_ROOT
try:
    # a1) 锚定后能认出已注册 worktree（修正生效的前提）
    if not aa._is_worktree_of(MAIN_ROOT / REL):
        fails.append("%s/%s 应是已注册 worktree（夹具失效）" % (MAIN_ROOT, REL))

    # a2) 旧缺陷复现：相对路径按 worker 进程 cwd（server/dsh/temporal-poc）解析
    #     → 匹配不上已注册 worktree（证明防的是真 bug，不是臆造场景）
    worker_cwd = MAIN_ROOT / "server" / "dsh" / "temporal-poc"
    if aa._is_worktree_of((worker_cwd / REL)):
        fails.append("worker cwd 视角解析相对路径不应匹配 worktree（旧缺陷场景未复现）")

    # b1) settle_lane 现在按 REPO_ROOT 锚定相对路径：落盘收到正确 cwd（monkeypatch 拦截）
    captured = {}

    def _fake_settle(cwd, ticket_id, stage_id, gen):
        captured["cwd"] = Path(cwd)
        return "captured"

    _orig = aa._settle_worktree_lane
    aa._settle_worktree_lane = _fake_settle
    try:
        r = asyncio.run(aa.settle_lane(SettleLaneArgs(
            ticket_id="t260901-16", worktree=REL, stage_id="implement", gen=1)))
        if captured.get("cwd") != MAIN_ROOT / REL:
            fails.append("settle_lane 未锚定到 %s，实际 %s" % (MAIN_ROOT / REL, captured.get("cwd")))
        if r.note != "captured":
            fails.append("settle_lane 未走锚定后的落盘路径（note=%r）" % r.note)
    finally:
        aa._settle_worktree_lane = _orig

    # b2) 非注册路径 → raise，不再静默回退主树代落盘
    raised = None
    try:
        asyncio.run(aa.settle_lane(SettleLaneArgs(
            ticket_id="t260901-16", worktree=str(MAIN_ROOT / "no-such-dir-t260901-16"),
            stage_id="implement", gen=1)))
    except RuntimeError as e:
        raised = str(e)
    if raised is None:
        fails.append("非注册路径应 raise（拒绝静默回退），实际正常返回")
    elif "回退" not in raised:
        fails.append("raise 信息应写明拒绝回退主树：%s" % raised[:120])

    # b3) 源码结构锁：锚定口径与拒绝回退在源里（防回归被顺手改掉）
    src = (MAIN_ROOT / "server" / "dsh" / "temporal-poc" / "agent_activities.py").read_text("utf-8")
    body = src[src.index("async def settle_lane"):src.index("def _run_scenarios")]
    if "if not wt.is_absolute():" not in body or "REPO_ROOT / wt" not in body:
        fails.append("settle_lane 缺相对路径 REPO_ROOT 锚定")
    if "cwd = REPO_ROOT" in body:
        fails.append("settle_lane 仍保留静默回退主树（cwd = REPO_ROOT）")
finally:
    aa.REPO_ROOT = _orig_root

subprocess.run(["git", "-C", str(MAIN_ROOT), "worktree", "remove", "--force", str(WT)],
               capture_output=True, text=True)
subprocess.run(["git", "-C", str(MAIN_ROOT), "branch", "-D", "lane/sc-t06-fixture"],
               capture_output=True, text=True)

for f in fails:
    print("FAIL:", f)
print("SUMMARY pass=%d skip=0 fail=%d" % (5 - len(fails), len(fails)))
sys.exit(0 if not fails else 1)
