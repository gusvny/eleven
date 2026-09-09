#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离测试台共享库（票 t260904-02 建、t260904-19 收敛）：「不连生产」守卫 +
fixture 注册表 + 引擎资产解析。

## 槽位制退役声明（t260904-19）

本库原有的 temporalite 槽位制已随「所有测试同一 docker 舞台」退役：temporal 台
由 integration/stage_docker.py 统一供给（compose 工程名隔离 + 端口档位锁 + 零残留
核验），槽位制处理过的故障模式逐项取舍见 stage_docker.py 头注。本库只留仍被
场景消费的面：

  PROD_PORTS / ProductionGuardError / assert_not_production   生产守卫（fail-closed）
  port_open / pick_free_port                                  探测原语
  main_root_of / _resolve_asset / resolve_temporal_bin / resolve_poc_python / poc_python
                                                              泳道资产解析（主树回退）
  audit_hook_env（+ sitecustomize 模板）                      被测子进程「不连生产」审计钩子
  write_registry                                              fixture 项目注册表

## 「不连生产」审计钩子（python 面）
sitecustomize.py 注入被测子进程 PYTHONPATH：sys.addaudithook 监 socket.connect，
目标端口∈PROD_PORTS 先记 jsonl 后 raise——audit 钩子在系统调用前触发，raise 即
阻断（自证腿连 127.0.0.1:7233 会被拦，零真连生产）。
边界（明示不静默）：只覆盖 python 子进程；Go 面（temporal CLI）由显式端口参数断言补面；
docker 台的容器内出网由 compose 网络拓扑约束（stage_docker 头注取舍表）。

环境缝（泳道缺资产时的回退）：
  SANDBAR_TEMPORAL_BIN   temporal 二进制（缺省 <repo>/server/engine/bin/temporal，
                        泳道缺失时读 .git gitfile 回退主树同位）
  SANDBAR_POC_PYTHON     带 temporalio 的解释器（缺省 <repo>/…/.venv/bin/python，同样回退主树）
