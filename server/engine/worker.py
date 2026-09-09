"""Worker: registers workflows/activities onto a task queue and runs them.

The worker is the "muscle"; the server is the "skeleton and memory". If the
worker dies or the code restarts, workflow state and history stay safe on the
server.

How to start:
    # Foreground (debugging / watching logs)
    .venv/bin/python worker.py

    # Background (long-running)
    .venv/bin/python worker.py --daemon [--pidfile data/worker.pid] [--logfile data/worker.log]

    # Per-ticket dedicated worker (usually spawned as a child process by console
    # keepalive; no need to run by hand):
    #   SANDBAR_TASK_QUEUE=<queue> SANDBAR_WATCH_WORKFLOW=<ticket-id> \
    #     .venv/bin/python worker.py --daemon --pidfile data/worker-<ticket-id>.pid --logfile data/worker-<ticket-id>.log
    #   In WATCH mode the worker periodically checks its own workflow status and
    #   exits gracefully once the workflow settles (no longer RUNNING).
    #   Poll interval via env SANDBAR_WATCH_INTERVAL_SEC (default 30s; malformed
    #   values fall back to the default, floor is 1s).
    #   Console child-process mode also sets SANDBAR_WATCH_PPID=1: if the host is
    #   SIGKILLed, ppid becomes 1 and the worker exits on its own — no orphan
    #   workers left behind (not set for manual --daemon starts, which stay up).
    # Ownership fingerprint (KI-033): with SANDBAR_WORKER_META=<path> the worker
    #   writes a meta JSON (repo_root/pid) at startup; daemon mode writes
    #   <pidfile>.meta. The ensure side uses it to detect a worker from another
    #   repo serving the same ticket (warn + refuse).

Graceful stop:
    kill -TERM $(cat data/worker.pid)      # SIGTERM / Ctrl-C (SIGINT) same idea
    → worker.shutdown(): finish in-flight activities, stop claiming new work,
    then exit cleanly. (Workflows on the server stay RUNNING while the worker is
    down; queued work resumes automatically after restart.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import signal
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES
from agent_activities import ALL_AGENT_ACTIVITIES
from shared import NAMESPACE, POC_DIR, REPO_ROOT, TARGET_HOST, TASK_QUEUE, configured_task_queues
from shared import write_worker_meta
from workflows import ALL_WORKFLOWS
from workflows_v2 import ALL_WORKFLOWS_V2

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

WATCH_INTERVAL_DEFAULT_SEC = 30.0  # production default: one poll round per 30s (settle-sensing delay cap ≈ one round)
WATCH_INTERVAL_MIN_SEC = 1.0       # floor clamp: guards against 0/negative busy-loop hammering describe


def watch_interval_sec(raw: "str | None" = None) -> float:
    """Watch poll interval in seconds. Env SANDBAR_WATCH_INTERVAL_SEC overrides,
    used to speed up integration scenarios. Only takes effect in per-ticket mode
    (SANDBAR_WATCH_WORKFLOW set) — the watch task is only created in that mode.
    Fully fault-tolerant on external input: unset/blank/non-numeric/NaN/Inf/<=0
    all fall back to the default; valid values below the floor clamp to the floor
    to prevent busy-looping."""
    if raw is None:
        raw = os.environ.get("SANDBAR_WATCH_INTERVAL_SEC") or ""
    raw = str(raw).strip()
    if not raw:
        return WATCH_INTERVAL_DEFAULT_SEC
    try:
        val = float(raw)
    except ValueError:
        return WATCH_INTERVAL_DEFAULT_SEC
    if val != val or val in (float("inf"), float("-inf")) or val <= 0:
        return WATCH_INTERVAL_DEFAULT_SEC
    return max(val, WATCH_INTERVAL_MIN_SEC)


def worker_meta_path(args: argparse.Namespace) -> str:
    """Where the ownership-fingerprint meta lands (KI-033).

    - Per-ticket mode (console supervisor spawn): read env SANDBAR_WORKER_META,
      the agreed value is <dataDir>/worker-<tid>.meta, same dir as the pidfile;
    - Daemon mode: <pidfile>.meta (the worker knows its own pidfile path);
    - Foreground debug mode: no meta (nothing will read it).

    The pidfile stays a bare numeric pid; the meta is a sidecar file. The ensure
    side flags a foreign-repo worker by "pid alive + meta pointing at another
    repo" — warn and refuse only, it never kills someone else's process."""
    env_path = os.environ.get("SANDBAR_WORKER_META") or ""
    if env_path:
        return env_path
    if args.daemon:
        return args.pidfile + ".meta"
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="溯游 Temporal worker")
    p.add_argument("--daemon", action="store_true", help="后台运行（fork+setsid，父进程立即退出）")
    p.add_argument("--pidfile", default=str(POC_DIR / "data" / "worker.pid"),
                   help="PID 文件路径（后台模式写自己的 pid，优雅停用 kill -TERM $(cat pidfile)）")
    p.add_argument("--logfile", default=str(POC_DIR / "data" / "worker.log"),
                   help="日志文件路径（后台模式 stdout/stderr 重定向到这里）")
    return p.parse_args()


