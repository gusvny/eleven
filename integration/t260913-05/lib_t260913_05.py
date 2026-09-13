#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260913-05 集成场景共享夹具（无 sc_ 前缀=共享代码，不进 SCENARIOS）。

本票主题=多仓泳道拆道逐仓化（`teardown_lane` 从单仓硬编码改为按 `_lane_scopes`
逐仓三清）。共享件：

- 三态断言契约（check/env_fail/summary，口径见 integration/README.md「执行契约」）；
- git 帮手（git/git_ok）与泳道夹具构造：
    build_project → 根仓+repo_a+repo_b 混合形态（根亦 git 仓、子仓真 git 仓）；
    make_lane     → <root>/.lane/<ticket> 泳道容器（根树 worktree）+ 成员仓 worktree
                    + 盘上清单镜像（.suyou/repo_worktrees.json；naming-compat：旧名
                    镜像路径存量欠账，读点消费引擎单一真源常量，不落裸字面量）
                    ——形态与 `_lane_scopes` 的消费面对齐；
- 拆道直调帮手 call_teardown：MergeArgs → asyncio.run(activity)，**字段名容忍**
  （repo_worktrees / scopes 两种命名皆可）——绑定浅，断言只锚回执契约与磁盘终态；
- 契约判读帮手：names_repo（逐仓点名是否落到**该仓**）、branch_lane_gone、
  worktree_has、residue_state。

夹具红线：一切 git/磁盘动作只落测试 tmp（<repo>/.sandbar/ 下，随场景 rmtree 自清），
不碰真实项目数据；调用方须先把 SANDBAR_TARGET_HOST 钉到不可达桩再 import 引擎模块，
本库自身不连任何 Temporal。
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name, flush=True)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)
    return bool(cond)


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    """套件输出约定（三态）：fail>0→1（产品红）；env_fail>0→2（环境红）；否则 0。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n),
          flush=True)
    if failed > 0:
        return 1
    if env_fail_n > 0:
        return 2
    return 0


# ---------- git / 磁盘帮手 ----------

def git(*args, cwd):
    """抛错版 git（夹具构造用；rc!=0 即场景自身缺陷，直接抛）。"""
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("git %s 失败 rc=%s: stderr=%r"
                             % (" ".join(args), p.returncode, (p.stderr or "")[-300:]))
    return p.stdout


def git_ok(*args, cwd):
    """不抛版 git：返回 (rc, stdout, stderr)。仓目录不在盘上=空结果（rc=127 哨兵），
    与「读不到注册/分支」同义——诊断帮手不得因被测的第三态自身炸掉。"""
    if not Path(cwd).is_dir():
        return 127, "", "repo dir missing: %s" % cwd
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def wait_until(fn, deadline_s, interval=2.0):
    """轮询至 fn() 为真或超时（fn 抛错视为未就绪）。"""
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    try:
        return bool(fn())
    except Exception:
        return False


def init_repo(path, rel_file, content="base\n"):
    """最小 git 仓夹具：init -b main + 单文件基线提交。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "ut@example.com", cwd=path)
    git("config", "user.name", "ut", cwd=path)
    f = path / rel_file
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return path


def build_project(base, name="proj"):
    """混合形态夹具：根亦 git 仓 + repo_a/repo_b 子仓（.gitignore 忽略子仓与产品点目录）。

    与 t260911-04 全链场景同款形态（dengzhufpv 缺陷现场）；本库只造磁盘/git，不起台。
    返回 {root, repo_a, repo_b}。"""
    root = Path(base) / name
    root.mkdir(parents=True, exist_ok=True)
    init_repo(root, "docs/root.md")
    (root / ".gitignore").write_text(
        "repo_a/\nrepo_b/\n.suyou/\n.sandbar/\n.dsh/\n", encoding="utf-8")  # naming-compat：.suyou/=旧名清单镜像目录，fixture 照造（t260911-04 同款）
    git("add", "-A", cwd=root)
    git("commit", "-m", "gitignore", cwd=root)
    init_repo(root / "repo_a", "src/a.py")
    init_repo(root / "repo_b", "lib/b.py")
    return {"root": root, "repo_a": root / "repo_a", "repo_b": root / "repo_b"}


def lane_branch(ticket, repo_rel):
    """与 shared.build_repo_worktrees 同形的分支名（根树 name=root）。"""
    return "lane/%s-%s" % (ticket, "root" if repo_rel == "" else repo_rel)


def make_lane(root, ticket, rels=("", "repo_a"), manifest=True, manifest_entries=None):
    """在混合形态项目里建泳道：根树（容器 worktree）+ 逐成员仓 worktree + 盘上清单。

    rels 顺序=清单条目顺序（默认根树在前=最易踩「根树先删连容器删光」的序）。
    返回 {root, lane, entries, branches, trees, manifest_path}。"""
    root = Path(root)
    lane = root / ".lane" / ticket
    branches, trees = {}, {}
    if "" in rels:  # 根树=泳道容器本身（根仓的 worktree）
        br = lane_branch(ticket, "")
        git("worktree", "add", "-b", br, str(lane), cwd=root)
        branches[""], trees[""] = br, lane
    for rel in rels:
        if rel == "":
            continue
        repo = root / rel
        br = lane_branch(ticket, rel)
        git("worktree", "add", "-b", br, str(lane / rel), cwd=repo)
        branches[rel], trees[rel] = br, lane / rel
    entries = manifest_entries if manifest_entries is not None else [
        {"repo": rel, "name": "root" if rel == "" else rel, "branch": branches[rel]}
        for rel in rels]
    manifest_path = lane / _manifest_rel()
    if manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return {"root": root, "lane": lane, "entries": entries, "branches": branches,
            "trees": trees, "manifest_path": manifest_path}


