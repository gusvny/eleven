#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-12 场景①：根亦 git 仓的混合多仓项目全链（dengzhufpv 形态，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同）：项目根=知识库 git 仓＋repos/* 子仓并存的
项目（宿主决策「知识库要 git」后的真实形态）也能开票——repos_under 的
「根含 .git→单仓」短路退位后：
- 仓集合=[根]+一层子仓（根无子仓→恒[根]，单仓项目全链零变化）；
- 写集归属三态：根仓路径票→根树（repo=""）、子仓路径票→子仓树、双命中票→
  两树同居一 lane 不串不丢（归属=最长前缀，票B 设计本义在混合形态延续）；
- 根树=泳道容器本身（repo=""，与 tree=lane/<repo_rel> 同式构造）：prepare
  created、分支 lane/<泳道>-root、基线随根仓；泳道清单落盘含 repo="" 条目；
- workflow 闸对 repo="" 合法条目放行；缺 branch/分支碰撞等真畸形照旧拒收
  （fail-closed 不弱化）；
- 复用幂等（转移接力 M4 面）：prepare 二次两树 reused、标记幸存、引用不漂；
- settle 逐树各归其仓：根树落账只含根仓写集文件、子仓不串仓；根仓 status
  不受子仓树/清单污染（advisory④ .gitignore 兜底）；
- fail-closed：根仓名下二层嵌套仓路径创建即拒收点名（不静默归根仓）。

