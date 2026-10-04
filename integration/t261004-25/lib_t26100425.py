#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-25 共享夹具（非 sc_ 前缀＝共享代码，不进 SCENARIOS）。

复用 t260916-19 的真 git 泳道夹具（mk_lane/settle/engine_modules——同机制、同
三态契约、同 tmp 自建仓纪律），只补本票需要的两块：
- MIN_VERIFY_YAML：merge_check 场景需要的最小 verify.yaml（lanes.code 声明，
  空命令表——写集白名单是纯 diff×write_set 判定，不跑命令检查）；
- run_verify_code：verify_lane code 道公开入口 run() 直调（公开组件契约面）。
跨票 import 走 sys.path.insert（共享 helpers 复用，纪律明文允许）。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LIB19 = REPO / "integration" / "t260916-19"
if str(LIB19) not in sys.path:
    sys.path.insert(0, str(LIB19))

from lib_t260916_19 import (  # noqa: E402,F401  (re-export)
    BASE, archive_find, apply_check, check, committed_names, engine_modules,
    env_fail, git, git_ok, head_count, head_sha, mk_lane, quarantine_root,
    read_file, rmtree, settle, status_entries, summary, tmpdir,
)

# 本票基线 = t260916-19 BASE + 最小 verify.yaml（merge_check 场景的 _cfg_load 需要）
BASE_WITH_VERIFY = dict(BASE)
BASE_WITH_VERIFY["verify.yaml"] = (
    "schema: v1\n"
    "lanes:\n"
    "  code:\n"
    "    write_allow:\n"
    "      - docs/\n"
    "    checks:\n"
    "      - id: noop\n"
    "        cmd: 'true'\n"
)


def run_verify_code(args):
    """verify_lane code 道公开入口（run({'lane':'code',...})），返回绿/红与检查项。

    进程内直调须走 no_narrowing_env（lint L12）：不继承外层泳道轮的收窄旋钮。"""
    if str(REPO / "integration") not in sys.path:
        sys.path.insert(0, str(REPO / "integration"))
    from lib_env import no_narrowing_env  # noqa: E402
    if str(REPO / "server" / "tools") not in sys.path:
        sys.path.insert(0, str(REPO / "server" / "tools"))
    import verify_lane  # noqa: E402
    payload = dict(args)
    payload["lane"] = "code"
    with no_narrowing_env():
        return verify_lane.run(payload)
