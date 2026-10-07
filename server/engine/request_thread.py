# -*- coding: utf-8 -*-
"""request_thread -- the ledger's thread face: states, links, ownership and the
judged source (t261007-02).

What this is: executor_requests (t261004-23) is the delivery gate that puts one
request in front of the host. This module is the THREAD face over the same
ledger (<ledger_root>/<key>/requests.jsonl, append-only, never rewritten):
row kinds expand to four (request head / reply / state / link), the state
machine has five states (open -> answered -> resolved | dismissed | superseded)
with a fixed setter per state, four link kinds (supersedes / duplicates /
follows_up / blocks), two ownership fields (source_ticket = a fact, may be
empty; epic = a judgement, required, or none plus one reason), and three source
classes where the project is derived from the registers and never self-reported
(design source: the 261004 host-decision note under notes/discussions/ --
the note itself stays Chinese by design; this module's copy follows the
261004 English standard).

Row contract (append-only, one row per fact):
  request head : the executor_requests fields + subject / epic / epic_reason /
                 source_ticket / source_class (new here; legacy rows without
                 these keys are valid history -- readers tolerate them and
                 render the fields empty; classifying those rows waits for the
                 host's word and is NOT invented here).
  reply        : {type:"reply", id, reply_for, at, text, by, intent,
                 source_class, via?, anchor?} -- the delegated-answer split:
                 by (who decided) / via (who filed it) / anchor (the host's
                 words). Shown as separate columns in the panel.
  state        : {type:"state", id, state_for, state, at, by, evidence?, note?}
                 -- every state change is its own row; resolved carries
                 evidence (a ticket id or a commit id).
  link         : {type:"link", id, kind, from?, to, at, by, dup_subject?,
                 dup_epic?, dup_source_ticket?} -- a duplicate re-file (same
                 source ticket + owning epic + subject over an open head) opens
                 NO new head: the engine appends one duplicates link row
                 mechanically. `from` is absent there (the denied filing never
                 became a row; review round 2 comment 1) and the triple
                 snapshot travels on the row; the panel renders it as a one-way
                 link to `to` and never resolves a dangling id.

Who may set which state (fixed, design note trade-off 4):
  answered / dismissed: the host, in the panel (answered = the answer route
              also lands a state row; dismissed = the panel state route; this
              CLI refuses both);
  resolved: the doer, with evidence (this CLI; a project session is refused);
  superseded: the machine -- landed automatically when a newer head links this
              one with supersedes; this CLI refuses a manual set.

Invariant (review round 2 comment 2): the link row lands first, the derived
state row second; each row is its own single append. A crash between them is
repaired at READ time from the supersedes link (recompute superseded) -- that
is display/contract repair of a torn multi-row op, never a license for the
write path to skip the state row (unit test: after a clean link both rows are
physically present). Replies carry no state gate (review round 1 comment 3:
the note gates replies by writer identity only, not by the head's state).

Single writer: the O_APPEND one-line-per-row discipline stays. The
check-then-append critical sections this face introduces (duplicate scan,
terminal-state check) run under an exclusive fcntl.flock on the ledger file --
normal, error and interrupt paths all release through the with block.

CLI (same shape as the other engine entries: one JSON argv):
    python3 server/engine/request_thread.py '<json>'
  op="file"  : file a thread head (executor_requests.resolve_caller three-gate
               + contract validation + this face's field validation + source
               classification + the mechanical duplicate link).
  op="reply" : append a reply (writer rules: executor / lane-agent may answer
               and add facts; a project session may ask and add facts --
               answering is a structured refusal).
  op="state" : append a state row (the engine side only allows resolved;
               evidence required).
  op="link"  : append a link row (supersedes derives the superseded state row).
  Output: one JSON receipt on stdout; ok=true carries row / linked_to; a
  refusal carries field + error. Exit codes: 0 = landed; 2 = refused
  (including a non-JSON / non-object argv -- field=body).

Direct-write closure (t261006-05, KI-208, same as executor_requests): the
resident executor channels (cwd / declared-session) must not append the ledger
in their own process; structured refusal naming the client.py deliver engine
face. The env channel (the scripts/fixtures/ops face) stays open.
"""
from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import executor_requests
import shared

