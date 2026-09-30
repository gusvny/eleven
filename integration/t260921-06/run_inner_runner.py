#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内层执行器驱动（t260921-06 看守族专用）：假表注入跑一轮 run_scenarios.main()。

用法：run_inner_runner.py <table_json> [exclude_pools]
- table_json：[{"name","intent","cmd","pool"}]——SCENARIOS 覆写为该表（既有注入式
  电池手法，sc_executor/summary-count-purity 同款），不经 INTEG_RUN_LOCK（嵌套安全）；
- exclude_pools：透传 main(exclude_pools=…)；空=缺省全跑。
以独立子进程形态被看守场景驱动（env 由调用方完全掌控：注入/剥离 SANDBAR_STAGE_BATCH、
PATH 桩、等待预算旋钮），退出码=main() 返回码（三态契约原样）。
"""
import importlib.util
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"


def main():
    if len(sys.argv) < 2:
        print("usage: run_inner_runner.py <table_json> [exclude_pools]", file=sys.stderr)
        return 1
    table = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    exclude = sys.argv[2] if len(sys.argv) > 2 else ""
    if str(INTEG) not in sys.path:
        sys.path.insert(0, str(INTEG))
    spec = importlib.util.spec_from_file_location("rs_t26092106", str(INTEG / "run_scenarios.py"))
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    rs.SCENARIOS = [(e["name"], e["intent"], e["cmd"], e.get("pool")) for e in table]
    # 260930：内层执行器绝不继承外层泳道轮的收窄旋钮（剥完再跑）
    with no_narrowing_env():
        rc = rs.main(exclude_pools=(exclude or None))
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
