# -*- coding: utf-8 -*-
"""request_sweep -- the engine-side sweep that resolves open request heads whose
DECLARED condition the delivery ledger has since answered (t261019-44; host
order 261019, option a: a declarative, machine-evaluated resolution condition;
the expiry-archive option b is NOT built here).

What this is: request_thread (t261007-02) moves a head only by a host
answer/dismiss or a doer resolve-with-evidence, so heads whose question the
ledger has objectively answered stay open. A head may carry `resolves_when` --
a CLOSED set of machine-checkable conditions over the delivery ledger:

    green_cert_after {cert}   the FIRST certification on the red cert's line
                              with seq strictly after it has a green run
                              (the `_releasing_green_cert` order rule,
                              develop_certify L672-690, carried verbatim)
    landing_on_line {ticket}  a landing row on the ledger names that ticket
    ticket_closed  {ticket}   the ticket's status projection reads "closed"
    freeze_closed  {freeze}   a freeze_change row `change: "closed"` exists
                              against that episode

The sweep evaluates every OPEN head that declares a condition, once per call
(one tick's ask), and appends ONE `resolved` state row whose `evidence` IS the
row it observed (the releasing cert id / the landing id / the freeze episode id
plus the closing change named in the note / the ticket id plus the NAMED status
source). Never a guess, never a summary a reader cannot check.

Fail-closed rules (spec 3):
  - unreadable delivery ledger, unreadable runs store, unavailable ticket
    reader, unknown condition kind -> SKIP + a named note in the receipt.
    Never a silent close, never a fabricated green;
  - a dangling reference (the named red cert / freeze episode is not on the
    ledger) is also a SKIP -- a citation that cannot be checked resolves
    nothing;
  - heads WITHOUT a declared condition are untouched (no retro-fitting); a
    condition may be attached later through `request_thread.py op=condition`
    (append-only, attributed), which the sweep reads as the head's effective
    condition (the latest condition row wins over the head's own field).

Identity (spec 5): the sweep writes under `by: "engine:request-sweep"`,
`surface: SURFACE_ENGINE` -- never as a host answer. The answered/dismissed
refusals in request_thread.state_op are untouched, and so is the "a project
session cannot resolve" rule: the sweep is neither -- it is the engine's own
named writer over rows only it writes.

Borrowed machinery, carried/dropped (plan rev2, review gen1 pass):
  - `_releasing_green_cert` order rule: CARRIED (strictly-after, non-int seq
    skipped, fail-closed when runs are unreadable);
  - coverage family's `landing_not_object` raise: CONVERTED to count-and-skip
    (a sweep must not die on one malformed row; the count travels on the
    receipt, mirroring `_read_rows_unlocked`'s malformed-line counter);
  - `line_round_tick_engine` per-project isolation: CARRIED (one broken
    project is a named receipt entry, never the sweep's death);
  - guard token / inflight registry / force marker: DROPPED -- the sweep
    spawns nothing, holds no cross-tick state, and its mutual exclusion with
    host answers/dismisses is the requests ledger's own flock
    (`request_thread._locked_append`), reused as-is; re-resolution cannot
    double-write because terminal heads are skipped via `head_states`.

Entry points:
    python3 server/engine/request_sweep.py '{"project":"<key>"}'   one project
    python3 server/engine/request_sweep.py '{}'                    every project
Output: one JSON receipt on stdout; exit 0 even when every head skipped
(a skip is a named outcome, not a failure); exit 2 only for a malformed argv.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import develop_certify
import executor_requests
import request_thread

# ---- the closed condition set ----
COND_GREEN_CERT_AFTER = "green_cert_after"
COND_LANDING_ON_LINE = "landing_on_line"
COND_TICKET_CLOSED = "ticket_closed"
COND_FREEZE_CLOSED = "freeze_closed"
# t261026-07: a ROUND row after the head — a round ends by writing a
# certification row on its line (green or red), so "a certification row on
# the line whose `at` is strictly after the head's filing time" IS the
# record-shaped "a round happened again". This is the class condition the
# executor files for run-stalled and run-silent heads.
COND_ROUND_AFTER = "round_after"
CONDITION_KINDS = (COND_GREEN_CERT_AFTER, COND_LANDING_ON_LINE,
                   COND_TICKET_CLOSED, COND_FREEZE_CLOSED, COND_ROUND_AFTER)
# each kind carries EXACTLY one param, under its own name
CONDITION_PARAM = {COND_GREEN_CERT_AFTER: "cert",
                   COND_LANDING_ON_LINE: "ticket",
                   COND_TICKET_CLOSED: "ticket",
                   COND_FREEZE_CLOSED: "freeze",
                   COND_ROUND_AFTER: "line"}

LINE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# scanning shape (NOT anchored): a ticket id inside prose — the residue pass
# parses a blocker's subject out of free text with this, and cites nothing
# when no id is present
TICKET_ID_SCAN_RE = re.compile(r"t\d{6}-\d+")

# t261026-07: the request-class -> closing-condition table (the executor's
# own vocabulary). A class listed here files with the matching `resolves_when`
# so the sweep can close it; a class in NOT_AUTO_CLOSABLE is the human's word
# by design — it files with the not-auto-closable face stamp so nobody waits
# for a machine.
CLASS_CONDITION_TABLE = {
    "run-silent": {"kind": COND_ROUND_AFTER, "param": "line",
                   "source": "the head's own line"},
    "run-stalled": {"kind": COND_ROUND_AFTER, "param": "line",
                    "source": "the head's own line"},
    "blocker": {"kind": COND_TICKET_CLOSED, "param": "ticket",
                "source": "the head's subject ticket (or its landing)"},
}
NOT_AUTO_CLOSABLE = ("finding", "question")

SWEEP_BY = "engine:request-sweep"
SWEEP_SURFACE = executor_requests.SURFACE_ENGINE
# t261026-07: the residue writer — the executor-side close of a legacy head
# whose condition can never exist, citing the row that ended its subject.
RESIDUE_BY = "executor:request-sweep-residue"

CERT_ID_RE = re.compile(r"^cert-[0-9A-Za-z]+$")
FREEZE_ID_RE = re.compile(r"^frz-[0-9A-Za-z]+$")
FREEZE_CHANGE_CLOSED = "closed"

USAGE = ("usage: python3 server/engine/request_sweep.py "
         "'{\"project\":\"<key>\"}'  (or '{}' for every project)")

# evaluator verdicts
VERDICT_TRUE = True
VERDICT_FALSE = False
VERDICT_SKIP = None


def _refuse(field: str, error: str) -> Dict[str, Any]:
    return {"ok": False, "field": field, "error": error}


# ---------- condition validation (the closed set, at filing and at attach) --

def validate_resolves_when(raw: Any) -> Dict[str, Any]:
    """Validate a `resolves_when` declaration. A dict with a known `kind` and
    EXACTLY its one param, well-shaped; anything else is a named refusal."""
    if not isinstance(raw, dict):
        return _refuse("resolves_when",
                       "resolves_when must be an object like "
                       '{"kind":"green_cert_after","cert":"cert-..."} (got %s)'
                       % type(raw).__name__)
    kind = raw.get("kind")
    if kind not in CONDITION_KINDS:
        return _refuse("resolves_when",
                       "resolves_when.kind must be one of %s (got %r) — the set "
                       "is closed; anything else is refused, never guessed"
                       % ("/".join(CONDITION_KINDS), kind))
    param_name = CONDITION_PARAM[kind]
    unknown = sorted(k for k in raw if k not in ("kind", param_name))
    if unknown:
        return _refuse("resolves_when",
                       "resolves_when for kind %s carries only {%s}; unknown "
                       "key(s): %s" % (kind, param_name, ",".join(unknown)))
    param = raw.get(param_name)
    if not isinstance(param, str) or not param.strip():
        return _refuse("resolves_when",
                       "resolves_when.%s must be a non-empty string" % param_name)
    param = param.strip()
    if kind == COND_GREEN_CERT_AFTER and not CERT_ID_RE.match(param):
        return _refuse("resolves_when",
                       "resolves_when.cert %r does not look like a certification "
                       "id (cert-...)" % param[:64])
    if kind == COND_FREEZE_CLOSED and not FREEZE_ID_RE.match(param):
        return _refuse("resolves_when",
                       "resolves_when.freeze %r does not look like a freeze "
                       "episode id (frz-...)" % param[:64])
    if kind in (COND_LANDING_ON_LINE, COND_TICKET_CLOSED) \
            and not request_thread.TICKET_ID_RE.match(param):
        return _refuse("resolves_when",
                       "resolves_when.ticket %r does not look like a ticket id "
                       "(tMMDDNN-N)" % param[:64])
    if kind == COND_ROUND_AFTER and not LINE_ID_RE.match(param):
        return _refuse("resolves_when",
                       "resolves_when.line %r does not look like a line id "
                       "(letters/digits/dots/underscores/dashes)" % param[:64])
    return {"ok": True, "condition": {"kind": kind, param_name: param}}


# ---------- effective condition per head (filing field or attached row) -----

def effective_conditions(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """head id -> its effective condition dict ({kind, ...}), or no entry when
    the head declares none. A head's own `resolves_when` is the base; a
    condition row (op=condition) attached later WINS (the latest one wins).
    A row that fails validate_resolves_when is carried as
    {"__invalid": reason} so the sweep can skip it BY NAME (never silently)."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "request":
            hid = r.get("id")
            if isinstance(hid, str) and isinstance(r.get("resolves_when"), dict):
                out[hid] = r["resolves_when"]
        elif r.get("type") == "condition":
            hid = r.get("condition_for")
            if isinstance(hid, str):
                out[hid] = r.get("resolves_when") \
                    if isinstance(r.get("resolves_when"), dict) \
                    else {"__invalid": "condition_row_not_object"}
    return out


