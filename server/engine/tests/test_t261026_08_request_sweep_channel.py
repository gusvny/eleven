"""t261026-08 -- the default_ticket_status_fn channel (request_sweep.py).

The sweep's `ticket_closed` reader was dead: it built the admin entry point
path as server/tools/admin.py, which does not exist in this repo (the tool
lives at server/admin.py). The function therefore returned None on every
call, and sweep_project -- by its own fail-closed rule -- skipped every
ticket_closed head. These tests keep the channel provable on both sides:

- a ticket known to be closed resolves to ("closed", "ticket-list-projection")
  (spec point 5, adapted: the data/tickets projection was deleted 260823 and
  ticket truth lives in Temporal, so the channel is exercised through the REAL
  default_ticket_status_fn with a stubbed subprocess returning a canned admin
  receipt -- no live Temporal, no live admin.py, still the real code path);
- a ticket id that cannot exist returns ("not-listed", ...) rather than None;
- a channel that truly cannot start (missing admin file, raising subprocess,
  non-zero exit, unparseable stdout) still yields None -- fail-closed stays
  provable;
- the regression itself: the command the function builds points at
  server/admin.py and never server/tools/admin.py;
- malformed input: a non-JSON stdout and a receipt whose tickets row is not a
  list both resolve to None, never a fabricated status.

All fixtures are local (canned strings); zero real ~/.sandbar, zero live
Temporal, zero external sources.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sweep as rs  # noqa: E402

CLOSED_ID = "t261019-44"
GHOST_ID = "t19990101-99"


def admin_receipt(tickets):
    """A canned admin.py `call ticket {"op":"list"}` stdout (gate receipt
    shape: {"ok": true, "result": {"count": N, "tickets": [...]}})."""
    return json.dumps({
        "ok": True,
        "result": {"count": len(tickets), "tickets": tickets},
    }, ensure_ascii=False)


TICKETS = [
    {"id": CLOSED_ID, "status": "closed", "title": "fixture"},
    {"id": "t261026-08", "status": "verified", "title": "fixture 2"},
]


class FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


@pytest.fixture
def live_channel(monkeypatch):
    """Stub subprocess.run to return the canned receipt and record the cmd."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc(stdout=admin_receipt(TICKETS))

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_channel_points_at_server_admin_py(live_channel):
    """The regression: the reader must invoke server/admin.py, never the old
    server/tools/admin.py path that never existed here."""
    assert rs.default_ticket_status_fn(CLOSED_ID) == ("closed",
                                                      "ticket-list-projection")
    assert len(live_channel) == 1
    cmd = live_channel[0]
    assert cmd[0] == sys.executable
    assert cmd[1] == os.path.join(rs.shared_module().REPO_ROOT,
                                  "server", "admin.py")
    assert cmd[2:4] == ["call", "ticket"]
    assert json.loads(cmd[4]) == {"op": "list"}


def test_closed_ticket_resolves(live_channel):
    assert rs.default_ticket_status_fn(CLOSED_ID) == ("closed",
                                                      "ticket-list-projection")


def test_open_ticket_resolves_its_status(live_channel):
    assert rs.default_ticket_status_fn("t261026-08") == (
        "verified", "ticket-list-projection")


def test_unknown_ticket_is_not_listed_not_none(live_channel):
    assert rs.default_ticket_status_fn(GHOST_ID) == (
        "not-listed", "ticket-list-projection")


def test_missing_admin_file_is_none(monkeypatch):
    """The old bug, pinned fail-closed: a missing admin file -> None."""
    monkeypatch.setattr(rs.os.path, "exists", lambda p: False)
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_empty_repo_root_is_none(monkeypatch):
    monkeypatch.setattr(rs, "shared_module", lambda: type(
        "M", (), {"REPO_ROOT": ""}))
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_subprocess_failure_is_none(monkeypatch, live_channel):
    def boom(cmd, **kwargs):
        raise OSError("cannot start")
    monkeypatch.setattr(subprocess, "run", boom)
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_timeout_is_none(monkeypatch, live_channel):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)
    monkeypatch.setattr(subprocess, "run", slow)
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_nonzero_exit_is_none(monkeypatch, live_channel):
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(returncode=3))
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_unparseable_stdout_is_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout="not json at all"))
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_malformed_tickets_row_is_none(monkeypatch):
    """A tickets row that is not a list is an unreadable projection: None."""
    bad = json.dumps({"ok": True, "result": {"tickets": "all-of-them"}})
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout=bad))
    assert rs.default_ticket_status_fn(CLOSED_ID) is None


def test_non_dict_rows_are_skipped_not_fatal(monkeypatch):
    """Junk entries inside an otherwise real list are skipped (existing
    behaviour); a real closed id among them still resolves."""
    mixed = json.dumps({"ok": True,
                        "result": {"tickets": ["x", 17, None,
                                               {"id": CLOSED_ID,
                                                "status": "closed"}]}})
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout=mixed))
    assert rs.default_ticket_status_fn(CLOSED_ID) == ("closed",
                                                      "ticket-list-projection")
    no_dicts = json.dumps({"ok": True,
                           "result": {"tickets": [CLOSED_ID, 17, None]}})
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout=no_dicts))
    assert rs.default_ticket_status_fn(CLOSED_ID) == (
        "not-listed", "ticket-list-projection")


def test_empty_ticket_list_is_not_listed(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout=admin_receipt([])))
    assert rs.default_ticket_status_fn(GHOST_ID) == (
        "not-listed", "ticket-list-projection")


def test_diagnostic_line_plus_receipt_is_parsed(monkeypatch):
    """The multi-object stream shape gate_receipt_parse tolerates: a leading
    diagnostic JSON line must not blind the reader."""
    noisy = ('{"note": "startup"}\n' + admin_receipt(TICKETS) + "\n")
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: FakeProc(stdout=noisy))
    assert rs.default_ticket_status_fn(CLOSED_ID) == ("closed",
                                                      "ticket-list-projection")
