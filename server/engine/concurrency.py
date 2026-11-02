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
stage starts, released for real at these points: the ticket is paused, the
ticket terminates, the ticket enters the MERGE human gate (t261022, host order
261022 — a ticket waiting for the merge signature would otherwise starve the
queue: seven merge-waiting tickets held all ten slots for hours), and the
ticket parks in a stage that cannot progress without an outside act (t261031-26
— `blocked` / `awaiting-human`: three of four slots were held by blocked
tickets in 261031 while two signed merges queued for half an hour). The
remaining rule points (stage end, the human-gate transition of every stage that
still CAN progress by itself) are ATOMIC RENEWALS: the holder record's reason
is rewritten in the same locked step (running <-> human-hold). There is
deliberately no between-stages window: a continuing ticket never loses its slot
to a queued ticket, so no mid-lane demotion race exists; acquire() on an
already-holding ticket is immediate, and a ticket that left a parked wait takes
its place in the ordinary FIFO queue again (it never jumps). The 60 s re-poll
backstop in the workflow gate protects WAITERS (a missed promotion resolves
within one poll); it is NOT leak protection — a holder whose workflow died
mid-stage is cleared by `ticket.py {"op":"concurrency","reconcile":true}`
(named output).

Merge claims (t261031-26, second half): the MERGE STEP itself holds no WORK
slot. It is a short engine activity (a squash + a commit), it starts no agent
session, so the resource the project limit protects is not in play; and putting
it in the work queue deadlocked the whole project (measured 261031: the freeze
that blocked the merge-waiting holders could only be lifted by a green line
round, and that round needed a signed merge to land — the queue was waiting on
itself). A signed merge therefore takes a MERGE CLAIM from the lists below:
visible on the ledger face (`merge_claims`), never counted against the work
limit, and never queued behind a work holder or a parked ticket. The claim
window is exactly the merge activity; a blocking or terminating end releases it
through the ordinary release path.
#
# t261019-31 (KI-01M533EHPA0AYQ2Y2GCNGXS4SD): the terminal-ending leak has two
# structural closes — (a) the engine-side cancel/terminate/close-out entries in
# client.py release the slot by name (CAUSE_TERMINATED) right after the
# workflow dies (host-side code survives the kill); (b) a stale-holder backstop
# in acquire (HOLDER_STALE_S, RUNNING holders only) mirrors the queue-corpse
# sweep for kills that bypass every client.py entry. An over-limit holder count
# is named on both faces (over_limit_face) — never a silent 12/7.

