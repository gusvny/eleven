#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_venv_compat.py — 引擎 venv 定位兼容契约（t260907-10 工单⑤，灰盒 L3）。

intent（用户可感知契约）：工单⑤「.venv 位置变更须保 worker 兼容（旧路径回落期一轮）」——
目录重构后，worker/工具链的 python 解释器定位必须：新路径 server/engine/.venv/bin/python
优先；新路径缺位（主树 .venv 尚未物理迁移的窗口期）回落旧路径
server/dsh/temporal-poc/.venv/bin/python；两缺时解析结果绝不静默落系统解释器
（错 python=temporalio 缺失，炸在 spawn 处而非炸在解释器语义处——报错必须精确）。
畸形形态（断链软链/不可执行文件）按缺位处理。verify.yaml test 道（接入契约 ②a 声明面）
必须锚新路径真源。

被测面：installer.InstallPaths（安装器单一装载面，KI-032 单一真源同族）——root/home
注入全隔离，不触碰真仓 .venv。回落机制宿主裁切法一（代码内探测）为本条主形态；
裁切法二（env 注入）时 leg2/4/5 的回落语义由 env 承担，本条随语义同步改读 env 锚。

high-level steps：
  1. 新旧 venv 桩都在（fixture 仓注入可执行桩脚本）→ 解析=新路径；
  2. 仅旧桩在（新路径 rm）→ 解析=旧路径（回落期兼容的核心契约）；
  3. 两缺 → 解析路径仍在仓树内（不落 /usr/bin 等系统解释器）；
  4. 新路径为断链软链 → 视同缺位 → 回落旧路径；
  5. 新路径桩不可执行 → 视同缺位 → 回落旧路径；
  6. verify.yaml test 道 cmd 引用 server/engine/.venv（新真源在声明面在场）。

Hermetic：全部活在 tempfile fixture 仓内，零端口零网络零 3099，秒级。
**implement 落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。**
"""
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260907-04"))  # 共享 helper：lib_naming.Rec
sys.path.insert(0, os.path.join(REPO, "server"))
import lib_naming  # noqa: E402
from installer.runtime import InstallPaths  # noqa: E402

NEW_VENV = os.path.join("server", "engine", ".venv", "bin", "python")
OLD_VENV = os.path.join("server", "dsh", "temporal-poc", ".venv", "bin", "python")


def _mk_stub(path, executable=True, dangling=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if dangling:
        os.symlink(os.path.join(path, "..", "no-such-target"), path)
        return
    with open(path, "w") as f:
        f.write("#!/bin/sh\necho stub-python\n")
    os.chmod(path, 0o755 if executable else 0o644)


def _fixture(with_new=True, with_old=True, new_dangling=False, new_noexec=False):
    root = tempfile.mkdtemp(prefix="venv-compat-root-")
    home = tempfile.mkdtemp(prefix="venv-compat-home-")
    if with_new:
        _mk_stub(os.path.join(root, NEW_VENV), executable=not new_noexec,
                 dangling=new_dangling)
    if with_old:
        _mk_stub(os.path.join(root, OLD_VENV))
    # InstallPaths 不允许 console_port 缺省（会拉起真 console 模块）——全注入隔离。
    return InstallPaths(root=root, home=home, server_port=7299, ui_port=8299,
                        console_port=3098)


def _rel_to_root(ip):
    try:
        return os.path.relpath(str(ip.venv_python), str(ip.root))
    except ValueError:
        return None


def main():
    r = lib_naming.Rec()

    print("== 1 新旧桩都在 → 新路径优先")
    ip = _fixture()
    r.check(str(ip.venv_python) == str(ip.root / NEW_VENV),
            "解析=%s（期望新路径）" % _rel_to_root(ip))

    print("== 2 仅旧桩在（新路径缺位窗口）→ 旧路径回落")
    ip = _fixture(with_new=False)
    r.check(str(ip.venv_python) == str(ip.root / OLD_VENV),
            "解析=%s（期望旧路径回落）" % _rel_to_root(ip))

    print("== 3 两缺 → 不静默落系统解释器（解析仍在仓树内）")
    ip = _fixture(with_new=False, with_old=False)
    rel = _rel_to_root(ip)
    r.check(rel is not None and not rel.startswith(".."),
            "解析=%s（不得指向仓外系统 python）" % rel)

    print("== 4 新路径为断链软链 → 视同缺位 → 旧路径回落")
    ip = _fixture(new_dangling=True)
    r.check(str(ip.venv_python) == str(ip.root / OLD_VENV),
            "解析=%s（断链视同缺失）" % _rel_to_root(ip))

    print("== 5 新路径桩不可执行 → 视同缺位 → 旧路径回落")
    ip = _fixture(new_noexec=True)
    r.check(str(ip.venv_python) == str(ip.root / OLD_VENV),
            "解析=%s（不可执行视同缺失）" % _rel_to_root(ip))

    print("== 6 verify.yaml test 锚新路径真源（契约声明面）")
    with open(os.path.join(REPO, "verify.yaml"), "r", encoding="utf-8") as f:
        test_cmd = ""
        in_test = False
        for line in f:
            if line.strip().startswith("- id: test"):
                in_test = True
            elif in_test and line.strip().startswith("- id:"):
                break
            elif in_test and "cmd:" in line:
                test_cmd = line
                break
    r.check("server/engine/.venv/bin/python" in test_cmd,
            "test 道 cmd 引用新 venv 真源（实得=%s）" % test_cmd.strip()[:90])

    r.finish()


if __name__ == "__main__":
    main()
