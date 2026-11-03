# -*- coding: utf-8 -*-
"""t261004-44 / KI-197 -- the bounded wait and named refusal of deliver (unit face).

Contract: with a stale worker (does not know ExecutorDeliveryWorkflow), deliver must
exit non-zero with a named refusal (class name + registered set + the failed check
name) and never hang; an absent fingerprint = explicit degradation to the bounded
wait; a bounded-wait timeout = cancel the remote zombie + named refusal + audit row
(fail-open, review C2). All io injected (env / stub client / temp dirs); zero real
Temporal, zero real ~/.sandbar.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import traceback
import unittest

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pr_flow  # noqa: E402  t261103-04: the PR-flow precondition face (carrier below)
import shared  # noqa: E402  t261103-04: the project-declaration loader tolerance row
import worker_registry  # noqa: E402


class FingerprintFaceTests(unittest.TestCase):
    """worker_registry: write / read / check faces (with malformed-input rows -- mandatory for anything consuming an external file)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sub", "worker-registry.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_then_read_roundtrip(self) -> None:
        doc = worker_registry.write_fingerprint(
            self.path, ["A", "ExecutorDeliveryWorkflow"], pid=4242, now_ms=1_000,
            code_fingerprint="sha-ki227", activity_names=["act_a"])
        # t261008-29 (KI-227): fingerprint bumped to v2 — the doc now also carries
        # the code identity and the activity registry.
        self.assertEqual(doc["version"], worker_registry.FINGERPRINT_VERSION)
        self.assertEqual(doc["code_fingerprint"], "sha-ki227")
        self.assertEqual(doc["activities"], ["act_a"])
        self.assertTrue(doc["activity_fingerprint"])
        self.assertEqual(doc["registered"], ["A", "ExecutorDeliveryWorkflow"])
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(err)
        assert got is not None
        self.assertEqual(got["pid"], 4242)

    def test_read_absent_is_named(self) -> None:
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertEqual(err, "absent")

    def test_read_malformed_is_named_not_crash(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json at all")
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertTrue(str(err).startswith("malformed"))

    def test_read_wrong_shape_is_malformed(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 99, "registered": "nope"}, f)
        got, err = worker_registry.read_fingerprint(self.path)
        self.assertIsNone(got)
        self.assertTrue(str(err).startswith("malformed"))

    def test_check_class_absent_refuses_with_registered_set(self) -> None:
        doc = worker_registry.write_fingerprint(
            self.path, ["ContentPipelineWorkflow"], pid=1, now_ms=2)
        got, _ = worker_registry.read_fingerprint(self.path)
        chk = worker_registry.delivery_registration_check(got)
        self.assertFalse(chk["ok"])
        self.assertEqual(chk["workflow_class"], "ExecutorDeliveryWorkflow")
        self.assertEqual(chk["registered"], ["ContentPipelineWorkflow"])

    def test_check_class_present_passes_even_if_doc_is_stale(self) -> None:
        """Review C3: a stale fingerprint (old pid / old code) does NOT change the verdict --
        it is not a health certificate; listed = proceed, the staleness risk is carried
        by the bounded wait."""
        got = {"version": 1, "pid": 6, "started_at_ms": 1,
               "code_fingerprint": "old", "registered": ["ExecutorDeliveryWorkflow"]}
        chk = worker_registry.delivery_registration_check(got)
        self.assertTrue(chk["ok"])

    def test_check_absent_doc_degrades_named(self) -> None:
        chk = worker_registry.delivery_registration_check(None)
        self.assertTrue(chk["ok"])
        self.assertIn("fingerprint absent", chk["degraded"])


class DeliverTimeoutTests(unittest.TestCase):
    def test_default_and_floor(self) -> None:
        import client
        self.assertEqual(client.DELIVER_TIMEOUT_DEFAULT_S, 60.0)
        self.assertEqual(client.deliver_timeout_sec({}), 60.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "0.5"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "abc"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "-3"}), 5.0)
        self.assertEqual(client.deliver_timeout_sec({"SANDBAR_DELIVER_TIMEOUT_S": "7"}), 7.0)