# ---------- dependency-injected ledger/runs/ticket readers ------------------

def load_delivery_ledger(project_key: str, env: Optional[Dict[str, str]] = None
                         ) -> Tuple[Optional[List[Dict[str, Any]]], int, str]:
    """Read the project's delivery ledger. Returns (rows, malformed_count, "")
    or (None, 0, reason) when the face is unreadable -- a skip, never a
    guessed empty ledger (a missing FILE is a normal empty ledger, not an
    error). Non-dict rows are counted (the same honesty as
    request_thread._read_rows_unlocked) and dropped from the row list."""
    try:
        # the override comes from the INJECTED env dict, never bare os.environ
        # (a test/process env must isolate the reader; ledger_path's own
        # fallback reads os.environ, so the dir is passed explicitly here --
        # the shared process pin, when set, still wins inside ledger_path).
        path = develop_certify.ledger_path(
            str(project_key), ledger_dir=_ledger_dir_override(env))
    except Exception as e:  # noqa: BLE001 — path resolution failure is a skip, not a crash
        return None, 0, "ledger_path_unresolvable:%s:%s" % (type(e).__name__, e)
    if not os.path.exists(path):
        return [], 0, ""
    try:
        # read_rows returns (rows, bad_lines): its own malformed-line report
        # (capped at 10) travels into ours, so nothing is silently dropped.
        raw_rows, bad_lines = develop_certify.read_rows(path)
    except Exception as e:  # noqa: BLE001
        return None, 0, "ledger_unreadable:%s:%s" % (type(e).__name__, e)
    rows: List[Dict[str, Any]] = []
    malformed = len(bad_lines)
    for r in raw_rows:
        if isinstance(r, dict):
            rows.append(r)
        else:
            malformed += 1
    return rows, malformed, ""


