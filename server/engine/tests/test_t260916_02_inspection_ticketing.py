"""t260916-02 票号 t 形化 + 显式去重单测（inspection_ticketing 全纯面，FakeClient 注入）。

覆盖口径（=plan-t260916-02.md §2.2/S2）：
  A. 铸号纯面：期号→前缀（t<YYMMDD>）、序号判定（shared.next_ticket_seq_from_ids 单点）、
     **跨类型**扫描（工单+巡检同天共享序号空间——修 _next_seq_v2 只扫工单店的现成缺陷）。
  B. 去重三路：SA 快路径 deduped（不建指针不 start）；指针三态（有效→describe 验票；
     陈旧超窗自动清+留痕；窗内显式报错；畸形同规则；SA 不一致=配置事故不自动清）；
     AlreadyStarted 归属判定（本（实例,期）=deduped；外来撞号=NN+1 让位重试≤5）。
  C. 失败路径：非 dedup 失败删自建指针；重试耗尽显式报错；畸形输入 fail-closed。
  D. 查询面：resolve_period_ticket_id（SA 命中 / legacy 只读探测 / 查无此票）；
     SA 未注册=显式报错点名注册步（R3）；STARTS_WITH 被拒=type_only_fallback 降级（R2）。
  E. 指针年龄基准=st_mtime（R4：过期指针注入统一 os.utime 操作 mtime）。

UT 全程禁网络/真 Temporal；conftest 只加 sys.path。
运行：server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260916_02_inspection_ticketing.py -q
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_ticketing as tick  # noqa: E402
import shared  # noqa: E402

INS = shared.INSPECTION_INSTANCE_SA_NAME
PER = shared.INSPECTION_PERIOD_SA_NAME


# ============================================================ FakeClient（最小语义面）

class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeHandle:
    def __init__(self, client, tid):
        self._c = client
        self._tid = tid
        self.first_execution_run_id = "run-%s" % tid

    async def describe(self):
        wf = self._c.wfs.get(self._tid)
        if wf is None:
            raise RuntimeError("NOT_FOUND: workflow %s not found" % self._tid)
        return FakeDesc(wf)

    async def query(self, name):
        wf = self._c.wfs.get(self._tid)
        return dict(wf.snap) if wf and wf.snap else {}


class FakeDesc:
    def __init__(self, wf):
        self.status = FakeStatus(wf.status)
        # dict-of-lists 形态（_sa_pairs 的 legacy 分支；真 SDK 为 pair 迭代——两条都容）
        self.typed_search_attributes = {k: [v] for k, v in (wf.sa or {}).items()}


class FakeWf:
    def __init__(self, tid, status="RUNNING", sa=None, wf_type="InspectionPeriodicWorkflow",
                 snap=None):
        self.id = tid
        self.status = FakeStatus(status)
        self.sa = dict(sa or {})
        self.workflow_type = wf_type
        self.snap = snap


class FakeClient:
    """最小 Temporal 客户端桩：list_workflows 按 query 形态建模（SA dedup / STARTS_WITH /
    纯类型扫）；reject_starts_with 注入 R2 降级分支；sa_unregistered 注入 R3 报错分支。"""

    def __init__(self, wfs=None, reject_starts_with=False, sa_unregistered=False):
        self.wfs = {w.id: w for w in (wfs or [])}
        self.reject_starts_with = reject_starts_with
        self.sa_unregistered = sa_unregistered
        self.started: list = []
        self.queries: list = []

    def get_workflow_handle(self, tid):
        return FakeHandle(self, tid)

    async def list_workflows(self, query):
        self.queries.append(query)
        if self.reject_starts_with and "STARTS_WITH" in query:
            raise ValueError("could not parse query: unsupported operator STARTS_WITH")
        if self.sa_unregistered and INS in query:
            raise RuntimeError("unknown search attribute InspectionInstance")
        if "STARTS_WITH" in query:
            import re as _re
            m = _re.search(r'STARTS_WITH "([^"]*)"', query)
            prefix = m.group(1)
            for w in self.wfs.values():
                if w.id.startswith(prefix):
                    yield w
            return
        if 'WorkflowType="InspectionPeriodicWorkflow"' in query:
            import re as _re
            inst_m = _re.search(r'%s="([^"]*)"' % INS, query)
            per_m = _re.search(r'%s="([^"]*)"' % PER, query)
            for w in self.wfs.values():
                if w.workflow_type != "InspectionPeriodicWorkflow":
                    continue
                if inst_m and w.sa.get(INS) != inst_m.group(1):
                    continue
                if per_m and w.sa.get(PER) != per_m.group(1):
                    continue
                yield w
            return
        for w in self.wfs.values():
            yield w

    async def start_workflow(self, wf_cls, payload, id=None, task_queue=None,
                             search_attributes=None, **kw):
        sa = {}
        try:
            for p in (search_attributes or []):
                sa[p.key.name] = p.value
        except TypeError:
            sa = dict(search_attributes or {})
        if id in self.wfs and getattr(self.wfs[id].status, "name", "") == "RUNNING":
            from temporalio.exceptions import WorkflowAlreadyStartedError
            raise WorkflowAlreadyStartedError(id, "InspectionPeriodicWorkflow", run_id="run-1")
        wf = FakeWf(id, "RUNNING", sa)
        self.wfs[id] = wf
        self.started.append({"id": id, "sa": sa, "payload": payload, "queue": task_queue})
        return FakeHandle(self, id)


def run(coro):
    return asyncio.run(coro)


def open_ticket(client, tmp_path, **kw):
    """open_period_ticket 的固定注入面：ledger 目录=夹具 tmp（接 SANDBAR_INSPECTION_DIR
    覆盖链，通过 open 内部 env 读取——这里用 monkeypatch 风格直接 setenv/restore）。"""
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(tmp_path / "ledger")
    try:
        base = dict(instance_id="integration-tests", period="20260916",
                    project_key="sandbar", repo_root="/repo", scan_face="test",
                    decl_path="", task_queue="tq")
        base.update(kw)
        return run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def pointer_of(tmp_path, instance="integration-tests", period="20260916"):
    return tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (instance, period))


def age_pointer(path, seconds):
    """R4：指针年龄基准=st_mtime——测试注入统一 os.utime 操作 mtime。"""
    past = time.time() - seconds
    os.utime(path, (past, past))


# ============================================================ A. 铸号纯面

def test_ticket_prefix_from_period_shapes():
    assert tick.ticket_prefix_from_period("20260916") == "t260916"
    assert tick.ticket_prefix_from_period("20260916-3") == "t260916"   # 桶段期取日期段
    for bad in ("", "2026-09-16", "2026091", "20260916-0"):
        with pytest.raises(tick.TicketingError):
            tick.ticket_prefix_from_period(bad)


def test_next_seq_core_counts_across_families():
    # 跨族同天序号共享：dev-lane 工单号与巡检票号都进 max+1（修 _next_seq_v2 缺陷的核心）
    ids = ["t260916-01", "t260916-07", "t260916-99", "inspection-x-20260916",
           "t260915-01", "t260916-abc"]
    assert shared.next_ticket_seq_from_ids("t260916", ids) == 100
    assert tick.ticket_id_from_seq("t260916", 100) == "t260916-100"


def test_scan_prefix_cross_type_and_fallback():
    async def scenario():
        client = FakeClient([FakeWf("t260916-01", sa={"ProjectKey": "p"}),
                             FakeWf("t260916-02", wf_type="InspectionPeriodicWorkflow"),
                             FakeWf("t260915-99"),
                             FakeWf("inspection-x-20260916")])
        ids, mode = await tick.scan_prefix_ticket_ids(client, "t260916")
        assert ids == ["t260916-01", "t260916-02"] and mode == "starts_with"
        client2 = FakeClient([FakeWf("t260916-01"), FakeWf("inspection-x-20260916")],
                             reject_starts_with=True)
        ids2, mode2 = await tick.scan_prefix_ticket_ids(client2, "t260916")
        assert ids2 == ["t260916-01"] and mode2 == "type_only_fallback"   # R2 降级分支
        client3 = FakeClient()
        async def dead(query):
            raise RuntimeError("visibility store down")
            yield  # pragma: no cover——unreachable，只为成为 async generator
        client3.list_workflows = dead
        with pytest.raises(tick.TicketingError):
            await tick.scan_prefix_ticket_ids(client3, "t260916")   # 两种扫描面都不可用
    asyncio.run(scenario())


# ============================================================ B. 去重三路

def test_open_dedup_via_sa_query_fast_path(tmp_path):
    client = FakeClient([FakeWf("t260916-03", sa={INS: "integration-tests",
                                                  PER: "20260916"})])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["ticket_id"] == "t260916-03"
    assert res["result"]["dedup_source"] == "sa_query"
    assert client.started == []                       # 快路径绝不重复起票
    assert not pointer_of(tmp_path).exists()          # 快路径不落指针


def test_open_multi_same_period_tickets_named_not_guessed(tmp_path):
    wfs = [FakeWf("t260916-01", sa={INS: "integration-tests", PER: "20260916"}),
           FakeWf("t260916-02", sa={INS: "integration-tests", PER: "20260916"})]
    res = open_ticket(FakeClient(wfs), tmp_path)
    assert not res["ok"] and "t260916-01" in res["error"] and "t260916-02" in res["error"]


def test_open_happy_path_mints_and_stamps_sa(tmp_path):
    client = FakeClient([FakeWf("t260916-01", wf_type="DevLaneWorkflow")])   # 同日已有工单
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-02"           # 工单占 01，巡检取 02
    assert res["result"]["scan_mode"] == "starts_with"
    st = client.started[0]
    assert st["sa"].get(INS) == "integration-tests" and st["sa"].get(PER) == "20260916"
    assert st["sa"].get("ProjectKey") == "sandbar"
    assert st["payload"].instance_id == "integration-tests" and st["payload"].period == "20260916"


def test_open_again_after_start_dedups_via_sa(tmp_path):
    client = FakeClient()
    first = open_ticket(client, tmp_path)
    assert first["ok"] and first["result"]["triggered"] is True
    second = open_ticket(client, tmp_path)
    assert second["ok"] and second["result"]["deduped"] is True
    assert second["result"]["dedup_source"] == "sa_query"
    assert len(client.started) == 1


def test_open_dedup_via_stale_pointer_cleared_with_trace(tmp_path):
    """陈旧指针（票不在、超窗）→ 自动清+留痕后照常开票（绝不永久楔死期号）。"""
    client = FakeClient()
    ppath = pointer_of(tmp_path)
    ppath.parent.mkdir(parents=True)
    ppath.write_text(json.dumps({"ticket_id": "t260916-01", "instance_id": "integration-tests",
                                 "period": "20260916", "project_key": "sandbar",
                                 "at": 1.0}), encoding="utf-8")
    age_pointer(ppath, tick.CLAIM_GRACE_SEC * 10)
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["stale_pointer_cleared"], "自动清必须留痕（可观测）"
    assert "t260916-01" in res["result"]["stale_pointer_cleared"][0]


def test_open_fresh_pointer_in_grace_window_errors_without_touching(tmp_path):
    """窗内「指针在票不在」=并发飞行中 → 显式报错、不动指针、不开票（不误杀并发）。"""
    client = FakeClient()
    ppath = pointer_of(tmp_path)
    ppath.parent.mkdir(parents=True)
    ppath.write_text(json.dumps({"ticket_id": "t260916-01", "at": 1.0}), encoding="utf-8")
    res = open_ticket(client, tmp_path)
    assert not res["ok"] and "飞行窗" in res["error"]
    assert ppath.exists() and client.started == []


def test_open_corrupt_pointer_old_cleared_fresh_named(tmp_path):
    client = FakeClient()
    ppath = pointer_of(tmp_path)
    ppath.parent.mkdir(parents=True)
    ppath.write_text('{"ticket_id": "t260916-01"', encoding="utf-8")   # 半截 JSON
    age_pointer(ppath, tick.CLAIM_GRACE_SEC * 10)                      # 超窗=可自动清
    res_old = open_ticket(client, tmp_path)
    assert res_old["ok"] and "畸形指针" in res_old["result"]["stale_pointer_cleared"][0]
    client.wfs.clear()                     # 清掉已起的票，隔离后续分段的快路径
    client.started.clear()
    ppath.write_text("garbage", encoding="utf-8")                      # 新鲜畸形
    res_fresh = open_ticket(client, tmp_path)
    assert not res_fresh["ok"] and "畸形" in res_fresh["error"]
    # 空文件同畸形
    ppath.write_text("", encoding="utf-8")
    res_empty = open_ticket(client, tmp_path)
    assert not res_empty["ok"]


def test_open_pointer_ticket_identity_mismatch_is_config_incident(tmp_path):
    """指针指向的票存在但 SA 与指针不一致 → 配置事故显式报错，**不自动清指针**。"""
    client = FakeClient([FakeWf("t260916-01", sa={INS: "other-instance", PER: "20260916"})])
    ppath = pointer_of(tmp_path)
    ppath.parent.mkdir(parents=True)
    ppath.write_text(json.dumps({"ticket_id": "t260916-01", "instance_id": "integration-tests",
                                 "period": "20260916"}), encoding="utf-8")
    res = open_ticket(client, tmp_path)
    assert not res["ok"] and "不一致" in res["error"] and "other-instance" in res["error"]
    assert ppath.exists(), "配置事故不自动清（防掩盖第二写入方）"


def test_open_pointer_identity_match_dedups(tmp_path):
    # 指针指向的票 SA=空（t260916-02 之前的旧票无实例章）：describe 证在+指针本引擎
    # 写入 → 可信 dedup（绝不误判成「SA 不一致」配置事故）
    client = FakeClient([FakeWf("t260916-05")])
    ppath = pointer_of(tmp_path)
    ppath.parent.mkdir(parents=True)
    ppath.write_text(json.dumps({"ticket_id": "t260916-05", "instance_id": "integration-tests",
                                 "period": "20260916"}), encoding="utf-8")
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["ticket_id"] == "t260916-05"
    assert res["result"]["dedup_source"] == "pointer"
    assert client.started == []


def test_open_already_started_same_identity_dedups_and_clears_pointer(tmp_path):
    """并发窗（ES 索引延迟模拟）：SA 查询与前缀扫描都看不见既有票，start 撞
    AlreadyStarted 且归属=本（实例,期）→ deduped，自建指针收尾清。"""
    class SplitClient(FakeClient):
        async def list_workflows(self, query):
            if INS in query or "STARTS_WITH" in query:   # 快路径/扫描全瞎（ES 延迟）
                return
            async for w in super().list_workflows(query):
                yield w

    client = SplitClient([FakeWf("t260916-01", sa={INS: "integration-tests",
                                                   PER: "20260916"})])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["dedup_source"] == "already_started"
    assert res["result"]["ticket_id"] == "t260916-01"
    assert not pointer_of(tmp_path).exists()      # deduped 收尾清自建指针


def test_open_already_started_foreign_owner_yields_and_retries(tmp_path):
    """外来撞号（他人同日同号）→ NN+1 让位；同日耗尽=显式报错点名候选。"""
    class CollideOnce(FakeClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.collided = 0

        async def start_workflow(self, *a, **k):
            if self.collided < 2 and k.get("id") in ("t260916-02", "t260916-03"):
                self.collided += 1
                self.wfs[k["id"]] = FakeWf(k["id"], sa={INS: "someone-else", PER: "20260901"})
                from temporalio.exceptions import WorkflowAlreadyStartedError
                raise WorkflowAlreadyStartedError(k["id"], "InspectionPeriodicWorkflow", run_id="run-x")
            return await super().start_workflow(*a, **k)

    res = open_ticket(CollideOnce([FakeWf("t260916-01", sa={INS: "someone-else",
                                                           PER: "20260901"})]), tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"    # 02/03 让位后落 04
    tick.clear_pointer(pointer_of(tmp_path))             # 成功 start 的指针按设计留存——下一段隔离

    class CollideAll(FakeClient):
        async def start_workflow(self, *a, **k):
            self.wfs[k["id"]] = FakeWf(k["id"], sa={INS: "someone-else", PER: "20260901"})
            from temporalio.exceptions import WorkflowAlreadyStartedError
            raise WorkflowAlreadyStartedError(k["id"], "InspectionPeriodicWorkflow", run_id="run-x")

    res2 = open_ticket(CollideAll(), tmp_path)
    assert not res2["ok"] and "耗尽" in res2["error"] and str(tick.MAX_ALLOC_RETRIES) in res2["error"]


def test_open_start_failure_clears_own_pointer(tmp_path):
    class BoomClient(FakeClient):
        async def start_workflow(self, *a, **k):
            raise RuntimeError("queue unavailable")
    res = open_ticket(BoomClient(), tmp_path)
    assert not res["ok"] and "已清自建指针" in res["error"]
    assert not pointer_of(tmp_path).exists()
    # 重试同期不受残指针影响（可再开）
    res2 = open_ticket(FakeClient(), tmp_path)
    assert res2["ok"] and res2["result"]["triggered"] is True


def test_open_sa_unregistered_named_with_registration_guidance(tmp_path):
    """R3：SA 未注册=显式报错归因到注册步，不谎报「查无此票」。"""
    res = open_ticket(FakeClient(sa_unregistered=True), tmp_path)
    assert not res["ok"]
    assert "InspectionInstance" in res["error"] and "search-attribute" in res["error"]


def test_open_malformed_inputs_fail_closed(tmp_path):
    res1 = open_ticket(FakeClient(), tmp_path, period="bad")
    assert not res1["ok"] and "期号形状非法" in res1["error"]
    res2 = open_ticket(FakeClient(), tmp_path, instance_id="")
    assert not res2["ok"] and "instance_id" in res2["error"]


# ============================================================ D. 查询面（sign/ticket/describe 的底座）

def test_resolve_period_ticket_id_three_ways(tmp_path):
    client = FakeClient([FakeWf("t260916-01", sa={INS: "integration-tests", PER: "20260916"})])
    hit = run(tick.resolve_period_ticket_id(client, "integration-tests", "20260916"))
    assert hit["ok"] and hit["ticket_id"] == "t260916-01" and hit["source"] == "sa"
    # legacy 只读探测（SA 查无但旧形票在——过渡窗在途票）
    legacy_client = FakeClient([FakeWf("inspection-integration-tests-20260901")])
    legacy = run(tick.resolve_period_ticket_id(legacy_client, "integration-tests", "20260901"))
    assert legacy["ok"] and legacy["ticket_id"] == "inspection-integration-tests-20260901"
    assert legacy["source"] == "legacy_id"
    # 查无此票≠连不上（报错点名两面都查过）
    miss = run(tick.resolve_period_ticket_id(FakeClient(), "integration-tests", "20260916"))
    assert not miss["ok"] and "查无" in miss["error"]
    # SA 未注册 → 注册步归因
    unreg = run(tick.resolve_period_ticket_id(FakeClient(sa_unregistered=True),
                                              "integration-tests", "20260916"))
    assert not unreg["ok"] and "search-attribute" in unreg["error"]


def test_describe_period_identity_transient_vs_not_found():
    client = FakeClient([FakeWf("t260916-01", sa={INS: "i", PER: "p"})])

    class JitterClient(FakeClient):
        async def list_workflows(self, q):
            if INS in q:
                return
            async for w in super().list_workflows(q):
                yield w

        def get_workflow_handle(self, tid):
            class H:
                async def describe(self):
                    raise TimeoutError("deadline exceeded")
            return H()
    res = open_ticket(JitterClient([FakeWf("t260916-01", sa={INS: "integration-tests",
                                                             PER: "20260916"})]),
                      Path(os.environ.get("TMPDIR", "/tmp")) / "t01")
    assert not res["ok"] and "暂不可判" in res["error"]   # 瞬态显式报错，绝不猜 dedup


# ============================================================ E. 指针读写纯面（畸形输入）

def test_pointer_read_state_malformed_forms(tmp_path):
    p = tmp_path / "x.ticket"
    p.write_text('{"ticket_id": "t1"}', encoding="utf-8")
    kind, data = tick.read_pointer_state(p)
    assert kind == "valid" and data["ticket_id"] == "t1"
    for bad in ('', 'nope', '[1,2]', '{"period": "x"}'):
        p.write_text(bad, encoding="utf-8")
        kind, _ = tick.read_pointer_state(p)
        assert kind == "corrupt"


def test_claim_pointer_is_atomic_and_idempotent_visible(tmp_path):
    p = tmp_path / "inspection-a-20260916.ticket"
    state, _ = tick.claim_pointer(p, "a", "20260916", "t260916-01", "proj")
    assert state == "claimed"
    state2, _ = tick.claim_pointer(p, "a", "20260916", "t260916-02", "proj")
    assert state2 == "exists"
    assert tick.pointer_age(p) < 5.0                 # R4：基准=mtime
    assert tick.clear_pointer(p) is True
    assert tick.clear_pointer(p) is False            # 幂等
