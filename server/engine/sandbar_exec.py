#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sandbar-exec：容器内 agent 进程 supervisor（t260913-04 容器执行面，方案 D3）。

被烤进 agent 镜像 /usr/local/bin/sandbar-exec（build_agent_image.sh 从本文件逐字拷贝），
也是宿主单测的被测对象（mac 上同码可跑——python3 stdlib 自含，无任何仓内依赖）。

契约：sandbar-exec <pgid文件> <cmd...>
  1. 以【新会话】（start_new_session）拉起 cmd —— pgid = 子进程 pid，与外层 docker exec
     的进程空间解耦（runc/OrbStack 对 exec'd 进程的组语义不做假设，这里显式造组）；
  2. 子进程 pid 原子落 <pgid文件>（同目录 tmp+rename）——宿主 reap 据此发组信号
     （对齐 KI-009 killpg 语义：迟写多属孙进程，必须按组收）；
  3. SIGTERM/SIGINT → 转发给子进程组（一层不丢）；
  4. wait 透传子进程 rc（docker exec 客户端 rc = 本进程 rc）；
  5. 全终态回收：正常 / 信号 / 子崩溃 / 自身收信号，finally 兜底（子还在 → 组 KILL）+
     删除 pgid 文件（不留陈旧句柄给下一次 reap 误杀）。

畸形输入纪律：<3 个 argv 或 pgid 目录不可建 → 用法红 exit 64，不留半状态；
cmd 不存在 → exit 127（Popen 异常面），pgid 文件不落。
"""
import os
import signal
import subprocess
import sys
import tempfile

USAGE = "usage: sandbar-exec <pgid-file> <cmd> [args...]"


def _write_pgid_file(path: str, pid: int) -> None:
    """原子落 pgid（同目录 tmp + os.replace，读方只见完整档）。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".pgid-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(pid))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv):
    if len(argv) < 3:
        print(USAGE, file=sys.stderr)
        return 64
    pgid_file, cmd = argv[1], argv[2:]
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
    except OSError as e:
        print("sandbar-exec: 无法启动 %r：%s" % (cmd[0], e), file=sys.stderr)
        return 127
    _write_pgid_file(pgid_file, proc.pid)

    # 信号转发：TERM/INT → 子进程组（子组独立，收到即全树落幕）；不含 KILL——
    # 升级权在宿主 reap（有界 TERM→KILL 节奏归引擎管）。
    forwarded = {"sig": None}

    def _forward(signum, _frame):
        forwarded["sig"] = signum
        try:
            os.killpg(proc.pid, signum)
        except OSError:
            pass  # 组已灭：等 wait 收尸即可

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _forward)
        except (ValueError, OSError):
            pass  # 非主线程注册等边角：保持缺省行为

    try:
        rc = proc.wait()
    except BaseException:
        # 自身被 KILL 等不可捕获终态：兜底组杀再抛回（全终态回收纪律）
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        raise
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.unlink(pgid_file)
        except OSError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
