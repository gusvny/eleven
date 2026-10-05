#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-02 UT：capture-lane 认证面裁决（KI-205 第六层，ticket required outcomes
2/3 的行为断言，与 server/ui-check/capture-lane.mjs selftest 8/8 同一张表）。

被测面（server/ui-check/capture-lane.mjs 导出纯函数，node 子进程直驱，零网络零
docker 零浏览器，秒级）：
- resolveAuthEntry：200 → browser-trust 裸 URL；401/303 + token → token-gate 兑换
  入口；401/303 无 token → 拒绝且文案点名「上一代 token 门面 + 本代 browser-trust
  （--trusted-host / token_source=none）+ 非时序」；未知状态 → 拒绝不猜。
- dshAuthFingerprint：可注入桩（fence/tokenOption 识别 + 缺席二进制容忍 unavailable）。

畸形输入纪律：另以 capture-lane --selftest（8/8 内含二进制垃圾/不可读日志/超长行）
覆盖 token 提取的畸形面——本文件不重复起那份，只钉 selftest 可跑且绿。

跑法：python3 integration/tests/test_capture_auth_surface.py
（stdlib-only + node 在 PATH，秒级）。
"""
import json
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
CAPTURE_LANE = REPO / "server" / "ui-check" / "capture-lane.mjs"

DRIVER = """
import { resolveAuthEntry, dshAuthFingerprint } from %s;
const cases = JSON.parse(process.argv[1]);
const out = cases.map((c) => {
  try {
    if (c.kind === "entry") {
      const r = resolveAuthEntry({ port: c.port, status: c.status, token: c.token || "",
                                   fingerprint: c.fingerprint || null });
      return { ok: r.ok, authMode: r.authMode, entryUrl: r.entryUrl || "",
               refusal: r.refusal || "" };
    }
    if (c.kind === "fp") {
      const r = dshAuthFingerprint({ bin: c.bin, helpArgs: c.helpArgs });
      return { fence: r.fence, tokenOption: r.tokenOption, source: r.source };
    }
    return { error: "unknown kind" };
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
});
process.stdout.write(JSON.stringify(out));
""" % json.dumps(CAPTURE_LANE.as_uri())


def drive(cases):
    p = subprocess.run(
        [sys.executable and "node", "--input-type=module", "-e", DRIVER, json.dumps(cases)],
        capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError(f"node driver failed rc={p.returncode}: {p.stderr[-500:]}")
    return json.loads(p.stdout)


class ResolveAuthEntryTest(unittest.TestCase):
    """认证面裁决表（t261006-02：probe-then-adapt，review 条件 2 的 303 谨慎口径）。"""

    def test_200_browser_trust_bare_url(self):
        (r,) = drive([{"kind": "entry", "port": 3199, "status": 200}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["authMode"], "browser-trust")
        self.assertEqual(r["entryUrl"], "http://127.0.0.1:3199/")

    def test_401_with_token_token_gate(self):
        (r,) = drive([{"kind": "entry", "port": 3199, "status": 401, "token": "tok123"}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["authMode"], "token-gate")
        self.assertEqual(r["entryUrl"], "http://127.0.0.1:3199/?token=tok123")

    def test_303_with_token_still_token_gate(self):
        # review 条件 2：303 不当 browser-trust（可能是登录跳转）——有 token 走兑换。
        (r,) = drive([{"kind": "entry", "port": 3199, "status": 303, "token": "tok123"}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["authMode"], "token-gate")

    def test_refusal_names_generation_surface(self):
        cases = [{"kind": "entry", "port": 3199, "status": st, "token": ""} for st in (401, 303)]
        for c, r in zip(cases, drive(cases)):
            self.assertFalse(r["ok"], f"HTTP {c['status']} 无 token 应拒绝")
            self.assertEqual(r["authMode"], "token-gate-no-token")
            for need in ("token 门面", "这一代构建", "--trusted-host",
                         "token_source=none", "SANDBAR_CAPTURE_LANE_BOOT_MS"):
                self.assertIn(need, r["refusal"],
                              f"拒绝文案须点名哪一代的哪个面（缺：{need}）")

    def test_unknown_status_refused_not_guessed(self):
        (r,) = drive([{"kind": "entry", "port": 3199, "status": 500}])
        self.assertFalse(r["ok"])
        self.assertIn("未认识的状态", r["refusal"])

    def test_fingerprint_does_not_flip_200(self):
        (r,) = drive([{"kind": "entry", "port": 3199, "status": 200,
                       "fingerprint": {"fence": True, "tokenOption": False, "source": "stub"}}])
        self.assertTrue(r["ok"])
        self.assertEqual(r["authMode"], "browser-trust")


class FingerprintTest(unittest.TestCase):
    """指纹面（ticket required outcome 3 的钉子）：可注入桩 + 缺席容忍。"""

    def test_fence_recognised(self):
        (r,) = drive([{"kind": "fp", "bin": sys.executable and "node",
                       "helpArgs": ["-e", "console.log('--trusted-host <a> --port <p>')"]}])
        self.assertTrue(r["fence"])
        self.assertFalse(r["tokenOption"])

    def test_token_option_recognised(self):
        (r,) = drive([{"kind": "fp", "bin": "node",
                       "helpArgs": ["-e", "console.log('--token <t>')"]}])
        self.assertTrue(r["tokenOption"])

    def test_missing_binary_tolerated(self):
        (r,) = drive([{"kind": "fp", "bin": "definitely-not-a-real-binary-t26100602",
                       "helpArgs": ["--profile", "web", "--help"]}])
        self.assertIsNone(r["fence"])
        self.assertTrue(r["source"].startswith("unavailable"))


class SelftestSmokeTest(unittest.TestCase):
    """capture-lane --selftest 全绿（含 8/8 认证面裁决表 + 畸形日志输入面）。"""

    def test_selftest_green(self):
        p = subprocess.run(["node", str(CAPTURE_LANE), "--selftest"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, f"selftest rc={p.returncode}\n{p.stdout[-800:]}\n{p.stderr[-800:]}")
        self.assertIn("8/8 绿", p.stdout)


if __name__ == "__main__":
    unittest.main()
