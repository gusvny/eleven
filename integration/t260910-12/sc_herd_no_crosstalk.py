#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：并发 N=6 套件起台零端口重叠零互相拆台（灰盒 L3，工单验收①）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 六路 ensure 真同时发车（各自 compose 工程名，temporal-only 档）全成功；
- 端口两两不相交、∉ 禁产硬集 {3099,3199,7233,8233,17233,18233}、全落档位窗
  [21000,25000)、各台 temporal 端口全程 TCP 可连；
- **持有期内二次 ensure=幂等复用**（reused=true 且 container_ids 与首起一致）
  ——「同 compose 项目二次起台挤掉健康台」（背景 run L/M/O 族）在 herd 风暴
  窗根治的用户级证据；
- 持有腿在场观测（pgrep -f CLI 子命令行，进程表公开观测面）；
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
    check,
    cli,
    compose_containers,
    docker_present,
    ensure_leg,
    ensure_up,
    env_guard,
    envfail,
    finish,
    guarded_down,
    hold_pids,
    port_set,
    stage_tag,
    tcp_open,
)

FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}
BAND_LO, BAND_HI = 21000, 25000
N = 6
TAG = stage_tag("t26091012-herd")  # 泳道唯一化（跨泳道同项目名互拆根治）


def spawn_ensure(project):
    """并发发车：ensure 子进程（不等待；共享缺省锁根纪律，不设 LOCK_DIR）。"""
    env = dict(os.environ)
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
    if not docker_present():
        envfail("docker 缺席——并发租约化起台面不可验（启动 Docker/OrbStack 后重试）")
        finish()
    projects = ["%s-%d" % (TAG, i) for i in range(N)]
    try:
        procs = [spawn_ensure(p) for p in projects]
        results = []
        for project, proc in zip(projects, procs):
            out, err = proc.communicate(timeout=960)
            env_guard(err, "%s 起台腿" % project)
            results.append((project, proc.returncode, out, err))

        # 起台腿三态归属（t260913-01 仲裁修，同族 t260912-02 up_ok 口径）：环境拒跑
        # （rc=2/3）记 ENV_FAIL 且**下游腿一并 not-checked**，不与产品契约混账。
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
                    "下游端口/幂等腿一并 not-checked（环境面，非产品红）"
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
        # 持有腿在场（进程表公开观测面）+ 台可服务 + 容器实盘与回报一致
        ids1 = {}
        for project, st in states.items():
            temporal = (st.get("ports") or {}).get("temporal")
            check(bool(temporal) and tcp_open(temporal),
                  "%s temporal 端口活（%s）" % (project, temporal))
            check(bool(hold_pids(project)), "%s 持有腿进程在场" % project)
            ids1[project] = sorted(st.get("container_ids") or [])
            check(ids1[project] != [] and ids1[project] == sorted(compose_containers(project)),
                  "%s 租约 container_ids 与 docker 实盘一致" % project)

        # 持有期内二次 ensure=幂等复用（互拆根治证据面）
        for project in projects[:2]:
            proc, st2 = ensure_up(project, timeout=300)
            check(proc.returncode == 0 and st2 is not None and bool(st2.get("reused")),
                  "%s 持有期内二次 ensure=幂等复用" % project)
            check(sorted((st2 or {}).get("container_ids") or []) == ids1[project],
                  "%s 二次 ensure 容器 id 与首起一致（未重建）" % project)
    finally:
        guarded_down(projects)

    for project in projects:
        check(not compose_containers(project), "%s 终态零残留" % project)
        check(not hold_pids(project), "%s 持有腿已收割" % project)
    finish()


if __name__ == "__main__":
    main()
