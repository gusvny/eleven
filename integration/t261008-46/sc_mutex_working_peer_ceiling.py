#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-46 场景：ensure 互斥等待的工作对端上限（灰盒 L2，离线注入）。

工单原文：bench ensure mutex budget routinely exceeded → gate runs zero
scenarios, needs a hand-made retry。根因=共享供给台（sandbar-test-integ）的
冷起可以合法地跑满持有者自己的健康窗（DEFAULT_TIMEOUT 600s），而后到者在
ensure-<project>.lock 上只给 120s 基础预算——真实起台例常打穿 → 供给红 →
闸零执行靠手工重试。收口后用户可感知行为：
  C1 争用形态（持锁者的 booting 租约在被续跳=观察到进度）→ 骑到工作对端上限
     （SANDBAR_STAGE_WORKING_PEER_CEILING_S，缺省 660s）才收诚实红 exit 2，
     红文案点名上限旋钮（报错精确纪律：命中哪条界点名哪条）——120s 基础预算
     不再拦腰截断合法冷起；
  C1b 裸持锁者（无租约=无进度）→ 基础预算快速红点名基础预算旋钮（t260920-01
      守卫：上限绝不适用于无进度对端）；
  C2 工作对端按时交付（持锁 3s 后释放）→ 等待者拿锁继续走到下一道门
     （死 docker 注入钉语义），绝不因等待红；
  C3 无争用形态 → 行为不变（锁立得，快速到下一道门，上限旋钮零代价，回归锚）。
断言只锚 CLI 进程级公开行为（退出码/文案/墙钟/锁可用性），不锚内部实现。
注入形态：SANDBAR_STAGE_LOCK_DIR 指 tmp 隔离锁根 + python 子进程 fcntl.flock
真持锁 + 续跳者子进程（进度=观察到的租约续跳；verify gen3 语义）+ 两旋钮调小
（base 2s / ceiling 5s）+ 死 docker PATH 注入钉下一道门。
纯离线零 docker 依赖；booting 翻面等待窗的两层上界（有进度骑上限/无进度基础
预算快速红）归 L1 电池 integration/tests/test_stage_mutex_wait.py（函数级，
真 flock+真租约文件），本条锁进程级消费缝。
分工：t260920-01-supply-ensure-wait-cap 锁「有界+点名+诚实红」旧契约（其
争用分支现同步注入 ceiling=base 保墙钟锚）；本条锁 t261008-46 新增的上限面。
实现已落地（本场景应全绿）；docker 缺席不影响（争用红是被测行为）。
跑法：python3 -B integration/t261008-46/sc_mutex_working_peer_ceiling.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

PROJECT = "t26100846-ceil"
LOCK_NAME = "ensure-%s.lock" % PROJECT
LEASE_NAME = "project-%s.json" % PROJECT
BUDGET_S = "2"
CEILING_S = "5"
CLI_TIMEOUT_S = "600"

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def inject_dead_docker(env):
    """下一道门钉语义：PATH 前置假 docker（daemon-probe 立即失败）——
    锁过之后的行为面用既有 ENV_FAIL 快速红点名 docker，不依赖真 daemon。"""
    shim = env.pop("_SHIM_DIR", None)
    if shim:
        env["PATH"] = shim + os.pathsep + env.get("PATH", "")
    return env


def run_ensure(lock_root, extra_env=None, timeout_s=60):
    env = dict(os.environ)
    env["SANDBAR_STAGE_LOCK_DIR"] = str(lock_root)
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = BUDGET_S
    env["SANDBAR_STAGE_WORKING_PEER_CEILING_S"] = CEILING_S
    env.update(extra_env or {})
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, "integration/stage_docker.py", "ensure",
         "--project", PROJECT, "--services", "temporal",
         "--timeout", CLI_TIMEOUT_S],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s, env=env)
    return p, time.time() - t0


