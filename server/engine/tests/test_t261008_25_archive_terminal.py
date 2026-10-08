"""t261008-25 KI-223 Step 2: `ticket-archive-terminal`, the named archive exit for
terminal-but-not-completed tickets.

L1 pins (plan + review conditions 1-3):
- a FAILED ticket is reachable; the manifest keeps the failure class verbatim
  (`terminal_status`, `legacy:false`, `archived_by`) and never a success shape;
- empty / non-string reason and missing who are refused structurally with ZERO side
  effects (no data dir created);
- status guard: RUNNING / CONTINUED_AS_NEW (KI-025, and the KI-218 family closure — a
  queued/live ticket cannot reach this exit because the terminal guard refuses it at
  describe) / COMPLETED (pointed back to the normal path) each refuse distinctly;
- the archive stays queryable: prune's dry-run counts it (manifest state=ok), and the
  on-disk manifest SURVIVES an actual prune execution (the injected deleter deletes
  only the workflow, never the data dir) — the durable audit record (review
  condition 2);
- idempotent: a second call skips without overwriting a real archive.

Offline stubs only: FakeHandle/FakeClient (t260922-10 same pattern), monkeypatched
`_connect` and `ticket_data_dir`; no network, no real Temporal.
"""
import asyncio
import json

import client
import shared


class FakeSearchAttrs:
    def __init__(self, project=""):
        self._p = project

    def get(self, key):
        return self._p


class FakeDesc:
    def __init__(self, status, project=""):
        self.status = type("ExecStatus", (), {"name": status})()
        self.typed_search_attributes = FakeSearchAttrs(project)
        self.search_attributes = {client.PROJECT_SA_NAME: project}


class FakeHandle:
    def __init__(self, status, project="sandbar"):
        self.status_name = status
        self.project = project
        self.calls = []

    async def describe(self):
        self.calls.append("describe")
        return FakeDesc(self.status_name, self.project)


class FakeClient:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, tid):
        return self.handle


def _run(coro):
    return asyncio.run(coro)


def _install(monkeypatch, tmp_path, status, project="sandbar", tid="t260901-01"):
    h = FakeHandle(status, project)
    monkeypatch.setattr(client, "_connect",
                        lambda: asyncio.sleep(0, result=FakeClient(h)))
    # sandbox the data face: any project key maps under the test tmp dir
    root = tmp_path / "data" / "tickets"
    monkeypatch.setattr(
        client, "ticket_data_dir",
        lambda project_key, ticket_id: root / (project_key or "_no_project") / ticket_id)
    # undeclared identity passes named (record policy) — the gate matrix itself is
    # covered by the t260922-10 suite; here we exercise the exit's own guards
    monkeypatch.setenv("SANDBAR_UNDECLARED_POLICY", "record")
    return h, root


REASON = "runner OOM on stage implement; worktree kept, failure not retriable"


def test_failed_ticket_reachable_and_failure_class_kept(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "FAILED")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert r["ok"], r
    res = r["result"]
    assert res["archived"] is True and res["terminal_status"] == "FAILED"
    assert res["who"] == "ops" and res["reason"] == REASON
    manifest = json.loads((tmp_path / "data" / "tickets" / "sandbar" / "t260901-01"
                           / "archive.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "v1"
    assert manifest["legacy"] is False
    assert manifest["terminal_status"] == "FAILED"   # failure class verbatim
    assert manifest["archived_by"] == "ops"
    assert manifest["reason"] == REASON


def test_empty_reason_refused_zero_side_effects(monkeypatch, tmp_path):
    h, root = _install(monkeypatch, tmp_path, "FAILED")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": "   "}))
    assert not r["ok"] and "reason" in r["error"].lower()
    assert not root.exists()          # zero side effects: no data dir was created
    assert h.calls == []              # refused before describe/gate/write (arg stage)


def test_non_string_reason_refused_structurally(monkeypatch, tmp_path):
    h, root = _install(monkeypatch, tmp_path, "FAILED")
    for bad in (["x"], 123, {"r": 1}):
        r = _run(client.cmd_ticket_archive_terminal(
            {"ticket_id": "t260901-01", "who": "ops", "reason": bad}))
        assert not r["ok"], bad
        assert not root.exists(), bad   # never str()-coerced into a pass
    assert h.calls == []                # refused at the arg stage, describe never ran


def test_missing_who_refused(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "FAILED")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "reason": REASON}))
    assert not r["ok"] and "who" in r["error"].lower()


