#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已知红基线挂账册（集成轮次瘦身提案 260923 A）卫生 + 只缩不增棘轮棒。

册子语义：存量红逐条定性后的挂账面——booked=产品面欠账挂账（有 home 认领），
isolated=环境/杂物/扫描面隔离（不挂产品欠账）。修掉即删行并下调 max_entries；
新挂账须 integration 岗位判词+home 认领，不得静默增行（棘轮：行数≤max_entries，
更新纪律=只降 max，不升）。抖动绿（串行复跑绿）不入册。

260926 追加（洞①时间证据）：每条还必须带**机械证据戳** `booked_at`（ISO8601，须带
时区）+ `booked_sha`（引入该行的 main 提交）——采纳判据要求 booked_at 早于本票开票
基点，缺戳/戳畸形条目不成立为「既有欠账」。戳的推断依据写在 meta.booked_evidence。

260929 追加（无主的红不许在册）：每条还必须带 `owner`（认领岗）+ `retire_when`
（撤账条件）——挂账的意义是「有人负责、有离场条件」；缺任一即红。宿主 260929 令：
「这些一直红，也没觉得有什么问题，那测试案例还有意义吗」＝红必须有归属与离场机制。
跑法：python3 integration/tests/test_t260923_known_red_baseline.py（stdlib-only）。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

BOOK = Path(__file__).resolve().parents[1] / "known-red-baseline.json"
VERDICTS = {"booked", "isolated"}
ENTRY_KEYS = {"name", "verdict", "home", "note", "booked_at", "booked_sha",
              "owner", "retire_when"}
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _load():
    return json.loads(BOOK.read_text(encoding="utf-8"))


def test_schema_hygiene():
    d = _load()
    meta, entries = d["meta"], d["entries"]
    assert isinstance(meta.get("max_entries"), int) and meta["max_entries"] > 0
    assert isinstance(meta.get("policy"), str) and meta["policy"]
    seen = set()
    for e in entries:
        assert set(e.keys()) == ENTRY_KEYS, e
        assert e["name"] and e["name"] not in seen, "场景名必非空且不重复：%s" % e["name"]
        seen.add(e["name"])
        assert e["verdict"] in VERDICTS, e
        assert e["home"].strip(), "每条挂账必须有 home 认领：%s" % e["name"]
        assert e["note"].strip(), "每条挂账必须有判词摘要：%s" % e["name"]
        # 260929：无主的红不许在册——owner=认领岗、retire_when=撤账条件（缺任一即红）
        assert str(e["owner"]).strip(), \
            "缺 owner（认领岗）：%s——260929 清账批次起每条必带；无主的红按退役处理" % e["name"]
        assert str(e["retire_when"]).strip(), \
            "缺 retire_when（撤账条件）：%s——挂账必须回答「什么条件下撤红」" % e["name"]


def test_evidence_stamps_are_mechanical_and_consistent():
    """260926 洞①：证据戳必须机械可判——booked_at=带时区的 ISO8601（naive/unknown/
    空串一律不成立），booked_sha=引入该行的 main 提交号；同一提交的条目时刻必一致
    （防手改单条漂移）；推断依据落 meta.booked_evidence（谁按什么补的，可复核）。"""
    d = _load()
    assert str(d["meta"].get("booked_evidence") or "").strip(), \
        "证据戳的推断依据必须落 meta.booked_evidence（可复核，不静默补戳）"
    by_sha = {}
    for e in d["entries"]:
        at, sha = e["booked_at"], e["booked_sha"]
        assert isinstance(at, str) and at.strip() and at.strip().lower() != "unknown", e["name"]
        assert isinstance(sha, str) and SHA_RE.match(sha.strip().lower()), e
        try:
            ts = _dt.datetime.fromisoformat(at.strip().replace("Z", "+00:00"))
        except ValueError:
            raise AssertionError("booked_at 不是 ISO8601：%s" % e["name"])
        assert ts.tzinfo is not None, "booked_at 必须带时区（不猜时区）：%s" % e["name"]
        by_sha.setdefault(sha.strip().lower(), set()).add(at.strip())
    assert by_sha and all(len(v) == 1 for v in by_sha.values()), \
        "同一 booked_sha 的 booked_at 必须一致（防逐条手改漂移）：%s" % by_sha


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
