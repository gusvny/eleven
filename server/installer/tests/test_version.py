"""version.py 单测：三态（正常/缺失/脏）全 fail-closed，畸形输入用桩文件复现。"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
ROOT = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

from version import VersionError, parse_semver, read_version, version_tuple  # noqa: E402


class ParseSemverTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(parse_semver("0.1.0"), (0, 1, 0))
        self.assertEqual(parse_semver(" 1.20.3\n"), (1, 20, 3))

    def test_reject_leading_zero(self):
        with self.assertRaises(VersionError):
            parse_semver("01.1.0")

    def test_reject_various_dirty(self):
        for bad in ("0.1", "0.1.0.0", "v0.1.0", "0.1.0-rc.1", "", "0.1.0 x",
                    "０.１.０", "0.1.0\n0.2.0"):
            with self.assertRaises(VersionError, msg=bad):
                parse_semver(bad)


class ReadVersionTest(unittest.TestCase):
    def _tmp(self, content: str) -> pathlib.Path:
        f = tempfile.NamedTemporaryFile(
            "w", suffix="VERSION", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        self.addCleanup(pathlib.Path(f.name).unlink)
        return pathlib.Path(f.name)

    def test_normal(self):
        p = self._tmp("0.1.0\n")
        self.assertEqual(read_version(p), "0.1.0")
        self.assertEqual(version_tuple(p), (0, 1, 0))

    def test_normal_tolerates_blank_lines(self):
        self.assertEqual(read_version(self._tmp("\n0.2.0\n\n")), "0.2.0")

    def test_missing_fail_closed(self):
        with self.assertRaisesRegex(VersionError, "VERSION 缺失"):
            read_version(pathlib.Path(
                tempfile.gettempdir()) / "no-such-VERSION-xyz")

    def test_dirty_empty(self):
        with self.assertRaisesRegex(VersionError, "脏"):
            read_version(self._tmp("\n\n"))

    def test_dirty_two_lines(self):
        with self.assertRaisesRegex(VersionError, "2 行"):
            read_version(self._tmp("0.1.0\n0.2.0\n"))

    def test_dirty_not_semver(self):
        for bad in ("0.1.0-rc.1\n", "v0.1.0\n", "garbage\n"):
            with self.assertRaisesRegex(VersionError, "非 semver", msg=bad):
                read_version(self._tmp(bad))


class RepoVersionTest(unittest.TestCase):
    def test_repo_version_is_010(self):
        """仓根真实 VERSION 存在且为 0.1.0（本票基线）；缺失即红。"""
        self.assertEqual(read_version(ROOT / "VERSION"), "0.1.0")


if __name__ == "__main__":
    unittest.main()
