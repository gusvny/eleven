"""Ticket dismissal journal (t261009-31): a recorded human decision that takes a
failed row off the board — and can put it back.

Carried over from the void face (inspection_ticketing.py, t261008-22), changed
where a dismissal differs:

  - Append-only JSONL journal, written and never read back for writes: an
    existing file stays appendable even when malformed. Suffix `.jsonl` for the
    same reason as `inspection-void.jsonl` — the deadman ledger scan only takes
    `.json`, and "this ticket was dismissed by a person" must never read as
    "this ticket ran".
  - Bad lines are skipped per line but COUNTED, never swallowed: a dismissal
    row is a human-disposition voucher; swallowing one is swallowing a
    signature.
  - Row shape `{at, ticket_id, who, reason, action}` — per ticket, no
    instance/period (a dismissal has no period; that scoping stays void-only).
  - LAST row for a ticket wins and its `action` decides (`dismiss` | `restore`):
    a dismissal is reversible, so an undo is another row, never an edit. (The
    void's first-signature-wins is deliberately NOT carried over.)
  - Bounds at this layer: who <= 64 (same scale as shared.AUTHZ_WHO_MAX_LEN),
    reason <= 2000; over-bound is refused structurally with zero side effects.
  - An empty reason is refused by name, never defaulted. A who that is an agent
    role name (shared.AUTHZ_AGENT_ROLE_NAMES) is refused: only a human signs —
    an agent may not dismiss a ticket it failed.
  - A dismissal is NOT a workflow signal: this module never advances, closes or
    re-opens a ticket, and never touches the workflow's history — that history
    stays the truth about how the ticket ended. A dismissed row must NOT be
    readable as a done ticket, so consumers expose it under its own
    `dismissed` key, never a DONE-family reclassification.

Client payload contract (consumed by client.py and, later, the UI ticket): the
augmented key is `dismissed` with guaranteed keys `{at, who, reason}`; on
journal read failure the key is absent AND a named `dismissed_note` travels in
the payload — never a silent "not dismissed".
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

#: Dismissal audit journal (see module docstring for the naming rationale).
DISMISS_JOURNAL_NAME = "ticket-dismiss.jsonl"

#: Input bounds (independent constants, same values as shared.AUTHZ_* — same
#: value, separately owned, like the void face's VOID_* bounds).
DISMISS_WHO_MAX_LEN = 64
DISMISS_REASON_MAX_LEN = 2000

#: Journal row actions. The LAST row's action is the ticket's standing face.
ACTION_DISMISS = "dismiss"
ACTION_RESTORE = "restore"


def journal_dir(override: Any = None) -> Path:
    """Journal home directory: explicit argument > SANDBAR_DISMISS_DIR env >
    shared.OUT_DIR (lazy import — no engine module import at module load, so
    tests can pin the location with tmp_path or the env alone)."""
    if override is not None:
        return Path(str(override))
    env = os.environ.get("SANDBAR_DISMISS_DIR")
    if env:
        return Path(env)
    import shared  # noqa: PLC0415 — lazy import, open_period_ticket precedent
    return Path(str(shared.OUT_DIR))


def dismiss_journal_path(override: Any = None) -> Path:
    """Full journal file path (single point; readers and writers agree)."""
    return journal_dir(override) / DISMISS_JOURNAL_NAME


def append_dismiss_journal(dir_override: Any, *, ticket_id: str, who: str,
                           reason: str, action: str,
                           now_fn: Callable[[], float] = time.time) -> None:
    """Append one dismissal audit row (append-only; write-only — never reads
    back, so a malformed existing file stays appendable). OSError propagates to
    the caller for an explicit error: a missing audit trail is never silent —
    the caller must not return a success receipt for a row that was not
    written."""
    p = dismiss_journal_path(dir_override)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": float(now_fn()), "ticket_id": str(ticket_id or ""),
               "who": str(who or ""), "reason": str(reason or ""),
               "action": str(action or "")}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_dismiss_journal(dir_override: Any, *,
                         with_malformed: bool = False):
    """Read the dismissal journal. Default return: the rows list in file order
    (order is the truth the last-row-wins reader needs). `with_malformed=True`
    returns (rows, malformed_count). Missing file = ([], 0); bad lines are
    skipped per line but COUNTED (module docstring: swallowing one row is
    swallowing one human signature)."""
    try:
        text = dismiss_journal_path(dir_override).read_text("utf-8")
    except (FileNotFoundError, OSError):
        return ([], 0) if with_malformed else []
    rows: List[Dict[str, Any]] = []
    malformed = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return (rows, malformed) if with_malformed else rows


def dismissed_ticket_row(rows: List[Dict[str, Any]],
                         ticket_id: str) -> Optional[Dict[str, Any]]:
    """Standing-disposition lookup (pure): the LAST row for that ticket, or
    None when the ticket has no row. An empty/blank ticket_id never matches —
    a malformed row without an id is nobody's voucher and must not shadow a
    real dismissal."""
    tid = str(ticket_id or "").strip()
    if not tid:
        return None
    found = None
    for row in rows:
        if str(row.get("ticket_id") or "").strip() == tid:
            found = row          # keep walking: the LAST row wins
    return found


def dismissed_face(last_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The consumer face for a ticket's standing row: the `{at, who, reason}`
    payload dict when the standing action is `dismiss`; None when the ticket is
    not dismissed (no row, or the standing action is `restore`). The action
    itself stays internal — the payload key shape is fixed at
    `dismissed:{at,who,reason}` (module docstring contract)."""
    if last_row is None:
        return None
    if str(last_row.get("action") or ACTION_DISMISS) != ACTION_DISMISS:
        return None
    return {"at": last_row.get("at"), "who": last_row.get("who"),
            "reason": last_row.get("reason")}