def make_dead_docker_shim(lock_root):
    d = lock_root / "shim"
    d.mkdir(exist_ok=True)
    shim = d / "docker"
    shim.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    shim.chmod(0o755)  # the FILE must be executable — chmod-ing only the dir
    # leaves the shim non-executable, PATH prefix silently falls through to the
    # REAL docker (arbitrate gen0: this made C2a/C3 boot real stages and red
    # them wrongly at rc=0).
    assert os.access(str(shim), os.X_OK), "dead-docker shim not executable"
    return str(d)



def spawn_heartbeater(lock_root, total_s=15):
    """工作对端续跳者（verify gen3 语义：进度=观察到的租约续跳）：写 booting
    租约并以自身 pid 为持有者、周期刷新 heartbeat_ts（hold 分支同款）。"""
    src = lock_root / "heartbeater.py"
    src.write_text(
        "import json, os, sys, time\n"
        "p = sys.argv[1]\n"
        "lease = {'lease_id': 'hb-1', 'project': 'hb',\n"
        "         'holder': {'ticket': 't261008-46', 'pid': os.getpid()},\n"
        "         'state': 'booting', 'services': ['temporal'], 'ports': {},\n"
        "         'subnet': None, 'owner_root': None, 'ts': time.time(),\n"
        "         'heartbeat_ts': time.time(), 'ttl_sec': 30}\n"
        "tmp = p + '.tmp'\n"
        "open(tmp, 'w').write(json.dumps(lease))\n"
        "os.replace(tmp, p)\n"
        "print('hb', flush=True)\n"
        "end = time.time() + float(sys.argv[2])\n"
        "while time.time() < end:\n"
        "    time.sleep(0.5)\n"
        "    lease = json.load(open(p))\n"
        "    lease['heartbeat_ts'] = time.time()\n"
        "    open(tmp, 'w').write(json.dumps(lease))\n"
        "    os.replace(tmp, p)\n", encoding="utf-8")
    return subprocess.Popen([sys.executable, str(src), str(lock_root / LEASE_NAME),
                             str(total_s)], stdout=subprocess.PIPE, text=True)


