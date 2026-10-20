#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Face B driver for sc_t261019_42 (t261019-42) — runs in its OWN process.

The temporalio build in the engine venv panics ("TaskLocals must only be set
once") when a second Worker/run() shares an event loop that already hosted one
(reproduced with a bare minimal script, no engine code). Isolating the busy
worker face in a fresh process keeps the contract under test real: a genuinely
running activity must survive TERM without the fast idle exit arming.

Prints PASS/FAIL lines on stdout; exit 0 = all green, 1 = any red,
2 = environment (no temporal server / import failure).
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "server" / "engine"
sys.path.insert(0, str(ENGINE))

IDLE_DEADLINE_ENV = "SANDBAR_WORKER_IDLE_SHUTDOWN_DEADLINE_SEC"

_failures = []
_checks = 0


def ok(cond, name, evidence=""):
    global _checks
    _checks += 1
    msg = ("PASS - %s" % name) if cond else ("FAIL - %s | %s" % (name, evidence))
    print(msg, flush=True)
    if not cond:
        _failures.append(name)


async def main():
    from selfcheck_graceful_stop_probe import CTRL, ProbeWorkflow, guarded_probe
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    import agent_activities
    import worker as worker_mod

    captured = []

    class _H(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    logging.getLogger().addHandler(_H(level=logging.INFO))
    logging.getLogger().setLevel(logging.INFO)

    queue = "t26101942-sc-b"
    ticket = "t26101942-busy"
    stage = "busy_stage"
    # Bounded guardrail: if release ever fails the grace wait must not run the
    # real default (1800s) inside a test. The contract is "not cut", not the
    # grace length.
    os.environ["SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"] = "20"
    async with await WorkflowEnvironment.start_local() as env:
        # Same construction order and shape as selfcheck_worker_graceful_stop
        # (_run_scenario): workflow first, then a plain Worker + run task (the
        # `async with Worker` form trips a validate panic in this SDK build).
        handle = await env.client.start_workflow(
            ProbeWorkflow.run,
            {"ticket": ticket, "stage": stage, "mode": "plain"},
            id="t26101942-sc-b-wf",
            task_queue=queue)
        w = Worker(env.client, task_queue=queue,
                   workflows=[ProbeWorkflow], activities=[guarded_probe],
                   **worker_mod._worker_extra_kwargs())
        run_task = asyncio.create_task(w.run())
        # A handover worker on the same queue (selfcheck's worker2 pattern):
        # after w1 stops, the workflow continuation (activity result delivery)
        # needs a live poller or the result never resolves.
        w2 = Worker(env.client, task_queue=queue,
                    workflows=[ProbeWorkflow], activities=[guarded_probe],
                    **worker_mod._worker_extra_kwargs())
        t2 = asyncio.create_task(w2.run())
        # Pre-seed the release gate so the stub activity WAITS in-flight until
        # we release it (without a gate the stub returns in milliseconds and
        # "in flight" is unobservable).
        CTRL["release"][ticket] = asyncio.Event()
        entered = False
        for _ in range(150):
            if CTRL["entered"].get(ticket) is True:
                entered = True
                break
            await asyncio.sleep(0.1)
        ok(entered, "B setup: the stub activity is genuinely in flight "
                   "(guard entered on the real activity)",
           "entered=%r snapshot=%r"
           % (CTRL["entered"].get(ticket),
              agent_activities.inflight_stage_snapshot()))

        # The real turnover wiring: signal handlers -> stop -> epilogue.
        stop = worker_mod.install_stop_signal_handlers()
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(stop.wait(), 10)
        shutdown_task = asyncio.create_task(
            worker_mod._graceful_shutdown([w], [run_task], None,
                                          meta_path=None))
        await asyncio.sleep(0.2)
        # Release AFTER shutdown starts (poll stopped) — the grace window is
        # what lets the in-flight activity finish. A TIGHT idle deadline: if
        # the gate were registry-blind (the pre-review v1 shape) it would cut
        # the worker at 1s despite the genuinely running activity.
        os.environ[IDLE_DEADLINE_ENV] = "1"
        rel = CTRL["release"].get(ticket)
        if rel is not None:
            rel.set()
        await asyncio.wait_for(shutdown_task, 60)

        res = await asyncio.wait_for(handle.result(), timeout=60)
        t2.cancel()
        try:
            await asyncio.gather(t2, return_exceptions=True)
        except Exception:
            pass
        ok(res.get("status") == "ok",
           "B: the running activity completes and reports ok — the fast idle "
           "exit did NOT cut it (result=%r)" % (res,),
           "res=%r" % (res,))
        ok(not any("fast idle exit armed" in t for t in captured),
           "B: the idle gate never armed while the SDK held an activity",
           "log lines with 'armed': %r"
           % [t for t in captured if "armed" in t])
        ok(any("停机点名" in t and ticket in t for t in captured),
           "B: the roll-call names the in-flight activity (ticket/stage)",
           "named=%r" % [t for t in captured if "停机点名" in t][:2])

    print("PASS=%d FAIL=%d" % (_checks - len(_failures), len(_failures)),
          file=sys.stderr)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
