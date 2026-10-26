"""t261026-06 -- the request sweep's ticket reader is reachable again, and a
dead reader is LOUD.

Defect (host-reported, measured 261026): default_ticket_status_fn built its
command from <repo_root>/server/tools/admin.py, a path that does not exist in
this repository (the entry point is <repo_root>/server/admin.py, shared.ADMIN_PY).
Every ticket_closed head therefore skipped with ticket_reader_unavailable and
the receipt still said ok:true -- 0 resolved, 65 skipped, silently.

Coverage:
- the reader path resolves through shared.ADMIN_PY (the engine-wide entry),
  and the stale server/tools/admin.py path is gone (no shadow fallback);
- (a) fixture repo: a stub server/admin.py answering a canned ticket-list
  receipt -- one head whose ticket_closed condition names a CLOSED ticket
  RESOLVES, with the projection source named in the evidence;
- (b) reader entry missing: the receipt's top-level `reader` block NAMES the
  missing path, ok stays true (a skip is a named outcome, pinned), and the
  per-head skip reason keeps its stable `ticket_reader_unavailable:<ticket>`
  format;
- runtime reader failures are named at receipt level too: non-zero exit,
  garbage stdout, and receipt-level ok:false (a refusal is an unavailable
  channel, NOT an honestly empty ticket list);
- an injected ticket_status_fn bypasses the reader block entirely.

All fixtures are local stubs; no real ticket channel, no ~/.sandbar.
"""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sweep as rs  # noqa: E402
import request_thread as rt  # noqa: E402

NOW = 1730000000000
SEQ = 3


class _StubShared:
    """Stand-in for the shared module's path surface (ADMIN_PY / REPO_ROOT)."""

    def __init__(self, admin_py, repo_root):
        self.ADMIN_PY = admin_py
        self.REPO_ROOT = repo_root


@pytest.fixture(autouse=True)
def _reset_reader_error():
    rs._READER_LAST_ERROR = None
    yield
    rs._READER_LAST_ERROR = None


def write_ledger(tmp_path, key, rows):
    path = tmp_path / key / "requests.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def head(hid, ticket):
    return {"type": "request", "id": hid, "at": NOW, "subject": "s-" + hid,
            "epic": "none", "epic_reason": "fixture",
            "resolves_when": {"kind": "ticket_closed", "ticket": ticket}}


STUB_TICKETS = [{"id": "t261025-13", "status": "closed"},
                {"id": "t261026-99", "status": "running"}]


def make_stub_admin(tmp_path, *, exit_code=0, stdout=None, ok=True):
    """A stub server/admin.py that prints a canned ticket-list receipt."""
    if stdout is None:
        stdout = json.dumps({"ok": ok, "run_id": "run-stub",
                             "result": {"tickets": STUB_TICKETS}}) + "\n"
    script = tmp_path / "repo" / "server" / "admin.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "import sys\n"
        "sys.stdout.write(%r)\n"
        "sys.exit(%d)\n" % (stdout, exit_code)
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def stub_reader(tmp_path, monkeypatch):
    """Fixture repo: stub admin entry + monkeypatched shared_module."""
    script = make_stub_admin(tmp_path)
    repo_root = str(tmp_path / "repo")
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(str(script), repo_root))
    return {"admin_py": str(script), "repo_root": repo_root}


# ---------- (a) a working reader resolves a closed ticket ---------------------

def test_reader_path_resolves_through_admin_py(stub_reader):
    assert rs.ticket_reader_path() == stub_reader["admin_py"]


def test_closed_ticket_reads_true_with_named_source(stub_reader):
    read = rs.default_ticket_status_fn("t261025-13")
    assert read == ("closed", "ticket-list-projection")


def test_open_ticket_reads_false_not_skip(stub_reader):
    # an honest False with the same named source -- not an unavailable channel
    assert rs.default_ticket_status_fn("t261026-99") == \
        ("running", "ticket-list-projection")


def test_sweep_resolves_ticket_closed_head_end_to_end(stub_reader, tmp_path):
    write_ledger(tmp_path, "p1", [head("h1", "t261025-13"),
                                  head("h2", "t261026-99")])
    receipt = rs.sweep_project("p1", NOW, SEQ, env={"SANDBAR_PANEL_DIR":
                                                    str(tmp_path)})
    assert [r["id"] for r in receipt["resolved"]] == ["h1"]
    resolved = receipt["resolved"][0]
    # the source is named in the evidence, checkable from the receipt alone
    assert "ticket-list-projection" in resolved["evidence"]
    assert "t261025-13" in resolved["evidence"]
    assert receipt["unchanged"] == 1  # the open ticket: honest False
    assert receipt["reader"] == {"available": True,
                                 "path": stub_reader["admin_py"],
                                 "error": ""}


# ---------- (b) a missing reader entry is LOUD --------------------------------

