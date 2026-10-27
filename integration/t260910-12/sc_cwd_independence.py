#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：全部 CLI 行为在不同 cwd 下结果一致（灰盒 L2，工单验收⑤）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 同一工程：cwd=仓库根 ensure 起台后，cwd=/tmp 与 cwd=/ 对同项目 ensure
  =幂等复用（reused、proc_ids 与端口和首起完全一致；进程台身份面）——cwd 不改变
  锁根/仓库锚/状态面解析，另一台被起出来（端口漂/容器更替）即红；
- cwd=/ down 拆台成功、零残留；
- 场景文件自身路径全部 __file__ 锚（不受执行 cwd 影响）。

锁根是用户家目录绝对路径、REPO 由 __file__ 推导是现状语义；本票新增
hold 子用例/租约文件/容量闸都挂在同一锁根下——本场景防新代码把任一环
写成 cwd 相对路径（验收⑤「全部 UT/场景在不同 cwd 下结果一致」的 CLI 子用例）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    REPO,
    bench_alive,
    bench_gate,
    check,
    cli,
    env_guard,
    envfail,
    finish,
    guarded_down,
    port_set,
    proc_ids,
    stage_tag,
    tcp_open,
)

A = stage_tag("t26091012-cwd")  # 泳道唯一化（跨泳道同项目名互拆根治）
ALTERNATE_CWDS = ["/tmp", "/"]


def ids_of(state):
    """进程台身份面（t261027-11 迁移）：proc_ids 取代 container_ids——
    租约/幂等语义不变，只有身份载体从容器换成 bench 进程。"""
    return proc_ids(state)


def main():
    bench_gate()   # 进程台供给门（docker_present 的等价物，t261027-11 迁移）

    try:
        p1, st1_raw = cli("ensure", "--project", A, "--services", "temporal", timeout=600), None
        env_guard(p1.stderr, "基线起台子用例")
        import json as _json
        try:
            st1 = _json.loads((p1.stdout or "").strip().split("\n")[-1])
        except (ValueError, IndexError):
            st1 = None
        if not check(p1.returncode == 0 and st1 is not None,
                     "cwd=仓库根 起台成功且回报 JSON"):
            finish()
        ids1, ports1 = ids_of(st1), port_set(st1)

        for cwd in ALTERNATE_CWDS:
            if not os.path.isdir(cwd):
                envfail("备用 cwd 不存在：%s" % cwd)
                continue
            p2 = cli("ensure", "--project", A, "--services", "temporal",
                     timeout=600, cwd=cwd)
            env_guard(p2.stderr, "cwd=%s 复用子用例" % cwd)
            try:
                st2 = _json.loads((p2.stdout or "").strip().split("\n")[-1])
            except (ValueError, IndexError):
                st2 = None
            if check(p2.returncode == 0 and st2 is not None,
                     "cwd=%s 同项目 ensure 成功" % cwd):
                check(bool(st2.get("reused")), "cwd=%s 为幂等复用（reused）" % cwd)
                check(ids_of(st2) == ids1, "cwd=%s bench 进程 id 与首起一致（未另起一台）" % cwd)
                check(port_set(st2) == ports1, "cwd=%s 端口与首起一致" % cwd)
                check(all(tcp_open(v) for v in port_set(st2)), "cwd=%s 台可服务" % cwd)

        p3 = cli("down", "--project", A, timeout=180, cwd="/")
        env_guard(p3.stderr, "cwd=/ 拆台子用例")
        check(p3.returncode == 0, "cwd=/ down 成功")
    finally:
        guarded_down([A])

    # 终态零残留（进程台观测面）：down 后 bench 进程亡 + 端口释放（t261027-11
    # 迁移改名——docker ps 容器计数面由 runner 窗口看守承接，场景内不再查 docker）。
    _port = ((st1 or {}).get("ports") or {}).get("temporal")
    _pid = (ids_of(st1) or [None])[0]
    check(not tcp_open(_port) and not (_pid and bench_alive(_port, _pid)),
          "终态零残留（bench 已停、temporal 端口已释放）")

    finish()


if __name__ == "__main__":
    main()