State file: <projects_root>/<key>/concurrency-state.json, guarded by a sibling
concurrency-state.lock (fcntl.flock) so claim/release/read are atomic across
processes (workers, CLI, panel). A malformed state file is itself a named
refusal — never treated as empty. Queue entries carry `since`; waited seconds
are computed at read time; queue order is the panel-orderable order (CL-3
writes it via reorder(); the engine consumes it as-is, FIFO by default).
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import threading
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
# release/renew cause vocabulary — the rule points, exactly.
CAUSE_STAGE_END = "stage-end"
CAUSE_TERMINATED = "terminated"
CAUSE_HUMAN_GATE = "human-gate"
CAUSE_PAUSED = "paused"
#: t261022 (host order 261022): the MERGE human gate hands the slot back while it
#: waits for the signature — a merge-waiting ticket is not doing work, so holding
#: the slot starves the queue (measured: 7 waiting tickets held all 10 slots for
#: hours while the delivery line was frozen). Its own cause word (never `paused`,
#: never `human-gate`) so the ledger, the panel face and the ticket log can tell a
#: merge-wait release from a zombie holder. t261031-26 generalised the rule to
#: every parked state (CAUSE_BLOCKED_WAIT below); the renew word
#: CAUSE_HUMAN_GATE now belongs only to stages that can still progress by
#: themselves (the quickmanual lane's parked work stage).
CAUSE_MERGE_WAIT = "merge-wait"
#: t261031-26 (KI-441 / KI-443 root cause): a ticket parked in
#: `stage_state=blocked` or `awaiting-human` CANNOT progress without an outside
#: act (a retry_qc, a rework, a signature, a remedy). Holding capacity there
#: protects nothing and starves the work that can progress - measured 261031:
#: three of four slots held by blocked tickets while two human-signed merges sat
#: in the queue for over half an hour, and the freeze that blocked two of the
#: three could only be lifted by a line round that needed one of those merges.
#: Its own cause word, because `paused` (an operator act) and `terminated` (an
#: ending) would both be lies here; `merge-wait` stays reserved for the merge
#: signature wait (t261022) so the two parked faces stay distinguishable.
#: Leaving the parked state is an ORDINARY acquire: the ticket queues behind
#: whoever is already waiting (it never jumps back in).
CAUSE_BLOCKED_WAIT = "blocked-wait"
#: t261103-05 (docs/design/github-pr-flow-v1.md step (b)): a ticket parked in
#: `stage_state=awaiting-remote-review` waits for a platform review, not for a
#: person at this console, and it does no work of its own - so it holds no slot.
#: Its own cause word keeps the ledger truthful about WHERE it waits (never
#: `blocked-wait`, which means "waiting for an act at this console", and never
#: `merge-wait`, which means "waiting for the merge signature"). It parks on the
#: existing `blocked_wait` face, which already records cause + stage: no new
#: ledger face is invented.
CAUSE_REMOTE_REVIEW_WAIT = "remote-review-wait"
REASON_RUNNING = "running"
REASON_HUMAN_HOLD = "human-hold"
#: The ledger lists that record a ticket WITHOUT holding a slot. They exist so a
#: reader can tell "released on purpose, waiting for something outside the
#: engine" from a leaked holder row (a zombie). None of them is ever counted by
#: the limit arithmetic, and none of them is a second holder list:
#:   merge_wait  - parked at the MERGE human gate, waiting for a signature
#:                 (t261022; the release cause is `merge-wait`).
#:   blocked_wait- parked in `blocked` / `awaiting-human`, waiting for an outside
#:                 act (t261031-26; the release cause is `blocked-wait`).
#:   merge_claims- running the merge step under a MERGE CLAIM (t261031-26): no
#:                 work slot, never queued behind work.
PARKED_FACES = ("merge_wait", "blocked_wait", "merge_claims")

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
    cause: str               # one of the CAUSE_* release points
    #: t261031-26: the stage the ticket parked in, recorded on the
    #: `blocked_wait` face so the release receipt names where the wait happened.
    #: Empty when the caller has no stage (pause/terminal releases).
    stage: str = ""


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
        fresh = {"version": STATE_VERSION, "holders": [], "queue": []}
        for face in PARKED_FACES:
            fresh[face] = []
        return fresh
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
    # Optional parked faces (t261022 merge-wait, t261031-26 blocked-wait and
    # merge claims). A ledger written before they existed simply has no key -
    # that is an empty face, never a malformed one. Any other shape is a named
    # refusal (the same fail-closed stance as holders/queue above): a face this
    # module cannot read must never be silently treated as absent.
    for face in PARKED_FACES:
        if face not in doc:
            doc[face] = []
        elif not isinstance(doc[face], list):
            raise ValueError(
                "Concurrency slot ledger face broken: %s key %r must be a list "
                "(got %s) - fail-closed refusal, never read as an empty face"
                % (os.path.join(root, STATE_FILE), face,
                   type(doc[face]).__name__))
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
    # t261022: tickets waiting at the MERGE gate with no slot. Named on the face
    # so the panel can tell "released on purpose, waiting for a signature" from
    # a holder that leaked — this list is never a holder list.
    merge_wait = [{"ticket": e.get("ticket"), "since": e.get("since"),
                   "waiting_s": round(now - float(e.get("since") or now), 3)}
                  for e in doc.get("merge_wait", [])
                  if isinstance(e, dict)]
    # t261031-26: the same face for a ticket parked in `blocked` /
    # `awaiting-human` — the receipt says who released, why (the cause word),
    # and at which stage, so the wait is auditable instead of being an
    # unexplained empty slot.
    blocked_wait = [{"ticket": e.get("ticket"), "since": e.get("since"),
                     "waiting_s": round(now - float(e.get("since") or now), 3),
                     "cause": e.get("cause") or CAUSE_BLOCKED_WAIT,
                     "stage": e.get("stage") or ""}
                    for e in doc.get("blocked_wait", [])
                    if isinstance(e, dict)]
    # t261031-26: merges in flight. Not holders: they consume no work slot.
    merge_claims = [{"ticket": e.get("ticket"), "since": e.get("since"),
                     "held_s": round(now - float(e.get("since") or now), 3)}
                    for e in doc.get("merge_claims", [])
                    if isinstance(e, dict)]
    return {"holders": holders, "queue": queue, "merge_wait": merge_wait,
            "blocked_wait": blocked_wait, "merge_claims": merge_claims}


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
        # t261022: taking the gate again (or queueing for it) means the ticket
        # has LEFT the merge gate — its merge-wait face entry is dropped here so
        # the panel never sees a stale "waiting for a signature" record.
        if any(isinstance(e, dict) and e.get("ticket") == t
               for e in doc.get("merge_wait", [])):
            doc["merge_wait"] = [e for e in doc.get("merge_wait", [])
                                 if not (isinstance(e, dict) and e.get("ticket") == t)]
        # t261031-26: the same discipline for the blocked-wait face — taking the
        # gate again means the parked wait is over, and the receipt NAMES the wait
        # it replaces (who released, why, when). The caller logs that line on the
        # ticket face, so both halves of the round trip (release, re-acquire) are
        # readable instead of the slot silently coming back.
        reacquired_from: Optional[Dict[str, Any]] = None
        for e in doc.get("blocked_wait", []):
            if isinstance(e, dict) and e.get("ticket") == t:
                reacquired_from = {"cause": e.get("cause") or CAUSE_BLOCKED_WAIT,
                                   "since": e.get("since"),
                                   "stage": e.get("stage") or ""}
                break
        if reacquired_from is not None:
            doc["blocked_wait"] = [e for e in doc.get("blocked_wait", [])
                                   if not (isinstance(e, dict)
                                           and e.get("ticket") == t)]
        held = next((h for h in holders if h.get("ticket") == t), None)
        if held is not None:
            # t261019-31: the already-holding early return is also the holder
            # HEARTBEAT — every stage start re-acquires, so refreshing `since`
            # here (atomic, same locked step) is what lets the stale-holder
            # sweep tell a live running holder from a corpse. A human-hold
            # holder is exempt from the sweep by design (its hold needs no
            # heartbeat); refreshing `since` is still correct bookkeeping.
            held["since"] = now
            return {"granted": True, "already_holding": True,
                    "reason": held.get("reason"), "position": 0,
                    "limit": limit, "holders": len(holders),
                    "waiting": len(queue),
                    "reacquired_from": reacquired_from}
        if not any(e.get("ticket") == t for e in queue):
            entry = {"ticket": t, "since": now}
            if priority:
                queue.insert(0, dict(entry))
            else:
                queue.append(dict(entry))
        else:
            # 261019: the entry's `since` is a HEARTBEAT, not "queued at".
            # A waiter re-polls on its backoff, so refreshing here is what
            # lets a promoter tell a live waiter from a corpse (QUEUE_STALE_S).
            for e in queue:
                if e.get("ticket") == t:
                    e["since"] = now
        # Clear corpses ahead of this waiter, so a dead head can never block
        # the queue for the hours it takes somebody to notice (261019: four
        # dead heads blocked nine live tickets).
        dropped_stale: List[str] = []
        if any(_is_stale(e, now) and e.get("ticket") != t for e in queue):
            kept = []
            for e in queue:
                if e.get("ticket") != t and _is_stale(e, now):
                    dropped_stale.append(e.get("ticket"))
                else:
                    kept.append(e)
            doc["queue"] = queue = kept
        pos = _queue_pos(queue, t)
        unlimited = limit is None
        # The room judgement uses the PRE-sweep holder count: acquire never
        # grants on holders it is itself about to condemn (the t261019-29
        # contract, main-green — its fixtures seed long-idle holders and pin
        # the refusal). The sweep still runs and names its drops; the freed
        # slot serves this waiter on its NEXT poll, bounded by the waiter's
        # declared backoff (5 s..120 s) — a bounded one-poll delay instead of
        # a same-call jackpot.
        room = unlimited or len(holders) < limit
        # t261019-31: sweep stale RUNNING holders in the same locked step.
        # HUMAN-HOLD holders are NEVER judged HERE — a gate waiter does not
        # re-acquire until after the signature, so it has no heartbeat by
        # design, and its hold is deliberate (rule 3); this heartbeat sweep
        # must never release it, whatever its age. (t261027-10: the
        # proof-of-death sweep judges by workflow liveness instead, and a
        # TERMINATED human-hold holder does lose its slot there.)
        dropped_stale_holders: List[str] = []
        if any(_holder_is_stale(h, now) for h in holders
               if h.get("ticket") != t):
            kept_h: List[Dict[str, Any]] = []
            for h in holders:
                if h.get("ticket") != t and _holder_is_stale(h, now):
                    dropped_stale_holders.append(h.get("ticket"))
                else:
                    kept_h.append(h)
            doc["holders"] = holders = kept_h
        if room and pos == 1:
            queue.pop(0)
            holders.append({"ticket": t, "since": now, "reason": REASON_RUNNING})
            return {"granted": True, "already_holding": False, "position": 0,
                    "limit": limit, "holders": len(holders), "waiting": len(queue),
                    "dropped_stale": dropped_stale,
                    "dropped_stale_holders": dropped_stale_holders,
                    "reacquired_from": reacquired_from}
        out = {"granted": False, "already_holding": False, "position": pos,
               "limit": limit, "holders": len(holders), "waiting": len(queue),
               "dropped_stale": dropped_stale,
               "dropped_stale_holders": dropped_stale_holders,
               "reacquired_from": reacquired_from}
        # t261019-31: name the over-limit state on the gate refusal too, so the
        # gate and the panel face read ONE judgement (never a silent 12/7).
        if not unlimited and len(holders) > limit:
            out["over_limit"] = over_limit_face(limit, len(holders))
        return out


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


