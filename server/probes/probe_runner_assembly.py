"""probe-runner-assembly：runner 装配面（必查项 A4/A5）。

断言：dsh 安装树内存在 stock `headless-runner` 注册项，且其 `inject` 含
`headlessStartup` 启动钩子注入点。fixture=桩 dsh-dist 树（runners.json）；
畸形档：缺清单 / 坏 JSON / 有 id 无注入点 → 红。live 档指路：DSH_INSTALL_ROOT。
"""

from __future__ import annotations

import json
import pathlib

from probes import ProbeResult

NAME = "probe-runner-assembly"
RUNNER_ID = "headless-runner"
INJECT_HOOK = "headlessStartup"
_MAX_DEPTH = 5


def run(install_root) -> ProbeResult:
    p = pathlib.Path(install_root) if install_root is not None else None
    if p is None or not p.is_dir():
        return ProbeResult(NAME, False, "dsh 安装根不存在或不是目录：%s" % p)
    seen_runner, seen_inject, json_files = None, False, 0
    for f in _json_files(p):
        json_files += 1
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            return ProbeResult(NAME, False, "坏 JSON（%s）：%s" % (f, e))
        for entry in _entries(data):
            if isinstance(entry, dict) and entry.get("id") == RUNNER_ID:
                seen_runner = f
                inject = entry.get("inject")
                if isinstance(inject, list) and INJECT_HOOK in inject:
                    seen_inject = True
    if json_files == 0:
        return ProbeResult(NAME, False, "安装树内未找到任何 runner 注册 JSON（A4 面）")
    if seen_runner is None:
        return ProbeResult(NAME, False,
                           "未找到 stock %s 注册项（A4 失配）——已扫 %d 个 JSON" % (RUNNER_ID, json_files))
    if not seen_inject:
        return ProbeResult(NAME, False,
                           "%s 在（%s）但缺 inject:[%s] 注入点（A5 失配，会话延续将静默丢失）"
                           % (RUNNER_ID, seen_runner, INJECT_HOOK))
    return ProbeResult(NAME, True, "stock %s 注册于 %s，inject 含 %s"
                       % (RUNNER_ID, seen_runner.relative_to(p), INJECT_HOOK))


def _json_files(root: pathlib.Path):
    """有界深度收集 *.json（深度 ≤_MAX_DEPTH）。"""
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_file() and e.suffix == ".json":
                yield e
            elif e.is_dir() and depth + 1 <= _MAX_DEPTH:
                stack.append((e, depth + 1))


def _entries(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        out = []
        for v in data.values():
            out.extend(_entries(v))
        return out
    return []
