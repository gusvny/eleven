"""t261028-17 — a closed ticket's row name comes from the archive, never from a message.

Host report 261028: the Epic tab showed old tickets as "workflow COMPLETED; snapshot past
the hydrate window; ..." instead of their real title. Cause: `cmd_ticket_list` took the
minimal-row branch for a closed ticket past Temporal's hydrate window (no snapshot, no
meta) and wrote that DIAGNOSTIC SENTENCE into the `title` slot, which the Epics tab
renders verbatim. The zero-live-pollers branch had the same anti-pattern (it replaced the
title with a "queue X has 0 live pollers ..." sentence).

Contract pinned here:
  A. an archived closed ticket past the hydrate window serves its REAL archived title on
     the row (plus epic / role / created where the manifest carries them);
  B. a missing / malformed / title-less archive serves an EMPTY title and an
     identity_note that names which condition held, with the path;
  C. the zero-pollers degraded row keeps its title untouched and carries the diagnostic
     in identity_note;
  D. no row title on any path carries a diagnostic sentence (the row family's note slot
     is `identity_note`);
  E. row-keyset parity: the no-snapshot family (FAILED / minimal / degraded) is ONE
     keyset, and the only key the family adds over the live row's key names is the
     pre-existing additive `identity_note` (t261009-76 spec (4), t260919-02 arbitrate).

Offline shape: the shared temporalio stub (integration/t260901-23/_stub_temporalio) plus
fake list/handle objects; the real client.py command layer runs end to end. The archive
store is a tmp project root (SANDBAR_PROJECTS_DIR) — no real ~/.sandbar path is written.
"""
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "integration" / "t260901-23"))
sys.path.insert(0, str(REPO / "server" / "engine"))

import _stub_temporalio  # noqa: E402
_stub_temporalio.install()

import client as client_mod  # noqa: E402  # the real client.py under the stub

PROJECT = "sandbar"
QUEUE = client_mod.TASK_QUEUE if hasattr(client_mod, "TASK_QUEUE") else "sandbar-tickets"
NOW = time.time()
PAST_WINDOW = datetime.fromtimestamp(NOW - 10 ** 7, tz=timezone.utc)

# The two diagnostics this ticket moved out of `title`. A row title must never contain
# any of these markers again (they are test-side markers, deliberately not shared with
# the engine code: the rule is about the row's shape, not about one message text).
DIAGNOSTIC_MARKERS = (
    "hydrate window",
    "0 live pollers",
    "reconciled",
    "unavailable(",
    "durable stage",
    "query timed out",
)


# ---------------------------------------------------------------- stubs
class _Status:
    def __init__(self, name):
        self.name = name


class _SAKeys:
    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        return self.kv.get(str(key))


class _Desc:
    def __init__(self, status_name):
        self.status = _Status(status_name) if status_name else None
        self.typed_search_attributes = _SAKeys({})


class FakeListWf:
    def __init__(self, tid, status_name, task_queue=None, sa_kv=None, close_time=None):
        self.id = tid
        self.status = _Status(status_name)
        self.task_queue = task_queue or QUEUE
        self.close_time = close_time
        self.start_time = None
        self._kv = sa_kv or {}

    @property
    def typed_search_attributes(self):
        return _SAKeys(self._kv)


class FakeHandle:
    def __init__(self, status_name=None, query_fn=None, result_fn=None):
        self._desc = _Desc(status_name)
        self._query_fn = query_fn
        self._result_fn = result_fn

    async def describe(self):
        return self._desc

    async def query(self, name):
        if self._query_fn is not None:
            return self._query_fn(name)
        return None

    async def result(self):
        if self._result_fn is not None:
            return self._result_fn()
        return None


class FakeClient:
    def __init__(self, wfs, handles):
        self._wfs = wfs
        self._handles = handles

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, _filter):
        for w in self._wfs:
            yield w


