# -*- coding: utf-8 -*-
"""executor_oneshot -- settle-note filing port for one-shot executor sessions
(ticket t261004-30).

What: after a watchdog-created ONE-SHOT executor session finishes one bounded
unit, this is the engine-side port that lands its result. The ledger-side two
of the three output faces (action ledger + request ledger) are carried by the
existing mechanisms (the session passes the SAME executor grant gate --
executor_grants.is_executor_channel; no new identity face). This module adds
the third: the settle note, appended to
`<projects_root>/<project>/ledger/executor-settle.jsonl` -- the result stays
visible after the session exits.

CLI (same shape as the other engine entries: one JSON argv):
    python3 server/engine/executor_oneshot.py '<json>'
  body: {op:"settle", project:<key>, session:<one-shot session id>,
         ticket:<ticket id>, result:<one-page takeaway>}
  stdout: one JSON receipt; ok=true carries row, a refusal carries
  field (the failing field name) + error. Exit code: 0=filed, 2=refused
  (including non-JSON / non-object argv -- field=body).

Identity (no anonymous filing, same gate semantics as the resident session):
the caller names its project and session; the session id must be DECLARED as
an executor session of that project -- read from either
  (a) the project declaration `<root>/<project>/executor_sessions.json`
      {"sessions": [{"id": ..., "kind": "one_shot"}]} -- the one-shot seam
      declaration; or
  (b) the project's executor-grants declaration (executor_grants.load_declaration,
      t261004-31 declared-session seam, the same file the resident executor is
      named in).
An undeclared session id is refused (field=session) and writes NOTHING.

Row schema v1 (exactly these keys):
  {v, at, project, ticket, session, result, surface}
  ticket = the object the bounded unit worked on; result <= 300 chars (the
  one-page takeaway); surface = "engine-oneshot" (readers tolerate unknown
  keys, the marker stays truthful).

Deliberately not done (recorded honestly, see the handover report):
  - executor_actions row schema v1 locks its exact key set behind unit tests;
    this ticket does not widen it. The one-shot marker rides the settle row's
    surface key; the action ledger takes additive `channel_kind` through
    record_executor_action(extra=...) with a whitelist.
  - retention sweep (7 days / summary before delete / referenced never
    deleted) lives watchdog-side in one-shot.ts (it owns the reference faces:
    watchdog config, authorization declarations, unanswered request owner);
    the engine settle ledger is append-only here.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import executor_grants
import executor_requests
import shared

SURFACE_ONESHOT = "engine-oneshot"
RESULT_MAX = 300
TICKET_MAX = 120
SESSION_KIND_ONESHOT = "one_shot"

USAGE = ("usage: python3 server/engine/executor_oneshot.py "
         "'{\"op\":\"settle\",\"project\":\"<key>\",\"session\":...,"
         "\"ticket\":...,\"result\":...}'")


def _refuse(field: str, error: str) -> Dict[str, Any]:
    return {"ok": False, "field": field, "error": error}


def projects_root(env: Optional[Dict[str, str]] = None) -> Path:
    """Projects root for the settle ledger: SANDBAR_PROJECTS_DIR (the engine
    projects-root truth) > SANDBAR_PANEL_DIR (panel seam) > the instance
    projects root (executor_requests.instance_projects_root, DSH_HOME aware --
    never falls back through $HOME into another instance's tree)."""
    env = dict(os.environ if env is None else env)
    direct = str(env.get("SANDBAR_PROJECTS_DIR") or "")
    if direct:
        return Path(direct)
    panel = str(env.get("SANDBAR_PANEL_DIR") or "")
    if panel:
        return Path(panel)
    return Path(executor_requests.instance_projects_root(env))


def settle_file(key: str, env: Optional[Dict[str, str]] = None) -> Path:
    """Settle ledger path: <projects_root>/<key>/ledger/executor-settle.jsonl."""
    return projects_root(env) / str(key) / "ledger" / "executor-settle.jsonl"


def _one_shot_seam_sessions(root: Path, key: str) -> List[str]:
    """One-shot seam declaration `<root>/<key>/executor_sessions.json`:
    {"sessions": [{"id": ..., "kind": "one_shot"}]}. Absent/malformed = empty
    (the seam stays closed; a broken fixture never escalates) -- same posture
    as executor_requests' declared-session anchor."""
    f = root / key / "executor_sessions.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- absent/unreadable/malformed all = closed seam
        return []
    out: List[str] = []
    for s in (doc or {}).get("sessions") or []:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
            kind = s.get("kind")
            if kind is None or kind == SESSION_KIND_ONESHOT:
                out.append(s["id"])
    return out


def session_declared(key: str, session: str,
                     env: Optional[Dict[str, str]] = None,
                     load_decl: Optional[Any] = None) -> bool:
    """The SAME-gate check: the session id must be named as an executor session
    of this project (seam declaration or the real executor-grants declaration)."""
    env = dict(os.environ if env is None else env)
    for sid in _one_shot_seam_sessions(projects_root(env), key):
        if sid == session:
            return True
    load = (load_decl or executor_grants.load_declaration)(key)
    if load.get("ok") and session in tuple(load.get("executor_sessions") or ()):
        return True
    return False


def validate_settle(body: Dict[str, Any]) -> Dict[str, Any]:
    """Settle row contract. Returns {"ok": True, "fields": {...}} or a refusal
    naming the failing field."""
    if body.get("op") != "settle":
        return _refuse("op", "op must be \"settle\" (got %r)" % (str(body.get("op"))[:40],))
    key = body.get("project")
    if not isinstance(key, str) or not shared.PROJECT_KEY_RE.match(key or ""):
        return _refuse("project", "project must be a valid project key (got %r)" % (str(key)[:60],))
    session = body.get("session")
    if not isinstance(session, str) or session.strip() == "":
        return _refuse("session", "session must be a non-empty string session id "
                                  "(the one-shot session that did the unit)")
    ticket = body.get("ticket")
    if not isinstance(ticket, str) or ticket.strip() == "" or len(ticket) > TICKET_MAX:
        return _refuse("ticket", "ticket must be a non-empty string of at most %d chars" % TICKET_MAX)
    result = body.get("result")
    if not isinstance(result, str) or result.strip() == "":
        return _refuse("result", "result must be a non-empty string (the one-page takeaway)")
    if len(result) > RESULT_MAX:
        return _refuse("result", "result too long (%d > %d chars) -- keep it to one page"
                       % (len(result), RESULT_MAX))
    return {"ok": True, "fields": {"project": key, "session": session,
                                   "ticket": ticket, "result": result}}


def append_settle(body: Dict[str, Any], now_ms: int,
                  env: Optional[Dict[str, str]] = None,
                  load_decl: Optional[Any] = None) -> Dict[str, Any]:
    """Engine-side settle filing: contract validation + the same-gate session
    declaration check + one O_APPEND line. Returns a receipt (with row) or a
    refusal (with field). A refusal writes NOTHING (no half-rows)."""
    env = dict(os.environ if env is None else env)
    body = executor_requests._sanitize(body)
    checked = validate_settle(body)
    if not checked.get("ok"):
        return checked
    fields = checked["fields"]
    key, session = fields["project"], fields["session"]
    if not session_declared(key, session, env=env, load_decl=load_decl):
        return _refuse("session",
                       "session %r is not declared as an executor session of project %s "
                       "(executor_sessions.json seam or %s) -- one-shot settle passes the "
                       "same declaration gate as the resident session"
                       % (session[:64], key, executor_grants.DECL_FILE))
    row: Dict[str, Any] = {
        "v": 1,
        "at": now_ms,
        "project": key,
        "ticket": fields["ticket"],
        "session": session,
        "result": fields["result"],
        "surface": SURFACE_ONESHOT,
    }
    path = settle_file(key, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return {"ok": True, "row": row, "file": str(path)}


def _emit(out: Dict[str, Any]) -> None:
    # Receipt exit guard (same as executor_requests): undecodable characters go
    # out as visible \\udcXX escapes; a crashed print never eats the receipt.
    print((json.dumps(out, ensure_ascii=False)
           .encode("utf-8", "backslashreplace").decode("utf-8")))


def _cli(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        _emit({"ok": False, "field": "body", "error": USAGE})
        return 2
    try:
        doc = json.loads(argv[0])
    except json.JSONDecodeError as e:
        _emit({"ok": False, "field": "body", "error": "argument is not valid JSON: %s" % e})
        return 2
    if not isinstance(doc, dict):
        _emit({"ok": False, "field": "body",
               "error": "argument must be a JSON object (got %s)" % type(doc).__name__})
        return 2
    now_ms = int(time.time() * 1000)
    out = append_settle(doc, now_ms)
    _emit(out)
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
