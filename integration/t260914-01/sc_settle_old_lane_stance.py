#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260914-01 场景①：老名协调目录泳道的 settle 姿态（灰盒 L2，真 git 夹具，无 docker 无 Temporal）。

intent（守护的用户可感知行为/契约）：
- **老名泳道里「只产出协调目录产物」的段必须正常收口**：settle 返回可读回执、零代落盘
  commit、**绝不抛异常**（抛异常＝Temporal 判「agent 活动故障」→ 工单 blocked，而 agent
  的产物其实是好的：dengzhufpv/t260911-07 每次重跑卡 create_plan 的真实形态）；
- **真实写集改动照旧代落盘**：修复判脏口径不得把真改动吞成「工作区已干净」（两态可辨）；
- **协调目录产物零丢失**：settle 前后结果文件原样在场（该段产物是工单继续推进的前提）；
- 两名协调目录（老名/新名）一律不算脏改，多仓形态下**逐仓**同样成立。

与相邻场景的 intent 分界（防 intent 级重复）：
- sc_settle_empty_staging_locks（本票场景②）：彼守**空提交与真失败的可辨性负锁**
  （注入形态 + 真 add/commit 失败必须响亮），本条守**正常收口终态与产物不丢**；
- sc_multirepo_dir_stance（本票场景③）：彼守**新建/存量多仓泳道的目录名姿态**（写侧真源），
  本条只用现成老名泳道验结算行为；
- t260911-03 系（路径闸拒绝面）：彼守闸拒绝后的「0 commit + 脏改动保留 + 点名」，
  本条不碰闸；t260913-05 系（拆道回执/残留）：彼守 merge 后清道，本条零 merge 面。

与 developer L1（server/engine/tests/test_t260914_01_settle_lane_stance.py）的分工：L1 守纯函数/
夹具级形状（含 monkeypatch 注入，白盒可随实现重写），本条守 **activity 级真实 git 态终态**
（真注册 worktree、真 index.lock/hook 注入、多仓逐仓 scope），绑定公开回执与 git 磁盘终态。

故障面清单（覆盖对应用例）：
① 老名泳道只产出协调目录产物（本修核心现场）→ T1；
② 真实改动与协调产物混合（不得吞真改动、也不得把协调产物写进历史）→ T2；
③ 两名协调目录并存（改名过渡期现实形态）→ T3；
④ 老名目录存在但为空（边界）→ T4；
⑤ 多仓逐仓收口（根树＋成员树各有协调产物）→ T5；
⑥ 产物零丢失/资源面（结果文件 settle 前后逐字节在场）→ T1d、T3b。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
引擎 venv/temporalio 缺席 = ENV_FAIL exit 2 点名（本场景无 stdlib 替代子用例：直调 activity）。
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260914_01 import (  # noqa: E402
    check, env_fail, summary, tmpdir, rmtree, init_repo, make_lane_worktree,
    head_count, head_sha, committed_names, dirty_paths, settle_pathspec,
    engine_modules, coordination_dir, write_stage_artifact, write_manifest,
    settle, mixed_project, git_ok,
)

