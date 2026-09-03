"""init/up/down/status 编排：pid 单真源、孤儿接管（V1 ppid 谓词）、retention fail-closed。

交接单 §2 逐项落点：
- #5 不装 keepalive：安装器是唯一拉起方，server 死了就报红，不自动复活；
- #7 单真源=安装器 pidfile（~/.sandbar/run/）；data/worker.pid 仅迁移期回落读侧（只读认领，两写禁止）；
- #8 retention 校正失败=fail-closed 红（不复刻 run_server.sh 的静默重试），刚拉起的带病 server 就地回收；
- #9 孤儿接管：端口被占→定位 pid→谓词全中才认领；V1：认领仅限真孤儿（父进程已死），
  supervisor 仍存活=只报告归属与处置指引，不对抗不认领（绝不「杀后被复活」）；
- down 时序：先 worker 后 server（保 SQLite 历史真源）。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import time

from installer import console as console_mod
from installer import runtime
from installer.runtime import InstallPaths

RETENTION = "876000h"          # 100 年（run_server.sh 同款语义，t260829-06 实测口径）
RETENTION_RETRY = 5            # 每次尝试都显式记日志；耗尽=fail-closed 红
NAMESPACE_DEFAULT = "default"
SEARCH_ATTRIBUTES = ("ProjectKey=Keyword", "EpicCode=Keyword")


class FailClosed(RuntimeError):
    """安装器红错：显式报错退出（exit 1），绝不静默降级。"""


class ToolingMissing(FailClosed):
    """工具面缺失（temporal CLI / worker venv）——init/up 冷启动红；
    up 的 worker 段对其显式黄条跳过（server 管辖面已完成，rc=0）。"""


def _log_line(log, line: str) -> None:
    log(line)


# ---------- 工具面检查 ----------

def check_server_tooling(paths: InstallPaths) -> None:
    """server 冷启动前置：temporal CLI 在位且可执行（缺件写明获取路径）。"""
    tb = paths.temporal_bin
    if not (tb.is_file() and (tb.stat().st_mode & 0o111) != 0):
        raise ToolingMissing(
            "temporal CLI 缺失：%s（运行期工件不入 git：跑 "
            "server/dsh/temporal-poc/setup.sh 获取）" % tb)


def check_worker_tooling(paths: InstallPaths) -> None:
    """worker 段前置：venv python 与 worker.py 在位。"""
    missing = []
    if not paths.venv_python.is_file():
        missing.append("%s（worker venv：跑 server/dsh/temporal-poc/setup.sh）"
                       % paths.venv_python)
    if not (paths.poc_dir / "worker.py").is_file():
        missing.append("%s（worker 入口缺失，仓不完整）" % (paths.poc_dir / "worker.py"))
    if missing:
        raise ToolingMissing("worker 工具面缺失，fail-closed：\n  - "
                             + "\n  - ".join(missing))


def check_tooling(paths: InstallPaths) -> None:
    """init 的全量工具面检查。"""
    try:
        check_server_tooling(paths)
    except ToolingMissing as e:
        raise FailClosed(str(e))
    check_worker_tooling(paths)


# ---------- 认领谓词（§2-#9 + V1） ----------

def surface_match(paths: InstallPaths, pid: int):
    """命令行+数据卷谓词（不含 ppid 面）。返回 (命中: bool, 原因: str)。

    ① 命令行含 temporal server start-dev；
    ② 数据卷路径属本安装：--db-filename 指向本仓 data 卷，或 --data 指向本
       安装 home（集成桩与真实 CLI 两种调用形态都覆盖）。
    """
    cmd = runtime.proc_cmdline(pid) or ""
    if not ("temporal" in cmd and "server" in cmd and "start-dev" in cmd):
        return False, "命令行非 temporal server start-dev：%s" % (cmd[:120] or "<读不到>")
    if str(paths.db_path) in cmd:
        return True, "数据卷=本仓 data 卷"
    if "--data" in cmd and str(paths.home) in cmd:
        return True, "数据卷=本安装 home"
    return False, "数据卷路径不属本安装（既非 %s 也非 --data %s）" % (paths.db_path, paths.home)


def claim_verdict(paths: InstallPaths, pid: int):
    """down 侧孤儿判定（V1）。返回 (可认领: bool, 原因: str)。

    谓词（全中才可认领）：surface_match ①② + ③ V1 父进程已死（真孤儿，
    ppid 判定）——supervisor 仍存活=只报告归属与处置指引，不对抗不认领。
    """
    ok, why = surface_match(paths, pid)
    if not ok:
        return False, why
    ppid = runtime.proc_ppid(pid)
    if ppid is None:
        return False, "读不到父进程 pid（需人工判读）"
    if ppid <= 1:
        return True, "父进程已不在（真孤儿，被 init/launchd 收养）"
    if runtime.pid_state(ppid) != runtime.DEAD:
        return False, ("父进程 %d 仍在（supervisor 拉起面，§2-#5：只报告归属与处置指引，"
                       "不对抗不认领）" % ppid)
    return True, "父进程 %d 已死（真孤儿）" % ppid


def _port_holders(paths: InstallPaths):
    try:
        pids = runtime.find_port_pids(paths.server_port)
    except RuntimeError as e:
        raise FailClosed("端口 %d 被占但无法定位占用 pid：%s" % (paths.server_port, e))
    if not pids:
        raise FailClosed("端口 %d 探活为开但无监听 pid——请人工判读" % paths.server_port)
    return pids


def adopt_running_server(paths: InstallPaths, log) -> int:
    """up 侧纳管语义：端口已在且 pidfile 无记录时，谓词命中即纳管（只记录，不杀不动）。

    up 是「点亮」路径，不存在对抗面；down 的 V1 纪律不受影响——没有先 up 纳管
    就直接 down 一个 supervisor 持有的 server，仍走 resolve_port_orphan 的
    「报告+不杀+不复活」。
    """
    verdicts, adoptable = [], None
    for pid in _port_holders(paths):
        ok, why = surface_match(paths, pid)
        verdicts.append("pid=%d：%s" % (pid, why))
        if ok and adoptable is None:
            adoptable = pid
    if adoptable is None:
        raise FailClosed("端口 %d 被占，不满足纳管谓词（不误杀，不重复拉起）：\n  %s"
                         % (paths.server_port, "\n  ".join(verdicts)))
    runtime.write_pid(paths.server_pidfile, adoptable)
    _log_line(log, "server 已在运行（pid=%d，命令行与数据卷属本安装）——已纳管进安装器 "
                   "pidfile，幂等返回（不重复拉起）" % adoptable)
    return adoptable


def resolve_port_orphan(paths: InstallPaths, log) -> int:
    """down 侧接管语义（#9+V1）：真孤儿才认领后可停；supervisor 持有=报告+不杀+不复活。"""
    verdicts, adoptable = [], None
    for pid in _port_holders(paths):
        ok, why = claim_verdict(paths, pid)
        verdicts.append("pid=%d：%s" % (pid, why))
        if ok and adoptable is None:
            adoptable = pid
    if adoptable is not None:
        runtime.write_pid(paths.server_pidfile, adoptable)
        _log_line(log, "[认领] 真孤儿 server（pid=%d）已收编进安装器 pidfile，可 down" % adoptable)
        return adoptable
    raise FailClosed("端口 %d 被占，不满足认领谓词（报告+不杀+不复活，绝不「杀后被复活」）：\n  %s"
                     % (paths.server_port, "\n  ".join(verdicts)))


