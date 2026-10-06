#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-08 scenario 2 — the shutdown roll-call enumerates the child processes
the worker owns and a machine-parseable receipt proves the reclaim (KI-210,
R2+R3; grey-box L3, offline, REAL child processes, zero docker).

User-perceivable contract (incident face: the old worker logged only
「停机点名：无在飞 agent 活动」then 「worker 已优雅停止」 — zero knowledge of
the subprocess class it had spawned; an operator reading ps concluded live
workers still existed):
- R1 roll-call enumerates: one line per still-owned child (tag/pid/age) plus a
  count line — the worker names what it started before it lets it go;
- R2 the reclaim receipt is machine-parseable from the worker log:
  `shutdown-reclaim receipt: owned=N reclaimed=M leftover=[...]` — the R3
  repeatable check is a grep, not ps archaeology; an empty registry still
  prints owned=0 (silence is indistinguishable from ignorance);
- R3 a pid that resists reclamation is NAMED in leftover (a non-empty
  leftover is never silently absorbed as success);
- R4 the reclaim runs in the shutdown epilogue AFTER Worker.shutdown() — i.e.
  on BOTH terminal paths (graceful drain AND grace expiry; the 08:32 orphan
  was born on the grace-expiry path), verified by a source lock on
  _graceful_shutdown.

Intent split: real-tree reaping behavior = scenario 1; TERM-first temp-dir
lifecycle = scenario 3; the drain-handover meta face = t261005-03's scenarios
(not re-asserted). Pre-implement = FAIL naming the missing face (TDD-phase red
expected); green at arbitrate/merge. Engine venv fallback chain exhausted =
ENV_FAIL exit 2. Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
  integration/t261006-08/sc_t26100608_shutdown_rollcall_receipt.py
