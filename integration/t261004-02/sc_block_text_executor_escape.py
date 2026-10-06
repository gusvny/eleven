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
said only "handing over to a human".

Gray-box anchoring: message content only — no internal function names, no line
numbers, no execution order. Assertions pin the user-visible message faces plus
the selfcheck anchor substrings ("conflict resolution %d rounds did not
converge" / "the same batch of files keeps conflicting"), which must survive
unchanged. The executor-clause wording is tolerant across the landed shapes of
"The executor's own way out ..." (t261004-02) and "Executable ways out ..."
(t261006-07: the human-only reset half now names the operator entry
`engine_ops.py sync <ticket-id> --abort` instead of an in-lane git command no
agent can run) — the contract, not the phrase, is pinned.

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


def src_find(hay, needle, start=0):
    """Find a runtime message in raw source, tolerating the landed split-literal
    shape ("...fragments " / "joined across lines"). Word-flexible on the join
    only; the pinned words themselves stay verbatim."""
    pat = r'(?:["\s]+| )'.join(re.escape(w) for w in needle.split(" "))
    m = re.compile(pat).search(hay, start)
    return m.start() if m else -1


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
# t261006-07: the clause shape widened — "Executable ways out ... (a) send
# rework(to_stage=implement)" is the same contract in its new landed wording.
EXEC_CLAUSE = (r"(?s:(?:The executor's own way out|Executable ways out)"
               r"(?:(?!handing over to a human).){0,400}?rework\(to_stage=implement\))")

# ---------- A. dev_lane merge_check dry-run block texts (over-cap + same-batch) ----------
section("A dev_lane merge_check 干跑态 blocked 文案：人路径保留 + 执行器出路点名")
for name, anchor in (
    ("over-cap", "handing over to a human: conflicting files %s."),
    ("same-batch", "the same batch of files keeps conflicting (same set for 2 "
                    "consecutive rounds, round %d), handing over to a human: %s."),
):
    i = src_find(DEV, anchor)
    ok(i >= 0, "%s 文案可定位且 human 锚「handing over to a human」保留" % name)
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
for kw in ("engine_ops.py sync", "retry_qc"):
    ok(kw in DEV, "人工半句保留（t261006-07：reset 半句=运营入口，不再点名泳道内 git 命令）：%s" % kw)
# t261006-07: per-text check instead of the fragile single-zone scan — every
# "handing over to a human" text must carry, within its own message, EITHER the
# executor exit (rework resets the counter now, so it is truthful at every
# conflict block) OR the operator reset pair (engine_ops.py sync + retry_qc);
# and no block text may assign an in-lane git command to anyone.
m_exec = re.search(EXEC_CLAUSE, DEV)
ok(m_exec is not None,
   "settle 文案带执行器出路子句（新老两种落定措辞均认，非仅归人）")
_n_human = 0
for _m in re.finditer(r"handing over to a human", DEV):
    _n_human += 1
    _tail = DEV[_m.start():_m.start() + 900]
    _has_exec = re.search(EXEC_CLAUSE, _tail) is not None
    _has_op = ("engine_ops.py sync" in _tail and "retry_qc" in _tail)
    ok(_has_exec or _has_op,
       "human 半句所在文案同段点名可执行出路（执行器 rework 或 运营入口+retry_qc）")
    ok("git merge --abort" not in _tail,
       "该文案不指挥任何人在泳道里跑 git merge --abort（t261006-07 R4）")
ok(_n_human >= 3, "human 半句锚点 ≥3 处（over-cap / same-batch / did-not-converge，实得 %d）" % _n_human)
_n_op = DEV.count("engine_ops.py sync")
ok(_n_op >= 2, "运营入口被 ≥2 处 did-not-converge 文案点名（实得 %d）" % _n_op)

# ---------- C. light_lane settle text (English, ticket-face) ----------
section("C light_lane settle_unconverged：executor 路径在前可执行、human 路径保留")
m = re.search(r'"settle_unconverged":\s*\((.*?)\),\s*\n\s*"back_to_implement"', LIGHT, re.S)
ok(m is not None, "LIGHT_MAIN_SYNC_TEXTS.settle_unconverged 可定位")
if m:
    t = re.sub(r'["\s]+', " ", m.group(1))
    ok("rework(to_stage=implement)" in t, "executor 出路 rework(to_stage=implement) 点名")
    ok("retry_qc" in t, "retry_qc 重验路径保留")
    ok("engine_ops.py sync" in t and "--abort" in t,
       "human 的复位路径保留且=运营入口（t261006-07：不再点名泳道内 git 命令）")
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
ok("the same batch of files keeps conflicting" in DEV and "冲突消解" in DEV,
   "selfcheck 文案锚（冲突消解/同批文件 keeps conflicting）零漂移")

# ---------- E. negative control: the t261003-10 fire point is covered ----------
section("E 负控：t261003-10 实发的那条文案必须带出路（事故回归棒）")
ANCHOR_SAMEBATCH = ("the same batch of files keeps conflicting (same set for 2 "
                    "consecutive rounds, round %d), handing over to a human: %s")
i = src_find(DEV, ANCHOR_SAMEBATCH)
ok(i >= 0 and "rework" in DEV[i:i + 600],
   "同批文案（实发条目）点名执行器出路——事故不复现")

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