class _NeverWorkflow:
    """Stub workflow handle: result() never returns (replays "the worker does not know the class => infinite retry")."""

    async def result(self) -> "NoReturn":  # type: ignore[name-defined]
        await asyncio.sleep(3600)

    async def cancel(self) -> None:
        self.cancelled = True  # type: ignore[attr-defined]
        return None


class _StubClient:
    """Stub Temporal client: raises or hangs per script."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.handle = _NeverWorkflow()
        self.started = 0

    async def start_workflow(self, wf_class, payload, id=None, task_queue=None):  # noqa: A002
        self.started += 1
        if self.mode == "already-started":
            raise RuntimeError("Workflow execution already started: " + str(id))
        if self.mode == "never":
            await asyncio.sleep(3600)
        raise RuntimeError("unexpected mode %s" % self.mode)

    def get_workflow_handle(self, wf_id: str) -> "_NeverWorkflow":
        return self.handle


class DeliverBoundedTests(unittest.TestCase):
    """_deliver_bounded: must raise TimeoutError, never truly hang for 3600s."""

    def test_bounded_wait_times_out(self) -> None:
        import client
        stub = _StubClient("never")
        async def run() -> None:
            t0 = time.monotonic()
            with self.assertRaises(asyncio.TimeoutError):
                await client._deliver_bounded(stub, "wf-1", {}, 0.15)
            self.assertLess(time.monotonic() - t0, 5.0)
        asyncio.run(run())

    def test_success_returns_receipt(self) -> None:
        import client
        class _Ok(_StubClient):
            async def start_workflow(self, wf_class, payload, id=None, task_queue=None):  # noqa: A002
                class _H:
                    async def result(self):
                        return {"ok": True}
                return _H()
        receipt = asyncio.run(client._deliver_bounded(_Ok("ok"), "wf-2", {}, 5))
        self.assertEqual(receipt, {"ok": True})

    def test_cancel_failure_is_named_not_fatal(self) -> None:
        import client
        class _Bad(_StubClient):
            def get_workflow_handle(self, wf_id):
                class _H:
                    async def cancel(self):
                        raise RuntimeError("handle gone")
                return _H()
        note = asyncio.run(client._cancel_deliver_workflow(_Bad("x"), "wf-3"))
        self.assertIsNotNone(note)
        self.assertIn("cancel failed", note)


class DeliverRegistrationRefusalTests(unittest.TestCase):
    """The pre-flight fingerprint check of cmd_deliver (env points at a temp fingerprint file; no state leaks between tests)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env_key = "SANDBAR_WORKER_REGISTRY_FINGERPRINT"
        self.saved = os.environ.get(self.env_key)
        self.path = os.path.join(self.tmp.name, "wr.json")
        os.environ[self.env_key] = self.path

    def tearDown(self) -> None:
        if self.saved is None:
            os.environ.pop(self.env_key, None)
        else:
            os.environ[self.env_key] = self.saved
        self.tmp.cleanup()

    def test_refusal_text_names_class_and_registered_set(self) -> None:
        import client
        worker_registry.write_fingerprint(
            self.path, ["ContentPipelineWorkflow"], pid=9, now_ms=5)
        msg = client._deliver_registration_refusal()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("ExecutorDeliveryWorkflow", msg)
        self.assertIn("ContentPipelineWorkflow", msg)
        self.assertIn("worker-registration-fingerprint", msg)
        self.assertIn("pid 9", msg)

    def test_class_present_passes(self) -> None:
        import client
        worker_registry.write_fingerprint(
            self.path, ["ExecutorDeliveryWorkflow"], pid=9, now_ms=5)
        self.assertIsNone(client._deliver_registration_refusal())

    def test_fingerprint_absent_degrades_to_bounded_wait(self) -> None:
        import client
        self.assertIsNone(client._deliver_registration_refusal())