#: How long a queue entry may go without a heartbeat before the promoter
#: treats it as a corpse (261019 measured starvation loop): a WAITER re-polls
#: `acquire` on a bounded backoff (dev_lane.CONC_GATE_POLL ..
#: CONC_GATE_POLL_MAX, 5 s .. 120 s) and every poll refreshes the entry's
#: `since`. The old code put the entry in the queue once and never touched it
#: again, so promoting "the queue head" could hand a slot to a workflow that
#: no longer existed. Measured cost: four queued tickets (t261019-16/-18/-19/
#: -27) were killed by Temporal's history limit after ~5 h of 5-second polls;
#: each promotion then parked a slot on a corpse, and five of the seven slots
#: were held by dead tickets while nine live tickets queued for hours.
#: Ten missed heartbeats at the slowest declared backoff is a generous margin:
#: a live waiter can never exceed 120 s between polls.
QUEUE_STALE_S = 900


def _is_stale(entry: Dict[str, Any], now: float,
              bound_s: float = QUEUE_STALE_S) -> bool:
    """A queue entry's (or merge claim's) heartbeat expired (its waiter is gone).
    A missing or non-numeric `since` counts as stale: an entry that cannot prove
    it is alive never takes a slot (fail-closed — the same stance reconcile takes
    for a holder it cannot prove). `bound_s` is the caller's window: the queue
    window is QUEUE_STALE_S, a merge claim's is MERGE_CLAIM_STALE_S."""
    try:
        since = float(entry.get("since"))
    except (TypeError, ValueError):
        return True
    return now - since > bound_s


#: How long a RUNNING holder may go without a heartbeat before the next
#: `acquire` treats it as a corpse (t261019-31, backstop arm of the terminal-
#: release fix). Measured cost of the leak this backstops: five cancelled
#: tickets (t261017-04/-03, t261016-14/-15, t261019-05) kept their slots for
#: 1.6 h to 66 h while live tickets queued. A running holder's heartbeat is
#: every stage start (the already-holding branch of `acquire` refreshes
#: `since`), and stages are separated by minutes-to-hours, so the window is
#: generous where the queue window (QUEUE_STALE_S) is tight: six hours clears
#: every observed corpse within half a day. Judgement is restricted to
#: `reason == REASON_RUNNING`: a human-hold holder waits for a signature and
#: does NOT re-acquire until after it, so it has no heartbeat by design and
#: THIS HEARTBEAT sweep must never judge it at any age. (t261027-10: the
#: proof-of-death sweep — `sweep`, above — is a different judgement: "the
#: workflow is gone" is a fact about the workflow, not about the hold
#: expiring, so it MAY release a TERMINATED holder parked as human-hold;
#: a live or unprovable one keeps its slot there.)
HOLDER_STALE_S = 6 * 3600

#: How long a MERGE CLAIM may sit on the ledger before the next claim treats it
#: as a corpse (t261031-26). A merge claim is taken once for one merge activity
#: (a short engine step: squash + commit) and ended by `end_merge_claim`, by a
#: blocking release, or by a terminal release. The bound is the same generous
#: six hours as HOLDER_STALE_S on purpose: an over-tight bound would drop a claim
#: while its merge is still running and let a second merge start on the same main
#: checkout. The normal reclaim path is reconcile (the workflow is proved gone),
#: not this bound.
MERGE_CLAIM_STALE_S = HOLDER_STALE_S


def _holder_is_stale(holder: Dict[str, Any], now: float) -> bool:
    """A RUNNING holder's heartbeat expired (its workflow is gone — cancelled,
    terminated, or killed by the server without passing a release path).
    Fail-closed on freshness exactly like `_is_stale`: a running holder that
    cannot prove it is alive (missing / non-numeric `since`) counts stale.
    A `human-hold` holder is exempt at any age: the hold is by design (rule 3)
    and the gate waiter has no heartbeat to expire — see HOLDER_STALE_S.
    (t261027-10: this exemption is about the HEARTBEAT judgement only; the
    proof-of-death sweep judges dead human-hold holders by workflow liveness.)"""
    if holder.get("reason") == REASON_HUMAN_HOLD:
        return False
    try:
        since = float(holder.get("since"))
    except (TypeError, ValueError):
        return True
    return now - since > HOLDER_STALE_S


