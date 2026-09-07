"""Worker：把 workflow/activity 注册到 task queue 上跑（定形版，t260821-02）。

worker 是「肌肉」，服务端是「骨架与记忆」。worker 挂了、代码重启，
workflow 的状态与历史都在服务端不丢——这正是要验证的模型性质。

启动形态：
    # 前台（调试/看日志）
    .venv/bin/python worker.py

    # 后台（常驻）
    .venv/bin/python worker.py --daemon [--pidfile data/worker.pid] [--logfile data/worker.log]

    # 工单专属 worker（260824 A 案起由 console keepalive 以子进程拉起，一般不用手跑）：
    #   SANDBAR_TASK_QUEUE=suyou-ticket-<工单id>（LEGACY 旧世界单值 env，桥接管）SANDBAR_WATCH_WORKFLOW=<工单id> \
    #     .venv/bin/python worker.py --daemon --pidfile data/worker-<工单id>.pid --logfile data/worker-<工单id>.log
    #   WATCH 模式下 worker 周期查自己 workflow 的状态，收口（非 RUNNING）即优雅自退。
    #   轮询间隔 env SANDBAR_WATCH_INTERVAL_SEC 可调（缺省 30s；畸形值回落缺省，下限钳 1s）。
    #   console 子进程模式另置 SANDBAR_WATCH_PPID=1：宿主被 SIGKILL 时 ppid 变 1 即自退，
    #   不留无主 worker（--daemon 手动拉起时不置此变量，保持常驻）。
    # 归属指纹（KI-033，t260904-02）：SANDBAR_WORKER_META=<路径>（supervisor 指路）时
    #   起跑即写 meta JSON（repo_root/pid）；daemon 模式写 <pidfile>.meta。ensure 侧
    #   据此识别异仓 worker 伺服同票（告警+拒接）。

优雅停：
    kill -TERM $(cat data/worker.pid)      # SIGTERM / Ctrl-C（SIGINT）同理
    → worker.shutdown()：把在跑的 activity 做完、不再领新活，然后干净退出。
    （worker 停掉期间服务端里的 workflow 仍 RUNNING，攒下的活等重启后自动接着跑。）
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

WATCH_INTERVAL_DEFAULT_SEC = 30.0  # 生产缺省：30s 一轮（收口感知延迟上限≈一轮）
WATCH_INTERVAL_MIN_SEC = 1.0       # 下限钳制：防 0/负值忙转打爆 describe


def watch_interval_sec(raw: "str | None" = None) -> float:
    """watch 轮询间隔（秒）。env SANDBAR_WATCH_INTERVAL_SEC 可调（集成场景提速用，
    生效前提=SANDBAR_WATCH_WORKFLOW 在置——watch 任务本身只在工单专属模式创建）。
    新 env 按宿主令 260904 用 sandbar 前缀（不扩 SUYOU_* 存量欠账）。
    消费外部输入，畸形态全容错：未置/空白/非数值/NaN/Inf/<=0 一律回落缺省；
    有效但低于下限 → 钳到下限（不忙转）。"""
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
    """归属指纹 meta 落点（KI-033，t260904-02）。

    - 工单专属模式（console supervisor 以子进程拉起）：读 env SANDBAR_WORKER_META
      （supervisor spawn 时指路，约定 = <dataDir>/worker-<tid>.meta，与 pidfile 同目录）；
    - daemon 模式（--daemon 常驻）：<pidfile>.meta（worker 自己知道 pidfile 路径）；
    - 前台调试模式：不落 meta（无注册方，写了也没人读）。

    pidfile 本体语义不动（纯数字 pid），meta 是旁车文件——ensure 侧按
    「pid 活着 + meta 异仓」判异仓（告警+拒接，不杀别人进程）。"""
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
    """单 fork 去会话化。返回 True 表示当前是父进程（调用方应立即退出）。"""
    pid = os.fork()
    if pid > 0:
        # 父进程：记下子 pid 后退出（子进程 setsid 不改变 pid）
        pathlib.Path(pidfile).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(pidfile).write_text(str(pid))
        return True
    # 子进程：脱离终端会话，重定向 stdio 到日志文件
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
    # 归属指纹自报（KI-033）：起跑早写（Client.connect 前）——确保 worker 一活起来
    # ensure 侧就能读到归属；best-effort，写失败不阻断启动（ensure 对缺失态有
    # unknown 兼容处理）。优雅停时 main() 里 best-effort 清理。
    meta_path = worker_meta_path(args)
    if meta_path:
        payload = write_worker_meta(meta_path, repo_root=str(REPO_ROOT), pid=os.getpid())
        logging.info("worker 归属指纹：repo_root=%s pid=%d meta=%s",
                     payload.get("repo_root"), payload.get("pid"), meta_path)
    else:
        logging.info("worker 归属指纹：前台模式不落 meta（repo_root=%s）", REPO_ROOT)
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    # 260823：老 TicketWorkflow 已随 tickets/ 投影目录退场（全部工单 closed）。
    # workflow 清单=步1 两类（兼容）+ 六模版子类；activity 清单=通用活动 + agent 段活动。
    # 多队列过渡（t260907-04 退役账#1/#2）：每队列一个 Worker 实例共享同一
    # registry——共享模式 poll 新旧共享队列（LEGACY 旧队列在飞 workflow 流干）；
    # 专属模式由 SANDBAR_TASK_QUEUES 注入「新,旧 ticket 队列」（在飞工单 worker
    # 重启后旧前缀 workflow 不搁浅）。启动日志逐队列打印 = 双注册证据。
    workers = []
    for _q in configured_task_queues():
        workers.append(Worker(
            client,
            task_queue=_q,
            workflows=ALL_WORKFLOWS + ALL_WORKFLOWS_V2,
            activities=ALL_ACTIVITIES + ALL_AGENT_ACTIVITIES,
        ))
    logging.info("worker polling queues: %s", ", ".join(configured_task_queues()))

    # 优雅停：SIGTERM/SIGINT → worker.shutdown()（在跑 activity 做完，停领新活）
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # 非主线程 / 平台不支持时退化为无信号处理（前台 Ctrl-C 仍由 asyncio 默认处理）

    # 工单专属模式（260824）：SANDBAR_WATCH_WORKFLOW=<工单id> 时周期查 workflow 状态，
    # 收口（非 RUNNING）即触发优雅自退——专属 worker 的生命周期跟工单走，不常驻。
    # 查询失败（网络抖动/workflow 不存在）不退出：worker 停了活会攒住，宁可多等一轮。
    # A 案（260824 二轮拍板：工单 worker 跟 console 走）：console 以子进程方式拉起时
    # 置 SANDBAR_WATCH_PPID=1——宿主被 SIGKILL（dispose 跑不到）时本进程被 launchd
    # 收养、ppid 变 1，据此自退，不留无主 worker（85222 版本投毒教训）。
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
        # 优雅停收尾：清自己的 meta（stale meta 由 ensure 侧按「pid 死」判定，
        # 但主动清更干净）。best-effort——清不掉不掩盖退出码。
        if meta_path:
            try:
                pathlib.Path(meta_path).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    main()
