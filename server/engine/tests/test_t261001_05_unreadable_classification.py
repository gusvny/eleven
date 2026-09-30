#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane/watchdog 读失败两分类 + 瞬态一次加预算重试（t261001-05）。

背景：周期 sweep 把每张非终态票的快照读失败并成一只桶（"had N unreadable ticket(s)"，
N=197 读起来像 197 张坏票）——实际几乎全是 query TimeoutError（扫描时 worker 缺位），
真坏票只有一张（"Workflow Task in failed state"，且已 terminate 清理）。

本面钉住的行为：
  A. 分类：瞬态（超时无应答）与永久（工作流本体条件）在活动回执 meta 里分开计数，
     逐票原始异常文本全保留（fail-closed：读不到的票绝不进 facts、绝不当「没问题」）。
  B. 重试：瞬态第一读超时后**恰好一次**更长单票预算的重试（成功则该票照常进 facts）；
     永久失败不重试（一次就点名）。
  C. 文案：发现条按类分开、分开计数；evidence 一句话点名本期主类及其含义；老回执
     （无分类键）回落单条旧形文案（重放确定性）。
  D. 界限不变：并发/单票超时/总预算三闸仍钳制（预算耗尽的票不再重试、归瞬态）。

跑法：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261001_05_unreadable_classification.py -q`
（零网络/零真 Temporal；桩 Client/注册表，私有临时根）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent          # server/engine
sys.path.insert(0, str(POC))

import activities  # noqa: E402
import inspection_flow as flow  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_lane_watchdog as lw  # noqa: E402
from shared import PROJECT_SA_NAME  # noqa: E402
from temporalio.common import SearchAttributeKey  # noqa: E402


# ---------------------------------------------------------------- 桩 Temporal 面 ----

class _FakeWF:
    def __init__(self, wid, project):
        self.id, self.run_id = wid, "run-1"
        self.typed_search_attributes = {
            SearchAttributeKey.for_keyword(PROJECT_SA_NAME): project}


class _FakeHandle:
    """按票行为桩：delay_s>0 睡（驱动 wait_for 真超时→加预算重试真过）；
    error=非超时异常（永久条件，如 "Workflow Task in failed state"）。"""

    def __init__(self, behavior, calls):
        self._behavior, self._calls = behavior, calls

    async def query(self, name):
        self._calls.append(("query", name))
        delay, error = self._behavior
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        return {"ticket_id": name}


class _FakeClient:
    def __init__(self, wfs, behaviors, calls):
        self._wfs, self._behaviors, self._calls = wfs, behaviors, calls

    async def list_workflows(self, query):
        self._calls.append(("list", query))
        for wf in self._wfs:
            yield wf

    def get_workflow_handle(self, wid, run_id=None):
        return _FakeHandle(self._behaviors.get(wid, (0.0, None)), self._calls)


def _patch_io(monkeypatch, wfs=(), behaviors=None):
    calls: list = []

    async def _connect(host, **kw):
        calls.append(("connect", host))
        return _FakeClient(list(wfs), behaviors or {}, calls)

    monkeypatch.setattr(activities.Client, "connect", _connect)
    monkeypatch.setattr(activities, "list_registered_projects",
                        lambda: ([{"key": "sandbar", "name": "sandbar", "dirs": ["/x"]}], []))
    return calls


def _run(args):
    return asyncio.run(activities.run_inspection_lane_watchdog(args))


ARGS = {"query_timeout_sec": 0.05, "snapshot_retry_timeout_sec": 1.0,
        "scan_budget_sec": 30.0, "tmp_fixture_root": "/nonexistent-t261001-05",
        "tmp_fixture_scan_ttl_sec": 0}


# ---------------------------------------------------------------- A. 分类 ----------

def test_a1_timeout_and_permanent_counted_separately(monkeypatch):
    """瞬态（超时无应答）与永久（failed-state）两类分开计数，原始文本逐票保留。"""
    wfs = [_FakeWF("t-transient", "sandbar"), _FakeWF("t-permanent", "sandbar")]
    behaviors = {"t-transient": (5.0, None),   # 两读都等满超时（无 worker 应答的僵票形态）
                 "t-permanent": (0.0, Exception("Workflow Task in failed state"))}
    _patch_io(monkeypatch, wfs, behaviors)
    out = _run(dict(ARGS, snapshot_retry_timeout_sec=0.06))
    assert out["ok"] is True, out
    meta = out["result"]["meta"]
    assert meta["unreadable_transient"] == ["t-transient: snapshot query failed after 1 "
                                            "retry: TimeoutError: "]
    assert len(meta["unreadable_permanent"]) == 1
    assert meta["unreadable_permanent"][0].startswith(
        "t-permanent: snapshot query failed: Exception: Workflow Task in failed state")
    assert sorted(meta["unreadable"]) == sorted(meta["unreadable_transient"]
                                                + meta["unreadable_permanent"])


def test_a2_malformed_retry_arg_falls_back_to_multiplier(monkeypatch):
    """畸形 snapshot_retry_timeout_sec → 回落 q_to×SNAPSHOT_RETRY_TIMEOUT_MULT（不抛）。"""
    wfs = [_FakeWF("t-ok", "sandbar")]
    _patch_io(monkeypatch, wfs, {"t-ok": (0.0, None)})
    bad = dict(ARGS, snapshot_retry_timeout_sec="not-a-number")
    out = _run(bad)
    assert out["ok"] is True and out["result"]["meta"]["unreadable"] == []


# ---------------------------------------------------------------- B. 重试 ----------

def test_b1_transient_retried_once_then_recovers(monkeypatch):
    """瞬态第一读超时 → 恰好一次加预算重试 → 成功则照常出 facts（不进 unreadable）。"""
    wfs = [_FakeWF("t-slow", "sandbar")]
    behaviors = {"t-slow": (0.2, None)}     # 0.05s 首读超时；1.0s 重试内 0.2s 能回
    calls = _patch_io(monkeypatch, wfs, behaviors)
    out = _run(dict(ARGS))
    meta = out["result"]["meta"]
    assert meta["unreadable"] == [] and meta["unreadable_transient"] == []
    assert meta["scanned"] == 1
    assert ("query", "snapshot") in calls
    assert sum(1 for c in calls if c[0] == "query") == 2          # 首读 + 恰好一次重试
    # 只读铁律：零写零信号
    assert {c[0] for c in calls} == {"connect", "list", "query"}


def test_b2_transient_gives_up_after_one_retry(monkeypatch):
    """重试仍超时 → 归瞬态、不再第三读（give-up 路径由 rod 驱动）。"""
    wfs = [_FakeWF("t-dead", "sandbar")]
    behaviors = {"t-dead": (5.0, None)}     # 两读都等满超时
    calls = _patch_io(monkeypatch, wfs, behaviors)
    out = _run(dict(ARGS, query_timeout_sec=0.05, snapshot_retry_timeout_sec=0.06,
                    scan_budget_sec=30.0, tmp_fixture_root="/nonexistent-t261001-05"))
    meta = out["result"]["meta"]
    assert len(meta["unreadable_transient"]) == 1
    assert "after 1 retry" in meta["unreadable_transient"][0]
    assert sum(1 for c in calls if c[0] == "query") == 2          # 恰好两次，无第三读


def test_b3_permanent_failure_never_retried(monkeypatch):
    """永久条件一次点名：没有第二次 query（重试只给瞬态类）。"""
    wfs = [_FakeWF("t-broken", "sandbar")]
    behaviors = {"t-broken": (0.0, Exception("Workflow Task in failed state"))}
    calls = _patch_io(monkeypatch, wfs, behaviors)
    out = _run(dict(ARGS))
    meta = out["result"]["meta"]
    assert len(meta["unreadable_permanent"]) == 1
    assert meta["unreadable_transient"] == []
    assert sum(1 for c in calls if c[0] == "query") == 1


# ---------------------------------------------------------------- C. 文案 ----------

def test_c1_specs_two_classes_dominant_named(monkeypatch):
    """两类 → 两条分开计数分开文案的发现规格；evidence 一句话点名主类及含义。"""
    meta = {"unreadable": ["t1: snapshot query failed after 1 retry: TimeoutError",
                           "t2: snapshot query failed after 1 retry: TimeoutError",
                           "t3: snapshot query failed: Exception: Workflow Task in failed state"],
            "unreadable_transient": ["t1: snapshot query failed after 1 retry: TimeoutError",
                                     "t2: snapshot query failed after 1 retry: TimeoutError"],
            "unreadable_permanent": ["t3: snapshot query failed: Exception: Workflow Task "
                                     "in failed state"]}
    specs = lw.unreadable_finding_specs(meta)
    assert len(specs) == 2
    by_subj = {s["subject"]: s for s in specs}
    perm = [s for s in specs if "permanent" in s["subject"]][0]
    trans = [s for s in specs if "transient" in s["subject"]][0]
    assert perm["severity"] == "med" and "needs a human" in perm["subject"]
    assert trans["severity"] == "low" and "not broken tickets" in trans["subject"]
    for s in (perm, trans):
        assert "Dominant class: transient." in s["evidence"]      # 本期主类=transient(2>1)
        assert "Workflow Task in failed state" in s["evidence"]   # 逐票原始文本保留
    assert "t3:" in perm["evidence"] and "t1:" in trans["evidence"] and "t2:" in trans["evidence"]
    # 畸形输入不抛
    assert lw.unreadable_finding_specs(None) == []
    assert lw.unreadable_finding_specs({"unreadable": [42], "unreadable_transient": "x",
                                        "unreadable_permanent": []})  # 老形回落不抛
    assert lw.unreadable_finding_specs({"unreadable": []}) == []


def test_c2_legacy_receipt_falls_back_to_old_single_finding():
    """老回执（无分类键）→ 单条旧形文案（不猜类，重放确定性不破）。"""
    meta = {"unreadable": ["t9: snapshot query failed: TimeoutError"]}
    specs = lw.unreadable_finding_specs(meta)
    assert len(specs) == 1
    assert specs[0]["subject"] == "Lane/watchdog sweep had 1 unreadable ticket(s)"
    assert specs[0]["severity"] == "med"
    assert "KI-126 zombie shape" in specs[0]["evidence"] and "t9:" in specs[0]["evidence"]


def test_c3_flow_wiring_two_class_findings(monkeypatch):
    """工作流接线：分类 meta → 两条发现进同一清单；建议位仍为 suggest=False。"""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    meta = {"unreadable": ["t1: snapshot query failed after 1 retry: TimeoutError",
                           "t3: snapshot query failed: Exception: Workflow Task in failed state"],
            "unreadable_transient": ["t1: snapshot query failed after 1 retry: TimeoutError"],
            "unreadable_permanent": ["t3: snapshot query failed: Exception: Workflow Task "
                                     "in failed state"]}

    async def _ok(*a, **kw):
        return {"ok": True, "result": {"findings": [], "section":
                lw.lane_section([], {"scanned": 2, "by_leg": {}}, source="declaration"),
                "section_merged": lw.lane_section([], {"scanned": 2, "by_leg": {}},
                                                  source="declaration"),
                "meta": meta}}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_ok))
    _sec, finds = asyncio.run(wf._lane_watchdog(object(), {}))
    unread = [f for f in finds if "unreadable ticket" in f["subject"]]
    assert len(unread) == 2                                   # 两类各一条，都不静默丢弃
    assert all(f["scan"] == "lane" and f["suggest"] is False for f in unread)
    assert ins.finding_language_violations(finds) == []


def test_c4_flow_wiring_legacy_receipt(monkeypatch):
    """老回执接线：单条旧形发现（逐字段同旧实现）。"""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    sec = lw.lane_section([], {"scanned": 1, "by_leg": {}}, source="declaration")

    async def _ok(*a, **kw):
        return {"ok": True, "result": {"findings": [], "section": sec, "meta":
                {"unreadable": ["t9: snapshot query failed: TimeoutError"]}}}
    monkeypatch.setattr(flow, "workflow", SimpleNamespace(execute_activity=_ok))
    _sec2, finds = asyncio.run(wf._lane_watchdog(object(), {}))
    assert len(finds) == 1
    assert finds[0]["subject"] == "Lane/watchdog sweep had 1 unreadable ticket(s)"
    assert finds[0]["severity"] == "med" and finds[0]["suggest"] is False


# ---------------------------------------------------------------- D. 界限不变 -------

def test_d1_budget_exhausted_ticket_is_transient_and_not_retried(monkeypatch):
    """总预算耗尽：没读成的票归瞬态、不再重试（预算已尽）；三闸计数字段原样在 meta。"""
    wfs = [_FakeWF("t-first", "sandbar"), _FakeWF("t-late", "sandbar")]
    behaviors = {"t-first": (5.0, None), "t-late": (0.0, None)}
    _patch_io(monkeypatch, wfs, behaviors)
    # 并发 1：第一张吃满两段超时把预算烧光，第二张进「预算耗尽」分支
    out = _run(dict(ARGS, concurrency=1, query_timeout_sec=0.05,
                    snapshot_retry_timeout_sec=0.06, scan_budget_sec=0.08,
                    tmp_fixture_root="/nonexistent-t261001-05"))
    meta = out["result"]["meta"]
    assert meta["concurrency"] == 1 and meta["scan_budget_sec"] == 0.08
    assert len(meta["unreadable"]) == 2 and len(meta["unreadable_transient"]) == 2
    assert meta["unreadable_permanent"] == []
    assert meta["enum_note"]        # 预算面点名（budget note）不丢
