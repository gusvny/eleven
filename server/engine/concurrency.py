"""concurrency — project-level running-ticket limit (ticket t261004-32, CL-1 engine half).

Design source: the 261004 concurrency-limit design page §3/§5 and the
concurrency-limit epic proposal (notes/epics/concurrency-limit.md). One project runs at most N tickets; a ticket
that does not get a slot WAITS in a queue; the limit never becomes a
machine-wide cap; the panel only reads the queue (it never recomputes it).

Declaration (rule 7): <projects_root>/<key>/concurrency-limit.json — the same
machine-level per-key family as executor-grants.json (root =
shared.perkey_projects_root()). Schema: {"version":1,"limit": 1..10 | "unlimited"}.

Fail-closed (rule 9): a missing / unreadable / malformed / wrong-version /
out-of-range declaration raises a named ValueError quoting the file path — it
must never degrade to "unlimited" and never silently default to 3. The default
3 lives where the host writes it (the shipped declaration template / the CL-2
panel's first Save), not in this loader.

Take-or-leave table vs the executor-grants loader (executor_grants.py), per the
plan-review checklist:
  absent        -> grants: normalized-empty default behaviors vary by caller.
                   LEAVE. Here: named refusal (rule 9 wins).
  unreadable    -> grants: error string. TAKE: named ValueError quoting path.
  malformed     -> grants: "malformed: ..." error. TAKE: same wording style.
  wrong-version -> grants: refusal, version must be 1. TAKE: identical rule.
  out-of-range  -> grants: per-key validation. TAKE: named refusal (limit must
                   be int 1..10 or the string "unlimited"; "3"/0/11/null refuse).
  audit "by"    -> grants/KI-193: `by` is engine-observed, never
                   caller-trusted. TAKE: record_limit_change refuses an empty
                   engine-side `by` and never echoes caller input as authority.

Slot accounting (decided, tested — see tests/test_t261004_32_concurrency.py):
the slot unit is the ticket's lane run. Lifetime = acquired before the first
stage starts, released for real at two points: the ticket is paused, and the
ticket terminates. The other two rule points (stage end, human-gate
transition) are ATOMIC RENEWALS: the holder record's reason is rewritten in the
same locked step (running <-> human-hold). There is deliberately no
between-stages window: a continuing ticket never loses its slot to a queued
ticket, so no mid-lane demotion race exists; acquire() on an already-holding
ticket is immediate. A human-gate ticket keeps its slot on purpose (rule 3);
after the signature it continues without re-queueing. The 60 s re-poll backstop
in the workflow gate protects WAITERS (a missed promotion resolves within one
poll); it is NOT leak protection — a holder whose workflow died mid-stage is
cleared by `ticket.py {"op":"concurrency","reconcile":true}` (named output).

State file: <projects_root>/<key>/concurrency-state.json, guarded by a sibling
concurrency-state.lock (fcntl.flock) so claim/release/read are atomic across
processes (workers, CLI, panel). A malformed state file is itself a named
refusal — never treated as empty. Queue entries carry `since`; waited seconds
are computed at read time; queue order is the panel-orderable order (CL-3
writes it via reorder(); the engine consumes it as-is, FIFO by default).
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import shared

DECL_FILE = "concurrency-limit.json"
STATE_FILE = "concurrency-state.json"
LOCK_SUFFIX = ".lock"
AUDIT_FILE = "concurrency-limit-audit.jsonl"
DECL_VERSION = 1
STATE_VERSION = 1
MIN_LIMIT = 1
MAX_LIMIT = 10
UNLIMITED = "unlimited"
# release/renew cause vocabulary — the four rule points, exactly.
CAUSE_STAGE_END = "stage-end"
CAUSE_TERMINATED = "terminated"
CAUSE_HUMAN_GATE = "human-gate"
CAUSE_PAUSED = "paused"
REASON_RUNNING = "running"
REASON_HUMAN_HOLD = "human-hold"

# Project key validation mirrors the registry whitelist (shared.PROJECT_KEY_RE)
# — an invalid key must refuse before any file is touched.
_PROJECT_KEY_RE = getattr(shared, "PROJECT_KEY_RE", None)


def declaration_path(key: str) -> str:
    return os.path.join(str(shared.perkey_projects_root()), str(key), DECL_FILE)


def state_path(key: str) -> str:
    return os.path.join(str(shared.perkey_projects_root()), str(key), STATE_FILE)


def audit_path(key: str) -> str:
    return os.path.join(str(shared.perkey_projects_root()), str(key), AUDIT_FILE)


def _check_key(key: str) -> str:
    k = str(key or "").strip()
    if not k:
        raise ValueError("Concurrency limit: empty project key - the declaration is "
                         "judged per project, an empty key is refused (decl root=%s)"
                         % shared.perkey_projects_root())
    if _PROJECT_KEY_RE is not None and not _PROJECT_KEY_RE.match(k):
        raise ValueError("Concurrency limit: project key %r fails the registry "
                         "whitelist (PROJECT_KEY_RE) - refused" % k)
    return k


# ---------- declaration loading (fail-closed, named refusals) ----------

def validate_limit(value: Any, path: str = DECL_FILE) -> Optional[int]:
    """Validate the declared limit. Returns None for unlimited, else int 1..10.
    Raises a named ValueError on anything else (rule 9). `path` is quoted so a
    multi-project machine can tell WHICH declaration is broken."""
    where = "（decl=%s）" % path
    if value == UNLIMITED:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "Malformed concurrency-limit declaration: %s limit must be an int "
            "%d..%d or the string %r (got %r) - refused, never a silent "
            "unlimited%s"
            % (path, MIN_LIMIT, MAX_LIMIT, UNLIMITED, value, where))
    if not (MIN_LIMIT <= value <= MAX_LIMIT):
        raise ValueError(
            "Out-of-range concurrency-limit declaration: %s limit=%r not in "
            "%d..%d - refused, never a silent unlimited%s"
            % (path, value, MIN_LIMIT, MAX_LIMIT, where))
    return int(value)


def load_limit(project_key: str) -> Optional[int]:
    """Read the project's declared limit. None = unlimited. Any missing /
    unreadable / malformed declaration raises a named ValueError (never a
    silent unlimited, never a silent default)."""
    k = _check_key(project_key)
    # Identity anchor = the declaration file itself (fail-closed on absence).
    # Deliberately NOT coupled to the project registry: the limit lives in the
    # project's own machine-level declaration, and every consumer of this
    # module (workflow gate, CLI, panel) addresses the project by key — a
    # missing declaration is already a named refusal below.
    path = declaration_path(k)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        raise ValueError(
            "Concurrency-limit declaration absent: %s does not exist - "
            "fail-closed refusal (never a silent unlimited; the limit is an "
            "explicit declaration, a missing file means the machine cannot "
            "know its cap)" % path)
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(
            "Concurrency-limit declaration unreadable: %s (%s: %s) - "
            "fail-closed refusal" % (path, type(e).__name__, e))
    except json.JSONDecodeError as e:
        raise ValueError(
            "Malformed concurrency-limit declaration: %s is not valid JSON "
            "(%s) - fail-closed refusal" % (path, e))
    if not isinstance(doc, dict):
        raise ValueError(
            "Malformed concurrency-limit declaration: %s top level must be a "
            "JSON object (got %s) - refused"
            % (path, type(doc).__name__))
    if doc.get("version") != DECL_VERSION:
        raise ValueError(
            "Concurrency-limit declaration version mismatch: %s version must "
            "be %d (got %r) - refused"
            % (path, DECL_VERSION, doc.get("version")))
    if "limit" not in doc:
        raise ValueError(
            "Concurrency-limit declaration missing the limit key: %s - "
            "refused (a missing key is not unlimited)" % path)
    limit = validate_limit(doc.get("limit"), path)
    if limit is None:
        return None
    return limit


def record_limit_change(project_key: str, by: str, old: Any, new: Any) -> Dict[str, Any]:
    """Append one audit line for a limit change (the CL-2 knob calls this).
    KI-193 discipline: `by` is the engine-observed identity — an empty `by`
    refuses; this module never accepts a caller-asserted authority token."""
    k = _check_key(project_key)
    who = str(by or "").strip()
    if not who:
        raise ValueError("Concurrency-limit audit refused: empty by (the actor "
                         "identity is required; KI-193: by is never a "
                         "caller-asserted trusted value)")
    row = {"ts": time.time(), "project": k, "by": who,
           "from": old, "to": new}
    path = audit_path(k)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ---------- the CL-2b write face (panel knob -> engine entry) ----------

def _declared_limit(value: Any) -> Any:
    """Validate a write-payload limit and return the value as DECLARED (int,
    or the string "unlimited"). One validation copy: everything routes through
    validate_limit (bool / 0 / out-of-range / "3" / 5.5 / null refuse by name
    there); this wrapper only maps the unlimited word so the declaration file
    stores exactly what load_limit reads back ("unlimited"), never a null."""
    if isinstance(value, str) and value.strip() == UNLIMITED:
        return UNLIMITED
    return validate_limit(value, "payload limit")


def set_limit(payload: Any) -> Dict[str, Any]:
    """Write one project's concurrency-limit declaration (CL-2b: the engine
    entry the panel spawns, `client.py concurrency-limit-write '<payload>'`).

    Contract (pinned by the panel parser parseConcurrencySaveReceipt and the
    landed scenario t261006-17-concurrency-save-gate — do not reshape):
      receipt = {"saved": True, "project": k, "limit": <declared>,
                 "audit_row": <the row appended to the audit file>, "decl": <path>}
      refusal = {"saved": False, "reason": <named>}
    Zero side effect on refusal: every judgment happens BEFORE any byte lands;
    if the audit append fails after the declaration was replaced, the previous
    declaration bytes are restored (rollback) and the receipt refuses by name.

    Fail-closed, named refusals: payload not an object / malformed project /
    non-integer, out-of-range or missing limit / missing or empty `by` /
    non-object `source`. Unknown extra keys (e.g. the scenario probe's
    caller_project) are ignored. The audit actor IS the payload `by` — the
    engine never invents one (KI-193: the panel fixes by to the credential-
    proven 'host' before spawning). First Save on a project with no
    declaration yet is legal (design: the default lives where the host writes
    it, i.e. this entry); `from` is null on that path.

    Enforcement semantics need NO new code here: lowering the limit never
    touches holders (a holder keeps its slot until a real release point —
    existing acquire/release rule); raising the limit lets the queue drain
    through the existing release/reconcile promotion and the 60 s re-poll
    backstop, both of which re-read load_limit per event.
    """
    try:
        if not isinstance(payload, dict):
            raise ValueError(
                "Concurrency-limit write refused: payload must be a JSON "
                "object {project, limit, by, source?} (got %s) - nothing "
                "written" % type(payload).__name__)
        k = _check_key(payload.get("project"))
        by = payload.get("by")
        if isinstance(by, bool) or not isinstance(by, str) or not by.strip():
            raise ValueError(
                "Concurrency-limit write refused: by must be a non-empty "
                "string naming the actor (the audit row's `by` is the payload "
                "value, never engine-invented) - nothing written")
        who = by.strip()
        if "limit" not in payload:
            raise ValueError(
                "Concurrency-limit write refused: the limit key is missing "
                "(a missing key is not unlimited) - nothing written")
        declared = _declared_limit(payload.get("limit"))
        source = payload.get("source")
        if source is not None and not isinstance(source, dict):
            raise ValueError(
                "Concurrency-limit write refused: source must be a JSON "
                "object when present (got %s) - nothing written"
                % type(source).__name__)
        path = declaration_path(k)
        try:
            old = load_limit(k)
        except ValueError:
            old = None   # first Save: no declaration exists yet
        try:
            with open(path, "r", encoding="utf-8") as f:
                prev_bytes = f.read()
        except FileNotFoundError:
            prev_bytes = None
        # Atomic declaration write (first Save creates the key dir).
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": DECL_VERSION, "limit": declared}, f,
                      ensure_ascii=False)
        os.replace(tmp, path)
        try:
            row = record_limit_change(k, who, old, declared)
        except BaseException:
            # The audit row is part of the contract: a save without it is
            # exactly the KI-198 family ("writer says saved, reader sees no
            # change"), so roll the declaration back and refuse by name.
            try:
                if prev_bytes is None:
                    os.remove(path)
                else:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(prev_bytes)
            except OSError as rb_err:
                raise ValueError(
                    "Concurrency-limit write FAILED AFTER the declaration was "
                    "replaced: the audit append refused and the rollback of "
                    "%s also failed (%s: %s) - the file is now out of "
                    "contract, inspect by hand"
                    % (path, type(rb_err).__name__, rb_err))
            raise
        return {"saved": True, "project": k, "limit": declared,
                "audit_row": {"ts": row["ts"], "by": row["by"],
                              "from": row["from"], "to": row["to"]},
                "decl": path}
    except ValueError as e:
        return {"saved": False, "reason": str(e)}
    except OSError as e:
        # A declaration/audit filesystem failure after the judgment phase: the
        # rollback above has restored (or named its own failure), so this is a
        # named refusal, never a partial save reported as success.
        return {"saved": False,
                "reason": "Concurrency-limit write failed on the filesystem "
                          "(%s: %s) - declaration rolled back, nothing "
                          "changed" % (type(e).__name__, e)}


# ---------- slot ledger (lock-guarded, single state file) ----------

@dataclass
class AcquireArgs:
    project: str
    ticket: str
    priority: bool = False   # period tickets jump the queue head (CL-4 face)


@dataclass
class ReleaseArgs:
    project: str
    ticket: str
    cause: str               # one of the CAUSE_* four points


def _queue_pos(entries: List[Dict[str, Any]], ticket: str) -> int:
    for i, e in enumerate(entries):
        if e.get("ticket") == ticket:
            return i + 1
    return 0


def _read_state_unlocked(root: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(root, STATE_FILE), "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return {"version": STATE_VERSION, "holders": [], "queue": []}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(
            "Concurrency slot ledger unreadable/malformed: %s (%s: %s) - "
            "fail-closed refusal, never treated as an empty ledger"
            % (os.path.join(root, STATE_FILE), type(e).__name__, e))
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION \
            or not isinstance(doc.get("holders"), list) \
            or not isinstance(doc.get("queue"), list):
        raise ValueError(
            "Concurrency slot ledger shape broken: %s (version/holders/queue "
            "missing or wrong type) - fail-closed refusal"
            % os.path.join(root, STATE_FILE))
    return doc


def _face(doc: Dict[str, Any], now: float) -> Dict[str, Any]:
    holders = [{"ticket": h.get("ticket"), "since": h.get("since"),
                "reason": h.get("reason"),
                "held_s": round(now - float(h.get("since") or now), 3)}
               for h in doc.get("holders", [])]
    queue = [{"ticket": e.get("ticket"), "position": i + 1,
              "since": e.get("since"),
              "waited_s": round(now - float(e.get("since") or now), 3)}
             for i, e in enumerate(doc.get("queue", []))]
    return {"holders": holders, "queue": queue}


def _locked(root: str):
    """Context manager yielding the state doc; writes back on clean exit."""
    class _Guard:
        def __init__(self):
            self.doc: Dict[str, Any] = {}
            self._fh = None

        def __enter__(self):
            os.makedirs(root, exist_ok=True)
            self._fh = open(os.path.join(root, STATE_FILE + LOCK_SUFFIX), "a+")
            try:
                fcntl.flock(self._fh, fcntl.LOCK_EX)
                self.doc = _read_state_unlocked(root)
            except BaseException:
                # A named refusal while reading the ledger (malformed state) must not leak
                # the lock - the next fd in the same process would deadlock on its
                # own flock (flock conflicts are judged per open file description).
                fcntl.flock(self._fh, fcntl.LOCK_UN)
                self._fh.close()
                raise
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    tmp = os.path.join(root, STATE_FILE + ".tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(self.doc, f, ensure_ascii=False)
                    os.replace(tmp, os.path.join(root, STATE_FILE))
            finally:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
                self._fh.close()
            return False

    return _Guard()


def acquire(project_key: str, ticket: str, priority: bool = False) -> Dict[str, Any]:
    """Judge the slot BEFORE a stage starts (rule 1). FIFO from the queue head;
    an already-holding ticket is granted immediately (renew semantics); a
    priority ticket (period ticket, CL-4) enters at the queue head but never
    exceeds the limit."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    if not t:
        raise ValueError("Concurrency slot acquire refused: empty ticket id")
    limit = load_limit(k)
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    with _locked(root) as g:
        doc = g.doc
        holders = doc["holders"]
        queue = doc["queue"]
        held = next((h for h in holders if h.get("ticket") == t), None)
        if held is not None:
            return {"granted": True, "already_holding": True,
                    "reason": held.get("reason"), "position": 0,
                    "limit": limit, "holders": len(holders),
                    "waiting": len(queue)}
        if not any(e.get("ticket") == t for e in queue):
            entry = {"ticket": t, "since": now}
            if priority:
                queue.insert(0, dict(entry))
            else:
                queue.append(dict(entry))
        pos = _queue_pos(queue, t)
        unlimited = limit is None
        room = unlimited or len(holders) < limit
        if room and pos == 1:
            queue.pop(0)
            holders.append({"ticket": t, "since": now, "reason": REASON_RUNNING})
            return {"granted": True, "already_holding": False, "position": 0,
                    "limit": limit, "holders": len(holders), "waiting": len(queue)}
        return {"granted": False, "already_holding": False, "position": pos,
                "limit": limit, "holders": len(holders), "waiting": len(queue)}


