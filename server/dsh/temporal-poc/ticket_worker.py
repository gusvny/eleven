"""工单专属 worker 的生/死/救（260824 用户拍板：一工单一 worker）。

每张工单 = 专属 task queue（sandbar-ticket-<id>，LEGACY 旧前缀见 shared.ticket_task_queues）
+ 一个专属 worker 进程。本模块只管进程生命周期：

- spawn_ticket_worker(tid)：拉起专属 worker（已活着则跳过，幂等）。
- reap_ticket_worker(tid)：SIGTERM 专属 worker（不存在则跳过，幂等）。
- ensure_ticket_workers(running_tids, all_ticket_ids)：对账——RUNNING 缺
  worker 补拉；专属 worker 活着但 workflow 不在跑 → 回收。

**定位（260824 A 案二轮拍板后）**：生产路径上工单 worker 由 **console
keepalive ensure 以子进程 spawn**（temporal-tools supervisor，跟 console 走，
dispose 带走；ticket.py create 不再 spawn）。本模块退为**手动/测试工具 +
reconcile 的 reap 原语**（reap_ticket_worker/worker_pid）；spawn 系列只在
测试栈或无 console 的手动场景用。

**stdlib-only**：server/tools/ticket.py 在系统 python3 下直载本模块（无 temporalio）。
Temporal 状态查询不在这里做——running/closed 名单由调用方（有 SDK 的一侧）给。

环境变量透传：spawn 继承 os.environ，所以 SANDBAR_TARGET_HOST / SANDBAR_NAMESPACE
（测试环境指向 Docker 隔离 Temporal，见 docs/testing-guide.md）自动传到子进程。
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
    """专属 worker 的活 pid（pidfile 在册且进程存活）；否则 0。pidfile 陈旧自动清。"""
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
        return pid  # 进程在但不是我们的——视为活着，不动


def _ticket_task_queue(tid: str) -> str:
    """工单专属队列名。shared.py 按文件路径直载（ticket.py 直载本模块时 'shared'
    不在 sys.path 上——它是 stdlib-only，路径加载两边行为一致）。"""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location('_tw_shared', POC_DIR / 'shared.py')
    mod = importlib.util.module_from_spec(spec)
    # 必须注册进 sys.modules：py3.9 dataclasses 处理 postponed annotations 时
    # 按 cls.__module__ 反查 sys.modules，查不到即 AttributeError（260821 实测）。
    sys.modules.setdefault('_tw_shared', mod)
    spec.loader.exec_module(mod)
    return mod.ticket_task_queue(tid)


def _ticket_task_queues(tid: str) -> list:
    """双 poll 清单（新前缀在前＋旧前缀，见 shared.ticket_task_queues / 退役账#2）。"""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location('_tw_shared', POC_DIR / 'shared.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault('_tw_shared', mod)
    spec.loader.exec_module(mod)
    return mod.ticket_task_queues(tid)


def spawn_ticket_worker(tid: str) -> str:
    """拉起工单专属 worker（幂等：已活着直接返回）。返回 'already' | 'spawned'。"""
    if worker_pid(tid):
        return 'already'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # 多队列注入（t260907-04）：新 ticket 队列在前＋旧 ticket 队列（在飞 workflow
    # 流干用）；worker.py 按 CSV 逐队列注册（共享同一 registry，日志双队列可证）。
    env['SANDBAR_TASK_QUEUES'] = ','.join(_ticket_task_queues(tid))
    env['SANDBAR_WATCH_WORKFLOW'] = tid  # workflow 收口自退（worker.py watcher）
    # --daemon：worker.py 自己 fork+setsid 并写 pidfile，本调用立即返回。
    subprocess.Popen(
        [VENV_PY, str(POC_DIR / 'worker.py'), '--daemon',
         '--pidfile', str(_pidfile(tid)), '--logfile', str(_logfile(tid))],
        cwd=str(POC_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    return 'spawned'


def reap_ticket_worker(tid: str) -> str:
    """SIGTERM 回收专属 worker（幂等）。返回 'reaped' | 'none'。"""
    pid = worker_pid(tid)
    if not pid:
        return 'none'
    try:
        os.kill(pid, signal.SIGTERM)  # 优雅停：在跑 activity 做完再走（worker.py 契约）
    except ProcessLookupError:
        pass
    try:
        _pidfile(tid).unlink()
    except OSError:
        pass
    return 'reaped'


def ensure_ticket_workers(running_tids, known_tids) -> dict:
    """巡检对账（救/收）：running 缺 worker 补拉；known 里不在跑的回收活着的 worker。

    running_tids：exec_status=RUNNING 的工单 id 集；known_tids：六模版块所有工单 id
    （含已收口）。返回 {'spawned': [...], 'reaped': [...]} 供巡检报告留痕。
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
