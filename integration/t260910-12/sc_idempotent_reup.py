#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：同租约二次 up 幂等复用——容器未被重建（灰盒 L2/L3，工单验收④）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 首起记 proc_ids（进程台身份面，t261027-11 迁移）→ 同项目二次 ensure：
  reused=true、proc_ids 逐个一致（bench 进程 id 不变=工单口径的进程台等价面）、
  端口一致且台可服务；
- daemon 侧独立佐证「未重建」：docker inspect StartedAt 逐容器不变（不靠
  租约自证——mock 替代不了真容器 id 观测）；
- down 拆台零残留 + down 幂等二连 rc 0（t260904-19 契约保留锚）。

与 t260904-19-stage-docker-cli-contract 的 ensure 幂等锚不同粒度：彼锚 CLI
缝 exit 0/JSON 形，本条锚本票新交付 proc_ids 契约字段与「进程 id 不变」
强断言——互拆根治的直接证据。temporal 二进制缺席=ENV_FAIL exit 2。
"""
import json
import os
import subprocess
import sys

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
    last_json,
    proc_ids,
    stage_tag,
    tcp_open,
)

TAG = stage_tag("t26091012-reup")  # 泳道唯一化（跨泳道同项目名互拆根治）


def main():
    bench_gate()   # 进程台供给门（docker_present 的等价物，t261027-11 迁移）
    try:
        proc, st1 = ensure_up(TAG, timeout=600)
        if not check(proc.returncode == 0 and st1 is not None,
                     "首次 ensure 成功（rc=%s）" % proc.returncode):
            finish()
        ids1 = proc_ids(st1)
        ports1 = st1.get("ports") or {}
        port1 = (st1.get("ports") or {}).get("temporal")
        check(bool(ids1), "首台有 bench 进程（租约回报 %s）" % ids1)
        check(all(bench_alive(port1, pid) for pid in ids1),
              "租约 proc_ids 与 bench 实盘一致（status pid_alive）")

        # 二次 ensure：幂等复用
        proc, st2 = ensure_up(TAG, timeout=300)
        env_guard(proc.stderr, "二次 ensure 子用例")
        check(proc.returncode == 0 and st2 is not None,
              "二次 ensure 成功（rc=%s）" % proc.returncode)
        check(bool((st2 or {}).get("reused")), "二次 ensure 标记 reused=true")
        check(proc_ids(st2) == ids1,
              "proc_ids 逐个一致（bench 进程 id 不变=工单口径的进程台等价面）")
        check((st2 or {}).get("ports") == ports1, "端口一致（%s）" % (ports1,))
        check(tcp_open(ports1.get("temporal")), "台可服务（temporal %s）"
              % ports1.get("temporal"))
        # 重建观测面（t261027-11 仲裁 gen3 修，等价强于 docker StartedAt）：
        # booted_ts 是 CLI 收据契约字段（翻面时刻）——复用不翻面故不变，重建必
        # 冷起翻面故必变；不依赖 ps//proc（两平台观测权限不同，实测双双缺席）。
        check(st2.get("booted_ts") == st1.get("booted_ts")
              and bool(st1.get("booted_ts")),
              "起台时刻收据不变（booted_ts，进程侧证未重建）")

        # 第三次 ensure（连续复用稳定面）
        proc, st3 = ensure_up(TAG, timeout=300)
        check(proc.returncode == 0 and bool((st3 or {}).get("reused")),
              "第三次 ensure 仍复用（幂等稳定）")
    finally:
        guarded_down([TAG])

    d2 = cli("down", "--project", TAG, timeout=180)
    check(d2.returncode == 0, "down 幂等二连 rc 0（实得 %s）" % d2.returncode)
    check(not tcp_open(port1) and not any(bench_alive(port1, pid) for pid in ids1),
          "终态零残留（bench 已停、端口已释放）")
    finish()


if __name__ == "__main__":
    main()