def renew(project_key: str, ticket: str, reason: str) -> Dict[str, Any]:
    """Atomic holder-record refresh at a rule-2 point that does NOT free the
    slot: stage end (reason -> running) and the human-gate transition
    (reason -> human-hold, rule 3: the human gate eats the slot on purpose).
    No window is opened; a queued ticket cannot be promoted here."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    if reason not in (REASON_RUNNING, REASON_HUMAN_HOLD):
        raise ValueError("Concurrency ledger renew refused: reason must be "
                         "%r|%r (got %r)"
                         % (REASON_RUNNING, REASON_HUMAN_HOLD, reason))
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    with _locked(root) as g:
        doc = g.doc
        held = next((h for h in doc["holders"] if h.get("ticket") == t), None)
        if held is None:
            # Not holding: the ticket must queue like anyone else (e.g. resumed
            # from a pause into an over-limit project).
            return {"renewed": False, "holding": False}
        held["reason"] = reason
        held["since"] = now
        return {"renewed": True, "holding": True, "reason": reason}


def release(project_key: str, ticket: str, cause: str) -> Dict[str, Any]:
    """Release the slot at a real release point (paused / terminated) and
    promote the queue head if the freed slot covers it. Idempotent: releasing
    a ticket that holds nothing is a no-op receipt, not an error.

    `human-gate` is deliberately NOT a freeing cause (rule 3: the human gate
    HOLDS its slot — design defect finding #1 of the t261004-32 test-design
    stage): that rule point is an atomic renew (see renew/CAUSE_HUMAN_GATE),
    never a release. Refused here by name so a mis-wired call site is loud."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    if cause not in (CAUSE_TERMINATED, CAUSE_PAUSED):
        raise ValueError(
            "Concurrency slot release refused: cause %r is not in the real-"
            "release vocabulary (terminated|paused) - human-gate is an atomic "
            "renew (the human gate eats the slot on purpose), never a release "
            "point" % cause)
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    with _locked(root) as g:
        doc = g.doc
        before = len(doc["holders"])
        doc["holders"] = [h for h in doc["holders"] if h.get("ticket") != t]
        doc["queue"] = [e for e in doc["queue"] if e.get("ticket") != t]
        released = len(doc["holders"]) < before
        promoted = None
        limit = load_limit(k)
        room = limit is None or len(doc["holders"]) < limit
        if room and doc["queue"]:
            head = doc["queue"].pop(0)
            doc["holders"].append({"ticket": head.get("ticket"),
                                   "since": now, "reason": REASON_RUNNING})
            promoted = head.get("ticket")
        return {"released": released, "cause": cause, "promoted": promoted,
                "holders": len(doc["holders"]), "waiting": len(doc["queue"])}


