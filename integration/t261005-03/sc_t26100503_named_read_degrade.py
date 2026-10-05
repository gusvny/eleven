#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-03 scenario ②: the read face degrades by name (clause B, grey-box L3,
offline against a stub handle — zero Temporal, zero docker, never touches 3099).

User-perceivable contract (261005: detail queries hung 25.8 s with no poller and
ops refusals surfaced a bare TimeoutError, leaving two tickets uncontrollable):
- R1 a snapshot read with NO live poller fails in bounded time and names the
  cause as no_poller together with the ticket id, the task queue and the poller
  count — never an unbounded hang;
- R2 a snapshot read that times out WITH live pollers is named query_timeout
  with the same ticket/queue/count context (the two causes must be
  distinguishable — 261005 showed a bare TimeoutError sends diagnosis the wrong
  way);
- R3 a poller face that cannot prove liveness (unreachable) yields an explicit
  cannot-prove value, never a silent zero that would fake a no_poller verdict;
- R4 a malformed queue name is refused by name, never crashing the caller;
- R5 repeated degraded reads (the workbench list polls per ticket) each stay
  bounded — the list face must not stack 25 s hangs.

Intent split: the workbench/UI rendering of the named reason and the kind
taxonomy integration (review condition C2 — the new reason must extend the
KI-025 kind faces, not fork them) are pinned by the engine gate; this entry
pins the read-face contract itself. Helpers declared by the approved plan
(named_snapshot_read / queue_live_pollers) missing = FAIL named
(TDD-phase red expected; arbitrate/merge must be green). Engine modules
unavailable = ENV_FAIL exit 2.

Run: PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
     integration/t261005-03/sc_t26100503_named_read_degrade.py  (cwd = repo root)
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100503 import check, env_fail, load_client, summary  # noqa: E402

BOUND_S = 5.0  # a degraded read must return well inside this bound


class TimeoutHandle:
    """Stub temporal handle: query('snapshot') hangs past the deadline — the
    zero-poller incident shape, without needing a real cluster."""

    def __init__(self, delay_s=60.0):
        self.delay_s = delay_s
        self.queries = []

    async def query(self, name, *a, **kw):
        self.queries.append(name)
        await asyncio.sleep(self.delay_s)
        return {}


class LivePollerFace:
    def __init__(self, live=0, reachable=True):
        self.live = live
        self.reachable = reachable

    def report_pollers(self):
        if not self.reachable:
            return None
        return {"live": self.live}


async def _run():
    client, why = None, ""
    client, why = load_client()
    if client is None:
        env_fail("client module unavailable (%s)" % why)
    tid, queue = "t261004-41", "sandbar-ticket-t261004-41"

    missing = [n for n in ("named_snapshot_read", "queue_live_pollers")
               if not hasattr(client, n)]
    if missing:
        check("R0 planned read-face helpers present", False,
              "missing on client: %s (pre-implement TDD red expected)" % ",".join(missing))
        return

    # --- R1 no poller: bounded, named no_poller with ticket/queue/count ---
    face = LivePollerFace(live=0)
    t0 = time.monotonic()
    try:
        res = await asyncio.wait_for(
            client.named_snapshot_read(TimeoutHandle(), tid, queue, 2.0, poller_face=face),
            timeout=BOUND_S)
        elapsed = time.monotonic() - t0
        text = res if isinstance(res, str) else repr(res)
        ok = ("no_poller" in text and tid in text and queue in text
              and ("0" in text))
        check("R1 no-poller read bounded and named", ok,
              "elapsed=%.1fs result=%.200r" % (elapsed, res))
        check("R1 read returned inside the bound", elapsed < BOUND_S,
              "elapsed=%.1fs" % elapsed)
    except asyncio.TimeoutError:
        check("R1 no-poller read bounded and named", False,
              "scenario wait_for(%ss) fired — the read face itself hung" % BOUND_S)

    # --- R2 live pollers but query times out: query_timeout, still named ---
    face = LivePollerFace(live=2)
    t0 = time.monotonic()
    try:
        res = await asyncio.wait_for(
            client.named_snapshot_read(TimeoutHandle(), tid, queue, 1.0, poller_face=face),
            timeout=BOUND_S)
        elapsed = time.monotonic() - t0
        text = res if isinstance(res, str) else repr(res)
        ok = ("query_timeout" in text and "no_poller" not in text
              and tid in text and "2" in text)
        check("R2 timeout-with-pollers named and distinguishable", ok,
              "elapsed=%.1fs result=%.200r" % (elapsed, res))
    except asyncio.TimeoutError:
        check("R2 timeout-with-pollers named and distinguishable", False,
              "read face hung past the scenario bound")

    # --- R3 unreachable poller face: cannot-prove is a value, not a fake zero ---
    face = LivePollerFace(reachable=False)
    try:
        res = await asyncio.wait_for(
            client.named_snapshot_read(TimeoutHandle(), tid, queue, 1.0, poller_face=face),
            timeout=BOUND_S)
        text = res if isinstance(res, str) else repr(res)
        check("R3 unreachable face is a named cannot-prove",
              ("cannot" in text.lower() or "unknown" in text.lower())
              and "no_poller" not in text,
              "result=%.200r" % (res,))
    except asyncio.TimeoutError:
        check("R3 unreachable face is a named cannot-prove", False, "read face hung")

    # --- R4 malformed queue name: refused by name, never a crash ---
    for bad in ("", "  ", "queue\ninjected"):
        try:
            res = await asyncio.wait_for(
                client.named_snapshot_read(TimeoutHandle(), tid, bad, 1.0,
                                           poller_face=LivePollerFace(live=1)),
                timeout=BOUND_S)
            text = res if isinstance(res, str) else repr(res)
            check("R4 malformed queue %r refused by name" % bad,
                  ("queue" in text.lower()), "result=%.120r" % (res,))
        except asyncio.TimeoutError:
            check("R4 malformed queue %r refused by name" % bad, False, "hung")
        except Exception as e:  # noqa: BLE001
            check("R4 malformed queue %r refused by name" % bad, False,
                  "raised %s: %s" % (type(e).__name__, e))

    # --- R5 degraded reads stay bounded under repetition (list-loop face) ---
    worst = 0.0
    for _ in range(3):
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(
                client.named_snapshot_read(TimeoutHandle(), tid, queue, 1.0,
                                           poller_face=LivePollerFace(live=0)),
                timeout=BOUND_S)
        except asyncio.TimeoutError:
            pass
        worst = max(worst, time.monotonic() - t0)
    check("R5 repeated degraded reads each bounded", worst < BOUND_S,
          "worst=%.1fs" % worst)


def main():
    asyncio.run(_run())
    summary()


if __name__ == "__main__":
    main()