"""
from __future__ import annotations

import errno
import fcntl
import os
import pathlib
import signal
import socket
import subprocess
import time

REPO = pathlib.Path(__file__).resolve().parent.parent

# 生产端口面（frontend/UI）：本库一切出网路径的 fail-closed 黑名单。
# metrics 端口生产侧未固定公开，不列入（隔离台自身 metrics 全显式即可）。
PROD_PORTS = {7233, 8233}

# 槽位端口基址（槽位制已退役，常量留作历史锚；结构性避开 7233/8233/3099）。
SLOT_FE_BASE = 19100
SLOT_UI_BASE = 19200
SLOT_MET_BASE = 19300


class ProductionGuardError(RuntimeError):
    """目标是生产 temporal（7233/8233）——fail-closed 拒跑。"""


class MissingAsset(RuntimeError):
    """temporal 二进制/venv 解释器不可得（exit2 语义，文案指路）。"""


def assert_not_production(host_port: str) -> str:
    """fail-closed：host:port 指向生产（7233/8233）即抛 ProductionGuardError。
    返回原串（合法时）供链式使用。"""
    s = str(host_port or "")
    port = None
    if ":" in s:
        port = s.rsplit(":", 1)[1].strip()
    elif s.isdigit():
        port = s
    if port is not None:
        try:
            n = int(port)
        except ValueError:
            n = None
        if n in PROD_PORTS:
            raise ProductionGuardError(
                "拒跑（fail-closed）：目标是生产 temporal 端口 %d（%r）——隔离台绝不碰 7233/8233"
                % (n, s))
    if not s:
        raise ProductionGuardError("拒跑（fail-closed）：空目标地址")
    return s


def port_open(port, host="127.0.0.1", timeout=1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, int(port))) == 0
    finally:
        s.close()


def pick_free_port() -> int:
    """port-0 内核分配（骨架口径：bind(0) 取内核给的端口后释放）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def main_root_of(repo_root) -> "pathlib.Path | None":
    """worktree 的 .git 是 gitfile（"gitdir: <main>/.git/worktrees/<name>"）→ 主仓根。
    非 worktree（.git 是目录）→ None。只读 .git 文件（不写不改）。"""
    git_path = pathlib.Path(repo_root) / ".git"
    try:
        if not git_path.is_file():
            return None
        first = git_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError:
        return None
    if not first.startswith("gitdir:"):
        return None
    gitdir = pathlib.Path(first[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = pathlib.Path(repo_root) / gitdir
    gitdir = gitdir.resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return None


def _resolve_asset(env_key, lane_path: pathlib.Path, what: str) -> pathlib.Path:
    """资产解析：env > 泳道位 > 主树回退（gitfile 推导）> MissingAsset。"""
    env_val = os.environ.get(env_key)
    if env_val:
        p = pathlib.Path(env_val)
        if p.exists():
            return p
        raise MissingAsset("%s=%s 不存在（env 指路优先，检查路径）" % (env_key, env_val))
    if lane_path.exists():
        return lane_path
    main = main_root_of(REPO)
    if main is not None:
        rel = lane_path.relative_to(REPO)
        cand = main / rel
        if cand.exists():
            return cand
    raise MissingAsset(
        "%s 不可得：泳道 %s 缺失，主树回退失败（非 worktree 或主树也缺）。"
        "处置：env %s=<路径> 指路，或在主树补齐资产" % (what, lane_path, env_key))


def resolve_temporal_bin() -> pathlib.Path:
    return _resolve_asset("SANDBAR_TEMPORAL_BIN",
                          REPO / "server" / "engine" / "bin" / "temporal",
                          "temporal 二进制")


def resolve_poc_python() -> pathlib.Path:
    return _resolve_asset("SANDBAR_POC_PYTHON",
                          REPO / "server" / "engine" / ".venv" / "bin" / "python",
                          "带 temporalio 的 venv 解释器")


def poc_python() -> str:
    """引擎 venv 解释器（含主树 gitfile 回退）。"""
    return str(resolve_poc_python())


# ---- 「不连生产」审计钩子（python 面）----
# sitecustomize.py 注入被测子进程 PYTHONPATH：sys.addaudithook 监 socket.connect，
# 目标端口∈PROD_PORTS 先记 jsonl 后 raise。边界（明示不静默）：只覆盖 python 子进程；
# Go 面（temporal CLI）由显式端口参数断言补面。

_AUDIT_SITECUSTOMIZE = '''import json as _json
import os as _os
import sys as _sys

_HITS = _os.environ.get("SANDBAR_AUDIT_HITS", "")
_FORBIDDEN = __FORBIDDEN__


def _bench_audit(event, args):
    if event != "socket.connect":
        return
    addr = args[1] if len(args) > 1 else None
    port = None
    if isinstance(addr, tuple) and len(addr) == 2:
        try:
            port = int(addr[1])
        except (TypeError, ValueError):
            port = None
    elif isinstance(addr, str) and addr.isdigit():
        port = int(addr)
    if port in _FORBIDDEN:
        if _HITS:
            try:
                with open(_HITS, "a") as f:
                    f.write(_json.dumps({"event": event, "addr": list(addr) if isinstance(addr, tuple) else str(addr)}) + "\\n")
            except OSError:
                pass
        raise PermissionError("bench 审计钩子：禁止连接生产端口 %d（隔离台 fail-closed）" % port)


_sys.addaudithook(_bench_audit)
'''


def audit_hook_env(dirpath):
    """装审计钩子。返回 (env 片段, 日志路径)：env 含 PYTHONPATH（前插）+
    SANDBAR_AUDIT_HITS；复装会清旧记录（每腿从零记账）。"""
    d = pathlib.Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sitecustomize.py").write_text(
        _AUDIT_SITECUSTOMIZE.replace("__FORBIDDEN__", repr(sorted(PROD_PORTS))),
        encoding="utf-8")
    log_path = d / "hits.jsonl"
    try:
        log_path.unlink()
    except FileNotFoundError:
        pass
    env_add = {"SANDBAR_AUDIT_HITS": str(log_path)}
    existing = os.environ.get("PYTHONPATH", "")
    env_add["PYTHONPATH"] = str(d) + (os.pathsep + existing if existing else "")
    return env_add, str(log_path)


# ---- fixture 注册表 ----

_REGISTRY_KEY_RE = None  # 延迟取 shared 的真源正则（见 write_registry）


def write_registry(dirpath, key, project_dir):
    """造 fixture 项目注册表（形状=server/engine shared.load_projects_registry
    的 per-key 目录档）。返回注册表根目录（SANDBAR_PROJECTS_DIR 直用）。"""
    import re
    d = pathlib.Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    if not re.match(r"^[a-z][a-z0-9-]{1,30}$", str(key)):
        raise ValueError("注册表 key 不合法（^[a-z][a-z0-9-]{1,30}$）：%r" % key)
    proj = pathlib.Path(project_dir)
    if not proj.is_absolute():
        raise ValueError("project_dir 必须绝对路径（锚定语义）：%r" % project_dir)
    key_dir = d / str(key)
    key_dir.mkdir(parents=True, exist_ok=True)
    # project_dir 原文落盘（不做 realpath 解引用）：场景断言以传入路径为锚比对，
    # macOS 下 /var→/private/var 符号链接解引用会制造假不匹配。
    (key_dir / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
        % (key, key, project_dir),
        encoding="utf-8")
    return str(d)
