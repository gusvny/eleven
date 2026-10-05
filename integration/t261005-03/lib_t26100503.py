#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-03 shared fixtures (non-sc_ prefix = shared helpers, not in SCENARIOS).

Provides:
- engine path setup + lazy imports of the engine faces under test
  (shared / worker guard / client named-read / lane_reclaim probe);
- pidfile+meta fixture makers (real live pid = this interpreter's own pid via a
  real pidfile shape, or a spawned child for the reclaim safety face);
- the check / summary / env_fail three-state harness (same shape as t261004-25).

Discipline: fixtures register under lib_tmp_reclaim; child processes are always
reaped in finally (resource-lifecycle rule).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ENGINE = REPO / "server" / "engine"

if str(REPO / "integration") not in sys.path:
    sys.path.insert(0, str(REPO / "integration"))
import lib_tmp_reclaim  # noqa: E402

_results: list = []


def env_fail(why: str):
    print("ENV_FAIL: %s" % why)
    sys.exit(2)


def check(name: str, ok: bool, detail: str = ""):
    _results.append((name, bool(ok), detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))


def summary():
    bad = [r for r in _results if not r[1]]
    print("SUMMARY %d/%d passed" % (len(_results) - len(bad), len(_results)))
    if bad:
        for n, _, d in bad:
            print("  FAILED: %s %s" % (n, d))
        sys.exit(1)
    sys.exit(0)


def load_engine():
    """Import engine faces. Returns (shared, worker) or (None, reason)."""
    if not ENGINE.is_dir():
        return None, "engine dir missing: %s" % ENGINE
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        import shared  # noqa: F401
        import worker
        return (shared, worker), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def load_client():
    """Import client with a dead-host stub pinned BEFORE import (red-line stub)."""
    os.environ.setdefault("SANDBAR_TARGET_HOST", "127.0.0.1:9")
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        import client
        return client, ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def mk_lane_root(label: str) -> Path:
    d = lib_tmp_reclaim.mkdtemp_reclaimed("t26100503-" + label + "-")
    (d / ".lane" / "t261005-03-fixture").mkdir(parents=True, exist_ok=True)
    return d


def write_pidfile(pidfile: Path, pid: int):
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(pid) + "\n", "utf-8")


def write_meta(pidfile: Path, pid: int, repo_root: str, state=None, raw=None):
    """Meta sidecar. state=None keeps the OLD shape (backward-compat face);
    raw=<str> writes garbage (malformed face)."""
    p = Path(str(pidfile) + ".meta")
    p.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        p.write_text(raw, "utf-8")
        return p
    payload = {"version": 1, "pid": int(pid), "repo_root": repo_root,
               "ts": int(time.time())}
    if state is not None:
        payload["state"] = state
    p.write_text(json.dumps(payload), "utf-8")
    return p


class LaneChild:
    """A real spawned child process with cwd under a fixture lane root, plus an
    optional pidfile naming it. ALWAYS terminated in close() (reclamation rule:
    the test must never manufacture the very orphan family it guards against)."""

    def __init__(self, lane_root: Path, with_pidfile: bool = False):
        self.dir = lane_root / ".lane" / "t261005-03-fixture" / ("child-%d" % time.time_ns())
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(self.dir))
        self.pidfile = None
        if with_pidfile:
            self.pidfile = self.dir / "worker.pid"
            write_pidfile(self.pidfile, self.proc.pid)

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        if self.alive:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
