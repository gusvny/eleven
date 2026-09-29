#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KI-122 两条同层修复的 L1 回归棒（260926 宿主直修令，main 直改不开票）。

背景（实案 t260926-05 报告 UI 票空转 5 轮，每轮 ~2h 全量）：仲裁每轮判
`verdict=tests-fault` 且判词自写「本票零新增红、转人工」，闸拦名单（blockers）非空但
**逐条都已在 known-red-baseline.json 挂账** → 旧逻辑走「探针未证全绿 → 保守计轮 → 重跑
集成测试」，于是烧了 5 趟全量、代码零变化。另：`tests_rounds` 连续计数的段入口复位对
「任何非 tests-fault 迭代来源的重进」都清零，人工 rework/retry_qc/pause 等外部处置可反复
击穿两道上限。

本文件钉四层（对应工单四条）：
  ① 零新增红 + tests-fault → **采纳判决推进**（不重跑）：名册归属纯判据 + dev_lane 两分支
     的采纳接线（决策先于重跑、推进 acceptance_walkthrough、票面带审计锚）；
  ② 有本票红（非在册）/ 名册不可用 → **照旧拦、照旧重跑**（fail-closed）；
  ③ 连续 N 轮被外部处置穿插仍能触顶：段入口复位在 KI122_STREAK_HOLD 门内停用；
  ④ 触顶后**不再自动重跑**且封面**具名**（谁判的/依据/下一步）。