# ---- state machine ----
STATE_OPEN = "open"
STATE_ANSWERED = "answered"
STATE_RESOLVED = "resolved"
STATE_DISMISSED = "dismissed"
STATE_SUPERSEDED = "superseded"
TERMINAL_STATES = (STATE_RESOLVED, STATE_DISMISSED, STATE_SUPERSEDED)
HOST_STATES = (STATE_ANSWERED, STATE_DISMISSED)   # the host, in the panel; this CLI refuses
MACHINE_STATES = (STATE_SUPERSEDED,)              # the machine, with a link; this CLI refuses

# ---- links ----
LINK_SUPERSEDES = "supersedes"
LINK_DUPLICATES = "duplicates"
LINK_FOLLOWS_UP = "follows_up"
LINK_BLOCKS = "blocks"
LINK_KINDS = (LINK_SUPERSEDES, LINK_DUPLICATES, LINK_FOLLOWS_UP, LINK_BLOCKS)

# ---- three source classes (register-derived, never self-reported) ----
SRC_EXECUTOR = "executor-session"
SRC_PROJECT = "project-session"
SRC_LANE = "lane-agent"

# ---- reply intents ----
INTENT_ANSWER = "answer"
INTENT_FACT = "fact"
INTENT_ASK = "ask"
REPLY_INTENTS = (INTENT_ANSWER, INTENT_FACT, INTENT_ASK)
PROJECT_SESSION_INTENTS = (INTENT_FACT, INTENT_ASK)  # a project session may not answer

# ---- field floors (a local bound is marked; the rest are design-note rules) ----
SUBJECT_MAX = 60            # one line; part of the family key
EPIC_REASON_MAX = 200       # local bound of this implementation (the note asks only for "one reason")
REPLY_TEXT_MAX = 500        # local bound; keep the head narrow, prose goes into replies
VIA_MAX = 120               # same floor as raised_by
ANCHOR_MAX = 200            # the host's words
TICKET_ID_RE = re.compile(r"^t\d{6}-\d+$")
COMMIT_ID_RE = re.compile(r"^[0-9a-f]{7,40}$")
EPIC_NONE = "none"

SURFACE_ENGINE = executor_requests.SURFACE_ENGINE
RESIDENT_EXECUTOR_CHANNELS = executor_requests.RESIDENT_EXECUTOR_CHANNELS
DIRECT_WRITE_REFUSAL = executor_requests.DIRECT_WRITE_REFUSAL

USAGE = ("usage: python3 server/engine/request_thread.py "
         "'{\"op\":\"file|reply|state|link\",\"project\":\"<key>\",...}'")


def _refuse(field: str, error: str) -> Dict[str, Any]:
    return {"ok": False, "field": field, "error": error}


# ---------- register readers ----------

def caller_session_of(env: Dict[str, str]) -> str:
    """The injected-chain session id (same order and same env list as
    executor_requests.resolve_caller) -- used only to rebuild the identity on
    the delivery-gate refusal downgrade; never reads a self-reported field."""
    import executor_grants
    for env_name in executor_grants.CALLER_SESSION_ENVS:
        sid = str(env.get(env_name) or "").strip()
        if sid:
            return sid
    return ""


def sessions_register_sessions(key: str, env: Dict[str, str]) -> set:
    """The project-session register reader: the session_id set from
    <ledger_root>/<key>/sessions.json.

    Tolerance discipline (borrowed face, see executor_grants.load_declaration /
    session-ledger-file.ts): a missing file / bad JSON / non-object / dirty
    entries all count as an empty set -- a broken register keeps the seam
    closed (no project-session judgement = structured refusal), never an
    escalation, never a guessed identity."""
    path = executor_requests.ledger_file(str(key), env).parent / "sessions.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        doc = json.loads(raw)
    except ValueError:
        return set()
    if not isinstance(doc, dict):
        return set()
    # Schema mirror of the register's WRITER face (workbench session-handles.ts
    # serializeSessionLedgerFile / parseSessionLedgerFile): {"version": 1,
    # "sessions": [{session_id, ...}]} — wrong version or a non-array sessions
    # field is an empty ledger, exactly like the writer's own parser. (Rework
    # defect 1: the reader invented an `entries` key the writer never writes,
    # which killed the whole project-session source class.)
    if doc.get("version") != 1:
        return set()
    entries = doc.get("sessions")
    if not isinstance(entries, list):
        return set()
    out = set()
    for e in entries:
        if isinstance(e, dict):
            sid = e.get("session_id")
            if isinstance(sid, str) and sid.strip():
                out.add(sid.strip())
    return out


