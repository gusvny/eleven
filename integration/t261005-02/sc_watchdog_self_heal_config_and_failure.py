#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_self_heal_config_and_failure.py — declared knobs fail closed and the cancel
failure path stays honest (t261005-02, gray-box L2, offline seconds, zero docker/ports/
browser, never touches 3099).

intent (host requirement 4 + destructive-act failure modes): every self-heal threshold is a
declared knob in the watchdog.json family, so a human — not code — decides "how long is too
long"; this scenario locks the config face and the failure branches of the cancel act. A1
the self_heal family absent falls to factory defaults and the status face names the active
config (receipt-naming requirement). A2/A3 malformed values (non-boolean enabled; park
minutes zero/negative/non-numeric) fail closed — config_error, the knob named, the watchdog
never runs on a guessed value. A4 the cross-knob guard: park_minutes at or under
long_turn_minutes would fire inside a healthy long turn's territory, so it is config_error
naming both knobs (review-plan comment; requirement 1 "never on a healthy long turn"). B the
cancel call failing: the receipt state names the failure, the alert names the error, the
briefing is STILL delivered (it queues behind the ask — the recovery path survives even when
the cancel itself is refused), and no retry loop starts (one attempt counted). C the host
cancel face absent: state=unsupported, explicit — never a silent pass.

intent split: the fire path (sc_watchdog_self_heal_fires_once) and the hold branches
(sc_watchdog_self_heal_holds) are separate faces; developer L1 owns config-parse unit tests —
this entry locks the user-visible config state machine and the cancel failure branches at the
component boundary. Seam not landed = FAIL named (TDD red expected); arbitrate/merge green.
Run directly: python3 integration/t261005-02/sc_watchdog_self_heal_config_and_failure.py.
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


def boot(h, project, overrides):
    kw = dict(project=project, config=h.fixture_config(project))
    if overrides is not None:
        kw["config"]["self_heal"] = overrides
    h.cmd("start", **kw)


def full_status(h, project):
    st = safe_cmd(h, "status", project=project)
    return st.get("status") if isinstance(st.get("status"), dict) else st


def main():
    h = Harness()
    h.start()
    try:
        if not seam_ready(h):
            print("FAIL: self-heal 测试缝未落地（cancel_log 不可应答——v3 缝契约见 "
                  "lib_selfheal_harness.py 头注；TDD 期红属预期）")
            summary_and_exit(PASS, FAIL + 1)

        # A1. family absent → factory defaults, config named on the read face
        boot(h, "p-cfg-a", None)
        st = full_status(h, "p-cfg-a")
        sh = st.get("self_heal") or {}
        ok(sh.get("config", {}).get("enabled") is True
           and isinstance(sh.get("config", {}).get("park_minutes"), (int, float)),
           "A1 defaults active and config named on the read face", json.dumps(sh)[:300])

        # A2/A3. malformed values fail closed, knob named
        for i, bad in enumerate([
                {"enabled": "yes", "park_minutes": 60},
                {"enabled": True, "park_minutes": 0},
                {"enabled": True, "park_minutes": -5},
                {"enabled": True, "park_minutes": "sixty"}]):
            boot(h, "p-cfg-b%d" % i, bad)
            st = full_status(h, "p-cfg-b%d" % i)
            blob = json.dumps(st)
            ok("config_error" in blob, "A2.%d malformed %s → config_error" % (i, bad),
               blob[:300])
            ok("park_minutes" in blob or "enabled" in blob,
               "A3.%d error names the offending knob" % i, blob[:300])

        # A4. cross-knob guard (review-plan condition, landed): a DECLARED long_turn at or
        # above park_minutes would put the cancel threshold inside healthy-long-turn
        # territory → config_error naming both knobs, never a silent default.
        h.cmd("start", project="p-cfg-c", config=h.fixture_config(
            "p-cfg-c", overrides={"long_turn_minutes": 60,
                                  "self_heal": {"enabled": True, "park_minutes": 45}}))
        blob = json.dumps(full_status(h, "p-cfg-c"))
        ok("config_error" in blob and "park_minutes" in blob and "long_turn_minutes" in blob,
           "A4 park_minutes <= long_turn_minutes rejected naming both knobs", blob[:300])

        # B. cancel call fails: receipt failed + named alert, brief still delivered, no retry
        boot(h, "p-cfg-d", {"enabled": True, "park_minutes": 2})
        sess = "executor-p-cfg-d"
        safe_cmd(h, "requests_seed", project="p-cfg-d", rows=[{
            "id": "ask-d1", "kind": "question", "by": sess, "at": 0, "status": "pending"}])
        safe_cmd(h, "brief_pending_set", sessionId=sess, pending=True)
        safe_cmd(h, "cancel_fail_next", error="stub: cancel refused by host")
        safe_cmd(h, "tick", seconds=600)
        st = full_status(h, "p-cfg-d")
        sh = st.get("self_heal") or {}
        ok(sh.get("state") == "failed", "B1 cancel failure → receipt state=failed",
           json.dumps(sh)[:300])
        ok("cancel refused by host" in json.dumps(sh) or "refused" in json.dumps(sh),
           "B2 receipt names the cancel error", json.dumps(sh)[:300])
        alerts = safe_cmd(h, "alerts_tail").get("rows", [])
        ok(any(a.get("kind") == "self_heal_cancel" for a in alerts),
           "B3 failure alert row present (named, not silent)", json.dumps(alerts)[-300:])
        wakes = safe_cmd(h, "delivered_wakes").get("wakes", [])
        ok(len(wakes) >= 1 and wakes[-1].get("accepted"),
           "B4 briefing still delivered (queued behind the ask)", json.dumps(wakes)[-300:])
        safe_cmd(h, "tick", seconds=600)
        ok(len(safe_cmd(h, "cancel_log").get("cancels", [])) <= 1,
           "B5 no retry loop after a failed cancel", "")

        # C. host cancel face absent → unsupported, explicit
        boot(h, "p-cfg-e", {"enabled": True, "park_minutes": 2})
        sess = "executor-p-cfg-e"
        safe_cmd(h, "requests_seed", project="p-cfg-e", rows=[{
            "id": "ask-e1", "kind": "question", "by": sess, "at": 0, "status": "pending"}])
        safe_cmd(h, "brief_pending_set", sessionId=sess, pending=True)
        safe_cmd(h, "cancel_fail_next", mode="absent")
        safe_cmd(h, "tick", seconds=600)
        sh = (full_status(h, "p-cfg-e") or {}).get("self_heal") or {}
        # The plan's own guard discipline: ourBriefPending=null (host absent → no-signal)
        # HOLDS — a cancel is never fired on a no-signal read, so the unsupported cancel
        # state is unreachable on the parked path. The acceptance bar here is the act
        # (zero cancels) plus an EXPLICIT named hold reason, never a silent pass.
        ok(sh.get("state") not in ("fired", "failed"),
           "C1 absent host face → held, never fired", json.dumps(sh)[:300])
        ok("no-signal" in json.dumps(sh),
           "C2 hold reason names the no-signal read (explicit, not silent)",
           json.dumps(sh)[:300])
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
