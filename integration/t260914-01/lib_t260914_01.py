#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260914-01 集成测试共享夹具与助手（非 sc_ 前缀＝共享代码，不进 SCENARIOS）。

被测面＝**结算面三修**（工单 t260914-01，症状＝多仓老名泳道每次重跑都在 create_plan
段被判「活动故障」，而 agent 产物其实是好的）：
  ① 判脏口径含老名协调目录（老名泳道里协调目录产物不得被算成脏改）；
  ② 空提交＝正常工作态（可辨回执，绝不升级成基础设施故障）；
  ③ 多仓泳道清单落「协调目录解析真源」（新泳道落新名、存量老名泳道原地粘滞）。

夹具纪律（沿本项目既有口径）：
- 一切 git 仓/泳道在测试 tmp 目录自建，不代用户建仓、不碰真实项目数据；
- 注入优先「真实 git 态」（index.lock 在场 / pre-commit hook 拒绝 / worktree 真注册），
  不用 monkeypatch 产品实现；唯一的显式形态注入＝把 settle 的判脏清单常量换回修复前
  口径以重演「判脏非空但暂存区空」现场（见 sc_settle_empty_staging_locks.py）；
- 协调目录名一律取 shared.DOT_DIR_OLD / DOT_DIR_NEW，本文件与场景文件零 dot 名字面量
  （命名守卫 t260907-04 的扫描面纪律）。

三态契约（t260904-12）：只有 pass/fail/env_fail；环境缺失一律 ENV_FAIL exit 2。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
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
    """环境缺失：一律 ENV_FAIL exit 2（本套场景无 stdlib 替代腿——直调 activity）。"""
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)
    sys.exit(2)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (passed, failed, env_fail_n, na_n))
    return 1 if failed else (2 if env_fail_n else 0)


def tmpdir(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


def rmtree(*paths):
    for p in paths:
        shutil.rmtree(str(p), ignore_errors=True)


# ---------------------------------------------------------------- git 夹具

def git(args, cwd):
    return subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)