def over_limit_face(limit: int, holders: int) -> Dict[str, Any]:
    """The named over-limit state (t261019-31 root cause 2): `at_work` exceeds
    the declared limit — reachable when the limit is lowered under existing
    holders and/or slots leaked past a terminal ending without a release path.
    Both consumers (the panel's read_state face and the gate's acquire refusal)
    call THIS one function, so the face and the gate read one judgement."""
    return {"limit": limit, "at_work": holders, "surplus": holders - limit}


# ---------- bounded liveness probe + dead-holder sweep (t261027-10, KI-378) ----------
#
# Measured fault: four of five slots on project-vision were held by TERMINATED
# workflows — three of them as `human-hold` rows. The only automatic backstop
# (the heartbeat sweep below) deliberately never judges a human-hold holder,
# and the only janitor was the manual reconcile entry, whose own probe had no
# time bound (measured: a 4-minute silent hang). Two closes, both engine-side
# so the ending caller's (possibly sandboxed, read-only) file access never
# matters:
#   (b) `probe_holder_liveness` — one bounded, named liveness probe. A probe
#       either answers, or the failure is NAMED on the receipt; it never waits
#       unbounded.
#   (a) `sweep` — probe every holder (concurrently, so the total cost is one
#       PROBE_TIMEOUT_S, not N x it), then drop ONLY provably-dead holders
#       under a fresh lock with revalidation (a holder that renewed between the
#       snapshot and the drop survives). The ledger lock is never held across
#       probes: a probe storm must not stall concurrent acquire/release/renew.
#
# Judgement split, stated once so no reader mistakes one for the other:
#   - HEARTBEAT sweep (_holder_is_stale): "this RUNNING holder stopped
#     proving it is alive". A human-hold holder has no heartbeat by design,
#     so this sweep never judges it at any age.
#   - PROOF-OF-DEATH sweep (`sweep`): "this workflow is GONE (Temporal says
#     not_found)". That is a fact about the workflow, not about the hold
#     being expired — it releases a dead human-hold holder exactly like a
#     dead running one. A live human-hold holder (the probe answers) keeps
#     its slot, as does anything unprovable (fail-closed, unchanged).
PROBE_TIMEOUT_S = 10.0
#: One sweep per process per interval, so a saturated project's acquire polls
#: (5 s..120 s backoff) cannot turn into a probe storm. The sweep receipt says
#: when it was skipped for throttle — visible, not silent.
SWEEP_MIN_INTERVAL_S = 60.0

#: The liveness probe seam. One async callable `(tid) -> (kind, note)` with
#: kind "" = the workflow answered, "not_found" = Temporal says it is gone,
#: anything else = an error name. Wiring is the worker's job (it owns the
#: Temporal client): worker.py calls `configure_probe`. Unset = the sweep
#: refuses by name instead of pretending to judge (a missing probe must not
#: look like "everybody is alive").
_probe_query = None
_sweep_state = {"at": 0.0}


def configure_probe(fn) -> None:
    """Install the liveness probe callable (worker.py wiring point). Passing
    None uninstalls (tests / shutdown)."""
    global _probe_query
    _probe_query = fn


def _classify_probe_kind(kind: str) -> str:
    """"live" / "dead" / "unknown" from the probe's structured kind. Only
    not_found is proof of death; everything else keeps the slot (fail-closed,
    the same stance reconcile takes on unknown)."""
    if kind == "":
        return "live"
    if kind == "not_found":
        return "dead"
    return "unknown"


async def probe_holder_liveness(probe, tid: str) -> Tuple[str, str]:
    """One bounded, named probe. Returns (verdict, note) with verdict
    live|dead|unknown; note is "" or a named failure a reader can act on.
    A hung probe is cancelled at PROBE_TIMEOUT_S and named; a probe that
    raises or returns a malformed result is unknown, never an exception and
    never silently alive."""
    try:
        res = await asyncio.wait_for(probe(str(tid)), timeout=PROBE_TIMEOUT_S)
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, TimeoutError):
        return "unknown", "probe timed out after %ss" % PROBE_TIMEOUT_S
    except Exception as e:  # noqa: BLE001 - a probe fault is named, not raised
        return "unknown", "%s: %s" % (type(e).__name__, str(e)[:160])
    if not (isinstance(res, tuple) and len(res) == 2
            and isinstance(res[0], str) and isinstance(res[1], str)):
        return "unknown", "malformed probe result: %r" % (res,)[:120]
    kind = res[0]
    note = res[1][:160]
    verdict = _classify_probe_kind(kind)
    if verdict == "unknown":
        # Name the kind on the note: the reader sees WHY the slot was kept.
        note = "kept (%s) %s" % (kind, note)
    return verdict, note


#: The kind the BLOCKING runner reports for a probe that did not answer inside
#: its bound (t261028-06). It is a named refusal, never a death:
#: `_classify_probe_kind` maps it to unknown, so the holder keeps its slot and
#: the receipt says why.
PROBE_KIND_TIMEOUT = "timeout"

#: Slack the blocking runner allows ABOVE the probe's own bound before it
#: declares a probe hung (t261028-06). The probe's own bound is expected to
#: fire first and report a clean, named timeout (the spawned query is killed at
#: that bound); this slack only covers a callable that ignores its own bound,
#: so the seam is a hard backstop over a bounded probe, never the primary
#: deadline. Zero would race the two bounds and could report "hung" for a probe
#: that was about to name its own timeout.
PROBE_SEAM_GRACE_S = 1.0