def _manifest_rel():
    """清单相对路径：消费引擎单一真源常量（不落 dot 目录裸字面量）。"""
    mods, why = engine_modules()
    if mods is None:
        raise RuntimeError("引擎模块不可用（%s）" % why)
    return mods[1].MULTI_MANIFEST_REL


def engine_modules():
    """装载引擎模块（需引擎 venv 的 temporalio）。返回 ((shared, aa), "") 或 (None, why)。"""
    poc = str(POC)
    if poc not in sys.path:
        sys.path.insert(0, poc)
    try:
        import shared as _shared  # noqa: F401
        import agent_activities as _aa  # noqa: F401
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:200])
    return (_shared, _aa), ""


_teardown_field = ""


def call_teardown(lane, branch, repo_worktrees=None, ticket=None):
    """直调拆道 activity（灰盒 L2：真 git 夹具 + 真 activity，零 docker/零 Temporal）。

    返回 (receipt, field_used)。repo_worktrees=None = 不带该键（老在途票 payload 形态）。
    字段名容忍 repo_worktrees / scopes：绑定浅，实现换名不判场景错。"""
    global _teardown_field
    mods, why = engine_modules()
    if mods is None:
        raise RuntimeError("引擎模块不可用（%s）" % why)
    shared_mod, aa = mods
    args = shared_mod.MergeArgs(ticket_id=ticket or Path(lane).name,
                                worktree=str(lane), branch=branch)
    field_used = ""
    if repo_worktrees is not None:
        for cand in ("repo_worktrees", "scopes"):
            if hasattr(shared_mod.MergeArgs, cand):
                field_used = cand
                break
        else:
            field_used = "repo_worktrees"  # 字段未落地：动态挂上，让实现读得到（红=契约缺口）
        setattr(args, field_used, list(repo_worktrees))
        _teardown_field = field_used
    return asyncio.run(aa.teardown_lane(args)), field_used


# ---------- 契约判读帮手（绑定浅：只锚「点名了哪个仓 / 磁盘终态」） ----------

def names_repo(error, name):
    """回执文案是否**逐仓点名**该仓：tag 形如 [name] 命中，或该仓名与失败词同段。"""
    txt = str(error or "")
    if re.search(r"\[[^\]]*%s[^\]]*\]" % re.escape(str(name)), txt):
        return True
    for seg in re.split(r"[；;]", txt):
        if str(name) in seg and ("失败" in seg or "不存在" in seg):
            return True
    return False


def segment_of(error, name):
    """回执里点名该仓的告警段（诊断文案用；找不到返回整串尾部）。"""
    for seg in re.split(r"[；;]", str(error or "")):
        if str(name) in seg:
            return seg[:220]
    return str(error or "")[-220:]


def branch_lane_gone(repo, prefix="lane/*"):
    """该仓 lane/* 分支已删（git 真值面）。"""
    rc, out, _ = git_ok("branch", "--list", prefix, cwd=repo)
    return rc == 0 and not out.strip()


def branch_lane_present(repo, branch):
    rc, out, _ = git_ok("branch", "--list", branch, cwd=repo)
    return rc == 0 and branch in out


def worktree_has(repo, tree):
    """该仓的 worktree 注册表里是否仍有该路径（真值面；dangling 注册也算在场）。"""
    rc, out, _ = git_ok("worktree", "list", "--porcelain", cwd=repo)
    if rc != 0:
        return False
    return str(Path(tree).resolve()) in out


def residue_state(project, lane):
    """逐仓残留快照（报告/诊断用）：project=build_project 返回值，lane=泳道容器。"""
    root = project["root"]
    out = {}
    for rel, repo in (("", root), ("repo_a", root / "repo_a"),
                      ("repo_b", root / "repo_b")):
        tree = Path(lane) if rel == "" else Path(lane) / rel
        out[rel or "root"] = {
            "worktree_registered": worktree_has(repo, tree),
            "tree_dir": tree.exists(),
            "lane_branches": git_ok("branch", "--list", "lane/*", cwd=repo)[1].split(),
        }
    return out


def lock_worktree(repo, tree):
    """注入「拆不掉」的真实 git 态：worktree lock（单次 --force 必失败且不删目录）。"""
    return git_ok("worktree", "lock", str(tree), cwd=repo)


def unlock_worktree(repo, tree):
    """回收注入（容忍路径已随容器被删：注册还在也能 unlock）。"""
    return git_ok("worktree", "unlock", str(tree), cwd=repo)


def tmpdir(prefix):
    """测试 tmp 落仓内 .sandbar/（沙箱对仓外 tmp 的 git 子进程有过拦截实证）。"""
    ws = REPO / ".sandbar"
    ws.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix + "-", dir=str(ws)))


def rmtree(p):
    shutil.rmtree(str(p), ignore_errors=True)
