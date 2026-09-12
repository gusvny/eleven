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

stdout always emits **one line of JSON**, `{"ok": true, "result": ...}` or
`{"ok": false, "error": "..."}`, parsed directly by the node.ts plugin. Temporal's
"audit / immutable history" is the workflow's own event history; no separate run_id is
invented.

Usage (each subcommand takes one JSON argument, default {}):

    python client.py start '{"type":"dispatcher-scan","id":"dispatcher-scan"}'
    python client.py query '{"workflow_id":"t260822-01"}'
    python client.py schedule-list
    python client.py cancel '{"workflow_id":"dispatcher-scan","reason":"清场"}'
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

from temporalio.client import Client
from temporalio.common import SearchAttributeKey

from shared import (
    AUTH_KINDS,
    DISPATCHER_WF_ID,
    ENGINE_V2,
    EPIC_CODE_RE,
    EPIC_SA_NAME,
    NAMESPACE,
    PROJECT_SA_NAME,
    TARGET_HOST,
    TASK_QUEUE,
    TICKET_QUEUE_PREFIX,
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


def _err(msg: str, kind: str = KIND_INTERNAL) -> Dict[str, Any]:
    """Structured error receipt. kind = the error class (see the table above); consumers
    route 404/503/410 from it. The "ticket does not exist" wording may only be produced
    with kind=not_found."""
    return {"ok": False, "error": msg, "kind": kind}


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


async def _connect() -> Client:
    return await Client.connect(TARGET_HOST, namespace=NAMESPACE)


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
                "ticket op=sign，清场/撤销走 cancel。")


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


async def cmd_cancel(args: Dict[str, Any]) -> Dict[str, Any]:
    wf_id = str(args.get("workflow_id") or "")
    if not wf_id:
        return _err("cancel 需要 workflow_id")
    reason = str(args.get("reason") or "client.py cancel")
    client = await _connect()
    handle = client.get_workflow_handle(wf_id)
    try:
        await handle.terminate(reason=reason)
    except Exception as e:  # already finished / missing etc. always produce a structured receipt, never a stack trace
        return _err(f"terminate 失败：{type(e).__name__}: {e}")
    return _ok({"workflow_id": wf_id, "terminated": True, "reason": reason})


