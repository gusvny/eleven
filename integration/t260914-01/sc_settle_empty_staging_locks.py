#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260914-01 场景②：空提交与真失败的可辨性负锁（灰盒 L2，真 git 夹具，无 docker 无 Temporal）。

intent（守护的用户可感知行为/契约）：
- 「**判脏非空但撤下协调目录后暂存区为空**」是正常工作态：settle 返回**可辨回执**
  （不是异常）——旧版在此抛 RuntimeError，被 Temporal 表现成「agent 活动故障」；
- 「**真失败必须响亮**」：git add 失败、暂存非空而 commit 失败，一律不得吞成回执
  （吞掉＝违规改动静默不落盘还报成功，是本修明令禁止的反向失守）；
- **三态可辨**：干净回执 / 空提交回执 / 代落盘回执 三者文案互不相同，人或机器可据此
  分辨「没东西可提交」与「落盘成功」与「本来就没改」。

注入纪律（本场景是本票唯一使用显式形态注入的地方，理由写在注入点）：
- 「判脏非空但暂存区空」在修复后已无法由正常路径自然产生（老名目录已被判脏口径排除），
  故按验收口径 C 显式注入该形态：把 settle 的判脏清单常量换回**修复前口径**
  （新名重复、老名缺失）——即现场事故当时的世界，注入点带**非空转负锁**（先证判脏确实
  非空，否则用例白跑）；
- 真 add 失败 / 真 commit 失败用**真实 git 态**注入（gitdir 内 index.lock 在场 /
  pre-commit hook 拒绝），不 monkeypatch 产品实现。

与相邻场景的 intent 分界：sc_settle_old_lane_stance（场景①）守正常收口终态与产物不丢
（无需注入）；本条守**异常/边界态的可辨性与响亮性**。与 t260911-03 系（路径闸拒绝面）
零重叠：本条不启用闸（path_gate 缺省 False）。

与 developer L1（server/engine/tests/test_t260914_01_settle_lane_stance.py）的分工：L1 守纯函数/
夹具级形状（含 monkeypatch 注入，白盒可随实现重写），本条守 **activity 级真实 git 态终态**
（真注册 worktree、真 index.lock/hook 注入、多仓逐仓 scope），绑定公开回执与 git 磁盘终态。

故障面清单：① 空提交形态（判脏非空/暂存空）→ T2；② 真 add 失败 → T4；
③ 真 commit 失败（暂存非空）→ T5；④ 干净态分界 → T1；⑤ 三态文案可辨 → T3；
⑥ 注入非空转负锁 → T2b。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
引擎 venv/temporalio 缺席 = ENV_FAIL exit 2 点名（本场景无 stdlib 替代腿：直调 activity）。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260914_01 import (  # noqa: E402
    check, env_fail, summary, tmpdir, rmtree, init_repo, make_lane_worktree,
    head_count, head_sha, dirty_paths, settle_pathspec, engine_modules,
    write_stage_artifact, settle, git, git_ok,
)

TID = "t26091401b"


def _note(r):
    return (getattr(r, "note", "") or "") if r is not None else ""


