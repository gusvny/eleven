#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-19 场景①：越权处置按 porcelain 状态分流（灰盒 L2，真 git 夹具，无 docker 无 Temporal）。

intent（守护的用户可感知行为/契约，工单修向 B＝滞留复判解除 + D＝证据面全量清单）：
- **?? 态越权（未跟踪新建）自动挪档**：从工作区消失、留档进引擎 dot 目录 quarantine（相对路径
  保留+manifest 审计）、回执点名去向——下一次 settle 不再被同批文件复判（实案死结②的解除面）；
- **M 态越权（tracked 修改）回滚＋diff 留档**：工作区回到基线（分支零删除落盘）、留档 diff
  可 `git apply` 还原（agent 修改零丢失，只是不落在分支上）；
- **D 态（删除型）/ staged（暂存型）越权拒绝＋人处，不自动动**：删除/暂存意图不可机判，
  fail-closed 不猜——拒绝终态只在这两态与 protected 上存在；
- **protected_path 拒绝一律不动**：人审放行通道需文件原地保留（t260912-03 授权面前提）；
- **混合批次一次处置**：合法产物与越权件同批时，处置后合法产物照常代落盘，且代落盘内容
  恰为合法清单（越权件与其留档件绝不进 commit）；
- **拒绝回执 judged_files＝本次实际判定脏清单全量**（不止违规项）——实案④「证据面歧义」的
  结构化解除面：人从回执就能看出引擎这一轮看过哪些文件。

与相邻场景 intent 分界（防 intent 级重复）：
- sc_t26091619_incident_replay（本票场景②）：彼锁**实案形态重演**（顶层 sc_*/README 合法化
  =修向 C 旅程 + lint_tests.py M 态回滚），本条锁**处置矩阵逐态终态**（含 D/staged/protected
  拒绝腿与 judged_files 证据面），分态不分家；
- t260911-03 系（路径闸拒绝面）：彼守**拒绝终态三件套**（0 commit+点名+原因码；越权腿=删除
  型 D 态——t260916-19 起 ??/M 态改自动处置不再终态拒绝），本条守**处置后的二次 settle 转绿**
  与留档可还原，彼不碰处置、本条不重复拒绝面枚举；
- t260914-01 系（settle 姿态）：彼守协调目录产物收口/空提交可辨，本条零协调目录面。

与 developer L1（test_t260914_01 形态真 git fixture 逐态腿）分工：L1 白盒逐态可随实现重写，
本条锁 **activity 级公开回执 + git 磁盘终态 + 留档可还原性**（契约不变的实现重构不得打破）。

故障面清单（覆盖对应用例）：
① ?? 挪档后二次 settle 复绿（滞留复判解除）→ L1；
② M 回滚后基线还原+留档可 apply（产物零丢失与分支零删除并存）→ L2；
③ D/staged 不可机判态 fail-closed 拒绝、状态不被引擎偷改 → L3/L4；
④ 受保护件两形：面内（gate② protected_path 判定）与面外（gate① 命中）都不进自动处置——
   保护名单优先于状态分流，工作区原地保留＝人处/授权前提 → L5a/L5b；
⑤ 合法与越权混合批次：只落合法清单、越权与留档件绝不入库 → L6；
⑥ judged_files 全量判定清单（证据面歧义解除）→ L3；
⑦ 留档件对后续 settle 不可见（dot 目录排除口径，处置不制造新脏）→ L1/L2 二次 settle 腿。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260916-19/sc_t26091619_disposal_matrix.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现落地前新契约腿红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260916_19 import (  # noqa: E402
    check, env_fail, summary, mk_lane, rmtree, head_sha, head_count,
    committed_names, read_file, status_entries, apply_check, engine_modules,
    settle, quarantine_root, archive_find, BASE,
)

TID = "t26091619a"


