#!/usr/bin/env python3
"""t260901-23 集成测试 t01：RUNNING 工单详情查询——指数退避重试，穷尽显式降级。

用户场景（KI-003 第 6 次活体的详情端）：工单台详情在 stage 转换窗打开，快照查询
撞上事件循环忙窗超时。t260903-06 升级后行为（KI-003 重试退避 + KI-025 错误分级）：
  A. 第一次超时、重试成功 → 详情正常返回快照（用户无感）。
  B. 三次（默认 attempts=3）都超时/失败 → 报错文案明说「请刷新重试」且回执带
     kind=transient，绝不出现「工单不存在」（谎报面消灭，KI-025）。
  C. 畸形输入不崩：空 ticket_id（kind=internal 兜底）、snapshot 返回非 dict、
     snapshot 缺 meta——命令边界只出 _ok/_err 形态，不抛裸异常。
  D. COMPLETED 路径回归不变：收口票仍走 result() 终态快照，重试逻辑不外溢。
  E. describe 分级（KI-025 另一半）：NotFoundFailure → kind=not_found（唯一
     「不存在」入水口，不重试）；普通异常重试 1 次后 kind=transient。
  F. COMPLETED result() 失败 → kind=transient（结果读取也是瞬时面）。
  G. 退避序列：0.5/1/2/4s 指数+封顶（纯函数直断言）；抖动只在界内波动。
黑盒口径：只在 client 模块的 _connect 边界打桩（假 Temporal client/handle/
describe），不碰实现内部函数；查询桩即时抛 asyncio.TimeoutError，不真等 8s；
重试延迟经模块级常量注入归零（QUERY_RETRY_BASE_DELAY 等，生产默认不动）。
跑法：python3 -B integration/t260901-23/t01_client_retry_and_degrade.py
（纯 stdlib + async，零模型调用，无需 temporalio。）
"""
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POC = HERE.parent.parent / "server" / "dsh" / "temporal-poc"
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


class WorkflowNotFoundError(Exception):
    """与 temporalio.client.WorkflowNotFoundError 同名的本地桩：分级判别按
    类名 MRO 命中（client 不做模块级 SDK import，_is_not_found_exc 结构化判别）。"""


class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeSA:
    def get(self, key):
        return None


class FakeDesc:
    def __init__(self, status_name):
        self.status = FakeStatus(status_name) if status_name else None
        self.typed_search_attributes = FakeSA()


class FakeHandle:
    """假 workflow handle：query/result/describe 行为由脚本逐案注入。"""

    def __init__(self, script=None, snapshot=None, result_value=None,
                 status_name="RUNNING", describe_script=None):
        self.script = list(script or [])    # 每次 query 弹一个动作
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.status_name = status_name
        self.describe_script = list(describe_script or [])  # 每次 describe 弹一个动作：None=成功
        self.queries = 0
        self.describes = 0

    async def describe(self):
        self.describes += 1
        if self.describe_script:
            exc = self.describe_script.pop(0)
            if exc is not None:
                raise exc
        return FakeDesc(self.status_name)

    async def query(self, name):
        self.queries += 1
        act = self.script.pop(0) if self.script else "ok"
        if act == "timeout":
            raise asyncio.TimeoutError("stub timeout")
        if act == "rpc_error":
            raise RuntimeError("stub rpc error")
        return self.snapshot

    async def result(self):
        if self.result_value is not None:
            return self.result_value
        raise RuntimeError("stub no result")

    result_run_id = "stub-run"
    run_id = "stub-run"


class FakeClient:
    def __init__(self, handles):
        self._handles = handles

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, _filter):
        for x in ():
            yield x