def test_missing_reader_entry_names_the_path(tmp_path, monkeypatch):
    missing = str(tmp_path / "repo" / "server" / "admin.py")
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(missing, str(tmp_path / "repo")))
    write_ledger(tmp_path, "p1", [head("h1", "t261025-13"),
                                  head("h2", "t261025-13")])
    receipt = rs.sweep_project("p1", NOW, SEQ, env={"SANDBAR_PANEL_DIR":
                                                    str(tmp_path)})
    reader = receipt["reader"]
    assert reader["available"] is False
    assert reader["path"] == missing            # the MISSING path, named
    assert "reader_entry_missing" in reader["error"]
    # ok stays true: a skip is a named outcome, not a failure (pinned decision)
    assert receipt["ok"] is True
    # per-head skip format is STABLE (vocabulary unchanged; review comment 1)
    assert [s["reason"] for s in receipt["skipped"]] == \
        ["ticket_reader_unavailable:t261025-13", "ticket_reader_unavailable:t261025-13"]
    assert receipt["resolved"] == []


def test_stale_tools_path_is_not_a_fallback(tmp_path, monkeypatch):
    # the path that caused the defect must NOT come back as a shadow branch
    repo = tmp_path / "repo"
    stale = repo / "server" / "tools" / "admin.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("# a stale admin.py sits here\n", encoding="utf-8")
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(None, str(repo)))
    assert rs.ticket_reader_path() == ""
    probe = rs.ticket_reader_probe()
    assert probe["available"] is False and "reader_entry_missing" in probe["error"]


def test_probe_without_sweep_names_missing_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared("", ""))
    probe = rs.ticket_reader_probe()
    assert probe == {"available": False, "path": "",
                     "error": "reader_entry_missing:"}


# ---------- (c) runtime reader failures are named, never fabricated -----------

def _sweep_with_stub(tmp_path, **stub_kwargs):
    # the caller monkeypatches rs.shared_module; this only mints the stub file
    return make_stub_admin(tmp_path, **stub_kwargs)


def test_nonzero_exit_is_a_named_unavailable_channel(tmp_path, monkeypatch):
    script = _sweep_with_stub(tmp_path, exit_code=3)
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(str(script), str(tmp_path / "repo")))
    assert rs.default_ticket_status_fn("t261025-13") is None
    err = rs._READER_LAST_ERROR
    assert err is not None and "reader_exit_3" in err and str(script) in err


def test_garbage_stdout_is_unparseable_not_empty(tmp_path, monkeypatch):
    script = _sweep_with_stub(tmp_path, stdout="not json at all\n")
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(str(script), str(tmp_path / "repo")))
    assert rs.default_ticket_status_fn("t261025-13") is None
    assert "reader_output_unparseable" in (rs._READER_LAST_ERROR or "")


def test_receipt_level_refusal_is_not_an_empty_list(tmp_path, monkeypatch):
    # review comment 2: exit 0 + ok:false receipt (unknown project shape) is
    # an unavailable channel, NOT an honestly empty ticket list -- a closed
    # ticket behind this shape must NEVER resolve
    stdout = json.dumps({"ok": False, "error": "unknown project"}) + "\n"
    script = _sweep_with_stub(tmp_path, stdout=stdout)
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(str(script), str(tmp_path / "repo")))
    assert rs.default_ticket_status_fn("t261025-13") is None
    assert "reader_refused" in (rs._READER_LAST_ERROR or "")
    write_ledger(tmp_path, "p1", [head("h1", "t261025-13")])
    receipt = rs.sweep_project("p1", NOW, SEQ, env={"SANDBAR_PANEL_DIR":
                                                    str(tmp_path)})
    assert receipt["resolved"] == []
    assert receipt["reader"]["available"] is False
    assert "reader_refused" in receipt["reader"]["error"]


def test_unavailable_shape_resolves_nothing_and_names_reason(tmp_path,
                                                             monkeypatch):
    script = _sweep_with_stub(tmp_path, exit_code=1)
    monkeypatch.setattr(rs, "shared_module",
                        lambda: _StubShared(str(script), str(tmp_path / "repo")))
    write_ledger(tmp_path, "p1", [head("h1", "t261025-13")])
    receipt = rs.sweep_project("p1", NOW, SEQ, env={"SANDBAR_PANEL_DIR":
                                                    str(tmp_path)})
    assert receipt["resolved"] == []
    assert receipt["unchanged"] == 0          # unavailable != an honest False
    assert receipt["skipped"][0]["reason"] == "ticket_reader_unavailable:t261025-13"
    assert receipt["reader"]["available"] is False
    assert "reader_exit_1" in receipt["reader"]["error"]


# ---------- injected fn: the reader block is not for you -----------------------

def test_injected_status_fn_gets_no_reader_block(tmp_path):
    write_ledger(tmp_path, "p1", [head("h1", "t261025-13")])
    receipt = rs.sweep_project("p1", NOW, SEQ,
                               env={"SANDBAR_PANEL_DIR": str(tmp_path)},
                               ticket_status_fn=lambda t: ("closed", "stub"))
    assert receipt["resolved"] and "reader" not in receipt