def classify_source(channel: str, lane_surface: str, session: str,
                    declared_sessions: Tuple[str, ...],
                    project_sessions: set) -> Tuple[Optional[str], Optional[str]]:
    """The three source classes (judged from the registers and the engine's
    injected channel only; no self-reported field is consulted).

    Order: lane agent (the engine-injected surface) -> executor session (named
    in executor_sessions, or a cwd-derived channel) -> project session (present
    in sessions.json). Nothing else: refusal (source-class-unknown).
    Returns (source_class, None) or (None, reason)."""
    import executor_grants
    if channel == "env" and lane_surface.strip() == shared.CALLER_SURFACE_LANE_AGENT:
        return SRC_LANE, None
    if executor_grants.is_executor_channel(channel, lane_surface, declared_sessions, session):
        return SRC_EXECUTOR, None
    if session in project_sessions:
        return SRC_PROJECT, None
    return None, ("source-class-unknown: session %s is neither named in the project's "
                  "executor_sessions nor registered in sessions.json, and the channel "
                  "%r is not an engine-injected lane-agent surface — anything else is "
                  "refused (the source is judged, never self-reported)" % (session, channel))


# ---------- single-writer critical section (flock) ----------

@contextmanager
def _locked_append(path: str):
    """The check-then-append critical section: read -> decide -> append inside
    an exclusive lock. Normal, error and interrupt paths all release."""
    import fcntl
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield fd
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_rows_unlocked(fd: int) -> Tuple[List[Dict[str, Any]], int]:
    """Read all rows from fd (ledger discipline: a bad line is counted and
    never silently dropped)."""
    rows: List[Dict[str, Any]] = []
    malformed = 0
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = ""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk.decode("utf-8", "replace")
    except OSError:
        return rows, malformed + 1
    for line in raw.split("\n"):
        if line.strip() == "":
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        else:
            malformed += 1
    return rows, malformed


def _append_line_unlocked(fd: int, row: Dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False) + "\n"
    os.lseek(fd, 0, os.SEEK_END)
    os.write(fd, line.encode("utf-8"))


# ---------- read view: state computation ----------

