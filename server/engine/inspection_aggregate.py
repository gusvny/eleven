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
                    ) -> Dict[str, Any]:
    """Assemble the one page (read-only derivation; the write privilege is the
    shell's). ticket_lookup(finding) -> {"ticket_id","state","closed"} | None:
    the injected ticket-state reader. No reader injected =>
    ticket_states_available=false; every finding without a record stays
    conservatively open."""
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
    for period in periods:
        for f in ledgers["docs"][period].get("findings") or []:
            if isinstance(f, dict) and f.get("id"):
                fid = str(f["id"])
                if fid not in first_seen:
                    first_seen[fid] = period
                    first_seen_finding[fid] = f
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
            seen = first_seen.get(fid, period)
            latest[fid] = {"finding": f, "period": period, "seen": seen}

    new_findings: List[Dict[str, Any]] = []
    fixed: List[Dict[str, Any]] = []
    open_items: List[Dict[str, Any]] = []
    overdue: List[Dict[str, Any]] = []
    added_new: set = set()
    ticket_reader_errors: List[str] = []

    for fid, st in latest.items():
        f, period, seen = st["finding"], st["period"], st["seen"]
        # rule 1: first-seen inside the window AND the first-seen entry counts.
        # A later recurring flag does not un-new the first occurrence.
        if seen in in_window and _counted(first_seen_finding.get(fid, f)) \
                and fid not in added_new:
            added_new.add(fid)
            new_by_sev[str(f.get("severity"))] = \
                new_by_sev.get(str(f.get("severity")), 0) + 1
            new_findings.append(dict(f, period=period))
        winner = verdicts["winners"].get(fid)
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
                and bool(first_seen_finding.get(fid, {}).get("recurring")):
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

    return {
        "kind": "inspection-aggregate",
        "instance_id": inst,
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
        "ordering": ORDERING_NOTE,
    }
