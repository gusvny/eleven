#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-04 共享助手（命名清理①场景族；不带 sc_ 前缀=共享代码，不登记 SCENARIOS）。

提供：三态计数收口（lib_env 之上包一层，fail 优先 env_fail——产品红不被环境红
稀释，run_scenarios C7 同序）、engine 子进程求值（引擎 import 时序在子进程
内现做，shim/解析语义本身就是被测行为）、docker 舞台单点入口转发（stage_docker
CLI 子进程式调用，退出码三态透传）。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
TP = os.path.join(REPO, "server", "engine")
STAGE_DOCKER = os.path.join(INTEG, "stage_docker.py")

import lib_env  # noqa: E402


class Rec(object):
    """腿级计数与退出收口：SUMMARY 行 + 退出码（0 全过 / 1 产品红 / 2 环境红）。"""

    def __init__(self):
        self.passed = self.failed = self.env_failed = self.na = 0

    def check(self, cond, label):
        if cond:
            self.passed += 1
            print("  ok %s" % label, flush=True)
        else:
            self.failed += 1
            print("  FAIL %s" % label, flush=True)
        return bool(cond)

    def env_fail(self, reason):
        self.env_failed += 1
        print("  ENV_FAIL: %s" % reason, flush=True)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
              % (self.passed, self.failed, self.env_failed, self.na), flush=True)
        if self.failed:
            sys.exit(lib_env.EXIT_FAIL)
        if self.env_failed:
            sys.exit(lib_env.EXIT_ENV_FAIL)
        sys.exit(lib_env.EXIT_PASS)


def poc_python():
    """temporalio SDK 优先走 poc venv；两缺=环境红（KI-020③ 族，返回 None）。"""
    # 回落链（t260907-10）：新路径 server/engine 优先，旧 server/dsh/temporal-poc 一轮兼容
    for tp in (os.path.join(REPO, "server", "engine"), TP):
        venv = os.path.join(tp, ".venv", "bin", "python")
        if os.path.exists(venv):
            return venv
    try:
        import temporalio  # noqa: F401
        return sys.executable
    except ImportError:
        return None


def tp_eval(snippet, env_extra=None, args=None, timeout=120, env_replace=False):
    """engine 目录内子进程求值 snippet（sys.path 已指向 TP）。
    返回 (rc, stdout, stderr)；SDK 缺失返回 None（调用方按环境红处理）。
    env_replace=True 时 env_extra 为**完整**子进程环境（不做 overlay）——
    调用方已做父环境净化的场景必须用它，否则剥离键会被 os.environ 放回
    （t260907-10 arbitrate 实证：runner 注入的 SANDBAR_TASK_QUEUE 泳道值
    经 overlay 复活，净化失效）。缺省 False 保持既有 overlay 语义。
    瞬态重试（t260910-12 目标④接线，arbitrate gen2）：台「回报 state=up」
    与 host 侧端口转发实际就绪之间存在缝隙（OrbStack 实证：容器 Up、容器内
    SA 自检过，host 侧 127.0.0.1 连接秒 refused 数秒）——连接类红命中瞬态
    白名单时自动重试一次（分类走 lib_transient_retry 单源，本库不复制名单）；
    重试仍红原样上报不吞不改。"""
    py = poc_python()
    if py is None:
        return None
    if env_replace and env_extra is not None:
        env = dict(env_extra)
    else:
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
    code = "import sys; sys.path.insert(0, %r)\n%s" % (TP, snippet)

    def _run_once():
        try:
            p = subprocess.run([py, "-c", code] + list(args or []), env=env,
                               cwd=TP, capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return (-1, "", "timeout %ss" % timeout)
        return (p.returncode, p.stdout, p.stderr)

    r = _run_once()
    if r[0] != 0:
        combined = (r[1] or "") + (r[2] or "")
        probe = subprocess.run(
            [sys.executable,
             os.path.join(INTEG, "lib_transient_retry.py"), "is-transient"],
            input=combined, capture_output=True, text=True, timeout=30)
        if probe.returncode == 0:
            time.sleep(2)
            r = _run_once()
    return r


def tp_json(snippet, env_extra=None, args=None, timeout=120, env_replace=False):
    """tp_eval 且 stdout 末行 JSON；返回 (obj|None, rc, stdout, stderr)。"""
    r = tp_eval(snippet, env_extra=env_extra, args=args, timeout=timeout,
                env_replace=env_replace)
    if r is None:
        return None, -1, "", "poc venv/SDK 缺失"
    rc, out, err = r
    try:
        return json.loads(out.strip().splitlines()[-1]), rc, out, err
    except Exception:
        return None, rc, out, err


def stage_ensure(project, services="temporal"):
    """stage_docker 单点搭台（CLI 子进程，退出码三态透传）。
    返回 (info_dict|None, errmsg)。环境红由调用方按 ENV_FAIL 收口。"""
    p = subprocess.run([sys.executable, STAGE_DOCKER, "ensure",
                        "--project", project, "--services", services],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        return None, (p.stdout + p.stderr).strip()[-500:]
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]), ""
    except Exception:
        return None, "stage ensure 输出非 JSON：" + (p.stdout + p.stderr).strip()[-300:]


def stage_down(project):
    subprocess.run([sys.executable, STAGE_DOCKER, "down", "--project", project],
                   capture_output=True, text=True, timeout=300)


def stage_endpoint(info):
    """从 ensure 回报 JSON 取 (host, namespace)。
    回报形状={project, services, namespace, ports:{temporal,ui}, ...}
    （ports.temporal 是数字端口，host 固定 127.0.0.1；namespace 是台注册好的
    缺省 namespace——本仓台缺省 suyou-test（测试基建面，naming-compat 在册），
    场景必须用台回报值，不得硬编码 'default'）。形状不符返回 (None, 原因)。"""
    if not isinstance(info, dict):
        return None, "ensure 回报非 dict"
    port = (info.get("ports") or {}).get("temporal")
    ns = info.get("namespace")
    if not port or not ns:
        return None, "回报缺 ports.temporal 或 namespace：%s" % info
    return "127.0.0.1:%s" % port, ns

