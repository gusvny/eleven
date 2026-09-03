"""快照键结构测试：sandbar_version 键落位 + legacy temporal_engine_version 原样。

快照组装点在 temporal-poc 引擎代码里（base.py / dev_lane.py），依赖 temporalio，
系统 python3 无该依赖——故用 AST 结构断言（对源码静态验证，行为面由
version.py 行为单测补齐），不 import 引擎模块。
"""

from __future__ import annotations

import ast
import pathlib
import unittest

POC = pathlib.Path(__file__).resolve().parents[3] / "server" / "dsh" / "temporal-poc"


def _snapshot_dicts(path: pathlib.Path):
    """返回文件里所有含 temporal_engine_version 键的字面 dict 的键集合列表。

    每文件恰有两处：一处组装点（含 workflow_input 键），一处 meta 回读视图
    （值形如 self.meta.get(...)）。范围纪律=只动组装点，回读视图不加键。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = set()
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
            if "temporal_engine_version" in keys:
                found.append(keys)
    return found


class SnapshotKeysTest(unittest.TestCase):
    def test_legacy_key_sites_are_two_per_file(self):
        for name in ("base.py", "dev_lane.py"):
            self.assertEqual(len(_snapshot_dicts(POC / name)), 2, name)

    def test_assembly_point_has_sandbar_version_legacy_view_does_not(self):
        for name in ("base.py", "dev_lane.py"):
            assembly = [d for d in _snapshot_dicts(POC / name)
                        if "workflow_input" in d]
            views = [d for d in _snapshot_dicts(POC / name)
                     if "workflow_input" not in d]
            self.assertEqual(len(assembly), 1, name)
            self.assertEqual(len(views), 1, name)
            self.assertIn("sandbar_version", assembly[0], name)
            self.assertNotIn("sandbar_version", views[0], name)

    def test_legacy_key_assignment_untouched(self):
        """legacy int 键仍取 self.engine_version（int 语义未动）。"""
        for name in ("base.py", "dev_lane.py"):
            src = (POC / name).read_text(encoding="utf-8")
            self.assertIn('"temporal_engine_version": self.engine_version,', src)

    def test_sandbar_version_from_version_module(self):
        for name in ("base.py", "dev_lane.py"):
            src = (POC / name).read_text(encoding="utf-8")
            self.assertIn('_sandbar_version()', src, name)
            self.assertIn("import version as _version", src, name)


if __name__ == "__main__":
    unittest.main()