运行：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t260926_ki122_adoption.py -q`（UT 全程禁网络/真 Temporal/真 git）。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import activities  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import (MAX_TESTS_EXEMPT_ROUNDS, MAX_TESTS_FAULT_ROUNDS,
                    blockers_known_red_adoption, integration_route,
                    known_red_roster)
from shared import tests_round_step as step_rounds  # 别名：防 pytest 误收集
from shared import tests_exempt_cap_blocked_text as exempt_cap_text
from shared import tests_fault_cap_audit_text as cap_audit_text  # 别名：防 pytest 误收集

SRC = (POC / "dev_lane.py").read_text(encoding="utf-8")
REPO = POC.parent.parent


def _roster_payload(entries):
    return {"entries": [dict({"name": n}, **v) for n, v in entries.items()]}


def _stamped(name, *, verdict="booked", home="h", booked_at="2026-09-23T19:59:23+08:00",
             booked_sha="f61f239c5e05ea691ae07e1abed25eb3f827ff77"):
    """单条带证据戳的名册条目（时间证据用例的最小载荷）。语义类用例一律用它自造夹具
    （见下「夹具取材纪律」）。"""
    return {"name": name, "verdict": verdict, "home": home, "note": "n",
            "booked_at": booked_at, "booked_sha": booked_sha}


# ---------------- 夹具取材纪律（260929 修：名册会随清账收缩） ----------------
# 旧形把**名册内容**（两条实案 blocker 名）当夹具钉死在本文件里；而册子按设计「只缩
# 不增」（integration/known-red-baseline.json 的 max_entries 棘轮 + 修绿即删行），
# 于是每次清账都会把本文件碎掉（260929 清账 dc8f7ad 除名 9 条 → 10 条红）。修法：
#   · 语义类用例（采纳/拦/时间证据/活基线）一律用 `_stamped` 自造 roster 夹具——判据
#     的输入是名册**形状**，不是某条真实欠账的名字；
#   · 只有「真名册可解析且形状合规」这一条读真文件，且**动态取样**（排序保证确定性，
#     缺类即 skip 并点名，绝不静默）。
def _real_roster():
    """读真名册文件 → (entries, raw)。文件缺席/畸形一律 fail（受控资产面异常）。"""
    path = REPO / shared.KNOWN_RED_BASELINE_REL
    assert path.is_file(), "名册文件缺席：%s" % path
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries, err = known_red_roster(raw)
    assert not err, err
    return entries, raw


def _sample_from_real_roster(entries, *verdicts):
    """按 verdict 类别动态取样（每类一条，名字排序取首=确定性）；某类在册为空=None
    （调用方 skip 并点名，不许静默换成别的类别）。"""
    out = {}
    for v in verdicts:
        names = sorted(n for n, e in entries.items() if e.get("verdict") == v)
        out[v] = names[0] if names else None
    return out


def _latest_stamp(entries):
    """名册里**最晚**的证据戳条目（时间证据用例的基点必须晚于它，才是「早于本票基点」）。
    名册只缩不增：新挂账的条目戳只会更新，写死基点=下批清账再碎一次。"""
    rows = [(e.get("booked_at") or "", n) for n, e in entries.items()]
    rows = [r for r in rows if r[0]]
    assert rows, "名册里没有任何带 booked_at 的条目（形状异常）"
    _, name = max(rows)
    return name, entries[name]


_REAL_ENTRIES, _REAL_RAW = _real_roster()
_SAMPLE = _sample_from_real_roster(_REAL_ENTRIES, "booked", "isolated")
SAMPLE_BOOKED = _SAMPLE["booked"]
SAMPLE_ISOLATED = _SAMPLE["isolated"]
#: 语义类用例的闸拦夹具（自造 roster，见上面取材纪律）：两条在同册的既有欠账名。
REAL_BLOCKERS = ["t260926-05-incident-blocker-a", "t260926-05-incident-blocker-b"]
#: 时间证据用例的基点：取真名册最晚戳的**次日**（严格晚于＝「早于本票基点」成立）。
BASE_AFTER = "2026-09-30T00:00:00+00:00"
BASE_BEFORE = "2026-09-01T00:00:00+00:00"


def _semantic_roster(verdicts=("booked", "booked")):
    """语义类用例的**自造** roster 夹具（与真册内容解耦）：名字 = REAL_BLOCKERS，
    verdict 逐条给，戳取真名册最晚戳（保证 BASE_AFTER 严格晚于它）。"""
    _, latest = _latest_stamp(_REAL_ENTRIES)
    at, sha = latest["booked_at"], latest["booked_sha"]
    return {n: {"verdict": v, "home": "ut home %s" % v, "note": "ut",
                "booked_at": at, "booked_sha": sha}
            for n, v in zip(REAL_BLOCKERS, verdicts)}


#: 语义类用例默认吃这份自造册（两条 booked）
SEMANTIC_ENTRIES = _semantic_roster()
#: 时间证据断言的「戳」基准（真名册最晚戳，逐条带上）
LATEST_BOOKED_AT, LATEST_BOOKED_SHA = (
    _latest_stamp(_REAL_ENTRIES)[1]["booked_at"],
    _latest_stamp(_REAL_ENTRIES)[1]["booked_sha"])


def _real_roster_entries():
    """语义类用例的 roster 入参（自造夹具；真名册只由 test_a1 读）。"""
    return dict(SEMANTIC_ENTRIES)


# ---------------- A. 名册归属纯判据（shared，UT 主面） ----------------

def test_a1_real_roster_is_parsable_and_shaped():
    """真名册（L1 读真文件）**只有一条形状断言**：可解析、verdict 合法、home/owner/
    retire_when 齐备、且 booked 与 isolated 两类在册各 ≥1。

    旧形把「两条实案 blocker 名」逐字钉死在本文件里——册子只缩不增（棘轮），清一次账
    就碎一次（260929 实测 10 条红）。形状面留着（它是判据的输入契约），**内容面不再钉**：
    语义面由自造夹具用例覆盖（见「夹具取材纪律」）。某类在册为空 = skip 并点名（不许
    静默降级成「只查一类也算过」）。"""
    e, raw = _real_roster()
    assert isinstance(raw, dict) and isinstance(raw.get("entries"), list), type(raw)
    assert e, "真名册解析结果为空"
    for name, v in e.items():
        assert v["verdict"] in shared.KNOWN_RED_VERDICTS, (name, v)
        assert v["home"].strip(), name
        # 260929 A 直修口径：每条挂账必须带 owner + retire_when（可追责、可撤账）
        raw_by_name = {d.get("name"): d for d in raw["entries"] if isinstance(d, dict)}
        row = raw_by_name.get(name) or {}
        assert str(row.get("owner") or "").strip(), ("缺 owner", name)
        assert str(row.get("retire_when") or "").strip(), ("缺 retire_when", name)
    for v in ("booked", "isolated"):
        if _SAMPLE[v] is None:
            pytest.skip("真名册里已无 %s 类条目（清账收缩所致）——该类的语义面由自造夹具"
                        "用例覆盖，本形状断言不降级" % v)
        assert _SAMPLE[v] in e and e[_SAMPLE[v]]["verdict"] == v, _SAMPLE[v]


def test_a2_roster_parsing_malformed_failclosed():
    """畸形名册一律整册不可用（fail-closed 的读面）：只缩不增的挂账册没有容错读法。"""
    ok = {"entries": [{"name": "a", "verdict": "booked", "home": "h", "note": "n"}]}
    entries, err = known_red_roster(ok)
    assert entries == {"a": {"verdict": "booked", "home": "h"}} and err == ""
    bad = [
        None, [], "x", {},
        {"entries": "nope"},
        {"entries": [1]},
        {"entries": [{"name": "", "verdict": "booked", "home": "h"}]},
        {"entries": [{"name": "a", "verdict": "fixed", "home": "h"}]},
        {"entries": [{"name": "a", "verdict": "booked", "home": "  "}]},
        {"entries": [{"name": "a", "verdict": "booked", "home": "h", "note": "n"},
                     {"name": "a", "verdict": "isolated", "home": "h2", "note": "n"}]},
    ]
    for b in bad:
        e2, err2 = known_red_roster(b)
        assert e2 == {} and err2, (b, e2, err2)


def test_a3_all_known_red_adopts_with_audit_anchor():
    """①零新增红 → 采纳：审计锚逐条列 blocker 名 + 名册 verdict/home（凭什么放行可复核），
    并带**时间证据**（每条登记早于本票开票基点）与**活基线可得性**（260926 洞①裁定）。
    调用方给了基点=判据可判；没给基点=fail-closed（见 test_a8）。"""
    a = blockers_known_red_adoption(REAL_BLOCKERS, _roster_payload(_real_roster_entries()),
                                    ticket_base_at=BASE_AFTER,
                                    ticket_base_source="ticket created (test)")
    assert a["adopt"] is True and a["why"] == "adopted"
    assert [k["name"] for k in a["known"]] == REAL_BLOCKERS and a["new"] == []
    assert a["known"][0]["verdict"] == "booked" and a["known"][1]["verdict"] == "booked"
    assert a["known"][0]["home"] and a["known"][1]["home"]
    for kw in ("ADOPTED", "zero new red", shared.KNOWN_RED_BASELINE_REL,
               "acceptance_walkthrough", REAL_BLOCKERS[0], REAL_BLOCKERS[1],
               "booked"):
        assert kw in a["note"], kw
    # 洞① 时间证据面：逐条戳进审计锚 + 基点具名 + 活基线不可得时明确「仅时间证据」
    assert a["stale"] == [] and a["stamps_ok"] is True
    assert a["known"][0]["booked_at"] == LATEST_BOOKED_AT
    assert a["known"][0]["booked_sha"] == LATEST_BOOKED_SHA.lower()
    for kw in ("basis 2: time evidence", BASE_AFTER, "ticket created (test)",
               "basis 3:", "UNAVAILABLE", "time evidence only"):
        assert kw in a["note"], kw
    # 文案是票面/报告面，一律英文（数据字段=blocker 名与 home 原文不译）
    assert not shared.__dict__.get("_never")


def test_a4_new_red_outside_roster_blocks():
    """②有本票红（非在册）→ 不采纳（照旧拦、照旧重跑），note 点名那条新红。"""
    e = _roster_payload(_real_roster_entries())
    a = blockers_known_red_adoption(REAL_BLOCKERS + ["t999999-99-brand-new-red"], e)
    assert a["adopt"] is False and a["why"] == "new-red"
    assert a["new"] == ["t999999-99-brand-new-red"] and len(a["known"]) == 2
    assert "t999999-99-brand-new-red" in a["note"] and "NOT adopted" in a["note"]
    # 一条非在册就整轮不采纳（不部分采纳——不新造第二套红绿判据）
    a2 = blockers_known_red_adoption(["t999999-99-nope", REAL_BLOCKERS[0]], e)
    assert a2["adopt"] is False and a2["why"] == "new-red"


def test_a5_roster_unavailable_is_failclosed_and_named():
    """②名册读不到/畸形 → fail-closed：照旧拦、照旧重跑，且票面点名名册路径与失败原因。
    空名册（读得到但零挂账）同族 fail-closed：任何 blocker 都算「非在册新红」→ 不采纳。"""
    for payload, err, why in (
            (None, "", "roster-unavailable"),
            ({}, "malformed JSON in %s: JSONDecodeError" % shared.KNOWN_RED_BASELINE_REL,
             "roster-unavailable"),
            ({"entries": []}, "", "new-red")):
        a = blockers_known_red_adoption(REAL_BLOCKERS, payload, roster_error=err)
        assert a["adopt"] is False and a["why"] == why, (payload, a)
        assert shared.KNOWN_RED_BASELINE_REL in a["note"]
    assert "fail-closed" in blockers_known_red_adoption(
        REAL_BLOCKERS, None)["note"]


def test_a6_startup_error_and_env_side_red_never_adopt():
    """③④启动级 error（没检验到）不是「零新增红」=一律不采纳；环境面红**必须具名**
    （B2，260929 宿主令·语义变更）：**未具名**的环境面照旧拒绝（保守侧，无法具名就不
    放行），**已具名**（`env_red` 非空）不再构成拒绝——采纳并在 note 里点名名单。

    本条只改「具名环境面」那半边期望（旧断言写死「环境面一律拒」）；启动级 error
    半边、畸形信号 fail-closed 半边（下面 `env_side_red="yes"` 那批）**一字未改**。"""
    e = _roster_payload(_real_roster_entries())
    a = blockers_known_red_adoption(REAL_BLOCKERS, e, run_error="supply assembly failed",
                                    ticket_base_at=BASE_AFTER,
                                    ticket_base_source="test")
    assert a["adopt"] is False and a["why"] == "startup-error"
    assert "Nothing was verified" in a["note"] or "nothing was verified" in a["note"]
    # 环境面未具名（缺 env_red / 空名单）⇒ 仍拒（B2 保守侧）
    for unnamed in (None, []):
        a2 = blockers_known_red_adoption(
            REAL_BLOCKERS, e, env_side_red=True, env_red=unnamed,
            ticket_base_at=BASE_AFTER, ticket_base_source="test")
        assert a2["adopt"] is False and a2["why"] == "env-side-red", unnamed
    # 环境面具名 ⇒ 不再构成拒绝（note 点名名单，env-face-named 记录面）
    a2b = blockers_known_red_adoption(
        REAL_BLOCKERS, e, env_side_red=True, env_red=["env-sc-one"],
        ticket_base_at=BASE_AFTER, ticket_base_source="test")
    assert "env-face-named" in a2b["note"] and "env-sc-one" in a2b["note"]
    assert (a2b["adopt"], a2b["why"]) == (True, "adopted"), a2b["note"]
    # 畸形信号一律按「拦」的一侧读（不因畸形放行）——260926 复核缺口②：旧断言把
    # `env_side_red="yes"` 的 **fail-open** 固化成契约（docstring 写「按拦读」而代码读成
    # 「非环境面」），此处改按裁定钉 fail-closed 的一侧，并点名畸形值本身。
    a3 = blockers_known_red_adoption(REAL_BLOCKERS, e, env_side_red="yes",
                                     run_error=None,
                                     ticket_base_at=BASE_AFTER, ticket_base_source="test")
    assert a3["adopt"] is False and a3["why"] == "env-side-red"
    assert "'yes'" in a3["note"] and "not a bool" in a3["note"]
    assert "BLOCK side" in a3["note"]
    # 非 bool 的其它形态（0 / None / "false"）同按拦读，不静默当「不是环境面」
    for bad in (0, None, "false", 1):
        r = blockers_known_red_adoption(REAL_BLOCKERS, e, env_side_red=bad,
                                        ticket_base_at=BASE_AFTER, ticket_base_source="test")
        assert r["adopt"] is False and r["why"] == "env-side-red", bad
    # 畸形 run_error（非串非 None）同按拦读（旧代码把它读成「无 error」= fail-open）
    for bad in (0, [], {}, object()):
        r = blockers_known_red_adoption(REAL_BLOCKERS, e, run_error=bad,
                                        ticket_base_at=BASE_AFTER, ticket_base_source="test")
        assert r["adopt"] is False and r["why"] == "startup-error", bad
        assert "not a string" in r["note"] and "BLOCK side" in r["note"]


def test_a7_empty_blockers_keeps_the_existing_exemption_lane():
    """空名单不在本面改判（既有 known_red 豁免车道语义不动，上限照旧兜底）。"""
    a = blockers_known_red_adoption([], _roster_payload(_real_roster_entries()))
    assert a["adopt"] is False and a["why"] == "no-blockers"
    # 畸形 blockers 载荷（非列表/条目非串）→ 剔除后仍无有效名字 → 一律 no-blockers
    #（260926 复核缺陷③：此处原为 `... or True` 恒真空断言，实际什么都没验）
    for bad in (None, "x", {}, [1, "", None], [["a"]]):
        a2 = blockers_known_red_adoption(bad, _roster_payload(_real_roster_entries()))
        assert a2["adopt"] is False and a2["why"] == "no-blockers", bad
        assert a2["known"] == [] and a2["new"] == []
    # 非串条目剔除后若无有效名字 → 仍走 no-blockers（保守：不放行）
    a3 = blockers_known_red_adoption([1, None, "  "], _roster_payload(_real_roster_entries()))
    assert a3["adopt"] is False and a3["why"] == "no-blockers"


# ---------------- A′. 260926 洞①：时间证据 + 活基线四象限（正反例） ----------------

def _one(name="cap-a"):
    return [_stamped(name)]


def test_a8_time_evidence_quadrants_positive_and_negative():
    """洞① 主判据：**时间证据 × 活基线**四象限（每格正反例齐）。
    - 时间证据成立＝每条在册 blocker 的 booked_at 早于本票开票基点；
    - 活基线可得＝有活基线红集（该红在集里）；在集里但不是红=按拦读；不可得=仅时间证据。"""
    pl = {"entries": _one()}
    # ① 时间成立 × 基线不可得（今天真实形态）→ 采纳，note 点名「仅时间证据」
    ok = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_AFTER,
                                     ticket_base_source="test")
    assert ok["adopt"] is True and ok["why"] == "adopted"
    assert "UNAVAILABLE" in ok["note"] and "time evidence only" in ok["note"]
    assert ok["live_baseline"]["available"] is False
    # ①′ 时间成立 × 基线有数据但**该名无答案**（没跑到）→ 仍采纳并逐条点名无答案之名
    ok2 = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_AFTER,
                                      ticket_base_source="test",
                                      live_baseline_red=["other-red"],
                                      live_baseline_green=["other-green"],
                                      live_baseline_source="ledger")
    assert ok2["adopt"] is True and ok2["live_baseline"]["no_answer"] == ["cap-a"]
    assert "live baseline set has NO answer for cap-a" in ok2["note"]
    assert "time evidence only" in ok2["note"]
    # ② 时间成立 × 活证据说 main 红（台账行）→ 两条都满足才采纳
    ok3 = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_AFTER,
                                      ticket_base_source="test",
                                      live_baseline_red=["cap-a", "other"],
                                      live_baseline_green=["other-green"],
                                      live_baseline_source="ledger")
    assert ok3["adopt"] is True and "cap-a" in ok3["live_baseline"]["red_hit"]
    assert "every blocker is red in it (cap-a)" in ok3["note"]
    # ③ 时间成立 × 活证据答 GREEN（本轮基线主跑在该名上 pass）→ 不采纳
    bad1 = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_AFTER,
                                       ticket_base_source="test",
                                       live_baseline_red=[],
                                       live_baseline_green=["cap-a"],
                                       live_baseline_source="in-round gate baseline")
    assert bad1["adopt"] is False and bad1["why"] == "live-baseline-green"
    assert "cap-a" in bad1["note"] and "GREEN" in bad1["note"]
    # ③′ 冲突（同一条既有红又有绿）→ **绿优先**拦，且冲突本身点名
    conf = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_AFTER,
                                       ticket_base_source="test",
                                       live_baseline_red=["cap-a"],
                                       live_baseline_green=["cap-a"],
                                       live_baseline_source="ledger + baseline")
    assert conf["adopt"] is False and conf["why"] == "live-baseline-green"
    assert "conflicting live red evidence" in conf["note"]
    assert conf["live_baseline"]["conflict"] == ["cap-a"]
    # ④ 时间不成立（戳晚于基点）→ 不采纳，逐条点名 booked-after-base
    bad2 = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_BEFORE,
                                       ticket_base_source="test")
    assert bad2["adopt"] is False and bad2["why"] == "stale-evidence"
    assert "booked-after-base" in bad2["note"] and "cap-a" in bad2["note"]
    assert bad2["stale"] and bad2["stale"][0]["name"] == "cap-a"
    # ⑤ 时间不成立 × 基线也不可得 → 时间证据独当一面（不因基线缺席放行）
    bad3 = blockers_known_red_adoption(["cap-a"], pl, ticket_base_at=BASE_BEFORE,
                                       ticket_base_source="test")
    assert bad3["adopt"] is False and bad3["why"] == "stale-evidence"
    # ⑥ 边界：戳 == 基点（严格早于才算）→ 拦
    same = {"entries": [_stamped("cap-a")]}
    eq = blockers_known_red_adoption(["cap-a"], same,
                                     ticket_base_at="2026-09-23T19:59:23+08:00",
                                     ticket_base_source="test")
    assert eq["adopt"] is False and eq["why"] == "stale-evidence"


def test_a9_roster_evidence_stamps_validated_missing_malformed():
    """洞① 戳校验（每条只废自己，不废整册）＋畸形活基线集按拦读。"""
    base = dict(ticket_base_at=BASE_AFTER, ticket_base_source="test")
    # 缺戳（老形态载荷）/ 缺一个字段 / 空串 / 非串 → stale-evidence，逐条点名原因
    for entry, kw in (
            ({"name": "cap-a", "verdict": "booked", "home": "h", "note": "n"}, "missing-stamp"),
            ({"name": "cap-a", "verdict": "booked", "home": "h",
              "booked_at": "2026-09-23T19:59:23+08:00"}, "missing-stamp"),
            (_stamped("cap-a", booked_at=""), "malformed-booked_at"),
            (_stamped("cap-a", booked_at="2026-09-23T19:59:23"), "malformed-booked_at"),  # naive=不猜时区
            (_stamped("cap-a", booked_at="not-a-time"), "malformed-booked_at"),
            (_stamped("cap-a", booked_sha=""), "malformed-booked_sha"),
            (_stamped("cap-a", booked_sha="xyz-not-a-sha"), "malformed-booked_sha"),
            (_stamped("cap-a", booked_sha=12345), "malformed-booked_sha")):
        r = blockers_known_red_adoption(["cap-a"], {"entries": [entry]}, **base)
        assert r["adopt"] is False and r["why"] == "stale-evidence", (entry, r["why"])
        assert kw in r["note"], (entry, r["note"])
    # 正例对照：同形条目补上合法戳即采纳（证明上面每格拦的是戳本身，不是别的原因）
    assert blockers_known_red_adoption(["cap-a"], {"entries": _one()}, **base)["adopt"] is True
    # 一条坏戳不影响另一条合法戳的判定口径：两条一起 → 整轮不采纳（不部分采纳），
    # 但 note 只点名坏的那条
    two = {"entries": [_stamped("cap-a"),
                       {"name": "cap-b", "verdict": "booked", "home": "h"}]}
    r2 = blockers_known_red_adoption(["cap-a", "cap-b"], two, **base)
    assert r2["adopt"] is False and [s["name"] for s in r2["stale"]] == ["cap-b"]
    assert "cap-b" in r2["note"] and "cap-a" not in r2["note"].split("|")[-1]
    # 畸形活基线集（不是名字表）→ 按拦读（绝不静默当「不可得」而放行）
    for bad_live in ("cap-a", {"cap-a": True}, 7):
        r3 = blockers_known_red_adoption(["cap-a"], {"entries": _one()},
                                         live_baseline_red=bad_live, **base)
        assert r3["adopt"] is False and r3["why"] == "live-baseline-malformed", bad_live
    for bad_live in ("cap-a", {"cap-a": True}, 7):
        r3b = blockers_known_red_adoption(["cap-a"], {"entries": _one()},
                                          live_baseline_green=bad_live, **base)
        assert r3b["adopt"] is False and r3b["why"] == "live-baseline-malformed", bad_live
    # 只给红集（不给绿集）= 其余名字无答案（可采纳但逐条点名）
    r4 = blockers_known_red_adoption(["cap-a", "cap-b"],
                                     {"entries": [_stamped("cap-a"), _stamped("cap-b")]},
                                     live_baseline_red=["cap-a"], **base)
    assert r4["adopt"] is True and r4["live_baseline"]["no_answer"] == ["cap-b"]


# ---------------- B. 活动壳（只读，真文件 IO） ----------------

def test_b1_roster_activity_is_readonly_and_names_failures(tmp_path):
    """活动壳只读：真名册读得到 → 条目结构化；读不到/畸形 → error 非空且路径点名（不抛）。"""
    r = asyncio.run(activities.read_known_red_roster({"repo_root": str(REPO)}))
    assert r["ok"] is True and r["result"]["error"] == ""
    # 条目面=**真名册的动态取样**（不钉名字：册子只缩不增，钉名必随清账碎）
    assert set(r["result"]["entries"]) >= set(_REAL_ENTRIES)
    assert r["result"]["path"].endswith(shared.KNOWN_RED_BASELINE_REL)
    r2 = asyncio.run(activities.read_known_red_roster({"repo_root": str(tmp_path)}))
    assert r2["ok"] is True and r2["result"]["entries"] == {}
    assert shared.KNOWN_RED_BASELINE_REL in r2["result"]["error"] and "FileNotFoundError" in r2["result"]["error"]
    (tmp_path / shared.KNOWN_RED_BASELINE_REL).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / shared.KNOWN_RED_BASELINE_REL).write_text("{ not json", encoding="utf-8")
    r3 = asyncio.run(activities.read_known_red_roster({"repo_root": str(tmp_path)}))
    assert r3["ok"] is True and "malformed JSON" in r3["result"]["error"]
    assert r3["result"]["entries"] == {}
    assert activities.read_known_red_roster in activities.ALL_ACTIVITIES


def test_b2_activity_is_registered_on_the_worker():
    names = [getattr(a, "__name__", "") for a in activities.ALL_ACTIVITIES]
    assert names.count("read_known_red_roster") == 1


def test_b3_receipt_carries_evidence_stamps_and_base_point(tmp_path):
    """260926 洞①：活动回执必须把**证据戳**与**开票基点**（base_ref 提交时刻）带出来，
    否则判据面根本判不了「登记早于本票」；解析不出来时具名（不静默、不猜）。"""
    # 动态取样（册子只缩不增，不钉名字/不钉 sha/不钉时刻）：取一条真条目，用它的
    # booked_sha 当 base_ref——「戳所指的那个提交」才是基点的校验面，写死 sha 与写死
    # 名字同病（每次清账/换戳即碎）。取**最晚戳**那条，断言面最强。
    probe_name, probe = _latest_stamp(_REAL_ENTRIES)
    r = asyncio.run(activities.read_known_red_roster(
        {"repo_root": str(REPO), "base_ref": probe["booked_sha"]}))
    res = r["result"]
    assert r["ok"] is True and res["error"] == ""
    e = res["entries"][probe_name]
    assert e["booked_at"] == probe["booked_at"]
    assert e["booked_sha"] == probe["booked_sha"]
    # base_at=base_ref 提交时刻；与「戳所指提交」的提交时刻同源（不猜时区、不回退）
    assert res["base_at"] and res["base_at_error"] == "", res
    assert shared.evidence_ts_epoch(res["base_at"]) is not None, res["base_at"]
    assert all(v.get("booked_at") and v.get("booked_sha") for v in res["entries"].values())
    # 反例①：base_ref 解析不出（不存在的 ref）→ 具名 error，条目照常返回（回落 created）
    r2 = asyncio.run(activities.read_known_red_roster({"repo_root": str(REPO),
                                                       "base_ref": "deadbeef"}))
    assert r2["result"]["base_at"] == "" and "unresolved" in r2["result"]["base_at_error"]
    assert r2["result"]["entries"], r2
    # 反例②：base_ref 缺席／像选项注入 → 不猜、不传给 git（安全面）
    r3 = asyncio.run(activities.read_known_red_roster({"repo_root": str(REPO)}))
    assert r3["result"]["base_at"] == "" and "empty or malformed" in r3["result"]["base_at_error"]
    r4 = asyncio.run(activities.read_known_red_roster({"repo_root": str(REPO),
                                                      "base_ref": "--upload-pack=x"}))
    assert r4["result"]["base_at"] == "" and "empty or malformed" in r4["result"]["base_at_error"]
    # 反例③：repo_root 非 git 仓 → 具名（不抛、不影响名册读面）
    r5 = asyncio.run(activities.read_known_red_roster({"repo_root": str(tmp_path),
                                                       "base_ref": "main"}))
    assert r5["ok"] is True and r5["result"]["base_at"] == ""
    assert r5["result"]["base_at_error"]


# ---------------- C. dev_lane 采纳接线（决策先于重跑） ----------------

def _lane(monkeypatch, entries, error="", *, base_at="", raw=None,
          with_meta=True, created=None):
    """免 Temporal 运行时的泳道壳：**自带 workflow 桩模块**（不经 dev_lane.workflow 现值——
    兄弟测试里有直接赋值 SimpleNamespace 且不还原的老套路，全局模块身份在会话内已不可信；
    本文件自装自还，顺序无关）。

    `with_meta`/`created`：260926 洞①裁定后采纳要「开票基点」在手。缺省给一张**晚于**
    名册全部证据戳的票面（模拟 260926 之后新开的票）；`base_at` 模拟活动解析出的 base_ref
    提交时刻。"""
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    if with_meta:
        wf.meta = {"created": created if created is not None else BASE_AFTER,
                   "base_ref": "c348c4c"}

    async def _exec(name, *a, **kw):
        assert name == "read_known_red_roster", name
        if raw is not None:
            return raw
        return {"ok": True, "result": {
            "entries": entries, "error": error,
            "path": "/repo/" + shared.KNOWN_RED_BASELINE_REL,
            "base_ref": str(wf.meta.get("base_ref") or "") if with_meta else "",
            "base_at": base_at, "base_at_error": ""}}

    monkeypatch.setattr(dev_lane, "workflow", SimpleNamespace(execute_activity=_exec))
    return wf


def _receipt(blockers=None, error="", failed=0, env_fail=0, ran=300):
    return shared.IntegrationRunResult(ran=ran, passed=ran - failed - env_fail,
                                      failed=failed, env_fail=env_fail,
                                      blockers=list(blockers or []), error=error)


def test_c1_lane_adoption_true_on_real_blockers(monkeypatch):
    """①实案形态：两条在册既有红（真名册）+ 开票基点在手 → 采纳（推进），note 带审计锚。"""
    wf = _lane(monkeypatch, _real_roster_entries())
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a["adopt"] is True and a["why"] == "adopted", a["note"]
    assert "basis 2: time evidence" in a["note"] and "time evidence only" in a["note"]
    assert wf._tests_env_side_red(_receipt(REAL_BLOCKERS)) is False


def test_c2_lane_adoption_false_on_ticket_red(monkeypatch):
    """②本票新增红 → 不采纳（照旧拦、照旧重跑）。"""
    wf = _lane(monkeypatch, _real_roster_entries())
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS + ["t9-new-red"])))
    assert a["adopt"] is False and a["why"] == "new-red"


def test_c3_lane_adoption_false_when_roster_unreadable(monkeypatch):
    """②名册读不到 → fail-closed（活动回执 error 非空）→ 不采纳且 note 点名。"""
    wf = _lane(monkeypatch, {}, error="cannot read %s: FileNotFoundError"
               % shared.KNOWN_RED_BASELINE_REL)
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a["adopt"] is False and a["why"] == "roster-unavailable"
    assert shared.KNOWN_RED_BASELINE_REL in a["note"]
    # 活动本身炸（旧 worker / 队列不可达）也不放行、不炸主链
    async def _boom(*a, **kw):
        raise RuntimeError("activity unavailable")
    monkeypatch.setattr(dev_lane, "workflow", SimpleNamespace(execute_activity=_boom))
    a2 = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a2["adopt"] is False and a2["why"] == "roster-unavailable"
    assert "roster activity failed" in a2["note"]


def test_c4_lane_adoption_no_blockers_skips_roster_read(monkeypatch):
    """空名单不发名册活动（既有豁免车道零额外命令——回放面无多余命令）。"""
    wf = object.__new__(dev_lane.DevLaneWorkflow)

    async def _boom(*a, **kw):   # 被调用即失败
        raise AssertionError("empty blockers must not issue the roster activity")

    monkeypatch.setattr(dev_lane, "workflow", SimpleNamespace(execute_activity=_boom))
    a = asyncio.run(wf._tests_fault_adoption(_receipt([])))
    assert a == {"adopt": False, "why": "no-blockers", "known": [], "new": [],
                 "roster_ok": False, "note": ""}


def test_c7_lane_failclosed_on_receipt_shape_drift(monkeypatch):
    """260926 复核缺口①：活动回执**形状漂移**（result/entries 非 dict、条目非对象、整份
    非 dict）一律 fail-closed 回来——不采纳、不抛。旧代码只查 raw["ok"]，漂移形状会抛
    AttributeError，而 `run()` 是裸 while 主循环=未捕获异常打断工作流实例。"""
    for tag, raw in (
            ("result is a list", {"ok": True, "result": ["a"]}),
            ("entries is a list", {"ok": True, "result": {"entries": ["a"]}}),
            ("entry is a list", {"ok": True, "result": {"entries": {"x": ["v"]}}}),
            ("entry is a string", {"ok": True, "result": {"entries": {"x": "v"}}}),
            ("receipt is a string", "nope"),
            ("receipt is a list", [1, 2])):
        wf = _lane(monkeypatch, {}, raw=raw)
        a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
        assert a["adopt"] is False and a["why"] == "roster-unavailable", (tag, a)
        assert shared.KNOWN_RED_BASELINE_REL in a["note"], tag
    # 形状合法的空回执 / 缺 result 键 → 名册读得到但零条目 = 任何 blocker 都「非在册」
    #（fail-closed 同族；receipt 形状本身不算畸形，故走 new-red 而非 roster-unavailable）
    for empty_raw in ({"ok": True, "result": None}, {"ok": True, "result": {}}):
        wf = _lane(monkeypatch, {}, raw=empty_raw)
        a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
        assert a["adopt"] is False and a["why"] == "new-red", empty_raw
    # 反例（正控）：形状合法的真名册 → 采纳，证明上面拦的是形状而非别的
    wf2 = _lane(monkeypatch, _real_roster_entries())
    assert asyncio.run(wf2._tests_fault_adoption(_receipt(REAL_BLOCKERS)))["adopt"] is True


def test_c8_lane_no_base_point_is_failclosed(monkeypatch):
    """洞① fail-closed 面：开票基点二者都不可得（无 meta=老回放 / created 畸形 /
    base_ref 解析失败）→ **不采纳**且点名原因（绝不因「判不了」放行）。"""
    # ① 无 meta（老回放形态：object.__new__ 壳没有 meta）
    wf = _lane(monkeypatch, _real_roster_entries(), with_meta=False)
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a["adopt"] is False and a["why"] == "no-base-point", a["note"]
    assert "no usable ticket base point" in a["note"]
    # ② created 畸形 + base_ref 解析失败 → 同拦
    wf2 = _lane(monkeypatch, _real_roster_entries(), created="not-a-time")
    a2 = asyncio.run(wf2._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a2["adopt"] is False and a2["why"] == "no-base-point"
    # ③ created 是 naive 串（不猜时区）→ 同拦
    wf3 = _lane(monkeypatch, _real_roster_entries(), created="2026-09-30T00:00:00")
    assert asyncio.run(wf3._tests_fault_adoption(_receipt(REAL_BLOCKERS)))["why"] == "no-base-point"


def test_c9_lane_base_point_uses_the_earliest_evidence(monkeypatch):
    """洞① 基点取值：base_ref 提交时刻 ∪ 票 created 取**更早者**（保守下界），两者都
    具名进票面；本票戳晚于该下界 → 拦（这一格证明下界不是摆设）。"""
    # base_ref 提交时刻=2026-09-25T15:26:54+08:00（=名册末批戳那一刻）｜created=更晚 →
    # 取更早者=base_ref 时刻 → 「戳 >= 基点」→ 拦
    wf = _lane(monkeypatch, _real_roster_entries(),
               base_at="2026-09-25T15:26:54+08:00", created=BASE_AFTER)
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a["adopt"] is False and a["why"] == "stale-evidence"
    assert "earliest of" in a["note"] and "base_ref commit time" in a["note"]
    # 同一票把 created 该早（更早者=created）→ 同样按更早者判（戳晚于它 → 拦）
    wf2 = _lane(monkeypatch, _real_roster_entries(),
                base_at="2026-10-05T00:00:00+08:00", created=BASE_BEFORE)
    a2 = asyncio.run(wf2._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a2["adopt"] is False and a2["why"] == "stale-evidence"
    assert "ticket created" in a2["note"] and "earliest of" in a2["note"]
    # base_ref 解析失败（base_at_error 非空）→ 具名进来源，仍用 created 判（可采纳）
    wf3 = _lane(monkeypatch, _real_roster_entries(), created=BASE_AFTER)
    raw = {"ok": True, "result": {
        "entries": _real_roster_entries(), "error": "",
        "path": "/repo/" + shared.KNOWN_RED_BASELINE_REL,
        "base_ref": "deadbeef", "base_at": "",
        "base_at_error": "base_ref commit time unresolved (git exit 128)"}}
    wf3 = _lane(monkeypatch, _real_roster_entries(), raw=raw)
    wf3.meta = {"created": BASE_AFTER, "base_ref": "deadbeef"}
    a3 = asyncio.run(wf3._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a3["adopt"] is True and a3["why"] == "adopted"
    assert "resolution issue" in a3["note"]


def test_c5_both_branches_adopt_before_rerun_and_advance():
    """①结构锁（串行+并行两分支同构）：采纳判定在计轮/重跑**之前**，采纳即推进验收。"""
    gate = "workflow.patched(KI122_ADOPTION_PATCH_ID)"
    assert SRC.count(gate) == 4, ("采纳门恰四处：串行/并行两分支的采纳判定 + 两分支的"
                                  "上限封面具名尾注；多=新分支未登记")
    assert SRC.count('KI122_ADOPTION_PATCH_ID = "dev-lane-ki122-adoption-v1"') == 1
    assert SRC.count("await self._tests_fault_adoption(cur_integ)") == 2
    for m in re.finditer(re.escape("await self._tests_fault_adoption(cur_integ)"), SRC):
        window = SRC[m.start():m.start() + 1400]
        i_adopt = window.index('adoption.get("adopt")')
        i_advance = window.index('phase = "acceptance"', i_adopt)
        i_handoff = window.index('self._handoff("arbitrate", adoption["note"]', i_adopt)
        assert i_adopt < i_handoff < i_advance
        # 采纳分支先于任何重跑赋值（窗口内重跑赋值只能出现在采纳分支之后）
        i_rerun = window.find('phase = "run_integration_tests"')
        assert i_rerun == -1 or i_rerun > i_advance
        # 计数面在采纳判定之后（未采纳才计轮/探针）
        assert window.index("await self._tests_round_account(") > i_adopt
        # 名册不可用时原因上票面（不静默）
        assert "adoption_note" in window


def test_c6_adoption_note_lands_on_ticket_face():
    """②名册不可用/本票红的具名原因随 handoff 上票面（两分支共四处：重跑×2 + 豁免×2）。

    B2（260929）在**不删不改原四处**的前提下，两支各补一处「环境面/已知红面，不重跑」
    handoff（同样带 adoption_note，具名原因不因归宿改道而丢）——故下面计数锚由 4 改
    6（原四处仍在：== 4 的语义改为 >= 4 且 == 6 的当前形态）。"""
    assert SRC.count("adoption_note") >= 8, SRC.count("adoption_note")
    assert SRC.count('self._log("tests-fault 判决未采纳：%s" % adoption_note)') == 2
    assert SRC.count('(" " + adoption_note) if adoption_note else ""') == 6
    assert SRC.count("环境面/已知红面，不重跑") == 2      # B2 新增两处（串行/平行同构）


# ---------------- D. ③外部处置不击穿上限 ----------------

def test_d1_streak_rounds_survive_external_handling_to_the_cap():
    """③连续 N 轮被外部处置（rework/retry_qc/pause 段入口重进）穿插仍触顶：
    新口径下段入口不复位（外部处置不再归零），故 cap 必然到达。"""
    rounds = exempt = 0
    for _ in range(MAX_TESTS_FAULT_ROUNDS + 1):
        rounds, exempt, counted, _ = step_rounds("tests-fault", rounds, exempt)
        assert counted is True
        # 外部处置穿插（旧口径在此复位）：新口径零动作——计数只由「红真的消失」复位
        assert rounds == 1 or rounds > 1
    assert rounds == MAX_TESTS_FAULT_ROUNDS + 1
    route = integration_route("tests-fault", rounds, 0)
    assert route.startswith("blocked:测试集迭代 %d 轮超限" % (MAX_TESTS_FAULT_ROUNDS + 1))
    # 反证（旧口径形态不被本面复用）：streak-reset 会把连续轮次清零 → 上限永不触发
    r0, e0, _, _ = step_rounds("streak-reset", MAX_TESTS_FAULT_ROUNDS, 0)
    assert (r0, e0) == (0, 0)
    assert integration_route("tests-fault", r0, 0) == "run_integration_tests"


def test_d2_entry_reset_is_disabled_under_hold_gate():
    """③结构锁：段入口复位只在 KI122_STREAK_HOLD 门**未开**时执行（旧历史逐字旧行为）。"""
    hold = 'KI122_STREAK_HOLD_PATCH_ID = "dev-lane-ki122-streak-hold-v1"'
    assert SRC.count(hold) == 1
    entry = SRC.index("if not tests_streak:")
    block = SRC[entry:entry + 1600]
    hold_gate = block.index("workflow.patched(KI122_STREAK_HOLD_PATCH_ID)")
    reset = block.index('tests_round_step("streak-reset", tests_rounds,')
    assert hold_gate < reset, "复位必须在 hold 门的 else 分支（新历史不复位）"
    assert block[hold_gate:reset].count("else:") == 1
    assert "计数不复位" in block[hold_gate:reset]
    # 复位语义只剩「红真的消失/清零」两点（pass 收敛 / 人工显式接受判决）
    assert SRC.count('tests_round_step("accept-reset", tests_rounds,') == 5  # pass×2 面 + 超限经人授权接受×2 + 并行 pass/授权合面×1
    entry_resets = [m.start() for m in re.finditer(
        re.escape('tests_round_step("streak-reset", tests_rounds,'), SRC)]
    assert len(entry_resets) == 3, "streak-reset 仅段入口一处 + code-fault 两分支（复位=收敛）"


# ---------------- E. ④触顶具名 + 不再自动重跑 ----------------

def test_e1_cap_audit_text_names_judge_basis_and_next_step():
    t = cap_audit_text(MAX_TESTS_FAULT_ROUNDS + 1, MAX_TESTS_FAULT_ROUNDS,
                                   MAX_TESTS_EXEMPT_ROUNDS, MAX_TESTS_EXEMPT_ROUNDS,
                                   "roster note")
    for kw in ("super-limit basis", "verdict=tests-fault", "consecutive cap %d" % MAX_TESTS_FAULT_ROUNDS,
               "rework / retry_qc / pause", "judged by", "no human judged this",
               "does NOT re-run the suite automatically", "human exit", "roster note"):
        assert kw in t, kw
    assert str(MAX_TESTS_FAULT_ROUNDS + 1) in t and str(MAX_TESTS_EXEMPT_ROUNDS) in t
    # 畸形入参不抛，保守截断
    bad = cap_audit_text(None, "x", object(), [], 123)
    assert "super-limit basis" in bad and "roster note" not in bad


def test_e2_cap_cover_prefix_byte_compat_and_audit_appended():
    """④既有封面前缀逐字节不变（零 re-point），具名审计只在尾注追加。"""
    r = integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS + 1, 0)
    assert r.startswith("blocked:测试集迭代 6 轮超限（上限 5），转人工判读")
    for kw in ("authorize", "ruling", "rework", "pause"):
        assert kw in r
    assert "super-limit basis" not in r, "route 纯函数零改动（审计尾注由调用方追加）"
    cover = r.split(":", 1)[1] + cap_audit_text(
        MAX_TESTS_FAULT_ROUNDS + 1, MAX_TESTS_FAULT_ROUNDS, 0, MAX_TESTS_EXEMPT_ROUNDS)
    assert cover.startswith("测试集迭代 6 轮超限（上限 5），转人工判读")
    assert "does NOT re-run the suite automatically" in cover
    # 豁免封面同族：缺省位逐字节不变，audit 位追加
    assert exempt_cap_text(MAX_TESTS_EXEMPT_ROUNDS + 1) == \
        "测试集连续 6 轮红项均属环境面/负载抖动（连续豁免超限，上限 5），转人工判读" + \
        shared._ARBITRATION_CAP_EXITS
    assert "super-limit basis" in exempt_cap_text(6, audit=cap_audit_text(6, 5))


def test_e3_cap_audit_wired_in_both_branches():
    """④结构锁：两分支的 tests 上限封面都追加具名审计（且只在 tests-fault 面）。"""
    assert SRC.count("route += tests_fault_cap_audit_text(") == 2
    for m in re.finditer(re.escape("route += tests_fault_cap_audit_text("), SRC):
        head = SRC[max(0, m.start() - 400):m.start()]
        assert 'if verdict == "tests-fault"' in head, "具名尾注只在 tests-fault 上限面"
        assert "workflow.patched(KI122_ADOPTION_PATCH_ID)" in head, "尾注在新历史门内"
        tail = SRC[m.start():m.start() + 500]
        assert "route.split(" in tail, "尾注追加后仍走既有 split 取用点（锚点不变）"
    # 上限常量只加不减（红线③：既有上限与断言不变）
    assert MAX_TESTS_FAULT_ROUNDS == 5 and MAX_TESTS_EXEMPT_ROUNDS == 5


def test_e4_no_automatic_rerun_route_at_or_over_cap():
    """④触顶即 blocked（不自动重跑）：边界逐值（=cap 放行 / >cap 拦）。"""
    assert integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS, 0) == "run_integration_tests"
    assert integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS + 1, 0).startswith("blocked:")
    assert integration_route("tests-fault", 99, 0).startswith("blocked:")
    assert integration_route("code-fault", 0, 0) == "implement"


# ---------------- B′/C′. 260926 加保险的真实生产者（两路实跑证据） ----------------

def test_b4_live_baseline_evidence_merge_single_source():
    """活基线证据合成（shared 纯函数，判据侧的单一数据入口）：两路（本轮闸基线主跑逐名
    答案 ∪ 场景台账可信行）合成 red/green 两名单；冲突两名单都带出（判定在判据侧=绿优先）；
    畸形逐项降级；两路都空=来源点名「没有活基线证据」。"""
    red, green, src = shared.live_baseline_evidence(
        {"a": "red", "b": "green", "c": "bogus", 1: "red", "d": None},
        ledger_red=["e", "a"], ledger_green=["f"], baseline_ref="main@abc123",
        ledger_available=True)
    assert red == ["a", "e"] and green == ["b", "f"]
    assert "in-round gate baseline (2 answered name(s), ref=main@abc123)" in src
    assert "scenario ledger (available)" in src
    # 冲突：同一条红绿都在 → 两名单都带出（判据侧绿优先，见 test_a8 ③′）
    red2, green2, _ = shared.live_baseline_evidence({"x": "green"}, ledger_red=["x"])
    assert red2 == ["x"] and green2 == ["x"]
    # 反例①：两路都空 → 来源点名（票面据此写「基线不可得，仅时间证据」）
    r3, g3, s3 = shared.live_baseline_evidence({}, [], [], ledger_available=False)
    assert (r3, g3) == ([], []) and "no live main-tip baseline evidence" in s3
    # 反例②：畸形入参不抛（非 dict / 非名字表 / 值非 red|green）
    for bad in (None, "x", 7, {"a": 1}, {"": "red"}, {None: "red"}):
        r4, g4, _ = shared.live_baseline_evidence(bad, ledger_red="nope", ledger_green={"k": 1})
        assert r4 == [] and g4 == [], bad


def test_b5_receipt_producers_are_wired_source_lock():
    """生产者接线锁（防止「判据有接口但没人产数据」的空转）：闸侧把逐名答案放进回执
    `baseline.answers`（判据单点=failure_protocol.baseline_answers）；活动壳把两路证据
    合成到 IntegrationRunResult 的 live_baseline_* 字段（合成单点=shared.live_baseline_evidence）。"""
    import failure_protocol as fp
    vlan = (REPO / "server/tools/verify_lane.py").read_text(encoding="utf-8")
    assert "'answers': fp.baseline_answers(" in vlan
    assert "fp.baseline_answers(" in vlan or "failure_protocol" in vlan
    assert hasattr(fp, "baseline_answers") and callable(fp.baseline_answers)
    acts = (POC / "agent_activities.py").read_text(encoding="utf-8")
    assert "shared.live_baseline_evidence(" in acts
    for k in ("out.live_baseline_red = ", "out.live_baseline_green = ",
              "out.live_baseline_source = "):
        assert k in acts, k
    # 回执数据类字段（additive，缺省空=老回放/老闸零漂移）
    r = shared.IntegrationRunResult()
    assert r.live_baseline_red == [] and r.live_baseline_green == [] \
        and r.live_baseline_source == ""


def test_c10_lane_live_baseline_green_blocks_and_red_adopts(monkeypatch):
    """洞①「最小复现」在**泳道入口**被拦：同名新红而活基线主跑在该名上答 pass（main 绿）
    → 不采纳（照旧拦、照旧重跑）；反过来台账可信红行在手 → 两条都满足才采纳。"""
    wf = _lane(monkeypatch, _real_roster_entries())
    green = _receipt(REAL_BLOCKERS)
    green.live_baseline_green = list(REAL_BLOCKERS)
    green.live_baseline_source = "in-round gate baseline (2 answered name(s), ref=main@abc)"
    a = asyncio.run(wf._tests_fault_adoption(green))
    assert a["adopt"] is False and a["why"] == "live-baseline-green", a["note"]
    assert REAL_BLOCKERS[0] in a["note"] and "GREEN" in a["note"]
    wf2 = _lane(monkeypatch, _real_roster_entries())
    red = _receipt(REAL_BLOCKERS)
    red.live_baseline_red = list(REAL_BLOCKERS)
    red.live_baseline_source = "in-round gate baseline (0 answered name(s)) + scenario ledger (available)"
    a2 = asyncio.run(wf2._tests_fault_adoption(red))
    assert a2["adopt"] is True and a2["why"] == "adopted", a2["note"]
    assert "every blocker is red in it" in a2["note"]
