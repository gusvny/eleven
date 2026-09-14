#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260914-01 场景③：多仓泳道协调目录名的对外姿态（灰盒 L2，真 git 夹具，无 docker 无 Temporal）。

intent（守护的用户可感知行为/契约）：
- **新建多仓泳道不再诞出老名目录**：清单落「协调目录解析真源」位（新泳道＝新名目录），
  泳道整条命不再被老名粘滞（后续所有段/产物目录随之归位）；
- **存量老名泳道保持粘滞**：重进 prepare 时清单**原地复写**、不诞出新名目录、不改写历史
  位置（改名过渡期的在飞票不被翻转；本修不得依赖任何手工迁移）；
- **读侧对存量位置零回归**：老名清单照旧可读（含「杂散新名目录 + 老名清单」过渡形态
  仍取到清单），读动作零副作用；
- **判定不放宽**：清单损坏照旧 fail-closed（RuntimeError），无形单仓照旧回落单仓锚。

与相邻场景的 intent 分界（防 intent 级重复）：本条守**目录名/清单位置的写读姿态**（写侧
真源与读侧回落契约）；引擎 L1（server/engine/tests）守纯函数与夹具级解析；t260910-03/-08、
t260911-04、t260913-05 等真链场景守各自旅程终态（本修只让它们的清单锚点跟随真源，intent
不变）。本条零 docker 零 Temporal，秒级，能与上述真链场景并存不互替。

与 developer L1（server/engine/tests/test_t260914_01_settle_lane_stance.py）的分工：L1 守纯函数/
夹具级形状（含 monkeypatch 注入，白盒可随实现重写），本条守 **activity 级真实 git 态终态**
（真注册 worktree、真 index.lock/hook 注入、多仓逐仓 scope），绑定公开回执与 git 磁盘终态。