# ---------- server ----------

def _server_cmd(paths: InstallPaths):
    return [
        str(paths.temporal_bin), "server", "start-dev",
        "--db-filename", str(paths.db_path),
        "--ip", "127.0.0.1",
        "--port", str(paths.server_port),
        "--ui-port", str(paths.ui_port),
        "--search-attribute", SEARCH_ATTRIBUTES[0],
        "--search-attribute", SEARCH_ATTRIBUTES[1],
        "--log-level", "warn",
    ]


def correct_retention(paths: InstallPaths, log) -> bool:
    """§2-#8：retention 幂等校正，失败=红（fail-closed，不静默放弃）。

    校正后用 namespace describe 复核（输出含 876000 才算成立）；
    每次尝试都显式记日志，耗尽重试→False（调用方就地回收刚拉起的 server）。
    """
    addr = "127.0.0.1:%d" % paths.server_port
    last_err = ""
    for attempt in range(1, RETENTION_RETRY + 1):
        _log_line(log, "retention 校正（%d/%d）：%s → %s"
                  % (attempt, RETENTION_RETRY, NAMESPACE_DEFAULT, RETENTION))
        try:
            r = subprocess.run(
                [str(paths.temporal_bin), "operator", "namespace", "update",
                 "--retention", RETENTION, "--address", addr, NAMESPACE_DEFAULT],
                capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                last_err = (r.stderr or r.stdout or "").strip()[-300:]
                time.sleep(1)
                continue
            v = subprocess.run(
                [str(paths.temporal_bin), "operator", "namespace", "describe",
                 "--address", addr, NAMESPACE_DEFAULT],
                capture_output=True, text=True, timeout=20)
            if v.returncode == 0 and "876000" in (v.stdout or ""):
                return True
            last_err = "describe 复核未见 %s：%s" % (RETENTION,
                                                    (v.stdout or v.stderr or "").strip()[-200:])
        except (subprocess.TimeoutExpired, OSError) as e:
            last_err = str(e)
        time.sleep(1)
    _log_line(log, "[红] retention 校正末次失败：%s" % last_err)
    return False


def ensure_server(paths: InstallPaths, log) -> str:
    """幂等拉起 server。返回 already/adopted/started；fail 路径全 FailClosed。"""
    if runtime.port_open(paths.server_port):
        pid = runtime.live_pid(paths.server_pidfile)
        if pid is not None:
            _log_line(log, "server 已在运行（pid=%d，gRPC %d / UI %d）——幂等返回"
                      % (pid, paths.server_port, paths.ui_port))
            return "already"
        adopt_running_server(paths, log)  # 纳管（只记录不杀）或 FailClosed（不误杀）
        return "adopted"
    check_server_tooling(paths)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _log_line(log, "拉起 temporal dev server：gRPC %d / UI %d，数据卷 %s"
              % (paths.server_port, paths.ui_port, paths.db_path))
    proc = runtime.spawn_detached(_server_cmd(paths), cwd=paths.poc_dir,
                                  log_path=paths.server_log)
    runtime.write_pid(paths.server_pidfile, proc.pid)
    if not runtime.wait_until(lambda: runtime.port_open(paths.server_port),
                              runtime.SERVER_START_TIMEOUT):
        # 启动失败：子进程是本安装器拉的，就地回收（全终态纪律）
        runtime.stop_process(proc.pid, "server（启动超时回收）", runtime.DOWN_TERM_TIMEOUT, log)
        runtime.clear_pidfile(paths.server_pidfile)
        raise FailClosed("server 启动超时（%gs），子进程已回收，日志：%s"
                         % (runtime.SERVER_START_TIMEOUT, paths.server_log))
    if not correct_retention(paths, log):
        runtime.stop_process(proc.pid, "server（retention 失败回收）", runtime.DOWN_TERM_TIMEOUT, log)
        runtime.clear_pidfile(paths.server_pidfile)
        raise FailClosed(
            "retention 校正失败（缺省 24h 会物理删除已关闭 workflow，§2-#8 fail-closed）——"
            "刚拉起的 server 已回收，日志：%s；处置：查日志后重试 up 或人工校正" % paths.server_log)
    _log_line(log, "server 已就绪（pid=%d，retention=%s）" % (proc.pid, RETENTION))
    return "started"


# ---------- worker（§2-#6/#7） ----------

def resolve_worker_pid(paths: InstallPaths, log):
    """单真源=安装器 pidfile；缺失时按 §2-#7 走 data/worker.pid 迁移期回落认领（只读侧）。"""
    pid = runtime.live_pid(paths.worker_pidfile)
    if pid is not None:
        return pid
    fb = runtime.read_pid(paths.worker_pid_fallback)
    if fb is not None and runtime.pid_state(fb) == runtime.ALIVE:
        cmd = runtime.proc_cmdline(fb) or ""
        if "worker.py" in cmd and str(paths.poc_dir) in cmd:
            runtime.write_pid(paths.worker_pidfile, fb)  # 认领：只写安装器 pidfile
            _log_line(log, "[认领] data/worker.pid 指向活 worker（pid=%d），"
                           "已收编进安装器 pidfile（迁移期一次性回落）" % fb)
            return fb
        _log_line(log, "[黄] data/worker.pid 指向 pid=%d 但命令行不属本安装 worker，不认领" % fb)
    elif fb is not None:
        _log_line(log, "（提示）data/worker.pid 为陈旧值（pid=%d 已不在）；"
                       "该文件归 worker.py 写面，本安装器不代删（两写禁止）" % fb)
    return None


def ensure_worker(paths: InstallPaths, log) -> str:
    """幂等拉起 worker：复用 worker.py 自带 --daemon（§2-#6 带手法），pid 只落安装器 pidfile。"""
    pid = resolve_worker_pid(paths, log)
    if pid is not None:
        _log_line(log, "worker 已在运行（pid=%d）——幂等返回" % pid)
        return "already"
    check_worker_tooling(paths)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(paths.venv_python), "worker.py", "--daemon",
           "--pidfile", str(paths.worker_pidfile),
           "--logfile", str(paths.worker_log)]
    try:
        r = subprocess.run(cmd, cwd=str(paths.poc_dir), timeout=60,
                           capture_output=True, text=True)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise FailClosed("worker 拉起失败：%s" % e)
    if r.returncode != 0:
        raise FailClosed("worker 拉起失败（rc=%d）：%s"
                         % (r.returncode, (r.stderr or r.stdout or "").strip()[-300:]))
    if not runtime.wait_until(lambda: resolve_worker_pid(paths, log) is not None,
                              runtime.WORKER_START_TIMEOUT):
        raise FailClosed("worker 启动超时（未写 pidfile 或即刻死亡），日志：%s"
                         % paths.worker_log)
    _log_line(log, "worker 已拉起（pid=%d）" % resolve_worker_pid(paths, log))
    return "started"


