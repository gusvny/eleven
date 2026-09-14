#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-04 集成测试共享夹具与助手（非 sc_ 前缀＝共享代码，不进 SCENARIOS）。

被测面＝**建票期拒收「整仓根形态」写集条目**（工单 t260915-04，KI-092 事故回归面）：
多仓/单仓项目的建票写集里，条目等于某个仓的根目录（'repo_a' / 'repo_a/'）或项目根
（'.'）在建票期一律拒收并给人话改法；'*'/'**'/空串/哨兵字符形态与运行期闸同口径。

夹具纪律（沿 t260914-01 同款口径）：
- 一切 git 仓/项目注册表在测试 tmp 目录自建，不代用户建仓、不碰真实项目数据；
- 注入优先「真实入口」（ticket.py 库装载 / client.py 子进程），不 mock 引擎函数；
- 红线：Temporal 地址钉不可达桩（127.0.0.1:9），绝不触生产 7233/8233/3099；
  拒收腿发生在连接之前＝零 Temporal 依赖；过闸腿以「连接失败而非拒收」为判别面。

三态契约（t260904-12）：只有 pass/fail/env_fail；环境缺失一律 ENV_FAIL exit 2。
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"
TOOLS = REPO / "server" / "tools"

passed = 0
failed = 0
env_fail_n = 0
na_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)
    return bool(cond)


def env_fail(reason):
    """环境缺失：一律 ENV_FAIL exit 2（本场景无 stdlib 替代腿——真入口子进程/直调）。"""
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)
    sys.exit(2)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (passed, failed, env_fail_n, na_n))
    return 1 if failed else (2 if env_fail_n else 0)


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- git 夹具

def git(args, cwd):
    return subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                          cwd=str(cwd), capture_output=True, text=True, timeout=60)


def git_ok(args, cwd):
    p = git(args, cwd)
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def init_repo(path, files=None, gitignore=()):
    """建基线仓（本地 identity 落地）。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    git(["config", "user.email", "ut@example.invalid"], path)
    git(["config", "user.name", "ut"], path)
    for rel, text in (files or {"README.md": "baseline\n"}).items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    if gitignore:
        (path / ".gitignore").write_text("\n".join(gitignore) + "\n", encoding="utf-8")
    git(["add", "-A"], path)
    git(["commit", "-qm", "baseline"], path)
    return path


def build_mixed_project(base, members=("repo_a", "repo_b")):
    """混合形态项目（dengzhufpv 现场形态：根亦 git 仓 + 子仓并存）。

    根仓 .gitignore 忽略成员仓目录（现场同款，防根仓 status 把成员 worktree
    当未跟踪目录）。members 可注入任意仓名（如 'integration' 做边角夹具）。"""
    root = Path(base) / ("mixed_" + "-".join(members))
    root.mkdir(parents=True, exist_ok=True)
    init_repo(root, files={"docs/kb.md": "kb\n"},
              gitignore=[m + "/" for m in members])
    for m in members:
        init_repo(root / m, files={"src/a.py" if m != "integration" else "run/x.py":
                                   "x = 1\n"})
    return root


def build_single_project(base):
    """单仓项目（根即仓、无子仓——sandbar 自身形态）。"""
    return init_repo(Path(base) / "single", files={"server/engine/x.py": "x = 1\n",
                                                   "README.md": "r\n"})


def build_projects_registry(base, mapping):
    """项目注册表缝夹具（SANDBAR_PROJECTS_DIR 指向；布局=<dir>/<key>/project.yaml，
    schema 与 t260910-03 同款——注册表是每 key 一目录，不是单文件）。"""
    regroot = Path(base) / "reg"
    regroot.mkdir(parents=True, exist_ok=True)
    for key, d in mapping.items():
        kdir = regroot / key
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: %s\n    name: UT %s\n    dirs:\n      - %s\n"
            % (key, key, d), "utf-8")
    return regroot


# ---------------------------------------------------------------- 真实入口

def load_ticket_module():
    """库装载 server/tools/ticket.py（无 __main__ CLI；先例=t260910-03 G8）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_t26091504_ticket",
                                                  str(TOOLS / "ticket.py"))
    tk = module = importlib.util.module_from_spec(spec)
    sys.modules["_t26091504_ticket"] = tk
    spec.loader.exec_module(tk)
    return tk


def run_client(py, sub, args, env, timeout=180):
    """spawn <py> client.py <sub> <argsJSON>（node.ts cli 同款口径）。返回 (rc, out)。"""
    p = subprocess.run([str(py), str(POC / "client.py"), sub, json.dumps(args)],
                       env=env, cwd=str(REPO), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


@contextlib.contextmanager
def stage_env(**kv):
    """进程内临时 env 桩（SANDBAR_* 均为调用时读，退出恢复）。"""
    saved = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def try_create(tk, payload):
    """ticket.py run(create) 容错执行：返回 (结果 dict 或 None, 错误串)。"""
    err = ""
    try:
        res = tk.run(payload)
        return (res if isinstance(res, dict) else None), err
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def payload_of(out):
    """从 client.py 子进程输出解析回执 dict（取首个 { 行；畸形→{}）。"""
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}
