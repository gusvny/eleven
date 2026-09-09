#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared library for the isolated test bench (created t260904-02, slimmed down
t260904-19): the "never touch production" guard + fixture registry + engine
asset resolution.

## Slot-system retirement note (t260904-19)

This library used to own a temporalite slot system. It retired when "every
test uses the same docker stage" landed: stage temporal now comes from
integration/stage_docker.py only (compose project-name isolation + port slot
locks + zero-residue checks). How each failure mode the slot system used to
handle is covered now is written up in the stage_docker.py header. What stays
in this library is only what scenarios still consume:

  PROD_PORTS / ProductionGuardError / assert_not_production   production guard (fail-closed)
  port_open / pick_free_port                                  probe primitives
  main_root_of / _resolve_asset / resolve_temporal_bin / resolve_poc_python / poc_python
                                                              lane asset resolution (main-tree fallback)
  audit_hook_env (+ sitecustomize template)                   "never touch production" audit hook for child processes
  write_registry                                              fixture project registry

## "Never touch production" audit hook (python side)
sitecustomize.py goes into the tested child process via PYTHONPATH:
sys.addaudithook watches socket.connect; if the target port is in PROD_PORTS
it first appends to a jsonl log, then raises. The audit hook fires before the
system call, so raising blocks the connect (the self-check leg proves a
127.0.0.1:7233 connect gets blocked with zero real production traffic).
Limits (stated, not hidden): covers python child processes only. The Go side
(temporal CLI) is covered by explicit port-argument assertions. Outbound
network from docker-stage containers is constrained by the compose network
topology (see the trade-off table in the stage_docker header).

Gaps in the lane (fallbacks when an asset is missing):
  SANDBAR_TEMPORAL_BIN   temporal binary (default <repo>/server/engine/bin/temporal;
                        falls back to the same path in the main tree via the .git gitfile)
  SANDBAR_POC_PYTHON     interpreter with temporalio (default <repo>/…/.venv/bin/python,
                        same main-tree fallback)
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

# Production port surface (frontend/UI): fail-closed blacklist for every
# outbound path in this library. The metrics port is not fixed on the
# production side, so it is not listed (the isolated bench exposes its own
# metrics explicitly anyway).
PROD_PORTS = {7233, 8233}

# Slot port bases (the slot system is retired; the constants stay as a
# historical anchor — they structurally avoid 7233/8233/3099).
SLOT_FE_BASE = 19100
SLOT_UI_BASE = 19200
SLOT_MET_BASE = 19300


class ProductionGuardError(RuntimeError):
    """The target is the production temporal (7233/8233) — fail-closed, refuse to run."""


class MissingAsset(RuntimeError):
    """temporal binary / venv interpreter not available (exit-2 semantics, message points the way)."""


def assert_not_production(host_port: str) -> str:
    """Fail-closed: raise ProductionGuardError if host:port points at production
    (7233/8233). Returns the original string (when legal) for chaining."""
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
    """Kernel port-0 allocation (skeleton contract: bind(0), take the kernel's
    port, release it)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def main_root_of(repo_root) -> "pathlib.Path | None":
    """In a worktree, .git is a gitfile ("gitdir: <main>/.git/worktrees/<name>")
    → returns the main repo root. Not a worktree (.git is a directory) → None.
    Only reads the .git file (never writes)."""
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
    """Asset resolution: env > lane path > main-tree fallback (via gitfile) > MissingAsset."""
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
    """Engine venv interpreter (with main-tree gitfile fallback)."""
    return str(resolve_poc_python())


# ---- "Never touch production" audit hook (python side) ----
# sitecustomize.py is injected into the tested child process via PYTHONPATH:
# sys.addaudithook watches socket.connect; if the target port is in
# PROD_PORTS it first appends to a jsonl log, then raises. Limits (stated,
# not hidden): covers python child processes only; the Go side (temporal CLI)
# is covered by explicit port-argument assertions.

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
    """Install the audit hook. Returns (env fragment, log path): the env holds
    PYTHONPATH (prepended) + SANDBAR_AUDIT_HITS. Reinstalling clears the old
    log (each leg starts counting from zero)."""
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


# ---- fixture registry ----

_REGISTRY_KEY_RE = None  # loaded lazily from shared's real regex (see write_registry)


def write_registry(dirpath, key, project_dir):
    """Create a fixture project registry (same shape as the per-key directory
    format of server/engine shared.load_projects_registry). Returns the
    registry root (SANDBAR_PROJECTS_DIR consumes it directly)."""
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
    # project_dir is written down verbatim (no realpath dereference): scenario
    # assertions compare against the passed path as the anchor, and on macOS
    # the /var→/private/var symlink dereference would create false mismatches.
    (key_dir / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
        % (key, key, project_dir),
        encoding="utf-8")
    return str(d)
