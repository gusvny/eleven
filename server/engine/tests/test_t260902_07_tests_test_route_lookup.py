"""integration/t260902-07/tests/test_route_lookup.py 迁入 UT（manifest 退役分流：原脚本断言即测试体，薄包装零改写）。"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "integration/t260902-07/tests/test_route_lookup.py"
REPO = Path(__file__).resolve().parents[3]


def test_t260902_07_tests_test_route_lookup():
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(REPO),
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout[-2000:] + proc.stderr[-2000:])
