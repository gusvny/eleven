"""integration/t260901-26/i03_lane_merge_scope.py 迁入 UT（manifest 退役分流：原脚本断言即测试体，薄包装零改写）。"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "integration/t260901-26/i03_lane_merge_scope.py"
REPO = Path(__file__).resolve().parents[3]


def test_t260901_26_i03_lane_merge_scope():
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(REPO),
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout[-2000:] + proc.stderr[-2000:])
