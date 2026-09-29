"""Temporal client CLI — the entry point spawned by the dsh plugin
`sandbar-temporal-tools`.

Safety red line (ticket t260821-02): the tool surface has **no "set stage / change
status" entry at all**:

    client.py start         start a workflow (dispatcher-scan)
    client.py query         read a workflow snapshot (read-only, cannot change state)
    client.py schedule-list list Schedules (read-only)
    client.py cancel        stop a workflow (terminate, for teardown/abort)
    client.py ticket        ticket operations (update/sign/rework/ruling/query)
    client.py ticket-start  create a v2 ticket (M11 templates-as-code: template id →
                            workflow class, no JSON projection)
    client.py ticket-list   v2 ticket list (workbench data source: Temporal list+query;
                            filterable by project / epic — EpicCode SA, epic-linkage)
    client.py ticket-query  single v2 ticket query (snapshot+meta+pulse heartbeat,
                            ticket t260825-03)
    client.py ticket-cancel 记名单票终结（t260922-10：ticket.py op=cancel 的引擎侧
                            入口——先 cancel_notice 信号留痕后 terminate（reason 同串），
                            已终态幂等回执；跨项目闸与写 op 同口径）

stdout always emits **one line of JSON**, `{"ok": true, "result": ...}` or
`{"ok": false, "error": "..."}`, parsed directly by the node.ts plugin. Temporal's
"audit / immutable history" is the workflow's own event history; no separate run_id is
invented.

Usage (each subcommand takes one JSON argument, default {}):

    python client.py start '{"type":"dispatcher-scan","id":"dispatcher-scan"}'
    python client.py query '{"workflow_id":"t260822-01"}'
    python client.py schedule-list
    python client.py cancel '{"workflow_id":"dispatcher-scan","reason":"清场"}'
    python client.py ticket-cancel '{"ticket_id":"t1","who":"ops","reason":"工作空间已不存在"}'
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from temporalio.client import Client
from temporalio.common import SearchAttributeKey

from shared import (
    AUTH_KINDS,
    CLOSE_OUT_PREFIX,
    close_out_terminate_reason,
    AUTHZ_SIGNAL_GATE_MARKER,
    CALLER_PROJECT_ENV,
    CALLER_UNDECLARED_MARK,
    CROSS_PROJECT_NOTE_LIMIT,
    DISPATCHER_WF_ID,
    ENGINE_V2,
    EPIC_CODE_RE,
    EPIC_SA_NAME,
    INSPECTION_INSTANCE_SA_NAME,
    INSPECTION_PERIOD_SA_NAME,
    NAMESPACE,
    PROJECT_SA_NAME,
    TARGET_HOST,
    TASK_QUEUE,
    TICKET_QUEUE_PREFIX,
    REPO_ROOT,
    load_projects_registry,
    HostRulingRequest,
    HumanAuthorization,
    PauseRequest,
    ReworkRequest,
    Signature,
    TicketInput,
    check_paths_under_project,
    derive_lane_workspace,
    lookup_project,
    multirepo_fuse_a_error,
    project_search_attributes,
    ticket_data_dir,
    ticket_search_attributes,
    ticket_task_queue,
    resolve_epics_dir,
    sign_face_fingerprint,
    validate_background_refs,
    validate_epic_code,
    validate_write_set_args,
)
from workflows import DispatcherScanWorkflow
from workflows_v2 import TEMPLATE_CLASSES

# KI-067（t260910-06）：无差别自审计 + entry_hint 单一真源（stdlib-only，同目录）。
# main() 每个出口（含 -h/无参/未知子命令/argsJSON 非法/连接失败兜底）都经
# _emit() 记 admin.log 并按 claimed-source 附回执提醒——连被拒收的调用也记。
import audit
# t260915-12：跨项目写操作闸的客户端身份解析/判定矩阵（同目录，import shared 单源）。
import caller_gate

# ---- Temporal regression runtime: proactive cleanup of closed-ticket history
#      (ticket t260902-02, M1-3) ----
# The real delete goes through the temporalio SDK: WorkflowHandle has no delete method,
# so the deletion seam is client.workflow_service.delete_workflow_execution +
# DeleteWorkflowExecutionRequest (verified present in temporalio.service 1.18.2). Only
# COMPLETED executions that are already archived (<data>/tickets/<id>/archive.json
# exists) are deletable — the archive's source of truth lives in the per-key data
# directory; Temporal only carries process state.
# The two API classes WorkflowExecution/DeleteWorkflowExecutionRequest are **not
# imported at module level** (deferred into the _sdk_deleter function body, same
# discipline as shared.py's "import temporalio inside functions"): this file's
# module-level SDK surface must stay the minimal temporalio.client/temporalio.common
# set, which is the premise t260901-23's _stub_temporalio stub relies on (someone once
# hoisted those two imports to the top, breaking the contract — it blew up without an
# SDK and was fixed).

# List rehydration window for closed tickets (seconds): COMPLETED executions inside the
# window get their terminal snapshot via result(), so the left-column dwell period has a
# title/role (the window only caps the rehydration cost; dwell length is a frontend
# setting).
CLOSED_HYDRATE_WINDOW_S = 7 * 86400

# ---- t260915-08 工单板收录巡检票（方案 v2 R1/R4/R8/R9；t260916-02 票号 t 形化改造） ----
# INSPECTION_BOARD_TYPES：ticket-list 巡检板面的类型过滤单点。刻意**不进**
# TEMPLATE_CLASSES——那是 ticket-start 模板注册表，ticket-prune/_closed_ticket_entries/
# epic 计数/sc_template_face_narrowing 收窄守卫/shared.TEMPLATE_CLASS_NAMES 交叉自检
# 都吃它；巡检票不是可开工单模板，只扩板面不进注册表。watcher（计数）与 spawner
# （cron 起票薄壳）是调度器不是票，永不上板。
INSPECTION_BOARD_TYPES = ("InspectionPeriodicWorkflow",)

# 巡检列表行的 engine 标记（≠ENGINE_V2）：UI availableOps 按它早退空操作集——
# 巡检票没有 advance/rework/pause/retry_qc 等管理信号，行卡不得给出会打错信号的操作键
# （签字唯一住详情面，走 sign 通道）。ticket-query 的回执 envelope 仍报 ENGINE_V2
# （server/tools/ticket.py _v2_query 以 ENGINE_V2 判 v2 工单，见该处坑A）。
INSPECTION_ROW_ENGINE = "inspection"

# 票号 t 形化（t260916-02）：id 不再编码实例/期——（实例,期号）真源=起票时刻的
# InspectionInstance/InspectionPeriod SA，票面 face 是镜像。旧形 id
# （inspection-<实例>-<期>，t260916 之前起的历史票）只剩**只读解析**：板面 legacy 查询路径
# 上板 + 行渲染兜底（_legacy_inspection_instance_period_of）。旧形铸造点已删（R1：
# 全仓零铸造点，见 integration/t260916-02 静态 grep 子用例），此处绝不铸造旧形新票。
_INSPECTION_LEGACY_ID_RE = re.compile(r"^inspection-(.+)-(\d{8}(?:-[1-9]\d*)?)$")


def _legacy_inspection_instance_period_of(ticket_id: str) -> "Tuple[str, str]":
    """旧形票号只读解析 → (实例, 期号)；新形/外来 id 返回 ("", "")（兼容读面）。"""
    m = _INSPECTION_LEGACY_ID_RE.match(str(ticket_id or ""))
    return (m.group(1), m.group(2)) if m else ("", "")


def _inspection_instance_period_of(wf: Any, ticket_id: str) -> "Tuple[str, str, str]":
    """（实例,期号）读取单点（板面行/白名单过滤/上板合并用）：
    InspectionInstance/InspectionPeriod SA 优先（t260916-02 起票时盖章）→ 旧形 id
    只读解析兜底（历史票，match_via=legacy_id 可辨）。
    返回 (instance, period, match_via)：match_via ∈ {"sa", "legacy_id", ""}；
    SA 读失败（异常/未注册）逐字段回落，不抛。"""
    inst = per = ""
    try:
        inst = str(wf.typed_search_attributes.get(
            SearchAttributeKey.for_keyword(INSPECTION_INSTANCE_SA_NAME)) or "")
        per = str(wf.typed_search_attributes.get(
            SearchAttributeKey.for_keyword(INSPECTION_PERIOD_SA_NAME)) or "")
    except Exception:
        inst = per = ""
    if inst:
        return inst, per, "sa"
    li, lp = _legacy_inspection_instance_period_of(ticket_id)
    if li:
        return li, lp, "legacy_id"
    return "", "", ""


def _inspection_enabled_instances() -> "Tuple[Tuple[str, ...], str, list]":
    """enabled 实例白名单（在册且启用的才上板，t260915-08 R2；t260916-02 起来源=
    遍历注册项目聚合——enabled_instance_whitelist 单点，多项目各持声明也收全；
    旧实现只读引擎仓单文件，已随声明落位迁移删除）。

    返回 (实例集, 降级说明, 降级清单)：降级说明非空 = 声明面有降级项（坏覆盖层/
    坏声明项目/跨项目撞名剔除），调用方必须显式标记进回执（degraded/degraded_projects/
    note 点名，KI-030 禁静默）；实例集为空且说明非空 = 板面显式空降级（绝不放全量，
    僵尸 Flooding 回场；也绝不静默清零不吭声——t260916-02 arbitrate 实锤：本包装层
    曾把 degraded/coverage 丢弃，坏声明时板面静默变空无任何点名）。降级清单=
    结构化条目（degraded_projects 回执键），与说明同源不双写。"""
    try:
        from inspection_decl import enabled_instance_whitelist
        instances, degraded, _coverage = enabled_instance_whitelist()
        note = "；".join("%s（%s）：%s" % (proj or "（覆盖层）", path, err)
                         for proj, path, err in (degraded or []))
        return tuple(sorted(instances)), note, list(degraded or [])
    except Exception as e:  # noqa: BLE001 — 声明损坏/缺文件是配置事故，翻译成显式降级
        return (), "%s: %s" % (type(e).__name__, e), []


def _inspection_coverage_overlay() -> str:
    """覆盖层标记（t260916-02 口径①：env SANDBAR_INSPECTION_DECL 降级为测试覆盖）——
    生效时回执可见（coverage_overlay 键），不静默。读取失败返回 ""（覆盖层语义归
    enabled_instance_whitelist 的降级摘要管，这里只做标记面）。"""
    try:
        from inspection_decl import coverage_decl_path
        return str(coverage_decl_path() or "")
    except Exception:  # noqa: BLE001——标记面绝不因读法翻车带崩板面
        return ""


def _query_operator_unsupported(exc: BaseException) -> bool:
    """list_workflows 查询被后端拒绝（算子/语法不可用）的归类（R2：STARTS_WITH 全仓
    零先例，首条路径被拒时才允许降级；连接/超时类错误绝不归入——降级只对「后端不认这个
    查询」，不对「后端暂时够不着」。措辞按 temporal/ES 常见报错形态归一）。"""
    txt = str(exc).lower()
    return ("parse" in txt or "syntax" in txt or "invalid" in txt
            or "operator" in txt or "could not" in txt)

# ---- Query error classification (KI-025, ticket t260903-06) ----
# kind semantics (produced by client → consumed by ticket.py → merged by tools_registry
# → routed by the workbench/UI):
#   not_found: the only "ticket does not exist" meaning; triggered exclusively by
#              describe hitting NotFoundFailure;
#   transient: momentary query failure (timeout/connection/RPC jitter/cancel
#              propagation); the wording must guide "refresh and retry" and must never
#              contain "does not exist" (a failed query reported as missing = the
#              KI-025 incident);
#   terminal: the workflow is in a terminal state (TERMINATED/CANCELED/FAILED etc.),
#             permanently unqueryable; the wording states plainly that "refreshing is
#             useless" and it is never transient (retrying a dead ticket forever is the
#             opposite lie);
#   internal: catch-all (malformed input/malformed snapshot/unknown); the wording says
#             precisely which check failed.
# Anything unlisted defaults to internal — every new _err exit must be registered here.
KIND_NOT_FOUND = "not_found"
KIND_TRANSIENT = "transient"
KIND_TERMINAL = "terminal"
KIND_INTERNAL = "internal"
# t260913-01（authorize 端到端）：新 kind 只加不占旧义；未列名单走 internal 兜底。
KIND_AUTHZ_FACE_ABSENT = "authz_face_absent"                # 旧 worker 无 sign_face query
KIND_AUTHZ_FACE_MISMATCH = "authz_face_mismatch"            # 指纹漂移
KIND_AUTHZ_FACE_UNREACHABLE = "authz_face_unreachable"      # worker 不在/超时/已终态
KIND_AUTHZ_FACE_ERROR = "authz_face_error"                  # 指纹 handler 自身失败（不吞成 absent）
KIND_AUTHZ_FACE_WRONG_TEMPLATE = "authz_face_wrong_template"  # 非 dev-lane 模板无人授权面
KIND_AUTHZ_SIGNAL_FAILED = "authz_signal_failed"            # signal 自身投递失败
KIND_CROSS_PROJECT_REFUSED = "cross_project_refused"        # t260915-12：跨项目写操作闸拒收
KIND_AUTHZ_LANDING_UNCONFIRMED = "authz_landing_unconfirmed"  # 预算内无落账无拒收

# ---- authorize 落账确认轮询参数（t260913-01）----
# 投递后有界轮询（指数退避 0.5→8s，6 轮 ≈ 20s 上限）：intake 在 worker 激活边界即跑，
# 常态 1-3s 内可见。常量模块级，便于单测注入加速。
AUTHZ_LANDING_POLLS = 6
AUTHZ_LANDING_BASE_DELAY = 0.5
AUTHZ_LANDING_MAX_DELAY = 8.0

# ---- RUNNING snapshot query retry parameters (KI-003, ticket t260903-06) ----
# The stage-transition inline mutation window recovers within 1-2 seconds (the workflow
# side's yield point is base._breathe): exponential backoff 0.5/1/2s with ±20% jitter,
# 3 attempts. Worst window = 3×8s timeouts + 3.5s backoff ≈ 27.5s.
# Module-level constants so integration tests can inject faster values; production
# leaves them alone.
QUERY_RETRY_ATTEMPTS = 3
QUERY_RETRY_BASE_DELAY = 0.5
QUERY_RETRY_MAX_DELAY = 4.0
QUERY_RETRY_JITTER = 0.2
QUERY_TIMEOUT_S = 8.0
# describe retry (the other half of KI-025: reporting an error straight away on a
# momentary describe failure is also a source of false "missing" claims).
DESCRIBE_RETRY_ATTEMPTS = 2
DESCRIBE_BASE_DELAY = 0.5


def _ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def _err(msg: str, kind: str = KIND_INTERNAL,
         face: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Structured error receipt. kind = the error class (see the table above); consumers
    route 404/503/410 from it. The "ticket does not exist" wording may only be produced
    with kind=not_found.

    face（t260919-02）：可选的可渲染失败面载荷（dict），当前仅 kind=terminal 的终态
    分支附带——**只加键不改级**：kind 与文案原样，HTTP 分级（host 侧 terminal→410）
    与诚实口径（刷新无效）零退化。face 取不到/畸形 → 不带键（消费方按纯错误降级），
    绝不带半残假面。"""
    out: Dict[str, Any] = {"ok": False, "error": msg, "kind": kind}
    if face is not None:
        out["face"] = face
    return out


def _is_not_found_exc(e: BaseException) -> bool:
    """Decide whether a describe exception carries the "ticket genuinely does not exist"
    meaning (the only entry point into KI-025's classification).

    Structured detection first (class-name MRO: WorkflowNotFoundError and named variants
    of the failure family), with the exception text as fallback. Take the narrow reading
    — when unsure, return False (lands as transient); misreading as not_found is exactly
    the false claim KI-025 exists to eliminate. No module-level SDK import (keeps the
    minimal SDK surface and the _stub_temporalio stub contract), so recognition is by
    class name only, never by referencing class objects."""
    for t in type(e).__mro__:
        if t.__name__ in ("WorkflowNotFoundError", "NotFoundFailureError", "NotFoundFailure"):
            return True
    return "not found" in str(e).lower()


def _backoff_delay(attempt: int, base_delay: float, max_delay: float,
                   jitter: float = 0.0) -> float:
    """Exponential backoff interval: base*2^(attempt-1) capped at max_delay; with
    jitter>0 it wobbles by ±jitter proportionally. Pure function (clock-independent);
    backoff-sequence assertions call it directly."""
    import random
    d = min(base_delay * (2 ** max(0, attempt - 1)), max_delay)
    if jitter > 0:
        d = random.uniform(d * (1 - jitter), d * (1 + jitter))
    return d


def _ts_epoch(ts_msg: Any) -> int:
    """proto Timestamp → epoch seconds; missing field/exception → 0."""
    try:
        return int(ts_msg.ToSeconds())
    except Exception:
        return 0