def reorder(project_key: str, order: List[str]) -> Dict[str, Any]:
    """Write the panel's manual queue order (CL-3). `order` must be a
    permutation of the current queue (the panel reads the queue first; the
    engine never invents or drops entries)."""
    k = _check_key(project_key)
    root = os.path.join(str(shared.perkey_projects_root()), k)
    want = [str(t) for t in (order or [])]
    with _locked(root) as g:
        doc = g.doc
        cur = [e.get("ticket") for e in doc["queue"]]
        if sorted(want) != sorted(cur):
            raise ValueError(
                "Concurrency queue reorder refused: the given order is not a "
                "permutation of the current queue (current=%s got=%s)"
                % (cur, want))
        by_t = {e.get("ticket"): e for e in doc["queue"]}
        doc["queue"] = [dict(by_t[t]) for t in want]
        return {"queue": [e.get("ticket") for e in doc["queue"]]}


def read_state(project_key: str) -> Dict[str, Any]:
    """Read-only face for the panel (rule 8): limit, holders, queue with
    1-based positions and waited seconds. The panel renders this; it never
    recomputes the queue."""
    k = _check_key(project_key)
    limit = load_limit(k)
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    # Read under the same lock so holders+queue are one consistent snapshot.
    with _locked(root) as g:
        face = _face(g.doc, now)
    face.update({"project": k, "limit": limit,
                 "unlimited": limit is None,
                 "decl": declaration_path(k)})
    return face


