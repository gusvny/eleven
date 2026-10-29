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
      live TCP endpoint.
  L1  the docker face stays empty: ZERO container-creating docker CLI
      invocations while the lease is live. The observation needs no docker
      daemon: a recording `docker` stand-in sits FIRST on the child's PATH and
      logs every invocation, so "zero containers ran" is read from the product's
      own call face (a container cannot start without invoking the CLI).
      Inspection calls (`docker ps` scans) are named, never hidden, and are not
      containers.
  L2  a malformed backend value cannot silently fall back to docker:
      SANDBAR_STAGE_BACKEND=bogus makes ensure exit non-zero with a named
      error, and the shim still records zero container-creating invocations (a
      silent fallback would re-create the docker dependency this ticket retires).
  L3  down leaves zero residue on BOTH faces, read from the outside: down
      rc=0, a second down is idempotent (rc=0), the ports refuse new binds
      (kernel-level: they are freed), no hold/CLI process for the project
      survives in the process table, and the terminal docker face is still zero
      container-creating invocations.

Re-pointed 2026-10-29 (ticket t261029-76, round run-01M63CEX71YDHNH56E612BX86C):
the premise "a docker daemon is reachable" was retired by host order 261027, so
the old L1/L2/L3 legs that queried `docker ps -a` booked ENV_FAIL on every round
of every tree. The claim they carried is unchanged; only the observation face
moved from the daemon's inventory to the product's own CLI call stream, which is
docker-free and cannot pass while a container is created. Disposition recorded in
integration/retired-premises.json.

Grey-box discipline: assertions bind to the CLI process contract (exit codes,
last-line JSON, stderr), the docker CLI argv vocabulary, TCP/bind probes, and the
process table - never to implementation files or private names. Shared fixture:
integration/t260910-12/lib_herd_case.py (allowed: shared helpers).

Three states: all legs green = PASS exit 0; a broken leg = FAIL exit 1; a
missing bench asset (the temporal binary) or a prepare-type ensure refusal =
ENV_FAIL exit 2. Offline, no browser, never touches the console port (3099) nor
the production Temporal ports (7233/8233).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "..", "t260910-12"))
if INTEG not in sys.path:
    sys.path.insert(0, INTEG)

from lib_herd_case import (  # noqa: E402
    EXIT_CONFLICT, FORBIDDEN_PORTS, can_bind, check, cli, container_calls,
    docker_calls, docker_shim, ensure_leg, envfail, finish, hold_pids, last_json,
    port_set, shim_env, stage_tag, tcp_open,
)
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402

BACKEND_ENV = {"SANDBAR_STAGE_BACKEND": "process"}
BAND_LO, BAND_HI = 21000, 25000


def shim_legs():
    """Install the recording docker stand-in for this run (t261029-76).

    Returns (env_extra, log_path): `env_extra` carries the shim-first PATH and
    the recorder's log path into every CLI child, so the docker CLI face this
    case judges is the very face its children see.
    """
    root = mkdtemp_reclaimed("t26102976-docker-shim-")
    shim_dir, log_path = docker_shim(root)
    env = shim_env(shim_dir, log_path)
    return {"PATH": env["PATH"], "DOCKER_SHIM_LOG": log_path}, log_path


def main():
    PROJECT = stage_tag("t26102711-procbench")
    env_extra, calls_log = shim_legs()

    def child_env(extra=None):
        merged = dict(env_extra)
        merged.update(extra or {})
        return merged

    # ---- L0: process-backend ensure succeeds, ports live in the band ----
    try:
        proc = cli("ensure", "--project", PROJECT, "--services", "temporal",
                   timeout=600,  # SANCTIONED-WAIT: subprocess ceiling (kill-on-expiry), not a sleep
                   env_extra=child_env(BACKEND_ENV))
    except Exception as exc:  # hard guard: subprocess crash is not a contract red
        envfail("ensure leg did not run (child process raised: %s)" % exc)
        finish()
    verdict = ensure_leg(PROJECT, proc.returncode,
                         ((proc.stderr or "").strip().splitlines() or [""])[-1])
    if verdict != "ok":
        finish()
    state = last_json(proc)
    ports = port_set(state)
    check(bool(ports), "process bench reports a non-empty port set (ports key present and parseable)")
    check(all(BAND_LO <= p < BAND_HI for p in ports),
          "every port sits in the band window [%d,%d): %s" % (BAND_LO, BAND_HI, sorted(ports)))
    check(not (ports & FORBIDDEN_PORTS), "no port touches the production hard set %s" % sorted(FORBIDDEN_PORTS))
    check(all(tcp_open(p) for p in ports), "every bench port answers TCP for the whole lease (%s)" % sorted(ports))

    # ---- L1: zero container-creating docker invocations while the lease is live ----
    calls = docker_calls(calls_log)
    creating = container_calls(calls)
    check(creating == [],
          "zero container-creating docker invocations while the lease is live (recorded: %s)"
          % (creating or "none"))
    print("note  docker CLI calls observed (inspections are not containers): %s"
          % (calls or "none"), flush=True)

    # ---- L2: malformed backend value = named red, never a docker fallback ----
    # On a FRESH project the backend is consulted at the boot dispatch, so a
    # bad value must be refused before anything is created. (On a live-lease
    # project ensure takes the reuse short-circuit and never reaches the
    # dispatch - asserting there would test the wrong seam.)
    before = len(docker_calls(calls_log))
    bad = cli("ensure", "--project", PROJECT + "-badbackend", "--services",
              "temporal", timeout=120,  # SANCTIONED-WAIT: subprocess ceiling, not a sleep
              env_extra=child_env({"SANDBAR_STAGE_BACKEND": "bogus-value"}))
    check(bad.returncode not in (0, EXIT_CONFLICT),
          "a malformed backend value is refused (rc=%d, neither 0 nor the conflict tier)" % bad.returncode)
    err = (bad.stderr or "") + (bad.stdout or "")
    check("bogus-value" in err or "backend" in err.lower(),
          "the error names the backend value itself (no 'no X' assertion)")
    after_calls = docker_calls(calls_log)[before:]
    check(container_calls(after_calls) == [],
          "the malformed value did not silently fall back to the docker payload "
          "(container-creating invocations: %s)" % (container_calls(after_calls) or "none"))

    # ---- L3: down leaves zero residue on both faces, reader side ----
    # SANCTIONED-WAIT: subprocess ceiling (kill-on-expiry), not a sleep.
    down = cli("down", "--project", PROJECT,  # SANCTIONED-WAIT: ceiling, kill-on-expiry
               timeout=300, env_extra=child_env(BACKEND_ENV))
    check(down.returncode == 0, "process bench down rc=0")
    down2 = cli("down", "--project", PROJECT, timeout=300,  # SANCTIONED-WAIT: ceiling
                env_extra=child_env(BACKEND_ENV))
    check(down2.returncode == 0, "second down is idempotent, rc=0")
    check(all(can_bind(p) for p in ports),
          "every port is released (kernel re-bind = reader-side evidence, not the stopped process's word)")
    check(hold_pids(PROJECT) == [], "zero surviving hold/CLI process for this project (pgrep -f)")
    check(container_calls(docker_calls(calls_log)) == [],
          "terminal docker face is still zero container-creating invocations")

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