def head_states(rows: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """The head-state table (read-side merge; torn-op tolerance, never a
    write-path license):

    - state rows take effect in landing order (an answer row also records
      `answered`: the legacy answer row keeps judging the head answered -- zero
      migration for existing rows);
    - a supersedes link without its derived state row (a crash between the two
      appends) -> the reader recomputes superseded (display/contract repair);
    - no record at all = open."""
    heads = {r["id"] for r in rows if r.get("type") == "request" and isinstance(r.get("id"), str)}
    states = {h: STATE_OPEN for h in heads}
    for r in rows:
        t = r.get("type")
        if t == "answer":
            k = r.get("answer_for")
            if k in states and states[k] == STATE_OPEN:
                states[k] = STATE_ANSWERED
        elif t == "state":
            k = r.get("state_for")
            s = r.get("state")
            if k in states and (s in TERMINAL_STATES or s == STATE_ANSWERED):
                states[k] = s
        elif t == "link" and r.get("kind") == LINK_SUPERSEDES:
            k = r.get("to")
            if k in states and states[k] != STATE_SUPERSEDED:
                # Torn-op tolerance: the link is present, the state row is not
                # -> recompute (see the module-header invariant).
                states[k] = STATE_SUPERSEDED
    return states


def find_open_duplicate(rows: Sequence[Dict[str, Any]], states: Dict[str, str],
                        source_ticket: str, epic: str, subject: str) -> Optional[str]:
    """An open head with the same (source ticket + owning epic + subject);
    None when there is none.

    Legacy heads (no subject key) stay out of the family scan -- they have no
    subject, so same-family is undecidable; classifying them waits for the
    host's word and is not invented here."""
    want = (source_ticket or "", epic or "", subject)
    for r in rows:
        if r.get("type") != "request":
            continue
        subj = r.get("subject")
        if not isinstance(subj, str) or subj == "":
            continue
        if (str(r.get("source_ticket") or ""), str(r.get("epic") or ""), subj) == want:
            hid = r.get("id")
            if isinstance(hid, str) and states.get(hid, STATE_OPEN) not in TERMINAL_STATES:
                return hid
    return None


# ---------- field validation ----------

def validate_head_extras(body: Dict[str, Any], epics_dir: Optional[str]) -> Dict[str, Any]:
    """The head's thread-face fields: subject required; epic required (a
    registered code, or none plus a reason); source_ticket optional (when
    given it must look like a ticket id). The only hard check is that the code
    is in the register; NO consistency check against the source ticket's epic
    (that would condemn legal history -- design note trade-off 2)."""
    subject = body.get("subject")
    if not isinstance(subject, str) or subject.strip() == "":
        return _refuse("subject", "subject must be a non-empty string (the family key: "
                                  "what recurs across instances)")
    subject = subject.strip()
    if len(subject) > SUBJECT_MAX:
        return _refuse("subject", "subject too long (%d > %d chars)" % (len(subject), SUBJECT_MAX))
    epic = body.get("epic")
    if not isinstance(epic, str) or epic.strip() == "":
        return _refuse("epic", "epic is required (a judgement, not a fact): a registered "
                               "epic code, or \"none\" plus one reason")
    epic = epic.strip()
    epic_reason = ""
    if epic == EPIC_NONE:
        epic_reason = body.get("epic_reason")
        if not isinstance(epic_reason, str) or epic_reason.strip() == "":
            return _refuse("epic_reason", "epic \"none\" requires one reason (why this "
                                          "problem belongs to no epic)")
        epic_reason = epic_reason.strip()
        if len(epic_reason) > EPIC_REASON_MAX:
            return _refuse("epic_reason", "epic_reason too long (%d > %d chars)"
                           % (len(epic_reason), EPIC_REASON_MAX))
    else:
        try:
            epic = shared.validate_epic_code(epic, epics_dir)
        except ValueError as e:
            return _refuse("epic", str(e))
    source_ticket = body.get("source_ticket", "")
    if source_ticket is None:
        source_ticket = ""
    if not isinstance(source_ticket, str):
        return _refuse("source_ticket", "source_ticket must be a string ticket id or empty "
                                        "(a fact, never validated against the epic)")
    source_ticket = source_ticket.strip()
    if source_ticket and not TICKET_ID_RE.match(source_ticket):
        return _refuse("source_ticket", "source_ticket %r does not look like a ticket id "
                                        "(tMMDDNN-N) — it is a fact field, leave it empty "
                                        "when unknown" % source_ticket[:64])
    return {"ok": True, "fields": {"subject": subject, "epic": epic,
                                   "epic_reason": epic_reason,
                                   "source_ticket": source_ticket}}


def validate_evidence(evidence: Any) -> Dict[str, Any]:
    """Evidence for resolved: a ticket id or a commit id; no evidence means no
    resolved (design note problem 1)."""
    if not isinstance(evidence, str) or evidence.strip() == "":
        return _refuse("evidence", "resolved requires evidence (a ticket id or a commit "
                                   "id); no evidence means no resolved")
    ev = evidence.strip()
    if not (TICKET_ID_RE.match(ev) or COMMIT_ID_RE.match(ev)):
        return _refuse("evidence", "evidence %r is neither a ticket id (tMMDDNN-N) nor a "
                                   "commit id (7-40 hex chars)" % ev[:64])
    return {"ok": True, "evidence": ev}


# ---------- ops ----------

def _resolve_and_gate(body: Dict[str, Any], env: Dict[str, str], cwd: str,
                      projects: Optional[Sequence[Dict[str, Any]]],
                      exclude_trees: Sequence[str],
                      load_decl: Optional[Callable[[str], Dict[str, Any]]],
                      delivered_via: Optional[str]) -> Dict[str, Any]:
    """The identity three-gate + the direct-write closure + source
    classification. Returns {"ok": True, "caller": {...}, "source_class": ...}
    or a refusal (with field)."""
    caller = executor_requests.resolve_caller(
        str(body.get("caller_project") or ""), env=env, cwd=cwd,
        projects=projects, exclude_trees=exclude_trees, load_decl=load_decl)
    if not caller.get("ok"):
        # The delivery gate refuses any non-executor; this face downgrades by
        # refusal reason into its own classification: lane-agent-exempt = the
        # engine-injected lane surface (a legal source); session-not-named =
        # consult the project-session register (sessions.json) -- registered =
        # project-session, otherwise keep the refusal (anything outside the
        # three classes is refused, reworded onto the source_class field).
        reason = str(caller.get("reason") or "")
        key0 = (str(body.get("caller_project") or "")
                or str(env.get(shared.CALLER_PROJECT_ENV) or ""))
        if "lane-agent-exempt" in reason:
            return {"ok": True,
                    "caller": {"ok": True, "project": key0,
                               "session": caller_session_of(env), "channel": "env"},
                    "source_class": SRC_LANE}
        if "session-not-named" in reason:
            sid = caller_session_of(env)
            if shared.PROJECT_KEY_RE.match(key0) and sid and \
                    sid in sessions_register_sessions(key0, env):
                return {"ok": True,
                        "caller": {"ok": True, "project": key0, "session": sid,
                                   "channel": "env"},
                        "source_class": SRC_PROJECT}
            return _refuse("source_class",
                           "source-class-unknown: session %r is neither named in the "
                           "project's executor_sessions nor registered in sessions.json "
                           "— anything else is refused" % sid)
        return caller
    key = caller["project"]
    if not shared.PROJECT_KEY_RE.match(key or ""):
        return _refuse("project", "project key shape invalid: %r" % (key or "",))
    if delivered_via is None and str(caller.get("channel") or "") in RESIDENT_EXECUTOR_CHANNELS:
        return _refuse("channel", DIRECT_WRITE_REFUSAL % caller.get("channel"))
    import executor_grants
    lane_surface = str(env.get(shared.CALLER_SURFACE_ENV) or "")
    load = load_decl(key) if load_decl else executor_grants.load_declaration(key)
    declared = tuple(load.get("executor_sessions") or ()) if load.get("ok") else ()
    project_sessions = sessions_register_sessions(key, env)
    src, reason = classify_source(str(caller.get("channel") or ""), lane_surface,
                                  caller["session"], declared, project_sessions)
    if src is None:
        return _refuse("source_class", reason or "source class unknown")
    return {"ok": True, "caller": caller, "source_class": src}


def _session_of(body: Dict[str, Any], caller: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    raised = body.get("raised_by")
    if raised is not None and raised != "":
        if not isinstance(raised, str):
            return None, _refuse("raised_by", "raised_by must be a string session id")
        if raised.strip() and raised.strip() != caller["session"]:
            return None, _refuse("raised_by", "raised_by %r does not match the resolved "
                                 "caller session %s — the engine records the true writer"
                                 % (raised.strip()[:64], caller["session"]))
    return caller["session"], None


def file_thread_op(body: Dict[str, Any], now_ms: int, seq: int,
                   env: Optional[Dict[str, str]] = None, cwd: str = "",
                   projects: Optional[Sequence[Dict[str, Any]]] = None,
                   exclude_trees: Sequence[str] = (),
                   load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
                   epics_dir: Optional[str] = None,
                   delivered_via: Optional[str] = None) -> Dict[str, Any]:
    """op=file: file a thread head. A duplicate re-file opens no new head --
    one duplicates link row is appended mechanically (from absent + the triple
    snapshot; review round 2 comment 1)."""
    env = dict(os.environ if env is None else env)
    body = executor_requests._sanitize(body)
    gated = _resolve_and_gate(body, env, cwd, projects, exclude_trees, load_decl, delivered_via)
    if not gated.get("ok"):
        return gated
    caller = gated["caller"]
    key = caller["project"]
    session, refusal = _session_of(body, caller)
    if refusal:
        return refusal
    checked = executor_requests.validate_request(body)
    if not checked.get("ok"):
        return checked
    extras = validate_head_extras(body, epics_dir)
    if not extras.get("ok"):
        return extras
    fields = checked["fields"]
    xf = extras["fields"]
    path = str(executor_requests.ledger_file(key, env))
    path_parent = os.path.dirname(path)
    os.makedirs(path_parent, exist_ok=True)
    with _locked_append(path) as fd:
        rows, _mal = _read_rows_unlocked(fd)
        states = head_states(rows)
        dup = find_open_duplicate(rows, states, xf["source_ticket"], xf["epic"], xf["subject"])
        if dup is not None:
            link = {"type": "link", "id": "lnk-%d-%04d" % (now_ms, seq), "kind": LINK_DUPLICATES,
                    "to": dup, "at": now_ms, "by": session, "surface": SURFACE_ENGINE,
                    "dup_subject": xf["subject"], "dup_epic": xf["epic"],
                    "dup_source_ticket": xf["source_ticket"]}
            _append_line_unlocked(fd, link)
            return {"ok": True, "linked_to": dup, "row": link, "file": path}
        row: Dict[str, Any] = {
            "type": "request",
            "id": executor_requests.make_request_id(now_ms, seq),
            "at": now_ms,
            "project": key,
            "kind": fields["kind"],
            "question": fields["question"],
            "detail": fields["detail"],
            "default_action": fields["default_action"],
            "expires_at": fields["expires_at"],
            "raised_by": session,
            "surface": SURFACE_ENGINE,
            "subject": xf["subject"],
            "epic": xf["epic"],
            "source_class": gated["source_class"],
        }
        if xf["epic_reason"]:
            row["epic_reason"] = xf["epic_reason"]
        if xf["source_ticket"]:
            row["source_ticket"] = xf["source_ticket"]
        if fields["options"] is not None:
            row["options"] = fields["options"]
        if delivered_via:
            row["delivered_via"] = delivered_via
        _append_line_unlocked(fd, row)
        return {"ok": True, "row": row, "file": path}


def reply_op(body: Dict[str, Any], now_ms: int, seq: int,
             env: Optional[Dict[str, str]] = None, cwd: str = "",
             projects: Optional[Sequence[Dict[str, Any]]] = None,
             exclude_trees: Sequence[str] = (),
             load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
             delivered_via: Optional[str] = None) -> Dict[str, Any]:
    """op=reply: append a reply. Writer rules (design note): an executor /
    lane-agent may answer and add facts; a project session may ask and add
    facts -- answering is a structured refusal. The host answers in the panel
    (never through this CLI)."""
    env = dict(os.environ if env is None else env)
    body = executor_requests._sanitize(body)
    gated = _resolve_and_gate(body, env, cwd, projects, exclude_trees, load_decl, delivered_via)
    if not gated.get("ok"):
        return gated
    caller = gated["caller"]
    key = caller["project"]
    session, refusal = _session_of(body, caller)
    if refusal:
        return refusal
    reply_for = body.get("id")
    if not isinstance(reply_for, str) or reply_for.strip() == "":
        return _refuse("id", "id must be a non-empty string (the head to reply to)")
    text = body.get("text")
    if not isinstance(text, str) or text.strip() == "":
        return _refuse("text", "text must be a non-empty string")
    text = text.strip()
    if len(text) > REPLY_TEXT_MAX:
        return _refuse("text", "text too long (%d > %d chars) — keep the head narrow, "
                               "put prose in replies" % (len(text), REPLY_TEXT_MAX))
    intent = body.get("intent", INTENT_FACT)
    if not isinstance(intent, str) or intent not in REPLY_INTENTS:
        return _refuse("intent", "intent must be one of %s (got %r)"
                       % ("/".join(REPLY_INTENTS), intent))
    src = gated["source_class"]
    if src == SRC_PROJECT and intent not in PROJECT_SESSION_INTENTS:
        return _refuse("reply", "a project session may ask and add facts; answering is "
                                "the host's word (intent=%s refused for %s)" % (intent, src))
    via = body.get("via", "")
    if via is None:
        via = ""
    if not isinstance(via, str):
        return _refuse("via", "via must be a string (who filed this on the decider's behalf)")
    via = via.strip()
    if len(via) > VIA_MAX:
        return _refuse("via", "via too long (%d > %d chars)" % (len(via), VIA_MAX))
    # Delegated answer (ticket item 7, rework defect 2): `by` names the DECIDER,
    # `via` names the filer (the resolved caller). A named decider requires the
    # filer field; the filer is identity-gated like raised_by (a via that is not
    # the resolved session is refused — no third-party filing). Without `by`,
    # the reply is the caller's own: by = the resolved session.
    by_field = body.get("by")
    if by_field is not None and by_field != "":
        if not isinstance(by_field, str) or by_field.strip() == "":
            return _refuse("by", "by must be a non-empty string (who decided) or omitted "
                                 "(then the reply is the caller's own)")
        by_field = by_field.strip()
        if len(by_field) > VIA_MAX:
            return _refuse("by", "by too long (%d > %d chars)" % (len(by_field), VIA_MAX))
        if not via:
            return _refuse("via", "a named decider (by=%s) requires the filer (via) — the "
                                  "three fields read: by who decided / via who filed it / "
                                  "anchor the host's words" % by_field[:64])
        if via != session:
            return _refuse("via", "via %r does not match the resolved caller session %s — "
                                  "the filer is the resolved session, never self-reported"
                                  % (via[:64], session))
        decider = by_field
    else:
        decider = session
    anchor = body.get("anchor", "")
    if anchor is None:
        anchor = ""
    if not isinstance(anchor, str):
        return _refuse("anchor", "anchor must be a string (the host's words or the anchor)")
    anchor = anchor.strip()
    if len(anchor) > ANCHOR_MAX:
        return _refuse("anchor", "anchor too long (%d > %d chars)" % (len(anchor), ANCHOR_MAX))
    path = str(executor_requests.ledger_file(key, env))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _locked_append(path) as fd:
        rows, _mal = _read_rows_unlocked(fd)
        heads = {r.get("id") for r in rows if r.get("type") == "request"}
        if reply_for not in heads:
            return _refuse("id", "no such request id: %s (nothing to reply to)" % reply_for)
        row: Dict[str, Any] = {"type": "reply", "id": "rpl-%d-%04d" % (now_ms, seq),
                               "reply_for": reply_for, "at": now_ms, "text": text,
                               "by": decider, "intent": intent, "source_class": src,
                               "surface": SURFACE_ENGINE}
        if via:
            row["via"] = via
        if anchor:
            row["anchor"] = anchor
        if delivered_via:
            row["delivered_via"] = delivered_via
        _append_line_unlocked(fd, row)
        return {"ok": True, "row": row, "file": path}


def state_op(body: Dict[str, Any], now_ms: int, seq: int,
             env: Optional[Dict[str, str]] = None, cwd: str = "",
             projects: Optional[Sequence[Dict[str, Any]]] = None,
             exclude_trees: Sequence[str] = (),
             load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
             delivered_via: Optional[str] = None) -> Dict[str, Any]:
    """op=state: the engine side only allows resolved (the doer, with
    evidence). answered/dismissed are the host's panel face; superseded is the
    machine's, with a supersedes link -- all refused with the way out named."""
    env = dict(os.environ if env is None else env)
    body = executor_requests._sanitize(body)
    gated = _resolve_and_gate(body, env, cwd, projects, exclude_trees, load_decl, delivered_via)
    if not gated.get("ok"):
        return gated
    caller = gated["caller"]
    key = caller["project"]
    session, refusal = _session_of(body, caller)
    if refusal:
        return refusal
    requested = body.get("state")
    if requested in HOST_STATES:
        return _refuse("state", "%s is the host's word, set in the panel — the engine CLI "
                                "does not set it" % requested)
    if requested in MACHINE_STATES:
        return _refuse("state", "superseded is set by the machine when a newer item links "
                                "this one (op=link with kind=supersedes) — never by hand")
    if requested != STATE_RESOLVED:
        return _refuse("state", "state must be one of open/answered/resolved/dismissed/"
                                "superseded; the engine CLI only sets resolved (got %r)"
                       % (requested,))
    src = gated["source_class"]
    if src == SRC_PROJECT:
        return _refuse("state", "a project session cannot resolve; the doer (executor or "
                                "lane agent) resolves with evidence")
    ev = validate_evidence(body.get("evidence"))
    if not ev.get("ok"):
        return ev
    target = body.get("id")
    if not isinstance(target, str) or target.strip() == "":
        return _refuse("id", "id must be a non-empty string (the head to resolve)")
    path = str(executor_requests.ledger_file(key, env))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _locked_append(path) as fd:
        rows, _mal = _read_rows_unlocked(fd)
        states = head_states(rows)
        if target not in states:
            return _refuse("id", "no such request id: %s" % target)
        if states[target] in TERMINAL_STATES:
            return _refuse("state", "request %s is already %s (terminal — a row is never "
                                    "rewritten)" % (target, states[target]))
        row = {"type": "state", "id": "st-%d-%04d" % (now_ms, seq), "state_for": target,
               "state": STATE_RESOLVED, "at": now_ms, "by": session,
               "evidence": ev["evidence"], "source_class": src, "surface": SURFACE_ENGINE}
        if delivered_via:
            row["delivered_via"] = delivered_via
        _append_line_unlocked(fd, row)
        return {"ok": True, "row": row, "file": path}


def link_op(body: Dict[str, Any], now_ms: int, seq: int,
            env: Optional[Dict[str, str]] = None, cwd: str = "",
            projects: Optional[Sequence[Dict[str, Any]]] = None,
            exclude_trees: Sequence[str] = (),
            load_decl: Optional[Callable[[str], Dict[str, Any]]] = None,
            delivered_via: Optional[str] = None) -> Dict[str, Any]:
    """op=link: append a link row. supersedes additionally lands a superseded
    state row automatically (link first, state second -- the module-header
    invariant; the unit test pins both rows physically present on the clean
    path)."""
    env = dict(os.environ if env is None else env)
    body = executor_requests._sanitize(body)
    gated = _resolve_and_gate(body, env, cwd, projects, exclude_trees, load_decl, delivered_via)
    if not gated.get("ok"):
        return gated
    caller = gated["caller"]
    key = caller["project"]
    session, refusal = _session_of(body, caller)
    if refusal:
        return refusal
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in LINK_KINDS:
        return _refuse("kind", "kind must be one of %s (got %r)"
                       % ("/".join(LINK_KINDS), kind))
    from_id = body.get("from")
    if from_id is not None and (not isinstance(from_id, str) or from_id.strip() == ""):
        return _refuse("from", "from must be a non-empty head id when given (a re-file "
                               "that was linked omits it; the snapshot travels on the row)")
    from_id = (from_id or "").strip()
    to_id = body.get("to")
    if not isinstance(to_id, str) or to_id.strip() == "":
        return _refuse("to", "to must be a non-empty head id (the linked item)")
    to_id = to_id.strip()
    path = str(executor_requests.ledger_file(key, env))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out_rows: List[Dict[str, Any]] = []
    with _locked_append(path) as fd:
        rows, _mal = _read_rows_unlocked(fd)
        heads = {r.get("id") for r in rows if r.get("type") == "request"}
        states = head_states(rows)
        if from_id and from_id not in heads:
            return _refuse("from", "no such request id: %s" % from_id)
        if to_id not in heads:
            return _refuse("to", "no such request id: %s" % to_id)
        if kind == LINK_SUPERSEDES and states.get(to_id) in TERMINAL_STATES:
            return _refuse("to", "cannot supersede %s: already %s" % (to_id, states[to_id]))
        link = {"type": "link", "id": "lnk-%d-%04d" % (now_ms, seq), "kind": kind,
                "to": to_id, "at": now_ms, "by": session, "surface": SURFACE_ENGINE}
        if from_id:
            link["from"] = from_id
        if delivered_via:
            link["delivered_via"] = delivered_via
        _append_line_unlocked(fd, link)
        out_rows.append(link)
        if kind == LINK_SUPERSEDES:
            st = {"type": "state", "id": "st-%d-%04d" % (now_ms, seq + 1),
                  "state_for": to_id, "state": STATE_SUPERSEDED, "at": now_ms,
                  "by": session, "note": "set automatically by the supersedes link",
                  "surface": SURFACE_ENGINE}
            if delivered_via:
                st["delivered_via"] = delivered_via
            _append_line_unlocked(fd, st)
            out_rows.append(st)
        return {"ok": True, "rows": out_rows, "file": path}


# ---------- CLI ----------

_OPS = {"file": file_thread_op, "reply": reply_op, "state": state_op, "link": link_op}


def _emit(out: Dict[str, Any]) -> None:
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
    op = doc.get("op")
    if op not in _OPS:
        _emit({"ok": False, "field": "op", "error": "op must be one of %s (got %r)"
               % ("/".join(sorted(_OPS)), op)})
        return 2
    import time as _time
    now_ms = int(_time.time() * 1000)
    try:
        cwd = os.path.realpath(os.getcwd())
    except OSError:
        cwd = ""
    try:
        projects, _quarantined = shared.load_projects_registry()
    except Exception:  # noqa: BLE001 — a broken registry must not escalate into a blanket refusal (identity falls back to arg/env)
        projects = None
    exclude_trees = (os.path.realpath(str(shared.REPO_ROOT)),)
    out = _OPS[op](doc, now_ms, 1, cwd=cwd, projects=projects,
                   exclude_trees=exclude_trees)
    _emit(out)
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
