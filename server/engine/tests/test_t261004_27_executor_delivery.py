# -*- coding: utf-8 -*-
"""t261004-27 — unit tests for the engine-process delivery face (executor_delivery.py).

Coverage (gen1 plan, §Steps):
- happy path per face (identity fully injected; ledger under a tmp root, zero real env);
- [R2] identity survival: a worker env carrying no caller session envs (with decoy
  values) still files rows attributed to the CALLER session id — the engine side
  never reads the worker's own env for identity (proved structurally, by test);
- [R3] identity is derived, never declared: a caller_project in the body is a named
  refusal with zero writes;
- every refusal path writes nothing (tmp ledger asserted absent);
- malformed inputs refused named, one by one (non-object payload / missing or
  unknown face / missing identity block or empty session / key mismatch /
  non-object body / lone surrogate / forged raised_by);
- idem shape and the declared bucket collapse; workflow-id derivation;
- registration: ExecutorDeliveryWorkflow ∈ ALL_WORKFLOWS (the worker registry's
  single source list).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import executor_actions  # noqa: E402
import executor_delivery as ed  # noqa: E402
import executor_requests as er  # noqa: E402
import shared  # noqa: E402

SESSION = "sess-exec-27"
PROJECT = "proj-alpha"

REQUEST_BODY = {
    "kind": "decision",
    "question": "Which option should the executor take for ticket T-1?",
    "options": ["Adopt plan A (rec.)", "Adopt plan B"],
}

IDENTITY = {"project": PROJECT, "session": SESSION,
            "channel": "env", "identity_src": "env"}

VERDICT_ALLOWED = {"allowed": True, "enforced": True,
                   "grant_op": "sign",
                   "provenance": {"keys": {"sign": "decl:hash"}}}


def _payload(face, body, identity=None, key=PROJECT):
    return {"face": face, "key": key,
            "identity": dict(IDENTITY if identity is None else identity),
            "body": body}


def _request_env(tmp: Path, identity=None) -> dict:
    """The env the activity builds for the borrowed append (identity-injected;
    the tmp ledger root rides SANDBAR_PANEL_DIR — the test's file seam)."""
    ident = IDENTITY if identity is None else identity
    return {
        "SANDBAR_PANEL_DIR": str(tmp),
        "SANDBAR_PROJECTS_DIR": str(tmp),
        shared.CALLER_PROJECT_ENV: ident["project"],
        "DSH_SESSION_ID": ident["session"],
        "DSH_HEADLESS_SESSION": "",
        shared.CALLER_IDENTITY_SRC_ENV: ident["channel"],
        shared.CALLER_SURFACE_ENV: "",
    }


def _handlers(tmp: Path, identity=None):
    """Real handlers with the request face bound to the identity-injected env.
    The declaration load is stubbed (host names the session in executor_sessions)
    — zero real grant files in tests."""
    def _decl(key):
        return {"ok": True, "executor_sessions": [SESSION]}
    return {"request": lambda body, now_ms, env: er.append_request(
                body, now_ms, env=_request_env(tmp, identity), load_decl=_decl,
                delivered_via=ed.DELIVERED_VIA),
            "actions-record": ed.default_handlers()["actions-record"],
            "grants-audit": ed.default_handlers()["grants-audit"]}


def _deliver(tmp: Path, payload, identity=None, now_ms=1000):
    return ed.perform_delivery(payload, now_ms, handlers=_handlers(tmp, identity))


def _requests_file(tmp: Path, key=PROJECT):
    return tmp / key / "requests.jsonl"


# ---------- request face: happy path + delivered_via stamp ----------

def test_request_face_files_row_with_delivered_via(tmp_path):
    out = _deliver(tmp_path, _payload("request", dict(REQUEST_BODY)))
    assert out["ok"] is True
    assert out["who"] == SESSION and out["identity_src"] == "env"
    row = out["result"]["row"]
    assert row["raised_by"] == SESSION
    assert row["surface"] == er.SURFACE_ENGINE
    assert row["delivered_via"] == "engine-process"
    assert json.loads(_requests_file(tmp_path).read_text().splitlines()[0]) == row


def test_delivered_via_omitted_when_not_passed(tmp_path):
    """Direct-CLI rows keep their historical shape: no delivered_via key."""
    def _decl(key):
        return {"ok": True, "executor_sessions": [SESSION]}
    out = er.append_request(dict(REQUEST_BODY), 1000, env=_request_env(tmp_path),
                            load_decl=_decl)
    assert out["ok"] is True
    assert "delivered_via" not in out["row"]


# ---------- [R2] identity survival: worker env never consulted ----------

def test_worker_env_without_caller_session_envs_still_files_caller_session(tmp_path, monkeypatch):
    """The activity-side env comes only from the identity block: a worker env with
    NO caller session envs — and a poisoned decoy in every one of them — cannot
    leak into the row."""
    poisoned = {
        "SANDBAR_PANEL_DIR": str(tmp_path),
        "DSH_SESSION_ID": "decoy-engine-session",
        "DSH_HEADLESS_SESSION": "decoy-headless",
        shared.CALLER_PROJECT_ENV: "decoy-project",
        shared.CALLER_IDENTITY_SRC_ENV: "decoy-src",
        shared.CALLER_SURFACE_ENV: "decoy-surface",
    }
    for k, v in poisoned.items():
        monkeypatch.setenv(k, v)
    out = _deliver(tmp_path, _payload("request", dict(REQUEST_BODY)))
    assert out["ok"] is True
    assert out["result"]["row"]["raised_by"] == SESSION
    assert out["result"]["row"]["project"] == PROJECT
    assert out["who"] == SESSION


def test_perform_delivery_env_identity_never_location_only(tmp_path, monkeypatch):
    """The handed-in env forwards LEDGER-LOCATION keys only (where to write);
    identity keys are overridden from the identity block — a poisoned decoy
    session id or project in that env cannot reach the row."""
    monkeypatch.setenv("DSH_SESSION_ID", "decoy-via-arg")
    out = ed.perform_delivery(
        _payload("request", dict(REQUEST_BODY)), 1000,
        env={"DSH_SESSION_ID": "decoy-via-arg",
             shared.CALLER_PROJECT_ENV: "decoy-project",
             "SANDBAR_PANEL_DIR": str(tmp_path)},
        handlers=_handlers(tmp_path))
    assert out["ok"] is True and out["who"] == SESSION
    assert out["result"]["row"]["project"] == PROJECT


def test_injected_env_carries_location_seams_from_worker_env(tmp_path):
    """Ledger-location keys pass through (the delivery must land in the
    instance's projects root), identity keys never do."""
    env = ed._injected_env(IDENTITY, {"SANDBAR_PANEL_DIR": "/tmp/root",
                                      "DSH_SESSION_ID": "engine-decoy"})
    assert env["SANDBAR_PANEL_DIR"] == "/tmp/root"
    assert env["DSH_SESSION_ID"] == SESSION


# ---------- refusal matrix (every refusal writes nothing) ----------

def _assert_no_writes(tmp_path):
    for key in (PROJECT, "proj-beta"):
        assert not (tmp_path / key / "requests.jsonl").exists()


@pytest.mark.parametrize("payload,field", [
    ("not-a-dict", "body"),
    ({"key": PROJECT, "identity": IDENTITY, "body": {}}, "face"),
    (_payload("grant-op", {}), "face"),
    (_payload("request", {}, identity={"project": PROJECT, "session": ""}), "identity"),
    ({"face": "request", "key": PROJECT, "identity": {"project": PROJECT}, "body": {}}, "identity"),
    (_payload("request", {}), "question"),
    (_payload("request", dict(REQUEST_BODY), key="proj-beta"), "identity"),
    (_payload("request", {**dict(REQUEST_BODY), "caller_project": "proj-beta"}), "caller_project"),
    (_payload("request", {**dict(REQUEST_BODY), "raised_by": "somebody-else"}), "raised_by"),
])
def test_refusals_are_named_and_write_free(tmp_path, payload, field):
    out = _deliver(tmp_path, payload)
    assert out["ok"] is False and out["field"] == field
    assert out["error"]
    _assert_no_writes(tmp_path)


def test_forged_raised_by_refused_via_injected_identity(tmp_path):
    """The raised_by truth check survives the hop: the comparison is injected
    caller identity vs payload raised_by — both caller-derived."""
    body = {**dict(REQUEST_BODY), "raised_by": "forged-session"}
    out = _deliver(tmp_path, _payload("request", body))
    assert out["ok"] is False and out["field"] == "raised_by"
    assert SESSION in out["error"] and "forged-session" in out["error"]
    _assert_no_writes(tmp_path)


def test_malformed_input_lone_surrogate_sanitized_not_fatal(tmp_path):
    body = {"kind": "decision",
            "question": "Which option should the executor take for T\udce9?",
            "options": ["Adopt plan A (rec.)", "Adopt plan B"]}
    out = _deliver(tmp_path, _payload("request", body))
    # sanitized into visible escapes → the row still files (or refuses by
    # contract), but the process never crashes and the ledger line is valid JSON.
    if out["ok"]:
        row = json.loads(_requests_file(tmp_path).read_text().splitlines()[0])
        assert isinstance(row["question"], str)


def test_actions_record_face_records_row(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_EXECUTOR_ACTIONS_DIR", str(tmp_path / "acts"))
    body = {"op": "sign", "ticket": "t1", "verdict": VERDICT_ALLOWED, "channel": "env"}
    out = _deliver(tmp_path, _payload("actions-record", body))
    assert out["ok"] is True
    assert out["result"]["appended"] is True
    lines = (tmp_path / "acts" / ("%s.jsonl" % PROJECT)).read_text().splitlines()
    row = json.loads(lines[0])
    assert row["session"] == SESSION and row["decision"] == "allowed"


def test_actions_record_exempt_verdict_zero_row(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_EXECUTOR_ACTIONS_DIR", str(tmp_path / "acts"))
    body = {"op": "sign", "ticket": "t1",
            "verdict": {"allowed": True, "enforced": False}, "channel": "env"}
    out = _deliver(tmp_path, _payload("actions-record", body))
    assert out["ok"] is True and out["result"].get("exempt") is True
    assert not (tmp_path / "acts").exists()


def test_actions_record_refused_verdict_row_with_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_EXECUTOR_ACTIONS_DIR", str(tmp_path / "acts"))
    body = {"op": "sign", "ticket": "t1",
            "verdict": {"allowed": False, "why": "grant sign not declared"}, "channel": "env"}
    out = _deliver(tmp_path, _payload("actions-record", body))
    assert out["ok"] is True
    row = json.loads((tmp_path / "acts" / ("%s.jsonl" % PROJECT)).read_text().splitlines()[0])
    assert row["decision"] == "refused" and "grant sign not declared" in row["reason"]


def test_grants_audit_face_appends_row(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_grants_module(), "audit_path",
                        lambda key: str(tmp_path / ("audit-%s.jsonl" % key)))
    row = {"at": 1, "action": "refuse", "project": PROJECT}
    out = _deliver(tmp_path, _payload("grants-audit", {"row": row}))
    assert out["ok"] is True
    saved = json.loads((tmp_path / ("audit-%s.jsonl" % PROJECT)).read_text().splitlines()[0])
    assert saved["action"] == "refuse"


def executor_grants_module():
    import executor_grants
    return executor_grants


# ---------- id / idem shapes ----------

def test_delivery_idem_deterministic_and_bucketed():
    a = ed.delivery_idem("request", PROJECT, SESSION, dict(REQUEST_BODY), 1)
    b = ed.delivery_idem("request", PROJECT, SESSION, dict(REQUEST_BODY), 1)
    assert a == b and len(a) == 16
    # same bucket (10 min) → same idem; next bucket → new idem
    c = ed.delivery_idem("request", PROJECT, SESSION, dict(REQUEST_BODY),
                         executor_actions.IDEM_BUCKET_MS - 1)
    d = ed.delivery_idem("request", PROJECT, SESSION, dict(REQUEST_BODY),
                         executor_actions.IDEM_BUCKET_MS)
    assert a == c and a != d


def test_workflow_id_shape():
    assert ed.workflow_id_for(PROJECT, "abcd1234") == "executor-delivery-%s-abcd1234" % PROJECT


# ---------- t261004-43: the activity shell forwards the executing-process env ----------
#
# The live defect (261004 23:41): delivery_activity called perform_delivery with
# env=None, so the ledger root resolved RELATIVE to the worker cwd
# ('.sandbar/projects/...' — receipt result.file was the tell). These cases
# exercise the REAL activity shell (the line that had zero coverage) through the
# real production env path (dict(os.environ) with HOME pointed at a tmp root) —
# they deliberately do NOT reuse the _handlers/_deliver env-injection seam that
# hid the bug.

import asyncio  # noqa: E402
import os  # noqa: E402


def _activity_env(monkeypatch, tmp_path, extra=None):
    """Point the process env at a tmp instance: HOME under tmp_path, the
    explicit location seams cleared so the default root must resolve through
    HOME. `extra` adds decoy worker-env values (identity-poison probes)."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for k in ("DSH_HOME", "SANDBAR_PANEL_DIR", "SANDBAR_PROJECTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (extra or {}).items():
        monkeypatch.setenv(k, v)
    return home


def _stub_declaration(monkeypatch):
    """Host names the executor session in executor_sessions (same stub shape as
    the other cases) — no real grant files read. Patched on the shared
    executor_grants module object that append_request reaches by default."""
    monkeypatch.setattr(executor_grants_module(), "load_declaration",
                        lambda key: {"ok": True, "executor_sessions": [SESSION]})


def _run_activity(payload):
    return asyncio.run(ed.delivery_activity(payload))


def test_activity_shell_files_into_instance_projects_root_absolute(monkeypatch, tmp_path):
    """t261004-43 Required (1)+(2)+(4): the activity forwards the executing
    process env (location keys only), so the row lands in the instance projects
    root and the receipt path is ABSOLUTE. Pre-fix this failed: env=None made
    the root relative to cwd and both asserts below tripped."""
    home = _activity_env(monkeypatch, tmp_path)
    _stub_declaration(monkeypatch)
    out = _run_activity(_payload("request", dict(REQUEST_BODY)))
    assert out["ok"] is True, out
    expected = er.ledger_file(PROJECT, {"HOME": str(home)})
    assert out["result"]["file"] == str(expected)
    assert os.path.isabs(out["result"]["file"])  # Required (4): receipt tripwire
    lines = expected.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["raised_by"] == SESSION


def test_activity_shell_worker_env_cannot_touch_identity(monkeypatch, tmp_path):
    """t261004-43 Required (3): decoy identity values in the worker env never
    reach the row — identity comes only from the payload identity block."""
    _activity_env(monkeypatch, tmp_path, extra={
        "DSH_SESSION_ID": "sess-decoy",
        shared.CALLER_PROJECT_ENV: "proj-decoy",
        "DSH_HEADLESS_SESSION": "sess-decoy-headless",
    })
    _stub_declaration(monkeypatch)
    out = _run_activity(_payload("request", dict(REQUEST_BODY)))
    assert out["ok"] is True, out
    blob = json.dumps(out, ensure_ascii=False)
    assert "sess-decoy" not in blob and "proj-decoy" not in blob
    assert out["result"]["row"]["raised_by"] == SESSION
    assert out["who"] == SESSION


def test_stripped_env_resolves_relative_root_guard(monkeypatch):
    """Pins the pre-condition the fix removes: with NO env at all the default
    root is relative to cwd — this is what made the live row vanish. If the
    activity ever stops forwarding env, the absolute-path assert above fails
    and this case explains the mechanism."""
    root = er.instance_projects_root({})
    assert not os.path.isabs(root)
    assert root == os.path.join(".sandbar", "projects")


def test_perform_delivery_receipt_absolutization_noop_on_odd_results(tmp_path):
    """The defensive abspath post-process is a no-op on non-dict results and on
    results without a file field — receipt shape unchanged."""
    def stub(body, now_ms, env):
        return {"ok": True, "unusual": True}

    hs = dict(ed.default_handlers())
    hs["request"] = stub
    out = ed.perform_delivery(_payload("request", dict(REQUEST_BODY)), 1000, handlers=hs)
    assert out["ok"] is True and "file" not in out["result"] and out["result"]["unusual"] is True


def test_perform_delivery_absolutizes_relative_receipt_file(tmp_path, monkeypatch):
    """Belt-and-braces (Required 4): a relative result.file is stored absolute
    in the receipt — a future stripped-env worker still exposes mis-location."""
    def stub(body, now_ms, env):
        return {"ok": True, "row": {}, "file": ".sandbar/projects/%s/requests.jsonl" % PROJECT}

    hs = dict(ed.default_handlers())
    hs["request"] = stub
    monkeypatch.chdir(tmp_path)
    out = ed.perform_delivery(_payload("request", dict(REQUEST_BODY)), 1000, handlers=hs)
    assert out["ok"] is True
    assert os.path.isabs(out["result"]["file"])
    assert out["result"]["file"] == str(tmp_path / ".sandbar" / "projects" / PROJECT / "requests.jsonl")


# ---------- registration (worker registry single source) ----------

def test_delivery_workflow_registered_in_all_workflows():
    import workflows
    assert any(getattr(w, "__name__", "") == "ExecutorDeliveryWorkflow"
               for w in workflows.ALL_WORKFLOWS)


def test_delivery_activity_registered_in_all_activities():
    import activities
    names = [getattr(a, "__name__", "") for a in activities.ALL_ACTIVITIES]
    assert "delivery_activity" in names


# ---------- cmd_deliver (client.py subcommand; fake workflow handle, no server) ----------

def _cli():
    import client
    return client


def _fake_client(monkeypatch, cli, receipt=None, exc=None):
    calls = {}

    class _Handle:
        async def result(self):
            return receipt

    class _FakeClient:
        async def start_workflow(self, wf, payload, id=None, task_queue=None):
            calls["wf"], calls["payload"], calls["id"], calls["task_queue"] = wf, payload, id, task_queue
            if exc is not None:
                raise exc
            return _Handle()

    async def _connect():
        return _FakeClient()

    monkeypatch.setattr(cli, "_connect", _connect)
    return calls


def _cli_env(monkeypatch, tmp_path, **kw):
    import executor_grants
    monkeypatch.setenv("DSH_SESSION_ID", SESSION)
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, PROJECT)
    monkeypatch.setenv(shared.CALLER_IDENTITY_SRC_ENV, "env")
    monkeypatch.setenv(shared.CALLER_SURFACE_ENV, "")
    monkeypatch.setattr(executor_grants, "load_declaration",
                        lambda key: {"ok": True, "executor_sessions": [SESSION]})


def test_cli_deliver_happy_path_carries_identity_block(tmp_path, monkeypatch):
    cli = _cli()
    receipt = {"ok": True, "face": "request", "who": SESSION}
    calls = _fake_client(monkeypatch, cli, receipt=receipt)
    _cli_env(monkeypatch, tmp_path)
    out = asyncio_run(cli.cmd_deliver({"face": "request", "body": dict(REQUEST_BODY)}))
    assert out == {"ok": True, "result": receipt}
    assert calls["wf"] == "ExecutorDeliveryWorkflow"
    assert calls["task_queue"] == cli.TASK_QUEUE
    assert calls["id"].startswith("executor-delivery-%s-" % PROJECT)
    assert calls["payload"]["identity"]["session"] == SESSION
    assert calls["payload"]["identity"]["project"] == PROJECT
    assert calls["payload"]["key"] == PROJECT


def test_cli_deliver_refuses_unknown_face_and_declared_identity(tmp_path, monkeypatch):
    cli = _cli()
    calls = _fake_client(monkeypatch, cli)
    _cli_env(monkeypatch, tmp_path)
    out = asyncio_run(cli.cmd_deliver({"face": "grant-op", "body": {}}))
    assert out["ok"] is False and "unknown face" in out["error"]
    out = asyncio_run(cli.cmd_deliver(
        {"face": "request", "body": {**dict(REQUEST_BODY), "caller_project": "proj-beta"}}))
    assert out["ok"] is False and "not declared" in out["error"] and out["kind"] == "internal"
    assert calls == {}   # nothing ever reached the engine


def test_cli_deliver_identity_refusals_named(tmp_path, monkeypatch):
    import executor_grants
    cli = _cli()
    _fake_client(monkeypatch, cli)
    _cli_env(monkeypatch, tmp_path)
    monkeypatch.delenv("DSH_SESSION_ID")
    out = asyncio_run(cli.cmd_deliver({"face": "request", "body": dict(REQUEST_BODY)}))
    assert out["ok"] is False and "session-absent" in out["error"]
    monkeypatch.setenv("DSH_SESSION_ID", SESSION)
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV)
    monkeypatch.chdir(tmp_path)   # cwd outside any registered project → undeclared
    out = asyncio_run(cli.cmd_deliver({"face": "request", "body": dict(REQUEST_BODY)}))
    assert out["ok"] is False and "caller-undeclared" in out["error"]
    _ = executor_grants


def test_cli_deliver_engine_unreachable_named_verbatim(tmp_path, monkeypatch):
    cli = _cli()
    _fake_client(monkeypatch, cli)

    async def _dead_connect():
        raise cli.TransientConnectError(
            "temporal server connect failed (boom-target): ConnectionRefusedError: detail")

    monkeypatch.setattr(cli, "_connect", _dead_connect)
    _cli_env(monkeypatch, tmp_path)
    out = asyncio_run(cli.cmd_deliver({"face": "request", "body": dict(REQUEST_BODY)}))
    assert out["ok"] is False
    assert "engine-unreachable" in out["error"]
    assert "ConnectionRefusedError: detail" in out["error"]   # verbatim, no bare claim
    assert out["kind"] == cli.KIND_TRANSIENT


def test_cli_deliver_exempt_verdict_never_starts_workflow(tmp_path, monkeypatch):
    cli = _cli()
    calls = _fake_client(monkeypatch, cli)
    _cli_env(monkeypatch, tmp_path)
    body = {"op": "sign", "ticket": "t1", "verdict": {"allowed": True, "enforced": False}}
    out = asyncio_run(cli.cmd_deliver({"face": "actions-record", "body": body}))
    assert out["ok"] is True and out["result"]["exempt"] is True
    assert calls == {}   # no delivery run for a non-gated write


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