class RecordDeliverRefusalTests(unittest.TestCase):
    """Audit row fail-open (review C2): a raising append_audit never withholds the refusal; the failure is named."""

    def test_append_failure_is_named(self) -> None:
        import client
        import executor_grants
        orig = executor_grants.append_audit
        def boom(key, row):
            raise RuntimeError("disk full")
        executor_grants.append_audit = boom
        try:
            note = client._record_deliver_refusal("proj", "sess-1", "request",
                                                  "delivery-deadline", "why")
        finally:
            executor_grants.append_audit = orig
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("audit row not filed", note)
        self.assertIn("RuntimeError", note)

    def test_row_shape_and_landing(self) -> None:
        import client
        import executor_grants
        with tempfile.TemporaryDirectory() as td:
            saved = dict(os.environ)
            os.environ["SANDBAR_PROJECTS_DIR"] = td
            try:
                importlib.reload(executor_grants)
                note = client._record_deliver_refusal("proj", "sess-1", "request",
                                                      "delivery-deadline", "why")
                self.assertIsNone(note)
                path = os.path.join(td, "proj", executor_grants.AUDIT_FILE)
                with open(path, "r", encoding="utf-8") as f:
                    row = json.loads(f.readline())
                self.assertEqual(row["kind"], "deliver_refused")
                self.assertEqual(row["who"], "sess-1")
                self.assertEqual(row["face"], "request")
                self.assertEqual(row["workflow_class"], "ExecutorDeliveryWorkflow")
            finally:
                os.environ.clear()
                os.environ.update(saved)
                importlib.reload(executor_grants)


if __name__ == "__main__":
    unittest.main()


class DeliverCmdRefusalTests(unittest.TestCase):
    """cmd_deliver-level L1 (stub client, zero Temporal): class absent = named refusal
    rc!=0; a hanging already-started receipt read = bounded refusal (review C1); the
    audit row is filed (C2)."""

    def _run_deliver(self, mode: str) -> "tuple[dict, list]":
        import client as client_mod
        import executor_requests
        saved_env = os.environ.get(client_mod.DELIVER_TIMEOUT_ENV)
        os.environ[client_mod.DELIVER_TIMEOUT_ENV] = "0.2"
        audit_calls: list = []
        orig_caller = executor_requests.resolve_caller
        orig_reg = getattr(client_mod, "load_projects_registry", None)
        orig_conn = client_mod._connect
        orig_audit = client_mod._record_deliver_refusal

        def fake_caller(*a, **k):
            return {"ok": True, "project": "proj", "session": "sess-1",
                    "channel": "cwd", "channel_src": "cwd"}

        client_mod.executor_requests.resolve_caller = fake_caller
        client_mod._record_deliver_refusal = (
            lambda project, who, face, check, reason: audit_calls.append(
                (project, who, face, check)) and None)
        stub = _StubClient(mode)
        client_mod._connect = lambda: _async_return(stub)
        try:
            out = asyncio.run(client_mod.cmd_deliver({"face": "request", "body": {}}))
        finally:
            executor_requests.resolve_caller = orig_caller
            client_mod._connect = orig_conn
            client_mod._record_deliver_refusal = orig_audit
            if orig_reg is not None:
                client_mod.load_projects_registry = orig_reg
            if saved_env is None:
                os.environ.pop(client_mod.DELIVER_TIMEOUT_ENV, None)
            else:
                os.environ[client_mod.DELIVER_TIMEOUT_ENV] = saved_env
        return out, audit_calls

    def test_unknown_class_refused_named_no_start(self) -> None:
        import client as client_mod
        saved = os.environ.get("SANDBAR_WORKER_REGISTRY_FINGERPRINT")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "wr.json")
            worker_registry.write_fingerprint(path, ["ContentPipelineWorkflow"],
                                              pid=3, now_ms=1)
            os.environ["SANDBAR_WORKER_REGISTRY_FINGERPRINT"] = path
            try:
                out, audit_calls = self._run_deliver("never")
            finally:
                if saved is None:
                    os.environ.pop("SANDBAR_WORKER_REGISTRY_FINGERPRINT", None)
                else:
                    os.environ["SANDBAR_WORKER_REGISTRY_FINGERPRINT"] = saved
        self.assertFalse(out["ok"])
        self.assertEqual(out["kind"], "deliver_refused")
        self.assertIn("ExecutorDeliveryWorkflow", out["error"])
        self.assertIn("ContentPipelineWorkflow", out["error"])
        self.assertIn("worker-registration-fingerprint", out["error"])
        self.assertEqual(len(audit_calls), 1)

    def test_duplicate_started_never_resolves_is_bounded_refusal(self) -> None:
        """Review C1: a hanging duplicate-started receipt read -> a bounded named refusal, not a second bare result()."""
        import time as _t
        t0 = _t.monotonic()
        out, audit_calls = self._run_deliver("already-started")
        self.assertLess(_t.monotonic() - t0, 10.0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["kind"], "deliver_refused")
        self.assertIn("delivery-deadline-first-receipt", out["error"])
        self.assertIn("ExecutorDeliveryWorkflow", out["error"])
        self.assertEqual(audit_calls, [("proj", "sess-1", "request",
                                        "delivery-deadline-first-receipt")])