def runs_store_path(project_key: str, env: Optional[Dict[str, str]] = None) -> str:
    """The line rounds' run headers: the same store the line-round tick writes
    (develop_certify line_round_tick_activity: scenario-runs.jsonl beside the
    delivery ledger)."""
    return str(develop_certify.ledger_path(str(project_key),
                                           ledger_dir=_ledger_dir_override(env)).parent
               / "scenario-runs.jsonl")


def _ledger_dir_override(env: Optional[Dict[str, str]]) -> Optional[str]:
    env = dict(os.environ if env is None else env)
    return str(env.get("SANDBAR_DELIVERY_LEDGER_DIR") or "") or None


def make_runs_green_fn(runs_path: str) -> Callable[[str], Optional[bool]]:
    """run id -> green? (run_verdict on the run header's cases counts).
    Returns None when the store or the run row is unreadable -- the fail-closed
    reading `_releasing_green_cert` already encodes ("cannot read runs: refuse
    to guess"), carried verbatim: None never means green."""
    def is_green(run_id: str) -> Optional[bool]:
        try:
            with open(runs_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return None
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a bad line in the runs store is not this run's verdict
            if isinstance(row, dict) and row.get("id") == run_id \
                    and isinstance(row.get("cases"), dict):
                return develop_certify.run_verdict(row["cases"]) == "green"
        return None  # run row missing: no verdict, never a guess
    return is_green


# Reader liveness, for the receipt: default_ticket_status_fn records WHY the
# channel is unavailable on its first failure (t261026-06: a dead reader used
# to look like 65 ordinary per-head skips with an ok:true receipt).
_READER_LAST_ERROR: Optional[str] = None
_TICKET_READER_TIMEOUT_S = 120  # carried from the pre-t261026-06 reader


def ticket_reader_path() -> str:
    """The reader entry point, resolved the way the rest of the engine does it
    (shared.ADMIN_PY -> <repo_root>/server/admin.py, the same file the gate
    activities call). No fallback: the stale <repo_root>/server/tools/admin.py
    path that caused t261026-06 is gone for good."""
    admin = getattr(shared_module(), "ADMIN_PY", None)
    return str(admin) if admin else ""


def ticket_reader_probe() -> Dict[str, Any]:
    """Cheap existence check on the reader entry, for the receipt's top-level
    `reader` block. A missing entry is loud even when no ticket_closed head is
    evaluated."""
    path = ticket_reader_path()
    if not path or not os.path.exists(path):
        return {"available": False, "path": path,
                "error": "reader_entry_missing:%s" % path}
    return {"available": True, "path": path, "error": ""}


def _note_reader_error(reason: str) -> None:
    global _READER_LAST_ERROR
    if _READER_LAST_ERROR is None:
        _READER_LAST_ERROR = reason


def default_ticket_status_fn(ticket: str
                             ) -> Optional[Tuple[str, str]]:
    """The engine's default `ticket_closed` reader: the ticket list projection
    the scan activities already use (admin ticket list). Returns
    (status, source) or None when the channel is unavailable -- with the
    unavailability reason recorded for the receipt (`_READER_LAST_ERROR`,
    surfaced by sweep_project). The source name travels into the resolved
    row's evidence, so a reader can check WHERE the "closed" was read from (a
    projection, per ledger-record-models-v1 -- named as such, never presented
    as the ticket ledger itself)."""
    import subprocess
    admin_py = ticket_reader_path()
    repo_root = str(getattr(shared_module(), "REPO_ROOT", "") or "")
    if not admin_py or not os.path.exists(admin_py):
        _note_reader_error("reader_entry_missing:%s" % admin_py)
        return None
    cmd = [sys.executable, admin_py, "call", "ticket",
           json.dumps({"op": "list"}, ensure_ascii=False)]
    try:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                              text=True, timeout=_TICKET_READER_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        # TimeoutExpired is a SubprocessError: a slow reader is an unavailable
        # reader, named -- never a fabricated empty list.
        _note_reader_error("reader_spawn_failed:%s:%s"
                           % (type(e).__name__, admin_py))
        return None
    if proc.returncode != 0:
        _note_reader_error("reader_exit_%d:%s" % (proc.returncode, admin_py))
        return None
    parsed = None
    try:
        import shared
        parsed = shared.gate_receipt_parse(proc.stdout)
    except Exception:  # noqa: BLE001 — parse failure is an unavailable channel
        _note_reader_error("reader_output_unparseable:%s" % admin_py)
        return None
    if "ok" not in parsed:
        # nothing parseable in the output stream at all: an unavailable
        # channel, NOT an honestly empty ticket list
        _note_reader_error("reader_output_unparseable:%s" % admin_py)
        return None
    if not parsed.get("ok"):
        # a receipt-level refusal (unknown project, tool error, ...) is an
        # unavailable channel, NOT an honestly empty ticket list
        _note_reader_error("reader_refused:%s" % admin_py)
        return None
    tickets = ((parsed.get("result") or {}).get("tickets")) or []
    for t in tickets:
        if isinstance(t, dict) and str(t.get("id") or "") == ticket:
            return str(t.get("status") or ""), "ticket-list-projection"
    # the ticket is simply not on the list: not "closed", an honest False with
    # the same named source
    return "not-listed", "ticket-list-projection"


def shared_module():
    import shared
    return shared


# ---------- the four evaluators ---------------------------------------------
# each returns (verdict, evidence, note): verdict True/False, or VERDICT_SKIP
# (None) with a named skip reason in `note` when the face is unreadable or a
# citation is dangling -- skip, never a silent close, never a fabricated green.

def eval_green_cert_after(cert_id: str, rows: List[Dict[str, Any]],
                          is_green: Callable[[str], Optional[bool]]
                          ) -> Tuple[Optional[bool], str, str]:
    """The `_releasing_green_cert` order rule, carried: the first cert on the
    red cert's line with seq strictly after it whose run is green."""
    red = None
    for r in rows:
        if r.get("kind") == develop_certify.KIND_CERT and r.get("id") == cert_id:
            red = r
            break
    if red is None:
        return VERDICT_SKIP, "", "red_cert_not_found:%s" % cert_id[:40]
    line = red.get("line")
    if not isinstance(line, str) or not line:
        return VERDICT_SKIP, "", "red_cert_line_unreadable:%s" % cert_id[:40]
    red_seq = red.get("seq")
    if not isinstance(red_seq, int):
        # carried from _releasing_green_cert: an unusable order never resolves
        return VERDICT_SKIP, "", "red_cert_seq_unreadable:%s" % cert_id[:40]
    later = [r for r in rows
             if r.get("kind") == develop_certify.KIND_CERT
             and r.get("line") == line
             and isinstance(r.get("seq"), int) and r["seq"] > red_seq]
    later.sort(key=lambda r: r["seq"])
    for cert in later:
        run_id = cert.get("run")
        if not isinstance(run_id, str) or not run_id:
            continue
        g = is_green(run_id)
        if g is None:
            return VERDICT_SKIP, "", "run_store_unreadable:%s" % run_id[:40]
        if g:
            return VERDICT_TRUE, str(cert.get("id") or ""), \
                "green_cert_after:%s released by %s" % (cert_id[:40], cert.get("id"))
    return VERDICT_FALSE, "", ""


def eval_landing_on_line(ticket: str, rows: List[Dict[str, Any]]
                         ) -> Tuple[Optional[bool], str, str]:
    for r in rows:
        if r.get("kind") == develop_certify.KIND_LANDING \
                and str(r.get("ticket") or "") == ticket:
            lid = r.get("id")
            if isinstance(lid, str) and lid:
                return VERDICT_TRUE, lid, "landing_on_line:%s landed as %s" % (
                    ticket, lid)
    return VERDICT_FALSE, "", ""


def eval_ticket_closed(ticket: str,
                       ticket_status_fn: Callable[[str], Optional[Tuple[str, str]]]
                       ) -> Tuple[Optional[bool], str, str]:
    read = ticket_status_fn(ticket)
    if read is None:
        return VERDICT_SKIP, "", "ticket_reader_unavailable:%s" % ticket
    status, source = read
    if status == "closed":
        # evidence names the projection it was read from (review gen1 comment 3)
        return VERDICT_TRUE, "%s status=closed via %s" % (ticket, source), \
            "ticket_closed:%s" % source
    return VERDICT_FALSE, "", ""


def eval_round_after(line: str, rows: List[Dict[str, Any]],
                     head_at: Optional[int]
                     ) -> Tuple[Optional[bool], str, str]:
    """A round row after the head: ANY certification row on the line (green
    or red — a round ends by writing its cert) whose `at` is strictly after
    the head's filing time. `at` must be readable on BOTH sides; an unusable
    order is a skip, never a guess (the same fail direction as
    eval_green_cert_after's seq rule)."""
    if not isinstance(head_at, int):
        return VERDICT_SKIP, "", "head_at_unreadable:%s" % line[:40]
    for r in rows:
        if r.get("kind") == develop_certify.KIND_CERT \
                and r.get("line") == line:
            at = r.get("at")
            if isinstance(at, int) and at > head_at:
                return VERDICT_TRUE, str(r.get("id") or ""), \
                    "round_after:%s round row %s at=%s" % (line[:40],
                                                           r.get("id"), at)
    return VERDICT_FALSE, "", ""


def eval_freeze_closed(freeze_id: str, rows: List[Dict[str, Any]]
                       ) -> Tuple[Optional[bool], str, str]:
    """The closing change row mints no id (record models: freeze_change rows
    are keyed (freeze, change)), so the evidence is the episode id and the
    note names the closing change (kind + at) -- checkable, never a guess."""
    episode = None
    closing = None
    for r in rows:
        if r.get("kind") == develop_certify.KIND_FREEZE and r.get("id") == freeze_id:
            episode = r
        if r.get("kind") == develop_certify.KIND_FREEZE_CHANGE \
                and r.get("freeze") == freeze_id \
                and r.get("change") == FREEZE_CHANGE_CLOSED:
            if closing is None or (isinstance(r.get("at"), int)
                                   and isinstance(closing.get("at"), int)
                                   and r["at"] >= closing["at"]):
                closing = r
    if episode is None and closing is None:
        return VERDICT_SKIP, "", "freeze_not_found:%s" % freeze_id[:40]
    if closing is not None:
        note = "freeze_closed:change=%s at=%s" % (FREEZE_CHANGE_CLOSED,
                                                  closing.get("at"))
        return VERDICT_TRUE, freeze_id, note
    return VERDICT_FALSE, "", ""


# ---------- legacy-residue helpers (t261026-07) ------------------------------

def head_line(head_row: Dict[str, Any]) -> Optional[str]:
    """The line a run-silent / run-stalled head is about: the detail's parsed
    `line` key first (the watch files detail as JSON with `line`), then the
    question's `on line <id>` phrasing. None when neither shape holds — an
    unparsable head is never guessed onto a line."""
    detail = head_row.get("detail")
    if isinstance(detail, str) and detail.strip():
        try:
            obj = json.loads(detail)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("line"), str) \
                and LINE_ID_RE.match(obj["line"].strip()):
            return obj["line"].strip()
    question = str(head_row.get("question") or "")
    m = re.search(r"on line ([A-Za-z0-9][A-Za-z0-9._-]*)", question)
    if m and LINE_ID_RE.match(m.group(1)):
        return m.group(1)
    return None