故障面清单：① 新建多仓泳道目录名姿态 → T1；② prepare 幂等重入 → T2；
③ 存量老名泳道粘滞不翻转 → T3；④ 过渡形态（杂散新名目录＋老名清单）读侧不瞎 → T4；
⑤ 无形单仓回落 → T5a；⑥ 清单损坏 fail-closed 不放宽 → T5b；⑦ 读动作零副作用 → T4c。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
引擎 venv/temporalio 缺席 = ENV_FAIL exit 2 点名（本场景无 stdlib 替代腿：直调 activity）。
"""
import json
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
    engine_modules, write_manifest, manifest_at, prepare, mixed_project, git,
)

TID = "t26091401c"


def _registered(tree, repo):
    p = git(["worktree", "list", "--porcelain"], repo)
    return ("worktree %s" % Path(tree).resolve()) in p.stdout


def _entries(tid, rels=("", "repo_a")):
    out = []
    for rel in rels:
        out.append({"repo": rel, "name": ("root" if not rel else rel),
                    "branch": "lane/%s-%s" % (tid, ("root" if not rel else rel))})
    return out


def _read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 activity 无 stdlib 替代腿" % why)
    shared, aa = mods
    tmp_roots = []

    # ---- T1 新建多仓泳道：清单落新名解析位、零老名目录诞生 ----
    proj = mixed_project("t260914-01c-new-")
    tmp_roots.append(proj)
    lane = Path(proj) / ".lane" / (TID + "n")
    entries = _entries(TID + "n")
    res = prepare(shared, aa, lane, proj, entries, ["docs/kb.md", "repo_a/src/a.py"], TID + "n")
    mp = manifest_at(shared, lane)
    check("T1a 新多仓泳道 prepare 全绿（created）",
          bool(getattr(res, "ok", False)) and getattr(res, "action", "") == "created",
          "res=%r" % (res,))
    check("T1b 清单落协调目录解析真源位（新名目录/repo_worktrees.json）",
          mp.is_file() and mp.parent.name == shared.DOT_DIR_NEW
          and mp.name == shared.MULTI_MANIFEST_NAME, "path=%s" % mp)
    check("T1c 新泳道零老名目录诞生（病灶③的对外可判形态）",
          not (Path(lane) / shared.DOT_DIR_OLD).exists())
    if mp.is_file():
        got = sorted((e.get("repo", ""), e.get("branch", "")) for e in _read(mp))
        exp = sorted((e["repo"], e["branch"]) for e in entries)
        check("T1d 清单条目与明细一致（repo/branch 全）", got == exp, "got=%r exp=%r" % (got, exp))
    else:
        check("T1d 清单条目与明细一致（repo/branch 全）", False, "清单不在场：%s" % mp)
    check("T1e 两树均为所属仓已注册 worktree",
          _registered(lane, proj) and _registered(Path(lane) / "repo_a", Path(proj) / "repo_a"))

    # ---- T2 prepare 幂等重入：位置不变、不诞新目录 ----
    res2 = prepare(shared, aa, lane, proj, entries, ["docs/kb.md", "repo_a/src/a.py"], TID + "n")
    check("T2a 二次 prepare 走复用（reused）且清单仍在解析位",
          bool(getattr(res2, "ok", False)) and getattr(res2, "action", "") == "reused"
          and manifest_at(shared, lane).is_file(),
          "res=%r" % (res2,))
    check("T2b 复用后零老名目录诞生", not (Path(lane) / shared.DOT_DIR_OLD).exists())

    # ---- T3 存量老名泳道重进 prepare：原地粘滞、不翻转 ----
    proj3 = mixed_project("t260914-01c-old-")
    tmp_roots.append(proj3)
    lane3 = Path(proj3) / ".lane" / (TID + "o")
    make_lane_worktree(proj3, lane3, "lane/%s-root" % (TID + "o"))
    ok3 = git(["worktree", "add", "-b", "lane/%s-repo_a" % (TID + "o"),
               str(lane3 / "repo_a"), "HEAD"], Path(proj3) / "repo_a").returncode == 0
    if not ok3:
        env_fail("成员仓 worktree add 失败（夹具环境问题，非被测红）")
    entries3 = _entries(TID + "o")
    write_manifest(shared, lane3, entries3, legacy=True)
    res3 = prepare(shared, aa, lane3, proj3, entries3, ["docs/kb.md"], TID + "o")
    legacy3 = Path(lane3) / shared.DOT_DIR_OLD / shared.MULTI_MANIFEST_NAME
    check("T3a 存量老名泳道 prepare 全绿（复用）",
          bool(getattr(res3, "ok", False)) and getattr(res3, "action", "") == "reused",
          "res=%r" % (res3,))
    check("T3b 清单原地复写在老名位（粘滞，不换名、不改历史位置）",
          legacy3.is_file() and not (Path(lane3) / shared.DOT_DIR_NEW).exists(),
          "legacy=%s new_dir_exists=%s" % (legacy3.is_file(),
                                           (Path(lane3) / shared.DOT_DIR_NEW).exists()))
    if legacy3.is_file():
        got3 = sorted((e.get("repo", ""), e.get("branch", "")) for e in _read(legacy3))
        check("T3c 复写内容与明细一致（base_ref 同批刷新）",
              got3 == sorted((e["repo"], e["branch"]) for e in entries3)
              and all("base_ref" in e for e in _read(legacy3)),
              "got=%r" % (got3,))
    else:
        check("T3c 复写内容与明细一致（base_ref 同批刷新）", False, "老名位清单不在场")
    scopes3 = aa._lane_scopes(lane3, write_set=["docs/kb.md", "repo_a/src/a.py"])
    check("T3d 老名清单读侧零回归（逐仓 scope=2，读得到成员仓）",
          len(scopes3) == 2 and sorted(s["repo_rel"] for s in scopes3) == ["", "repo_a"],
          "scopes=%r" % ([s["repo_rel"] for s in scopes3],))

    # ---- T4 过渡形态：杂散新名目录 + 老名清单 → 读侧仍取到清单 ----
    stray = Path(lane3) / shared.DOT_DIR_NEW / "screenshots"
    stray.mkdir(parents=True, exist_ok=True)
    (stray / "x.png").write_bytes(b"p")
    check("T4a 写侧语义已在解析位（新名目录在场→解析翻新名）",
          manifest_at(shared, lane3).parent.name == shared.DOT_DIR_NEW)
    check("T4b 读侧仍取到老名清单（过渡形态不瞎：解析位不是文件时回落老名镜像位）",
          manifest_at(shared, lane3, legacy_fallback=True) == legacy3,
          "read=%s legacy=%s" % (manifest_at(shared, lane3, legacy_fallback=True), legacy3))
    scopes4 = aa._lane_scopes(lane3, write_set=["docs/kb.md"])
    check("T4c 过渡形态下逐仓 scope=2 且读动作零副作用（不新建清单文件）",
          len(scopes4) == 2
          and not (Path(lane3) / shared.DOT_DIR_NEW / shared.MULTI_MANIFEST_NAME).exists(),
          "scopes=%r" % ([s["repo_rel"] for s in scopes4],))

    # ---- T5 判定不放宽：无形单仓回落 / 清单损坏 fail-closed ----
    proj5 = init_repo(tmpdir("t260914-01c-single-"), files={"README.md": "s\n"})
    tmp_roots.append(proj5)
    lane5 = Path(proj5) / ".lane" / (TID + "s")
    make_lane_worktree(proj5, lane5, "lane/%s-s-root" % TID)
    scopes5 = aa._lane_scopes(lane5, write_set=["README.md"])
    check("T5a 无形＝单仓回落（既有语义不变，1 scope、无成员仓）",
          len(scopes5) == 1 and scopes5[0]["repo_rel"] == "", "scopes=%r" % (scopes5,))

    proj6 = mixed_project("t260914-01c-bad-")
    tmp_roots.append(proj6)
    lane6 = Path(proj6) / ".lane" / (TID + "b")
    make_lane_worktree(proj6, lane6, "lane/%s-b-root" % TID)
    bad = Path(lane6) / shared.DOT_DIR_NEW / shared.MULTI_MANIFEST_NAME
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json", encoding="utf-8")
    raised = ""
    try:
        aa._lane_scopes(lane6, write_set=[])
    except Exception as e:
        raised = "%s: %s" % (type(e).__name__, e)
    check("T5b 清单损坏 fail-closed（RuntimeError 点名，绝不静默回落单仓锚）",
          "RuntimeError" in raised, "raised=%r" % raised[:200])

    rmtree(*tmp_roots)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
