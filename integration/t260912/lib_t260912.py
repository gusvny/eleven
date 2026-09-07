#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-12 集成测试共享夹具：根亦 git 仓的混合多仓项目（dengzhufpv 形态）。
不带 sc_ 前缀 = 共享夹具代码，不进 SCENARIOS（run_scenarios 约定）。

夹具红线（沿 t260907-06 lib 口径）：假项目只在测试 tmp 目录自建，
不代用户建仓/搬码，不碰真实项目数据。
环境口径（三态契约）：stdlib 面（shared 纯函数/git 夹具）系统 python3 可跑；
temporalio 面（prepare/settle 行为腿）缺失=ENV_FAIL exit 2，不写 SKIP。

复用纪律：通用 helpers（check/summary/env_fail/三态口径/git/容错调用工厂）
跨票 import t260907-06 lib（夹具跨票复用先例：t260905-08→t260907-08），
本 lib 只新增混合形态夹具。
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "t260907-06"))

from lib_t260907_06 import (  # noqa: E402,F401
    POC, check, summary, env_fail, temporalio_available, git, git_ok,
    CapabilityMissing, call_with_supported_fields, call_prepare,
    shared_workspace_prep_cls, verify_yaml_text, _init_repo,
)

sys.path.insert(0, str(POC))  # shared / agent_activities 可导入（call_prepare 依赖）


def build_mixed_project(prefix="t260907-12-mixed-", nested=False):
    """混合形态夹具（tmp 自建）：项目根=git 仓（知识库仓）+ 一层子仓并存
    （票文口径「[根]+一层子仓集合」，dengzhufpv 形态）。

      <root>/                 git 仓（基线提交含 README.md、docs/kb.md、
                              .gitignore 忽略子仓目录与 .suyou/（naming-compat：旧名清单镜像面））
      <root>/repo_a/          git 仓（基线提交含 src/a.py）
      <root>/repo_b/          git 仓（基线提交含 lib/b.py）

    .gitignore 是契约 advisory④ 的夹具落地：根树=泳道容器本身时，子仓树与
    泳道清单（.suyou/）落在根仓工作区内，必须被忽略（根仓 status 不受污染；naming-compat：旧名清单镜像面，
    真源=agent_activities.MULTI_MANIFEST_REL——stdlib 面不 import 其 temporalio 依赖，字面量对齐即可）。
    nested=True 时在 <root>/docs/nested/ 再放一个嵌套 git 仓——一层扫描之外的
    集合外嵌套仓（归属游走从根仓起全长走，专测混合形态的 fail-closed：
    子仓若挂在二层容器目录下同样按此语义拒收，不静默归根仓）。
    返回 (root, {"repo_a": Path, "repo_b": Path, "nested": Path|None})。
    """
    root = Path(tempfile.mkdtemp(prefix=prefix))
    _init_repo(root, "baseline: 根仓（知识库仓）")
    (root / "docs").mkdir()
    (root / "docs" / "kb.md").write_text("knowledge base entry\n", encoding="utf-8")
    (root / ".gitignore").write_text("repo_a/\nrepo_b/\n.suyou/\n", encoding="utf-8")  # naming-compat fixture：造旧名清单镜像目录
    git("add", "-A", cwd=root)
    git("commit", "-m", "root: docs/kb.md + advisory④ gitignore", cwd=root)

    repos = {}
    ra = root / "repo_a"
    _init_repo(ra, "baseline: repos/repo_a")
    (ra / "src").mkdir()
    (ra / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    git("add", "-A", cwd=ra)
    git("commit", "-m", "repo_a: src/a.py", cwd=ra)
    repos["repo_a"] = ra

    rb = root / "repo_b"
    _init_repo(rb, "baseline: repos/repo_b")
    (rb / "lib").mkdir()
    (rb / "lib" / "b.py").write_text("print('b')\n", encoding="utf-8")
    git("add", "-A", cwd=rb)
    git("commit", "-m", "repo_b: lib/b.py", cwd=rb)
    repos["repo_b"] = rb

    # 引擎自留工作区模拟（单仓零变化红线面）：.lane/<id> 是本引擎泳道 worktree
    # 的既定路径约定（_lane_repo_root 自锚 .lane/.worktrees），.git 为 gitfile
    # 形态——引擎自留工作区绝不能进仓集合，否则根仓无子仓的项目（sandbar 自身）
    # 被误判多仓形态，全链误激活。
    lane_wt = root / ".lane" / "wt-tfix"
    _init_repo(lane_wt, "baseline: 引擎自留泳道 worktree 模拟")
    repos["lane_wt"] = lane_wt

    repos["nested"] = None
    if nested:
        nd = root / "docs" / "nested"
        _init_repo(nd, "baseline: docs/nested（容器目录下的仓，归属类属设计歧义面）")
        (nd / "n.txt").write_text("nested\n", encoding="utf-8")
        git("add", "-A", cwd=nd)
        git("commit", "-m", "nested: n.txt", cwd=nd)
        repos["nested"] = nd
    # 真嵌套仓（已登记仓内部套仓）：fail-closed 原样语义的注入面（票B 原定义）
    sub = repos["repo_a"] / "subrepo"
    _init_repo(sub, "baseline: repo_a/subrepo（仓内套仓）")
    (sub / "s.txt").write_text("s\n", encoding="utf-8")
    git("add", "-A", cwd=sub)
    git("commit", "-m", "subrepo: s.txt", cwd=sub)
    repos["subrepo"] = sub
    return root, repos


def build_single_repo_project(prefix="t260907-12-single-"):
    """单仓对照夹具（根 .git 无子仓=sandbar 自身形态，零变化回归面用）。"""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    _init_repo(root, "baseline: 单仓项目根")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('main')\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-m", "single: src/main.py", cwd=root)
    lane_wt = root / ".lane" / "wt-tfix"
    _init_repo(lane_wt, "baseline: 引擎自留泳道 worktree 模拟")
    return root


def read_manifest(container):
    """读泳道清单（workspace.repo_worktrees 的落盘镜像=公开契约面）。缺失返 None。"""
    import json
    mf = container / ".suyou" / "repo_worktrees.json"  # naming-compat：旧名镜像读点（真源=MULTI_MANIFEST_REL）
    if not mf.is_file():
        return None
    return json.loads(mf.read_text("utf-8"))


def lane_worktree_registered(repo, tree):
    """tree 是否 repo 的已注册 worktree（git worktree list 绝对路径比对）。"""
    out = git("worktree", "list", "--porcelain", cwd=repo)
    return ("worktree %s" % str(tree.resolve())) in out


def cleanup(*roots):
    for r in roots:
        shutil.rmtree(r, ignore_errors=True)