与相邻场景 intent 分界：t260907-06 三场景守「父目录作根」形态（根无 .git）的
归属/合并闸/拒收面；本场景守根亦 git 仓的**混合形态**新面。通用路径逃逸、
写集条目畸形形态属建票写集契约既有面（t260907-06 场景③在册），intent 级
重复不另起。单仓零变化另设对照腿（存量场景族项目根=仓根，无「根含 .git 且
旁边有子仓」的对照形态）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（prepare/settle 行为腿），stdlib 契约腿照跑。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260912 import (  # noqa: E402
    POC, check, summary, env_fail, temporalio_available, git,
    build_mixed_project, build_single_repo_project, read_manifest,
    lane_worktree_registered, cleanup, call_prepare, CapabilityMissing,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

TICKET_RT = "t260912rt"   # 态1：根仓路径票
TICKET_DB = "t260912db"   # 态3：双命中票（根仓+子仓）
TICKET_SG = "t260912sg"   # 单仓对照
WS_RT = ["docs/kb.md", "README.md"]
WS_DB = ["docs/kb.md", "repo_a/src/a.py"]
WS_SUB = ["repo_b/lib/b.py"]

root, repos = build_mixed_project(prefix="t260912-mixed-", nested=True)


def wname(ticket_id):
    lane_rel, _b = shared.default_lane_paths(ticket_id)
    return lane_rel.split("/", 1)[1]


w_rt, w_db = wname(TICKET_RT), wname(TICKET_DB)
container_rt = root / ".lane" / w_rt
container_db = root / ".lane" / w_db
tree_a_db = container_db / "repo_a"

# ---------- stdlib 面 M1：仓集合与写集归属三态契约 ----------
repos_under = getattr(shared, "repos_under", None)
if repos_under is None:
    check("M1a 仓集合：repos_under 已落地", False, "shared.repos_under 缺失")
else:
    got = repos_under(root)
    got_s = sorted(str(p) for p in got)
    exp_s = sorted([str(root), str(repos["repo_a"]), str(repos["repo_b"])])
    check("M1a 仓集合：根含 .git 且有子仓 → [根]+一层子仓",
          got[0] == root and got_s == exp_s and len(got) == 3,
          "got=%r" % (got,))
    check("M1a-2 引擎自留工作区不入仓集合（.lane/<id> worktree=单仓零变化红线）",
          str(repos["lane_wt"]) not in got_s,
          "got 含 %r——.lane 泳道 worktree 被当子仓=根仓无子仓项目误激活多仓"
          % (repos["lane_wt"],))

resolve = getattr(shared, "resolve_repos_for_paths", None)
if resolve is None:
    check("M1b 归属三态：resolve_repos_for_paths 已落地", False, "shared.resolve_repos_for_paths 缺失")
else:
    try:
        m_root = resolve(str(root), WS_RT)
        check("M1b 态1 根仓路径票：全条目归根仓（repo 相对路径=空）",
              list(m_root.keys()) == [str(root.resolve())]
              and m_root[str(root.resolve())] == WS_RT, "m=%r" % (m_root,))
    except Exception as e:
        check("M1b 态1 根仓路径票：全条目归根仓", False,
              "resolve 抛异常: %s: %s" % (type(e).__name__, e))
    try:
        m_sub = resolve(str(root), WS_SUB)
        check("M1c 态2 子仓路径票：归 repo_b（最长前缀）",
              list(m_sub.keys()) == [str(repos["repo_b"].resolve())], "m=%r" % (m_sub,))
    except Exception as e:
        check("M1c 态2 子仓路径票：归 repos/repo_b", False,
              "resolve 抛异常: %s: %s" % (type(e).__name__, e))
    try:
        m_db = resolve(str(root), WS_DB)
        owners = sorted(m_db.keys())
        got_paths = sorted(p for ps in m_db.values() for p in ps)
        check("M1d 态3 双命中票：根仓+子仓各认领、不串不丢",
              owners == sorted([str(root.resolve()), str(repos["repo_a"].resolve())])
              and got_paths == sorted(WS_DB)
              and m_db[str(root.resolve())] == ["docs/kb.md"]
              and m_db[str(repos["repo_a"].resolve())] == ["repo_a/src/a.py"],
              "m=%r" % (m_db,))
    except Exception as e:
        check("M1d 态3 双命中票：根仓+子仓各认领", False,
              "resolve 抛异常: %s: %s" % (type(e).__name__, e))
    try:
        resolve(str(root), ["repo_a/subrepo/s.txt"])
        check("M1e 真嵌套仓（已登记仓内部套仓）路径拒收", False,
              "未拒收（嵌套仓 fail-closed 原样语义失守=错仓落账前奏）")
    except ValueError as e:
        check("M1e 真嵌套仓（已登记仓内部套仓）路径拒收点名",
              "集合外嵌套仓" in str(e), "e=%s" % e)
    except Exception as e:
        check("M1e 集合外嵌套仓（根仓名下二层）路径拒收", False,
              "异常类型错: %s: %s" % (type(e).__name__, e))

# ---------- stdlib 面 M2：workflow 闸腿（repo="" 合法放行、真畸形照旧拒） ----------
gate = getattr(shared, "lane_workspace_gate_error", None)
if gate is None:
    check("M2 闸腿：lane_workspace_gate_error 已落地", False, "shared.lane_workspace_gate_error 缺失")
else:
    ws_ok = {"type": "worktree", "path": str(container_rt),
             "repo_worktrees": [
                 {"repo": "", "name": "root", "branch": "lane/%s-root" % w_rt},
                 {"repo": "repo_a", "name": "repo_a",
                  "branch": "lane/%s-repo_a" % w_rt},
             ]}
    meta_ok = {"lane": shared.LANE_WORKTREE, "workspace": dict(ws_ok),
               "worktree": str(container_rt), "branch": "lane/" + w_rt}
    check("M2a 闸：repo=\"\" 根树条目过闸（合法形状不假报畸形）", gate(meta_ok) == "",
          "gate=%r" % (gate(meta_ok),))
    ws_nobranch = dict(ws_ok)
    ws_nobranch["repo_worktrees"] = [{"repo": "", "name": "root"}]
    meta_nb = dict(meta_ok, workspace=ws_nobranch)
    check("M2b 闸：缺 branch 的条目照旧拒（fail-closed 不弱化）", gate(meta_nb) != "",
          "gate=%r" % (gate(meta_nb),))
    ws_dup = dict(ws_ok)
    ws_dup["repo_worktrees"] = [
        {"repo": "", "name": "root", "branch": "lane/%s-root" % w_rt},
        {"repo": "repo_a", "name": "repo_a", "branch": "lane/%s-root" % w_rt},
    ]
    meta_dup = dict(meta_ok, workspace=ws_dup)
    check("M2c 闸：分支碰撞照旧点名拒收", "碰撞" in gate(meta_dup), "gate=%r" % (gate(meta_dup),))

# ---------- temporalio 面 M3-M5：prepare 三态/复用幂等/settle 逐树 ----------
if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：prepare/settle 行为腿不可执行——"
             "stdlib 仓集合/归属/闸契约腿已在本场跑完；arbitrate/merge 期 venv 环境必须全绿")
