"""server/dsh/temporal-poc 单元测试包（t260902-10 测试体系 L1）。

最小 conftest：只把被测包目录加进 sys.path，无其它魔法。
运行：仓库根 `server/dsh/temporal-poc/.venv/bin/python -m pytest server/dsh/temporal-poc/tests -q`
（venv 缺失时用任一装有 pytest 的解释器；UT 全程禁网络/真 Temporal/真 git）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
