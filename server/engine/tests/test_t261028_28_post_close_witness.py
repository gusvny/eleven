"""t261028-30 (evidence name: t261028_28): the post-close terminal witness.

Why it exists (measured 261028, not re-derived here): the request sweep already has a
lawful archive-citation rule (t261028-25: a head may be closed only on a manifest that
proves terminal closure), but NOT ONE production archive manifest carries such a proof —
460 of 460 are the merge-stage close-path shape, whose `meta.status` is a stale mid-run
snapshot, and the terminal-archive exit that would write `terminal_status` has never run.
The missing piece is a witness written AFTER the workflow is terminal.

What this battery pins (L1, grey-box on the public entry faces):
  1. a terminal close writes the post-close witness exactly once, with attribution
     (schema / ticket_id / terminal_status / closed_at / workflow_id / engine_version /
     written_by) — driven through the real `client.cmd_ticket_close_out` entry over a
     stubbed Temporal handle;
  2. a non-terminal end writes NO witness: a close whose post-terminate describe still
     reports a live status writes nothing and names why, and the merge-stage archive
     activity (`agent_activities.archive_ticket`) never writes one at all — that face
     runs while the ticket is still open;
  3. idempotence: a second write is a no-op and the marker stays byte-identical; a
     foreign file at the marker path is never overwritten (evidence is not regenerated);
  4. the refusal faces — absent / malformed / unknown schema / unattributed (hand-made
     file without the engine writer identity or engine version) — are all NO witness,
     named, and the sweep-facing citation refuses them under its own bucket;
  5. the sweep-facing citation accepts the marker and names the marker path plus the
     terminal status it proves (the consumer half of the rule lands with t261028-25's
     archive-citation code; the citation API pinned here is what it consults).

Offline only: stubbed Temporal handles (`_connect` patched), `SANDBAR_PROJECTS_DIR`
injected into a tmp dir, no network, no real Temporal, no git, never port 3099.
"""
import asyncio
import json

import pytest

import client
import shared

SCHEMA = shared.CLOSED_WITNESS_SCHEMA
MARKER = shared.CLOSED_WITNESS_FILE
PROJECT = "sandbar"
TID = "t261028-28"


# ---------- fixtures ----------

