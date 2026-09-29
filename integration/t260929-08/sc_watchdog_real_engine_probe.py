#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_real_engine_probe.py — 引擎存活判据的真探针锁（t260929-08，灰盒 L3，自管监听口零 7233 接触）。

intent（用户可感知行为=「面板引擎在线状态是真布尔；引擎在线绝不因看板读不到而误报
『引擎不可达』」——工单证据第 3 条的假警报面）：本条是**包装场景**，被测体= developer
交付的真宿主台 server/plugins/watchdog/bench/host-session-signals-bench.mjs（--leg engine）。
探针目标端口经 SANDBAR_ENGINE_PORT 覆写指向 **bench 自己起/自己收的**临时监听口——
不接触真 7233、不接触 3099（docs/testing-guide.md 红线；SANDBAR_ENGINE_PORT 覆写面
本身也是本条要守的部署承诺）。判据：
- 端口有监听 → engineOnline.online=true（真布尔，不再恒 null）；
- 端口关闭 → engine_down redline 落账且 online=false（不再从 board.ok 派生出
  「unknown 但报警」的自相矛盾态）；
- 端口开 + 看板读失败（t260929-07 未修期间的真实形态）→ **不**产 engine_down
  （假警报锁；降级面由 reconcile_degraded 另行可见）；
- 畸形 SANDBAR_ENGINE_PORT（非数字/越界）→ 显式 ENV_FAIL/显式错误点名，不静默
  回落成「看起来正常」。

intent 分工：engine_down 判据与告警去重面归 t260928-28 各条（探针为桩）；本条只锁
「探针=真 TCP 连通性」与「看板故障≠引擎下线」两桩够不到的面。

三态：node 或 dsh 0.1.5 安装缺席=ENV_FAIL exit 2；bench 缺席/断言红=FAIL exit 1
点名（TDD 红属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-08/sc_watchdog_real_engine_probe.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BENCH = REPO / "server" / "plugins" / "watchdog" / "bench" / "host-session-signals-bench.mjs"
LEG = "engine"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（bench 是 node 缝）")
        sys.exit(2)
    dsh = pathlib.Path.home() / ".sandbar" / "dsh-015"
    if not dsh.is_dir():
        print("ENV_FAIL: dsh 0.1.5 安装缺席：%s（真宿主需要）" % dsh)
        sys.exit(2)
    if not BENCH.is_file():
        print("FAIL: 真宿主信号台未落地：%s（工单 scope 3 交付面；TDD 红属预期）" % BENCH)
        sys.exit(1)
    p = subprocess.run(["node", str(BENCH), "--leg", LEG], capture_output=True, text=True,
                       cwd=str(REPO), timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    if p.returncode == 2 or "[ENV_FAIL]" in out:
        print("FAIL: bench 自报环境缺件（ENV_FAIL 必须以 exit 2 透传）")
        sys.exit(2)
    if p.returncode != 0:
        print("FAIL: bench 退出码 %d（真机引擎探针面有红，见上方输出点名）" % p.returncode)
        sys.exit(1)
    pass_n = re.findall(r"PASS[=:]\s*(\d+)", out)
    fail_n = re.findall(r"FAIL[=:]\s*(\d+)", out)
    if fail_n and int(fail_n[-1]) > 0:
        print("FAIL: bench 自报 FAIL=%s" % fail_n[-1])
        sys.exit(1)
    if not pass_n:
        print("FAIL: bench 输出无 PASS 汇总行（不可判定=红）")
        sys.exit(1)
    print("PASS=%s" % pass_n[-1])
    sys.exit(0)


if __name__ == "__main__":
    main()
