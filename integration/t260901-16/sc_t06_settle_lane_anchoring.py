#!/usr/bin/env python3
"""T06 settle_lane 路径锚定修正锁（t260901-16 arbitrate 打回主修项）。

用户视角：并行分叉票的唯一落盘机会是汇合点 settle_lane——workflow 传的
worktree 是相对路径（如 ".worktrees/t260901-16"，相对主仓根）。修前它按
worker 进程 cwd（server/engine）解析，匹配不上已注册 worktree 后
**静默回退主树**：主树本来就干净 → 「无需代落盘」假绿，泳道产物全漏落盘
（第一轮集成测试 2 哨兵红实锤）。修正后：
  a. 相对路径按模块 REPO_ROOT 锚定（同 verify_review_gate / run_integration_tests）；
  b. 不是已注册 worktree 时 raise（拒绝回退主树），交 Temporal 重试/上层可见。
本环境无 temporalio，用桩模块导入真源码做函数级断言；REPO_ROOT 打桩为**自包含
迷你主仓**（tempfile 下 git init，t260904-12 乙段：消「需主库环境=ENV_FAIL」门，
泳道内可跑），fixture worktree 注册与 settle 代落盘语义全部锚定迷你仓；落盘动作用
monkeypatch 拦截（本测试不产生任何业务 commit，也不向工作空间外遗留任何东西——
finally 全终态清理）。

注入方式说明：agent_activities 是 `from shared import REPO_ROOT`（import 时拷贝），
但其消费点（settle_lane / _is_worktree_of）解析的是本模块全局名 aa.REPO_ROOT
（运行时动态查名），故 import 之后改 `aa.REPO_ROOT = MINI_ROOT` 即全量生效。
"""
import asyncio
import logging
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 被测真源码的锚点：场景文件所在仓根（泳道内跑=泳道根，主库跑=主库根）。
# 只用于 import 被测源码与源码结构锁断言，**不**锚定 fixture 注册/落盘语义。
SRC_ROOT = Path(subprocess.run(
    ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
    capture_output=True, text=True).stdout.strip())

# ---- 自包含迷你主仓：git init + 最小可注册结构（≥1 commit，worktree add 需要 HEAD） ----
MINI_ROOT = Path(tempfile.mkdtemp(prefix="sc-t06-mini-repo-"))
REL = ".worktrees/sc-t06-fixture"
WT = MINI_ROOT / REL


def _git_mini(*args):
    return subprocess.run(["git", "-C", str(MINI_ROOT)] + list(args),
                          capture_output=True, text=True)


def _bootstrap_mini_repo():
    r = _git_mini("init", "-q")
    if r.returncode != 0:
        raise RuntimeError("迷你仓 git init 失败: %s" % r.stderr.strip())
    _git_mini("config", "user.email", "sc-t06@example.invalid")
    _git_mini("config", "user.name", "sc-t06 fixture")
    (MINI_ROOT / "README.md").write_text("sc-t06 自包含迷你主仓 fixture\n", "utf-8")
    _git_mini("add", "README.md")
    r = _git_mini("commit", "-q", "-m", "fixture: minimal repo for settle_lane anchoring")
    if r.returncode != 0:
        raise RuntimeError("迷你仓首 commit 失败: %s" % r.stderr.strip())


def _teardown_mini_repo():
    # 全终态回收：worktree 注销 → 分支清理 → 临时仓整体删除（泄漏=红）
    _git_mini("worktree", "remove", "--force", str(WT))
    _git_mini("branch", "-D", "lane/sc-t06-fixture")
    shutil.rmtree(MINI_ROOT, ignore_errors=True)