def daemonize(pidfile: str, logfile: str) -> bool:
    """Single-fork detach from the session. Returns True if this is the parent
    process (the caller should exit immediately)."""
    pid = os.fork()
    if pid > 0:
        # Parent: record the child pid, then exit (setsid in the child keeps the pid)
        pathlib.Path(pidfile).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(pidfile).write_text(str(pid))
        return True
    # Child: leave the terminal session, redirect stdio to the log file
    os.setsid()
    log_path = pathlib.Path(logfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "a", buffering=1)
    os.dup2(logf.fileno(), 1)
    os.dup2(logf.fileno(), 2)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    pathlib.Path(pidfile).write_text(str(os.getpid()))
    return False


async def run_worker(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    # Write the ownership fingerprint early (KI-033): before Client.connect, so
    # the ensure side can read the ownership as soon as the worker is alive.
    # Best-effort — a write failure must not block startup (the ensure side
    # tolerates a missing meta as unknown).
    meta_path = worker_meta_path(args)
    if meta_path:
        payload = write_worker_meta(meta_path, repo_root=str(REPO_ROOT), pid=os.getpid())
        logging.info("worker 归属指纹：repo_root=%s pid=%d meta=%s",
                     payload.get("repo_root"), payload.get("pid"), meta_path)
    else:
        logging.info("worker 归属指纹：前台模式不落 meta（repo_root=%s）", REPO_ROOT)
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    # The old TicketWorkflow is retired (ticket t260823, all tickets closed).
    # Workflow list = the two step-1 classes (compat) + the six template
    # subclasses; activity list = generic activities + agent-stage activities.
    # Multi-queue (ticket t260907-04 retirement ledger): one Worker instance per
    # queue, sharing the same registry. Shared mode polls the old and new shared
    # queues (in-flight workflows on the old queue drain out); dedicated mode
    # gets the old and new ticket queues injected via SANDBAR_TASK_QUEUES (so
    # old-prefix workflows of in-flight tickets don't strand after a worker
    # restart). The startup log prints every queue = evidence of double registration.
    workers = []
    for _q in configured_task_queues():
        workers.append(Worker(
            client,
            task_queue=_q,
            workflows=ALL_WORKFLOWS + ALL_WORKFLOWS_V2,
            activities=ALL_ACTIVITIES + ALL_AGENT_ACTIVITIES,
        ))
    logging.info("worker polling queues: %s", ", ".join(configured_task_queues()))

    # Graceful stop: SIGTERM/SIGINT → worker.shutdown() (finish in-flight
    # activities, stop claiming new work)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # non-main thread / unsupported platform: degrade to no signal handling (foreground Ctrl-C is still handled by asyncio's default)

    # Per-ticket mode: with SANDBAR_WATCH_WORKFLOW=<ticket-id>, poll the workflow
    # status periodically and exit gracefully once it settles (no longer RUNNING)
    # — a dedicated worker's lifecycle follows its ticket, it is not long-running.
    # A failed query does not exit (network flakiness / missing workflow don't
    # count): if the worker stops, work piles up, so we prefer to wait one more round.
    # ppid guard: when console spawns us as a child it sets SANDBAR_WATCH_PPID=1 —
    # if the host is SIGKILLed (dispose can't run), this process gets adopted by
    # launchd, ppid becomes 1, and we exit on that — no orphan workers.
    watch_wf = os.environ.get("SANDBAR_WATCH_WORKFLOW") or ""
    watch_ppid = os.environ.get("SANDBAR_WATCH_PPID") == "1"
    watch_interval = watch_interval_sec()
    watch_task: "asyncio.Task | None" = None

    async def _watch() -> None:
        while not stop.is_set():
            await asyncio.sleep(watch_interval)
            if watch_ppid and os.getppid() == 1:
                logging.info("watch：宿主 console 已退出（ppid=1 被收养），专属 worker 自退")
                stop.set()
                return
            try:
                desc = await client.get_workflow_handle(watch_wf).describe()
                status = desc.status.name if desc.status is not None else ""
                if status and status != "RUNNING":
                    logging.info("watch：workflow %s 已收口（%s），专属 worker 自退", watch_wf, status)
                    stop.set()
                    return
            except Exception as e:
                logging.warning("watch：查询 %s 状态失败（下一轮再试）：%s: %s",
                                watch_wf, type(e).__name__, e)

    if watch_wf:
        watch_task = asyncio.create_task(_watch())
        logging.info("worker 起来了：queues=%s host=%s watch=%s（工单专属，收口自退）",
                     ",".join(configured_task_queues()), TARGET_HOST, watch_wf)
    else:
        logging.info("worker 起来了：queues=%s host=%s",
                     ",".join(configured_task_queues()), TARGET_HOST)
    run_tasks = [asyncio.create_task(w.run()) for w in workers]
    await stop.wait()
    logging.info("收到停止信号，优雅停：在跑 activity 完成后停领新活 …")
    await asyncio.gather(*(w.shutdown() for w in workers))
    if watch_task is not None:
        watch_task.cancel()
    try:
        await asyncio.gather(*run_tasks)
    except asyncio.CancelledError:
        pass
    logging.info("worker 已优雅停止")


def main() -> None:
    args = parse_args()
    if args.daemon:
        is_parent = daemonize(args.pidfile, args.logfile)
        if is_parent:
            return
    meta_path = worker_meta_path(args)
    try:
        asyncio.run(run_worker(args))
    except KeyboardInterrupt:
        pass
    finally:
        # Graceful-stop cleanup: remove our own meta. A stale meta would be
        # dropped by the ensure side anyway ("pid dead"), but removing it
        # actively is cleaner. Best-effort — a removal failure must not mask
        # the exit code.
        if meta_path:
            try:
                pathlib.Path(meta_path).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    main()
