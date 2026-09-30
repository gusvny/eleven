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
import agent_runtime
from agent_activities import ALL_AGENT_ACTIVITIES, make_stage_activity
from dsh_pin import dsh_face_payload, enforce_expected
from agent_activities import inflight_stage_snapshot, recent_stage_outcomes
from shared import NAMESPACE, POC_DIR, REPO_ROOT, TARGET_HOST, TASK_QUEUE, configured_task_queues
from shared import write_worker_meta
from workflows import ALL_WORKFLOWS
from workflows_v2 import (ALL_WORKFLOWS_V2, PROJECT_TEMPLATE_PASSTHROUGH_MODULES,
                          PROJECT_TEMPLATE_STAGE_IDS)

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
    acts = list(ALL_ACTIVITIES) + list(ALL_AGENT_ACTIVITIES) + [
        make_stage_activity(s) for s in extra_stage_ids]
    seen = {}
    for a in acts:
        name = activity_registered_name(a)
        src = getattr(a, "__module__", "?")
        if name in seen:
            raise ValueError(
                "活动名撞车（worker 注册前置断言，KI-121）：活动 %s 已由 %s 注册，"
                "再来件 %s —— 外置模板段 id 不得与引擎注册活动同名（同名=注册期崩，"
                "工人起不来）；加载口应已在合并期拒收，此处为最后防线"
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


def pid_alive(pid: int) -> bool:
    """存活探测（守卫专用）：`kill(pid, 0)` + **僵尸面**修正。

    `kill(pid, 0)` 对**僵尸**（已退出但父进程未收割）仍然成功——只按它判会把「已死的旧
    worker」读成活，于是 --replace 白等到超时（installer 侧同款实缺陷）。所以能查就查：
      · Linux：/proc/<pid>/stat 第三列 'Z' ⇒ 已死；
      · **本进程自己的子进程**：waitpid(WNOHANG) 真收割（顺带防僵尸堆积）⇒ 已死；
      · 其它情况（macOS 上非自家子进程，无法查状态）：按**活**处理（保守——宁可拒绝启动
        让人看一眼，也不静默起第二颗；生产里 daemon worker 归 init 收养，退出即被收割，
        不会长期停在僵尸态）。
    EPERM（存在但非本用户）也算活。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    # 僵尸修正
    try:
        with open("/proc/%d/stat" % pid, encoding="ascii", errors="replace") as f:
            parts = f.read().split()
        if len(parts) > 2 and parts[2] == "Z":
            return False
    except OSError:
        pass
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        pass
    return True


def read_pidfile_state(pidfile: str) -> dict:
    """pidfile 四态（纯读、零副作用）：absent / malformed / stale / live。

    live 是重启的**唯一合法拦截点**；malformed/stale 都按「陈旧可接管」处理但留痕
    （读不懂 ≠ 没有——所以仍然点名，不静默当不存在）。"""
    p = pathlib.Path(pidfile)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return {"state": "absent", "pid": None, "raw": "", "mtime": 0.0, "detail": "文件不存在"}
    except OSError as e:
        return {"state": "stale", "pid": None, "raw": "", "mtime": 0.0,
                "detail": "读失败（%s: %s）——按陈旧接管" % (type(e).__name__, e)}
    mtime = p.stat().st_mtime if p.exists() else 0.0
    try:
        pid = int(raw)
        if pid <= 0:
            raise ValueError(raw)
    except (TypeError, ValueError):
        return {"state": "malformed", "pid": None, "raw": raw[:40], "mtime": mtime,
                "detail": "内容非正整数（%r）——按陈旧接管" % raw[:40]}
    if pid_alive(pid):
        return {"state": "live", "pid": pid, "raw": raw, "mtime": mtime, "detail": "进程存活"}
    return {"state": "stale", "pid": pid, "raw": raw, "mtime": mtime,
            "detail": "pid=%d 已不在" % pid}


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
        return ("拒绝 --replace：pidfile 旁车 meta 指向**另一个仓**（repo_root=%s，本仓=%s）"
                "——不代杀他人进程，请人工处置（核对 %s 里的 pid=%d）"
                % (where, own_root, pidfile, pid))
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log.warning("--replace：旧 worker pid=%d 在发信号前已退出——直接接管", pid)
        return None
    except OSError as e:
        return ("--replace 失败：向旧 worker pid=%d 发 SIGTERM 出错（%s: %s）——未起新进程，"
                "请人工处置" % (pid, type(e).__name__, e))
    t0 = time.time()
    while time.time() - t0 < REPLACE_WAIT_SEC:
        if not pid_alive(pid):
            log.info("--replace：旧 worker pid=%d 已优雅退出（等待 %.1fs）——本进程接管该槽",
                     pid, time.time() - t0)
            return None
        time.sleep(REPLACE_POLL_SEC)
    return ("--replace 超时：旧 worker pid=%d 在 %.0fs 内未退出——**不 KILL**（在飞 agent 活动"
            "被硬切会让票面带病），本次不起新进程。请人工处置：查 data/worker.log 的"
            "「停机点名」看在飞活动，或 kill -TERM %d 后再起"
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
    else:
        logging.info("worker 归属指纹：前台模式不落 meta（repo_root=%s）", REPO_ROOT)
    if face["expected_state"] == "mismatch":
        logging.warning("%s（已随 worker meta 落盘可查：%s）", face_note,
                        meta_path or "前台模式无 meta")
    else:
        logging.info("%s", face_note)
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
    # 260930 code_stamp：在**进程入口**钉真·启动时刻（此处非沙箱，允许读墙钟）。
    # 为什么必须在这里钉：shared 的惰性兜底只能给「首次访问时刻」（活动里），那么
    # 「worker 启动后、首次取 stamp 前落盘的改动」永远判不出 stale——正是 t260928-01
    # （`>3000s` 旧码值）与 t260930-01（deadman 中文）两次实案的形态。
    # 放 daemonize **之前**：父进程（daemon 化后立即返回的那个）也钉同一值，
    # 子进程继承的模块状态不受影响（子进程自己会在自己的 main 里钉）。
    try:
        import shared as _shared
        _shared.note_process_start()
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
        if meta_path:
            try:
                pathlib.Path(meta_path).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    main()
