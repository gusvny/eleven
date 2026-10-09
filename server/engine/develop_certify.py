#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""develop_certify — certify a buffer line on a schedule, and bound a red.

Ticket t261009-19 (the proof half of the develop buffer; design source
docs/design/develop-buffer-v1.md goals 6-10, record shapes
docs/reference/ledger-record-models-v1.md section A).

What this module owns:

- The **delivery ledger**: one append-only JSONL holding landing,
  certification, freeze-episode, freeze-change and range-growth rows for a
  project, in ONE ``seq`` ordering space. The shared space is load-bearing:
  "the landings after the line's previous certification" is derived from it,
  which is exactly why ``base``/``covered_from`` were dropped from the record
  models (261009).
- The **certification record**: it CITES a run and never restates what the
  run measured (no counts, no verdict on the certification itself — a red
  certification is still a certification, that is how a freeze gets opened;
  restating is a schema violation, refused by name on append).
- The **schedule decision**: ``should_certify`` — event-driven trigger with a
  timed backstop, at most one certification in flight per tick (guard token).
  The call site that wires this into the scheduler is T1.3's opening move;
  this module delivers the decision, the guard and the record writer.
- The **bounded red ladder**: ``next_red_action`` answers one pure step at a
  time — rerun the SAME candidate once (the cheap flake discriminator)
  before any search, then the per-lane scenario results as a free first
  filter, then the range — and a range already searched is refused, never
  searched twice (goal 10). The honest outcomes are recorded: ``isolated``,
  or the required second sentence ``boundary, culprit not isolated``.
- The **freeze records**: an episode is an entity (id, line, cause); its
  state, culprits and closure are separate change records keyed to it —
  never editable fields on the episode body. A freeze opens only on a red
  that implicates content; "could not run" writes a range-growth record and
  opens nothing (goal 24: the freeze rule keys on content red, never on an
  unavailable proof).

Dependency seams (the dispatch's "write against concepts" rule): T1.1's
line/landing records and T0.1's run record are consumed as plain record
dicts passed in by the caller — this module never guesses their wiring; the
adapter to integration/scenario_ledger's real store lives with the caller,
so the engine never imports the integration support layer.

Borrowed-implementation fault-mode dispositions (review hook, plan round 2
R1 — the pattern is integration/scenario_ledger.py and its ULID mint):

- flock whole-append serialisation under ``<dir>/.lock``, single write +
  fsync per append: **carried**. The lock file is SEPARATE from the scenario
  ledger's (the delivery ledger lives in the project store, a different
  home); seq assignment happens inside the same critical section.
- duplicate-id refusal on append: **carried** (record models: refuse a
  duplicate id loudly — a collision is silent by construction).
- malformed/partial lines on read: **carried exactly** — bad lines are
  collected and reported (capped at 10), never silently skipped; append
  refuses to touch a ledger that already has malformed lines.
- retention/rollup: **not carried, accepted debt** — these rows are cited by
  other records forever, so the ledger is append-only with no rewrite face;
  growth is slow (one row per landing/certification/event) and the growth
  policy is the fact-ledger design's own later decision.
- append never rewrites ledger bytes: **carried** (t260922-12 R2).
- loud maintenance failures, availability explicit: **carried** — an
  unreadable or corrupt store raises a named error, never reads as "nothing
  known"; a corrupt guard file is a loud failure, never read as "free".
- ULID mint (48-bit ms + 80-bit tail, Crockford base32, monotonic within the
  process, clock-skew floor): **carried**, re-declared here rather than
  imported because the engine must not import the integration support layer
  at module level (the shape is pinned by the record-models document; the
  origin is ``integration/scenario_ledger.py::mint_run_id``).
