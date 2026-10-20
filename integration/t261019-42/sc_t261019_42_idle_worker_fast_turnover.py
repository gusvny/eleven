#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261019-42 — an idle worker turnover takes seconds, not the full grace window.

Grey-box L3 (integration-owned), offline seconds, zero docker/3099/7233: the
REAL server/engine/worker.py is exercised twice — once as a REAL PROCESS
against a real local SDK test server (subprocess face), once in-process through
the real shutdown machinery with a REAL running activity (SDK face). Never
touches production 3099/7233; the server is one temporalio
WorkflowEnvironment.start_local on a random port shared by both faces (the
temporalio runtime admits only ONE ephemeral server per process).

User-perceivable behavior under contract (the 261019 incident, twice measured):
  A TERM an idle worker -> the process is GONE in seconds and exits 0.
    Pre-fix it logged "no in-flight agent activities" and then pinned for
    1800s until an operator KILL. The process face is the contract: exit code
    and wall clock, read from the outside, not from a writer receipt.
  B TERM a worker whose SDK genuinely holds a running activity -> the fast
    idle exit must NOT fire; the activity completes inside the full grace
    window and reports ok (the 261019 incident shape must never be hard-cut).
  C the shutdown roll-call is honest: while the registry looks empty, the log
    names the SDK-side count (sdk_running_activities=0), so the next incident
    cannot hide behind a blind roll-call; and the shutdown epilogue (reclaim
    receipt) still runs on the fast path.

Intent split vs developer L1 (stub-level, server/engine/tests/): the parser
matrix, the three-face gate over fake workers, and the introspection degrade
are developer L1. THIS entry owns the real-process turnover wall clock (A) and
the real-running-activity not-cut guarantee (B); the t260916-29 selfcheck owns
grace-completion and the "worker terminated externally" classification, not
the idle gate. Steps share the local-server fixture; the intents do not
overlap.

