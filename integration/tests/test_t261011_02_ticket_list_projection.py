# -*- coding: utf-8 -*-
"""t261011-02 L1: the CLI list row says what the engine row says.

The engine row face (server/engine/client.py `_row_from_meta` + its minimal
closed-row and degraded variants) is the single source. `ticket.py _list` is a
thin-shell projection: every key the engine sends must survive, nothing may be
recomputed, and an absent key stays honestly absent/empty. The predecessor bug:
two fixed-key whitelist rebuilds gutted paused/paused_phase/exec_status/
close_health/close_health_reason/lane_version/develop_line, so `ticket list`
reported every ticket as legacy.

Pure projection tests — no Temporal, no console, no docker. `_poc` is the
declared three-arg stub seam (ticket.py contract, t260922-10) and is
monkeypatched to return canned engine-row envelopes.
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(REPO, "server", "tools")
sys.path.insert(0, TOOLS)
import ticket  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "t26101102_engine_rows", os.path.join(REPO, "server", "engine", "client.py"))


# ---- canned engine rows: one per shape the engine row face emits ----

def _live_row():
    # shape 1: _row_from_meta live row (+ close_ts added by the caller)
    return {
        "id": "t261009-80", "project": "sandbar", "epic": "",
        "role": "developer", "status": "running", "title": "opt-in ticket",
        "workflow": "wf-80", "proposal_id": "",
        "stage": "implement", "stage_state": "running",
        "paused": False, "paused_phase": "",
        "handoff_count": 2, "pending_count": 0,
        "worktree": ".lane/t261009-80", "workspace": "ws",
        "lane_version": "develop-buffer-v1", "develop_line": "develop-buffer",
        "created": "10-11 02:00", "updated": "10-11 02:20", "updated_ts": 1760145600,
        "engine": "engine_v2", "exec_status": "RUNNING",
        "close_health": "", "close_health_reason": "",
        "authz_active": 1, "close_ts": 0,
    }


def _paused_row():
    row = _live_row()
    row.update({"id": "t260908-01", "workflow": "wf-paused",
                "status": "running", "stage_state": "running",
                "stage": "implement", "lane_version": "", "develop_line": "",
                "paused": True, "paused_phase": "at_gate", "authz_active": 0})
    return row


def _minimal_closed_row():
    # shape 2: no-snapshot minimal closed row — shares the key family minus
    # paused/paused_phase; absent keys must read honestly empty, never KeyError
    return {
        "id": "t260901-01", "project": "sandbar", "epic": "", "role": None,
        "status": "closed", "title": "", "workflow": "", "proposal_id": "",
        "stage": None, "stage_state": "awaiting",
        "handoff_count": 0, "pending_count": 0, "worktree": "",
        "lane_version": "", "develop_line": "",
        "workspace": None, "created": None, "updated": "10-11 03:00",
        "updated_ts": 1760149200, "close_ts": 1760149200,
        "engine": "engine_v2", "exec_status": "COMPLETED",
        "close_health": "ok", "close_health_reason": "", "authz_active": 0,
    }


def _old_engine_row():
    # shape 3: an older engine that does not know the newer keys at all
    return {"id": "t260801-01", "project": "sandbar", "role": "developer",
            "status": "running", "title": "old", "workflow": "wf-old",
            "stage": "create", "stage_state": "awaiting",
            "handoff_count": 0, "pending_count": 0}


def _env(*rows):
    return {"ok": True, "result": {"tickets": list(rows)}}


@pytest.fixture()
def list_rows(monkeypatch):
    """Stub the _poc seam; returns a recorder of the calls it saw."""
    calls = []

    def _install(rows, ok=True):
        def fake_poc(subcmd, payload, caller=None):
            calls.append({"subcmd": subcmd, "payload": dict(payload)})
            if not ok:
                return {"ok": False, "error": "temporal unreachable"}
            return _env(*rows)
        monkeypatch.setattr(ticket, "_poc", fake_poc)

    _install.calls = calls
    return _install


# ---- 1. the named bug: lane opt-in keys survive the projection ----

def test_develop_buffer_row_lands_on_cli_face(list_rows):
    list_rows([_live_row()])
    out = ticket._list({"project": "sandbar"})
    row = out["tickets"][0]
    assert row["lane_version"] == "develop-buffer-v1"
    assert row["develop_line"] == "develop-buffer"


def test_paused_row_lands_on_cli_face(list_rows):
    list_rows([_paused_row()])
    row = ticket._list({})["tickets"][0]
    assert row["paused"] is True
    assert row["paused_phase"] == "at_gate"


# ---- 2. seam closure: per-row key-set parity (against THAT row's own keys,
#      so a shape with close_ts but no paused does not false-red) ----

@pytest.mark.parametrize("shape", [_live_row, _paused_row,
                                   _minimal_closed_row, _old_engine_row])
def test_every_engine_key_is_carried(list_rows, shape):
    src = shape()
    list_rows([src])
    row = ticket._list({})["tickets"][0]
    missing = [k for k in src if k not in row]
    assert not missing, "projection dropped engine keys: %r" % missing
    for k, v in src.items():
        assert row[k] == v, "engine key %r recomputed/renamed: engine=%r cli=%r" % (k, v, row[k])


def test_emitted_key_set_is_stable_superset(list_rows):
    # review conditional 1: additive-only output contract — the emitted key set
    # equals {pre-existing CLI keys} ∪ {previously dropped keys}. No silent
    # renames (e.g. workflow stays `workflow`, never `workflow_id`).
    list_rows([_live_row()])
    row = ticket._list({})["tickets"][0]
    existing = {"id", "project", "epic", "role", "status", "title", "workflow",
                "proposal_id", "stage", "stage_state", "engine", "handoff_count",
                "pending_count", "worktree", "workspace", "created", "updated",
                "updated_ts", "close_ts", "authz_active", "lane_version",
                "develop_line"}
    dropped = {"paused", "paused_phase", "exec_status", "close_health",
               "close_health_reason"}
    assert set(row) == existing | dropped
    assert "workflow_id" not in row


def test_nothing_recomputed_updated_faces(list_rows):
    # the engine formats `updated` at its own read point; the projection must
    # pass it through, not re-derive from updated_ts (which would re-read the
    # CLI wall clock and could disagree with the engine face by a tick).
    src = _live_row()
    src["updated"] = "12-31 23:59"
    src["updated_ts"] = 1
    list_rows([src])
    row = ticket._list({})["tickets"][0]
    assert row["updated"] == "12-31 23:59"
    assert row["updated_ts"] == 1


# ---- 3. honesty: absent / old / malformed rows stay honestly empty ----

def test_old_engine_row_reads_honestly_empty(list_rows):
    list_rows([_old_engine_row()])
    row = ticket._list({})["tickets"][0]
    assert row["lane_version"] == "" and row["develop_line"] == ""
    assert row["paused"] is False and row["paused_phase"] == ""
    assert row["exec_status"] == "" and row["close_health"] == ""
    assert row["stage_state"] == "awaiting"


@pytest.mark.parametrize("bad,want_authz", [
    ("not-a-dict", 0),       # row is a bare string
    (42, 0),                 # row is a number
    (None, 0),               # row is None
    ({"handoff_count": "two", "pending_count": None, "authz_active": "3"}, 3),
    ({"id": None, "updated_ts": "nope", "close_ts": []}, 0),
])
def test_malformed_rows_do_not_crash_the_list(list_rows, bad, want_authz):
    list_rows([_live_row(), bad])
    out = ticket._list({})
    assert out["count"] == 2
    row = out["tickets"][1]
    assert row["handoff_count"] == 0 and row["pending_count"] == 0
    # a NUMERIC string coerces to its value; a non-numeric one lands on 0
    assert row["authz_active"] == want_authz and row["updated_ts"] == 0


# ---- 4. filters still bite on the projected row ----

def test_filters_run_on_the_projected_row(list_rows):
    list_rows([_live_row(), _paused_row()])
    out = ticket._list({"status": "running", "stage_state": "running"})
    assert out["count"] == 2
    out = ticket._list({"workflow": "wf-paused"})
    assert [r["id"] for r in out["tickets"]] == ["t260908-01"]
    out = ticket._list({"stage_state": "awaiting"})
    assert out["count"] == 0


# ---- 5. the error path stays loud (review conditional 3) ----

def test_engine_failure_raises_not_silent_empty(list_rows):
    list_rows([], ok=False)
    with pytest.raises(ValueError):
        ticket._list({})
