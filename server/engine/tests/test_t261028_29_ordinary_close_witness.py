"""t261028-35 (evidence name: t261028_29): the ORDINARY close mints the post-close witness.

Why this battery exists (measured 261028, not re-derived here): t261028-30 gave the
engine a post-close witness written by the caller-driven close entries (ticket-cancel,
ticket-close-out, archive-terminal, prune, archive-legacy). The ORDINARY way a ticket
closes - the merge lane finishing and the workflow completing on its own - writes none:
the merge stage archives the ticket while it is STILL OPEN, so that face can never carry
a terminal fact, and the request sweep could therefore never cite an ordinary closure.

What this battery pins (L1, grey-box on the engine's own watch face):
  1. a ticket that settles on the ordinary path leaves EXACTLY ONE witness, carrying the
     observed terminal status, the target ticket's project key, the watching writer's
     registered identity and the engine version - minted through the shared writer
     (one implementation, one schema), driven through the production mint the watch round
     calls (`worker.observe_ordinary_close`) with the loop wiring pinned in place;
  2. a ticket that is still RUNNING leaves none, and a query failure neither stops the
     watcher nor writes anything (the status is observed, never inferred);
  3. CONTINUED_AS_NEW is never a closure (it is an unclosed watcher handover), and an
     unreadable project key is never guessed: both write nothing and say why;
  4. idempotence and attribution are the shared writer's, unchanged: a second observation
     is a no-op with byte-identical bytes, and a hand-made/foreign file at the marker
     path is refused by name and never overwritten;
  5. the sweep-facing leg: a blocker head citing such a ticket is closed on the marker
     citation (bucket `archived_closed`, via `archive`, evidence naming the marker path
     and the terminal status), while the same head without the marker stays open, named;
  6. nothing is written outside the ticket's own data dir and no archive manifest is
     touched (the manifest contract is not this ticket's business).

Offline only: stubbed Temporal handles, `SANDBAR_PROJECTS_DIR` / `SANDBAR_PANEL_DIR`
injected into tmp dirs, no network, no real Temporal, no git, never port 3099.
"""
import asyncio
import json

import pytest

import request_sweep as rs
import shared
import worker

SCHEMA = shared.CLOSED_WITNESS_SCHEMA
MARKER = shared.CLOSED_WITNESS_FILE
PROJECT = "sandbar"
TID = "t261028-29"


# ---------- fixtures ----------

@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Isolate every env face the witness path and the sweep read."""
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    return tmp_path


class FakeSearchAttrs:
    def __init__(self, project=""):
        self._p = project

    def get(self, key):
        return self._p


class FakeDesc:
    def __init__(self, status, project=PROJECT, close_time=None):
        self.status = type("ExecStatus", (), {"name": status})()
        self.typed_search_attributes = FakeSearchAttrs(project)
        self.search_attributes = {shared.PROJECT_SA_NAME: project}
        self.close_time = close_time


class FakeHandle:
    """A ticket workflow that settles on its own (the ORDINARY merge close: the lane
    finishes, the workflow completes — nobody terminates it). `describe_exc` and
    `statuses` let a test pin the torn read and the per-observation status."""

    def __init__(self, statuses=("RUNNING", "COMPLETED"), project=PROJECT,
                 tid=TID, describe_exc=None, close_time=None):
        self.statuses = list(statuses)
        self.project = project
        self.tid = tid
        self.describe_exc = describe_exc
        self.close_time = close_time
        self.describes = 0

    async def describe(self):
        self.describes += 1
        if self.describe_exc is not None:
            raise self.describe_exc
        idx = min(self.describes - 1, len(self.statuses) - 1)
        return FakeDesc(self.statuses[idx], self.project, self.close_time)


class FakeClient:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, tid):
        return self.handle


def _observe(handle, tid=TID):
    return asyncio.run(worker.observe_ordinary_close(handle, tid))


def _watch_source():
    """The per-ticket watch loop's own source (its wiring is the claim under test)."""
    import inspect
    return inspect.getsource(worker.run_worker)


