#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane/watchdog 巡检面（260926，KI-122 追加面 / KI-126 同源）的 L1 回归棒。

宿主追问（260926）「巡检发现这个问题了吗」→ 没有：巡检各面只读制品与代码（套件回执/变化面
diff/KI 清单/台账），**没有一面读票的工作流时间线**——而活锁只体现在泳道层（同一票
`gate → tests-fault → 重跑`）。本文件钉这一路新发现源：

  A. 阈值档：声明侧 `watchdog:` 解析（正/负用例）+ 运行期回落与**来源点名**（不静默）；
  B. 三族判据（纯函数）：同票重跑轮次 / tests-fault 回路停留 / 在飞静默僵尸——每族
     **各命中 + 各反例**；每票聚合一条；畸形事实逐项降级点名；
  C. **活动/入口级端到端**（桩数据）：走 activities.run_inspection_lane_watchdog 真入口，
     桩 Temporal client + 桩注册表，三类形态各命中/各反例，且**零写零信号**（只 query）；
  D. 巡检接线：face 段 + 心跳合成 + 活动失败/截断/查不到的具名发现（不静默）。

叙述文案一律英文（报告面零 CJK 守门覆盖本面三族：subject/why/suggestion 全扫，含正控）。
运行：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t260926_lane_watchdog.py -q`（UT 全程禁网络/真 Temporal/真 git）。
"""
from __future__ import annotations

import asyncio
import inspect as _inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
REPO = POC.parent.parent

import activities  # noqa: E402
import inspection_decl as decl  # noqa: E402
import inspection_flow as flow  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_lane_watchdog as lw  # noqa: E402
from inspection_deadman import make_finding  # noqa: E402

NOW = 1_790_430_000.0     # 固定「此刻」（判据全是相对量，易读即可）


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _facts(ticket_id="t1", project="sandbar", *, rounds=1, round_gap=1800,
           last_round_ago=0.0, verdict="", verdict_age=0.0, last_lag=0.0,
           stage="implement", stage_state="running", status="dispatched", now=NOW):
    """桩事实（绕开快照解析，直接喂判据面）：rounds 轮套件（末轮距此刻 last_round_ago 秒）、
    判决在 verdict_age 秒之前、最后进展在 last_lag 秒之前。"""
    starts = [now - last_round_ago - round_gap * (rounds - 1 - i) for i in range(rounds)]
    v_at = (now - verdict_age) if verdict else 0.0
    return {"ticket_id": ticket_id, "project": project, "workflow_id": ticket_id,
            "stage": stage, "stage_state": stage_state, "status": status,
            "verdict": verdict, "verdict_at": v_at,
            "suite_rounds": rounds, "suite_entries": starts,
            "last_activity_at": now - last_lag, "created_at": now - 86400,
            "paused": False, "blocked_reason": "", "parse_notes": []}


def _snapshot(*, rounds=1, round_gap=1800, verdict="", verdict_age=0.0,
              last_lag=0.0, stage="implement", stage_state="running",
              status="dispatched", created_ago=86400, now=NOW, timeline=None,
              last_round_ago=None):
    """桩快照（与真 snapshot query 同形：timeline/gens/results/meta）。"""
    tl = timeline if timeline is not None else []
    last_round_ago = round_gap if last_round_ago is None else last_round_ago
    starts = [now - last_round_ago - round_gap * (rounds - 1 - i) for i in range(rounds)]
    for i, t in enumerate(starts, start=1):
        tl.append({"at": _iso(t), "stage": "run_integration_tests", "state": "running",
                   "gen": i, "reason": "进入本步（第 %d 次）" % i})
        tl.append({"at": _iso(t + round_gap * 0.4), "stage": "run_integration_tests",
                   "state": "done", "gen": i, "reason": "run_integration_tests：..."})
    results = {}
    if verdict:
        tl.append({"at": _iso(now - verdict_age), "stage": "arbitrate",
                   "state": "running", "gen": rounds, "reason": "进入本步（第 %d 次）" % rounds})
        results["arbitrate"] = {"status": "failed", "summary": "verdict=%s 判词" % verdict}
    tl.append({"at": _iso(now - last_lag), "stage": stage, "state": stage_state,
               "reason": "进入本步（第 1 次）"})
    return {"stage": stage, "stage_state": stage_state, "status": status,
            "gens": {"run_integration_tests": rounds} if rounds else {},
            "results": results, "timeline": tl,
            "meta": {"created": now - created_ago, "updated": now - last_lag,
                     "log": [{"ts": now - last_lag, "note": "stub"}]}}


def _scan(facts_list, **thr):
    return lw.lane_findings(facts_list, now_ts=NOW, thresholds=thr or None)


# ---------------- A. 阈值档（声明解析 + 运行期回落与来源点名） ----------------

def test_a1_no_declaration_uses_module_defaults_and_names_source():
    thr, source, note, problems = lw.resolve_thresholds(None)
    assert thr == {"rerun_rounds": lw.DEFAULT_RERUN_ROUNDS,
                   "fault_loop_min": lw.DEFAULT_FAULT_LOOP_MIN,
                   "inflight_silent_min": lw.DEFAULT_INFLIGHT_SILENT_MIN}
    assert (source, problems) == (lw.THRESHOLD_SOURCE_DEFAULT, [])
    assert "source=default" in note
    assert lw.DEFAULT_RERUN_ROUNDS == 3 and lw.DEFAULT_FAULT_LOOP_MIN == 90
    assert lw.DEFAULT_INFLIGHT_SILENT_MIN == 120


def test_a2_declaration_values_win_and_source_is_declaration():
    thr, source, note, problems = lw.resolve_thresholds(
        {"rerun_rounds": "5", "fault_loop_min": "30", "inflight_silent_min": "45"})
    assert (thr, source, problems) == ({"rerun_rounds": 5, "fault_loop_min": 30,
                                        "inflight_silent_min": 45},
                                       lw.THRESHOLD_SOURCE_DECL, [])
    assert "source=declaration" in note and "rerun_rounds=5" in note


def test_a3_malformed_falls_back_per_key_and_names_every_reason():
    thr, source, note, problems = lw.resolve_thresholds(
        {"rerun_rounds": "x", "fault_loop_min": 0, "inflight_silent_min": 120})
    assert thr == {"rerun_rounds": 3, "fault_loop_min": 90, "inflight_silent_min": 120}
    assert source == lw.THRESHOLD_SOURCE_DEFAULT
    assert any("rerun_rounds" in p for p in problems) and any("fault_loop_min" in p for p in problems)
    assert "fallbacks" in note
    thr2, src2, note2, probs2 = lw.resolve_thresholds("nope")
    assert (src2, thr2["rerun_rounds"]) == (lw.THRESHOLD_SOURCE_DEFAULT, 3)
    assert "not a mapping" in probs2[0]
    thr3, src3, _, probs3 = lw.resolve_thresholds({"bogus": "1"})
    assert src3 == lw.THRESHOLD_SOURCE_DEFAULT and any("unknown" in p for p in probs3)


def test_a4_declaration_side_validation_is_failclosed():
    """声明侧三键词法/范围闸（与 inspect 预算键同款 fail-closed；范围单源=本模块）。"""
    src = (POC / "inspection_decl.py").read_text(encoding="utf-8")
    assert "WATCHDOG_DEFAULTS" in src and "WATCHDOG_RANGES" in src
    decl_src = (REPO / "inspection.yaml").read_text(encoding="utf-8")
    assert "watchdog:" in decl_src and "rerun_rounds: 3" in decl_src
    d = decl.parse_decl_text(decl_src, "inspection.yaml")
    inst = d.instance("integration-tests")
    assert inst is not None and inst.watchdog == {
        "rerun_rounds": "3", "fault_loop_min": "90", "inflight_silent_min": "120"}
    plan = decl.resolve_instance_plan.__wrapped__("integration-tests") if hasattr(
        decl.resolve_instance_plan, "__wrapped__") else None
    # plan 透传（additive 键）：直接走纯函数 _plan_from_decl，零 IO
    plan = decl._plan_from_decl(d, "integration-tests")
    assert plan["watchdog"] == inst.watchdog
    for bad, kw in (("      rerun_rounds: 0\n", "rerun_rounds"),
                    ("      fault_loop_min: abc\n", "fault_loop_min"),
                    ("      nope: 1\n", "unknown")):
        txt = decl_src.replace("      rerun_rounds: 3\n", bad if "rerun" in bad or "nope" in bad
                               else "      rerun_rounds: 3\n")
        if kw == "fault_loop_min":
            txt = decl_src.replace("      fault_loop_min: 90\n", bad)
        with pytest.raises(decl.DeclError):
            decl.parse_decl_text(txt, "bad.yaml")


# ---------------- B. 三族判据（纯函数，各命中/各反例） ----------------

def test_b1_rerun_rounds_hit_reports_rounds_and_wall_clock():
    finds, meta = _scan([_facts(rounds=6, round_gap=3600,
                                stage="run_integration_tests")], rerun_rounds=3)
    assert len(finds) == 1 and finds[0]["legs"] == [lw.LEG_RERUN]
    assert finds[0]["scan"] == lw.LANE_SCAN and finds[0]["suggest"] is False
    ev = finds[0]["evidence"]
    assert "suite re-runs=6 > threshold 3" in ev
    assert "60.0min, 60.0min, 60.0min, 60.0min, 60.0min" in ev     # 每轮墙钟（有则给）
    assert "in flight" in ev
    # 当前已不在套件段 → 末轮标 "last round to date"（不假装还在跑）
    ev2 = _scan([_facts(rounds=6, round_gap=3600)])[0][0]["evidence"]
    assert "last round to date" in ev2 and "in flight" not in ev2
    assert meta["by_leg"][lw.LEG_RERUN] == 1 and meta["scanned"] == 1


def test_b2_rerun_rounds_counterexamples_no_finding():
    for rounds in (1, 2, 3):
        finds, meta = _scan([_facts(rounds=rounds)], rerun_rounds=3)
        assert finds == [] and meta["with_findings"] == 0, rounds
    # 4 轮 > 3：命中（阈值语义=严格大于）
    finds, _ = _scan([_facts(rounds=4)], rerun_rounds=3)
    assert len(finds) == 1


def test_b3_rerun_severity_ladder():
    med, _ = _scan([_facts(rounds=4)], rerun_rounds=3)
    assert med[0]["severity"] == "med"          # >N
    high, _ = _scan([_facts(rounds=6)], rerun_rounds=3)
    assert high[0]["severity"] == "high"        # >=2N（今天实案 6 轮即 high）
    # 阈值可配：N=5 时 6 轮只算 med
    med2, _ = _scan([_facts(rounds=6)], rerun_rounds=5)
    assert med2[0]["severity"] == "med"


def test_b4_fault_loop_stall_hit_and_counterexamples():
    # 判决已下、停留 3h > 90min → 命中（high），evidence 点名判决与停留时长
    f, _ = _scan([_facts(rounds=3, verdict="tests-fault", verdict_age=3 * 3600,
                         last_round_ago=3 * 3600, last_lag=3 * 3600)],
                 fault_loop_min=90)
    legs = [x for x in f if lw.LEG_FAULT_LOOP in x["legs"]]
    assert len(legs) == 1 and legs[0]["severity"] == "high"
    assert "verdict=tests-fault handed down 3.0h ago > threshold 90min" in legs[0]["evidence"]
    assert "tests-fault" in legs[0]["subject"]
    # 反例①：停留未超阈值（30min < 90min）
    f2, _ = _scan([_facts(rounds=3, verdict="tests-fault", last_lag=1800)], fault_loop_min=90)
    assert all(lw.LEG_FAULT_LOOP not in x["legs"] for x in f2)
    # 反例②：判决为 pass（收敛）——不是「判决已下却不收敛」
    f3, _ = _scan([_facts(rounds=3, verdict="pass", last_lag=3 * 3600)], fault_loop_min=90)
    assert all(lw.LEG_FAULT_LOOP not in x["legs"] for x in f3)
    # 反例③：无判决时刻（老快照/畸形）→ 不判（保守，不假报）
    facts = _facts(rounds=3, last_lag=3 * 3600)
    facts["verdict"], facts["verdict_at"] = "tests-fault", 0.0
    f4, _ = lw.lane_findings([facts], now_ts=NOW, thresholds={"fault_loop_min": 90})
    assert all(lw.LEG_FAULT_LOOP not in x["legs"] for x in f4)


def test_b5_inflight_silence_hit_and_counterexample():
    f, _ = _scan([_facts(rounds=1, last_lag=4 * 3600)], inflight_silent_min=120)
    assert len(f) == 1 and f[0]["legs"] == [lw.LEG_INFLIGHT]
    assert f[0]["severity"] == "high"
    assert "silent 4.0h > threshold 120min" in f[0]["evidence"]
    assert "stage=implement/running" in f[0]["evidence"]     # 点名 stage（数据不译）
    # 反例：刚好在阈值内 / 无进展时刻（老快照）→ 不判
    f2, _ = _scan([_facts(rounds=1, last_lag=119 * 60)], inflight_silent_min=120)
    assert f2 == []
    facts = _facts(rounds=1)
    facts["last_activity_at"] = 0.0
    f3, _ = lw.lane_findings([facts], now_ts=NOW, thresholds={"inflight_silent_min": 120})
    assert f3 == []


def test_b6_same_ticket_is_aggregated_into_one_finding():
    """同票多族 → **一条**发现（legs 列全），不按族刷屏；不同票各一条。"""
    facts = _facts(ticket_id="t260926-05", rounds=6, verdict="tests-fault",
                   verdict_age=4 * 3600, last_round_ago=4 * 3600, last_lag=4 * 3600)
    f, meta = _scan([facts, _facts(ticket_id="t-other", rounds=1, last_lag=60)], rerun_rounds=3)
    assert len(f) == 1, f
    assert set(f[0]["legs"]) == {lw.LEG_RERUN, lw.LEG_FAULT_LOOP, lw.LEG_INFLIGHT}
    assert f[0]["ticket_id"] == "t260926-05" and f[0]["subject"].startswith("t260926-05 ")
    assert all(tid not in f[0]["subject"] for tid in ("t-other",))
    assert meta["scanned"] == 2 and meta["with_findings"] == 1
    assert meta["by_leg"] == {lw.LEG_RERUN: 1, lw.LEG_FAULT_LOOP: 1, lw.LEG_INFLIGHT: 1}
    # 两票都卡 → 两条（每票一条）
    f2, _ = _scan([_facts(ticket_id="a", rounds=5), _facts(ticket_id="b", rounds=9)])
    assert sorted(x["ticket_id"] for x in f2) == ["a", "b"]


def test_b7_snapshot_parsing_degrades_and_names_malformed():
    """快照解析（facts_from_snapshot）：真形取数正确；畸形逐项降级并点名，绝不抛。"""
    snap = _snapshot(rounds=4, round_gap=600, verdict="tests-fault", verdict_age=300,
                     last_lag=120)
    facts = lw.facts_from_snapshot("t9", "sandbar", snap, now_ts=NOW)
    assert facts["suite_rounds"] == 4 and len(facts["suite_entries"]) == 4
    assert facts["verdict"] == "tests-fault" and facts["verdict_at"] > 0
    assert facts["last_activity_at"] == NOW - 120 and facts["parse_notes"] == []
    assert facts["stage"] == "implement" and facts["status"] == "dispatched"
    # 畸形：非 dict / 时间戳不可解 / gens 与时间线条数不符 → 点名（不静默）
    bad = lw.facts_from_snapshot("t9", "p", None, now_ts=NOW)
    assert bad["suite_rounds"] == 0 and bad["parse_notes"]
    noisy = _snapshot(rounds=2)
    noisy["timeline"].append({"at": "not-a-time", "stage": "arbitrate", "state": "running"})
    noisy["gens"]["run_integration_tests"] = 9
    fb = lw.facts_from_snapshot("t9", "p", noisy, now_ts=NOW)
    assert fb["suite_rounds"] == 9 and any("unparseable" in n for n in fb["parse_notes"])
    assert any("gens[run_integration_tests]=9" in n for n in fb["parse_notes"])
    # 名单级畸形：tickets 非列表/条目非 dict/缺票号 → 跳过并点名
    f2, meta = lw.lane_findings([None, {"project": "x"}, {"ticket_id": "t-ok", "suite_rounds": 0}],
                                now_ts=NOW)
    assert f2 == [] and meta["scanned"] == 1 and len(meta["skipped"]) == 2


def test_b8_lane_section_counts_and_threshold_source():
    finds, meta = _scan([_facts(rounds=6)], rerun_rounds=3)
    sec = lw.lane_section(finds, meta, source=lw.THRESHOLD_SOURCE_DECL,
                          source_note="threshold source=declaration (rerun_rounds=3 ...)")
    assert sec["scan"] == lw.LANE_SCAN and sec["scanned"] == 1
    assert sec["finding_count"] == 1 and sec["max_severity"] == "high"
    assert sec["by_leg"][lw.LEG_RERUN] == 1
    assert sec["threshold_source"] == lw.THRESHOLD_SOURCE_DECL
    assert sec["thresholds"]["rerun_rounds"] == 3
    empty = lw.lane_section(None, None)
    assert empty["finding_count"] == 0 and empty["max_severity"] == ""
    assert empty["threshold_source"] == lw.THRESHOLD_SOURCE_DEFAULT


def test_b9_three_classes_are_covered_by_the_report_language_gate():
    """报告面零 CJK 守门覆盖本面三族：默认文案 subject/why/suggestion 全英文（正控=注入
    CJK 后闸必须命中——闸本身有牙）。"""
    facts = _facts(ticket_id="t-lang", rounds=6, verdict="tests-fault",
                   verdict_age=4 * 3600, last_round_ago=4 * 3600, last_lag=4 * 3600)
    finds, _ = _scan([facts], rerun_rounds=3)
    assert ins.finding_language_violations(finds) == [], finds[0]
    assert not ins.CJK_RE.search(finds[0]["subject"] + finds[0]["why"])
    assert finds[0]["suggestion"] == ""
    poisoned = [dict(f, subject=f["subject"] + " 中文") for f in finds]
    v = ins.finding_language_violations(poisoned)
    assert v and v[0]["fields"] == ["subject"]
    # why 也在闸面内（叙述字段白名单不变：subject/why/suggestion；数据字段不译）
    assert ins.NARRATIVE_FIELDS == ("subject", "why", "suggestion")
    poisoned2 = [dict(f, why=f["why"] + "中文") for f in finds]
    assert ins.finding_language_violations(poisoned2)[0]["fields"] == ["why"]


def test_b10_finding_shape_matches_the_mechanical_family():
    finds, _ = _scan([_facts(rounds=6)])
    f = finds[0]
    assert set(f) >= {"id", "scan", "severity", "subject", "evidence", "suggestion",
                      "suggest", "legs", "why", "ticket_id", "project"}
    assert f["scan"] == lw.LANE_SCAN and f["suggest"] is False and f["suggestion"] == ""
    ref = make_finding("lane", "med", "same subject", "same evidence", suggest=False)
    assert f["id"] and len(f["id"]) == len(ref["id"])       # 形状单点（同一 id 生成器）


# ---------------- C. 活动/入口级端到端（桩数据；零网络零真 Temporal） ----------------

from temporalio.common import SearchAttributeKey  # noqa: E402
from shared import PROJECT_SA_NAME  # noqa: E402


class _FakeWF:
    def __init__(self, wid, project, run_id="run-1"):
        self.id, self.run_id = wid, run_id
        self.typed_search_attributes = {
            SearchAttributeKey.for_keyword(PROJECT_SA_NAME): project}


class _FakeHandle:
    def __init__(self, snap, calls):
        self._snap, self._calls = snap, calls

    async def query(self, name):
        self._calls.append(("query", name))
        if isinstance(self._snap, Exception):
            raise self._snap
        return self._snap


class _FakeClient:
    def __init__(self, wfs, snaps, calls):
        self._wfs, self._snaps, self._calls = wfs, snaps, calls

    async def list_workflows(self, query):
        self._calls.append(("list", query))
        for wf in self._wfs:
            yield wf

    def get_workflow_handle(self, wid, run_id=None):
        return _FakeHandle(self._snaps.get(wid, {}), self._calls)


def _patch_lane_io(monkeypatch, wfs, snaps, projects=("sandbar",)):
    calls: list = []
    async def _connect(host, **kw):
        calls.append(("connect", host))
        return _FakeClient(wfs, snaps, calls)
    monkeypatch.setattr(activities.Client, "connect", _connect)
    monkeypatch.setattr(activities, "list_registered_projects",
                        lambda: ([{"key": k, "name": k, "dirs": ["/x"]} for k in projects], []))
    return calls


def _run_lane_activity(args):
    return asyncio.run(activities.run_inspection_lane_watchdog(args))


def test_c1_entry_level_three_shapes_hit_and_counterexamples(monkeypatch):
    """入口级端到端：三张非终态票各命中一族 + 一张正常票零发现 + 一张查不到的票具名。"""
    wfs = [_FakeWF("t-hit-rerun", "sandbar"), _FakeWF("t-hit-loop", "sandbar"),
           _FakeWF("t-hit-zombie", "sandbar"), _FakeWF("t-clean", "sandbar"),
           _FakeWF("t-unreadable", "sandbar"), _FakeWF("t-other-project", "nusuyou")]
    snaps = {
        "t-hit-rerun": _snapshot(rounds=6, round_gap=3600, last_lag=60,
                                 stage="run_integration_tests"),
        "t-hit-loop": _snapshot(rounds=2, verdict="tests-fault", verdict_age=3 * 3600,
                                last_round_ago=3 * 3600, last_lag=3 * 3600,
                                stage="arbitrate"),
        "t-hit-zombie": _snapshot(rounds=1, last_round_ago=5 * 3600, last_lag=5 * 3600,
                                  stage="run_integration_tests"),
        "t-clean": _snapshot(rounds=1, last_lag=60, stage="acceptance_walkthrough"),
        "t-unreadable": RuntimeError("query timeout"),
    }
    calls = _patch_lane_io(monkeypatch, wfs, snaps)
    out = _run_lane_activity({})
    assert out["ok"] is True, out
    res = out["result"]
    by_ticket = {f["ticket_id"]: f for f in res["findings"]}
    assert set(by_ticket) == {"t-hit-rerun", "t-hit-loop", "t-hit-zombie"}, by_ticket.keys()
    assert by_ticket["t-hit-rerun"]["legs"] == [lw.LEG_RERUN]
    assert lw.LEG_FAULT_LOOP in by_ticket["t-hit-loop"]["legs"]
    assert lw.LEG_INFLIGHT in by_ticket["t-hit-zombie"]["legs"]
    meta = res["meta"]
    assert meta["non_terminal"] == 5 and meta["scanned"] == 4    # 非注册项目票不入扫面；查不到的不计 scanned
    assert res["section"]["non_terminal"] == 5
    assert meta["with_findings"] == 3
    assert any("t-unreadable" in e and "snapshot query failed" in e
               for e in meta["unreadable"])
    assert meta["errors"] and all("t-unreadable" not in e for e in meta["errors"])
    assert any("nusuyou" in e for e in meta["errors"])           # 非注册项目点名（不静默）
    assert res["section"]["finding_count"] == 3
    assert res["section"]["threshold_source"] in (lw.THRESHOLD_SOURCE_DECL,
                                                 lw.THRESHOLD_SOURCE_DEFAULT)
    assert ins.finding_language_violations(res["findings"]) == []
    # 只读：只 connect/list/query，无 update/signal/start/cancel/terminate
    kinds = {c[0] for c in calls}
    assert kinds == {"connect", "list", "query"}, calls
    assert all("ExecutionStatus=\"Running\"" in c[1] for c in calls if c[0] == "list")


def test_c2_entry_level_declaration_thresholds_take_effect(monkeypatch):
    """入口级：声明阈值生效（N=5 → 6 轮不报），且 lane 段点名来源=declaration。"""
    wfs = [_FakeWF("t-6", "sandbar")]
    snaps = {"t-6": _snapshot(rounds=6, round_gap=600, last_lag=60)}
    _patch_lane_io(monkeypatch, wfs, snaps)
    # N=6 → 6 轮不超阈（严格大于才报；阈值语义与缺省一脉）
    out = _run_lane_activity({"watchdog": {"rerun_rounds": "6", "fault_loop_min": "90",
                                           "inflight_silent_min": "120"}})
    res = out["result"]
    assert res["findings"] == [] and res["meta"]["scanned"] == 1
    assert res["section"]["threshold_source"] == lw.THRESHOLD_SOURCE_DECL
    assert res["section"]["thresholds"]["rerun_rounds"] == 6
    # 同票同一快照，N=5 → 超阈即报（阈值真的在起作用，不是恒绿）
    out1 = _run_lane_activity({"watchdog": {"rerun_rounds": "5"}})
    assert [f["legs"] for f in out1["result"]["findings"]] == [[lw.LEG_RERUN]]
    # 畸形声明档 → 回落缺省并在段上点名（不静默）
    out2 = _run_lane_activity({"watchdog": {"rerun_rounds": "0"}})
    res2 = out2["result"]
    assert res2["findings"] and res2["section"]["threshold_source"] == lw.THRESHOLD_SOURCE_DEFAULT
    assert "fallbacks" in res2["section"]["threshold_note"]


def test_c3_entry_level_registry_failure_is_failclosed(monkeypatch):
    """入口级：注册表读不到=ok False 点名（不静默扫零票当「全绿」）。"""
    def _boom():
        raise ValueError("registry root missing")
    monkeypatch.setattr(activities, "list_registered_projects", _boom)
    out = _run_lane_activity({})
    assert out["ok"] is False and "注册表" in out["error"]


def test_c4_activity_registered_and_readonly_source_lock():
    names = [getattr(a, "__name__", "") for a in activities.ALL_ACTIVITIES]
    assert names.count("run_inspection_lane_watchdog") == 1
    src = _inspect.getsource(activities.run_inspection_lane_watchdog)
    for forbidden in ("update_workflow", "signal_workflow", "start_workflow",
                      "cancel_workflow", "terminate_workflow", ".signal(", ".update(",
                      ".cancel(", ".terminate(", "start_workflow("):
        assert forbidden not in src, forbidden
    assert "\"snapshot\"" in src and "list_workflows" in src
    ws = (POC / "inspection_lane_watchdog.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "open(", "write_text", "Path(", "os.environ"):
        assert forbidden not in ws, forbidden


# ---------------- D. 巡检接线（face 段 + 心跳 + 具名失败） ----------------

def test_d1_flow_wires_lane_face_behind_the_patch_gate():
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow._run_inspect_period_flow)
    assert "workflow.patched(LANE_WATCHDOG_PATCH_ID)" in src
    gate = src.index("workflow.patched(LANE_WATCHDOG_PATCH_ID)")
    call = src.index("await self._lane_watchdog(inp, plan)")
    assert gate < call, "活动调用必须在版本门后（老在途票 history 零新命令）"
    assert "extra_findings += lane_findings" in src
    assert "lane=lane_section" in src
    assert flow.LANE_WATCHDOG_PATCH_ID == "inspection-lane-watchdog-v1"
    # 老轨道（legacy）不接本面（只服务老票 replay）
    legacy = _inspect.getsource(flow._run_legacy_period_flow)
    assert "run_inspection_lane_watchdog" not in legacy


def test_d0_watchdog_budget_and_timeout_inequality():
    """双闸不等式（SUITE/INSPECT 同款纪律）：Temporal 硬超时必须晚于活动内部预算，
    否则「预算用尽」的收口跑不到、巡检票被 Temporal 判死。"""
    assert flow.WATCHDOG_SCAN_BUDGET_SEC >= 30
    assert flow.LANE_WATCHDOG_TO.total_seconds() >= flow.WATCHDOG_SCAN_BUDGET_SEC + 30
    assert flow.RETRY_LANE_WATCHDOG.maximum_attempts == 1
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow._lane_watchdog)
    assert "LANE_WATCHDOG_TO" in src and "RETRY_LANE_WATCHDOG" in src
    assert "scan_budget_sec" in src and "WATCHDOG_SCAN_BUDGET_SEC" in src


def test_d2_face_carries_lane_section_and_heartbeat_composition():
    baseline = flow.build_ticket_face(
        "t1", "inst", "20260926",
        {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True})
    assert "lane" not in baseline and baseline["heartbeat"] is True
    finds, meta = _scan([_facts(rounds=6)])
    sec = lw.lane_section(finds, meta, source=lw.THRESHOLD_SOURCE_DEFAULT,
                          source_note="threshold source=default")
    face = flow.build_ticket_face(
        "t1", "inst", "20260926",
        {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True},
        extra_findings=finds, lane=sec)
    assert face["lane"] == sec
    assert face["lane"]["finding_count"] == 1
    assert face["summary"]["high"] == 1       # 追加发现进摘要重计（计数可见；6 轮=high）
    assert face["heartbeat"] is False         # 票卡在泳道里 ≠ 全绿心跳期
    assert ins.finding_language_violations(face["findings"]) == []
    # 零发现的 lane 段不破心跳（本期扫过但无卡票）
    sec0 = lw.lane_section([], {"scanned": 3, "by_leg": {}}, source=lw.THRESHOLD_SOURCE_DECL)
    face0 = flow.build_ticket_face(
        "t1", "inst", "20260926",
        {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True},
        lane=sec0)
    assert face0["heartbeat"] is True and face0["lane"]["scanned"] == 3


def test_d3_lane_activity_failure_and_unreadable_tickets_are_named(monkeypatch):
    """活动炸 / 查不到的票 / 枚举截断：一律具名发现（这个面本身不许静默）。"""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)

    async def _boom(*a, **kw):
        raise RuntimeError("worker missing")
    # 自装自还的 workflow 桩（兄弟测试有直接赋值 SimpleNamespace 不还原的老套路，
    # 全局模块身份在会话内不可信——本文件不依赖它）
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_boom))
    sec, finds = asyncio.run(wf._lane_watchdog(object(), {"watchdog": {}}))
    assert sec is None and len(finds) == 1
    assert finds[0]["scan"] == "lane" and finds[0]["severity"] == "high"
    assert "did not run" in finds[0]["subject"] and finds[0]["suggest"] is False

    async def _notok(*a, **kw):
        return {"ok": False, "error": "temporal server 不可达"}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_notok))
    sec2, finds2 = asyncio.run(wf._lane_watchdog(object(), {}))
    assert sec2 is None and "不可达" in finds2[0]["evidence"]

    async def _ok(*a, **kw):
        return {"ok": True, "result": {
            "findings": [], "section": lw.lane_section([], {"scanned": 2}),
            "meta": {"unreadable": ["t300001-01: snapshot query failed: Timeout"],
                     "errors": ["t300002-02: project 'x' not in the project registry (skipped)"],
                     "enum_note": "scan truncated at max_tickets=1"}}}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_ok))
    sec3, finds3 = asyncio.run(wf._lane_watchdog(object(), {}))
    assert sec3 is not None and len(finds3) == 3
    assert "unreadable ticket" in finds3[0]["subject"]
    assert "skipped" in finds3[1]["subject"]
    assert "truncated" in finds3[2]["subject"]
    assert all(f["scan"] == "lane" and f["suggest"] is False for f in finds3)
    assert ins.finding_language_violations(finds3) == []
