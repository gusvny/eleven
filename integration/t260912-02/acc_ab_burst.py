#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 A+B：并发 32 台 32/32 零超时墙钟 ≤60s；fully subnetted 零复发
且逐台网络子网 ∈ 受管网段表（B 的常跑回归网另在 sc_stage_docker_parallel_zero_residue）。

A 轮=32×dsh（与 create_plan 一致），48 轮=48×temporal（允许排队、不得有非环境失败）。
生产拓扑：缺省锁根+缺省档位窗（不隔离——保险丝计数与受管网段在真共享面受检）。
打印实际发起数对账（防「脚本自己少发」）、boot 挂点清扫耗时行、容器出网探针一行
（review 风险项：10.213/16 撞 VPN 时好归因；探针失败=环境记录行，不作产品断言）。

结构纪律：main 全程 try/finally 兜底拆台（工程名确定性可推导——崩溃路径也零残留，
acc_ab 首跑探针 uncaught 超时炸掉 finally 的教训）。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration", "t260910-12"))
from lib_herd_case import (  # noqa: E402
    DAEMON_ENV_PAT, check, compose_containers, docker_present, envfail,
    finish, guarded_down, stage_tag,
)
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

TAG = stage_tag("t26091202-ab")
WALL_BUDGET_S = 60


def launch_burst(n, services, tag_prefix):
    """n 路真并发 up（Popen 同时发车），返回 (结果列表, 墙钟秒, 发起数)。"""
    procs = []
    since = time.time()
    for i in range(n):
        proj = "%s-%s-%02d" % (TAG, tag_prefix, i)
        procs.append((proj, subprocess.Popen(
            [sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
             "up", "--project", proj, "--services", services, "--timeout", "900"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO)))
    launched = len(procs)
    results = []
    for proj, proc in procs:
        try:
            out, err = proc.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = "", "communicate 超时（外层 900s）"
        results.append({"project": proj, "rc": proc.returncode, "out": out, "err": err})
    return results, time.time() - since, launched


def outbound_probe(project):
    """容器出网探针（记录行，非断言）。探针自身任何失败=「探针不可用」记录，不炸。"""
    try:
        names = subprocess.run(
            ["docker", "ps", "--filter",
             "label=com.docker.compose.project=%s" % project,
             "--filter", "label=com.docker.compose.service=dsh",
             "--format", "{{.Names}}"], capture_output=True, text=True,
            timeout=15).stdout.split()
        if not names:
            return "（无在跑容器可探）"
        probe = subprocess.run(
            ["docker", "exec", names[0], "sh", "-c",
             "wget -q -T 3 -O- http://1.1.1.1 >/dev/null 2>&1 && echo OUT_OK "
             "|| echo OUT_BLOCKED"],
            capture_output=True, text=True, timeout=12)
        return "rc=%s out=%s" % (probe.returncode, (probe.stdout or "").strip())
    except (subprocess.SubprocessError, OSError) as e:
        return "探针不可用（%s: %s——环境事实，不作产品断言）" % (type(e).__name__, e)


def main():
    if not docker_present():
        envfail("docker 缺席——并发台阶梯不可验")
        finish()
    # 确定性工程全集（发车前先定，finally 兜底不依赖中途变量）
    all_projects = (["%s-d32-%02d" % (TAG, i) for i in range(32)]
                    + ["%s-t48-%02d" % (TAG, i) for i in range(48)])
    res32 = res48 = []
    wall32 = wall48 = -1.0
    launched32 = launched48 = 0
    try:
        print("== A 轮：并发 32×dsh（预算墙钟 ≤%ds）==" % WALL_BUDGET_S, flush=True)
        res32, wall32, launched32 = launch_burst(32, "dsh", "d32")
        print("实际发起 %d 路（对账 32）" % launched32, flush=True)
        check(launched32 == 32, "A 轮实际发起数=32（对账）")
        ok32 = [r for r in res32 if r["rc"] == 0]
        check(len(ok32) == 32, "A 32/32 成功（实得 %d/32）" % len(ok32))
        check(wall32 <= WALL_BUDGET_S, "A 墙钟 %.1fs ≤ %ds" % (wall32, WALL_BUDGET_S))
        env_hits = [r["project"] for r in res32
                    if r["rc"] != 0 and DAEMON_ENV_PAT.search(r["err"] or "")]
        if env_hits:
            print("ENV_FAIL 环境类失败点名（不算产品红，但本环境红仍使 A 不达）：%s"
                  % env_hits, flush=True)
        for r in res32:
            if r["rc"] != 0:
                print("  红样本 %s rc=%s：%s" % (r["project"], r["rc"],
                                                " ".join((r["err"] or "").split())[:160]),
                      flush=True)
        sweep_lines = [ln for r in res32 for ln in (r["err"] or "").splitlines()
                       if ln.startswith("[stage-sweep]")]
        print("boot 挂点清扫行（首 3 条）：%s"
              % (sweep_lines[:3] or ["（本轮无判拆/报告项——安静）"]), flush=True)

        print("== B 子用例：fully subnetted 零复发 + 网段 ∈ 受管表 ==", flush=True)
        merged = "\n".join((r["out"] or "") + (r["err"] or "") for r in res32)
        check("fully subnetted" not in merged, "A 轮 stdout/stderr 无 fully subnetted")
        ev = subprocess.run(["docker", "events", "--since",
                             "%d" % (time.time() - max(int(wall32), 2) - 120),
                             "--until", "%d" % time.time(),
                             "--filter", "type=network"],
                            capture_output=True, text=True, timeout=60)
        check("fully subnetted" not in (ev.stdout or "") + (ev.stderr or ""),
              "docker events（network 面）无 fully subnetted")
        table = set(sd.net_table())
        bad = []
        for r in ok32:
            p = subprocess.run(["docker", "network", "inspect",
                                sd.NET_NAME_FMT % r["project"], "--format",
                                "{{(index .IPAM.Config 0).Subnet}}"],
                               capture_output=True, text=True, timeout=15)
            sub = (p.stdout or "").strip()
            if sub not in table:
                bad.append((r["project"], sub))
        check(not bad, "A 轮 %d 台网络子网全部 ∈ 受管网段表（越表=%s）"
              % (len(ok32), bad or "无"))
        print("出网探针（记录行）：%s" % outbound_probe(ok32[0]["project"] if ok32 else ""),
              flush=True)

        print("== 第二轮：并发 48×temporal（不得有非环境失败）==", flush=True)
        res48, wall48, launched48 = launch_burst(48, "temporal", "t48")
        print("实际发起 %d 路（对账 48），墙钟 %.1fs" % (launched48, wall48), flush=True)
        check(launched48 == 48, "48 轮实际发起数=48（对账）")
        bad48 = [r for r in res48
                 if r["rc"] != 0 and not DAEMON_ENV_PAT.search(r["err"] or "")]
        env48 = [r for r in res48
                 if r["rc"] != 0 and DAEMON_ENV_PAT.search(r["err"] or "")]
        check(not bad48, "48 轮无非环境类失败（非环境红=%s）"
              % ([r["project"] for r in bad48] or "无"))
        print("48 轮环境类失败（不计产品红）：%s" % ([r["project"] for r in env48] or "无"),
              flush=True)
    finally:
        guarded_down(all_projects)
        left = [p for p in all_projects if compose_containers(p)]
        check(not left, "两轮全部拆净零残留（剩 %s）" % (left or "无"))
    finish()


if __name__ == "__main__":
    main()