def head_subject_ticket(head_row: Dict[str, Any]) -> Optional[str]:
    """A blocker head's subject ticket: the FIRST strict ticket id in the
    head's source_ticket, detail or question. Prose-only references stay
    unparsed (None) — the residue pass never closes on a guess."""
    for field in ("source_ticket", "detail", "question"):
        val = head_row.get(field)
        if not isinstance(val, str):
            continue
        m = TICKET_ID_SCAN_RE.search(val)
        if m:
            return m.group(0)
    return None


def close_legacy_residue(head_rows: Dict[str, Dict[str, Any]], states: Dict[str, str],
                         conditions: Dict[str, Dict[str, Any]],
                         ledger_rows: List[Dict[str, Any]],
                         ticket_status_fn: Callable[[str], Optional[Tuple[str, str]]],
                         now_ms: int, seq: int, append_fn: Callable[[Dict[str, Any]], None]
                         ) -> List[Dict[str, Any]]:
    """t261026-07 build C+D: close OPEN heads with NO declared condition whose
    subject row can be CITED. Bound D is absolute:
      - `finding` / `question` are NEVER machine-closed (bucket `human_word`);
      - a blocker whose ticket reads not-listed is NOT closable (a nonexistent
        row cannot be cited — bucket `not_listed`);
      - anything without a citable ending row stays open (bucket `uncited`).
    Each close appends ONE resolved state row whose evidence names the exact
    observed row. Returns the receipt entries (one per evaluated head)."""
    out: List[Dict[str, Any]] = []
    for hid, state in states.items():
        if state != request_thread.STATE_OPEN:
            continue
        if conditions.get(hid) is not None:
            continue  # the condition pass owns conditioned heads
        head_row = head_rows.get(hid) or {}
        kind = str(head_row.get("kind") or "")
        entry: Dict[str, Any] = {"id": hid, "class": kind}
        if kind in NOT_AUTO_CLOSABLE:
            entry["bucket"] = "human_word"
            out.append(entry)
            continue
        head_at = head_row.get("at") if isinstance(head_row.get("at"), int) else None
        verdict: Optional[bool] = VERDICT_FALSE
        evidence = note = ""
        if kind in ("run-silent", "run-stalled"):
            line = head_line(head_row)
            if line is None:
                verdict, evidence, note = VERDICT_SKIP, "", "residue_line_unparsable"
            else:
                verdict, evidence, note = eval_round_after(line, ledger_rows, head_at)
        elif kind == "blocker":
            ticket = head_subject_ticket(head_row)
            if ticket is None:
                verdict, evidence, note = VERDICT_SKIP, "", "residue_subject_unparsable"
            else:
                entry["ticket"] = ticket
                # a landing naming the ticket ends the subject too
                verdict, evidence, note = eval_landing_on_line(ticket, ledger_rows)
                if verdict is VERDICT_FALSE:
                    verdict, evidence, note = eval_ticket_closed(ticket, ticket_status_fn)
                    if verdict is VERDICT_FALSE:
                        read = ticket_status_fn(ticket)
                        if read is not None and read[0] == "not-listed":
                            entry["bucket"] = "not_listed"
                            out.append(entry)
                            continue
        else:
            verdict, evidence, note = VERDICT_SKIP, "", "residue_class_unhandled:%s" % kind
        if verdict is not VERDICT_TRUE:
            if "bucket" not in entry:
                entry["bucket"] = "uncited"
                if note:
                    entry["reason"] = note
            out.append(entry)
            continue
        row = {"type": "state", "id": "st-%d-%04d" % (now_ms, seq),
               "state_for": hid, "state": request_thread.STATE_RESOLVED,
               "at": now_ms, "by": RESIDUE_BY, "evidence": evidence,
               "note": "legacy_residue:%s" % note, "surface": SWEEP_SURFACE}
        append_fn(row)
        seq += 1
        entry.update({"bucket": "closed", "evidence": evidence, "note": note,
                      "row_id": row["id"]})
        out.append(entry)
    return out