def _pulse_from_desc(desc: Any) -> Optional[Dict[str, Any]]:
    """Pull heartbeat details out of describe's pending activity (the data source for
    the running-pulse row, ticket t260825-03).

    agent_activities.py's polling loop heartbeats every 5s (POLL_SEC) with
    json.dumps({stage,gen,polls,session_kb}); describe's pending_activities exist only
    for RUNNING executions. Non-agent sections (prepare_workspace/merge_check etc.)
    never heartbeat, and in stub mode the heartbeat is a plain string — so everything
    degrades softly: no pending → None; a non-JSON heartbeat → truncated passthrough in
    heartbeat_raw. Any exception returns the partial result or None; the query path must
    never hang on heartbeat extraction.
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
            # Fallback: the default converter's heartbeat is a single json/plain payload;
            # decode one layer by hand
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


class TransientConnectError(RuntimeError):
    """连不上 temporal server（KI-029 全族修复，260929）：**瞬时**类基础设施失败。

    为什么立个类型而不是逐点 try（本文件 14 个 `await _connect()` 全在分类块之外，
    实测静态扫描 14/14）：错误分类是**契约**（模块头分类表 + 各命令 docstring），
    分类点该收成单点。旧行为=连接异常一路逃到 main() 兜底，被记成 kind=internal
    （5xx 语义，用户据此以为「服务端有 bug」而不是「重试一次」）——正是 KI-025
    契约被违反的形态。做成 RuntimeError 子类：既有 except RuntimeError 行为零变化。"""
    kind = KIND_TRANSIENT


async def _connect() -> Client:
    """连服务端；失败一律翻成 TransientConnectError（瞬时，可刷新重试）。"""
    try:
        return await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    except Exception as e:  # noqa: BLE001——连接失败=瞬时，绝不冒充 internal
        raise TransientConnectError(
            "连接 temporal server 失败（%s，瞬时，请刷新重试）：%s: %s"
            % (TARGET_HOST, type(e).__name__, e)) from e


# ---------- the four subcommands ----------

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

    # Host order 260904: content-pipeline was retired along with its template, so
    # start's legal surface narrows to dispatcher-scan;
    # tickets always go through ticket-start (template id → workflow class).
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


# The signal subcommand is retired (host order 260904): after v1 content-pipeline was
# deleted, sign/retry_qc lost their anchor, but the dsh plugin family's old call surface
# may still spawn here — the subcommand name is kept to produce a retired error, not to
# mislead into "unknown subcommand".
async def cmd_signal(args: Dict[str, Any]) -> Dict[str, Any]:
    del args  # no usable arguments
    return _err("signal 子命令已退役（260904 宿主令）：sign/retry_qc 只服务 v1 "
                "content-pipeline 人门段，该模板已随模版退役删除；人门签字走 "
                "ticket op=sign，清场/撤销走 ticket op=cancel（t260922-10 记名清场，"
                "裸 cancel 只留给引擎件清场）。")


async def cmd_schedule_list(args: Dict[str, Any]) -> Dict[str, Any]:
    del args  # no arguments
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


# ---- t260915-12 跨项目写操作闸（客户端单点） ----
# gate 对象面：ticket 写 op 全集 + ticket-start（创建）+ cancel（终结）。
# 不设闸：query/ticket-list/ticket-query/running-tickets/schedule-list/start（读/扫描）、
# signal（260904 已退役=结构化拒收）、ticket-prune/ticket-archive-legacy（只触 closed+已
# 归档票，自带双 fail-closed，README 决策记录）。
_GATED_TICKET_OPS = ("sign", "authorize", "rework", "retry_qc", "ruling",
                     "pause", "resume", "update")
# 记名分档（review C3）：这些 op 载荷契约不收盖章字段（retry_qc=裸 who 字符串、
# update=@workflow.update 同步面、cancel/ticket-start=无 workflow 侧落点）——undeclared
# 记名只在 admin.log，查询面 cross_project_uses 列不出；回执 notice 必须按 op 说实话。
_UNSTAMPED_NOTICE_OPS = ("retry_qc", "update", "cancel", "ticket-start")


def _caller_identity(args: Dict[str, Any]) -> Dict[str, Any]:
    """调用方身份解析（arg > env > cwd 窄兜底 > none）。cwd 兜底带仓树排除（C1）：
    本进程被 spawn 于仓树内（dsh 工具链/console 插件）时 cwd 指向引擎自身=不推导；
    被真人在注册项目工作区直跑时推导（出处=cwd×注册表）。注册表读不到=cwd 兜底
    缺席（身份退回 arg/env/undeclared），不让注册表故障放大成全写面拒收。"""
    try:
        cwd = os.path.realpath(os.getcwd())
    except Exception:  # noqa: BLE001
        cwd = ""
    try:
        projects, _quarantined = load_projects_registry()  # 二元组：只消费 projects 面
    except Exception:  # noqa: BLE001
        projects = None
    return caller_gate.resolve_identity(
        str(args.get("caller_project") or ""),
        os.environ.get(CALLER_PROJECT_ENV, ""),
        cwd=cwd, exclude_trees=(os.path.realpath(str(REPO_ROOT)),),
        projects=projects)


def _registered_hint(key: str) -> Optional[bool]:
    """C2② 观测键：形状合法的 declared key 是否在注册表（不在=仍按 declared 判，
    误配显式暴露；None=undeclared/哨兵，无此键）。"""
    if not key or key == CALLER_UNDECLARED_MARK:
        return None
    try:
        lookup_project(key)
        return True
    except Exception:
        return False


def _gate_refusal(verdict: Dict[str, Any], identity: Dict[str, Any],
                  context: str = "") -> Dict[str, Any]:
    r = _err(verdict["why"] + context, KIND_CROSS_PROJECT_REFUSED)
    r.update(caller_gate.identity_receipt(identity, verdict))
    # 拒收判定不带 stamp——declared 身份从 identity.value 兜底，误配的注册表外观测键照给
    reg = _registered_hint(str(verdict.get("stamp") or identity.get("value") or ""))
    if reg is not None:
        r["caller_project_registered"] = reg
    return r


async def _write_gate(handle: Any, tid: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """ticket 写 op 闸前置（唯一入口）：读目标票 project（快照 meta）→ 判定矩阵。

    返回 {"err": 回执|None, "verdict", "keys", "snap", "stamp", "note", "notice"}——
    err 非 None=调用方直接返回（瞬时读取失败=KIND_TRANSIENT 不判越权（KI-025）、
    不存在=KIND_NOT_FOUND、身份形状非法/畸形旗/跨项目无旗=KIND_CROSS_PROJECT_REFUSED）。
    snap 一并带回（authorize 复用作落账 diff 基线，免二次查询）。"""
    try:
        identity = _caller_identity(args)
    except caller_gate.CallerIdentityError as e:
        return {"err": _err(str(e), KIND_CROSS_PROJECT_REFUSED)}
    try:
        snap = await _query_snapshot_with_retry(handle)
    except Exception as e:
        if _is_not_found_exc(e):
            return {"err": _err("工单不存在：%s（Temporal 无此 workflow）" % tid, KIND_NOT_FOUND)}
        return {"err": _err("目标票快照不可得（%s: %s）——跨项目闸前置读取失败，未执行任何"
                            "动作（瞬时抖动不判越权）；稍后重试" % (type(e).__name__, e),
                            KIND_TRANSIENT)}
    meta = (snap or {}).get("meta") or {}
    target = str(meta.get("project") or "")
    override, oerr = caller_gate.validate_override(args)
    if oerr:
        return {"err": _err(oerr, KIND_CROSS_PROJECT_REFUSED)}
    verdict = caller_gate.judge_caller(identity, target, override)
    if verdict["decision"] == "refuse":
        # 人话点名带目标票号（值守第一眼就知道动的是哪张票）
        return {"err": _gate_refusal(verdict, identity,
                                     context="（目标票 %s，属项目 %s）" % (tid, target or "（无项目面）"))}
    keys = caller_gate.identity_receipt(identity, verdict)
    reg = _registered_hint(str(verdict.get("stamp") or ""))
    if reg is not None:
        keys["caller_project_registered"] = reg
    return {"err": None, "verdict": verdict, "keys": keys, "snap": snap,
            "identity": identity, "stamp": str(verdict.get("stamp") or ""),
            "note": str((override or {}).get("reason") or ""),
            "notice": str(verdict.get("notice") or "")}


def _gate_receipt(result: Dict[str, Any], gate: Optional[Dict[str, Any]],
                  op: str) -> Dict[str, Any]:
    """闸身份键并入成功回执（外层——与拒收回执同层同形状：拒收键在 _err 顶层，成功键
    也在顶层，消费方一个层级读两种结局）；undeclared 且 op 不盖章→notice 补
    admin.log-only 口径（C3：回执文案不许超诺——不盖章 op 的记名查询面列不出）。

    t260925-08：keys 里的 injected_by∈{lane-agent, external-env} 由
    caller_gate.identity_receipt 构造（identity_src=env 时附带）——尽力面标签非安全
    断言：只回答「身份从哪个面进来」（引擎 spawn 链注入=lane-agent，手工旁路设 env=
    external-env），不回答「谁注入的」；审计不得单凭此键下「谁操作」断言。"""
    if not gate:
        return result
    out = dict(result)
    out.update(gate.get("keys") or {})
    notice = str(gate.get("notice") or "")
    if (gate.get("verdict") or {}).get("decision") == "record_undeclared" \
            and op in _UNSTAMPED_NOTICE_OPS:
        notice = (notice + "；" if notice else "") + (
            "本 op=%s 载荷契约不盖章：本次记名仅在 admin.log（identity_class=undeclared），"
            "查询面 cross_project_uses 列不出" % op)
    if notice:
        out["cross_project_notice"] = notice
    return out


async def cmd_cancel(args: Dict[str, Any]) -> Dict[str, Any]:
    wf_id = str(args.get("workflow_id") or "")
    if not wf_id:
        return _err("cancel 需要 workflow_id")
    reason = str(args.get("reason") or "client.py cancel")
    # t260915-12：cancel 进闸（终结算写操作）。前置读目标 ProjectKey SA——瞬时失败=
    # 结构化拒收可重试（C2①：绝不 fail-open 静默放行 terminate）；无项目 SA 的引擎件
    # （dispatcher-scan 等）=不设闸放行，identity_class=engine-internal 照记 admin.log。
    try:
        identity = _caller_identity(args)
    except caller_gate.CallerIdentityError as e:
        return _err(str(e), KIND_CROSS_PROJECT_REFUSED)
    override, oerr = caller_gate.validate_override(args)
    if oerr:
        return _err(oerr, KIND_CROSS_PROJECT_REFUSED)
    client = await _connect()
    handle = client.get_workflow_handle(wf_id)
    try:
        desc = await handle.describe()
    except Exception as e:
        if _is_not_found_exc(e):
            return _err("cancel 目标不存在：%s（%s: %s）" % (wf_id, type(e).__name__, e),
                        KIND_NOT_FOUND)
        return _err("cancel 目标读取失败（%s: %s）——跨项目闸前置读取失败，未执行任何动作；"
                    "稍后重试" % (type(e).__name__, e), KIND_TRANSIENT)
    target = str(desc.typed_search_attributes.get(
        SearchAttributeKey.for_keyword(PROJECT_SA_NAME)) or "")
    verdict = caller_gate.judge_caller(identity, target, override)
    if verdict["decision"] == "refuse":
        return _gate_refusal(verdict, identity,
                             context="（目标 %s，属项目 %s）" % (wf_id, target or "（无项目面）"))
    gate = {"verdict": verdict, "notice": str(verdict.get("notice") or ""),
            "keys": caller_gate.identity_receipt(
                identity, verdict,
                identity_class="engine-internal" if not target else "")}
    try:
        await handle.terminate(reason=reason)
    except Exception as e:  # already finished / missing etc. always produce a structured receipt, never a stack trace
        return _err(f"terminate 失败：{type(e).__name__}: {e}")
    return _gate_receipt(_ok({"workflow_id": wf_id, "terminated": True, "reason": reason}),
                         gate, "cancel")


# t260922-10 cancel 幂等闸口径（review 条3）：与 _EXEC_ALIVE_OK 对照着读——COMPLETED
# 虽在 _EXEC_ALIVE_OK（那是「非失败类」白名单，供 _is_failed_exec 用），但对 cancel 而
# 言 COMPLETED=票已 closed 终态（无需清场）；活票只有 RUNNING 与 CONTINUED_AS_NEW
# （巡检 watcher 换代中，属未收口——KI-025 红线：不许把活报成终）。
_TICKET_CANCEL_ALIVE = ("RUNNING", "CONTINUED_AS_NEW")


async def cmd_ticket_cancel(args: Dict[str, Any]) -> Dict[str, Any]:
    """记名单票终结（t260922-10）：ticket.py op=cancel 的引擎侧入口——terminate 包装成
    带身份、带理由的记名操作（裸 cmd_cancel 的记名只在 admin.log，票面查不到是谁、
    为什么；本入口补票面留痕）。次序纪律（宿主令 260922「留痕必须先写、后终结」，
    与同批 A3.5 票教训同源）：

      参数校验 → describe → 幂等闸 → 跨项目闸(_write_gate) → 先 signal cancel_notice
      （留痕入事件历史）→ 后 terminate(reason=同一串)

    次序的机械保证：signal 事件由 server 先落事件历史，terminated 事件必然追加其后
    ——事件历史里 cancel_notice（载荷含 who+reason 原文）恒先于 terminated（同串
    reason）。幂等（验收③）：已终态票（执行状态不在 _TICKET_CANCEL_ALIVE）→ ok 回执
    already_terminal，不跑闸、不写任何东西；CONTINUED_AS_NEW 属未收口，不得谎报已终态。
    回执诚实口径（review 条1，KI-025 家族）：delivered:true=「signal 已落事件历史」，
    不承诺 handler 已执行（KI-081：老 worker 静默丢新信号——对账面不依赖 handler 承接，
    事件历史由 server 落账）；终态后票面查询面不可得，权威对账=workflow 事件历史
    （cancel_notice 先于 terminated、载荷含 who+reason）×admin.log 同串（本回执即
    _emit→audit_call 的落账源，summary 含同串 reason）；票面 log/timeline/
    cross_project_uses 是终结前窗口尽力面。巡检票（inspection workflow 类）无本信号
    handler：仅事件历史+admin.log 留痕。拒绝=零副作用：参数/身份/越权旗/闸任一拒收
    都发生在任何写动作之前（被拒调用仍由 _emit 记 admin.log——留痕在运维面不在票面）。
    裸入口 cmd_cancel（workflow_id 口径，引擎件清场）保持原样，两入口不混用。"""
    tid = str(args.get("ticket_id") or args.get("id") or "")
    who = str(args.get("who") or "").strip()
    raw_reason = args.get("reason")
    if raw_reason is not None and not isinstance(raw_reason, str):
        # 非串 reason 不做 str() 静默归一（t260922-10 场景②R4 同口径）：["x"] 归一会
        # 变成 "['x']" 非空放行——清场理由是对账锚，类型畸形=结构化拒收零副作用。
        return _err("ticket-cancel 的 reason 需为字符串（收到 %s）——清场理由必须逐字"
                    "可对账，非串不做静默归一" % type(raw_reason).__name__)
    reason = str(raw_reason or "").strip()
    if not tid:
        return _err("ticket-cancel 需要 ticket_id")
    if not who:
        return _err("ticket-cancel 需要 who（操作人必填非空——记名清场不留 op-local）")
    if not reason:
        return _err("ticket-cancel 需要 reason（清场理由必填非空——终结后 admin.log 与 "
                    "workflow 事件历史按此串精确对账，空=结构化拒收）")
    if len(reason) > CROSS_PROJECT_NOTE_LIMIT:
        return _err("ticket-cancel reason 超限（%d > %d 字符）——拆短后重试（建议 ≤300 "
                    "字符，保跨项目记名条目 cross_project_uses 全文入账）"
                    % (len(reason), CROSS_PROJECT_NOTE_LIMIT))
    client = await _connect()
    handle = client.get_workflow_handle(tid)
    try:
        desc = await handle.describe()
    except Exception as e:
        if _is_not_found_exc(e):
            return _err("工单不存在：%s（Temporal 无此 workflow）" % tid, KIND_NOT_FOUND)
        return _err("目标读取失败（%s: %s）——未执行任何动作，稍后重试"
                    % (type(e).__name__, e), KIND_TRANSIENT)
    exec_status = desc.status.name if desc.status is not None else ""
    # 幂等闸（验收③）：非活=已终态 → 明确回「已终态」，零改动（也不跑闸——闸护的是写，
    # 本分支不写任何东西；closed 票无需清场）。
    if exec_status not in _TICKET_CANCEL_ALIVE:
        return _ok({"ticket_id": tid, "already_terminal": True,
                    "exec_status": exec_status or "未知",
                    "reason": reason, "who": who,
                    "note": "已终态（%s），未执行任何动作（幂等回执，重试安全）"
                            % (exec_status or "未知")})
    # 跨项目闸：与既有写 op 同一判定矩阵（_write_gate 三态，拒收单一出口）；快照瞬时
    # 不可得=transient 拒收不终结（fail-closed，C2① 同口径——绝不无闸放行 terminate）。
    gate = await _write_gate(handle, tid, args)
    if gate["err"] is not None:
        return gate["err"]
    # 先留痕：cancel_notice 事件先落事件历史（载荷含 who+reason 原文与盖章值）。
    # 投递失败=结构化 _err 且明确「未终结」（T9：先留痕失败即不终结，重试安全）。
    try:
        await handle.signal("cancel_notice",
                            {"who": who, "reason": reason,
                             "caller_project": gate["stamp"] if gate else "",
                             "cross_project_note": gate["note"] if gate else ""})
    except Exception as e:
        return _err("cancel_notice 留痕信号投递失败：%s: %s——未执行终结（先留痕失败"
                    "即不终结）；零票面副作用，稍后重试" % (type(e).__name__, e))
    # 后终结：terminate 的 reason=同一 reason 串（与信号载荷、回执三方同串，== 精确对账）。
    try:
        await handle.terminate(reason=reason)
    except Exception as e:
        return _err("terminate 失败：%s: %s——cancel_notice 记名信号已入事件历史，本次"
                    "未终结（可能自然完单/已被终结）；重试安全（已终态将回幂等回执）"
                    % (type(e).__name__, e))
    return _gate_receipt(_ok({"ticket_id": tid, "terminated": True,
                              "reason": reason, "who": who,
                              "signal": "cancel_notice", "delivered": True,
                              "receipt_note": ("delivered=signal 已落事件历史（不承诺 "
                                               "handler 已执行，KI-081）；终态后票面查询面"
                                               "不可得，权威对账=workflow 事件历史"
                                               "（cancel_notice 先于 terminated、载荷含 "
                                               "who+reason）×admin.log 同串；票面 log/"
                                               "timeline/cross_project_uses 为终结前窗口"
                                               "尽力面")}),
                         gate, "ticket-cancel")


async def cmd_ticket_close_out(args: Dict[str, Any]) -> Dict[str, Any]:
    """人工记名收口（t260927 宿主实报④；ticket.py op=close_out 的引擎侧入口）。

    与 ticket-cancel 同款纪律、不同语义：
      · cancel = 记名**清场**（理由=为什么废掉）；
      · close_out = 记名**收口**（理由=工作已完成的依据）——用于「票被误判 blocked、
        工作其实已经干完」这一类：A3.5 护栏把 blocked 态的 `status=closed` 堵死了，
        于是完成态没有任何正路能收口、看板永不归零。

    次序同 cancel（宿主令 260922「留痕必须先写、后终结」）：参数校验 → describe →
    幂等闸 → 跨项目闸（_write_gate）→ 先 signal close_out_notice（who/reason 原文进
    事件历史，handler 写票面 close_out 记录并把 status 置 closed）→ 后 terminate
    （reason=带固定前缀的同一串，终态面与 admin.log 一眼可辨「人工收口」而非「清场」）。

    诚实口径：`delivered:true` 只承诺「信号已落事件历史」，不承诺 handler 已执行
    （KI-081 老 worker 静默丢新信号；对账面不依赖 handler 承接）；被拒调用零副作用。
    """
    tid = str(args.get("ticket_id") or args.get("id") or "")
    who = str(args.get("who") or "").strip()
    raw_reason = args.get("reason")
    if raw_reason is not None and not isinstance(raw_reason, str):
        return _err("ticket-close-out 的 reason 需为字符串（收到 %s）——收口理由是记名"
                    "对账锚，非串不做静默归一" % type(raw_reason).__name__)
    reason = str(raw_reason or "").strip()
    if not tid:
        return _err("ticket-close-out 需要 ticket_id")
    if not who:
        return _err("ticket-close-out 需要 who（操作人必填非空——记名收口不留 op-local）")
    if not reason:
        return _err("ticket-close-out 需要 reason（收口依据必填非空：说清凭什么认定工作"
                    "已完成——这是事后审计的唯一锚点，空=结构化拒收）")
    if len(reason) > CROSS_PROJECT_NOTE_LIMIT:
        return _err("ticket-close-out reason 超限（%d > %d 字符）——拆短后重试"
                    % (len(reason), CROSS_PROJECT_NOTE_LIMIT))
    client = await _connect()
    handle = client.get_workflow_handle(tid)
    try:
        desc = await handle.describe()
    except Exception as e:
        if _is_not_found_exc(e):
            return _err("工单不存在：%s（Temporal 无此 workflow）" % tid, KIND_NOT_FOUND)
        return _err("目标读取失败（%s: %s）——未执行任何动作，稍后重试"
                    % (type(e).__name__, e), KIND_TRANSIENT)
    exec_status = desc.status.name if desc.status is not None else ""
    if exec_status not in _TICKET_CANCEL_ALIVE:
        return _ok({"ticket_id": tid, "already_terminal": True,
                    "exec_status": exec_status or "未知", "reason": reason, "who": who,
                    "note": "已终态（%s），未执行任何动作（幂等回执，重试安全）"
                            % (exec_status or "未知")})
    gate = await _write_gate(handle, tid, args)
    if gate["err"] is not None:
        return gate["err"]
    try:
        await handle.signal("close_out_notice",
                            {"who": who, "reason": reason, "kind": "close_out",
                             "caller_project": gate["stamp"] if gate else "",
                             "cross_project_note": gate["note"] if gate else ""})
    except Exception as e:
        return _err("close_out_notice 留痕信号投递失败：%s: %s——未执行终结（先留痕失败"
                    "即不终结）；零票面副作用，稍后重试" % (type(e).__name__, e))
    term_reason = close_out_terminate_reason(reason)
    try:
        await handle.terminate(reason=term_reason)
    except Exception as e:
        return _err("terminate 失败：%s: %s——close_out_notice 记名信号已入事件历史，"
                    "本次未终结（可能自然完单/已被终结）；重试安全（已终态将回幂等回执）"
                    % (type(e).__name__, e))
    return _gate_receipt(_ok({"ticket_id": tid, "terminated": True,
                              "reason": reason, "terminate_reason": term_reason,
                              "who": who, "signal": "close_out_notice", "delivered": True,
                              "receipt_note": ("delivered=signal 已落事件历史（不承诺 "
                                               "handler 已执行，KI-081）；权威对账=事件"
                                               "历史（close_out_notice 先于 terminated）"
                                               "×admin.log；terminate_reason 前缀"
                                               "%r 即人工收口的可辨标记"
                                               % CLOSE_OUT_PREFIX)}),
                         gate, "ticket-close-out")


async def cmd_ticket(args: Dict[str, Any]) -> Dict[str, Any]:
    """Ticket stage machine (step 2): exposes only legal advance entries, no set-stage /
    force_stage.

    op ∈ advance / accept / rework / update / dispatch-next / sign / query /
    ledger_rebuild.
    The first five are workflow updates (synchronous result + into the immutable
    history); sign is a human approval signature; query is read-only;
    ledger_rebuild (t260928-13) is engine-local ops tooling: reads the ticket
    snapshot and regenerates the ticket's event-ledger lines from its timeline
    (no workflow mutation, no ticket-face write).
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
            # Running pulse (t260825-03): the pending activity heartbeat; non-RUNNING or
            # no heartbeat → None
            "pulse": _pulse_from_desc(desc) if running else None,
        })

    # t260915-12：写 op 过跨项目闸（目标 project←快照 meta；stamps 随载荷下发，
    # workflow 侧消费盖章值做第二道校验+记名）。读 op（query）不设闸。
    gate = None
    if op in _GATED_TICKET_OPS:
        gate = await _write_gate(handle, tid, args)
        if gate["err"] is not None:
            return gate["err"]

    if op == "sign":
        raw = args.get("input") or {}
        if not isinstance(raw, dict):
            raw = args
        sig = Signature(
            who=str(raw.get("who") or ""),
            gate=str(raw.get("gate") or ""),
            decision=str(raw.get("decision") or "approve"),
            note=str(raw.get("note") or ""),
            # t260915-12 盖章：调用方传入的 caller_project 已被解析结果盖写（不许自认）。
            caller_project=gate["stamp"] if gate else "",
            cross_project_note=gate["note"] if gate else "",
        )
        await handle.signal("sign", sig)  # a signal with the same name on old and new classes; sending by name serves both
        return _gate_receipt(_ok({"ticket_id": tid, "signal": "sign", "gate": sig.gate,
                                  "decision": sig.decision, "who": sig.who, "delivered": True}),
                             gate, op)

    if op == "authorize":
        # t260912-03：人授权例外通道（受保护路径 / 仲裁上限）——**唯一入口＝sign 信号面**
        # （Signature.authorize 载荷；此处不新开信号，与签字同源同审计面）。本侧只做
        # payload 归一（expires 收 ISO8601|epoch 秒两形）+ 结构性拒收（畸形=结构化 _err，
        # 不进事件历史）；who/scope/reason/上限与反自签的权威判定在 workflow intake
        # （authz_gates.validate_authorization，refused 可观测）。
        # t260913-01：投递前先验对端 worker 的 sign 信号面指纹（旧 worker 会把 authorize
        # 当未知字段解码静默丢弃——本票事故根因），缺失/漂移/不在=拒发并点名检查；
        # 投递后有界轮询确认落账三态（landed/refused/unconfirmed）——delivered=true
        # 从此只代表「送达 server」，端到端结果看 landing 键。既有回执键全保留。
        auth, aerr = normalize_authorize_args(args)
        if auth is None:
            return _err(aerr)

        # 基线快照：同时供给模板分叉（C2）与落账 diff 的基线。拿不到基线不盲投
        # （无法区分旧账/新账），按其异常类别结构化报错（工单不存在≠瞬时抖动）。
        # t260915-12：基线复用闸前置读取的同一份快照（_write_gate 已含同款
        # not_found/transient 分级，不二次查询）。
        snap0 = gate["snap"]
        wf_class = str((snap0 or {}).get("workflow_class") or "")
        template_id = str((snap0 or {}).get("template_id") or "")

        # face 前置检查（拒发）：absent/mismatch/unreachable/face_error 一律不投。
        state, detail, _out = await _probe_sign_face(handle)
        if state != "match":
            kind, msg = authz_face_refusal(state, detail, wf_class, template_id)
            return _err(msg, kind)

        baseline_authz = _authz_entries(snap0)
        baseline_refused = _refused_entries(snap0)
        sig = Signature(who=auth.who, gate=AUTHZ_SIGNAL_GATE_MARKER, decision="approve",
                        authorize=auth,
                        # t260915-12 盖章：授权签发同样过项目归属闸（stamps 由闸解析）。
                        caller_project=gate["stamp"] if gate else "",
                        cross_project_note=gate["note"] if gate else "")
        try:
            await handle.signal("sign", sig)  # 同一 sign 信号面（不得新开旁路）
        except Exception as e:
            return _err("授权信号投递失败：%s: %s——信号未投出（票面无变化）；工单可能已完单"
                        "或连接异常" % (type(e).__name__, e), KIND_AUTHZ_SIGNAL_FAILED)

        state2, payload, last_snap = await _await_authz_landing(
            handle, baseline_authz, baseline_refused, auth.who, auth.kind, int(auth.expires))
        face_keys = {"ticket_id": tid, "signal": "sign(authorize)", "kind": auth.kind,
                     "who": auth.who, "scope": list(auth.scope),
                     "expires": auth.expires, "delivered": True}
        if state2 == "landed":
            return _gate_receipt(_ok({**face_keys, "landing": "landed",
                                      "authorization": payload}), gate, op)
        if state2 == "refused":
            return _gate_receipt(_ok({**face_keys, "landing": "refused",
                                      "refused_why": payload}), gate, op)
        plain = ""
        for it in _refused_entries(last_snap):
            if str(it.get("want") or "") != "sign(authorize)":
                plain = "want=%s why=%s" % (it.get("want"), it.get("why"))
                break
        hint = "face=match 但预算内既无落账也无 sign(authorize) 拒收"
        if plain:
            hint += "；却出现普通签字拒收（%s）——与 face=match 矛盾，优先核该票 worker 血统" % plain
        return _err("授权送达确认超时（%s）。请核该票专属 worker（data/worker-<票号>.pid.meta"
                    " 的 repo_root 必须本仓，KI-033）并重启后重试" % hint,
                    KIND_AUTHZ_LANDING_UNCONFIRMED)

    if op == "rework":
        # v2: rework = a signal (re-run from the target stage)
        note = str(args.get("note") or "")
        if not note:
            return _err("rework 需要 note（返工原因）")
        req = ReworkRequest(who=str(args.get("who") or "op-local"),
                            target_stage=str(args.get("to_stage") or ""),
                            note=note,
                            # t260915-12 盖章（同 sign 家族契约）。
                            caller_project=gate["stamp"] if gate else "",
                            cross_project_note=gate["note"] if gate else "")
        await handle.signal("rework", req)
        return _gate_receipt(_ok({"ticket_id": tid, "signal": "rework",
                                  "target_stage": req.target_stage, "delivered": True}),
                             gate, op)

    if op == "retry_qc":
        # KI-067（t260910-06）：retry_qc 的 CLI 正规通道（signal 子命令退役后唯一
        # 非直连入口）。workflow 侧契约（base.py retry_qc(self, who: str)）只收
        # **裸字符串**：本侧只转发 who；note 非空显式拒收（静默蒸发不可接受），
        # 带话走 update pending_add 或 ruling 注入。包装层只加审计不加权力。
        if str(args.get("note") or "").strip():
            return _err("retry_qc 不收 note（workflow 契约只收 who）——带话走 "
                        "ticket op=update 的 pending_add，或 op=ruling 注入裁决")
        who = str(args.get("who") or "op-local")
        await handle.signal("retry_qc", who)
        # t260915-12：retry_qc 载荷契约只收裸 who（base.py 契约），不盖章——undeclared
        # 记名仅 admin.log（_gate_receipt 按档补 notice，C3 不许谎称查询面可列）。
        return _gate_receipt(_ok({"ticket_id": tid, "signal": "retry_qc", "who": who,
                                  "delivered": True}), gate, op)

    if op == "ruling":
        # KI-053: host ruling injection — the official channel for human opinions,
        # sendable in any state (blocked included).
        # Sending a ruling does not automatically wake a blocked: the re-run still needs
        # a retry_qc, and the next prompt picks up the ruling (the build_stage_prompt
        # injection surface).
        note = str(args.get("note") or "")
        if not note.strip():
            return _err("ruling 需要 note（裁决内容，非空）")
        req = HostRulingRequest(who=str(args.get("who") or "op-local"), note=note,
                                # t260915-12 盖章（同 sign 家族契约）。
                                caller_project=gate["stamp"] if gate else "",
                                cross_project_note=gate["note"] if gate else "")
        await handle.signal("host_ruling", req)
        return _gate_receipt(_ok({"ticket_id": tid, "signal": "host_ruling",
                                  "who": req.who, "delivered": True}), gate, op)

    if op in ("pause", "resume"):
        # t260908-01：段间暂停/恢复（与 sign/rework/ruling 同族的信号通道）。
        # 幂等反馈可辨在 workflow 侧（重复 pause / 空态 resume / 畸形 payload 落
        # refused，snapshot 可观测）；本侧只对「对端不可达/已终结」报结构化 _err。
        # payload 兼容两形：input 包装（node.ts/集成场景先例同 sign）与顶层直给。
        raw = args.get("input")
        if not isinstance(raw, dict):
            raw = args
        who = str(raw.get("who") or "op-local")
        note = str(raw.get("note") or "")
        req = PauseRequest(who=who, note=note,
                           # t260915-12 盖章（同 sign 家族契约）。
                           caller_project=gate["stamp"] if gate else "",
                           cross_project_note=gate["note"] if gate else "")
        await handle.signal(op, req)
        return _gate_receipt(_ok({"ticket_id": tid, "signal": op, "who": req.who,
                                  "delivered": True}), gate, op)

    if op in ("advance", "accept", "dispatch-next"):
        return _err("v2 引擎（模版即代码）已取消 %s：workflow 过门自动推进，"
                    "验收=事后看产物（query 快照的 results/handoffs）；"
                    "打回用 rework，blocked 重跑用 ticket op=retry_qc" % op)

    if op == "update":
        # v2 base.py's update handler (called by name; the same-named handler on the old
        # class left with that class)
        r = await handle.execute_update(
            "update_status", args=[str(args.get("status") or ""),
                                   str(args.get("note") or ""),
                                   str(args.get("pending_add") or ""),
                                   args.get("book_path")])
        # t260915-12：update=@workflow.update 同步面，载荷不盖章——undeclared 记名仅
        # admin.log（_gate_receipt 按档补 notice，C3）。
        return _gate_receipt(_ok(r), gate, op)

    if op == "ledger_rebuild":
        # t260928-13：事件账本重建（engine-local ops 面，零 workflow 变更/零票面写）。
        # 身份口径（review 条件1）：project/ticket 一律取自**票面快照**（workflow
        # 侧盖章真源），绝不信调用方 args——否则调用方可把行重建进别项目的账本文件
        # （t260915-12「调用方身份只盖章不许自认」同源纪律）。账本未声明/停用不阻
        # 断重建（rebuild 走 skip_enabled_gate 的补洞路径：账本是时间线的派生投影，
        # 停用只是停增量，不否定补历史）。
        snap = await handle.query("snapshot")
        if not isinstance(snap, dict) or not snap:
            return _err("ledger_rebuild 拒收：票面快照不可得（票不存在或非 v2 工作流）",
                        KIND_NOT_FOUND)
        meta = snap.get("meta") or {}
        project = str((meta.get("project") if isinstance(meta, dict) else "") or "")
        if not project:
            return _err("ledger_rebuild 拒收：快照缺 project（票面无项目归属，无法定位账本）")
        from event_ledger import ledger_rebuild
        report = ledger_rebuild(
            project,
            str(snap.get("ticket_id") or tid),      # ticket 同取快照（handle.id 在场兜底）
            snap.get("timeline") or [],
            workflow_class=str(snap.get("workflow_class") or ""),
            template_id=str(snap.get("template_id") or ""),
            marks=snap.get("ledger_marks") or [])   # [R-merge]：marks 现役轨
        return _ok({"ticket_id": tid, "project": project, **report})

    return _err("未知工单操作 %r（可用：rework=打回 / ruling=宿主裁决注入 / "
                "authorize=人授权签发（sign 信号面） / retry_qc=blocked 重跑 / "
                "pause|resume=段间暂停·恢复 / update=更新 / sign=签字 / query=查询 / "
                "ledger_rebuild=事件账本重建（t260928-13）；"
                "记名单票终结（清场）=子命令 ticket-cancel，t260922-10）" % op)


