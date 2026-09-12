#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 E：保险丝。缺省 100 显式断言（C7）；注入失控循环（200 路并发
起台，SANDBAR_STAGE_MAX_STAGES=4 代理）必须刹停并逐条点名，损害有界：
容器 ≤ 保险丝值、失败路零租约零容器、无孤儿 hold、终态清零。

隔离锁根 + SANDBAR_STAGE_SWEEP=off（E 只测保险丝面，不让清扫腿掺和计时）。
200 路的失败输出全量落盘 out/ 目录（逐条点名证据，不截断）。
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
    check, cli, compose_containers, docker_present, envfail, finish,
    guarded_down, stage_tag,
)
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

TAG = stage_tag("t26091202-e")
ROOT = "/tmp/sandbar-t26091202-e"
OUT = os.path.join(REPO, "out", "t26091202-e")
ENV = {"SANDBAR_STAGE_LOCK_DIR": ROOT, "SANDBAR_STAGE_MAX_STAGES": "4",
       "SANDBAR_STAGE_SWEEP": "off"}
N = 200


def main():
    # 腿0（C7 显式断言）：缺省值=100（独立净 env 进程内断言，防回落 12）
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import stage_docker as sd; "
         "assert sd.max_stages() == 100, sd.max_stages(); print('DEFAULT=100')" % (
             os.path.join(REPO, "integration"))],
        capture_output=True, text=True, timeout=30, cwd=REPO,
        env={k: v for k, v in os.environ.items() if k != "SANDBAR_STAGE_MAX_STAGES"})
    check(probe.returncode == 0 and "DEFAULT=100" in probe.stdout,
          "C7 缺省保险丝=100（显式断言，非输出观察）")

    if not docker_present():
        envfail("docker 缺席——失控循环样本不可验")
        finish()
    os.makedirs(ROOT, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    winners, losers = [], []
    procs = []
    try:
        t0 = time.time()
        for i in range(N):
            proj = "%s-%03d" % (TAG, i)
            procs.append((proj, subprocess.Popen(
                [sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                 "up", "--project", proj, "--services", "temporal", "--timeout", "900"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO,
                env=dict(os.environ, **ENV))))
        for proj, proc in procs:
            try:
                out, err = proc.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = "", "communicate 超时"
            rec = {"project": proj, "rc": proc.returncode, "out": out, "err": err}
            if proc.returncode == 0:
                winners.append(rec)
            else:
                losers.append(rec)
        dur = time.time() - t0
        print("200 路发毕：赢 %d / 刹停 %d（%.1fs）；明细落 %s"
              % (len(winners), len(losers), dur, OUT), flush=True)
        for r in losers:
            with open(os.path.join(OUT, os.path.basename(r["project"]) + ".err"), "w") as f:
                f.write(r["err"] or "")
        check(launched_accounting(N, winners, losers), "对账：赢+刹停=%d（实发 %d）"
              % (len(winners) + len(losers), N))
        check(len(winners) == 4, "保险丝=4：恰 4 路入位（实得 %d）" % len(winners))
        check(all(r["rc"] == 2 for r in losers),
              "刹停路全部 rc=2（env 语义；反例=%s)"
              % [r["project"] for r in losers if r["rc"] != 2][:5])
        no_name = [r["project"] for r in losers if "起台保险丝" not in (r["err"] or "")]
        check(not no_name, "刹停 196 路逐条点名「起台保险丝」（漏点名=%s）"
              % (no_name[:5] or "无"))
        no_manifest = [r["project"] for r in losers
                       if "活租约清单" not in (r["err"] or "")]
        check(not no_manifest, "刹停红附活租约清单（漏=%s）" % (no_manifest[:5] or "无"))
        check("满员" not in "".join(r["err"] or "" for r in losers),
              "刹停红不含「满员」字样（瞬态白名单负锁，196 路全量查）")
        # 损害有界：容器 ≤ 保险丝值
        containers = sum(len(compose_containers(r["project"]))
                         for r in winners + losers)
        check(containers <= 4, "损害有界：容器 %d ≤ 保险丝 4" % containers)
        # 失败路零租约（capacity 临界区拒绝在写租约之前）
        winner_set = {r["project"] for r in winners}
        stray = [f for f in os.listdir(ROOT)
                 if f.startswith("project-")
                 and f[len("project-"):-len(".json")] not in winner_set]
        check(not stray, "刹停路零租约残留（stray=%s）" % (stray[:5] or "无"))
        # 损害有界（续）：刹停路的 hold 在握手宽限期内自退（hold_wait_s，秒级），
        # 等排空再断言「无孤儿」——首跑断言时机过早（hold 还在宽限等待）的教训。
        drain_deadline = time.time() + 90
        while time.time() < drain_deadline:
            hf = [f for f in os.listdir(ROOT) if f.startswith("holder-")]
            if len(hf) <= len(winners):
                break
            time.sleep(1)
        holder_files = [f for f in os.listdir(ROOT) if f.startswith("holder-")]
        check(len(holder_files) <= 4, "无孤儿 holder pid 文件（%d ≤ 4）"
              % len(holder_files))
        ps = subprocess.run(["pgrep", "-f",
                             "stage_docker.py hold --project %s" % TAG],
                            capture_output=True, text=True, timeout=15)
        hold_pids = [int(x) for x in (ps.stdout or "").split()]
        check(len(hold_pids) <= 4, "无孤儿 hold 进程（本票 %d ≤ 4）" % len(hold_pids))
    finally:
        guarded_down([r["project"] for r in winners],
                     env_extra=ENV)
        # 收割兜底：still-alive hold 进程（winners 的）随 down 自灭；再扫一遍
        subprocess.run(["pkill", "-f", "%s hold --project %s" % (
            os.path.join(REPO, "integration", "stage_docker.py"), TAG)],
            capture_output=True)
        left_all = [r["project"] for r in winners if compose_containers(r["project"])]
        check(not left_all, "终态赢家全部拆净（剩 %s）" % (left_all or "无"))
        shutil.rmtree(ROOT, ignore_errors=True)
    finish()


def launched_accounting(n, winners, losers):
    return len(winners) + len(losers) == n


if __name__ == "__main__":
    main()
