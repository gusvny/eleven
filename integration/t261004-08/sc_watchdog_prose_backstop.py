#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_prose_backstop.py — a prose ask reaches the panel ledger
mechanically (t261004-08 Part 2, grey-box L3, offline seconds, injected clock,
zero docker, zero 3099/7233; driven through the watchdog harness seam).

intent (user-perceivable: when the executor writes "still waiting on you" in
its own round report, the host sees a real request row in the panel — the
261004 evidence incident had the host relay both asks by hand):

- A  fires and files exactly one: idle session + a round text carrying a
     waiting marker + no matching unanswered ledger row → exactly one NEW
     ledger row, kind question, attributed raised_by = the executor session,
     detail quotes the marker sentence and names the session; exactly one
     prose_ask_filed alert.
- B  idempotent: the same sentence on later cycles files no second row and no
     second alert (both dedupe layers: ledger coverage + persisted journal).
- C  per-ask-instance idempotency (review note): after the row is ANSWERED,
     the same sentence re-appearing files exactly one NEW row — per ask, not
     once forever.
- D  coverage check: an unanswered row already attributed to the session is
     coverage — no filing (the backstop must not duplicate a real ask).
- E  fail loud, never silent: malformed round text / no text source → the
     prose_backstop status reads 'unknown' with a reason, exactly one
     prose_backstop_unknown alert, ZERO filings. "Nothing to report" is a
     red line.
- F  idle gate: a marker while the session is still running files nothing.
- G  restart replay: after a harness restart with the same sentence still the
     latest round text, no duplicate row (journal replayed on startup).

intent split: marker substring truth table and journal key derivation are
developer L1 (prose-backstop.test.mjs); the panel ledger append/read contract
itself is t260929-03 R1-R5; this scenario owns the end-to-end prose-ask
behavior. Heuristic-by-nature detection is the documented miss-mode: a missed
marker still surfaces via stall/self_lock, and the assertion set here pins
only the contract, not any particular marker list. Seam or implementation not
landed = FAIL with the gap named (TDD red expected; green at arbitrate/merge).
Run directly: python3 integration/t261004-08/sc_watchdog_prose_backstop.py (cwd=repo root).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_waiting_harness import (  # noqa: E402
    EXEC_SESSION, WaitingHarness, ok, request_row,
)

PROJECT = "p1"
MARKER = "仍等你一句话的：worker 重启 / 要不要开批量清红票"  # the 261004 evidence sentence


class SeamGap(Exception):
    pass


def need(h, r, seam):
    if not r.get("ok", False):
        ok(False, "seam command landed: %s" % seam, str(r)[:200])
        raise SeamGap(seam)


def status(h):
    return h.cmd("status", project=PROJECT)["status"]


def filed_rows(h):
    return [r for r in h.request_rows().get("rows", [])
            if str(r.get("detail", "")).find(MARKER) >= 0]


def prose_alerts(h, rule="prose_ask_filed"):
    return [a for a in status(h).get("alerts", []) if rule in str(a.get("key", ""))]


