#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：并发 N=6 套件起台零端口重叠零互相拆台（灰盒 L3，工单验收①）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 六路 ensure 真同时发车（各自 compose 工程名，temporal-only 档）全成功；
- 端口两两不相交、∉ 禁产硬集 {3099,3199,7233,8233,17233,18233}、全落档位窗
  [21000,25000)、各台 temporal 端口全程 TCP 可连；
- **持有期内二次 ensure=幂等复用**（reused=true 且 proc_ids 与首起一致；进程台身份面）
  ——「同 compose 项目二次起台挤掉健康台」（背景 run L/M/O 族）在 herd 风暴
  窗根治的用户级证据；
- 持有子用例在场观测（pgrep -f CLI 子命令行，进程表公开观测面）；
- 终态：六工程 down 零残留、租约释放（holder 死）。

与 t260904-19 双台隔离场景 intent 不同面：本条锚 herd 风暴窗规模（engine 池
自述产品红阈值上沿 N=6）与持有期幂等稳定。资源口径：6×temporal-only 台，
跑在 run_scenarios 并发窗内（与兄弟场景互为真实负载，竞态压力就是被测面）；
docker 缺席=ENV_FAIL exit 2。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLI = os.path.join(REPO, "integration", "stage_docker.py")
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    bench_alive,
    bench_gate,
    check,
    cli,
    ensure_leg,
    ensure_up,
    env_guard,
    envfail,
    finish,
    guarded_down,
    hold_pids,
    port_set,
    proc_ids,
    stage_tag,
    tcp_open,
)

FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}
BAND_LO, BAND_HI = 21000, 25000
N = 6
TAG = stage_tag("t26091012-herd")  # 泳道唯一化（跨泳道同项目名互拆根治）


def spawn_ensure(project):
    """并发发车：ensure 子进程（不等待；共享缺省锁根纪律，不设 LOCK_DIR）。
    后端注入（t261027-11 仲裁 gen5 修）：本场景与 cli() 同走 process 后端——
    裸 Popen 不经 cli()，缺此注入则六路并发回落 docker 台，与 down 子用例的
    process 后端错位（docker 租约被 process down 诚实空转 rc=0，容器残留）。"""
    env = dict(os.environ)
    env["SANDBAR_STAGE_BACKEND"] = "process"
    return subprocess.Popen(
        [sys.executable, CLI, "ensure", "--project", project,
         "--services", "temporal", "--timeout", "900"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=REPO, env=env)


def parse_state(out):
    """ensure stdout 末行 JSON；解析失败 None（断言面自判）。"""
    try:
        return json.loads((out or "").strip().split("\n")[-1])
    except (ValueError, IndexError):
        return None


def main():
    bench_gate()   # 进程台供给门（docker_present 的等价物，t261027-11 迁移）
    projects = ["%s-%d" % (TAG, i) for i in range(N)]
    try:
        procs = [spawn_ensure(p) for p in projects]
        results = []
        for project, proc in zip(projects, procs):
            out, err = proc.communicate(timeout=960)
            env_guard(err, "%s 起台子用例" % project)
            results.append((project, proc.returncode, out, err))

        # 起台子用例三态归属（t260913-01 仲裁修，同族 t260912-02 up_ok 口径）：环境拒跑
        # （rc=2/3）记 ENV_FAIL 且**下游子用例一并 not-checked**，不与产品契约混账。
        env_legs = []
        for project, rc, out, err in results:
            # 证据尾取两流合并的末段（真实原因在 stdout 的 STAGE_ENV 行；stderr 常只有
            # 降级提示——只取 stderr 会把诊断引错方向）
            tail = " ".join(((out or "") + " " + (err or "")).strip().split())[-160:]
            if ensure_leg(project, rc, tail) == "env":
                env_legs.append(project)
        states = {}
        for project, rc, out, _ in results:
            if rc == 0:
                st = parse_state(out)
                if st is not None:
                    states[project] = st
        if env_legs:
            envfail("六台全部交付租约化 JSON 未验成：%d 台起台环境拒跑（%s）——"
                    "下游端口/幂等子用例一并 not-checked（环境面，非产品红）"
                    % (len(env_legs), "、".join(env_legs)))
            finish()
        if not check(len(states) == N,
                     "六台全部交付租约化 JSON（实得 %d 台）" % len(states)):
            finish()

        # 端口面：两两不相交 + 禁区 + 档位窗 + TCP 活
        all_ports = {}
        for project, st in states.items():
            for port in port_set(st):
                all_ports.setdefault(port, []).append(project)
        dup = {p: ps for p, ps in all_ports.items() if len(ps) > 1}
        check(not dup, "端口两两不相交（重叠 %s）" % dup)
        check(not (set(all_ports) & FORBIDDEN_PORTS),
              "端口 ∩ 禁产硬集 = ∅（工单⑤保留面）")
        check(all(BAND_LO <= p < BAND_HI for p in all_ports),
              "全部端口落档位窗 [%d,%d)（实得 %s）" % (BAND_LO, BAND_HI,
                                                     sorted(all_ports)))
        # 持有子用例在场（进程表公开观测面）+ 台可服务 + 容器实盘与回报一致
        ids1 = {}
        for project, st in states.items():
            temporal = (st.get("ports") or {}).get("temporal")
            check(bool(temporal) and tcp_open(temporal),
                  "%s temporal 端口活（%s）" % (project, temporal))
            check(bool(hold_pids(project)), "%s 持有子用例进程在场" % project)
            ids1[project] = proc_ids(st)
            temporal_port = (st.get("ports") or {}).get("temporal")
            check(ids1[project] != [] and all(bench_alive(temporal_port, pid)
                  for pid in ids1[project]),
                  "%s 租约 proc_ids 与 bench 实盘一致（status pid_alive）" % project)

        # 持有期内二次 ensure=幂等复用（互拆根治证据面）
        for project in projects[:2]:
            proc, st2 = ensure_up(project, timeout=300)
            check(proc.returncode == 0 and st2 is not None and bool(st2.get("reused")),
                  "%s 持有期内二次 ensure=幂等复用" % project)
            check(proc_ids(st2) == ids1[project],
                  "%s 二次 ensure bench 进程 id 与首起一致（未重建）" % project)
    finally:
        guarded_down(projects)

    for project in projects:
        # 终态零残留（进程台观测面，t261027-11 迁移改名）：down 后租约身份亡、
        # 端口释放——容器计数归 runner 窗口看守。
        _st = states.get(project) or {}
        _port = (_st.get("ports") or {}).get("temporal")
        check(_port is not None and not tcp_open(_port)
              and not any(bench_alive(_port, pid) for pid in ids1.get(project, [])),
              "%s 终态零残留（bench 已停、端口已释放）" % project)
        check(not hold_pids(project), "%s 持有子用例已收割" % project)
    finish()


if __name__ == "__main__":
    main()