def reconcile(project_key: str, alive_tickets: Iterable[str],
              draining_tickets: Iterable[str] = (),
              unknown_tickets: Iterable[str] = ()) -> Dict[str, Any]:
    """Drop holders whose workflows are gone (crash-path leak janitor, review
    item 5). `alive_tickets` is the caller-verified set of live ticket ids
    (ticket.py checks Temporal per holder). `draining_tickets` (t261009-74)
    is the caller-verified set of holders whose dedicated worker process is
    alive but stopped polling (graceful drain); `unknown_tickets` is the set
    whose liveness could not be proven (transient probe errors, unreadable
    pidfile/meta). Neither keeps-to-drop: the slot is a fact about a lane
    that still holds work, so draining AND unknown holders KEEP their slot —
    only `dead` is a zombie, and fail-closed means "do not drop on unknown".
    Callers omitting the arguments keep today's behavior. Promotion follows
    in the same locked step. Named output: exactly which stale holders were
    dropped, and which holders are draining."""
    k = _check_key(project_key)
    alive = {str(t) for t in (alive_tickets or ())}
    draining = {str(t) for t in (draining_tickets or ())} - alive
    unknown = {str(t) for t in (unknown_tickets or ())} - alive - draining
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    dropped: List[str] = []
    with _locked(root) as g:
        doc = g.doc
        keep = [h for h in doc["holders"] if h.get("ticket") in alive
                or h.get("ticket") in draining or h.get("ticket") in unknown]
        dropped = [h.get("ticket") for h in doc["holders"]
                   if h.get("ticket") not in alive
                   and h.get("ticket") not in draining
                   and h.get("ticket") not in unknown]
        doc["holders"] = keep
        promoted = None
        limit = load_limit(k)
        room = limit is None or len(doc["holders"]) < limit
        if room and doc["queue"]:
            head = doc["queue"].pop(0)
            doc["holders"].append({"ticket": head.get("ticket"),
                                   "since": now, "reason": REASON_RUNNING})
            promoted = head.get("ticket")
        return {"dropped": dropped, "promoted": promoted,
                "draining": [h.get("ticket") for h in doc["holders"]
                             if h.get("ticket") in draining],
                "holders": len(doc["holders"]), "waiting": len(doc["queue"])}


