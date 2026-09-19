"""t260919-02 终态失败票两面可见——引擎侧 UT（详情失败面 + 板面失败行）。

黑盒口径不依赖真 Temporal：temporalio 导入桩（integration/t260901-23/_stub_temporalio
共享夹具）+ Fake handle/describe/list_workflows，真 client.py 命令层跑全程。
覆盖（票面验收①②③ + review 意见钉死项）：
  A. _is_failed_exec 判别单点真值表（补集口径）。
  B. _failure_reason_of 异常链提取（__cause__ 下钻/深度上限/畸形 cause/全链无消息）。
  C. 详情失败面（cmd_ticket_query 终态分支）：FAILED → kind=terminal、文案一字不改
     （「刷新无效」在、绝不「刷新重试/瞬时/工单不存在」）、face 结构化载荷
     （原因串/票身份实例期号/无快照说明/终态时刻）；负腿=原因不可得显式文案；
     超时腿；矛盾腿（终态但 result 未抛）；畸形 desc 降级。
  D. 板面失败行（cmd_ticket_list）：巡检形（SA 白名单桩）与 dev-lane 形各一腿——
     行 status/stage_state=failed、标题诚实不含「查询超时/刷新重试」、
     行键集与既有极简/降级行逐键同形（t260915-08 parity）。
  E. 回归腿：RUNNING 三败降级行、COMPLETED 窗内 meta 行、COMPLETED 超窗匿名最小行、
     TERMINATED 不上板、RUNNING/COMPLETED 详情通路原样。
"""
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "integration" / "t260901-23"))
sys.path.insert(0, str(REPO / "server" / "engine"))

import _stub_temporalio  # noqa: E402
_stub_temporalio.install()

import client as client_mod  # noqa: E402  # 桩环境下的真 client.py


# ---------------------------------------------------------------- 桩件

class _Status:
    def __init__(self, name):
        self.name = name


class _SAKeys:
    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        return self.kv.get(str(key))


class _Desc:
    """describe 桩：status + SA（kv 可空）；无 close_time/start_time 属性=畸形降级腿。"""

    def __init__(self, status_name, sa_kv=None):
        self.status = _Status(status_name) if status_name else None
        self.typed_search_attributes = _SAKeys(sa_kv or {})


class WorkflowFailureError(Exception):
    """与 Temporal 同名的本地桩类：result() 历史回放的失败异常形态。"""


class FakeHandle:
    def __init__(self, status_name=None, desc=None, query_fn=None,
                 result_fn=None, describe_exc=None):
        self._desc = desc if desc is not None else _Desc(status_name)
        self._query_fn = query_fn
        self._result_fn = result_fn
        self._describe_exc = describe_exc
        self.queries = 0
        self.results = 0
        self.run_id = "stub-run"
        self.result_run_id = "stub-run"

    async def describe(self):
        if self._describe_exc is not None:
            raise self._describe_exc
        return self._desc

    async def query(self, name):
        self.queries += 1
        if self._query_fn is not None:
            return self._query_fn(name)
        return None

    async def result(self):
        self.results += 1
        if self._result_fn is not None:
            v = self._result_fn()
            if asyncio.iscoroutine(v):
                v = await v
            return v
        return None


class FakeListWf:
    def __init__(self, tid, status_name, task_queue, sa_kv=None, close_time=None):
        self.id = tid
        self.status = _Status(status_name)
        self.task_queue = task_queue
        self.close_time = close_time
        self.start_time = None
        self._kv = sa_kv or {}

    @property
    def typed_search_attributes(self):
        return _SAKeys(self._kv)


class FakeClient:
    def __init__(self, wfs=None, handles=None):
        self._wfs = wfs or []
        self._handles = handles or {}

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, _filter):
        for w in self._wfs:
            yield w


def _install(wfs=None, handles=None):
    async def _fake_connect():
        return FakeClient(wfs, handles)
    client_mod._connect = _fake_connect


# ---------------------------------------------------------------- 工具

def _run(coro_fn):
    return asyncio.run(coro_fn())


def _query(tid, handle):
    _install(handles={tid: handle})

    async def runner():
        return await client_mod.cmd_ticket_query({"ticket_id": tid})
    return _run(runner)


