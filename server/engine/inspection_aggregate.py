#!/usr/bin/env python3
"""inspection_aggregate — cross-face / cross-period aggregate weekly page
(epic inspection ticket 3, t261006-14).

Position (same discipline as inspection_deadman): a READ-ONLY pure-function
layer over the ledger directory and journals — zero temporalio dependency. It
only derives; it keeps NO books of its own: every input comes from existing
artifacts (period ledgers inspection-<instance>-<period>.json, verdict
ledgers -verdicts.json, spawn/reopen journals). No second ledger is
introduced (the "hand-maintained register becomes a dead table" discipline).
The write privilege belongs to the calling shell only
(inspection_trigger.py `weekly`), and it writes exactly ONE file, its own
report: aggregate-<instance>-<anchor-period>.json — the `aggregate-` prefix
deliberately fails inspection_deadman.LEDGER_NAME_RE / ledger_periods(), so
the aggregate never enters per-period deadman accounting.

Three declared rules (plan gen1; each pinned by unit tests):
  1) "New this week" window (three conditions): the finding's period falls
     inside the window (anchor = newest readable period; window =
     (anchor - window_days, anchor], start EXCLUSIVE, window_days default 7)
     AND the first-seen entry is counted (not recurring/suppressed, per
     is_counted) AND the id is absent from every period before the window.
  2) Conflicting verdicts across periods: the NEWEST period by
     period_sort_key wins; within one period file the LAST entry wins (same
     consumption rule the verdict writer documents). (period, file position)
     is a total order — no ties.
  3) Overdue: age > overdue_days (default 7) from the first-seen date AND no
     adjudication (winner is not false-positive) AND no fix-ticket record
     (the injected ticket_lookup returns None). A finding whose FIRST-SEEN
     entry already carries recurring=True (its earlier ledger is gone or
     pruned, real origin unknowable) is conservatively aged from before the
     window — rather report one extra overdue than miss one.

Ticket state is an INJECTED face: ticket_lookup(finding) ->
{ticket_id, state, closed} | None. The pure layer never guesses; None means
"no ticket record for this finding". No injected reader at all =>
ticket_states_available=false. A raising reader is caught and named in
ticket_reader_errors; the finding stays conservatively open — never a
corrupt page.

Degradation is explicit (never silent): a missing/damaged ledger lands in
periods_not_available with a reason; a damaged verdicts file carries
read_verdicts_file's named error; a torn trailing .jsonl journal line keeps
the borrowed readers' line-level tolerance but its skip count surfaces in
journal_note — the gap is visible, not hidden.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

WINDOW_DAYS_DEFAULT = 7
OVERDUE_DAYS_DEFAULT = 7

#: journal torn-tail / bad-line count keys (visible-gap face)
#: t261008-22: the void journal joins the registry — a torn void row is a swallowed
#: human signature, so it must stay visible in the aggregate's malformed-count face.
JOURNAL_NAMES = ("inspection-spawn.jsonl", "inspection-reopen.jsonl",
                 "inspection-void.jsonl")

#: the ordering statement carried verbatim in the report body (explicit
#: declaration; never any data source's iteration order)
ORDERING_NOTE = (
    "instances by id; periods by period_sort_key (date, bucket) — descending "
    "for winner election, ascending for listing; findings by (SEVERITY_RANK, "
    "finding id)")

#: t261009-69 receipt (requirement 5): the mint widened 8 -> 16 hex; old period
#: ledgers on disk still carry 8-hex ids and are NOT renumbered. Cross-period and
#: verdict matching therefore resolves a stored id by stored value first, then by
#: the 8-hex prefix rule (an 8-hex id is a strict prefix of the widened id for the
#: same content, because the widening only extends the same sha256 digest).
LEGACY_ID_NOTE = (
    "finding ids are minted at 16 hex since t261009-69; stored 8-hex ids from "
    "older period ledgers still resolve (exact match, else 8-hex prefix of the "
    "widened id) — history is not renumbered")

_MINT_ID_WIDTH = 16


def _fid_lookup_keys(fid: str) -> List[str]:
    """Lookup keys for a minted finding id: the id itself, then its 8-hex
    prefix when widened (the alias under which an older ledger stored it).
    Stored values are compared AS STORED (no case folding — ids are minted
    lowercase, but a stored id must keep resolving verbatim)."""
    f = str(fid or "").strip()
    if len(f) > 8:
        return [f, f[:8]]
    return [f]

_SEVERITY_RANK = {"high": 0, "med": 1, "low": 2}
_PERIOD_RE = re.compile(r"^(\d{8})(?:-([1-9]\d*))?$")


# ========================================================================================
# period helpers (period_sort_key single-sourced from inspection_inspect, lazy import)
# ========================================================================================

def _sort_key(period: str) -> Tuple[int, int]:
    from inspection_inspect import period_sort_key
    return period_sort_key(period)


def _period_date(period: str) -> Optional[date]:
    m = _PERIOD_RE.match(str(period or ""))
    if not m:
        return None
    s = m.group(1)
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def aggregate_report_name(instance_id: str, anchor_period: str) -> str:
    """Report file name (single point): aggregate-<instance>-<anchor-period>.json.
    The anchor period is the newest period covered by the window. The
    `aggregate-` prefix deliberately falls outside inspection_deadman.LEDGER_NAME_RE
    (which requires the `inspection-` prefix) — the aggregate never mixes into
    per-period ledger accounting."""
    if not instance_id or not _PERIOD_RE.match(str(anchor_period or "")):
        raise ValueError(
            "aggregate report name needs instance_id and an anchor period (got %r / %r)"
            % (instance_id, anchor_period))
    return "aggregate-%s-%s.json" % (instance_id, anchor_period)


# ========================================================================================
# period-x-face coverage (t261009-49, KI-01M4GGFXPAHDGSQ9767VMB5NGM)
# ========================================================================================
#
# A SECOND fact, never merged with the dead-man verdict: dead-man answers "was the
# period's ticket created?" and counts a blocked/failed ticket as ran — right for the
# missing-run question. This face answers one level down, "did the face PRODUCE a
# result this period", and reports one row per (declared instance, period) with
# exactly one state:
#
#   produced   — the ledger is readable and served (blocked_reason empty/absent; an
#                all-green served ledger is a produced result).
#   blocked    — the BLOCKED-SHELL shape: readable ledger + non-empty blocked_reason
#                + zero served findings (t261002-12; judgement single-sources
#                inspection_ticketing.period_ledger_face — no second truth). This is
#                "ran but produced nothing" and must never read produced.
#   failed     — attempts exist (injected reader) but no served ledger was produced.
#   not_run    — zero attempts recorded for the period. Different fact, different
#                copy from failed.
#   unreadable — the ledger file exists but cannot be parsed (or is not a dict).
#                Named as unreadable; no default turns it into fine or missing.
#
# One-way accounting (ticket spec item 4): no new ledger kind, no second source of
# "did this face run" — the projection reads the existing period ledgers and, via an
# INJECTED reader (same discipline as build_aggregate's ticket_lookup), the attempt
# rows. The projection is droppable, rebuildable, and cited by nothing. Attempt
# terminal states are never re-derived here (the five-state single point owns them).

COVERAGE_STATES = ("produced", "blocked", "failed", "not_run", "unreadable")

#: Per-row attempt evidence cap (anti-flooding; the overflow is counted, not hidden).
COVERAGE_ATTEMPT_CAP = 5

COVERAGE_NOTE = (
    "one row per (declared instance, period); exactly one of %s. A blocked shell "
    "(readable ledger + non-empty blocked_reason) is 'blocked', never 'produced'. "
    "last_ok_period = the newest strictly-earlier period this face produced a result, "
    "or the literal 'never'. Attempt states are carried verbatim from the injected "
    "reader; a state the reader does not know stays verbatim — terminal states are "
    "never re-derived here." % ", ".join(COVERAGE_STATES))


def _read_one_ledger(ledger_dir: Any, instance_id: str, period: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """One period ledger -> (doc|None, "ok"|"unreadable"|"absent"). Absent is distinct
    from unreadable: absent feeds the attempt question, unreadable is named as such
    (never fine, never missing)."""
    path = Path(str(ledger_dir)) / ("inspection-%s-%s.json" % (instance_id, period))
    try:
        raw = path.read_text("utf-8")
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    try:
        doc = json.loads(raw)
    except ValueError:
        return None, "unreadable"
    if not isinstance(doc, dict):
        return None, "unreadable"
    # Same served-shape bar as read_period_ledgers: a served ledger always carries a
    # findings list; a doc without one is malformed on this face too (unless it is a
    # blocked shell, whose served evidence is the blocked_reason itself).
    if not isinstance(doc.get("findings"), list) and not str(doc.get("blocked_reason") or "").strip():
        return None, "unreadable"
    return doc, "ok"


def _sanitize_attempts(raw: Any) -> Tuple[List[Dict[str, str]], int]:
    """Attempt rows -> sanitised evidence + malformed count. Non-list input counts as
    one malformed row; non-dict entries are counted, never fabricated into evidence."""
    if not isinstance(raw, list):
        return [], 1
    out: List[Dict[str, str]] = []
    bad = 0
    for e in raw:
        if isinstance(e, dict):
            # `terminal_state` is the journal-row vocabulary; `state` the reader
            # shorthand — either is accepted, both stay verbatim (never re-derived).
            out.append({"ticket_id": str(e.get("ticket_id") or "").strip(),
                        "state": str(e.get("state") or e.get("terminal_state") or "").strip(),
                        "blocked_reason": str(e.get("blocked_reason") or "").strip()})
        else:
            bad += 1
    return out, bad


def face_coverage(instance_id: str, face_id: str, ledger_dir: Any, periods: Any,
                  attempts: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """The pure coverage projection (see the section comment above for the contract).

    attempts(period) -> list of {ticket_id, state, blocked_reason} | anything:
    the INJECTED attempt reader. None means "no reader on this surface": rows stay
    derivable, `attempts_available=false` says so, and an absent-ledger row reads
    not_run with the explicit caveat — the surface could not check attempts, so
    "no attempt" is that surface's limit, not a verified fact. A raising reader
    degrades named per period (never crash, never silent green)."""
    from inspection_ticketing import period_ledger_face

    inst = str(instance_id or "")
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    malformed_total = 0
    period_list = sorted({str(p) for p in (periods or []) if str(p)}, key=_sort_key)
    last_ok: Optional[str] = None
    for period in period_list:
        prev_ok = last_ok
        doc, status = _read_one_ledger(ledger_dir, inst, period)
        evidence: List[Dict[str, str]] = []
        if status == "ok":
            if period_ledger_face(doc, str((doc or {}).get("ticket_id") or "")) == "blocked":
                result = "blocked"
                evidence = [{"ticket_id": str((doc or {}).get("ticket_id") or ""),
                             "state": "blocked",
                             "blocked_reason": str((doc or {}).get("blocked_reason") or "").strip()}]
            else:
                result = "produced"
                last_ok = period
        elif status == "unreadable":
            result = "unreadable"
        else:  # absent ledger -> the attempt question
            attempt_rows: Any = []
            if attempts is not None:
                try:
                    attempt_rows = attempts(period)
                except Exception as e:  # noqa: BLE001 — a raising reader degrades named, not corrupt
                    errors.append("attempts reader failed for %s: %s: %s"
                                  % (period, type(e).__name__, e))
                    attempt_rows = []
            evidence, malformed = _sanitize_attempts(attempt_rows)
            malformed_total += malformed
            result = "failed" if evidence else "not_run"
        rows.append({
            "period": period,
            "face": str(face_id) if face_id else None,
            # `result` and `state` are the same five-state value under both names:
            # `state` is the vocabulary word, `result` the report-field name.
            "result": result,
            "state": result,
            "last_ok_period": prev_ok if prev_ok else "never",
            "attempts": evidence[:COVERAGE_ATTEMPT_CAP],
            "attempts_truncated": max(0, len(evidence) - COVERAGE_ATTEMPT_CAP),
            "attempts_unavailable": result == "not_run" and attempts is None,
        })
    return {
        "kind": "inspection-coverage",
        "instance_id": inst,
        "face": str(face_id) if face_id else None,
        "attempts_available": attempts is not None,
        "attempts_reader_errors": sorted(errors),
        "malformed_attempt_rows": malformed_total,
        "states": list(COVERAGE_STATES),
        "rows": rows,
        "produced_nothing": [r for r in rows if r["result"] != "produced"],
        "note": COVERAGE_NOTE,
    }


# ========================================================================================
# read-only collection (every face degrades explicitly; one bad file never kills the page)
# ========================================================================================

def read_period_ledgers(ledger_dir: Any, instance_id: str) -> Dict[str, Any]:
    """Period ledgers: {period: doc} plus not_available{period: reason} — missing
    and damaged files named per entry, never silently blank."""
    from inspection_deadman import ledger_periods
    inst = str(instance_id or "")
    out: Dict[str, Any] = {"docs": {}, "not_available": {}, "ledger_exist": False,
                           "malformed_names": []}
    if not inst:
        out["not_available"]["<none>"] = "instance id is empty"
        return out
    info = ledger_periods(ledger_dir, inst)
    out["ledger_exist"] = bool(info["exist"])
    out["malformed_names"] = list(info["malformed"])
    d = Path(str(ledger_dir))
    for period in sorted(info["periods"], key=_sort_key):
        try:
            doc = json.loads((d / ("inspection-%s-%s.json" % (inst, period))).read_text("utf-8"))
        except (OSError, ValueError) as e:
            out["not_available"][period] = "ledger unreadable: %s: %s" % (type(e).__name__, e)
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("findings"), list):
            out["not_available"][period] = "ledger malformed: findings list missing"
            continue
        out["docs"][period] = doc
    return out


def collect_winning_verdicts(ledger_dir: Any, instance_id: str) -> Dict[str, Any]:
    """Verdict ledgers -> {finding_id: winning entry}. Winner rule (2): the newest
    period wins; within one period the last entry wins. Damaged-file errors are
    carried named in `errors` (never silently zeroed)."""
    from inspection_inspect import VERDICTS_RECEIPT_SUFFIX, _ledger_candidates, read_verdicts_file
    inst = str(instance_id or "")
    out: Dict[str, Any] = {"winners": {}, "errors": {}}
    if not inst:
        return out
    # _ledger_candidates is newest-first: the first read wins across periods, so an
    # older period can never overwrite a newer verdict (the period axis of rule 2).
    for period, path in _ledger_candidates(Path(ledger_dir), inst, VERDICTS_RECEIPT_SUFFIX):
        res = read_verdicts_file(path)
        if res["error"]:
            out["errors"][period] = res["error"]
            continue
        for entry in res["entries"]:
            fid = str(entry.get("finding_id") or "")
            if fid:
                if fid not in out["winners"]:
                    out["winners"][fid] = dict(entry, period=period)
                else:
                    cur = out["winners"][fid]
                    if _sort_key(cur.get("period") or "") == _sort_key(period):
                        out["winners"][fid] = dict(entry, period=period)
    return out


def journal_skip_counts(ledger_dir: Any) -> Dict[str, Any]:
    """Torn-tail / bad-line count per journal (the visible-gap face; line-level
    tolerance follows the ticketing discipline, but the skipped-line count is
    reported instead of hidden)."""
    out: Dict[str, Any] = {}
    for name in JOURNAL_NAMES:
        try:
            text = (Path(str(ledger_dir)) / name).read_text("utf-8")
        except (FileNotFoundError, OSError):
            continue
        bad = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(row, dict):
                bad += 1
        if bad:
            out[name] = bad
    return out


# ========================================================================================
# aggregate assembly (pure derivation; the three declared rules live here)
# ========================================================================================

def _counted(finding: Dict[str, Any]) -> bool:
    from inspection_inspect import is_counted
    return bool(is_counted(finding))


def build_aggregate(instance_id: str, ledger_dir: Any,
                    window_days: int = WINDOW_DAYS_DEFAULT,
                    overdue_days: int = OVERDUE_DAYS_DEFAULT,
                    cron: str = "", tz_name: str = "",
                    lookback_days: int = 7, grace_days: int = 0,
                    ticket_lookup: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
                    declared_face: str = "",
                    attempts: Optional[Callable[[str], Any]] = None,
                    ) -> Dict[str, Any]:
    """Assemble the one page (read-only derivation; the write privilege is the
    shell's). ticket_lookup(finding) -> {"ticket_id","state","closed"} | None:
    the injected ticket-state reader. No reader injected =>
    ticket_states_available=false; every finding without a record stays
    conservatively open. declared_face / attempts feed the period-x-face coverage
    projection (face_coverage, t261009-49): declared_face is the instance's declared
    scan_face — an empty value keeps the rows but carries face=None (the declared
    face is named as not supplied on this call, never invented)."""
    from inspection_deadman import missed_periods
    from inspection_inspect import SEVERITY_RANK
    from inspection_ticketing import spawn_skip_periods

    inst = str(instance_id or "")
    ledgers = read_period_ledgers(ledger_dir, inst)
    verdicts = collect_winning_verdicts(ledger_dir, inst)
    skips = journal_skip_counts(ledger_dir)
    skipped_no_change = spawn_skip_periods(ledger_dir, inst)

    periods = sorted(ledgers["docs"], key=_sort_key)
    anchor = periods[-1] if periods else ""
    anchor_date = _period_date(anchor)

    # ---- missing periods (deadman single source; explained idle stays separate) ----
    missed: List[str] = []
    deadman_error = ""
    if cron:
        try:
            missed = missed_periods(cron, set(periods) | skipped_no_change, None,
                                    lookback_days, grace_days, tz_name)
        except Exception as e:  # noqa: BLE001 — unparseable cron is named, never faked green
            deadman_error = "%s: %s" % (type(e).__name__, e)

    # ---- window and first-seen (window = (anchor - window_days, anchor], start
    #      EXCLUSIVE; ledgers outside the window never enter `new`) ----
    window_start_date = (anchor_date - timedelta(days=max(0, int(window_days)))
                         ) if anchor_date else None
    first_seen: Dict[str, str] = {}
    first_seen_finding: Dict[str, Dict[str, Any]] = {}
    # legacy-id aliases (t261009-69): alias key -> canonical id, so an 8-hex id
    # stored in an older ledger resolves to the same finding as its widened form
    fid_alias: Dict[str, str] = {}

    def _canon(fid: str) -> str:
        """Resolve a finding id to its canonical key: exact alias hit first,
        then the 8-hex prefix alias (a stored 8-hex id seen earlier resolves a
        later widened sighting of the same content), else the id itself."""
        f = str(fid or "").strip()
        if f in fid_alias:
            return fid_alias[f]
        if len(f) > 8 and f[:8] in fid_alias:
            return fid_alias[f[:8]]
        return f

    for period in periods:
        for f in ledgers["docs"][period].get("findings") or []:
            if isinstance(f, dict) and f.get("id"):
                fid = str(f["id"])
                canon = _canon(fid)
                for k in _fid_lookup_keys(fid):
                    fid_alias.setdefault(k, canon)
                if canon not in first_seen:
                    first_seen[canon] = period
                    first_seen_finding[canon] = f
    in_window = [p for p in periods
                 if anchor_date and _period_date(p)
                 and window_start_date < _period_date(p) <= anchor_date]

    # ---- per-finding derivation (one final state per id; a later period overwrites,
    #      same order as rule 2) ----
    new_by_sev: Dict[str, int] = {"high": 0, "med": 0, "low": 0}
    latest: Dict[str, Dict[str, Any]] = {}
    # ticket-state availability = whether a reader was injected at all (a None
    # return means "no ticket record for this finding", not "reader unavailable").
    ticket_states_available = ticket_lookup is not None

    for period in in_window:
        doc = ledgers["docs"][period]
        for f in doc.get("findings") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            fid = str(f["id"])
            canon = fid_alias.get(fid, fid)   # legacy 8-hex stored id resolves here
            seen = first_seen.get(canon, period)
            latest[canon] = {"finding": f, "period": period, "seen": seen,
                             "id": fid}

    new_findings: List[Dict[str, Any]] = []
    fixed: List[Dict[str, Any]] = []
    open_items: List[Dict[str, Any]] = []
    overdue: List[Dict[str, Any]] = []
    added_new: set = set()
    ticket_reader_errors: List[str] = []

    for canon, st in latest.items():
        f, period, seen = st["finding"], st["period"], st["seen"]
        fid = st.get("id") or canon
        # rule 1: first-seen inside the window AND the first-seen entry counts.
        # A later recurring flag does not un-new the first occurrence.
        if seen in in_window and _counted(first_seen_finding.get(canon, f)) \
                and canon not in added_new:
            added_new.add(canon)
            new_by_sev[str(f.get("severity"))] = \
                new_by_sev.get(str(f.get("severity")), 0) + 1
            new_findings.append(dict(f, period=period))
        winner = None
        for k in _fid_lookup_keys(fid) + _fid_lookup_keys(canon):
            winner = verdicts["winners"].get(k)   # stored value first, then prefix alias
            if winner:
                break
        verdict = str((winner or {}).get("verdict") or "")
        try:
            lookup = ticket_lookup(f) if ticket_lookup else None
        except Exception as e:  # noqa: BLE001 — a raising reader degrades named, not corrupt
            lookup = None
            ticket_reader_errors.append(
                "ticket-state reader failed for %s: %s: %s" % (fid, type(e).__name__, e))
        entry = {"id": fid, "scan": f.get("scan"), "severity": f.get("severity"),
                 "subject": f.get("subject"), "first_seen": seen, "period": period,
                 "verdict": verdict or None,
                 "ticket": (lookup or {}).get("ticket_id"),
                 "ticket_state": (lookup or {}).get("state")}
        if verdict == "false-positive":
            continue                       # adjudicated: not open / fixed / overdue
        if lookup and lookup.get("closed"):
            fixed.append(entry)
            continue
        open_items.append(entry)
        # overdue age: counted from the first-seen date. A finding whose first-seen
        # entry is already recurring (earlier ledger gone/pruned, real origin
        # unknowable) is conservatively aged from before the window.
        seen_date = _period_date(seen)
        if seen_date and window_start_date \
                and bool(first_seen_finding.get(canon, {}).get("recurring")):
            seen_date = min(seen_date, window_start_date - timedelta(days=1))
        if (anchor_date and seen_date
                and (anchor_date - seen_date).days > int(overdue_days)
                and lookup is None):
            overdue.append(entry)

    def _fk(e: Dict[str, Any]) -> Tuple[int, str]:
        return (SEVERITY_RANK.get(str(e.get("severity")), 9), str(e.get("id")))

    new_findings.sort(key=_fk)
    fixed.sort(key=_fk)
    open_items.sort(key=_fk)
    overdue.sort(key=_fk)

    not_available = dict(ledgers["not_available"])
    for period, err in sorted(verdicts["errors"].items()):
        not_available["%s (verdicts)" % period] = err

    # ---- period-x-face coverage projection (t261009-49; droppable, cited by nothing):
    #      window periods PLUS any unreadable-ledger period inside the window (an
    #      unreadable ledger is a named row, never a silent absence). The window's
    #      upper bound extends to the newest named ledger period even when it is
    #      unreadable — otherwise the very period that produced nothing would fall
    #      outside the window. Fallback: the anchor alone when the window collapsed. ----
    coverage_periods = set(in_window) or ({anchor} if anchor else set())
    cov_upper = anchor_date
    for p in ledgers["not_available"]:
        pd = _period_date(p) if _PERIOD_RE.match(str(p)) else None
        if pd is None:
            continue
        if cov_upper is None or pd > cov_upper:
            cov_upper = pd
    if anchor_date and window_start_date and cov_upper:
        for p in ledgers["not_available"]:
            pd = _period_date(p) if _PERIOD_RE.match(str(p)) else None
            if pd and window_start_date < pd <= cov_upper:
                coverage_periods.add(p)
    coverage = face_coverage(inst, declared_face, ledger_dir, sorted(coverage_periods), attempts)

    return {
        "kind": "inspection-aggregate",
        "instance_id": inst,
        "finding_id_width": _MINT_ID_WIDTH,
        "legacy_id_note": LEGACY_ID_NOTE,
        "anchor_period": anchor,
        "window_days": int(window_days),
        "overdue_days": int(overdue_days),
        "ledger_periods": periods,
        "periods_not_available": [{"period": p, "status": "not available", "reason": r}
                                  for p, r in sorted(not_available.items())],
        "malformed_names": sorted(ledgers["malformed_names"]),
        "missed_periods": [p for p in missed if p not in skipped_no_change],
        "skipped_no_change_periods": sorted(skipped_no_change),
        "deadman_error": deadman_error,
        "journal_note": {k: v for k, v in sorted(skips.items())},
        "ticket_states_available": ticket_states_available,
        "ticket_reader_errors": sorted(ticket_reader_errors),
        "new_findings": {"window_periods": in_window,
                         "by_severity": {k: new_by_sev[k] for k in ("high", "med", "low")},
                         "items": new_findings},
        "fixed": fixed,
        "still_open": open_items,
        "overdue": overdue,
        "coverage": coverage,
        "ordering": ORDERING_NOTE,
    }