else:
    # M3 态1：根仓路径票——根树=泳道容器本身
    res = None
    try:
        res = call_prepare(container_rt, TICKET_RT, WS_RT, root)
    except CapabilityMissing as e:
        check("M3 态1 根树 prepare", False, str(e))
    if res is not None:
        check("M3a 态1 prepare：回执 ok 且 created（多仓分支）",
              bool(getattr(res, "ok", False)) and "created" in str(res), "res=%r" % (res,))
        check("M3b 根树=泳道容器本身且属根仓（worktree list 注册）",
              lane_worktree_registered(root, container_rt), "container=%s" % container_rt)
        got_br = git("rev-parse", "--abbrev-ref", "HEAD", cwd=container_rt).strip()
        check("M3c 根树分支命名 lane/<泳道>-root",
              got_br == "lane/%s-root" % w_rt, "got=%r" % (got_br,))
        check("M3d 根树随根仓基线（docs/kb.md 在场）",
              (container_rt / "docs" / "kb.md").is_file())
        mf = read_manifest(container_rt)
        check("M3e 泳道清单落盘含 repo=\"\" 根树条目",
              isinstance(mf, list) and any(e.get("repo") == "" for e in mf),
              "mf=%r" % (mf,))

    # M4 态3：双命中票——两树同居一 lane + 复用幂等
    res = None
    try:
        res = call_prepare(container_db, TICKET_DB, WS_DB, root)
    except CapabilityMissing as e:
        check("M4 态3 双命中 prepare", False, str(e))
    if res is not None and getattr(res, "ok", False):
        check("M4a 态3 prepare：回执 ok", True)
        check("M4b 根树属根仓", lane_worktree_registered(root, container_db))
        check("M4c 子仓树 repo_a 属 repo_a（worktree 注册）",
              lane_worktree_registered(repos["repo_a"], tree_a_db),
              "tree=%s" % tree_a_db)
        br_root = git("rev-parse", "--abbrev-ref", "HEAD", cwd=container_db).strip()
        br_a = git("rev-parse", "--abbrev-ref", "HEAD", cwd=tree_a_db).strip()
        check("M4d 双树分支逐仓独立（root / repo_a 压平）",
              br_root == "lane/%s-root" % w_db
              and br_a == "lane/%s-repo_a" % w_db,
              "got=(%r, %r)" % (br_root, br_a))
        check("M4e 基线随仓：根树见 docs/kb.md 不见 repo_a 内容",
              (container_db / "docs" / "kb.md").is_file()
              and not (container_db / "src").exists())
        (container_db / ".lane_marker").write_text("keep\n", encoding="utf-8")
        (tree_a_db / ".lane_marker").write_text("keep\n", encoding="utf-8")
        ref_root = git("rev-parse", "HEAD", cwd=container_db).strip()
        ref_a = git("rev-parse", "HEAD", cwd=tree_a_db).strip()
        try:
            res2 = call_prepare(container_db, TICKET_DB, WS_DB, root)
            check("M4f prepare 二次：两树 reused（复用幂等，M4 转移接力）",
                  "reused" in str(res2), "res2=%r" % (res2,))
        except CapabilityMissing as e:
            check("M4f prepare 二次：两树 reused", False, str(e))
        check("M4g 树未重建（标记文件幸存）",
              (container_db / ".lane_marker").is_file()
              and (tree_a_db / ".lane_marker").is_file())
        check("M4h 分支引用不漂移",
              git("rev-parse", "HEAD", cwd=container_db).strip() == ref_root
              and git("rev-parse", "HEAD", cwd=tree_a_db).strip() == ref_a)

        # M5 下游读腿：清单镜像 + settle 逐树各归其仓（间接覆盖清单读取消费方）
        mf = read_manifest(container_db)
        check("M5a 双命中清单：repo=\"\" 与子仓条目并存（机械真源镜像）",
              isinstance(mf, list)
              and sorted(e.get("repo", "?") for e in mf) == ["", "repo_a"]
              and all(e.get("branch") and e.get("name") for e in mf),
              "mf=%r" % (mf,))
        (container_db / "docs" / "kb.md").write_text("changed by ticket\n", encoding="utf-8")
        (tree_a_db / "src" / "a.py").write_text("print('a changed')\n", encoding="utf-8")
        try:
            import asyncio
            import agent_activities  # noqa: E402
            sres = asyncio.run(agent_activities.settle_lane(
                shared.SettleLaneArgs(ticket_id=TICKET_DB, worktree=str(container_db),
                                      stage_id="sc1", gen=0)))
            serr = str(getattr(sres, "error", "") or "")
            check("M5b settle 双命中 lane：回执无 error（逐树代落盘，repo=\"\" 不断链）",
                  serr == "", "sres=%r" % (sres,))
            log_root = git("log", "--name-only", "--format=%s", "-1", "HEAD", cwd=container_db)
            log_a = git("log", "--name-only", "--format=%s", "-1", "HEAD", cwd=tree_a_db)
            check("M5c 根树分支收到根仓改动（docs/kb.md）",
                  "docs/kb.md" in log_root, "log=%r" % (log_root,))
            check("M5d 子仓树分支收到子仓改动（src/a.py）",
                  "src/a.py" in log_a, "log=%r" % (log_a,))
            check("M5e 不串仓：根树落账不含子仓文件",
                  "repo_a/src/a.py" not in log_root
                  and "src/a.py" not in log_root, "log=%r" % (log_root,))
            dirty = git("status", "--porcelain", cwd=container_db).strip()
            check("M5f 根仓 status 干净（子仓树/清单被 advisory④ .gitignore 兜住）",
                  dirty == "", "porcelain=%r" % (dirty,))
        except Exception as e:
            check("M5 settle/落账腿（双命中逐树）", False,
                  "异常: %s: %s（repo=\"\" 读侧未放行即在此断，红属 TDD 预期）"
                  % (type(e).__name__, e))