async def cmd_ticket(args: Dict[str, Any]) -> Dict[str, Any]:
    """Ticket stage machine (step 2): exposes only legal advance entries, no set-stage /
    force_stage.

    op ∈ advance / accept / rework / update / dispatch-next / sign / query.
    The first five are workflow updates (synchronous result + into the immutable
    history); sign is a human approval signature; query is read-only.
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
        await handle.signal("sign", sig)  # a signal with the same name on old and new classes; sending by name serves both
        return _ok({"ticket_id": tid, "signal": "sign", "gate": sig.gate,
                    "decision": sig.decision, "who": sig.who, "delivered": True})

    if op == "authorize":
        # t260912-03：人授权例外通道（受保护路径 / 仲裁上限）——**唯一入口＝sign 信号面**
        # （Signature.authorize 载荷；此处不新开信号，与签字同源同审计面）。本侧只做
        # payload 归一（expires 收 ISO8601|epoch 秒两形）+ 结构性拒收（畸形=结构化 _err，
        # 不进事件历史）；who/scope/reason/上限与反自签的权威判定在 workflow intake
        # （authz_gates.validate_authorization，refused 可观测）。
        auth, aerr = normalize_authorize_args(args)
        if auth is None:
            return _err(aerr)
        sig = Signature(who=auth.who, gate="", decision="approve", authorize=auth)
        await handle.signal("sign", sig)  # 同一 sign 信号面（不得新开旁路）
        return _ok({"ticket_id": tid, "signal": "sign(authorize)", "kind": auth.kind,
                    "who": auth.who, "scope": list(auth.scope),
                    "expires": auth.expires, "delivered": True})

    if op == "rework":
        # v2: rework = a signal (re-run from the target stage)
        note = str(args.get("note") or "")
        if not note:
            return _err("rework 需要 note（返工原因）")
        req = ReworkRequest(who=str(args.get("who") or "op-local"),
                            target_stage=str(args.get("to_stage") or ""),
                            note=note)
        await handle.signal("rework", req)
        return _ok({"ticket_id": tid, "signal": "rework",
                    "target_stage": req.target_stage, "delivered": True})

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
        return _ok({"ticket_id": tid, "signal": "retry_qc", "who": who,
                    "delivered": True})

    if op == "ruling":
        # KI-053: host ruling injection — the official channel for human opinions,
        # sendable in any state (blocked included).
        # Sending a ruling does not automatically wake a blocked: the re-run still needs
        # a retry_qc, and the next prompt picks up the ruling (the build_stage_prompt
        # injection surface).
        note = str(args.get("note") or "")
        if not note.strip():
            return _err("ruling 需要 note（裁决内容，非空）")
        req = HostRulingRequest(who=str(args.get("who") or "op-local"), note=note)
        await handle.signal("host_ruling", req)
        return _ok({"ticket_id": tid, "signal": "host_ruling", "who": req.who,
                    "delivered": True})

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
        req = PauseRequest(who=who, note=note)
        await handle.signal(op, req)
        return _ok({"ticket_id": tid, "signal": op, "who": req.who,
                    "delivered": True})

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
        return _ok(r)

    return _err("未知工单操作 %r（可用：rework=打回 / ruling=宿主裁决注入 / "
                "authorize=人授权签发（sign 信号面） / retry_qc=blocked 重跑 / "
                "pause|resume=段间暂停·恢复 / update=更新 / sign=签字 / query=查询）" % op)


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
        return _err("未知模板 %r（可用：%s）" % (tpl, "、".join(sorted(TEMPLATE_CLASSES))))
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
        # t260911-03 路径闸总开关：新派单钉死进输入（replay 稳定）——只对 dev-lane 模板
        # 开（段×面规则表的键集=dev-lane 段链；退役模板/fixture 模板不受闸，回归面为零）。
        # 老在途票的已记录输入无此字段 → 永远 False，不追溯。
        path_gate=(str(tpl) == "dev-lane"),
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
    return _ok({
        "id": tid, "workflow_id": handle.id, "run_id": handle.result_run_id,
        "template": tpl, "workflow_class": cls.__name__,
        "project": project, "epic": epic,
        "stage": first.id, "stage_state": "running", "role": first.role,
        "status": "dispatched", "engine": ENGINE_V2,
    })


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
        # t260912-03：本票生效中的人授权（类型/范围/授权人/到期在 ticket show 的
        # meta.authorizations 全量可读；列表行只给计数徽标数据源）
        "authz_active": len(_authz),
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
        return _err("工单已终态（%s），快照不可得——终态票不再推进，刷新无效"
                    % (exec_status or "未知"), KIND_TERMINAL)
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
    260824 起工单走每工单专属队列（LEGACY 旧前缀 <id> 形态），过滤器放行共享队列 + 新旧专属前缀。  # naming-compat"""
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
    # Multiple runs with the same id: non-TERMINATED wins — a ticket reopened under the
    # same id after a terminate must reach the board (a seen-mark-first approach would
    # let the old TERMINATED run swallow the new reopened run and the board entry would
    # vanish).
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
                        "close_ts": wf.close_time.timestamp() if wf.close_time else 0})

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
        if exec_status == "RUNNING":
            try:
                snap = await _query_snapshot_with_retry(client.get_workflow_handle(tid))
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
                m = dict((snap or {}).get("meta") or {})
                m["paused"] = bool((snap or {}).get("paused"))
                m["paused_phase"] = str((snap or {}).get("paused_phase") or "")
                return m
            except Exception:
                return {}
        return {}

    metas = await asyncio.gather(*(_meta_of(e["id"], e["exec_status"], e["close_ts"]) for e in entries))
    for e, meta in zip(entries, metas):
        tid, sa_project, sa_epic = e["id"], e["sa_project"], e["sa_epic"]
        exec_status = e["exec_status"]
        if meta.get("_query_degraded"):
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
                         "authz_active": 0})  # t260912-03 降级/极简行同形（无快照=无授权面可读）
    rows.sort(key=lambda r: -(r.get("created") or 0))
    return _ok({"count": len(rows), "tickets": rows})


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
    "  只服务 v1 content-pipeline 人门段，该模板已删）；签字走 ticket op=sign，\n"
    "  blocked 重跑走 ticket op=retry_qc（t260910-06 正规通道）。\n"
    "ticket 子命令（步2）：op=rework|ruling|authorize|retry_qc|pause|resume|update|sign|query。\n"
    "  authorize=人授权签发（t260912-03：受保护路径/仲裁上限的放行钥匙，唯一入口＝\n"
    "  sign 信号面；kind/who/scope/reason/expires 由调用方注入，agent 不得自签）。\n"
    "  v2 引擎（M11 模版即代码）：advance/accept/dispatch-next 已取消（自动推进），\n"
    "  rework=signal 回目标段重跑，ruling=宿主裁决注入（人工意见正规通道，任何状态\n"
    "  可发，blocked 态注入后配 retry_qc 重跑下段即见），sign=人工审批签字，\n"
    "  pause/resume=段间暂停·恢复（t260908-01：当前段自然跑完停在段间门口，重复/空态\n"
    "  /畸形拒收落 refused，snapshot 的 paused/paused_phase 二态可观测），\n"
    "  update=状态维护，query 只读。\n"
    "ticket-start 创建 v2 工单（模板 id→workflow 类）；ticket-list/ticket-query=工单台数据源。\n"
    "ticket-prune 清理 closed 且已归档工单的 workflow 历史（Temporal 回归运行态，M1-3；\n"
    "  默认 --dry-run 零删除，--execute 真删；未归档/legacy 未确认双拒删，fail-closed）。\n"
    "ticket-archive-legacy 存量诚实过账：closed 且无档票写 legacy manifest（不伪造不补产）。\n"
    "running-tickets=轻量 RUNNING 工单清单（console keepalive ensure 专用，无 snapshot 查询）。\n"
    '例：python client.py ticket-start \'{"ticket_id":"t260822-01","template_id":"dev-lane","title":"…"}\''
)


def _emit(sub: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
    """唯一回执出口（KI-067）：附 entry_hint（bare 待遇，含成功回执）→ 打印 →
    记 admin.log 一行（claimed-source 可辨，连被拒收调用也记）。审计失败不吞回执。"""
    audit.attach_entry_hint(result)
    print(json.dumps(result, ensure_ascii=False))
    audit.audit_call(sub or "(none)", result)


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
        result = _err(f"{type(e).__name__}: {e}")

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