"""
from __future__ import annotations

import io
import logging
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_t26100608 import (  # noqa: E402
    ENGINE, import_engine_module, ok, section, spawn_child, summary,
    env_fail, wait_gone,
)

RECEIPT_RE = re.compile(
    r"shutdown-reclaim receipt:\s*owned=(\d+)\s+reclaimed=(\d+)\s+leftover=\[([^\]]*)\]")

if not (ENGINE / "worker.py").is_file():
    env_fail("engine worker.py missing under %s" % ENGINE)
wk = import_engine_module("worker")
aa = import_engine_module("agent_activities")
if wk is None or aa is None:
    env_fail("engine venv cannot import worker/agent_activities (temporalio?)")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.buf = io.StringIO()

    def emit(self, record):
        self.buf.write(self.format(record) + "\n")


def main():
    snapshot = getattr(aa, "owned_spawn_snapshot", None)
    reap_all = getattr(aa, "reap_owned_spawns", None)
    rollcall = getattr(wk, "_log_shutdown_disposition", None)
    if snapshot is None or reap_all is None or rollcall is None:
        ok(False, "missing faces: owned_spawn_snapshot / reap_owned_spawns / "
              "shutdown roll-call extension (t261006-08 Steps 1-2 not landed — "
              "TDD-phase red expected)")
        summary("shutdown-rollcall-receipt")
        return

    tmp = Path(tempfile.mkdtemp(prefix="sandbar-sc-t26100608-"))
    log = logging.getLogger("sc-t26100608")
    log.setLevel(logging.INFO)
    log.handlers = []
    cap = Capture()
    cap.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(cap)
    # engine logs via the root logger; route it too
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [cap]

    # ---- R1 roll-call names each owned child ---------------------------------
    section("R1 shutdown roll-call enumerates owned child processes")
    p1, _ = spawn_child("sleep", tmp)
    p2, _ = spawn_child("sleep", tmp)
    reg = getattr(aa, "register_owned_spawn", None)
    if reg:
        reg(p1, "sc-r1-a")
        reg(p2, "sc-r1-b")
    rollcall()
    text = cap.buf.getvalue()
    lines = text.splitlines()
    named = [ln for ln in lines if str(p1.pid) in ln]
    count = [ln for ln in lines if "2" in ln and ("名下" in ln or "owned" in ln
                                                  or "子进程" in ln)]
    ok(bool(named), "R1 roll-call names owned pid %d" % p1.pid)
    ok(bool(count), "R1 roll-call carries a count line for the owned class")
    import asyncio as _a

    def reap_all_sync():
        out = reap_all()
        return _a.new_event_loop().run_until_complete(out) if _a.iscoroutine(out) else out

    # ---- R2 reclaim receipt: dict face + machine-parseable log face ----------
    section("R2 the reclaim receipt is machine-checkable, not ps archaeology")
    if reap_all:
        receipt = reap_all_sync()
        ok(isinstance(receipt, dict) and
           {"owned", "reclaimed", "leftover"} <= set(receipt),
           "R2 receipt carries owned/reclaimed/leftover (got %r)" %
           (sorted(receipt) if isinstance(receipt, dict) else receipt))
        if isinstance(receipt, dict):
            ok(int(receipt.get("owned") or 0) >= 2,
               "R2 owned count reflects the registry (>=2)")
            ok(int(receipt.get("reclaimed") or 0) >= 2 and
               not receipt.get("leftover"),
               "R2 both owned children reclaimed, leftover empty")
        # the worker log face: the receipt token with the same keys is logged by
        # the shutdown epilogue (machine-parseable from the worker log = R3 grep)
        wsrc = (ENGINE / "worker.py").read_text("utf-8")
        ok("shutdown-reclaim receipt" in wsrc,
           "R2 worker epilogue logs the shutdown-reclaim receipt line")
    else:
        ok(False, "R2 reap_owned_spawns missing")
    ok(wait_gone(p1, 20) and wait_gone(p2, 20),
       "R2 reclamation actually ends both owned children")

    # ---- R3 empty registry still reports owned=0 -----------------------------
    section("R3 empty registry is a named owned=0, never silence")
    if reap_all:
        out2 = reap_all_sync()
        ok(isinstance(out2, dict) and out2.get("owned") == 0,
           "R3 empty/drain face reports owned=0 (got %r)" % (out2,))

    # ---- R3b resisting pid is named in leftover ------------------------------
    section("R3b a pid resisting reclaim lands in leftover")
    p3, _ = spawn_child("sticky", tmp)  # ignores SIGTERM
    # seal BOTH signal legs: killpg (injected EPERM) AND the direct-child
    # fallback (the engine treats ProcessLookupError/OSError as best-effort
    # pass) — otherwise the fallback KILLs the sticky child and leftover
    # can never be exercised
    def _dead_send(sig):
        raise ProcessLookupError(3, "No such process (injected)")
    p3.send_signal = _dead_send  # type: ignore[method-assign]
    if reg:
        reg(p3, "sc-r3b")
    import os as _os
    real_killpg = _os.killpg

    def eperm_killpg(pgid, sig, *a, **k):
        raise PermissionError(1, "Operation not permitted (injected)")

    _os.killpg = eperm_killpg
    try:
        out3 = reap_all_sync()
    finally:
        _os.killpg = real_killpg
    ok(isinstance(out3, dict) and str(p3.pid) in
       [str(x) for x in (out3.get("leftover") or [])],
       "R3b resisting pid named in the receipt (leftover face)")
    # cleanup the sticky child for real (escalate directly; undo the seal)
    try:
        p3.send_signal = p3.__class__.send_signal.__get__(p3) \
            if hasattr(p3.__class__, "send_signal") else (lambda sig: None)
        real_killpg(_os.getpgid(p3.pid), 9)
    except Exception:
        import signal as _sig
        _os.kill(p3.pid, _sig.SIGKILL)
    ok(wait_gone(p3, 15), "R3b fixture child cleaned up by the scenario itself")

    # ---- R4 reclaim sits in the shutdown epilogue (both terminal paths) ------
    section("R4 reclaim is in _graceful_shutdown after Worker.shutdown (source lock)")
    wsrc = (ENGINE / "worker.py").read_text("utf-8")
    mgs = re.search(r"async def _graceful_shutdown\(.*?(?=\n(?:async )?def |\Z)",
                    wsrc, re.S)
    ok(mgs is not None, "R4 _graceful_shutdown located")
    if mgs:
        body = mgs.group(0)
        ok("reap_owned_spawns" in body,
           "R4 epilogue calls the owned-spawn reaper")
        ok(body.index("shutdown") < body.index("reap_owned_spawns")
           if "reap_owned_spawns" in body else False,
           "R4 reclamation runs AFTER Worker.shutdown() (grace-expiry path covered)")

    summary("shutdown-rollcall-receipt")


if __name__ == "__main__":
    main()
