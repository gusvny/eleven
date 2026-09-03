"""matrix 单测：append 幂等、schema 校验 fail-closed、原子写。"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_DIR))

from installer import matrix  # noqa: E402


def _row(probe="probe-x"):
    return {"ts": 1, "sandbar_version": "0.1.0", "dsh_point": "0.1.1-rc.2",
            "project_schema": "v1", "probe": probe}


class MatrixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sandbar-ut-matrix-")
        self.path = os.path.join(self.tmp, "compat-matrix.json")

    def test_missing_file_empty(self):
        data = matrix.load(self.path)
        self.assertEqual(data, {"schema": 1, "rows": []})

    def test_append_and_idempotent(self):
        appended, n = matrix.append_row(self.path, "probe-x", "0.1.0", "0.1.1-rc.2", "v1")
        self.assertTrue(appended); self.assertEqual(n, 1)
        appended, n = matrix.append_row(self.path, "probe-x", "0.1.0", "0.1.1-rc.2", "v1")
        self.assertFalse(appended)  # 同键幂等
        self.assertEqual(n, 1)
        data = matrix.load(self.path)
        self.assertEqual(len(data["rows"]), 1)

    def test_append_different_probe_grows(self):
        matrix.append_row(self.path, "probe-a", "0.1.0", "0.1.1-rc.2", "v1")
        _, n = matrix.append_row(self.path, "probe-b", "0.1.0", "0.1.1-rc.2", "v1")
        self.assertEqual(n, 2)

    def test_corrupt_json_fail_closed(self):
        with open(self.path, "w") as f:
            f.write("{not-json")
        with self.assertRaises(matrix.MatrixError):
            matrix.load(self.path)

    def test_bad_schema_fail_closed(self):
        with open(self.path, "w") as f:
            json.dump({"schema": 99, "rows": []}, f)
        with self.assertRaisesRegex(matrix.MatrixError, "schema"):
            matrix.load(self.path)

    def test_row_missing_key_fail_closed(self):
        with open(self.path, "w") as f:
            json.dump({"schema": 1, "rows": [{"ts": 1, "probe": "x"}]}, f)
        with self.assertRaisesRegex(matrix.MatrixError, "缺键"):
            matrix.load(self.path)

    def test_row_bad_type_fail_closed(self):
        with open(self.path, "w") as f:
            json.dump({"schema": 1, "rows": [
                {"ts": "x", "sandbar_version": "", "dsh_point": "d",
                 "project_schema": "v1", "probe": "p"}]}, f)
        with self.assertRaises(matrix.MatrixError):
            matrix.load(self.path)

    def test_atomic_write_no_tmp_left(self):
        matrix.append_row(self.path, "probe-x", "0.1.0", "0.1.1-rc.2", "v1")
        leftovers = [f for f in os.listdir(self.tmp) if f.startswith(".compat-matrix-")]
        self.assertEqual(leftovers, [])

    def test_render(self):
        matrix.append_row(self.path, "probe-x", "0.1.0", "0.1.1-rc.2", "v1")
        out = matrix.render(matrix.load(self.path)["rows"])
        self.assertIn("probe-x", out)
        self.assertIn("0.1.1-rc.2", out)
        self.assertIn("未验证", matrix.render([]))


if __name__ == "__main__":
    unittest.main()
