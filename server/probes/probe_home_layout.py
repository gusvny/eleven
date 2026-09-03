"""probe-home-layout：dsh home 布局面（必查项 B1）。

断言：profiles/ 目录存在；`.credentials.yaml` 与 `settings.yaml` 文件名指纹
（**带点前缀**的 credentials 与 settings.yaml 本名）在 ≤2 层深度内可寻得。
fixture 桩=good/bad_missing/bad_wrong_name 三档；live 档指路：DSH_HOME。
"""

from __future__ import annotations

import pathlib

from probes import ProbeResult

NAME = "probe-home-layout"
_MAX_DEPTH = 2


def run(root, dsh_home=None) -> ProbeResult:
    p = pathlib.Path(root) if root is not None else None
    if p is None or not p.is_dir():
        return ProbeResult(NAME, False, "目标根不存在或不是目录：%s" % p)
    profiles = p / "profiles"
    if not profiles.is_dir():
        return ProbeResult(NAME, False, "缺 profiles/ 目录（B1 布局面）")
    found_cred, found_settings = None, None
    for depth, path in _walk(p, depth=0):
        if depth > _MAX_DEPTH:
            continue
        if path.name == ".credentials.yaml" and found_cred is None:
            found_cred = path
        if path.name == "settings.yaml" and found_settings is None:
            found_settings = path
    missing = []
    if found_cred is None:
        missing.append(".credentials.yaml（注意点前缀文件名指纹）")
    if found_settings is None:
        missing.append("settings.yaml")
    if missing:
        return ProbeResult(NAME, False, "指纹文件缺失：%s" % "；".join(missing))
    return ProbeResult(NAME, True,
                       "profiles/ 在位；.credentials.yaml → %s；settings.yaml → %s"
                       % (found_cred.relative_to(p), found_settings.relative_to(p)))


def _walk(root: pathlib.Path, depth: int):
    """有界深度遍历（≤_MAX_DEPTH），产出 (depth, path)。"""
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return
    for e in entries:
        yield depth, e
        if e.is_dir() and depth + 1 <= _MAX_DEPTH:
            yield from _walk(e, depth + 1)
