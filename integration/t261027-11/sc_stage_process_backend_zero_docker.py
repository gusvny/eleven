#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261027-11 L3: stage_docker under SANDBAR_STAGE_BACKEND=process is docker-free.

Ticket t261027-11 (host order 261027: retire docker from the test estate a few
cases at a time). The five t260910-12 lease/queue cases migrate onto the
process backend of integration/stage_docker.py. Their own lease/queue/idempotence
contracts stay owned by the migrated cases themselves; THIS scenario uniquely
owns the migration's user-visible outcome, asserted on public faces only:

  L0  a process-backend ensure succeeds: rc=0, the reported ports sit in the
      band window [21000, 25000) minus the forbidden set, and each port is a
      live TCP endpoint. No docker precondition of any kind is consulted.
  L1  the docker face stays empty: `docker ps -a` filtered by this project's
      compose label returns ZERO containers while the lease is live. If the
      docker daemon itself is unreachable the observation cannot be made and
      the scenario exits ENV_FAIL (named) - never a silent green.
  L2  a malformed backend value cannot silently fall back to docker:
      SANDBAR_STAGE_BACKEND=bogus makes ensure exit non-zero with a named
      error, and still zero containers exist for the project (a silent
      fallback would re-create the docker dependency this ticket retires).
  L3  down leaves zero residue on BOTH faces, read from the outside: down
      rc=0, a second down is idempotent (rc=0), the ports refuse new binds
      (kernel-level: they are freed), and no hold/CLI process for the project
      survives in the process table.

Grey-box discipline: assertions bind to the CLI process contract (exit codes,
last-line JSON, stderr), the docker public query face, TCP/bind probes, and
the process table - never to implementation files or private names. Shared
fixture: integration/t260910-12/lib_herd_case.py (allowed: shared helpers).

Three states: all legs green = PASS exit 0; a broken leg = FAIL exit 1;
docker face unobservable or prepare-type ensure refusal = ENV_FAIL exit 2.
Offline, no browser, never touches the console port (3099) nor the production
Temporal ports (7233/8233).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "t260910-12"))

from lib_herd_case import (  # noqa: E402
    EXIT_CONFLICT, FORBIDDEN_PORTS, can_bind, check, cli, compose_containers,
    docker_present, ensure_leg, envfail, finish, hold_pids, last_json, port_set,
    stage_tag, tcp_open,
)

BACKEND_ENV = {"SANDBAR_STAGE_BACKEND": "process"}
BAND_LO, BAND_HI = 21000, 25000

PROJECT = stage_tag("t26102711-procbench")


def main():
    # ---- L0: process-backend ensure succeeds, ports live in the band ----
    try:
        proc = cli("ensure", "--project", PROJECT, "--services", "temporal",  # SANCTIONED-WAIT: subprocess ceiling (kill-on-expiry), not a sleep
                   timeout=600, env_extra=BACKEND_ENV)
    except Exception as exc:  # hard guard: subprocess crash is not a contract red
        envfail("ensure 子用例未跑成（子进程异常：%s）" % exc)
        finish()
    verdict = ensure_leg(PROJECT, proc.returncode,
                         ((proc.stderr or "").strip().splitlines() or [""])[-1])
    if verdict != "ok":
        finish()
    state = last_json(proc)
    ports = port_set(state)
    check(bool(ports), "process 台回报非空端口集（ports 键在场且可解析）")
    check(all(BAND_LO <= p < BAND_HI for p in ports),
          "端口全部落在带宽窗 [%d,%d)：%s" % (BAND_LO, BAND_HI, sorted(ports)))
    check(not (ports & FORBIDDEN_PORTS), "端口不碰禁产硬集 %s" % sorted(FORBIDDEN_PORTS))
    check(all(tcp_open(p) for p in ports), "每台端口全程 TCP 可连（%s）" % sorted(ports))

    # ---- L1: the docker face is empty while the lease is live ----
    if not docker_present():
        envfail("docker 观测面不可达：L1/L2 的『零容器』断言没验成（不假绿）")
        finish()
    check(compose_containers(PROJECT) == [],
          "持有期内本项目 pattern 零容器（docker ps -a 按 compose 工程 label）")

    # ---- L2: malformed backend value = named red, never a docker fallback ----
    # On a FRESH project the backend is consulted at the boot dispatch, so a
    # bad value must be refused before anything is created. (On a live-lease
    # project ensure takes the reuse short-circuit and never reaches the
    # dispatch - asserting there would test the wrong seam.)
    bad = cli("ensure", "--project", PROJECT + "-badbackend", "--services",
              "temporal", timeout=120,  # SANCTIONED-WAIT: subprocess ceiling, not a sleep
              env_extra={"SANDBAR_STAGE_BACKEND": "bogus-value"})
    check(bad.returncode not in (0, EXIT_CONFLICT),
          "非法 backend 值不被接受（rc=%d，非 0/非 conflict 档）" % bad.returncode)
    err = (bad.stderr or "") + (bad.stdout or "")
    check("bogus-value" in err or "backend" in err.lower(),
          "报错点名 backend/取值本身（不断言『没有 X』）")
    check(compose_containers(PROJECT) == []
          and compose_containers(PROJECT + "-badbackend") == [],
          "非法值未静默回落 docker（回落后会出现本工程容器）")

    # ---- L3: down leaves zero residue on both faces, reader side ----
    # SANCTIONED-WAIT: subprocess ceiling (kill-on-expiry), not a sleep.
    down = cli("down", "--project", PROJECT, timeout=300, env_extra=BACKEND_ENV)
    check(down.returncode == 0, "process 台 down rc=0")
    down2 = cli("down", "--project", PROJECT, timeout=300,  # SANCTIONED-WAIT: ceiling
                env_extra=BACKEND_ENV)
    check(down2.returncode == 0, "二次 down 幂等 rc=0")
    check(all(can_bind(p) for p in ports),
          "全部端口已释放（内核可重绑=独立于被停进程自述的读者面证据）")
    check(hold_pids(PROJECT) == [], "进程表零本工程 hold/CLI 幸存者（pgrep -f）")
    check(compose_containers(PROJECT) == [], "终态 docker 面仍零容器")

    # ---- L3b: delayed re-probe (the resurrection face) ----
    # t261027-11 仲裁 gen5 实测：down 回执 clean 后 ~2.5s 端口重新可连——TERM
    # 只杀了 leader，真正的 server 子进程幸存并重新绑定。终态零残留必须是
    # 「时间上的终态」，不是 down 返回那一拍；此处有界等 3s 后复核双面仍死。
    time.sleep(float(os.environ.get("SANDBAR_SCENARIO_RESURRECT_PROBE_S", "3")))  # SANCTIONED-WAIT: bounded resurrect-window probe, injectable
    check(all(not tcp_open(pt) for pt in ports),
          "延迟复核（%ss 后）：端口仍拒连（bench 未复活重绑）"
          % os.environ.get("SANDBAR_SCENARIO_RESURRECT_PROBE_S", "3"))
    check(hold_pids(PROJECT) == [], "延迟复核：进程表仍零本工程幸存者")

    finish()


if __name__ == "__main__":
    main()
