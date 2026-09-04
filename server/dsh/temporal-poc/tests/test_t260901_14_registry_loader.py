"""t260901-14 registry-loader：装载器 intent 承接（t260904-02 重指）。

原形态：subprocess 跑 integration/t260901-14/registry-loader.py——该目录随 sandbar
迁仓未入本仓（悬空 latent red，本仓 integration/ 只有 t260903-10/12/13，ls 可证）。
t260904-02 把装载器上收 temporal-poc/shared.py（KI-032 单一真源）后，本 intent 的
合法落点=直接驱动 shared 装载器：legacy / per-key / 隔离 / 空 / 未知 五态最小集。
全量用例（含 env 现读、key 白名单畸形、check_paths、硬闸行为级）在
test_t260904_02_registry_anchor.py——本文件保持原票号可见 + 最小五态，不重复全量。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402


def _mk(root, key, content):
    d = Path(root) / key
    d.mkdir(parents=True)
    (d / "project.yaml").write_text(content, encoding="utf-8")
    return d


_GOOD = "schema: v1\nproject:\n  - key: %s\n    name: n\n    dirs:\n      - /tmp/%s\n"


class RegistryLoaderLegacyIntent(unittest.TestCase):
    def test_legacy_env_mode(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="t260901-14-r-")
        legacy = os.path.join(tmp, "projects.yaml")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("projects:\n  - key: legacy\n    name: 旧档\n    dirs:\n      - /tmp/legacy\n")
        os.environ["SUYOU_PROJECTS_YAML"] = legacy
        try:
            projects, quarantined = shared.load_projects_registry()
            self.assertEqual(projects[0]["key"], "legacy")
            self.assertEqual(quarantined, [])
        finally:
            del os.environ["SUYOU_PROJECTS_YAML"]

    def test_per_key_scan_and_quarantine(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="t260901-14-p-")
        _mk(tmp, "good-one", _GOOD % ("good-one", "g"))
        _mk(tmp, "sick-one", "schema: v1\nproject:\n  - key: sick-one\n    name: n\n    dirs:\n      - /tmp/s\nxxx-bad-line: 1\n")
        os.environ["SANDBAR_PROJECTS_DIR"] = tmp
        try:
            projects, quarantined = shared.load_projects_registry()
            self.assertEqual([p["key"] for p in projects], ["good-one"])
            self.assertEqual(len(quarantined), 1)
            # 隔离条目按 key 可见原因
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("sick-one")
            self.assertIn("已隔离", str(cm.exception))
        finally:
            del os.environ["SANDBAR_PROJECTS_DIR"]

    def test_unknown_and_empty(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="t260901-14-u-")
        _mk(tmp, "only", _GOOD % ("only", "o"))
        os.environ["SANDBAR_PROJECTS_DIR"] = tmp
        try:
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("ghost")
            self.assertIn("未知项目", str(cm.exception))
        finally:
            del os.environ["SANDBAR_PROJECTS_DIR"]
        with self.assertRaises(ValueError) as cm2:
            shared.assert_registry_nonempty([], [])
        self.assertIn("没有任何项目条目", str(cm2.exception))


if __name__ == "__main__":
    unittest.main()