def _sa_kv(**kw):
    _K = client_mod.SearchAttributeKey
    names = {"project": client_mod.PROJECT_SA_NAME, "epic": client_mod.EPIC_SA_NAME}
    return {str(_K.for_keyword(names[k])): v for k, v in kw.items()}


def _list(monkeypatch, wfs, handles, args=None):
    async def _fake_connect():
        return FakeClient(wfs, handles)
    monkeypatch.setattr(client_mod, "_connect", _fake_connect)

    async def runner():
        return await client_mod.cmd_ticket_list(dict(args or {}))
    return asyncio.run(runner())


def _row_of(res, tid):
    for r in ((res.get("result") or {}).get("tickets") or []):
        if r.get("id") == tid:
            return r
    return None


def _archive_path(projects_root: Path, tid: str) -> Path:
    return projects_root / PROJECT / "data" / "tickets" / tid / "archive.json"


def _write_archive(projects_root: Path, tid: str, meta) -> Path:
    path = _archive_path(projects_root, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "v1", "ticket_id": tid, "legacy": False,
               "archived_at": "2026-10-28T00:00:00+00:00", "meta": meta,
               "files": [], "absent": []}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def setup_module(module):
    # Retry backoff is a config knob: zero it so the degraded path is instant (the
    # production default is untouched).
    client_mod.QUERY_RETRY_BASE_DELAY = 0.0
    client_mod.QUERY_RETRY_JITTER = 0.0


