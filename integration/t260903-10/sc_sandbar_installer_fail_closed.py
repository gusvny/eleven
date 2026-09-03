#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景⑥：依赖故障显式红不静默（§2-#1/#8 fail-closed 家族的 CLI 面）。

用户视角契约：依赖坏了必须红得可诊断——
  A. temporal 可执行缺失 → up 非零且报错点名 temporal（报错精确：说哪个检查失败）；
  B. 假 temporal 秒退（起不来）→ up 在 30s 量级超时内非零退出、显式报错、
     刚拉起的子进程就地回收显式声明（不挂死、不假绿、不留带病进程）；
  C. status 空态（无 pidfile、无进程）→ 零退出、不崩、不误报在管、必印 3099
     红线提示。

隔离（t260903-11 环境无关化）：依赖故障经公共旗标 --root 注入 fixture 仓
（absent/crash 两档），走安装器真实拉起路径（原 PATH 注入是无效缝，秒退路径
从未真正被走到）；演练端口=自选空闲端口。所选端口被占 → exit 3 环境冲突。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import (Fail, cleanup, cli_args, guard_runtime_ports,  # noqa: E402
                           make_fixture_root, make_temp_home, pick_free_ports,
                           run_cli, require_installer_entry)


def main():
    fail = Fail("t260903-10 ⑥依赖故障显式红不静默")
    entry = require_installer_entry(fail)
    server_port, ui_port = pick_free_ports(2)
    guard_runtime_ports(fail, (server_port, ui_port))

    # ---- 半 A：temporal 可执行缺失 ----
    tmp, env = make_temp_home()
    try:
        fx = make_fixture_root(tmp, "absent")
        rc, out = run_cli(entry, cli_args(fx, server_port, ui_port, "up"), env, timeout=60)
        fail.check(rc != 0, "半A：可执行缺失 → up 非零（不静默吞错）")
        fail.check("temporal" in out.lower(), "半A：报错点名 temporal（out=%s）" % out.strip()[:160])
    finally:
        cleanup(tmp)

    # ---- 半 B：假 temporal 秒退（依赖起不来）----
    tmp, env = make_temp_home()
    try:
        fx = make_fixture_root(tmp, "crash")
        t0 = time.time()
        rc, out = run_cli(entry, cli_args(fx, server_port, ui_port, "up"), env, timeout=60)
        elapsed = time.time() - t0
        fail.check(rc != 0, "半B：秒退依赖 → up 非零（out=%s）" % out.strip()[:160])
        fail.check(elapsed < 40, "半B：%0.1fs 内显式失败（30s 量级超时纪律，不挂死）" % elapsed)
        fail.check("回收" in out, "半B：启动超时子进程就地回收显式声明（全终态纪律）")
    finally:
        cleanup(tmp)

    # ---- 半 C：status 空态不崩不误报 ----
    tmp, env = make_temp_home()
    try:
        fx = make_fixture_root(tmp, "absent")
        rc, out = run_cli(entry, cli_args(fx, server_port, ui_port, "status"), env, timeout=30)
        fail.check(rc == 0, "半C：status 空态零退出")
        fail.check(bool(out.strip()), "半C：输出非空（人读状态，out=%s）" % out.strip()[:80])
        fail.check("console 属用户操作面" in out, "半C：空态同样必印 3099 红线提示")
        fail.check("运行中（pid" not in out, "半C：不误报在管（out=%s）" % out.strip()[:120])
    finally:
        cleanup(tmp)

    fail.finish()


if __name__ == "__main__":
    main()