lock_root = Path(tempfile.mkdtemp(prefix="t26100846-ceil-"))
os.environ["_SHIM_DIR"] = make_dead_docker_shim(lock_root)
lock_path = lock_root / LOCK_NAME
sleeper = None
try:
    # ---- C1 争用：对端在续跳（观察到租约续跳=在干活）→ 骑到上限才红 ----
    sleeper_src = lock_root / "sleeper.py"
    sleeper_src.write_text(
        "import fcntl, sys, time\n"
        "f = open(sys.argv[1], 'w')\n"
        "fcntl.flock(f, fcntl.LOCK_EX)\n"
        "print('held', flush=True)\n"
        "time.sleep(float(sys.argv[2]))\n", encoding="utf-8")
    sleeper = subprocess.Popen(
        [sys.executable, str(sleeper_src), str(lock_path), "90"],
        stdout=subprocess.PIPE, text=True)
    held = sleeper.stdout.readline().strip() if sleeper.stdout else ""
    ok(held == "held" and sleeper.poll() is None,
       "C0 前置：真持有者已 flock 持锁（got: %r）" % held[:20])
    hb = spawn_heartbeater(lock_root)   # 持有者的 booting 租约在被续跳=在干活
    time.sleep(0.6)   # 首次观察到的续跳须落在基础预算窗内
    p, wall = run_ensure(lock_root)
    combined = (p.stdout or "") + (p.stderr or "")
    ok(p.returncode == 2, "C1 预租约争用 exit 2 诚实红（got rc=%s）" % p.returncode)
    ok(wall >= 4.0,
       "C1b 骑过基础预算（2s）到上限：原语义这里已红（wall=%.1fs）" % wall)
    ok(wall < 12.0, "C1c 上限仍是有界红，不硬等（wall=%.1fs，上限 %ss）"
       % (wall, CEILING_S))
    ok("工作对端上限" in combined and "SANDBAR_STAGE_WORKING_PEER_CEILING_S" in combined,
       "C1d 红文案点名命中的界（上限旋钮名在场；got tail: %s）"
       % combined[-200:].replace("\n", " "))
    ok(PROJECT in combined, "C1e 点名在等谁（项目/锁名在场）")
    ok(sleeper.poll() is None, "C1f 真持有者零波及（不误杀不抢锁）")
    if sleeper.poll() is None:
        sleeper.kill()
        sleeper.wait(timeout=10)
    if hb.poll() is None:
        hb.kill()
        hb.wait(timeout=10)
    try:
        (lock_root / LEASE_NAME).unlink()
    except FileNotFoundError:
        pass

    # ---- C1b 裸持锁者（无租约=无观察进度）→ 基础预算快速红（t260920-01 守卫）----
    bare = subprocess.Popen(
        [sys.executable, str(sleeper_src), str(lock_path), "30"],
        stdout=subprocess.PIPE, text=True)
    heldb = bare.stdout.readline().strip() if bare.stdout else ""
    ok(heldb == "held", "C1b 前置：裸持有者持锁且无租约（got: %r）" % heldb[:20])
    pb, wallb = run_ensure(lock_root)
    combinedb = (pb.stdout or "") + (pb.stderr or "")
    ok(pb.returncode == 2, "C1b 裸锁争用 exit 2 诚实红（got rc=%s）" % pb.returncode)
    ok(wallb <= 4.0, "C1b-1 无进度快速收基础预算红 %.0fs，上限不适用（wall=%.1fs）"
       % (int(BUDGET_S), wallb))
    ok("SANDBAR_STAGE_WAIT_BUDGET_S" in combinedb,
       "C1b-2 基础预算红点名基础预算旋钮（与上限红可辨）")
    if bare.poll() is None:
        bare.kill()
        bare.wait(timeout=10)

    # ---- C2 工作对端按时交付：等待者拿锁继续走到下一道门 ----
    sleeper2 = subprocess.Popen(
        [sys.executable, str(sleeper_src), str(lock_path), "3"],
        stdout=subprocess.PIPE, text=True)
    held2 = sleeper2.stdout.readline().strip() if sleeper2.stdout else ""
    ok(held2 == "held", "C2 前置：持有者 3s 后自然释放（got: %r）" % held2[:20])
    hb2 = spawn_heartbeater(lock_root)   # 续跳=对端在干活而非停滞
    time.sleep(0.6)
    p2, wall2 = run_ensure(lock_root, extra_env=inject_dead_docker(dict(os.environ)))
    combined2 = (p2.stdout or "") + (p2.stderr or "")
    ok(p2.returncode == 2 and "docker" in combined2,
       "C2a 持有者交付后走到下一道门=死 docker 快速红（rc=%s, tail: %s）"
       % (p2.returncode, combined2[-120:].replace("\n", " ")))
    ok(wall2 >= 2.0, "C2b 确实等过基础预算窗（原语义这里已红，wall=%.1fs）" % wall2)
    ok(wall2 < 12.0, "C2c 交付后立即拿锁，无上限拖尾（wall=%.1fs）" % wall2)
    if sleeper2.poll() is None:
        sleeper2.kill()
        sleeper2.wait(timeout=10)
    if hb2.poll() is None:
        hb2.kill()
        hb2.wait(timeout=10)
    try:
        (lock_root / LEASE_NAME).unlink()
    except FileNotFoundError:
        pass

    # ---- C3 无争用回归锚：行为不变，上限旋钮零代价 ----
    p3, wall3 = run_ensure(lock_root, extra_env=inject_dead_docker(dict(os.environ)))
    combined3 = (p3.stdout or "") + (p3.stderr or "")
    ok(p3.returncode == 2 and "docker" in combined3,
       "C3 无争用形态仍诚实红点名 docker（rc=%s）" % p3.returncode)
    ok(wall3 < 6, "C3b 无争用路径零上限代价（wall=%.1fs）" % wall3)
finally:
    for s in (sleeper, bare, sleeper2, hb, hb2):
        if s is not None and s.poll() is None:
            s.kill()
            try:
                s.wait(timeout=10)
            except Exception:
                pass
    shutil.rmtree(lock_root, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