def _list(args, wfs, handles):
    _install(wfs=wfs, handles=handles)

    async def runner():
        return await client_mod.cmd_ticket_list(dict(args))
    return _run(runner)


def _row_of(res, tid):
    for r in ((res.get("result") or {}).get("tickets") or []):
        if r.get("id") == tid:
            return r
    return None


def _sa_kv(**kw):
    _K = client_mod.SearchAttributeKey
    out = {}
    for k, v in kw.items():
        name = {"project": client_mod.PROJECT_SA_NAME,
                "epic": client_mod.EPIC_SA_NAME,
                "inst": client_mod.INSPECTION_INSTANCE_SA_NAME,
                "per": client_mod.INSPECTION_PERIOD_SA_NAME}[k]
        out[str(_K.for_keyword(name))] = v
    return out


def setup_module(module):
    # 重试延迟注入归零（模块级常量=配置面）：测试提速，生产默认不动。
    client_mod.QUERY_RETRY_BASE_DELAY = 0.0
    client_mod.QUERY_RETRY_JITTER = 0.0


# ---------------------------------------------------------------- A 判别单点

def test_a_is_failed_exec_truth_table():
    f = client_mod._is_failed_exec
    assert f("FAILED") and f("CANCELED") and f("TIMED_OUT") and f("TERMINATED")
    assert f("SOME_NEW_TERMINAL_STATE")          # 补集口径：未知新终态宁显失败
    assert not f("RUNNING") and not f("COMPLETED") and not f("CONTINUED_AS_NEW")
    assert not f("")                              # 空=describe 缺 status，不判失败


def test_b_failure_reason_of_chain():
    # 正常链：WorkflowFailureError → RuntimeError("套件 boom")，取最深消息。
    def boom():
        try:
            raise RuntimeError("套件 boom")
        except RuntimeError as e:
            raise WorkflowFailureError("Workflow execution failed") from e
    try:
        boom()
    except WorkflowFailureError as e:
        reason = client_mod._failure_reason_of(e)
    assert "套件 boom" in reason
    # 深度上限：3 层 __cause__ 后停（不无限下钻）。
    def deep():
        cur = RuntimeError("level0")
        for i in range(1, 8):
            nxt = RuntimeError("level%d" % i)
            nxt.__cause__ = cur
            cur = nxt
        raise cur
    try:
        deep()
    except RuntimeError as e:
        reason = client_mod._failure_reason_of(e)
    assert reason.startswith("level") and reason != ""
    # 畸形 cause（非异常对象）就地停，不抛——直接赋值会被 CPython setter 拒
    # （exception cause must be BaseException），用子类类属性遮蔽描述子模拟
    # C 扩展/反序列化产出的脏链形态。
    class _WeirdCause(RuntimeError):
        __cause__ = "not-an-exception"      # 类属性遮蔽 BaseException 的 getset 描述子
    assert client_mod._failure_reason_of(_WeirdCause("outer")) == "outer"
    # 全链无消息 → ''（调用方显式「原因不可得」，绝不编造）。
    empty = WorkflowFailureError("")
    empty.__cause__ = RuntimeError("   ")
    assert client_mod._failure_reason_of(empty) == ""
    assert client_mod._failure_reason_of(None) == ""


# ---------------------------------------------------------------- C 详情失败面

TID = "t260919-01"


def _failed_handle(sa_kv=None, result_fn=None):
    def _raise():
        try:
            raise RuntimeError("套件 boom")
        except RuntimeError as e:
            raise WorkflowFailureError("Workflow execution failed") from e
    return FakeHandle("FAILED", desc=_Desc("FAILED", sa_kv or {}),
                      result_fn=result_fn or _raise)


