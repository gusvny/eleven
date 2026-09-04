#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260903-10 场景②：doctor 全量探针 → 兼容矩阵落盘契约（契约⑧-3 三轴）。

用户视角契约：`sandbar doctor` 一条命令跑全量探针（缺省 fixture 档，不起真 dsh
进程、不写真 dsh home），绿一行 append 一行到 ~/.sandbar/compat-matrix.json；
矩阵行 = sandbar 版本 × dsh 已验证点 × 项目 schema 版本；重复 doctor 幂等
（行集合不变）；读侧 schema 校验=遇坏矩阵不静默（显式报错或恢复合法）。

HOME 桩隔离：矩阵落临时 HOME，绝不碰真 ~/.sandbar。零端口依赖。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_installer import (REPO, Fail, cleanup, find_installer_entry, make_temp_home,  # noqa: E402
                           run_cli, require_installer_entry)

EXPECTED_PROBES = 5  # 五面：home 布局 / session 格式 / runner 装配 / settings resolve + probe-engine-zombies（t260904-02 落第五面，census 缺省档绿）


def matrix_path(home):
    return os.path.join(home, ".sandbar", "compat-matrix.json")


def read_rows(path):
    """宽容读行集合：顶层 list 即行；顶层 dict 取 rows/list 类字段。返回 (ok, rows)。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, []
    if isinstance(data, list):
        return True, data
    if isinstance(data, dict):
        for key in ("rows", "matrix", "entries", "data"):
            if isinstance(data.get(key), list):
                return True, data[key]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return True, v
    return True, []


def main():
    fail = Fail("t260903-10 ②doctor 全量→兼容矩阵落盘契约")
    entry = require_installer_entry(fail)
    tmp, env = make_temp_home()
    try:
        mpath = matrix_path(tmp)
        t0 = time.time()
        rc, out = run_cli(entry, ["doctor"], env, timeout=120)
        fail.check(rc == 0, "doctor 缺省 fixture 档零退出（%0.1fs）out=%s" % (time.time() - t0, out.strip()[:100] or "∅"))

        rows_ok, rows = read_rows(mpath)
        fail.check(os.path.isfile(mpath), "矩阵落盘于 $HOME/.sandbar/compat-matrix.json（HOME 桩内）")
        if os.path.isfile(mpath):
            fail.check(rows_ok and len(rows) > 0, "矩阵为合法 JSON 且含行集合")
        fail.check(rows_ok and len(rows) == EXPECTED_PROBES,
                   "四面全绿=%d 行（绿一行 append 一行，实得 %d）" % (EXPECTED_PROBES, len(rows)))
        blob = json.dumps(rows, ensure_ascii=False) if rows else ""
        # 版本锚单源化（t260903-12）：断言的是「矩阵 sandbar 版本轴=仓根 VERSION 单源值」，
        # 不是某个历史字面量——升版本场景不再连环红。dsh 已验证点是 ⑧-1 列举制固定值，保留字面量。
        sandbar_ver = open(os.path.join(REPO, "VERSION"), encoding="utf-8").read().strip()
        fail.check(sandbar_ver in blob, "三轴之一 sandbar 版本（单源仓根 VERSION=%s）在案" % sandbar_ver)
        fail.check("0.1.1-rc.2" in blob, "三轴之一 dsh 已验证点 0.1.1-rc.2 在案")

        _, rows_before = read_rows(mpath)
        rc2, out2 = run_cli(entry, ["doctor"], env, timeout=120)
        _, rows_after = read_rows(mpath)
        fail.check(rc2 == 0, "重复 doctor 仍零退出")
        fail.check(rows_before == rows_after, "append 幂等：二次 doctor 行集合不变（%d 行）" % len(rows_after))

        # 读侧 schema 校验：坏矩阵不静默（显式报错 或 恢复合法），绝不假绿
        with open(mpath, "w", encoding="utf-8") as f:
            f.write("{not-json-at-all")
        rc3, out3 = run_cli(entry, ["doctor"], env, timeout=120)
        ok_after, rows3 = read_rows(mpath)
        fail.check(rc3 != 0 or (ok_after and len(rows3) >= 1),
                   "坏矩阵注入后不静默：非零报错（rc=%d）或读侧校验恢复合法（%d 行）" % (rc3, len(rows3)))
    finally:
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