# ---------- M11 v2: ticket-start / ticket-list / ticket-query ----------

async def cmd_ticket_start(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a v2 ticket: template id → workflow class (the shared.TEMPLATE_CLASS_NAMES
    mapping), with every business attribute pinned into TicketInput (state lives only in
    the workflow, no JSON projection).
    epic-linkage: when args.epic is given it is strictly validated (code shape + the
    existence of notes/epics/<code>.md); if valid, the workflow gets the EpicCode search
    attribute and can be fished out by querying EpicCode="...". """
    tpl = str(args.get("template_id") or args.get("workflow") or "")
    cls = TEMPLATE_CLASSES.get(tpl)
    if cls is None:
        # t260924-04：未知模板文案附项目外置模板拒收明细（fail-closed 点名：检查项＋
        # 双方/缺什么）。明细段置于「可用：」段之前（收窄守卫 C 半按 rsplit('可用：')
        # 判列表面）。已知 project 则只点名该项目的拒收。
        from shared import project_template_rejection_note
        _note = project_template_rejection_note(str(args.get("project") or ""))
        _seg = ("；%s；" % _note) if _note else ""
        return _err("未知模板 %r（%s可用：%s）"
                    % (tpl, _seg, "、".join(sorted(TEMPLATE_CLASSES))))
    tid = str(args.get("ticket_id") or args.get("id") or "")
    if not tid:
        return _err("ticket-start 需要 ticket_id")
    project = str(args.get("project") or "")
    if not project:
        return _err("ticket-start 需要 project（projects.yaml 注册表 key，无默认值）——"
                    "无 project 即拒收：泳道落仓禁止退化为「由执行 worker 的 REPO_ROOT 决定」"
                    "的相对路径（t260904-01 首开脑裂形态，宁可拒收不静默降级）")
    # Hard gate (KI-032): as soon as a project arrives, self-check the machine-level
    # registry to anchor project_root, same source as ticket.py create (single source of
    # truth = the shared loader; the SANDBAR_PROJECTS_DIR env override semantics are
    # preserved). Unanchored (unknown key / quarantined entry / empty registry) = refuse
    # at creation — the workspace produced by this bare entry must be an absolute path
    # anchored to the project's main directory, decoupling the landing repo from the
    # executing worker.
    try:
        proj = lookup_project(project)
    except ValueError as e:
        return _err("ticket-start 拒收（project 未锚定，开票走正规入口请先注册项目）：%s" % e)
    project_root = str(proj["dirs"][0])
    # t260915-12：创建面进闸（caller 身份 vs 目标 args.project）。创建载荷（TicketInput）
    # 不盖章（钉死业务属性面不掺调用方身份）——记名分档=admin.log + 回执（C3）。
    try:
        identity = _caller_identity(args)
    except caller_gate.CallerIdentityError as e:
        return _err(str(e), KIND_CROSS_PROJECT_REFUSED)
    override, oerr = caller_gate.validate_override(args)
    if oerr:
        return _err(oerr, KIND_CROSS_PROJECT_REFUSED)
    verdict = caller_gate.judge_caller(identity, project, override)
    if verdict["decision"] == "refuse":
        return _gate_refusal(verdict, identity,
                             context="（目标票 %s，属项目 %s）" % (tid, project))
    gate = {"verdict": verdict, "notice": str(verdict.get("notice") or ""),
            "keys": caller_gate.identity_receipt(identity, verdict)}
    reg = _registered_hint(str(verdict.get("stamp") or ""))
    if reg is not None:
        gate["keys"]["caller_project_registered"] = reg
    # Epic linkage (epic-linkage): the single strict-validation point for --epic — a
    # code-shape whitelist + the epic archive existing. The validation directory comes
    # from resolve_epics_dir(project) — anchored to the project registry entry's main
    # directory notes/epics (same source as the workbench UI's resolveEpicsDir); the
    # SANDBAR_EPICS_DIR env wins, keeping the self-test semantics. Empty = no epic
    # linkage (allowed).
    try:
        epic = validate_epic_code(str(args.get("epic") or ""), resolve_epics_dir(project))
    except ValueError as e:
        return _err(str(e))
    # Lane-parameter derivation + validation single point (consolidated after the three
    # incidents t260824-04/-10/-11): for lane=worktree, workspace/worktree/branch are
    # derived when absent, filled in one by one, and refused outright on inconsistency
    # or a bad shape — no more passing empty fields through for prepare_workspace to
    # silently skip, leaving the agent running in an empty directory.
    try:
        lane, workspace, worktree, branch = derive_lane_workspace(
            tid, cls.TEMPLATE_LANE,
            lane=str(args.get("lane") or ""),
            workspace=args.get("workspace") if isinstance(args.get("workspace"), dict) else None,
            worktree=str(args.get("worktree") or ""),
            branch=str(args.get("branch") or ""),
            template_workspace_dir=bool(getattr(cls, "TEMPLATE_WORKSPACE_DIR", False)),
            project_root=project_root,
            # Ticket B (t260907-06): multi-repo projects (parent directory as root) get a
            # multi-repo lane derived from write-set ownership; single-repo projects
            # (project root == repo root) are silently ignored inside derive, zero
            # regression on the old path.
            repo_write_set=(args.get("write_set")
                            if isinstance(args.get("write_set"), list) else None))
    except ValueError as e:
        return _err("ticket-start 参数非法：%s" % e)
    # t260908-02: derive's mixed/multi-repo shape embeds repo_worktrees (list[dict])
    # inside ws, while TicketInput.workspace is annotated Dict[str, str] — payload
    # decoding would certainly blow up (confirmed by t260907-13). Split at this file's
    # only call site: the detail moves to the first-class repo_worktrees field, and
    # workspace returns to a pure {type, path} (explicit shape, encode and decode sides
    # in sync).
    repo_worktrees = []
    if isinstance(workspace, dict):
        rws = workspace.pop("repo_worktrees", None)
        if isinstance(rws, list) and rws:
            repo_worktrees = [dict(e) for e in rws if isinstance(e, dict)]
    # Hard-gate companion (KI-032): an explicitly given absolute workspace/worktree must
    # land inside the registered directory (the same judgment as ticket.py create's
    # _check_paths_under_project, so the bare entry cannot bypass the anchor by explicitly
    # passing another project's or some unrelated path). Relative paths are not stopped
    # (already covered by the project_root anchoring semantics).
    try:
        check_paths_under_project(proj, workspace, worktree)
    except ValueError as e:
        return _err("ticket-start 参数非法：%s" % e)
    # 保险丝A（t260910-03，开票拒收）：写集条目命中成员仓路径（resolve_repos_for_paths
    # 归属非项目根本体）而 repo_worktrees 为空 → fail-closed 拒收并点名条目（显式
    # workspace/worktree 也不能绕过——判据是写集归属不是派生路径）。归属解析自身的
    # ValueError（逃逸/嵌套仓/条目畸形）同样拒收，绝不静默放行。单仓项目恒放行。
    try:
        fuse_a_err = multirepo_fuse_a_error(project_root,
                                            args.get("write_set"), repo_worktrees)
    except ValueError as e:
        return _err("ticket-start 拒收（写集归属解析 fail-closed）：%s" % e)
    if fuse_a_err:
        return _err(fuse_a_err)
    overrides: Dict[str, Any] = {}
    for sid, g in (args.get("gate_overrides") or {}).items():
        if isinstance(g, dict):
            from shared import GateSpec
            overrides[str(sid)] = GateSpec(
                stage=str(g.get("stage") or sid), tool=str(g.get("tool") or "qc_run"),
                args=dict(g.get("args") or {}), label=str(g.get("label") or ""),
                cmd=g.get("cmd") or None)
    # Write-set lifecycle (t260829-07 A1): the single refusal point for an empty write
    # set — a ticket with an empty write set leaves the agent without its whitelist
    # guardrail and breaks UI-ticket judgment. The way out is written into the refusal
    # message; never silently let it through.
    ok_ws, ws_flags, ws_err = validate_write_set_args(
        args.get("write_set"), bool(args.get("allow_empty_write_set")))
    if not ok_ws:
        return _err(ws_err)
    # Gate 1, the background-files gate (t260904-18; the ticket-reference iron rule "an
    # uncommitted note must not become a ticket"): background files referenced on the
    # ticket must be committed and clean (HEAD state — the lane reads a frozen HEAD copy,
    # so a dirty modification is invisible to the agent). Inserted before _connect(): the
    # refusal path does not depend on Temporal being reachable. refs absent = no
    # validation (in-flight existing tickets are not retroactively checked).
    refs_raw = args.get("refs")
    refs = [str(x).strip() for x in refs_raw] if isinstance(refs_raw, list) else refs_raw
    try:
        ok_refs, refs_err = validate_background_refs(refs, project_root)
    except Exception as e:  # an exception in the validator itself also refuses (fail-closed, never silently allowed)
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
        repo_worktrees=repo_worktrees,
        # t260910-08: the project root travels into the workflow so meta.project_root
        # exists and WorkspacePrep's fallback ring ③ (write_set+project_root derivation)
        # stays alive — the t260910-07 incident's second dead feed
        project_root=project_root,
        worktree=worktree,
        branch=branch,
        base_ref=str(args.get("base_ref") or ""),
        proposal_id=str(args.get("proposal_id") or ""),
        book_path=str(args.get("book_path") or ""),
        write_set=[str(x) for x in (args.get("write_set") or [])],
        no_file_changes=bool(ws_flags.get("no_file_changes")),
        acceptance_extra=[str(x) for x in (args.get("acceptance_extra") or [])],
        deliverables=str(args.get("deliverables") or ""),
        # M16: body = the original user request (user_request kept verbatim, explicit
        # and preferred; falls back to body when absent); spec independent
        user_request=str(args.get("user_request") or ""),
        spec=str(args.get("spec") or ""),
        body=str(args.get("body") or ""),
        created=int(args.get("created") or 0),
        gate_overrides=overrides,
        # t260911-03 路径闸总开关 + KI-124（t260925-23）声明化：不再硬编码模板名——
        # 改读模板类声明（DevLaneWorkflow.PATH_GATE=True 保持现行为；项目外置模板在
        # 自己的模板类声明 PATH_GATE / PATH_GATE_RULES 即可开闸并登记段×允许面规则，
        # 声明合法性由加载口深检把守）。派单钉死进输入（replay 稳定）；老在途票的
        # 已记录输入无此字段 → 永远 False，不追溯。
        path_gate=bool(getattr(cls, "PATH_GATE", False)),
        path_gate_rules=dict(getattr(cls, "PATH_GATE_RULES", None) or {}),
    )
    client = await _connect()
    try:
        # 每工单专属队列（260824）：workflow 只被专属队列（LEGACY 旧前缀 suyou-ticket-<tid>）上的 worker 执行，  # naming-compat
        # 共享池 worker 抢不到——版本错开的 worker 不再交叉投毒。专属 worker 由 ticket.py 拉起。
        handle = await client.start_workflow(
            cls.run, inp, id=tid, task_queue=ticket_task_queue(tid),
            search_attributes=ticket_search_attributes(project, epic))
    except Exception as e:
        if "AlreadyStarted" in type(e).__name__:
            return _err("工单 %s 已在 Temporal 存在（单例，AlreadyStarted）" % tid)
        # Epic acceptance criterion 4: an environment that has not registered EpicCode
        # must fail loudly, never silently drop the label.
        # The signature match does not pin one exact wording (temporalite/temporal-server
        # phrasing may differ): any error containing the SA name plus "unregistered /
        # not defined"-style wording is recognized, and a fix is suggested.
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
    return _gate_receipt(_ok({
        "id": tid, "workflow_id": handle.id, "run_id": handle.result_run_id,
        "template": tpl, "workflow_class": cls.__name__,
        "project": project, "epic": epic,
        "stage": first.id, "stage_state": "running", "role": first.role,
        "status": "dispatched", "engine": ENGINE_V2,
    }), gate, "ticket-start")


def normalize_authorize_args(args: Dict[str, Any]):
    """authorize 载荷归一（纯函数，单测直调）：返回 (HumanAuthorization|None, error)。

    - 两形兼容：input 包装（node.ts/集成场景先例同 sign）与顶层直给；
    - expires 收 epoch 秒（int/数字串）或 ISO8601（含 Z 尾），畸形=结构化错误；
    - scope 收数组或逗号分隔串；kind/scope/expires/who 的结构性拒收在此（人话错误），
      who/scope/reason 的上限与反自签权威判定在 workflow intake（authz_gates）。
    """
    raw = args.get("input")
    if not isinstance(raw, dict) or not raw:
        raw = args          # input 包装与顶层直给两形（空 dict 视同未包装）
    kind = str(raw.get("kind") or "")
    if kind not in AUTH_KINDS:
        return (None, "authorize 需要 kind ∈ %s（收到 %r）" % ("|".join(AUTH_KINDS), kind))
    scope = raw.get("scope")
    if isinstance(scope, str):
        scope = [s for s in scope.split(",") if s.strip()]
    if not isinstance(scope, list) or not scope:
        return (None, "authorize 需要非空 scope（数组，或逗号分隔串）：路径/目录前缀 "
                      "（protected_path）或本票票号（arbitration_verdict）")
    exp_raw = raw.get("expires")
    exp = exp_raw if isinstance(exp_raw, int) else None
    if exp is None:
        s_exp = str(exp_raw or "").strip()
        try:
            exp = int(s_exp)
        except ValueError:
            try:
                from datetime import datetime as _dt
                exp = int(_dt.fromisoformat(s_exp.replace("Z", "+00:00")).timestamp())
            except (ValueError, OverflowError, OSError):
                return (None, "authorize 的 expires 非法：%r（收 epoch 秒或 ISO8601）"
                              % (exp_raw,))
    if exp is None or exp <= 0:
        return (None, "authorize 需要 expires（epoch 秒或 ISO8601，必填——授权必须到期作废）")
    who = str(raw.get("who") or "")
    if not who.strip():
        return (None, "authorize 需要 who（授权人身份由调用方注入，不得留空）")
    return (HumanAuthorization(kind=kind, who=who, scope=[str(s).strip() for s in scope],
                               reason=str(raw.get("reason") or ""), expires=int(exp)), "")


# ---- t260913-01：authorize 端到端（sign_face 指纹先验 + 落账三态确认） ----
# 事故根因：常驻 worker 的内存代码可以早于磁盘代码（本次=旧 Signature 类解码时把
# authorize 当未知字段静默丢弃），delivered=true 只证「信号送达 server」。本组函数把
# 「投递前先验对端 worker 新鲜度、投递后确认真落账」做成 op=authorize 的固定步骤。

def _authz_entries(snap: Any) -> List[Dict[str, Any]]:
    """快照里的授权条目（容错读面）：条目真源在 snapshot['meta']['authorizations']
    （dev_lane intake 落 meta），顶层亦容——镜像 integration 场景 authz_items 的双读
    先例。任何畸形（snap/meta 非 dict、authorizations 非 list、条目非 dict）一律降级
    空表：不炸、不误判（降级只会让落账判定停在 pending，不会假报 landed）。"""
    try:
        holders = [snap if isinstance(snap, dict) else None,
                   snap.get("meta") if isinstance(snap, dict) else None]
    except Exception:
        return []
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        items = holder.get("authorizations")
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
    return []


def _refused_entries(snap: Any) -> List[Dict[str, Any]]:
    """快照顶层 refused 的容错读面（非 list/条目非 dict 一律跳过，不炸）。"""
    if not isinstance(snap, dict):
        return []
    items = snap.get("refused")
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def classify_query_failure(exc_name: str, msg: str) -> "tuple[str, str]":
    """sign_face query 失败三分（纯函数，SDK 异常类在探针函数体内才导入——本文件
    模块级 SDK 导面最小化契约，t260901-23）：

    - QueryFailed 且文案含「expected but not found」→ absent：旧 worker 没有该 query
      （结构性陈旧判别；query 未命中不写历史不失败 task，零副作用）；
    - 其它 QueryFailed → face_error：指纹 handler 自身失败，**不得吞成 absent**
      （吞了会把「代码漂移」误报成「代码陈旧」）；
    - 其余（超时/RPC/已终态）→ unreachable。"""
    if "QueryFailed" in (exc_name or "") and "expected but not found" in (msg or ""):
        return ("absent", msg or "")
    if "QueryFailed" in (exc_name or ""):
        return ("face_error", "%s: %s" % (exc_name, msg))
    return ("unreachable", "%s: %s" % (exc_name, msg))


def classify_sign_face(hint: str, payload: Any,
                       expected: Any) -> "tuple[str, str]":
    """sign_face 探针结果 → (state, detail)（纯函数）。hint ∈ ok/absent/face_error/
    unreachable；ok 时与 expected（CLI 进程现算的指纹）逐键比对 → match/mismatch。"""
    if hint != "ok":
        return (hint, str(payload or ""))
    if not isinstance(payload, dict):
        return ("face_error", "sign_face 返回形状非法: %r" % (payload,))
    if not isinstance(expected, dict):
        return ("match", "")
    diffs = []
    for k in sorted(set(payload) | set(expected)):
        if payload.get(k) != expected.get(k):
            diffs.append("%s: cli=%r worker=%r" % (k, expected.get(k), payload.get(k)))
    if diffs:
        return ("mismatch", "; ".join(diffs))
    return ("match", "")


def authz_face_refusal(state: str, detail: str,
                       wf_class: str = "", template_id: str = "") -> "tuple[str, str]":
    """face 拒发文案（纯函数）。C2：先分叉模板/类名再出文案——absent 对「非 dev-lane
    模板」是误投（该模板结构性无授权面），对「dev_lane 票」才是 worker 陈旧，两句话
    必须可辨。返回 (kind, msg)。"""
    lineage = ("并核该票专属 worker 血统：data/worker-<票号>.pid.meta 的 repo_root 必须"
               "本仓（KI-033），SIGTERM 后 console keepalive 会重生新代码 worker")
    if state == "absent":
        is_dev_lane = ("DevLaneWorkflow" in (wf_class or "")) or \
                      ((template_id or "") == "dev-lane")
        if wf_class and not is_dev_lane:
            return (KIND_AUTHZ_FACE_WRONG_TEMPLATE,
                    "该票模板 %s（workflow_class=%s）无人授权面——人授权唯一入口是 "
                    "dev_lane 模板；未投递，票面无变化" % (template_id or "?", wf_class or "?"))
        if wf_class:
            return (KIND_AUTHZ_FACE_ABSENT,
                    "worker 代码早于本票（sign_face query 不存在）——旧 Signature 类解码时"
                    "会静默丢弃 authorize 载荷，已拒发未投递。处置：重启该票专属 worker"
                    "（kill -TERM $(cat data/worker-<票号>.pid)），%s" % lineage)
        return (KIND_AUTHZ_FACE_ABSENT,
                "worker 不带 sign_face 指纹面且快照不可得（worker 代码早于本票，或票已完单/"
                "worker 不在）——authorize 已拒发未投递。处置：%s" % lineage)
    if state == "mismatch":
        return (KIND_AUTHZ_FACE_MISMATCH,
                "worker 与 CLI 代码漂移（sign_face 指纹不符：%s）——authorize 已拒发未投递。"
                "处置：重启该票专属 worker，%s" % (detail, lineage))
    if state == "face_error":
        return (KIND_AUTHZ_FACE_ERROR,
                "sign_face 指纹面自身失败（非「query 不存在」）：%s——authorize 已拒发"
                "未投递，按 worker 侧错误排查（不得当作旧 worker 处理）" % detail)
    return (KIND_AUTHZ_FACE_UNREACHABLE,
            "worker 不在服务或查询超时（%s）——authorize 已拒发未投递；核该票专属 worker "
            "进程存活与血统后重试" % detail)


def _authz_key(it: Dict[str, Any]) -> "tuple[str, str, int, int]":
    return (str(it.get("who") or "").strip(), str(it.get("kind") or ""),
            int(it.get("expires") or 0), int(it.get("issued") or 0))


def evaluate_authz_landing(baseline_authz: List[Any], baseline_refused: List[Any],
                           snap: Any, who: str, kind: str, expires: int,
                           ) -> "tuple[str, Any]":
    """落账三态判定（纯函数）：landed / refused / pending。集合式 diff（不数条数，
    重复授权由 intake 盖写的 issued 区分）；基线不可读（畸形降级空表）最多导致
    pending，不炸、不误报。"""
    want = (who or "").strip()
    base_keys = {_authz_key(b) for b in baseline_authz if isinstance(b, dict)}
    for it in _authz_entries(snap):
        if str(it.get("who") or "").strip() != want or str(it.get("kind") or "") != kind:
            continue
        if int(it.get("expires") or 0) != int(expires):
            continue
        if _authz_key(it) not in base_keys:
            return ("landed", dict(it))
    base_ref = set()
    for it in baseline_refused:
        if isinstance(it, dict):
            base_ref.add((str(it.get("want") or ""), str(it.get("who") or ""),
                          str(it.get("why") or "")))
    for it in _refused_entries(snap):
        key = (str(it.get("want") or ""), str(it.get("who") or ""), str(it.get("why") or ""))
        if key[0] == "sign(authorize)" and key not in base_ref:
            return ("refused", key[2])
    return ("pending", "")


async def _probe_sign_face(handle: Any, timeout: float = QUERY_TIMEOUT_S,
                           ) -> "tuple[str, str, Any]":
    """sign_face query 探针（指纹在 worker 进程内现算）。SDK 异常类在此函数体内导入
    （模块级 SDK 导面最小化契约，t260901-23/_sdk_deleter 同款纪律）。"""
    from temporalio.client import WorkflowQueryFailedError as _WQF
    from temporalio.service import RPCError as _RPCError
    expected = sign_face_fingerprint()
    try:
        out = await asyncio.wait_for(handle.query("sign_face"), timeout=timeout)
    except _WQF as e:
        hint, detail = classify_query_failure(type(e).__name__, str(e))
        return (hint, detail, None)
    except (_RPCError, asyncio.TimeoutError) as e:
        return ("unreachable", "%s: %s" % (type(e).__name__, e), None)
    except Exception as e:   # CLI 健壮度兜底：未知异常不炸整条 CLI，归 unreachable
        return ("unreachable", "%s: %s" % (type(e).__name__, e), None)
    hint, detail = classify_sign_face("ok", out, expected)
    return (hint, detail, out)


async def _await_authz_landing(handle: Any, baseline_authz: List[Any],
                               baseline_refused: List[Any],
                               who: str, kind: str, expires: int,
                               polls: int = AUTHZ_LANDING_POLLS,
                               base_delay: float = AUTHZ_LANDING_BASE_DELAY,
                               max_delay: float = AUTHZ_LANDING_MAX_DELAY,
                               timeout: float = QUERY_TIMEOUT_S,
                               ) -> "tuple[str, Any, Any]":
    """投递后有界轮询（指数退避）：返回 (state, payload, 末次快照)。单轮快照失败按
    过渡窗抖动处理（KI-003 同源），下一轮再取；预算走完仍是 pending 交由调用方出
    unconfirmed。"""
    delay = base_delay
    last_snap: Any = None
    for _ in range(max(1, polls)):
        await asyncio.sleep(delay)
        delay = min(max_delay, delay * 2)
        try:
            s = await asyncio.wait_for(handle.query("snapshot"), timeout=timeout)
        except Exception:
            continue
        last_snap = s
        state, payload = evaluate_authz_landing(baseline_authz, baseline_refused,
                                                s, who, kind, expires)
        if state != "pending":
            return (state, payload, s)
    return ("pending", None, last_snap)


def _row_from_meta(tid: str, meta: Dict[str, Any], exec_status: str) -> Dict[str, Any]:
    import time as _t
    # t260912-03：生效中的人授权计数（列表可读面）。口径＝meta['authorizations'] 里
    # kind 合法且 expires>now 的条数；读侧是 CLI 进程（非 workflow 代码），墙钟可用
    # （工单留痕口径：issued/expires 一律 epoch 秒，比较点=读取时刻）。
    _now = int(_t.time())
    _authz = [a for a in (meta.get("authorizations") or [])
              if isinstance(a, dict)
              and str(a.get("kind") or "") in ("protected_path", "arbitration_verdict")
              and int(a.get("expires") or 0) > _now]
    # t260921-03：收口健康度单次推导（推导单点=_close_health_of）
    _health, _health_reason = _close_health_of(exec_status)
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
        "paused": bool(meta.get("paused")),                     # t260908-01 段间暂停二态（列表徽标/操作位数据源）
        "paused_phase": str(meta.get("paused_phase") or ""),    # pending=已受理待段间生效 / at_gate=已停段间门口
        "handoff_count": len(meta.get("handoffs") or []),
        "pending_count": len(meta.get("pending") or []),
        "worktree": meta.get("worktree") or "",
        "workspace": meta.get("workspace"),
        "created": meta.get("created"),
        "updated": _t.strftime("%m-%d %H:%M", _t.localtime(meta.get("updated") or 0)),
        "updated_ts": meta.get("updated"),
        "engine": ENGINE_V2,
        "exec_status": exec_status,
        # t260921-03：收口健康度（键只加，与巡检行同名单）。dev-lane 无产物契约——
        # 终态成功即 ok，缺产物判定不泛化到 dev-lane；失败类终态带事实原因。
        "close_health": _health,
        "close_health_reason": _health_reason,
        # t260912-03：本票生效中的人授权（类型/范围/授权人/到期在 ticket show 的
        # meta.authorizations 全量可读；列表行只给计数徽标数据源）
        "authz_active": len(_authz),
    }


def _inspection_title_of(snap: Dict[str, Any], ticket_id: str,
                         instance_id: str = "", period: str = "") -> str:
    """巡检行标题（票面优先；face 缺字段回落调用方解析出的（实例,期）——SA 直读或旧形
    id 只读解析（t260916-02：id 不再编码实例/期，此处绝不从新形 id 反解）。宁显编号
    不显空）。

    词面**英文**（宿主令 260924 票面英文 + 260925 控制台英文：本串是巡检票唯一 title
    生成点——票面无存底 title（face/meta 都没有），行/详情/左栏三处读面全吃这一处，
    故英文在这里落地即全绿面一致）。"""
    face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
    instance = str(face.get("instance_id") or instance_id or "")
    period = str(face.get("period") or period or "")
    if instance and period:
        return "Inspection %s · period %s" % (instance, period)
    if instance:
        return "Inspection %s" % instance
    return "Inspection ticket %s" % ticket_id


def _row_from_inspection_face(
    tid: str,
    snap: Dict[str, Any],
    sa_project: str,
    sa_epic: str,
    exec_status: str,
    close_ts: float,
    created_ts: int,
    *,
    degraded: bool = False,
    instance_id: str = "",
    period: str = "",
    match_via: str = "",
    legacy_unowned: bool = False,
) -> Dict[str, Any]:
    """巡检票列表行（方案 R4：独立分支，不套 dev-lane 行形状）。

    数据源=snapshot 顶层（stage/stage_state/status/decision）+ face（票面真源
    build_ticket_face：summary/heartbeat/findings/report_path/human_gate）。键集是
    dev-lane 行的**超集**（通用键全保留——UI 四态/筛选/折叠组件零特判可跑），
    巡检字段额外叠加；engine 用 INSPECTION_ROW_ENGINE（UI availableOps 早退，坑B）。

    t260916-02：instance_id/period 由调用方解析（SA 直读→旧形 id 只读解析）随参进，
    本函数不再从 id 反解（新形 id 也反解不出）；行带 match_via（sa|legacy_id）与
    legacy_unowned（无 ProjectKey SA=「历史票无项目身份」，口径⑤显式可辨）。

    待签判定（awaiting_gate）**只读 stage_state**，不读 face.human_gate——该键仅在
    签字后写入（inspection_flow.py close 段），签字前常态缺键（方案 R4/打回4）；
    human_gate 原样透传仅作已签回执展示。

    degraded=True：窗内闭合行 result() 读取失败的显式降级（KI-008 同纪律——绝不匿名
    空行）。status 钉死 'running'（review 执行项1）：deriveTicketState 首判
    status==='closed'→done 会被收口折叠吃掉，错误行必须保持可见（UT 真值表钉此）。"""
    face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
    summary = face.get("summary") if isinstance(face.get("summary"), dict) else {}
    findings = face.get("findings") if isinstance(face.get("findings"), list) else []
    counts = {"high": 0, "med": 0, "low": 0}
    for f in findings:
        if isinstance(f, dict) and str(f.get("severity") or "") in counts:
            counts[str(f.get("severity"))] += 1
    if degraded:
        stage = "close"
        stage_state = "running"
        status = "running"
        title = "巡检收口快照读取失败，刷新重试"
        counts = {"high": 0, "med": 0, "low": 0}
    else:
        stage = str(snap.get("stage") or "") or None
        stage_state = str(snap.get("stage_state") or "") or "awaiting"
        status = str(snap.get("status") or "")
        title = _inspection_title_of(snap, tid, instance_id, period)
    sev_counts = {
        "high": int(summary.get("high") or counts["high"]),
        "med": int(summary.get("med") or counts["med"]),
        "low": int(summary.get("low") or counts["low"]),
    }
    updated_txt = time.strftime("%m-%d %H:%M", time.localtime(created_ts)) if created_ts else ""
    human_gate = face.get("human_gate") if isinstance(face.get("human_gate"), dict) else None
    # t260921-03 收口健康度（键只加）：行自带可判定字段——exec 终态对账在 UI 判序
    # 单点落地，本行键是其数据源（status/stage_state 词面**原样保留**：面快照是事实，
    # 对账不改写历史面，只增量表达「怎么结束的」）。巡检侧 require_artifacts=True：
    # 终态成功但无面可核 → unreadable（存疑显式，不冒充 ok）。
    close_health, close_health_reason = _close_health_of(exec_status, face, degraded,
                                                         require_artifacts=True)
    return {
        "id": tid,
        "project": sa_project,
        "epic": sa_epic,
        "kind": "inspection",
        "role": None,
        "status": status,
        "title": title,
        "workflow": "",
        "proposal_id": "",
        "stage": stage,
        "stage_state": stage_state,
        "paused": False,           # 巡检模板无段间暂停面（无 TicketPauseMixin）
        "paused_phase": "",
        "handoff_count": 0,
        "pending_count": 0,
        "worktree": "",
        "workspace": None,
        "template": str(snap.get("template") or "inspection-lite"),
        # 实例/期号：face（票面镜像）优先，调用方解析值（SA/legacy 只读）兜底——
        # 绝不从票号反解（t260916-02 反解点清理；match_via 标注数据来源可辨）
        "instance_id": str(face.get("instance_id") or instance_id or ""),
        "period": str(face.get("period") or period or ""),
        "match_via": match_via,
        # 口径⑤：无 ProjectKey SA 的历史票显式降级可辨（「历史票无项目身份」），
        # 不静默丢 project、不误归项目（project 恒如实出 SA 值，空=空）
        "legacy_unowned": bool(legacy_unowned),
        # 有主旧形票的布尔标（定稿方案 §2.3；arbitrate gen2 缺陷②）：走 legacy 查询路径
        # 且有项目身份（非 unowned）才标——B1 无 SA 历史票仍只标 legacy_unowned
        "legacy_id": bool(match_via == "legacy_id" and not legacy_unowned),
        # 发现数：face.summary（真源）优先，畸形 summary 逐条重计兜底（两口径互核）
        "findings": {**sev_counts, "total": len(findings)},
        "heartbeat": bool(face.get("heartbeat")),
        "report_path": str(face.get("report_path") or ""),
        # 待签判定=阶段机推导（awaiting-human），human_gate 只是已签回执
        "awaiting_gate": stage_state == "awaiting-human",
        "human_gate": human_gate,
        "blocked_reason": str(face.get("blocked_reason") or ""),
        "gate_error": str(snap.get("gate_error") or ""),
        "created": created_ts or None,
        "updated": updated_txt,
        "updated_ts": created_ts or 0,
        "engine": INSPECTION_ROW_ENGINE,
        "exec_status": exec_status,
        # t260921-03：收口健康度（ok/failed/abnormal/unreadable/''=未收口）+ 事实原因
        # （badge 与详情终态卡数据源；''=未收口无健康度可言）
        "close_health": close_health,
        "close_health_reason": close_health_reason,
        "authz_active": 0,
        "close_ts": close_ts,
    }


async def _query_snapshot_with_retry(handle: Any, timeout: float = QUERY_TIMEOUT_S,
                                     attempts: int = QUERY_RETRY_ATTEMPTS,
                                     base_delay: float = QUERY_RETRY_BASE_DELAY,
                                     max_delay: float = QUERY_RETRY_MAX_DELAY,
                                     jitter: float = QUERY_RETRY_JITTER) -> Any:
    """Retry for a failed snapshot query on a RUNNING ticket (the KI-003/KI-008 net).

    An 8s timeout is mostly momentary jitter in the stage-transition window (the
    workflow-side yield point is base._breathe; the mechanism conclusion: the inline
    mutation window recovers within 1-2 seconds) — 3 exponential-backoff attempts cover
    the window. When retries run out, the last exception is raised and the caller does an
    explicit degradation (a transient detail error, a degraded list row); no more
    swallowing silently. The delay parameters are injectable so self-tests can speed
    things up with 0 and not drag the tests."""
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
    """describe with one backoff retry (the other half of KI-025): failing a momentary
    describe outright is the other source of false "does not exist" claims
    (connection/timeout-class failures). NotFoundFailure is a deterministic conclusion —
    re-raised immediately with no retry; every other exception is treated as momentary
    and retried once, then the last exception is re-raised when retries run out."""
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


# ---- 终态失败票两面可见（t260919-02）：判别/原因提取/失败面 ----
# 终态「活/成」白名单（UI deriveTicketState 的 EXEC_STATUS_ALIVE 同一词表的双侧
# 镜像；改这里必须同步改 UI 侧并跑两侧 UT）。口径=补集：显式在跑（RUNNING）与
# 显式成功收口（COMPLETED，含 CONTINUED_AS_NEW 换代继续）之外的一切非空执行状态
# （FAILED/CANCELED/TIMED_OUT/TERMINATED/未知新终态）都按失败类处置——未知新终态
# 宁可显失败不可显在跑（诚实缺省）。空串=describe 缺 status 的畸形形态，不判失败
# （保持既有行形状，不新增谎报面）。
_EXEC_ALIVE_OK = ("RUNNING", "COMPLETED", "CONTINUED_AS_NEW")
# face 原因提取上限：__cause__ 链最多下钻 3 级、消息截 500 字（Temporal 的
# WorkflowFailureError→ActivityError→ApplicationError 链实测 ≤3 级见到人话）。
TERMINAL_FACE_CAUSE_DEPTH = 3
TERMINAL_FACE_REASON_MAX_CHARS = 500
# 终态执行 result() 历史回放的单次等待上限（秒）：服务端直读历史，正常亚秒；
# 超时=读不到原因（显式「原因不可得」），绝不为一张死票拖住详情回执。
TERMINAL_FACE_RESULT_TIMEOUT_S = 8.0


def _is_failed_exec(exec_status: str) -> bool:
    """失败类终态判别单点（板面行组装与详情 face 共用）：非空且不在活/成白名单
    即失败类。纯函数；词表口径见 _EXEC_ALIVE_OK 注。"""
    return bool(exec_status) and exec_status not in _EXEC_ALIVE_OK


# ---- 收口健康度（t260921-03）：已结束的票必须同时表达「结束了」与「怎么结束的」----
# 终态成功执行状态（UI 侧 ticket-list-model.ts EXEC_STATUS_DONE_OK 同一词表的引擎侧
# 正源；改任一侧必须同步另一侧并跑两侧 UT）。_EXEC_ALIVE_OK 语义不变（服务
# _is_failed_exec 补集口径），本表只服务收口健康度推导——COMPLETED 从「活/成」
# 混称里拆出来，是本票对账的第一步。
_EXEC_DONE_OK = ("COMPLETED",)


def _close_health_of(exec_status: str, face: Optional[Dict[str, Any]] = None,
                     degraded: bool = False, require_artifacts: bool = False) -> Tuple[str, str]:
    """收口健康度推导单点（板面行与详情面共用；t260921-03）。

    返回 (close_health, close_health_reason)：
      ''           未收口（RUNNING/CONTINUED_AS_NEW/空畸形）——健康度不可判，不给；
      'ok'         正常收口（终态成功且应有产物在；巡检=面无受阻记录且 report_path
                   在。dev-lane 无产物契约（require_artifacts=False），终态成功即
                   ok——缺产物判定不泛化）；
      'failed'     失败类终态（FAILED/CANCELED/TIMED_OUT/未知新终态——_is_failed_exec
                   补集口径，t260919-02 行形状零回归）；
      'abnormal'   异常收口（终态成功但没跑成实质工作：巡检=面带受阻记录——无论
                   report_path 是否在，t260917-02 起 blocked 收口也落账，落账文件走
                   report 同名约定，report_path 在场≠报告在（实案 t260920-02/
                   t260921-01 的「报告」即受阻面镜像）；或面无受阻但 report_path
                   缺失。findings/summary 空只作 reason 佐证。有产物且无受阻不判
                   异常，反用例防对账反向撒谎）；
      'unreadable' 已结束·待核（面读取失败/无面可核——KI-008 显式降级纪律：存疑
                   显式化，绝不冒充 ok，也绝不冒充异常下结论）。
    require_artifacts=True 供巡检侧调用（行组装与详情面）：终态成功但无面可核
    （face 缺失/非字典）→ unreadable；dev-lane 缺省 False，face 参数不参与推导。
    TERMINATED 维持既有「不上板」纪律，板面不产生本推导的行。纯函数：face 畸形
    （非 dict/键值畸形）逐键按缺失降级，不抛；reason 只放事实（KI-018①：「刷新重试」
    类占位语绝不进数据字段）。"""
    if degraded:
        return ("unreadable", "收口面读取失败：已结束但票面不可读（显式存疑，未判定产物）")
    if not exec_status:
        return ("", "")
    if exec_status in _EXEC_DONE_OK:
        f = face if isinstance(face, dict) else {}
        if not f:
            if require_artifacts:
                return ("unreadable", "收口面不可读：已结束但无票面可核产物（显式存疑）")
            return ("ok", "")
        if not require_artifacts:
            return ("ok", "")  # dev-lane：无产物契约，face 不参与推导
        blocked = f.get("blocked_reason")
        has_blocked = isinstance(blocked, str) and bool(blocked.strip())
        report_path = f.get("report_path")
        has_report = isinstance(report_path, str) and bool(report_path.strip())
        if has_blocked:
            # 受阻面=没跑成实质工作（实案 t260920-02/t260921-01）。t260917-02 起
            # blocked 收口也落账（dead-man 面），落账走 report 同名约定——文件在
            # 场只是受阻面镜像，不构成「报告在」：健康度看面不看文件名。
            findings = f.get("findings") if isinstance(f.get("findings"), list) else []
            tail = ("落账文件为受阻面镜像" if has_report else "本期无报告")
            return ("abnormal", "面快照 blocked：%s；发现 %d 条（%s）"
                    % (blocked.strip(), len(findings), tail))
        if has_report:
            return ("ok", "")
        return ("abnormal", "本期无报告（report_path 缺失，发现 %d 条）"
                % len(f.get("findings") if isinstance(f.get("findings"), list) else []))
    if _is_failed_exec(exec_status):
        return ("failed", "工作流终态 %s" % exec_status)
    return ("", "")


def _failure_reason_of(exc: Optional[BaseException]) -> str:
    """从 result() 异常链提取失败原因（正源=Temporal 工作流执行失败信息）。

    沿 __cause__ 向下最多 TERMINAL_FACE_CAUSE_DEPTH 级，取能走到的最深一层消息、
    截 TERMINAL_FACE_REASON_MAX_CHARS 字；__cause__ 是非异常对象（畸形/桩）就地停；
    全链零消息 → ''（调用方显式写「原因不可得」，绝不编造）。纯函数零 IO。"""
    cur = exc
    depth = 0
    while cur is not None and depth < TERMINAL_FACE_CAUSE_DEPTH:
        nxt = cur.__cause__
        if not isinstance(nxt, BaseException):
            break
        cur = nxt
        depth += 1
    if cur is None:
        return ""
    return str(cur).strip()[:TERMINAL_FACE_REASON_MAX_CHARS]


def _terminated_reason_of(exc: Optional[BaseException]) -> str:
    """从 result() 异常链提取 terminate 理由（t260922-10 终态 face 增量键）。

    TerminatedError 携带结构化 .reason 属性（terminate 的 reason 原文，正是记名清场的
    对账串）——沿 __cause__ 链找第一个带非空字符串 reason 属性的异常；链断/畸形/桩/
    无 reason → ''（调用方写「不可得」，绝不编造）。与 _failure_reason_of 并存不互替：
    后者取消息链（FAILED 正源，既有 face 链在用不动=回归面最小），本函数取结构化
    reason 属性（TERMINATED 正源）。纯函数零 IO。"""
    cur = exc
    depth = 0
    while cur is not None and depth < TERMINAL_FACE_CAUSE_DEPTH:
        r = getattr(cur, "reason", None)
        if isinstance(r, str) and r.strip():
            return r.strip()[:TERMINAL_FACE_REASON_MAX_CHARS]
        nxt = cur.__cause__
        if not isinstance(nxt, BaseException):
            break
        cur = nxt
        depth += 1
    return ""


def _terminal_face_ts_of(v: Any) -> int:
    """终态时刻字段归一 → epoch 秒（0=不可得）。SDK describe 的 start/close 是 proto
    Timestamp（ToSeconds()），list 扫描行/测试桩常给 datetime 或 epoch 数值——只读
    展示字段宽容读取三形通吃，畸形一律 0（绝不因时刻形态翻车带崩失败面）。"""
    if v is None:
        return 0
    ts = _ts_epoch(v)
    if ts:
        return ts
    try:
        return int(v.timestamp())          # datetime 形（naive/aware 均可）
    except Exception:
        pass
    try:
        n = int(v)                          # epoch 数值形
        return n if n > 0 else 0
    except Exception:
        return 0


def _terminal_face_ts_txt(ts: int) -> str:
    """face 时刻展示串（引擎本地时区，与板面行 updated 同口径）；0=不可得 → ''。"""
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


async def _terminal_failure_face(tid: str, handle: Any, desc: Any,
                                 exec_status: str) -> Dict[str, Any]:
    """终态票可渲染失败面（ticket-query kind=terminal 回执的 face 键，t260919-02）。

    消费面：workbench host 对 terminal 回执补一次引擎直读把 face 带进 410 body →
    UI 详情失败面板（结构化、零操作入口）。ticket.py QueryError 不带 face（写集外），
    CLI ticket show 维持旧样诚实错误——host 直读是桥。

    诚实纪律（KI-025 家族红线）：
      - kind/文案/HTTP 级一字不改（face 只加载荷不换语义；终态仍「刷新无效」）；
      - 拿不到的字段显式「不可得」（reason_available=false + *_note 说明为何），
        绝不编造、绝不给推进/重试入口语义；
      - 快照为何无：终态工作流不再运行，snapshot query 无执行方承接——确定性结论，
        不是瞬时故障。
    """
    # 原因：终态执行 handle.result() 走服务端历史回放（不需要 worker 在场），
    # FAILED 抛 WorkflowFailureError 且 __cause__ 链携带失败消息（正源）。
    reason = ""
    reason_note = ""
    # terminate 理由（t260922-10 记名清场的对账串）：只有 TERMINATED 形态才可能取到。
    terminated_reason = ""
    try:
        await asyncio.wait_for(handle.result(), timeout=TERMINAL_FACE_RESULT_TIMEOUT_S)
        # 未抛=「状态说终态失败、结果却读成功」的矛盾形态（桩/版本错位）：不编造。
        reason_note = ("原因不可得：终态执行的结果读取未报失败（与执行状态 %s 矛盾，"
                       "疑似数据/版本错位）——不编造原因" % (exec_status or "未知"))
    except asyncio.TimeoutError:
        reason_note = ("原因不可得：执行结果读取超时（%ds）——终态历史回放未在限时内"
                       "返回，不编造原因" % int(TERMINAL_FACE_RESULT_TIMEOUT_S))
    except Exception as e:  # noqa: BLE001 —— 任何失败异常都只取消息链，绝不外抛
        reason = _failure_reason_of(e)
        terminated_reason = _terminated_reason_of(e)
        if reason:
            reason_note = "来源：Temporal 工作流执行失败信息（终态执行历史回放异常链）"
        else:
            reason_note = ("原因不可得：失败异常链（%s）未携带可读消息——不编造原因"
                           % type(e).__name__)
    # 时刻：describe 的 start/close（proto Timestamp/datetime/epoch 数值三形通吃；
    # 桩/缺字段降级 0=不可得）。
    start_ts = _terminal_face_ts_of(getattr(desc, "start_time", None))
    close_ts = _terminal_face_ts_of(getattr(desc, "close_time", None))
    # 票身份：project/epic/实例/期 全走 SA 直读（try/except 降级空串），
    # 实例/期再以旧形 id 只读解析兜底（历史票）——绝不从新形 id 反解（t260916-02 口径）。
    project = epic = ""
    inst = per = ""
    try:
        tsa = getattr(desc, "typed_search_attributes", None)
        project = str(tsa.get(SearchAttributeKey.for_keyword(PROJECT_SA_NAME)) or "")
    except Exception:  # noqa: BLE001
        project = ""
    try:
        tsa = getattr(desc, "typed_search_attributes", None)
        epic = str(tsa.get(SearchAttributeKey.for_keyword(EPIC_SA_NAME)) or "")
    except Exception:  # noqa: BLE001
        epic = ""
    try:
        tsa = getattr(desc, "typed_search_attributes", None)
        inst = str(tsa.get(SearchAttributeKey.for_keyword(INSPECTION_INSTANCE_SA_NAME)) or "")
        per = str(tsa.get(SearchAttributeKey.for_keyword(INSPECTION_PERIOD_SA_NAME)) or "")
    except Exception:  # noqa: BLE001
        inst = per = ""
    if not inst:
        inst, per = _legacy_inspection_instance_period_of(tid)
    return {
        "exec_status": exec_status or "未知",
        "ticket_id": tid,
        "project": project,
        "epic": epic,
        "instance_id": inst,
        "period": per,
        "reason": reason,
        "reason_available": bool(reason),
        "reason_source": reason_note,
        # t260922-10 增量键（additive，只加载荷不换语义）：terminate 的 reason 原文
        # （记名清场的对账串；非 terminate 终态/取不到=不可得，绝不编造）。
        "terminate_reason": terminated_reason,
        "terminate_reason_available": bool(terminated_reason),
        "snapshot_available": False,
        "snapshot_note": ("无快照：终态工作流不再运行，snapshot 查询没有执行方承接"
                          "（终态的确定性结论，不是瞬时故障，刷新无效）"),
        "last_stage": None,
        "last_stage_note": ("最后已知阶段不可得：引擎未在阶段迁移时把阶段写入 Temporal "
                            "memo，终态后快照亦不可查询——宁缺不猜"),
        "start_ts": start_ts,
        "close_ts": close_ts,
        "start_time_txt": _terminal_face_ts_txt(start_ts),
        "close_time_txt": _terminal_face_ts_txt(close_ts),
    }


def _classify_infra_error(e: BaseException) -> Dict[str, Any]:
    """兜底异常 → 分类回执（KI-029 单点）：连接类=transient（叫用户重试），其余=internal。

    「连不上」与「服务端有 bug」是两件事：前者刷新即好，后者要人查。混成一类会把诊断
    引向错误方向（KI-079/KI-029 同族纪律）。类型携带 kind（TransientConnectError.kind），
    不靠文案匹配猜。"""
    kind = getattr(e, "kind", None) or KIND_INTERNAL
    return _err(f"{type(e).__name__}: {e}", kind)


async def cmd_ticket_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """Single-ticket query (v2): the full snapshot + meta (a JSON-compatible ticket
    shape, consumed directly by ticket.py show).

    Error classification contract (KI-025, t260903-06): the receipt carries a kind field;
    the classification table is in the module header. "Ticket does not exist" may only be
    triggered by describe hitting NotFoundFailure (kind=not_found); timeout/connection/
    cancel are always transient; terminal states (TERMINATED/CANCELED/FAILED…) are always
    terminal (permanently unavailable, with wording that says refreshing is useless);
    malformed input/snapshot is internal."""
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
        # A closed workflow's run() return value is the final snapshot (_snapshot()) —
        # take it directly with result(), no worker needed. A query would land on the
        # already-exited dedicated worker's queue and wait out the timeout (observed:
        # 29s later it reports a false "ticket does not exist" and the closed ticket's
        # detail/changes/agent log all go dark).
        try:
            snap = await handle.result()
        except Exception as e:
            return _err("workflow 结果读取失败（瞬时），请刷新重试：%s: %s"
                        % (type(e).__name__, e), KIND_TRANSIENT)
    elif exec_status == "RUNNING":
        try:
            # KI-003/KI-008: a failing RUNNING query is usually momentary jitter in the
            # stage-transition window (a mutation burst choking the event loop; the
            # workflow side already has a yield point), so retry with exponential backoff
            # before reporting.
            snap = await _query_snapshot_with_retry(handle)
        except Exception as e:
            return _err("snapshot 查询失败（已重试 %d 次，瞬时抖动？请刷新重试）：%s: %s"
                        % (QUERY_RETRY_ATTEMPTS - 1, type(e).__name__, e), KIND_TRANSIENT)
    else:
        # Terminal states (TERMINATED/CANCELED/FAILED etc.) are permanently unqueryable:
        # a dedicated kind=terminal whose wording states plainly that refreshing is
        # useless — never transient (retrying a dead ticket forever is the opposite lie,
        # KI-025 review C2).
        # t260919-02：文案与 kind 一字不改（410 分级/诚实口径零退化），只**加** face
        # 载荷——结构化失败面让终端能把「为什么失败」渲染出来，而不是一面空白。
        return _err("工单已终态（%s），快照不可得——终态票不再推进，刷新无效"
                    % (exec_status or "未知"), KIND_TERMINAL,
                    face=await _terminal_failure_face(tid, handle, desc, exec_status))
    # Malformed-input defense (t260901-23): a non-dict query result (old code/stub/bad
    # data) → an explicit _err, never a bare AttributeError at the command boundary.
    if not isinstance(snap, dict):
        # Wording discipline: must not contain the "ticket does not exist" substring
        # (not even negated — scenarios guard the false-claim surface by substring).
        return _err("snapshot 返回形态异常（预期 dict，实得 %s）——数据/版本问题，"
                    "请核对 worker/模板版本" % type(snap).__name__, KIND_INTERNAL)
    # epic-linkage: dev-lane's _init builds its own meta in dev_lane.py (outside this
    # ticket's write set) and has no epic key. The epic's source of truth is the
    # workflow's EpicCode SA, backfilled at the query boundary — so the meta.epic seen by
    # snapshot consumers (ticket.py show / the workbench) always matches the SA.
    if isinstance(snap, dict) and isinstance(snap.get("meta"), dict) \
            and "epic" not in snap["meta"]:
        try:
            sa_epic = str(desc.typed_search_attributes.get(
                SearchAttributeKey.for_keyword(EPIC_SA_NAME)) or "")
        except Exception:
            sa_epic = ""
        snap["meta"]["epic"] = sa_epic
    # t260915-08（坑A + R6）：巡检票详情分支——快照无 meta/engine 键，缺省通道会把
    # 巡检票谎报「工单不存在」（ticket.py _v2_query 以 engine==ENGINE_V2 判 v2）。
    # 显式回 ENGINE_V2（v2 执行是真）+ meta 走巡检组装面（face 可达）。
    if isinstance(snap, dict) and snap.get("kind") == "inspection":
        # t260921-03：终态时刻随 meta 下发（详情终态卡「结束方式」数据源）；
        # desc.close_time 畸形/缺失 → ''（不可得显式，不编造）。
        _close_txt = ""
        if exec_status == "COMPLETED" and getattr(desc, "close_time", None):
            try:
                _close_txt = _terminal_face_ts_txt(int(desc.close_time.timestamp()))
            except Exception:
                _close_txt = ""
        return _ok({
            "ticket_id": tid,
            "run_id": handle.result_run_id or handle.run_id,
            "exec_status": exec_status or None,
            "engine": ENGINE_V2,
            "snapshot": snap,
            "ticket": _inspection_query_meta(tid, snap, exec_status, _close_txt),
            "pulse": _pulse_from_desc(desc) if exec_status == "RUNNING" else None,
        })
    return _ok({
        "ticket_id": tid,
        "run_id": handle.result_run_id or handle.run_id,
        "exec_status": exec_status or None,
        "engine": (snap or {}).get("engine") or "",
        "snapshot": snap,
        "ticket": (snap or {}).get("meta") or {},
        # Running pulse (t260825-03): while RUNNING, pull the pending activity heartbeat
        # out of describe ({stage,gen,polls,session_kb} + heartbeat time); non-RUNNING or
        # no heartbeat → degraded to None.
        "pulse": _pulse_from_desc(desc) if exec_status == "RUNNING" else None,
    })


def _inspection_query_meta(ticket_id: str, snap: Dict[str, Any],
                           exec_status: str = "",
                           close_time_txt: str = "") -> Dict[str, Any]:
    """巡检票详情面（ticket.py `_show` 消费的 meta 同构，方案 R6 + 实证11）。

    ticket.py `_v2_query` 只从 snapshot 投影白名单键（signatures/gate_runs/timeline…），
    **不含 face**——face 必须由这里并进 meta，否则详情下钻拿不到发现摘要/报告路径/
    人门回执。待签判定同 R4：消费方从 stage_state 推导；human_gate 仅已签回执，
    缺键不编造（None）。畸形 face 逐字段降级（不抛、不编造）。

    t260921-03（键只加）：exec_status/close_health/close_health_reason/close_time_txt
    ——详情头与状态卡的终态对账数据源（COMPLETED 巡检票详情必须可判「怎么结束的」，
    blocked 词面不得再裸奔成「受阻」；dev-lane 详情侧 ticket.py 写集外不带 exec_status，
    终态卡仅巡检面落地）。"""
    from inspection_flow import CLOSE_GATE_ID
    face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
    findings = face.get("findings") if isinstance(face.get("findings"), list) else []
    # t260916-02：实例/期号=face 镜像优先；face 缺键回落旧形 id 只读解析（历史票，
    # 兼容读面）——新形 id 反解不出，宁可出空串也不编造（口径②：不从票号反解）。
    _li, _lp = _legacy_inspection_instance_period_of(str(ticket_id or ""))
    meta: Dict[str, Any] = {
        "id": str(snap.get("id") or ticket_id),
        "kind": "inspection",
        "template": str(snap.get("template") or "inspection-lite"),
        "title": _inspection_title_of(snap, ticket_id, _li, _lp),
        "stage": snap.get("stage"),
        "stage_state": snap.get("stage_state"),
        "status": snap.get("status"),
        "decision": snap.get("decision"),
        # 签字通道的 gate 单点（引擎常量）：详情面签字按它回带 gate，workflow intake
        # validate_close_signature 才放行（gate 不匹配拒收，零旁路）
        "gate_id": CLOSE_GATE_ID,
        "instance_id": str(face.get("instance_id") or _li or ""),
        "period": str(face.get("period") or _lp or ""),
        "report_path": face.get("report_path") or "",
        "red_line": face.get("red_line"),
        "heartbeat": bool(face.get("heartbeat")),
        "summary": face.get("summary") if isinstance(face.get("summary"), dict) else {},
        "findings": findings,
        "suggested_fix_tickets": face.get("suggested_fix_tickets")
        if isinstance(face.get("suggested_fix_tickets"), list) else [],
        "blocked_reason": str(face.get("blocked_reason") or ""),
        "human_gate": face.get("human_gate") if isinstance(face.get("human_gate"), dict) else None,
        "gate_error": str(snap.get("gate_error") or ""),
        "timeline": snap.get("timeline") if isinstance(snap.get("timeline"), list) else [],
        "engine": INSPECTION_ROW_ENGINE,
        "worktree": "",
        "workspace": None,
    }
    for k in ("suite", "lane", "lane_teardown"):
        if face.get(k) is not None:
            meta[k] = face[k]
    # t260921-03：收口健康度四键（键只加）——行/详情同一推导单点（_close_health_of），
    # reason 只放事实不放占位语（KI-018①）。巡检侧 require_artifacts=True。
    _chealth, _cheason = _close_health_of(exec_status, face, require_artifacts=True)
    meta["exec_status"] = exec_status or None
    meta["close_health"] = _chealth
    meta["close_health_reason"] = _cheason
    meta["close_time_txt"] = close_time_txt
    # t260916-05：模板拓扑导出透传（快照门内 additive 键；workbench detail.topology
    # → 泳道图唯一图源通道——巡检 detail 无 workflow_id，模板级兜底通道不存在）。
    # dict 才带键：老实例（_patched=False 无键）与畸形值都省键=渲染器回落，不编造。
    if isinstance(snap.get("topology"), dict):
        meta["topology"] = snap["topology"]
    return meta


async def cmd_ticket_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """v2 ticket list: list workflows (the six template classes) + per-ticket snapshot
    query → ticket.py list row shape. With args.project given, filter by the ProjectKey
    search attribute (multi-project, ticket t260823; old executions without the label do
    not match the filter, so only new tickets are listed). Not given = all projects (the
    admin's global view). With args.epic given, additionally AND EpicCode="<code>"
    (epic-linkage acceptance criterion 5; stackable with project).
    epic is only shape-checked here (the EPIC_CODE_RE whitelist); the strong existence
    check for the code lives in ticket.py _list (the validate_epic_code single point) —
    a nonexistent code going through the ticket.py channel errors clearly instead of
    returning an empty table.
    Only executions on production task queues are collected (stragglers on the self-test
    dedicated queue are neither queried nor listed — querying them would wait out a
    timeout).
    260824 起工单走每工单专属队列（LEGACY 旧前缀 <id> 形态），过滤器放行共享队列 + 新旧专属前缀。  # naming-compat
    t260916-02 增两参数面：
      - args.id_prefix：铸号扫描面（ticket.py _next_seq_v2 的序号真源）——**全类型**前缀
        扫描（工单 + 巡检票同天共享序号空间，只扫工单店=两族互撞的现成缺陷）。算子
        WorkflowId STARTS_WITH 后端拒绝时回落「全类型扫 + 客户端前缀过滤」（scan_mode
        可辨；过滤仍发生在快照查询之前，不产生 snapshot 成本）。与 kind=inspection 不并用。
      - kind=inspection 的板面改**两分支查询+合并**（F3）：SA 查询路径（在册实例
        InspectionInstance OR 串）+ legacy 查询路径（旧形 id 前缀，20 前历史票——id 不再编码
        实例，只能前缀捞），合并按 id 去重；行带 match_via 与 legacy_unowned 徽标。"""
    project = str(args.get("project") or "")
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", project):
        return _err("project 形状不合法（注册表 key 白名单：小写字母/数字/中划线）")
    epic = str(args.get("epic") or "").strip()
    if epic and not EPIC_CODE_RE.match(epic):
        return _err("epic 形状不合法（立项代号白名单：%s，小写字母/数字/连字符），实际 %r"
                    % (EPIC_CODE_RE.pattern, epic))
    # t260915-08（方案 R9）：缺省列表行集合零变化（仍只 TEMPLATE_CLASSES，dev-lane）；
    # kind=inspection 才切巡检板面（行走巡检分支）。
    # 工单台巡检端点即走本参数；未知 kind 显式报错（fail-closed，防拼写错静默回落全列表）。
    kind = str(args.get("kind") or "")
    if kind and kind != "inspection":
        return _err("kind 只认 'inspection'（工单板巡检面；缺省=dev-lane 原列表）")
    inspection_mode = kind == "inspection"
    id_prefix = str(args.get("id_prefix") or "").strip()
    if id_prefix and inspection_mode:
        return _err("id_prefix（铸号扫描面）与 kind=inspection（板面）不并用")
    if id_prefix and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$", id_prefix):
        return _err("id_prefix 形状不合法（字母/数字开头，[A-Za-z0-9._-]，≤61 字符）：%r"
                    % id_prefix)
    client = await _connect()

    async def _scan(query: str, prefix_filter: str = "") -> "Tuple[Dict[str, Any], List[str]]":
        """一遍查询 → (runs, order)。同 id 多 run 合并：非 TERMINATED 胜——terminate 后
        重开的票必须上板（seen-mark-first 会让旧 TERMINATED run 吞掉新 run，板面条目
        凭空消失）。prefix_filter 非空=客户端前缀过滤（查询算子被后端拒绝时的降级分支；
        过滤发生在快照查询之前，不产生 snapshot 成本）。"""
        runs_l: Dict[str, Any] = {}
        order_l: List[str] = []
        async for wf in client.list_workflows(query):
            tid = wf.id
            if prefix_filter and not tid.startswith(prefix_filter):
                continue
            cur = runs_l.get(tid)
            if cur is None:
                runs_l[tid] = wf
                order_l.append(tid)
            elif (cur.status.name if cur.status is not None else "") == "TERMINATED" and \
                    (wf.status.name if wf.status is not None else "") != "TERMINATED":
                runs_l[tid] = wf
        return runs_l, order_l

    inspection_note = ""
    inspection_decl_note = ""          # 声明面降级摘要（部分降级不拦查询，回执点名）
    inspection_degraded: list = []     # 结构化降级清单（degraded_projects 回执键）
    inspection_info: Optional[Dict[str, Any]] = None
    inspection_scan_mode = ""
    runs: Dict[str, Any] = {}
    order: List[str] = []
    if inspection_mode:
        # 白名单先读（t260915-08 R2；t260916-02 聚合来源）：全降级=板面显式空
        # （绝不放全量）；部分降级（坏项目/撞名剔除）=好项目照常收，回执点名。
        whitelist, inspection_decl_note, inspection_degraded = _inspection_enabled_instances()
        if not whitelist and inspection_decl_note:
            # 显式全降级（原 R2 行为不变）：声明面读不出白名单 → 不查询、行集合显式空
            # （绝不放全量，历史僵尸会 Flooding 回场）；回执带 degraded 让调用方
            # 看得见为什么空（KI-025 纪律：空 ≠ 无声）。
            runs, order = {}, []
            inspection_note = "inspection 声明不可读，巡检板面降级为空（%s）" % inspection_decl_note
            inspection_info = {"kind": "inspection", "enabled_instances": [],
                               "degraded": True, "note": inspection_note,
                               "scan_mode": "skipped"}
    if inspection_mode and inspection_info is None:
        type_base = " OR ".join('WorkflowType="%s"' % t for t in INSPECTION_BOARD_TYPES)
        tail = (' AND ProjectKey="%s"' % project if project else "") + \
               (' AND EpicCode="%s"' % epic if epic else "")
        # 查询路径①（SA）：在册实例的 OR 串（新票起票时盖 InspectionInstance/Period）。
        # 空白名单=没有任何在册实例 → 板面显式空（跳查询，与旧 R2 行为一致）。
        if whitelist:
            sa_q = '(%s AND (InspectionInstance="%s"))%s' % (
                type_base, '" OR InspectionInstance="'.join(whitelist), tail)
            runs, order = await _scan(sa_q)
        # 查询路径②（legacy）：旧形 id 前缀（t260916 之前的历史票）。R2：WorkflowId
        # STARTS_WITH 全仓零先例——首条路径被后端拒绝 → 回落「类型扫 + 客户端前缀过滤」
        # （inspection- 前缀，防僵尸收益不破；scan_mode/降级原因进回执可辨），
        # 取舍记录进 README §13，绝不静默换实现。
        legacy_q = '(%s AND WorkflowId STARTS_WITH "inspection-")%s' % (type_base, tail)
        try:
            lruns, lorder = await _scan(legacy_q)
            inspection_scan_mode = "starts_with"
        except Exception as e:  # noqa: BLE001——只有「后端不认查询」才允许降级（连接/超时照抛）
            if not _query_operator_unsupported(e):
                raise
            lruns, lorder = await _scan(type_base + tail if (project or epic)
                                        else type_base, "inspection-")
            inspection_scan_mode = "type_only_fallback"
            inspection_note = ("legacy 查询路径 STARTS_WITH 被后端拒绝，已回落类型扫+客户端前缀"
                               "过滤（%s: %s）" % (type(e).__name__, str(e)[:80]))
        for tid in lorder:                     # 两条查询路径合并：同 id 去重，非 TERMINATED 胜
            cur = runs.get(tid)
            if cur is None:
                runs[tid] = lruns[tid]
                order.append(tid)
            elif (cur.status.name if cur.status is not None else "") == "TERMINATED" and \
                    (lruns[tid].status.name if lruns[tid].status is not None else "") != "TERMINATED":
                runs[tid] = lruns[tid]
    elif not inspection_mode:
        if id_prefix:
            # 铸号扫描面：全类型前缀直查（工单+巡检票同天序号空间）。
            try:
                runs, order = await _scan('WorkflowId STARTS_WITH "%s"' % id_prefix)
                inspection_scan_mode = "starts_with"
            except Exception as e:  # noqa: BLE001——同 R2：算子被拒才降级
                if not _query_operator_unsupported(e):
                    raise
                type_all = " OR ".join(
                    ['WorkflowType="%s"' % c.__name__ for c in TEMPLATE_CLASSES.values()]
                    + ['WorkflowType="%s"' % t for t in INSPECTION_BOARD_TYPES])
                runs, order = await _scan(type_all, id_prefix + "-")
                inspection_scan_mode = "type_only_fallback"
        else:
            type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                                      for c in TEMPLATE_CLASSES.values())
            if project:
                type_filter = '(%s) AND ProjectKey="%s"' % (type_filter, project)
            if epic:
                type_filter = '(%s) AND EpicCode="%s"' % (type_filter, epic)
            runs, order = await _scan(type_filter)
    rows: List[Dict[str, Any]] = []
    entries: List[Dict[str, str]] = []
    for tid in order:
        wf = runs[tid]
        q = str(getattr(wf, "task_queue", "") or "")
        if q not in (TASK_QUEUE,) and not (
                q.startswith(TICKET_QUEUE_PREFIX)):
            continue
        exec_status = wf.status.name if wf.status is not None else ""
        if exec_status == "TERMINATED":
            continue  # torn-down/aborted tickets stay off the board (history remains queryable in Temporal)
        # ProjectKey / EpicCode read straight from the SA: even when the snapshot is
        # unavailable (worker never ran / old code) the row's project / epic are not lost
        # (the SA is the source of truth for ownership; the snapshot is only a mirror).
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
                        "created": int(wf.start_time.timestamp()) if getattr(wf, "start_time", None) else 0,
                        "close_ts": wf.close_time.timestamp() if wf.close_time else 0})

    # t260915-08（方案 R2/R8）预过滤（t260916-02 改两分支合并后的统一行筛选）：
    # （实例,期）按 SA 直读→旧形 id 只读解析（_inspection_instance_period_of），
    # 白名单过滤=实例身份判定（僵尸不烧 snapshot 查询），闭合窗（R8）施加于合并后
    # 行集；match_via/（实例,期）随 entry 记下供行渲染（不再二次反解）。
    inspection_match_via: Dict[str, str] = {}
    inspection_inst_period: Dict[str, "Tuple[str, str]"] = {}
    inspection_unresolved: set = set()   # 在跑且实例身份不可辨的票 id（修复②降级可见分支）
    if inspection_mode and inspection_info is None:
        # whitelist/降级摘要/降级清单已在查询段单点取得（不二次读声明面）
        kept: List[Dict[str, Any]] = []
        dropped_unresolved = 0
        kept_unresolved = 0
        for e in entries:
            inst, per, via = _inspection_instance_period_of(runs[e["id"]], e["id"])
            if not inst:
                # t260917-02 修复②：不可辨「且在跑」的巡检型运行不再静默丢——260917
                # 实况：旧调度 action 直发的 awaiting-human 票（无 SA 且 id 非旧形词法）
                # 被本分支吞掉，正在等人的巡检在 UI 上不存在。降级可见（identity_note
                # 假设语气：疑似旧 action 直发或演练残留，不写死处方）；不可辨「且已
                # 闭合」仍不上板——僵尸纪律半边不动（test-face/suite-drill 历史残件
                # 不借修复复活；t260916-02-board-legacy-three-state 守的「可辨但不在
                # 册→不上板」口径对可辨实例原样保留，与本条不矛盾）。
                if e["exec_status"] != "RUNNING":
                    dropped_unresolved += 1
                    continue
                kept_unresolved += 1
                inspection_unresolved.add(e["id"])
                kept.append(e)
                continue
            inspection_match_via[e["id"]] = via
            inspection_inst_period[e["id"]] = (inst, per)
            if inst not in whitelist:
                continue  # 未在册实例（test-face/suite-drill 等历史测试僵尸）不上板
            if e["exec_status"] == "COMPLETED" and (
                    not e["close_ts"]
                    or time.time() - e["close_ts"] >= CLOSED_HYDRATE_WINDOW_S):
                continue  # 闭合行只在 hydrate 窗口内上板（R8 有界口径）；close_ts=0 防御不收
            kept.append(e)
        entries = kept
        # 回执聚合：声明面降级（部分/全）与 R2 扫描降级分开记账、合并点名；
        # coverage 覆盖层标记 additive 可见（t260916-02 arbitrate：丢弃=静默清零缺陷）。
        merged_note = "；".join(x for x in (inspection_decl_note, inspection_note) if x)
        inspection_info = {"kind": "inspection", "enabled_instances": list(whitelist),
                           "degraded": bool(inspection_decl_note),
                           "note": merged_note,
                           "degraded_projects": [
                               {"project": p, "path": str(pa), "error": err}
                               for p, pa, err in inspection_degraded],
                           "coverage_overlay": _inspection_coverage_overlay(),
                           "scan_mode": inspection_scan_mode or "starts_with",
                           "dropped_unresolved": dropped_unresolved,
                           # t260917-02 修复②：在跑不可辨行计数（降级可见，不再与丢弃混装）
                           "kept_unresolved": kept_unresolved}

    # The snapshot query is issued only for RUNNING executions, and concurrently — a
    # non-RUNNING query lands on the already-exited dedicated worker's queue and waits
    # out the full 8s timeout (observed: each closed ticket slowed the list by 8s,
    # serially stacking to 16s+, and a workbench refresh landing in that window left the
    # left column blank for a long time).
    # RUNNING queries carry retries (KI-003/KI-008): worst case ~18s per ticket
    # (8s×2+2s), and because gather is concurrent the list's aggregate latency does not
    # grow with ticket count. A still-failing retry takes the explicit degradation path
    # (a degraded row, never a silent anonymous one).
    # COMPLETED executions inside the rehydration window use result() for the terminal
    # snapshot (run()'s return value = _snapshot(), no worker needed) — a closed ticket's
    # left-column dwell period must have a title/role, not an anonymous minimal row.
    async def _meta_of(tid: str, exec_status: str, close_ts: float) -> Dict[str, Any]:
        # 注意（t260901-23 t02 真值表钉死）：dev-lane 路径的 meta 抽取必须留在 try 内——
        # 非 dict 快照（老代码/桩/坏数据）靠 except 兜成显式降级行，挪出 try = 列表崩。
        # 巡检分支同样住 try 内：任何异常都落各自的显式降级标记，绝不外抛。
        if exec_status == "RUNNING":
            try:
                snap = await _query_snapshot_with_retry(client.get_workflow_handle(tid))
                if inspection_mode:
                    # 巡检快照无 meta 键（方案实证2）——整个快照原样交给巡检行分支；
                    # 巡检类型却拿不到巡检快照（含非 dict）=worker/模板版本错位，
                    # 同按显式降级处理。
                    if isinstance(snap, dict) and snap.get("kind") == "inspection":
                        return {"_inspection_snap": snap}
                    return {"_query_degraded": True}
                m = dict((snap or {}).get("meta") or {})
                # t260908-01：paused 二态是 snapshot 顶层键（TicketPauseMixin 的产物，
                # 不进 meta）——行形状（列表徽标/操作位数据源）在此显式并入。
                m["paused"] = bool((snap or {}).get("paused"))
                m["paused_phase"] = str((snap or {}).get("paused_phase") or "")
                return m
            except Exception:
                # KI-008 explicit degradation: a degraded marker (not a silent {}) — the
                # row-assembly branch uses it to build a "query timed out, refresh and
                # retry" row, and stage_state stays running (a ticket that really is
                # running must not be shown as waiting).
                return {"_query_degraded": True}

        if exec_status == "COMPLETED" and close_ts \
                and time.time() - close_ts < CLOSED_HYDRATE_WINDOW_S:
            try:
                snap = await asyncio.wait_for(
                    client.get_workflow_handle(tid).result(), timeout=8)
                if inspection_mode:
                    # 巡检窗内闭合行=完整巡检形（result() 终态快照，R8）；读败/形状错
                    # 位 → 显式巡检降级行（绝不匿名空行）。
                    if isinstance(snap, dict) and snap.get("kind") == "inspection":
                        return {"_inspection_snap": snap}
                    return {"_inspection_closed_degraded": True}
                m = dict((snap or {}).get("meta") or {})
                m["paused"] = bool((snap or {}).get("paused"))
                m["paused_phase"] = str((snap or {}).get("paused_phase") or "")
                return m
            except Exception:
                return {"_inspection_closed_degraded": True} if inspection_mode else {}
        if _is_failed_exec(exec_status):
            # t260919-02：失败类终态（FAILED/CANCELED/TIMED_OUT/未知新终态）显式标记
            # ——行组装按它出「已失败」行。绝不落入后续「查询超时，刷新重试」降级
            # 形状（对死票既显在跑又诱导刷新=双重不诚实，本票病灶），也不落匿名
            # 极简行（exec_status 在行上，UI 依它/词面显失败态）。
            return {"_terminal_failed": True}
        return {}

    metas = await asyncio.gather(*(_meta_of(e["id"], e["exec_status"], e["close_ts"]) for e in entries))
    for e, meta in zip(entries, metas):
        tid, sa_project, sa_epic = e["id"], e["sa_project"], e["sa_epic"]
        exec_status = e["exec_status"]
        if inspection_mode:
            # 巡检行分支（方案 R4/R8；t260916-02 增 match_via/legacy_unowned）：
            # 完整快照行 / 窗内闭合降级行（status≠closed，不进收口折叠）/ RUNNING
            # 查询降级行——三种都带巡检标识，永无匿名空行。
            inst_p = inspection_inst_period.get(tid) or ("", "")
            insp_kw = dict(instance_id=inst_p[0], period=inst_p[1],
                           match_via=inspection_match_via.get(tid, ""),
                           legacy_unowned=not sa_project)
            if meta.get("_inspection_snap"):
                rows.append(_row_from_inspection_face(
                    tid, meta["_inspection_snap"], sa_project, sa_epic,
                    exec_status, e["close_ts"], e.get("created") or 0, **insp_kw))
            elif meta.get("_inspection_closed_degraded"):
                rows.append(_row_from_inspection_face(
                    tid, {}, sa_project, sa_epic, exec_status, e["close_ts"],
                    e.get("created") or 0, degraded=True, **insp_kw))
            elif meta.get("_terminal_failed"):
                # t260919-02：失败类终态巡检行——标题=正常巡检标题（身份保留，实例/期
                # 可辨），status/stage_state=failed（UI 显「已失败」红标），绝不落
                # 「巡检票查询超时，刷新重试」降级形状（死票不诱导刷新）。updated 取
                # 终态时刻（close_ts，板上最后已知时间），无窗=永驻板面（本票要求
                # 失败可见；闭合窗是否对齐另议不擅动）。
                row = _row_from_inspection_face(
                    tid, {}, sa_project, sa_epic, exec_status, e["close_ts"],
                    e.get("created") or 0, **insp_kw)
                row["title"] = _inspection_title_of({}, tid, inst_p[0], inst_p[1])
                row["stage"] = None
                row["stage_state"] = "failed"
                row["status"] = "failed"
                row["awaiting_gate"] = False
                if e["close_ts"]:
                    row["updated_ts"] = int(e["close_ts"])
                    row["updated"] = time.strftime("%m-%d %H:%M", time.localtime(e["close_ts"]))
                rows.append(row)
            else:
                row = _row_from_inspection_face(
                    tid, {}, sa_project, sa_epic, exec_status, e["close_ts"],
                    e.get("created") or 0, **insp_kw)
                row["title"] = "巡检票查询超时，刷新重试"
                row["stage"] = None
                row["stage_state"] = "running"
                row["status"] = "dispatched"
                row["awaiting_gate"] = False
                rows.append(row)
            continue
        if meta.get("_terminal_failed"):
            # t260919-02：失败类终态显式失败行（dev-lane 极简形）——键集与极简行逐键
            # 同形（t260915-08 parity，不加新键），只有值诚实化：status/stage_state=
            # failed（UI 五态显「已失败」红标，不与在跑/收口混同）、标题点名执行失败
            # 且不带「刷新重试」（死票不诱导重试）、updated=终态时刻。
            rows.append({"id": tid, "project": sa_project, "epic": sa_epic,
                         "role": None,
                         "status": "failed",
                         "title": "工单执行失败（%s）" % (exec_status or "未知"),
                         "workflow": "", "proposal_id": "",
                         "stage": None, "stage_state": "failed",
                         "handoff_count": 0, "pending_count": 0, "worktree": "",
                         "workspace": None, "created": None,
                         "updated": (time.strftime("%m-%d %H:%M", time.localtime(e["close_ts"]))
                                     if e["close_ts"] else ""),
                         "updated_ts": int(e["close_ts"]) if e["close_ts"] else 0,
                         "close_ts": e["close_ts"],
                         "engine": ENGINE_V2, "exec_status": exec_status,
                         "close_health": _close_health_of(exec_status)[0],
                         "close_health_reason": _close_health_of(exec_status)[1],
                         "authz_active": 0})  # 降级/极简/失败行同形（无快照=无授权面可读）
        elif meta.get("_query_degraded"):
            # KI-008: a RUNNING query still failing after retries → an explicit degraded
            # row. id/project/epic come straight from the SA and are unaffected;
            # stage_state/status keep the running-state reading (not the anonymous row's
            # awaiting/empty, so a genuinely running ticket is not misread as waiting).
            rows.append({"id": tid, "project": sa_project, "epic": sa_epic,
                         "role": None,
                         "status": "dispatched",
                         "title": "查询超时，刷新重试",
                         "workflow": "", "proposal_id": "",
                         "stage": None, "stage_state": "running",
                         "handoff_count": 0, "pending_count": 0, "worktree": "",
                         "workspace": None, "created": None, "updated": "", "updated_ts": 0,
                         "close_ts": e["close_ts"],
                         "engine": ENGINE_V2, "exec_status": exec_status,
                         "close_health": _close_health_of(exec_status)[0],
                         "close_health_reason": _close_health_of(exec_status)[1],
                         "authz_active": 0})  # t260912-03 降级/极简行同形（无快照=无授权面可读）
        elif meta:
            meta.setdefault("project", sa_project)
            # epic takes the EpicCode SA as truth (SA first) with meta as fallback (the
            # snapshot mirror when the SA read fails or is unregistered); ticket-query's
            # meta.epic backfill follows the same idea.
            meta["epic"] = sa_epic or str(meta.get("epic") or "")
            row = _row_from_meta(tid, meta, exec_status)
            row["close_ts"] = e["close_ts"]
            rows.append(row)
        else:  # snapshot unavailable (closed past the window / worker never ran / old code) → minimal row
            rows.append({"id": tid, "project": sa_project, "epic": sa_epic,
                         "role": None,
                         "status": "closed" if exec_status == "COMPLETED" else "",
                         "title": "", "workflow": "", "proposal_id": "",
                         "stage": None, "stage_state": "awaiting",
                         "handoff_count": 0, "pending_count": 0, "worktree": "",
                         "workspace": None, "created": None, "updated": "", "updated_ts": 0,
                         "close_ts": e["close_ts"],
                         "engine": ENGINE_V2, "exec_status": exec_status,
                         "close_health": _close_health_of(exec_status)[0],
                         "close_health_reason": _close_health_of(exec_status)[1],
                         "authz_active": 0})  # t260912-03 降级/极简行同形（无快照=无授权面可读）
    # t260917-02 修复②收尾 pass（巡检板面专用）：
    # ① identity_note：不可辨且在跑的行（kept_unresolved 分支）带假设语气注记——疑似
    #   旧调度 action 直发或演练残留，给核查入口不写死处方（报错必须精确纪律）。
    # ② same_period_closed：同 (实例,期) 下 open 行与 closed 行并存时，open 行标注
    #   同期已有收口票（方案②「未收口运行单独成行并标注同期已有收口票」的承接；
    #   不合并行、不隐藏任何一张——每期一票语义下的双行只注不并）。
    if inspection_mode:
        closed_by_ip: Dict[Tuple[str, str], str] = {}
        for r in rows:
            if r.get("engine") != INSPECTION_ROW_ENGINE or r.get("status") != "closed":
                continue
            ip = (str(r.get("instance_id") or ""), str(r.get("period") or ""))
            if ip[0] and ip not in closed_by_ip:
                closed_by_ip[ip] = str(r.get("id") or "")
        for r in rows:
            if r.get("engine") != INSPECTION_ROW_ENGINE:
                continue
            if r.get("id") in inspection_unresolved:
                r["identity_note"] = ("巡检在跑但实例身份不可辨（无实例/期 SA 且 id 非旧形）"
                                      "——疑似旧调度 action 直发或演练残留；核查入口："
                                      "inspection_trigger.py describe（schedule_action 段）")
            if r.get("status") == "closed":
                continue
            ip = (str(r.get("instance_id") or ""), str(r.get("period") or ""))
            if ip[0] and ip in closed_by_ip and closed_by_ip[ip] != str(r.get("id") or ""):
                r["same_period_closed"] = closed_by_ip[ip]
    rows.sort(key=lambda r: -(r.get("created") or 0))
    result: Dict[str, Any] = {"count": len(rows), "tickets": rows}
    if inspection_info is not None:
        result["inspection_filter"] = inspection_info
    if id_prefix:
        # 铸号扫描面回执（t260916-02）：scan_mode 可辨（starts_with / type_only_fallback）
        result["id_prefix_scan"] = {"prefix": id_prefix, "scan_mode": inspection_scan_mode}
    return _ok(result)


# Archive manifest parsing, three states (contract v1.4 (1)c; prune/archive-legacy share
# the same judgment).
def _read_archive_manifest(ticket_id: str, project_key: str) -> Dict[str, Any]:
    """Read <data>/tickets/<id>/archive.json and return a status dict:

    {"state": "missing"|"ok"|"malformed"|"error", "legacy": bool, "detail": str}
    missing = the ticket is not archived (prune refuses to delete); malformed = a broken
    manifest (fail-closed: counted as a prune failure, never quietly treated as
    unarchived); error = an IO exception (counted as a failure)."""
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
    """List COMPLETED (closed) ticket entries: {id, sa_project, close_ts} (TERMINATED is
    not collected — same reading as ticket-list: torn-down/aborted executions stay off
    the board and out of the archive-cleanup surface)."""
    client = await _connect()
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    async for wf in client.list_workflows('(%s) AND ExecutionStatus="Completed"' % type_filter):
        q = str(getattr(wf, "task_queue", "") or "")
        if q not in (TASK_QUEUE,) and not (
                q.startswith(TICKET_QUEUE_PREFIX)):
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
    """Temporal regression runtime: clean up workflow history for tickets that are both
    closed and archived (M1-3).

    Deletion conditions (three fail-closed lists): archive.json exists with schema=v1 →
    deletable; legacy:true → requires --allow-legacy (an honest legacy posting, released
    only after human confirmation); missing → skipped (never delete an unarchived ticket
    — evaporating history is the very incident this ticket exists to fix); malformed →
    counted as a failure.
    Default --dry-run (zero deletions); only --execute really deletes. The real deletion
    seam is an injected deleter function (signature deleter(workflow_id) -> None; the SDK
    implementation goes through workflow_service-level DeleteWorkflowExecution, so tests
    can inject a fake deleter without a real Temporal).
    Per-ticket deletion is bounded by an asyncio.wait_for timeout; errors are caught one
    by one into failed without interrupting the batch.
    entries/deleter are test-injection seams: by default it works on live Temporal data
    (list_workflows).
    """
    dry_run = not bool(args.get("execute"))
    allow_legacy = bool(args.get("allow_legacy"))
    project = str(args.get("project") or "").strip()
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", project):
        return _err("project 形状不合法（注册表 key 白名单：小写字母/数字/中划线）")
    per_ticket_timeout = float(args.get("timeout_sec") or 30)

    async def _sdk_deleter(wf_id: str) -> None:
        # SDK API classes imported inside the function (the minimize-module-level-SDK
        # discipline; see the M1-3 note in the file header)
        from temporalio.api.common.v1 import WorkflowExecution
        from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
        c = await _connect()
        # Delete with an explicit run_id: without one, the dev server's delete waits for
        # the visibility store to converge asynchronously before disappearing from
        # describe (observed >60s; with run_id ~5s). Describe first to get the current
        # run, then delete, so delete-confirmation latency does not depend on the
        # server's visibility cleanup cadence.
        desc = await c.get_workflow_handle(wf_id).describe()
        await c.workflow_service.delete_workflow_execution(
            DeleteWorkflowExecutionRequest(
                namespace=NAMESPACE,
                workflow_execution=WorkflowExecution(workflow_id=wf_id,
                                                     run_id=desc.run_id)))

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
            failed.append({"id": tid, "why": m["detail"]})   # malformed / error: fail-closed
            continue
        if m["legacy"] and not allow_legacy:
            skipped_archived_legacy.append(tid)
            continue
        if dry_run:
            deleted.append(tid)   # dry-run counts into the "would delete" list (deleter never called)
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
    """Honest legacy posting: write archive.json for historical tickets that are "closed
    with the lane already torn down and the stage report unrecoverable" (legacy:true,
    empty files, a plainly stated reason) — never fabricated, never reconstructed
    (M1-3 R4).

    Only COMPLETED tickets without an archive.json are processed; a ticket that already
    has a manifest is skipped (a real archive is never overwritten). The meta snapshot
    comes from the workflow's terminal result() (no worker needed for COMPLETED); when
    unavailable an empty meta is recorded and written into detail. A write failure counts
    that ticket into failed without interrupting the batch.
    entries/result_of are test-injection seams: by default it works on live Temporal data
    (list_workflows / handle.result()), with result_of returning the terminal snapshot
    dict."""
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
            skipped.append(tid)   # a real archive already exists (or was already legacy-posted) — idempotent, no overwrite
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
    """Lightweight RUNNING ticket list (the 260824 option A: the data source for the
    console keepalive's ensure).

    Runs a single visibility query (v2 template classes AND ExecutionStatus=Running;
    from 260904 the only template is dev-lane) and does no per-ticket snapshot query —
    the keepalive calls every 15s, and anything heavier would saturate the worker.
    Returns [{id, queue}]: queue is read from the execution itself (zero constant
    duplication on the spawn side).
    """
    client = await _connect()
    type_filter = " OR ".join('WorkflowType="%s"' % c.__name__
                              for c in TEMPLATE_CLASSES.values())
    running: List[Dict[str, str]] = []
    async for wf in client.list_workflows('(%s) AND ExecutionStatus="Running"' % type_filter):
        q = str(getattr(wf, "task_queue", "") or "")
        if q not in (TASK_QUEUE,) and not (
                q.startswith(TICKET_QUEUE_PREFIX)):
            continue  # stragglers on the self-test dedicated queue are not collected
        running.append({"id": wf.id, "queue": q})
    return _ok({"count": len(running), "running": running})


async def cmd_template_faces(args: Dict[str, Any]) -> Dict[str, Any]:
    """t260926-03（KI-123）：权威模板面查询（只读、纯本地、**不连 Temporal**）。

    背景：类面合并（project_template_classes_merged）原是 workflows_v2 import 时
    一次性执行、结果只活在引擎进程内存；ticket.py create 面只读本进程名面表，
    类面拒收对它完全不可见 → 「既不 accepted 也不 rejected」的静默空转。本 op 在
    引擎 venv 子进程里**每次现算**类面（fresh scan，不吃 import 时冻结），回执带：

      names             引擎进程当前 shared.TEMPLATE_CLASS_NAMES（内置∪夹具∪名面∪类面）
      class_available   本次现算类面通过深检、真正可起的模板 id（sorted）
      rejections        结构化拒收清单（project/module/check/detail）
      builtin           内置∪夹具快照（BUILTIN_TEMPLATE_KEYS）
      projects_scanned  注册表枚举到的项目数
      declared_projects 其中声明 workflow_modules 的项目数
      projects_root     本次扫描的注册根（SANDBAR_PROJECTS_DIR 现读语义，空转排查面）

    消费方=server/tools/ticket.py create 模板闸（三态文案可判别：扫了但拒 /
    空转没扫 / 面不可达）。任何异常走 main() 的结构化回执兜底，绝不静默空表。
    """
    import shared  # noqa: PLC0415——本文件其余处 from shared import 具名清单，
    # 此处要的是模块属性现读面（TEMPLATE_CLASS_NAMES 类回写后的活表），局部取模块对象。
    res = shared.project_template_classes_merged()
    # t260926-03 第 2 轮（KI-123 残余缺陷实锤）：创建体（ticket.py _create）原经
    # server/workflows/<id>.yaml 快照取 lane/workspace/stage0 推导——项目外置模板在
    # 引擎仓无 yaml（快照只随内置模板生成）→ 闸放行后仍「模板不存在」，票建不出来。
    # 改：回执带 templates（id → 类属性推导视图：lane/workspace_dir/name/最小段表），
    # 创建体对无 yaml 的外置 id 改吃本视图，与 client.py ticket-start 的类属性消费
    # 同源（TEMPLATE_LANE/TEMPLATE_WORKSPACE_DIR/STAGES），不另造第二真源。
    templates = {}
    for tid, cls in sorted(res.classes.items()):
        stages = []
        for st in getattr(cls, "STAGES", ()):
            stages.append({
                "id": str(getattr(st, "id", "") or ""),
                "role": str(getattr(st, "role", "") or ""),
                "name": str(getattr(st, "name", "") or ""),
                "next": str(getattr(st, "next", "") or ""),
                "exit": str(getattr(st, "exit", "") or ""),
                "acceptance": [str(x) for x in (getattr(st, "acceptance", ()) or ())],
            })
        # t260927-05：外置模板拓扑导出（STAGES 线性投影，纯函数）＋声明项目键——
        # 消费方=workflow.py 目录/list 面与 ticket.py show 拓扑回落（同一权威面，
        # 不另立第二真源）。导出失败=该条目 topology=None + topology_error 点名
        # （fail-closed 不静默出假图），绝不让单模板炸掉整个回执。
        topology = None
        topology_error = ""
        try:
            from template_topology import topology_from_stages
            topology = topology_from_stages(
                tid, str(getattr(cls, "TEMPLATE_NAME", "") or tid),
                getattr(cls, "STAGES", ()))
        except Exception as e:  # 拓扑声明非法/STAGES 畸形：点名留痕，回执照常
            topology_error = "%s: %s" % (type(e).__name__, e)
        templates[tid] = {
            "name": str(getattr(cls, "TEMPLATE_NAME", "") or tid),
            "lane": str(getattr(cls, "TEMPLATE_LANE", "") or "main"),
            "workspace_dir": bool(getattr(cls, "TEMPLATE_WORKSPACE_DIR", False)),
            "stages": stages,
            # 声明项目键（builtin/夹具模板=""；项目外置模板=注册 key）——
            # 目录面按项目过滤的依据（「只有声明方看得见」）。
            "project": str((res.accepted.get(tid) or {}).get("project", "") or ""),
            "topology": topology,
            "topology_error": topology_error,
        }
    return _ok({
        "names": dict(shared.TEMPLATE_CLASS_NAMES),
        "class_available": sorted(res.classes),
        "accepted": sorted(res.accepted),
        "rejections": [dict(r) for r in res.rejections],
        "builtin": sorted(shared.BUILTIN_TEMPLATE_KEYS),
        "projects_scanned": res.projects_scanned,
        "declared_projects": res.declared_projects,
        "projects_root": str(shared.perkey_projects_root()),
        "templates": templates,
    })



COMMANDS = {
    "start": cmd_start,
    "query": cmd_query,
    "signal": cmd_signal,
    "schedule-list": cmd_schedule_list,
    "cancel": cmd_cancel,
    "ticket-cancel": cmd_ticket_cancel,
    "ticket-close-out": cmd_ticket_close_out,
    "ticket": cmd_ticket,
    "ticket-start": cmd_ticket_start,
    "ticket-list": cmd_ticket_list,
    "ticket-query": cmd_ticket_query,
    "ticket-prune": cmd_ticket_prune,
    "ticket-archive-legacy": cmd_ticket_archive_legacy,
    "running-tickets": cmd_running_tickets,
    "template-faces": cmd_template_faces,
}

USAGE = (
    "用法：python client.py <start|query|schedule-list|cancel|ticket|ticket-start|ticket-list|ticket-query|ticket-cancel|ticket-prune|ticket-archive-legacy|template-faces> [argsJSON]\n"
    "安全红线：工具面只暴露上述子命令，无 set-stage / force_stage / 改状态入口。\n"
    "signal 子命令已退役（260904 宿主令）：调用一律返回结构化退役报错（sign/retry_qc\n"
    "  只服务 v1 content-pipeline 人门段，该模板已删）；签字走 ticket op=sign，\n"
    "  blocked 重跑走 ticket op=retry_qc（t260910-06 正规通道）。\n"
    "ticket 子命令（步2）：op=rework|ruling|authorize|retry_qc|pause|resume|update|sign|query。\n"
    "  写 op 过跨项目闸（t260915-12）：调用方项目身份（env %s 或显式 caller_project）与目标\n"
    "  票项目不符=fail-closed 拒收（kind=cross_project_refused）；确需跨项目带越权旗\n"
    "  cross_project={by, reason 必填}（记名留痕可查）；未声明身份=拒收（缺省策略，\n"
    "  t260925-08 翻严）；过渡期可经旋钮 SANDBAR_UNDECLARED_POLICY=record 显式回记名放行\n"
    "  （契约见 server/engine/README.md）。\n"
    "  authorize=人授权签发（t260912-03：受保护路径/仲裁上限的放行钥匙，唯一入口＝\n"
    "  sign 信号面；kind/who/scope/reason/expires 由调用方注入，agent 不得自签）。\n"
    "  v2 引擎（M11 模版即代码）：advance/accept/dispatch-next 已取消（自动推进），\n"
    "  rework=signal 回目标段重跑，ruling=宿主裁决注入（人工意见正规通道，任何状态\n"
    "  可发，blocked 态注入后配 retry_qc 重跑下段即见），sign=人工审批签字，\n"
    "  pause/resume=段间暂停·恢复（t260908-01：当前段自然跑完停在段间门口，重复/空态\n"
    "  /畸形拒收落 refused，snapshot 的 paused/paused_phase 二态可观测），\n"
    "  update=状态维护，query 只读。\n"
    "ticket-start 创建 v2 工单（模板 id→workflow 类）；ticket-list/ticket-query=工单台数据源。\n"
    "ticket-cancel 记名单票终结（t260922-10，ticket.py op=cancel 的引擎侧）：\n"
    "  {ticket_id, who 必填, reason 必填}；先 cancel_notice 信号留痕（who+reason 入事件\n"
    "  历史，跨项目/未声明身份经闸落 cross_project_uses）后 terminate（reason 同串）；\n"
    "  已终态=幂等回执零改动；终态后票面快照不可得，权威对账=事件历史×admin.log 同串；\n"
    "  巡检票无信号 handler，仅事件历史+admin.log 留痕。裸 cancel 留给引擎件清场。\n"
    "ticket-prune 清理 closed 且已归档工单的 workflow 历史（Temporal 回归运行态，M1-3；\n"
    "  默认 --dry-run 零删除，--execute 真删；未归档/legacy 未确认双拒删，fail-closed）。\n"
    "template-faces 权威模板面查询（t260926-03 KI-123；只读、纯本地、不连 Temporal）：\n"
    "  引擎 venv 子进程现算类面（fresh importlib 深检），回执 names/class_available/\n"
    "  rejections/builtin/projects_scanned/declared_projects/projects_root——\n"
    "  ticket.py create 模板闸的单一权威源，类面拒收与空转在此点名而非静默。\n"
    "ticket-archive-legacy 存量诚实过账：closed 且无档票写 legacy manifest（不伪造不补产）。\n"
    "running-tickets=轻量 RUNNING 工单清单（console keepalive ensure 专用，无 snapshot 查询）。\n"
    '例：python client.py ticket-start \'{"ticket_id":"t260822-01","template_id":"dev-lane","title":"…"}\''
)


def _emit(sub: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
    """唯一回执出口（KI-067）：附 entry_hint（bare 待遇，含成功回执）→ 记
    admin.log 一行（claimed-source 可辨，连被拒收调用也记）→ 打印。审计**先于**
    打印（t260916-21 范围偏差·有意为之：client.py 在硬写集 server/engine/ 内；
    不改则验收⑤结构上不可达——打印在前则落盘失败的 audit_write_failed 点名
    永远无处附着，nusuyou/dengzhufpv 实测「写失败回执正常」正是此序所致）。
    审计失败不吞回执。"""
    audit.attach_entry_hint(result)
    # t260915-12：跨项目闸身份键随行落账（键在外层——拒收/成功同层同形状；兼容读内层）。
    # override 恒布尔：拒收行 override=false 也是对账面的一笔记录（场景相三判据）。
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}

    def _pick(name):
        v = result.get(name)
        return v if v is not None else inner.get(name)

    audit.audit_call(sub or "(none)", result,
                     caller_project=_pick("caller_project"),
                     identity_class=_pick("identity_class"),
                     identity_src=_pick("identity_src"),
                     override=bool(_pick("cross_project_used")))
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _emit(sub or "help", {}, {"ok": False, "error": USAGE})
        return

    fn = COMMANDS.get(sub)
    if fn is None:
        _emit(sub, {}, {"ok": False, "error": f"未知子命令 {sub!r}。{USAGE}"})
        return

    args: Dict[str, Any] = {}
    if len(sys.argv) > 2:
        try:
            parsed = json.loads(sys.argv[2])
            if not isinstance(parsed, dict):
                _emit(sub, {}, {"ok": False, "error": "argsJSON 需为 JSON 对象"})
                return
            args = parsed
        except json.JSONDecodeError as e:
            _emit(sub, {}, {"ok": False, "error": f"argsJSON 不是合法 JSON：{e}"})
            return

    try:
        result = asyncio.run(fn(args))
    except Exception as e:  # infra failure (cannot reach the server etc.) → structured receipt
        result = _classify_infra_error(e)

    _emit(sub, args, result)


if __name__ == "__main__":
    main()
    # On the connection-failure path the temporalio Rust core can SIGABRT during
    # interpreter teardown (confirmed in a 260909 container: the JSON receipt had already
    # landed on stdout, yet the exit code was -6, so the subprocess caller harvested a
    # signal death and the diagnostic string degraded to "exit -6"). The receipt contract
    # is fully discharged inside main(), so here we flush explicitly and exit the process,
    # skipping teardown — the exit code semantics stay byte-for-byte identical to the
    # normal path (every main() path exits 0). Active only under __main__: the module
    # import surface (server/tools calling in-process) never takes this path, so no side
    # effects.
    sys.stdout.flush()
    os._exit(0)
