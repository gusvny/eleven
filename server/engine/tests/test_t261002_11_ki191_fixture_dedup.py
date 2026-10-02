"""t261002-11 / KI-191 单测：快进夹具不得占真排程的期号空间（dedup 认标记）。

病根（KI-191，20261002 实证）：260926 巡检 UI 夹具快进时钟跑真流程，铸出期=20261002
的巡检票（t261002-01，无事件账本行=非真跑）→「一期一票」幂等账把它当真身，真班连
续多日被 deduped=True 静默吞掉；回执 `ticket=?`（读错键）掩盖了一切。

修复口径（本文件守的行为面）：
  ①夹具标记隔离：带 fixture_mark 的开票盖 InspectionFixture/InspectionSlotTakenAt
    SA 章；真班（无标记）视夹具票为**非去重对象**——跳过并照常铸真票；夹具开票遇
    真票/异标票 = 具名报错（fixture mark ownership check failed）。
  ②清坑单点 release_period_slot：只放行带本标记的活票；missing mark / 双清 / 越权
    （真班票）三检查全部具名报错，绝不裸布尔。
  ③回执点名：deduped 回执必须带 ticket_id（既有键）+ slot_taken_at（占坑章；
    无章=unknown 诚实呈报）+ fixture 标 + skipped_fixture_tickets（真班被夹具占过坑
    的可见痕）。
  ④期槽诚实面 describe_period_slot：占用人/状态/标记/占坑时刻可查询。

UT 全程禁网络/真 Temporal；夹具复用 test_t260916_02 的 FakeClient 形制（岗位纪律
允许的夹具共享）。
运行：server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261002_11_ki191_fixture_dedup.py -q
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspection_ticketing as tick  # noqa: E402
import shared  # noqa: E402
from test_t260916_02_inspection_ticketing import (  # noqa: E402
    FakeClient, FakeHandle, FakeWf)

INS = shared.INSPECTION_INSTANCE_SA_NAME
PER = shared.INSPECTION_PERIOD_SA_NAME
FIX = shared.INSPECTION_FIXTURE_SA_NAME
TAKEN = shared.INSPECTION_SLOT_TAKEN_SA_NAME
INST = "integration-tests"
PERIOD = "20261002"
MARK = "fixture-t260926-ui"


def open_ticket(client, tmp_path, **kw):
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(tmp_path / "ledger")
    try:
        base = dict(instance_id=INST, period=PERIOD, project_key="sandbar",
                    repo_root="/repo", scan_face="test", decl_path="", task_queue="tq")
        base.update(kw)
        return asyncio.run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def ticket(tid, status="RUNNING", fx="", taken=""):
    sa = {INS: INST, PER: PERIOD}
    if fx:
        sa[FIX] = fx
    if taken:
        sa[TAKEN] = taken
    return FakeWf(tid, status=status, sa=sa)


# ============================================================ ① 夹具标记隔离

def test_real_spawn_skips_fixture_squatter_and_mints_real_ticket(tmp_path):
    """验收①主回归：夹具票占着期 → 真班照常铸真票（绝不被 deduped 吞掉）。"""
    client = FakeClient([ticket("t261002-01", "RUNNING", fx=MARK,
                                taken="2026-09-26T21:30:00+00:00")])
    res = open_ticket(client, tmp_path)
    assert res["ok"], res
    r = res["result"]
    assert r["triggered"] is True and r["deduped"] is False
    assert r["ticket_id"] == "t261002-02"          # 夹具占 01，真票取 02
    assert r["fixture"] is False
    assert r["skipped_fixture_tickets"] == ["t261002-01"]   # 占坑痕可见
    # 新真票无夹具章、有占坑章（ISO 时刻）
    st = client.started[0]
    assert FIX not in st["sa"]
    assert st["sa"].get(TAKEN)
    assert "T" in st["sa"][TAKEN] and ":" in st["sa"][TAKEN]


def test_fixture_spawn_dedups_onto_same_mark_ticket(tmp_path):
    client = FakeClient([ticket("t261002-01", "RUNNING", fx=MARK,
                                taken="2026-09-26T21:30:00+00:00")])
    res = open_ticket(client, tmp_path, fixture_mark=MARK)
    assert res["ok"] and res["result"]["deduped"] is True
    r = res["result"]
    assert r["ticket_id"] == "t261002-01" and r["dedup_source"] == "sa_query"
    assert r["fixture"] is True
    assert r["slot_taken_at"] == "2026-09-26T21:30:00+00:00"   # 点名占坑时刻
    assert client.started == []


def test_fixture_spawn_vs_real_ticket_named_error(tmp_path):
    """夹具开票遇真票：具名报错（检查名=fixture mark ownership check），零新票。"""
    client = FakeClient([ticket("t261002-01", "RUNNING")])
    res = open_ticket(client, tmp_path, fixture_mark=MARK)
    assert not res["ok"]
    assert "fixture mark ownership check failed" in res["error"]
    assert "t261002-01" in res["error"]
    assert client.started == []


def test_fixture_open_stamps_fixture_sa_and_pointer_payload(tmp_path):
    client = FakeClient([])
    res = open_ticket(client, tmp_path, fixture_mark=MARK)
    assert res["ok"] and res["result"]["fixture"] is True
    st = client.started[0]
    assert st["sa"].get(FIX) == MARK and st["sa"].get(TAKEN)
    ptr = json.loads((tmp_path / "ledger" /
                      ("inspection-%s-%s.ticket" % (INST, PERIOD))).read_text("utf-8"))
    assert ptr.get("fixture") == MARK               # 指针飞行窗内的夹具身份痕


def test_real_spawn_clears_fixture_pointer_and_mints(tmp_path):
    """指针层归属检查：夹具飞行指针不楔死真班——清痕重走铸号，留痕可见。"""
    (tmp_path / "ledger").mkdir(parents=True)
    ppath = tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD))
    ppath.write_text(json.dumps({"ticket_id": "t261002-01", "instance_id": INST,
                                 "period": PERIOD, "project_key": "sandbar",
                                 "supersedes_ticket_id": "", "at": 0.0,
                                 "fixture": MARK}), encoding="utf-8")
    client = FakeClient([ticket("t261002-01", "RUNNING", fx=MARK)])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t261002-02"
    assert any("夹具指针归属检查" in c for c in res["result"]["stale_pointer_cleared"])


# ============================================================ ② 清坑单点

def release(client, tmp_path, mark=MARK, **kw):
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(tmp_path / "ledger")
    (tmp_path / "ledger").mkdir(parents=True, exist_ok=True)
    try:
        base = dict(instance_id=INST, period=PERIOD, fixture_mark=mark)
        base.update(kw)
        return asyncio.run(tick.release_period_slot(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


class CancelableHandle(FakeHandle):
    async def cancel(self):
        wf = self._c.wfs.get(self._tid)
        if wf is None:
            raise RuntimeError("NOT_FOUND: workflow %s not found" % self._tid)
        wf.status.name = "TERMINATED"


class CancelableClient(FakeClient):
    def get_workflow_handle(self, tid):
        return CancelableHandle(self, tid)


def test_release_cancels_marked_ticket_and_clears_pointer(tmp_path):
    """验收②：夹具清坑 → 票终态 + 指针清 → 期槽释放，无占坑残骸。"""
    (tmp_path / "ledger").mkdir(parents=True)
    ppath = tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD))
    ppath.write_text("{}", encoding="utf-8")
    client = CancelableClient([ticket("t261002-01", "RUNNING", fx=MARK)])
    res = release(client, tmp_path)
    assert res["ok"], res
    assert res["released"] == ["t261002-01"] and res["pointer_cleared"] is True
    assert client.wfs["t261002-01"].status.name == "TERMINATED"
    assert not ppath.exists()
    # 终态后再查期槽：freed（真班下次起票由 KI-114 自动放行重开）
    face = asyncio.run(tick.describe_period_slot(client, INST, PERIOD))
    assert face["ok"] and face["slot_state"] == "freed"


def test_release_missing_mark_named_error(tmp_path):
    client = CancelableClient([ticket("t261002-01", "RUNNING", fx=MARK)])
    res = release(client, tmp_path, mark="")
    assert not res["ok"]
    assert "fixture mark missing check failed" in res["error"]
    assert client.wfs["t261002-01"].status.name == "RUNNING"   # 票保持原状


def test_release_double_clean_named_error(tmp_path):
    client = CancelableClient([])
    res = release(client, tmp_path)
    assert not res["ok"]
    assert "double-clean check failed" in res["error"]
    assert "已释放" in res["error"]


def test_release_already_freed_ticket_is_double_clean(tmp_path):
    """夹具票已终态（清过坑）再 release：同样是 double-clean 具名报错。"""
    client = CancelableClient([ticket("t261002-01", "TERMINATED", fx=MARK)])
    res = release(client, tmp_path)
    assert not res["ok"]
    assert "double-clean check failed" in res["error"]


def test_release_real_ticket_ownership_refusal(tmp_path):
    """越权清坑：真班（无章）活票不可被夹具清坑面释放——具名拒绝。"""
    client = CancelableClient([ticket("t261002-01", "RUNNING")])
    res = release(client, tmp_path)
    assert not res["ok"]
    assert "ownership mismatch check failed" in res["error"]
    assert client.wfs["t261002-01"].status.name == "RUNNING"


def test_release_malformed_period_named_error(tmp_path):
    res = release(FakeClient([]), tmp_path, period="2026-10-02")
    assert not res["ok"]
    assert "period shape check failed" in res["error"]


def test_release_cancel_failure_named_error(tmp_path):
    class NoCancelHandle(FakeHandle):
        async def cancel(self):
            raise RuntimeError("RPC unavailable: permission denied")
    class NoCancelClient(FakeClient):
        def get_workflow_handle(self, tid):
            return NoCancelHandle(self, tid)
    client = NoCancelClient([ticket("t261002-01", "RUNNING", fx=MARK)])
    res = release(client, tmp_path)
    assert not res["ok"] and "cancel 票" in res["error"]
    assert "RuntimeError" in res["error"]


# ============================================================ ③ 回执点名 + ④ 期槽诚实面

def test_dedup_receipt_names_unstamped_ticket_as_unknown(tmp_path):
    """事故票形态（t261002-01：无夹具章也无占坑章——但作为**真班**占坑者）：
    deduped 回执点名票号 + slot_taken_at=unknown（诚实，绝不伪造时刻）。"""
    client = FakeClient([ticket("t261002-01", "COMPLETED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    r = res["result"]
    assert r["ticket_id"] == "t261002-01"
    assert r["slot_taken_at"] == "unknown"          # 无章≠编一个时刻


def test_describe_period_slot_faces(tmp_path):
    # 空
    face = asyncio.run(tick.describe_period_slot(FakeClient([]), INST, PERIOD))
    assert face["ok"] and face["slot_state"] == "empty"
    # 活夹具票占坑
    face = asyncio.run(tick.describe_period_slot(
        FakeClient([ticket("t261002-01", "RUNNING", fx=MARK,
                           taken="2026-09-26T21:30:00+00:00")]), INST, PERIOD))
    assert face["ok"] and face["slot_state"] == "live"
    assert face["ticket_id"] == "t261002-01" and face["fixture_mark"] == MARK
    assert face["slot_taken_at"] == "2026-09-26T21:30:00+00:00"
    # 无章老票（事故票形态）：照实 unknown，绝不伪造
    face = asyncio.run(tick.describe_period_slot(
        FakeClient([ticket("t261002-01", "RUNNING")]), INST, PERIOD))
    assert face["ok"] and face["fixture_mark"] == ""
    assert face["slot_taken_at"] == "unknown"
    # 具名失败：期号形状
    face = asyncio.run(tick.describe_period_slot(FakeClient([]), INST, "bad-period"))
    assert not face["ok"] and "期号形状非法" in face["error"]
    # 具名失败：缺 instance
    face = asyncio.run(tick.describe_period_slot(FakeClient([]), "", PERIOD))
    assert not face["ok"] and "instance" in face["error"]


def test_describe_period_slot_multi_live_named_error(tmp_path):
    client = FakeClient([ticket("t261002-01", "RUNNING"),
                         ticket("t261002-02", "RUNNING")])
    face = asyncio.run(tick.describe_period_slot(client, INST, PERIOD))
    assert not face["ok"] and "多张**活**同期票" in face["error"]


def test_spawn_receipt_source_lock_names_ticket_id():
    """源码锁：spawn 回执必须读 `ticket_id`（KI-191 根因=`ticket` 键错读打 `?`）。"""
    src = (POC / "inspection_flow.py").read_text("utf-8")
    assert 'result.get("ticket_id")' in src
    assert 'result.get("ticket") or "?"' not in src
    assert "slot_taken_at" in src and "skipped_fixture_tickets" in src


def test_malformed_pointer_fixture_payload_does_not_crash_mint(tmp_path):
    """畸形输入：指针 payload 的 fixture 字段非串（坏 JSON 之外的形状漂移）——
    真班路径按「无章」容忍（不 crash、不误判），夹具路径按归属不符具名报错。"""
    (tmp_path / "ledger").mkdir(parents=True)
    ppath = tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD))
    ppath.write_text(json.dumps({"ticket_id": "t261002-01", "instance_id": INST,
                                 "period": PERIOD, "project_key": "sandbar",
                                 "supersedes_ticket_id": "", "at": 0.0,
                                 "fixture": 12345}), encoding="utf-8")
    # 真班：SA 层先命中无章活票（真班占坑）→ 正确 deduped（指针层不被触达）；
    # 占坑章缺失 → slot_taken_at=unknown（诚实）
    client = FakeClient([ticket("t261002-01", "RUNNING")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["ticket_id"] == "t261002-01"
    assert res["result"]["slot_taken_at"] == "unknown"
