"""四面探针单测：fixture 红绿双向 + 畸形桩（坏 JSON/缺文件/截断流）。"""

from __future__ import annotations

import pathlib
import sys
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from probes import runner  # noqa: E402
from probes import probe_home_layout, probe_runner_assembly, probe_session_format, probe_settings_resolve  # noqa: E402
from probes import _miniyaml  # noqa: E402

FIX = runner.FIXTURE_ROOT


class RunnerAllTest(unittest.TestCase):
    def test_fixture_mode_four_green(self):
        results = runner.run_all(live=False)
        self.assertEqual([r.name for r in results], [
            "probe-home-layout", "probe-session-format",
            "probe-runner-assembly", "probe-settings-resolve"])
        for r in results:
            self.assertTrue(r.ok, r.line())


class HomeLayoutTest(unittest.TestCase):
    def test_good(self):
        r = probe_home_layout.run(FIX / "home_layout" / "good")
        self.assertTrue(r.ok, r.line())
        self.assertIn(".credentials.yaml", r.detail)
        self.assertIn("settings.yaml", r.detail)

    def test_missing_credentials_red(self):
        r = probe_home_layout.run(FIX / "home_layout" / "bad_missing")
        self.assertFalse(r.ok)
        self.assertIn(".credentials.yaml", r.detail)

    def test_wrong_name_red(self):
        """文件名指纹：credentials.yaml（无点）≠ .credentials.yaml。"""
        r = probe_home_layout.run(FIX / "home_layout" / "bad_wrong_name")
        self.assertFalse(r.ok)

    def test_absent_root_red(self):
        r = probe_home_layout.run(FIX / "no-such-root")
        self.assertFalse(r.ok)

    def test_none_root_red(self):
        self.assertFalse(probe_home_layout.run(None).ok)


class SessionFormatTest(unittest.TestCase):
    def test_good_usage_extracted(self):
        r = probe_session_format.run(FIX / "session" / "good" / "session.jsonl")
        self.assertTrue(r.ok, r.line())
        self.assertIn("inputTokens=11", r.detail)
        self.assertIn("cacheReadTokens=3", r.detail)

    def test_truncated_stream_red(self):
        r = probe_session_format.run(FIX / "session" / "bad_truncated" / "session.jsonl")
        self.assertFalse(r.ok)
        self.assertIn("截断", r.detail)

    def test_bad_json_red(self):
        r = probe_session_format.run(FIX / "session" / "bad_json" / "session.jsonl")
        self.assertFalse(r.ok)
        self.assertIn("JSON", r.detail)

    def test_missing_file_red(self):
        self.assertFalse(probe_session_format.run(None).ok)
        self.assertFalse(probe_session_format.run(FIX / "nope.jsonl").ok)

    def test_usage_missing_keys_red(self):
        import tempfile
        f = pathlib.Path(tempfile.mkstemp(suffix=".jsonl")[1])
        f.write_text('{"type":"assistant","message":{"data":{"usage":{"inputTokens":1}}}}\n',
                     encoding="utf-8")
        self.addCleanup(f.unlink)
        self.assertFalse(probe_session_format.run(f).ok)

    def test_zstd_magic_without_dep_declared(self):
        """zstd 魔数：依赖缺席=显式红并写明降级路径（不静默、不假装绿）。"""
        try:
            import zstandard  # noqa: F401
            has_dep = True
        except ImportError:
            has_dep = False
        if has_dep:
            self.skipTest("环境有 zstandard，本测只验缺依赖降级口径")
        import tempfile
        f = pathlib.Path(tempfile.mkstemp(suffix=".zst")[1])
        f.write_bytes(b"\x28\xb5\x2f\xfd" + b"garbage")
        self.addCleanup(f.unlink)
        r = probe_session_format.run(f)
        self.assertFalse(r.ok)
        self.assertIn("zstandard", r.detail)
        self.assertIn("降级", r.detail)


class RunnerAssemblyTest(unittest.TestCase):
    def test_good(self):
        r = probe_runner_assembly.run(FIX / "runner" / "good" / "dsh-dist")
        self.assertTrue(r.ok, r.line())

    def test_missing_inject_red(self):
        r = probe_runner_assembly.run(FIX / "runner" / "bad_no_inject" / "dsh-dist")
        self.assertFalse(r.ok)
        self.assertIn("inject", r.detail)

    def test_bad_json_red(self):
        r = probe_runner_assembly.run(FIX / "runner" / "bad_json" / "dsh-dist")
        self.assertFalse(r.ok)
        self.assertIn("JSON", r.detail)

    def test_no_json_at_all_red(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.assertFalse(probe_runner_assembly.run(d).ok)


class SettingsResolveTest(unittest.TestCase):
    def test_good(self):
        r = probe_settings_resolve.run(FIX / "settings" / "good")
        self.assertTrue(r.ok, r.line())

    def test_resolve_semantics(self):
        merged = probe_settings_resolve.resolve(
            {"model": {"gui_default": "g-ui"}, "theme": "dark"},
            {"model": {"route": "g-route"}})
        self.assertEqual(merged, {"model": {"gui_default": "g-ui", "route": "g-route"},
                                  "theme": "dark"})
        # patch 深层键必须胜出（不被用户层静默盖掉）
        merged2 = probe_settings_resolve.resolve(
            {"model": {"route": "user-wins"}},
            {"model": {"route": "decl-wins"}})
        self.assertEqual(merged2["model"]["route"], "decl-wins")

    def test_bad_yaml_red(self):
        r = probe_settings_resolve.run(FIX / "settings" / "bad_yaml")
        self.assertFalse(r.ok)
        self.assertIn("解析失败", r.detail)

    def test_missing_patch_red(self):
        r = probe_settings_resolve.run(FIX / "settings" / "bad_missing_patch")
        self.assertFalse(r.ok)


class MiniYamlTest(unittest.TestCase):
    def test_good_subset(self):
        text = ("# 注释\n"
                "model:\n"
                "  gui_default: g-ui\n"
                "  route: g-route   # 行尾注释\n"
                "theme: dark\n"
                "retries: 3\n"
                "ratio: 0.5\n"
                "debug: false\n"
                "label: \"quoted: value\"\n"
                "items:\n"
                "  - a\n"
                "  - b\n")
        data = _miniyaml.loads(text)
        self.assertEqual(data, {
            "model": {"gui_default": "g-ui", "route": "g-route"},
            "theme": "dark", "retries": 3, "ratio": 0.5, "debug": False,
            "label": "quoted: value", "items": ["a", "b"]})

    def test_tab_indent_red(self):
        with self.assertRaises(_miniyaml.YamlError):
            _miniyaml.loads("model:\n\tkey: v\n")

    def test_duplicate_key_red(self):
        with self.assertRaisesRegex(_miniyaml.YamlError, "重复键"):
            _miniyaml.loads("a: 1\na: 2\n")

    def test_flow_syntax_red(self):
        with self.assertRaisesRegex(_miniyaml.YamlError, "flow"):
            _miniyaml.loads("a: {b: c}\n")

    def test_unclosed_quote_red(self):
        with self.assertRaises(_miniyaml.YamlError):
            _miniyaml.loads('a: "unclosed\n')

    def test_inconsistent_indent_red(self):
        with self.assertRaises(_miniyaml.YamlError):
            _miniyaml.loads("a:\n    b: 1\n  c: 2\n")

    def test_missing_file_red(self):
        with self.assertRaises(_miniyaml.YamlError):
            _miniyaml.load_file("/no/such/file.yaml")


if __name__ == "__main__":
    unittest.main()
