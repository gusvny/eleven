#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景①：3099 红线源码级静态守卫（交接单 §3，C1 补全词表）。

用户视角契约：console（3099）永属用户操作面——安装器任何代码路径只能探测与提示，
不得执行 kill/pkill/重启/spawn/start/launch。断言=全词表 × 3099/console 上下文
零容忍；提示文案（「请手动」「操作面」）白名单豁免——区分提示与执行。

结构：扫描器自证半（干净样本绿 + 注入禁词副本红，先证明扫描器自身有效）
→ 真对象半（入口 + server/installer/** 全源扫描）。纯静态、零端口、零进程，
池=ro，implement 交付前对象缺失=exit 2（精确归因，不误报断言失败）。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import REPO, Fail, find_installer_entry, MISSING_EXIT  # noqa: E402

# 交接单 §3 禁词表（C1 补全后）：英文词走词边界（skill 不误伤），中文词直接子串
BANNED = re.compile(r"\b(kill|pkill|spawn|start|launch)\b|重启")
CONTEXT = re.compile(r"3099|console", re.IGNORECASE)
HINT_WHITELIST = re.compile(r"请手动|操作面")
SCAN_WINDOW = 2  # 命中行 ±2 行内的 3099/console 视为同上下文


def scan_paths(paths):
    """返回违例列表 [(relpath, lineno, line)]。"""
    hits = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if not BANNED.search(line):
                continue
            window = lines[max(0, i - SCAN_WINDOW):i + SCAN_WINDOW + 1]
            if not any(CONTEXT.search(ln) for ln in window):
                continue
            if HINT_WHITELIST.search(line):
                continue  # 提示文案豁免（提示 ≠ 执行）
            hits.append((os.path.relpath(path, REPO), i + 1, line.rstrip()[:120]))
    return hits


def installer_sources():
    """扫描集=入口文件 + server/installer/** 全源。"""
    paths = []
    entry = find_installer_entry()
    if entry:
        paths.append(entry)
    pkg = os.path.join(REPO, "server", "installer")
    if os.path.isdir(pkg):
        for root, _dirs, files in os.walk(pkg):
            for fn in sorted(files):
                if fn.endswith(".py"):
                    paths.append(os.path.join(root, fn))
    return paths


def selfcheck(fail):
    """扫描器自证：干净样本绿、注入禁词样本红、提示白名单豁免生效。"""
    tmp = tempfile.mkdtemp(prefix="sandbar-it-selfcheck-")
    try:
        clean = os.path.join(tmp, "clean.py")
        with open(clean, "w", encoding="utf-8") as f:
            f.write(
                "CONSOLE_PORT = 3099\n"
                "def probe(host):\n"
                "    s.connect_ex((host, CONSOLE_PORT))  # 只读探测\n"
                '    print("console 属用户操作面，请手动起停；如需启动请用 start-console.sh（操作面提示）")\n'
            )
        fail.check(not scan_paths([clean]), "自证：干净样本（探测+提示文案）零违例")
        poisoned = os.path.join(tmp, "poison.py")
        with open(poisoned, "w", encoding="utf-8") as f:
            f.write("import subprocess\nsubprocess.run(['pkill', '-f', 'console 3099'])\n")
        fail.check(len(scan_paths([poisoned])) == 1, "自证：注入 pkill×3099 副本被判红")
        hinted = os.path.join(tmp, "hinted.py")
        with open(hinted, "w", encoding="utf-8") as f:
            f.write('print("console 未在位？请手动 start start-console.sh（console 属用户操作面，请手动起停）")\n')
        fail.check(not scan_paths([hinted]), "自证：含 start 的提示文案行走白名单豁免")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    fail = Fail("t260903-10 ①3099 红线源码级静态守卫")
    selfcheck(fail)
    # 入口是断言面必要组成：入口缺失=断言面不完整（未交付态），即使包已交付也不许绿
    entry = find_installer_entry()
    paths = installer_sources()
    if entry is None or not paths:
        fail.bail(
            "安装器源码不在预期落点（入口 ./sandbar|./scripts/sandbar 缺或不可执行，server/installer/ 源缺）"
            "——implement 未交付或落点变更；bin/sandbar 为禁用落点（.gitignore bin/ 吞交付物，review 附条件1）。",
            MISSING_EXIT)
    hits = scan_paths(paths)
    for rel, lineno, line in hits[:5]:
        print("  违例 %s:%d: %s" % (rel, lineno, line), flush=True)
    fail.check(not hits,
               "真对象半：入口+server/installer/** 共 %d 文件，3099 执行动词零违例" % len(paths))
    fail.finish()


if __name__ == "__main__":
    main()