def _async_return(v):
    async def _g():
        return v
    return _g()


# ---------------------------------------------------------------------------
# t261103-04 CARRIER -- PR-flow step (a): the per-project switch (default OFF)
# and the GitHub credential kept outside every repository worktree.
#
# Why this file: the anchors manifest (integration/test_anchors.json) is outside
# this ticket's write set (server/engine/), so a NEW server/engine/tests/test_*.py
# would be an L16 "anchor missing" error. This file is the delivery
# named-refusal carrier (t261004-44, already extended once by t261008-29), which
# is the same face these rows judge: a delivery precondition that refuses BY NAME
# instead of failing silently.
#
# Everything is injected (projects root, sandbar home, probe, credential reader):
# zero real ~/.sandbar, zero network, no Temporal, no docker, no port 3099.
# ---------------------------------------------------------------------------

TOKEN = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"      # 44 chars, token-shaped
TOKEN_SHAPE_OTHER = "ghp_" + "Z" * 36                     # never registered with us


@pytest.fixture(autouse=True)
def _fresh_secret_registry():
    """Each row starts and ends with an empty redaction registry (the registry is a
    process global on purpose -- a caller cannot forget to register a secret)."""
    pr_flow.forget_secrets()
    yield
    pr_flow.forget_secrets()


def _write_declaration(root, key="proj", body=""):
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    p = d / "project.yaml"
    p.write_text("schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n"
                 "      - /repo/%s\n%s" % (key, key, key, body), "utf-8")
    return p


def _write_credential(home, value=TOKEN, mode=0o600):
    path = pr_flow.credential_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, "utf-8")
    os.chmod(path, mode)
    return path


def _stop_code(fn, *a, **kw):
    """Run fn; return the named stop's code (AssertionError when it does not refuse)."""
    try:
        fn(*a, **kw)
    except pr_flow.PrFlowStop as e:
        return e.code
    raise AssertionError("expected a named stop, got none")


# ---- 1. the switch: attribute truth table --------------------------------

SWITCH_ROWS = [
    # (label, declaration body, enabled, reason)
    ("absent-section", "", False, "absent"),
    ("off", "github_pr:\n  enabled: false\n", False, "off"),
    ("off-without-repositories", "github_pr:\n  enabled: no\n", False, "off"),
    ("on", "github_pr:\n  enabled: true\n  repositories:\n    - owner/name\n",
     True, "on"),
    ("on-synonyms", "github_pr:\n  enabled: YES\n  repositories:\n    - o/r\n"
                    "    - a-b/c.d\n", True, "on"),
]


@pytest.mark.parametrize("label,body,enabled,reason", SWITCH_ROWS,
                         ids=[r[0] for r in SWITCH_ROWS])
def test_pr_flow_switch_truth_table(tmp_path, label, body, enabled, reason):
    root = tmp_path / "projects"
    _write_declaration(root, body=body)
    d = pr_flow.read_switch("proj", root)
    assert (d.enabled, d.reason) == (enabled, reason)
    assert d.face() == {"enabled": enabled, "reason": reason,
                        "repositories": list(d.repositories),
                        "declaration": d.declaration}
    if enabled:
        assert d.repositories                       # least privilege needs the set
    else:
        assert d.repositories == ()


