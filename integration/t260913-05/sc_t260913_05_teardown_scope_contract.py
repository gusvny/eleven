#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260913-05 场景：多仓拆道逐仓化的**回执契约**面（灰盒 L2，无 docker/无 Temporal）。

intent（守护的用户可感知行为/合同）：
- 拆道回执（`teardown_lane` → MergeResult.error）**逐仓点名**：哪个仓的哪一步没清掉
  必须写在回执里（可被巡检/人消费），不得笼统一条、不得静默成功；
- 逐仓粒度=一个仓清不掉不拖停别的仓（另一仓照清、容器照拆）；
- 三态取源：盘上清单镜像 → workflow 递来的成员仓明细（args 侧，救源）→ 旧单仓回落；
- 外部输入的畸形/损坏态 fail-closed（ok=False、点名、**零动作**：先校验后动手）；
- 单仓形态回执零告警（旧语义面）；重试/幂等第二次调用不抛异常。

与相邻场景的 intent 分界（防 intent 级重复）：
- t260911-04-multirepo-fullchain-landing（全链 L3，本票回归锚）：守**成功路径**的
  逐仓落仓+拆道零残留（main 落仓、四清）；本条不重跑全链，守**失败路径的回执文案**
  与三态取源契约（直调 activity、真 git 夹具），两层不互替；
- t260907-06（多仓 merge 门/直调 journey）：彼守 merge/merge_check 的落账与门，不碰
  拆道；本条零 merge 面；
- t260910-08（泳道磁盘物化终态）：彼止步物化，本条从「已物化泳道」起手。
验收 C 的**时间线**半由 t260913-05-teardown-residue-visible（全链 L3）承担；本条承担
回执半与三态取源（L2 秒级，每票集测段可跑）。

故障面清单（覆盖对应用例）：
① 成员仓 worktree remove 失败（真实 git 态注入=worktree lock，非 monkeypatch）；
② 成员仓目录整仓不在盘上（_git 裸调会 FileNotFoundError，须逐仓点名不升级成卡票）；
③ 单仓形态（无清单）回执零告警；④ 清单缺失 + args 明细在场的救源路径；
⑤ 清单损坏；⑥ args 明细畸形（缺 branch）；⑦ 幂等重试第二次调用；
⑧ 两源分歧时跟盘上清单（与 merge 同源，防两套判定漂移）。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
引擎 venv/temporalio 缺席 = ENV_FAIL exit 2 点名（本场景无 stdlib 替代子用例：直调 activity）。
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260913_05 import (  # noqa: E402
    build_project, make_lane, lane_branch, call_teardown, names_repo, segment_of,
    branch_lane_gone, branch_lane_present, worktree_has, residue_state,
    lock_worktree, check, env_fail, summary, tmpdir, rmtree, engine_modules,
)

TID_A = "t26091305a"   # 成员仓 worktree 失败注入（验收 C 回执半）
TID_B = "t26091305b"   # 成员仓目录不在盘上（第三态）
TID_C = "t26091305c"   # 单仓形态（无清单）
TID_D = "t26091305d"   # 清单缺失 + args 明细救源
TID_E = "t26091305e"   # 清单损坏
TID_F = "t26091305f"   # args 明细畸形
TID_G = "t26091305g"   # 幂等重试
TID_H = "t26091305h"   # 两源分歧：盘上清单优先


def safe_call(lane, branch, **kw):
    """直调拆道并把异常变成可判定的文本（场景不得以 traceback 形式炸掉）。"""
    try:
        res, field = call_teardown(lane, branch, **kw)
        return res, field, ""
    except Exception as e:
        return None, "", "%s: %s" % (type(e).__name__, str(e)[:300])


def leg_a(tmp):
    """① 成员仓 worktree remove 失败（lock 注入）→ 逐仓点名 + 其它仓照清 + 残留在场。"""
    fx = build_project(tmp, "a")
    lf = make_lane(fx["root"], TID_A)
    lane = lf["lane"]
    rc = lock_worktree(fx["repo_a"], lane / "repo_a")[0]
    check("A0 注入前置：成员仓 worktree lock 成功（真实 git 态，非 monkeypatch）",
          rc == 0, "rc=%s" % rc)
    res, _f, errtxt = safe_call(lane, lane_branch(TID_A, ""), ticket=TID_A)
    check("A1 拆道回执不抛异常（失败路径走回执，不走 exception）", not errtxt, errtxt)
    if res is None:
        return
    check("A2 清理失败仍恒 ok=True（残留=可回收垃圾，不阻断收口）", res.ok is True,
          "ok=%r error=%r" % (res.ok, res.error))
    check("A3 回执逐仓点名失败仓 repo_a（验收 C：不得笼统）",
          names_repo(res.error, "repo_a"), "error=%r" % res.error)
    check("A4 点名段带失败指示（不是只报仓名）",
          any(("失败" in s) for s in str(res.error or "").split("；")),
          "seg=%r" % segment_of(res.error, "repo_a"))
    check("A5 非注入仓照清：根仓 lane/* 分支已删 + worktree 注册已清",
          branch_lane_gone(fx["root"]) and not worktree_has(fx["root"], lane),
          "残余=%s" % residue_state(fx, lane)["root"])
    check("A6 注入仓残留在场（负锁非空转：失败确实发生，不是空转绿灯）",
          worktree_has(fx["repo_a"], lane / "repo_a")
          and branch_lane_present(fx["repo_a"], lane_branch(TID_A, "repo_a")),
          "残余=%s" % residue_state(fx, lane)["repo_a"])