def main():
    h = WaitingHarness()
    h.start()
    try:
        h.cmd("session_stat_set", running=False, updatedAtMs=1000)
        h.seed_requests([])
        h.set_round_text(MARKER)
        r = h.cmd("start", project=PROJECT,
                  config=h.fixture_config(PROJECT), now="2026-09-28T10:00:00+08:00")
        need(h, r, "start")
        need(h, h.cmd("requests_rows"), "requests_rows")
        need(h, h.cmd("session_text_set", text="x"), "session_text_set")

        # A fires and files exactly one attributed row + one alert
        h.cmd("tick", seconds=1)
        rows = filed_rows(h)
        ok(len(rows) == 1, "A exactly one row filed for the marker sentence", rows)
        if rows:
            row = rows[0]
            ok(row.get("kind") == "question", "A row kind=question", row.get("kind"))
            ok(row.get("raised_by") == EXEC_SESSION,
               "A row attributed to the executor session", row.get("raised_by"))
            ok(MARKER in str(row.get("detail", "")) and EXEC_SESSION in str(row.get("detail", "")),
               "A detail quotes the sentence and names the session", row.get("detail"))
        ok(len(prose_alerts(h)) == 1, "A exactly one prose_ask_filed alert", prose_alerts(h))

        # B idempotent: later cycles add nothing
        h.cmd("tick", seconds=60)
        h.cmd("tick", seconds=60)
        ok(len(filed_rows(h)) == 1, "B same sentence files no second row", filed_rows(h))
        ok(len(prose_alerts(h)) == 1, "B no second alert", prose_alerts(h))

        # C answered row + same sentence re-appears -> exactly one NEW row
        # (answering is an APPENDED answer row per the panel contract t260929-03 R2)
        prior = filed_rows(h)
        h.seed_requests(
            # re-seed the prior rows verbatim (seed = replace; keep their quoted detail)
            # plus an appended answer row each — the panel contract shape for "answered"
            [dict(r) for r in prior] + [h.answer_row(r["id"]) for r in prior])
        h.set_round_text("done; " + MARKER)
        h.cmd("tick", seconds=60)
        ok(len(filed_rows(h)) == 2,
           "C answered + sentence re-appears = exactly one new row (per ask instance)",
           filed_rows(h))

        # D coverage: an unanswered attributed row blocks filing (seed = replace, so
        # assert on the row SET before/after the tick, not on a running total)
        h.set_round_text("another one: waiting for the host decision")
        h.seed_requests([request_row("req-real", EXEC_SESSION)])
        before = sorted(r["id"] for r in h.request_rows().get("rows", []))
        h.cmd("tick", seconds=60)
        after = sorted(r["id"] for r in h.request_rows().get("rows", []))
        ok(before == after == ["req-real"],
           "D unanswered attributed row is coverage: nothing filed", (before, after))

        # E fail loud: malformed text source -> unknown + one alert, zero filings
        # (the C-filed row stays in the ledger — the ledger is append-only, so the
        # realistic slate keeps it; assertions compare the row SET across the tick)
        def row_ids():
            return sorted(r["id"] for r in h.request_rows().get("rows", []))
        h.round_text_malformed()
        ids_before = row_ids()
        h.cmd("tick", seconds=60)
        pb = status(h).get("prose_backstop", {})
        ok(pb.get("state") == "unknown" and bool(pb.get("reason")),
           "E malformed transcript = unknown + reason", pb)
        ok(len(prose_alerts(h, "prose_backstop_unknown")) == 1,
           "E exactly one prose_backstop_unknown alert", prose_alerts(h, "prose_backstop_unknown"))
        ok(row_ids() == ids_before, "E zero filings on unknown", row_ids())

        # F idle gate: a marker while the session was JUST active files nothing
        # (idle = now - last activity, per the ticket's "idle for N minutes")
        h.round_text_absent()
        now_ms = h.cmd("tick", seconds=0).get("now")
        h.set_round_text(MARKER + " (again)")
        h.cmd("session_stat_set", running=True, updatedAtMs=now_ms)
        h.cmd("tick", seconds=60)
        ok(row_ids() == ids_before, "F just-active session: marker files nothing", row_ids())

        # G restart replay: the already-filed sentence's journal entry names a row
        # that is STILL waiting -> no duplicate after the restart
        h.set_round_text(MARKER)
        h.cmd("session_stat_set", running=False, updatedAtMs=1000)
        h.cmd("restart")
        h.cmd("tick", seconds=1)
        ok(row_ids() == ids_before,
           "G restart replays the journal: no duplicate row", row_ids())
    except SeamGap:
        pass  # gap already recorded via ok(); finish() below exits 1
    finally:
        h.finish()


if __name__ == "__main__":
    main()