def probe_holders_bounded(probe, tickets: Iterable[str],
                          timeout_s: Optional[float] = None) -> Dict[str, Any]:
    """Blocking, bounded, named liveness probe for a consumer that is NOT async.

    t261028-06 (KI-378 ②): the repair entry
    (`ticket.py op=concurrency reconcile=true`) runs on the plain host python
    next to a Temporal socket it cannot await. Measured fault: a probe that
    blocked in that socket held the command for 4+ minutes with a
    byte-identical state file and no output. Every probe here runs on its own
    daemon thread and the calls are joined against ONE shared deadline
    (`timeout_s` plus PROBE_SEAM_GRACE_S), so the wall-clock cost of N probes is
    about one bound, not N.

    Returns {"results": {tid: {"verdict", "kind", "note"}}, "hung": [tids],
             "timeout_s": <bound>, "elapsed_s": <wall clock seconds>}.

    The verdict follows the SAME rule as `probe_holder_liveness`
    (`_classify_probe_kind`): only not_found is proof of death; a timeout, a
    raise and a malformed answer are all unknown — the holder keeps its slot
    and the reason is NAMED on `note`. Nothing here raises on a probe fault.
    A thread still running at the deadline is abandoned, never joined again:
    daemon threads die with the process, so a wedged probe can never become a
    wedged exit.
    """
    tids = [str(t) for t in (tickets or ())]
    if not callable(probe):
        raise ValueError(
            "Concurrency holder probe refused: no probe callable - refusing "
            "instead of judging holders with an absent probe")
    budget = PROBE_TIMEOUT_S if timeout_s is None else float(timeout_s)
    t0 = time.monotonic()
    deadline = t0 + max(0.0, budget) + PROBE_SEAM_GRACE_S
    raw: Dict[str, Tuple[str, str]] = {}
    guard = threading.Lock()

    def _one(tid: str) -> None:
        try:
            res = probe(tid)
        except BaseException as e:  # noqa: BLE001 - a probe fault is named, not raised
            row: Tuple[str, str] = ("unknown",
                                    "%s: %s" % (type(e).__name__, str(e)[:160]))
        else:
            if isinstance(res, tuple) and len(res) == 2 \
                    and isinstance(res[0], str) and isinstance(res[1], str):
                row = (res[0], res[1][:160])
            else:
                row = ("malformed", "malformed probe result: %r" % (res,))
        with guard:
            raw[tid] = row

    threads: List[Tuple[str, threading.Thread]] = []
    for tid in tids:
        th = threading.Thread(target=_one, args=(tid,),
                              name="conc-probe", daemon=True)
        th.start()
        threads.append((tid, th))
    for _tid, th in threads:
        th.join(max(0.0, deadline - time.monotonic()))
    results: Dict[str, Dict[str, str]] = {}
    hung: List[str] = []
    for tid, _th in threads:
        seen = raw.get(tid)
        if seen is None:
            hung.append(tid)
            kind, note = (PROBE_KIND_TIMEOUT,
                          "probe timed out after %ss" % (round(budget, 3),))
        else:
            kind, note = seen
        results[tid] = {"verdict": _classify_probe_kind(kind),
                        "kind": kind, "note": note}
    return {"results": results, "hung": hung,
            "timeout_s": budget,
            "elapsed_s": round(time.monotonic() - t0, 3)}


async def sweep(project_key: str, probe) -> Dict[str, Any]:
    """Probe every holder of the project and drop only provably-dead ones.

    Lock discipline (review_plan condition 1): the ledger lock is taken twice,
    briefly — once to snapshot the holder records, once to drop — and NEVER
    across probes; concurrent acquire/release/renew of the project cannot
    stall behind a probe. Cost bound (condition 2): probes run concurrently,
    so the wall-clock cost is one PROBE_TIMEOUT_S, and the receipt carries
    `elapsed_s` plus per-holder named notes. Drop revalidation: a holder is
    dropped only if it is still present AND identical to its snapshot
    (ticket+since+reason); a holder that renewed between snapshot and drop is
    KEPT and named in `kept_revalidated`. Human-hold holders are judged here
    by proof of death, not by hold age — a live human-hold keeps its slot
    (tested), an unprovable one keeps it too."""
    k = _check_key(project_key)
    if not callable(probe):
        raise ValueError(
            "Concurrency sweep refused: no liveness probe is configured - "
            "the worker must wire one via concurrency.configure_probe; "
            "refusing instead of judging with an absent probe")
    root = os.path.join(str(shared.perkey_projects_root()), k)
    t0 = time.monotonic()
    with _locked(root) as g:
        snap = {h.get("ticket"): dict(h) for h in g.doc.get("holders", [])
                if isinstance(h, dict)}
    if not snap:
        return {"probed": 0, "dropped": [], "kept_revalidated": [],
                "unknown": [], "probe_errors": {}, "dropped_evidence": [],
                "promoted": None, "dropped_stale": [],
                "holders": 0, "waiting": 0,
                "elapsed_s": round(time.monotonic() - t0, 3)}
    verdicts: Dict[str, Tuple[str, str]] = {}

    async def _one(tid: str) -> None:
        verdicts[tid] = await probe_holder_liveness(probe, tid)

    await asyncio.gather(*(_one(t) for t in snap))
    dead = {t for t, (v, _n) in verdicts.items() if v == "dead"}
    dropped: List[str] = []
    kept_revalidated: List[str] = []
    promoted = None
    dropped_stale: List[str] = []
    holders_now = len(snap)
    waiting_now = 0
    if dead:
        with _locked(root) as g:
            doc = g.doc
            keep: List[Dict[str, Any]] = []
            for h in doc.get("holders", []):
                tid = h.get("ticket")
                s = snap.get(tid)
                if tid in dead and s is not None \
                        and h.get("since") == s.get("since") \
                        and h.get("reason") == s.get("reason"):
                    dropped.append(tid)
                    continue
                if tid in dead:
                    # The holder changed between snapshot and drop (it renewed
                    # or was rewritten) - it proved itself alive meanwhile.
                    kept_revalidated.append(tid)
                keep.append(h)
            doc["holders"] = keep
            limit = load_limit(k)
            room = limit is None or len(keep) < limit
            if room and doc.get("queue"):
                hop = _promote_live_head(doc, time.time())
                promoted = hop["promoted"]
                dropped_stale = hop["dropped_stale"]
            holders_now = len(keep)
            waiting_now = len(doc.get("queue", []))
    else:
        face = read_state(k)
        holders_now = len(face.get("holders", []))
        waiting_now = len(face.get("queue", []))
    unknown = sorted(t for t, (v, _n) in verdicts.items() if v == "unknown")
    probe_errors = {t: verdicts[t][1] for t in snap if verdicts[t][1]}
    dropped_evidence = [{"ticket": t, "verdict": "dead",
                         "probe": verdicts[t][1]} for t in sorted(dead)]
    return {"probed": len(snap), "dropped": sorted(dropped),
            "kept_revalidated": sorted(kept_revalidated),
            "unknown": unknown, "probe_errors": probe_errors,
            "dropped_evidence": dropped_evidence,
            "promoted": promoted, "dropped_stale": dropped_stale,
            "holders": holders_now, "waiting": waiting_now,
            "elapsed_s": round(time.monotonic() - t0, 3)}