# ---------- 子命令 ----------

def cmd_init(paths: InstallPaths, log=print) -> int:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    (paths.poc_dir / "data").mkdir(parents=True, exist_ok=True)
    check_tooling(paths)
    import sys as _sys
    server_dir = str(paths.root / "server")
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    import version as _version
    meta = {
        "root": str(paths.root),
        "sandbar_version": _version.sandbar_version(),
        "server_port": paths.server_port,
        "ui_port": paths.ui_port,
        "created": int(time.time()),
    }
    (paths.run_dir / "install.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _log_line(log, "init 完成：run 目录 %s；工具面齐（temporal CLI + worker venv）；"
                   "数据卷目录 %s" % (paths.run_dir, paths.poc_dir / "data"))
    _log_line(log, "sandbar 版本 %s" % meta["sandbar_version"])
    _log_line(log, console_mod.describe(paths.console_port,
                                        console_mod.probe_console(paths.console_port)))
    return 0


def cmd_up(paths: InstallPaths, log=print, skip_worker: bool = False) -> int:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    ensure_server(paths, log)
    if skip_worker:
        _log_line(log, "（--skip-worker）本次不起 worker")
    else:
        try:
            ensure_worker(paths, log)
        except ToolingMissing as e:
            # 工具面缺失=显式黄条跳过（非静默）：server 管辖面已完成；
            # worker 启动失败（非缺件）仍走 FailClosed 红。
            _log_line(log, "[黄] %s" % str(e).replace("\n", "\n[黄] "))
            _log_line(log, "[黄] worker 未拉起（工具面缺失，显式跳过）；server 管辖面已完成")
    _log_line(log, console_mod.describe(paths.console_port,
                                        console_mod.probe_console(paths.console_port)))
    return 0