def _data_dir(root, ticket=TID, project=PROJECT):
    return root / project / "data" / "tickets" / ticket


def _marker(root, ticket=TID, project=PROJECT):
    return _data_dir(root, ticket, project) / MARKER


def _doc(root, ticket=TID, project=PROJECT):
    return json.loads(_marker(root, ticket, project).read_text(encoding="utf-8"))


# ======================================================================================
# 1. an ordinary merge-close leaves exactly one witness, naming the observed status
# ======================================================================================

def test_ordinary_merge_close_mints_exactly_one_witness(projects_root):
    """The settling observation records the SAME witness the client close entries write —
    one marker, the observed status, the ticket's own project key."""
    # the round before the settle: a live ticket is never observed as a close
    assert _observe(FakeHandle(statuses=("RUNNING",)))["written"] is False
    assert not _data_dir(projects_root).exists()
    # the round in which the lane finished: the ticket has settled -> one witness
    h = FakeHandle(statuses=("COMPLETED",))
    face = _observe(h)
    assert face["written"] is True, face
    assert face["skipped"] is False
    # exactly one file in the ticket's data dir (the atomic temp file never survives)
    assert sorted(p.name for p in _data_dir(projects_root).iterdir()) == [MARKER]
    doc = _doc(projects_root)
    assert doc["schema"] == SCHEMA and doc["schema"] != "v1"  # never the archive schema
    assert doc["ticket_id"] == TID and doc["project"] == PROJECT
    assert doc["terminal_status"] == "COMPLETED"              # the OBSERVED status
    assert doc["workflow_id"] == TID
    assert doc["engine_version"] == shared.ENGINE_VERSION_V2
    assert doc["written_by"] == worker.WITNESS_TICKET_WATCH
    assert doc["written_by"] in shared.CLOSED_WITNESS_WRITERS
    assert doc["closed_at"]                                     # ISO-8601 UTC when readable
    assert "worker.ticket-watch" in doc["observed_by"]
    # the receipt names the file it wrote (never silent)
    assert face["path"] == str(_marker(projects_root))
    assert face["terminal_status"] == "COMPLETED"
    # the shared reader accepts it as a witness
    read = shared.read_closed_witness(PROJECT, TID)
    assert read["witness"] is True and read["state"] == "ok"
    assert read["terminal_status"] == "COMPLETED"


def test_the_witness_writer_id_is_a_registered_engine_writer():
    """Attribution is the shared closed set's: an unregistered identity would make the
    marker indistinguishable from a hand-made file (the writer refuses it by name)."""
    assert worker.WITNESS_TICKET_WATCH in shared.CLOSED_WITNESS_WRITERS


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELED", "TIMED_OUT",
                                    "TERMINATED"])
def test_every_eligible_terminal_status_is_recorded_verbatim(projects_root, status):
    """The eligible set is shared.CLOSED_WITNESS_STATUSES — the terminal set minus
    CONTINUED_AS_NEW. Each one is recorded verbatim, never mapped."""
    face = _observe(FakeHandle(statuses=(status,)))
    assert face["written"] is True, face
    assert face["terminal_status"] == status
    assert _doc(projects_root)["terminal_status"] == status


def test_the_close_time_of_the_workflow_is_the_witness_closed_at(projects_root):
    """When the describe carries the execution's own close time, that is what the
    marker records — the observation's timestamp, not the writer's clock guess."""
    import datetime
    ct = datetime.datetime(2026, 10, 28, 3, 30, tzinfo=datetime.timezone.utc)
    face = _observe(FakeHandle(statuses=("COMPLETED",), close_time=ct))
    assert face["written"] is True, face
    assert _doc(projects_root)["closed_at"] == ct.isoformat(timespec="seconds")