def sweep_due(now: Optional[float] = None) -> bool:
    """Whether a new sweep may start (one per process per
    SWEEP_MIN_INTERVAL_S). Tests drive the clock through the parameter."""
    now = time.time() if now is None else now
    return now - _sweep_state["at"] >= SWEEP_MIN_INTERVAL_S


def sweep_mark(now: Optional[float] = None) -> None:
    """Record that a sweep is starting (the throttle marker)."""
    _sweep_state["at"] = time.time() if now is None else now


def _promote_live_head(doc: Dict[str, Any], now: float) -> Dict[str, Any]:
    """Pop the first LIVE queue entry into a holder record, naming every stale
    entry dropped on the way. Shared by release / reconcile so the two call
    sites can never disagree about what "the queue head" is."""
    dropped: List[str] = []
    while doc["queue"]:
        head = doc["queue"][0]
        if _is_stale(head, now):
            dropped.append(head.get("ticket"))
            doc["queue"].pop(0)
            continue
        doc["queue"].pop(0)
        doc["holders"].append({"ticket": head.get("ticket"),
                               "since": now, "reason": REASON_RUNNING})
        return {"promoted": head.get("ticket"), "dropped_stale": dropped}
    return {"promoted": None, "dropped_stale": dropped}


def release(project_key: str, ticket: str, cause: str,
            stage: str = "") -> Dict[str, Any]:
    """Release the slot at a real release point (paused / terminated / merge-wait
    / blocked-wait) and promote the queue head if the freed slot covers it.
    Idempotent: releasing a ticket that holds nothing is a no-op receipt, not an
    error.

    `human-gate` is deliberately NOT a freeing cause: the renewal points of a
    stage that can still progress by itself (stage end, and the gates t261031-26
    did not move) are atomic renews (see renew/CAUSE_HUMAN_GATE), never a
    release. Refused here by name so a mis-wired call site is loud.

    t261022 (host order 261022): the MERGE human gate is one exception and frees
    the slot with its OWN cause word (`merge-wait`), so a ticket waiting for a
    merge signature no longer starves the queue. The freed ticket is recorded on
    the ledger's `merge_wait` face (not as a holder) and leaves that face when it
    takes a slot again — the panel can therefore tell a merge-wait release from a
    zombie holder.

    t261031-26 (KI-441 / KI-443): the second exception is a ticket parked in
    `blocked` / `awaiting-human` — a state the engine sets itself when the ticket
    cannot progress without an outside act. It releases with its own
    `blocked-wait` cause and is recorded on the `blocked_wait` face (ticket,
    when, why, which stage), so the release is auditable and the ticket is never
    read as a zombie. `stage` names the stage it parked in ("" when the caller
    has none). Every real release clears the ticket from ALL faces (holder, queue,
    merge-wait, blocked-wait, merge claims): a parked or claimed row can never
    outlive the release that ends it."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    if cause not in (CAUSE_TERMINATED, CAUSE_PAUSED, CAUSE_MERGE_WAIT,
                     CAUSE_BLOCKED_WAIT, CAUSE_REMOTE_REVIEW_WAIT):
        raise ValueError(
            "Concurrency slot release refused: cause %r is not in the real-"
            "release vocabulary (terminated|paused|merge-wait|blocked-wait|"
            "remote-review-wait) - a stage that can still progress renews its "
            "hold (an atomic renew, never a release point); only a parked state "
            "the engine itself set (merge signature wait, blocked/awaiting-human, "
            "awaiting remote review) releases its slot"
            % cause)
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    parked_stage = str(stage or "")
    with _locked(root) as g:
        doc = g.doc
        before = len(doc["holders"])
        doc["holders"] = [h for h in doc["holders"] if h.get("ticket") != t]
        doc["queue"] = [e for e in doc["queue"] if e.get("ticket") != t]
        # Any real release clears the ticket's parked faces too (a cancelled or
        # paused gate waiter must not linger as "waiting for a signature", and a
        # blocked-then-cancelled ticket must not linger as "waiting for an act").
        for face in PARKED_FACES:
            doc[face] = [e for e in doc.get(face, [])
                         if not (isinstance(e, dict) and e.get("ticket") == t)]
        released = len(doc["holders"]) < before
        parked: Optional[Dict[str, Any]] = None
        if released and cause == CAUSE_MERGE_WAIT:
            doc["merge_wait"].append({"ticket": t, "since": now})
            parked = {"face": CAUSE_MERGE_WAIT, "ticket": t, "since": now}
        elif released and cause in (CAUSE_BLOCKED_WAIT, CAUSE_REMOTE_REVIEW_WAIT):
            doc["blocked_wait"].append({"ticket": t, "since": now,
                                        "cause": cause,
                                        "stage": parked_stage})
            parked = {"face": CAUSE_BLOCKED_WAIT, "ticket": t, "since": now,
                      "cause": cause, "stage": parked_stage}
        promoted = None
        dropped_stale: List[str] = []
        limit = load_limit(k)
        room = limit is None or len(doc["holders"]) < limit
        if room and doc["queue"]:
            hop = _promote_live_head(doc, now)
            promoted = hop["promoted"]
            dropped_stale = hop["dropped_stale"]
        return {"released": released, "cause": cause, "promoted": promoted,
                "dropped_stale": dropped_stale,
                "holders": len(doc["holders"]), "waiting": len(doc["queue"]),
                "parked": parked}


#: t261031-26 (second half): the merge step's own accounting.
#:
#: WHY a merge claims instead of taking a work slot: the work limit protects the
#: resource a lane run actually consumes (a stage with an agent session, a
#: worktree, a development line). The merge step is a short engine activity - a
#: squash onto main - and starts no agent. Making it queue for a work slot is
#: what deadlocked the project on 261031: two human-signed tickets waited over
#: half an hour behind three blocked holders, the freeze that blocked those
#: holders could only be lifted by a green line round, and that round needed one
#: of the queued merges to land. The queue was waiting on itself. So a signed
#: merge takes a MERGE CLAIM: recorded (who/when) for a reader, never a holder,
#: never counted by the limit, never queued behind work.
#:
#: WHY a claim is still recorded instead of nothing at all: two merges writing
#: the same main checkout at once race on the git index, so the face must show
#: which merges are in flight and since when. The claim does not make a merge
#: WAIT (a merge is never queued: the cap is deliberately absent), it only makes
#: the merge visible - and reconcile/terminal release clear it by name.

def claim_merge(project_key: str, ticket: str) -> Dict[str, Any]:
    """Take the MERGE CLAIM for a signed merge (t261031-26).

    Never refuses and never queues: a signed merge must not wait for a work slot
    (measured cost above). Idempotent — claiming again keeps the original
    `since`, because the claim records when THIS merge started, not when it was
    last polled. Taking the claim also ends the ticket's parked faces (the merge
    signature wait is over, and so is any blocked wait), so the panel never sees
    a ticket both parked and merging.

    Stale claims (older than MERGE_CLAIM_STALE_S) are dropped in the same locked
    step and NAMED on the receipt: a claim whose workflow died mid-merge must not
    linger forever. This is the heartbeat backstop; `reconcile` is the normal
    janitor."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    if not t:
        raise ValueError("Concurrency merge claim refused: empty ticket id")
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    with _locked(root) as g:
        doc = g.doc
        claims = doc["merge_claims"]
        for face in ("merge_wait", "blocked_wait"):
            doc[face] = [e for e in doc.get(face, [])
                         if not (isinstance(e, dict) and e.get("ticket") == t)]
        dropped_stale: List[str] = []
        kept: List[Dict[str, Any]] = []
        for e in claims:
            if not isinstance(e, dict):
                continue
            if _is_stale(e, now, MERGE_CLAIM_STALE_S):
                dropped_stale.append(e.get("ticket"))
                continue
            kept.append(e)
        doc["merge_claims"] = claims = kept
        mine = next((e for e in claims if e.get("ticket") == t), None)
        already = mine is not None
        if mine is None:
            mine = {"ticket": t, "since": now}
            claims.append(mine)
        return {"claimed": True, "already": bool(already),
                "ticket": t, "since": mine.get("since"),
                "merge_claims": len(claims),
                "dropped_stale": dropped_stale}