def git_ok(args, cwd):
    p = git(args, cwd)
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def init_repo(path, files=None, gitignore=()):
    """建基线仓（本地 identity 落地：prepare 的身份检查与代落盘 commit 都要它）。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    git(["config", "user.email", "ut@example.invalid"], path)
    git(["config", "user.name", "ut"], path)
    for rel, text in (files or {"README.md": "baseline\n"}).items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    if gitignore:
        (path / ".gitignore").write_text("\n".join(gitignore) + "\n", encoding="utf-8")
    git(["add", "-A"], path)
    git(["commit", "-qm", "baseline"], path)
    return path


def make_lane_worktree(repo, lane, branch):
    """按项目路径约定把泳道容器建成 repo 的已注册 worktree（<proj>/.lane/<票>）。"""
    lane.parent.mkdir(parents=True, exist_ok=True)
    ok, out = git_ok(["worktree", "add", "-b", branch, str(lane), "HEAD"], repo)
    if not ok:
        raise RuntimeError("worktree add 失败: %s" % out[-300:])
    return lane


def head_count(tree):
    p = git(["rev-list", "--count", "HEAD"], tree)
    return int(p.stdout.strip() or -1) if p.returncode == 0 else -1


def head_sha(tree):
    p = git(["rev-parse", "HEAD"], tree)
    return p.stdout.strip() if p.returncode == 0 else ""


def committed_names(tree, ref="HEAD"):
    """某 commit 的改动文件清单（相对该树根）——代落盘内容面的可点名校验。"""
    p = git(["show", "--pretty=format:", "--name-only", ref], tree)
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def settle_pathspec(shared):
    """判脏路径清单（与引擎同口径；名字取 shared 真源，本文件零 dot 名字面量）。"""
    return [".", ":!.dsh", ":!" + shared.DOT_DIR_NEW, ":!" + shared.DOT_DIR_OLD]


def dirty_paths(tree, shared, pathspec=None):
    """`git status --porcelain -z -- . <排除…>` 解析（与引擎判脏同口径）。"""
    ps = list(pathspec if pathspec is not None else settle_pathspec(shared))
    p = git(["status", "--porcelain", "-z", "--"] + ps, tree)
    if p.returncode != 0:
        return None
    out = []
    for entry in p.stdout.split("\0"):
        if len(entry) > 3:
            out.append(entry[3:])
    return out


# ---------------------------------------------------------------- 引擎模块

def engine_modules():
    """装载引擎模块（需引擎 venv 的 temporalio）。返回 ((shared, aa), "") 或 (None, why)。

    调用前必须已钉死 SANDBAR_TARGET_HOST（shared 在 import 期读它）——各场景文件顶部
    有红线桩，本函数不再改 env。
    """
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    try:
        import shared  # noqa: F401,E402
        import agent_activities as aa  # noqa: F401,E402
    except Exception as e:  # ImportError / 依赖缺失
        return None, "%s: %s" % (type(e).__name__, e)
    return (shared, aa), ""


def coordination_dir(shared, base, new=True):
    return Path(base) / (shared.DOT_DIR_NEW if new else shared.DOT_DIR_OLD)


def write_stage_artifact(shared, tree, name="stage_create_plan_gen3.json", new=False):
    """在 tree 的协调目录写一个「结果/回执」产物（该段只产出协调目录产物的形态）。"""
    d = coordination_dir(shared, tree, new=new)
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(json.dumps({"status": "ok", "note": "ut artifact"}, ensure_ascii=False),
                 encoding="utf-8")
    return f


def write_manifest(shared, lane, entries, legacy=False):
    """夹具造清单：legacy=True 直写老名镜像位（存量老泳道形态）；False 走解析位真源。"""
    if legacy:
        p = Path(lane) / shared.DOT_DIR_OLD / shared.MULTI_MANIFEST_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
    else:
        p = shared.multi_manifest_path(lane, create=True)
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def manifest_at(shared, lane, legacy_fallback=False):
    return shared.multi_manifest_path(lane, legacy_fallback=legacy_fallback)


# ---------------------------------------------------------------- activity 直调

def settle(shared, aa, tree, ticket, stage="create_plan", gen=0, **kw):
    """直调 join 点 settle activity（公开组件契约面；异常照原样上抛给调用方判定）。"""
    args = shared.SettleLaneArgs(ticket_id=ticket, worktree=str(tree),
                                 stage_id=stage, gen=gen, **kw)
    return asyncio.run(aa.settle_lane(args))


def prepare(shared, aa, lane, project_root, entries, write_set, ticket):
    """直调 prepare_workspace activity（多仓通道：repo_worktrees 明细＝真源）。"""
    prep = shared.WorkspacePrep(ticket_id=ticket,
                                workspace={"type": "worktree", "path": str(lane)},
                                write_set=list(write_set),
                                project_root=str(project_root),
                                repo_worktrees=list(entries))
    return asyncio.run(aa.prepare_workspace(prep))


def mixed_project(prefix, gitignore=("repo_a/",)):
    """混合形态项目：根仓（知识库仓）＋一层子仓 repo_a（dengzhufpv 形态）。

    缺省 .gitignore 忽略子仓目录＝契约 advisory④ 的夹具落地（根树=泳道容器本身时，
    成员树落在根仓工作区内，必须被忽略，否则根仓 status 把成员 worktree 当未跟踪目录，
    settle 会把它当 embedded repo 暂存成 gitlink 进历史——实测形态，见票据报告遗留项）。
    """
    root = init_repo(tmpdir(prefix), files={"docs/kb.md": "kb\n"}, gitignore=gitignore)
    init_repo(root / "repo_a", files={"src/a.py": "a = 1\n"})
    return root


def absent(d, key):
    """清单/回执 JSON 安全取值（畸形时判红而非抛）。"""
    if not isinstance(d, dict):
        return None
    return d.get(key)