TID = "t26091401a"
TID_M = "t26091401am"


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 activity 无 stdlib 替代子用例" % why)
    shared, aa = mods

    root = init_repo(tmpdir("t260914-01a-"), files={"docs/kb.md": "kb\n"})
    lane = Path(root) / ".lane" / TID
    make_lane_worktree(root, lane, "lane/%s-root" % TID)

    # ---- T1 老名泳道：只产出协调目录产物（本修核心现场） ----
    art = write_stage_artifact(shared, lane)          # 老名协调目录里的结果文件
    art_before = art.read_text(encoding="utf-8")
    n0, sha0 = head_count(lane), head_sha(lane)
    dirty0 = dirty_paths(lane, shared)
    err1, r1 = None, None
    try:
        r1 = settle(shared, aa, lane, TID, "create_plan", 3)
    except Exception as e:
        err1 = "%s: %s" % (type(e).__name__, e)
    check("T1a 老名泳道只产出协调目录产物：settle 正常收口（不得抛异常＝不得被判活动故障）",
          err1 is None, "异常=%s" % err1)
    note1 = (getattr(r1, "note", "") or "") if r1 is not None else ""
    check("T1b 回执可读且非闸拒绝（无 path_gate_reason=，workflow 不会据此转 blocked）",
          bool(note1) and "path_gate_reason=" not in note1, "note=%r" % note1[:200])
    check("T1c 零代落盘 commit（协调目录产物不进历史）",
          head_sha(lane) == sha0 and head_count(lane) == n0,
          "sha %s→%s count %s→%s" % (sha0[:8], head_sha(lane)[:8], n0, head_count(lane)))
    check("T1d agent 产物零丢失（结果文件原样在场，工单可继续推进）",
          art.is_file() and art.read_text(encoding="utf-8") == art_before)
    check("T1e 判脏面已排除老名协调目录（脏判为空，不含老名目录条目）",
          dirty0 == [], "dirty=%r" % (dirty0,))
    check("T1f lane_commits 不增（-1=未取到属既有容许形态）",
          getattr(r1, "lane_commits", -1) in (n0, -1),
          "lane_commits=%r expect %s" % (getattr(r1, "lane_commits", None), n0))

    # ---- T2 真实写集改动照旧代落盘（修复不得吞真改动） ----
    (lane / "docs" / "t260914.md").write_text("real change\n", encoding="utf-8")
    err2, r2 = None, None
    try:
        r2 = settle(shared, aa, lane, TID, "create_plan", 3, write_set=["docs/"])
    except Exception as e:
        err2 = "%s: %s" % (type(e).__name__, e)
    names2 = committed_names(lane)
    check("T2a 真实改动照旧代落盘（新提交落地）", err2 is None and head_count(lane) == n0 + 1,
          "异常=%s count=%s" % (err2, head_count(lane)))
    check("T2b 代落盘内容只含真实改动（协调目录产物不入 commit）",
          names2 == ["docs/t260914.md"]
          and all(shared.DOT_DIR_NEW not in x and shared.DOT_DIR_OLD not in x for x in names2),
          "committed=%r" % (names2,))

    # ---- T3 两名协调目录并存（改名过渡期现实形态） ----
    art_new = write_stage_artifact(shared, lane, new=True)
    n3, sha3 = head_count(lane), head_sha(lane)
    err3, r3 = None, None
    try:
        r3 = settle(shared, aa, lane, TID, "create_plan", 3)
    except Exception as e:
        err3 = "%s: %s" % (type(e).__name__, e)
    check("T3a 两名协调目录并存：settle 正常收口、零 commit",
          err3 is None and head_sha(lane) == sha3 and head_count(lane) == n3,
          "异常=%s" % err3)
    check("T3b 两名目录产物均原样在场（零丢失）",
          art.is_file() and art_new.is_file())

    # ---- T4 老名目录存在但为空（边界） ----
    empty_root = init_repo(tmpdir("t260914-01a-empty-"), files={"README.md": "x\n"})
    lane_e = Path(empty_root) / ".lane" / (TID + "e")
    make_lane_worktree(empty_root, lane_e, "lane/%s-root" % (TID + "e"))
    coordination_dir(shared, lane_e).mkdir(parents=True, exist_ok=True)
    ne = head_count(lane_e)
    err4 = None
    try:
        settle(shared, aa, lane_e, TID + "e", "create_plan", 0)
    except Exception as e:
        err4 = "%s: %s" % (type(e).__name__, e)
    check("T4 空老名目录（边界）：正常收口、零 commit",
          err4 is None and head_count(lane_e) == ne, "异常=%s" % err4)

    # ---- T5 多仓老名泳道：逐仓收口（根树＋成员树各有协调产物） ----
    # 夹具对齐产品契约（advisory④：多仓项目的根仓 .gitignore 忽略泳道容器内的成员树
    # 目录）：成员树是**另一棵仓的已注册 worktree**，不忽略时 git add -A 会把它当作
    # embedded 仓库暂存成 gitlink 提交进根树——那是与本票守护面无关的第三方脏源
    # （实测 T5 形态修复前后同形同因：提交内容都是 gitlink repo_a，非本次三修引入）。
    # 只忽略成员树、**不忽略两名协调目录**：协调目录"未 gitignore 时靠引擎判脏/撤下兜底"
    # 正是本票要守的现场形态（dengzhufpv/t260911-07 的 .dsh/、老名目录都是未忽略态）。
    proj = mixed_project("t260914-01a-mixed-", gitignore=("repo_a/",))
    lane_m = Path(proj) / ".lane" / TID_M
    make_lane_worktree(proj, lane_m, "lane/%s-root" % TID_M)
    member = lane_m / "repo_a"
    ok, out = git_ok(["worktree", "add", "-b", "lane/%s-repo_a" % TID_M, str(member), "HEAD"],
                     proj / "repo_a")
    if not ok:
        env_fail("成员仓 worktree add 失败（夹具环境问题，非被测红）：%s" % out[-200:])
    art_r = write_stage_artifact(shared, lane_m)
    art_a = write_stage_artifact(shared, member)
    entries = [{"repo": "", "name": "root", "branch": "lane/%s-root" % TID_M},
               {"repo": "repo_a", "name": "repo_a", "branch": "lane/%s-repo_a" % TID_M}]
    write_manifest(shared, lane_m, entries, legacy=True)
    nr, na_ = head_count(lane_m), head_count(member)
    err5, r5 = None, None
    try:
        r5 = settle(shared, aa, lane_m, TID_M, "create_plan", 0)
    except Exception as e:
        err5 = "%s: %s" % (type(e).__name__, e)
    check("T5a 多仓老名泳道逐仓收口：settle 不抛异常（两树均不得被判活动故障）",
          err5 is None, "异常=%s" % err5)
    check("T5b 两树零代落盘 commit（根树与成员树的协调产物都不进历史）",
          head_count(lane_m) == nr and head_count(member) == na_,
          "root %s→%s member %s→%s" % (nr, head_count(lane_m), na_, head_count(member)))
    check("T5c 两树协调产物原样在场", art_r.is_file() and art_a.is_file())
    check("T5d 逐仓回执可读（多仓形态下 note 不得为空）",
          bool((getattr(r5, "note", "") or "").strip()),
          "note=%r" % ((getattr(r5, "note", "") or "")[:200],))

    rmtree(root, empty_root, proj)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
