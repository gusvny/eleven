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
    → worker.shutdown(): stop claiming new work, then give in-flight activities a
    grace period (graceful_shutdown_timeout) to finish before cancelling whatever
    is still running. Grace comes from env SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC
    (default 1800s; explicit "0" = the old cancel-immediately behavior; malformed
    values fall back to the default). At shutdown the worker names every in-flight
    agent activity (ticket/stage/gen/attempt) in the log, and after shutdown it
    logs the final disposition (finished vs interrupted) — a cancelled activity is
    converted by agent_activities.worker_termination_guard into a typed
    ApplicationError so the ticket face says "worker 被外部终止（停机/重载）" instead
    of a generic activity fault (t260916-29; ops runbook: server/engine/README.md
    §8.3.1). (Workflows on the server stay RUNNING while the worker is down; queued
    work resumes automatically after restart.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import signal
import sys
import time
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES
from agent_activities import ALL_AGENT_ACTIVITIES
from agent_activities import inflight_stage_snapshot, recent_stage_outcomes
from shared import NAMESPACE, POC_DIR, REPO_ROOT, TARGET_HOST, TASK_QUEUE, configured_task_queues
from shared import write_worker_meta
from workflows import ALL_WORKFLOWS
from workflows_v2 import ALL_WORKFLOWS_V2

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

WATCH_INTERVAL_DEFAULT_SEC = 30.0  # production default: one poll round per 30s (settle-sensing delay cap ≈ one round)
WATCH_INTERVAL_MIN_SEC = 1.0       # floor clamp: guards against 0/negative busy-loop hammering describe

GRACEFUL_SHUTDOWN_ENV = "SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"
GRACEFUL_SHUTDOWN_DEFAULT_SEC = 1800.0  # 30min: covers the typical 10~40min agent stage tail; longer runs get the named-cancel path (README §8.3.1)


def graceful_shutdown_timeout_sec(raw: "str | None" = None) -> float:
    """Grace period for in-flight activities after shutdown is requested, in
    seconds. Env SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC overrides; fault tolerance
    mirrors watch_interval_sec: unset/blank/malformed/NaN/Inf/negative all fall
    back to the default (a negative must NOT mean "cancel immediately" by
    accident — the immediate-cancel escape hatch is an explicit "0"). No upper
    clamp on purpose: the operator owns the linger trade-off (a shutting-down
    worker stays alive up to this long to let in-flight activities finish;
    documented in README §8.3.1)."""
    if raw is None:
        raw = os.environ.get(GRACEFUL_SHUTDOWN_ENV) or ""
    raw = str(raw).strip()
    if not raw:
        return GRACEFUL_SHUTDOWN_DEFAULT_SEC
    try:
        val = float(raw)
    except ValueError:
        return GRACEFUL_SHUTDOWN_DEFAULT_SEC
    if val != val or val in (float("inf"), float("-inf")) or val < 0:
        return GRACEFUL_SHUTDOWN_DEFAULT_SEC
    return val


def _worker_extra_kwargs() -> dict:
    """Single source of the Worker(...) kwargs this ticket owns (t260916-29):
    the explicit graceful shutdown timeout. Both the production constructor and
    the self-check build their workers from here, so the wiring cannot drift
    (UT test_t260916_29_worker_graceful_stop pins the shape)."""
    return {"graceful_shutdown_timeout":
            timedelta(seconds=graceful_shutdown_timeout_sec())}


def install_stop_signal_handlers() -> asyncio.Event:
    """SIGTERM/SIGINT → the returned stop event (same wiring run_worker has used
    since step 1; extracted so the graceful-stop self-check can exercise the real
    handler path). Degrades to no signal handling on unsupported platforms
    (non-main thread / Windows): foreground Ctrl-C is still handled by asyncio's
    default."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # non-main thread / unsupported platform: degrade to no signal handling
    return stop


def _log_shutdown_disposition() -> None:
    """停机点名与终态清单（t260916-29 要求①）：signal 时点在飞 agent 活动逐个点名
    （票/段/gen/attempt/已运行时长），shutdown 完成后按 outcome 汇总（在飞快照来自
    agent_activities 的注册表——只有走 worker_termination_guard 的四个长活动汇聚点
    在册；merge_check 等短活动不在册，见 README §8.3.1 已知边界）。"""
    inflight = inflight_stage_snapshot()
    grace = graceful_shutdown_timeout_sec()
    if inflight:
        for e in inflight:
            logging.info("停机点名：在飞 agent 活动 票 %s 段 %s gen %s attempt %s（已运行 %ds）",
                         e.get("ticket"), e.get("stage"), e.get("gen"), e.get("attempt"),
                         int(time.monotonic() - e.get("started_monotonic", time.monotonic())))
        logging.info("停机点名：在飞 agent 活动 %d 个，graceful_shutdown_timeout=%ss"
                     "——期内未收尾的将被取消并在票面点名「worker 被外部终止」", len(inflight), grace)
    else:
        logging.info("停机点名：无在飞 agent 活动（graceful_shutdown_timeout=%ss）", grace)


def _log_shutdown_outcome() -> None:
    outcomes = recent_stage_outcomes()
    if not outcomes:
        return
    finished = [e for e in outcomes if e.get("outcome") == "completed"]
    interrupted = [e for e in outcomes if e.get("outcome") != "completed"]
    logging.info("停机终态：本轮收尾 agent 活动 %d 个（完成 %d / 中断 %d）",
                 len(outcomes), len(finished), len(interrupted))
    for e in interrupted:
        logging.info("停机终态：被中断 票 %s 段 %s gen %s（outcome=%s）——票面将点名「worker 被外部终止」",
                     e.get("ticket"), e.get("stage"), e.get("gen"), e.get("outcome"))


async def _graceful_shutdown(workers, run_tasks, watch_task) -> None:
    """停机收尾（run_worker 的尾部原样抽出）：点名在飞 → 各 Worker.shutdown()
    （SDK 按 graceful_shutdown_timeout 等在飞 activity）→ 收 runner/watch 任务 →
    打终态清单。selfcheck_worker_graceful_stop 走同一函数，测的是真停机路径。"""
    _log_shutdown_disposition()
    await asyncio.gather(*(w.shutdown() for w in workers))
    if watch_task is not None:
        watch_task.cancel()
    try:
        await asyncio.gather(*run_tasks)
    except asyncio.CancelledError:
        pass
    _log_shutdown_outcome()
    logging.info("worker 已优雅停止")


def verify_signal_transport() -> list:
    """信号面运输自检（t260913-01，**窄效力**）：带 authorize 的 Signature 经默认转换器
    编码→带类型提示解码，逐 dataclass 字段断言存活。只兜「本进程的载荷类与转换器
    不兼容」（如新增字段类型不可序列化）这类带病上线；**不宣称**能测「进程陈旧」——
    旧进程根本不跑本函数，对端 worker 陈旧由 client 的 sign_face 指纹面在每次
    op=authorize 时实时鉴别（C1/C4 效力口径）。返回问题列表（空=通过）。"""
    problems: list = []
    try:
        import dataclasses as _dc

        from temporalio.converter import DefaultPayloadConverter

        from shared import (AUTHZ_SIGNAL_GATE_MARKER as _MARKER,
                            HumanAuthorization as _HA,
                            Signature as _SIG)
        auth = _HA(kind="protected_path", who="__boot__", scope=["integration/x"],
                   reason="boot 自检", expires=1)
        sig = _SIG(who="__boot__", gate=_MARKER, decision="approve", note="", authorize=auth)
        pc = DefaultPayloadConverter()
        out = pc.from_payload(pc.to_payload(sig), _SIG)
        for f in _dc.fields(_SIG):
            if not hasattr(out, f.name):
                problems.append("Signature.%s 解码丢失（转换器静默丢弃未知字段）" % f.name)
        got = getattr(out, "authorize", None)
        if got is None:
            problems.append("authorize 载荷解码后为空——sign 信号面会静默回落普通签字路径")
        else:
            for f in _dc.fields(_HA):
                if not hasattr(got, f.name):
                    problems.append("HumanAuthorization.%s 解码丢失" % f.name)
            if got.kind != auth.kind or list(got.scope) != list(auth.scope):
                problems.append("authorize 字段值漂移（kind/scope 不一致）")
        if str(getattr(out, "gate", "")) != _MARKER:
            problems.append("gate 标量字段未存活（authorize 丢失可见化依赖它）")
    except Exception as e:
        problems.append("运输自检异常：%s: %s" % (type(e).__name__, e))
    return problems


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
            **_worker_extra_kwargs(),  # t260916-29：显式宽限（缺省 1800s，env 可调）
        ))
    logging.info("worker polling queues: %s", ", ".join(configured_task_queues()))

    # Graceful stop: SIGTERM/SIGINT → stop event → _graceful_shutdown（宽限期内
    # 在跑 activity 收尾，超宽限才取消；见模块头 Graceful stop 与 README §8.3.1）
    stop = install_stop_signal_handlers()

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
    await _graceful_shutdown(workers, run_tasks, watch_task)


def main() -> None:
    args = parse_args()
    # 信号面运输自检（t260913-01）在 daemonize 之前跑：坏 worker 在前台 loud 死掉，
    # 不留一个静默丢字段的后台进程。窄效力声明见 verify_signal_transport。
    boot_problems = verify_signal_transport()
    if boot_problems:
        for p in boot_problems:
            print("worker boot 自检失败：%s" % p, file=sys.stderr)
        raise SystemExit("worker 代码与 sign 信号面不匹配，拒绝上线（authorize 会被"
                         "解码端静默丢弃；修代码或换兼容转换器后再启动）")
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