def evaluate(condition: Dict[str, Any], rows: List[Dict[str, Any]],
             is_green: Callable[[str], Optional[bool]],
             ticket_status_fn: Callable[[str], Optional[Tuple[str, str]]],
             head_at: Optional[int] = None
             ) -> Tuple[Optional[bool], str, str]:
    kind = condition.get("kind")
    if kind == COND_GREEN_CERT_AFTER:
        return eval_green_cert_after(str(condition.get("cert") or ""), rows, is_green)
    if kind == COND_LANDING_ON_LINE:
        return eval_landing_on_line(str(condition.get("ticket") or ""), rows)
    if kind == COND_TICKET_CLOSED:
        return eval_ticket_closed(str(condition.get("ticket") or ""), ticket_status_fn)
    if kind == COND_FREEZE_CLOSED:
        return eval_freeze_closed(str(condition.get("freeze") or ""), rows)
    if kind == COND_ROUND_AFTER:
        return eval_round_after(str(condition.get("line") or ""), rows, head_at)
    return VERDICT_SKIP, "", "condition_kind_unknown:%r" % (kind,)


# ---------- the sweep --------------------------------------------------------

def close_legacy_residue_locked(path: str, ledger_rows: List[Dict[str, Any]],
                                ticket_status_fn: Callable[[str], Optional[Tuple[str, str]]],
                                now_ms: int, seq: int
                                ) -> Tuple[List[Dict[str, Any]], int]:
    """The residue pass as its OWN flock pass over the requests ledger
    (t261026-07): re-reads the rows (the condition pass may have appended
    resolved rows in its pass — those heads are now terminal and skipped), so
    the condition pass's body stays byte-shape-compatible with the merge base
    and the residue insert never collides with another side's tail insert.
    Idempotent by the same terminal-head skip. Returns (entries, next_seq) —
    the seq is threaded back to the caller so the passes can never mint two
    state rows carrying the same id in one sweep (acceptance gen7 finding)."""
    with request_thread._locked_append(path) as fd:
        req_rows, _mal = request_thread._read_rows_unlocked(fd)
        states = request_thread.head_states(req_rows)
        conditions = effective_conditions(req_rows)
        head_rows = {r.get("id"): r for r in req_rows
                     if isinstance(r, dict) and r.get("type") == "request"
                     and isinstance(r.get("id"), str)}
        entries: List[Dict[str, Any]] = []
        counter = {"seq": seq}

        def append_row(row: Dict[str, Any]) -> None:
            request_thread._append_line_unlocked(fd, row)
            counter["seq"] += 1

        entries = close_legacy_residue(
            head_rows, states, conditions, ledger_rows, ticket_status_fn,
            now_ms, counter["seq"], append_row)
        return entries, counter["seq"]


