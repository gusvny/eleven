"""integration/t260901-19/t03_suggest_next_precache.py 迁入 UT（manifest 退役分流：原脚本断言即测试体，薄包装零改写）。"""
import os
import subprocess
import sys
from pathlib import Path

from shared import TEST_STUB_ENV_KNOBS

SCRIPT = Path(__file__).resolve().parents[3] / "integration/t260901-19/t03_suggest_next_precache.py"
REPO = Path(__file__).resolve().parents[3]

# 环境净化（t260908-01 实证）：本脚本断言 suggest_next 的真实行为契约，而引擎的
# 桩旋钮族（shared.TEST_STUB_ENV_KNOBS）是测试台线束——merge_check 在桩脑工单
# 的泳道里跑 verify_lane 时这些旋钮随 worker env 漏进 pytest 子进程，会把被测
# 行为换成桩行为造成假红（e2e 实证 FAIL ok-hit-marker）。UT 语义=「无论 ambient
# 如何，本契约恒真」，故显式剥除（单一真源=shared，merge_check 调用点同款）。


def test_t260901_19_t03_suggest_next_precache():
    env = {k: v for k, v in os.environ.items() if k not in TEST_STUB_ENV_KNOBS}
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout[-2000:] + proc.stderr[-2000:])