def test_the_watch_loop_mints_in_the_settled_branch_before_it_stops():
    """Where the mint sits is the whole ticket: the per-ticket watch loop is the actor
    that OBSERVES the ordinary close, so the mint must live in its settled branch —
    after the settle observation, before the stop. The stop rule itself is unchanged
    (any status outside RUNNING), and the settle line keeps its wording because the
    t260905-02 scenario greps it (a consumed cross-face contract)."""
    src = _watch_source()
    settle = src.index("if status and status != \"RUNNING\":")   # copy-lang-allow:fixture
    mint = src.index("observe_ordinary_close(", settle)
    say = src.index("log_watch_witness(", mint)
    stop = src.index("stop.set()", settle)
    assert settle < mint < say < stop, src[settle:stop]
    # the consumed settle line is still emitted by the loop, verbatim
    assert "已收口" in src[settle:stop]                    # copy-lang-allow:fixture


# ======================================================================================
# 2. never a guess: a live ticket, a failed read and an unreadable project key
# ======================================================================================

def test_running_ticket_mints_nothing(projects_root):
    """A ticket Temporal still reports as RUNNING is no close: nothing is written."""
    assert _observe(FakeHandle(statuses=("RUNNING",)))["written"] is False
    assert not _data_dir(projects_root).exists()      # nothing written at all


def test_a_failed_read_writes_nothing_and_names_the_fault(projects_root):
    """A flaky read is NOT a close: no marker, and the refusal names the fault."""
    face = _observe(FakeHandle(describe_exc=RuntimeError("temporal hiccup")))
    assert face["written"] is False and face["path"] == ""
    assert "RuntimeError: temporal hiccup" in face["reason"]
    assert not _data_dir(projects_root).exists()


def test_torn_terminal_read_writes_nothing_and_is_named(projects_root):
    """The status is observed, never inferred: the settling observation is a FRESH
    describe of its own, so a read that tears at that moment records nothing — and the
    refusal names the failing check instead of guessing a status."""
    class Torn(FakeHandle):
        async def describe(self):
            raise ConnectionError("read torn mid-flight")

    face = _observe(Torn(statuses=("COMPLETED",)))
    assert face["written"] is False and face["path"] == ""
    assert face["reason"].startswith("ordinary_close_describe_failed")
    assert "ConnectionError: read torn mid-flight" in face["reason"]
    assert not _data_dir(projects_root).exists()


def test_continued_as_new_is_never_a_closure(projects_root):
    """CONTINUED_AS_NEW is an unclosed watcher handover (KI-025), not a close: the
    watcher stops on it (unchanged rule) but records no witness and says why."""
    face = _observe(FakeHandle(statuses=("CONTINUED_AS_NEW",)))
    assert face["written"] is False
    assert face["reason"].startswith("ordinary_close_status_not_eligible")
    assert "CONTINUED_AS_NEW" in face["reason"]
    assert not _data_dir(projects_root).exists()


def test_an_unreadable_project_key_is_never_guessed(projects_root):
    """Without the target ticket's project key the marker would land in a guessed data
    dir: nothing is written and the refusal names it."""
    face = _observe(FakeHandle(statuses=("COMPLETED",), project=""))
    assert face["written"] is False
    assert face["reason"].startswith("ordinary_close_project_unknown")
    assert list(projects_root.rglob("*")) == []       # not even an empty data dir


# ======================================================================================
# 3. idempotence and attribution are the shared writer's, unchanged
# ======================================================================================

def test_a_second_observation_writes_nothing_and_keeps_the_bytes(projects_root):
    h = FakeHandle(statuses=("COMPLETED",))
    assert _observe(h)["written"] is True
    first = _marker(projects_root).read_bytes()
    second = _observe(h)                                  # the same settled ticket again
    assert second["written"] is False and second["skipped"] is True
    assert second["reason"].startswith("closed_witness_already_recorded")
    assert _marker(projects_root).read_bytes() == first
    # a third observation of the same settled ticket changes nothing either
    third = _observe(FakeHandle(statuses=("COMPLETED",)))
    assert third["written"] is False and third["skipped"] is True
    assert _marker(projects_root).read_bytes() == first
    assert sorted(p.name for p in _data_dir(projects_root).iterdir()) == [MARKER]


