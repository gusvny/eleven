#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-19 集成测试共享夹具与助手（非 sc_ 前缀＝共享代码，不进 SCENARIOS）。

被测面＝**路径闸 blocked 死结三修**（工单 t260916-19，实案=dengzhufpv t260916-11）：
  B 越权处置按 porcelain 状态分流（?? 挪档 / M 回滚+diff 留档 / D·staged·rename 拒绝+人处 /
    protected 不动），处置后一轮复判使「下一次 settle 不再被同批文件复判」；
  C 声明=执法（arbitrate 测试面收 integration/ 顶层 sc_*.py|.mjs 与 README.md 登记表，
    lint_tests.py 共享工具仍不放行）；
  D 证据面（拒绝回执 judged_files=本次实际判定脏清单全量，不止违规项）。

夹具纪律（沿 t260914-01 口径）：
- 一切 git 仓/泳道在测试 tmp 目录自建，不代用户建仓、不碰真实项目数据；
- 注入一律「真实 git 态」（真 tracked 修改/真删除/真暂存/真注册 worktree），不 monkeypatch 产品实现；
- 本目录文件零 dot 目录名字面量（命名守卫 t260907-04 扫描面纪律），dot 名一律取 shared 真源。

三态契约（t260904-12）：只有 pass/fail/env_fail；环境缺失一律 ENV_FAIL exit 2。
实现落地前新契约腿红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"

passed = 0
failed = 0
env_fail_n = 0
na_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)
    return bool(cond)


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)
    sys.exit(2)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (passed, failed, env_fail_n, na_n))
    return 1 if failed else (2 if env_fail_n else 0)


# ---------------------------------------------------------------- git 夹具

def git(args, cwd):
    return subprocess.run(["git"] + [str(a) for a in args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)


def git_ok(args, cwd):
    p = git(args, cwd)
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def tmpdir(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def rmtree(*paths):
    import shutil
    for p in paths:
        shutil.rmtree(str(p), ignore_errors=True)


# 泳道分叉点基线（面判定/受保护闸/合法面的真实相对路径形态）。
# 覆盖四类面：非测试面普通文件（docs/、notes/…）、受保护真源（docs/design）、
# 测试面（tests/）、integration 顶层（本票 C 修的声明=执法面）。
BASE = {
    "README.md": "# baseline\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/kb.md": "kb baseline\n",
    "notes/legacy.md": "legacy note\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "tests/legit.md": "legit note\n",
    "integration/lint_tests.py": "# shared lint tool baseline\n",
    "integration/README.md": "# scenario registry baseline\n",
}


def mk_lane(prefix, base=None):
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, mainrepo, lane, 分叉sha)。

    泳道按项目路径约定落在 <主仓>/.lane/<票> 内（t260914-01 同款）——settle_lane 的
    归属仓解析走 worktree gitfile→主仓 gitdir；泳道建成主仓兄弟目录会回落到进程
    cwd 的仓锚而被拒（t260901-16 拒绝回退主树口径，本夹具实测撞过）。
    """
    tmp = tmpdir(prefix)
    main = tmp / "main"
    main.mkdir(parents=True, exist_ok=True)
    for rel, content in (base if base is not None else BASE).items():
        p = main / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(["init", "-q"], main)
    git(["config", "user.email", "ut@example.invalid"], main)
    git(["config", "user.name", "ut"], main)
    git(["add", "-A"], main)
    git(["commit", "-qm", "baseline"], main)
    fork = head_sha(main)
    lane = main / ".lane" / "t260916-19"
    ok, out = git_ok(["worktree", "add", "-q", "-b", "lane/t260916-19", lane], main)
    if not ok:
        raise RuntimeError("worktree add 失败: %s" % out[-300:])
    return tmp, main, lane, fork


def head_sha(tree):
    p = git(["rev-parse", "HEAD"], tree)
    return p.stdout.strip() if p.returncode == 0 else ""


def head_count(tree):
    p = git(["rev-list", "--count", "HEAD"], tree)
    return int(p.stdout.strip() or -1) if p.returncode == 0 else -1


def committed_names(tree, ref="HEAD"):
    p = git(["show", "--pretty=format:", "--name-only", ref], tree)
    return sorted(ln.strip() for ln in p.stdout.splitlines() if ln.strip())


def read_file(tree, rel):
    p = Path(tree) / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def status_entries(tree, shared):
    """`git status --porcelain -z -- . <排除协调目录>` → [(XY, path)]（与引擎同路径口径）。"""
    ps = [".", ":!.dsh", ":!" + shared.DOT_DIR_NEW, ":!.suyou"]  # naming-compat: .suyou=老泳道协调目录（镜像引擎 SETTLE_PATHSPEC 同口径排除，shared.DOT_DIR_OLD）
    p = git(["status", "--porcelain", "-z", "--"] + ps, tree)
    if p.returncode != 0:
        return None
    out = []
    for ent in p.stdout.split("\0"):
        if len(ent) >= 4 and ent[2] == " ":
            out.append((ent[:2], ent[3:]))
    return out


def apply_check(lane, diff_text):
    """留档 diff 可还原性（git apply --check；真还原由人决定，场景只验可还原）。"""
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".diff", delete=False,
                                encoding="utf-8") as f:
        f.write(diff_text)
        tmp = f.name
    try:
        return git_ok(["apply", "--check", tmp], lane)
    finally:
        import os
        os.unlink(tmp)


# ---------------------------------------------------------------- 引擎模块

def engine_modules():
    """装载引擎模块（需引擎 venv 的 temporalio）。返回 ((shared, aa), "") 或 (None, why)。

    调用前必须已钉死 SANDBAR_TARGET_HOST（shared 在 import 期读它）——场景文件顶部红线桩。
    """
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    try:
        import shared  # noqa: E402
        import agent_activities as aa  # noqa: E402
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    return (shared, aa), ""


# ---------------------------------------------------------------- activity 直调

def settle(shared, aa, lane, ticket, stage, gen, base_ref, write_set=None):
    """直调 join 点 settle activity（公开组件契约面，实案死结发生的同一入口）。

    返回 SettleLaneResult（note/error/lane_commits/gate_refusal）；异常照原样上抛。
    """
    args = shared.SettleLaneArgs(ticket_id=ticket, worktree=str(lane),
                                 stage_id=stage, gen=gen,
                                 write_set=list(write_set if write_set is not None
                                                else ["integration/"]),
                                 base_ref=str(base_ref),
                                 path_gate=True,
                                 authorizations=[])
    return asyncio.run(aa.settle_lane(args))


def quarantine_root(lane, shared):
    """隔离档根（既有 lane_dot_path(cwd,'quarantine') 先例位置，真源取 shared dot 名）。"""
    return Path(lane) / shared.DOT_DIR_NEW / "quarantine"


def archive_find(root, name):
    """在隔离档根下按文件名尾段找留档件（不锚具体档目录名——那是实现细节，
    公开契约只有「隔离档在引擎 dot 目录 quarantine 下、点名在回执、留档可还原」）。"""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob(name) if p.is_file())
