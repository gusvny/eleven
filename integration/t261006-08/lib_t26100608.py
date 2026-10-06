#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for the t261006-08 scenarios (worker shutdown must reclaim
its child process tree, KI-210).

Offline, seconds, zero docker/Temporal-server/browser, never touches 3099.
The engine modules are only importable under the engine venv (temporalio);
every scenario resolves the interpreter through the declared fallback chain
(verify.yaml test-check chain): server/engine/.venv/bin/python -> python3.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"

PASS = 0
FAIL = 0


def venv_py() -> str:
    p = ENGINE / ".venv" / "bin" / "python"
    return str(p) if p.is_file() and os.access(str(p), os.X_OK) else sys.executable


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title: str) -> None:
    print("\n%s" % title)


def env_fail(reason: str) -> "NoReturn":  # type: ignore[name-defined]
    print("ENV_FAIL: %s" % reason)
    print("SUMMARY pass=%d fail=%d env_fail=1 na=0" % (PASS, FAIL))
    sys.exit(2)


def summary(name: str) -> None:
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    if FAIL:
        print("%s: FAIL (%d failed checks)" % (name, FAIL))
        sys.exit(1)
    print("%s: PASS" % name)
    sys.exit(0)


def import_engine_module(modname: str):
    """Import an engine module under the venv interpreter; None if the face is
    absent (caller turns None into a named FAIL — TDD-phase red expected)."""
    sys.path.insert(0, str(ENGINE))
    try:
        return __import__(modname)
    except ImportError as e:
        print("  note: engine module %s not importable here (%s)" % (modname, e))
        return None


# ---- real-process fixture ----------------------------------------------------
#
# Child protocol (all in ONE file, chosen by argv[1]):
#   sleep   : block ~600s; on SIGTERM write "<tag> term\n" to receipt, exit 0.
#   termtree: same as sleep plus spawns a grandchild sleep, so a group-granular
#             reclaim has two live pids to reap.
#   sticky  : SIG_IGN on SIGTERM (resists TERM; only KILL ends it) — the
#             escalation / leftover face.
#   tmpclean: create a temp dir with a fixture file; on SIGTERM remove the dir,
#             write receipt, exit — the R4 lever (TERM lets the suite reclaim
#             its own fixtures; a KILL-only reaper would leak the dir).
CHILD_SRC = r'''
import os, shutil, signal, sys, time
mode, receipt, payload = sys.argv[1], sys.argv[2], sys.argv[3]
def on_term(signum, frame):
    with open(receipt, "a") as f:
        f.write(os.path.basename(mode) + " term\n")
    if mode == "tmpclean" and os.path.isdir(payload):
        shutil.rmtree(payload, ignore_errors=True)
    sys.exit(0)
signal.signal(signal.SIGTERM, on_term if mode != "sticky" else signal.SIG_IGN)
gc = None
if mode == "termtree":
    gc = os.fork()
    if gc == 0:
        signal.signal(signal.SIGTERM, on_term)
        time.sleep(600)
while True:
    time.sleep(1)
'''


class AsyncProcHandle:
    """Adapter over subprocess.Popen exposing the asyncio-subprocess face the
    engine's reaper consumes (proc.wait() awaitable, poll(), pid,
    send_signal) — the engine activities spawn with
    asyncio.create_subprocess_exec, so the fixture must present the same
    contract, not a raw sync Popen."""

    def __init__(self, p):
        self._p = p
        self.pid = p.pid

    def poll(self):
        return self._p.poll()

    @property
    def returncode(self):
        return self._p.returncode

    def send_signal(self, sig):
        self._p.send_signal(sig)

    def kill(self):
        self._p.kill()

    async def wait(self):
        import asyncio as _a
        return await _a.get_event_loop().run_in_executor(None, self._p.wait)


def write_child_src(workdir: Path) -> Path:
    src = workdir / "child_src.py"
    src.write_text(CHILD_SRC, "utf-8")
    return src


def spawn_child(mode: str, workdir: Path, start_new_session: bool = True,
                payload: "Path | None" = None):
    """Spawn the fixture child in its own session (same face the engine's long
    activities use). Returns (AsyncProcHandle, receipt_path)."""
    src = write_child_src(workdir)
    receipt = workdir / ("receipt-%s-%d" % (mode, time.monotonic_ns()))
    p = subprocess.Popen(
        [sys.executable, "-B", str(src), mode, str(receipt), str(payload or workdir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=start_new_session)
    return AsyncProcHandle(p), receipt


def wait_gone(p, timeout: float = 15.0) -> bool:
    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        if p.poll() is not None:
            return True
        time.sleep(0.1)
    return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
