#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260922-18 共享夹具：真 git 项目仓/泳道 worktree 的构造与观测（纯 stdlib+git CLI）。

供同票两场景共用（sc_main_sync_gate_evidence / sc_main_sync_incident_shapes）。
一切产物落 tempfile 临时目录，零真仓接触、零 docker、零端口、不触 3099/7233。

泳道 worktree 由本模块直接 `git worktree add -b lane/<票>` 自建（注入手段）——
被测对象是「验证前主同步 main」的编排与事故形态终态，不是建道活动本身
（prepare_workspace 的 dir 模式在编排场景里由 workflow 真跑，worktree 建法不锚）。
"""
import subprocess
from pathlib import Path


def git_ok() -> bool:
    """git 在场门（缺失=环境红，场景 exit 2）。"""
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


def git(*args, cwd, check=True):
    """git CLI 单点：返回 CompletedProcess；check=True 时非零抛 RuntimeError（点名命令）。"""
    p = subprocess.run(["git", "-C", str(cwd)] + list(args),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s 失败（cwd=%s）: %s"
                           % (" ".join(args), cwd, (p.stderr or p.stdout or "")[-300:]))
    return p


def commit_files(repo, files: dict, msg: str, author="fixture <fx@example.invalid>"):
    """在 repo 当前分支写文件并提交（files: {相对路径: 内容}；内容 None=删除）。"""
    for rel, content in files.items():
        fp = Path(repo) / rel
        if content is None:
            if fp.exists():
                fp.unlink()
        else:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("-c", "user.name=fixture", "-c", "user.email=fx@example.invalid",
        "commit", "-m", msg, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def lane_branch(ticket):
    """The lane branch name for a ticket ("lane/<ticket>") — single naming point.

    t261016-13: the main-sync guard judges the NAMED branch (unreadable or behind
    HEAD = refused by name), so any caller injecting prepare/settle must pass the
    lane's real branch, never a hardcoded literal."""
    return "lane/" + ticket


def make_repo(path):
    """新项目仓：git init + 初始提交（README.md）。返回仓路径。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.name", "fixture", cwd=path)
    git("config", "user.email", "fx@example.invalid", cwd=path)
    commit_files(path, {"README.md": "fixture repo\n",
                        ".gitignore": ".lane/\n"}, "init")
    return path


def make_lane(repo, ticket, base=None):
    """自项目仓建泳道 worktree（分支 lane/<票>，基点=base 或 main HEAD；main 缺位回落 HEAD）。

    泳道落 `<repo>/.lane/<票>`——引擎 _lane_repo_root 的项目归属路径约定（t260903-10），
    settle_lane 的 scope 解析据此认主（否则回落引擎仓=落错树）。"""
    lane = Path(repo) / ".lane" / ticket
    lane.parent.mkdir(parents=True, exist_ok=True)
    if not base:
        base = branch_tip(repo) or head_repo(repo)
    git("worktree", "add", "-b", "lane/%s" % ticket, str(lane), base, cwd=repo)
    return lane


def head_repo(repo):
    """仓当前 HEAD（worktree 外的主仓用）。"""
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def head(wt):
    return git("rev-parse", "HEAD", cwd=wt).stdout.strip()


def short(wt):
    return git("rev-parse", "--short", "HEAD", cwd=wt).stdout.strip()


def parent_count(commit, wt):
    return len(git("rev-list", "--parents", "-n", "1", commit, cwd=wt).stdout.split()) - 1


def merge_commits(wt):
    """泳道历史里双亲 merge commit 的 sha 清单（first-parent 全历史）。"""
    out = git("rev-list", "--first-parent", "--parents", "HEAD", cwd=wt).stdout
    return [ln.split()[0] for ln in out.splitlines() if len(ln.split()) >= 3]


def is_ancestor(anc, desc, wt):
    return git("merge-base", "--is-ancestor", anc, desc, cwd=wt, check=False).returncode == 0


def merge_base(x, y, wt):
    p = git("merge-base", x, y, cwd=wt, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def porcelain(wt):
    return git("status", "--porcelain", cwd=wt).stdout


def ls_files(wt, pathspec):
    return git("ls-files", "--", pathspec, cwd=wt).stdout.splitlines()


def branch_tip(repo, branch="main"):
    p = git("rev-parse", "--verify", branch, cwd=repo, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def drop_branch(repo, branch="main"):
    """删分支（先 detach HEAD 以允许删当前分支）——main 不可达形态构造。"""
    git("checkout", "--detach", cwd=repo)
    git("branch", "-D", branch, cwd=repo)