@pytest.mark.parametrize("label,body,code", [
    ("enabled-value-junk", "github_pr:\n  enabled: maybe\n  repositories:\n"
                           "    - o/r\n", pr_flow.STOP_DECLARATION_MALFORMED),
    ("enabled-missing", "github_pr:\n  repositories:\n    - o/r\n",
     pr_flow.STOP_DECLARATION_MALFORMED),
    ("unknown-key", "github_pr:\n  enable: true\n", pr_flow.STOP_DECLARATION_MALFORMED),
    ("duplicate-block", "github_pr:\n  enabled: true\ngithub_pr:\n  enabled: false\n",
     pr_flow.STOP_DECLARATION_MALFORMED),
    ("inline-repositories", "github_pr:\n  enabled: true\n  repositories: [o/r]\n",
     pr_flow.STOP_DECLARATION_MALFORMED),
    ("repository-not-owner-name", "github_pr:\n  enabled: true\n  repositories:\n"
                                  "    - justaname\n",
     pr_flow.STOP_DECLARATION_MALFORMED),
    ("on-without-repositories", "github_pr:\n  enabled: true\n",
     pr_flow.STOP_SWITCH_REPOSITORIES_MISSING),
])
def test_pr_flow_switch_malformed_is_a_named_stop(tmp_path, label, body, code):
    """An unusable switch is NEVER read as "off": a typo must not pick the delivery
    mode. Each row proves its own named stop."""
    root = tmp_path / "projects"
    _write_declaration(root, body=body)
    assert _stop_code(pr_flow.read_switch, "proj", root) == code


def test_pr_flow_switch_refuses_a_non_key(tmp_path):
    """The project key is a path segment: a traversal is refused before the join."""
    assert _stop_code(pr_flow.read_switch, "../escape", tmp_path) == \
        pr_flow.STOP_DECLARATION_MALFORMED


# ---- 2. default OFF is the historical path (negative control) ------------


def test_pr_flow_default_off_matches_the_historical_path(tmp_path):
    """A project that does not set the attribute is indistinguishable from today:
    the declaration is the only file read, no credential is resolved, no probe
    runs, no file appears, and the decision face carries no credential field."""
    root = tmp_path / "projects"
    home = tmp_path / "home"
    _write_declaration(root)                       # no github_pr: block
    cred = _write_credential(home)                 # a perfect credential, untouched

    calls = {"reader": 0, "probe": 0}

    def bomb_reader(**kwargs):
        calls["reader"] += 1
        raise AssertionError("the credential was read while the switch is off")

    def bomb_probe(token):
        calls["probe"] += 1
        raise AssertionError("the validity probe ran while the switch is off")

    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    cred_before = cred.read_bytes()

    decision = pr_flow.delivery_decision(
        "proj", projects_root_dir=root, home=home, probe=bomb_probe,
        credential_reader=bomb_reader)

    assert decision.enabled is False and decision.reason == "absent"
    assert decision.face() == {"enabled": False, "reason": "absent",
                               "repositories": [], "declaration": decision.declaration,
                               "credential_fingerprint": ""}
    assert calls == {"reader": 0, "probe": 0}
    assert cred.read_bytes() == cred_before
    assert sorted(p.relative_to(tmp_path).as_posix()
                  for p in tmp_path.rglob("*")) == before


def test_pr_flow_off_explicit_is_the_historical_path_too(tmp_path):
    root = tmp_path / "projects"
    _write_declaration(root, body="github_pr:\n  enabled: false\n")
    decision = pr_flow.delivery_decision(
        "proj", projects_root_dir=root, home=tmp_path / "nowhere",
        credential_reader=lambda **kw: (_ for _ in ()).throw(
            AssertionError("credential read on an off switch")))
    assert decision.face()["enabled"] is False and decision.reason == "off"
    assert not (tmp_path / "nowhere").exists()     # nothing probed into existence


def test_pr_flow_off_path_binds_no_network_client():
    """The module namespace carries no HTTP client: the one network seam
    (probe_github_token) imports its client inside the function, and the OFF path
    never reaches it."""
    for name in ("urllib", "request", "urlopen", "http", "socket", "requests"):
        assert name not in vars(pr_flow)


def test_pr_flow_switch_read_creates_nothing(tmp_path):
    root = tmp_path / "projects"
    d = pr_flow.read_switch("proj", root)
    assert (d.enabled, d.reason) == (False, "absent")
    assert not root.exists()                       # a read creates no state


