#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_real_progress_signal.py — 停摆判据的真信号锁（t260929-08，灰盒 L3，隔离真宿主）。

intent（用户可感知行为=「executor 真的停摆 15 分钟会叫我，真的在推进则不叫」——
工单验收 (a)(d)）：本条是**包装场景**，被测体= developer 交付的真宿主台
server/plugins/watchdog/bench/host-session-signals-bench.mjs（隔离 temp DSH_HOME +
临时端口，绝不接触 3099；进展信号走真宿主 sessionController.list() 读 watchdog.json
声明的 executor_session，不是桩、不是猜的文件路径）。判据：
(a) 真会话静默、注入时钟推过 stall_minutes（15min 缺省）→ stall alert 落账；
    真会话推进（list().updatedAt 前进）→ 同样时长不报 stalled；
(d) 反证分支：同输入下 deps 缺省（core 默认 sessionStat advanced:null）的守望者
    实例永远 no_signal、不产 stall alert —— 新锁对修复前接线必红。bench 输出须含
    ANTIPROOF=ok 标记，缺标记=不可判定=红（不假绿）。

intent 分工：注入桩面的判定真值表归 t260928-28-watchdog-liveness-selflock（秒级、
先行）；本条只锁「真宿主会话面经真实接线进入判定」这一桩够不到的面——KI-152/KI-153
家族（桩按实现者假设造形 ⇒ 真机必红测试全绿）的正面对治，互不顶替。

三态：node 或 dsh 0.1.5 安装（~/.sandbar/dsh-015）缺席=ENV_FAIL exit 2；
bench 缺席/断言红/无 ANTIPROOF 标记=FAIL exit 1 点名（TDD 红属预期，
arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260929-08/sc_watchdog_real_progress_signal.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BENCH = REPO / "server" / "plugins" / "watchdog" / "bench" / "host-session-signals-bench.mjs"
LEG = "progress"


def main():
    if not shutil.which("node"):
        print("ENV_FAIL: node 不在 PATH（bench 是 node 缝）")
        sys.exit(2)
    dsh = pathlib.Path.home() / ".sandbar" / "dsh-015"
    if not dsh.is_dir():
        print("ENV_FAIL: dsh 0.1.5 安装缺席：%s（真宿主会话面需要）" % dsh)
        sys.exit(2)
    if not BENCH.is_file():
        print("FAIL: 真宿主信号台未落地：%s（工单 scope 1 交付面；TDD 红属预期）" % BENCH)
        sys.exit(1)
    p = subprocess.run(["node", str(BENCH), "--leg", LEG], capture_output=True, text=True,
                       cwd=str(REPO), timeout=600)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    if p.returncode == 2 or "[ENV_FAIL]" in out:
        print("FAIL: bench 自报环境缺件（ENV_FAIL 必须以 exit 2 透传，不得吞成产品红）")
        sys.exit(2)
    if p.returncode != 0:
        print("FAIL: bench 退出码 %d（真机停摆判据面有红，见上方输出点名）" % p.returncode)
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
