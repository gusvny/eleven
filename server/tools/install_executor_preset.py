#!/usr/bin/env python3
"""install_executor_preset.py —— 把仓内 sandbar-executor preset 安装进宿主 dsh preset 目录。

背景（工单 t261001-13）：executor preset 的真源在
``server/profile/agent-presets/sandbar-executor/``，但此前安装是手工 ``cp -R``，
宿主上没装 ⇒ watchdog 按需代建会话被逐次拒绝（261001 实证 18/18 refused）且无人知晓。
本工具 = 安装面的机械化入口：幂等安装 + 装前装后校验 + ``--check`` 只读自检
（可挂进首启自检 / doctor 链）。

用法::

    python3 server/tools/install_executor_preset.py            # 安装（幂等）
    python3 server/tools/install_executor_preset.py --check    # 只读自检，缺=exit 3
    python3 server/tools/install_executor_preset.py --force    # 覆盖已装目录

退出码：0=就绪（含已装）；1=失败（原因点名到 stderr）；3=--check 且未安装。
不重启、不触碰 console（3099）/引擎（7233）——纯文件面操作。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

PRESET_NAME = "sandbar-executor"
NAME_LINE_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_MISSING = 3


def repo_root_of(script: Path) -> Path:
    """仓根 = 本文件所在目录的上两级（server/tools/ → 仓根）。"""
    return script.resolve().parent.parent.parent


def dsh_home(env: dict[str, str]) -> Path:
    """宿主 dsh home（env DSH_HOME 优先；缺省 ~/.dsh——与 presetReady 同源表达式）。"""
    raw = env.get("DSH_HOME") or str(Path.home() / ".dsh")
    return Path(raw)


def validate_preset_dir(src: Path) -> str:
    """装前校验：preset.yml 存在且 ``name:`` 行等于目录名（真源坏=拒装，绝不复制坏 preset）。

    返回人类可读错误；就绪返回空串。
    """
    yml = src / "preset.yml"
    if not yml.is_file():
        return f"preset.yml 缺席：{yml}——真源不完整，拒装"
    try:
        raw = yml.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"preset.yml 不可读：{yml}：{e}"
    m = NAME_LINE_RE.search(raw)
    if not m:
        return f"preset.yml 无 name 行：{yml}——形状不合规，拒装"
    if m.group(1) != PRESET_NAME:
        return f"preset.yml name={m.group(1)} ≠ {PRESET_NAME}（目录名）——拒装"
    return ""


def install(repo: Path, home: Path, force: bool) -> tuple[int, str]:
    """安装主流程。返回 (exit_code, 人类可读结论)。"""
    src = repo / "server" / "profile" / "agent-presets" / PRESET_NAME
    err = validate_preset_dir(src)
    if err:
        return EXIT_FAIL, err
    dst = home / ".agent-presets" / PRESET_NAME
    if dst.exists():
        err = validate_preset_dir(dst)
        if not err and not force:
            return EXIT_OK, f"已安装且校验通过，幂等跳过：{dst}（覆盖请用 --force）"
        if not force:
            return EXIT_FAIL, f"已装目录校验不通过且未指定 --force：{err}"
        try:
            shutil.rmtree(dst)
        except OSError as e:
            return EXIT_FAIL, f"旧目录移除失败（--force）：{dst}：{e}"
    try:
        shutil.copytree(src, dst)
    except OSError as e:
        # 半截复制的目录本身就是坏 preset（下次运行校验会拒）——这里显式点名，不静默。
        return EXIT_FAIL, f"复制失败：{src} → {dst}：{e}"
    err = validate_preset_dir(dst)
    if err:
        return EXIT_FAIL, f"装后回读校验不通过（装了但坏，需人看）：{dst}：{err}"
    return EXIT_OK, f"安装完成并校验通过：{src} → {dst}"


def check(home: Path) -> tuple[int, str]:
    """只读自检：装了吗？装的还是好的吗？"""
    dst = home / ".agent-presets" / PRESET_NAME
    if not dst.is_dir():
        return EXIT_MISSING, f"未安装：缺 {dst}——executor 会话代建将被逐次拒绝"
    err = validate_preset_dir(dst)
    if err:
        return EXIT_FAIL, f"已装但校验不通过：{err}"
    return EXIT_OK, f"就绪：{dst}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", type=Path, default=None, help="仓根（缺省=按脚本位置推算）")
    p.add_argument("--dsh-home", type=Path, default=None, help="宿主 dsh home（缺省 env DSH_HOME 或 ~/.dsh）")
    p.add_argument("--check", action="store_true", help="只读自检，不安装")
    p.add_argument("--force", action="store_true", help="已装时先删后装（覆盖）")
    args = p.parse_args(argv)
    env = dict(os.environ)
    home = args.dsh_home if args.dsh_home is not None else dsh_home(env)
    if args.check:
        code, msg = check(home)
    else:
        repo = args.repo if args.repo is not None else repo_root_of(Path(__file__))
        code, msg = install(repo, home, force=args.force)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
