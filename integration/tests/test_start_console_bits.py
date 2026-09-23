#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start-console.sh 的「dsh 安装 bits 指纹对账」回归用例（260923 事故后落地）。

事故形态（260923 实弹）：`npm install -g @deepseek-ai/dsh@0.1.5-rc.2` 装出来的
那一套，与 09-21 验证过的 tarball 解包**不是同一套 bits**——dsh 的依赖写的是
semver 区间，09-23 解析到的 cordis 族各高一档，其中 cordis-plugin-hmr 1.0.18
**删掉了 registerConfig**；而 launcher（dsh-app-boot watchUserPatches）在
profile patchReload=live（自定义 profile 缺省值）下必调该 API ⇒ 该安装自不相容，
而「version 字段 == 0.1.5-rc.2」这一步两套都过——只校版本号判不出可用。

本用例把守三层（全离线：假 bin、零真 dsh、零 Temporal、不占端口、不起服务）：
  ① 好套在位 → 壳选中它并正常启动；
  ② 坏套（版本漂移 / 缺 registerConfig）→ 壳响亮拒绝，且点名具体是哪项不符；
  ③ 显式 DSH_BIN 指向坏套 → 同样拒绝（不许静默换成另一套骗人）。

跑法（与 integration/tests 惯例一致，无自动跑点）：
  python3 integration/tests/test_start_console_bits.py
