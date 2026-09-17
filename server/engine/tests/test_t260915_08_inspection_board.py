"""t260915-08 工单板收录巡检票 单测（方案 v2 S1/S2 对应 L1 层）。

覆盖口径（=plan-t260915-08.md §2 单测清单 + review 执行项1）：
  A. `_inspection_instance_of` 票号解析真值表（bucket 期号/实例含连字符数字/畸形）。
  B. `_row_from_inspection_face` 行分支真值表：
     - awaiting-human 人门行（face 在而 human_gate 缺=签字前常态，待签判定只读
       stage_state——打回4/实证18）；
     - 已签回执行（human_gate 透传）；
     - 畸形 face 逐字段降级（不抛不编造）；
     - **降级闭合行 status≠'closed'**（review 执行项1：deriveTicketState 首判
       closed→done 会被收口折叠吃掉，错误行必须保持可见；UI 侧四态腿在
       workbench tests/t260915-08-inspection-face.mjs 补）。
  C. `cmd_ticket_list` 黑盒（FakeClient，镜 t260901-23/t02 注入面——取舍清单见方案
     §3.5 镜A）：白名单挡僵尸/R9 默认列表行集合零变化/R8 闭合窗口过滤/声明降级
     显式标记/RUNNING 与窗内闭合两条降级行路径/kind 白名单/type_filter 单点。
  D. `cmd_ticket_query` 巡检分支：envelope engine=ENGINE_V2（坑A）+ meta 组装面
     （gate_id/face 可达/human_gate 缺键=None）+ dev-lane 快照零变化。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path；声明白名单一律注入，
不读真 inspection.yaml——真实声明面由 exclusive 场景守）。
运行：server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260915_08_inspection_board.py -q
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import client as client_mod  # noqa: E402
from shared import ENGINE_V2  # noqa: E402

# 重试延迟注入归零（t02 同款配置面）：降级路径毫秒级跑完，生产默认不动。
client_mod.QUERY_RETRY_BASE_DELAY = 0.0
client_mod.QUERY_RETRY_JITTER = 0.0

TASK_QUEUE = client_mod.TASK_QUEUE

# dev-lane 行键集（parity 钉死用；与 _row_from_meta 产出逐键一致，t260912-03 形状）
DEVLANE_ROW_KEYS = {
    "id", "project", "epic", "role", "status", "title", "workflow", "proposal_id",
    "stage", "stage_state", "paused", "paused_phase", "handoff_count", "pending_count",
    "worktree", "workspace", "created", "updated", "updated_ts", "engine",
    "exec_status", "authz_active", "close_ts",
}


# ---------------------------------------------------------------- fakes（镜 t02 注入面）

class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeSAKeys:
    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        return self.kv.get(str(key))


class FakeSA:
    def __init__(self, kv):
        self.typed_search_attributes = FakeSAKeys(kv)


class FakeListWf:
    def __init__(self, tid, status_name, task_queue, kv, close_time=None, start_time=None,
                 workflow_type="DevLaneWorkflow"):
        self.id = tid
        self.status = FakeStatus(status_name)
        self.task_queue = task_queue
        self.close_time = close_time
        self.start_time = start_time
        self.workflow_type = workflow_type
        self._sa = FakeSA(kv)

    @property
    def typed_search_attributes(self):
        return self._sa.typed_search_attributes


class FakeHandle:
    def __init__(self, script=None, snapshot=None, result_value=None):
        self.script = list(script or [])
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.queries = 0
        self.result_run_id = None
        self.run_id = "run-stub"

    async def query(self, name):
        self.queries += 1
        act = self.script.pop(0) if self.script else "ok"
        if act in ("timeout", "rpc_error"):
            raise asyncio.TimeoutError("stub timeout") if act == "timeout" \
                else RuntimeError("stub rpc")
        return self.snapshot

    async def result(self):
        if self.result_value is not None:
            return self.result_value
        raise RuntimeError("stub no result")


class FakeDesc:
    """describe 桩：无 raw_description → _pulse_from_desc 软降级 None（其自身纪律）。"""

    def __init__(self, status_name="RUNNING"):
        self.status = FakeStatus(status_name)
        self.typed_search_attributes = FakeSAKeys({})
        self.result_run_id = None
        self.run_id = "run-stub"

    async def describe(self):
        return self


class FakeClient:
    def __init__(self, wfs, handles, reject_starts_with=False):
        self._wfs = wfs
        self._handles = handles
        self.reject_starts_with = reject_starts_with
        self.filters: list[str] = []

    def get_workflow_handle(self, tid):
        return self._handles.get(tid) or FakeHandle(snapshot={})

    async def list_workflows(self, filter_str):
        """建模服务端可见性过滤的最小语义（t02 桩的已知缺口——其 fixture 只喂同型
        workflow 所以不需要；本票 R9 断言「缺省列表不得混入巡检行」，桩必须真按
        WorkflowType 过滤，否则测的是假客户端不是板面）。ProjectKey/EpicCode AND
        段同法substring 匹配 + SA 值比对。
        t260916-02：建模 WorkflowId STARTS_WITH（板面 legacy 腿 + id_prefix 铸号扫描面）；
        reject_starts_with 注入 R2 降级腿（后端拒绝算子）。"""
        self.filters.append(filter_str)
        import re as _re
        starts_m = _re.search(r'STARTS_WITH "([^"]*)"', filter_str)
        if starts_m:
            if self.reject_starts_with:
                raise ValueError("could not parse query: unsupported operator STARTS_WITH")
            for w in self._wfs:
                if w.id.startswith(starts_m.group(1)):
                    yield w
            return
        proj_m = _re.search(r'AND ProjectKey="([^"]*)"', filter_str)
        epic_m = _re.search(r'AND EpicCode="([^"]*)"', filter_str)
        proj_key = str(_K.for_keyword(client_mod.PROJECT_SA_NAME))
        epic_key = str(_K.for_keyword(client_mod.EPIC_SA_NAME))
        for w in self._wfs:
            if 'WorkflowType="%s"' % getattr(w, "workflow_type", "") not in filter_str:
                continue
            if proj_m and str(w.typed_search_attributes.get(proj_key) or "") != proj_m.group(1):
                continue
            if epic_m and str(w.typed_search_attributes.get(epic_key) or "") != epic_m.group(1):
                continue
            yield w


def _connect_with(wfs, handles):
    client_obj = FakeClient(wfs, handles)

    async def _connect(*a, **k):
        return client_obj

    client_mod._connect = _connect
    return client_obj


def InspWf(tid, status_name, task_queue, kv, **kw):
    """巡检型 workflow 桩（type_filter 语义建模后必须带 WorkflowType 才可见）。"""
    return FakeListWf(tid, status_name, task_queue, kv,
                      workflow_type="InspectionPeriodicWorkflow", **kw)


def run_list(args, wfs, handles):
    client_obj = _connect_with(wfs, handles)

    async def runner():
        return await client_mod.cmd_ticket_list(dict(args))

    return asyncio.run(runner()), client_obj


def run_query(tid, handle):
    _connect_with([], {tid: handle})

    async def runner():
        return await client_mod.cmd_ticket_query({"ticket_id": tid})

    return asyncio.run(runner())


def tickets_of(res):
    return ((res or {}).get("result") or {}).get("tickets") or []


def row_of(res, tid):
    for r in tickets_of(res):
        if r.get("id") == tid:
            return r
    return None


_K = client_mod.SearchAttributeKey
SA_EMPTY = {}
SA_FOO = {str(_K.for_keyword(client_mod.PROJECT_SA_NAME)): "foo"}


def inspection_snap(stage="close", stage_state="awaiting-human", status="running",
                    face=None, gate_error=""):
    return {
        "id": "inspection-x", "kind": "inspection", "template": "inspection-lite",
        "stage": stage, "stage_state": stage_state, "status": status,
        "decision": "", "gate_error": gate_error,
        "face": face if face is not None else {
            "ticket_id": "inspection-integration-tests-20260915",
            "kind": "inspection", "instance_id": "integration-tests",
            "period": "20260915", "heartbeat": True,
            "summary": {"high": 1, "med": 2, "low": 0},
            "findings": [
                {"id": "f1", "severity": "high", "scan": "test", "subject": "s1"},
                {"id": "f2", "severity": "med", "scan": "test", "subject": "s2"},
                {"id": "f3", "severity": "med", "scan": "doc", "subject": "s3"},
            ],
            "suggested_fix_tickets": [{"template": "dev-lane", "title": "修:x"}],
            "report_path": "/repo/out/inspection/inspection-integration-tests-20260915.json",
            # 注意：无 human_gate 键=签字前常态（实证18），是本 UT 的钉死对象之一
        },
        "timeline": [{"at": "2026-09-15T07:31:00", "stage": "close",
                      "state": "awaiting-human", "reason": "人审"}],
    }


# ---------------------------------------------- C2. t260917-02 修复②：不可辨/同期同注/R6

def test_unresolved_running_visible_and_closed_dropped(monkeypatch):
    """修复②两态：不可辨 RUNNING 降级可见（identity_note+kept_unresolved 计数）；
    不可辨 COMPLETED 仍不上板（僵尸纪律半边不动，dropped_unresolved 计数）。"""
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    now = time.time()
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    wfs = [
        InspWf("inspection-integration-tests-period-2026-09-16T23:30:00Z", "RUNNING",
               TASK_QUEUE, SA_EMPTY, start_time=start),   # 不可辨在跑（服务端后缀形 id）
        InspWf("inspection-nobody-period-2026-09-10T00:00:00Z", "COMPLETED", TASK_QUEUE, SA_EMPTY,
               close_time=datetime.fromtimestamp(now - 60, tz=timezone.utc),
               start_time=start),                          # 不可辨已闭合（僵尸残件）
    ]
    handles = {"inspection-integration-tests-period-2026-09-16T23:30:00Z":
               FakeHandle(snapshot=inspection_snap(
                   face={"ticket_id": "inspection-integration-tests-period-2026-09-16T23:30:00Z",
                         "kind": "inspection", "instance_id": "integration-tests",
                         "period": "20260916", "summary": {}, "findings": []}))}
    res, _ = run_list({"kind": "inspection"}, wfs, handles)
    ids = [r["id"] for r in tickets_of(res)]
    assert "inspection-integration-tests-period-2026-09-16T23:30:00Z" in ids   # 在跑可见
    assert "inspection-nobody-period-2026-09-10T00:00:00Z" not in ids           # 闭合不复活
    info = res["result"]["inspection_filter"]
    assert info["kept_unresolved"] == 1 and info["dropped_unresolved"] == 1
    row = row_of(res, "inspection-integration-tests-period-2026-09-16T23:30:00Z")
    assert row["awaiting_gate"] is True                       # 真快照行：等人状态可读
    assert "疑似" in row["identity_note"] and "describe" in row["identity_note"]


def test_same_period_open_row_annotated_with_closed(monkeypatch):
    """同期 closed+awaiting-human 并存：双行都在板，open 行带 same_period_closed 注；
    异期 closed 行不误注（生产 260916 实况的板面等价形态）。"""
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    now = time.time()
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    sa_ip = {str(_K.for_keyword(client_mod.INSPECTION_INSTANCE_SA_NAME)): "integration-tests",
             str(_K.for_keyword(client_mod.INSPECTION_PERIOD_SA_NAME)): "20260916"}
    sa_ip15 = dict(sa_ip)
    sa_ip15[str(_K.for_keyword(client_mod.INSPECTION_PERIOD_SA_NAME))] = "20260915"
    wfs = [
        InspWf("t260916-13", "COMPLETED", TASK_QUEUE, sa_ip,
               close_time=datetime.fromtimestamp(now - 60, tz=timezone.utc), start_time=start),
        InspWf("t260916-99", "COMPLETED", TASK_QUEUE, sa_ip15,
               close_time=datetime.fromtimestamp(now - 60, tz=timezone.utc), start_time=start),
        InspWf("inspection-integration-tests-period-2026-09-16T23:30:00Z", "RUNNING",
               TASK_QUEUE, SA_EMPTY, start_time=start),
    ]
    handles = {
        "t260916-13": FakeHandle(result_value=inspection_snap(stage="close", stage_state="done",
                                                              status="closed",
                                                              face={"ticket_id": "t260916-13",
                                                                    "instance_id": "integration-tests",
                                                                    "period": "20260916",
                                                                    "summary": {}, "findings": []})),
        "t260916-99": FakeHandle(result_value=inspection_snap(stage="close", stage_state="done",
                                                              status="closed",
                                                              face={"ticket_id": "t260916-99",
                                                                    "instance_id": "integration-tests",
                                                                    "period": "20260915",
                                                                    "summary": {}, "findings": []})),
        "inspection-integration-tests-period-2026-09-16T23:30:00Z":
            FakeHandle(snapshot=inspection_snap(
                face={"ticket_id": "inspection-integration-tests-period-2026-09-16T23:30:00Z",
                      "instance_id": "integration-tests", "period": "20260916",
                      "summary": {}, "findings": []})),
    }
    res, _ = run_list({"kind": "inspection"}, wfs, handles)
    open_row = row_of(res, "inspection-integration-tests-period-2026-09-16T23:30:00Z")
    assert open_row is not None and open_row["awaiting_gate"] is True   # 修复②可见性半边
    assert open_row["same_period_closed"] == "t260916-13"               # 同期注精确到票号
    assert "same_period_closed" not in {k: v for k, v in open_row.items() if v == "t260916-99"}
    closed_row = row_of(res, "t260916-13")
    assert closed_row is not None and closed_row["status"] == "closed"  # closed 行照常在板
    assert "same_period_closed" not in closed_row


def test_partial_sa_truth_table_and_board_legs(monkeypatch):
    """R6：部分 SA 畸形态真值表（解析单点四态）+ 板面腿（有实例无期上板 period 空；
    有期无实例走不可辨在跑腿）。"""
    # —— 解析单点真值表 ——
    def wf_with(kv):
        return FakeListWf("x", "RUNNING", TASK_QUEUE, kv)
    inst_only = {str(_K.for_keyword(client_mod.INSPECTION_INSTANCE_SA_NAME)): "inst-a"}
    per_only = {str(_K.for_keyword(client_mod.INSPECTION_PERIOD_SA_NAME)): "20260916"}
    both = dict(inst_only)
    both[str(_K.for_keyword(client_mod.INSPECTION_PERIOD_SA_NAME))] = "20260916"
    assert client_mod._inspection_instance_period_of(wf_with(inst_only), "x") == ("inst-a", "", "sa")
    assert client_mod._inspection_instance_period_of(wf_with(per_only), "x") == ("", "", "")
    assert client_mod._inspection_instance_period_of(wf_with(both), "x") == ("inst-a", "20260916", "sa")
    # 无 SA 但旧形 id → legacy 只读解析兜底（既有口径回归钉）
    assert client_mod._inspection_instance_period_of(wf_with(SA_EMPTY), "inspection-docs-sync-20260908") \
        == ("docs-sync", "20260908", "legacy_id")
    # —— 板面腿 ——
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("inst-a",), "", []))
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    wfs = [
        InspWf("inspection-a-no-period", "RUNNING", TASK_QUEUE, inst_only, start_time=start),
        InspWf("inspection-period-only-2026-09-16T00:00:00Z", "RUNNING", TASK_QUEUE, per_only, start_time=start),
    ]
    handles = {"inspection-a-no-period": FakeHandle(snapshot=inspection_snap(
        face={"instance_id": "inst-a", "period": "", "summary": {}, "findings": []}))}
    res, _ = run_list({"kind": "inspection"}, wfs, handles)
    r1 = row_of(res, "inspection-a-no-period")
    assert r1 is not None and r1["instance_id"] == "inst-a" and r1["period"] == ""
    r2 = row_of(res, "inspection-period-only-2026-09-16T00:00:00Z")
    assert r2 is not None and "identity_note" in r2          # 有期无实例=不可辨在跑→降级可见
    assert res["result"]["inspection_filter"]["kept_unresolved"] == 1


# ---------------------------------------------------------------- A. 票号解析（legacy 只读）

def test_inspection_instance_of_truth_table():
    """t260916-02：票号 t 形化后旧形解析只剩只读兼容面（返回 (实例,期) 二元组；
    新形 id 反解不出=空对——铸造点已删，本面绝不反过来铸造旧形票号）。"""
    f = client_mod._legacy_inspection_instance_period_of
    assert f("inspection-integration-tests-20260915") == ("integration-tests", "20260915")
    assert f("inspection-my-ci-20260915-2") == ("my-ci", "20260915-2")   # bucket 期号
    assert f("inspection-docs-sync-20260908") == ("docs-sync", "20260908")
    assert f("inspection-foo") == ("", "")                              # 缺期号段
    assert f("inspection--20260915") == ("", "")                        # 空实例段
    assert f("t260915-08") == ("", "")                                  # dev-lane 票号
    assert f("t260916-01") == ("", "")                                  # 新形巡检票号
    assert f("") == ("", "") and f(None) == ("", "")                    # 畸形输入不抛


# ---------------------------------------------------------------- B. 行分支真值表

def test_row_awaiting_gate_derives_from_stage_state_not_human_gate():
    row = client_mod._row_from_inspection_face(
        "inspection-integration-tests-20260915", inspection_snap(), "", "",
        "RUNNING", 0.0, 1760000000)
    # 待签判定=stage_state 推导；face.human_gate 缺键常态下仍判待签（打回4）
    assert row["awaiting_gate"] is True
    assert row["human_gate"] is None
    assert row["kind"] == "inspection" and row["engine"] == client_mod.INSPECTION_ROW_ENGINE
    assert row["engine"] != ENGINE_V2  # 坑B：不得喂 availableOps 的 v2 分支
    assert row["title"] == "巡检 integration-tests · 期 20260915"
    assert row["instance_id"] == "integration-tests" and row["period"] == "20260915"
    assert row["findings"] == {"high": 1, "med": 2, "low": 0, "total": 3}
    assert row["heartbeat"] is True
    assert row["stage"] == "close" and row["stage_state"] == "awaiting-human"
    assert row["paused"] is False and row["authz_active"] == 0
    assert row["created"] == 1760000000 and row["updated_ts"] == 1760000000
    assert row["report_path"].endswith(".json")
    # dev-lane 通用键全在场（UI 组件零特判可跑）
    assert DEVLANE_ROW_KEYS <= set(row)


def test_row_signed_human_gate_passthrough_and_closed_state():
    snap = inspection_snap(stage="close", stage_state="done", status="closed")
    snap["face"]["human_gate"] = {"who": "host", "gate": "inspection-close",
                                  "decision": "approve", "note": ""}
    row = client_mod._row_from_inspection_face("inspection-x", snap, "", "",
                                               "COMPLETED", 1000.0, 5)
    assert row["status"] == "closed" and row["awaiting_gate"] is False
    assert row["human_gate"] == {"who": "host", "gate": "inspection-close",
                                 "decision": "approve", "note": ""}


def test_row_degraded_closed_never_closed_status():
    # review 执行项1：降级闭合行 status 钉死≠'closed'（否则四态 done 被收口折叠吃掉）
    row = client_mod._row_from_inspection_face(
        "inspection-x", {}, "", "", "COMPLETED", 1000.0, 5, degraded=True)
    assert row["status"] != "closed" and row["status"] == "running"
    assert row["stage_state"] == "running" and row["awaiting_gate"] is False
    assert "刷新重试" in row["title"] and row["kind"] == "inspection"
    assert row["findings"] == {"high": 0, "med": 0, "low": 0, "total": 0}


def test_row_malformed_face_degrades_per_field():
    snap = inspection_snap(face={"findings": "not-a-list", "summary": "garbage"})
    row = client_mod._row_from_inspection_face(
        "inspection-weird-20260901", snap, "p", "", "RUNNING", 0.0, 0,
        instance_id="weird", period="20260901", match_via="legacy_id")
    assert row["findings"] == {"high": 0, "med": 0, "low": 0, "total": 0}
    assert row["heartbeat"] is False
    # face 缺 instance/period → 调用方解析值（SA/legacy 只读）兜底（title/字段不裸空）
    assert row["instance_id"] == "weird"
    assert row["title"] == "巡检 weird · 期 20260901"
    assert row["match_via"] == "legacy_id"
    # t260916-02：本函数自身绝不从 id 反解——调用方不给解析值就如实出空（不编造）
    row2 = client_mod._row_from_inspection_face(
        "t260916-01", inspection_snap(face={"findings": "x"}), "", "", "RUNNING", 0.0, 0)
    assert row2["instance_id"] == "" and row2["period"] == ""
    assert row2["match_via"] == "" and row2["legacy_unowned"] is False


def test_row_summary_is_source_of_truth_over_recount():
    # face.summary 是真源：与其和 findings 重计冲突时以 summary 为准（口径写在代码注）
    snap = inspection_snap(face={"findings": [{"severity": "high"}],
                                 "summary": {"high": 7, "med": 0, "low": 0}})
    row = client_mod._row_from_inspection_face("x", snap, "", "", "RUNNING", 0.0, 0)
    assert row["findings"]["high"] == 7
    assert row["findings"]["total"] == 1


# ---------------------------------------------------------------- C. cmd_ticket_list 黑盒

def test_inspection_mode_rows_whitelist_and_closed_window(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("docs-sync", "integration-tests"), "", []))
    now = time.time()
    in_win = now - 3600
    beyond = now - (client_mod.CLOSED_HYDRATE_WINDOW_S + 3600)
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    wfs = [
        InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE, SA_EMPTY,
                   start_time=start),
        InspWf("inspection-docs-sync-20260908", "COMPLETED", TASK_QUEUE, SA_EMPTY,
                   close_time=datetime.fromtimestamp(in_win, tz=timezone.utc),
                   start_time=start),
        InspWf("inspection-integration-tests-20260901", "COMPLETED", TASK_QUEUE,
                   SA_EMPTY,
                   close_time=datetime.fromtimestamp(beyond, tz=timezone.utc),
                   start_time=start),
        InspWf("inspection-test-face-20260910", "RUNNING", TASK_QUEUE, SA_EMPTY,
                   start_time=start),          # 僵尸：声明外（260910 改名失声明）
        InspWf("inspection-mechanism-face-20260910", "RUNNING", TASK_QUEUE, SA_EMPTY,
                   start_time=start),          # 僵尸：declared but enabled=false
        InspWf("inspection-suite-drill-20260913", "RUNNING", TASK_QUEUE, SA_EMPTY,
                   start_time=start),          # 僵尸：从未声明
        InspWf("inspection-foo", "RUNNING", TASK_QUEUE, SA_EMPTY, start_time=start),
    ]
    handles = {"inspection-integration-tests-20260915":
               FakeHandle(snapshot=inspection_snap()),
               "inspection-docs-sync-20260908":
               FakeHandle(result_value=inspection_snap(stage_state="done", status="closed"))}
    res, client_obj = run_list({"kind": "inspection"}, wfs, handles)
    ids = [r["id"] for r in tickets_of(res)]
    assert "inspection-integration-tests-20260915" in ids   # 在册 RUNNING 上板
    assert "inspection-docs-sync-20260908" in ids           # 窗内闭合完整形上板
    assert "inspection-integration-tests-20260901" not in ids  # 超窗闭合不上板（R8）
    assert "inspection-test-face-20260910" not in ids          # 僵尸不上板（R2）
    assert "inspection-mechanism-face-20260910" not in ids
    assert "inspection-suite-drill-20260913" not in ids
    # t260917-02 修复②（契约翻转，R5 对账）：不可辨「且在跑」降级可见——
    # 260917 实况（旧 action 直发的 awaiting-human 票被静默吞）修复后的新契约；
    # 不可辨「且已闭合」仍不上板（下一测试的负腿）。僵尸三行是「可辨但不在册」
    # （t260916-02-board-legacy-three-state 守的口径），本条不碰。
    assert "inspection-foo" in ids
    foo_row = row_of(res, "inspection-foo")
    assert "identity_note" in foo_row and "疑似" in foo_row["identity_note"]
    info = res["result"]["inspection_filter"]
    assert info["kept_unresolved"] == 1 and info["dropped_unresolved"] == 0
    assert info["degraded"] is False and info["enabled_instances"] == [
        "docs-sync", "integration-tests"]
    # t260916-02 双腿：SA 腿（白名单 OR 串）+ legacy 腿（STARTS_WITH 前缀）；类型过滤
    # 仍只拼 INSPECTION_BOARD_TYPES 单点（两腿都含同一 WorkflowType 串）
    assert len(client_obj.filters) == 2
    assert 'WorkflowType="InspectionPeriodicWorkflow"' in client_obj.filters[0]
    assert 'InspectionInstance="docs-sync"' in client_obj.filters[0]
    assert 'InspectionInstance="integration-tests"' in client_obj.filters[0]
    assert 'WorkflowId STARTS_WITH "inspection-"' in client_obj.filters[1]
    assert info["scan_mode"] == "starts_with"
    rows_by_id = {r["id"]: r for r in tickets_of(res)}
    assert rows_by_id["inspection-integration-tests-20260915"]["match_via"] == "legacy_id"
    assert rows_by_id["inspection-integration-tests-20260915"]["legacy_unowned"] is True
    # 窗内闭合行=完整巡检形（非匿名）
    closed = row_of(res, "inspection-docs-sync-20260908")
    assert closed["kind"] == "inspection" and closed["status"] == "closed"
    assert closed["title"].startswith("巡检 ")
    assert closed["awaiting_gate"] is False


def test_inspection_mode_decl_degraded_explicit(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: ((), "DeclError: 声明不可解析", []))
    now = time.time()
    wfs = [InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE,
                      SA_EMPTY)]
    res, _ = run_list({"kind": "inspection"}, wfs, {})
    assert tickets_of(res) == []  # 行全不上板（绝不放全量）
    info = res["result"]["inspection_filter"]
    assert info["degraded"] is True and "DeclError" in info["note"]


def test_inspection_mode_running_query_degraded_row(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    h = FakeHandle(["timeout", "timeout", "timeout"])
    res, _ = run_list(
        {"kind": "inspection"},
        [InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE,
                    SA_EMPTY)],
        {"inspection-integration-tests-20260915": h})
    r = row_of(res, "inspection-integration-tests-20260915")
    assert r is not None and "刷新重试" in r["title"]
    assert r["status"] == "dispatched" and r["stage_state"] == "running"
    assert r["awaiting_gate"] is False and r["kind"] == "inspection"


def test_inspection_mode_closed_result_failure_degraded_visible(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("docs-sync",), "", []))
    now = time.time()
    wf = InspWf("inspection-docs-sync-20260908", "COMPLETED", TASK_QUEUE, SA_EMPTY,
                    close_time=datetime.fromtimestamp(now - 60, tz=timezone.utc))
    res, _ = run_list({"kind": "inspection"}, [wf], {})  # handle 缺 → result() 必败
    r = row_of(res, "inspection-docs-sync-20260908")
    assert r is not None, "窗内闭合行读取失败必须显式在板（不消失不匿名）"
    assert r["status"] != "closed" and r["status"] == "running"   # review 执行项1
    assert r["kind"] == "inspection" and "刷新重试" in r["title"]


def test_inspection_mode_nondict_snapshot_degrades_not_crashes(monkeypatch):
    # t02 真值表的巡检侧同款腿：snapshot 非 dict（老代码/桩/坏数据）→ 显式降级不崩
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    res, _ = run_list(
        {"kind": "inspection"},
        [InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE, SA_EMPTY)],
        {"inspection-integration-tests-20260915": FakeHandle(snapshot=["not", "a", "dict"])})
    r = row_of(res, "inspection-integration-tests-20260915")
    assert r is not None and r["kind"] == "inspection"
    assert "刷新重试" in r["title"] and r["stage_state"] == "running"


def test_default_mode_row_set_zero_change(monkeypatch):
    # R9：缺省列表（无 kind）行集合零变化——巡检 workflow 即使在 visibility 里也不上板
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    snap = {"engine": "v2", "meta": {"id": "t-run", "title": "真票", "project": "suyou",
                                     "role": "developer", "status": "dispatched",
                                     "stage": "implement", "stage_state": "running",
                                     "created": 1700000000, "updated": 1700000100}}
    _K = client_mod.SearchAttributeKey
    sa = {str(_K.for_keyword(client_mod.PROJECT_SA_NAME)): "suyou"}
    q = TASK_QUEUE
    wfs = [
        FakeListWf("t-run", "RUNNING", q, sa),
        InspWf("inspection-integration-tests-20260915", "RUNNING", q, sa),
        InspWf("inspection-test-face-20260910", "RUNNING", q, sa),
    ]
    res, client_obj = run_list({}, wfs, {"t-run": FakeHandle(snapshot=snap)})
    ids = sorted(r["id"] for r in tickets_of(res))
    assert ids == ["t-run"], "缺省列表不得混入任何巡检行（行集合与今天同集）"
    assert 'WorkflowType="DevLaneWorkflow"' in client_obj.filters[0]
    assert "InspectionPeriodicWorkflow" not in client_obj.filters[0]
    # dev-lane 行形状 parity：键集逐键钉死
    row = row_of(res, "t-run")
    assert set(row) == DEVLANE_ROW_KEYS
    assert row["title"] == "真票" and row["engine"] == ENGINE_V2


def test_unknown_kind_fails_closed(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances", lambda: ((), "", []))
    res, _ = run_list({"kind": "inspectionn"}, [], {})
    assert res.get("ok") is False and "kind" in (res.get("error") or "")


def test_project_epic_filter_stackable_in_inspection_mode(monkeypatch):
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    _K = client_mod.SearchAttributeKey
    sa = {str(_K.for_keyword(client_mod.PROJECT_SA_NAME)): "foo",
          str(_K.for_keyword(client_mod.EPIC_SA_NAME)): "ep1"}
    wfs = [InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE, sa)]
    res, client_obj = run_list(
        {"kind": "inspection", "project": "foo", "epic": "ep1"}, wfs,
        {"inspection-integration-tests-20260915": FakeHandle(snapshot=inspection_snap())})
    # ProjectKey/EpicCode 过滤保持生效（spec）：过滤串 AND 叠加，SA 直读进行
    assert 'AND ProjectKey="foo"' in client_obj.filters[0]
    assert 'AND EpicCode="ep1"' in client_obj.filters[0]
    r = row_of(res, "inspection-integration-tests-20260915")
    assert r["project"] == "foo" and r["epic"] == "ep1"


# ---------------------------------------------------------------- D. ticket-query 巡检分支

def test_ticket_query_inspection_branch_engine_and_meta():
    snap = inspection_snap()
    h = FakeHandle(snapshot=snap)
    h.describe = FakeDesc("RUNNING").describe  # type: ignore[method-assign]
    res = run_query("inspection-integration-tests-20260915", h)
    assert res.get("ok") is True
    r = res["result"]
    assert r["engine"] == ENGINE_V2, "坑A：巡检快照无 engine 键，必须显式回 v2（否则谎报不存在）"
    m = r["ticket"]
    assert m["kind"] == "inspection" and m["gate_id"] == "inspection-close"
    assert m["title"] == "巡检 integration-tests · 期 20260915"
    assert m["instance_id"] == "integration-tests" and m["period"] == "20260915"
    assert len(m["findings"]) == 3 and m["heartbeat"] is True
    assert m["human_gate"] is None            # 签字前常态缺键不编造
    assert m["timeline"] and m["timeline"][0]["state"] == "awaiting-human"
    assert r["snapshot"] is snap or r["snapshot"] == snap
    assert r["pulse"] is None                 # 桩无 pending → 软降级


def test_ticket_query_devlane_snapshot_unchanged():
    snap = {"engine": "v2", "meta": {"id": "t-run", "title": "真票"}, "stage_acceptance": []}
    h = FakeHandle(snapshot=snap)
    h.describe = FakeDesc("RUNNING").describe  # type: ignore[method-assign]
    res = run_query("t-run", h)
    r = res["result"]
    assert r["engine"] == "v2"                # 沿用快照 engine 原语义（零变化）
    assert r["ticket"]["id"] == "t-run" and r["ticket"]["title"] == "真票"
    assert "kind" not in r["ticket"] and "gate_id" not in r["ticket"]


# ---------------------------------------------------------------- t260916-02 双腿/扫描面

def _ins_sa(inst, per):
    return {str(_K.for_keyword(client_mod.INSPECTION_INSTANCE_SA_NAME)): inst,
            str(_K.for_keyword(client_mod.INSPECTION_PERIOD_SA_NAME)): per}


def test_inspection_board_sa_leg_rows_match_via_sa(monkeypatch):
    """新票（t 形 id）靠 InspectionInstance SA 上板：match_via=sa，实例/期不从 id 反解
    （id 里根本没有）——legacy_unowned 随 ProjectKey SA 缺席=True（口径⑤）。"""
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: (("integration-tests",), "", []))
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    wfs = [InspWf("t260916-01", "RUNNING", TASK_QUEUE, {**_ins_sa("integration-tests", "20260916"),
                                                        **SA_FOO}, start_time=start)]
    handles = {"t260916-01": FakeHandle(snapshot=inspection_snap())}
    res, _c = run_list({"kind": "inspection"}, wfs, handles)
    rows = tickets_of(res)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "t260916-01" and row["match_via"] == "sa"
    # 期号取 face 镜像（真源优先，20260915）；SA 值用于白名单过滤与 face 缺键兜底
    assert row["instance_id"] == "integration-tests" and row["period"] == "20260915"
    assert row["project"] == "foo" and row["legacy_unowned"] is False
    assert row["title"] == "巡检 integration-tests · 期 20260915"


def test_inspection_board_degraded_whitelist_named(monkeypatch):
    """声明面降级 → 板面显式空 + degraded 标记（查询都不发；R2 纪律不回退）。"""
    monkeypatch.setattr(client_mod, "_inspection_enabled_instances",
                        lambda: ((), "decl boom", [("", "/tmp/decl.yaml", "decl boom")]))
    wfs = [InspWf("inspection-integration-tests-20260915", "RUNNING", TASK_QUEUE, SA_EMPTY)]
    res, c = run_list({"kind": "inspection"}, wfs, {})
    assert tickets_of(res) == []
    info = res["result"]["inspection_filter"]
    assert info["degraded"] is True and "decl boom" in info["note"]
    assert info["scan_mode"] == "skipped" and c.filters == []


def test_ticket_list_id_prefix_scan_cross_family():
    """铸号扫描面（ticket.py _next_seq_v2 的序号真源）：id_prefix=全类型前缀直查——
    dev-lane 工单与巡检票同入（同天序号空间，修 _next_seq_v2 只扫工单店的现成缺陷）；
    后端拒绝算子 → 类型扫+客户端前缀过滤降级（scan_mode 可辨）；与 kind 并用=显式拒。"""
    start = datetime.fromtimestamp(1760000000, tz=timezone.utc)
    wfs = [FakeListWf("t260916-01", "RUNNING", TASK_QUEUE, SA_EMPTY,
                      workflow_type="DevLaneWorkflow", start_time=start),
           InspWf("t260916-02", "RUNNING", TASK_QUEUE, SA_EMPTY, start_time=start),
           FakeListWf("t260916-99", "RUNNING", "self-test-queue", SA_EMPTY,
                      workflow_type="DevLaneWorkflow", start_time=start),  # 非生产队列不收
           InspWf("inspection-x-20260916", "RUNNING", TASK_QUEUE, SA_EMPTY, start_time=start)]
    res, c = run_list({"id_prefix": "t260916"}, wfs, {})
    ids = [r["id"] for r in tickets_of(res)]
    assert ids == ["t260916-01", "t260916-02"]            # 跨族同扫
    assert res["result"]["id_prefix_scan"]["scan_mode"] == "starts_with"
    assert len(c.filters) == 1 and "STARTS_WITH" in c.filters[0]
    # kind 并用闸（fail-closed）
    res_bad = _run_list_raw({"kind": "inspection", "id_prefix": "t"}, wfs, {})
    assert res_bad["ok"] is False and "不并用" in res_bad["error"]
    # R2 降级：算子被拒 → 类型扫（工单+巡检两类）+ 客户端前缀过滤
    c2 = _connect_with(list(wfs), {})
    c2.reject_starts_with = True

    async def _runner():
        return await client_mod.cmd_ticket_list({"id_prefix": "t260916"})

    res2 = asyncio.run(_runner())
    assert res2["result"]["id_prefix_scan"]["scan_mode"] == "type_only_fallback"
    assert [r["id"] for r in tickets_of(res2)] == ["t260916-01", "t260916-02"]


def _run_list_raw(args, wfs, handles):
    _connect_with(wfs, handles)
    return asyncio.run(client_mod.cmd_ticket_list(dict(args)))