# ---------- Temporal activities (registered by worker.py) ----------
# Thin wrappers only; all decisions live in the functions above so unit tests
# exercise the real logic without a Temporal backend. They never swallow the
# named refusals: a declaration failure propagates and fails the workflow
# task loudly (rule 9 — fail closed at the gate, not inside a stage).
#
# temporalio is a guarded import: server/tools/ticket.py loads this module by
# file path on the plain host python (no engine venv) for the read/reconcile
# face — there the activity wrappers simply do not exist, the ledger functions
# above are the whole surface.

try:
    from temporalio import activity  # noqa: E402
except ImportError:  # pragma: no cover — stdlib-only consumer face (ticket.py)
    activity = None

if activity is not None:
    @activity.defn
    async def concurrency_acquire(args: AcquireArgs) -> Dict[str, Any]:
        return acquire(args.project, args.ticket, priority=bool(args.priority))

    @activity.defn
    async def concurrency_release(args: ReleaseArgs) -> Dict[str, Any]:
        return release(args.project, args.ticket, cause=args.cause)

    @activity.defn
    async def concurrency_renew(args: ReleaseArgs) -> Dict[str, Any]:
        reason = REASON_HUMAN_HOLD if args.cause == CAUSE_HUMAN_GATE else REASON_RUNNING
        return renew(args.project, args.ticket, reason)

    CONCURRENCY_ACTIVITIES = (concurrency_acquire, concurrency_release,
                              concurrency_renew)
else:  # pragma: no cover
    CONCURRENCY_ACTIVITIES = ()
