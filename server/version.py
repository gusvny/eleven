"""sandbar 版本单源：唯一真源=仓根 VERSION 文件（契约⑧-4 口径）。

三态判定，全部 fail-closed，不造历史映射：
- 正常：内容恰为一行 semver（MAJOR.MINOR.PATCH，三段纯整数，不许前导零）；
- 缺失：VERSION 文件不存在；
- 脏：空文件 / 多行非空内容 / 非 semver 字样。

任何异常态抛 VersionError，由调用方显式展示；绝不猜一个版本顶上去
（v2 时代的引擎从未以 semver 存在，事后映射即伪造历史）。
"""

from __future__ import annotations

import pathlib
import re

# 三段整数、不许前导零（严格 semver 核心段，不带 prerelease/build 后缀——
# 仓根 VERSION 是发布版本，不是 dsh 已验证点那种 rc 串）。
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VersionError(RuntimeError):
    """VERSION 缺失或脏（非 semver）——fail-closed 红。"""


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION_PATH = REPO_ROOT / "VERSION"


def parse_semver(text: str):
    """解析 semver 字符串为 (major, minor, patch)；不合法抛 VersionError。"""
    m = _SEMVER_RE.match(text.strip())
    if not m:
        raise VersionError("VERSION 脏（非 semver）：%r" % text)
    return tuple(int(x) for x in m.groups())


def read_version(path=None) -> str:
    """读 VERSION 文件，返回 semver 字符串；缺失/脏抛 VersionError。"""
    p = pathlib.Path(path) if path is not None else VERSION_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise VersionError("VERSION 缺失：%s" % p)
    except IsADirectoryError:
        raise VersionError("VERSION 路径是目录不是文件：%s" % p)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) != 1:
        raise VersionError(
            "VERSION 脏（应恰为一行 semver，实得 %d 行非空内容）" % len(lines))
    parse_semver(lines[0])
    return lines[0]


def sandbar_version(path=None) -> str:
    """对外口径：自报 sandbar 版本字符串（快照 sandbar_version 键的值）。"""
    return read_version(path)


def version_tuple(path=None):
    """对外口径：semver 三元组（升版 diff/降版判定用）。"""
    return parse_semver(read_version(path))