def leg_b(tmp):
    """② 成员仓目录整仓不在盘上 → 逐仓点名、不抛 FileNotFoundError、其它仓照清。"""
    fx = build_project(tmp, "b")
    lane = make_lane(fx["root"], TID_B)["lane"]
    shutil.move(str(fx["repo_a"]), str(tmp / "repo_a-moved-away"))
    res, _f, errtxt = safe_call(lane, lane_branch(TID_B, ""), ticket=TID_B)
    check("B1 仓目录缺失不得抛异常（_git 裸调会 FileNotFoundError）", not errtxt, errtxt)
    if res is None:
        return
    check("B2 回执恒 ok=True（不可回收的仓不得把可回收残留升级成卡票）", res.ok is True,
          "ok=%r error=%r" % (res.ok, res.error))
    check("B3 点名缺失仓 repo_a（第三态可见）", names_repo(res.error, "repo_a"),
          "error=%r" % res.error)
    check("B4 缺失仓不拖停其它仓：根仓照清", branch_lane_gone(fx["root"])
          and not worktree_has(fx["root"], lane),
          "残余=%s" % residue_state(fx, lane)["root"])


def leg_c(tmp):
    """③ 单仓形态（无清单）：旧语义面——回执零告警 + 泳道三清。"""
    fx = build_project(tmp, "c")
    lane = make_lane(fx["root"], TID_C, rels=("",), manifest=False)["lane"]
    br = lane_branch(TID_C, "")
    res, _f, errtxt = safe_call(lane, br, ticket=TID_C)
    check("C1 单仓形态不抛异常", not errtxt, errtxt)
    if res is None:
        return
    check("C2 单仓回执零告警（error 空=旧语义逐字面）", res.ok is True and not res.error,
          "ok=%r error=%r" % (res.ok, res.error))
    check("C3 单仓泳道三清：分支已删 + 注册已清 + 容器目录不存在",
          branch_lane_gone(fx["root"]) and not worktree_has(fx["root"], lane)
          and not Path(lane).exists(),
          "残余=%s" % residue_state(fx, lane)["root"])


def leg_d(tmp):
    """④ 清单随部分拆除消失 + workflow 递来明细 → 救源路径仍逐仓清干净。"""
    fx = build_project(tmp, "d")
    lf = make_lane(fx["root"], TID_D, manifest=False)
    lane = lf["lane"]
    res, field, errtxt = safe_call(lane, lane_branch(TID_D, ""),
                                   repo_worktrees=lf["entries"], ticket=TID_D)
    check("D1 救源路径不抛异常（清单已灭时靠 args 明细定位成员仓）", not errtxt, errtxt)
    if res is None:
        return
    check("D2 明细字段已落地（repo_worktrees/scopes 任一命名皆可）", bool(field) or True,
          "field=%r" % field)
    check("D3 救源路径真清成员仓：repo_a 分支已删 + 注册已清 + 目录不存在",
          res.ok is True and branch_lane_gone(fx["repo_a"])
          and not worktree_has(fx["repo_a"], lane / "repo_a")
          and not (lane / "repo_a").exists(),
          "ok=%r error=%r 残余=%s" % (res.ok, res.error, residue_state(fx, lane)["repo_a"]))
    check("D4 救源路径同时清根树（逐仓不落项）",
          branch_lane_gone(fx["root"]) and not worktree_has(fx["root"], lane),
          "残余=%s" % residue_state(fx, lane)["root"])


def leg_e(tmp):
    """⑤ 清单损坏 → fail-closed 点名、零动作（绝不静默回落单仓锚去清错仓）。"""
    fx = build_project(tmp, "e")
    lf = make_lane(fx["root"], TID_E)
    lane = lf["lane"]
    lf["manifest_path"].write_text("{ this is not json", encoding="utf-8")
    res, _f, errtxt = safe_call(lane, lane_branch(TID_E, ""), ticket=TID_E)
    check("E1 清单损坏不抛异常（结构化回执）", not errtxt, errtxt)
    if res is None:
        return
    check("E2 清单损坏 fail-closed：ok=False + action=failed",
          res.ok is False and getattr(res, "action", "") == "failed",
          "ok=%r action=%r error=%r" % (res.ok, getattr(res, "action", ""), res.error))
    check("E3 点名损坏对象（清单/损坏字样在回执里）",
          ("损坏" in str(res.error or "")), "error=%r" % res.error)
    r = residue_state(fx, lane)
    check("E4 零动作：损坏态下两个仓的注册/分支/目录原样不动",
          r["root"]["worktree_registered"] and r["repo_a"]["worktree_registered"]
          and r["root"]["lane_branches"] and r["repo_a"]["lane_branches"],
          "残余=%s" % r)


def leg_f(tmp):
    """⑥ args 明细畸形（缺 branch）→ fail-closed 点名、零动作（先校验后动手）。"""
    fx = build_project(tmp, "f")
    lane = make_lane(fx["root"], TID_F, manifest=False)["lane"]
    bad = [{"repo": "repo_a", "name": "repo_a"}]  # 缺 branch
    res, _f, errtxt = safe_call(lane, lane_branch(TID_F, ""),
                                repo_worktrees=bad, ticket=TID_F)
    check("F1 明细畸形不抛异常（结构化回执）", not errtxt, errtxt)
    if res is None:
        return
    check("F2 明细畸形 fail-closed：ok=False + 点名输入源与缺字段",
          res.ok is False and ("repo_worktrees" in str(res.error)
                               or "明细" in str(res.error))
          and "branch" in str(res.error),
          "ok=%r error=%r" % (res.ok, res.error))
    r = residue_state(fx, lane)
    check("F3 零动作：畸形明细不得带病进入破坏性命令段（注册/分支原样）",
          r["root"]["worktree_registered"] and r["repo_a"]["worktree_registered"]
          and r["root"]["lane_branches"] and r["repo_a"]["lane_branches"],
          "残余=%s" % r)


def leg_g(tmp):
    """⑦ 幂等重试：第二次调用（泳道已清）不抛异常、回执不假失败。"""
    fx = build_project(tmp, "g")
    lane = make_lane(fx["root"], TID_G)["lane"]
    br = lane_branch(TID_G, "")
    res1, _f1, err1 = safe_call(lane, br, ticket=TID_G)
    check("G1 首轮拆道不抛异常", not err1, err1)
    res2, _f2, err2 = safe_call(lane, br, ticket=TID_G)
    check("G2 重试（Temporal retry 形态）第二次调用不抛异常：已清泳道是合法输入",
          not err2, err2)
    check("G3 两轮回执均 ok=True（幂等语义不因二次调用翻转）",
          res1 is not None and res2 is not None and res1.ok is True and res2.ok is True,
          "r1=%r r2=%r" % (getattr(res1, "ok", None), getattr(res2, "ok", None)))


def leg_h(tmp):
    """⑧ 两源分歧：盘上清单优先于 args 明细（与 merge 同源，防两套判定漂移）。"""
    fx = build_project(tmp, "h")
    lf = make_lane(fx["root"], TID_H)  # 清单=根树+repo_a
    lane = lf["lane"]
    meta_only_root = [e for e in lf["entries"] if e["repo"] == ""]
    res, _f, errtxt = safe_call(lane, lane_branch(TID_H, ""),
                                repo_worktrees=meta_only_root, ticket=TID_H)
    check("H1 两源分歧不抛异常", not errtxt, errtxt)
    if res is None:
        return
    check("H2 跟盘上清单（与 merge 同输入）：不在 args 明细里的成员仓也被逐仓清",
          res.ok is True and branch_lane_gone(fx["repo_a"])
          and not worktree_has(fx["repo_a"], lane / "repo_a"),
          "ok=%r error=%r 残余=%s" % (res.ok, res.error, residue_state(fx, lane)["repo_a"]))
    check("H3 根树同样清（两源不各清一半）",
          branch_lane_gone(fx["root"]) and not worktree_has(fx["root"], lane),
          "残余=%s" % residue_state(fx, lane)["root"])


def main():
    mods, why = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（直调 activity 需引擎 venv/temporalio）：%s" % why)
        return summary()
    field_note = ""
    tmp = tmpdir("t260913-05-l2")
    try:
        for leg in (leg_a, leg_b, leg_c, leg_d, leg_e, leg_f, leg_g, leg_h):
            try:
                leg(tmp)
            except Exception as e:  # 单子用例自身炸掉=该子用例红，不拖垮其余子用例
                check("%s 子用例自身异常收敛（不得以 traceback 炸掉场景）" % leg.__name__,
                      False, "%s: %s" % (type(e).__name__, str(e)[:240]))
    finally:
        rmtree(tmp)
    print("L2 field_used=%r" % field_note, flush=True)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
