#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已知红基线挂账册（集成轮次瘦身提案 260923 A）卫生 + 只缩不增棘轮棒。

册子语义：存量红逐条定性后的挂账面——booked=产品面欠账挂账（有 home 认领），
isolated=环境/杂物/扫描面隔离（不挂产品欠账）。修掉即删行并下调 max_entries；
新挂账须 integration 岗位判词+home 认领，不得静默增行（棘轮：行数≤max_entries，
更新纪律=只降 max，不升）。抖动绿（串行复跑绿）不入册。
跑法：python3 integration/tests/test_t260923_known_red_baseline.py（stdlib-only）。
"""
from __future__ import annotations

import json
from pathlib import Path

BOOK = Path(__file__).resolve().parents[1] / "known-red-baseline.json"
VERDICTS = {"booked", "isolated"}


def _load():
    return json.loads(BOOK.read_text(encoding="utf-8"))


def test_schema_hygiene():
    d = _load()
    meta, entries = d["meta"], d["entries"]
    assert isinstance(meta.get("max_entries"), int) and meta["max_entries"] > 0
    assert isinstance(meta.get("policy"), str) and meta["policy"]
    seen = set()
    for e in entries:
        assert set(e.keys()) == {"name", "verdict", "home", "note"}, e
        assert e["name"] and e["name"] not in seen, "场景名必非空且不重复：%s" % e["name"]
        seen.add(e["name"])
        assert e["verdict"] in VERDICTS, e
        assert e["home"].strip(), "每条挂账必须有 home 认领：%s" % e["name"]
        assert e["note"].strip(), "每条挂账必须有判词摘要：%s" % e["name"]


def test_ratchet_shrink_only():
    d = _load()
    assert len(d["entries"]) <= d["meta"]["max_entries"], \
        "基线只缩不增：行数 %d 超 max_entries %d——修掉即删行并下调 max，新挂账须判词+home" \
        % (len(d["entries"]), d["meta"]["max_entries"])


def test_fixed_must_leave_the_book():
    """修掉即删行的负棒：今天两笔「修掉」定性不得回册（回册=账面与事实不符）。"""
    d = _load()
    names = {e["name"] for e in d["entries"]}
    assert "t260915-12-cross-project-gate" not in names      # A② 修掉（84/0 实证）
    assert "t260903-02-lock-update-integrity" not in names   # A① 修掉（12/0 实证）
    assert "t260921-06-batch-ns-isolation" not in names      # 抖动绿（串行复跑绿）不入册


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
