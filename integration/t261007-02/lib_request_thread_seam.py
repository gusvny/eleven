#!/usr/bin/env python3
"""lib_request_thread_seam — shared fixture/CLI helper for the t261007-02 scenarios.

Grey-box seam (binding kept shallow): the thread machine is driven through the
engine CLI entry `server/engine/request_thread.py` (one JSON argv, receipt or
refusal printed on stdout, per plan v2), and the ground truth is always read
back from the ledger FILE the panel reads — <projects_root>/<key>/requests.jsonl
(reader-side evidence, KI-195 discipline: a writer receipt alone is not proof).

Identity seams (all env-injected, zero real ~/.sandbar):
  - projects root  : SANDBAR_PROJECTS_DIR / SANDBAR_PANEL_DIR -> a temp dir
  - executor reg   : <root>/<key>/executor-grants.json {"executor_sessions":[...]}
  - project reg    : <root>/<key>/sessions.json {"version":1,"sessions":[{"session_id":...}]}
  - epic register  : SANDBAR_EPICS_DIR -> <dir>/<code>.md files
  - lane agent     : SANDBAR_CALLER_SURFACE=lane-agent (engine-injected channel)

Stdlib only; the temp tree is reclaimed by TemporaryDirectory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "server/engine/request_thread.py"
EPICS = ("localization", "executor-reliability")

# Identities used across the scenarios.
EXEC_SESSION = "session-exec-t26100702"
PROJ_SESSION = "session-proj-t26100702"
KEY = "t26100702fixture"


def base_env(root: str) -> dict:
    env = dict(os.environ)
    # The engine spawn chain injects a lane identity; the scenario drives its own.
    for k in ("DSH_SESSION_ID", "DSH_HEADLESS_SESSION",
              "SANDBAR_CALLER_SURFACE", "SANDBAR_CALLER_PROJECT",
              "SANDBAR_CALLER_IDENTITY_SRC"):
        env.pop(k, None)
    env["HOME"] = root
    env["DSH_HOME"] = str(Path(root) / "dsh-home")
    env["SANDBAR_PANEL_DIR"] = root
    env["SANDBAR_PROJECTS_DIR"] = root
    env["SANDBAR_EPICS_DIR"] = str(Path(root) / "epics")
    return env


@contextmanager
def make_world(caller_role: str = "executor"):
    """Context manager: create the iso project + registers; yields (root, env).

    caller_role: "executor" (named in executor_sessions) | "project"
    (named in sessions.json) | "lane" (engine-injected lane channel) |
    "unknown" (no register names the session — must be refused).
    """
    tmp = tempfile.TemporaryDirectory(prefix="sc-t26100702-")
    root = str(Path(tmp.name) / "projects")
    d = Path(root) / KEY
    d.mkdir(parents=True)
    epics = Path(root) / "epics"
    epics.mkdir(parents=True)
    for code in EPICS:
        (epics / (code + ".md")).write_text("# epic %s\nfixture register entry\n" % code, "utf-8")
    env = base_env(root)
    env["SANDBAR_CALLER_PROJECT"] = KEY
    if caller_role == "executor":
        (d / "executor-grants.json").write_text(json.dumps(
            {"version": 1, "grants": {}, "executor_sessions": [EXEC_SESSION]}), "utf-8")
        env["DSH_SESSION_ID"] = EXEC_SESSION
    elif caller_role == "project":
        (d / "executor-grants.json").write_text(
            json.dumps({"version": 1, "grants": {}, "executor_sessions": []}), "utf-8")
        (d / "sessions.json").write_text(json.dumps(
            # the register's writer schema (workbench serializeSessionLedgerFile):
            # {"version": 1, "sessions": [{session_id, ...}]}
            {"version": 1, "sessions": [{"session_id": PROJ_SESSION, "title": "proj session"}]}), "utf-8")
        env["DSH_SESSION_ID"] = PROJ_SESSION
    elif caller_role == "lane":
        (d / "executor-grants.json").write_text(
            json.dumps({"version": 1, "grants": {}, "executor_sessions": []}), "utf-8")
        # The lane class rides the engine-injected channel AND carries its own
        # injected session id (the identity chain, not a self-report).
        env["SANDBAR_CALLER_SURFACE"] = "lane-agent"
        env["DSH_SESSION_ID"] = "session-lane-agent-t26100702"
    else:  # unknown: nobody names this session
        (d / "executor-grants.json").write_text(
            json.dumps({"version": 1, "grants": {}, "executor_sessions": []}), "utf-8")
        env["DSH_SESSION_ID"] = "session-nobody-knows-me"
    yield root, env


def run_op(op: str, body: dict, env: dict, cwd=None):
    """One thread op through the engine CLI; returns the parsed receipt."""
    doc = dict(body, op=op)
    if op == "file" and "default_action" not in body:
        # The head inherits today's request contract: a head with no options
        # must still state what happens if the host does not answer.
        doc["default_action"] = "answer in the panel"
    argv = json.dumps(doc)
    proc = subprocess.run(
        [sys.executable, str(CLI), argv],
        capture_output=True, text=True,
        env=env, cwd=str(cwd or ROOT), timeout=60)
    text = (proc.stdout or "").strip()
    try:
        doc = json.loads(text.splitlines()[-1]) if text else {}
    except Exception:
        doc = {}
    return proc.returncode, doc, (proc.stderr or "")


def ledger_rows(root: str, key: str = KEY):
    p = Path(root) / key / "requests.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_torn": line[:80]})
    return rows


def seed_rows(root: str, rows, key: str = KEY):
    p = Path(root) / key / "requests.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def heads(rows):
    return [r for r in rows if r.get("type") == "request"]


def named(doc: dict, text: str, field: str) -> bool:
    """The refusal names the failed field (structured `field` key or in the
    human-facing error). Tolerant to both landed shapes."""
    if not isinstance(doc, dict) or doc.get("ok") is not False:
        return False
    return str(doc.get("field", "")) == field or field in json.dumps(doc) or field in text


def open_world(caller_role: str = "executor"):
    """Non-context-manager twin of make_world for try/finally bodies:
    returns (root, env, cleanup)."""
    cm = make_world(caller_role)
    root, env = cm.__enter__()
    return root, env, cm.__exit__


def seed_world(root: str, caller_role: str = "executor"):
    """Registers only (no TemporaryDirectory): turn an EXISTING root dir into a
    world of the given role; returns env. For scenarios that juggle several
    roles over one tree."""
    import shutil
    d = Path(root) / KEY
    d.mkdir(parents=True, exist_ok=True)
    epics = Path(root) / "epics"
    epics.mkdir(parents=True, exist_ok=True)
    for code in EPICS:
        (epics / (code + ".md")).write_text("# epic %s\nfixture register entry\n" % code, "utf-8")
    env = base_env(root)
    env["SANDBAR_CALLER_PROJECT"] = KEY
    decl = {"version": 1, "grants": {}, "executor_sessions": []}
    if caller_role == "executor":
        decl["executor_sessions"] = [EXEC_SESSION]
        env["DSH_SESSION_ID"] = EXEC_SESSION
    elif caller_role == "project":
        (d / "sessions.json").write_text(json.dumps(
            # the register's writer schema (workbench serializeSessionLedgerFile):
            # {"version": 1, "sessions": [{session_id, ...}]}
            {"version": 1, "sessions": [{"session_id": PROJ_SESSION, "title": "proj session"}]}), "utf-8")
        env["DSH_SESSION_ID"] = PROJ_SESSION
    elif caller_role == "lane":
        env["SANDBAR_CALLER_SURFACE"] = "lane-agent"
        env["DSH_SESSION_ID"] = "session-lane-agent-t26100702"
    else:
        env["DSH_SESSION_ID"] = "session-nobody-knows-me"
    (d / "executor-grants.json").write_text(json.dumps(decl), "utf-8")
    return env
