#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-06 批级共享台看守族的共享助手（前置/基础步骤复用面，非场景）。

绑定面（灰盒铁律：只绑公开契约，不绑实现内部）：
- integration/stage_docker.py CLI（up/ensure/down + t260921-06 新增 ns-acquire/ns-drop，
  形状以其头注契约为锚：ns-acquire 回 JSON {project, namespace, ports, ...}、
  ns-drop 幂等 NotFound=ok、--kind batch 与 --keep 互斥）；
- docker CLI（compose 工程 label / 容器/卷/网计数——工单验收口径点名允许的机械取数面；
  窗口差分按 working_dir label 限定本泳道，gen1 review 条件2）；
- temporal CLI（operator namespace/search-attribute、workflow start/list）；
- run_scenarios.py 执行器公开行为（假表注入=既有手法：SCENARIOS 覆写后直调 main()，
  不经 INTEG_RUN_LOCK——见其池文档「注入式电池不经过本锁」）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]   # 本文件路径→票目录→integration→仓根
INTEG = REPO / "integration"
TICKET_DIR = Path(__file__).resolve().parent
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"

# 自测避撞旋钮（房式惯例 SANDBAR_UT_RUN_SUFFIX）：并发两次同名单独跑会撞
# 工程名/命名空间；手工自测给唯一后缀，闸内缺省零后缀。
RUN_SUFFIX = "".join(ch for ch in os.environ.get("SANDBAR_UT_RUN_SUFFIX", "")
                     if ch.isalnum() or ch in "-_") or ("p%x" % os.getpid())
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def slug_ok(name):
    return bool(PROJECT_RE.match(str(name or "")))


# ---------------------------------------------------------------- 三态框架

class Legs:
    """场景级三态判定（与 lib_env 同词表 pass/fail/env_fail/na；退出码 0/1/2）。"""

    def __init__(self, scenario):
        self.scenario = scenario
        self.rows = []  # (state, name, detail)

    def check(self, name, cond, detail=""):
        self.rows.append(("pass" if cond else "fail", name, "" if cond else str(detail)[:500]))
        print("%s %s%s" % ("ok   " if cond else "FAIL ", name,
                           ("" if cond else " —— %s" % str(detail)[:400])), flush=True)
        return cond

    def env_fail_leg(self, name, reason):
        self.rows.append(("env_fail", name, str(reason)[:500]))
        print("ENV_FAIL(段) %s —— %s" % (name, str(reason)[:300]), flush=True)

    def na_leg(self, name, reason):
        self.rows.append(("na", name, str(reason)[:300]))
        print("N/A: %s（%s）" % (name, reason), flush=True)

    def finish(self):
        n = {"pass": 0, "fail": 0, "env_fail": 0, "na": 0}
        for st, _, _ in self.rows:
            n[st] += 1
        print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
              % (n["pass"], n["fail"], n["env_fail"], n["na"]), flush=True)
        if n["pass"] + n["fail"] + n["env_fail"] == 0 and n["na"] > 0:
            print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题）", flush=True)
            sys.exit(1)
        if n["env_fail"]:
            sys.exit(2)
        if n["fail"]:
            sys.exit(1)
        sys.exit(0)


# ---------------------------------------------------------------- docker 取数

def sh(args, timeout=60, env=None, cwd=None):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          timeout=timeout, env=env, cwd=str(cwd or REPO))


def docker_ok(timeout=25):
    try:
        return sh(["docker", "info"], timeout=timeout).returncode == 0
    except subprocess.SubprocessError:
        return False


def compose_projects_scoped(timeout=60, attempts=3):
    """本泳道全部 compose 工程名；docker 不可达返回 None（调用方按环境红处理）。
    作用域=compose label `working_dir` ∈ {仓根, 仓根/server}（realpath 归一——
    compose 把该 label 写成 compose 文件所在目录，实证=<树>/server 而非树根，
    t260921-06 看守首跑假红 A3 的根因）。daemon 拥堵下 `docker ps` 瞬态超时/
    非零=看守假红源（多泳道同机 30s 窗会不够），预算 60s×重试 3 次带退避——
    只对「命令失败」重试，解析成功即返回（不做结果缓存）。"""
    roots = {str(REPO.resolve()), str((REPO / "server").resolve())}
    for i in range(max(1, attempts)):
        try:
            p = sh(["docker", "ps", "-a", "--format", "{{.Labels}}"], timeout=timeout)
        except subprocess.SubprocessError:
            p = None
        if p is not None and p.returncode == 0:
            names = set()
            for line in (p.stdout or "").splitlines():
                lab = {}
                for kv in line.strip().split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        lab[k] = v
                if lab.get(WORKING_DIR_LABEL) in roots:
                    proj = lab.get("com.docker.compose.project")
                    if proj:
                        names.add(proj)
            return names
        if i < attempts - 1:
            time.sleep(3.0 * (i + 1))   # 退避重试（daemon 拥堵窗通常秒级自恢复）
    return None


