#!/usr/bin/env python3
"""sc_block_text_executor_escape — every mechanical-conflict block text names the
executor's own way out when one exists (t261004-02, gray-box L2, offline, seconds).

User-perceivable contract (ticket-face text the executor reads at the moment of
block): when the engine hands a mechanical sync/merge conflict to a human, the
same block text must also name the executor's own path out — send-back
(rework(to_stage=implement)) — whenever that path truthfully exists; branches
where only a human can act (git merge --abort / reset, executor cannot write the
lane's .git gitfile) keep truthful human-only wording. The t261003-10 incident:
the executor was woken, diagnosed correctly, and still deferred because the text
said only "转人工处置".

Gray-box anchoring: message content only — no internal function names, no line
numbers, no execution order. Assertions pin the user-visible message faces plus
the selfcheck anchor substrings (「冲突消解 %d 轮未收敛」/「同批文件反复冲突」), which
must survive unchanged. The executor-clause wording is tolerant across the two
landed shapes (「执行器可自解」/「执行器自己的出路」) — the contract, not the phrase, is
pinned.

Stdlib-only, zero docker, zero Temporal, no ENV_FAIL face.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = (ROOT / "server/engine/dev_lane.py").read_text("utf-8")
LIGHT = (ROOT / "server/engine/light_lane.py").read_text("utf-8")

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(t):
    print("\n%s" % t)


# Executor-escape clause, wording-tolerant across landed shapes; the message must
# name rework(to_stage=implement) as the executor's own send-back path.
EXEC_CLAUSE = (r"执行器(?:可自解|自己的出路)[\s\"'\n]*[：:，,]?[\s\"'\n]*"
               r"(?:发|这条)?[\s\"'\n]*\"?\n?\s*\"?rework\(to_stage=implement\)")

# ---------- A. dev_lane merge_check dry-run block texts (over-cap + same-batch) ----------
section("A dev_lane merge_check 干跑态 blocked 文案：人路径保留 + 执行器出路点名")
for name, anchor in (
    ("超限", "转人工处置：冲突文件 %s"),
    ("同批", "同批文件反复冲突（连续 2 轮集合相同，第 %d 轮），转人工处置：%s"),
):
    i = DEV.find(anchor)
    ok(i >= 0, "%s 文案可定位且 human 锚「转人工处置」保留" % name)
    if i >= 0:
        tail = DEV[i:i + 600]
        ok(re.search(r"rework\(to_stage=implement\)", tail) is not None,
           "%s 文案同句点名执行器出路 rework(to_stage=implement)" % name)
        ok(re.search(r"git\s+merge\s+--abort", tail) is None,
           "%s 文案不把 git 操作指派给执行器（干跑态执行器跑不了 git）" % name)

# ---------- B. dev_lane mid-merge settle texts (merge_check + main-sync default) ----------
section("B dev_lane 合并进行中态 settle 文案：出路归执行器、abort/reset 归人，两者同段在场")
n_exec = len(re.findall(EXEC_CLAUSE, DEV))
ok(n_exec >= 2, "settle 文案带执行器出路子句（rework(to_stage=implement)），两处 ≥2（实得 %d）" % n_exec)
for kw in ("git merge --abort", "retry_qc"):
    ok(kw in DEV, "人工半句保留：%s" % kw)
# The reset half must stay attributed to the human (executor cannot run git):
# 「人工」 must sit in the same sentence as git merge --abort / retry_qc.
m_exec = re.search(EXEC_CLAUSE, DEV)
abort_at = DEV.find("git merge --abort", m_exec.start()) if m_exec else -1
zone = DEV[m_exec.start():abort_at] if (m_exec and abort_at > 0) else ""
ok("人工" in zone, "abort/reset 半句归人工（执行器跑不了 git，不越权点名）")
ok(re.search(r"执行器[^。]{0,40}rework", DEV) is not None,
   "settle 文案带执行器第一人称出路子句（非仅归人）")

# ---------- C. light_lane settle text (English, ticket-face) ----------
section("C light_lane settle_unconverged：executor 路径在前可执行、human 路径保留")
m = re.search(r'"settle_unconverged":\s*\((.*?)\),\s*\n\s*"back_to_implement"', LIGHT, re.S)
ok(m is not None, "LIGHT_MAIN_SYNC_TEXTS.settle_unconverged 可定位")
if m:
    t = re.sub(r'["\s]+', " ", m.group(1))
    ok("rework(to_stage=implement)" in t, "executor 出路 rework(to_stage=implement) 点名")
    ok("retry_qc" in t, "retry_qc 重验路径保留")
    ok("git merge --abort" in t, "human 的 abort 复位路径保留（真 human-only 半句不删）")
    ok("a human has to take it: %s" not in t,
       "开场不再把整块归人（t261003-10 矛盾形态拆除）")

# ---------- D. human-only branches stay human-only (no false escape) ----------
section("D 真人工分支零污染：unreachable / reset_* 不许伪造执行器出路")
for key in ("unreachable", "reset_exception", "reset_failed"):
    m2 = re.search(r'"%s":\s*\((.*?)\),' % key, LIGHT, re.S) or \
         re.search(r'"%s":\s*("(?:[^"]|"\s*\n\s*")*"),' % key, LIGHT, re.S)
    ok(m2 is not None, "%s 文案可定位" % key)
    if m2:
        ok("a human has to" in re.sub(r'["\s]+', " ", m2.group(1)),
           "%s 仍如实指向人" % key)
        ok("rework(" not in re.sub(r'["\s]+', " ", m2.group(1)),
           "%s 不伪造执行器出路" % key)
ok("同批文件反复冲突" in DEV and "冲突消解" in DEV,
   "selfcheck 文案锚（冲突消解/同批文件反复冲突）零漂移")

# ---------- E. negative control: the t261003-10 fire point is covered ----------
section("E 负控：t261003-10 实发的那条文案必须带出路（事故回归棒）")
i = DEV.find(ANCHOR_SAMEBATCH) if (ANCHOR_SAMEBATCH := "同批文件反复冲突（连续 2 轮集合相同，第 %d 轮），转人工处置：%s") else -1
ok(i >= 0 and "rework" in DEV[i:i + 600],
   "同批文案（实发条目）点名执行器出路——事故不复现")

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
