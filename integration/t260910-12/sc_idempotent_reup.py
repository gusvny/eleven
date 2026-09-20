#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：同租约二次 up 幂等复用——容器未被重建（灰盒 L2/L3，工单验收④）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 首起记 container_ids → 同项目二次 ensure：reused=true、container_ids 逐个
  一致（容器 id 不变=工单原文口径）、端口一致且台可服务；
- daemon 侧独立佐证「未重建」：docker inspect StartedAt 逐容器不变（不靠
  租约自证——mock 替代不了真容器 id 观测）；
- down 拆台零残留 + down 幂等二连 rc 0（t260904-19 契约保留锚）。

与 t260904-19-stage-docker-cli-contract 的 ensure 幂等锚不同粒度：彼锚 CLI
缝 exit 0/JSON 形，本条锚本票新交付 container_ids 契约字段与「容器 id 不变」
强断言——互拆根治的直接证据。docker 缺席=ENV_FAIL exit 2。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    check,
    cli,
    compose_containers,
    docker_present,
    ensure_up,
    env_guard,
    envfail,
    finish,
    guarded_down,
    last_json,
    stage_tag,
    tcp_open,
)

TAG = stage_tag("t26091012-reup")  # 泳道唯一化（跨泳道同项目名互拆根治）


def started_at(container):
    """docker inspect 公开观测面：容器启动时刻（重建即变）。"""
    p = subprocess.run(["docker", "inspect", container, "--format",
                        "{{.State.StartedAt}}"], capture_output=True, text=True,
                       timeout=30)
    return (p.stdout or "").strip()


def main():
    if not docker_present():
        envfail("docker 缺席——幂等复用面不可验（启动 Docker/OrbStack 后重试）")
        finish()
    try:
        proc, st1 = ensure_up(TAG, timeout=600)
        if not check(proc.returncode == 0 and st1 is not None,
                     "首次 ensure 成功（rc=%s）" % proc.returncode):
            finish()
        ids1 = sorted(st1.get("container_ids") or [])
        ports1 = st1.get("ports") or {}
        started1 = {c: started_at(c) for c in compose_containers(TAG)}
        check(bool(ids1), "首台有容器（租约回报 %s）" % ids1)
        check(ids1 == sorted(compose_containers(TAG)),
              "租约 container_ids 与 docker 实盘一致")

        # 二次 ensure：幂等复用
        proc, st2 = ensure_up(TAG, timeout=300)
        env_guard(proc.stderr, "二次 ensure 子用例")
        check(proc.returncode == 0 and st2 is not None,
              "二次 ensure 成功（rc=%s）" % proc.returncode)
        check(bool((st2 or {}).get("reused")), "二次 ensure 标记 reused=true")
        check(sorted((st2 or {}).get("container_ids") or []) == ids1,
              "container_ids 逐个一致（容器 id 不变=工单口径）")
        check((st2 or {}).get("ports") == ports1, "端口一致（%s）" % (ports1,))
        check(tcp_open(ports1.get("temporal")), "台可服务（temporal %s）"
              % ports1.get("temporal"))
        started2 = {c: started_at(c) for c in compose_containers(TAG)}
        check(started2 == started1 and all(started1.values()),
              "StartedAt 逐容器不变（daemon 侧证未重建）")

        # 第三次 ensure（连续复用稳定面）
        proc, st3 = ensure_up(TAG, timeout=300)
        check(proc.returncode == 0 and bool((st3 or {}).get("reused")),
              "第三次 ensure 仍复用（幂等稳定）")
    finally:
        guarded_down([TAG])

    d2 = cli("down", "--project", TAG, timeout=180)
    check(d2.returncode == 0, "down 幂等二连 rc 0（实得 %s）" % d2.returncode)
    check(not compose_containers(TAG), "终态零残留容器")
    finish()


if __name__ == "__main__":
    main()
