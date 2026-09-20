#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-06 场景①：多仓票全链旅程（验收①前半+复用幂等，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同，用户手册多 repo 模型=项目父目录作根、
一票涉多 repo 时多棵树同居一 lane）：
- 建票归属契约：写集路径落两子仓 → 每仓各得其路径子集（路径归属=最近 .git
  祖先仓，一票两仓各自认领，不串仓不丢路径）；单仓口径条目透传不碎；
- 泳道开进正确子仓：lane 容器（<项目根>/.lane/<泳道>，普通目录不入任何仓）下
  每仓一棵树，树=**所属子仓**的已注册 worktree（git worktree list 按绝对路径
  可验），基线文件随仓（不是空目录不是别的仓的内容）；
- 分支命名：lane/<泳道目录名>-<仓相对路径压平>，逐仓独立；
- 复用幂等（转移接力 M4 面）：prepare 二次执行两树 reused——树不重建（树内
  标记文件幸存=未重建），分支引用不漂移；
- 结算各归其仓：两树分别改动后 settle，提交各落**各自树**的分支，且每棵树的
  落账只含本仓写集内文件（改动串仓=错仓落账，验收红线）。

与相邻场景 intent 分界：场景②守合并闸/逐仓收口/重入；场景③守 fail-closed
拒收面（逃逸/嵌套仓/删仓/来历不明占位）。单仓零回归不另起用例——存量
integration 场景族即单仓回归面（intent 相同，不重复造）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为子用例），stdlib 归属契约子用例照跑。
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260907_06 import (  # noqa: E402
    POC, check, summary, env_fail, temporalio_available,
    git, build_multirepo_project, lane_dirname, call_prepare,
    CapabilityMissing,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

TICKET = "t26090706jt"
WS = ["repo_a/src/a.py", "repo_b/lib/b.py"]

root, repos = build_multirepo_project(prefix="t260907-06-jt-")
wname = lane_dirname(TICKET)
container = root / ".lane" / wname
tree_a = container / "repo_a"
tree_b = container / "repo_b"

# ---------- stdlib 面：写集→子仓归属契约 ----------
resolve = getattr(shared, "resolve_repos_for_paths", None)
if resolve is None:
    check("J1 写集归属：resolve_repos_for_paths 已落地", False,
          "shared.resolve_repos_for_paths 缺失——票B 仓锚推导未落地（红属 TDD 预期）")
else:
    try:
        mapping = resolve(str(root), WS)
        got_paths = sorted(
            p for paths in (mapping.values() if hasattr(mapping, "values") else mapping)
            for p in paths) if hasattr(mapping, "values") else []
        check("J1 写集归属：两仓各自认领、路径不丢不串",
              len(mapping) == 2 and got_paths == sorted(WS),
              "mapping=%r" % (mapping,))
    except Exception as e:
        check("J1 写集归属：两仓各自认领、路径不丢不串", False,
              "resolve 抛异常: %s: %s" % (type(e).__name__, e))

rebase = getattr(shared, "rebase_write_set", None)
if rebase is None:
    check("J2 写集重基：单仓口径透传（repo_rel 空=原样）", False,
          "shared.rebase_write_set 缺失——写集重基未落地（红属 TDD 预期）")
else:
    probe = ["repo_a/src/a.py", "other/x.py"]
    out = rebase(list(probe), "")
    check("J2 写集重基：单仓口径透传（repo_rel 空=原样）", list(out) == probe,
          "out=%r" % (out,))

# ---------- temporalio 面：prepare 两树并存 + 复用幂等 + settle 各归其仓 ----------
if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：prepare/settle 行为子用例不可执行——"
             "stdlib 归属契约子用例已在本场跑完；arbitrate/merge 期 venv 环境必须全绿")