def test_pr_flow_declaration_loader_tolerates_the_section(tmp_path):
    """The engine's own registry loader must not quarantine a declaration that
    carries the attribute, and must parse a declaration without it unchanged."""
    before = "schema: v1\nproject:\n  - key: proj\n    name: proj\n    dirs:\n      - /repo\n"
    plain = shared.parse_project_file(before, "project.yaml")
    with_section = before + "github_pr:\n  enabled: true\n  repositories:\n    - o/r\n"
    parsed = shared.parse_project_file(with_section, "project.yaml")
    assert parsed == plain == {"key": "proj", "name": "proj", "dirs": ["/repo"]}


# ---- 3. credential resolution truth table --------------------------------


def test_pr_flow_credential_resolution_truth_table(tmp_path):
    home = tmp_path / "home"
    path = _write_credential(home)

    good = pr_flow.resolve_credential(home=home)
    assert good.reveal() == TOKEN and len(good.fingerprint) == 12
    assert TOKEN not in str(good) and TOKEN not in repr(good)
    # the same row read twice yields the same fingerprint (stable audit label)
    assert pr_flow.resolve_credential(home=home).fingerprint == good.fingerprint

    os.unlink(path)
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_MISSING

    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()                                   # a directory is not a credential
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_MISSING
    path.rmdir()

    for label, value in (("empty", ""), ("blank", "  \n\t\n")):
        _write_credential(home, value=value)
        assert _stop_code(pr_flow.resolve_credential, home=home) == \
            pr_flow.STOP_CREDENTIAL_EMPTY, label

    _write_credential(home)
    path.write_bytes(b"\xff\xfe\x00not-utf8")      # unreadable content, 0600
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_UNREADABLE

    if os.geteuid() != 0:                          # root reads anything
        _write_credential(home)
        os.chmod(path, 0o000)
        assert _stop_code(pr_flow.resolve_credential, home=home) == \
            pr_flow.STOP_CREDENTIAL_UNREADABLE
        os.chmod(path, 0o600)                      # restore, then start a fresh file
        os.unlink(path)

    _write_credential(home, value="short")
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_SHORT

    _write_credential(home, value=TOKEN + "\n" + TOKEN)
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_MALFORMED

    _write_credential(home, value="g" * (pr_flow.MAX_CREDENTIAL_CHARS + 1))
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_MALFORMED

    _write_credential(home, value=TOKEN, mode=0o644)
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_PERMISSIONS

    _write_credential(home, value=TOKEN, mode=0o604)
    assert _stop_code(pr_flow.resolve_credential, home=home) == \
        pr_flow.STOP_CREDENTIAL_PERMISSIONS

    _write_credential(home, value=TOKEN + "\n", mode=0o400)   # trailing newline is fine
    assert pr_flow.resolve_credential(home=home).reveal() == TOKEN


def test_pr_flow_credential_must_live_outside_every_worktree(tmp_path):
    """Placement is judged BEFORE any read: a credential inside a worktree (an
    ancestor carries .git) or under a declared project directory is refused by
    name, so the value is never even read."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    at_worktree_root = repo / "github" / "credential"
    _write_credential(repo, value=TOKEN, mode=0o644)   # bad mode AND bad content
    assert _stop_code(pr_flow.resolve_credential, home=repo) == \
        pr_flow.STOP_CREDENTIAL_IN_WORKTREE

    plain_home = tmp_path / "home"
    os.makedirs(plain_home / "github")
    os.rename(str(at_worktree_root), str(plain_home / "github" / "credential"))
    # outside the git-ancestor test, but still under a declared project directory
    assert _stop_code(pr_flow.resolve_credential, home=plain_home,
                      project_dirs=[str(tmp_path)]) == \
        pr_flow.STOP_CREDENTIAL_IN_WORKTREE
    os.chmod(str(plain_home / "github" / "credential"), 0o600)
    assert pr_flow.resolve_credential(home=plain_home).reveal() == TOKEN


def test_pr_flow_probe_rows(tmp_path):
    """The single validity probe is injectable: accepted / rejected / could not
    answer; the rejected stop carries the platform's reason, never the secret."""
    home = tmp_path / "home"
    _write_credential(home)

    assert pr_flow.resolve_credential(home=home, probe=lambda t: "").reveal() == TOKEN

    seen = []

    def rejecting(token):
        seen.append(token)
        return "401 Bad credentials for token %s" % token

    stopped = None
    try:
        pr_flow.resolve_credential(home=home, probe=rejecting)
    except pr_flow.PrFlowStop as e:
        stopped = e
    assert stopped is not None and stopped.code == pr_flow.STOP_CREDENTIAL_REJECTED
    assert seen == [TOKEN]
    assert TOKEN not in stopped.message() and TOKEN not in json.dumps(stopped.face())
    assert "401 Bad credentials" in stopped.message()          # the reason survives

    def unreachable(token):
        raise ConnectionError("no route to host (token=%s)" % token)

    stopped = None
    try:
        pr_flow.resolve_credential(home=home, probe=unreachable)
    except pr_flow.PrFlowStop as e:
        stopped = e
    assert stopped is not None and stopped.code == pr_flow.STOP_PROBE_FAILED
    assert TOKEN not in str(stopped)


