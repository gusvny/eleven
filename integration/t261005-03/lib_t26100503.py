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

Fixture child lifetime (t261030-43): a spawned `LaneChild` ANNOUNCES readiness on
its own stdout (`lane-child-ready pid=<pid>`) and then blocks reading stdin, so it
lives exactly until the parent lets it go. It never lives on a wall clock: the old
shape slept 120 s, a loaded round took 123.9 s, the children retired mid-case and
the orphan-probe legs judged a fixture race as a product red. The parent wait for
the ready line is bounded and injectable through the project's `SANDBAR_*_SECS`
convention, and its expiry is NAMED per child (which pid, which condition).
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

#: Readiness line the fixture child prints once its interpreter is up (`exec`
#: done, cwd and argv final) and before it blocks on stdin.
CHILD_READY_MARK = "lane-child-ready"
#: Bounded, injectable wait for that line — the project's `SANDBAR_*_SECS`
#: convention (same shape as SANDBAR_D2B_PYTEST_BUDGET_SECS, t260930-09 family).
CHILD_READY_ENV = "SANDBAR_T26100503_CHILD_READY_SECS"
DEFAULT_CHILD_READY_S = 30.0

#: The fixture child program: announce readiness, then hold the process open
#: until the parent closes the stdin pipe (EOF). Parent-owned lifetime, so no
#: wall clock can retire the child while a leg under load is still probing it.
CHILD_PROGRAM = (
    "import os, sys\n"
    "sys.stdout.write(%r + ' pid=' + str(os.getpid()) + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.read()\n"
) % (CHILD_READY_MARK,)


def child_ready_budget() -> "tuple[float, str]":
    """(effective readiness wait in seconds, provenance) — never silent.

    A malformed or non-positive value is NAMED and falls back to the default
    (an unreadable knob must not shorten the wait into a false red)."""
    raw = (os.environ.get(CHILD_READY_ENV) or "").strip()
    if not raw:
        return DEFAULT_CHILD_READY_S, "default"
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CHILD_READY_S, "malformed %r -> default" % raw
    if not value > 0:
        return DEFAULT_CHILD_READY_S, "non-positive %r -> default" % raw
    return value, "env %r" % raw


def _read_ready_line(proc, budget_s: float, provenance: str) -> "tuple[str, str]":
    """Read one line from the child's stdout with a bounded wait.

    Returns (line, "") when the condition became true, or ("", why) naming the
    condition that never became true (timeout vs. child already gone — two
    different causes, never one anonymous failure)."""
    import select  # local import: only the readiness wait needs it

    fd = proc.stdout.fileno()
    end = time.monotonic() + budget_s
    buf = b""
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return "", ("no %s line within %.1fs (wait=%s)"
                        % (CHILD_READY_MARK, budget_s, provenance))
        try:
            ready, _, _ = select.select([fd], [], [], left)
        except (OSError, ValueError) as e:
            return "", ("could not wait for the %s line (%s: %s)"
                        % (CHILD_READY_MARK, type(e).__name__, e))
        if not ready:
            return "", ("no %s line within %.1fs (wait=%s)"
                        % (CHILD_READY_MARK, budget_s, provenance))
        try:
            chunk = os.read(fd, 4096)
        except OSError as e:
            return "", ("could not read the %s line (%s: %s)"
                        % (CHILD_READY_MARK, type(e).__name__, e))
        if not chunk:
            rc = proc.poll()
            return "", ("child closed stdout before the %s line (exit=%r)"
                        % (CHILD_READY_MARK, rc))
        buf += chunk
        if b"\n" in buf:
            return buf.split(b"\n", 1)[0].decode("utf-8", "replace"), ""


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
    optional pidfile naming it.

    Lifetime is PARENT-OWNED (t261030-43): the child prints the readiness line
    and blocks on stdin, so it stays alive exactly until close() lets go — a
    loaded round can no longer outlive its own fixture. `ready_ok` /
    `ready_detail` carry the outcome of the bounded readiness wait that
    __init__ performs, so a caller can fail BY NAME instead of guessing.

    ALWAYS terminated in close() (reclamation rule: the test must never
    manufacture the very orphan family it guards against)."""

    def __init__(self, lane_root: Path, with_pidfile: bool = False):
        self.dir = lane_root / ".lane" / "t261005-03-fixture" / ("child-%d" % time.time_ns())
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", CHILD_PROGRAM], cwd=str(self.dir),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            budget, how = child_ready_budget()
            line, why = _read_ready_line(self.proc, budget, how)
            self.ready_line = line
            self.ready_ok = bool(line)
            self.ready_detail = why or (line + " (wait=%.1fs, %s)" % (budget, how))
            self.pidfile = None
            if with_pidfile:
                self.pidfile = self.dir / "worker.pid"
                write_pidfile(self.pidfile, self.proc.pid)
        except BaseException:
            # A half-built fixture must not leave its child running (the test
            # never manufactures the orphan family it guards against).
            self.close()
            raise

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def state(self) -> str:
        """One-line diagnostic for a NAMED failure: which pid, alive or exited
        with which code, and whether its own readiness line arrived."""
        rc = self.proc.poll()
        return ("pid=%d %s ready=%s"
                % (self.proc.pid, "alive" if rc is None else "EXITED rc=%s" % rc,
                   "yes" if self.ready_ok else "no (%s)" % self.ready_detail))

    def close(self):
        if self.alive:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
