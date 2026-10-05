# -*- coding: utf-8 -*-
"""executor_delivery —— executor project-ledger writes performed by the ENGINE
process (ticket t261004-27; host decision 261004 option 1, engine-side delivery).

Problem it closes: after the panel write gate (t261004-18) the executor's
remaining legitimate writes target the project ledger under
`$HOME/.sandbar/projects/<key>/…`, which sits OUTSIDE the executor session's
workspace-write sandbox. The pre-existing entries append IN the caller's
process (executor_requests.py CLI, the client.py grant-gate audit faces), so a
granted authority can be read but not exercised from that session (executor
request -0020 evidence). This module is the delivery face: the caller only
SUBMITS; a worker performs the ledger append in the engine process.

Faces (fixed, fail-closed — anything else is a named refusal):
  request         append one request row via executor_requests.append_request
  actions-record  record one gated-write verdict via executor_actions.record_from_gate
  grants-audit    append one grants audit row via executor_grants.append_audit

Callers (t261005-12): the executor grant gate (client._executor_grant_gate ->
_record_gate_engine_side -> _submit_engine_delivery) now submits face
`actions-record` so the verdict row is written by THIS engine process — the
sandboxed executor session cannot reach the project ledger (live 261005: every
in-process append failed silently, the Recent-actions pane stayed empty). The
CLI subcommand `deliver` keeps its own env>cwd identity resolution and
delegates submission to the same client helper. Body keys for
`actions-record`: {op, ticket, verdict, channel}.

Hard boundary: no self-authorization. This face performs no grant judgment,
never touches the declaration file, and cannot widen to non-ledger files.
Authority still comes only from the host (Grants page) or an on-record anchor.
What to grant is the host's decision (request -0001) and stays out of scope.

Identity survival (review R2, gen1 plan): identity is resolved ONCE, caller
side (client.py `deliver`), and shipped in the payload as an explicit
`identity` block. The engine-side core NEVER lets the borrowed functions read
the worker's ambient env: it builds the env dict handed to append_request from
the identity block only, and passes `session=` explicitly into
record_from_gate. The worker env identifies the ENGINE, not the caller, and is
structurally unread here.

Truthful who (review R3): the face derives identity from env > cwd at the CLI
and accepts NO caller_project argument (present = named refusal). Receipts
carry who (session id), identity_src and channel_src — the derivation source
is on record with every row.

Payload contract (workflow input):
  {"face": "request"|"actions-record"|"grants-audit",
   "key": <project key>,                       # == identity.project, cross-checked
   "identity": {"project", "session", "channel", "identity_src"},
   "body": {...}}                              # face-specific, sanitized

Receipt: {"ok": True, "face", "who", "identity_src", "channel_src", "result"}
or {"ok": False, "field", "error"} — every refusal is named, no refusal path
writes anything.

Workflow: ephemeral, one delivery per run. Deterministic id
`executor-delivery-<key>-<idem>` (sha1 + 10-min UTC bucket, executor_actions
shape) so a caller retry inside one bucket collapses onto the first receipt —
two intentionally identical appends in one bucket are ONE row; a caller that
truly needs a second row waits out the bucket.

temporalio import is guarded: the delivery core below is importable in a
temporalio-free interpreter (the same light-import discipline the audit faces
already follow); only the workflow/activity shells need temporalio and the
worker always has it.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Dict, Optional

import executor_actions
import executor_grants
import executor_requests
import shared

FACES = ("request", "actions-record", "grants-audit")
DELIVERED_VIA = "engine-process"
IDEM_BUCKET_MS = executor_actions.IDEM_BUCKET_MS   # same bucket shape, one truth
WORKFLOW_ID_PREFIX = "executor-delivery"
# Ledger-LOCATION seams only (forwarded from the executing process; these decide
# WHERE a row lands, never WHO raised it — identity keys are overridden below).
LEDGER_ROOT_ENV_KEYS = ("SANDBAR_PANEL_DIR", "SANDBAR_PROJECTS_DIR", "DSH_HOME", "HOME")

DeliveryHandlers = Dict[str, Callable[..., Any]]


# ---------- payload / id helpers ----------

def identity_block(project: str, session: str, channel: str, identity_src: str) -> Dict[str, str]:
    """Caller-resolved identity shipped into the payload (the ONLY identity the
    engine side consumes; the worker's own env is never read)."""
    return {"project": str(project or ""), "session": str(session or ""),
            "channel": str(channel or ""), "identity_src": str(identity_src or "")}


def delivery_idem(face: str, key: str, session: str, body: Dict[str, Any], at_ms: int) -> str:
    """Deterministic idem: stable payload summary + 10-min UTC bucket
    (executor_actions.idem_key shape; bucket-bound duplicate artifact declared
    in the module head)."""
    bucket = int(max(0, int(at_ms)) // IDEM_BUCKET_MS)
    basis = "|".join([str(face or ""), str(key or ""), str(session or ""),
                      json.dumps(body, sort_keys=True, ensure_ascii=False,
                                  default=str)[:512], str(bucket)])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def workflow_id_for(key: str, idem: str) -> str:
    return "%s-%s-%s" % (WORKFLOW_ID_PREFIX, key, idem)


def _injected_env(identity: Dict[str, str], env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The env the borrowed functions see. Identity keys come ONLY from the
    identity block (the worker env identifies the engine, never the caller —
    a poisoned decoy session id in the process env cannot leak into a row).
    Ledger-LOCATION seams (where to write, never who writes) forward from the
    worker env so the delivery lands in the instance's projects root."""
    out = {k: str(env[k]) for k in LEDGER_ROOT_ENV_KEYS
           if env is not None and env.get(k) is not None}
    out.update({
        shared.CALLER_PROJECT_ENV: identity["project"],
        "DSH_SESSION_ID": identity["session"],
        "DSH_HEADLESS_SESSION": "",
        shared.CALLER_IDENTITY_SRC_ENV: identity["channel"],
        shared.CALLER_SURFACE_ENV: "",
    })
    return out


def default_handlers() -> DeliveryHandlers:
    return {
        "request": lambda body, now_ms, env: executor_requests.append_request(
            body, now_ms, env=env, delivered_via=DELIVERED_VIA),
        "actions-record": lambda body, key, identity, now_ms: (
            executor_actions.record_from_gate(
                str(body.get("op") or ""), str(key or ""), str(body.get("ticket") or ""),
                body.get("verdict") if isinstance(body.get("verdict"), dict) else {},
                str(body.get("channel") or identity.get("channel") or ""),
                now_ms=now_ms, session=identity["session"])),
        "grants-audit": lambda body, key: executor_grants.append_audit(
            str(key or ""), body.get("row") if isinstance(body.get("row"), dict) else {}),
    }


# ---------- engine-side core (temporalio-free; IO-injectable for tests) ----------

def perform_delivery(payload: Any, now_ms: int,
                     env: Optional[Dict[str, str]] = None,
                     handlers: Optional[DeliveryHandlers] = None,
                     ) -> Dict[str, Any]:
    """One delivery, executed IN the engine process. Pure dispatch on `face`
    with the identity cross-checks ahead of any handler call: every refusal
    path below returns before a single byte is written. `env` is the EXECUTING
    process env: only ledger-location keys are forwarded; identity never rides it."""
    hs = default_handlers() if handlers is None else handlers
    payload = executor_requests._sanitize(payload)
    if not isinstance(payload, dict):
        return {"ok": False, "field": "body",
                "error": "delivery payload must be a JSON object (got %s)"
                         % type(payload).__name__}
    face = str(payload.get("face") or "")
    if face not in FACES:
        return {"ok": False, "field": "face",
                "error": "unknown delivery face %r — allowed faces: %s (fixed; fail-closed)"
                         % (face[:40], list(FACES))}
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        return {"ok": False, "field": "identity",
                "error": "identity block missing — the caller resolves identity once "
                         "(env > cwd) and ships it; the engine side never re-derives it "
                         "from the worker env"}
    key = str(payload.get("key") or "")
    project = str(identity.get("project") or "")
    session = str(identity.get("session") or "")
    if not project:
        return {"ok": False, "field": "identity",
                "error": "identity block must carry a non-empty project "
                         "(who, and the derivation source)"}
    if not session and face != "actions-record":
        # t261005-12: the gate verdict row keeps the pre-ticket session semantics —
        # the session column is best-effort identity (the old in-process
        # record_from_gate wrote '' when no env session existed, and the row was
        # still the gate's on-record verdict). Refusing the row for an absent
        # session would silently unrecord every sessionless gated write. Every
        # other face keeps the strict non-empty session rule.
        return {"ok": False, "field": "identity",
                "error": "identity block must carry a non-empty session "
                         "(who, and the derivation source)"}
    if not key:
        return {"ok": False, "field": "key", "error": "delivery target project key missing"}
    if key != project:
        return {"ok": False, "field": "identity",
                "error": "payload key %r disagrees with identity.project %r — the delivery "
                         "target is the caller's own project" % (key[:64], project[:64])}
    body = payload.get("body")
    if not isinstance(body, dict):
        return {"ok": False, "field": "body",
                "error": "delivery body must be a JSON object (got %s)"
                         % type(body).__name__}
    if face == "request":
        # Truthful who: identity is derived at the caller, never declared (R3).
        if body.get("caller_project"):
            return {"ok": False, "field": "caller_project",
                    "error": "the deliver face derives identity from the environment and "
                             "working directory — a caller_project declaration is not accepted here"}
        if body.get("face"):
            return {"ok": False, "field": "body",
                    "error": "face belongs to the delivery envelope, not the request body"}
        result = hs["request"](body, now_ms, _injected_env(identity, env))
    elif face == "actions-record":
        result = hs["actions-record"](body, key, identity, now_ms)
    else:
        result = hs["grants-audit"](body, key)
    if isinstance(result, dict) and result.get("ok") is False:
        out: Dict[str, Any] = {"ok": False, "field": result.get("field") or "body"}
        out["error"] = result.get("error") or result.get("reason") or "delivery refused"
        return out
    # t261004-43 Required (4): the receipt must expose mis-location by itself —
    # a relative result.file (the tell of the live 261004 defect) is stored
    # absolute. No-op on results without a file field; row content untouched.
    if isinstance(result, dict) and result.get("file"):
        result["file"] = os.path.abspath(str(result["file"]))
    return {"ok": True, "face": face, "who": session,
            "identity_src": str(identity.get("identity_src") or ""),
            "channel_src": str(identity.get("channel") or ""),
            "result": result}


def delivery_payload(face: str, key: str, identity: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
    """CLI-side payload assembly (identity already resolved caller-side)."""
    return {"face": str(face or ""), "key": str(key or ""),
            "identity": dict(identity), "body": body}


# ---------- workflow / activity shells (worker side; temporalio required) ----------

try:  # noqa: SIM105 — guarded light import; the core above stays temporalio-free
    from datetime import timedelta

    from temporalio import activity as _activity
    from temporalio import workflow as _workflow

    @_activity.defn(name="executor_delivery_activity")
    async def delivery_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Runs in the worker: the append happens in the ENGINE process.
        t261004-43: this shell is the ledger-LOCATION forwarding point — the
        executing-process env rides in (filtered to LEDGER_ROOT_ENV_KEYS) so
        the row lands in the instance projects root, never relative to the
        worker cwd. Identity still comes only from the payload block."""
        import time as _time
        return perform_delivery(payload, int(_time.time() * 1000), env=dict(os.environ))

    @_workflow.defn
    class ExecutorDeliveryWorkflow:
        """Ephemeral, one delivery per run; every path returns a receipt.
        No timers, no child workflows, no spawns — full-terminal-state by shape."""

        @_workflow.run
        async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            return await _workflow.execute_activity(
                delivery_activity, payload, start_to_close_timeout=timedelta(seconds=60))

except ImportError:  # temporalio-free interpreter: core only, shells absent
    ExecutorDeliveryWorkflow = None  # type: ignore[assignment]
    delivery_activity = None  # type: ignore[assignment]
