"""运行时低层件：pidfile / 存活分态 / 端口探测 / 进程信息 / 停机升级。

对应交接单 §2 取舍的机制底座：
- #1 幂等判据与超时常量（与被借鉴 supervisor 同量级：端口探活 1.5s / 起服务 30s）；
- #2 pidfile 读侧容错：脏值→null 并自清，陈旧 pid（进程已不在）自清；
- #3 存活探测分态：ESRCH=死 / EPERM=进程还在（报「权限不足需人工」，不判死）；
- #4 停机 TERM→限时→KILL 升级，超时强杀显式声明；
- #6/#7 pid 单真源=安装器 pidfile；data/worker.pid 只作迁移期回落读侧，两写禁止。

所有子进程/信号/轮询路径都有终态：正常、报错、超时、无此进程，四条路都能走到清理。
"""

from __future__ import annotations

import errno
import os
import pathlib
import re
import signal
import socket
import subprocess
import time

# —— 超时常量（§2-#1：同量级移植）——
PORT_PROBE_TIMEOUT = 1.5
SERVER_START_TIMEOUT = 30.0
WORKER_START_TIMEOUT = 15.0
DOWN_TERM_TIMEOUT = 10.0
DOWN_KILL_TIMEOUT = 5.0
POLL_INTERVAL = 0.2

# 存活分态（§2-#3）
ALIVE = "alive"
DEAD = "dead"
EPERM = "eperm"  # 进程还在但无权发信号：=活着，上层报「权限不足需人工」

_PID_RE = re.compile(r"\d+")


def repo_root() -> pathlib.Path:
    """仓根 = 本包 server/ 的上一级（server/installer/runtime.py → 上两级）。"""
    return pathlib.Path(__file__).resolve().parents[2]


class InstallPaths:
    """一次安装的全部路径与端口。测试可整体替换 root/home/端口/二进制。"""

    def __init__(self, root=None, home=None, server_port=7233, ui_port=8233,
                 console_port=None, temporal_bin=None, venv_python=None):
        self.root = pathlib.Path(root) if root is not None else repo_root()
        env_home = os.environ.get("SANDBAR_HOME")
        self.home = pathlib.Path(home) if home is not None else \
            pathlib.Path(env_home) if env_home else pathlib.Path.home() / ".sandbar"
        self.poc_dir = self.root / "server" / "dsh" / "temporal-poc"
        self.run_dir = self.home / "run"
        self.server_pidfile = self.run_dir / "server.pid"
        self.worker_pidfile = self.run_dir / "worker.pid"
        self.server_log = self.run_dir / "server.log"
        self.worker_log = self.run_dir / "worker.log"
        self.db_path = self.poc_dir / "data" / "temporal.db"
        # §2-#7：data/worker.pid 是迁移期回落读侧（只读，两写禁止）
        self.worker_pid_fallback = self.poc_dir / "data" / "worker.pid"
        self.server_port = int(server_port)
        self.ui_port = int(ui_port)
        if console_port is None:
            from installer import console as _console
            console_port = _console.CONSOLE_PORT
        self.console_port = int(console_port)
        # 二进制可注入（测试用桩脚本）；缺省=仓内运行期工件（.gitignore 的 bin//.venv/）
        self._temporal_bin = pathlib.Path(temporal_bin) if temporal_bin else None
        self._venv_python = pathlib.Path(venv_python) if venv_python else None

    @property
    def temporal_bin(self) -> pathlib.Path:
        return self._temporal_bin or (self.poc_dir / "bin" / "temporal")

    @property
    def venv_python(self) -> pathlib.Path:
        return self._venv_python or (self.poc_dir / ".venv" / "bin" / "python")


# ---------- pidfile 读写（§2-#2/#7） ----------

def _unlink_quiet(path) -> None:
    try:
        pathlib.Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass  # 自清失败不遮蔽主流程；下次读侧再试


def read_pid(path):
    """读 pidfile；脏值→None 并自清。文件缺失→None。"""
    try:
        raw = pathlib.Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (IsADirectoryError, PermissionError, UnicodeDecodeError, OSError):
        _unlink_quiet(path)
        return None
    if not _PID_RE.fullmatch(raw or ""):
        _unlink_quiet(path)  # 脏值自清
        return None
    pid = int(raw)
    if pid <= 0:
        _unlink_quiet(path)
        return None
    return pid


def write_pid(path, pid: int) -> None:
    """写 pidfile（原子：tmp + replace），单行十进制。"""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("%d\n" % int(pid), encoding="utf-8")
    os.replace(str(tmp), str(p))


def clear_pidfile(path) -> None:
    _unlink_quiet(path)


def pid_state(pid) -> str:
    """存活分态：ALIVE / DEAD / EPERM（§2-#3：EPERM=进程还在，不判死）。"""
    if pid is None:
        return DEAD
    try:
        os.kill(pid, 0)
        return ALIVE
    except ProcessLookupError:
        return DEAD
    except PermissionError:
        return EPERM
    except OSError as e:
        if e.errno == errno.ESRCH:
            return DEAD
        if e.errno == errno.EPERM:
            return EPERM
        raise


def live_pid(path):
    """读侧口径：pidfile 指向活进程才返回 pid；脏/陈旧自清（§2-#2）。"""
    pid = read_pid(path)
    if pid is None:
        return None
    st = pid_state(pid)
    if st == ALIVE:
        return pid
    if st == DEAD:
        _unlink_quiet(path)  # 陈旧 pid 自清
        return None
    return pid  # EPERM：进程还在（无权确认细节），按在位交上层提示


# ---------- 进程信息 ----------

