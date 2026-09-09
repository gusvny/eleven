"""Lifecycle of a ticket-dedicated worker: start, stop, rescue (host decision
260824: one worker per ticket).

Each ticket gets a dedicated task queue (sandbar-ticket-<id>, see the LEGACY old
prefixes in shared.ticket_task_queues) plus one dedicated worker process. This
module only manages the process lifecycle:

- spawn_ticket_worker(tid): start the dedicated worker (skip if already alive;
  idempotent).
- reap_ticket_worker(tid): SIGTERM the dedicated worker (skip if absent;
  idempotent).
- ensure_ticket_workers(running_tids, all_ticket_ids): reconcile — start a
  worker for every RUNNING ticket that lacks one; reap workers whose workflow
  is no longer running.

Role (after the 260824 round-A decision): in production, ticket workers are
spawned as child processes by the console keepalive ensure (temporal-tools
supervisor, tied to the console lifetime and disposed with it; ticket.py create
no longer spawns). This module stays as the manual/test tool plus the reap
primitive for reconcile (reap_ticket_worker / worker_pid). The spawn family is
only for the test stack or manual use without a console.

stdlib-only: server/tools/ticket.py loads this module directly under the system
python3 (no temporalio available). Temporal state queries do not happen here —
the caller (the side that has the SDK) supplies the running/closed id lists.

Env passthrough: spawn inherits os.environ, so SANDBAR_TARGET_HOST /
SANDBAR_NAMESPACE (in tests pointing at the Docker-isolated Temporal, see
docs/testing-guide.md) reach the child process automatically.
"""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess

POC_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = POC_DIR / 'data'
VENV_PY = str(POC_DIR / '.venv' / 'bin' / 'python')


def _pidfile(tid: str) -> pathlib.Path:
    return DATA_DIR / ('worker-%s.pid' % tid)


def _logfile(tid: str) -> pathlib.Path:
    return DATA_DIR / ('worker-%s.log' % tid)


def worker_pid(tid: str) -> int:
    """Live pid of the dedicated worker (pidfile present and process alive);
    0 otherwise. A stale pidfile is removed automatically."""
    try:
        pid = int(_pidfile(tid).read_text().strip())
    except Exception:
        return 0
    try:
        os.kill(pid, 0)
        return pid
    except ProcessLookupError:
        try:
            _pidfile(tid).unlink()
        except OSError:
            pass
        return 0
    except PermissionError:
        return pid  # process exists but is not ours — treat as alive, do not touch


def _ticket_task_queue(tid: str) -> str:
    """Task queue name for the ticket. shared.py is loaded here by file path
    (when ticket.py loads this module directly, 'shared' is not on sys.path —
    this side is stdlib-only, and path loading behaves the same both ways)."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location('_tw_shared', POC_DIR / 'shared.py')
    mod = importlib.util.module_from_spec(spec)
    # must register in sys.modules: python 3.9 dataclasses resolves postponed
    # annotations via cls.__module__ against sys.modules and raises
    # AttributeError when the lookup fails (observed 260821).
    sys.modules.setdefault('_tw_shared', mod)
    spec.loader.exec_module(mod)
    return mod.ticket_task_queue(tid)


def _ticket_task_queues(tid: str) -> list:
    """Both queues to poll (new prefix first, then the old one; see
    shared.ticket_task_queues and retired-account #2)."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location('_tw_shared', POC_DIR / 'shared.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault('_tw_shared', mod)
    spec.loader.exec_module(mod)
    return mod.ticket_task_queues(tid)


def spawn_ticket_worker(tid: str) -> str:
    """Start the ticket's dedicated worker (idempotent: returns immediately if
    alive). Returns 'already' | 'spawned'."""
    if worker_pid(tid):
        return 'already'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # multi-queue injection (t260907-04): the new ticket queue first plus the old
    # ticket queue (so in-flight workflows on the old queue still drain); worker.py
    # registers each CSV queue (same registry; the log shows both queues).
    env['SANDBAR_TASK_QUEUES'] = ','.join(_ticket_task_queues(tid))
    env['SANDBAR_WATCH_WORKFLOW'] = tid  # worker self-exits when the workflow closes (worker.py watcher)
    # --daemon: worker.py forks+setsid itself and writes the pidfile, so this
    # call returns immediately.
    subprocess.Popen(
        [VENV_PY, str(POC_DIR / 'worker.py'), '--daemon',
         '--pidfile', str(_pidfile(tid)), '--logfile', str(_logfile(tid))],
        cwd=str(POC_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    return 'spawned'


def reap_ticket_worker(tid: str) -> str:
    """SIGTERM the dedicated worker (idempotent). Returns 'reaped' | 'none'."""
    pid = worker_pid(tid)
    if not pid:
        return 'none'
    try:
        os.kill(pid, signal.SIGTERM)  # graceful stop: running activities finish first (worker.py contract)
    except ProcessLookupError:
        pass
    try:
        _pidfile(tid).unlink()
    except OSError:
        pass
    return 'reaped'


def ensure_ticket_workers(running_tids, known_tids) -> dict:
    """Reconcile loop (rescue / collect): start workers for RUNNING tickets
    that lack one; reap live workers for known tickets that are no longer running.

    running_tids: ids with exec_status=RUNNING; known_tids: all ticket ids known
    to the module (including closed ones). Returns {'spawned': [...],
    'reaped': [...]} so the scan report can keep a trace.
    """
    running = set(running_tids)
    spawned, reaped = [], []
    for tid in sorted(running):
        if not worker_pid(tid):
            spawn_ticket_worker(tid)
            spawned.append(tid)
    for tid in sorted(set(known_tids) - running):
        if worker_pid(tid):
            reap_ticket_worker(tid)
            reaped.append(tid)
    return {'spawned': spawned, 'reaped': reaped}