def main():
    (mods, why) = engine_modules()
    if mods is None:
        env_fail("引擎模块不可用（%s）——直调 activity 无 stdlib 替代腿" % why)
    shared, aa = mods

    # ---- L1 ?? 态（未跟踪新建越权）→ 挪档＋回执点名去向＋二次 settle 复绿 ----
    print("\n== L1 ?? 挪档：工作区消失+留档+点名+复绿（滞留复判解除）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l1-")
    rogue = lane / "docs" / "rogue.md"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text("self-rescue artifact\n", encoding="utf-8")
    n0, sha0 = head_count(lane), head_sha(lane)
    r1 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note1 = r1.note or ""
    qroot = quarantine_root(lane, shared)
    check("L1a 无终态拒绝（?? 态改自动处置，不再产生 path_gate_reason 终态）",
          "path_gate_reason=" not in note1, "note=%r" % note1[:200])
    check("L1b 回执点名处置对象与去向（ rogue.md 在回执）",
          "docs/rogue.md" in note1, "note=%r" % note1[:200])
    check("L1c 越权件已离开工作区（下一轮 status 不再见到它＝不复判）",
          not rogue.exists(), "still exists")
    check("L1d 留档在隔离档内（相对路径保留，manifest 审计在场）",
          bool(archive_find(qroot, "rogue.md"))
          and bool(archive_find(qroot, "manifest.json")),
          "root=%s found=%r" % (qroot, [p.name for p in archive_find(qroot, "rogue.md")]))
    check("L1e 零代落盘 commit（处置不产生历史）",
          head_sha(lane) == sha0 and head_count(lane) == n0,
          "sha %s→%s" % (sha0[:8], head_sha(lane)[:8]))
    r1b = settle(shared, aa, lane, TID, "arbitrate", 2, fork)
    check("L1f 二次 settle 复绿（无原因码＝不再被同批文件复判）且零新档扰动",
          "path_gate_reason=" not in (r1b.note or ""), "note=%r" % (r1b.note or "")[:200])
    rmtree(tmp)

    # ---- L2 M 态（tracked 修改越权）→ 回滚＋diff 留档可还原 ----
    print("\n== L2 M 回滚：基线还原+diff 留档可 apply（产物零丢失、分支零删除）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l2-")
    (lane / "docs" / "kb.md").write_text("kb hacked by agent\n", encoding="utf-8")
    baseline = read_file(mainrepo, "docs/kb.md")
    n0, sha0 = head_count(lane), head_sha(lane)
    r2 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note2 = r2.note or ""
    qroot = quarantine_root(lane, shared)
    # 留档锚实质不锚命名：diff 件=档内 *.diff 且 diff 头点名原路径（方案钉名 <原路径>.diff，
    # 但公开契约只是「该路径的修改以 diff 留档且可还原」）。
    diffs = [p for p in qroot.rglob("*.diff") if p.is_file()
             and "docs/kb.md" in p.read_text(encoding="utf-8", errors="replace")] \
        if qroot.is_dir() else []
    check("L2a 无终态拒绝（M 态改自动处置）", "path_gate_reason=" not in note2,
          "note=%r" % note2[:200])
    check("L2b 回执点名处置对象（kb.md 在回执）", "docs/kb.md" in note2,
          "note=%r" % note2[:200])
    check("L2c 工作区回到基线（分支零删除落盘、基线内容未丢）",
          read_file(lane, "docs/kb.md") == baseline, "now=%r" % read_file(lane, "docs/kb.md"))
    check("L2d 留档 diff 在档且可 git apply 还原（agent 修改零丢失）",
          bool(diffs) and apply_check(lane, diffs[0].read_text(encoding="utf-8"))[0],
          "diffs=%r" % [p.name for p in diffs])
    check("L2e 零代落盘 commit", head_sha(lane) == sha0, "sha=%s" % head_sha(lane)[:8])
    rmtree(tmp)

    # ---- L3 D 态（删除型越权）→ 拒绝＋人处＋judged_files 全量 ----
    print("\n== L3 D 拒绝：终态拒绝保留+judged_files 全量判定清单（证据面）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l3-")
    (lane / "docs" / "kb.md").unlink()                       # D 态越权（不可机判意图）
    (lane / "tests" / "legit.md").write_text("legit edited\n",
                                             encoding="utf-8")  # 合法 M（面内）
    n0, sha0 = head_count(lane), head_sha(lane)
    r3 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note3 = r3.note or ""
    gref = r3.gate_refusal if isinstance(r3.gate_refusal, dict) else {}
    files = gref.get("files") or []
    judged = gref.get("judged_files") or []
    check("L3a 删除型越权拒绝（终态拒绝只留 D/staged/protected，fail-closed 不猜意图）",
          "path_gate_reason=" in note3, "note=%r" % note3[:200])
    check("L3b 原因码=unauthorized_path 且点名违规路径",
          gref.get("reason_code") == "unauthorized_path" and "docs/kb.md" in note3,
          "rc=%r files=%r" % (gref.get("reason_code"), files))
    check("L3c judged_files=本次实际判定脏清单全量（含合法改动，不止违规项）",
          "docs/kb.md" in judged and "tests/legit.md" in judged,
          "judged=%r" % judged)
    check("L3d 删除态不被引擎偷改（仍呈待删、未恢复未提交＝人处前提）",
          read_file(lane, "docs/kb.md") is None and head_sha(lane) == sha0,
          "exists=%r sha=%s" % (read_file(lane, "docs/kb.md") is not None,
                                head_sha(lane)[:8]))
    rmtree(tmp)

    # ---- L4 staged 态（暂存型越权）→ 拒绝＋人处，暂存态不被引擎偷改 ----
    print("\n== L4 staged 拒绝：暂存意图不自动动（fail-closed）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l4-")
    rogue2 = lane / "docs" / "rogue2.md"
    rogue2.write_text("staged rogue\n", encoding="utf-8")
    gitadd = __import__("subprocess").run(
        ["git", "add", "docs/rogue2.md"], cwd=str(lane),
        capture_output=True, text=True)
    if gitadd.returncode != 0:
        env_fail("夹具 git add 失败（环境问题非被测红）：%s" % gitadd.stderr[-200:])
    sha0 = head_sha(lane)
    r4 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note4 = r4.note or ""
    ents = status_entries(lane, shared) or []
    staged = [p for xy, p in ents if xy and xy[0] not in (" ", "?")]
    check("L4a 暂存型越权拒绝（终态拒绝）", "path_gate_reason=" in note4,
          "note=%r" % note4[:200])
    check("L4b 暂存态原样保留（引擎不代用户清暂存＝人处前提）",
          "docs/rogue2.md" in staged, "entries=%r" % ents)
    check("L4c 零代落盘 commit", head_sha(lane) == sha0, "sha=%s" % head_sha(lane)[:8])
    rmtree(tmp)

    # ---- L5 受保护件两形：面内（gate② protected_path）不动＝授权命门；面外按面判定处置 ----
    print("\n== L5a 面内受保护 M 态：不动（人审放行通道需文件原地）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l5-", base=dict(
        BASE, **{"integration/t260902-07/tests/test_route_table.py": "# shared guard\n"}))
    guard = lane / "integration/t260902-07/tests/test_route_table.py"
    guard.write_text("# shared guard TAMPERED\n", encoding="utf-8")  # tests/ 面内→gate①过→gate②拦
    tampered = guard.read_text(encoding="utf-8")
    sha0 = head_sha(lane)
    r5 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note5 = r5.note or ""
    gref5 = r5.gate_refusal if isinstance(r5.gate_refusal, dict) else {}
    check("L5a-1 受保护路径拒绝（protected_path，gate② 判定）",
          gref5.get("reason_code") == "protected_path", "rc=%r note=%r"
          % (gref5.get("reason_code"), note5[:160]))
    check("L5a-2 文件原地保留且内容原样（不挪档不回滚＝授权消费面前提）",
          guard.read_text(encoding="utf-8") == tampered,
          "now=%r" % guard.read_text(encoding="utf-8"))
    check("L5a-3 零代落盘 commit", head_sha(lane) == sha0, "sha=%s" % head_sha(lane)[:8])
    rmtree(tmp)

    print("\n== L5b 面外受保护件：保护名单优先于状态分流（两闸都不处置，原地保留）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l5b-")
    (lane / "docs" / "design" / "contract-v1.md").write_text(
        "# contract v1 TAMPERED\n", encoding="utf-8")  # 面外（非测试面）→gate① 拒
    tampered = read_file(lane, "docs/design/contract-v1.md")
    sha0 = head_sha(lane)
    r5b = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note5b = r5b.note or ""
    check("L5b-1 名单件不进自动处置（protected 命中即跳过分流：拒绝+工作区原样保留，"
          "人处/授权前提不因面外失守）",
          "path_gate_reason=" in note5b, "note=%r" % note5b[:160])
    check("L5b-2 文件原地保留且内容原样（不被回滚/挪档）",
          read_file(lane, "docs/design/contract-v1.md") == tampered,
          "now=%r" % read_file(lane, "docs/design/contract-v1.md"))
    check("L5b-3 零代落盘 commit", head_sha(lane) == sha0, "sha=%s" % head_sha(lane)[:8])
    rmtree(tmp)

    # ---- L6 混合批次：合法产物照常落盘且内容恰为合法清单 ----
    print("\n== L6 混合批次一次处置：只落合法清单（越权与留档件绝不入库）")
    tmp, mainrepo, lane, fork = mk_lane("t26091619-l6-")
    (lane / "tests" / "legit.md").write_text("legit edited\n", encoding="utf-8")
    (lane / "docs" / "rogue3.md").write_text("rogue\n", encoding="utf-8")
    (lane / "docs" / "kb.md").write_text("kb hacked again\n", encoding="utf-8")
    n0 = head_count(lane)
    r6 = settle(shared, aa, lane, TID, "arbitrate", 1, fork)
    note6 = r6.note or ""
    qroot = quarantine_root(lane, shared)
    check("L6a 无终态拒绝（越权两件均可处置，处置后复判只剩合法面）",
          "path_gate_reason=" not in note6, "note=%r" % note6[:200])
    check("L6b 合法产物代落盘且内容恰为合法清单（越权件与其留档件零入库）",
          head_count(lane) == n0 + 1
          and committed_names(lane) == ["tests/legit.md"],
          "committed=%r" % committed_names(lane))
    check("L6c 越权件已处置（?? 挪走、M 回基线）",
          not (lane / "docs" / "rogue3.md").exists()
          and read_file(lane, "docs/kb.md") == "kb baseline\n",
          "rogue_exists=%r kb=%r" % ((lane / "docs" / "rogue3.md").exists(),
                                     read_file(lane, "docs/kb.md")))
    check("L6d 两件越权留档均在档（?? 原件+M diff 锚实质：diff 头点名原路径）",
          bool(archive_find(qroot, "rogue3.md"))
          and any("docs/kb.md" in p.read_text(encoding="utf-8", errors="replace")
                  for p in qroot.rglob("*.diff") if p.is_file()),
          "found=%r" % [p.name for p in qroot.rglob("*") if qroot.is_dir() and p.is_file()])
    r6b = settle(shared, aa, lane, TID, "arbitrate", 2, fork)
    check("L6e 二次 settle 复绿零新 commit（收口干净，无循环复判）",
          "path_gate_reason=" not in (r6b.note or "") and head_count(lane) == n0 + 1,
          "note=%r count=%s" % ((r6b.note or "")[:120], head_count(lane)))
    rmtree(tmp)

    return summary()


if __name__ == "__main__":
    sys.exit(main())
