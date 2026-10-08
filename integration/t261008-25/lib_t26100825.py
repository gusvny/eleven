#!/usr/bin/env python3
"""t261008-25 KI-223 scenario shared fixture (no sc_ prefix = shared code, not registered).

Offline full-chain stub style (t260922-10 lib_t26092210 same pattern, zero docker /
zero 3099 / zero real Temporal):
  stub Temporal client/handle (reuses t260901-23 _stub_temporalio)
    -> real client.py command layer (cmd_ticket_archive_terminal /
       cmd_ticket_list / cmd_ticket_prune with injected entries+deleter)

Audit/write isolation: the fixture redirects ticket_data_dir (the single point where
_read_archive_manifest and the archive exit resolve the per-ticket data dir) into a
per-scenario tmp dir, so the repo tree gets zero writes and each scenario sees its own
disposition state. Callers must call install_data_root() before any command call.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

sys.path.insert(0, str(HERE.parent / 't260901-23'))   # shared stub _stub_temporalio
sys.path.insert(0, str(REPO / 'server' / 'engine'))   # real client.py
sys.path.insert(0, str(REPO / 'server'))              # real tools_registry

import _stub_temporalio  # noqa: E402  must install before client import
_stub_temporalio.install()

import client as client_mod  # noqa: E402

FIXTURE_PROJECT = 'ki223-fixture'   # the ticket says: the fixture creates its own


class _Status:
    def __init__(self, name):
        self.name = name


class _SA:
    """Minimal typed_search_attributes stand-in: keyword get by name."""

    def __init__(self, project=''):
        self._project = project

    def get(self, key):
        # SearchAttributeKey.for_keyword("ProjectKey") stringifies to something that
        # contains the name in the real SDK; the stub matches on the plain name.
        if 'ProjectKey' in str(key):
            return self._project
        return None


class _Wf:
    """A visibility row: id + status name (+ optional project SA / start_time)."""

    def __init__(self, tid, status_name, project=''):
        self.id = tid
        self.status = _Status(status_name)
        self.typed_search_attributes = _SA(project)
        self.run_id = 'run-' + tid
        # the board row gate reads wf.task_queue (production-queue discipline):
        # the fixture rows must look like real ticket executions on the shared queue
        self.task_queue = client_mod.TASK_QUEUE

    class _Ts:  # datetime-like
        def __init__(self, ts):
            self._ts = ts

        def timestamp(self):
            return self._ts

    start_time = _Ts(1767000000)
    close_time = _Ts(1767000100)


class FakeHandle:
    """Handle stub: describe() reports the configured status; query() returns the
    snapshot dict (the write-gate pre-read face)."""

    def __init__(self, status='RUNNING', snapshot=None):
        self.status_name = status
        self.snapshot = snapshot if snapshot is not None else {
            'meta': {'project': FIXTURE_PROJECT, 'title': 'ki223 fixture ticket'},
            'status': 'closed' if status in
                      ('COMPLETED', 'FAILED', 'TERMINATED', 'CANCELED', 'TIMED_OUT')
                      else 'open',
            'stage_state': 'awaiting',
            'created': 1767000000,
        }

    async def describe(self):
        class _D:
            status = _Status(self.status_name)
            typed_search_attributes = _SA(FIXTURE_PROJECT)
            run_id = 'run-describe'
        return _D()

    async def query(self, name, *a, **kw):
        return dict(self.snapshot)


class FakeClient:
    """Client stub: one handle per workflow id; list_workflows yields the seeded rows
    regardless of the query text (the board face's query shape is pinned by the map
    scenario, not here)."""

    def __init__(self, handles, rows=()):
        self._handles = handles
        self._rows = list(rows)

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, query):
        for r in self._rows:
            yield r


def install_client(handles, rows=()):
    async def _fake_connect():
        return FakeClient(handles, rows)
    client_mod._connect = _fake_connect
    return FakeClient(handles, rows)


_DATA_ROOT = None


def install_data_root():
    """Redirect ticket_data_dir into a fresh tmp dir (repo zero-write; per-scenario
    state isolation). Returns the tmp Path."""
    global _DATA_ROOT
    _DATA_ROOT = Path(tempfile.mkdtemp(prefix='t26100825-data-'))
    old = client_mod.ticket_data_dir

    def _fake_tdd(project_key, ticket_id):
        return _DATA_ROOT / str(project_key or 'unknown') / str(ticket_id)
    _fake_tdd._ki223_real = old  # escape hatch for assertion reuse
    client_mod.ticket_data_dir = _fake_tdd
    return _DATA_ROOT


def manifest_path(ticket_id, project=FIXTURE_PROJECT):
    return _DATA_ROOT / project / ticket_id / 'archive.json'


def cleanup():
    import shutil
    if _DATA_ROOT is not None and _DATA_ROOT.exists():
        shutil.rmtree(_DATA_ROOT, ignore_errors=True)