# ---------------------------------------------------------------- A. the real title
def test_a_archived_closed_row_serves_the_real_title(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    _write_archive(tmp_path, "t-arch", {
        "id": "t-arch", "title": "Old tickets show a diagnostic sentence as their title",
        "epic": "epic-from-archive", "role": "developer", "created": 1788764302,
        "status": "dispatched", "stage": "merge", "stage_state": "running",
    })
    wf = FakeListWf("t-arch", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                    close_time=PAST_WINDOW)
    res = _list(monkeypatch, [wf], {"t-arch": FakeHandle("COMPLETED")})
    row = _row_of(res, "t-arch")
    assert row is not None, "a closed ticket past the hydrate window stays on the board"
    assert row["title"] == "Old tickets show a diagnostic sentence as their title", \
        "the row serves the archive's real title: %r" % (row.get("title"),)
    # identity from the manifest where it is present
    assert row["epic"] == "epic-from-archive"
    assert row["role"] == "developer"
    assert row["created"] == 1788764302
    # the diagnostic is still readable, in the note slot
    assert "hydrate window" in row["identity_note"]
    assert not any(m in row["title"] for m in DIAGNOSTIC_MARKERS)


def test_a_search_attribute_epic_beats_the_archive(monkeypatch, tmp_path):
    # The SA is the ownership truth; the archive epic is the fallback (same precedence
    # as the snapshot meta path).
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    _write_archive(tmp_path, "t-arch-sa", {"title": "real name", "epic": "from-archive"})
    wf = FakeListWf("t-arch-sa", "COMPLETED", sa_kv=_sa_kv(project=PROJECT, epic="from-sa"),
                    close_time=PAST_WINDOW)
    row = _row_of(_list(monkeypatch, [wf], {"t-arch-sa": FakeHandle("COMPLETED")}),
                  "t-arch-sa")
    assert row["epic"] == "from-sa" and row["title"] == "real name"


# ---------------------------------------------------------------- B. honest empties
def test_b_missing_archive_is_an_empty_title_and_a_named_note(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    wf = FakeListWf("t-noarch", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                    close_time=PAST_WINDOW)
    row = _row_of(_list(monkeypatch, [wf], {"t-noarch": FakeHandle("COMPLETED")}),
                  "t-noarch")
    assert row["title"] == "", "no archive = no name, never a sentence: %r" % (row["title"],)
    note = row["identity_note"]
    assert "missing" in note, note
    assert str(_archive_path(tmp_path, "t-noarch")) in note, note
    assert not any(m in row["title"] for m in DIAGNOSTIC_MARKERS)


def test_b_malformed_archive_is_an_empty_title_and_a_named_note(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    path = _archive_path(tmp_path, "t-badarch")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    wf = FakeListWf("t-badarch", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                    close_time=PAST_WINDOW)
    row = _row_of(_list(monkeypatch, [wf], {"t-badarch": FakeHandle("COMPLETED")}),
                  "t-badarch")
    assert row["title"] == ""
    note = row["identity_note"]
    assert "malformed" in note and str(path) in note, note
    assert "missing" not in note.replace("missing schema", ""), \
        "a malformed manifest must not be reported as missing: %r" % note


def test_b_manifest_without_a_title_names_that_condition(monkeypatch, tmp_path):
    # The manifest parses but carries no meta.title: the note says exactly that (a
    # blanket "missing" would send the reader to the wrong place).
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    _write_archive(tmp_path, "t-notitle", {"epic": "e1"})
    wf = FakeListWf("t-notitle", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                    close_time=PAST_WINDOW)
    row = _row_of(_list(monkeypatch, [wf], {"t-notitle": FakeHandle("COMPLETED")}),
                  "t-notitle")
    assert row["title"] == ""
    assert "no meta.title" in row["identity_note"], row["identity_note"]


def test_b_malformed_project_key_is_named_not_raised(monkeypatch, tmp_path):
    # No usable project key on the SA (unregistered / old run): the archive read cannot
    # build a path. The row still lands, empty-named and named-cause (never a crash).
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    wf = FakeListWf("t-noproj", "COMPLETED", close_time=PAST_WINDOW)
    row = _row_of(_list(monkeypatch, [wf], {"t-noproj": FakeHandle("COMPLETED")}),
                  "t-noproj")
    assert row["title"] == "" and row["identity_note"] != ""
    assert "archive manifest" in row["identity_note"], row["identity_note"]


# ---------------------------------------------------------------- C. zero pollers
def _degraded_row(monkeypatch, poller_face, tid="t-q0"):
    """One RUNNING ticket whose snapshot query times out, with the poller probe's face
    pinned to `poller_face`. The memo reader is stubbed out so the durable labels do not
    vary; only the zero-pollers naming differs between the two calls."""
    monkeypatch.setattr(client_mod, "queue_live_pollers",
                        lambda *a, **k: _async(poller_face))

    async def _no_memo(_desc):
        raise RuntimeError("no memo stub")
    monkeypatch.setattr(client_mod, "_terminal_face_stage_from_memo", _no_memo)

    def _timeout(_name):
        raise asyncio.TimeoutError("stub timeout")
    wf = FakeListWf(tid, "RUNNING", sa_kv=_sa_kv(project=PROJECT))
    return _row_of(_list(monkeypatch, [wf], {tid: FakeHandle("RUNNING", query_fn=_timeout)}),
                   tid)


def test_c_zero_pollers_keeps_the_title_and_notes_the_cause(monkeypatch):
    # Control run: the probe cannot prove anything (available=False) -> the generic
    # degraded row. Compare run: the probe PROVES zero live pollers. The title must be
    # byte-identical across the two (the branch changes the NOTE, not the name).
    control = _degraded_row(monkeypatch, {"available": False}, tid="t-q0-control")
    row = _degraded_row(monkeypatch, {"available": True, "live_pollers": 0,
                                      "queue": "sandbar-ticket-t-q0"})
    assert control["title"] == row["title"], \
        "the zero-pollers branch must not overwrite the title: %r vs %r" % (
            row["title"], control["title"])
    assert row["title"] != "" and not any(m in row["title"] for m in DIAGNOSTIC_MARKERS)
    note = row["identity_note"]
    assert "0 live pollers" in note and "sandbar-ticket-t-q0" in note, note
    assert "0 live pollers" not in control["identity_note"], \
        "an unproven poller face must not claim zero pollers: %r" % control["identity_note"]
    # the control row's note slot is still a string (no diagnostic to report there)
    assert control["identity_note"] == ""


def test_c_durable_labels_ride_in_the_note_not_the_title(monkeypatch):
    monkeypatch.setattr(client_mod, "queue_live_pollers",
                        lambda *a, **k: _async({"available": False}))

    async def _memo(_desc):
        return {"last_stage": "implement", "last_stage_available": True,
                "last_stage_note": "", "last_stage_history": [{"ts": 1793136231}]}
    monkeypatch.setattr(client_mod, "_terminal_face_stage_from_memo", _memo)

    def _timeout(_name):
        raise asyncio.TimeoutError("stub timeout")
    wf = FakeListWf("t-dur", "RUNNING", sa_kv=_sa_kv(project=PROJECT))
    row = _row_of(_list(monkeypatch, [wf], {"t-dur": FakeHandle("RUNNING", query_fn=_timeout)}),
                  "t-dur")
    assert "durable stage: implement" in row["identity_note"], row["identity_note"]
    assert "implement" not in row["title"], \
        "the durable label is a diagnostic, not a name: %r" % (row["title"],)
    assert row["title"] != "" and not any(m in row["title"] for m in DIAGNOSTIC_MARKERS)
    assert row["updated_ts"] == 1793136231, "the durable time still reaches the row"


async def _async(value):
    return value


# ---------------------------------------------------------------- D. no sentence in title
def test_d_no_row_title_carries_a_diagnostic(monkeypatch, tmp_path):
    # One board holding every shape this file can produce at once: archived closed,
    # archive-less closed, failed, zero-poller degraded, healthy live.
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    _write_archive(tmp_path, "t-arch2", {"title": "Real archived name"})
    monkeypatch.setattr(client_mod, "queue_live_pollers",
                        lambda *a, **k: _async({"available": True, "live_pollers": 0,
                                                "queue": "sandbar-ticket-t-q0"}))

    async def _no_memo(_desc):
        raise RuntimeError("no memo stub")
    monkeypatch.setattr(client_mod, "_terminal_face_stage_from_memo", _no_memo)

    def _timeout(_name):
        raise asyncio.TimeoutError("stub timeout")

    def _raise():
        raise RuntimeError("boom")

    live_snap = {"engine": "v2", "meta": {"id": "t-live2", "title": "Live ticket name",
                                          "project": PROJECT, "role": "developer",
                                          "status": "dispatched", "stage": "implement",
                                          "stage_state": "running",
                                          "created": 1700000000, "updated": 1700000100}}
    wfs = [
        FakeListWf("t-arch2", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                   close_time=PAST_WINDOW),
        FakeListWf("t-old2", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                   close_time=PAST_WINDOW),
        FakeListWf("t-fail2", "FAILED", sa_kv=_sa_kv(project=PROJECT),
                   close_time=datetime.fromtimestamp(NOW - 60, tz=timezone.utc)),
        FakeListWf("t-q02", "RUNNING", sa_kv=_sa_kv(project=PROJECT)),
        FakeListWf("t-live2", "RUNNING", sa_kv=_sa_kv(project=PROJECT)),
    ]
    handles = {
        "t-arch2": FakeHandle("COMPLETED"),
        "t-old2": FakeHandle("COMPLETED"),
        "t-fail2": FakeHandle("FAILED", result_fn=_raise),
        "t-q02": FakeHandle("RUNNING", query_fn=_timeout),
        "t-live2": FakeHandle("RUNNING", query_fn=lambda name: live_snap),
    }
    res = _list(monkeypatch, wfs, handles)
    rows = (res.get("result") or {}).get("tickets") or []
    assert len(rows) == 5, "all five shapes stay on the board"
    for r in rows:
        assert isinstance(r["title"], str)
        for marker in DIAGNOSTIC_MARKERS:
            assert marker not in r["title"], \
                "ticket %s puts a diagnostic in its name slot (%r)" % (r["id"], r["title"])
    assert _row_of(res, "t-arch2")["title"] == "Real archived name"
    assert _row_of(res, "t-live2")["title"] == "Live ticket name"


def test_d_title_slot_source_rule():
    # The rule as code: a `title` slot takes a NAME (a value or a short label), never a
    # built sentence. A parenthesized / multi-line title expression is exactly the shape
    # that produced this bug, so it is refused at the source.
    src = (REPO / "server" / "engine" / "client.py").read_text(encoding="utf-8")
    assert not re.search(r'"title"\s*:\s*\(\s*"', src), \
        "a title slot must not take a parenthesized sentence"
    for literal in re.findall(r'"title"\s*:\s*"([^"\n]*)"', src):
        assert len(literal) <= 32 and "; " not in literal, \
            "title literal reads as a sentence: %r" % literal
    for literal in re.findall(r'\["title"\]\s*=\s*"([^"\n]*)"', src):
        assert len(literal) <= 32 and "; " not in literal, \
            "title literal reads as a sentence: %r" % literal


# ---------------------------------------------------------------- E. keyset parity
def test_e_row_keyset_parity_across_the_no_snapshot_family(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(client_mod, "queue_live_pollers",
                        lambda *a, **k: _async({"available": False}))

    async def _no_memo(_desc):
        raise RuntimeError("no memo stub")
    monkeypatch.setattr(client_mod, "_terminal_face_stage_from_memo", _no_memo)

    def _timeout(_name):
        raise asyncio.TimeoutError("stub timeout")

    def _raise():
        raise RuntimeError("boom")

    wfs = [
        FakeListWf("t-fail3", "FAILED", sa_kv=_sa_kv(project=PROJECT),
                   close_time=datetime.fromtimestamp(NOW - 60, tz=timezone.utc)),
        FakeListWf("t-closed3", "COMPLETED", sa_kv=_sa_kv(project=PROJECT),
                   close_time=PAST_WINDOW),
        FakeListWf("t-run3", "RUNNING", sa_kv=_sa_kv(project=PROJECT)),
        # a non-terminal minimal row: no snapshot path applies (continued-as-new), so
        # the row is assembled from the minimal branch with an empty exec identity
        FakeListWf("t-cont3", "CONTINUED_AS_NEW", sa_kv=_sa_kv(project=PROJECT),
                   close_time=datetime.fromtimestamp(NOW - 60, tz=timezone.utc)),
    ]
    handles = {
        "t-fail3": FakeHandle("FAILED", result_fn=_raise),
        "t-closed3": FakeHandle("COMPLETED"),
        "t-run3": FakeHandle("RUNNING", query_fn=_timeout),
        "t-cont3": FakeHandle("CONTINUED_AS_NEW"),
    }
    res = _list(monkeypatch, wfs, handles)
    failed = _row_of(res, "t-fail3")
    closed = _row_of(res, "t-closed3")
    degraded = _row_of(res, "t-run3")
    minimal = _row_of(res, "t-cont3")
    for row in (failed, closed, degraded, minimal):
        assert row is not None
    # ONE keyset across FAILED / minimal / degraded (t260919-02 / t260921-03 parity).
    keyset = set(closed)
    for row in (failed, degraded, minimal):
        assert set(row) == keyset, "no-snapshot family keyset drifted: %s" % sorted(
            set(row) ^ keyset)
    # The live row's key names, pinned by the list face it actually serves (t261009-76
    # spec (4)); the family's only extra key is the pre-existing additive note slot.
    live_keys = set(client_mod._row_from_meta("t-live", {"title": "x"}, "RUNNING"))
    live_keys.add("close_ts")                      # cmd_ticket_list stamps close_ts
    assert keyset - live_keys == {"identity_note"}
    assert live_keys - keyset == {"paused", "paused_phase"}   # pre-existing, untouched
    assert "identity_note" in keyset
    # the note slot is a string on every shape (consumers may read it unconditionally)
    assert failed["identity_note"] == "" and isinstance(degraded["identity_note"], str)
