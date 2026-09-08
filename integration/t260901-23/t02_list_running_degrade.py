#!/usr/bin/env python3
"""t260901-23 集成测试 t02：工单列表 RUNNING 行——降级显式化，匿名行不再吞 RUNNING。

用户场景（KI-003 活体的列表端）：左栏在 stage 转换窗刷新，RUNNING 票查询失败时
旧行为是静默回最小行——行只剩 id（用户亲见的「匿名行」）。收口后行为：
  A. RUNNING 查询首败重试成功 → 正常行（标题/角色/阶段齐全）。
  B. RUNNING 三败（t260903-06 升级：默认 attempts=3 指数退避）→ 显式降级行：
     标题「查询超时，刷新重试」、stage_state=running、
     status=dispatched、id/project/epic 保留——绝不能显示成等待态或只剩 id。
  C. COMPLETED 超窗的匿名最小行路径回归不变（快照真不可得的唯一合法匿名形态）。
黑盒口径：_connect 打桩 + 假 list_workflows；SA 经 typed_search_attributes 假对象
直取，验证「SA 直取不受快照影响」。

跑法：python3 -B integration/t260901-23/t02_list_running_degrade.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
POC = HERE.parent.parent / "server" / "engine"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(POC))

import _stub_temporalio  # noqa: E402  # client 顶层 import temporalio——无包环境先装桩
_stub_temporalio.install()

import client as client_mod  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


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
    def __init__(self, tid, status_name, task_queue, kv):
        self.id = tid
        self.status = FakeStatus(status_name)
        self.task_queue = task_queue
        self.close_time = None
        self._sa = FakeSA(kv)

    @property
    def typed_search_attributes(self):
        return self._sa.typed_search_attributes


class FakeSARef:
    """cmd_ticket_query 里的 SearchAttributeKey.for_keyword 桩不适用——列表路径
    用 wf.typed_search_attributes.get(...)，上面已覆盖。"""


class FakeHandle:
    def __init__(self, script=None, snapshot=None, result_value=None):
        self.script = list(script or [])
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.queries = 0

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


class FakeClient:
    def __init__(self, wfs, handles):
        self._wfs = wfs
        self._handles = handles

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, _filter):
        for w in self._wfs:
            yield w


GOOD_SNAP = {"engine": "v2", "meta": {"id": "t-run", "title": "真票",
                                      "project": "suyou", "role": "developer",
                                      "status": "dispatched", "stage": "implement",
                                      "stage_state": "running",
                                      "created": 1700000000, "updated": 1700000100}}


def run_list(wfs, handles):
    async def _connect(*a, **k):
        return FakeClient(wfs, handles)

    client_mod._connect = _connect

    async def runner():
        return await client_mod.cmd_ticket_list({})

    try:
        return asyncio.run(runner())
    except Exception as e:
        return {"error": "UNCAUGHT %s: %s" % (type(e).__name__, e)}


def row_of(res, tid):
    tickets = ((res or {}).get("result") or {}).get("tickets") or []
    for r in tickets:
        if r.get("id") == tid:
            return r
    return None


def main():
    print("t02 列表 RUNNING 降级显式化")
    # 重试延迟注入归零（模块级常量=配置面）：t260903-06 退避升级后测试提速，生产默认不动。
    client_mod.QUERY_RETRY_BASE_DELAY = 0.0
    client_mod.QUERY_RETRY_JITTER = 0.0
    q = client_mod.TASK_QUEUE if hasattr(client_mod, "TASK_QUEUE") else "suyou-tickets"  # naming-compat
    # SA 键用与 client 同源的 for_keyword 构造再 str 化——键必须与 FakeSAKeys.get
    # (str(key)) 的查找键一致（t260901-23 修正：原硬编码 "PROJECT"/"EPIC" 与桩
    # 产物永不匹配，属于 fixture 自身不一致，SA 直取分支测不到）。
    _K = client_mod.SearchAttributeKey
    sa = {str(_K.for_keyword(client_mod.PROJECT_SA_NAME)): "suyou",
          str(_K.for_keyword(client_mod.EPIC_SA_NAME)): "ki-003"}

    # A. RUNNING 首败重试成功 → 正常行
    h = FakeHandle(["timeout", "ok"], GOOD_SNAP)
    res = run_list([FakeListWf("t-a", "RUNNING", q, sa)], {"t-a": h})
    r = row_of(res, "t-a")
    ok(r is not None and r.get("title") == "真票" and h.queries == 2,
       "首败重试成功出正常行（queries=%d title=%r）" % (h.queries, r and r.get("title")))

    # B. RUNNING 三败（默认 attempts=3，t260903-06 退避升级）→ 显式降级行
    h = FakeHandle(["timeout", "timeout", "timeout"])
    res = run_list([FakeListWf("t-b", "RUNNING", q, sa)], {"t-b": h})
    r = row_of(res, "t-b")
    ok(r is not None, "降级行仍在台面（不是消失/只剩隐身）")
    ok(r is not None and h.queries == 3, "降级行穷尽 3 次尝试（queries=%d）" % h.queries)
    ok(r is not None and "刷新重试" in str(r.get("title") or ""),
       "降级行标题含「刷新重试」：%r" % (r and r.get("title"),))
    ok(r is not None and r.get("stage_state") == "running",
       "降级行 stage_state=running 不显示成等待态：%r" % (r and r.get("stage_state"),))
    ok(r is not None and r.get("status") == "dispatched",
       "降级行 status=dispatched：%r" % (r and r.get("status"),))
    ok(r is not None and r.get("project") == "suyou" and r.get("epic") == "ki-003",
       "降级行保留 SA 直取的 project/epic：%r/%r" % (r and r.get("project"), r and r.get("epic")))

    # C. COMPLETED 超窗 → 匿名最小行回归不变
    import time
    w = FakeListWf("t-c", "COMPLETED", q, sa)
    w.close_time = datetime.fromtimestamp(time.time() - 10**7, tz=timezone.utc)  # 远超回填窗
    h = FakeHandle([], result_value=None)
    res = run_list([w], {"t-c": h})
    r = row_of(res, "t-c")
    ok(r is not None and r.get("title") == "" and r.get("stage_state") == "awaiting",
       "COMPLETED 超窗仍匿名最小行（title=%r）" % (r and r.get("title"),))

    # C2. 畸形：RUNNING 查询回非 dict / 缺 meta → 不崩，降级或空 meta 均可，不能裸抛
    h = FakeHandle(["ok"], snapshot="garbage")
    res = run_list([FakeListWf("t-d", "RUNNING", q, sa)], {"t-d": h})
    ok(row_of(res, "t-d") is not None and "UNCAUGHT" not in str(res),
       "snapshot 非 dict 列表不崩")
    h = FakeHandle(["ok"], snapshot={"engine": "v2"})
    res = run_list([FakeListWf("t-e", "RUNNING", q, sa)], {"t-e": h})
    ok(row_of(res, "t-e") is not None and "UNCAUGHT" not in str(res),
       "snapshot 缺 meta 列表不崩")

    print("t02 结果：pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
