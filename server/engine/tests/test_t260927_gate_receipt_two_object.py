#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260927 宿主实报回归锁：门回执是「说明行 + 回执行」的多对象 stdout 时，门必须被判对。

实案（nusuyou content-studio `content-260808`，宿主机上实报「门绿了也判 blocked，票永远
收不了口」）：该段门脚本 `cs_publish_audit.py publish` 先打一行诊断 JSON、再打真回执：

    {"note": "含 marker 子串但非记名块形态的提交（不作判据数据源）：…"}
    {"ok": true, "result": {"note": "", "green": false, "red_count": 1, …}}

老实现 `activities._parse` 是整段 `json.loads(stdout)` → `JSONDecodeError` → `{}` ⇒
`green=False, red_count=0`（ticket t260927-16 的 gate_runs 实录：green=False / red_count=0 /
exit_code=0），票面写成「脚本门 … **红灯 0 项** → blocked」——与「门真红 5 项」逐字同句，
且 retry_qc 重跑多少次都同一句（解析结果恒定）⇒ 票永远收不了口、看板永不归零。

本锁钉三件：①容错解析取到真回执（优先含 ok 键的对象）；②判定三要素逐项带出、判据不放宽
（ok ∧ result.green ∧ exit==0 才绿）；③非绿文案**精确点名**（回执不可解析 / 真红 N 项 /
要素没过），不许再用「红灯 0 项」冒充。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared import gate_failure_note, gate_receipt_parse, gate_verdict  # noqa: E402

#: 实案 stdout 逐字形态（两行两个 JSON 对象；第 2 行才是回执）
REAL_TWO_OBJECT = (
    '{"note": "含 marker 子串但非记名块形态的提交（不作判据数据源）：验收报告补记：'
    'ai-review 评定上调（交叉/只判不改有硬证据）＋转述门内 4 组建议级意见（R1–R4）"}\n'
    '{"ok": true, "result": {"note": "", "green": false, "red_count": 1, '
    '"scope": "publish-audit", "checks": [{"check": "发布账对账", "level": "red", "count": 1, '
    '"items": [{"detail": "发布账无本票条目：source=content-260808 未在版本目录在册（共 1 条）"}]}]}}\n'
)

#: 同样两行形态，但回执**是绿的**——老实现下这类「真绿」也会被读成非绿（本锁的核心回归面）
GREEN_TWO_OBJECT = (
    '{"note": "诊断行：某提交含 marker 子串但不是记名块形态"}\n'
    + json.dumps({"ok": True, "result": {"note": "", "green": True, "red_count": 0,
                                         "scope": "publish-audit",
                                         "checks": [{"check": "发布账对账", "level": "green",
                                                     "count": 0}]}}, ensure_ascii=False) + "\n")


def test_two_object_stdout_parses_to_receipt_not_note():
    """解析面：必须取到含 ok 的回执，而不是那行诊断 JSON（也不是空）。"""
    payload = gate_receipt_parse(REAL_TWO_OBJECT)
    assert payload.get("ok") is True, payload
    assert (payload.get("result") or {}).get("red_count") == 1, payload


def test_green_two_object_stdout_is_green():
    """核心回归：两行形态的**绿**回执必须判绿（老实现这里返回 {} ⇒ 判非绿 ⇒ 票永远 blocked）。"""
    v = gate_verdict(gate_receipt_parse(GREEN_TWO_OBJECT), 0)
    assert v["parsed"] is True and v["green"] is True, v
    assert v["red_count"] == 0


def test_verdict_keeps_three_element_rule():
    """判据不放宽：ok / result.green / exit==0 三者全过才算绿；任缺其一都非绿。"""
    green_payload = gate_receipt_parse(GREEN_TWO_OBJECT)
    assert gate_verdict(green_payload, 0)["green"] is True
    assert gate_verdict(green_payload, 3)["green"] is False          # 退出码非 0
    ok_false = {"ok": False, "result": {"green": True, "red_count": 0}}
    assert gate_verdict(ok_false, 0)["green"] is False               # 载荷 ok=false
    gfalse = {"ok": True, "result": {"green": False, "red_count": 0}}
    assert gate_verdict(gfalse, 0)["green"] is False                 # result.green=false


def test_unparsable_receipt_is_named_not_silently_red_zero():
    """畸形/空 stdout：parsed=False，且文案必须说「回执不可解析」，不许写「红灯 0 项」。"""
    for bad in ("", "not json at all\n", "traceback\n..."):
        v = gate_verdict(gate_receipt_parse(bad), 0)
        assert v["parsed"] is False and v["red_count"] == 0
        note = gate_failure_note("发布账对账", v, 0, raw_head=bad[:80])
        assert "回执不可解析" in note and "红灯 0 项" not in note, note


def test_failure_note_distinguishes_real_red_from_parse_failure():
    """三态各写各的：真红点名项数、解析失败点名解析、要素没过点名三个值。"""
    real_red = gate_verdict(gate_receipt_parse(REAL_TWO_OBJECT), 0)
    note_red = gate_failure_note("发布账对账", real_red, 0)
    assert "红灯 1 项" in note_red, note_red
    note_parse = gate_failure_note("发布账对账", gate_verdict({}, 0), 0)
    assert "回执不可解析" in note_parse
    note_elem = gate_failure_note(
        "发布账对账", gate_verdict({"ok": False, "result": {"green": True}}, 0), 0)
    assert "ok=False" in note_elem and "result.green=True" in note_elem, note_elem
    # 三种文案必须互不相同（「读日志的人分不清」正是实案痛点）
    assert len({note_red, note_parse, note_elem}) == 3


def test_old_parser_behaviour_is_the_regression_we_are_locking():
    """反证（可执行证据）：老实现口径=整段 json.loads，在本实案 stdout 上**必然**拿不到东西。

    这条把「老实现为什么红」写成可复核的断言，而不是只留一句注释：整段解析抛
    JSONDecodeError → `{}` → 门判非绿且 red_count=0 ⇒ 票面「红灯 0 项 → blocked」。
    """
    import json
    try:
        old_payload = json.loads(REAL_TWO_OBJECT)
    except json.JSONDecodeError:
        old_payload = {}
    assert old_payload == {}, "夹具前提：整段解析在这份 stdout 上必须失败（老口径的死因）"
    v = gate_verdict(old_payload, 0)
    assert v["green"] is False and v["red_count"] == 0 and v["parsed"] is False


def test_whole_single_object_stdout_still_works():
    """零回归面：传统「整段单对象」回执照旧。"""
    one = json.dumps({"ok": True, "result": {"green": True, "red_count": 0}})
    assert gate_receipt_parse(one).get("ok") is True
    assert gate_verdict(gate_receipt_parse(one), 0)["green"] is True


if __name__ == "__main__":                                  # 允许单文件直跑（诊断面）
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