def sweep_project(project_key: str, now_ms: int, seq: int,
                  env: Optional[Dict[str, str]] = None,
                  ledger_rows_fn: Optional[Callable[[], Tuple[Optional[List[Dict[str, Any]]], int, str]]] = None,
                  is_green: Optional[Callable[[str], Optional[bool]]] = None,
                  ticket_status_fn: Optional[Callable[[str], Optional[Tuple[str, str]]]] = None
                  ) -> Dict[str, Any]:
    """One project's sweep: inside the requests ledger's flock, evaluate every
    open head's effective condition against the delivery ledger and append one
    resolved state row per head whose condition now reads true. Skips are
    named in the receipt; terminal heads are untouched. Heads WITHOUT a
    declared condition go through the legacy-residue pass (t261026-07): they
    close only on a CITED subject row, and `finding`/`question` never close.
    The ledger/runs/ticket readers are injectable for tests."""
    env = dict(os.environ if env is None else env)
    key = str(project_key)
    path = str(executor_requests.ledger_file(key, env))
    receipt: Dict[str, Any] = {"ok": True, "project": key, "file": path,
                               "resolved": [], "skipped": [], "unchanged": 0,
                               "residue": [], "malformed_lines": 0}
    if ledger_rows_fn is None:
        def ledger_rows_fn(_key=key, _env=env):
            return load_delivery_ledger(_key, _env)
    if is_green is None:
        is_green = make_runs_green_fn(runs_store_path(key, env))
    if ticket_status_fn is None:
        ticket_status_fn = default_ticket_status_fn
    uses_default_reader = ticket_status_fn is default_ticket_status_fn
    if uses_default_reader:
        # t261026-06: a dead reader is louder than 65 identical per-head skips
        # -- the receipt names the channel once, at the top level. ok stays
        # true (a skip is a named outcome, per the module contract), pinned by
        # the reader regression test.
        global _READER_LAST_ERROR
        _READER_LAST_ERROR = None
        receipt["reader"] = ticket_reader_probe()
    if not os.path.exists(path):
        receipt["unchanged"] = 0
        receipt["note"] = "no_requests_ledger"
        return receipt
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ledger_rows, ledger_malformed, ledger_error = ledger_rows_fn()
    if ledger_rows is None:
        # spec 3: unreadable engine face = skip EVERYTHING, named -- never a
        # silent close and never a fabricated green.
        receipt["skipped_all"] = ledger_error or "ledger_unreadable"
        return receipt
    receipt["malformed_lines"] = ledger_malformed
    # t261026-07: the legacy residue FIRST, as its own flock pass — open heads
    # with no declared condition, closed ONLY on a cited subject row (bound D:
    # a `finding`/`question` never; a not-listed ticket never). Heads it
    # closes read terminal in the condition pass below, and it never touches
    # conditioned heads, so the two passes are independent and idempotent.
    # The seq is threaded back (acceptance gen7 finding): the condition pass
    # starts AFTER the residue's rows, so one sweep can never mint two state
    # rows with the same id.
    receipt["residue"], seq = close_legacy_residue_locked(
        path, ledger_rows, ticket_status_fn, now_ms, seq)
    with request_thread._locked_append(path) as fd:
        req_rows, req_malformed = request_thread._read_rows_unlocked(fd)
        receipt["malformed_lines"] += req_malformed
        states = request_thread.head_states(req_rows)
        conditions = effective_conditions(req_rows)
        head_rows = {r.get("id"): r for r in req_rows
                     if isinstance(r, dict) and r.get("type") == "request"
                     and isinstance(r.get("id"), str)}
        for hid, state in states.items():
            if state != request_thread.STATE_OPEN:
                continue  # terminal OR answered: never touched, never double-resolved
            cond = conditions.get(hid)
            if cond is None:
                continue  # the residue pass below owns unconditioned heads
            checked = validate_resolves_when(cond)
            if not checked.get("ok"):
                receipt["skipped"].append({"id": hid, "reason":
                                           "condition_invalid:%s" % checked.get("error")})
                continue
            head_at = head_rows.get(hid, {}).get("at") \
                if isinstance(head_rows.get(hid, {}).get("at"), int) else None
            verdict, evidence, note = evaluate(checked["condition"], ledger_rows,
                                               is_green, ticket_status_fn,
                                               head_at=head_at)
            if verdict is VERDICT_SKIP:
                receipt["skipped"].append({"id": hid, "reason": note})
                continue
            if verdict is VERDICT_FALSE:
                receipt["unchanged"] += 1
                continue
            row = {"type": "state", "id": "st-%d-%04d" % (now_ms, seq),
                   "state_for": hid, "state": request_thread.STATE_RESOLVED,
                   "at": now_ms, "by": SWEEP_BY, "evidence": evidence,
                   "note": note, "surface": SWEEP_SURFACE}
            request_thread._append_line_unlocked(fd, row)
            seq += 1
            receipt["resolved"].append({"id": hid, "evidence": evidence,
                                        "note": note, "row_id": row["id"]})
    if uses_default_reader and "reader" in receipt and _READER_LAST_ERROR:
        # the probe passed but the channel failed at runtime (spawn / exit /
        # parse / receipt-level refusal): the receipt says so, named
        receipt["reader"]["available"] = False
        receipt["reader"]["error"] = _READER_LAST_ERROR
    return receipt