def cmd_down(paths: InstallPaths, log=print, term_timeout=runtime.DOWN_TERM_TIMEOUT) -> int:
    """down：先 worker 后 server（交接单安全红线 + manifest ④R1）。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    rc = 0
    # 1) worker 先停
    wpid = resolve_worker_pid(paths, log)
    if wpid is None:
        _log_line(log, "worker：本就未在运行")
    else:
        outcome = runtime.stop_process(wpid, "worker", term_timeout, log)
        runtime.clear_pidfile(paths.worker_pidfile)
        if outcome in ("eperm", "failed"):
            rc = 1
        else:
            _log_line(log, "worker（pid=%d）已停（%s）" % (wpid, outcome))
    # 2) server 后停
    spid = runtime.live_pid(paths.server_pidfile)
    if spid is None and runtime.port_open(paths.server_port):
        spid = resolve_port_orphan(paths, log)  # 真孤儿→认领后停；supervisor 持有→FailClosed
    if spid is None:
        _log_line(log, "server：本就未在运行")
    else:
        outcome = runtime.stop_process(spid, "server", term_timeout, log)
        runtime.clear_pidfile(paths.server_pidfile)
        if outcome in ("eperm", "failed"):
            rc = 1
        else:
            _log_line(log, "server（pid=%d）已停（%s）" % (spid, outcome))
    # 3) console 只报告（永不对抗）
    _log_line(log, console_mod.describe(paths.console_port,
                                        console_mod.probe_console(paths.console_port)))
    return rc


def gather_status(paths: InstallPaths) -> dict:
    """status 事实收集（--json 与人读共用）。"""
    import sys as _sys
    server_dir = str(paths.root / "server")
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    import version as _version
    try:
        ver = _version.sandbar_version()
        ver_err = ""
    except _version.VersionError as e:
        ver, ver_err = "", str(e)
    spid = runtime.read_pid(paths.server_pidfile)
    sstate = runtime.pid_state(spid)
    sport = runtime.port_open(paths.server_port)
    uport = runtime.port_open(paths.ui_port)
    wpid = runtime.read_pid(paths.worker_pidfile)
    wstate = runtime.pid_state(wpid)
    return {
        "sandbar_version": ver,
        "version_error": ver_err,
        "server": {"pid": spid, "state": sstate, "port_open": sport, "ui_port_open": uport},
        "worker": {"pid": wpid, "state": wstate},
        "console": {"port": paths.console_port,
                    "present": console_mod.probe_console(paths.console_port)},
    }


def cmd_status(paths: InstallPaths, log=print, as_json: bool = False) -> int:
    facts = gather_status(paths)
    if as_json:
        log(json.dumps(facts, ensure_ascii=False, indent=2))
        return 0
    if facts["version_error"]:
        _log_line(log, "[红] VERSION：%s" % facts["version_error"])
    s = facts["server"]
    if s["state"] == runtime.ALIVE and s["port_open"]:
        sline = "server：运行中（pid=%d，gRPC %d %s，UI %d %s）" % (
            s["pid"], paths.server_port, _openmark(s["port_open"]),
            paths.ui_port, _openmark(s["ui_port_open"]))
    elif s["state"] == runtime.EPERM:
        sline = "server：pid=%d 在位但权限不足（需人工判读）" % s["pid"]
    elif s["port_open"]:
        sline = ("server：端口 %d 开但安装器 pidfile 无活 pid——孤儿/supervisor 面，"
                 "up/down 会走认领或报告路径" % paths.server_port)
    else:
        sline = "server：未运行"
    _log_line(log, sline)
    w = facts["worker"]
    if w["state"] == runtime.ALIVE:
        wline = "worker：运行中（pid=%d）" % w["pid"]
    elif w["state"] == runtime.EPERM:
        wline = "worker：pid=%d 在位但权限不足（需人工判读）" % w["pid"]
    else:
        wline = "worker：未运行"
    _log_line(log, wline)
    _log_line(log, console_mod.describe(facts["console"]["port"],
                                        facts["console"]["present"]))
    return 0


def _openmark(b: bool) -> str:
    return "开" if b else "关"
