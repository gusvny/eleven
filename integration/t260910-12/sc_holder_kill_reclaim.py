#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：持有者被杀 → TTL 后回收且不影响他人（灰盒 L3，工单验收②）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 起台 A 后持有子用例进程在场（pgrep -f 匹配 CLI 子命令行，进程表公开观测面）
  → SIGKILL 杀持有子用例；
- 杀后立即起台 B：成功且可服务（他人零波及——杀持有者绝不波及在租台）；
- 注入小 TTL（SANDBAR_STAGE_LEASE_TTL_S 方案注入口，只影响本场景子进程）
  等租约过期（holder 死 + 过期=唯一回收判据，无 docker ps 采样/宽限参与）
  → A 再 ensure=接管重起：proc_ids 更替（旧台回收重建，非复活残台；进程台身份面）、
  非 reused；
- B 全程不受 A 回收影响（端口活、容器 id 不变、持有子用例 pid 不变）；
- 双工程终态零残留、持有子用例全收割。

与 developer L1（假 pid 四象限 UT，shim 面）intent 不同层：本条守真进程被
杀后的真实时间窗（TTL 两条子用例都是真事实：真时钟 + 真进程表）。docker 缺席
=ENV_FAIL exit 2。
"""
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    bench_alive,
    bench_gate,
    check,
    cli,
    ensure_up,
    env_guard,
    envfail,
    finish,
    guarded_down,
    hold_pids,
    proc_ids,
    stage_tag,
    tcp_open,
    wait_until,
)

TAG = stage_tag("t26091012-reclaim")  # 泳道唯一化（跨泳道同项目名互拆根治）
LEASE_TTL_S = "6"
HEARTBEAT_S = "1"
ENV = {"SANDBAR_STAGE_LEASE_TTL_S": LEASE_TTL_S,
       "SANDBAR_STAGE_HEARTBEAT_S": HEARTBEAT_S}
PROJ_A, PROJ_B = "%s-a" % TAG, "%s-b" % TAG


def main():
    bench_gate()   # 进程台供给门（docker_present 的等价物，t261027-11 迁移）
    try:
        proc, st1 = ensure_up(PROJ_A, timeout=600, env_extra=ENV)
        if not check(proc.returncode == 0 and st1 is not None,
                     "A 台起好（rc=%s）" % proc.returncode):
            finish()
        ids1 = proc_ids(st1)
        check(bool(hold_pids(PROJ_A)), "A 持有子用例进程在场（pgrep 观测）")
        hold_a = (hold_pids(PROJ_A) or [None])[0]

        # SIGKILL 杀 A 的持有子用例（进程表公开观测面确认死亡）
        if hold_a:
            os.kill(hold_a, signal.SIGKILL)
        check(wait_until(lambda: not hold_pids(PROJ_A), budget=10),
              "A 持有子用例确认死亡（SIGKILL）")

        # 杀后立即起台 B：他人零波及
        proc, st_b = ensure_up(PROJ_B, timeout=600, env_extra=ENV)
        env_guard(proc.stderr, "B 起台子用例")
        check(proc.returncode == 0 and st_b is not None,
              "杀持有者后 B 起台成功（rc=%s）" % proc.returncode)
        port_b = (st_b or {}).get("ports", {}).get("temporal")
        check(bool(port_b) and tcp_open(port_b), "B 台可服务（temporal %s）" % port_b)
        b_ids = proc_ids(st_b)
        b_hold = (hold_pids(PROJ_B) or [None])[0]

        # 注入 TTL 到期：A 旧租约=过期 AND holder 死 → 接管重建
        time.sleep(int(LEASE_TTL_S) + 3)
        proc, st_a2 = ensure_up(PROJ_A, timeout=600, env_extra=ENV)
        env_guard(proc.stderr, "A 接管子用例")
        check(proc.returncode == 0, "A 再 ensure 成功（rc=%s）" % proc.returncode)
        check(bool(st_a2) and not st_a2.get("reused"),
              "A 死租约不被复用（接管重起）")
        check(proc_ids(st_a2) != ids1 and bool(proc_ids(st_a2)),
              "A bench 进程 id 更替（旧台回收重建，非复活残台）")
        port_a2 = (st_a2 or {}).get("ports", {}).get("temporal")
        a2_ids = proc_ids(st_a2)
        check(tcp_open(port_a2), "A 新台可服务")

        # B 全程不受 A 回收影响
        check(tcp_open(port_b), "B temporal 端口仍活")
        check(all(bench_alive(port_b, pid) for pid in b_ids),
              "B bench 进程 id 不变（零波及——原进程仍活）")
        check((hold_pids(PROJ_B) or [None])[0] == b_hold, "B 持有子用例 pid 不变")
    finally:
        guarded_down([PROJ_A, PROJ_B])

    # 终态零残留（进程台观测面，t261027-11 迁移改名）：down 后租约身份亡、
    # 端口释放——容器计数归 runner 窗口看守。
    check(not tcp_open(port_a2)
          and not any(bench_alive(port_a2, pid) for pid in a2_ids),
          "A 终态零残留（bench 已停、端口已释放）")
    check(not tcp_open(port_b), "B 终态零残留（temporal 端口已释放）")
    check(not hold_pids(PROJ_A) and not hold_pids(PROJ_B), "持有子用例全收割")
    finish()


if __name__ == "__main__":
    main()
