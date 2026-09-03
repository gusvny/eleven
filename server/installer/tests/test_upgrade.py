"""upgrade 单测：契约⑧解析、必查项映射、--to 畸形态全 fail-closed。"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
ROOT = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

from installer import upgrade  # noqa: E402
from version import VersionError  # noqa: E402

CONTRACT = ROOT / "docs" / "design" / "sandbar项目接入契约v1.md"


class ParseRealContractTest(unittest.TestCase):
    """真源副本（仓内同源副本）解析——副本缺节/坏格式的正反向都有专测。"""

    def test_schema_and_points(self):
        c = upgrade.load_contract(ROOT)
        self.assertEqual(c["schema"], "v1")
        self.assertEqual(c["points"], ["0.1.1-rc.2"])

    def test_four_checks_with_codes(self):
        c = upgrade.load_contract(ROOT)
        self.assertEqual(len(c["checks"]), 4)
        codes = [x["codes"] for x in c["checks"]]
        self.assertEqual(codes, [["A3"], ["A4", "A5"], ["B1", "C1", "C2"], ["D1"]])

    def test_coverage_mapping(self):
        c = upgrade.load_contract(ROOT)
        cov = upgrade.coverage(c)
        self.assertEqual(cov[0][1], ["probe-settings-resolve"])
        self.assertEqual(cov[1][1], ["probe-runner-assembly"])
        self.assertEqual(sorted(cov[2][1]),
                         ["probe-home-layout", "probe-session-format"])
        self.assertEqual(cov[3][1], [])  # D1 无 fixture 探针，人工复扫

    def test_render_contains_anchors(self):
        c = upgrade.load_contract(ROOT)
        lines = upgrade.render_report(c, "0.1.0", target="0.2.0")
        blob = "\n".join(lines)
        for anchor in ("0.1.0", "0.1.1-rc.2", "A3", "A4", "B1", "C1", "D1", "v1",
                       "只读", "M2-D"):
            self.assertIn(anchor, blob, anchor)


class ParseMalformedTest(unittest.TestCase):
    def _tmp(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        self.addCleanup(pathlib.Path(f.name).unlink)
        return f.name

    def _base(self):
        return (ROOT / "docs" / "design" / "sandbar项目接入契约v1.md").read_text(encoding="utf-8")

    def test_missing_file(self):
        with self.assertRaisesRegex(upgrade.ContractError, "缺失"):
            upgrade.load_contract_text(ROOT, path="/no/such/contract.md")

    def test_no_section8(self):
        text = self._base().replace("### ⑧", "### 8").replace("⑧-1", "8-1")
        with self.assertRaisesRegex(upgrade.ContractError, "⑧"):
            upgrade.parse_contract(text)

    def test_no_points(self):
        text = self._base().replace("`0.1.1-rc.2`", "`x`")
        with self.assertRaisesRegex(upgrade.ContractError, "已验证点"):
            upgrade.parse_contract(text)

    def test_fewer_than_four_checks(self):
        text = self._base()
        # 删掉第 4 条必查项（headless SIGTERM 语义整段）
        idx = text.find("4. **headless SIGTERM 语义**")
        end = text.find("\n\n", idx)
        text = text[:idx] + text[end + 2:]
        with self.assertRaisesRegex(upgrade.ContractError, "不足四条"):
            upgrade.parse_contract(text)

    def test_check_without_touchpoint_code(self):
        text = self._base().replace("**headless SIGTERM 语义**（D1）",
                                    "**headless SIGTERM 语义**（无代号）")
        with self.assertRaisesRegex(upgrade.ContractError, "touchpoints 代号"):
            upgrade.parse_contract(text)


class PrecheckTest(unittest.TestCase):
    def _ver(self, content):
        f = tempfile.NamedTemporaryFile("w", suffix=".ver", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        self.addCleanup(pathlib.Path(f.name).unlink)
        return f.name

    def test_upgrade_target_ok(self):
        cur, tgt = upgrade.precheck("0.2.0", ROOT, version_path=str(ROOT / "VERSION"))
        self.assertEqual((cur, tgt), ("0.1.0", "0.2.0"))

    def test_bad_semver_red(self):
        for bad in ("abc", "1.2", "0.1.0-rc.1", "-1.0.0"):
            with self.assertRaises(VersionError, msg=bad):
                upgrade.precheck(bad, ROOT, version_path=str(ROOT / "VERSION"))

    def test_downgrade_red(self):
        with self.assertRaisesRegex(VersionError, "降版本"):
            upgrade.precheck("0.0.9", ROOT, version_path=str(ROOT / "VERSION"))
        with self.assertRaises(VersionError):
            upgrade.precheck("0.1.0", ROOT, version_path=str(ROOT / "VERSION"))  # 平级也非升序

    def test_dirty_version_red(self):
        with self.assertRaisesRegex(VersionError, "脏"):
            upgrade.precheck("0.2.0", ROOT, version_path=self._ver("garbage\n"))


if __name__ == "__main__":
    unittest.main()