else:
    try:
        res = call_prepare(container, TICKET, WS, root)
    except CapabilityMissing as e:
        res = None
        check("J3 prepare 多仓分支：两树并存且各属正确仓", False, str(e))
    if res is not None:
        check("J3a prepare 多仓分支：回执 ok（不抛、交回执）", bool(getattr(res, "ok", False)),
              "res=%r" % (res,))
        in_a = ("worktree %s" % tree_a.resolve()) in git("worktree", "list", "--porcelain", cwd=repos["repo_a"])
        in_b = ("worktree %s" % tree_b.resolve()) in git("worktree", "list", "--porcelain", cwd=repos["repo_b"])
        wl_a = git("worktree", "list", "--porcelain", cwd=repos["repo_a"])
        check("J3b 树 repo_a 属 repo_a（worktree list 注册）", in_a)
        check("J3c 树 repo_b 属 repo_b（worktree list 注册）", in_b)
        check("J3d 树不串仓：repo_a 的注册表里没有 repo_b 的树",
              ("worktree %s" % tree_b.resolve()) not in wl_a)
        check("J3e 树随仓基线：repo_a 树内见 repo_a 基线文件",
              (tree_a / "src" / "a.py").is_file() and not (tree_a / "lib" / "b.py").exists())
        exp_branch_a = "lane/%s-repo_a" % wname
        exp_branch_b = "lane/%s-repo_b" % wname
        got_a = git("rev-parse", "--abbrev-ref", "HEAD", cwd=tree_a).strip()
        got_b = git("rev-parse", "--abbrev-ref", "HEAD", cwd=tree_b).strip()
        check("J3f 分支命名压平且逐仓独立", (got_a, got_b) == (exp_branch_a, exp_branch_b),
              "got=(%r, %r) exp=(%r, %r)" % (got_a, got_b, exp_branch_a, exp_branch_b))

        # 复用幂等：标记文件幸存=未重建；分支引用不漂
        (tree_a / ".lane_reuse_marker").write_text("keep\n", encoding="utf-8")
        ref_a_before = git("rev-parse", "HEAD", cwd=tree_a).strip()
        try:
            res2 = call_prepare(container, TICKET, WS, root)
            check("J4a prepare 二次：回执含 reused（两树都复用，不部分重建）",
                  "reused" in str(res2), "res2=%r" % (res2,))
        except CapabilityMissing as e:
            check("J4a prepare 二次：回执含 reused（两树都复用，不部分重建）", False, str(e))
        check("J4b 树未重建（标记文件幸存）", (tree_a / ".lane_reuse_marker").is_file())
        check("J4c 分支引用不漂移", git("rev-parse", "HEAD", cwd=tree_a).strip() == ref_a_before)

        # settle 各归其仓：两树分别落改动
        (tree_a / "src" / "a.py").write_text("print('a changed')\n", encoding="utf-8")
        (tree_b / "lib" / "b.py").write_text("print('b changed')\n", encoding="utf-8")
        try:
            import asyncio
            import agent_activities  # noqa: E402
            sres = asyncio.run(agent_activities.settle_lane(
                shared.SettleLaneArgs(ticket_id=TICKET, worktree=str(container),
                                      stage_id="sc1", gen=0)))
            serr = str(getattr(sres, "error", "") or "")
            check("J5a settle_lane 多仓：回执无 error（逐树代落盘）", serr == "",
                  "sres=%r" % (sres,))
            log_a = git("log", "--name-only", "--format=%s", "-1", "HEAD", cwd=tree_a)
            log_b = git("log", "--name-only", "--format=%s", "-1", "HEAD", cwd=tree_b)
            check("J5b repo_a 树分支收到 a.py 改动（各归其仓）",
                  "src/a.py" in log_a, "log_a=%r" % (log_a,))
            check("J5c repo_b 树分支收到 b.py 改动（各归其仓）",
                  "lib/b.py" in log_b, "log_b=%r" % (log_b,))
            check("J5d 不串仓：repo_a 树的落账不含 repo_b 文件",
                  "lib/b.py" not in log_a, "log_a=%r" % (log_a,))
        except Exception as e:
            check("J5 settle_lane 多仓逐树代落盘", False,
                  "异常: %s: %s（签名/行为未落地红属 TDD 预期）" % (type(e).__name__, e))

shutil.rmtree(root, ignore_errors=True)
sys.exit(summary())
