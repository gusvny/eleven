#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_wake_harness — t260929-04 wake-delivery 集成场景的共享驱动缝（灰盒 L2/L3）。

复用纪律：夹具缝不复制——直接继承 t260928-28 的 lib_watchdog_harness.Harness
（一行 JSON 一命令的 stdin/stdout 协议、注入时钟、tmp 隔离、L8 回收全在基类）。
本库只做两件事：
  1) 声明**本票新增的 harness 协议命令**（implement 段在 server/plugins/watchdog/
     harness.mjs 里落地；场景在落地前跑=FAIL exit 1 点名，属 TDD 红预期）：
       - session_stub_set {present, prompt_result}：夹具 sessionController 桩的
         形态注入。present:false = 宿主 ctx.sessionController 缺席（headless 形态）；
         prompt_result = {accepted:true} | {accepted:false,error:"..."} | "throw"。
         桩必须记录每次 prompt 调用的 {requestId, sessionId, mode, content} 供
         delivered_wakes 读出——真实 API 形状 prompt({requestId, sessionId, mode,
         content}, signal) 的可判定锚。
       - control_seed {queues}：注入 baseline 帧（{sessionId: [queuedItem...]}）。
       - control_frame {sessionId, items}：注入增量 queue 帧（整会话替换语义）。
       - control_fail {mode:"error"}：镜像流故障注入（= mirror genuinely
         unreachable），守望者必须显式 no-signal 而非静默假设已消化。
       - delivered_wakes（既有命令，语义收紧）：回执行新增 requestId/sessionId
         字段（requestId 是本票 client-minted watchdog-<uuid> 的证明面）。
  2) queuedItem 夹具形状（对齐 dsh SessionQueuedItem 公开形状：id/placement/
     rpcId/message，灰盒锚公开契约不锚内部）。

三态：node 缺席=ENV_FAIL exit 2；harness/新协议命令未落地=FAIL exit 1 点名。
"""
from __future__ import annotations

import pathlib
import sys

_PREV = pathlib.Path(__file__).resolve().parent.parent / "t260928-28"
sys.path.insert(0, str(_PREV))
from lib_watchdog_harness import (  # noqa: E402,F401  (共享缝，不复制)
    Harness, PASS, FAIL, ok, ledger_row, noise_row, summary_and_exit,
)

WAKE_KEYS = {"at", "ticket", "dedupe_key", "mode", "accepted"}  # panel-contract.md 承诺键集，一个不改


def queued_item(item_id, rpc_id=None, placement="queued"):
    """dsh SessionQueuedItem 公开形状夹具（rpcId=prompt requestId 回显面）。"""
    d = {"id": item_id, "placement": placement,
         "message": {"id": item_id, "content": [{"type": "text", "text": "watchdog brief"}]}}
    if rpc_id is not None:
        d["rpcId"] = rpc_id
    return d


class WakeHarness(Harness):
    """t260928-28 Harness + 本票新增协议命令（薄封装，全部走既有 cmd 通道）。"""

    def session_stub_set(self, present=True, prompt_result=None):
        kw = {"present": present}
        if prompt_result is not None:
            kw["prompt_result"] = prompt_result
        return self.cmd("session_stub_set", **kw)

    def control_seed(self, queues):
        return self.cmd("control_seed", queues=queues)

    def control_frame(self, session_id, items):
        return self.cmd("control_frame", sessionId=session_id, items=items)

    def control_fail(self):
        return self.cmd("control_fail", mode="error")

    def delivered_wakes(self, project):
        """排水面：回全部投递记录并清空（harness delivered_wakes 语义）。"""
        return self.cmd("delivered_wakes", project=project).get("wakes") or []

    def pump(self, project, seconds=5):
        """推进时钟并泵到期周期，回本轮投递列表（一次性排水——回执即清，勿二次取）。"""
        self.cmd("tick", seconds=seconds)
        return self.delivered_wakes(project)

    def drain(self, project, seconds=5):
        """pump 的计数形（逐段排水，计数不跨段混淆）。"""
        return len(self.pump(project, seconds=seconds))