def test_c_terminal_face_full():
    h = _failed_handle(sa_kv=_sa_kv(project="sandbar", epic="engine-hardening",
                                    inst="integration-tests", per="20260919"))
    res = _query(TID, h)
    # 诚实口径（KI-025 红线）：kind=terminal、文案一字不改。
    assert res.get("ok") is False and res.get("kind") == "terminal"
    msg = str(res.get("error") or "")
    assert "终态" in msg and "刷新无效" in msg
    assert "刷新重试" not in msg and "瞬时" not in msg and "工单不存在" not in msg
    # face 结构化失败面（验收②全字段）。
    face = res.get("face")
    assert isinstance(face, dict)
    assert face["exec_status"] == "FAILED" and face["ticket_id"] == TID
    assert face["reason_available"] is True and "套件 boom" in face["reason"]
    assert "Temporal" in face["reason_source"]
    assert face["instance_id"] == "integration-tests" and face["period"] == "20260919"
    assert face["project"] == "sandbar" and face["epic"] == "engine-hardening"
    assert face["snapshot_available"] is False and "无快照" in face["snapshot_note"]
    assert face["last_stage"] is None and face["last_stage_note"]
    assert face["reason_source"] != ""


def test_c_terminal_face_reason_unavailable():
    # 负腿：失败异常链无消息 → 显式「原因不可得」，执行状态保留（绝不编造）。
    def _silent():
        raise WorkflowFailureError("")
    h = _failed_handle(result_fn=_silent)
    res = _query(TID, h)
    face = res["face"]
    assert res["kind"] == "terminal" and face["reason_available"] is False
    assert face["reason"] == ""
    assert "原因不可得" in face["reason_source"]
    assert face["exec_status"] == "FAILED"          # 执行状态原文保留


def test_c_terminal_face_result_timeout(monkeypatch=None):
    # 超时腿：result() 卡死（协程让出控制权后超时）→ 原因不可得（超时归因）。
    async def _hang():
        await asyncio.sleep(1.0)
        return {}
    old = client_mod.TERMINAL_FACE_RESULT_TIMEOUT_S
    client_mod.TERMINAL_FACE_RESULT_TIMEOUT_S = 0.2
    try:
        h = _failed_handle(result_fn=_hang)
        res = _query(TID, h)
    finally:
        client_mod.TERMINAL_FACE_RESULT_TIMEOUT_S = old
    face = res["face"]
    assert face["reason_available"] is False and "超时" in face["reason_source"]


def test_c_terminal_face_contradictory_result():
    # 矛盾腿：状态说 FAILED、result 却返回成功形态 → 不编造原因。
    h = _failed_handle(result_fn=lambda: {"meta": {}})
    res = _query(TID, h)
    face = res["face"]
    assert face["reason_available"] is False and "矛盾" in face["reason_source"]


def test_c_terminal_face_malformed_desc():
    # 畸形 desc（无 SA/无时刻属性）→ 全降级空值/不可得，绝不抛。
    class _BareDesc:
        status = _Status("FAILED")
        typed_search_attributes = None
    h = FakeHandle("FAILED", desc=_BareDesc(),
                   result_fn=lambda: (_ for _ in ()).throw(WorkflowFailureError("x")))
    res = _query("inspection-legacy-inst-20260918", h)
    face = res["face"]
    assert res["kind"] == "terminal" and isinstance(face, dict)
    assert face["project"] == "" and face["epic"] == ""
    # 旧形 id 只读解析兜底（历史票身份，绝不从新形 id 反解）。
    assert face["instance_id"] == "legacy-inst" and face["period"] == "20260918"
    assert face["start_time_txt"] == "" and face["close_time_txt"] == ""


