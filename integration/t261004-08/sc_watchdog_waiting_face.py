#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_waiting_face.py — waiting-on-host becomes an observable state
(t261004-08 Part 1, grey-box L3, offline seconds, injected clock, zero docker,
zero 3099/7233; driven through the watchdog harness seam).

intent (user-perceivable: the host reads the watchdog status face and can tell
WHEN the executor is waiting on a human, instead of reading round reports by
hand — the 261004 evidence incident):

- A  additive status key: `waiting_on_host` appears on the status face and is
    'unknown' before the first tick (face not yet evaluated) — it never reads
    as normal/silence; every pre-existing status key keeps its meaning.
- B  waiting is visible: an unanswered ledger row attributed to the executor
    session while the session reads idle → state='waiting', the ask is named
    (request id present), without waiting for the alert threshold.
- C  threshold escalation, exactly one alert: below `waiting_minutes` the
    verdict is the new pre-threshold state 'waiting' and NO self_lock alert
    exists; past the threshold exactly one self_lock alert names the ask; a
    second cycle in the same cooldown window adds no duplicate (ticket:
    "past a threshold it produces exactly one alert ... a second cycle
    produces no duplicate").
- D  face unavailable = explicit unknown: unreadable panel ledger → state
    'unknown' with a reason; it never masquerades as clear (t260928-28 case E
    discipline carried over to the new face).
- E  missing session snapshot is NOT idle (review C3): runningOf() null →
    'unknown', never 'waiting' built from a stale/absent snapshot.
- F  attribution is exact: a waiting row raised by ANOTHER session does not
    make this face waiting; an unattributed (empty raised_by) row is counted
    in the reason, never matched.

intent split (no intent-level duplicate): self-lock truth table and alert
dedupe internals stay with developer L1 (self-lock.test.mjs / core.test.mjs);
t260928-28-watchdog-liveness-selflock owns the immediate-fire contract of the
OLD behavior and is superseded by this ticket's threshold change (its case D
assertion is updated there); this scenario owns the NEW observable-face
contract end to end. Seam or implementation not landed = FAIL with the gap
named (TDD red expected; green at arbitrate/merge).
Run directly: python3 integration/t261004-08/sc_watchdog_waiting_face.py (cwd=repo root).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_waiting_harness import (  # noqa: E402
    EXEC_SESSION, WaitingHarness, ok, request_row,
)

PROJECT = "p1"


class SeamGap(Exception):
    pass


def need(h, r, seam):
    if not r.get("ok", False):
        ok(False, "seam command landed: %s" % seam, str(r)[:200])
        raise SeamGap(seam)


def status(h):
    return h.cmd("status", project=PROJECT)["status"]


def main():
    h = WaitingHarness()
    h.start()
    try:
        # A0 pre-tick: face exists and reads unknown before any evaluation
        pre = h.cmd("status", project=PROJECT)["status"]
        face = pre.get("waiting_on_host")
        ok(isinstance(face, dict) and face.get("state") == "unknown",
           "A pre-tick waiting_on_host present and unknown", face)
        h.cmd("session_stat_set", running=False, updatedAtMs=1000)
        h.seed_requests([])
        r = h.cmd("start", project=PROJECT,
                  config=h.fixture_config(PROJECT), now="2026-09-28T10:00:00+08:00")
        need(h, r, "start(config with waiting_minutes/prose_backstop)")
        st = status(h)
        ok(isinstance(st.get("waiting_on_host"), dict),
           "A waiting_on_host key present once declared", st.get("waiting_on_host"))
        ok("self_lock" in st and "liveness" in st and "heartbeat" in st,
           "A additive-only: existing status keys intact", sorted(st.keys()))

        # B idle session + unanswered attributed row -> waiting, ask named
        h.seed_requests([request_row("req-1", EXEC_SESSION)])
        h.cmd("tick", seconds=1)
        face = status(h).get("waiting_on_host")
        ok(face.get("state") == "waiting", "B idle + attributed unanswered row = waiting", face)
        ok("req-1" in str(face), "B the ask is named by id", face)

        # C below threshold: pre-threshold state, zero alerts
        sl = status(h).get("self_lock", {})
        alerts = status(h).get("alerts", [])
        ok(sl.get("state") == "waiting", "C below threshold = pre-threshold 'waiting'", sl)
        ok(not any("self_lock" in str(a.get("key", "")) for a in alerts),
           "C below threshold: no self_lock alert yet", alerts)

        # C2 past threshold: exactly one alert naming the ask
        h.cmd("tick", seconds=6 * 60)
        alerts = [a for a in status(h).get("alerts", []) if "self_lock" in str(a.get("key", ""))]
        ok(len(alerts) == 1, "C2 past threshold: exactly one self_lock alert", alerts)
        ok("req-1" in str(alerts), "C2 the alert names the ask", alerts)

        # C3 second cycle: no duplicate inside the cooldown window
        h.cmd("tick", seconds=60)
        alerts = [a for a in status(h).get("alerts", []) if "self_lock" in str(a.get("key", ""))]
        ok(len(alerts) == 1, "C3 second cycle adds no duplicate", alerts)

        # D face unavailable: explicit unknown, never clear
        h.seed_requests_unreadable()
        h.cmd("tick", seconds=1)
        face = status(h).get("waiting_on_host", {})
        ok(face.get("state") == "unknown" and bool(face.get("reason")),
           "D unreadable ledger = unknown + reason (never clear)", face)
        h.seed_requests([])

        # E missing session snapshot is not idle (review C3)
        h.session_missing()
        h.seed_requests([request_row("req-2", EXEC_SESSION)])
        h.cmd("tick", seconds=1)
        face = status(h).get("waiting_on_host", {})
        ok(face.get("state") == "unknown", "E snapshot missing = unknown, not waiting", face)

        # F attribution is exact: another session's row never matches
        h.cmd("session_stat_set", running=False, updatedAtMs=1000)
        h.seed_requests([request_row("req-3", "executor-other"),
                         request_row("req-4", "")])
        h.cmd("tick", seconds=1)
        face = status(h).get("waiting_on_host", {})
        ok(face.get("state") == "clear" or face.get("state") == "waiting",
           "F face readable with foreign/unattributed rows", face)
        ok("req-3" not in str(face.get("asks", face)),
           "F another session's row is not this face's ask", face)
        ok("req-4" not in str(face.get("asks", face)),
           "F unattributed row never matches", face)
        ok(bool(face.get("reason")) if face.get("state") == "clear" else True,
           "F unattributed gap visible in reason (not silent)", face.get("reason"))
    except SeamGap:
        pass  # gap already recorded via ok(); finish() below exits 1
    finally:
        h.finish()


if __name__ == "__main__":
    main()