def test_pr_flow_four_required_stops_are_four_distinct_names(tmp_path):
    """The design names four stops; they must be four names, not one reworded."""
    assert len(set(pr_flow.REQUIRED_STOPS)) == 4
    home = tmp_path / "home"
    codes = set()
    codes.add(_stop_code(pr_flow.resolve_credential, home=home))          # missing
    _write_credential(home, value="")
    codes.add(_stop_code(pr_flow.resolve_credential, home=home))          # empty
    _write_credential(home)
    home_cred = pr_flow.credential_path(home)
    home_cred.write_bytes(b"\xff\xfe")
    codes.add(_stop_code(pr_flow.resolve_credential, home=home))          # unreadable
    _write_credential(home)
    codes.add(_stop_code(pr_flow.resolve_credential, home=home,
                         probe=lambda t: "rejected"))                     # rejected
    assert codes == set(pr_flow.REQUIRED_STOPS)


def test_pr_flow_on_switch_makes_the_credential_a_hard_precondition(tmp_path):
    root = tmp_path / "projects"
    home = tmp_path / "home"
    _write_declaration(root, body="github_pr:\n  enabled: true\n  repositories:\n"
                                   "    - owner/name\n")
    assert _stop_code(pr_flow.delivery_decision, "proj",
                      projects_root_dir=root, home=home) == \
        pr_flow.STOP_CREDENTIAL_MISSING
    _write_credential(home)
    decision = pr_flow.delivery_decision("proj", projects_root_dir=root, home=home)
    assert decision.enabled is True and decision.reason == "on"
    assert decision.repositories == ("owner/name",)
    assert len(decision.credential_fingerprint) == 12
    assert decision.face()["credential_fingerprint"] == decision.credential_fingerprint


# ---- 4. the redaction property ------------------------------------------


def test_pr_flow_secret_never_reaches_any_surface(tmp_path):
    """The property the design's upfront constraint demands: the value never
    reaches a ticket face, a handoff, a ledger row, a log line or an exception
    string -- including when the platform echoes the token back in its reason."""
    root = tmp_path / "projects"
    home = tmp_path / "home"
    _write_declaration(root, body="github_pr:\n  enabled: true\n  repositories:\n"
                                   "    - owner/name\n")
    _write_credential(home)

    # (i) a stop that carries a platform reason which echoes the token
    stopped = None
    try:
        pr_flow.delivery_decision(
            "proj", projects_root_dir=root, home=home,
            probe=lambda t: "bad token %s and lookalike %s" % (t, TOKEN_SHAPE_OTHER))
    except pr_flow.PrFlowStop as e:
        stopped = e
    assert stopped is not None and stopped.code == pr_flow.STOP_CREDENTIAL_REJECTED
    surfaces = [
        str(stopped), repr(stopped), stopped.message(),
        json.dumps(stopped.face(), ensure_ascii=False),
        "".join(traceback.format_exception(type(stopped), stopped,
                                           stopped.__traceback__)),
    ]

    # (ii) the success path: the decision face, the credential's own repr
    decision = pr_flow.delivery_decision("proj", projects_root_dir=root, home=home)
    credential = pr_flow.resolve_credential(home=home)
    surfaces += [json.dumps(decision.face(), ensure_ascii=False),
                 str(credential), repr(credential)]

    # (iii) a ledger row / handoff payload scrubbed before it is written
    row = {"kind": "pr_flow", "token": TOKEN,
           "note": "opened with %s" % TOKEN,
           "nested": {"%s_as_key" % TOKEN: [TOKEN]}}
    handoff = {"summary": "credential %s accepted" % TOKEN, "rows": [row]}
    surfaces.append(json.dumps(pr_flow.scrub(handoff), ensure_ascii=False))

    for surface in surfaces:
        assert TOKEN not in surface, surface
        assert TOKEN[:16] not in surface, surface        # no partial leak either
        assert TOKEN_SHAPE_OTHER not in surface, surface
    assert pr_flow.REDACTED in json.dumps(pr_flow.scrub(row))
    assert pr_flow.REDACTED in str(credential)

    # the secret is registered by construction: one explicit way to get it
    assert pr_flow.redact("wrapped %s wrapped" % TOKEN).count(pr_flow.REDACTED) == 1
    assert pr_flow.redact("wrapped %s wrapped" % TOKEN) == \
        "wrapped %s wrapped" % pr_flow.REDACTED