def test_c_terminal_face_time_forms():
    # 时刻字段三形通吃（proto Timestamp / datetime / epoch 数值）+ 畸形降级：
    # SDK describe 给 proto，list 扫描行/测试桩常给 datetime——只读展示字段宽容读取。
    class _ProtoTs:
        def __init__(self, sec):
            self._sec = sec

        def ToSeconds(self):
            return self._sec

    class _DtDesc(_Desc):
        def __init__(self):
            super().__init__("FAILED")
            self.start_time = datetime.fromtimestamp(1758240000, tz=timezone.utc)
            self.close_time = datetime.fromtimestamp(1758243600, tz=timezone.utc)

    class _ProtoDesc(_Desc):
        def __init__(self):
            super().__init__("FAILED")
            self.start_time = _ProtoTs(1758240000)
            self.close_time = _ProtoTs(1758243600)

    h = FakeHandle(desc=_DtDesc(), result_fn=lambda: (_ for _ in ()).throw(WorkflowFailureError("x")))
    face = _query(TID, h)["face"]
    assert abs(face["close_ts"] - 1758243600) < 1 and face["close_time_txt"] != ""
    h = FakeHandle(desc=_ProtoDesc(), result_fn=lambda: (_ for _ in ()).throw(WorkflowFailureError("x")))
    face = _query(TID, h)["face"]
    assert abs(face["start_ts"] - 1758240000) < 1 and face["start_time_txt"] != ""
    # 畸形时刻值 → 0/''（不可得，绝不带崩失败面）。
    class _BadDesc(_Desc):
        def __init__(self):
            super().__init__("FAILED")
            self.start_time = "not-a-time"
            self.close_time = object()
    h = FakeHandle(desc=_BadDesc(), result_fn=lambda: (_ for _ in ()).throw(WorkflowFailureError("x")))
    face = _query(TID, h)["face"]
    assert face["start_ts"] == 0 and face["close_ts"] == 0 \
        and face["start_time_txt"] == "" and face["close_time_txt"] == ""


def test_c_face_only_on_terminal_receipts():
    # face 只在终态回执：RUNNING/COMPLETED 详情通路零 face 键（零回归）。
    good_snap = {"engine": "v2", "meta": {"id": TID, "title": "真票"}}
    h = FakeHandle("RUNNING", desc=_Desc("RUNNING"), query_fn=lambda name: good_snap)
    res = _query(TID, h)
    assert res.get("ok") is True and "face" not in res
    h = FakeHandle("COMPLETED", desc=_Desc("COMPLETED"), result_fn=lambda: good_snap)
    res = _query(TID, h)
    assert res.get("ok") is True and "face" not in res


def test_c_terminal_wording_other_states():
    # TERMINATED/CANCELED 同走终态分支：kind=terminal + face（执行状态各自原文）。
    h = FakeHandle("TERMINATED", desc=_Desc("TERMINATED"),
                   result_fn=lambda: (_ for _ in ()).throw(WorkflowFailureError("torn down")))
    res = _query(TID, h)
    assert res["kind"] == "terminal" and res["face"]["exec_status"] == "TERMINATED"
    assert "TERMINATED" in res["error"] and "刷新无效" in res["error"]


# ---------------------------------------------------------------- D 板面失败行

Q = client_mod.TASK_QUEUE if hasattr(client_mod, "TASK_QUEUE") else "sandbar-tickets"
_NOW = time.time()


def _failed_result_fn():
    def _raise():
        try:
            raise RuntimeError("套件 boom")
        except RuntimeError as e:
            raise WorkflowFailureError("Workflow execution failed") from e
    return _raise


def test_d_inspection_failed_row():
    # 巡检形：白名单桩 + FAILED 巡检票 → 显式失败行（不是「查询超时，刷新重试」）。
    client_mod._inspection_enabled_instances = lambda: (("integration-tests",), "", [])
    w = FakeListWf("inspection-i-20260919", "FAILED", Q,
                   sa_kv=_sa_kv(inst="integration-tests", per="20260919"),
                   close_time=datetime.fromtimestamp(_NOW - 60, tz=timezone.utc))
    h = FakeHandle("FAILED", desc=_Desc("FAILED"),
                   result_fn=_failed_result_fn(), query_fn=lambda name: None)
    res = _list({"kind": "inspection"}, [w], {"inspection-i-20260919": h})
    r = _row_of(res, "inspection-i-20260919")
    assert r is not None, "失败巡检票必须在板面（两面可见之一）"
    assert r["status"] == "failed" and r["stage_state"] == "failed"
    assert r["exec_status"] == "FAILED"
    assert r["engine"] == client_mod.INSPECTION_ROW_ENGINE
    # 标题=正常巡检标题（身份保留），绝不含降级诱导词。
    assert "integration-tests" in str(r["title"])
    assert "查询超时" not in str(r["title"]) and "刷新重试" not in str(r["title"])
    assert r["awaiting_gate"] is False
    # 终态时刻成为行上最后已知时间。
    assert r["updated_ts"] and abs(r["updated_ts"] - (_NOW - 60)) < 5