def _settle_try(shared, aa, tree, ticket, **kw):
    """返回 (result, err_str)：异常不吞、原样交给用例判定。"""
    try:
        return settle(shared, aa, tree, ticket, **kw), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _lane(shared, tag, gitignore=()):
    root = init_repo(tmpdir("t260914-01b-%s-" % tag), files={"docs/kb.md": "kb\n"})
    lane = Path(root) / ".lane" / (TID + tag)
    make_lane_worktree(root, lane, "lane/%s%s-root" % (TID, tag))
    return root, lane


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 activity 无 stdlib 替代腿" % why)
    shared, aa = mods

    # ---- T1 干净泳道：干净回执（三态分界的锚） ----
    root1, lane1 = _lane(shared, "c")
    n1, sha1 = head_count(lane1), head_sha(lane1)
    r1, e1 = _settle_try(shared, aa, lane1, TID + "c", stage="create_plan", gen=0)
    note_clean = _note(r1)
    check("T1 干净泳道：正常收口、零 commit、回执非空",
          e1 is None and head_sha(lane1) == sha1 and head_count(lane1) == n1 and bool(note_clean),
          "异常=%s note=%r" % (e1, note_clean[:160]))

    # ---- T2 注入「判脏非空但暂存区空」→ 空提交回执（不抛） ----
    root2, lane2 = _lane(shared, "e")
    art = write_stage_artifact(shared, lane2)          # 老名协调目录产物
    n2, sha2 = head_count(lane2), head_sha(lane2)
    # 注入点（显式，现场重演）：判脏清单换回修复前口径＝新名重复、老名缺失。
    # 修复后正常路径已排除老名目录，该形态只能这样重演；finally 必还原。
    pre_fix = [".", ":!.dsh", ":!" + shared.DOT_DIR_NEW, ":!" + shared.DOT_DIR_NEW]
    orig = aa.SETTLE_PATHSPEC
    r2 = e2 = None
    dirty_seen = None
    try:
        aa.SETTLE_PATHSPEC = pre_fix
        dirty_seen = dirty_paths(lane2, shared, pathspec=pre_fix)
        r2, e2 = _settle_try(shared, aa, lane2, TID + "e", stage="create_plan", gen=3)
    finally:
        aa.SETTLE_PATHSPEC = orig
    note_empty = _note(r2)
    check("T2a 注入非空转负锁：修复前口径下判脏确实非空（含老名协调目录条目）",
          bool(dirty_seen) and any(shared.DOT_DIR_OLD in d for d in dirty_seen),
          "dirty=%r" % (dirty_seen,))
    check("T2b 空提交＝正常收口：不抛异常（旧版在此抛 RuntimeError）", e2 is None, "异常=%s" % e2)
    check("T2c 回执可辨（含空暂存标记串，且不是干净回执文案）",
          "暂存区为空" in note_empty and "判脏" in note_empty and note_empty != note_clean,
          "note=%r" % note_empty[:220])
    check("T2d 回执不是闸拒绝（无 path_gate_reason=，workflow 不会据此转 blocked）",
          "path_gate_reason=" not in note_empty)
    check("T2e 零代落盘 commit、产物零丢失",
          head_sha(lane2) == sha2 and head_count(lane2) == n2 and art.is_file(),
          "count %s→%s" % (n2, head_count(lane2)))

    # ---- T3 同一注入世界下真改动仍代落盘（三态可辨，防「空提交分支吞真改动」） ----
    (lane2 / "docs" / "real.md").write_text("real\n", encoding="utf-8")
    r3 = e3 = None
    try:
        aa.SETTLE_PATHSPEC = pre_fix
        r3, e3 = _settle_try(shared, aa, lane2, TID + "e", stage="create_plan", gen=3,
                             write_set=["docs/"])
    finally:
        aa.SETTLE_PATHSPEC = orig
    note_commit = _note(r3)
    check("T3a 注入世界下真实改动照旧代落盘（不得被空提交分支吞掉）",
          e3 is None and head_count(lane2) == n2 + 1, "异常=%s count=%s" % (e3, head_count(lane2)))
    check("T3b 三态文案互不相同（干净／空提交／代落盘 可辨）",
          len({note_clean, note_empty, note_commit}) == 3,
          "clean=%r empty=%r commit=%r" % (note_clean[:60], note_empty[:60], note_commit[:60]))

    # ---- T4 真 add 失败：真实 git 态注入（gitdir 内 index.lock 在场）→ 必须响亮 ----
    root4, lane4 = _lane(shared, "f")
    (lane4 / "docs" / "real.md").write_text("real\n", encoding="utf-8")
    gd = git(["rev-parse", "--path-format=absolute", "--absolute-git-dir"], lane4)
    if gd.returncode != 0:
        env_fail("取泳道 gitdir 失败（夹具环境问题）：%s" % (gd.stderr or "")[-200:])
    lock = Path(gd.stdout.strip()) / "index.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    n4, sha4 = head_count(lane4), head_sha(lane4)
    r4 = e4 = None
    try:
        lock.write_text("", encoding="utf-8")
        r4, e4 = _settle_try(shared, aa, lane4, TID + "f", stage="create_plan", gen=0,
                             write_set=["docs/"])
    finally:
        lock.unlink(missing_ok=True)
    check("T4a 真 git add 失败必须响亮（不得吞成回执）", e4 is not None, "result=%r" % _note(r4)[:160])
    check("T4b 报错点名失败的那一步（add）", bool(e4) and "add" in e4, "异常=%s" % e4)
    check("T4c 失败后零 commit（不假落盘）",
          head_sha(lane4) == sha4 and head_count(lane4) == n4)

    # ---- T5 真 commit 失败（暂存非空）：pre-commit hook 拒绝 → 必须响亮 ----
    root5, lane5 = _lane(shared, "g")
    (lane5 / "docs" / "real.md").write_text("real\n", encoding="utf-8")
    cd = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], lane5)
    if cd.returncode != 0:
        env_fail("取仓公共 gitdir 失败（夹具环境问题）：%s" % (cd.stderr or "")[-200:])
    hook = Path(cd.stdout.strip()) / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    n5, sha5 = head_count(lane5), head_sha(lane5)
    r5 = e5 = None
    try:
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        r5, e5 = _settle_try(shared, aa, lane5, TID + "g", stage="create_plan", gen=0,
                             write_set=["docs/"])
    finally:
        hook.unlink(missing_ok=True)
    check("T5a 真 commit 失败（暂存非空）必须响亮（不得吞成回执）",
          e5 is not None, "result=%r" % _note(r5)[:160])
    check("T5b 报错点名失败的那一步（commit）", bool(e5) and "commit" in e5, "异常=%s" % e5)
    check("T5c 失败后零 commit（不假落盘）",
          head_sha(lane5) == sha5 and head_count(lane5) == n5)

    rmtree(root1, root2, root4, root5)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
