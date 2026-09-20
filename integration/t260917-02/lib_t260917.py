# -*- coding: utf-8 -*-
"""t260917-02 场景共享前置（无 sc_ 前缀=共享步骤代码，不登记场景清单）。

本票三场景（legacy-fire-redirect / board-unresolved-running / ledger-archive-regression）
共享的夹具与观测步骤：旧 action 直发壳起票、无 worker 夹具票、SA 读取、调度计数面、
板面行取用。跨票复用 t260905-03 lib_inspection（StageWorker/spawn_env/票账本/三态纪律）
与 t260916-02 lib_relocation（precheck_stage/注册表夹具/RARE_CRON/调度删除）——前置代码
共享复用是纪律允许面；断言面各自独立，不共享。

绑定面（方案 t260917-02 v2 声明的对外契约，场景侧不发明实现细节）：
- 旧 action 直发形态：InspectionPeriodicWorkflow + payload
  {face:"test", instance_id, period:"", repo_root, scenarios_path:""}——**无 project_key**
  （260917 线上 action payload 原始字节逐字复刻，review R2a 实证形态）；
- 旧壳 id 词法：inspection-<实例>-period[-<时间戳>]（非 t 形；服务端是否追加时间戳后缀
  不在断言面——方案 v2 已声明不依赖该细节）；
- 巡检票 SA：ProjectKey / InspectionInstance / InspectionPeriod（Keyword）；
- 调度 skip 观测面：ScheduleInfo.num_actions / num_actions_skipped_overlap /
  running_actions（review C1：跳火可直接观测）；
- 自建调度 id：sandbar-inspection-<实例>（deadman describe 的同名约定）。
- 三态契约：PASS exit 0 / FAIL exit 1（产品红，缺什么点名什么）/ ENV_FAIL exit 2
  （docker 测试台/temporal CLI/venv 缺件=环境红点名，不假红不假绿）。
  实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-02"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

from lib_inspection import (  # noqa: E402,F401 ——跨票共享前置（纪律允许）
    TEST_NAMESPACE, TEST_TARGET_HOST, cleanup_tickets, die_env, die_fail,
    note_started_ticket, run_client, run_trigger, spawn_env,
)
import lib_relocation as lr  # noqa: E402

# t 形票号词法（对外契约：工单号同形式，t260916-02 起）——形状判别用，不锚实现函数。
T_SHAPE_RE = re.compile(r"^t\d{6}-\d{2,}$")
SA_PROJECT = lr.SA_PROJECT
SA_INSTANCE = lr.SA_INSTANCE
SA_PERIOD = lr.SA_PERIOD


# ---------------------------------------------------------------- 基础观测面

def run_async(coro):
    return asyncio.run(coro)


async def _connect():
    from temporalio.client import Client
    return await Client.connect(TEST_TARGET_HOST, namespace=TEST_NAMESPACE)


def start_old_action_shell(instance: str, queue: str, repo_root: str, tag: str) -> str:
    """直发一枚「旧调度 action 形」壳（260917 生产实况复刻）：非 t 形 id、payload 无
    project_key、period 空。返回 workflow id（已登记进 STARTED_TICKETS 退出自清账本）。

    已存在（上轮残留同 id）不视为夹具失败：隔离台内去重，照常判读（t260916-02 同款）。"""
    from inspection_flow import InspectionPeriodicInput

    wid = "inspection-%s-period-%s" % (instance, tag)

    async def _go():
        c = await _connect()
        try:
            await c.start_workflow(
                "InspectionPeriodicWorkflow",
                InspectionPeriodicInput(instance_id=instance, face="test", period="",
                                        repo_root=repo_root, scenarios_path=""),
                id=wid, task_queue=queue)
        except Exception as e:  # noqa: BLE001——AlreadyStarted=残留去重，可判读；其余上抛
            if "already started" not in str(e).lower():
                raise

    try:
        run_async(_go())
    except Exception as e:  # noqa: BLE001
        die_fail("旧 action 壳夹具直发失败（%s）：%s: %s" % (wid, type(e).__name__, e))
    note_started_ticket(wid)
    return wid


def start_workerless_ticket(wid: str, queue: str, instance: str, period: str,
                            sa_project: str = "", sa_instance: str = "",
                            sa_period: str = "") -> str:
    """无 worker 夹具票：SDK 直发后不供给 worker——板面行来自列表面不依赖快照
    （t260916-02 board 场景同款习语）。sa_instance/sa_period 非空时盖 SA 三件套。"""
    from inspection_flow import InspectionPeriodicInput

    async def _go():
        c = await _connect()
        kwargs = dict(id=wid, task_queue=queue)
        payload = InspectionPeriodicInput(instance_id=instance, face="test", period=period)
        if sa_instance or sa_period:
            from temporalio.common import SearchAttributeKey, SearchAttributePair, \
                TypedSearchAttributes
            pairs = [SearchAttributePair(SearchAttributeKey.for_keyword(SA_INSTANCE), sa_instance),
                     SearchAttributePair(SearchAttributeKey.for_keyword(SA_PERIOD), sa_period)]
            if sa_project:
                pairs.append(SearchAttributePair(SearchAttributeKey.for_keyword(SA_PROJECT), sa_project))
            sa = TypedSearchAttributes(pairs)
            try:
                await c.start_workflow("InspectionPeriodicWorkflow", payload,
                                       typed_search_attributes=sa, **kwargs)
                return
            except TypeError:  # SDK 新旧两形参数名依序回退（客户端公开面）
                await c.start_workflow("InspectionPeriodicWorkflow", payload,
                                       search_attributes=sa, **kwargs)
            return
        await c.start_workflow("InspectionPeriodicWorkflow", payload, **kwargs)

    try:
        run_async(_go())
    except Exception as e:  # noqa: BLE001
        if "already started" not in str(e).lower():
            die_fail("无 worker 夹具票直发失败（%s）：%s: %s" % (wid, type(e).__name__, e))
    note_started_ticket(wid)
    return wid


def wait_terminal(wid: str, budget_s: float, step: float = 2.0) -> str:
    """轮询到终态，返回终态名；超时返回 ""（调用方判 FAIL——不静默不假绿）。"""

    async def _one():
        c = await _connect()
        d = await c.get_workflow_handle(wid).describe()
        return (d.status.name if d.status is not None else "RUNNING")

    deadline = time.time() + budget_s
    st = ""
    while time.time() < deadline:
        try:
            st = run_async(_one())
        except Exception:  # noqa: BLE001——describe 瞬时失败继续轮（不静默吞预算）
            st = ""
        if st in ("COMPLETED", "FAILED", "CANCELED", "TERMINATED"):
            return st
        time.sleep(step)
    return ""


def status_of(wid: str) -> str:
    """读单票 exec_status 名（终态判别用；瞬时失败返回 ""）。"""

    async def _one():
        c = await _connect()
        d = await c.get_workflow_handle(wid).describe()
        return (d.status.name if d.status is not None else "RUNNING")

    try:
        return run_async(_one())
    except Exception:  # noqa: BLE001——瞬时失败继续轮
        return ""


def sa_triple(wid: str) -> dict:
    """读一枚票的巡检 SA 三件套（客户端公开读取面；缺 SA=空串）。"""

    async def _one():
        c = await _connect()
        d = await c.get_workflow_handle(wid).describe()
        from temporalio.common import SearchAttributeKey
        tsa = d.typed_search_attributes

        def kv(name):
            try:
                return str(tsa.get(SearchAttributeKey.for_keyword(name)) or "")
            except Exception:  # noqa: BLE001——未注册/形状差异=空，不炸判读
                return ""
        return {SA_PROJECT: kv(SA_PROJECT), SA_INSTANCE: kv(SA_INSTANCE),
                SA_PERIOD: kv(SA_PERIOD)}

    return run_async(_one())


def list_ids_by_instance(instance: str) -> list:
    """按实例 SA 列 workflow id（SA 查询路径公开查询面；数量断言用）。"""

    async def _one():
        c = await _connect()
        out = []
        async for wf in c.list_workflows("%s = '%s'" % (SA_INSTANCE, instance)):
            out.append(wf.id)
        return out

    return run_async(_one())


def schedule_counters(schedule_id: str, budget_s: float = 30.0) -> dict:
    """调度跳火观测面（review C1：ScheduleInfo 直接携带，跳火可观测不推断）。
    create 后调度器系统工作流异步启动，紧邻 describe 会撞「workflow not found」
    （实测 RPCError，temporal-sys-scheduler:<id> 未就绪）——读面最终一致，内部重试。"""
    import time as _t

    async def _one():
        c = await _connect()
        d = await c.get_schedule_handle(schedule_id).describe()
        info = d.info
        return {"num_actions": int(getattr(info, "num_actions", 0) or 0),
                "skipped_overlap": int(getattr(info, "num_actions_skipped_overlap", 0) or 0),
                "running_actions": len(list(getattr(info, "running_actions", None) or []))}

    dl = _t.time() + budget_s
    while True:
        try:
            return run_async(_one())
        except Exception as e:  # noqa: BLE001——未就绪重试；超预算才点名
            if _t.time() >= dl:
                die_fail("调度计数面不可读（%s）：%s: %s"
                         % (schedule_id, type(e).__name__, e))
            _t.sleep(2.0)


def create_interval_schedule(instance: str, queue: str, repo_root: str,
                             every_s: int = 10) -> str:
    """自建 interval 调度（旧直发 action 形 + OverlapPolicy=SKIP——生产形态压缩复刻）。
    id 按 deadman describe 同名约定 sandbar-inspection-<实例>；退出经
    lib_relocation.delete_schedule_best_effort 删除。"""
    from datetime import timedelta
    from inspection_flow import InspectionPeriodicInput

    async def _go():
        from temporalio.client import (Schedule, ScheduleActionStartWorkflow,
                                       ScheduleIntervalSpec, ScheduleOverlapPolicy,
                                       SchedulePolicy, ScheduleSpec)
        c = await _connect()
        await c.create_schedule(
            "sandbar-inspection-%s" % instance,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    "InspectionPeriodicWorkflow",
                    InspectionPeriodicInput(instance_id=instance, face="test",
                                            period="", repo_root=repo_root,
                                            scenarios_path=""),
                    id="inspection-%s-period" % instance, task_queue=queue),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=every_s))]),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)))

    try:
        run_async(_go())
    except Exception as e:  # noqa: BLE001
        if "already exists" not in str(e).lower():
            die_fail("自建 interval 调度失败（sandbar-inspection-%s）：%s: %s"
                     % (instance, type(e).__name__, e))
    return "sandbar-inspection-%s" % instance


def poll(fn, budget_s: float, step: float = 2.0):
    """fn()->truthy 轮询；超时返回 None（调用方判 FAIL）。"""
    deadline = time.time() + budget_s
    while time.time() < deadline:
        try:
            v = fn()
        except Exception:  # noqa: BLE001——单次观测失败继续轮
            v = None
        if v:
            return v
        time.sleep(step)
    return None


# ---------------------------------------------------------------- 板面取用面

def board_blob(env: dict):
    """ticket-list kind=inspection → (parsed, 原始 json 串)。"""
    _, parsed = run_client("ticket-list", {"kind": "inspection"}, env=dict(env))
    if isinstance(parsed, dict):
        return parsed, json.dumps(parsed, ensure_ascii=False)
    return {}, ""


def row_of(parsed, tid: str):
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    rows = (res or {}).get("tickets") if isinstance(res, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("id") == tid:
            return r
    return None


def tickets_env(reg_root: str, ledger_dir: str, queue: str = "") -> dict:
    """子进程/板面 env 单点：夹具注册表 + 夹具台账目录（隔离仓 out/ 不沾手）。"""
    extra = {"SANDBAR_PROJECTS_DIR": reg_root, "SANDBAR_INSPECTION_DIR": ledger_dir}
    if queue:
        extra["SANDBAR_TASK_QUEUE"] = queue
    return spawn_env(extra)
