#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""④ 人工记名收口（close_out）回归锁（260927 宿主实报；宿主选定选项 B）。

实报原话：「blocked 状态下 status 白名单卡住收口（A3.5）……和 №1 叠加＝一条已完成的票
根本没有任何正路能收口（我最后按允许序列 dispatched→settled 收的）」。A3.5 护栏本身
合理（防「用通用 update 把 blocked 悄悄写成非 blocked」），但它把「人工确认工作已完成、
显式收口」这条正当语义也堵死了。

处置（选项 B=语义自洽）：新增 `ticket.py op=close_out`——一条 op 同时做三件：①记名
（who/reason 必填非空，进不可变事件历史与 admin.log）；②置票面终态 closed；③终止工作流
（terminate 的 reason 带固定前缀，终态面与 admin.log 一眼可辨「人工收口」而非「清场」）。
与 cancel 的分工：cancel=清场（为什么废掉），close_out=收口（凭什么认定已完成）。

本锁钉：①纯函数前缀往返；②notice handler 的写入面与 A3.5 关系（补记 was_state/was_stage
如实留痕）；③畸形载荷零副作用；④op 面注册齐全（ticket.py enum+分发、client COMMANDS）；
⑤能力放在**共享 mixin**（dev_lane 与模板族都拿到——dev_lane 原本连 cancel_notice 都缺）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parents[3]
POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import base as base_mod  # noqa: E402
import shared  # noqa: E402


class _Shell(base_mod.TicketCrossProjectMixin):
    """免 Temporal 运行时的最小壳：只给 handler 真正用到的面。"""

    def __init__(self, meta=None):
        self.meta = dict(meta or {})
        self.refused = []
        self.timeline = []
        self.logs = []
        self.marks = []

    # ——— mixin 依赖的最小面（与两棵类树上的同名方法同签名）———
    def _now_iso(self):
        return "2026-09-27T00:00:00+00:00"

    def _now_epoch(self):
        return 1790000000.0

    def _log(self, note, status=None):
        self.logs.append(note)

    def _mark(self, stage, state, reason=""):
        self.marks.append((stage, state, reason))

    def _touch(self):
        pass


def test_terminate_reason_prefix_roundtrip():
    r = shared.close_out_terminate_reason("v000012 已上线，账目在册")
    assert r.startswith(shared.CLOSE_OUT_PREFIX)
    assert shared.is_close_out_reason(r) is True
    assert shared.is_close_out_reason("普通清场理由") is False
    assert shared.is_close_out_reason("") is False
    # 前缀必须与「清场」可辨——这是终态面/admin.log 唯一的机器可读标记
    assert "close-out" in shared.CLOSE_OUT_PREFIX


def test_notice_records_close_out_and_sets_closed_from_blocked():
    """核心面：blocked 态经本信号置 closed（A3.5 的正当旁路），并把原状态如实留痕。"""
    wf = _Shell({"status": "dispatched", "stage": "cs-publish", "stage_state": "blocked",
                 "blocked_reason": "脚本门 … 红灯 0 项", "blocked_detail": {"x": 1},
                 "project": "nusuyou"})
    wf.close_out_notice({"who": "宿主", "reason": "v000012 已上线且账目在册，人工收口",
                         "kind": "close_out"})
    m = wf.meta
    assert m["status"] == "closed"
    assert m["stage_state"] == "awaiting"
    assert m["blocked_reason"] == "" and m["blocked_detail"] is None
    rec = m["close_out"]
    assert rec["who"] == "宿主" and "人工收口" in rec["reason"]
    # 被覆盖的状态如实留痕（A3.5 的「不许掩盖」在收口语义下靠留证成立）
    assert rec["was_state"] == "blocked" and rec["was_stage"] == "cs-publish"
    assert any("named close-out (close_out)" in x for x in wf.logs)
    assert any(st == "closed" for _s, st, _r in wf.marks)
    assert wf.refused == []


def test_notice_rejects_malformed_payload_with_zero_side_effects():
    """畸形载荷=refused[] 零副作用：一不得动 status，二不得写 close_out 记录。"""
    for payload in ({}, {"who": "  "}, {"who": "宿主", "reason": "   "}, "垃圾"):
        wf = _Shell({"status": "dispatched", "stage_state": "blocked"})
        wf.close_out_notice(payload)
        assert wf.meta.get("status") != "closed"
        assert "close_out" not in wf.meta
        assert wf.refused and wf.refused[0]["want"] == "close_out_notice"


def test_capability_lives_in_the_shared_mixin():
    """两棵类树都要拿到这条能力（dev_lane + 模板族）——放在共享 mixin 的机械保证。"""
    assert hasattr(base_mod.TicketCrossProjectMixin, "close_out_notice")
    import dev_lane  # noqa: PLC0415
    assert issubclass(dev_lane.DevLaneWorkflow, base_mod.TicketCrossProjectMixin)
    assert issubclass(base_mod.TicketWorkflowBase, base_mod.TicketCrossProjectMixin)
    assert (dev_lane.DevLaneWorkflow.close_out_notice
            is base_mod.TicketCrossProjectMixin.close_out_notice)


def test_op_registered_across_the_three_entries():
    """op 面三处注册齐全（缺一处＝「宣告不支持的工具面」=说明书撒谎，KI-079 同族）。"""
    tsrc = (REPO / "server" / "tools" / "ticket.py").read_text(encoding="utf-8")
    assert "'close_out'" in tsrc                                   # schema enum
    assert "if op == 'close_out':" in tsrc and "return _close_out(args)" in tsrc
    assert "_write_op_poc('ticket-close-out'" in tsrc
    csrc = (REPO / "server" / "engine" / "client.py").read_text(encoding="utf-8")
    assert '"ticket-close-out": cmd_ticket_close_out' in csrc
    assert "close_out_terminate_reason(reason)" in csrc
    assert 'handle.signal("close_out_notice"' in csrc


if __name__ == "__main__":                                          # 允许单文件直跑
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
