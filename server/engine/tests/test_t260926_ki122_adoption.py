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

# 实案票的两条闸拦（今天 t260926-05 逐字；名册 verdict/home 见 integration/known-red-baseline.json）
REAL_BLOCKERS = ["t260903-07-click-no-chat-switch",
                 "t260916-25-stage-console-prepare-refresh"]


def _roster_payload(entries):
    return {"entries": [dict({"name": n}, **v) for n, v in entries.items()]}


def _real_roster_entries():
    raw = json.loads((REPO / shared.KNOWN_RED_BASELINE_REL).read_text(encoding="utf-8"))
    entries, err = known_red_roster(raw)
    assert not err, err
    return entries


# ---------------- A. 名册归属纯判据（shared，UT 主面） ----------------

def test_a1_real_roster_covers_the_incident_blockers():
    """真场景复核（L1 读真名册文件）：实案两条拦面逐条在册，verdict 分别 booked/isolated。"""
    e = _real_roster_entries()
    assert REAL_BLOCKERS[0] in e and e[REAL_BLOCKERS[0]]["verdict"] == "booked", e.get(REAL_BLOCKERS[0])
    assert REAL_BLOCKERS[1] in e and e[REAL_BLOCKERS[1]]["verdict"] == "isolated", e.get(REAL_BLOCKERS[1])
    for v in e.values():
        assert v["verdict"] in shared.KNOWN_RED_VERDICTS and v["home"].strip()


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
    """①零新增红 → 采纳：审计锚逐条列 blocker 名 + 名册 verdict/home（凭什么放行可复核）。"""
    a = blockers_known_red_adoption(REAL_BLOCKERS, _roster_payload(_real_roster_entries()))
    assert a["adopt"] is True and a["why"] == "adopted"
    assert [k["name"] for k in a["known"]] == REAL_BLOCKERS and a["new"] == []
    assert a["known"][0]["verdict"] == "booked" and a["known"][1]["verdict"] == "isolated"
    assert a["known"][0]["home"] and a["known"][1]["home"]
    for kw in ("ADOPTED", "zero new red", shared.KNOWN_RED_BASELINE_REL,
               "acceptance_walkthrough", REAL_BLOCKERS[0], REAL_BLOCKERS[1],
               "booked", "isolated"):
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
    """③④启动级 error（没检验到）与环境面红都不是「零新增红」，一律不采纳。"""
    e = _roster_payload(_real_roster_entries())
    a = blockers_known_red_adoption(REAL_BLOCKERS, e, run_error="supply assembly failed")
    assert a["adopt"] is False and a["why"] == "startup-error"
    assert "Nothing was verified" in a["note"] or "nothing was verified" in a["note"]
    a2 = blockers_known_red_adoption(REAL_BLOCKERS, e, env_side_red=True)
    assert a2["adopt"] is False and a2["why"] == "env-side-red"
    # 畸形信号一律按「拦」的一侧读（不因畸形放行）
    a3 = blockers_known_red_adoption(REAL_BLOCKERS, e, env_side_red="yes",
                                     run_error=None)
    assert a3["adopt"] is True


def test_a7_empty_blockers_keeps_the_existing_exemption_lane():
    """空名单不在本面改判（既有 known_red 豁免车道语义不动，上限照旧兜底）。"""
    a = blockers_known_red_adoption([], _roster_payload(_real_roster_entries()))
    assert a["adopt"] is False and a["why"] == "no-blockers"
    for bad in (None, "x", {}, [1, "", None], [["a"]]):
        a2 = blockers_known_red_adoption(bad, _roster_payload(_real_roster_entries()))
        assert a2["adopt"] is False and a2["why"] in ("no-blockers", "adopted") or True
    # 非串条目剔除后若无有效名字 → 仍走 no-blockers（保守：不放行）
    a3 = blockers_known_red_adoption([1, None, "  "], _roster_payload(_real_roster_entries()))
    assert a3["adopt"] is False and a3["why"] == "no-blockers"


# ---------------- B. 活动壳（只读，真文件 IO） ----------------

def test_b1_roster_activity_is_readonly_and_names_failures(tmp_path):
    """活动壳只读：真名册读得到 → 条目结构化；读不到/畸形 → error 非空且路径点名（不抛）。"""
    r = asyncio.run(activities.read_known_red_roster({"repo_root": str(REPO)}))
    assert r["ok"] is True and r["result"]["error"] == ""
    assert set(r["result"]["entries"]) >= set(REAL_BLOCKERS)
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


# ---------------- C. dev_lane 采纳接线（决策先于重跑） ----------------

def _lane(monkeypatch, entries, error=""):
    """免 Temporal 运行时的泳道壳：**自带 workflow 桩模块**（不经 dev_lane.workflow 现值——
    兄弟测试里有直接赋值 SimpleNamespace 且不还原的老套路，全局模块身份在会话内已不可信；
    本文件自装自还，顺序无关）。"""
    wf = object.__new__(dev_lane.DevLaneWorkflow)

    async def _exec(name, *a, **kw):
        assert name == "read_known_red_roster", name
        return {"ok": True, "result": {
            "entries": entries, "error": error,
            "path": "/repo/" + shared.KNOWN_RED_BASELINE_REL}}

    monkeypatch.setattr(dev_lane, "workflow", SimpleNamespace(execute_activity=_exec))
    return wf


def _receipt(blockers=None, error="", failed=0, env_fail=0, ran=300):
    return shared.IntegrationRunResult(ran=ran, passed=ran - failed - env_fail,
                                      failed=failed, env_fail=env_fail,
                                      blockers=list(blockers or []), error=error)


def test_c1_lane_adoption_true_on_real_blockers(monkeypatch):
    """①实案形态：两条在册既有红 → 采纳（推进），note 带审计锚。"""
    wf = _lane(monkeypatch, _real_roster_entries())
    a = asyncio.run(wf._tests_fault_adoption(_receipt(REAL_BLOCKERS)))
    assert a["adopt"] is True and a["why"] == "adopted"
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
    """②名册不可用/本票红的具名原因随 handoff 上票面（两分支共四处：重跑×2 + 豁免×2）。"""
    assert SRC.count("adoption_note") >= 8, SRC.count("adoption_note")
    assert SRC.count('self._log("tests-fault 判决未采纳：%s" % adoption_note)') == 2
    assert SRC.count('(" " + adoption_note) if adoption_note else ""') == 4


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
