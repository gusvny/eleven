#!/usr/bin/env python3
"""Deadman shim: the bench dies with its owner (ticket t261022-15).

Why this exists (host order 261022, ticket t261022-15): a case that runs past
its budget is killed as a process group with SIGKILL. The bench sits in its own
session (so a case's group kill can miss it), and SIGKILL cannot be caught, so
atexit never runs and the bench leaks. Live evidence: a bench survived 4h26m.

The rule this file implements: THE BENCH DIES WITH ITS OWNER.

How (one pipe, no dependency):

- the owner calls bench_spawn (in integration/process_bench.py) and keeps the
  write end of a pipe; this shim gets the read end as an inherited fd and is
  the session leader of the bench group;
- the owner dies for ANY reason, including SIGKILL: the kernel closes the last
  write end, the shim reads EOF, kills the bench group, removes the temp dir
  and the registry entry, and exits. Measured delay: ~0.1 s (the select tick);
- the owner may hand the bench over on purpose (the `up` CLI path, a bench that
  must outlive its starter): it writes ONE byte to the pipe. The shim reads the
  byte, stops watching the deadman, and exits when the bench itself exits;
- the shim ignores SIGTERM and SIGHUP, so a group kill aimed at the bench does
  not kill the watcher before it can act. It still dies with the bench.

Usage (only process_bench.py calls this):

  python3 -B integration/bench_deadman.py <dead_fd> <db_dir> <registry_dir> <cmd...>

Exit status: the child's own status when the child exits by itself, else 0.
"""
from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time

#: The bench temp dir prefix (must match process_bench.TEMP_PREFIX). The shim is
#: self-contained on purpose: it runs before, and after, the owner's module.
TEMP_PREFIX = "sandbar-bench-"
#: The absolute delay when the owner disappears. One select tick is enough; the
#: acceptance bound is 2 s.
DETECT_S = 0.1
#: A bench gets this long to leave on its own before the shim kills it.
TERM_S = 0.9
KILL_S = 1.0


def _note(registry_dir, text):
    """Append one line to the deadman log (best effort, never fatal)."""
    if not registry_dir:
        return
    try:
        path = os.path.join(registry_dir, "deadman.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%.3f %s\n" % (time.time(), text))
    except OSError:
        pass


def _signal_pid(pid, sig):
    try:
        os.kill(int(pid), sig)
    except (OSError, ProcessLookupError):
        pass


def _reclaim_dir(db_dir):
    """Remove the bench temp dir, and ONLY one this module created."""
    if not db_dir:
        return False
    path = os.path.abspath(db_dir)
    if not os.path.basename(path).startswith(TEMP_PREFIX):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.exists(path)


def _drop_entry(registry_dir):
    if not registry_dir:
        return
    try:
        os.unlink(os.path.join(registry_dir, "%d.json" % os.getpid()))
    except OSError:
        pass


def _die(proc, db_dir, registry_dir):
    """The owner is gone: kill the bench group, reclaim the temp dir, exit."""
    _signal_pid(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=TERM_S)
    except subprocess.TimeoutExpired:
        _signal_pid(proc.pid, signal.SIGKILL)
        try:
            proc.wait(timeout=KILL_S)
        except subprocess.TimeoutExpired:
            pass
    reclaimed = _reclaim_dir(db_dir)
    _drop_entry(registry_dir)
    _note(registry_dir, "pid %d: owner gone; bench reaped, db_reclaimed=%s"
          % (os.getpid(), reclaimed))
    # Any descendant is still in our group. Kill the group last: this shim is in
    # it, so it dies here too, after the cleanup above is done. Only a shim that
    # is its own group leader may do this: a shim inside a foreign group must
    # not kill that group.
    if os.getpid() == os.getpgrp():
        try:
            os.killpg(os.getpgid(0), signal.SIGKILL)
        except OSError:
            pass


def _wait(proc, dead_fd, registry_dir):
    """Wait for the child to exit, or for the owner to die or hand over.

    Returns ("child-exit", rc) or ("owner-gone", None).
    """
    watch = dead_fd is not None
    while True:
        if watch:
            try:
                ready, _, _ = select.select([dead_fd], [], [], DETECT_S)
            except OSError:
                ready = []
                watch = False
            if ready:
                try:
                    data = os.read(dead_fd, 64)
                except OSError:
                    data = b""
                if not data:
                    return "owner-gone", None
                # One byte = hand-over: the bench must outlive its starter.
                watch = False
                try:
                    os.close(dead_fd)
                except OSError:
                    pass
                _note(registry_dir, "pid %d: handed over, deadman off"
                      % os.getpid())
        else:
            time.sleep(DETECT_S)
        rc = proc.poll()
        if rc is not None:
            return "child-exit", rc


def main(argv):
    if len(argv) < 4:
        print("usage: bench_deadman.py <dead_fd> <db_dir> <registry_dir> "
              "<cmd...>", file=sys.stderr)
        return 2
    dead_fd = int(argv[0])
    db_dir = argv[1]
    registry_dir = argv[2]
    cmd = argv[3:]
    # A group SIGTERM aimed at the bench must not kill the watcher first. Use a
    # HANDLER and not SIG_IGN: an ignored signal disposition is inherited across
    # exec, so an ignoring shim would hand the bench a SIGTERM it cannot feel.
    # A caught signal is reset to the default action by exec.
    def _keep_running(signum, frame):
        return

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _keep_running)
        except (OSError, ValueError):
            pass
    os.set_inheritable(dead_fd, False)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    except OSError as exc:
        print("deadman: spawn failed (%s): %s" % (type(exc).__name__, exc),
              file=sys.stderr, flush=True)
        _reclaim_dir(db_dir)
        _drop_entry(registry_dir)
        return 2
    reason, rc = _wait(proc, dead_fd, registry_dir)
    if reason == "owner-gone":
        _die(proc, db_dir, registry_dir)
        return 0
    return rc if rc is not None else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