def end_merge_claim(project_key: str, ticket: str) -> Dict[str, Any]:
    """End a merge claim (the merge activity returned, ok or not).

    Idempotent: ending a claim the ticket does not hold is a no-op receipt, not
    an error (the blocking / terminal release paths end it too). This is NOT a
    slot release — a merge claim is not a slot — so it does not promote the
    queue: the merge step never held capacity that a waiter could inherit."""
    k = _check_key(project_key)
    t = str(ticket or "").strip()
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    with _locked(root) as g:
        doc = g.doc
        before = len(doc["merge_claims"])
        held_s = 0.0
        for e in doc["merge_claims"]:
            if isinstance(e, dict) and e.get("ticket") == t:
                try:
                    held_s = round(now - float(e.get("since")), 3)
                except (TypeError, ValueError):
                    held_s = 0.0
        doc["merge_claims"] = [e for e in doc["merge_claims"]
                               if not (isinstance(e, dict) and e.get("ticket") == t)]
        return {"ended": len(doc["merge_claims"]) < before,
                "ticket": t, "held_s": held_s,
                "merge_claims": len(doc["merge_claims"])}


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
    # t261019-31: name the split judgement — a holder count above the declared
    # limit (leaked slots, or a lowered limit under holders) is a machine-
    # readable flag on the face, never a silent 12/7. Same single judgement
    # source as the gate refusal (over_limit_face).
    if limit is not None and len(face["holders"]) > limit:
        face["over_limit"] = over_limit_face(limit, len(face["holders"]))
    else:
        face["over_limit"] = None
    return face