# ---------- M6 单仓零变化对照（根 .git 无子仓=sandbar 自身形态） ----------
single = build_single_repo_project()
derive = getattr(shared, "derive_lane_workspace", None)
if derive is None:
    check("M6a 单仓对照：derive_lane_workspace 已落地", False, "shared.derive_lane_workspace 缺失")
else:
    try:
        _lane, ws_sg, _wt, _br = derive(
            TICKET_SG, "tmpl", lane="worktree", project_root=str(single),
            repo_write_set=["src/main.py"])
        check("M6a 单仓对照：derive 不激活多仓（workspace 无 repo_worktrees）",
              isinstance(ws_sg, dict) and "repo_worktrees" not in ws_sg,
              "ws=%r" % (ws_sg,))
    except Exception as e:
        check("M6a 单仓对照：derive 不激活多仓", False,
              "异常: %s: %s" % (type(e).__name__, e))
predicate = getattr(shared, "is_multi_repo_layout", None)
if predicate is None:
    check("M6b 激活谓词：is_multi_repo_layout 已落地", False,
          "shared.is_multi_repo_layout 缺失（红属 TDD 预期）")
else:
    check("M6b 激活谓词三态：单仓 False / 混合 True / 根无 .git 有子仓 True",
          predicate(single) is False and predicate(root) is True,
          "single=%r mixed=%r" % (predicate(single), predicate(root)))
check("M6c 仓集合：单仓根恒 [根]（引擎自留 .lane 工作区不入集合）",
      [str(p) for p in shared.repos_under(single)] == [str(single)],
      "got=%r" % (shared.repos_under(single),))
if temporalio_available():
    container_sg = single / ".lane" / wname(TICKET_SG)
    try:
        res = call_prepare(container_sg, TICKET_SG, ["src/main.py"], single)
        check("M6d 单仓 prepare：走旧单仓路径（created、无多仓清单）",
              bool(getattr(res, "ok", False)) and "created" in str(res)
              and read_manifest(container_sg) is None
              and git("rev-parse", "--abbrev-ref", "HEAD", cwd=container_sg).strip()
              == "lane/" + wname(TICKET_SG),
              "res=%r mf=%r" % (res, read_manifest(container_sg)))
    except CapabilityMissing as e:
        check("M6d 单仓 prepare：走旧单仓路径", False, str(e))

cleanup(root, single)
sys.exit(summary())