def _fmt_ts(v: Any) -> str:
    """epoch -> readable time (refusal copy; non-number = as-written, never
    guessed)."""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(v)))
    except (TypeError, ValueError):
        return str(v or "unknown")


def _decision(dir_override: Any, *, action: str, ticket_id: str, who: str,
              reason: str, now_fn: Callable[[], float],
              known_ticket_ids: Optional[Union[set, Callable[[], set]]]) -> Dict[str, Any]:
    """Shared named-decision body for dismiss_ticket / restore_ticket.

    Refusal order (fail-closed, every path named, EVERY refusal zero-write —
    the journal file is not even opened for append until the last gate passes):
      (1) shape: ticket_id / who / reason non-empty; who <= 64; reason <= 2000;
          who not an agent role name (only a human signs).
      (2) existence: when known_ticket_ids is provided (set or callable), the
          ticket must be in it — an unknown ticket is refused by name, never
          guessed. Callers that cannot prove the population pass nothing and
          own that honesty themselves.
      (3) state: the LAST row decides — `dismiss` on an already-dismissed
          ticket is refused quoting the standing disposition (re-dismiss after
          a restore is allowed: the standing action is then `restore`);
          `restore` on a not-dismissed ticket is refused by name.
    On success: exactly one append_dismiss_journal row; OSError from the append
    propagates (a receipt must never claim a row that was not written)."""
    tid = str(ticket_id or "").strip()
    w = str(who or "").strip()
    r = str(reason or "").strip()

    def _err(msg: str) -> Dict[str, Any]:
        return {"ok": False, "error": "%s (action %s ticket %s)" % (msg, action, tid)}

    # (1) shape — before any write, zero side effects
    if not tid:
        return _err("%s is missing ticket_id" % action)
    if not w:
        return _err("%s is missing who (a human signature is mandatory — a signature-less "
                    "disposition is never accepted)" % action)
    if len(w) > DISMISS_WHO_MAX_LEN:
        return _err("who is too long (> %d chars)" % DISMISS_WHO_MAX_LEN)
    import shared  # noqa: PLC0415 — role-name set single point (lazy import)
    if w.lower() in shared.AUTHZ_AGENT_ROLE_NAMES:
        return _err("who is an agent role name (%s) — only a human can sign a dismissal; "
                    "an agent may not dismiss a ticket it failed" % w)
    if not r:
        return _err("%s is missing reason (the reason is mandatory — a reason-less "
                    "disposition is never accepted, never defaulted)" % action)
    if len(r) > DISMISS_REASON_MAX_LEN:
        return _err("reason is too long (> %d chars)" % DISMISS_REASON_MAX_LEN)

    # (2) existence gate
    known = known_ticket_ids() if callable(known_ticket_ids) else known_ticket_ids
    if known is not None and tid not in known:
        return _err("unknown ticket: %s is not in the engine ticket population — "
                    "check the id, never guess" % tid)

    # (3) state gate — the LAST row decides, so re-dismiss after restore is legal
    rows, _malformed = read_dismiss_journal(dir_override, with_malformed=True)
    standing = dismissed_ticket_row(rows, tid)
    face = dismissed_face(standing)
    if action == ACTION_DISMISS and face is not None:
        return _err("ticket already dismissed (%s at %s: %s) — the standing disposition "
                    "is a dismiss; to take it back use restore (another row, never an edit)"
                    % (face.get("who"), _fmt_ts(face.get("at")), face.get("reason")))
    if action == ACTION_RESTORE and face is None:
        return _err("ticket is not dismissed (no standing dismiss row) — restore applies "
                    "only to a dismissed ticket")

    at = float(now_fn())
    append_dismiss_journal(dir_override, ticket_id=tid, who=w, reason=r,
                           action=action, now_fn=lambda: at)
    receipt_key = {"dismiss": "dismissed", "restore": "restored"}[action]
    return {"ok": True, receipt_key: {"at": at, "who": w, "reason": r,
                                      "ticket_id": tid},
            "journal": str(dismiss_journal_path(dir_override))}


def dismiss_ticket(dir_override: Any, *, ticket_id: str, who: str, reason: str,
                   now_fn: Callable[[], float] = time.time,
                   known_ticket_ids: Optional[Union[set, Callable[[], set]]] = None
                   ) -> Dict[str, Any]:
    """Named dismissal of one ticket (see _decision for the refusal contract).

    Receipt: ok=True -> {ok, dismissed:{at,who,reason,ticket_id}, journal:<path>}
    (at carries this row's own epoch — the just-written disposition);
    ok=False -> a single-line readable error naming the reason; every refusal
    path is zero-write."""
    return _decision(dir_override, action=ACTION_DISMISS, ticket_id=ticket_id,
                     who=who, reason=reason, now_fn=now_fn,
                     known_ticket_ids=known_ticket_ids)


def restore_ticket(dir_override: Any, *, ticket_id: str, who: str, reason: str,
                   now_fn: Callable[[], float] = time.time,
                   known_ticket_ids: Optional[Union[set, Callable[[], set]]] = None
                   ) -> Dict[str, Any]:
    """Named restore (undo) of one dismissed ticket — itself another signed
    human row with its own reason (see _decision for the refusal contract).
    Receipt: ok=True -> {ok, restored:{at,who,reason,ticket_id}, journal:<path>}."""
    return _decision(dir_override, action=ACTION_RESTORE, ticket_id=ticket_id,
                     who=who, reason=reason, now_fn=now_fn,
                     known_ticket_ids=known_ticket_ids)
