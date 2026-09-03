"""integration/t260902-09/t01_creds_merge.py 迁入 UT（manifest 退役分流：原脚本断言即测试体，薄包装零改写）。"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "integration/t260902-09/t01_creds_merge.py"
REPO = Path(__file__).resolve().parents[4]


def test_t260902_09_t01_creds_merge():
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(REPO),
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout[-2000:] + proc.stderr[-2000:])