try:
    _bootstrap_mini_repo()
    # fixture worktree 注册：与原场景同款（相对路径 .worktrees/<name> + lane/ 分支）
    r = _git_mini("worktree", "add", str(WT), "-b", "lane/sc-t06-fixture")
    if r.returncode != 0:
        raise RuntimeError("fixture worktree 注册失败: %s" % (r.stderr or r.stdout).strip())

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

    sys.path.insert(0, str(SRC_ROOT / "server" / "engine"))
    sys.path.insert(0, str(SRC_ROOT / "server"))
    sys.path.insert(0, str(SRC_ROOT / "server" / "tools"))
    import agent_activities as aa  # noqa: E402
    from shared import SettleLaneArgs  # noqa: E402

    fails = []

    # 生产 worker 视角：模块 REPO_ROOT=迷你主仓根（monkeypatch 注入，见头注释），
    # worktree 传相对主仓根的路径
    _orig_root = aa.REPO_ROOT
    aa.REPO_ROOT = MINI_ROOT
    try:
        # a1) 锚定后能认出已注册 worktree（修正生效的前提）
        if not aa._is_worktree_of(MINI_ROOT / REL):
            fails.append("%s/%s 应是已注册 worktree（夹具失效）" % (MINI_ROOT, REL))

        # a2) 旧缺陷复现：相对路径按 worker 进程 cwd（server/engine）解析
        #     → 匹配不上已注册 worktree（证明防的是真 bug，不是臆造场景）
        worker_cwd = SRC_ROOT / "server" / "engine"
        if aa._is_worktree_of((worker_cwd / REL)):
            fails.append("worker cwd 视角解析相对路径不应匹配 worktree（旧缺陷场景未复现）")

        # b1) settle_lane 现在按 REPO_ROOT 锚定相对路径：落盘收到正确 cwd（monkeypatch 拦截）
        captured = {}

        # t260907-06 票B：settle_lane 逐树化，settle 收 repo 锚（单仓=None 语义不变）
        def _fake_settle(cwd, ticket_id, stage_id, gen, repo=None):
            captured["cwd"] = Path(cwd)
            return "captured"

        _orig = aa._settle_worktree_lane
        aa._settle_worktree_lane = _fake_settle
        try:
            r = asyncio.run(aa.settle_lane(SettleLaneArgs(
                ticket_id="t260901-16", worktree=REL, stage_id="implement", gen=1)))
            if captured.get("cwd") != MINI_ROOT / REL:
                fails.append("settle_lane 未锚定到 %s，实际 %s" % (MINI_ROOT / REL, captured.get("cwd")))
            if r.note != "captured":
                fails.append("settle_lane 未走锚定后的落盘路径（note=%r）" % r.note)
        finally:
            aa._settle_worktree_lane = _orig

        # b2) 非注册路径 → raise，不再静默回退主树代落盘
        raised = None
        try:
            asyncio.run(aa.settle_lane(SettleLaneArgs(
                ticket_id="t260901-16", worktree=str(MINI_ROOT / "no-such-dir-t260901-16"),
                stage_id="implement", gen=1)))
        except RuntimeError as e:
            raised = str(e)
        if raised is None:
            fails.append("非注册路径应 raise（拒绝静默回退），实际正常返回")
        elif "回退" not in raised:
            fails.append("raise 信息应写明拒绝回退主树：%s" % raised[:120])

        # b3) 源码结构锁：锚定口径与拒绝回退在源里（防回归被顺手改掉）
        src = (SRC_ROOT / "server" / "engine" / "agent_activities.py").read_text("utf-8")
        body = src[src.index("async def settle_lane"):src.index("def _run_scenarios")]
        if "if not wt.is_absolute():" not in body or "REPO_ROOT / wt" not in body:
            fails.append("settle_lane 缺相对路径 REPO_ROOT 锚定")
        if "cwd = REPO_ROOT" in body:
            fails.append("settle_lane 仍保留静默回退主树（cwd = REPO_ROOT）")
    finally:
        aa.REPO_ROOT = _orig_root
finally:
    _teardown_mini_repo()

for f in fails:
    print("FAIL:", f)
print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (5 - len(fails), len(fails)))
sys.exit(0 if not fails else 1)
