#!/usr/bin/env python3
"""sc_profile_plugin_mounts.py — 控制台 profile 的插件挂载必须「可解析」（离线秒级，ro 池）。

来历（260929 实报，本岗复核 t260928-28 合并件时发现）：守望者插件把挂载行写进了
server/profile/cordis.patch.yml 与 profile-headless，却**没有同批落 node_modules 软链**
（部署面=仓内 profile 目录，`~/.dsh/profiles/sandbar` 即指向 server/profile）⇒ 挂载**不可解析**：
现在是「插件永远不生效」，下一次控制台重启则是**启动期插件装载失败**（宿主面直接受影响）。
仓里对「新增顶层声明键」已有派生式锁（sc_registry_additive_keys A2），对「新增插件挂载」
此前一条锁都没有——本场景补上，判据同族：**声明的东西必须能被解析**。

判据（全部静态、零进程、零 3099 接触）：
  A1 每个 profile 的挂载清单可从 cordis.patch.yml 里派生出来（派生为空=红：防闸空转）；
  A2 每个挂载名在 <profile>/node_modules/<name> 有软链，且软链指向存在的目录；
  A3 该目录有 package.json，其 name == 挂载名（挂错链=同族故障）；
  A4 package.json 的 exports/main 指向存在的入口文件。
退出码：0 全绿 / 1 红 / 2 ENV（profile 目录缺席=环境面）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILES = ("server/profile", "server/profile-headless")

PASS = 0
FAIL = 0

#: 挂载形：`- insert:` 下的 `- id: X` / `name: 'X'`（id 与 name 同值=裸包名挂载）
MOUNT_RE = re.compile(r"^\s*-\s*id:\s*([A-Za-z0-9_@/.-]+)\s*$", re.M)


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  \u2713 %s" % label)
    else:
        FAIL += 1
        print("  \u2717 %s" % label)
    return bool(cond)


def mounts_of(patch_file: Path):
    if not patch_file.is_file():
        return None
    return sorted(set(MOUNT_RE.findall(patch_file.read_text(encoding="utf-8"))))


def repo_plugin_dirs():
    """本仓提供的插件包：server/plugins/*/package.json 的 name → 插件目录。"""
    out = {}
    for pkg in sorted((ROOT / "server/plugins").glob("*/package.json")):
        try:
            name = json.loads(pkg.read_text(encoding="utf-8")).get("name")
        except ValueError:
            continue
        if name:
            out[str(name)] = pkg.parent
    return out


def main() -> int:
    total = 0
    ours = repo_plugin_dirs()
    if not ours:
        print("ENV_FAIL: server/plugins/*/package.json 一个都读不到（环境面）")
        return 2
    for rel in PROFILES:
        prof = ROOT / rel
        patch = prof / "cordis.patch.yml"
        if not prof.is_dir():
            print("ENV_FAIL: profile 目录缺席 %s" % rel)
            return 2
        print("\n== %s ==" % rel)
        names = mounts_of(patch)
        if names is None:
            print("ENV_FAIL: %s 缺席" % patch.relative_to(ROOT))
            return 2
        ok(bool(names), "挂载清单可派生（空=闸空转）：%s 项" % len(names))
        # 只对本仓提供的插件包做「必须可解析」判定：dsh 自带插件（webserver/schedule/
        # agent-presets…）由 dsh 安装面解析，不在本仓 profile/node_modules 下——按面归类，
        # 不硬编码名单（本仓插件集从 server/plugins/*/package.json 派生）。
        local = [n for n in names if n in ours]
        ok(bool(local), "其中本仓插件挂载 %d 项：%s" % (len(local), local))
        for name in local:
            total += 1
            link = prof / "node_modules" / name
            if not ok(link.exists(), "挂载 %s: node_modules/%s 可解析" % (name, name)):
                continue
            target = link.resolve()
            ok(target == ours[name].resolve(),
               "挂载 %s: 指向本仓插件目录（实得 %s）" % (name, target.name))
            pkg = target / "package.json"
            if not ok(pkg.is_file(), "挂载 %s: 目标含 package.json" % name):
                continue
            entry = (json.loads(pkg.read_text(encoding="utf-8")).get("exports") or {}).get(".")
            entry = entry or json.loads(pkg.read_text(encoding="utf-8")).get("main") or "index.js"
            ok((target / str(entry)).exists(), "挂载 %s: 入口 %s 存在" % (name, entry))
    print("\n==== summary: PASS=%d FAIL=%d（本仓挂载点 %d）" % (PASS, FAIL, total))
    if total == 0:
        print("FAIL: 零本仓挂载点——场景无可验对象（修场景而非改环境）")
        return 1
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
