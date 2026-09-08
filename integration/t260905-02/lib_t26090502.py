# -*- coding: utf-8 -*-
"""t260905-02 共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

三场景共用：被测 worker 子进程 env 装配（舞台指路+审计钩子护体）、stderr 语义
标记等待、进程退出等待、孤儿中间短命父拉起、ppid 观测、watch 间隔旋钮常量。

红线纪律（沿 t260904-02 lib_gate）：
- 绝不向真环境（3099/7233/8233 现有占用者）发任何信号；
- 被测子进程一律审计钩子护体（对 PROD_PORTS 的 socket.connect 先记 jsonl 后抛）；
- 一切状态写临时目录；spawn 的进程收尾 TERM→KILL 兜底（cleanup）；
- 断言锚公开行为输出（meta 文件/进程终态/stderr 日志行），日志锚用兼容正则
  锚语义不锁措辞（KI-051 教训）。
"""
import json
import os
import re
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POC = os.path.join(REPO, "server", "engine")
WORKER_PY = os.path.join(POC, "worker.py")

# watch 间隔旋钮（t260905-02 实现面交付：缺省 30s、下限钳制；新命名按宿主令
# 260904 用中性名，不扩 SUYOU_* 存量欠账）。旋钮未落地时 worker 自然走 30s
# 慢档——场景断言上限一律按慢档给，快慢档都绿，实现只影响快慢不影响判定。
KNOB = "SANDBAR_WATCH_INTERVAL_SEC"
KNOB_FAST = "2"


def child_env(stage_host, namespace, audit_env, extra=None):
    """被测 worker 子进程 env：连舞台 temporal/舞台 namespace/审计钩子护体。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = stage_host
    env["SANDBAR_NAMESPACE"] = namespace
    if audit_env:
        env.update(audit_env)
    env.update(extra or {})
    return env


def spawn_worker(py, log_path, env):
    """前台拉起 worker.py（stdout/stderr→日志文件：语义标记等待与证据留档面）。"""
    logf = open(log_path, "a", buffering=1)
    try:
        p = subprocess.Popen([py, WORKER_PY], stdout=logf, stderr=logf,
                             stdin=subprocess.DEVNULL, env=env)
    except Exception:
        logf.close()
        raise
    p._logf = logf  # 场景收尾 close_logf 统一关
    return p


def close_logf(p):
    f = getattr(p, "_logf", None)
    if f is not None:
        try:
            f.close()
        except Exception:
            pass


def stderr_text(log_path):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def wait_marker(log_path, pattern, timeout_s, interval=0.25):
    """等 stderr 出现语义标记（兼容正则）。超时返回 False（不断言，交场景判定）。"""
    rx = re.compile(pattern)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if rx.search(stderr_text(log_path)):
            return True
        time.sleep(interval)
    return bool(rx.search(stderr_text(log_path)))


def wait_exit(proc, timeout_s, interval=0.25):
    """等进程退出。返回 True=已退出。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(interval)
    return proc.poll() is not None


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ppid_of(pid):
    try:
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10).stdout.split()
        return int(out[0]) if out else None
    except Exception:
        return None


def log_holders(path):
    """lsof 观测文件的存活持有者 pid 列表（None=观测面不可用，区别于零持有者）。

    为什么用 lsof 而不用 ps：沙箱环境（workspace-write）对进程名目观测（ps/
    pgrep）可整类拒绝，但对具体文件的 fd 持有者查询可用（20260905 本仓泳道实
    测）——重复 child 的 stdout/stderr=node 开的工单 worker 日志 fd，持有者归零
    即 child 已死，判定面恰落在可用观测上。"""
    try:
        r = subprocess.run(["lsof", "-t", path],
                           capture_output=True, text=True, timeout=10)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:
        return None


def wait_ppid(pid, want, timeout_s, interval=0.5):
    """等进程 ppid 变为 want（孤儿收养观测）。返回 (达到与否, 最后观测值)。

    孤儿被谁收养是系统状态条件（macOS=launchd(1)；Linux 容器内 subreaper 可使
    ppid≠1）——达不到时调用方按 N/A 条件腿处置，不算被测行为红。"""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = ppid_of(pid)
        if last == want:
            return True, last
        time.sleep(interval)
    return False, last


def spawn_via_shortlived_parent(py, env, log_path):
    """经中间短命父拉起 worker：中间父 spawn 后立即退出 → worker 成孤儿被收养。

    返回中间父 Popen（worker pid 从其 stdout 读）；worker 的输出落 log_path。"""
    snippet = (
        "import json, subprocess, sys\n"
        "env = json.load(open(sys.argv[1]))\n"
        "logf = open(sys.argv[2], 'a', buffering=1)\n"
        "p = subprocess.Popen([sys.executable, sys.argv[3]], env=env,\n"
        "                     stdout=logf, stderr=logf, stdin=subprocess.DEVNULL)\n"
        "print(p.pid, flush=True)\n"
    )
    envf = log_path + ".env.json"
    with open(envf, "w", encoding="utf-8") as f:
        json.dump(env, f)
    return subprocess.Popen([py, "-c", snippet, envf, log_path, WORKER_PY],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