def test_live_ticket_refused_ki218_family(monkeypatch, tmp_path):
    # A queued/live ticket cannot reach the exit: the terminal guard refuses it at
    # describe (KI-218 family closure, review condition 3).
    h, root = _install(monkeypatch, tmp_path, "RUNNING")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert not r["ok"] and "terminal" in r["error"].lower()
    assert not root.exists()


def test_continued_as_new_refused_ki025(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "CONTINUED_AS_NEW")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert not r["ok"] and "CONTINUED_AS_NEW" in r["error"]


def test_completed_pointed_back_to_the_normal_path(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "COMPLETED")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert not r["ok"] and "ticket-archive-legacy" in r["error"]


def test_archived_ticket_stays_queryable_by_prune_dry_run(monkeypatch, tmp_path):
    # L3 pre-prune phase: board face still lists the row; the collection face agrees —
    # prune's dry-run counts the archived FAILED ticket into its would-delete list.
    _install(monkeypatch, tmp_path, "FAILED")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert r["ok"]
    deleted, calls = [], []

    async def fake_deleter(wf_id):
        calls.append(wf_id)

    p = _run(client.cmd_ticket_prune(
        {"execute": False},
        entries=[{"id": "t260901-01", "sa_project": "sandbar", "close_ts": 1}],
        deleter=fake_deleter))
    assert p["ok"]
    assert p["result"]["deleted"] == ["t260901-01"]
    assert calls == []              # dry-run: the deleter is never invoked


def test_manifest_survives_actual_prune_execution(monkeypatch, tmp_path):
    # Review condition 2: the durable audit record is the on-disk manifest — prune
    # --execute deletes the workflow (injected deleter), never the data dir.
    _install(monkeypatch, tmp_path, "FAILED")
    assert _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))["ok"]
    mpath = (tmp_path / "data" / "tickets" / "sandbar" / "t260901-01" / "archive.json")

    async def fake_deleter(wf_id):
        # the real deleter goes through DeleteWorkflowExecution: the Temporal workflow
        # disappears; the ticket data dir is never touched by it
        pass

    p = _run(client.cmd_ticket_prune(
        {"execute": True},
        entries=[{"id": "t260901-01", "sa_project": "sandbar", "close_ts": 1}],
        deleter=fake_deleter))
    assert p["ok"] and p["result"]["deleted"] == ["t260901-01"]
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    assert manifest["terminal_status"] == "FAILED"
    assert manifest["reason"] == REASON and manifest["archived_by"] == "ops"


def test_second_call_idempotent_no_overwrite(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "FAILED")
    first = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert first["ok"]
    mpath = (tmp_path / "data" / "tickets" / "sandbar" / "t260901-01" / "archive.json")
    before = mpath.read_text(encoding="utf-8")
    second = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops",
         "reason": "a different, later reason must NOT overwrite"}))
    assert second["ok"] and second["result"]["skipped"] is True
    assert mpath.read_text(encoding="utf-8") == before


def test_malformed_manifest_fail_closed(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, "FAILED")
    mpath = (tmp_path / "data" / "tickets" / "sandbar" / "t260901-01")
    mpath.mkdir(parents=True)
    (mpath / "archive.json").write_text("{not json", encoding="utf-8")
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": "t260901-01", "who": "ops", "reason": REASON}))
    assert not r["ok"] and "manifest" in r["error"].lower()
    # the malformed manifest is never overwritten
    assert (mpath / "archive.json").read_text(encoding="utf-8") == "{not json"