- batch all-or-nothing append: **carried** — validation precedes the write.
"""

import fcntl
import json
import os
import secrets
import time
from pathlib import Path

LEDGER_DIR_ENV = "SANDBAR_DELIVERY_LEDGER_DIR"
MAIN_NAME = "delivery.jsonl"
LOCK_NAME = ".lock"
GUARD_NAME = "delivery-guard.json"

KIND_LANDING = "landing"
KIND_CERT = "certification"
KIND_FREEZE = "freeze"
KIND_FREEZE_CHANGE = "freeze_change"
KIND_RANGE_GROWTH = "range_growth"

CHANGE_ATTRIBUTION = "attribution"
CHANGE_CLOSED = "closed"
CHANGE_REOPENED = "reopened"
CHANGE_SEARCHED = "searched"
CHANGE_KINDS = (CHANGE_ATTRIBUTION, CHANGE_CLOSED, CHANGE_REOPENED,
                CHANGE_SEARCHED)

BOUNDARY_VALUE = "boundary, culprit not isolated"

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LAST_MINT = {"ms": -1, "tail": 0}


class CertifyError(Exception):
    """A named failure of the certification step. Raised, never guessed."""


class DuplicateIdError(CertifyError):
    """A record id that already exists in the ledger (append-time check)."""


class CouldNotRun(CertifyError):
    """The proof could not be produced as a run: a run header is missing
    (interrupted run) or the run executed nothing (ran == 0). Neither is
    evidence of anything — the caller records range growth, never a red."""


class AlreadySearchedError(CertifyError):
    """The candidate range was already searched for this red (goal 10:
    ranges already attributed are not searched twice)."""


# ---- identity: family prefix + monotonic ULID (stdlib only) ----------------

def _b32(value, bits):
    chars = []
    top = ((bits + 4) // 5 - 1) * 5
    for shift in range(top, -1, -5):
        chars.append(_CROCKFORD[(value >> shift) & 0x1F])
    return "".join(chars)


def mint_id(prefix, at_ms=None):
    """Mint ``<prefix>-<ULID>``: 48-bit millisecond timestamp + 80-bit tail,
    Crockford base32. Monotonic within this process: when the millisecond
    repeats (or a caller passes an instant older than the last mint — the
    clock-skew floor), the tail increments instead of re-randomising, so two
    ids from one process never tie and never order backwards."""
    ms = int(at_ms) if at_ms is not None else int(time.time() * 1000)
    if ms < _LAST_MINT["ms"]:
        ms = _LAST_MINT["ms"]
    if ms == _LAST_MINT["ms"]:
        tail = _LAST_MINT["tail"] + 1
        if tail >= (1 << 80):  # practically unreachable; roll to next ms
            ms += 1
            tail = secrets.randbits(80)
    else:
        tail = secrets.randbits(80)
    _LAST_MINT["ms"] = ms
    _LAST_MINT["tail"] = tail
    return "%s-%s%s" % (prefix, _b32(ms, 48), _b32(tail, 80))


# ---- ledger path -----------------------------------------------------------

def ledger_path(project, ledger_dir=None):
    """Resolve the delivery ledger path for a project. Explicit dir or
    SANDBAR_DELIVERY_LEDGER_DIR means a flat directory holding
    ``<project>.jsonl`` (tests/isolation); default is the project store:
    ``~/.sandbar/projects/<project>/ledger/delivery.jsonl``."""
    d = ledger_dir or os.environ.get(LEDGER_DIR_ENV, "").strip() or None
    if d:
        return Path(d) / ("%s.jsonl" % project)
    home = Path(os.path.expanduser("~"))
    return home / ".sandbar" / "projects" / str(project) / "ledger" / MAIN_NAME


# ---- row validation --------------------------------------------------------

def _bad(why):
    return None, why


def _valid_repos(repos):
    if not isinstance(repos, list) or not repos:
        return False
    for r in repos:
        if not isinstance(r, dict):
            return False
        if not isinstance(r.get("repo"), str) or not r["repo"].strip():
            return False
        if not isinstance(r.get("revision"), str) or not r["revision"].strip():
            return False
    return True


def _valid_at(at):
    return isinstance(at, int) and not isinstance(at, bool) and at > 0


def validate_row(row):
    """Validate one candidate row. Returns (clean_row_or_None, why).
    Unknown kind / missing field / wrong shape is refused by name, never
    guessed around."""
    if not isinstance(row, dict):
        return _bad("row_not_object")
    kind = row.get("kind")
    rid = row.get("id")
    if kind == KIND_LANDING:
        if not (isinstance(rid, str) and rid.startswith("ldg-")):
            return _bad("landing_id_not_ldg")
        for f in ("ticket", "line"):
            if not isinstance(row.get(f), str) or not row[f].strip():
                return _bad("landing_missing_%s" % f)
        if not _valid_repos(row.get("repos")):
            return _bad("landing_repos_invalid")
        if not isinstance(row.get("actor"), str) or not row["actor"].strip():
            return _bad("landing_missing_actor")
    elif kind == KIND_CERT:
        if not (isinstance(rid, str) and rid.startswith("cert-")):
            return _bad("cert_id_not_cert")
        if not isinstance(row.get("line"), str) or not row["line"].strip():
            return _bad("cert_missing_line")
        if not _valid_repos(row.get("repos")):
            return _bad("cert_repos_invalid")
        run = row.get("run")
        if not (isinstance(run, str) and run.startswith("run-")):
            return _bad("cert_run_not_run_id")
        for f in ("booked_red", "judged_by"):
            if not isinstance(row.get(f), str) or not row[f].strip():
                return _bad("cert_missing_%s" % f)
        # Deliberately NO counts / verdict fields here: the certification
        # cites the run; restating it would be a second answer (record
        # models section A) — so restating is a schema violation, refused
        # by name, not just absent by convention.
        for stolen in ("cases", "verdict", "counts"):
            if stolen in row:
                return _bad("cert_restates_run:%s" % stolen)
        # covered_range, if present, is a PROJECTION of the records' order,
        # recomputable at any time by derive_range; the derivation rule is
        # authoritative — a disagreement between the stored copy and the
        # records is a defect to report, never two truths (plan round 2 R3).
        if "covered_range" in row and not isinstance(row["covered_range"], list):
            return _bad("cert_covered_range_not_list")
    elif kind == KIND_FREEZE:
        if not (isinstance(rid, str) and rid.startswith("frz-")):
            return _bad("freeze_id_not_frz")
        if not isinstance(row.get("line"), str) or not row["line"].strip():
            return _bad("freeze_missing_line")
        cause = row.get("cause")
        if not (isinstance(cause, str) and cause.startswith("cert-")):
            return _bad("freeze_cause_not_cert")
        # state / culprit / closure live on separate change records keyed to
        # this episode — they must never appear as editable fields here.
        for stolen in ("state", "closure", "culprit", "landings",
                       "resolved", "attributed"):
            if stolen in row:
                return _bad("freeze_carries_mutable_field:%s" % stolen)
    elif kind == KIND_FREEZE_CHANGE:
        fz = row.get("freeze")
        if not (isinstance(fz, str) and fz.startswith("frz-")):
            return _bad("change_freeze_not_frz")
        if row.get("change") not in CHANGE_KINDS:
            return _bad("change_kind_unknown")
        if row["change"] in (CHANGE_ATTRIBUTION, CHANGE_SEARCHED):
            if not isinstance(row.get("value"), str) or not row["value"].strip():
                return _bad("change_missing_value")
        if not isinstance(row.get("by"), str) or not row["by"].strip():
            return _bad("change_missing_by")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            return _bad("change_missing_reason")
    elif kind == KIND_RANGE_GROWTH:
        # Never cited by anything, so it carries no id: the key is
        # (line, seq). A proof that could not be produced grows the range;
        # it is never a red and never opens a freeze (goal 24).
        if not isinstance(row.get("line"), str) or not row["line"].strip():
            return _bad("growth_missing_line")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            return _bad("growth_missing_reason")
    else:
        return _bad("kind_unknown:%r" % (kind,))
    if not _valid_at(row.get("at")):
        return _bad("at_not_ms")
    return row, ""


# ---- store face (flock append, shared seq space) ---------------------------

def _acquire_lock(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target.parent / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_lock(fd):
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _dumps(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def read_rows(path):
    """Read the ledger. Returns (rows, bad) — bad lines are collected and
    reported (capped at 10), never silently skipped; an absent ledger is an
    empty one, a wrong-shaped path is named."""
    rows, bad = [], []
    try:
        with open(str(path), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except ValueError:
                    bad.append(s[:160])
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad.append(s[:160])
    except FileNotFoundError:
        return [], []
    except IsADirectoryError:
        bad.append("ledger path is a directory: %s" % path)
        return [], bad
    return rows, bad[:10]


def append_rows(rows, path):
    """Validate + append a batch under flock. One write + fsync. ``seq`` is
    assigned inside the critical section (monotonic, gaps legal) — this is
    the shared ordering space the covered range is derived from. A duplicate
    id is refused loudly. All-rejected means zero bytes land (no file is
    created). Returns {"written", "rejected": [{"index","reason"}],
    "seqs": [...]}. Append never rewrites existing bytes."""
    fd = None
    try:
        fd = _acquire_lock(Path(path))
        existing, bad = read_rows(path)
        if bad:
            raise CertifyError("ledger_has_malformed_lines:%d" % len(bad))
        seen = {r.get("id") for r in existing if isinstance(r, dict)}
        try:
            max_seq = max(int(r["seq"]) for r in existing
                          if isinstance(r, dict) and isinstance(r.get("seq"), int))
        except ValueError:
            max_seq = 0
        clean, rejected = [], []
        for i, row in enumerate(rows):
            c, why = validate_row(row)
            if c is None:
                rejected.append({"index": i, "reason": why})
                continue
            if c.get("id") and c["id"] in seen:
                rejected.append({"index": i, "reason": "duplicate_id:%s" % c["id"]})
                continue
            seen.add(c.get("id"))
            clean.append(c)
        if not clean:
            return {"written": 0, "rejected": rejected, "seqs": []}
        seqs = []
        lines = []
        for c in clean:
            max_seq += 1
            c["seq"] = max_seq
            seqs.append(max_seq)
            lines.append(_dumps(c))
        with open(str(path), "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return {"written": len(clean), "rejected": rejected, "seqs": seqs}
    finally:
        _release_lock(fd)


# ---- derivation (pure; the records' order is authoritative) ----------------

def _of_kind(rows, kind, line=None):
    out = [r for r in rows
           if isinstance(r, dict) and r.get("kind") == kind
           and (line is None or r.get("line") == line)]
    out.sort(key=lambda r: r["seq"])
    return out


def derive_range(rows, line):
    """Derive, from the records' order alone: the line's previous
    certification, the landings it covers (every landing whose seq is AFTER
    that certification's — a landing sharing the certification's seq is
    ordered by the shared space, never by a clock race), and the certified
    prefix (the last certification's revision set — the greatest certified
    revision, always landable, goal 8). Never stored on the landing; this
    function is the only authority."""
    certs = _of_kind(rows, KIND_CERT, line)
    landings = _of_kind(rows, KIND_LANDING, line)
    last = certs[-1] if certs else None
    if last is None:
        return {"previous_certification": None, "covered_landings": landings,
                "certified_prefix": None}
    covered = [l for l in landings if l["seq"] > last["seq"]]
    return {"previous_certification": last, "covered_landings": covered,
            "certified_prefix": last["repos"]}


def landable(rows, line, landing, is_green=None):
    """May this landing be delivered? True iff it is contained in a
    certification on this line whose run is green. ``is_green`` maps a run id
    to bool (injected; None means every certification counts — a caller that
    cannot read runs must say so, not guess). Containment per repository is
    revision equality in the single-repository phase (the records name exact
    revisions; ancestry is a git question this pure face does not open)."""
    if not isinstance(landing, dict):
        raise CertifyError("landing_not_object")
    lrev = {r["repo"]: r["revision"] for r in landing.get("repos", [])}
    for cert in _of_kind(rows, KIND_CERT, line):
        if callable(is_green) and not is_green(cert.get("run")):
            continue
        crev = {r["repo"]: r["revision"] for r in cert.get("repos", [])}
        if lrev == crev:
            return True
    return False


# ---- the tick decision -----------------------------------------------------

def should_certify(trigger, rows, line, guard_held, now_ms=None,
                   backstop_ms=None):
    """At most one certification per tick: a held guard refuses every
    trigger. A change trigger certifies iff the derived range is non-empty
    (the line's content moved since the last certification). The timed
    backstop certifies on the same condition, or when nothing has been
    certified for longer than the backstop (a quiet line still gets its
    proof). Pure; the scheduler owns the call site (T1.3)."""
    if guard_held:
        return False, "guard_held"
    rng = derive_range(rows, line)
    if rng["covered_landings"]:
        return True, "range_non_empty"
    if trigger == "change":
        return False, "range_empty"
    if trigger != "backstop":
        raise CertifyError("trigger_unknown:%r" % (trigger,))
    last = rng["previous_certification"]
    if last is None:
        return True, "never_certified"
    if backstop_ms is None:
        return False, "no_backstop_configured"
    if not isinstance(now_ms, int):
        raise CertifyError("backstop_needs_now_ms")
    if now_ms - last["at"] >= backstop_ms:
        return True, "backstop_elapsed"
    return False, "backstop_not_elapsed"


# ---- guard token (current state, not a fact) -------------------------------

def guard_acquire(path, held_by):
    """Mark a certification in flight. Returns the guard dict or None when
    already held (the caller skips the tick — at most one per tick). A
    corrupt guard file is a loud failure, never read as 'free'."""
    lock = _acquire_lock(Path(path))
    try:
        gp = Path(path).parent / GUARD_NAME
        try:
            with open(str(gp), encoding="utf-8") as fh:
                state = json.load(fh)
            if not isinstance(state, dict):
                raise ValueError("guard_not_object")
        except FileNotFoundError:
            state = None
        except (ValueError, OSError) as e:
            raise CertifyError("guard_unreadable:%s" % e)
        if state and state.get("held"):
            return None
        state = {"held": True, "by": held_by,
                 "at": int(time.time() * 1000)}
        gp.parent.mkdir(parents=True, exist_ok=True)
        with open(str(gp), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        return state
    finally:
        _release_lock(lock)


def guard_release(path):
    """Release the guard (normal, error, timeout, cancel — every path that
    stops a certification ends here; a guard left held would pin the tick)."""
    lock = _acquire_lock(Path(path))
    try:
        gp = Path(path).parent / GUARD_NAME
        state = {"held": False, "released_at": int(time.time() * 1000)}
        gp.parent.mkdir(parents=True, exist_ok=True)
        with open(str(gp), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        return state
    finally:
        _release_lock(lock)


# ---- certification ---------------------------------------------------------

def run_verdict(counts):
    """The mechanical roll-up: green iff something ran and nothing failed.
    ran == 0 is never a proof (a live incident made that rule)."""
    ran = int(counts.get("ran", 0))
    failed = int(counts.get("failed", 0))
    env_failed = int(counts.get("env_failed", 0))
    return "green" if (ran > 0 and failed == 0 and env_failed == 0) else "red"


def build_certification(candidate_repos, run_header, booked_red, judged_by,
                        at_ms=None, line="default", covered_range=None):
    """Build the certification record: the candidate revision set, the run it
    cites, the expected-red inventory version in force, who/what judged, and
    the moment. NO counts, NO verdict — those belong to the cited run. A
    missing header (interrupted run) or a run that executed nothing raises
    CouldNotRun: not a red, range growth (goal 24)."""
    if not isinstance(run_header, dict):
        raise CouldNotRun("run_header_missing")
    rid = run_header.get("id")
    if not (isinstance(rid, str) and rid.startswith("run-")):
        raise CouldNotRun("run_id_not_run_id:%r" % (rid,))
    counts = run_header.get("cases")
    if not isinstance(counts, dict):
        raise CouldNotRun("run_cases_missing")
    try:
        if int(counts.get("ran", 0)) < 1:
            raise CouldNotRun("run_executed_nothing")
    except (TypeError, ValueError):
        raise CouldNotRun("run_cases_not_counts")
    row = {
        "kind": KIND_CERT,
        "id": mint_id("cert", at_ms),
        "line": line,
        "repos": [dict(r) for r in candidate_repos],
        "run": rid,
        "booked_red": str(booked_red),
        "judged_by": str(judged_by),
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }
    if covered_range is not None:
        # Projection of the records' order (see validate_row): recomputable
        # by derive_range; the derivation is authoritative, never this copy.
        row["covered_range"] = list(covered_range)
    return row


# ---- freeze records --------------------------------------------------------

def open_freeze_rows(cert_row, at_ms=None):
    """Open a freeze episode for a red certification. The episode is an
    entity: id, line, cause, at. No state, no culprit, no closure —
    everything after this is another record keyed to it."""
    return [{
        "kind": KIND_FREEZE,
        "id": mint_id("frz", at_ms),
        "line": cert_row["line"],
        "cause": cert_row["id"],
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }]


def freeze_change_row(freeze_id, change, by, reason, value=None, at_ms=None,
                      line=None):
    """A change to a freeze episode: attribution / closed / reopened, plus
    the deliberate fourth kind ``searched`` (the range that was searched, so
    goal 10's never-search-twice is checkable from records — the record
    models' three kinds carry no place for it; the extension is declared
    here, not smuggled in). ``reason`` is mandatory; a fact is never edited,
    a correction is another row. ``line`` is optional (the episode already
    carries it) but the ladder's already-searched check reads it, so a
    ``searched`` row should carry the line."""
    row = {
        "kind": KIND_FREEZE_CHANGE,
        "freeze": freeze_id,
        "change": change,
        "by": str(by),
        "reason": str(reason),
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }
    if value is not None:
        row["value"] = str(value)
    if line is not None:
        row["line"] = str(line)
    return row


def could_not_run_row(line, reason, at_ms=None):
    """The proof was unavailable (environment, missing fixtures, dead
    runner). Recorded as range growth for the next certification; never a
    red, never a freeze (goal 24)."""
    return {
        "kind": KIND_RANGE_GROWTH,
        "line": line,
        "reason": str(reason),
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }


def should_freeze(attribution_value):
    """A freeze opens only when the red implicates content. ``could not
    run`` is not a red — it grows the range instead (goal 24)."""
    return bool(attribution_value)


# ---- the bounded red ladder (goal 9 / goal 10) -----------------------------

def range_key(landing_ids):
    """Canonical name of a searched range (sorted, joined) — the value a
    ``searched`` change record carries, and the key already-searched ranges
    are refused by."""
    return ",".join(sorted(str(x) for x in landing_ids))


def _red_range(rows, line, red_cert):
    """The candidate range of THIS red: the landings that landed after the
    certification before it, up to and including it — not "after the last
    certification" (a rerun, once recorded, is now the last one)."""
    certs = _of_kind(rows, KIND_CERT, line)
    certs_before = [c for c in certs if c["seq"] < red_cert["seq"]]
    prev_seq = certs_before[-1]["seq"] if certs_before else 0
    return [l for l in _of_kind(rows, KIND_LANDING, line)
            if prev_seq < l["seq"] <= red_cert["seq"]]


def next_red_action(rows, line, red_cert, lane_reds):
    """The ladder, one pure step at a time.

    1. rerun the SAME candidate once before any search (the cheap flake
       discriminator). A rerun is visible as a later certification on this
       line whose candidate set equals the red's; if none exists, the answer
       is ('rerun', None) — the caller runs the suite again on the same
       revisions.
    2. per-lane scenario results as a free first filter: exactly one
       landing's own scenarios red names it — ('isolated', landing).
    3. a range of one landing is isolated by arithmetic — ('isolated',
       landing).
    4. a range already searched for this red raises AlreadySearchedError
       (goal 10: ranges already attributed are not searched twice).
    5. otherwise ('search', landings) — and if the search cannot narrow,
       the honest outcome is BOUNDARY_VALUE: attributed at the boundary,
       culprit not isolated.

    ``lane_reds`` is the caller's free filter input: the landing ids whose
    own per-lane scenarios are red. Garbage shapes fail loud
    (CertifyError), never silently green.
    """
    if not isinstance(red_cert, dict) or red_cert.get("kind") != KIND_CERT:
        raise CertifyError("red_cert_not_certification")
    if lane_reds is not None:
        if not isinstance(lane_reds, (list, tuple)) or \
                not all(isinstance(x, str) and x for x in lane_reds):
            raise CertifyError("lane_reds_not_landing_ids")
    certs = _of_kind(rows, KIND_CERT, line)
    candidate = sorted(r["repo"] + "@" + r["revision"]
                       for r in red_cert["repos"])
    rerun_done = False
    for c in certs:
        if c["seq"] <= red_cert["seq"]:
            continue
        other = sorted(r["repo"] + "@" + r["revision"] for r in c["repos"])
        if other == candidate:
            rerun_done = True
    if not rerun_done:
        return "rerun", None
    landings = _red_range(rows, line, red_cert)
    ids = {l["id"] for l in landings}
    if lane_reds:
        named = [x for x in lane_reds if x in ids]
        if len(named) == 1:
            hit = [l for l in landings if l["id"] == named[0]][0]
            return "isolated", hit
    if len(landings) == 1:
        return "isolated", landings[0]
    key = range_key([l["id"] for l in landings])
    for ch in _of_kind(rows, KIND_FREEZE_CHANGE, line):
        if ch.get("change") == CHANGE_SEARCHED and ch.get("value") == key:
            raise AlreadySearchedError("range_already_searched:%s" % key)
    return "search", landings
