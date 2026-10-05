#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_self_heal_holds.py — the self-heal cancel never fires off-signal
(t261005-02, gray-box L2, offline seconds, zero docker/ports/browser, never touches 3099).

intent (host requirement 1 negative face + KI discipline): an automatic turn cancellation is
a destructive act — the design's own promise is "never on a healthy long turn; one attempt
per park". This scenario locks every hold branch through the public Watchdog face: a healthy
long turn (running, silent past the threshold, NO ask) is never cancelled; an ask inside the
threshold is held; a consumed briefing is held (the park already got its one wake); an
unreadable mirror (no-signal null) is held — a cancel is never fired on a no-signal read; a
pending prose question marker (no ledger ask row) DOES satisfy the ask condition — the
prose-backstop branch of requirement 1(a); and the declared off switch (self_heal.enabled
false) turns the whole face off explicitly with state=off.

intent split: the fire path and the receipt face are sc_watchdog_self_heal_fires_once;
config parsing/malformed values are sc_watchdog_self_heal_config_and_failure; developer L1
owns the decision-function truth table internals — this entry locks that each guard holds at
the component boundary (status state + zero cancels). Seam not landed = FAIL named (TDD red
expected); arbitrate/merge must be green.
Run directly: python3 integration/t261005-02/sc_watchdog_self_heal_holds.py (cwd=repo root).
"""
from __future__ import annotations

import json
import shutil
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lib_selfheal_harness import (  # noqa: E402
    Harness, NamedSeamError, safe_cmd, seam_ready, summary_and_exit)

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (label, detail))


def boot(h, project, enabled=True):
    h.cmd("start", project=project, config=h.fixture_config(
        project, overrides={"self_heal": {"enabled": enabled, "park_minutes": 2}}))


def cancels(h, project=None):
    """cancel_log 是缝级全局账；断言按会话过滤（共享时钟会泵所有实例，
    别的 project 的合法 fire 不属于本分支的判据）。"""
    rows = safe_cmd(h, "cancel_log").get("cancels", [])
    if project is None:
        return rows
    return [c for c in rows if c.get("sessionId") == "executor-" + project]


def sh_state(h, project):
    st = safe_cmd(h, "status", project=project)
    return (st.get("status") or st).get("self_heal") or {}


def holds(h, project, label):
    ok(len(cancels(h, project)) == 0, "%s — no cancel for this session" % label)
    st = sh_state(h, project).get("state")
    ok(st in ("idle", "hold", "off", "unknown"), "%s — state=%s not fired" % (label, st),
       json.dumps(sh_state(h, project))[:200])


def seed_ask(h, project, ask_id):
    safe_cmd(h, "requests_seed", project=project, rows=[{
        "id": ask_id, "kind": "question", "raised_by": "executor-" + project,
        "at": 0, "status": "waiting"}])


def main():
    h = Harness()
    h.start()
    try:
        if not seam_ready(h):
            print("FAIL: self-heal 测试缝未落地（cancel_log 不可应答——v3 缝契约见 "
                  "lib_selfheal_harness.py 头注；TDD 期红属预期）")
            summary_and_exit(PASS, FAIL + 1)
        # 每分支一个独立 project 实例（同一 harness 进程；waitingSeam 全局态逐分支重置）。

        # A. healthy long turn: running + silent past threshold + NO ask → never cancel
        safe_cmd(h, "session_stat_set", missing=False, running=True)
        boot(h, "p-hold-a")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-a", pending=True)
        safe_cmd(h, "tick", seconds=600)
        holds(h, "p-hold-a", "A1 healthy long turn (no ask) never cancelled")

        # B. ask present but silence under threshold → hold
        safe_cmd(h, "session_stat_set", missing=True, running=False)
        boot(h, "p-hold-b")
        seed_ask(h, "p-hold-b", "ask-b1")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-b", pending=True)
        safe_cmd(h, "tick", seconds=60)  # 1min < park_minutes 2
        holds(h, "p-hold-b", "B2 ask inside threshold held")

        # C. our briefing already consumed → hold (the park already got its wake)
        boot(h, "p-hold-c")
        seed_ask(h, "p-hold-c", "ask-c1")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-c", pending=False)
        safe_cmd(h, "tick", seconds=600)
        holds(h, "p-hold-c", "C3 consumed briefing held")

        # D. mirror unreadable (no-signal null) → hold, never cancel on a no-signal read
        boot(h, "p-hold-d")
        seed_ask(h, "p-hold-d", "ask-d1")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-d", pending="null")
        safe_cmd(h, "tick", seconds=600)
        holds(h, "p-hold-d", "D4 unreadable mirror (no-signal) held")

        # E. prose question marker (no ledger ask row) satisfies condition (a) → fires
        boot(h, "p-hold-e")
        safe_cmd(h, "session_text_set",
                 text="please decide: should I proceed? (question marker)")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-e", pending=True)
        safe_cmd(h, "tick", seconds=600)
        ce = cancels(h)
        ok(len(ce) == 1, "E5 prose question marker branch fires exactly once",
           json.dumps(ce)[:200])

        # F. declared off switch → whole face off, never cancel even with all conditions
        boot(h, "p-hold-f", enabled=False)
        seed_ask(h, "p-hold-f", "ask-f1")
        safe_cmd(h, "brief_pending_set", sessionId="executor-p-hold-f", pending=True)
        safe_cmd(h, "tick", seconds=600)
        ok(len(cancels(h, "p-hold-f")) == 0, "F6 disabled config never cancels")
        ok(sh_state(h, "p-hold-f").get("state") == "off",
           "F7 state=off explicit (not absent)", json.dumps(sh_state(h, "p-hold-f"))[:200])
        summary_and_exit(PASS, FAIL)
    except NamedSeamError as e:
        print("FAIL: 缝命令失败：%s" % e)
        summary_and_exit(PASS, FAIL + 1)
    finally:
        h.stop()


if __name__ == "__main__":
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（watchdog 面是 node 缝）")
        sys.exit(2)
    main()