def reconcile(project_key: str, alive_tickets: Iterable[str],
              draining_tickets: Iterable[str] = (),
              unknown_tickets: Iterable[str] = (),
              dead_tickets: Optional[Iterable[str]] = None) -> Dict[str, Any]:
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
    dropped, and which holders are draining. The `merge_wait` face (t261022) is
    pruned by the same rule: a gate waiter nobody could prove alive leaves it.
    The `blocked_wait` and `merge_claims` faces (t261031-26) are pruned by that
    same rule too — and because a parked/claimed ticket holds no slot, it can
    never be reported in `dropped`: a blocked-and-released ticket is not a
    zombie by construction.

    t261028-06 (KI-378 (a), the proof-of-death form): `dead_tickets` is the
    PROOF set — the holders whose workflow the caller PROVED terminal (the
    liveness probe answered not_found). When it is given, ONLY those holders
    lose their slot: a holder that is neither proved alive nor proved dead (the
    probe timed out, or it entered the ledger after the caller's snapshot)
    KEEPS its slot and is named in `kept_unclassified`. That is the difference
    between "nobody vouched for it" and "we watched it die"; an absent set
    (None) keeps the legacy contract the earlier callers rely on, where an
    unclassified holder is dropped."""
    k = _check_key(project_key)
    alive = {str(t) for t in (alive_tickets or ())}
    draining = {str(t) for t in (draining_tickets or ())} - alive
    unknown = {str(t) for t in (unknown_tickets or ())} - alive - draining
    proven_dead: Optional[set] = None
    if dead_tickets is not None:
        proven_dead = {str(t) for t in (dead_tickets or ())} \
            - alive - draining - unknown
    root = os.path.join(str(shared.perkey_projects_root()), k)
    now = time.time()
    dropped: List[str] = []
    kept_unclassified: List[str] = []
    merge_wait_dropped: List[str] = []
    with _locked(root) as g:
        doc = g.doc
        keep: List[Dict[str, Any]] = []
        for h in doc["holders"]:
            tid = h.get("ticket")
            if tid in alive or tid in draining or tid in unknown:
                keep.append(h)
            elif proven_dead is None or tid in proven_dead:
                dropped.append(tid)
            else:
                # Neither proved alive nor proved dead: the slot is not ours to
                # take (fail-closed). Named on the receipt, never dropped.
                kept_unclassified.append(tid)
                keep.append(h)
        doc["holders"] = keep
        # t261022: the merge-wait face is not a second zombie channel — a gate
        # waiter the caller could not prove alive leaves the face exactly like a
        # dead holder leaves the holder list (unknown/draining keep it, same
        # fail-closed stance as above). t261028-06: under the proof form, a
        # waiter that was not proved dead keeps the face too.
        kept_wait: List[Dict[str, Any]] = []
        for e in doc.get("merge_wait", []):
            if not isinstance(e, dict):
                continue
            tid = e.get("ticket")
            if tid in alive or tid in draining or tid in unknown:
                kept_wait.append(e)
            elif proven_dead is None or tid in proven_dead:
                merge_wait_dropped.append(tid)
            else:
                kept_wait.append(e)
        doc["merge_wait"] = kept_wait
        # t261031-26: the two new faces follow the SAME rule as merge_wait, so a
        # parked or merging ticket is never a second zombie channel: a ticket
        # nobody could prove alive leaves the face, a live/unprovable one keeps
        # it. A blocked-and-released ticket is NOT a holder, so it can never be
        # reported in `dropped` — that is the whole point of the release.
        blocked_wait_dropped: List[str] = []
        kept_blocked: List[Dict[str, Any]] = []
        for e in doc.get("blocked_wait", []):
            if not isinstance(e, dict):
                continue
            tid = e.get("ticket")
            if tid in alive or tid in draining or tid in unknown:
                kept_blocked.append(e)
            elif proven_dead is None or tid in proven_dead:
                blocked_wait_dropped.append(tid)
            else:
                kept_blocked.append(e)
        doc["blocked_wait"] = kept_blocked
        merge_claims_dropped: List[str] = []
        kept_claims: List[Dict[str, Any]] = []
        for e in doc.get("merge_claims", []):
            if not isinstance(e, dict):
                continue
            tid = e.get("ticket")
            if tid in alive or tid in draining or tid in unknown:
                kept_claims.append(e)
            elif proven_dead is None or tid in proven_dead:
                merge_claims_dropped.append(tid)
            else:
                kept_claims.append(e)
        doc["merge_claims"] = kept_claims
        promoted = None
        dropped_stale: List[str] = []
        limit = load_limit(k)
        room = limit is None or len(doc["holders"]) < limit
        if room and doc["queue"]:
            hop = _promote_live_head(doc, now)
            promoted = hop["promoted"]
            dropped_stale = hop["dropped_stale"]
        return {"dropped": dropped, "promoted": promoted,
                "dropped_stale": dropped_stale,
                "kept_unclassified": kept_unclassified,
                "merge_wait_dropped": merge_wait_dropped,
                "blocked_wait_dropped": blocked_wait_dropped,
                "merge_claims_dropped": merge_claims_dropped,
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
        res = acquire(args.project, args.ticket, priority=bool(args.priority))
        # t261027-10 (KI-378 ① guarantee arm): when the project is saturated
        # (this waiter was refused because holders >= limit) and a liveness
        # probe is wired, sweep the holders before this poll gives up: dead
        # holders (including TERMINATED ones parked as human-hold) are
        # reclaimed here, by the worker — which owns both the Temporal client
        # and write access to the projects root — never by the ending caller.
        # Bounded: at most one sweep per process per SWEEP_MIN_INTERVAL_S,
        # each sweep's probes concurrent under one PROBE_TIMEOUT_S; the
        # receipt carries the sweep outcome so a skipped or failed sweep is
        # visible on the acquire receipt, never silent.
        if (not res.get("granted") and callable(_probe_query)
                and res.get("limit") is not None
                and int(res.get("holders") or 0) >= int(res["limit"])
                and sweep_due()):
            sweep_mark()
            try:
                sw = await sweep(args.project, _probe_query)
            except Exception as e:  # noqa: BLE001 - named, never fatal to the poll
                sw = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            res["sweep"] = sw
            if sw.get("dropped"):
                # A real reclaim: re-judge once so this waiter can take the
                # freed slot in the same poll instead of waiting a backoff.
                res = acquire(args.project, args.ticket,
                              priority=bool(args.priority))
                res["sweep"] = sw
        return res

    @activity.defn
    async def concurrency_release(args: ReleaseArgs) -> Dict[str, Any]:
        return release(args.project, args.ticket, cause=args.cause)

    @activity.defn
    async def concurrency_renew(args: ReleaseArgs) -> Dict[str, Any]:
        reason = REASON_HUMAN_HOLD if args.cause == CAUSE_HUMAN_GATE else REASON_RUNNING
        return renew(args.project, args.ticket, reason)

    @activity.defn
    async def concurrency_claim_merge(args: AcquireArgs) -> Dict[str, Any]:
        """t261031-26: the merge step's accounting. Reuses AcquireArgs (project +
        ticket); it is not an admission judgement and it never refuses for lack
        of capacity — see claim_merge."""
        return claim_merge(args.project, args.ticket)

    @activity.defn
    async def concurrency_end_merge_claim(args: AcquireArgs) -> Dict[str, Any]:
        return end_merge_claim(args.project, args.ticket)

    @activity.defn
    async def concurrency_sweep(args: AcquireArgs) -> Dict[str, Any]:
        """Standalone sweep entry (also callable on demand). Refuses by name
        when no probe is wired — never judges with an absent probe."""
        return await sweep(args.project, _probe_query)

    CONCURRENCY_ACTIVITIES = (concurrency_acquire, concurrency_release,
                              concurrency_renew, concurrency_sweep,
                              concurrency_claim_merge,
                              concurrency_end_merge_claim)
else:  # pragma: no cover
    CONCURRENCY_ACTIVITIES = ()
