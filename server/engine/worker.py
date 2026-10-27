"""Worker: registers workflows/activities onto a task queue and runs them.

The worker is the "muscle"; the server is the "skeleton and memory". If the
worker dies or the code restarts, workflow state and history stay safe on the
server.

How to start:
    # Foreground (debugging / watching logs)
    .venv/bin/python worker.py

    # Background (long-running)
    .venv/bin/python worker.py --daemon [--pidfile data/worker.pid] [--logfile data/worker.log]

Restart discipline (host report 260930 — the one rule that keeps a restart
deterministic):
    **After a restart, verify exactly ONE poller on the queue before pushing any
    ticket.** A duplicate poller is not a cosmetic problem: whichever worker claims
    a workflow task executes it, so a result produced while two builds poll the same
    queue cannot be attributed to a code version (observed: two "worker 起来了"
    lines 3-5s apart in this log, and a ticket face whose text/counts came from two
    different builds).
    The tools for that rule:
      * daemon starts are now guarded: if the pidfile names a LIVE process, the
        start is REFUSED (named stderr, exit code 2) instead of silently adding a
        second poller — a stale/absent pidfile is taken over normally;
      * `--replace` is the explicit takeover: TERM the old worker, wait (bounded)
        for its graceful exit, then start; a timeout is an error — this path never
        KILLs silently (an in-flight activity would be cut off mid-write);
      * foreground runs write no pidfile, so they cannot be guarded — they are for
        debugging only, and one that lands on a shared queue prints a loud warning
        naming the live daemon it is doubling;
      * poller count is a server-side fact: `describe_task_queue` (or the console's
        health row) is the check to run before pushing tickets.

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
    values fall back to the default). Fast idle exit (t261019-42): when the
    shutdown roll-call is empty on ALL faces (guard registry, owned spawns, AND
    the SDK-introspected running-activity count), shutdown is raced against env
    SANDBAR_WORKER_IDLE_SHUTDOWN_DEADLINE_SEC (default 10s; "0" disables) — an
    SDK-idle worker settles in well under a second, so a timeout is a named
    anomaly and the exit is forced instead of pinning the process for the full
    grace window. At shutdown the worker names every in-flight
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
import agent_runtime
from agent_activities import ALL_AGENT_ACTIVITIES, make_stage_activity
# t261004-32 (CL-1): the three thin concurrency-cap activities (decision
# logic lives in concurrency.py; this layer only enters the Temporal registry).
# t261027-10: also wires the liveness probe the dead-holder sweep uses.
from concurrency import CONCURRENCY_ACTIVITIES, configure_probe
from dsh_pin import dsh_face_payload, enforce_expected
from agent_activities import (inflight_stage_snapshot, owned_spawn_snapshot,
                              recent_stage_outcomes, reap_owned_spawns)
from shared import (NAMESPACE, POC_DIR, REPO_ROOT, TARGET_HOST, TASK_QUEUE,
                    configured_task_queues, pid_alive, read_pidfile_state)
from shared import write_worker_meta
from workflows import ALL_WORKFLOWS
from workflows_v2 import (ALL_WORKFLOWS_V2, PROJECT_TEMPLATE_PASSTHROUGH_MODULES,
                          PROJECT_TEMPLATE_STAGE_IDS)
import worker_registry

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

WATCH_INTERVAL_DEFAULT_SEC = 30.0  # production default: one poll round per 30s (settle-sensing delay cap ≈ one round)
WATCH_INTERVAL_MIN_SEC = 1.0       # floor clamp: guards against 0/negative busy-loop hammering describe

GRACEFUL_SHUTDOWN_ENV = "SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"
GRACEFUL_SHUTDOWN_DEFAULT_SEC = 1800.0  # 30min: covers the typical 10~40min agent stage tail; longer runs get the named-cancel path (README §8.3.1)


def activity_registered_name(fn) -> str:
    """活动在 temporalio 注册面的名字（不是 Python 函数名）：@activity.defn 可显式
    改名（如 make_stage_activity(name=段 id)），退役段与外置段取名可能不一致——
    判撞名必须按定义名。定义缺席（非 defn 对象）回落函数名，保证断言总有判据。"""
    d = getattr(fn, "__temporal_activity_definition", None)
    return getattr(d, "name", None) or getattr(fn, "__name__", repr(fn))


def compose_worker_activities(extra_stage_ids=()):
    """组装 worker 活动注册表并前置唯一性断言（KI-121，t260925-16）。

    为什么在 Worker(...) 构造前自己查：temporalio 注册期的撞名报错是裸
    ValueError（无点名、崩栈在第三方深处）。这里 fail-loud 点名「活动名＋
    两个来源模块」。正常路径下加载口（workflows_v2 合并期「活动名撞引擎注册面」
    检查）已拒收撞名模板——本断言是 Worker 构造前的最后一道防线，不信任上游。"""
    acts = (list(ALL_ACTIVITIES) + list(ALL_AGENT_ACTIVITIES)
            + list(CONCURRENCY_ACTIVITIES) + [
        make_stage_activity(s) for s in extra_stage_ids])
    seen = {}
    for a in acts:
        name = activity_registered_name(a)
        src = getattr(a, "__module__", "?")
        if name in seen:
            raise ValueError(
                "activity name collision (worker registration pre-assert, KI-121): "
                "activity %s is already registered by %s, and %s offers it again — "
                "external template segment ids must not share a name with a "
                "registered engine activity (same name = crash at registration, "
                "the worker cannot start); the load gate should have refused this "
                "at merge time, this is the last line of defense"
                % (name, seen[name], src))
        seen[name] = src
    return acts


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


IDLE_SHUTDOWN_ENV = "SANDBAR_WORKER_IDLE_SHUTDOWN_DEADLINE_SEC"
IDLE_SHUTDOWN_DEFAULT_SEC = 10.0


def idle_shutdown_deadline_sec(raw: "str | None" = None) -> float:
    """Deadline, in seconds, for the fast idle-exit path at shutdown (t261019-42).

    Used ONLY when the worker proves idle on ALL THREE faces: the guard registry
    (in-flight agent activities), the owned-spawn registry, and the SDK-side
    introspected running-activity count. An SDK-idle worker settles shutdown in
    well under a second (measured, t261019-42), so anything past this deadline is
    a named anomaly and the exit is forced instead of pinning the process for the
    full graceful window. Fault tolerance mirrors graceful_shutdown_timeout_sec:
    unset/blank/malformed/NaN/Inf/negative all fall back to the default; the
    explicit escape hatch is "0" (= the fast path is OFF, old behavior only)."""
    if raw is None:
        raw = os.environ.get(IDLE_SHUTDOWN_ENV) or ""
    raw = str(raw).strip()
    if not raw:
        return IDLE_SHUTDOWN_DEFAULT_SEC
    try:
        val = float(raw)
    except ValueError:
        return IDLE_SHUTDOWN_DEFAULT_SEC
    if val != val or val in (float("inf"), float("-inf")) or val < 0:
        return IDLE_SHUTDOWN_DEFAULT_SEC
    return val


def sdk_running_activity_count(worker) -> "int | None":
    """Best-effort count of activities the temporalio SDK itself still considers
    running, read from the worker's private state (t261019-42).

    The guard-registry roll-call only sees the four long agent activities that
    pass through worker_termination_guard; short activities (merge_check,
    inspection, lane, executor) are invisible to it — exactly the blindness that
    let a "nothing in flight" worker linger for the full 30-minute grace window
    (261019 incidents). The SDK's own running-activity set is the authoritative
    count. Returns None when the private shape is unreadable (SDK upgrade, wrong
    object) — callers MUST treat None as NOT idle (fail-safe: worst case is
    today's slow shutdown, never a wrong fast cut)."""
    try:
        acts = worker._activity_worker._running_activities
        return len(acts)
    except AttributeError:
        return None
    except Exception as e:  # noqa: BLE001 — any introspection surprise is a degrade, never a crash
        logging.debug("sdk running-activity introspection degraded: %s: %s",
                      type(e).__name__, e)
        return None


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


def _log_shutdown_disposition(workers=None) -> None:
    """Shutdown roll-call and final-outcome ledger (t260916-29 requirement 1):
    name every in-flight agent activity at signal time (ticket/stage/gen/attempt/
    elapsed), then summarize by outcome after shutdown completes (the in-flight
    snapshot comes from the agent_activities registry — only the four long
    activity chokepoints that pass through worker_termination_guard register;
    short activities like merge_check are not in it, a known boundary documented
    in README §8.3.1).
    t261019-42: the registry face is known-blind to short activities, so when the
    worker objects are available the SDK-side running-activity count is printed
    next to it — the log can no longer claim "no in-flight agent activities"
    while the SDK is waiting on something (the 261019 incident shape)."""
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
    # t261006-08 (R2): extend the roll-call to the child process groups this worker
    # still owns — the old roll-call had zero knowledge of this class (261006: a
    # whole inspection suite ran orphaned for another hour, unclaimed on ps).
    spawns = owned_spawn_snapshot()
    if spawns:
        for s in spawns:
            logging.info("shutdown roll-call: owned child process group tag=%s pid=%s (running %ds)",
                         s.get("tag") or "?", s.get("pid"),
                         int(time.monotonic() - s.get("started_monotonic", time.monotonic())))
        logging.info("shutdown roll-call: %d owned child process group(s) — reclaimed at the shutdown epilogue (see shutdown-reclaim receipt)",
                     len(spawns))
    else:
        logging.info("shutdown roll-call: 0 owned child process groups")
    # t261019-42: the SDK-side face. Printed whether or not the registry looks
    # empty; the fast-idle-exit gate reads the same helper.
    sdk_counts = [sdk_running_activity_count(w) for w in (workers or [])]
    if any(c is None for c in sdk_counts) or not sdk_counts:
        if workers:
            logging.info("shutdown roll-call: sdk_running_activities=? "
                         "(introspection unavailable — treated as NOT idle, "
                         "fail-safe)")
        sdk_total = None
    else:
        sdk_total = sum(sdk_counts)
        logging.info("shutdown roll-call: sdk_running_activities=%d", sdk_total)
    return sdk_total


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


CONSOLE_BOOT_ENV = "SANDBAR_CONSOLE_BOOT"  # t261009-55: set by the console at spawn


def merge_worker_meta_extras(meta_path: "str | None", extras: dict) -> bool:
    """t261009-55: merge console_boot / polling into this worker's ownership meta.

    WHY a worker-owned merge instead of new shared.write_worker_meta kwargs: the
    meta schema lives in shared.py, which is NOT in this ticket's write set — so
    the worker post-processes the file it just (best-effort) wrote: read the meta,
    verify it still names OUR pid, add the extras, atomically replace the file
    (tmp + os.replace, same discipline as shared.write_worker_meta).

    Guards (borrow-fault-mode table, t261005-03):
    - pid guard: after a takeover the meta may belong to the replacement; a pid
      mismatch means we never clobber the new owner's fingerprint.
    - draining guard: a meta already in state='draining' is never re-touched — a
      late refresher tick must not resurrect a released slot as polling.
    Best-effort like the base write: any failure logs once (debug) and returns
    False; the ensure side treats a boot-less meta under the pre-t261009-55 rules
    (named transitional limitation, plan R6)."""
    if not meta_path or not isinstance(extras, dict) or not extras:
        return False
    try:
        import json as _json
        import shared as _shared
        meta, _state, _detail = _shared.read_worker_meta_state(meta_path)
        if not isinstance(meta, dict) or int(meta.get("pid") or 0) != os.getpid():
            return False
        if str(meta.get("state") or "") == _shared.WORKER_META_STATE_DRAINING:
            return False
        merged = dict(meta)
        merged.update(extras)
        p = pathlib.Path(meta_path)
        tmp = p.with_name("%s.tmp.merge.%d" % (p.name, os.getpid()))
        tmp.write_text(_json.dumps(merged, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
        return True
    except Exception as e:  # noqa: BLE001 — the extras are observability, never a gate
        logging.debug("meta extras merge skipped (%s: %s) meta=%s",
                      type(e).__name__, e, meta_path)
        return False


# t261019-24: consecutive stale ticks required before a self-stop. Two ticks mean the
# worst case a stale worker can still claim new work is ~2x watch_interval after the
# code change lands on disk — bounded, and named in the self-stop log line so a
# residual stale claim is diagnosable rather than surprising.
STALE_TURNOVER_TICKS = 2


def stale_modules_for_self(mtime_fn=None, started_at=None, repo_root=None) -> list:
    """Stale worker-loaded modules for THIS process (t261019-24).

    Thin, injectable wrapper over shared.worker_code_stamp — the SAME pure function
    the gate receipt uses, so this check never re-implements (and can never weaken)
    the stamp judgment: stale = module file mtime newer than this process's start
    baseline; unreadable/malformed mtime is never stale (conservative, never
    over-reports). verify_lane is excluded by the stamp itself (gate subprocess role).

    Returns the stale module-name list; an empty list means the process is current.
    All inputs are injectable so the unit tests pin every shape without touching disk.
    Raises whatever shared.worker_code_stamp raises (the caller owns the retry)."""
    import shared as _shared
    stamp = _shared.worker_code_stamp(mtime_fn=mtime_fn, started_at=started_at,
                                      pid=os.getpid(), repo_root=repo_root)
    return [str(x) for x in (stamp.get("stale") or [])]


def record_self_stop(meta_path: "str | None", reason: str, stale: list) -> bool:
    """Persist WHY this worker stopped itself (t261019-24): a ``self_stop`` extra in
    the ownership meta. The loud log line is the human copy; this is the machine-
    readable postmortem face — see keep_meta_on_self_stop for why the meta file must
    survive the exit for the record to be readable. Best-effort, never a gate."""
    ok = merge_worker_meta_extras(meta_path, {
        "self_stop": {"reason": str(reason), "stale": [str(x) for x in (stale or [])],
                      "ts": int(time.time())},
    })
    if not ok:
        logging.warning("self-stop: meta extra write failed (meta=%s) — the log line "
                        "above is the surviving record", meta_path)
    return ok


def keep_meta_on_self_stop(meta_path: "str | None") -> bool:
    """Exit-time guard (t261019-24, review comment 1): main's finally unlinks our own
    meta on a normal exit — which a self-stop IS, so the self_stop record would be
    erased before anyone reads it. When the meta carries a self_stop marker (and still
    names OUR pid — a taken-over meta is never touched), keep the file: a dead-pid meta
    is read as such by the ensure side, and the supervisor's replacement overwrites it
    through its own ownership write. True = keep the meta (caller must not unlink)."""
    if not meta_path:
        return False
    try:
        import shared as _shared
        meta, state, _detail = _shared.read_worker_meta_state(meta_path)
        if state != "ok" or not isinstance(meta, dict):
            return False
        if int(meta.get("pid") or 0) != os.getpid():
            return False
        return bool(meta.get("self_stop"))
    except Exception:  # noqa: BLE001 — the keep-decision must never break the exit path
        return False


def console_boot_id() -> str:
    """This worker's console boot generation (t261009-55): whatever the console
    already knows about itself (supervisor pid + process start ms), passed at
    spawn via SANDBAR_CONSOLE_BOOT. Empty when unset (foreground runs /
    pre-upgrade consoles) — a boot-less meta keeps the pre-t261009-55 ensure
    rules (named transitional limitation, plan R6)."""
    return str(os.environ.get(CONSOLE_BOOT_ENV) or "").strip()


def mark_meta_draining(meta_path: "str | None") -> bool:
    """Rewrite this worker's ownership meta with state='draining' (t261005-03).

    Called at the graceful-shutdown entry, BEFORE the pollers stop: from that instant
    the single-poller guard (guard_single_worker) and the console's ensure side must
    treat this pid as a released slot, not a live owner — otherwise a RUNNING ticket
    sits with zero pollers for up to the whole graceful drain (261005: 15 minutes,
    two lanes).

    Ownership-guarded: only writes when the meta names OUR pid — after a takeover the
    pidfile/meta may already belong to the replacement, and clobbering it would erase
    the new owner's fingerprint. Best-effort: a write failure returns False and the
    caller logs; the read face (clause B) names the no-poller cause for the residual
    window this leaves (named known boundary, never silently absorbed)."""
    if not meta_path:
        return False
    try:
        import shared as _shared
        meta, _state, _detail = _shared.read_worker_meta_state(meta_path)
        if int((meta or {}).get("pid") or 0) != os.getpid():
            logging.info("drain handover: meta (%s) already has a new owner "
                         "(pid=%s != this process %d) — not rewritten",
                         meta_path, (meta or {}).get("pid"), os.getpid())
            return False
        # t261019-24: a self-stop reason recorded before the drain must survive the
        # rewrite (write_worker_meta builds a fixed payload and would drop it) —
        # carry it over, pid-guarded, or the postmortem face is erased at exit.
        self_stop = (meta or {}).get("self_stop")
        _shared.write_worker_meta(
            meta_path, repo_root=str((meta or {}).get("repo_root") or REPO_ROOT),
            pid=os.getpid(), state=_shared.WORKER_META_STATE_DRAINING)
        if self_stop is not None:
            meta2, _st2, _dt2 = _shared.read_worker_meta_state(meta_path)
            if isinstance(meta2, dict) and int(meta2.get("pid") or 0) == os.getpid():
                merged = dict(meta2)
                merged["self_stop"] = self_stop
                p = pathlib.Path(meta_path)
                tmp = p.with_name("%s.tmp.merge.%d" % (p.name, os.getpid()))
                tmp.write_text(_shared._json.dumps(merged, ensure_ascii=False), "utf-8")
                os.replace(tmp, p)
        logging.info("drain handover: meta state=draining written (pid=%d meta=%s) — "
                     "guard/ensure may admit the replacement at once",
                     os.getpid(), meta_path)
        return True
    except Exception as e:  # noqa: BLE001 — the hand-over marker never blocks shutdown
        logging.warning("drain handover: writing draining to meta (%s) failed (%s: %s) "
                        "— the residual window is caught by the named read degrade "
                        "(kind=no_poller)", meta_path, type(e).__name__, e)
        return False


async def _graceful_shutdown(workers, run_tasks, watch_task,
                             meta_path: "str | None" = None,
                             stamp_task: "asyncio.Task | None" = None) -> None:
    """Shutdown epilogue (extracted verbatim from run_worker's tail): hand over the
    slot (meta state=draining, t261005-03) → name the in-flight activities →
    Worker.shutdown() per worker (the SDK waits graceful_shutdown_timeout for the
    in-flight activities) → reap the runner/watch tasks → log the outcome ledger.
    selfcheck_worker_graceful_stop drives the same real shutdown path.

    t261019-42 fast idle exit: when the roll-call is empty on ALL THREE faces
    (guard registry, owned spawns, SDK-introspected running activities), the
    shutdown phase is raced against idle_shutdown_deadline_sec(). A proven-idle
    worker settles in well under a second (measured), so expiry is a named
    anomaly: the pending shutdown wait is cancelled and the epilogue (outcome
    ledger, spawn reap) still runs — the process exits instead of pinning for
    the full grace window. When NOT proven idle, the unbounded graceful path
    runs verbatim: full grace window, SDK grace-expiry cancel, and the typed
    "worker terminated externally" classification all unchanged."""
    mark_meta_draining(meta_path)
    inflight_idle = not inflight_stage_snapshot()
    spawns_idle = not owned_spawn_snapshot()
    sdk_total = _log_shutdown_disposition(workers)
    idle = inflight_idle and spawns_idle and sdk_total == 0
    shutdown_phase = asyncio.gather(*(w.shutdown() for w in workers))
    if idle:
        deadline = idle_shutdown_deadline_sec()
        if deadline > 0:
            logging.info("fast idle exit armed: registry empty, spawns empty, "
                         "sdk_running_activities=0 — shutdown must settle in %ss "
                         "(env %s)", deadline, IDLE_SHUTDOWN_ENV)
            try:
                await asyncio.wait_for(shutdown_phase, timeout=deadline)
            except asyncio.TimeoutError:
                logging.warning("fast idle exit fired: worker proven idle on all "
                                "three faces yet shutdown did not settle in %ss "
                                "(expected <1s) — forcing exit instead of pinning "
                                "for the full graceful window (t261019-42); the "
                                "roll-call above names every face we could see",
                                deadline)
        else:
            await shutdown_phase  # deadline "0": fast path explicitly off
    else:
        await shutdown_phase
    if watch_task is not None:
        watch_task.cancel()
    if stamp_task is not None:
        stamp_task.cancel()
    try:
        await asyncio.gather(*run_tasks)
    except asyncio.CancelledError:
        pass
    _log_shutdown_outcome()
    # t261006-08 (R1+R3): after Worker.shutdown() returns — BOTH the graceful drain
    # and the grace-expiry path funnel through this epilogue (once the SDK gives up
    # at expiry, only this code still runs) — reclaim every process group this
    # worker still owns and emit the receipt. The receipt line is the handover's
    # mechanical check face: `shutdown-reclaim receipt:` with leftover=[] means
    # "no process left behind for a failed/cancelled activity", no ps archaeology.
    receipt = await reap_owned_spawns()
    logging.info("shutdown-reclaim receipt: owned=%d reclaimed=%d leftover=%s",
                 receipt["owned"], receipt["reclaimed"], receipt["leftover"])
    if receipt["leftover"]:
        logging.warning("shutdown-reclaim: pid=%s survived even KILL (see the named "
                        "group-escape boundary on reap_spawn_group) — not silently "
                        "absorbed, operator follow-up needed",
                        receipt["leftover"])
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
            problems.append("authorize payload is empty after decode — the sign "
                            "signal face would silently fall back to the plain "
                            "signature path")
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
    p.add_argument("--replace", action="store_true",
                   help="显式接管：pidfile 里那颗 worker 还活着时，先 TERM 它、有界等待其"
                        "优雅退出再起本进程（超时报错，绝不静默 KILL）。缺省=有活 worker"
                        "就拒绝启动（同队列并存两颗会让结果不可归因到代码版本）")
    return p.parse_args()


#: 拒绝启动的退出码（同队列已有活 worker / --replace 超时 / 不代杀他人进程）。
#: 与场景「环境红=2」同档：这是运维面可机器识别的「没起来」，不是崩溃。
WORKER_REFUSED_EXIT = 2

#: --replace 等旧 worker 优雅退出的上界（秒）。到点报错、绝不静默 KILL：
#: 在飞 agent 活动被硬切会把票面带病（t260916-29 的停机宽限语义）。
REPLACE_WAIT_SEC = 60.0
REPLACE_POLL_SEC = 0.2


def _meta_of(pidfile: str) -> dict:
    """读同槽旁车 meta（<pidfile>.meta）——只读、失败即空 dict（fail-open 读侧）。"""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import shared as _shared
        meta, _state, _detail = _shared.read_worker_meta_state(pidfile + ".meta")
        return dict(meta or {})
    except Exception:  # noqa: BLE001——旁车只是诊断面，读不到不拦启动
        return {}


def guard_single_worker(pidfile: str, replace: bool = False) -> "str | None":
    """起 daemon worker **之前**的唯一性守卫（宿主 260930：重启必须确定）。

    返回 None=放行（可启动）；返回字符串=拒绝原因（调用方 stderr 具名 + 非零退出）。

    四态 × 两档：
      · absent / 陈旧 / 畸形 → 放行，并把「接管」写进日志（留痕，不静默）；
      · 活 pid 且未给 --replace → 拒绝启动（点名 pid/起于/pidfile/repo_root + 两条出路）；
      · 活 pid 且给了 --replace → 先 TERM、**有界等待**其优雅退出；超时报错（绝不 KILL）；
        旁车 meta 指向**别的仓** → 直接拒绝（不代杀他人进程）。
    为什么必须（宿主实报）：两颗 worker 同队列并存数秒时，谁领到 workflow task 就谁执行，
    票面结果于是不可归因到某个代码版本；pidfile 是单槽，写入即「最后一次覆盖」，
    没有这道守卫第二个启动只会静默改写它。

    已知边界（**具名不静默**）：①pid 被系统回收后可能指向一个无关进程 ⇒ 本守卫会保守地
    拒绝启动并在文案里给 pid/时间/旁车归属（人可核对，绝不代杀）；②前台档不写 pidfile ⇒
    不在本守卫射程内，改由 `foreground_shared_queue_warning` 响亮提示；③本机 `ps` 常被
    沙箱拒，故按 pidfile+kill(0) 判定，不做命令行归属核对。"""
    st = read_pidfile_state(pidfile)
    log = logging.getLogger()
    if st["state"] != "live":
        if st["state"] == "absent":
            log.info("pidfile 不在（%s）——首启放行", pidfile)
        else:
            log.warning("pidfile 陈旧已接管：%s（pidfile=%s）——旧进程不在位，本进程接管该槽",
                        st["detail"], pidfile)
        return None
    pid = int(st["pid"])
    meta = _meta_of(pidfile)
    # t261005-03: the slot state decides, not pid liveness. A draining worker is alive
    # but polls NOTHING — treating its pid as a live owner left RUNNING tickets with
    # zero pollers for up to the whole graceful drain (261005). Only an exact match
    # (meta state='draining' AND meta.pid == pidfile pid) opens the slot; anything
    # else (meta missing/malformed/foreign/serving) keeps today's conservative refusal.
    if str(meta.get("state") or "") == "draining" \
            and int(meta.get("pid") or 0) == pid:
        log.warning("pidfile worker (pid=%d, pidfile=%s) is draining (polling stopped, "
                    "in-flight activities being finished) — the slot is released, this "
                    "process takes over the queue slot; the old process finishes its own "
                    "exit (t261005-03)", pid, pidfile)
        return None
    started = ""
    if meta.get("ts"):
        try:
            started = "，起于 %s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.localtime(int(meta["ts"])))
        except (TypeError, ValueError, OSError):
            started = ""
    elif st.get("mtime"):
        started = "，pidfile 落于 %s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                                     time.localtime(st["mtime"]))
    where = str(meta.get("repo_root") or "（旁车 meta 缺失，归属未知）")
    if not replace:
        return ("同队列已有**活** worker（pid=%d%s；pidfile=%s；repo_root=%s）——拒绝启动，"
                "绝不在同一队列上并存第二颗（谁领到 workflow task 就谁执行 ⇒ 结果不可归因到"
                "代码版本）。出路：① 优雅停旧的：kill -TERM %d，等它退出后重起；"
                "② 显式替换：本命令加 --replace（先 TERM 旧 worker、有界等待其优雅退出再起，"
                "超时报错不静默 KILL）"
                % (pid, started, pidfile, where, pid))
    own_root = os.path.realpath(str(pathlib.Path(__file__).resolve().parents[2]))
    if meta.get("repo_root") and os.path.realpath(str(meta["repo_root"])) != own_root:
        return ("--replace refused: the pidfile sidecar meta points at another repo "
                "(repo_root=%s, this repo=%s) — this process will not kill another "
                "repo's process; handle it manually (check pid=%d in %s)"
                % (where, own_root, pid, pidfile))
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log.warning("--replace：旧 worker pid=%d 在发信号前已退出——直接接管", pid)
        return None
    except OSError as e:
        return ("--replace failed: error sending SIGTERM to old worker pid=%d "
                "(%s: %s) — no new process was started; handle it manually"
                % (pid, type(e).__name__, e))
    t0 = time.time()
    while time.time() - t0 < REPLACE_WAIT_SEC:
        if not pid_alive(pid):
            log.info("--replace：旧 worker pid=%d 已优雅退出（等待 %.1fs）——本进程接管该槽",
                     pid, time.time() - t0)
            return None
        time.sleep(REPLACE_POLL_SEC)
    return ("--replace timed out: old worker pid=%d did not exit within %.0fs — "
            "NO KILL (hard-cutting in-flight agent activities would leave tickets "
            "in a half-done state); no new process was started this time. Handle it "
            "manually: check data/worker.log for the shutdown roll-call to see "
            "in-flight activities, or kill -TERM %d and start again"
            % (pid, REPLACE_WAIT_SEC, pid))


def foreground_shared_queue_warning(args: argparse.Namespace) -> str:
    """前台启动的**响亮**提示：前台不写 pidfile ⇒ 不受唯一性守卫保护。

    若这个前台 worker 会落在共享队列（默认 sandbar）上、而 pidfile 里那颗 daemon worker
    还活着，就是宿主 260930 实报里「同一队列两颗 poller 并存」的另一种形态——
    大声说出来（不拒绝：前台是调试面，测试栈也用它，拒绝会误伤）。"""
    if args.daemon:
        return ""
    try:
        queues = set(configured_task_queues())
    except Exception:  # noqa: BLE001——队列名取不到不是拦点
        return ""
    if TASK_QUEUE not in queues:
        return ""
    st = read_pidfile_state(args.pidfile)
    if st["state"] == "live":
        return ("前台启动不写 pidfile，**不受唯一性守卫保护**：pidfile（%s）里那颗 worker"
                "（pid=%d）仍活着，且本进程要落在同一个共享队列（%s）上 ⇒ 此刻同队列会有两个"
                "poller，票面结果不可归因到代码版本。调试请继续（前台档的已知代价），"
                "但要推票请先 kill -TERM %d，或改用 --daemon（后者有守卫）"
                % (args.pidfile, int(st["pid"]), TASK_QUEUE, int(st["pid"])))
    # pidfile 陈旧/缺席的前台档同样危险（宿主 260930 窗口一实测形态）：pidfile 是 console
    # supervisor 判「worker 在不在」的唯一依据，读成死的 ⇒ 它的 keepalive（缺省 5s）会另起
    # 一颗 daemon ⇒ 又是两颗 poller。响亮说出来（不拒绝：前台是调试面）。
    return ("前台启动不写 pidfile，而 pidfile（%s）%s：console supervisor（keepalive 缺省 "
            "5s）会据此判定「worker 不在位」并**另起一颗** ⇒ 本进程会与它同队列并存，"
            "票面结果不可归因到代码版本。若这是常驻形态请改用 --daemon（写 pidfile、有守卫）；"
            "调试用请只留一个前台进程并盯着 poller 面"
            % (args.pidfile, "内容非数字" if st["state"] == "malformed"
               else "指向已不在的 pid=%s" % st["pid"] if st["state"] == "stale"
               else "不在"))


def daemonize(pidfile: str, logfile: str, replace: bool = False) -> bool:
    """Single-fork detach from the session. Returns True if this is the parent
    process (the caller should exit immediately).

    重启唯一性（宿主 260930）：fork **之前**先过 `guard_single_worker`——pidfile 里是活
    进程就拒绝启动（除非显式 --replace，那条路先 TERM 后**有界等待**优雅退出，超时报错、
    绝不 KILL）。守卫不通过时抛 SystemExit(WORKER_REFUSED_EXIT)：**不 fork、不改 pidfile**，
    门口就把「同队列并存两颗」拦住。"""
    refusal = guard_single_worker(pidfile, replace=replace)
    if refusal:
        print("worker 拒绝启动：%s" % refusal, file=sys.stderr)
        raise SystemExit(WORKER_REFUSED_EXIT)
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


def process_stale_tick(ticks: int, stale: list, meta_path: "str | None",
                       watch_interval: float, stop_event) -> int:
    """One tick of the code-stamp watch (t261019-24), split out of run_worker's async
    loop so the unit tests can drive every shape without Temporal. ``ticks`` is the
    previous consecutive-stale count; ``stale`` the stamp verdict for THIS tick.
    Returns the new count. When the count reaches STALE_TURNOVER_TICKS the self-stop
    fires: loud bounded-worst-case log line, self_stop meta record, then the caller's
    stop event (the SAME event SIGTERM sets — the drain path is the existing graceful
    one)."""
    if not stale:
        return 0
    ticks = int(ticks) + 1
    if ticks < STALE_TURNOVER_TICKS:
        return ticks
    logging.info(
        "self-stop: code stamp stale on %d consecutive tick(s): %s — draining "
        "in-flight activities (bounded by graceful_shutdown_timeout=%ss) then "
        "exiting; the console supervisor starts a fresh worker. Worst case this "
        "process could still claim work for ~%dx watch_interval (%.0fs) after the "
        "code change landed (t261019-24)",
        ticks, ",".join(stale), graceful_shutdown_timeout_sec(),
        STALE_TURNOVER_TICKS, STALE_TURNOVER_TICKS * watch_interval)
    record_self_stop(meta_path, "stale-code", stale)
    stop_event.set()
    return ticks


async def run_worker(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    # Write the ownership fingerprint early (KI-033): before Client.connect, so
    # the ensure side can read the ownership as soon as the worker is alive.
    # Best-effort — a write failure must not block startup (the ensure side
    # tolerates a missing meta as unknown).
    meta_path = worker_meta_path(args)
    # dsh 版本面（t260916-24）：启动即算即记——本 worker 用的 dsh 版本/来源/路径
    # （host=实证 `<dsh> --version`；docker=镜像 tag 提取，tag-derived 非实证）。
    # 期望版本不符（SANDBAR_DSH_EXPECTED_VERSION）→ 响亮 warning；
    # SANDBAR_DSH_STRICT=1 → enforce_expected 在此 raise 拒绝上线（硬闸）。
    # 坏 SANDBAR_AGENT_CMD → dsh_face_payload 响亮抛（对齐旧 DSH_CMD import 时炸的
    # 行为，文案带旋钮名）。
    face = dsh_face_payload(mode=agent_runtime.runtime_mode(),
                            default_image=agent_runtime.DEFAULT_AGENT_IMAGE)
    face_note = enforce_expected(face)
    if meta_path:
        payload = write_worker_meta(meta_path, repo_root=str(REPO_ROOT), pid=os.getpid(),
                                    dsh_face=face)
        logging.info("worker 归属指纹：repo_root=%s pid=%d meta=%s",
                     payload.get("repo_root"), payload.get("pid"), meta_path)
        # t261009-55: boot generation + polling fact ride on the same meta (worker-
        # owned merge, shared.py untouched). console_boot lets a RESTARTED console
        # admit a substitute in one ensure tick without waiting for this worker to
        # reach state='draining'; polling lets the ensure name and repair an alive
        # worker that shed its poller.
        _extras: dict = {"polling": True}
        _boot = console_boot_id()
        if _boot:
            _extras["console_boot"] = _boot
        if merge_worker_meta_extras(meta_path, _extras):
            logging.info("worker meta extras merged: console_boot=%s polling=true (meta=%s)",
                         _boot or "(unset)", meta_path)
        else:
            logging.warning("worker meta extras merge failed — the ensure keeps the "
                            "pre-t261009-55 rules for this worker (meta=%s)", meta_path)
    else:
        logging.info("worker 归属指纹：前台模式不落 meta（repo_root=%s）", REPO_ROOT)
    if face["expected_state"] == "mismatch":
        logging.warning("%s（已随 worker meta 落盘可查：%s）", face_note,
                        meta_path or "前台模式无 meta")
    else:
        logging.info("%s", face_note)
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)

    # t261027-10 (KI-378 ①): wire the dead-holder sweep's liveness probe to
    # THIS worker's client. The worker process owns both the Temporal client
    # and write access to the projects root, so the sweep runs here — the
    # ending caller's (possibly sandbox-locked) file access never decides
    # whether a terminal ticket's slot comes back. Probe contract (see
    # concurrency.configure_probe): async (tid) -> (kind, note), kind
    # ""=answered, "not_found"=workflow gone, else an error name. The sweep
    # itself bounds every probe (PROBE_TIMEOUT_S) and fails closed on unknown.
    def _temporal_probe(c):
        # Not-found recognition mirrors client._is_not_found_exc (narrow
        # reading, class-name MRO + text fallback; no SDK class import — the
        # same KI-025 stance: a misread "gone" is exactly the false claim this
        # probe must never make, because the sweep DROPS on not_found).
        def _is_not_found(e: BaseException) -> bool:
            return any(t.__name__ in ("WorkflowNotFoundError",
                                      "NotFoundFailureError", "NotFoundFailure")
                       for t in type(e).__mro__) \
                or "not found" in str(e).lower()

        async def probe_one(tid):
            try:
                await c.get_workflow_handle(str(tid)).describe()
                return "", ""
            except Exception as e:  # noqa: BLE001 - classified, named upstream
                if _is_not_found(e):
                    return "not_found", "workflow gone (not_found)"
                return type(e).__name__, str(e)[:160]

        return probe_one

    configure_probe(_temporal_probe(client))
    logging.info("concurrency liveness probe wired (t261027-10 sweep arm)")
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
    # D3（t260924-04 第 2 轮打回）：项目外置模板模块名注入 sandbox passthrough——
    # temporalio workflow sandbox 在 validate/执行期按模块名 re-import 定义模块，
    # 外置模块经 importlib 按名装载（sandbar_ext_<key>_<stem>），不在任何 import
    # path 上，不注入即 ModuleNotFoundError 崩工人。加载器侧另有 sandbox 预校验
    # （project_templates._sandbox_validate）：校验失败的模板根本进不了本注册表，
    # 此注入只服务「通过了预校验的好模板」——双层防线，坏模板永不炸工人进程。
    # 无外置模板 = 缺省 runner，零行为变化。
    _workflow_runner = None
    if PROJECT_TEMPLATE_PASSTHROUGH_MODULES:
        # D4（t260924-04 第 3 轮打回）：temporalio 1.18.2 公开类名=SandboxRestrictions
        # （workflow_sandbox 导出面：RestrictedWorkflowAccessError/SandboxMatcher/
        #  SandboxRestrictions/SandboxedWorkflowRunner；with_passthrough_modules 在
        #  SandboxRestrictions 上）。
        from temporalio.worker.workflow_sandbox import (
            SandboxedWorkflowRunner,
            SandboxRestrictions,
        )
        _workflow_runner = SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                *sorted(PROJECT_TEMPLATE_PASSTHROUGH_MODULES)))
        logging.info("project template modules passthrough: %s",
                     sorted(PROJECT_TEMPLATE_PASSTHROUGH_MODULES))
    for _q in configured_task_queues():
        _extra = {}
        if _workflow_runner is not None:
            _extra["workflow_runner"] = _workflow_runner
        workers.append(Worker(
            client,
            task_queue=_q,
            workflows=ALL_WORKFLOWS + ALL_WORKFLOWS_V2,
            activities=compose_worker_activities(PROJECT_TEMPLATE_STAGE_IDS),
            **_extra,
            **_worker_extra_kwargs(),  # t260916-29：显式宽限（缺省 1800s，env 可调）
        ))
    # Registration fingerprint face (t261004-44, KI-197 way out (2)): which workflow
    # classes THIS worker knows, written to a file deliver reads pre-flight — class
    # absent = named refusal, never an unbounded wait. Best-effort: a write failure
    # logs loudly and never blocks startup (deliver degrades to the bounded wait).
    # KI-227 (t261008-29): the file now also records the ACTIVITY registry this
    # process actually registered (the exact thing that went stale on 261008) and
    # the code identity it loaded (HEAD sha + dirty flag) — staleness becomes a
    # file read, not a stack trace.
    try:
        _acts = sorted({activity_registered_name(a)
                        for a in compose_worker_activities(PROJECT_TEMPLATE_STAGE_IDS)})
        _identity = worker_registry.code_identity(str(POC_DIR))
        if _identity.get("error"):
            logging.warning("worker code identity probe degraded (%s) — "
                            "code_fingerprint written empty (honest unknown, never a made-up sha)",
                            _identity["error"])
        reg_doc = worker_registry.write_fingerprint(
            worker_registry.fingerprint_path(),
            [getattr(c, "__name__", repr(c)) for c in (ALL_WORKFLOWS + ALL_WORKFLOWS_V2)],
            pid=os.getpid(), now_ms=int(time.time() * 1000),
            code_fingerprint=str(_identity.get("sha") or ""),
            activity_names=_acts,
            code_dirty=bool(_identity.get("dirty")))
        logging.info("worker registration fingerprint written: %s (registered=%d, pid=%d, "
                     "activities=%d, code=%s%s)",
                     worker_registry.fingerprint_path(), len(reg_doc["registered"]), os.getpid(),
                     len(reg_doc["activities"]),
                     reg_doc["code_fingerprint"][:12] or "(unknown)",
                     " dirty" if reg_doc["code_dirty"] else "")
    except Exception as e:  # noqa: BLE001 — the fingerprint is an enabler, not a gate: a write failure never blocks startup
        logging.warning("worker registration fingerprint write failed (deliver degrades to the bounded wait): %s: %s",
                        type(e).__name__, e)
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

    # t261009-55: keep the meta's `polling` fact honest — one refresh per watch
    # interval. polling = every poller task still alive (a crashed/exited run task
    # means this worker has shed its poller while the process lives; the ensure
    # names that state and repairs it). Draining-guarded + pid-guarded in the
    # merge, so a late tick can never resurrect a released slot.
    async def _meta_refresher() -> None:
        while not stop.is_set():
            await asyncio.sleep(watch_interval)
            polling = bool(run_tasks) and all(not t.done() for t in run_tasks)
            merge_worker_meta_extras(meta_path, {"polling": polling})

    meta_refresher_task: "asyncio.Task | None" = None
    if meta_path:
        meta_refresher_task = asyncio.create_task(_meta_refresher())

    # t261019-24: self-turnover on stale code. A worker imports the engine once at
    # startup; after a fix lands, a stale worker keeps taking new work as if it were
    # current (the 261019 mixed-fleet incidents). Consequence, drain-first: when the
    # shared code stamp names stale worker-loaded modules on STALE_TURNOVER_TICKS
    # consecutive ticks, record the reason and set the SAME stop event SIGTERM uses —
    # the existing _graceful_shutdown then stops the pollers from claiming, drains
    # in-flight activities within graceful_shutdown_timeout, and the console
    # supervisor's keepalive replaces the process. This code never starts or signals
    # any other process, and never cancels an in-flight activity to speed things up
    # (the graceful cap stays t261019-19's subject). Detection stays owned by
    # shared.worker_code_stamp / engine_ops drift — this only consumes their verdict.
    async def _code_stamp_watch() -> None:
        stale_ticks = 0
        while not stop.is_set():
            await asyncio.sleep(watch_interval)
            try:
                stale = stale_modules_for_self()
            except Exception as e:  # noqa: BLE001 — a stamp failure must not kill the worker; retry next tick
                logging.warning("code stamp watch: stamp computation failed (next "
                                "tick retries): %s: %s", type(e).__name__, e)
                stale_ticks = 0
                continue
            stale_ticks = process_stale_tick(stale_ticks, stale, meta_path,
                                             watch_interval, stop)

    stamp_task: "asyncio.Task | None" = asyncio.create_task(_code_stamp_watch())
    await stop.wait()
    if meta_refresher_task is not None:
        meta_refresher_task.cancel()
        try:
            await meta_refresher_task
        except asyncio.CancelledError:
            pass
    await _graceful_shutdown(workers, run_tasks, watch_task, meta_path=meta_path,
                             stamp_task=stamp_task)


def main() -> None:
    args = parse_args()
    # 260930 code_stamp：在**进程入口**钉真·启动时刻（此处非沙箱，允许读墙钟）。
    # 为什么必须在这里钉：shared 的惰性兜底只能给「首次访问时刻」（活动里），那么
    # 「worker 启动后、首次取 stamp 前落盘的改动」永远判不出 stale——正是 t260928-01
    # （`>3000s` 旧码值）与 t260930-01（deadman 中文）两次实案的形态。
    # 放 daemonize **之前**：父进程（daemon 化后立即返回的那个）也钉同一值，
    # 子进程继承的模块状态不受影响（子进程自己会在自己的 main 里钉）。
    try:
        import shared as _shared
        _shared.note_process_start()
        # 261019: pin the delivery ledger root here (this file is NOT sandboxed) so the
        # in-workflow close-out guard never reads the environment.
        _shared.note_delivery_ledger_dir(os.environ.get("SANDBAR_DELIVERY_LEDGER_DIR", ""))
    except Exception:  # noqa: BLE001——身份面故障绝不拦 worker 启动
        pass
    # 信号面运输自检（t260913-01）在 daemonize 之前跑：坏 worker 在前台 loud 死掉，
    # 不留一个静默丢字段的后台进程。窄效力声明见 verify_signal_transport。
    boot_problems = verify_signal_transport()
    if boot_problems:
        for p in boot_problems:
            print("worker boot 自检失败：%s" % p, file=sys.stderr)
        raise SystemExit("worker 代码与 sign 信号面不匹配，拒绝上线（authorize 会被"
                         "解码端静默丢弃；修代码或换兼容转换器后再启动）")
    if not args.daemon:
        # 前台档：不写 pidfile ⇒ 不受唯一性守卫保护；落在共享队列且已有活 daemon 时
        # 响亮点名（宿主 260930 实报的「同队列两颗 poller」前台形态）。不拒绝：前台是
        # 调试面，测试栈也用它（各测试用私有队列+私有 bench，不触发本提示）。
        _warn = foreground_shared_queue_warning(args)
        if _warn:
            print("⚠️  worker 唯一性提示：%s" % _warn, file=sys.stderr, flush=True)
    if args.daemon:
        is_parent = daemonize(args.pidfile, args.logfile, replace=args.replace)
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
        # t261005-03: ownership-guarded — after a takeover the meta may already
        # belong to the replacement worker; only unlink when it still names OUR pid
        # (unconditional unlink used to erase the new owner's fingerprint).
        # t261019-24: but a self-stop meta is the postmortem face — keeping it (with
        # the self_stop reason) is the point; see keep_meta_on_self_stop.
        if meta_path and not keep_meta_on_self_stop(meta_path):
            try:
                import shared as _shared
                meta, _st, _dt = _shared.read_worker_meta_state(meta_path)
                if int((meta or {}).get("pid") or 0) == os.getpid():
                    pathlib.Path(meta_path).unlink()
            except ValueError:
                pass
            except OSError:
                pass


if __name__ == "__main__":
    main()
