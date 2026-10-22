#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Process-bench stage seam for scenarios that no longer buy a docker stage.

Why this exists (host order 261022): a scenario that needs a real Temporal
server used to boot a docker stage (integration/stage_docker.py) and then wait
with ceilings of 240-300 s, because the stage took minutes to come up and it
competed with every other lane on the host. integration/process_bench.py brings
the same gRPC front end up as a plain process in ~0.2 s on a kernel-picked
port with a private SQLite file, and reaps it by process group.

This module is the seam between that bench and the fixtures the migrated
scenarios already use (lib_ki061.stage_env / send_signal read a stage-shaped
state dict). It owns four things and nothing else:

  up(fail)            start the bench, or a NAMED env red (exit 2) when the
                      bench refuses (no temporal binary, boot failed);
  BenchStage.state()  the stage-shaped identity the existing fixtures consume
                      ({"ports": {"temporal": ...}} + namespace);
  preflight(...)      fail fast in SECONDS: the endpoint serves, the worker
                      process is alive, the ticket's read face answers. Only
                      after these hold may the caller wait for the state under
                      test (a missing precondition is a named red, never a
                      three-minute silence);
  down(stage, fail)   stop it and judge the residue from the OUTSIDE: the port
                      refuses, the pid is gone, the process group is empty, the
                      private temp dir is reclaimed.

Ceilings are graded by the caller: the case names the state it waits for and
the seconds it allows, and prints the last snapshot when it expires. This
module never waits for a state.
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import process_bench  # noqa: E402

#: Seconds a precondition probe may spend before it is a named red. Injectable
#: so a battery can buy its evidence with a small bound instead of a real wait.
PREFLIGHT_S = float(os.environ.get("SANDBAR_SC_BENCH_PREFLIGHT_S") or 5.0)

#: Exit code for "the bench cannot be supplied at all" (the three-state rule:
#: a missing runtime is an environment red, not a product red).
EXIT_ENV = 2


def _tail(text, limit=600):
    return (text or "").strip()[-limit:]


def _read_tail(path, limit=600):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return _tail(fh.read(), limit)
    except OSError:
        return "<log unreadable: %s>" % path


class BenchStage(object):
    """One running process bench, seen through the stage-shaped fixtures."""

    def __init__(self, handle, mod=process_bench):
        self.mod = mod
        self.handle = handle
        self.port = int(handle["port"])
        self.pid = int(handle["pid"])
        self.db = handle.get("db") or ""
        self.namespace = getattr(mod, "NAMESPACE", "default")
        self.bin = mod.default_bin()
        self.start_s = handle.get("start_s")

    def endpoint(self):
        return self.mod.endpoint(self.port)

    def state(self):
        """A stage-shaped state dict (the shape lib_ki061.stage_env reads)."""
        return {"ports": {"temporal": self.port},
                "namespace": self.namespace,
                "project": "process-bench",
                "request_project": "process-bench",
                "sa_registered": True}

    def down(self, term_s=None, kill_s=None):
        return self.mod.stop(self.port, self.pid, term_s=term_s,
                             kill_s=kill_s, db=self.db)


def up(fail, facts=print):
    """Start the bench. A refusal or a bad binary is a named env red (exit 2)."""
    t0 = time.time()
    handle = process_bench.start()
    if not handle.get("ok"):
        fail.bail("PREFLIGHT RED (environment): the process bench did not start"
                  " - %s" % handle.get("reason"), EXIT_ENV)
    stage = BenchStage(handle)
    facts("bench up: endpoint=%s pid=%s start_s=%s wall=%.2fs db=%s"
          % (stage.endpoint(), stage.pid, stage.start_s, time.time() - t0,
             stage.db))
    return stage


def preflight(fail, stage, worker=None, wlog=None, probe=None, what="the "
              "state under test", bound_s=None, facts=print):
    """Fail fast in seconds: endpoint serves, worker alive, read face answers.

    Each check names WHICH precondition is missing. A missing precondition
    ends the run here - the caller must not go on to wait for a state that
    cannot arrive (the 261022 host order: no three-minute silence).
    """
    bound = PREFLIGHT_S if bound_s is None else float(bound_s)
    t0 = time.time()

    ok, detail = stage.mod.wait_ready(stage.bin, stage.port, boot_s=bound)
    if not ok:
        alive = stage.mod.pid_alive(stage.pid)
        fail.bail("PREFLIGHT RED: temporal is not reachable at the bench "
                  "endpoint %s (%s; bench pid=%s %s) - nothing is waited for "
                  "until this holds" % (stage.endpoint(), detail, stage.pid,
                                        "alive" if alive else "dead"))

    if worker is not None and worker.poll() is not None:
        fail.bail("PREFLIGHT RED: worker process is not alive (rc=%s) - it "
                  "must be running before any state is waited for; log tail: %s"
                  % (worker.returncode, _read_tail(wlog) if wlog else "<no log>"))

    if probe is not None:
        deadline = time.time() + bound
        got = None
        while time.time() < deadline:
            got = probe()
            if got:
                break
            time.sleep(0.2)
        if not got:
            fail.bail("PREFLIGHT RED: the ticket read face did not answer in "
                      "%.1fs on %s - the query path is dead, so waiting for %s "
                      "would only burn the ceiling" % (bound, stage.endpoint(),
                                                       what))

    facts("preflight ok in %.2fs: endpoint serves, worker alive, read face "
          "answers (%s)" % (time.time() - t0, stage.endpoint()))


def down(stage, fail, tag="bench"):
    """Stop the bench and judge the residue from outside (no residue = clean)."""
    block = stage.down()
    fail.check(bool(block.get("port_refuses")),
               "%s down: the endpoint refuses connections (port %s)"
               % (tag, stage.port))
    fail.check(not block.get("pid_alive"),
               "%s down: the bench pid is gone (pid %s)" % (tag, stage.pid))
    fail.check(not block.get("group_alive"),
               "%s down: no surviving child in the bench process group "
               "(survivors=%s)" % (tag, block.get("survivors")))
    fail.check(bool(block.get("clean")),
               "%s residue clean: stopped_s=%s escalated=%s (port refuses, no "
               "pid, empty group)" % (tag, block.get("stopped_s"),
                                      block.get("escalated")))
    fail.check(bool(block.get("db_removed")),
               "%s down: the private temp dir was reclaimed (%s)"
               % (tag, stage.db))
    return block
