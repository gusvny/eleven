# -*- coding: utf-8 -*-
"""t261004-30 -- one-shot executor session settle port (executor_oneshot.py).

Covers: row shape (schema v1 exact key set), the same-gate session declaration
check (seam file + executor-grants declaration; an undeclared session writes
NOTHING), per-field named refusals (op/project/session/ticket/result), the
projects-root precedence (SANDBAR_PROJECTS_DIR > SANDBAR_PANEL_DIR > instance
root), vocabulary drift locks against the watchdog one-shot.ts source, and CLI
malformed input (non-JSON / non-object / unknown op / missing session).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import executor_oneshot as eo  # noqa: E402
import shared  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

VALID_BODY = {
    "op": "settle",
    "project": "proj-alpha",
    "session": "os-e1",
    "ticket": "t-42",
    "result": "Deleted 1 out-of-face file so the lane could proceed.",
}


def _env(tmp: Path, **kw) -> dict:
    env = {"SANDBAR_PROJECTS_DIR": str(tmp)}
    env.update(kw)
    return env


def _seam(tmp: Path, key: str, sessions):
    """Write the one-shot seam declaration <root>/<key>/executor_sessions.json."""
    d = tmp / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "executor_sessions.json").write_text(json.dumps(
        {"sessions": [{"id": s, "kind": "one_shot"} for s in sessions]}), encoding="utf-8")


def _file(tmp, key="proj-alpha"):
    return tmp / key / "ledger" / "executor-settle.jsonl"


# ---------- vocabulary drift lock: ticket/request/alert with the watchdog source ----------

def test_object_key_vocabulary_matches_watchdog_source():
    """The watchdog deriveObjectKey vocabulary (ticket/request/alert prefixes)
    drifting is red -- the settle port names the same objects."""
    src = (REPO / "server/plugins/watchdog/src/host/one-shot.ts").read_text()
    assert re.search(r"ticket.*request.*alert", src), \
        "one-shot.ts must keep the ticket/request/alert object-key vocabulary"
    for kind in ("ticket", "request", "alert"):
        assert f"'{kind}'" in src, kind


# ---------- filing: row shape / append-only ----------

def test_settle_appends_v1_row(tmp_path):
    _seam(tmp_path, "proj-alpha", ["os-e1"])
    out = eo.append_settle(dict(VALID_BODY), 1000, env=_env(tmp_path))
    assert out["ok"] is True
    row = out["row"]
    assert set(row.keys()) == {"v", "at", "project", "ticket", "session", "result", "surface"}
    assert row["v"] == 1 and row["project"] == "proj-alpha"
    assert row["ticket"] == "t-42" and row["session"] == "os-e1"
    assert row["surface"] == eo.SURFACE_ONESHOT
    lines = _file(tmp_path).read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == row


def test_settle_is_append_only(tmp_path):
    _seam(tmp_path, "proj-alpha", ["os-e1"])
    eo.append_settle(dict(VALID_BODY), 1000, env=_env(tmp_path))
    second = dict(VALID_BODY, ticket="t-43", result="It hit the lock timeout.")
    out = eo.append_settle(second, 2000, env=_env(tmp_path))
    assert out["ok"] is True
    lines = _file(tmp_path).read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["ticket"] == "t-43"


# ---------- same gate: the session must be declared ----------

def test_undeclared_session_refused_writes_nothing(tmp_path):
    out = eo.append_settle(dict(VALID_BODY), 1000, env=_env(tmp_path))
    assert out["ok"] is False and out["field"] == "session"
    assert not _file(tmp_path).exists()


def test_seam_declaration_accepts_named_one_shot(tmp_path):
    _seam(tmp_path, "proj-alpha", ["os-e1"])
    out = eo.append_settle(dict(VALID_BODY), 1000, env=_env(tmp_path))
    assert out["ok"] is True


def test_grants_declaration_also_accepts(tmp_path):
    """A session named in the real executor-grants declaration passes too
    (t261004-31 declared-session seam)."""
    calls = []

    def load_decl(key):
        calls.append(key)
        return {"ok": True, "executor_sessions": ["os-grants"]}

    out = eo.append_settle(dict(VALID_BODY, session="os-grants"), 1000,
                           env=_env(tmp_path), load_decl=load_decl)
    assert out["ok"] is True and calls == ["proj-alpha"]


def test_non_one_shot_kind_in_seam_is_closed(tmp_path):
    """kind != one_shot in the seam declaration does not open the settle face."""
    d = tmp_path / "proj-alpha"
    d.mkdir(parents=True)
    (d / "executor_sessions.json").write_text(json.dumps(
        {"sessions": [{"id": "os-x", "kind": "resident"}]}), encoding="utf-8")
    out = eo.append_settle(dict(VALID_BODY, session="os-x"), 1000, env=_env(tmp_path))
    assert out["ok"] is False and out["field"] == "session"


def test_malformed_seam_file_never_opens(tmp_path):
    d = tmp_path / "proj-alpha"
    d.mkdir(parents=True)
    (d / "executor_sessions.json").write_text("{not json", encoding="utf-8")
    out = eo.append_settle(dict(VALID_BODY), 1000, env=_env(tmp_path))
    assert out["ok"] is False and out["field"] == "session"


# ---------- named refusals (per field) ----------

@pytest.mark.parametrize("bad,field", [
    ({"op": "shout", "project": "proj-alpha"}, "op"),
    ({"op": "settle", "project": "BAD KEY"}, "project"),
    ({"op": "settle", "project": ""}, "project"),
    ({"op": "settle", "project": "proj-alpha", "session": ""}, "session"),
    ({"op": "settle", "project": "proj-alpha", "session": "os-e1", "ticket": ""}, "ticket"),
    ({"op": "settle", "project": "proj-alpha", "session": "os-e1", "ticket": "t", "result": ""}, "result"),
    ({"op": "settle", "project": "proj-alpha", "session": "os-e1", "ticket": "t", "result": "x" * 301}, "result"),
    ({"op": "settle", "project": "proj-alpha", "session": "os-e1", "ticket": "x" * 121, "result": "r"}, "ticket"),
])
def test_contract_refusals_name_the_field(tmp_path, bad, field):
    _seam(tmp_path, "proj-alpha", ["os-e1"])
    out = eo.append_settle(bad, 1000, env=_env(tmp_path))
    assert out["ok"] is False and out["field"] == field
    assert not _file(tmp_path).exists()


# ---------- projects root precedence ----------

def test_projects_root_precedence(tmp_path):
    panel = tmp_path / "panel"
    assert eo.projects_root({"SANDBAR_PROJECTS_DIR": str(tmp_path), "SANDBAR_PANEL_DIR": str(panel)}) == tmp_path
    assert eo.projects_root({"SANDBAR_PANEL_DIR": str(panel)}) == panel
    assert eo.projects_root({"HOME": "/h", "DSH_HOME": "/h/.dsh"}) == Path("/h/.sandbar/projects")
    assert eo.projects_root({"HOME": "/h", "DSH_HOME": "/other"}) == Path("/other/sandbar/projects")
    assert eo.settle_file("k", env={"SANDBAR_PROJECTS_DIR": str(tmp_path)}) == \
        tmp_path / "k" / "ledger" / "executor-settle.jsonl"


# ---------- CLI malformed input (external argv consumer: malformed cases via stub) ----------

def _cli(args):
    import os
    return subprocess.run(
        [sys.executable, str(REPO / "server/engine/executor_oneshot.py"), *args],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "SANDBAR_PROJECTS_DIR": "/tmp/oneshot-cli-tmp",
             "PYTHONPATH": str(REPO / "server/engine")})


def test_cli_rejects_non_json():
    r = _cli(["not json"])
    assert r.returncode == 2 and json.loads(r.stdout)["field"] == "body"


def test_cli_rejects_non_object():
    r = _cli(["[1,2]"])
    assert r.returncode == 2 and json.loads(r.stdout)["field"] == "body"


def test_cli_usage_on_help():
    r = _cli([])
    assert r.returncode == 2 and "usage" in json.loads(r.stdout)["error"]