@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Isolate every env face these entries read: admin.log, identity, projects root."""
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, PROJECT)
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")
    return tmp_path


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
    """A ticket workflow that becomes terminal on terminate (the real server contract:
    terminate leaves the execution in TERMINATED). `after_terminate` lets a test pin the
    torn case instead - a post-terminate read that still reports a live status."""

    def __init__(self, status="RUNNING", project=PROJECT, tid=TID,
                 after_terminate="TERMINATED", desc_exc=None,
                 desc_exc_after_terminate=None):
        self.status_name = status
        self.project = project
        self.tid = tid
        self.after_terminate = after_terminate
        self.desc_exc = desc_exc
        self.desc_exc_after_terminate = desc_exc_after_terminate
        self.terminated = None
        self.events = []
        self._describes = 0

    async def query(self, name):
        return {"meta": {"project": self.project, "status": "dispatched"},
                "workflow_class": "DevLaneWorkflow", "template_id": "dev-lane",
                "refused": [], "authorizations": []}

    async def describe(self):
        self._describes += 1
        if self.desc_exc is not None:
            raise self.desc_exc
        if self.terminated is not None and self.desc_exc_after_terminate is not None:
            raise self.desc_exc_after_terminate
        status = self.after_terminate if self.terminated is not None else self.status_name
        return FakeDesc(status, self.project)

    async def signal(self, name, payload):
        self.events.append(("signal", name, payload))

    async def terminate(self, reason=""):
        self.events.append(("terminate", reason))
        self.terminated = reason


class FakeClient:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, tid):
        return self.handle


def _install(monkeypatch, handle):
    monkeypatch.setattr(client, "_connect",
                        lambda: asyncio.sleep(0, result=FakeClient(handle)))
    return handle


def _run(coro):
    return asyncio.run(coro)


def _data_dir(root, ticket=TID, project=PROJECT):
    return root / project / "data" / "tickets" / ticket


def _marker(root, ticket=TID, project=PROJECT):
    return _data_dir(root, ticket, project) / MARKER


def _close_out(**over):
    args = {"ticket_id": TID, "who": "integration",
            "reason": "work verified complete, merge booked"}
    args.update(over)
    return _run(client.cmd_ticket_close_out(args))


# ---------- 1. a terminal close writes the witness exactly once ----------

def test_terminal_close_writes_exactly_one_witness(projects_root, monkeypatch):
    h = _install(monkeypatch, FakeHandle())
    r = _close_out()
    assert r["ok"], r
    assert r["result"]["terminated"] is True
    # the close happened first (trace: signal -> terminate), then the observed write
    assert [e[0] for e in h.events] == ["signal", "terminate"]
    marker = _marker(projects_root)
    # exactly one marker file (the atomic temp file never survives)
    assert sorted(p.name for p in _data_dir(projects_root).iterdir()) == [MARKER]
    doc = json.loads(marker.read_text(encoding="utf-8"))
    assert doc["schema"] == SCHEMA and doc["schema"] != "v1"   # never the archive's schema
    assert doc["ticket_id"] == TID and doc["project"] == PROJECT
    assert doc["terminal_status"] == "TERMINATED"             # the OBSERVED status
    assert doc["workflow_id"] == TID
    assert doc["engine_version"] == shared.ENGINE_VERSION_V2
    assert doc["written_by"] in shared.CLOSED_WITNESS_WRITERS
    assert doc["written_by"] == client.WITNESS_CLOSE_OUT
    assert doc["closed_at"]                                  # ISO-8601 UTC, present
    assert "close-out" in doc["observed_by"]
    # the receipt names the recorded marker (never silent)
    face = r["result"]["post_close_witness"]
    assert face["written"] is True and face["path"] == str(marker)
    assert face["terminal_status"] == "TERMINATED"
    # the reader accepts it as a witness
    read = shared.read_closed_witness(PROJECT, TID)
    assert read["witness"] is True and read["state"] == "ok"
    assert read["terminal_status"] == "TERMINATED"


def test_no_data_written_outside_the_ticket_data_dir(projects_root, monkeypatch):
    _install(monkeypatch, FakeHandle())
    _close_out()
    # the witness is the only thing under the tickets data face, and it sits in the
    # cited ticket's own directory (the slot release writes its own ledger elsewhere)
    in_tickets = sorted(str(p.relative_to(projects_root))
                        for p in projects_root.rglob("data/tickets/*/*") if p.is_file())
    assert in_tickets == ["%s/data/tickets/%s/%s" % (PROJECT, TID, MARKER)], in_tickets
    assert _marker(projects_root).is_file()


# ---------- 2. a non-terminal end writes none ----------

def test_torn_post_terminate_read_writes_no_witness(projects_root, monkeypatch):
    """The status is observed, never inferred: a post-terminate read that still reports
    a live status records nothing and says which check failed."""
    _install(monkeypatch, FakeHandle(after_terminate="RUNNING"))
    r = _close_out()
    assert r["ok"], r                       # the close itself is not failed by this
    face = r["result"]["post_close_witness"]
    assert face["written"] is False and face["skipped"] is False
    assert face["reason"].startswith("post_close_status_not_terminal:RUNNING")
    assert not _marker(projects_root).exists()
    assert shared.read_closed_witness(PROJECT, TID)["state"] == "missing"


def test_failed_post_terminate_read_writes_no_witness(projects_root, monkeypatch):
    """terminate succeeded but the terminal status cannot be read back: nothing is
    inferred - no marker, and the receipt names the unreadable read."""
    h = _install(monkeypatch, FakeHandle(
        desc_exc_after_terminate=RuntimeError("visibility store down")))
    r = _close_out()
    assert r["ok"] is True and r["result"]["terminated"] is True
    assert [e[0] for e in h.events] == ["signal", "terminate"]
    face = r["result"]["post_close_witness"]
    assert face["written"] is False
    assert face["reason"].startswith("post_close_describe_failed:RuntimeError")
    assert not _marker(projects_root).exists()
    assert shared.read_closed_witness(PROJECT, TID)["state"] == "missing"


def test_merge_stage_archive_never_writes_a_witness(projects_root):
    """The ordinary close path archives INSIDE the merge stage, before the ticket is
    terminal - that face must never mint the post-close fact (the measured defect)."""
    import agent_activities

    res = asyncio.run(agent_activities.archive_ticket(
        shared.ArchiveArgs(ticket_id=TID, project_key=PROJECT, legacy=True)))
    assert res.ok is True
    ddir = _data_dir(projects_root)
    assert (ddir / "archive.json").is_file()      # the existing manifest contract, untouched
    assert not (ddir / MARKER).exists()
    assert shared.read_closed_witness(PROJECT, TID)["state"] == "missing"


# ---------- 3. idempotence ----------

def test_second_write_is_a_no_op_and_the_marker_stays_byte_identical(projects_root):
    first = shared.write_closed_witness(PROJECT, TID, "TERMINATED",
                                        client.WITNESS_CANCEL, observed_by="test")
    assert first["written"] is True
    path = _marker(projects_root)
    before = path.read_bytes()
    second = shared.write_closed_witness(PROJECT, TID, "COMPLETED",
                                         client.WITNESS_PRUNE, observed_by="test")
    assert second["written"] is False and second["skipped"] is True
    assert second["reason"].startswith("closed_witness_already_recorded")
    assert path.read_bytes() == before           # never rewritten, not even byte-equal
    assert json.loads(path.read_text(encoding="utf-8"))["terminal_status"] == "TERMINATED"


def test_second_close_writes_nothing_new(projects_root, monkeypatch):
    h = _install(monkeypatch, FakeHandle())
    assert _close_out()["ok"] is True
    path = _marker(projects_root)
    before = path.read_bytes()
    # the second close is the already-terminal idempotent branch (zero side effects)
    r = _close_out()
    assert r["ok"] is True and r["result"]["already_terminal"] is True
    assert path.read_bytes() == before
    assert sorted(p.name for p in _data_dir(projects_root).iterdir()) == [MARKER]
    assert h.events == [("signal", "close_out_notice", h.events[0][2]),
                        ("terminate", h.events[1][1])]


def test_existing_foreign_file_is_never_overwritten(projects_root):
    path = _marker(projects_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")
    before = path.read_bytes()
    res = shared.write_closed_witness(PROJECT, TID, "TERMINATED", client.WITNESS_PRUNE)
    assert res["written"] is False and res["skipped"] is False
    assert res["reason"].startswith("closed_witness_exists_and_is_not_a_witness:malformed")
    assert path.read_bytes() == before
    assert shared.read_closed_witness(PROJECT, TID)["state"] == "malformed"


# ---------- 4. the refusal faces: absent / malformed / unknown schema / unattributed --

def test_absent_witness_is_refused_by_name(projects_root):
    read = shared.read_closed_witness(PROJECT, TID)
    assert read["witness"] is False and read["state"] == "missing"
    assert read["reason"].startswith("closed_witness_absent:")
    cite = shared.closed_witness_citation(PROJECT, TID)
    assert cite["citable"] is False
    assert cite["bucket"] == "archive_no_terminal_witness"
    assert cite["reason"].startswith("closed_witness_absent:")


@pytest.mark.parametrize("content,state,needle", [
    ("{not json at all", "malformed", "closed_witness_malformed"),
    ("[]", "malformed", "closed_witness_malformed"),
    (json.dumps({"schema": "v9-future"}), "unknown_schema",
     "closed_witness_schema_unknown"),
    (json.dumps({"schema": "v1", "ticket_id": TID}), "unknown_schema",
     "closed_witness_schema_unknown"),
])
def test_broken_marker_is_no_witness(projects_root, content, state, needle):
    path = _marker(projects_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    read = shared.read_closed_witness(PROJECT, TID)
    assert read["witness"] is False and read["state"] == state
    assert needle in read["reason"]
    cite = shared.closed_witness_citation(PROJECT, TID)
    assert cite["citable"] is False
    assert cite["bucket"] == "archive_no_terminal_witness" and needle in cite["reason"]


def _hand_made(status="COMPLETED", **over):
    doc = {"schema": SCHEMA, "ticket_id": TID, "project": PROJECT,
           "terminal_status": status, "closed_at": "2026-10-28T00:00:00+00:00",
           "workflow_id": TID, "engine_version": shared.ENGINE_VERSION_V2,
           "written_by": client.WITNESS_PRUNE, "observed_by": "n/a"}
    doc.update(over)
    return doc


@pytest.mark.parametrize("over,needle", [
    ({"written_by": "hand:me"}, "closed_witness_unattributed"),
    ({"written_by": ""}, "closed_witness_unattributed"),
    ({"engine_version": None}, "closed_witness_unattributed"),
    ({"engine_version": "three"}, "closed_witness_unattributed"),
    ({"terminal_status": "RUNNING"}, "closed_witness_terminal_status_invalid"),
    ({"terminal_status": "CONTINUED_AS_NEW"}, "closed_witness_terminal_status_invalid"),
    ({"ticket_id": "t260101-01"}, "closed_witness_ticket_mismatch"),
])
def test_hand_made_marker_is_refused_by_name(projects_root, over, needle):
    """Attribution is what separates a real marker from a hand-made file: the writer
    identity must be an engine entry and the engine version must be a real one. A file
    that only copies the shape is NO witness."""
    path = _marker(projects_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_hand_made(**over)), encoding="utf-8")
    read = shared.read_closed_witness(PROJECT, TID)
    assert read["witness"] is False, over
    assert needle in read["reason"], read
    assert shared.closed_witness_citation(PROJECT, TID)["citable"] is False


def test_unknown_status_is_never_written(projects_root):
    for bad in ("RUNNING", "CONTINUED_AS_NEW", "", None, "done"):
        res = shared.write_closed_witness(PROJECT, TID, bad, client.WITNESS_CLOSE_OUT)
        assert res["written"] is False, bad
        assert res["reason"].startswith("closed_witness_terminal_status_invalid"), bad
    assert not _marker(projects_root).exists()


def test_unknown_writer_is_never_written(projects_root):
    res = shared.write_closed_witness(PROJECT, TID, "TERMINATED", "integration:me")
    assert res["written"] is False
    assert res["reason"].startswith("closed_witness_writer_unknown")
    assert not _marker(projects_root).exists()


# ---------- 5. the sweep-facing citation ----------

def test_citation_names_the_marker_path_and_terminal_status(projects_root):
    shared.write_closed_witness(PROJECT, TID, "COMPLETED", client.WITNESS_PRUNE,
                                observed_by="temporal-visibility listing")
    cite = shared.closed_witness_citation(PROJECT, TID)
    assert cite["citable"] is True
    assert cite["bucket"] == "archived_closed" == shared.CLOSED_WITNESS_CITABLE_BUCKET
    assert str(_marker(projects_root)) in cite["evidence"]
    assert "terminal_status=COMPLETED" in cite["evidence"]
    assert client.WITNESS_PRUNE in cite["evidence"]
    assert cite["terminal_status"] == "COMPLETED"


@pytest.mark.parametrize("status", ["FAILED", "CANCELED", "TIMED_OUT", "TERMINATED",
                                    "COMPLETED"])
def test_every_terminal_status_is_citable(projects_root, status):
    shared.write_closed_witness(PROJECT, TID, status, client.WITNESS_ARCHIVE_TERMINAL)
    cite = shared.closed_witness_citation(PROJECT, TID)
    assert cite["citable"] is True and cite["terminal_status"] == status


# ---------- 6. every close entry writes the same witness ----------

def test_archive_terminal_writes_the_witness_and_keeps_the_manifest_shape(
        projects_root, monkeypatch):
    h = _install(monkeypatch, FakeHandle(status="FAILED"))
    r = _run(client.cmd_ticket_archive_terminal(
        {"ticket_id": TID, "who": "ops",
         "reason": "runner OOM on stage implement; worktree kept"}))
    assert r["ok"], r
    manifest = json.loads((_data_dir(projects_root) / "archive.json").read_text("utf-8"))
    assert manifest["schema"] == "v1" and manifest["legacy"] is False
    assert manifest["terminal_status"] == "FAILED"          # manifest contract unchanged
    doc = json.loads(_marker(projects_root).read_text(encoding="utf-8"))
    assert doc["terminal_status"] == "FAILED"
    assert doc["written_by"] == client.WITNESS_ARCHIVE_TERMINAL
    assert h.events == []                                    # no signal, no terminate


def test_cancel_writes_the_witness_after_terminate(projects_root, monkeypatch):
    h = _install(monkeypatch, FakeHandle())
    r = _run(client.cmd_ticket_cancel(
        {"ticket_id": TID, "who": "ops", "reason": "workspace gone, not retriable"}))
    assert r["ok"], r
    assert [e[0] for e in h.events] == ["signal", "terminate"]
    doc = json.loads(_marker(projects_root).read_text(encoding="utf-8"))
    assert doc["written_by"] == client.WITNESS_CANCEL
    assert doc["terminal_status"] == "TERMINATED"


def test_prune_writes_the_witness_before_it_deletes_the_workflow(
        projects_root, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects_root))
    ddir = _data_dir(projects_root)
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "archive.json").write_text(
        json.dumps({"schema": "v1", "ticket_id": TID, "legacy": False,
                    "meta": {}, "files": [], "absent": []}), encoding="utf-8")
    seen_at_delete = {}

    async def deleter(wf_id):
        seen_at_delete[wf_id] = _marker(projects_root).is_file()

    r = _run(client.cmd_ticket_prune(
        {"execute": True}, entries=[{"id": TID, "sa_project": PROJECT, "close_ts": 1}],
        deleter=deleter))
    assert r["ok"], r
    body = r["result"]
    assert body["deleted"] == [TID]
    assert body["post_close_witness"]["written"] == [TID]
    assert seen_at_delete[TID] is True, "the witness must exist BEFORE the delete"
    assert shared.closed_witness_citation(PROJECT, TID)["citable"] is True


def test_prune_keeps_a_ticket_it_cannot_witness(projects_root):
    """Fail-closed: deleting the workflow destroys the last proof of terminality, so a
    ticket whose witness cannot be written is kept and named."""
    ddir = _data_dir(projects_root)
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "archive.json").write_text(
        json.dumps({"schema": "v1", "ticket_id": TID, "legacy": False,
                    "meta": {}, "files": [], "absent": []}), encoding="utf-8")
    (ddir / MARKER).write_text("{corrupt", encoding="utf-8")
    calls = []

    async def deleter(wf_id):
        calls.append(wf_id)

    r = _run(client.cmd_ticket_prune(
        {"execute": True}, entries=[{"id": TID, "sa_project": PROJECT, "close_ts": 1}],
        deleter=deleter))
    assert r["ok"], r
    body = r["result"]
    assert calls == [] and body["deleted"] == []
    assert len(body["failed"]) == 1 and body["failed"][0]["id"] == TID
    assert "post-close witness not recorded" in body["failed"][0]["why"]
    assert (ddir / "archive.json").is_file()          # nothing destroyed


def test_prune_dry_run_writes_nothing(projects_root):
    ddir = _data_dir(projects_root)
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "archive.json").write_text(
        json.dumps({"schema": "v1", "ticket_id": TID, "legacy": False,
                    "meta": {}, "files": [], "absent": []}), encoding="utf-8")

    async def deleter(wf_id):                     # pragma: no cover - never called
        raise AssertionError("dry-run must not delete")

    r = _run(client.cmd_ticket_prune(
        {}, entries=[{"id": TID, "sa_project": PROJECT, "close_ts": 1}],
        deleter=deleter))
    assert r["ok"] and r["result"]["deleted"] == [TID]
    assert r["result"]["post_close_witness"] == {"written": [], "skipped": []}
    assert not _marker(projects_root).exists()


def test_archive_legacy_records_the_witness_for_completed_entries(projects_root):
    """The legacy posting face reaches historical tickets, and every entry it sees is a
    COMPLETED workflow: it records the witness while the legacy manifest stays
    witness-less by contract (`legacy:true` proves no terminal fact)."""
    async def result_of(tid):
        return {"meta": {"status": "closed"}}

    r = _run(client.cmd_ticket_archive_legacy(
        {}, entries=[{"id": TID, "sa_project": PROJECT, "close_ts": 1}],
        result_of=result_of))
    assert r["ok"], r
    assert r["result"]["written"] == [{"id": TID, "path": str(_data_dir(projects_root))}]
    manifest = json.loads((_data_dir(projects_root) / "archive.json").read_text("utf-8"))
    assert manifest["legacy"] is True and manifest["schema"] == "v1"
    assert "terminal_status" not in manifest and "closed_at" not in manifest
    doc = json.loads(_marker(projects_root).read_text(encoding="utf-8"))
    assert doc["terminal_status"] == "COMPLETED"
    assert doc["written_by"] == client.WITNESS_ARCHIVE_LEGACY
    assert r["result"]["post_close_witness"]["written"] == [TID]
    # a second pass is a no-op on both faces (manifest skipped, witness skipped)
    r2 = _run(client.cmd_ticket_archive_legacy(
        {}, entries=[{"id": TID, "sa_project": PROJECT, "close_ts": 1}],
        result_of=result_of))
    assert r2["result"]["skipped"] == [TID]
    assert r2["result"]["post_close_witness"] == {"written": [], "skipped": [TID],
                                                  "failed": []}
    assert shared.closed_witness_citation(PROJECT, TID)["citable"] is True


def test_the_archive_manifest_contract_is_untouched(projects_root):
    """The witness is additive: it never rewrites an existing manifest, and the manifest
    never grows witness fields."""
    ddir = _data_dir(projects_root)
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "archive.json").write_text(
        json.dumps({"schema": "v1", "ticket_id": TID, "legacy": False,
                    "meta": {"status": "dispatched"}, "files": [], "absent": []}),
        encoding="utf-8")
    before = (ddir / "archive.json").read_bytes()
    shared.write_closed_witness(PROJECT, TID, "COMPLETED", client.WITNESS_PRUNE)
    assert (ddir / "archive.json").read_bytes() == before


# ======================================================================================
# The consumer half (t261028-25's cited-terminal rule + this ticket's marker): the
# request sweep closes a head ONLY when the cited ticket's on-disk evidence proves
# terminal closure. Marker present = citable; missing/malformed/hand-made = the head
# stays OPEN, named. Fixture roots are injected; the ticket channel is a stub.
# ======================================================================================
import request_sweep as rs  # noqa: E402

SWEEP_KEY = "proj-alpha"
SWEEP_NOW = 1730000000000
SWEEP_SEQ = 3


@pytest.fixture
def sweep_store(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    panel = tmp_path / "panel"
    projects.mkdir()
    panel.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("SANDBAR_PANEL_DIR", str(panel))
    env = {"SANDBAR_PROJECTS_DIR": str(projects), "SANDBAR_PANEL_DIR": str(panel)}
    return env, projects, panel


def _ledger_file(panel):
    return panel / SWEEP_KEY / "requests.jsonl"


def _write_heads(panel, rows):
    path = _ledger_file(panel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return path


def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _head(hid, kind, tid):
    return {"type": "request", "id": hid, "kind": kind,
            "question": "blocker: %s blocks the landing" % tid,
            "detail": "", "at": SWEEP_NOW, "default_action": "wait",
            "raised_by": "sess-x", "surface": "engine"}


def _close_path_manifest(projects, tid):
    """The shape the merge-stage close path writes: schema v1, legacy false, a
    mid-run meta snapshot, and NO terminal_status (measured 460/460)."""
    path = projects / SWEEP_KEY / "data" / "tickets" / tid / "archive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "v1", "ticket_id": tid, "legacy": False,
                                "archived_at": "2026-10-27T21:14:59+00:00",
                                "meta": {"status": "dispatched", "stage": "merge",
                                         "stage_state": "running"},
                                "files": [], "absent": [], "excluded_rules": []}),
                    encoding="utf-8")
    return path


def _sweep(env, status_map=None):
    def status_fn(ticket):
        if status_map and ticket in status_map:
            return status_map[ticket]
        return ("not-listed", "ticket-list-projection")
    return rs.sweep_project(
        SWEEP_KEY, SWEEP_NOW + 5, SWEEP_SEQ, env=env,
        ledger_rows_fn=lambda: ([], 0, ""),
        is_green=lambda rid: True, ticket_status_fn=status_fn)


def _residue(receipt, hid):
    for e in receipt.get("residue") or []:
        if e.get("id") == hid:
            return e
    return None


def test_sweep_closes_a_head_whose_cited_ticket_carries_the_marker(sweep_store):
    env, projects, panel = sweep_store
    tid = "t261026-91"
    _close_path_manifest(projects, tid)           # the witness-less production shape
    shared.write_closed_witness_at(
        projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER, tid, "COMPLETED",
        client.WITNESS_ARCHIVE_LEGACY, workflow_id=tid,
        observed_by="temporal-visibility listing (ExecutionStatus=Completed)",
        project_key=SWEEP_KEY)
    ledger = _write_heads(panel, [_head("b1", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b1")
    assert entry["bucket"] == "closed" and entry["via"] == "archive"
    marker_path = str(projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER)
    assert marker_path in entry["evidence"]                 # evidence cites the marker
    assert "terminal_status=COMPLETED" in entry["evidence"] # ... and the status
    # one resolved state row, quoting the same evidence
    states = [r for r in _rows(ledger) if r.get("state_for") == "b1"]
    assert len(states) == 1 and states[0]["state"] == rs.request_thread.STATE_RESOLVED
    assert states[0]["evidence"] == entry["evidence"]
    # the tally is honest: the on-disk-witness close is counted as archived_closed
    assert receipt["residue_buckets"]["archived_closed"] == 1
    assert receipt["residue_buckets"]["unchanged"] == 0


def test_sweep_keeps_the_head_open_when_the_marker_is_absent(sweep_store):
    """A ticket with no witness stays open, named — never inferred from the manifest's
    existence or its mid-run meta snapshot."""
    env, projects, panel = sweep_store
    tid = "t261026-92"
    _close_path_manifest(projects, tid)
    _write_heads(panel, [_head("b2", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b2")
    assert entry["bucket"] == "archive_no_terminal_witness"
    assert "archive_manifest_no_terminal_witness" in entry["reason"]
    assert "closed_witness_absent" in entry["reason"]      # both refusals named
    assert receipt["residue_buckets"]["archived_closed"] == 0
    assert receipt["residue_buckets"]["unchanged"] == 1


@pytest.mark.parametrize("content,needle", [
    (json.dumps({"schema": SCHEMA, "ticket_id": "t261026-93",
                 "terminal_status": "COMPLETED", "written_by": "hand:me",
                 "engine_version": shared.ENGINE_VERSION_V2,
                 "closed_at": "2026-10-28T00:00:00+00:00"}), "closed_witness_unattributed"),
    (json.dumps({"schema": SCHEMA, "ticket_id": "t261026-93",
                 "terminal_status": "RUNNING",
                 "written_by": client.WITNESS_PRUNE,
                 "engine_version": shared.ENGINE_VERSION_V2}),
     "closed_witness_terminal_status_invalid"),
    (json.dumps({"schema": "post-close-witness-v9", "ticket_id": "t261026-93"}),
     "closed_witness_schema_unknown"),
    ("{not json", "closed_witness_malformed"),
])
def test_sweep_refuses_a_bad_marker_by_name(sweep_store, content, needle):
    env, projects, panel = sweep_store
    tid = "t261026-93"
    _close_path_manifest(projects, tid)
    mpath = projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(content, encoding="utf-8")
    _write_heads(panel, [_head("b3", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b3")
    assert entry["bucket"] == "archive_no_terminal_witness"
    assert needle in entry["reason"], entry
    assert receipt["residue_buckets"]["archived_closed"] == 0


def test_sweep_still_accepts_a_manifest_that_carries_the_terminal_status(sweep_store):
    """t261028-25's archive rule is unchanged: a manifest written by the terminal
    archive exit closes the head with NO marker present."""
    env, projects, panel = sweep_store
    tid = "t261026-94"
    path = projects / SWEEP_KEY / "data" / "tickets" / tid / "archive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "v1", "ticket_id": tid, "legacy": False,
                                "terminal_status": "FAILED", "meta": {},
                                "files": [], "absent": [], "excluded_rules": []}),
                    encoding="utf-8")
    _write_heads(panel, [_head("b4", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b4")
    assert entry["bucket"] == "closed" and entry["via"] == "archive"
    assert "archive_terminal" in entry["note"]
    assert "terminal_status=FAILED" in entry["evidence"]
    assert not (projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER).exists()


def test_sweep_closes_on_the_marker_even_when_the_manifest_is_legacy(sweep_store):
    """The marker is an independent witness: a legacy manifest (witness-less by
    contract) does not cancel it, and the reason names the marker."""
    env, projects, panel = sweep_store
    tid = "t261026-95"
    path = projects / SWEEP_KEY / "data" / "tickets" / tid / "archive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "v1", "ticket_id": tid, "legacy": True,
                                "meta": {}, "files": [], "absent": []}),
                    encoding="utf-8")
    shared.write_closed_witness_at(
        projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER, tid, "COMPLETED",
        client.WITNESS_PRUNE, workflow_id=tid,
        observed_by="test", project_key=SWEEP_KEY)
    _write_heads(panel, [_head("b5", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b5")
    assert entry["bucket"] == "closed" and entry["via"] == "archive"
    assert entry["note"] == "post_close_witness:%s" % tid
    assert "terminal_status=COMPLETED" in entry["evidence"]


def test_sweep_never_consults_the_marker_against_a_live_projection(sweep_store):
    """A ticket Temporal still lists in a non-terminal state keeps the head open even
    when a marker file is on disk (a contradiction is never resolved into a close)."""
    env, projects, panel = sweep_store
    tid = "t261026-96"
    shared.write_closed_witness_at(
        projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER, tid, "COMPLETED",
        client.WITNESS_PRUNE, workflow_id=tid, observed_by="test",
        project_key=SWEEP_KEY)
    _write_heads(panel, [_head("b6", "blocker", tid)])
    receipt = _sweep(env, status_map={tid: ("dispatched", "ticket-list-projection")})
    entry = _residue(receipt, "b6")
    assert entry["bucket"] == "uncited"
    assert entry["reason"].startswith("cited_ticket_not_terminal")


def test_cross_project_close_writes_the_marker_into_the_target_project(
        projects_root, monkeypatch):
    """A lawful cross-project close-out records the witness under the TARGET ticket's
    project key (its snapshot meta), never the caller's stamp - the other key must stay
    untouched."""
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "other-proj")
    _install(monkeypatch, FakeHandle())
    r = _close_out(cross_project={"by": "integration",
                                  "reason": "closing a foreign ticket under the flag"})
    assert r["ok"], r
    assert _marker(projects_root, project=PROJECT).is_file()
    assert not (projects_root / "other-proj" / "data" / "tickets" / TID).exists(), \
        "the marker must never land in the caller's project"
    doc = json.loads(_marker(projects_root, project=PROJECT).read_text("utf-8"))
    assert doc["project"] == PROJECT
