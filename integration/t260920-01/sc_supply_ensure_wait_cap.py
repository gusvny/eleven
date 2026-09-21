#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01 场景③：ensure 争用等待的预算封顶 + 点名（灰盒 L2，离线注入）。

用户场景（epic stage-ops 背景③实案）：多泳道并行跑批撞同一套共享台 → 后到者在
ensure 锁/翻面/心跳等待上硬等（界=CLI timeout 缺省 600s），等待期零进度——
「在等谁、已等多久、为何未就绪」全不可知，最终以「装配超时」整段炸掉。

收口后用户可感知行为（工单要求②③）：
  W1 争用形态（他人持台锁）→ 预算内诚实红 exit 2（绝不硬等 600s）、stderr 点名
     （在等的项目/锁 + 已等秒数）、**真持有者零波及**（不误杀别人的台、不抢锁）；
  W2 无争用形态 → 行为不变（锁立得，照常走到下一道门；下一道门用 PATH 注入的
     立即失败假 docker 钉语义=既有 ENV_FAIL 快速红点名 docker——预算旋钮只作用
     于等别人的路径，健康/无争用路径零代价，回归锚；不依赖真 daemon 状态）；
  W3 场景收尾后锁可复抢（自己不留残留锁、sleeper 清场，资源纪律）。
断言只锚 CLI 进程级公开行为（退出码/stderr 文案/墙钟/锁可用性/进程表），不锚
内部实现。区分锚=墙钟：预算封顶（秒级）与旧 CLI 超时形态（本场景 --timeout 8s）
在墙钟上机械可辨——预算旋钮生效即墙钟贴预算，旋钮不生效即墙钟贴 --timeout。

与既有资产 intent 分工（防重复声明）：
  · t260910-12 L1 电池（test_stage_docker.py，假 docker shim）锁锁获取有界等待
    与 ensure 状态机函数行为；t260910-12 场景族锁 herd/保险丝/租约回收——均无
    「争用等待预算旋钮 + 等待期进度点名」对象（本票新增面）；
  · 场景②（daemon-probe）锁等 daemon 面，本条锁等别人持台面——同票两等待对象
    不同面（daemon 未就绪 vs 同项目锁/翻面被占）。
注入形态：SANDBAR_STAGE_LOCK_DIR 指 tmp 隔离锁根（绝不触真 /tmp/sandbar-test-
stages）+ python 子进程 fcntl.flock 持 ensure-<project>.lock（真持有者语义）+
预算 env 旋钮调小 + --timeout 8 兜底（实现前防卡 600s）。纯离线零 docker 依赖、
无 ENV_FAIL 腿（争用红是被测行为，不是环境缺失）。
实现落地前红属预期（TDD 信号：W1 墙钟腿红=W2 既有行为绿），arbitrate/merge 期
必须绿。
跑法：python3 -B integration/t260920-01/sc_supply_ensure_wait_cap.py
"""
import fcntl
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

PROJECT = "t26092001-cap"
LOCK_NAME = "ensure-%s.lock" % PROJECT
BUDGET_S = "2"          # 预算旋钮（实现后墙钟贴 2s）
CLI_TIMEOUT_S = "8"     # --timeout 兜底（实现前防卡 600s；墙钟上与预算可辨）

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def run_ensure(lock_root, extra_env=None, timeout_s=60):
    env = dict(os.environ)
    env["SANDBAR_STAGE_LOCK_DIR"] = str(lock_root)
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = BUDGET_S
    env.update(extra_env or {})
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, "integration/stage_docker.py", "ensure",
         "--project", PROJECT, "--services", "temporal",
         "--timeout", CLI_TIMEOUT_S],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s, env=env)
    return p, time.time() - t0


def inject_dead_docker(env):
    """PATH 前置立即失败的假 docker：无争用路径的「下一道门」（gates docker
    在场门）秒级可判红，不依赖真 daemon 状态——daemon 假死/缺席机器上真 docker
    调用会把 sweep 的逐台接触拖成 20s×N（260920 本泳道 daemon 假死实况实测），
    注入保证本场景在任何环境可判定。"""
    bindir = lock_root_unused[0] / "fakedocker"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "docker"
    if not fake.exists():
        fake.write_text("#!/bin/sh\necho fake-docker-unavailable >&2\nexit 1\n",
                        encoding="utf-8")
        fake.chmod(0o755)
    env = dict(env)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    return env


lock_root_unused = [None]  # inject_dead_docker 的注入目录锚（enter 后赋值）


lock_root = Path(tempfile.mkdtemp(prefix="t26092001-cap-"))
lock_root_unused[0] = lock_root
lock_path = lock_root / LOCK_NAME
sleeper = None
try:
    # ---- W1 争用腿：真持有者持锁 → 预算内 exit 2 + 点名 + 持有者零波及 ----
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
       "W0 前置：真持有者已 flock 持锁（got: %r）" % held[:20])
    p, wall = run_ensure(lock_root)
    combined = (p.stdout or "") + (p.stderr or "")
    ok(p.returncode == 2,
       "W1 争用形态 exit 2 诚实红（got rc=%s）" % p.returncode)
    ok(wall < 6,
       "W1b 预算封顶生效：墙钟贴预算 %.1fs 级而非 CLI 超时 %ss（wall=%.1fs）"
       % (int(BUDGET_S), CLI_TIMEOUT_S, wall))
    ok(PROJECT in combined, "W1c 点名在等谁（项目/锁名在场）")
    ok(re.search(r"\d+", combined) is not None, "W1d 点名已等多久（秒数在场）")
    ok(sleeper.poll() is None,
       "W1e 真持有者零波及（不误杀不抢锁，got poll=%r）" % sleeper.poll())

    # ---- W3 收尾清场 + 锁可复抢（自己不残留） ----
    if sleeper.poll() is None:
        sleeper.kill()
        sleeper.wait(timeout=10)
    # 锁已释放：下一次 ensure 不再有争用（落到无争用路径，快速到下一道门；
    # 假 docker 注入钉门语义，见 inject_dead_docker）
    p2, wall2 = run_ensure(lock_root, extra_env=inject_dead_docker({}))
    ok(p2.returncode == 2 and wall2 < 15,
       "W3 释放后锁可复抢：无争用路径快速到下一道门（wall=%.1fs，rc=%s）"
       % (wall2, p2.returncode))

    # ---- W2 无争用腿（回归锚）：行为不变，预算不误伤无争用路径 ----
    p3, wall3 = run_ensure(lock_root, extra_env=inject_dead_docker({}))
    combined3 = (p3.stdout or "") + (p3.stderr or "")
    ok(p3.returncode == 2,
       "W2 无争用形态仍诚实红（got rc=%s）" % p3.returncode)
    ok("docker" in combined3,
       "W2b 无争用红点名家门（docker 不可用=下一道门，got tail: %s）"
       % combined3[-200:].replace("\n", " "))
    ok(wall3 < 15, "W2c 无争用路径零预算代价（wall=%.1fs）" % wall3)
finally:
    if sleeper is not None and sleeper.poll() is None:
        sleeper.kill()
        try:
            sleeper.wait(timeout=10)
        except Exception:
            pass
    shutil.rmtree(lock_root, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
