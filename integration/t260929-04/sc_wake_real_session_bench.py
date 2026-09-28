#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_wake_real_session_bench.py — 「不丢」的真机证明面（t260929-04，灰盒 L3，隔离真宿主）。

intent（用户可感知行为=「排队简报真的落进一个真会话」——工单 scope 6 明言：只有桩
测试不算证明）：本条是**包装场景**，被测体= developer 交付的真宿主台
server/plugins/watchdog/bench/host-prompt-bench.mjs（隔离 temp DSH_HOME + 临时端口，
绝不接触 3099；同一 host API 通路 = sessionController.prompt(mode:'queue') +
control 镜像）。判据：bench 退出 0 且输出含 PASS 汇总；bench 内部已断言——
(a) 队列项在 control 流可见 (b) 消化后消息在会话内可读（不丢）
(c) 未消化窗内第二事件被守望路径扣下 (d) 消化后新事件再醒。

intent 分工：桩面行为归 sc_wake_host_api_delivery / sc_wake_digested_window（秒级、
TDD 期先行）；本条只锁「真宿主端到端同一通路」这一桩够不到的面——故两池并列，
互不顶替（KIT 取证纪律：复现真机面用定点场景，不用全套）。
三态：node 或 dsh 0.1.5 安装（~/.sandbar/dsh-015）缺席=ENV_FAIL exit 2；
bench 缺席/断言红=FAIL exit 1 点名（TDD 红属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-04/sc_wake_real_session_bench.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BENCH = REPO / "server" / "plugins" / "watchdog" / "bench" / "host-prompt-bench.mjs"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（bench 是 node 缝）")
        sys.exit(2)
    dsh = pathlib.Path.home() / ".sandbar" / "dsh-015"
    if not dsh.is_dir():
        print("ENV_FAIL: dsh 0.1.5 安装缺席：%s（bench 需真宿主）" % dsh)
        sys.exit(2)
    if not BENCH.is_file():
        print("FAIL: 真宿主台未落地：%s（工单 scope 6 交付面；TDD 红属预期）" % BENCH)
        sys.exit(1)
    p = subprocess.run(["node", str(BENCH)], capture_output=True, text=True, cwd=str(REPO), timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    pass_n = re.findall(r"PASS[=:]\s*(\d+)", out) or ([1] if re.search(r"^PASS\b", out, re.M) else [])
    fail_n = re.findall(r"FAIL[=:]\s*(\d+)", out) or ([1] if re.search(r"^FAIL\b", out, re.M) else [])
    if p.returncode != 0:
        print("FAIL: bench 退出码 %d（见上方输出点名）" % p.returncode)
        sys.exit(1)
    if fail_n and int(fail_n[-1]) > 0:
        print("FAIL: bench 自报 FAIL=%s（真机会话面有红）" % fail_n[-1])
        sys.exit(1)
    if not pass_n:
        print("FAIL: bench 输出无 PASS 汇总行（不可判定=红，不假绿）")
        sys.exit(1)
    print("PASS=%s" % pass_n[-1])
    sys.exit(0)


if __name__ == "__main__":
    main()