def sweep_all_projects(now_ms: int, seq: int,
                       env: Optional[Dict[str, str]] = None,
                       **deps: Any) -> Dict[str, Any]:
    """Every project that has a requests ledger. One broken project is a named
    receipt entry, never the sweep's death (the line_round_tick discipline)."""
    env = dict(os.environ if env is None else env)
    root = executor_requests.ledger_root(env)
    out: Dict[str, Any] = {"ok": True, "projects": {}, "resolved_total": 0}
    try:
        keys = sorted(d.name for d in root.iterdir()
                      if d.is_dir() and (d / "requests.jsonl").exists())
    except OSError as e:
        return {"ok": False, "field": "ledger_root",
                "error": "requests ledger root unreadable: %s" % e}
    for key in keys:
        try:
            r = sweep_project(key, now_ms, seq, env=env, **deps)
        except Exception as e:  # noqa: BLE001 — one broken project is an entry
            r = {"ok": False, "project": key,
                 "error": "sweep_failed:%s:%s" % (type(e).__name__, e)}
        out["projects"][key] = r
        out["resolved_total"] += len(r.get("resolved") or [])
    return out


# ---------- CLI ----------

def _cli(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(json.dumps({"ok": False, "field": "body", "error": USAGE}))
        return 2
    try:
        doc = json.loads(argv[0])
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "field": "body",
                          "error": "argument is not valid JSON: %s" % e}))
        return 2
    if not isinstance(doc, dict):
        print(json.dumps({"ok": False, "field": "body",
                          "error": "argument must be a JSON object"}))
        return 2
    import time as _time
    now_ms = int(_time.time() * 1000)
    project = str(doc.get("project") or "")
    if project:
        import shared
        if not shared.PROJECT_KEY_RE.match(project):
            print(json.dumps({"ok": False, "field": "project",
                              "error": "project key shape invalid: %r" % project}))
            return 2
        out = sweep_project(project, now_ms, 1)
    else:
        out = sweep_all_projects(now_ms, 1)
    # 261020: same dynamic-payload exit rule as every other receipt printer — a
    # lone surrogate in a request row must not take the whole receipt down.
    print(json.dumps(out, ensure_ascii=False)
          .encode("utf-8", "backslashreplace").decode("utf-8"))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