def test_a_witness_a_close_entry_already_recorded_is_never_replaced(projects_root):
    """The watcher is a second OBSERVER, not a second authority: when a caller-driven
    close already recorded the witness, the watcher's observation is a no-op — the
    bytes and the attribution stay the close entry's."""
    import client
    first = shared.write_closed_witness(PROJECT, TID, "TERMINATED",
                                        client.WITNESS_CLOSE_OUT, workflow_id=TID,
                                        observed_by="temporal-describe after "
                                                    "ticket-close-out terminate")
    assert first["written"] is True, first
    before = _marker(projects_root).read_bytes()
    face = _observe(FakeHandle(statuses=("TERMINATED",)))
    assert face["written"] is False and face["skipped"] is True
    assert _marker(projects_root).read_bytes() == before
    assert _doc(projects_root)["written_by"] == client.WITNESS_CLOSE_OUT


def test_a_hand_made_marker_is_refused_by_name_and_never_overwritten(projects_root):
    """A file at the marker path that the engine did not write is evidence of something
    else: the writer refuses by name and leaves it byte-identical."""
    path = _marker(projects_root)
    path.parent.mkdir(parents=True)
    hand_made = json.dumps({"schema": SCHEMA, "ticket_id": TID, "project": PROJECT,
                            "terminal_status": "COMPLETED",
                            "written_by": "hand:me",
                            "engine_version": shared.ENGINE_VERSION_V2})
    path.write_text(hand_made, encoding="utf-8")
    face = _observe(FakeHandle(statuses=("COMPLETED",)))
    assert face["written"] is False
    assert "closed_witness_exists_and_is_not_a_witness" in face["reason"]
    assert "unattributed" in face["reason"]        # the failing check is named
    assert path.read_text(encoding="utf-8") == hand_made
    # and the shared reader still treats it as NO witness
    assert shared.read_closed_witness(PROJECT, TID)["witness"] is False


def test_the_witness_log_names_what_happened_never_dresses_up_a_refusal(projects_root,
                                                                       caplog):
    """The witness line reports the close observation's outcome. A witness that was NOT
    written must never read as one that was: the refusal reason rides on the same line
    (the consumed settle line itself lives in the loop and is pinned above)."""
    face = _observe(FakeHandle(statuses=("COMPLETED",)))
    with caplog.at_level("INFO", logger="root"):
        worker.log_watch_witness(TID, face)
    text = "\n".join(r.getMessage() for r in caplog.records)
    written_line = [m for m in text.splitlines() if "post-close witness" in m]
    assert len(written_line) == 1, text
    assert "written=True" in written_line[0]
    assert "observed=COMPLETED" in written_line[0]
    assert str(_marker(projects_root)) in written_line[0]
    # a refused witness says so on the same line (never silent, never dressed up)
    caplog.clear()
    refused = _observe(FakeHandle(statuses=("CONTINUED_AS_NEW",)))
    with caplog.at_level("INFO", logger="root"):
        worker.log_watch_witness(TID, refused)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "written=False" in text
    assert "ordinary_close_status_not_eligible" in text


def test_nothing_is_written_outside_the_ticket_data_dir(projects_root):
    """The marker is the only thing the watch face writes, and it sits in the cited
    ticket's own directory — no archive manifest, no sibling ticket, no other key."""
    assert _observe(FakeHandle(statuses=("COMPLETED",)))["written"] is True
    files = sorted(str(p.relative_to(projects_root))
                   for p in projects_root.rglob("*") if p.is_file())
    assert files == ["%s/data/tickets/%s/%s" % (PROJECT, TID, MARKER)], files
    assert not (_data_dir(projects_root) / "archive.json").exists()


