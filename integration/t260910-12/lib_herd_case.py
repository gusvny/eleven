#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景共享夹具（integration 岗 design_integration_tests 段）。

三态框架 / daemon 环境红归因 / CLI 子进程调用 / 残留观测，六条场景共用，
避免每份场景复制 80 行样板（前置与基础步骤允许共享——岗位用例设计纪律）。
断言只锚公开面：CLI 进程级行为（退出码 / stdout JSON / stderr STAGE_ 行）、
docker 公开观测面（ps -a 的 compose label / 端口 bind / TCP 可连性）、
进程表公开观测面（pgrep -f 匹配 CLI 子命令行）。实现内部文件与私有命名
不进断言——契约不变的实现重构不得打破场景（灰盒铁律）。
"""
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLI = os.path.join(REPO, "integration", "stage_docker.py")

import hashlib  # noqa: E402


def stage_tag(base):
    """场景台项目名唯一化（arbitrate gen2，跨泳道互拆根治）：compose 项目名是
    docker daemon **全局**可见面，硬编码常量会让并行泳道跑同一场景时互相
    down 掉对方的台（t26091012 泳道 schedule 场景被 t260910-14 泳道拆台，
    docker events 铁证 working_dir=t260910-14）。后缀=本 worktree 路径 hash：
    同 worktree 内稳定（二次跑幂等复用断言不受影响），跨 worktree 不同
    （互拆根治）。场景内部所有项目名都须经本 helper 派生。"""
    return "%s-%s" % (base, hashlib.md5(REPO.encode("utf-8")).hexdigest()[:8])

# 禁产端口硬集（工单保留面⑤：生产 3099/3199/7233/8233 + 缺省台 17233/18233）
FORBIDDEN_PORTS = {3099, 3199, 7233, 8233, 17233, 18233}

# docker daemon 资源类失败特征（t260905-06 归因纪律：环境缺件≠产品红）。
# t260912-02 注：fully subnetted 一支自受管网段落地起**不再是活路径**（建网
# 显式带子网，不走分配器库存），保留为防御性归因——手工直跑 compose/旧期
# 残留仍可能撞池，命中照归环境红，不诬产品。
DAEMON_ENV_PAT = re.compile(
    r"address pools have been fully subnetted"
    r"|no space left on device"
    r"|Cannot connect to the Docker daemon", re.I)

_passed = _failed = _env_failed = 0


def check(cond, label):
    """三态之一：PASS / FAIL。不写 SKIP——环境缺件走 envfail(exit 2)。"""
    global _passed, _failed
    print(("ok    " if cond else "FAIL  ") + label, flush=True)
    if cond:
        _passed += 1
    else:
        _failed += 1
    return bool(cond)


def envfail(label):
    global _env_failed
    _env_failed += 1
    print("ENV_FAIL %s（环境缺件，没验成——原因归环境，exit 2）" % label, flush=True)


def finish():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (_passed, _failed, _env_failed), flush=True)
    sys.exit(2 if _env_failed and not _failed else (1 if _failed else 0))


def env_guard(err, leg="腿"):
    """stderr 命中 daemon 资源类失败 → ENV_FAIL exit 2（点名特征），不吞产品红。"""
    if err and DAEMON_ENV_PAT.search(err):
        envfail("docker daemon 资源类失败（%s…）：%s没验成——归环境供给，清残留容器/网络后自动生效"
                % (" ".join((err or "").strip().split())[:150], leg))
        finish()
    return False


def cli(*args, **kw):
    """stage_docker CLI 子进程调用。拓扑纪律：不设 SANDBAR_STAGE_LOCK_DIR，
    与生产调用方共享缺省锁根（flock 互斥只在共享根下生效）。
    kw: cwd=（默认仓库根）、env_extra=（注入满员/TTL 旋钮等）、timeout=。"""
    cwd = kw.get("cwd", REPO)
    timeout = kw.get("timeout", 900)
    env_extra = kw.get("env_extra")
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, CLI] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=timeout,
                          cwd=cwd, env=env)


def last_json(proc):
    """CLI 末行 JSON 回报；解析失败返回 None（断言面自行判）。"""
    try:
        return json.loads((proc.stdout or "").strip().split("\n")[-1])
    except (ValueError, IndexError):
        return None


def docker_present():
    try:
        return subprocess.run(["docker", "info"], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def compose_containers(project):
    """docker ps -a 按 compose 工程 label 过滤（compose 公开语义）——残留观测面。"""
    p = subprocess.run(["docker", "ps", "-a", "--filter",
                        "label=com.docker.compose.project=%s" % project,
                        "--format", "{{.ID}}"],
                       capture_output=True, text=True, timeout=30)
    return [l for l in (p.stdout or "").split() if l]


def tcp_open(port, timeout=2.0):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def can_bind(port):
    """端口空闲可绑定探测（占用/空闲两态由调用方自证防恒真）。"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def hold_pids(project):
    """持有腿进程观测（pgrep -f 匹配 CLI 子命令名——CLI 面是公开契约，
    不读任何实现内部文件）。无 pgrep 或无命中返回空表。"""
    try:
        p = subprocess.run(["pgrep", "-f",
                            "stage_docker.py hold --project %s" % project],
                           capture_output=True, text=True, timeout=15)
        return [int(x) for x in (p.stdout or "").split() if x.strip().isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def ensure_up(project, services="temporal", timeout=600, **kw):
    """ensure 起台并归因 daemon 环境红。返回 (proc, state_json)。"""
    proc = cli("ensure", "--project", project, "--services", services,
               timeout=timeout, **kw)
    env_guard(proc.stderr, "起台腿")
    return proc, last_json(proc)


def guarded_down(projects, **kw):
    """finally 兜底拆台：无论断言走道，起过的工程不残留（崩溃路径零残留半边）。"""
    for proj in projects:
        try:
            cli("down", "--project", proj, timeout=180, **kw)
        except (OSError, subprocess.SubprocessError):
            pass


def port_set(state):
    """回报 JSON 的端口集合（int 化）；缺 ports 键返回空集（断言面自行判）。"""
    if not state or not isinstance(state.get("ports"), dict):
        return set()
    return {int(v) for v in state["ports"].values() if str(v).strip().lstrip("-").isdigit()}


def wait_until(fn, budget, gap=0.5):
    """有界轮询：fn() 为真即返回 True，超预算返回 False（绝不裸等）。"""
    t0 = time.time()
    while time.time() - t0 < budget:
        if fn():
            return True
        time.sleep(gap)
    return False
