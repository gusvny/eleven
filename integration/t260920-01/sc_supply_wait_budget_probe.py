#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01 场景②：供给链 daemon 等待预算 CLI 契约（灰盒 L2，离线注入）。

用户场景（epic stage-ops 背景①③实案）：Docker daemon 假死（「socket 连通但 90s
无回包」当日 3 次）时，供给链若对 daemon 的接触无界，就挂到 900s 段级兜底——
整轮集测被一个等不来的 daemon 硬拖，票面只见「supply 装配超时（>900s）」，无
进度、无预算、不可判。

收口后用户可感知行为（工单要求②③）：
  P1 daemon 假死形态（命令挂住无回包）→ 等待预算内收口（绝不硬等 900s/600s）、
     exit 2 诚实红、stderr 进度点名（在等 docker daemon、已等多久）；
  P2 docker 缺席形态 → 预算内收口红（exit 2）点名 docker，不挂 900s 不静默；
  P3 daemon 健康形态 → exit 0 正常通过（预算只在坏形态介入，健康路径零代价）；
  P4 daemon 命令立即失败形态 → 预算内红点名，不重试风暴；
  P5 预算 env 畸形（非整数等）→ 不崩、健康路径照常通过（回退缺省值的行为面归
     developer L1 数值锁，本场景锁「畸形不炸 + 契约不破」）。
断言只锚 CLI 进程级公开行为（退出码/stderr 文案/墙钟/进程表），不锚内部实现
——契约不变的实现重构不得打破本场景。

与既有资产 intent 分工（防重复声明）：
  · t260904-19 sc_stage_docker_cli_contract 锁 up/down CLI 缝（JSON 形状/幂等/
    docker 缺席红）与 t260910-12 L1 电池锁锁获取有界等待——均为**起台/拆台面**；
    本条锁本票**新增的 daemon 探活预算面**（供给链等 daemon 这一件小事的有界
    化与点名），彼两处无此对象；
  · developer L1 锁 wait_budget_s 纯函数数值与回退方向——本条锁进程级契约。
注入形态：PATH 前置假 docker 脚本（sleep 挂住=daemon 假死模拟 / exit 0=健康 /
exit 1=立即失败）+ 预算 env 旋钮调小；纯离线零 docker 依赖、无 环境用例。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260920-01/sc_supply_wait_budget_probe.py
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def make_fake_docker(td, body):
    """PATH 前置的假 docker：body 为 /bin/sh 脚本体。返回注入后的 env。"""
    bindir = td / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "docker"
    fake.write_text("#!/bin/sh\n%s\n" % body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    return env


def run_probe(env, timeout_s=60):
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, "integration/stage_docker.py", "daemon-probe"],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s, env=env)
    return p, time.time() - t0


def no_leftover_sleep(td):
    """进程表公开观测面：注入目录关联的假 docker/sleep 无残留（资源回收）。"""
    try:
        ps = subprocess.run(["ps", "-eo", "command"], capture_output=True,
                            text=True, timeout=15).stdout
    except Exception:
        return True  # 进程表不可读时不误红（该用例由退出与墙钟锚兜底）
    return str(td) not in ps


td = Path(tempfile.mkdtemp(prefix="t26092001-probe-"))
try:
    # ---- P1 daemon 假死用例：挂住命令 + 预算 2s → 预算内 exit 2 + 进度点名 ----
    env = make_fake_docker(td, "sleep 30")
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = "2"
    p, wall = run_probe(env)
    ok(p.returncode == 2, "P1 假死形态 exit 2（诚实红，got rc=%s）" % p.returncode)
    ok(wall < 15, "P1b 预算内收口不硬等（wall=%.1fs，预算 2s 级）" % wall)
    ok("docker" in (p.stderr or ""), "P1c stderr 点名在等 docker daemon")
    ok(re.search(r"\d+", (p.stderr or "")) is not None,
       "P1d stderr 点名已等时长（秒数在场）")
    ok(no_leftover_sleep(td), "P1e 无残留子进程（超时即回收，资源纪律）")

    # ---- P2 docker 缺席用例：PATH 无 docker → 预算内红点名 ----
    # 契约口径：缺席形态（docker 命令不存在=FileNotFoundError）由实现按「未就绪」
    # 反复探到预算收口（预算内收口=契约内）；「缺席秒级快速红」是体验级改进点，
    # 上报不作为契约断言——本用例注入小预算，断言预算内收口+点名。
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        d for d in env.get("PATH", "").split(os.pathsep)
        if not os.path.exists(os.path.join(d, "docker"))) if env.get("PATH") else ""
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = "2"
    p, wall = run_probe(env)
    ok(p.returncode == 2, "P2 缺席形态 exit 2（got rc=%s）" % p.returncode)
    ok(wall < 15, "P2b 预算内收口不挂（wall=%.1fs，注入预算 2s）" % wall)
    ok("docker" in (p.stderr or ""), "P2c 点名 docker（缺什么说什么）")

    # ---- P3 健康用例：假 docker 正常 → exit 0 无红 ----
    env = make_fake_docker(td, "exit 0")
    p, wall = run_probe(env)
    ok(p.returncode == 0, "P3 健康形态 exit 0（got rc=%s）" % p.returncode)
    ok("ENV_FAIL" not in (p.stdout or "") + (p.stderr or ""),
       "P3b 健康路径零 ENV_FAIL（预算不误伤好形态）")

    # ---- P4 立即失败用例：快速红点名，不重试风暴 ----
    env = make_fake_docker(td, "echo cannot connect >&2\nexit 1")
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = "5"
    p, wall = run_probe(env)
    ok(p.returncode == 2 and wall < 15,
       "P4 立即失败 → exit 2 快速收口（wall=%.1fs，rc=%s）" % (wall, p.returncode))
    ok("docker" in (p.stderr or "") + (p.stdout or ""),
       "P4b 点名 docker（失败原因可读）")

    # ---- P5 预算 env 畸形用例：不崩，健康路径照常通过 ----
    # （畸形回退缺省值后的红面墙钟行为归 developer L1 数值锁；本场景锁「畸形
    # 不炸 + 契约不破」——健康桩下进程正常完成三态生命周期。）
    env = make_fake_docker(td, "exit 0")
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = "abc"
    p, wall = run_probe(env)
    ok(p.returncode == 0, "P5 畸形预算不崩且健康用例照常 exit 0（got rc=%s）" % p.returncode)
    ok(wall < 15, "P5b 畸形预算不挂（wall=%.1fs）" % wall)
finally:
    shutil.rmtree(td, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