def test_an_existing_archive_manifest_is_left_alone(projects_root):
    """The archive manifest contract is not this ticket's business: a manifest already
    on disk keeps its exact bytes (the witness is additive)."""
    manifest = _data_dir(projects_root) / "archive.json"
    manifest.parent.mkdir(parents=True)
    before = json.dumps({"schema": "v1", "ticket_id": TID, "legacy": False,
                         "meta": {"status": "merge", "stage": "merge"},
                         "files": [], "absent": [], "excluded_rules": []})
    manifest.write_text(before, encoding="utf-8")
    assert _observe(FakeHandle(statuses=("COMPLETED",)))["written"] is True
    assert manifest.read_text(encoding="utf-8") == before
    assert _marker(projects_root).is_file()


# ======================================================================================
# 4. the consumer: the request sweep closes a head on the marker the worker minted
# ======================================================================================

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
    """The shape the merge-stage close path writes: schema v1, legacy false, a mid-run
    meta snapshot and NO terminal_status. It proves nothing on its own."""
    path = projects / SWEEP_KEY / "data" / "tickets" / tid / "archive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "v1", "ticket_id": tid, "legacy": False,
                                "archived_at": "2026-10-28T03:00:00+00:00",
                                "meta": {"status": "merge", "stage": "merge",
                                         "stage_state": "running"},
                                "files": [], "absent": [], "excluded_rules": []}),
                    encoding="utf-8")
    return path


def _sweep(env):
    return rs.sweep_project(
        SWEEP_KEY, SWEEP_NOW + 5, SWEEP_SEQ, env=env,
        ledger_rows_fn=lambda: ([], 0, ""),
        is_green=lambda rid: True,
        ticket_status_fn=lambda t: ("not-listed", "ticket-list-projection"))


def _residue(receipt, hid):
    for e in receipt.get("residue") or []:
        if e.get("id") == hid:
            return e
    return None


def test_sweep_closes_a_blocker_head_on_the_marker_the_worker_minted(sweep_store):
    """End to end on the fixture store: the ordinary close's marker (minted by the real
    watch face) is citable closure evidence for a blocker head citing the ticket."""
    env, projects, panel = sweep_store
    tid = "t261026-97"
    _close_path_manifest(projects, tid)          # the witness-less ordinary-close shape
    handle = FakeHandle(statuses=("COMPLETED",), project=SWEEP_KEY, tid=tid)
    assert _observe(handle, tid)["written"] is True
    ledger = _write_heads(panel, [_head("b7", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b7")
    assert entry["bucket"] == "closed" and entry["via"] == "archive"
    assert entry["note"] == "post_close_witness:%s" % tid
    marker_path = str(projects / SWEEP_KEY / "data" / "tickets" / tid / MARKER)
    assert marker_path in entry["evidence"]                  # evidence cites the marker
    assert "terminal_status=COMPLETED" in entry["evidence"]   # ... and the status
    assert worker.WITNESS_TICKET_WATCH in entry["evidence"]   # ... and who wrote it
    states = [r for r in _rows(ledger) if r.get("state_for") == "b7"]
    assert len(states) == 1 and states[0]["state"] == rs.request_thread.STATE_RESOLVED
    assert states[0]["evidence"] == entry["evidence"]
    assert receipt["residue_buckets"]["archived_closed"] == 1
    assert receipt["residue_buckets"]["unchanged"] == 0


def test_sweep_keeps_the_head_open_without_the_worker_marker(sweep_store):
    """The merge-stage manifest alone (what every ordinary close used to leave) is no
    closure: without the marker the head stays open, and both refusals are named."""
    env, projects, panel = sweep_store
    tid = "t261026-98"
    _close_path_manifest(projects, tid)
    _write_heads(panel, [_head("b8", "blocker", tid)])
    receipt = _sweep(env)
    entry = _residue(receipt, "b8")
    assert entry["bucket"] == "archive_no_terminal_witness"
    assert "archive_manifest_no_terminal_witness" in entry["reason"]
    assert "closed_witness_absent" in entry["reason"]
    assert receipt["residue_buckets"]["archived_closed"] == 0
    assert receipt["residue_buckets"]["unchanged"] == 1