Pre-implement tree red on A/B = the named TDD signal; green required at the
integration gate / merge. Engine venv or the temporal CLI missing = ENV_FAIL
exit 2 (no SKIP). Contract: PASS/FAIL/ENV_FAIL only.
"""

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
VENV_PY = ENGINE / ".venv" / "bin" / "python"
WORKER_PY = ENGINE / "worker.py"

IDLE_DEADLINE_ENV = "SANDBAR_WORKER_IDLE_SHUTDOWN_DEADLINE_SEC"

# Wall-clock budget (a guardrail; the assertion is the order of magnitude):
# pre-fix the idle turnover takes 1800s; post-fix it must land far below this.
TERM_BUDGET_S = 30.0

_failures = []
_checks = 0


def ok(cond, name, evidence=""):
    global _checks
    _checks += 1
    if cond:
        print("PASS - %s" % name, flush=True)
    else:
        print("FAIL - %s | %s" % (name, evidence), flush=True)
        _failures.append(name)
    return bool(cond)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason, flush=True)
    sys.exit(2)


# ---- Face A/C: REAL worker.py process, idle, TERM -> gone in seconds --------

async def _face_a(env, target):
    # The ticket runner's env leaks the HOST ticket's worker wiring into every
    # child (SANDBAR_WATCH_WORKFLOW / SANDBAR_WATCH_PPID would make the child
    # self-exit mid-test; SANDBAR_WORKER_META would point its ownership meta at
    # the main tree — a write outside this lane). The child gets a CLEAN
    # worker env: SANDBAR_* stripped, only what this scenario declares added.
    child_env = {k: v for k, v in os.environ.items()
                 if not k.startswith("SANDBAR_")}
    child_env.update({IDLE_DEADLINE_ENV: "3",
                      "SANDBAR_TARGET_HOST": target,
                      "SANDBAR_TASK_QUEUES": "t26101942-sc-a"})

    with tempfile.TemporaryDirectory(prefix="t26101942-") as tmp:
        pidfile = os.path.join(tmp, "w.pid")
        # logging goes to stderr (basicConfig default) — merge into stdout so
        # one combined stream serves both the readiness wait and the log-face
        # assertions (read back on the reader side, not a writer receipt).
        proc = subprocess.Popen(
            [str(VENV_PY), "-B", str(WORKER_PY),
             "--pidfile", pidfile,
             "--logfile", os.path.join(tmp, "w.log")],
            cwd=str(ENGINE), env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + 60
        ready = False
        outs = []
        while time.monotonic() < deadline and proc.poll() is None:
            line = proc.stdout.readline()
            if not line:
                break
            outs.append(line)
            if "worker 起来了" in line:
                ready = True
                break
        if not ready:
            rest = proc.stdout.read() if proc.poll() is None else ""
            proc.kill()
            env_fail("worker subprocess never reached polling within 60s; "
                     "output tail: %s" % ("".join(outs) + rest)[-2000:])

        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            rest, _ = proc.communicate(timeout=TERM_BUDGET_S + 20)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            rest, _ = proc.communicate()
            rc = None
        elapsed = time.monotonic() - t0
        outs.append(rest or "")
        roll = "".join(outs)

    ok(rc == 0 and elapsed < TERM_BUDGET_S,
       "A: TERM an idle worker -> exits 0 well inside the grace window "
       "(rc=%s, %.1fs; pre-fix shape would hold ~1800s)" % (rc, elapsed),
       "rc=%r elapsed=%.1fs output_tail=%r" % (rc, elapsed, roll[-400:]))
    ok("sdk_running_activities=0" in roll,
       "C1: the roll-call names the SDK-side count while the registry is "
       "empty (the 261019 blind spot is closed on the log face)",
       "output tail: %s" % roll[-1500:])
    ok("shutdown-reclaim receipt" in roll and "worker 已优雅停止" in roll,
       "C2: the shutdown epilogue (reclaim receipt + final line) ran on the "
       "fast path", "output tail: %s" % roll[-800:])


# ---- Face B: REAL running activity is never hard-cut by the idle gate -------
# Driven in its OWN process (see face_b_busy_worker_driver.py header): the
# engine venv's temporalio build panics when a second Worker/run() shares an
# event loop, and the fixture must not fight the SDK. The parent relays the
# driver's PASS/FAIL lines verbatim and judges on its exit code.

DRIVER_PY = Path(__file__).resolve().parent / "face_b_busy_worker_driver.py"


def _face_b():
    # SANCTIONED-WAIT: outer guardrail around a real SDK Worker subprocess doing
    # a full graceful turnover (grace-completion face B); seconds-scale, never
    # reached on a green run — the fixture's own assertions judge the wall clock.
    p = subprocess.run([str(VENV_PY), "-B", str(DRIVER_PY)],
                       # SANCTIONED-WAIT: caps a hung driver only, never hit green
                       cwd=str(ENGINE), timeout=300,
                       capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stdout.flush()
    if p.returncode == 2:
        env_fail("face B driver reports environment red: %s"
                 % (p.stdout + p.stderr)[-800:])
    ok(p.returncode == 0,
       "B: busy-worker turnover face (driver exit=%s, see its lines above)"
       % p.returncode,
       (p.stdout + p.stderr)[-800:])


async def _main():
    from temporalio.testing import WorkflowEnvironment

    if not VENV_PY.exists():
        env_fail("engine venv python missing: %s" % VENV_PY)
    if not WORKER_PY.exists():
        env_fail("worker.py missing: %s" % WORKER_PY)

    # One ephemeral server for the whole scenario (temporalio allows only one
    # per process). The subprocess face needs an ADDRESS, so pin a free port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    async with await WorkflowEnvironment.start_local(port=port) as env:
        await _face_a(env, "127.0.0.1:%d" % port)
        _face_b()

    print("PASS=%d FAIL=%d" % (_checks - len(_failures), len(_failures)),
          file=sys.stderr)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
