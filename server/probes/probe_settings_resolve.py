"""probe-settings-resolve：settings 层叠面（必查项 A3）。

断言：声明层 patch 与用户层合成时「路由优先于 GUI」语义成立——patch 键在
合成结果中可观测（不被用户层静默盖掉），且用户层独有键保留。
合成顺序口径：deep-merge，声明层 patch 逐键胜出（dsh settings/resolve A3 面）。
fixture 畸形档：坏 YAML（tab）/缺 patch 文件 → 红。
"""

from __future__ import annotations

import pathlib

from probes import ProbeResult
from probes import _miniyaml

NAME = "probe-settings-resolve"


def run(root) -> ProbeResult:
    p = pathlib.Path(root) if root is not None else None
    if p is None or not p.is_dir():
        return ProbeResult(NAME, False, "目标根不存在或不是目录：%s" % p)
    user_f, patch_f = p / "user.yaml", p / "project.patch.yaml"
    try:
        user = _miniyaml.load_file(user_f)
    except _miniyaml.YamlError as e:
        return ProbeResult(NAME, False, "用户层 settings 解析失败：%s" % e)
    try:
        patch = _miniyaml.load_file(patch_f)
    except _miniyaml.YamlError as e:
        return ProbeResult(NAME, False, "声明层 patch 解析失败（缺文件/坏格式）：%s" % e)
    merged = resolve(user, patch)
    problems = _assert_observability(user, patch, merged)
    if problems:
        return ProbeResult(NAME, False, "；".join(problems))
    return ProbeResult(NAME, True,
                       "声明层 patch 值在合成结果中可观测，用户层独有键保留（A3 顺序成立）")


def resolve(user: dict, patch: dict) -> dict:
    """层叠合成：deep-merge，声明层 patch 逐键胜出（同键不静默保留用户层）。"""
    out = dict(user)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = resolve(out[k], v)
        else:
            out[k] = v
    return out


def _assert_observability(user: dict, patch: dict, merged: dict):
    """A3 断言：patch 每个叶子键在 merged 中=patch 值；user 独有叶子键保留。"""
    problems = []
    for kpath, want in _leaves(patch):
        got = _dig(merged, kpath)
        if got != want:
            problems.append("patch 键 %s 未在合成结果观测到（got=%r want=%r，"
                            "疑被用户层静默盖掉）" % (".".join(kpath), got, want))
    patch_paths = {".".join(map(str, kp)) for kp, _ in _leaves(patch)}
    for kpath, val in _leaves(user):
        if ".".join(map(str, kpath)) in patch_paths:
            continue
        got = _dig(merged, kpath)
        if got != val:
            problems.append("用户层独有键 %s 丢失（got=%r）" % (".".join(kpath), got))
    return problems


def _leaves(obj, prefix=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, prefix + (k,))
    else:
        yield prefix, obj


def _dig(obj, path):
    for k in path:
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj
