#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_request_contract -- the executor-request layer contract, executable
(t261021-08, plan rev2, review gen2 conditional pass).

Scope of this ticket: the write set is ``integration/`` only, so the
enforcement CANNOT land here. What lands here is (a) the CONTRACT as pure,
stdlib-only functions -- the exact validators and the fold the follow-up fix
ticket ports verbatim into ``server/engine/executor_requests.py`` / the UI
reader -- and (b) the defect DETECTORS that turn every measured defect class
of the live ledger into a named red. The handover spec
(``HANDOFF-request-layer-fix.md``) binds the two halves to the engine files.

Design authority: docs/design/executor-operational-envelope-v1.md section 3
(a request carries ``audience`` and, when the records can settle it,
``resolves_when``). Convergence representation: APPEND-FOLDED -- a repeat
request with the same ``condition_key`` appends one ``request-update`` row;
the reader folds updates into their head so the OPEN LIST still shows one
card per condition. The head row is never rewritten (the ledger's existing
discipline is append-only under ``request_thread._locked_append``, a lock
with no read-modify-write recovery path).

Legacy contract (backward compatibility, ticket item 8): a row without
``condition_key`` / ``expires_at`` is legal history; nothing here refuses or
rewrites it, and ``fold_updates`` classifies it ``legacy`` so the digest can
carry it instead of dropping it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: a FULL ticket id (t261021-08 shape). "45 stops on an identical face" is
#: the measured disease: an elided id stops being readable a day later.
TICKET_RE = re.compile(r"(?i)\bt\d{6}-\d{2}\b")

#: per-instance values that must never survive in a condition key (the
#: measured disease: ``run-silent:<line>:<round>`` -- one card per round).
PER_INSTANCE_RE = re.compile(
    r"round[-_ ]?\d+|run[-_ ]?\d+|\brun_id\b|\bround\b|"
    r"\b1[0-9]{12}\b"                # millisecond timestamps
    r"|\b\d{4}-\d{2}-\d{2}\b")       # ISO dates

#: a default_action that only re-checks is a card filed for a condition that
#: resolves itself (measured: "run-watch re-checks the records next tick").
NOOP_DEFAULT_RE = re.compile(
    r"re-?check|next\s+tick|\bwatch\b|\bmonitor\b", re.IGNORECASE)

#: kind -> expiry TTL in ms (behavior 6: every card carries an expiry; the
#: producer may stamp its own, this is the default when it does not).
KIND_TTL_MS = {
    "blocker": 7 * 24 * 3600 * 1000,
    "authorization": 7 * 24 * 3600 * 1000,
    "notice": 48 * 3600 * 1000,
    "question": 72 * 3600 * 1000,
    "decision": 72 * 3600 * 1000,
    "run-stalled": 7 * 24 * 3600 * 1000,
    "run-silent": 7 * 24 * 3600 * 1000,
}
DEFAULT_TTL_MS = 72 * 3600 * 1000

#: the declared open-card cap (behavior 7); env-overridable at the engine
#: call site (SANDBAR_REQUESTS_OPEN_CAP), this is the declared default.
OPEN_CARD_CAP = 20

HOST_AUDIENCES = ("host",)


def _refuse(field: str, reason: str) -> Dict[str, Any]:
    return {"ok": False, "field": field, "reason": reason}


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    return dict(payload, ok=True)


# ---------- validators (the spec the fix ticket ports verbatim) ----------


def normalize_condition_key(row: Dict[str, Any]) -> Dict[str, Any]:
    """Behavior 1: build ``kind:project:line/ticket:cause`` and refuse any
    per-instance value inside it. The cause is normalized (lowercased,
    whitespace collapsed, per-instance tokens stripped); an empty normalized
    cause or a missing kind/project is a named refusal."""
    kind = str(row.get("kind") or "").strip()
    project = str(row.get("project") or "").strip()
    if not kind:
        return _refuse("condition_key", "missing kind")
    if not project:
        return _refuse("condition_key", "missing project")
    line = str(row.get("line") or "").strip()
    ticket = str(row.get("ticket") or "").strip()
    if not line and not ticket:
        return _refuse("condition_key", "needs line or ticket")
    cause = re.sub(r"\s+", " ", str(row.get("cause") or row.get("question") or "")
                   ).strip().lower()
    if PER_INSTANCE_RE.search(cause):
        return _refuse("condition_key",
                       "per-instance-value: the condition key must name the "
                       "condition, never a round id / run id / timestamp")
    cause = PER_INSTANCE_RE.sub(" ", cause)
    cause = re.sub(r"\s+", " ", cause).strip(" :-")
    if not cause:
        return _refuse("condition_key", "cause normalizes to empty")
    return _ok({"condition_key": "%s:%s:%s:%s" % (
        kind, project, ticket or line, cause)})


def check_self_contained(row: Dict[str, Any]) -> Dict[str, Any]:
    """Behavior 2: the row must name the ticket id IN FULL, the line, the
    stage and the decision asked. Returns the list of what is missing; a
    non-empty list is a named refusal at the write path."""
    missing: List[str] = []
    question = str(row.get("question") or "")
    ticket = str(row.get("ticket") or "")
    if not (TICKET_RE.search(ticket) or TICKET_RE.search(question)):
        missing.append("full_ticket_id")
    if not str(row.get("line") or "").strip():
        missing.append("line")
    if not str(row.get("stage") or "").strip():
        missing.append("stage")
    decision = row.get("decision")
    has_decision = (isinstance(decision, str) and decision.strip()) or \
        (isinstance(decision, list) and len(decision) >= 2)
    if not has_decision:
        missing.append("decision_yes_no_or_named_options")
    if missing:
        return _refuse("self_contained",
                       "question is not self-contained, missing: "
                       + ", ".join(missing))
    return _ok({"missing": []})


def check_default_action(row: Dict[str, Any]) -> Dict[str, Any]:
    """Behavior 3: a concrete default ({action, after_ms}) or an explicit
    hold ({hold: true}). A no-op re-check default is refused BY NAME."""
    da = row.get("default_action")
    if isinstance(da, dict):
        if da.get("hold") is True:
            return _ok({"default": "hold"})
        action = str(da.get("action") or "").strip()
        after = da.get("after_ms")
        if action and isinstance(after, int) and not isinstance(after, bool) \
                and after > 0:
            return _ok({"default": action})
        return _refuse("default_action",
                       "a dict default needs action + a positive after_ms "
                       "(got action=%r after_ms=%r)" % (action, after))
    if isinstance(da, str):
        if NOOP_DEFAULT_RE.search(da):
            return _refuse("default_action", "no-op-recheck: a default that "
                           "only re-checks files a card for a condition that "
                           "resolves itself")
        if da.strip():
            return _ok({"default": da.strip()})
    return _refuse("default_action", "missing: carry a concrete default "
                   "{action, after_ms} or {hold: true}")


def route_audience(row: Dict[str, Any]) -> Dict[str, Any]:
    """Behavior 4: only host-audience rows reach the host ledger; a row
    addressed to another role goes to that role's thread surface. Returns
    ``surface`` = "host" or "role:<role>" (the file is the role surface, not
    requests.jsonl). A missing audience defaults to host (legacy shape)."""
    audience = row.get("audience")
    if audience is None:
        return _ok({"surface": "host"})
    if not isinstance(audience, str) or not audience.strip():
        return _refuse("audience", "must be a role name or 'host'")
    a = audience.strip()
    if a in HOST_AUDIENCES:
        return _ok({"surface": "host"})
    return _ok({"surface": "role:%s" % a})


def expiry_for(kind: str, now_ms: int) -> int:
    """Behavior 6: the kind TTL default. An unknown kind still expires (the
    72h question default) -- no card is born immortal."""
    return now_ms + KIND_TTL_MS.get(str(kind or ""), DEFAULT_TTL_MS)


# ---------- the fold (behavior 1/5/6/7 consumer half) ----------


def fold_updates(rows: List[Dict[str, Any]], now_ms: int,
                 cap: int = OPEN_CARD_CAP) -> Dict[str, Any]:
    """Fold a requests ledger into the open-list view.

    Returns:
      heads     every head row, folded: ``count`` / ``last_seen`` from its
                ``request-update`` rows, ``state`` from its latest state row
                (resolved/expired/dismissed/answered), ``folded_into`` when
                it lost the cap contest, ``legacy`` when it predates the
                condition contract.
      open      resolved/expired/folded heads excluded -- what the host sees.
      expired   ids of heads whose ``expires_at`` passed (counted in the
                digest, never silently dropped).
      legacy    ids of heads with no condition key and no expiry.
      orphans   count of update rows naming no known head (counted, never
                folded into nothing).
      digest    ONE digest card above the cap (or None): lists the folded
                heads with their ages and which carry a default.
    """
    heads_by_id: Dict[str, Dict[str, Any]] = {}
    updates: List[Dict[str, Any]] = []
    states: Dict[str, str] = {}
    orphans = 0
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        rtype = str(r.get("type") or "")
        if rtype == "request" and rid:
            heads_by_id[rid] = dict(r, count=1, last_seen=r.get("at"))
        elif rtype == "request-update":
            updates.append(r)
        elif rtype in ("resolved", "expired", "dismissed", "answered"):
            # the state row is attached by its own id OR an explicit head
            # reference (both shapes exist on the ledger) -- a row naming
            # neither head is ignored, never misattached
            target = str(r.get("head") or r.get("id") or "")
            if target:
                states[target] = rtype
    # condition identity (behavior 1, reader half): a SECOND head row with a
    # key already on file is the same condition -- it folds into the first
    # head (count+1, last_seen) instead of standing as another card. The
    # write path must not create these rows; until it enforces that, the
    # reader still converges them (the measured 6-cards disease dies here).
    keys: Dict[str, str] = {}
    merged: Dict[str, str] = {}
    for hid in sorted(heads_by_id, key=lambda i: heads_by_id[i].get("at") or 0):
        ck = heads_by_id[hid].get("condition_key")
        if isinstance(ck, str) and ck:
            if ck in keys:
                first = heads_by_id[keys[ck]]
                first["count"] = int(first.get("count") or 1) + 1
                if (heads_by_id[hid].get("at") or 0) >= (first.get("at") or 0):
                    first["last_seen"] = heads_by_id[hid].get("at")
                merged[hid] = keys[ck]
            else:
                keys[ck] = hid
    for hid in merged:
        del heads_by_id[hid]
    for u in updates:
        ck = str(u.get("condition_key") or "")
        hid = keys.get(ck)
        if hid is None:
            orphans += 1
            continue
        h = heads_by_id[hid]
        h["count"] = int(h.get("count") or 1) + int(u.get("count") or 1)
        if u.get("last_seen") is not None:
            h["last_seen"] = u["last_seen"]
    open_heads: List[Dict[str, Any]] = []
    expired: List[str] = []
    for hid, h in heads_by_id.items():
        h["state"] = states.get(hid, "open")
        ck = h.get("condition_key")
        exp = h.get("expires_at")
        h["legacy"] = not (isinstance(ck, str) and ck) and exp is None
        if h["state"] == "resolved":
            continue
        if isinstance(exp, (int, float)) and now_ms > exp:
            h["state"] = "expired"
            expired.append(hid)
            continue
        open_heads.append(h)
    open_heads.sort(key=lambda h: (h.get("at") or 0))
    digest: Optional[Dict[str, Any]] = None
    if len(open_heads) > cap:
        keep, folded = open_heads[:cap], open_heads[cap:]
        digest = {
            "type": "request-digest",
            "id": "digest-%d" % now_ms,
            "at": now_ms,
            "kind": "digest",
            "question": "%d open cards above the cap of %d" % (len(folded), cap),
            "folded": [{"id": f["id"], "age_ms": now_ms - (f.get("at") or 0),
                        "has_default": bool(f.get("default_action"))}
                       for f in folded],
        }
        for f in folded:
            f["folded_into"] = digest["id"]
        open_heads = keep
    return {"heads": list(heads_by_id.values()), "open": open_heads,
            "expired": expired,
            "legacy": [h["id"] for h in heads_by_id.values() if h["legacy"]],
            "orphans": orphans, "digest": digest}


# ---------- defect detectors (one per measured class) ----------


def _heads(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows or () if isinstance(r, dict)
            and r.get("type") == "request" and r.get("id")]


def _ids(rows: List[Dict[str, Any]], pred) -> List[str]:
    return [str(h["id"]) for h in _heads(rows) if pred(h)]


def detect_duplicate_condition_keys(rows: List[Dict[str, Any]]) -> List[str]:
    """D1 (measured: 6 run-silent cards, one per round)."""
    seen: Dict[str, str] = {}
    bad: List[str] = []
    for h in _heads(rows):
        ck = h.get("condition_key")
        if not isinstance(ck, str) or not ck:
            continue
        if ck in seen:
            bad.append(str(h["id"]))
        else:
            seen[ck] = h["id"]
    return bad


def detect_elided_ticket_ids(rows: List[Dict[str, Any]]) -> List[str]:
    """D2 (measured: '45 stops on an identical face')."""
    return _ids(rows, lambda h: not TICKET_RE.search(str(h.get("question") or ""))
                and not TICKET_RE.search(str(h.get("ticket") or "")))


def detect_why_questions(rows: List[Dict[str, Any]]) -> List[str]:
    """D3 (measured: 'Gate receipt counts 8 over the list, every round.
    Why?') -- a question that asks why instead of naming a defect and a
    decision."""
    def _why(h):
        if re.search(r"\bwhy\b|\?\s*$", str(h.get("question") or "")):
            d = h.get("decision")
            named = (isinstance(d, str) and d.strip()) or \
                (isinstance(d, list) and len(d) >= 2)
            return not named
        return False
    return _ids(rows, _why)


def detect_noop_defaults(rows: List[Dict[str, Any]]) -> List[str]:
    """D4 (measured: 'run-watch re-checks the records next tick')."""
    return _ids(rows, lambda h: isinstance(h.get("default_action"), str)
                and bool(NOOP_DEFAULT_RE.search(h["default_action"])))


def detect_null_expiry(rows: List[Dict[str, Any]]) -> List[str]:
    """D5 (measured: expires_at null on every row). Legacy rows carry null
    too -- the detector reports them; the fix ticket's acceptance counts only
    POST-fix rows."""
    return _ids(rows, lambda h: h.get("expires_at") is None)


def detect_cross_role_notices(rows: List[Dict[str, Any]]) -> List[str]:
    """D6 (measured: 18 notice rows addressed to another role in the HOST
    ledger)."""
    def _foreign(h):
        a = h.get("audience")
        if isinstance(a, str):
            return bool(a.strip()) and a.strip() not in HOST_AUDIENCES
        # legacy shape: no audience field, the addressee only in the text
        # (measured: an addressee marker in the question/detail) -- that
        # mention is the detector's object, a sanctioned mention by role
        text = str(h.get("question") or "") + str(h.get("detail") or "")
        return a is None and bool(re.search(r"【给(?!宿主)|给(?!宿主)", text))
    return _ids(rows, _foreign)


def detect_uncollapsed_corrections(rows: List[Dict[str, Any]]) -> List[str]:
    """D7 (measured: 35 correction/supersedes rows, 12 percent) -- update
    rows for one condition that no reader folded."""
    folded_keys = set()
    for r in rows or ():
        if isinstance(r, dict) and r.get("type") == "request-update":
            folded_keys.add(str(r.get("condition_key") or ""))
    bad: List[str] = []
    for r in rows or ():
        if isinstance(r, dict) and str(r.get("type") or "").startswith(
                ("correction", "supersede", "superseded")):
            if str(r.get("condition_key") or "") not in folded_keys:
                bad.append(str(r.get("id") or ""))
    return bad


DETECTORS = (
    ("duplicate_condition_keys", detect_duplicate_condition_keys),
    ("elided_ticket_ids", detect_elided_ticket_ids),
    ("why_questions", detect_why_questions),
    ("noop_defaults", detect_noop_defaults),
    ("null_expiry", detect_null_expiry),
    ("cross_role_notices", detect_cross_role_notices),
    ("uncollapsed_corrections", detect_uncollapsed_corrections),
)


def run_all_detectors(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Every measured class, evidence-first: each detector returns the
    offending row ids."""
    return {name: fn(rows) for name, fn in DETECTORS}
