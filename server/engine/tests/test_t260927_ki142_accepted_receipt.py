#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KI-142 反向锁：裸入口写 op 的「受理」判据必须判 ok=true（拒收不许读成受理）。

背景（260927 实案，integration 岗登记）：`client.py ticket-start` 的**拒收回执**
`rc=0` 而且把票号回显在错误文案里：

    {"ok": false, "error": "跨项目闸：调用方项目身份未声明…",
     "kind": "cross_project_refused", "identity_class": "undeclared",
     "entry_hint": "此为裸入口，请走 server/tools/ticket.py"}
    …（目标票 t26091505r1，属项目 t26091505）

于是场景里手写的 `fail.check(rc == 0 and tid in out, "ticket-start 受理")` 在
**票根本没建出来**时照样打印「受理」= 假绿；旅程随后干等 240s 报「票没到
create_plan/running」，worker 日志整段 `workflow not found`（实案
integration/t260915-05/tests/sc_detail_lane_reds.py）。本锁把这三种回执钉在
`integration/t260904-02/lib_gate.py::accepted` 上：受理面只认 ok=true。

分层归属：这是 **L1 单元层**对集成侧共用判据的锁（跨组件缝的判据本身是纯函数），
不是场景层用例；场景层的真链路复验由 integration 侧场景负责。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "integration" / "t260904-02"))

import lib_gate  # noqa: E402

#: 实案原文（照抄真实回执的关键字段；文案截断但字段形状逐字保真）
REFUSAL = json.dumps({
    "ok": False,
    "error": "跨项目闸：调用方项目身份未声明（SANDBAR_CALLER_PROJECT 未注入且无显式参数），"
             "引擎策略=拒收——经注入链/包装层声明调用方项目后再操作（目标票 t26091505r1，"
             "属项目 t26091505）",
    "kind": "cross_project_refused", "caller_project": "", "identity_src": "none",
    "identity_class": "undeclared",
    "entry_hint": "此为裸入口，请走 server/tools/ticket.py"}, ensure_ascii=False)

ACCEPT = json.dumps({
    "ok": True, "ticket_id": "t26091505r1", "workflow_id": "t26091505r1",
    "identity_src": "arg", "identity_class": "declared", "caller_project": "t26091505"},
    ensure_ascii=False)


def test_refusal_receipt_is_not_acceptance():
    """反向锁本体：旧判据（rc==0 且票号在输出里）在拒收回执上为真，本判据必须为假。"""
    assert "t26091505r1" in REFUSAL, "夹具前提：拒收回执里确实含票号（旧判据的假绿根源）"
    good, why = lib_gate.accepted(REFUSAL, "t26091505r1")
    assert good is False
    assert "ok≠true" in why and "cross_project_refused" in why, why


def test_accept_receipt_passes_and_names_ticket():
    good, why = lib_gate.accepted(ACCEPT, "t26091505r1")
    assert good is True and "ok=true" in why


def test_malformed_and_mismatched_receipts_are_named():
    """消费外部输入三态：畸形（非 JSON/空）、票号不符都不得静默按受理处理。"""
    assert lib_gate.accepted("", "t1")[0] is False
    assert lib_gate.accepted("not json at all", "t1")[0] is False
    good, why = lib_gate.accepted(ACCEPT, "t-someone-else")
    assert good is False and "票号不符" in why


def test_check_accepted_wires_fail_collector():
    """封装面：`check_accepted` 把判据结果落进 Fail 收集器（场景侧统一入口）。"""

    class _Fail:
        def __init__(self):
            self.calls = []

        def check(self, cond, msg):
            self.calls.append((bool(cond), msg))
            return bool(cond)

    f = _Fail()
    assert lib_gate.check_accepted(f, ACCEPT, "t26091505r1", "ticket-start 受理") is True
    assert lib_gate.check_accepted(f, REFUSAL, "t26091505r1", "ticket-start 受理") is False
    assert [c[0] for c in f.calls] == [True, False]
    assert all("受理" in c[1] for c in f.calls)


def test_receipt_shape_contract_holds_for_other_write_ops():
    """同一判据对别的写 op 回执同形（ticket-start 之外的裸入口写 op 亦适用）。"""
    for op_receipt in ({"ok": True, "ticket_id": "tX", "op": "sign"},
                       {"ok": False, "error": "跨项目写操作拒收：…", "kind": "cross_project_refused"}):
        good, _ = lib_gate.accepted(json.dumps(op_receipt, ensure_ascii=False), "tX")
        assert good is op_receipt["ok"]


def test_receipt_without_id_keys_falls_back_to_raw_echo():
    """有的 op 回执不带票号键（只回 ok/明细）：此时以**原文回显**为准；
    既无票号键、原文也没票号=含糊回执，不许放行。"""
    assert lib_gate.accepted(json.dumps({"ok": True, "result": {}}) + "\n(tX)", "tX")[0] is True
    good, why = lib_gate.accepted(json.dumps({"ok": True, "result": {}}), "tX")
    assert good is False and "未回显票号" in why


def test_multiline_receipt_is_accepted():
    """跨行回执同样判受理：有的 op 会缩进多行打印（带 describe 明细），
    逐行口径会整条落空——受理判据必须跨行也认（否则真受理被读成「不可解析」）。"""
    multi = ("some banner\n"
             + json.dumps({"ok": True, "ticket_id": "tX"}, ensure_ascii=False, indent=1)
             + "\ntrailing noise\n")
    good, why = lib_gate.accepted(multi, "tX")
    assert good is True, why


def _lint_module():
    """装载 integration/lint_tests.py（L9 机械闸的真源；两处判据必须同源，不抄第二份）。"""
    import importlib.util
    path = REPO / "integration" / "lint_tests.py"
    spec = importlib.util.spec_from_file_location("_lint_tests_for_l9", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_ticket_start_call_site_is_classified():
    """L9 锁：全仓每一处裸入口建票调用点都要么声明身份、要么显式豁免（KI-142）。

    这条把「机械闸的判据」也钉进 L1：以后新增场景若照抄旧写法（不声明 caller_project
    又无豁免标记），引擎套件这一条先红，不必等它在某个池里跑出「票没推进」的假象。
    """
    lint = _lint_module()
    sites = lint._ticket_start_sites()
    assert sites, "夹具前提：仓里至少有一处 ticket-start 调用点（判据本身不得空转）"
    naked = [s for s in sites if not s["declared"] and not s["allowed"]]
    assert naked == [], "未分类的建票调用点：%s" % naked
    assert lint.L9_STRICT is True, "存量清完后 L9 应为严格档（缺身份=error）"


def test_l9_gate_is_error_level_now():
    """档位锁：L9_STRICT=True —— 漏声明身份必须是 error（不是 warning）。"""
    lint = _lint_module()
    assert lint.L9_STRICT is True


if __name__ == "__main__":                              # 允许单文件直跑（诊断面）
    sys.exit(pytest.main([__file__, "-q"]))