def _proc_cmdline_linux(pid):
    """Linux /proc 兜底（macOS 无 /proc，返回 OSError→None 走 ps）。"""
    try:
        raw = pathlib.Path("/proc/%d/cmdline" % pid).read_bytes()
    except OSError:
        return None
    parts = [x for x in raw.decode("utf-8", "replace").split("\0") if x]
    return " ".join(parts) or None


def _proc_ppid_linux(pid):
    try:
        stat = pathlib.Path("/proc/%d/stat" % pid).read_text(encoding="utf-8")
    except OSError:
        return None
    try:  # comm 可能含空格：取右括号之后；ppid 为其后第 2 字段
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (ValueError, IndexError):
        return None


def proc_cmdline(pid):
    """进程命令行（argv 面）：/proc 优先，ps -ww 兜底；读不到（已死/无权/被禁）返回 None。"""
    via_proc = _proc_cmdline_linux(pid)
    if via_proc is not None:
        return via_proc
    try:
        out = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def proc_ppid(pid):
    """父 pid：/proc 优先，ps 兜底；读不到返回 None（由上层按「需人工判读」处理）。"""
    via_proc = _proc_ppid_linux(pid)
    if via_proc is not None:
        return via_proc
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    raw = out.stdout.strip()
    try:
        return int(raw)
    except ValueError:
        return None


def find_port_pids(port):
    """端口监听者 pid 列表：lsof 优先，ss 兜底；两者皆缺→RuntimeError（上层 fail-closed）。"""
    try:
        out = subprocess.run(
            ["lsof", "-ti", "tcp:%d" % int(port), "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            pids = sorted({int(x) for x in out.stdout.split() if x.strip().isdigit()})
            if pids:
                return pids
    except FileNotFoundError:
        pass
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    try:  # Linux 兜底：ss -lptn
        out = subprocess.run(["ss", "-lptn", "sport = :%d" % int(port)],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            pids = sorted({int(m) for m in re.findall(r"pid=(\d+)", out.stdout)})
            if pids:
                return pids
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    raise RuntimeError("需 lsof 或 ss 之一在场才能定位端口占用 pid")


# ---------- 端口探测（§2-#1） ----------

def port_open(port, timeout=PORT_PROBE_TIMEOUT, host="127.0.0.1") -> bool:
    """TCP connect 判在位（幂等 up 判据）；拒绝/超时/无路由都=不在位。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_until(pred, timeout: float) -> bool:
    """限时轮询；到点未成立=假（调用方 fail-closed）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(POLL_INTERVAL)
    return pred()


# ---------- 信号与停机（§2-#4） ----------

def send_signal(pid, sig) -> str:
    """发信号，返回分态：ALIVE（已递）/ DEAD（ESRCH）/ EPERM。"""
    try:
        os.kill(pid, sig)
        return ALIVE
    except ProcessLookupError:
        return DEAD
    except PermissionError:
        return EPERM


def stop_process(pid, what: str, term_timeout=DOWN_TERM_TIMEOUT, log=print) -> str:
    """TERM → 限时等待 → KILL 升级。返回 stopped/killed/eperm/failed。

    - EPERM：进程还在但无权停——显式报「权限不足需人工」，不判死不假装成功；
    - KILL 升级与强杀失败都显式声明（不静默）；
    - 轮询前先 reap_children()：本进程拉起的孩子退出后若未被回收（zombie），
      os.kill(pid,0) 仍报活，会把「已停」误判成「杀不掉」。
    """
    reap_children()
    st = send_signal(pid, signal.SIGTERM)
    if st == DEAD:
        return "stopped"
    if st == EPERM:
        log("[红] %s（pid=%d）权限不足，无法停（需人工处理）" % (what, pid))
        return "eperm"
    deadline = time.monotonic() + term_timeout
    while time.monotonic() < deadline:
        reap_children()
        if pid_state(pid) == DEAD:
            return "stopped"
        time.sleep(POLL_INTERVAL)
    log("[黄] %s（pid=%d）TERM 后 %gs 未退，升级 SIGKILL（超时强杀，显式声明）"
        % (what, pid, term_timeout))
    send_signal(pid, signal.SIGKILL)
    deadline = time.monotonic() + DOWN_KILL_TIMEOUT
    while time.monotonic() < deadline:
        reap_children()
        if pid_state(pid) == DEAD:
            return "killed"
        time.sleep(POLL_INTERVAL)
    log("[红] %s（pid=%d）SIGKILL 后仍未退出——需人工介入" % (what, pid))
    return "failed"


def spawn_detached(cmd, cwd, log_path):
    """拉起脱离会话的长驻子进程：stdio 落安装器日志，新会话（不随终端退）。

    返回 Popen（调用方持 pid 与回收责任）；本进程拉起的孩子登记进
    _SPAWNED，由 reap_children() 在停机轮询里回收——否则退出的孩子成
    zombie，os.kill(pid,0) 仍报活，存活探测会被僵尸骗过。
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), stdout=logf, stderr=logf,
            stdin=subprocess.DEVNULL, start_new_session=True)
        _SPAWNED.append(proc)
        return proc
    finally:
        logf.close()  # 子进程已 dup 句柄，父侧及时归还 fd


# 本进程拉起的长驻子进程登记（僵尸回收责任面）
_SPAWNED = []


def reap_children() -> int:
    """回收本进程已退出的拉起子进程（waitpid 语义），返回回收数。"""
    reaped = 0
    for proc in list(_SPAWNED):
        if proc.poll() is not None:
            _SPAWNED.remove(proc)
            reaped += 1
    return reaped