def test_d_devlane_failed_row_key_parity():
    # dev-lane 形：FAILED 极简失败行——键集与 COMPLETED 超窗匿名极简行逐键同形。
    w_fail = FakeListWf("t-fail", "FAILED", Q, sa_kv=_sa_kv(project="sandbar"),
                        close_time=datetime.fromtimestamp(_NOW - 60, tz=timezone.utc))
    w_old = FakeListWf("t-old", "COMPLETED", Q, sa_kv=_sa_kv(project="sandbar"),
                       close_time=datetime.fromtimestamp(_NOW - 10**7, tz=timezone.utc))
    h_fail = FakeHandle("FAILED", desc=_Desc("FAILED"), result_fn=_failed_result_fn())
    h_old = FakeHandle("COMPLETED", desc=_Desc("COMPLETED"), result_fn=lambda: None)
    res = _list({}, [w_fail, w_old],
                {"t-fail": h_fail, "t-old": h_old})
    r_fail = _row_of(res, "t-fail")
    r_old = _row_of(res, "t-old")
    assert set(r_fail.keys()) == set(r_old.keys()), "t260915-08 行键集 parity（不加新键）"
    assert r_fail["status"] == "failed" and r_fail["stage_state"] == "failed"
    assert r_fail["exec_status"] == "FAILED"
    assert "执行失败" in str(r_fail["title"]) and "刷新重试" not in str(r_fail["title"])
    assert r_fail["project"] == "sandbar"           # SA 直读保留
    assert r_old["status"] == "closed" and r_old["title"] == ""  # 超窗匿名行零回归


def test_d_regression_running_completed_terminated_rows():
    # 回归腿：RUNNING 三败降级行 / COMPLETED 窗内 meta 行 / TERMINATED 不上板。
    client_mod._inspection_enabled_instances = lambda: (("integration-tests",), "", [])
    w_run = FakeListWf("t-run", "RUNNING", Q, sa_kv=_sa_kv(project="sandbar"))
    h_run = FakeHandle("RUNNING", desc=_Desc("RUNNING"),
                       query_fn=lambda name: (_ for _ in ()).throw(asyncio.TimeoutError("stub")))
    w_done = FakeListWf("t-done", "COMPLETED", Q, sa_kv=_sa_kv(project="sandbar"),
                        close_time=datetime.fromtimestamp(_NOW - 10, tz=timezone.utc))
    good_snap = {"engine": "v2", "meta": {"id": "t-done", "title": "收口票",
                                          "project": "sandbar", "status": "closed"}}
    h_done = FakeHandle("COMPLETED", desc=_Desc("COMPLETED"), result_fn=lambda: good_snap)
    w_term = FakeListWf("t-term", "TERMINATED", Q, sa_kv=_sa_kv(project="sandbar"))
    res = _list({}, [w_run, w_done, w_term],
                {"t-run": h_run, "t-done": h_done, "t-term": FakeHandle("TERMINATED")})
    r_run = _row_of(res, "t-run")
    assert r_run is not None and r_run["status"] == "dispatched" \
        and r_run["stage_state"] == "running" and "刷新重试" in r_run["title"], \
        "RUNNING 三败降级行零回归（真在跑才可显在跑+刷新指引）"
    r_done = _row_of(res, "t-done")
    assert r_done is not None and r_done["title"] == "收口票" and r_done["status"] == "closed", \
        "COMPLETED 窗内 result() 通路零回归"
    assert _row_of(res, "t-term") is None, "TERMINATED 不上板纪律零回归"


def test_d_inspection_failed_reason_not_on_list_path():
    # 板面行不带 face（失败面只在详情通路）；失败行不进收口折叠判据（status≠closed）。
    client_mod._inspection_enabled_instances = lambda: (("integration-tests",), "", [])
    w = FakeListWf("inspection-x-20260919", "FAILED", Q,
                   sa_kv=_sa_kv(inst="integration-tests", per="20260919"))
    h = FakeHandle("FAILED", desc=_Desc("FAILED"), result_fn=_failed_result_fn())
    res = _list({"kind": "inspection"}, [w], {"inspection-x-20260919": h})
    r = _row_of(res, "inspection-x-20260919")
    assert "face" not in r and r["status"] == "failed"
