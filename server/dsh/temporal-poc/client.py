"""Temporal client CLI —— dsh 插件 `suyou-temporal-tools` spawn 的入口。

安全红线（t260821-02）：工具面**绝无「设置 stage / 改状态」入口**：

    client.py start         启动 workflow（dispatcher-scan；260904 起 content-pipeline
                            已退役，工单一律走 ticket-start）
    client.py query         读 workflow 快照（只读，改不了状态）
    client.py schedule-list 列 Schedule（只读）
    client.py cancel        停掉 workflow（terminate，清场/撤销用）
    client.py ticket        工单操作（步2 update/sign；v2 见下）
    client.py ticket-start  创建 v2 工单（M11 模版即代码：模板 id→workflow 类，不落 JSON）
    client.py ticket-list   v2 工单列表（工单台数据源：Temporal list+query；
                            可按 project / epic 过滤——EpicCode SA，epic-linkage）
    client.py ticket-query  单张 v2 工单查询（snapshot+meta+pulse 运行脉搏心跳，t260825-03）

stdout 一律输出**单行 JSON** `{"ok": true, "result": ...}` 或 `{"ok": false, "error": "..."}`，
供 node.ts 插件直接解析。Temporal 的「审计/不可变历史」= workflow 自身的事件历史，
不需要再另造 run_id。

用法（每个子命令带一个 JSON 参数，缺省 {}）：

    python client.py start '{"type":"dispatcher-scan","id":"dispatcher-scan"}'
    python client.py query '{"workflow_id":"t260822-01"}'
    python client.py schedule-list
    python client.py cancel '{"workflow_id":"dispatcher-scan","reason":"清场"}'
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from typing import Any, Dict, List, Optional

from temporalio.client import Client
from temporalio.common import SearchAttributeKey

from shared import (
    DISPATCHER_WF_ID,
    ENGINE_V2,
    EPIC_CODE_RE,
    EPIC_SA_NAME,
    NAMESPACE,
    PROJECT_SA_NAME,
    TARGET_HOST,
    TASK_QUEUE,
    TICKET_QUEUE_PREFIX,
    ReworkRequest,
    Signature,
    TicketInput,
    check_paths_under_project,
    derive_lane_workspace,
    lookup_project,
    project_search_attributes,
    ticket_data_dir,
    ticket_search_attributes,
    ticket_task_queue,
    validate_background_refs,
    validate_epic_code,
    validate_write_set_args,
)
from workflows import DispatcherScanWorkflow
from workflows_v2 import TEMPLATE_CLASSES

# ---- M1-3（t260902-02）：Temporal 回归运行态——closed 工单历史主动清理 ----
# 真删走 temporalio SDK（本文件全走 asyncio、零 subprocess；WorkflowHandle 无
# delete 方法，删除缝 = client.workflow_service.delete_workflow_execution +
# DeleteWorkflowExecutionRequest，temporalio.service 实测 1.18.2 存在）。删除对象
# 限「已归档」（<data>/tickets/<id>/archive.json 存在）的 COMPLETED 执行：
# 归档真源已出仓到 per-key 数据目录（契约 v1.4 ①c），Temporal 只承担过程状态。
# 注意：WorkflowExecution/DeleteWorkflowExecutionRequest 两个 API 类**不做模块级
# import**（延迟到 _sdk_deleter 函数体内，同 shared.py「temporalio 延迟到函数内
# import」纪律）——本文件模块级 SDK 面必须维持 temporalio.client/temporalio.common
# 最小集，t260901-23 的 _stub_temporalio 桩按此前提覆盖（t260902-02 implement
# gen0 曾把两行提到顶层破坏该契约，t260901-23 t01/t02 无 SDK 环境即炸，已修）。

# 收口工单的列表回填窗口（秒）：窗口内的 COMPLETED 执行用 result() 取终态快照，
# 让左栏 sandbar 驻留期有标题/角色（窗口只封顶回填成本，驻留时长是前端配置项）。
CLOSED_HYDRATE_WINDOW_S = 7 * 86400

# ---- 查询错误分级（KI-025，t260903-06）----
# kind 语义（client 产出 → ticket.py 消费 → tools_registry 并入 → 工作台/UI 分流）：
#   not_found：唯一「工单不存在」语义，只能由 describe 命中 NotFoundFailure 触发；
#   transient：瞬时查询故障（超时/连接/RPC 抖动/取消传播），文案引导「刷新重试」，
#              绝不允许出现「不存在」字样（查询失败谎报不存在=KI-025 实案 t260903-02）；
#   terminal：workflow 已终态（TERMINATED/CANCELED/FAILED 等），永久不可查询，
#             文案明说「刷新无效」，绝不 transient（对死票无限重试=反向谎报）；
#   internal：兜底（畸形入参/畸形快照/未知），文案精确说哪个检查失败，非不存在非瞬时。
# 未列出口一律默认 internal——新增 _err 出口时须在此表登记。
KIND_NOT_FOUND = "not_found"
KIND_TRANSIENT = "transient"
KIND_TERMINAL = "terminal"
KIND_INTERNAL = "internal"

# ---- RUNNING snapshot query 重试参数（KI-003，t260903-06）----
# 阶段切换 inline 突变窗 1-2 秒即恢复（KI-003 机制结论）：指数退避 0.5/1/2s ±20%
# 抖动，3 次尝试。最坏窗口 = 3×8s 超时 + 3.5s 退避 ≈ 27.5s（超时每次尝试各付一次），
# 工作台轮询侧配 in-flight 守卫防堆叠（同票 UI 段）。模块级常量供集成测试注入
# 提速（t260901-23 t01/t02 直跑形态），生产不动。
QUERY_RETRY_ATTEMPTS = 3
QUERY_RETRY_BASE_DELAY = 0.5
QUERY_RETRY_MAX_DELAY = 4.0
QUERY_RETRY_JITTER = 0.2
QUERY_TIMEOUT_S = 8.0
# describe 重试（KI-025 另一半：describe 失败当前直接报错，1 次退避重试消抖）。
DESCRIBE_RETRY_ATTEMPTS = 2
DESCRIBE_BASE_DELAY = 0.5


def _ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def _err(msg: str, kind: str = KIND_INTERNAL) -> Dict[str, Any]:
    """结构化错误回执。kind=错误分级（见上方分级表），消费方据此分流 404/503/410，
    「工单不存在」文案只能随 kind=not_found 产出。"""
    return {"ok": False, "error": msg, "kind": kind}


def _is_not_found_exc(e: BaseException) -> bool:
    """判别 describe 异常是否「工单真不存在」语义（KI-025 分级的唯一入水口）。

    结构化判别优先（类名 MRO：temporalio.client.WorkflowNotFoundError 及失败族
    命名变体），异常文案兜底；口径取窄——判不准一律 False（落 transient），
    误判 not_found 就是 KI-025 要消灭的谎报本身。不做模块级 SDK import
    （维持 temporalio.client/temporalio.common 最小集、_stub_temporalio 桩契约），
    故只按类名识别、不引用具体类对象。"""
    for t in type(e).__mro__:
        if t.__name__ in ("WorkflowNotFoundError", "NotFoundFailureError", "NotFoundFailure"):
            return True
    return "not found" in str(e).lower()


def _backoff_delay(attempt: int, base_delay: float, max_delay: float,
                   jitter: float = 0.0) -> float:
    """指数退避间隔：base*2^(attempt-1) 封顶 max_delay；jitter>0 时 ±jitter 比例抖动。

    纯函数（时钟无关）——退避序列断言直接调它（t260901-23 t01）。"""
    import random
    d = min(base_delay * (2 ** max(0, attempt - 1)), max_delay)
    if jitter > 0:
        d = random.uniform(d * (1 - jitter), d * (1 + jitter))
    return d


def _ts_epoch(ts_msg: Any) -> int:
    """proto Timestamp → epoch 秒；缺字段/异常 → 0。"""
    try:
        return int(ts_msg.ToSeconds())
    except Exception:
        return 0


def _pulse_from_desc(desc: Any) -> Optional[Dict[str, Any]]:
    """从 describe 的 pending activity 掏心跳详情（t260825-03 运行脉搏行的数据源）。

    agent_activities.py 的轮询循环每 5s（POLL_SEC）activity.heartbeat(json.dumps(
    {stage,gen,polls,session_kb}))；describe 的 pending_activities 仅 RUNNING 执行有。
    非 agent 段（prepare_workspace/merge_check 等）不心跳、stub 模式心跳是纯字符串
    ——一律软降级：无 pending → None；心跳非 JSON → heartbeat_raw 截断透传。
    任何异常都返回现有部分或 None，绝不让查询路径因掏心跳而挂。
    """
    try:
        acts = list(getattr(desc.raw_description, "pending_activities", []) or [])
    except Exception:
        return None
    if not acts:
        return None
    pa = acts[0]
    out: Dict[str, Any] = {
        "activity": str(getattr(getattr(pa, "activity_type", None), "name", "") or ""),
        "attempt": int(getattr(pa, "attempt", 0) or 0),
        "last_heartbeat_ts": _ts_epoch(getattr(pa, "last_heartbeat_time", None)),
        "started_ts": _ts_epoch(getattr(pa, "last_started_time", None)),
    }
    try:
        state = getattr(pa, "state", None)
        out["state"] = str(getattr(state, "name", "") or state or "")
    except Exception:
        pass
    try:
        details = getattr(pa, "heartbeat_details", None)
        if details is None or len(details.payloads) == 0:
            return out
        raw: Any = None
        try:
            vals = desc.data_converter.payload_converter.from_payloads(details)
            raw = vals[0] if vals else None
        except Exception:
            # 兜底：默认 converter 的心跳是 json/plain 单 payload，手工解一层
            raw = json.loads(bytes(details.payloads[0].data).decode("utf-8"))
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    out["heartbeat"] = parsed
                else:
                    out["heartbeat_raw"] = raw[:200]
            except json.JSONDecodeError:
                out["heartbeat_raw"] = raw[:200]
        elif raw is not None:
            out["heartbeat_raw"] = str(raw)[:200]
    except Exception:
        pass
    return out


async def _connect() -> Client:
    return await Client.connect(TARGET_HOST, namespace=NAMESPACE)


# ---------- 四个子命令 ----------

async def cmd_start(args: Dict[str, Any]) -> Dict[str, Any]:
    client = await _connect()
    wf_type = str(args.get("type") or "")
    if wf_type == "dispatcher-scan":
        wf_id = str(args.get("id") or DISPATCHER_WF_ID)
        sa = project_search_attributes(str(args["project"])) if args.get("project") else None
        handle = await client.start_workflow(
            DispatcherScanWorkflow.run, id=wf_id, task_queue=TASK_QUEUE,
            search_attributes=sa,
        )
        return _ok(
            {"type": wf_type, "workflow_id": handle.id, "run_id": handle.result_run_id}
        )

    # 260904 宿主令：content-pipeline 已随模版退役，start 合法面收窄为 dispatcher-scan；
    # 工单一律走 ticket-start（模板 id→workflow 类）。
    return _err(f"未知 workflow type={wf_type!r}（可用 dispatcher-scan）")


async def cmd_query(args: Dict[str, Any]) -> Dict[str, Any]:
    wf_id = str(args.get("workflow_id") or "")
    if not wf_id:
        return _err("query 需要 workflow_id")
    client = await _connect()
    handle = client.get_workflow_handle(wf_id)
    desc = await handle.describe()
    snap = await handle.query("snapshot")
    return _ok(
        {
            "workflow_id": wf_id,
            "run_id": handle.result_run_id or handle.run_id,
            "status": desc.status.name if desc.status is not None else None,
            "snapshot": snap,
        }
    )


# signal 子命令退役（260904 宿主令）：v1 content-pipeline 随模版退役删除后，
# sign/retry_qc 无可挂靠对象（白名单一并摘除）；但 dsh 插件族旧调用面仍可能 spawn
# 到这里——保留子命令名做 fail-closed 退役报错，避免误导为「未知子命令」。
async def cmd_signal(args: Dict[str, Any]) -> Dict[str, Any]:
    del args  # 无参可用
    return _err("signal 子命令已退役（260904 宿主令）：sign/retry_qc 只服务 v1 "
                "content-pipeline 人门段，该模板已随模版退役删除；人门签字走 "
                "ticket op=sign，清场/撤销走 cancel。")


async def cmd_schedule_list(args: Dict[str, Any]) -> Dict[str, Any]:
    del args  # 无参
    client = await _connect()
    out: List[Dict[str, Any]] = []
    async for desc in await client.list_schedules():
        sched = desc.schedule
        state = getattr(sched, "state", None) if sched is not None else None
        info = desc.info
        out.append(
            {
                "id": desc.id,
                "paused": bool(getattr(state, "paused", False)) if state is not None else None,
                "note": (getattr(state, "note", "") or "") if state is not None else "",
                "next_action_times": [
                    t.isoformat(timespec="seconds")
                    for t in (getattr(info, "next_action_times", None) or [])
                ]
                if info is not None
                else [],
                "recent_actions": len(getattr(info, "recent_actions", None) or [])
                if info is not None
                else 0,
            }
        )
    return _ok({"count": len(out), "schedules": out})


async def cmd_cancel(args: Dict[str, Any]) -> Dict[str, Any]:
    wf_id = str(args.get("workflow_id") or "")
    if not wf_id:
        return _err("cancel 需要 workflow_id")
    reason = str(args.get("reason") or "client.py cancel")
    client = await _connect()
    handle = client.get_workflow_handle(wf_id)
    try:
        await handle.terminate(reason=reason)
    except Exception as e:  # 已结束/不存在等一律结构化回执，不抛栈
        return _err(f"terminate 失败：{type(e).__name__}: {e}")
    return _ok({"workflow_id": wf_id, "terminated": True, "reason": reason})


async def cmd_ticket(args: Dict[str, Any]) -> Dict[str, Any]:
    """工单 stage 机（步2）：只暴露合法的推进入口，无 set-stage / force_stage。

    op ∈ advance / accept / rework / update / dispatch-next / sign / query。
    前五个是 workflow update（同步返回结果+进不可变历史）；sign 是人工审批签字；query 只读。
    """
    op = str(args.get("op") or "")
    tid = str(args.get("ticket_id") or args.get("id") or "")
    if not tid:
        return _err("ticket 需要 ticket_id")
    client = await _connect()
    handle = client.get_workflow_handle(tid)

    if op == "query":
        desc = await handle.describe()
        snap = await handle.query("snapshot")
        running = desc.status is not None and desc.status.name == "RUNNING"
        return _ok({
            "ticket_id": tid,
            "run_id": handle.result_run_id or handle.run_id,
            "status": desc.status.name if desc.status is not None else None,
            "snapshot": snap,
            # 运行脉搏（t260825-03）：pending activity 心跳；非 RUNNING/无心跳 → None
            "pulse": _pulse_from_desc(desc) if running else None,
        })

    if op == "sign":
        raw = args.get("input") or {}
        if not isinstance(raw, dict):
            raw = args
        sig = Signature(
            who=str(raw.get("who") or ""),
            gate=str(raw.get("gate") or ""),
            decision=str(raw.get("decision") or "approve"),
            note=str(raw.get("note") or ""),
        )
        await handle.signal("sign", sig)  # 新旧类同名的 signal，按名发送两类通吃
        return _ok({"ticket_id": tid, "signal": "sign", "gate": sig.gate,
                    "decision": sig.decision, "who": sig.who, "delivered": True})

    if op == "rework":
        # v2：rework=signal（回目标段重跑）
        note = str(args.get("note") or "")
        if not note:
            return _err("rework 需要 note（返工原因）")
        req = ReworkRequest(who=str(args.get("who") or "op-local"),
                            target_stage=str(args.get("to_stage") or ""),
                            note=note)
        await handle.signal("rework", req)
        return _ok({"ticket_id": tid, "signal": "rework",
                    "target_stage": req.target_stage, "delivered": True})

    if op in ("advance", "accept", "dispatch-next"):
        return _err("v2 引擎（模版即代码）已取消 %s：workflow 过门自动推进，"
                    "验收=事后看产物（query 快照的 results/handoffs）；"
                    "打回用 rework，blocked 重跑用 signal retry_qc" % op)

    if op == "update":
        # v2 base.py 的 update handler（按名调用，新旧类同名历史已随旧类退场）
        r = await handle.execute_update(
            "update_status", args=[str(args.get("status") or ""),
                                   str(args.get("note") or ""),
                                   str(args.get("pending_add") or ""),
                                   args.get("book_path")])
        return _ok(r)

    return _err("未知工单操作 %r（可用：rework=打回 / update=更新 / sign=签字 / query=查询）" % op)


# ---------- M11 v2：ticket-start / ticket-list / ticket-query ----------

async def cmd_ticket_start(args: Dict[str, Any]) -> Dict[str, Any]:
    """创建 v2 工单：模板 id → workflow 类（shared.TEMPLATE_CLASS_NAMES 映射），
    业务属性全量钉进 TicketInput（状态只在 workflow，不落 JSON）。
    epic-linkage：args.epic 给定时强校验（代号形状 + notes/epics/<代号>.md 存在），
    合法则 workflow 打 EpicCode search attribute，可按 EpicCode="..." 查询捞出。"""
    tpl = str(args.get("template_id") or args.get("workflow") or "")
    cls = TEMPLATE_CLASSES.get(tpl)
    if cls is None:
        return _err("未知模板 %r（可用：%s）" % (tpl, "、".join(sorted(TEMPLATE_CLASSES))))
    tid = str(args.get("ticket_id") or args.get("id") or "")
    if not tid:
        return _err("ticket-start 需要 ticket_id")
    project = str(args.get("project") or "")
    if not project:
        return _err("ticket-start 需要 project（projects.yaml 注册表 key，无默认值）——"
                    "无 project 即拒收：泳道落仓禁止退化为「由执行 worker 的 REPO_ROOT 决定」"
                    "的相对路径（t260904-01 首开脑裂形态，宁可拒收不静默降级）")
    # 硬闸（KI-032，t260904-02）：收 project 即自查机器级注册表锚 project_root，
    # 与 ticket.py create 同源（单一真源=shared 装载器；SANDBAR_PROJECTS_DIR 等
    # env 覆盖语义保持）。未锚定（未知 key/条目隔离/注册表空）=创建即拒收——
    # 裸入口产出的 workspace 必为锚定项目主目录的绝对路径，落仓与执行 worker 解耦。
    try:
        proj = lookup_project(project)
    except ValueError as e:
        return _err("ticket-start 拒收（project 未锚定，开票走正规入口请先注册项目）：%s" % e)
    project_root = str(proj["dirs"][0])
    # 立项关联（epic-linkage）：--epic 强校验单点——代号形状白名单 + notes/epics/<代号>.md
    # 必须存在，否则拒收（立项验收标准 2）。空 = 不关联立项（允许）。
    try:
        epic = validate_epic_code(str(args.get("epic") or ""))
    except ValueError as e:
        return _err(str(e))
    # 泳道参数推导+校验单点（t260824-04/-10/-11 三次事故）：lane=worktree 的
    # workspace/worktree/branch 缺省推导、缺一补一、不一致/形态错即拒收——
    # 不再透传空字段让 prepare_workspace 静默跳过、agent 空目录空跑。
    try:
        lane, workspace, worktree, branch = derive_lane_workspace(
            tid, cls.TEMPLATE_LANE,
            lane=str(args.get("lane") or ""),
            workspace=args.get("workspace") if isinstance(args.get("workspace"), dict) else None,
            worktree=str(args.get("worktree") or ""),
            branch=str(args.get("branch") or ""),
            template_workspace_dir=bool(getattr(cls, "TEMPLATE_WORKSPACE_DIR", False)),
            project_root=project_root)
    except ValueError as e:
        return _err("ticket-start 参数非法：%s" % e)
    # 硬闸配套（KI-032）：显式给的绝对 workspace/worktree 必须落在注册目录内
    # （与 ticket.py create 的 _check_paths_under_project 同一判定，防裸入口
    # 显式塞别项目/别处的路径绕锚）。相对路径不拦（已由 project_root 锚定语义覆盖）。
    try:
        check_paths_under_project(proj, workspace, worktree)
    except ValueError as e:
        return _err("ticket-start 参数非法：%s" % e)
    overrides: Dict[str, Any] = {}
    for sid, g in (args.get("gate_overrides") or {}).items():
        if isinstance(g, dict):
            from shared import GateSpec
            overrides[str(sid)] = GateSpec(
                stage=str(g.get("stage") or sid), tool=str(g.get("tool") or "qc_run"),
                args=dict(g.get("args") or {}), label=str(g.get("label") or ""),
                cmd=g.get("cmd") or None)
    # 写集生命周期（t260829-07 A1）：空写集拒收单点——空写集票 agent 无白名单护栏、
    # UI 票判定失效（t260829-05/-06 实锤）。出路写进拒收文案，不静默放行。
    ok_ws, ws_flags, ws_err = validate_write_set_args(
        args.get("write_set"), bool(args.get("allow_empty_write_set")))
    if not ok_ws:
        return _err(ws_err)
    # 门①背景文件闸（t260904-18；知识库设计.md §1 工单引用铁律，260904 宿主令
    # 「没提交的 note 不让建工单」）：票面引用的背景文件必须已提交且干净（HEAD 态
    # ——泳道读的是 HEAD 冻结副本，脏改版 agent 读不到）。插在 _connect() 之前：
    # 拒收路径不依赖 Temporal 可达。refs 缺省=不校验（存量在飞票不追溯）。
    refs_raw = args.get("refs")
    refs = [str(x).strip() for x in refs_raw] if isinstance(refs_raw, list) else refs_raw
    try:
        ok_refs, refs_err = validate_background_refs(refs, project_root)
    except Exception as e:  # 校验器自身异常也拒收（fail-closed，不静默放行）
        return _err("背景文件闸故障（fail-closed）：%s: %s" % (type(e).__name__, e))
    if not ok_refs:
        return _err("ticket-start 拒收：%s" % refs_err)
    inp = TicketInput(
        ticket_id=tid, template_id=tpl,
        project=project,
        epic=epic,
        refs=[str(x).strip() for x in (refs_raw or [])] if isinstance(refs_raw, list) else [],
        title=str(args.get("title") or ""),
        lane=lane,
        workspace=workspace,
        worktree=worktree,
        branch=branch,
        base_ref=str(args.get("base_ref") or ""),
        proposal_id=str(args.get("proposal_id") or ""),
        book_path=str(args.get("book_path") or ""),
        write_set=[str(x) for x in (args.get("write_set") or [])],
        no_file_changes=bool(ws_flags.get("no_file_changes")),
        acceptance_extra=[str(x) for x in (args.get("acceptance_extra") or [])],
        deliverables=str(args.get("deliverables") or ""),
        # M16：正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body）；spec 独立
        user_request=str(args.get("user_request") or ""),
        spec=str(args.get("spec") or ""),
        body=str(args.get("body") or ""),
        created=int(args.get("created") or 0),
        gate_overrides=overrides,
    )
    client = await _connect()
    try:
        # 每工单专属队列（260824）：workflow 只被 suyou-ticket-<tid> 上的专属 worker 执行，
        # 共享池 worker 抢不到——版本错开的 worker 不再交叉投毒。专属 worker 由 ticket.py 拉起。
        handle = await client.start_workflow(
            cls.run, inp, id=tid, task_queue=ticket_task_queue(tid),
            search_attributes=ticket_search_attributes(project, epic))
    except Exception as e:
        if "AlreadyStarted" in type(e).__name__:
            return _err("工单 %s 已在 Temporal 存在（单例，AlreadyStarted）" % tid)
        # 立项验收标准 4：EpicCode 未注册的环境必须大声报错，不静默丢标。
        # 特征匹配不钉死单一文案（temporalite/temporal-server 措辞可能不同）：
        # 报错含 SA 名 + 「未注册/未定义」类措辞即识别，给修复指引。
        # （260825 实测 temporalite 原文：Namespace <ns> has no mapping defined
        #   for search attribute EpicCode）
        msg = "%s: %s" % (type(e).__name__, e)
        if epic and EPIC_SA_NAME in msg and re.search(
                r"not (defined|registered)|no mapping defined|未注册|no search attribute",
                msg, re.I):
            return _err(
                "启动失败：环境未注册 %s search attribute（立项 epic 打标失败，不静默降级）。"
                "修复：生产环境重启走 run_server.sh（启动参数自带注册），已在运行的 server 用 "
                "bin/temporal operator search-attribute create --name %s --type Keyword 补注册；"
                "测试环境步骤见 docs/testing-guide.md。原始报错：%s"
                % (EPIC_SA_NAME, EPIC_SA_NAME, msg))
        return _err("启动失败：%s" % msg)
    first = cls.STAGES[0]
    return _ok({
        "id": tid, "workflow_id": handle.id, "run_id": handle.result_run_id,
        "template": tpl, "workflow_class": cls.__name__,
        "project": project, "epic": epic,
        "stage": first.id, "stage_state": "running", "role": first.role,
        "status": "dispatched", "engine": ENGINE_V2,
    })


def _row_from_meta(tid: str, meta: Dict[str, Any], exec_status: str) -> Dict[str, Any]:
    import time as _t
    return {
        "id": tid,
        "project": meta.get("project") or "",
        "epic": meta.get("epic") or "",
        "role": meta.get("role"),
        "status": meta.get("status"),
        "title": meta.get("title"),
        "workflow": meta.get("workflow_id") or "",
        "proposal_id": meta.get("proposal_id") or "",
        "stage": meta.get("stage"),
        "stage_state": meta.get("stage_state") or "awaiting",
        "handoff_count": len(meta.get("handoffs") or []),
        "pending_count": len(meta.get("pending") or []),
        "worktree": meta.get("worktree") or "",
        "workspace": meta.get("workspace"),
        "created": meta.get("created"),
        "updated": _t.strftime("%m-%d %H:%M", _t.localtime(meta.get("updated") or 0)),
        "updated_ts": meta.get("updated"),
        "engine": ENGINE_V2,
        "exec_status": exec_status,
    }


async def _query_snapshot_with_retry(handle: Any, timeout: float = QUERY_TIMEOUT_S,
                                     attempts: int = QUERY_RETRY_ATTEMPTS,
                                     base_delay: float = QUERY_RETRY_BASE_DELAY,
                                     max_delay: float = QUERY_RETRY_MAX_DELAY,
                                     jitter: float = QUERY_RETRY_JITTER) -> Any:
    """RUNNING 工单的 snapshot query 失败重试（KI-003/KI-008 兜底，t260903-06 升级）。

    8s 超时多半是 stage 转换窗瞬时抖动（workflow 侧让路点见 base._breathe，
    KI-003 机制结论：inline 突变窗 1-2 秒即恢复）——指数退避 0.5/1/2s ±20% 抖动
    3 次尝试，覆盖突变窗。重试穷尽抛最后一次异常，由调用方走显式降级（详情
    transient 报错、列表 degraded 行），不再静默吞。只收 workflow handle
    （调用方均已持有）。delay 参数化供自测注入 0 提速，不拖测试。"""
    last: Optional[BaseException] = None
    for i in range(max(1, attempts)):
        if i:
            await asyncio.sleep(_backoff_delay(i, base_delay, max_delay, jitter))
        try:
            return await asyncio.wait_for(handle.query("snapshot"), timeout=timeout)
        except Exception as e:
            last = e
    assert last is not None
    raise last


async def _describe_with_retry(handle: Any, attempts: int = DESCRIBE_RETRY_ATTEMPTS,
                               base_delay: float = DESCRIBE_BASE_DELAY,
                               jitter: float = QUERY_RETRY_JITTER) -> Any:
    """describe 带一次退避重试（KI-025 另一半）：describe 失败原样裸报是谎报
    「不存在」的另一半来源（连接/超时类瞬时故障）。NotFoundFailure 是确定性
    结论，不重试直接上抛；其余异常按瞬时重试 1 次，穷尽上抛最后一次异常。"""
    last: Optional[BaseException] = None
    for i in range(max(1, attempts)):
        if i:
            await asyncio.sleep(_backoff_delay(i, base_delay, base_delay, jitter))
        try:
            return await handle.describe()
        except Exception as e:
            if _is_not_found_exc(e):
                raise
            last = e
    assert last is not None
    raise last


async def cmd_ticket_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """单张工单查询（v2）：snapshot 全文 + meta（JSON 兼容工单形态，ticket.py show 直接消费）。

    错误分级契约（KI-025，t260903-06）：回执带 kind 字段，分级表见模块头。
    「工单不存在」只能由 describe 命中 NotFoundFailure（kind=not_found）触发；
    超时/连接/取消一律 transient；终态（TERMINATED/CANCELED/FAILED…）一律 terminal
    （永久不可得，文案明说刷新无效）；畸形入参/快照 internal。"""
    tid = str(args.get("ticket_id") or args.get("id") or "")
    if not tid:
        return _err("ticket-query 需要 ticket_id", KIND_INTERNAL)
    client = await _connect()
    handle = client.get_workflow_handle(tid)
    try:
        desc = await _describe_with_retry(handle)
    except Exception as e:
        if _is_not_found_exc(e):
            return _err("工单不存在：%s（Temporal 无此 workflow）" % tid, KIND_NOT_FOUND)
        return _err("查询失败（瞬时，已重试 %d 次），请刷新重试：%s: %s"
                    % (DESCRIBE_RETRY_ATTEMPTS - 1, type(e).__name__, e), KIND_TRANSIENT)
    exec_status = desc.status.name if desc.status is not None else ""
    snap: Any = None
    if exec_status == "COMPLETED":
        # 收口 workflow 的 run() 返回值就是最终 snapshot（_snapshot()）——用 result() 直接取，
        # 不需要 worker。query 会打到已退出的专属 worker 队列上空等超时（260824 实测
        # 29s 后报假「工单不存在」，关闭工单的详情/变更/Agent 日志全瘫）。
        try:
            snap = await handle.result()
        except Exception as e:
            return _err("workflow 结果读取失败（瞬时），请刷新重试：%s: %s"
                        % (type(e).__name__, e), KIND_TRANSIENT)
    elif exec_status == "RUNNING":
        try:
            # KI-003/KI-008：RUNNING query 失败多为 stage 转换窗瞬时抖动（突变串
            # 噎事件循环，t260901-23 已在 workflow 侧插让路点），指数退避重试再报。
            snap = await _query_snapshot_with_retry(handle)
        except Exception as e:
            return _err("snapshot 查询失败（已重试 %d 次，瞬时抖动？请刷新重试）：%s: %s"
                        % (QUERY_RETRY_ATTEMPTS - 1, type(e).__name__, e), KIND_TRANSIENT)
    else:
        # 终态（TERMINATED/CANCELED/FAILED 等）永久不可查询：独立 kind=terminal，
        # 文案明说刷新无效——绝不 transient（对死票无限重试=反向谎报，KI-025 review C2）。
        return _err("工单已终态（%s），快照不可得——终态票不再推进，刷新无效"
                    % (exec_status or "未知"), KIND_TERMINAL)
    # 畸形输入防御（t260901-23）：query 结果非 dict（旧代码/桩/坏数据）→ 显式
    # _err，不让命令边界裸抛 AttributeError。
    if not isinstance(snap, dict):
        # 文案纪律：不得含「工单不存在」子串（哪怕否定式——场景按子串守卫谎报面）。
        return _err("snapshot 返回形态异常（预期 dict，实得 %s）——数据/版本问题，"
                    "请核对 worker/模板版本" % type(snap).__name__, KIND_INTERNAL)
    # epic-linkage：dev-lane 的 _init 在 dev_lane.py（本工单写集外）自建 meta，
    # 不含 epic 键。epic 以 workflow 的 EpicCode SA 为真源，在查询边界回填——
    # 快照消费方（ticket.py show / 工单台）看到的 meta.epic 与 SA 恒一致。
    if isinstance(snap, dict) and isinstance(snap.get("meta"), dict) \
            and "epic" not in snap["meta"]:
        try:
            sa_epic = str(desc.typed_search_attributes.get(
                SearchAttributeKey.for_keyword(EPIC_SA_NAME)) or "")
        except Exception:
            sa_epic = ""
        snap["meta"]["epic"] = sa_epic
    return _ok({
        "ticket_id": tid,
        "run_id": handle.result_run_id or handle.run_id,
        "exec_status": exec_status or None,
        "engine": (snap or {}).get("engine") or "",
        "snapshot": snap,
        "ticket": (snap or {}).get("meta") or {},
        # 运行脉搏（t260825-03）：RUNNING 时从 describe 掏 pending activity 心跳
        # （{stage,gen,polls,session_kb}+心跳时间）；非 RUNNING/无心跳 → None 降级。
        "pulse": _pulse_from_desc(desc) if exec_status == "RUNNING" else None,
    })


async def cmd_ticket_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """v2 工单列表：list workflows（六模版类）+ 逐张 query 快照 → ticket.py list 行形态。
    args.project 给定时按 ProjectKey search attribute 过滤（多项目化 260823；
    存量未打标的旧执行不匹配过滤条件，只列新工单）。不传 = 全部项目（admin 全局视图）。
    args.epic 给定时再 AND EpicCode="<代号>"（epic-linkage 验收标准 5；与 project 可叠加）。
    epic 此处只校形状（EPIC_CODE_RE 白名单）；代号存在性强校验在 ticket.py _list
    （validate_epic_code 单点）——不存在的代号走 ticket.py 通道会明确报错而非空表。
    只收生产 task queue 上的执行（自测专属 queue 的滞留实例不查不列——查它们会等超时）。
    260824 起工单走每工单专属队列（suyou-ticket-<id>），过滤器放行共享队列 + 专属前缀。"""
    project = str(args.get("project") or "")
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", project):
        return _err("project 形状不合法（注册表 key 白名单：小写字母/数字/中划线）")
    epic = str(args.get("epic") or "").strip()
    if epic and not EPIC_CODE_RE.match(epic):
        return _err("epic 形状不合法（立项代号白名单：%s，小写字母/数字/连字符），实际 %r"
                    % (EPIC_CODE_RE.pattern, epic))
    client = await _connect()
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    if project:
        type_filter = '(%s) AND ProjectKey="%s"' % (type_filter, project)
    if epic:
        type_filter = '(%s) AND EpicCode="%s"' % (type_filter, epic)
    rows: List[Dict[str, Any]] = []
    # 同 id 多 run：非 TERMINATED 优先（terminate 后同 id 重开的票必须上台面——
    # t260831-03 实测：seen 先标记会让重开的新 run 被旧 TERMINATED run 吞掉，台面消失）
    runs: Dict[str, Any] = {}
    order: List[str] = []
    async for wf in client.list_workflows(type_filter):
        tid = wf.id
        cur = runs.get(tid)
        if cur is None:
            runs[tid] = wf
            order.append(tid)
        elif (cur.status.name if cur.status is not None else "") == "TERMINATED" and \
                (wf.status.name if wf.status is not None else "") != "TERMINATED":
            runs[tid] = wf
    entries: List[Dict[str, str]] = []
    for tid in order:
        wf = runs[tid]
        q = str(getattr(wf, "task_queue", "") or "")
        if q != TASK_QUEUE and not q.startswith(TICKET_QUEUE_PREFIX):
            continue
        exec_status = wf.status.name if wf.status is not None else ""
        if exec_status == "TERMINATED":
            continue  # 清场/撤销的工单不上台面（历史仍在 Temporal 可查）
        # ProjectKey / EpicCode 从 SA 直取：快照不可得（worker 未跑/旧代码）时
        # 行内 project / epic 也不丢（SA 是归属真源，snapshot 只是镜像）。
        try:
            sa_project = str(wf.typed_search_attributes.get(
                SearchAttributeKey.for_keyword(PROJECT_SA_NAME)) or "")
        except Exception:
            sa_project = ""
        try:
            sa_epic = str(wf.typed_search_attributes.get(
                SearchAttributeKey.for_keyword(EPIC_SA_NAME)) or "")
        except Exception:
            sa_epic = ""
        entries.append({"id": tid, "sa_project": sa_project, "sa_epic": sa_epic,
                        "exec_status": exec_status,
                        "close_ts": wf.close_time.timestamp() if wf.close_time else 0})

    # snapshot query 只对 RUNNING 的执行发，且并发发——非 RUNNING 的 query 会打到
    # 已退出的专属 worker 队列上空等 8s 超时（260824 实测：每张收口工单拖慢列表 8s，
    # 串行叠加到 16s+，工单台刷新正好落在这个窗口时左栏长时间空白）。
    # RUNNING query 带 1 次重试（间隔 2s，KI-003/KI-008）：单票最坏 ~18s（8s×2+2s），
    # gather 并发所以列表聚合时延不随票数叠加。重试仍败走显式降级（degraded 行，
    # 不再静默匿名）。
    # COMPLETED 且在回填窗口内的走 result() 拿终态快照（run() 返回值=_snapshot()，
    # 无需 worker）——收口工单在左栏 sandbar 驻留期要有标题/角色，不能是匿名最小行。
    async def _meta_of(tid: str, exec_status: str, close_ts: float) -> Dict[str, Any]:
        if exec_status == "RUNNING":
            try:
                snap = await _query_snapshot_with_retry(client.get_workflow_handle(tid))
                return dict((snap or {}).get("meta") or {})
            except Exception:
                # KI-008 显式降级：degraded 标记（非静默 {}）——行组装分支据此
                # 生成「查询超时，刷新重试」行，stage_state 保持 running（真在跑
                # 的票不能显示成等待态）。
                return {"_query_degraded": True}
        if exec_status == "COMPLETED" and close_ts \
                and time.time() - close_ts < CLOSED_HYDRATE_WINDOW_S:
            try:
                snap = await asyncio.wait_for(
                    client.get_workflow_handle(tid).result(), timeout=8)
                return dict((snap or {}).get("meta") or {})
            except Exception:
                return {}
        return {}

    metas = await asyncio.gather(*(_meta_of(e["id"], e["exec_status"], e["close_ts"]) for e in entries))
    for e, meta in zip(entries, metas):
        tid, sa_project, sa_epic = e["id"], e["sa_project"], e["sa_epic"]
        exec_status = e["exec_status"]
        if meta.get("_query_degraded"):
            # KI-008：RUNNING 查询重试仍败 → 显式降级行。id/project/epic 走 SA
            # 直取不受影响；stage_state/status 保持运行态口径（不照抄匿名行的
            # awaiting/空，避免把真在跑的票误导成等待态）。
            rows.append({"id": tid, "project": sa_project, "epic": sa_epic,
                         "role": None,
                         "status": "dispatched",
                         "title": "查询超时，刷新重试",
                         "workflow": "", "proposal_id": "",
                         "stage": None, "stage_state": "running",
                         "handoff_count": 0, "pending_count": 0, "worktree": "",
                         "workspace": None, "created": None, "updated": "", "updated_ts": 0,
                         "close_ts": e["close_ts"],
                         "engine": ENGINE_V2, "exec_status": exec_status})
        elif meta:
            meta.setdefault("project", sa_project)
            # epic 以 EpicCode SA 为真源（SA 优先），meta 兜底（SA 读取失败/未注册时
            # 用快照镜像）；ticket-query 的 meta.epic 回填是同一理念。
            meta["epic"] = sa_epic or str(meta.get("epic") or "")
            row = _row_from_meta(tid, meta, exec_status)
            row["close_ts"] = e["close_ts"]
            rows.append(row)
        else:  # 快照不可得（已收口超窗/worker 未跑/旧代码）→ 最小行
            rows.append({"id": tid, "project": sa_project, "epic": sa_epic,
                         "role": None,
                         "status": "closed" if exec_status == "COMPLETED" else "",
                         "title": "", "workflow": "", "proposal_id": "",
                         "stage": None, "stage_state": "awaiting",
                         "handoff_count": 0, "pending_count": 0, "worktree": "",
                         "workspace": None, "created": None, "updated": "", "updated_ts": 0,
                         "close_ts": e["close_ts"],
                         "engine": ENGINE_V2, "exec_status": exec_status})
    rows.sort(key=lambda r: -(r.get("created") or 0))
    return _ok({"count": len(rows), "tickets": rows})


# 归档 manifest 解析三态（契约 v1.4 ①c；prune/archive-legacy 共用同一判定）。
def _read_archive_manifest(ticket_id: str, project_key: str) -> Dict[str, Any]:
    """读 <data>/tickets/<id>/archive.json，返回状态 dict：

    {"state": "missing"|"ok"|"malformed"|"error", "legacy": bool, "detail": str}
    missing = 该票未归档（prune 拒删）；malformed = manifest 畸形（fail-closed：
    计 prune 失败，不静默当未归档）；error = IO 异常（计失败）。"""
    import json as _json
    try:
        mpath = ticket_data_dir(project_key, ticket_id) / "archive.json"
    except ValueError as e:
        return {"state": "error", "legacy": False, "detail": "键形状非法：%s" % e}
    if not mpath.is_file():
        return {"state": "missing", "legacy": False, "detail": str(mpath)}
    try:
        data = _json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"state": "malformed", "legacy": False,
                "detail": "%s 不可解析：%s: %s" % (mpath, type(e).__name__, e)}
    if not isinstance(data, dict) or str(data.get("schema") or "") != "v1":
        return {"state": "malformed", "legacy": False,
                "detail": "%s 缺 schema=v1（灰面，人工处置）" % mpath}
    return {"state": "ok", "legacy": bool(data.get("legacy")), "detail": str(mpath)}


async def _closed_ticket_entries(args: Dict[str, Any]) -> "List[Dict[str, Any]]":
    """列 COMPLETED（收口）工单条目：{id, sa_project, close_ts}（TERMINATED 不收——
    与 ticket-list 同口径：清场/撤销的执行不上台面也不进归档清理面）。"""
    client = await _connect()
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    async for wf in client.list_workflows('(%s) AND ExecutionStatus="Completed"' % type_filter):
        q = str(getattr(wf, "task_queue", "") or "")
        if q != TASK_QUEUE and not q.startswith(TICKET_QUEUE_PREFIX):
            continue
        try:
            sa_project = str(wf.typed_search_attributes.get(
                SearchAttributeKey.for_keyword(PROJECT_SA_NAME)) or "")
        except Exception:
            sa_project = ""
        yield {"id": wf.id, "sa_project": sa_project,
               "close_ts": wf.close_time.timestamp() if wf.close_time else 0}


async def cmd_ticket_prune(args: Dict[str, Any], entries: "Optional[List[Dict[str, Any]]]" = None,
                           deleter: Any = None) -> Dict[str, Any]:
    """Temporal 回归运行态：清理 closed 且已归档工单的 workflow 历史（M1-3）。

    删除条件（fail-closed 三清单）：archive.json 存在且 schema=v1 → 可删；
    legacy:true → 需 --allow-legacy（存量诚实过账，人工确认后放行）；missing →
    跳过（未归档绝不删——历史蒸发=本单要根治的事故）；malformed → 计失败。
    默认 --dry-run（零删除），--execute 才真删。真删缝 = deleter 注入函数
    （签名 deleter(workflow_id) -> None；SDK 实现走 workflow_service 级
    DeleteWorkflowExecution，测试注入假 deleter 不依赖真 Temporal）。
    单票删除用 asyncio.wait_for 兜死超时；错误逐个捕获计入 failed，不中断全批。
    entries/deleter 为测试注入缝：缺省走 Temporal 活数据（list_workflows）。
    """
    dry_run = not bool(args.get("execute"))
    allow_legacy = bool(args.get("allow_legacy"))
    project = str(args.get("project") or "").strip()
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", project):
        return _err("project 形状不合法（注册表 key 白名单：小写字母/数字/中划线）")
    per_ticket_timeout = float(args.get("timeout_sec") or 30)

    async def _sdk_deleter(wf_id: str) -> None:
        # SDK API 类函数内 import（模块级 SDK 面最小化纪律，见文件头 M1-3 注释）
        from temporalio.api.common.v1 import WorkflowExecution
        from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
        c = await _connect()
        await c.workflow_service.delete_workflow_execution(
            DeleteWorkflowExecutionRequest(
                namespace=NAMESPACE,
                workflow_execution=WorkflowExecution(workflow_id=wf_id)))

    if deleter is None:
        deleter = _sdk_deleter
    if entries is None:
        entries = [e async for e in _closed_ticket_entries(args)]
    deleted: List[str] = []
    skipped_archived_legacy: List[str] = []
    skipped_not_archived: List[str] = []
    failed: List[Dict[str, str]] = []
    for e in entries:
        tid = e["id"]
        if project and e["sa_project"] != project:
            continue
        m = _read_archive_manifest(tid, e["sa_project"])
        if m["state"] == "missing":
            skipped_not_archived.append(tid)
            continue
        if m["state"] != "ok":
            failed.append({"id": tid, "why": m["detail"]})   # malformed / error：fail-closed
            continue
        if m["legacy"] and not allow_legacy:
            skipped_archived_legacy.append(tid)
            continue
        if dry_run:
            deleted.append(tid)   # dry-run 计入「将删」清单（deleter 零调用）
            continue
        try:
            await asyncio.wait_for(deleter(tid), timeout=per_ticket_timeout)
            deleted.append(tid)
        except asyncio.TimeoutError:
            failed.append({"id": tid, "why": "删除超时（%ss）" % per_ticket_timeout})
        except Exception as ex:
            failed.append({"id": tid, "why": "%s: %s" % (type(ex).__name__, str(ex)[:300])})
    return _ok({"dry_run": dry_run, "allow_legacy": allow_legacy, "project": project or None,
                "deleted": deleted, "skipped_not_archived": skipped_not_archived,
                "skipped_legacy": skipped_archived_legacy, "failed": failed,
                "summary": "prune %s：将删/已删 %d，未归档跳过 %d，legacy 待确认 %d，失败 %d"
                           % ("dry-run" if dry_run else "execute",
                              len(deleted), len(skipped_not_archived),
                              len(skipped_archived_legacy), len(failed))})


async def cmd_ticket_archive_legacy(args: Dict[str, Any],
                                    entries: "Optional[List[Dict[str, Any]]]" = None,
                                    result_of: Any = None) -> Dict[str, Any]:
    """存量诚实过账：为「closed 且泳道已拆除、stage 报告不可恢复」的历史工单写
    archive.json（legacy:true、files 空、reason 明牌）——不伪造不补产（M1-3 R4）。

    只处理 COMPLETED 且无 archive.json 的票；已有 manifest 的票跳过（不覆盖真档）。
    meta 快照取 workflow 终态 result()（COMPLETED 无需 worker）；取不到记空 meta
    并写进 detail。写盘失败单票计 failed 不中断全批。
    entries/result_of 为测试注入缝：缺省走 Temporal 活数据（list_workflows /
    handle.result()），result_of 返回终态 snapshot dict。"""
    import json as _json
    import datetime as _dt
    project = str(args.get("project") or "").strip()
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", project):
        return _err("project 形状不合法（注册表 key 白名单：小写字母/数字/中划线）")
    if entries is None:
        client = await _connect()

        async def _live_result_of(wf_id: str) -> Any:
            return await asyncio.wait_for(
                client.get_workflow_handle(wf_id).result(), timeout=10)

        entries = [e async for e in _closed_ticket_entries(args)]
        if result_of is None:
            result_of = _live_result_of
    written: List[Dict[str, Any]] = []
    skipped: List[str] = []
    failed: List[Dict[str, str]] = []
    for e in entries:
        tid = e["id"]
        if project and e["sa_project"] != project:
            continue
        m = _read_archive_manifest(tid, e["sa_project"])
        if m["state"] == "ok":
            skipped.append(tid)   # 已有真档（或已 legacy 过账）——幂等，不覆盖
            continue
        if m["state"] == "malformed":
            failed.append({"id": tid, "why": m["detail"]})
            continue
        meta: Dict[str, Any] = {}
        if result_of is not None:
            try:
                snap = await result_of(tid)
                if isinstance(snap, dict):
                    meta = dict(snap.get("meta") or {})
            except Exception as ex:
                meta = {"_meta_unavailable": "%s: %s" % (type(ex).__name__, str(ex)[:200])}
        try:
            dpath = ticket_data_dir(e["sa_project"], tid)
            dpath.mkdir(parents=True, exist_ok=True)
            manifest = {"schema": "v1", "ticket_id": tid, "legacy": True,
                        "archived_at": _dt.datetime.now(
                            _dt.timezone.utc).isoformat(timespec="seconds"),
                        "meta": meta, "files": [], "absent": ["worktree"],
                        "reason": "归档前泳道已拆除，stage 报告不可恢复（存量工单诚实过账）",
                        "excluded_rules": []}
            (dpath / "archive.json").write_text(
                _json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append({"id": tid, "path": str(dpath)})
        except Exception as ex:
            failed.append({"id": tid, "why": "%s: %s" % (type(ex).__name__, str(ex)[:300])})
    return _ok({"project": project or None, "written": written, "skipped": skipped,
                "failed": failed,
                "summary": "archive-legacy：过账 %d，已有档跳过 %d，失败 %d"
                           % (len(written), len(skipped), len(failed))})


async def cmd_running_tickets(args: Dict[str, Any]) -> Dict[str, Any]:
    """轻量 RUNNING 工单清单（260824 A 案：console keepalive 的 ensure 数据源）。

    只跑一条 visibility 查询（v2 模版类 AND ExecutionStatus=Running；260904 起
    模板仅 dev-lane），不做
    逐张 snapshot query——keepalive 每 15s 调一次，重了会打满 worker。
    返回 [{id, queue}]：queue 从执行本身取（spawn 侧零常量复制）。
    """
    client = await _connect()
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    running: List[Dict[str, str]] = []
    async for wf in client.list_workflows('(%s) AND ExecutionStatus="Running"' % type_filter):
        q = str(getattr(wf, "task_queue", "") or "")
        if q != TASK_QUEUE and not q.startswith(TICKET_QUEUE_PREFIX):
            continue  # 自测专属 queue 的滞留实例不收
        running.append({"id": wf.id, "queue": q})
    return _ok({"count": len(running), "running": running})


COMMANDS = {
    "start": cmd_start,
    "query": cmd_query,
    "signal": cmd_signal,
    "schedule-list": cmd_schedule_list,
    "cancel": cmd_cancel,
    "ticket": cmd_ticket,
    "ticket-start": cmd_ticket_start,
    "ticket-list": cmd_ticket_list,
    "ticket-query": cmd_ticket_query,
    "ticket-prune": cmd_ticket_prune,
    "ticket-archive-legacy": cmd_ticket_archive_legacy,
    "running-tickets": cmd_running_tickets,
}

USAGE = (
    "用法：python client.py <start|query|schedule-list|cancel|ticket|ticket-start|ticket-list|ticket-query|ticket-prune|ticket-archive-legacy> [argsJSON]\n"
    "安全红线：工具面只暴露上述子命令，无 set-stage / force_stage / 改状态入口。\n"
    "signal 子命令已退役（260904 宿主令）：调用一律返回结构化退役报错（sign/retry_qc\n"
    "  只服务 v1 content-pipeline 人门段，该模板已删）；签字走 ticket op=sign。\n"
    "ticket 子命令（步2）：op=advance|accept|rework|update|dispatch-next|sign|query。\n"
    "  v2 引擎（M11 模版即代码）：advance/accept/dispatch-next 已取消（自动推进），\n"
    "  rework=signal 回目标段重跑，sign=人工审批签字，update=状态维护，query 只读。\n"
    "ticket-start 创建 v2 工单（模板 id→workflow 类）；ticket-list/ticket-query=工单台数据源。\n"
    "ticket-prune 清理 closed 且已归档工单的 workflow 历史（Temporal 回归运行态，M1-3；\n"
    "  默认 --dry-run 零删除，--execute 真删；未归档/legacy 未确认双拒删，fail-closed）。\n"
    "ticket-archive-legacy 存量诚实过账：closed 且无档票写 legacy manifest（不伪造不补产）。\n"
    "running-tickets=轻量 RUNNING 工单清单（console keepalive ensure 专用，无 snapshot 查询）。\n"
    '例：python client.py ticket-start \'{"ticket_id":"t260822-01","template_id":"dev-lane","title":"…"}\''
)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(json.dumps({"ok": False, "error": USAGE}, ensure_ascii=False))
        return

    sub = sys.argv[1]
    fn = COMMANDS.get(sub)
    if fn is None:
        print(json.dumps({"ok": False, "error": f"未知子命令 {sub!r}。{USAGE}"}, ensure_ascii=False))
        return

    args: Dict[str, Any] = {}
    if len(sys.argv) > 2:
        try:
            parsed = json.loads(sys.argv[2])
            if not isinstance(parsed, dict):
                print(json.dumps({"ok": False, "error": "argsJSON 需为 JSON 对象"}, ensure_ascii=False))
                return
            args = parsed
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"argsJSON 不是合法 JSON：{e}"}, ensure_ascii=False))
            return

    try:
        result = asyncio.run(fn(args))
    except Exception as e:  # 基础设施故障（连不上 server 等）→ 结构化回执
        result = _err(f"{type(e).__name__}: {e}")

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