def run_with(handles, coro):
    """打桩 _connect 后跑命令协程，返回 (载荷, err)；命令边界不允许裸抛。
    载荷 = _ok 包裹内的 result dict（或 _err 的完整 dict——含 kind 分级字段）。"""
    async def _connect(*a, **k):
        return FakeClient(handles)
    client_mod._connect = _connect
    try:
        res = asyncio.run(coro)
        if isinstance(res, dict) and res.get("error"):
            return res, res["error"]
        payload = res.get("result") if isinstance(res, dict) else None
        return payload, None
    except Exception as e:
        return None, "UNCAUGHT %s: %s" % (type(e).__name__, e)


GOOD_SNAP = {"engine": "v2", "meta": {"id": "t-x", "status": "dispatched",
                                      "stage": "review_plan", "stage_state": "running",
                                      "role": "integration"}}


async def q(args):
    return await client_mod.cmd_ticket_query(args)


def main():
    # 重试延迟注入归零（模块级常量=配置面，非实现内部函数）：测试提速，生产默认不动。
    client_mod.QUERY_RETRY_BASE_DELAY = 0.0
    client_mod.QUERY_RETRY_JITTER = 0.0
    client_mod.DESCRIBE_BASE_DELAY = 0.0

    print("t01 RUNNING 详情查询重试与显式降级")

    # A. 首败重试成功 → ok + 快照
    h = FakeHandle(["timeout", "ok"], GOOD_SNAP)
    res, err = run_with({"t-a": h}, q({"ticket_id": "t-a"}))
    ok(not err and isinstance(res, dict),
       "首败重试成功返回 ok（err=%r）" % err)
    ok(h.queries == 2, "首败一枪重试即中（queries=%d）" % h.queries)
    ok(isinstance(res, dict) and isinstance(res.get("snapshot"), dict)
       and (res["snapshot"].get("meta") or {}).get("id") == "t-x",
       "快照内容透传给用户")

    # B. 三败（默认 attempts=3）→ 显式报错，kind=transient，文案含「刷新重试」
    h = FakeHandle(["timeout", "timeout", "timeout"])
    res, err = run_with({"t-b": h}, q({"ticket_id": "t-b"}))
    ok(err and h.queries == 3, "三败穷尽后报错（queries=%d）" % h.queries)
    ok(isinstance(res, dict) and res.get("kind") == "transient",
       "回执 kind=transient（分级产出）：%r" % (isinstance(res, dict) and res.get("kind"),))
    ok(err and "刷新重试" in str(err), "报错文案含「刷新重试」：%r" % (err,))
    ok(err and "工单不存在" not in str(err), "瞬时文案零「工单不存在」（KI-025 谎报面）")
    ok(err and "UNCAUGHT" not in str(err), "报错走 _err 形态不裸抛")

    # B2. 非超时异常同口径（RPC 抖动同属瞬时故障）
    h = FakeHandle(["rpc_error", "rpc_error", "rpc_error"])
    res, err = run_with({"t-b2": h}, q({"ticket_id": "t-b2"}))
    ok(err and h.queries == 3, "rpc 三败同样穷尽后报错（queries=%d）" % h.queries)
    ok(isinstance(res, dict) and res.get("kind") == "transient", "rpc 失败 kind=transient")
    ok(err and "刷新重试" in str(err), "rpc 报错文案含「刷新重试」：%r" % (err,))

    # C. 畸形输入
    res, err = run_with({"t-c": FakeHandle(["ok"])}, q({}))
    ok(err and "ticket_id" in str(err) and "UNCAUGHT" not in str(err),
       "空 ticket_id 明确报错不崩：%r" % (err,))
    ok(isinstance(res, dict) and res.get("kind") == "internal",
       "空 ticket_id 兜底 kind=internal（未列出口默认档，gen1 条件 2）")

    h = FakeHandle(["ok"], snapshot="not-a-dict")
    res, err = run_with({"t-c2": h}, q({"ticket_id": "t-c2"}))
    ok("UNCAUGHT" not in str(err), "snapshot 非 dict 不崩（err=%r）" % (err,))
    ok(isinstance(res, dict) and res.get("kind") == "internal", "snapshot 非 dict kind=internal")
    ok(err and "工单不存在" not in str(err) and "瞬时" not in str(err),
       "畸形文案不谎报不存在、不谎报瞬时：%r" % (err,))

    h = FakeHandle(["ok"], snapshot={"engine": "v2"})   # 无 meta 键
    res, err = run_with({"t-c3": h}, q({"ticket_id": "t-c3"}))
    ok(not err and "UNCAUGHT" not in str(err), "snapshot 缺 meta 不崩且按空 meta 放行（err=%r）" % (err,))

    # D. COMPLETED 回归：result() 路径不动、不吃重试逻辑
    h = FakeHandle([], result_value=GOOD_SNAP, status_name="COMPLETED")
    res, err = run_with({"t-d": h}, q({"ticket_id": "t-d"}))
    ok(isinstance(res, dict) and isinstance(res.get("snapshot"), dict),
       "COMPLETED 仍走 result() 终态快照")
    ok(h.queries == 0, "COMPLETED 不发 query（queries=%d）" % h.queries)

    # E1. describe 命中 NotFoundFailure → kind=not_found（唯一「不存在」入水口），不重试
    h = FakeHandle(None, status_name=None, describe_script=[WorkflowNotFoundError("workflow not found (stub)")])
    res, err = run_with({"t-e1": h}, q({"ticket_id": "t-e1"}))
    ok(isinstance(res, dict) and res.get("kind") == "not_found",
       "describe NotFoundFailure → kind=not_found（404 唯一合法来源）")
    ok(err and "工单不存在" in str(err), "不存在语义只在 NotFound 路径出现：%r" % (err,))
    ok(h.describes == 1, "确定性 NotFound 不重试（describes=%d）" % h.describes)

    # E2. describe 普通异常（连接失败）→ 退避重试 1 次，穷尽 kind=transient
    h = FakeHandle(None, status_name=None, describe_script=[RuntimeError("conn refused (stub)"), RuntimeError("conn refused (stub)")])
    res, err = run_with({"t-e2": h}, q({"ticket_id": "t-e2"}))
    ok(h.describes == 2, "describe 瞬时失败重试 1 次（describes=%d）" % h.describes)
    ok(isinstance(res, dict) and res.get("kind") == "transient", "describe 穷尽 kind=transient")
    ok(err and "刷新重试" in str(err) and "工单不存在" not in str(err),
       "describe 瞬时文案指引刷新、零谎报：%r" % (err,))

    # F. COMPLETED result() 失败 → kind=transient（结果读取也是瞬时面）
    h = FakeHandle([], result_value=None, status_name="COMPLETED")
    res, err = run_with({"t-f": h}, q({"ticket_id": "t-f"}))
    ok(err and "UNCAUGHT" not in str(err), "result() 失败显式报错不崩（err=%r）" % (err,))
    ok(isinstance(res, dict) and res.get("kind") == "transient", "result() 失败 kind=transient")
    ok(err and "刷新重试" in str(err) and "工单不存在" not in str(err),
       "result() 失败文案指引刷新、零谎报：%r" % (err,))

    # G. 退避序列：0.5/1/2/4 指数+封顶（jitter=0 确定性）；jitter>0 只在界内波动
    seq = [round(client_mod._backoff_delay(i, 0.5, 4.0), 6) for i in (1, 2, 3, 4, 5)]
    ok(seq == [0.5, 1.0, 2.0, 4.0, 4.0], "退避序列 0.5/1/2/4/4（指数+封顶）：%r" % (seq,))
    lo, hi = 0.5 * 0.8, 0.5 * 1.2
    inb = all(lo <= client_mod._backoff_delay(1, 0.5, 4.0, 0.2) <= hi for _ in range(50))
    ok(inb, "jitter=0.2 时波动落在 ±20% 界内（50 采样）")

    print("t01 结果：pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
