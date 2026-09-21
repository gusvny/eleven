#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_console 壳 + UI 面断言库的行为断言 UT（t260916-25）。

零 Temporal、零真 dsh、零外网：护栏用例走真壳脚本（毫秒级红绿），断言库用例
走 lib --selftest（内置本地 stub，覆盖畸形输入：500/慢响应/截断 HTML/无
script/空 bundle/二进制乱码/非 JSON API/坏参数/红线静态自保）。

跑法（无自动跑点，手工口径，与 tests/ 目录惯例一致）：
  python3 integration/tests/test_stage_console.py
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHELL = REPO / "server" / "tools" / "stage_console.sh"
LIB = REPO / "integration" / "lib_stage_ui_surface.mjs"


def run_shell(args, env_extra=None, timeout=60):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["/bin/sh", str(SHELL), *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )


def port_free(port):
    r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                       capture_output=True, text=True)
    return r.returncode != 0 or not r.stdout.strip()


class ShellSyntaxTest(unittest.TestCase):
    def test_sh_n_green(self):
        r = subprocess.run(["/bin/sh", "-n", str(SHELL)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class GuardTests(unittest.TestCase):
    """护栏红绿：保护端口硬拒、畸形参数 usage 红（起台类命令无副作用路径）。"""

    def test_3099_rejected(self):
        r = run_shell(["start", "--port", "3099", "--home", tempfile.mkdtemp()])
        self.assertEqual(r.returncode, 2)
        self.assertIn("保护面", r.stderr)
        self.assertIn("3099", r.stderr)

    def test_7233_rejected(self):
        r = run_shell(["start", "--port", "7233", "--home", tempfile.mkdtemp()])
        self.assertEqual(r.returncode, 2)
        self.assertIn("保护面", r.stderr)

    def test_8233_rejected(self):
        r = run_shell(["prepare", "--port", "8233", "--home", tempfile.mkdtemp()])
        self.assertEqual(r.returncode, 2)
        self.assertIn("保护面", r.stderr)

    def test_port_must_be_number(self):
        r = run_shell(["start", "--port", "abc"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--port", r.stderr)

    def test_port_out_of_range(self):
        r = run_shell(["start", "--port", "99999"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("越界", r.stderr)

    def test_missing_flag_value(self):
        r = run_shell(["start", "--port"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("缺值", r.stderr)

    def test_unknown_flag(self):
        r = run_shell(["start", "--bogus"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--bogus", r.stderr)

    def test_unknown_subcommand(self):
        r = run_shell(["frobnicate"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("未知子命令", r.stderr)

    def test_start_without_version_or_dsh_root(self):
        # 过端口护栏后（用冷口），resolve 前置校验应 usage 红。
        port = "39571"
        if not port_free(port):
            self.skipTest(f"冷口 {port} 被占，跳过")
        home = tempfile.mkdtemp()
        src = os.path.join(home, "src")
        os.makedirs(src)  # src-home 必须存在（真源只读面）
        r = run_shell(["start", "--port", port, "--home", os.path.join(home, "st"),
                       "--src-home", src])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--version", r.stderr)

    def test_home_equals_src_home_rejected(self):
        port = "39572"
        if not port_free(port):
            self.skipTest(f"冷口 {port} 被占，跳过")
        home = tempfile.mkdtemp()
        r = run_shell(["start", "--port", port, "--home", home, "--src-home", home])
        self.assertEqual(r.returncode, 2)
        self.assertIn("不得等于 --src-home", r.stderr)

    def test_home_production_dsh_rejected(self):
        # HOME 指向临时目录（零真机耦合）：~/.dsh=临时 .dsh，home 命中生产 home 护栏。
        port = "39573"
        if not port_free(port):
            self.skipTest(f"冷口 {port} 被占，跳过")
        fake_home = tempfile.mkdtemp()
        os.makedirs(os.path.join(fake_home, ".dsh"))
        os.makedirs(os.path.join(fake_home, "othersrc"))
        r = run_shell(
            ["start", "--port", port,
             "--home", os.path.join(fake_home, ".dsh"),
             "--src-home", os.path.join(fake_home, "othersrc")],
            env_extra={"HOME": fake_home},
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("生产 home", r.stderr)


class KillOwnershipStaticTest(unittest.TestCase):
    """gen16 打回项静态防呆（机制化，防盲杀回潮）：stop 主链与 start 幂等分支
    必须先经 ps_refresh + pid_class 归属核对才许杀伐；孤儿补杀必须走 our_pids
    锚判据（判据单点化，不许裸 grep 锚散落）。行为级对抗面归
    sc_stage_console_fault_paths 子用例 A/B（宿主 ps 环境跑）。"""

    def setUp(self):
        import re
        self.re = re
        self.src = SHELL.read_text(encoding="utf-8")

    def section(self, name):
        # 取函数体：定义行起，到下一个顶级（零缩进）行为止。
        # 函数体到首个顶格「}」（函数收尾）为止——die_red 多行文案的续行
        # （$(tail …) 顶格）会骗过「下一个零缩进行」朴素切法。
        m = self.re.search(rf"^{name}\(\) \{{(.*?)(?=^\}})",
                           self.src, self.re.S | self.re.M)
        self.assertIsNotNone(m, f"{name} 函数体未找到")
        return m.group(1)

    def test_stop_kill_gated_by_ownership_check(self):
        body = self.section("cmd_stop")
        self.assertIn("ps_refresh", body, "stop 主链缺 ps_refresh（ps 盲 fail-closed 门）")
        self.assertIn("pid_class", body, "stop 主链缺 pid_class 归属核对")
        self.assertLess(body.index("pid_class"), body.index("kill_group"),
                        "stop 的 kill_group 出现在 pid_class 之前——盲杀回潮")

    def test_stop_orphan_rekill_uses_anchor_helper(self):
        body = self.section("cmd_stop")
        self.assertIn("our_pids", body, "孤儿补杀缺 our_pids 锚判据")
        self.assertNotIn("grep -F", body, "锚判据必须单点在 our_pids/pid_class，不许裸 grep")

    def test_start_idempotent_branch_gated(self):
        body = self.section("cmd_start")
        self.assertIn("pid_class", body, "start 幂等分支缺 pid_class 归属核对")
        self.assertIn("已在跑", body, "start 幂等分支缺「已在跑」幂等出口")

    def test_ps_probe_single_point(self):
        # ps 调用只许出现在 ps_refresh 一处（判据/旗标单点化；头注释里的文档
        # 提及不算——只数非注释行的真实调用）。
        calls = [ln for ln in self.src.splitlines()
                 if "ps -axEo" in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(len(calls), 1, f"ps -axEo 调用应单点化在 ps_refresh，现 {len(calls)} 处")
        body = self.section("ps_refresh")
        self.assertIn("ps -axEo", body, "ps 调用应位于 ps_refresh 函数体内")


class StartReapStaticTest(unittest.TestCase):
    """gen17 打回项静态防呆：start 的「台没起成」终态（URL 静默含在内）必须
    收掉自起进程组 + 清 pidfile，不许「保留运行」悬空台回潮（行为级对抗面归
    sc_stage_console_fault_paths 的 D 子用例，宿主跑）。"""

    def setUp(self):
        import re
        self.re = re
        self.src = SHELL.read_text(encoding="utf-8")

    def section(self, name):
        # 函数体到首个顶格「}」（函数收尾）为止——die_red 多行文案的续行
        # （$(tail …) 顶格）会骗过「下一个零缩进行」朴素切法。
        m = self.re.search(rf"^{name}\(\) \{{(.*?)(?=^\}})",
                           self.src, self.re.S | self.re.M)
        self.assertIsNotNone(m, f"{name} 函数体未找到")
        return m.group(1)

    def test_url_silent_path_reaps_own_process(self):
        body = self.section("cmd_start")
        self.assertNotIn("保留运行", body, "URL 静默路「保留运行」悬空台文案回潮")
        self.assertIn("已停掉自起进程", body, "URL 静默 die_red 文案缺「已停掉自起进程」")
        # URL 宽限旋钮（GRACE 首现）之后、URL 静默 die_red 之前必须有 kill_group
        # 收台 + 清 pidfile（端口未就绪超时路的 kill_group 在 GRACE 之前，不计入；
        # 「已停掉自起进程」有两处文案，取最后一处=URL 静默）。
        grace = body.index("GRACE")
        silent_red = body.rindex("已停掉自起进程")
        self.assertIn("kill_group", body[grace:silent_red],
                      "URL 静默路未在 die_red 前 kill_group 收台")
        self.assertIn("rm -f", body[grace:silent_red],
                      "URL 静默路未清 pidfile")


class ShellStaticGuardTest(unittest.TestCase):
    """壳源码静态防呆（机制化，不靠记忆）。"""

    def test_no_bare_var_adjacent_to_multibyte(self):
        # t260913-02 同族（本票实弹踩中 20 处后根治）：裸 $VAR 紧跟全角字符时
        # macOS bash 把全角字符首字节并入变量名 → set -u 下 unbound variable。
        # 壳内一律 ${VAR} 花括号形式，本用例机械把守。
        import re
        src = SHELL.read_text(encoding="utf-8")
        bad = [
            f"{i}: {line.strip()[:60]}"
            for i, line in enumerate(src.splitlines(), 1)
            if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)
        ]
        self.assertEqual(
            bad, [],
            "存在 $VAR 紧贴全角字符（应写 ${VAR}）：\n" + "\n".join(bad),
        )


class LibSelftestTest(unittest.TestCase):
    def test_lib_selftest_green(self):
        r = subprocess.run(["node", str(LIB), "--selftest"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout or "") + (r.stderr or ""))
        self.assertIn("绿", r.stdout)

    def test_lib_usage_red(self):
        r = subprocess.run(["node", str(LIB)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--base-url", r.stderr)


class ChecklistTest(unittest.TestCase):
    def test_checklist_prints_readonly_warning(self):
        r = run_shell(["checklist"])
        self.assertEqual(r.returncode, 0, r.stderr)
        # R7：警示到达面——清单打印必须带只读警示。
        self.assertIn("生产", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
