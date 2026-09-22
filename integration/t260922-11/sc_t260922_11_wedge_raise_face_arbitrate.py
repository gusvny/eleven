#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t260922_11_wedge_raise_face_arbitrate.py —— 仲裁面失败路径的自动隔离分型
（t260922-11 场景②，池=ro，灰盒 L3，进程内夹具+假 dsh 桩秒级零网络零 docker）。

intent（守护的用户可感知行为）：同一套「dsh 点名撕裂→自动隔离」机制在**独立活动
实现**的仲裁面上必须同样生效，且保持其**raise 型**失败分型——仲裁段被撕裂档楔死
时，用户可感知终态=infra 失败响亮（进既有有界重试链）+坏档已自动挪离+留痕在案，
而不是静默或软错吞掉。这是同机制「一处实现、多处接线不漂移」的编排面回归锁：
主面旅程见场景①，本条只守独立活动面上的分型与隔离动作。

high-level steps：E 类撕裂档夹具（会话身份=<票>-integration，即仲裁面缺省会话）+
永不成功的假 dsh 桩（撕裂文案 rc=1）→ 真实驱动仲裁活动一次 → 断言：raise 型失败
（不是软错回执——分型面，接错型即红）+文案含自动隔离注记+坏档挪离原位字节级留档+
事件记录 action=已隔离。

三态：PASS exit 0 / FAIL exit 1 / 环境缺供（zstd CLI、引擎模块装载）ENV_FAIL exit 2
点名。实现未落地/行为退化=FAIL（TDD 信号），arbitrate/merge 期必须绿。

直跑：python3 integration/t260922-11/sc_t260922_11_wedge_raise_face_arbitrate.py（cwd=仓库根）。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_wedge import (EXIT_ENV, Fail, TEAR_LINE, knob_guard,  # noqa: E402
                       load_activities, make_args, make_lane, make_stub,
                       zstd_available)

TICKET, STAGE, ROLE = "t-it-wedge-arb", "arbitrate", "integration"


def main() -> int:
    if not zstd_available():
        print("ENV_FAIL: zstd CLI 缺席（夹具构造与引擎检疫面共同依赖，环境缺供）")
        return EXIT_ENV
    aa = load_activities()

    f = Fail("t260922-11 场景② 仲裁面失败路径自动隔离分型")
    work, dsh, sdir, torn, sid = make_lane("sc-t26092211-arb-", TICKET, STAGE, ROLE)
    try:
        original = torn.read_bytes()
        rfile = work / ".sandbar" / ("stage_%s_gen0.json" % STAGE)
        stub, state = make_stub(work, success_at=99)  # 永不成功：只验失败路径
        raised = None
        with knob_guard(SANDBAR_AGENT_CMD=str(stub),
                        WEDGE_STUB_RESULT_FILE=str(rfile),
                        WEDGE_STUB_EXTRA_LINE=TEAR_LINE,
                        WEDGE_STUB_SID=sid,
                        WEDGE_STUB_STATE=str(state)):
            args = make_args(aa, work, TICKET, STAGE, ROLE)
            try:
                asyncio.run(aa.arbitrate(args))
            except RuntimeError as e:
                raised = e
        f.check(raised is not None, "仲裁面失败为 raise 型（infra 语义，非软错回执）")
        f.check(raised is not None and "已自动隔离" in str(raised),
                "失败文案追加自动隔离注记")
        f.check(not torn.exists(), "点名撕裂档挪离原位")
        dsts = list((work / ".sandbar" / "quarantine").glob("torn-%s-*" % sid))
        f.check(len(dsts) == 1 and dsts[0].read_bytes() == original,
                "隔离区恰一份留档且字节级=原档（挪不删可回溯）")
        evs = list((work / ".sandbar" / "quarantine").glob(
            "session-wedge-%s-%s-*.json" % (TICKET, STAGE)))
        ev_ok = bool(evs) and json.loads(evs[0].read_text(encoding="utf-8")).get(
            "action") == "quarantined"
        f.check(ev_ok, "事件记录在案且 action=已隔离（留痕面）")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
