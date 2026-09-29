#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_real_selflock_signal.py — 自锁判据的真信号锁（t260929-08，灰盒 L3，隔离真宿主+真账本文件）。

intent（用户可感知行为=「executor 在等一个它自己发起的请求 → 立刻报『它在等自己』，
不等停摆超时」——工单验收 (b)(d) + 设计稿验收动作第三条）：本条是**包装场景**，
被测体= developer 交付的真宿主台 server/plugins/watchdog/bench/host-session-signals-bench.mjs
（--leg selflock）。证据源=**真文件**：临时 SANDBAR_PANEL_DIR 下的 requests.jsonl，
行经 executor-panel 的**真追加 API**（appendRequest，含 raised_by 归因字段）写入——
不是场景手造的假行（KI-152：桩按实现者假设造形=真机必红）。判据：
(b) 有一条 raised_by=executor_session 的 waiting 行 → 下一拍 self_lock.state=
    waiting_on_itself 且指向该请求（不推进 stall 时钟）；
- 未归因行（无 raised_by）永不匹配，且全未归因时 state=none 但 reason 点名
  「N 条 waiting 行缺归因」（诚实规则：绝不冒充「一切正常」）；
- 账本文件不可读 → state=unknown+原因（显式 unknown，绝不假 none）；
(d) 反证分支：同输入下 deps 缺省（core 默认 pendingProvider available:false）的
    实例恒 unknown、不产自锁告警 —— 新锁对修复前接线必红（ANTIPROOF=ok 标记）。

intent 分工：判定真值表（纯函数、注入桩）归 t260928-28-watchdog-liveness-selflock；
本条只锁「真账本文件 → 真接线 → 公开 status」的端到端面，互不顶替。

三态：node 或 dsh 0.1.5 安装缺席=ENV_FAIL exit 2；bench 缺席/断言红/无
ANTIPROOF 标记=FAIL exit 1 点名（TDD 红属预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-08/sc_watchdog_real_selflock_signal.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BENCH = REPO / "server" / "plugins" / "watchdog" / "bench" / "host-session-signals-bench.mjs"
LEG = "selflock"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（bench 是 node 缝）")
        sys.exit(2)
    dsh = pathlib.Path.home() / ".sandbar" / "dsh-015"
    if not dsh.is_dir():
        print("ENV_FAIL: dsh 0.1.5 安装缺席：%s（真宿主需要）" % dsh)
        sys.exit(2)
    if not BENCH.is_file():
        print("FAIL: 真宿主信号台未落地：%s（工单 scope 2 交付面；TDD 红属预期）" % BENCH)
        sys.exit(1)
    p = subprocess.run(["node", str(BENCH), "--leg", LEG], capture_output=True, text=True,
                       cwd=str(REPO), timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    if p.returncode == 2 or "[ENV_FAIL]" in out:
        print("FAIL: bench 自报环境缺件（ENV_FAIL 必须以 exit 2 透传）")
        sys.exit(2)
    if p.returncode != 0:
        print("FAIL: bench 退出码 %d（真机自锁判据面有红，见上方输出点名）" % p.returncode)
        sys.exit(1)
    # bench 的反证分支以逐项 ok 行落地（"ok   ANTIPROOF: ..."）；兼容 "ANTIPROOF=ok" 汇总形。
    if not (re.search(r"^ok\s+ANTIPROOF", out, re.M) or "ANTIPROOF=ok" in out):
        print("FAIL: bench 无 ANTIPROOF 反证分支结果行（反证分支不可判定=红，不假绿；工单验收 d）")
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