def assets_for_project(project):
    """某 compose 工程的容器/卷/网计数（验收口径的机械取数面）。"""
    def count(args):
        try:
            p = sh(args, timeout=30)
            return len([l for l in (p.stdout or "").splitlines() if l.strip()]) if p.returncode == 0 else -1
        except subprocess.SubprocessError:
            return -1
    return {
        "containers": count(["docker", "ps", "-a", "-q",
                             "--filter", "label=com.docker.compose.project=%s" % project]),
        "volumes": count(["docker", "volume", "ls", "-q",
                          "--filter", "label=com.docker.compose.project=%s" % project]),
        "networks": count(["docker", "network", "ls", "-q",
                           "--filter", "label=com.docker.compose.project=%s" % project]),
    }


def container_id(name):
    try:
        p = sh(["docker", "ps", "-a", "-q", "--filter", "name=^%s$" % name], timeout=30)
    except subprocess.SubprocessError:
        return None
    out = (p.stdout or "").strip().splitlines()
    return out[0].strip() if out and p.returncode == 0 else None


# ---------------------------------------------------------------- stage CLI 缝

def stage_cli(args, timeout=180, env=None):
    return sh([sys.executable, "-B", "integration/stage_docker.py"] + list(args),
              timeout=timeout, env=env)


def _json_last_line(text):
    for line in reversed((text or "").strip().splitlines()):
        s = line.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except Exception:
                continue
    return None


def boot_batch(project, timeout=300, env=None):
    """起批台（头注契约：up --kind batch；与 --keep 互斥）。返回 (rc, state, err_tail)。"""
    p = stage_cli(["up", "--project", project, "--kind", "batch",
                   "--services", "temporal"], timeout=timeout, env=env)
    return p.returncode, _json_last_line(p.stdout), ((p.stderr or "") + (p.stdout or ""))[-500:]


def down_stage(project, timeout=180, env=None):
    p = stage_cli(["down", "--project", project], timeout=timeout, env=env)
    return p.returncode, _json_last_line(p.stdout), ((p.stderr or "") + (p.stdout or ""))[-500:]


def ns_acquire(batch, ns, timeout=90, env=None):
    p = stage_cli(["ns-acquire", "--project", batch, "--namespace", ns],
                  timeout=timeout, env=env)
    return p.returncode, _json_last_line(p.stdout), ((p.stderr or "") + (p.stdout or ""))[-500:]


def ns_drop(batch, ns, timeout=90, env=None):
    p = stage_cli(["ns-drop", "--project", batch, "--namespace", ns],
                  timeout=timeout, env=env)
    return p.returncode, _json_last_line(p.stdout), ((p.stderr or "") + (p.stdout or ""))[-500:]


def cleanup_projects(names, note=""):
    """收尾卫生：逐工程 down 兜底（响亮留痕，不抛）——防看守自己留残台。"""
    for proj in sorted(names or []):
        try:
            rc, _, tail = down_stage(proj, timeout=120)
            if rc != 0:
                print("STAGE_ 收尾 down 非零（%s）：%s %s" % (proj, note, tail[:160]),
                      file=sys.stderr, flush=True)
        except Exception as e:  # 清理失败不掩盖段判定，但必须响亮
            print("STAGE_ 收尾 down 异常（%s）：%s: %s %s" % (proj, type(e).__name__, e, note),
                  file=sys.stderr, flush=True)


# ---------------------------------------------------------------- temporal CLI

def temporal_bin():
    exe = os.environ.get("SANDBAR_TEMPORAL_BIN")
    if exe and Path(exe).exists():
        return exe
    lane = REPO / "server" / "engine" / "bin" / "temporal"
    if lane.exists():
        return str(lane)
    try:
        if str(INTEG) not in sys.path:
            sys.path.insert(0, str(INTEG))
        import bench  # noqa: PLC0415
        return str(bench.resolve_temporal_bin())
    except Exception:
        return None


def tcli(args, timeout=45, addr=None):
    cmd = [temporal_bin()] + list(args)
    if addr:
        cmd += ["--address", addr]
    return sh(cmd, timeout=timeout)


# ---------------------------------------------------------------- 临时目录

def mkworkdir():
    return Path(tempfile.mkdtemp(prefix="t26092106-"))


def rmworkdir(path):
    shutil.rmtree(str(path), ignore_errors=True)


def wait_until(fn, deadline_s, interval=2.0):
    """轮询到 fn() 为真或超时；返回 fn() 最终值。"""
    end = time.time() + deadline_s
    while True:
        val = fn()
        if val:
            return val
        if time.time() >= end:
            return False
        time.sleep(interval)
