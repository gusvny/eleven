#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_self_heal_fires_once.py — a parked session is cancelled exactly once and the
cancel is visible on the read face (t261005-02, gray-box L2, offline seconds, zero docker/
ports/browser, never touches 3099).

intent (user-perceivable, host requirement 1+2): the live incident (KI-196+KI-197) left a
session frozen 56 minutes on an unanswered ask and NOTHING reported it — a human had to
notice by hand. This scenario locks the recovery: a session with (a) an unanswered ask
attributed to it, (b) silence past the declared park threshold, and (c) our wake briefing
still unconsumed gets its wedged turn cancelled EXACTLY ONCE and then receives the briefing
(the queued brief survives cancel, so the session starts a new turn and reads the ledger);
and the judgement result plus the last cancel are visible on the watchdog read face
(status.self_heal state=fired, last_cancel naming the session, the ask and the threshold;
a self_heal_cancel alert row) so a human can see that it happened, not only that the session
resumed. One attempt per park: further ticks past the threshold never cancel again (no
cancel loop).

intent split: the pure guard truth table (each guard holding the fire off) is the holds
scenario's face; the healthy-long-turn and disabled-config negatives live there too. The
developer's L1 stub tests cover the decision function internals; this scenario locks the
component contract through the public Watchdog face (status + alert ledger + recorded
cancels). Seam not landed = FAIL named (TDD red expected); arbitrate/merge must be green.
Run directly: python3 integration/t261005-02/sc_watchdog_self_heal_fires_once.py (cwd=repo root).
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


def main():
    h = Harness()
    h.start()
    try:
        h.start_fix = None
        h.cmd("start", project="p-selfheal", config=h.fixture_config(
            "p-selfheal", overrides={"self_heal": {"enabled": True, "park_minutes": 2}}))
        if not seam_ready(h):
            print("FAIL: self-heal 测试缝未落地（cancel_log 不可应答——v3 缝契约见 "
                  "lib_selfheal_harness.py 头注；TDD 期红属预期）")
            summary_and_exit(PASS, FAIL + 1)
        sess = "executor-p-selfheal"

        # A. all three conditions hold → one cancel + one brief + visible receipt
        safe_cmd(h, "requests_seed", project="p-selfheal", rows=[{
            "id": "ask-1", "kind": "question", "by": sess, "at": 0, "status": "pending"}])
        safe_cmd(h, "brief_pending_set", sessionId=sess, pending=True)
        r = safe_cmd(h, "tick", seconds=180)  # silence 3min > park_minutes 2
        st = safe_cmd(h, "status", project="p-selfheal")
        sh = (st.get("status") or st).get("self_heal")
        ok(isinstance(sh, dict), "A1 status face exposes self_heal key (requirement 2)",
           json.dumps(st)[:300])
        ok(sh and sh.get("state") == "fired", "A2 judgement state=fired",
           json.dumps(sh)[:300])
        cancels = safe_cmd(h, "cancel_log").get("cancels", [])
        ok(len(cancels) == 1 and cancels[0].get("sessionId") == sess,
           "A3 exactly one cancel, naming the session", json.dumps(cancels)[:300])
        last = (sh or {}).get("last_cancel") or {}
        blob = json.dumps(last)
        ok(sess in blob and "ask-1" in blob and "2" in blob,
           "A4 receipt names session + ask + threshold", blob[:300])
        alerts = safe_cmd(h, "alerts_tail").get("rows", [])
        ok(any(a.get("kind") == "self_heal_cancel" for a in alerts),
           "A5 self_heal_cancel alert row on the read face", json.dumps(alerts)[-300:])
        wakes = safe_cmd(h, "delivered_wakes").get("wakes", [])
        ok(len(wakes) >= 1 and wakes[-1].get("accepted"),
           "A6 briefing delivered after the cancel (the un-park path)", json.dumps(wakes)[-300:])

        # B. one attempt per park — more silent beats never cancel again
        safe_cmd(h, "tick", seconds=600)
        cancels2 = safe_cmd(h, "cancel_log").get("cancels", [])
        ok(len(cancels2) == 1, "B1 no cancel loop: still exactly one cancel after further beats",
           json.dumps(cancels2)[:200])

        # C. receipt stays visible on later ticks (reader's side, not a transient)
        st2 = safe_cmd(h, "status", project="p-selfheal")
        sh2 = (st2.get("status") or st2).get("self_heal") or {}
        ok(sh2.get("state") == "fired" and sh2.get("last_cancel"),
           "C1 last cancel still visible after later ticks", json.dumps(sh2)[:300])
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