"""
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHELL = REPO / "start-console.sh"

# 已验证的解析集（09-21 tarball；`--before=2026-09-22` 可复现）
GOOD = {"cordis": "4.0.2", "cordis-plugin-loader": "1.0.3", "cordis-plugin-hmr": "1.0.17"}
# 09-23 npm 解析到的漂移集（hmr 1.0.18 已无 registerConfig）
DRIFTED = {"cordis": "4.0.3", "cordis-plugin-loader": "1.0.4", "cordis-plugin-hmr": "1.0.18"}


def make_install(root: pathlib.Path, versions, *, register_config: bool) -> pathlib.Path:
    """造一套假的 dsh 安装（布局对齐真安装：<root>/lib/node_modules/@deepseek-ai/dsh）。

    bin.js 是假可执行：起得来就打印 FAKE-DSH-EXEC，用于证明「壳确实走到了启动那一步」。
    """
    pkg = root / "lib" / "node_modules" / "@deepseek-ai" / "dsh"
    nm = pkg / "node_modules" / "@deepseek-ai"
    for name, ver in versions.items():
        d = nm / name
        (d / "lib").mkdir(parents=True, exist_ok=True)
        (d / "package.json").write_text(
            json.dumps({"name": name, "version": ver}), encoding="utf-8")
    if register_config:
        (nm / "cordis-plugin-hmr" / "lib" / "index.js").write_text(
            "async registerConfig(filename, refresh) {}\n", encoding="utf-8")
    (pkg / "lib").mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@deepseek-ai/dsh", "version": "0.1.5-rc.2"}), encoding="utf-8")
    (pkg / "lib" / "bin.js").write_text(
        '#!/bin/sh\necho "FAKE-DSH-EXEC $*"\n', encoding="utf-8")
    (pkg / "lib" / "bin.js").chmod(0o755)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    link = root / "bin" / "dsh"
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink("../lib/node_modules/@deepseek-ai/dsh/lib/bin.js", link)
    return link


def run_shell(args, env_extra=None, timeout=60):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        ["/bin/bash", str(SHELL), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(REPO),
    )


class BitsFingerprintGateTest(unittest.TestCase):
    """壳的选套/拦套行为（走真脚本，毫秒级红绿）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sandbar-bits-ut-")
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _isolated_env(self, *, path="/usr/bin:/bin", **extra):
        """隔离 HOME（免机器钉串扰）+ 收窄 PATH（免真 dsh 串扰）。"""
        home = self.tmp / "home"
        (home / ".sandbar").mkdir(parents=True, exist_ok=True)
        env = {"HOME": str(home), "PATH": path}
        env.update(extra)
        return env

    def test_good_bits_selected_and_started(self):
        """① 机器钉位放好套 → 壳选它、对账通过、真的走到启动。"""
        good = make_install(self.tmp / "good", GOOD, register_config=True)
        home = self.tmp / "home"
        (home / ".sandbar" / "dsh-015" / "bin").mkdir(parents=True, exist_ok=True)
        os.symlink(str(good), str(home / ".sandbar" / "dsh-015" / "bin" / "dsh"))
        r = run_shell(["--no-open"], self._isolated_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("bits 指纹对账通过", r.stdout)
        self.assertIn("FAKE-DSH-EXEC", r.stdout, "对账通过后没有走到启动那一步")

    def test_drifted_bits_refused_when_auto_discovering(self):
        """② 只有坏套在位 → 拒绝启动，且不许静默用上（点名原因）。"""
        bad = make_install(self.tmp / "bad", DRIFTED, register_config=False)
        home = self.tmp / "home"
        (home / ".sandbar" / "dsh-015" / "bin").mkdir(parents=True, exist_ok=True)
        os.symlink(str(bad), str(home / ".sandbar" / "dsh-015" / "bin" / "dsh"))
        r = run_shell(["--no-open"], self._isolated_env())
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("FAKE-DSH-EXEC", r.stdout, "坏套竟被启动")
        self.assertIn("cordis 族版本与已验证集不符", r.stderr)
        self.assertIn("hmr=1.0.18", r.stderr, "报错未点出实得的漂移版本")
        self.assertIn("没有一套 dsh 安装通过 bits 指纹对账", r.stderr)

    def test_version_ok_but_api_missing_refused(self):
        """②b 版本号对、但 hmr 里没有 launcher 必调的 registerConfig → 仍拒。

        这一条锁的是「因果」而非「版本清单」：事故里上游删的正是这个 API，
        版本号本身不构成可用性证据。
        """
        # 用 GOOD 版本号，但拿掉 registerConfig
        make_install(self.tmp / "fake-good", GOOD, register_config=False)
        home = self.tmp / "home"
        (home / ".sandbar" / "dsh-015" / "bin").mkdir(parents=True, exist_ok=True)
        os.symlink(str(self.tmp / "fake-good" / "bin" / "dsh"),
                   str(home / ".sandbar" / "dsh-015" / "bin" / "dsh"))
        r = run_shell(["--no-open"], self._isolated_env())
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("没有 registerConfig", r.stderr)

    def test_explicit_bad_bin_refused_not_silently_swapped(self):
        """③ 显式指定坏套 → 拒绝（而不是偷偷换另一套起）——升级预演要能信 DSH_BIN。"""
        bad = make_install(self.tmp / "bad", DRIFTED, register_config=False)
        good = make_install(self.tmp / "good", GOOD, register_config=True)
        home = self.tmp / "home"
        (home / ".sandbar" / "dsh-015" / "bin").mkdir(parents=True, exist_ok=True)
        # 机器钉位放好套：显式指定坏套时也**不许**回落到它
        os.symlink(str(good), str(home / ".sandbar" / "dsh-015" / "bin" / "dsh"))
        r = run_shell(["--no-open"], self._isolated_env(DSH_BIN=str(bad)))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("显式指定的 DSH_BIN", r.stderr)
        self.assertNotIn("FAKE-DSH-EXEC", r.stdout)

    def test_explicit_missing_path_refused(self):
        """③b 显式路径不存在 → 报「无法定位安装根」，不猜不静默。"""
        r = run_shell(["--no-open"], self._isolated_env(
            DSH_BIN=str(self.tmp / "nope" / "bin" / "dsh")))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("无法从 bin 定位安装根", r.stderr)

    def test_skip_switch_lets_it_through(self):
        """升级预演逃生门：明知 bits 不对也能起（但必须留痕）。"""
        bad = make_install(self.tmp / "bad", DRIFTED, register_config=False)
        r = run_shell(["--no-open"], self._isolated_env(
            DSH_BIN=str(bad), SANDBAR_SKIP_DSH_BITS_CHECK="1"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SANDBAR_SKIP_DSH_BITS_CHECK=1", r.stderr)
        self.assertIn("FAKE-DSH-EXEC", r.stdout)


class ShellStaticGuardTest(unittest.TestCase):
    """壳源码静态防呆（机制化，不靠记忆）。"""

    def test_no_bare_var_adjacent_to_multibyte(self):
        # t260913-02 同族：裸 $VAR 紧跟全角字符时 macOS bash 把全角字符首字节
        # 并入变量名 → set -u 下 unbound variable（本次改壳实弹踩中过一次）。
        src = SHELL.read_text(encoding="utf-8")
        bad = [
            f"{i}: {line.strip()[:60]}"
            for i, line in enumerate(src.splitlines(), 1)
            if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)
        ]
        self.assertEqual(bad, [], "存在 $VAR 紧贴全角字符（应写 ${VAR}）：\n" + "\n".join(bad))

    def test_no_unchecked_bin_fallback(self):
        # 回归钉子：裸 `command -v dsh` 直接当启动体（260923 的复发入口）必须
        # 已经过指纹对账——静态把守「默认取值不得绕过 bits_check」。
        src = SHELL.read_text(encoding="utf-8")
        self.assertNotIn('DSH_BIN="${DSH_BIN:-$(command -v dsh', src,
                         "默认 dsh 取值又绕过了 bits 指纹对账")


if __name__ == "__main__":
    unittest.main(verbosity=2)