def test_pr_flow_stop_face_is_a_plain_redacted_payload(tmp_path):
    """Every stop is exportable into a receipt/ticket face as data: named code,
    the check that failed, the non-secret path -- and nothing else."""
    home = tmp_path / "home"
    stopped = None
    try:
        pr_flow.resolve_credential(home=home, probe=None)
    except pr_flow.PrFlowStop as e:
        stopped = e
    face = stopped.face()
    assert face["ok"] is False
    assert face["code"] == pr_flow.STOP_CREDENTIAL_MISSING
    assert face["path"] == str(pr_flow.credential_path(home))
    assert "which check failed" not in face["message"]
    assert face["message"].startswith(pr_flow.STOP_CREDENTIAL_MISSING)
    assert set(face) == {"ok", "code", "message", "detail", "path"}


def test_pr_flow_default_location_resolution_is_env_injectable(tmp_path, monkeypatch):
    """The production defaults resolve from $SANDBAR_PROJECTS_DIR / $SANDBAR_HOME, so
    the whole flow is reachable without ever touching the real ~/.sandbar; with no
    env at all the paths are the per-user home (asserted by string, never opened)."""
    monkeypatch.delenv(pr_flow.PROJECTS_DIR_ENV, raising=False)
    monkeypatch.delenv(pr_flow.HOME_ENV, raising=False)
    assert pr_flow.projects_root() == pr_flow.Path.home() / ".sandbar" / "projects"
    assert pr_flow.sandbar_home() == pr_flow.Path.home() / ".sandbar"
    assert pr_flow.credential_path() == pr_flow.Path.home() / ".sandbar" / "github" / "credential"
    assert ".." not in str(pr_flow.credential_path())      # outside every worktree by layout

    root = tmp_path / "projects"
    home = tmp_path / "home"
    _write_declaration(root, body="github_pr:\n  enabled: true\n  repositories:\n"
                                   "    - owner/name\n")
    _write_credential(home)
    monkeypatch.setenv(pr_flow.PROJECTS_DIR_ENV, str(root))
    monkeypatch.setenv(pr_flow.HOME_ENV, str(home))
    decision = pr_flow.delivery_decision("proj")
    assert decision.enabled is True and decision.repositories == ("owner/name",)
    assert TOKEN not in json.dumps(decision.face())


def test_pr_flow_named_stops_are_terminal_and_never_read_as_off():
    """One vocabulary, fourteen names, every one terminal: a stop is raised once (no
    retry loop) and is never reported as "off" (that would pick the historical
    delivery mode behind the operator's back).

    t261103-13 grew the table by two: the park's `beat_seconds` and `wake_entry`
    refusals (each naming its own key) belong to the same terminal vocabulary."""
    constants = {v for k, v in vars(pr_flow).items()
                 if k.startswith("STOP_") and isinstance(v, str)}
    assert constants == set(pr_flow.STOP_TABLE)
    assert len(constants) == 14
    for code in constants:
        assert pr_flow.is_named_stop(code) is True
    assert pr_flow.is_named_stop("") is False and pr_flow.is_named_stop("nope") is False
    assert set(pr_flow.REQUIRED_STOPS) <= constants
