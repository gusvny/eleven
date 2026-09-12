#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 F：名额不再自我挤压。在册 6 条常驻租约（形态=在飞票控制台台/
供给台）存在的前提下，并发 16 台仍 16/16 绿。负锁腿（证明修复有意义）：同拓扑下
把 SANDBAR_STAGE_MAX_STAGES 压回旧缺省 12 → 16 路中恰 12-6=6 路入位、其余刹停
点名保险丝（旧行为会自我挤压，新缺省不挤）。

常驻租约形态：活 holder（sleep 进程）+ 心跳新鲜 + owner 目录存在但非工作树
（C4b 形态——起台挂点清扫只报告不拆，正好复现「常驻台一直被计数」的生产现实）。
隔离锁根；SANDBAR_STAGE_SWEEP=off 省噪音（常驻租约不被清≠本验收关注面）。
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration", "t260910-12"))
from lib_herd_case import (  # noqa: E402
    check, compose_containers, docker_present, envfail, finish, stage_tag,
)
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

TAG = stage_tag("t26091202-f")
ROOT = "/tmp/sandbar-t26091202-f"
RESIDENT = 6
BURST = 16


def main():
    if not docker_present():
        envfail("docker 缺席——并发 16 台不可验")
        finish()
    os.makedirs(ROOT, exist_ok=True)
    # 锁根纪律（acc_c/acc_d 同款教训）：sd 原语按**进程 env**解析锁根——常驻
    # 租约必须真落在注入面，否则写进生产降级根（泄漏+本场景空转假绿）。
    os.environ["SANDBAR_STAGE_LOCK_DIR"] = ROOT
    c4b_dir = os.path.join(ROOT, "c4b-owner")
    os.makedirs(c4b_dir, exist_ok=True)
    holders = []
    base_env = {"SANDBAR_STAGE_LOCK_DIR": ROOT, "SANDBAR_STAGE_SWEEP": "off"}
    try:
        now = time.time()
        for i in range(RESIDENT):
            pid = subprocess.Popen(["/bin/sleep", "1200"]).pid
            holders.append(pid)
            lease = sd.new_lease("%s-res%d" % (TAG, i), holder_pid=pid,
                                 services=["temporal"], ttl=90)
            lease.update({"state": "up", "heartbeat_ts": now - 1,
                          "owner_root": c4b_dir})
            sd.write_lease("%s-res%d" % (TAG, i), lease)
        print("已注入 %d 条常驻租约（活 holder+新鲜心跳+C4b 形态）" % RESIDENT, flush=True)

        def burst(n, extra_env, tag):
            procs = []
            for i in range(n):
                proj = "%s-%s-%02d" % (TAG, tag, i)
                procs.append((proj, subprocess.Popen(
                    [sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                     "up", "--project", proj, "--services", "temporal",
                     "--timeout", "900"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    cwd=REPO, env=dict(os.environ, **base_env, **extra_env))))
            recs = []
            for proj, proc in procs:
                try:
                    out, err = proc.communicate(timeout=900)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, err = "", "communicate 超时"
                recs.append({"project": proj, "rc": proc.returncode,
                             "out": out, "err": err})
            return recs

        print("== 主腿：缺省保险丝（100）下并发 16 ==", flush=True)
        recs = burst(BURST, {}, "d16")
        ok = [r for r in recs if r["rc"] == 0]
        check(len(ok) == BURST, "F 16/16 绿（实得 %d/16）" % len(ok))
        check(all("起台保险丝" not in (r["err"] or "") for r in recs),
              "主腿零保险丝红（缺省 100 不触）")
        alive = sum(1 for i in range(RESIDENT)
                    if os.path.exists(os.path.join(ROOT, "project-%s-res%d.json" % (TAG, i))))
        check(alive == RESIDENT, "常驻租约全程在场（%d/%d，未被清扫未被动）"
              % (alive, RESIDENT))
        # 负锁腿前置：先拆净主腿 16 台（否则它们的活租约本身就把 12 槽占满，
        # 负锁腿变成 16 自挤 16，测不到「常驻挤掉场景台」的旧语义形态）
        winners_main = [r["project"] for r in ok]
        for proj in winners_main:
            cli_down(proj)
        drain_deadline = time.time() + 30
        while time.time() < drain_deadline and any(
                os.path.exists(os.path.join(ROOT, "project-%s.json" % p))
                for p in winners_main):
            time.sleep(0.5)
        left_main = [p for p in winners_main
                     if os.path.exists(os.path.join(ROOT, "project-%s.json" % p))]
        check(not left_main, "主腿 16 台拆净释放（剩租约=%s）" % (left_main or "无"))

        print("== 负锁腿：压回旧缺省 12 → 恰 6 入位其余刹停 ==", flush=True)
        recs12 = burst(BURST, {"SANDBAR_STAGE_MAX_STAGES": "12"}, "d12")
        ok12 = [r for r in recs12 if r["rc"] == 0]
        stopped = [r for r in recs12 if r["rc"] == 2]
        check(len(ok12) == 6, "旧缺省 12 下恰 12-6=6 路入位（实得 %d）" % len(ok12))
        check(len(stopped) == 10, "其余 10 路刹停（实得 %d）" % len(stopped))
        check(all("起台保险丝" in (r["err"] or "") for r in stopped),
              "刹停路全部点名保险丝")
        check(all(r["rc"] not in (0,) and "满员" not in (r["err"] or "")
                  for r in stopped), "刹停红无「满员」字样（不排队不假红）")
    finally:
        # 清场：拆全部本票台 + 常驻租约 + holder 收割 + 锁根清空
        try:
            projs = []
            for f in os.listdir(ROOT) if os.path.isdir(ROOT) else []:
                if f.startswith("project-") and f.endswith(".json"):
                    projs.append(f[len("project-"):-len(".json")])
            for proj in projs:
                try:
                    cli_down(proj)
                except Exception:  # noqa: BLE001 兜底
                    pass
            for pid in holders:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            subprocess.run(["pkill", "-f", "stage_docker.py hold --project %s" % TAG],
                           capture_output=True)
            shutil.rmtree(ROOT, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            print("WARN 清场异常（原异常继续）：%r" % (exc,), flush=True)
    finish()


def cli_down(proj):
    return subprocess.run(
        [sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
         "down", "--project", proj],
        capture_output=True, text=True, timeout=300, cwd=REPO,
        env=dict(os.environ, SANDBAR_STAGE_LOCK_DIR=ROOT,
                 SANDBAR_STAGE_SWEEP="off"))


if __name__ == "__main__":
    main()
