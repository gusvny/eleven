#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景④：安装器生命周期用户旅程（黑盒 CLI + fixture 仓注入 + 假 temporal 替身）。

用户旅程契约：up 起 temporal dev server（演练端口探活 + 状态真源 ~/.sandbar/run/
落 pidfile）→ status 报在管且必印「console 属用户操作面，请手动起停」（红线提示
契约）→ 重复 up 幂等（不重复拉起：监听者与 stub 自报 pid 恒为首发进程）→
down 先 worker 后 server（TERM 时间戳红线观测）且终态进程全灭 + run 目录 pid 清空。

隔离（t260903-11 环境无关化）：临时 HOME（状态真源随之隔离）；假 temporal 经
公共旗标 --root 注入 fixture 仓（安装器按 <root>/server/engine/bin/
temporal 定位，PATH 注入是无效缝）；演练端口=自选空闲端口（公共旗标
--server-port/--ui-port，与真 7233/8233 零接触）；幂等观测走 lsof 监听者 +
stub 自报 pid 双面（不数全机进程表——机器全局断言在真环境自带 start-dev 时必假红）。
本场景零 ps 依赖（spawn/幂等/down 全程不读 argv 观测面）。所选端口被占 →
exit 3 环境冲突（不对抗，不放行掩盖——三态 §7.3 环境红走 ENV_FAIL 退 2）。
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import (Fail, cleanup, cli_args, guard_runtime_ports,  # noqa: E402
                           lsof_listeners, make_fixture_root, make_temp_home,
                           pick_free_ports, port_open, run_cli,
                           require_installer_entry, spawn_daemon_term_stub,
                           wait_pid_dead, wait_port, wait_stamp)

RUN_DIR = os.path.join(".sandbar", "run")  # 相对 $HOME


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def main():
    fail = Fail("t260903-10 ④安装器生命周期用户旅程")
    entry = require_installer_entry(fail)
    server_port, ui_port = pick_free_ports(2)
    guard_runtime_ports(fail, (server_port, ui_port))
    tmp, env = make_temp_home()
    try:
        fx = make_fixture_root(tmp, "ok")
        server_stamp = os.path.join(tmp, "server_stamp")
        env["SANDBAR_STUB_STAMP"] = server_stamp           # 安装器拉起的假 temporal 读
        env["SANDBAR_STUB_PORTS"] = "%d,%d" % (server_port, ui_port)
        run_dir = os.path.join(tmp, RUN_DIR)

        def cli(*rest, timeout=90):
            return run_cli(entry, cli_args(fx, server_port, ui_port, *rest), env, timeout=timeout)

        rc, out = cli("up")
        fail.check(rc == 0, "up 零退出（out=%s）" % out.strip()[:160])
        fail.check(port_open(server_port), "up 后演练端口 %d 探活" % server_port)
        server_pidfile = os.path.join(run_dir, "server.pid")
        server_pid = read_text(server_pidfile)
        fail.check(server_pid.isdigit(),
                   "状态真源 ~/.sandbar/run/ 落 server pidfile（实得 %r）" % server_pid)
        alive_pid = read_text(server_stamp + ".alive")
        fail.check(server_pid.isdigit() and alive_pid == server_pid,
                   "pidfile 指向的正是被拉起的 stub（pidfile=%s vs stub 自报=%s）"
                   % (server_pid, alive_pid))

        rc, out = cli("status", timeout=30)
        fail.check(rc == 0, "status 零退出")
        fail.check("console 属用户操作面" in out and "请手动起停" in out,
                   "status 必印 3099 红线提示（只探测只提示）")
        fail.check("运行中" in out, "status 报 server 运行中（out=%s）" % out.strip()[:120])

        rc, out = cli("up")
        listeners = lsof_listeners(server_port)
        fail.check(rc == 0, "重复 up 零退出")
        fail.check(server_pid.isdigit() and listeners == [int(server_pid)]
                   and read_text(server_stamp + ".alive") == server_pid,
                   "重复 up 幂等：%d 监听者恰为首发 stub 且自报 pid 不变（lsof=%s）"
                   % (server_port, listeners))

        # 预置 worker stub（down 按 pidfile 全量停的契约面），观测 down 时序红线。
        # stub 用 double-fork daemon 拓扑（真 worker.py --daemon 同款）：父=场景
        # 进程的 stub 被安装器 TERM 后会成 zombie（场景不 waitpid），安装器
        # os.kill 探活如实报 zombie「需人工介入」——那是拓扑伪影不是实现错。
        worker_pid, worker_stamp = spawn_daemon_term_stub(tmp, "worker_stamp")
        fail.check(bool(worker_pid) and read_text(worker_stamp + ".alive") == str(worker_pid),
                   "worker stub 预置在位（pid=%s）" % worker_pid)
        with open(os.path.join(run_dir, "worker.pid"), "w") as f:
            f.write(str(worker_pid))

        t0 = time.time()
        rc, out = cli("down", timeout=90)
        fail.check(rc == 0, "down 零退出（%0.1fs，out=%s）" % (time.time() - t0, out.strip()[:100]))
        ts_worker = wait_stamp(worker_stamp, timeout=20)
        ts_server = wait_stamp(server_stamp, timeout=20)
        fail.check(ts_worker is not None, "worker stub 收到 TERM（观测点命中）")
        fail.check(ts_server is not None, "server stub 收到 TERM（观测点命中）")
        fail.check(ts_worker is not None and ts_server is not None and ts_worker <= ts_server,
                   "红线：down 先 worker 后 server（worker %.3f ≤ server %.3f）"
                   % (ts_worker or -1, ts_server or -1))
        fail.check(bool(worker_pid) and wait_pid_dead(worker_pid),
                   "down 终态：worker 进程灭（pid=%s）" % worker_pid)
        fail.check(server_pid.isdigit() and wait_pid_dead(int(server_pid)),
                   "down 终态：server 进程灭（pid=%s）" % server_pid)
        fail.check(wait_port(server_port, want_open=False, timeout=10), "down 终态：演练端口释放")
        fail.check(not glob.glob(os.path.join(run_dir, "*.pid")), "down 终态：run 目录 pid 清空")
    finally:
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
