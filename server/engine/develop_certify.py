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

- The **waiting faces** (t261009-21, design goals 8/14/15/16):
  ``freeze_state``, ``ticket_wait_state``, ``may_land`` and ``needs_slot``
  are PROJECTIONS of the same records, never stored state. A waiting ticket
  is dated (``waiting_since``), names the certification it waits for, and
  never reads as ``red_implicated`` — the design doc's three look-alikes
  ("waiting", "red and implicated", "reverted") are distinct by
  construction. ``needs_slot`` answers the scheduler's one question:
  waiting holds no capacity (goal 15 — if waiting held a slot, one tick
  would pin the whole fleet). ``may_land`` judges the freeze exemption as a
  caller-declared structural fact (goal 17), never a self-set flag. Like
  ``should_certify``, these deliver decisions; the scheduler call sites
  belong to a later ticket.

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
# The promotion family joined the delivery ledger's ordering space
# (t261009-29): one file, one writer, one seq space. The relation rows
# (record-models §B) joined with it — ``reverted_at`` and the withdrawal
# guard already join relations to promotions and landings, so a second
# file would re-create the cross-file comparison one level down.
KIND_PROMOTION = "promotion"
REL_KIND_WITHDRAWS = "withdraws"
REL_KIND_REPAIRS = "repairs"
REL_KIND_SUPERSEDES = "supersedes"
# The finding-chain kind (t261009-71, record-models §B line 618): a work
# ticket names the finding it was opened FROM. Single-direction-stored
# (ticket -> finding), derived on read like every other kind; its live
# consumers are the inspection design's closing section (both-direction
# read, content-based closure, no second filing) — "only kinds with a
# live consumer".
REL_KIND_ORIGINATES = "originates from a finding"
RELATION_KINDS = (REL_KIND_WITHDRAWS, REL_KIND_REPAIRS, REL_KIND_SUPERSEDES,
                  REL_KIND_ORIGINATES)

# What a relation's evidence may be about (t261009-62): the declared
# subject vocabulary — one shape ``{"what": <one of these>, "ref": <str>}``.
# Extension (e.g. observations, P2-f) adds names here; the shape is fixed.
# ``finding`` (t261009-71): the ref is the content-minted finding id the
# attribution rests on.
RELATION_EVIDENCE_WHATS = ("revision", "patch_id", "ticket",
                           "certification", "path_line", "finding")


def _relation_recorder_not_beneficiary(row):
    """The shared structural rule behind every kind's permission today: the
    recorder may never be the ticket that benefits (``from``). A recorder
    naming a ticket uses the ``ticket:<id>`` form; a ``ticket:`` prefix with
    an unusable id cannot be evaluated, so it fails closed. Bare actor
    names (``host``, ``integration``, the patrol) stay legal — attribution
    by a person is the design's normal path."""
    recorded_by = row.get("recorded_by")
    if not isinstance(recorded_by, str) or not recorded_by.strip():
        return "relation_missing_recorded_by"
    if recorded_by.startswith("ticket:"):
        named = recorded_by[len("ticket:"):].strip()
        if not named:
            return "relation_recorder_malformed"
        if named == row.get("from"):
            return "relation_self_benefit:%s" % row.get("from")
    return ""


#: Per-kind recorder permission (t261009-62): each kind's rule lives here;
#: a kind missing from the table refuses by name (fail closed) rather than
#: being accepted with no rule.
RELATION_RECORDER_RULES = {
    REL_KIND_WITHDRAWS: _relation_recorder_not_beneficiary,
    REL_KIND_REPAIRS: _relation_recorder_not_beneficiary,
    REL_KIND_SUPERSEDES: _relation_recorder_not_beneficiary,
    # t261009-71: for ``originates from a finding`` the ``from`` ticket is
    # the beneficiary — the relation claims the finding as the ticket's
    # justification — so the SAME structural rule applies: the ticket that
    # benefits may not record its own origin. Table discipline, no new
    # rule shape.
    REL_KIND_ORIGINATES: _relation_recorder_not_beneficiary,
}

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
    elif kind == KIND_PROMOTION:
        # t261009-29: the promotion lives in THIS ledger's ordering space.
        # Refusal names carried over verbatim from the sibling-file era
        # (develop_promote's validators), so existing callers read the same
        # reasons; the shared writer assigns the ``seq``.
        if not (isinstance(rid, str) and rid.startswith("prom-")):
            return _bad("promotion_id_not_prom")
        cert = row.get("certification")
        if not (isinstance(cert, str) and cert.startswith("cert-")):
            # Spec (b): the refusal is by name. A promotion that cannot NAME
            # a certification is never built with a default or an inferred
            # one.
            return _bad("promotion_without_named_certification")
        if not isinstance(row.get("line"), str) or not row["line"].strip():
            return _bad("promotion_missing_line")
        if not _valid_repos(row.get("repos")):
            return _bad("promotion_repos_invalid")
        tickets = row.get("tickets")
        if not isinstance(tickets, list) or not tickets \
                or not all(isinstance(t, str) and t.strip() for t in tickets):
            return _bad("promotion_tickets_invalid")
        for f in ("main_before", "main_after"):
            if not _valid_repos(row.get(f)):
                return _bad("promotion_%s_invalid" % f)
        # Spec (a): three separate fields. ``on_behalf_of`` and ``authority``
        # stand together — delegation recorded without the order (or the
        # order without the delegate) is a half fact, refused by name.
        behalf, authority = row.get("on_behalf_of"), row.get("authority")
        if (behalf is None) != (authority is None):
            return _bad("delegation_incomplete")
        if behalf is not None and not (isinstance(behalf, str)
                                       and behalf.strip()):
            return _bad("delegation_on_behalf_of_invalid")
        if authority is not None and not (isinstance(authority, str)
                                          and authority.strip()):
            return _bad("delegation_authority_invalid")
        if not isinstance(row.get("signer"), str) or not row["signer"].strip():
            return _bad("promotion_missing_signer")
        if "note" in row and row["note"] is not None \
                and not isinstance(row["note"], str):
            return _bad("promotion_note_not_string")
        # t261009-66: the promotion NAMES the remedy relations it contains
        # (``repairs`` / ``withdraws`` rows recorded by covered tickets).
        # The field is a naming of ledger rows (each entry cites its
        # ``rel-`` id), never a second stored direction — the ledger stays
        # the source. Legacy rows without the field stay valid (append-only
        # ledger, old rows byte-identical).
        if "repairs" in row and row["repairs"] is not None:
            reps = row["repairs"]
            if not isinstance(reps, list):
                return _bad("promotion_repairs_not_list")
            for e in reps:
                if not (isinstance(e, dict)
                        and isinstance(e.get("id"), str)
                        and e["id"].startswith("rel-")
                        and isinstance(e.get("from"), str)
                        and e["from"].strip()
                        and isinstance(e.get("to"), str)
                        and e["to"].strip()
                        and e.get("kind") in (REL_KIND_REPAIRS,
                                              REL_KIND_WITHDRAWS)):
                    return _bad("promotion_repairs_entry_invalid")
    elif kind in RELATION_KINDS:
        # Record-models §B shape: the ``kind`` FIELD carries the relation
        # kind, the ``rel-`` id prefix carries the family — family detection
        # is by id prefix, not by this field.
        if not (isinstance(rid, str) and rid.startswith("rel-")):
            return _bad("relation_id_not_rel")
        for f in ("from", "to"):
            if not isinstance(row.get(f), str) or not row[f].strip():
                return _bad("relation_missing_%s" % f)
        if not isinstance(row.get("recorded_by"), str) \
                or not row["recorded_by"].strip():
            return _bad("relation_missing_recorded_by")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            return _bad("relation_missing_reason")
        # Evidence (t261009-62): a relation asserts an attribution, so the
        # row must say WHAT it is about, in the one declared shape.
        ev = row.get("evidence")
        if not isinstance(ev, dict):
            return _bad("relation_missing_evidence")
        if ev.get("what") not in RELATION_EVIDENCE_WHATS:
            return _bad("relation_evidence_what_unknown:%r"
                        % (ev.get("what"),))
        if not isinstance(ev.get("ref"), str) or not ev["ref"].strip():
            return _bad("relation_evidence_ref_invalid")
        # Who may record what (t261009-62): the kind's own rule decides.
        # Today every kind shares one structural rule — the recorder may
        # never be the ticket that benefits (``from``) — held in a table so
        # later consumers (t261009-63/-64) add entries without reshaping
        # this validator. Fail closed: a recorder that cannot be evaluated
        # is a refusal, never an acceptance.
        rule = RELATION_RECORDER_RULES.get(kind)
        if rule is None:  # unreachable while RELATION_KINDS ⊆ table keys
            return _bad("relation_recorder_rule_missing:%s" % kind)
        bad = rule(row)
        if bad:
            return _bad(bad)
        # Correction linkage (t261009-62): a wrong relation is corrected by
        # a NEW row naming the old row's id. Row-local checks only — whether
        # the named id exists is the reader's question (a dangling pointer
        # never matches, so the correcting row stays current).
        sup = row.get("supersedes_relation")
        if sup is not None:
            if not isinstance(sup, str) or not sup.startswith("rel-"):
                return _bad("relation_supersedes_not_rel")
            if sup == rid:
                return _bad("relation_supersedes_self")
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


def _covering_green_cert(rows, line, landing, is_green):
    """THE one coverage rule (t261011-23, KI-01M4N5ASATAVWP6E38NSPECCAT): a
    landing is covered iff it lies inside the range of a GREEN certification
    on its line — ``prev_cert(cert).seq < landing.seq <= cert.seq``, the same
    predicate ``derive_range()`` computes for ``covered_landings`` and
    ``_red_range()`` uses for reds. Revision identity is NOT tested here in
    the single-repository phase: it matters only where the BUILDER anchors it
    (``candidate_set()`` takes the per-repo HEAD across the range — the
    multi-repository per-repo anchoring), never in this reader. Certification
    ranges partition the line's landings, so at most one cert's range
    contains a landing; the first hit is returned. Returns None when no green
    range contains the landing."""
    if not isinstance(landing, dict):
        raise CertifyError("landing_not_object")
    certs = _of_kind(rows, KIND_CERT, line)
    for cert in certs:
        if callable(is_green) and not is_green(cert.get("run")):
            continue
        prev_seq = 0
        for earlier in certs:
            if earlier["seq"] < cert["seq"] and earlier["seq"] > prev_seq:
                prev_seq = earlier["seq"]
        if prev_seq < landing.get("seq", 0) <= cert["seq"]:
            return cert
    return None


def landable(rows, line, landing, is_green=None):
    """May this landing be delivered? True iff it lies inside the range of a
    GREEN certification on this line: ``prev_cert(cert).seq < landing.seq <=
    cert.seq`` — a green round certifies the range that has grown since the
    previous certification, not one ticket per round (t261011-23). ``is_green``
    maps a run id to bool (injected; None means every certification counts — a
    caller that cannot read runs must say so, not guess)."""
    return _covering_green_cert(rows, line, landing, is_green) is not None


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


# ---- the waiting faces (t261009-21: goals 8 / 14 / 15 / 16) ----------------
# Projections of the delivery ledger, same discipline as derive_range: the
# records' order is authoritative, nothing here writes a field onto any row
# (the culprit range AND the wait are derived, never stored).

WAIT_WAITING = "waiting"
WAIT_CERTIFIED = "certified"
WAIT_RED_IMPLICATED = "red_implicated"
WAIT_REVERTED = "reverted"
# t261009-64: reachable. A ticket whose landing was withdrawn shows this
# waiting face; ``withdrawn_by`` names the withdrawal relation that ended
# the landing's life (derived from the current relation rows, never stored).

FREEZE_EXEMPT_KIND = "fix"
"""The one ticket kind that may land on a frozen line. Being exempt is a
property of HOW THE WORK WAS OPENED (the fix workflow, goal 17) — the caller
declares it from the relation record, this face only judges it; no landing
can acquire it by writing a field about itself."""

LANDABLE_KINDS = (FREEZE_EXEMPT_KIND, "chore")
"""The lane version's declared ticket kinds that ever land. A kind outside
the declaration is refused by name on a frozen line — a typo of the exempt
kind must not read as "the freeze says no" and silently deadlock the real
fix; the vocabulary grows by declaration, not by use."""


def freeze_state(rows, line):
    """Read a line's freeze from the records alone: the latest episode is
    the live one; its state is replayed from its change records by seq
    (open at creation, ``closed`` closes, ``reopened`` opens again). The
    culprit is the episode's latest ``attribution`` value — including the
    honest boundary sentence, passed through verbatim. No freeze field is
    ever written onto a landing or a certification by this face."""
    episodes = _of_kind(rows, KIND_FREEZE, line)
    if not episodes:
        return {"frozen": False, "episode": None, "cause": None,
                "culprit": None, "closed_at": None}
    ep = episodes[-1]
    frozen, closed_at = True, None
    culprit = None
    for ch in _of_kind(rows, KIND_FREEZE_CHANGE, line):
        if ch.get("freeze") != ep["id"]:
            continue
        if ch.get("change") == CHANGE_CLOSED:
            frozen, closed_at = False, ch["at"]
        elif ch.get("change") == CHANGE_REOPENED:
            frozen, closed_at = True, None
        elif ch.get("change") == CHANGE_ATTRIBUTION:
            culprit = ch.get("value")
    return {"frozen": frozen, "episode": ep["id"], "cause": ep["cause"],
            "culprit": culprit, "closed_at": closed_at}


def _current_relation_rows(rows):
    """The current (non-superseded) ``rel-`` rows of the ledger list
    (t261009-63): every relation row EXCEPT the ones another row
    supersedes. The same linkage ``develop_promote.current_relations``
    reads; re-declared here because the engine's certify half must not
    import the promote half (import direction: promote -> certify, never
    back). A supersedes cycle makes BOTH rows non-current, as there."""
    rels = [r for r in rows
            if isinstance(r, dict) and isinstance(r.get("id"), str)
            and r["id"].startswith("rel-")]
    superseded = set()
    for r in rels:
        target = r.get("supersedes_relation")
        if isinstance(target, str) and target.startswith("rel-"):
            superseded.add(target)
    return [r for r in rels if r["id"] not in superseded]


def _relation_finding_ref(ref):
    """Is this relation-target reference a FINDING id by form (t261009-71)?
    Two shapes name a finding: the declared ``finding:<id>`` prefix, and a
    bare content-minted id (``fi-`` prefix, or 8/16 hex characters — the
    two truncations the models document allows). A finding is not a ticket;
    a reader must never show one as one."""
    if not (isinstance(ref, str) and ref.strip()):
        return False
    r = ref.strip()
    if r.startswith("finding:"):
        return bool(r[len("finding:"):].strip())
    if r.startswith("fi-"):
        return len(r) > 3
    body = r[2:] if r.startswith("0x") else r
    return len(body) in (8, 16) and all(c in "0123456789abcdefABCDEF"
                                        for c in body)


def _relation_target_tickets(rows, ref, patch_ids):
    """Resolve ONE relation target reference to the set of ticket ids it
    names (t261009-66). Relations are project-level facts (goal 15), so —
    unlike ``_repair_target_landing`` — there is NO line scoping here: the
    benefited side is answered across lines. The same three target forms
    the exemption face resolves: a ``ldg-`` landing id (the landing row
    names its ticket); a patch identity matched against the caller-supplied
    ``patch_ids={landing_id: pid}`` map (landings store no patch ids, so
    the map is the caller's explicit declaration); any other non-empty
    string is a ticket id BY FORM and names itself — a reader shows the
    stored fact whether or not a landing for that ticket exists. A finding
    id by form (t261009-71: ``finding:<id>``, ``fi-<id>``, or bare content
    hex) is NOT a ticket and resolves to the empty set — the by-form
    fallback must never mint a phantom ticket out of a finding."""
    out = set()
    if not (isinstance(ref, str) and ref.strip()):
        return out
    if _relation_finding_ref(ref):
        return out
    if ref.startswith("ldg-"):
        for r in rows:
            if (isinstance(r, dict) and r.get("kind") == KIND_LANDING
                    and r.get("id") == ref
                    and isinstance(r.get("ticket"), str) and r["ticket"]):
                out.add(r["ticket"])
        return out
    if isinstance(patch_ids, dict):
        for r in rows:
            if (isinstance(r, dict) and r.get("kind") == KIND_LANDING
                    and patch_ids.get(r.get("id")) == ref
                    and isinstance(r.get("ticket"), str) and r["ticket"]):
                out.add(r["ticket"])
    return out | {ref}


def _patch_named_rel(rel):
    """Does this relation name a patch identity via its evidence? The same
    rule ``develop_promote._patch_named`` reads; declared here because the
    certify half must not import the promote half (import direction:
    promote -> certify, never back)."""
    ev = rel.get("evidence")
    return isinstance(ev, dict) and ev.get("what") == "patch_id" \
        and isinstance(ev.get("ref"), str) and ev["ref"].strip() != ""


def relations_of(rows, ticket, patch_ids=None):
    """The ONE declared relation reader (t261009-66): what are this
    ticket's relations, from BOTH directions, over the ledger rows —
    "One direction is stored; the other side is derived" (ticket-relations
    design). Never writes; never a second stored row.

    - ``as_actor`` (the STORED side): current relation rows whose ``from``
      is this ticket — what it repairs / withdraws / supersedes.
    - ``as_benefited`` (the DERIVED side, every entry marked
      ``"derived": True``): current relation rows whose ``to`` RESOLVES to
      this ticket — what repaired / withdrew / superseded it. Resolution
      goes through ``_relation_target_tickets`` (ticket id, ``ldg-``
      landing id, or patch identity via ``patch_ids``).
    - ``unresolved``: ids of relations whose evidence names a patch
      identity but no ``patch_ids`` map was supplied — the gap stays
      visible by name, never guessed into an answer (the same honesty rule
      as the outcome face's ``repaired_unresolved``).
    - ``finding_refs`` (t261009-71): the finding-id references (``finding:``
      prefix, ``fi-`` prefix, or bare content hex) among this ticket's
      current relations, named as findings — never shown as tickets.

    Corrected relations (``supersedes_relation`` linkage, t261009-62) drop
    out through ``_current_relation_rows`` — a corrected relation never
    appears as current; a supersedes CYCLE makes both rows non-current,
    as there. Malformed rows are filtered the same way, never crashed on.

    Consumers call THIS for direction logic — no second implementation of
    the direction matching may appear (the promote half re-exports it as
    the same object).
    """
    if not (isinstance(ticket, str) and ticket.strip()):
        raise CertifyError("relations_of_bad_ticket")
    current = _current_relation_rows(rows)
    as_actor = {k: [] for k in RELATION_KINDS}
    as_benefited = {k: [] for k in RELATION_KINDS}
    unresolved = []
    finding_refs = []
    for rel in current:
        kind = rel.get("kind")
        if kind not in RELATION_KINDS:
            continue
        entry = {"id": rel.get("id"), "from": rel.get("from"),
                 "to": rel.get("to"), "kind": kind, "at": rel.get("at")}
        if _relation_finding_ref(rel.get("to")):
            # A finding id is never a ticket (t261009-71): kept visible as
            # a named finding reference instead of guessed into a ticket.
            finding_refs.append({"id": rel.get("id"),
                                 "ref": str(rel.get("to")).strip(),
                                 "kind": kind})
        if rel.get("from") == ticket:
            as_actor[kind].append(dict(entry, derived=False))
        if ticket in _relation_target_tickets(rows, rel.get("to"), patch_ids):
            as_benefited[kind].append(dict(entry, derived=True))
        elif _patch_named_rel(rel) and not isinstance(patch_ids, dict):
            unresolved.append(rel.get("id"))
    return {"ticket": ticket, "as_actor": as_actor,
            "as_benefited": as_benefited, "unresolved": unresolved,
            "finding_refs": finding_refs}


def _repair_target_landing(rows, line, ref, patch_ids):
    """Resolve ONE repair-target reference to a landing row on ``line``
    (t261009-63). Three naming forms, all resolving to the landing the
    repair names: a ``ldg-`` landing id; a ticket id whose latest landing
    sits on the line; a patch identity matched against the caller-supplied
    ``patch_ids={landing_id: pid}`` map (landings do not store patch ids —
    the withdrawal guard computes them through git — so the map is the
    caller's explicit declaration). None when the reference names nothing
    on THIS line. A cross-line target is not an invalid relation — it is
    simply not an exemption for this line (the freeze on line L comes from
    a red on line L, so only repairing L's own landing justifies landing
    into L); relations themselves stay project-level facts (goal 15)."""
    landings = [r for r in rows
                if isinstance(r, dict) and r.get("kind") == KIND_LANDING
                and r.get("line") == line]
    if isinstance(ref, str) and ref.startswith("ldg-"):
        for r in landings:
            if r.get("id") == ref:
                return r
        return None
    if isinstance(patch_ids, dict):
        for r in landings:
            if isinstance(patch_ids.get(r.get("id")), str) \
                    and patch_ids[r["id"]] == ref:
                return r
    for r in landings:
        if r.get("ticket") == ref:
            return r
    return None


def _repair_grants(rows, line, ticket, repair, patch_ids):
    """Is ``repair`` a CURRENT ``repairs`` relation by ``ticket`` that names
    a landing on ``line`` (t261009-63)? Returns "" when it grants, else a
    named refusal. Deliberately re-checks every field it consumes — this
    face is the judge, never a trustee of the caller's or of a helper's
    filter (fail closed, defence in depth)."""
    if not isinstance(repair, dict):
        return "repair_relation_not_record"
    if repair.get("kind") != REL_KIND_REPAIRS:
        return "repair_relation_not_repairs"
    if repair.get("from") != ticket:
        return "repair_from_not_ticket:%r" % (repair.get("from"),)
    if not (isinstance(repair.get("id"), str)
            and repair["id"].startswith("rel-")):
        return "repair_relation_id_not_rel"
    if not any(r.get("id") == repair["id"]
               for r in _current_relation_rows(rows)):
        return "repair_relation_superseded:%s" % repair["id"]
    ev = repair.get("evidence")
    targets = []
    if isinstance(repair.get("to"), str) and repair["to"].strip():
        targets.append(repair["to"])
    if (isinstance(ev, dict) and ev.get("what") == "patch_id"
            and isinstance(ev.get("ref"), str) and ev["ref"].strip()):
        targets.append(ev["ref"])
    if not targets:
        return "repair_target_missing"
    for ref in targets:
        if _repair_target_landing(rows, line, ref, patch_ids) is not None:
            return ""
    return "repair_target_unresolved:%s" % "|".join(targets)


def may_land(rows, line, ticket_kind, ticket=None, repair=None,
             patch_ids=None):
    """May this kind of ticket land into ``line`` now? An unfrozen line
    takes every declared kind — with or without a repair relation. A
    frozen line takes only the structurally exempt fix kind (goal 16/17),
    and since t261009-63 the exemption is DERIVED FROM A ``repairs``
    RELATION, never from the ticket's own kind alone: ``ticket`` names the
    candidate and ``repair`` must be a current ``repairs`` relation
    recorded BY that ticket naming a landing on this line — by landing id,
    by the repaired ticket's id, or by patch identity matched against the
    explicit ``patch_ids={landing_id: pid}`` map (a patch-id-named
    relation without the map is refused by name, never guessed into an
    exemption). The same-line requirement is THIS face's scoping, not a
    relation rule: relations are project-level facts (goal 15), but only a
    repair of the line's OWN landing justifies landing into that line's
    freeze. NO relation at all is refused by name —
    ``freeze_repair_relation_missing`` — so a ticket that merely declares
    itself a fix cannot land during a freeze (the one new intent this
    ticket owns). An undeclared kind is refused by name as before (a
    misspelled fix kind must not deadlock silently), and a relation never
    mints a kind: a non-exempt kind on a frozen line is refused with or
    without one."""
    if not isinstance(ticket_kind, str) or not ticket_kind.strip():
        raise CertifyError("ticket_kind_missing")
    if ticket_kind not in LANDABLE_KINDS:
        raise CertifyError("ticket_kind_undeclared:%r" % (ticket_kind,))
    if patch_ids is not None and not isinstance(patch_ids, dict):
        raise CertifyError("patch_ids_not_map")
    frozen = freeze_state(rows, line)["frozen"]
    if not frozen:
        return True
    if ticket_kind != FREEZE_EXEMPT_KIND:
        return False
    if repair is None:
        raise CertifyError("freeze_repair_relation_missing")
    if not (isinstance(ticket, str) and ticket.strip()):
        raise CertifyError("repair_ticket_missing")
    why = _repair_grants(rows, line, ticket, repair, patch_ids)
    if why:
        raise CertifyError(why)
    return True


def landing_freeze_face(rows, line, ticket_id, patch_ids=None):
    """The landing act's freeze consultation (t261009-67, goals 16/17/168):
    may THIS ticket land into ``line`` NOW, judged from the records alone?

    Returns a dict, never raises for a refusal (the caller formats the named
    error): ``allowed`` / ``reason`` ("" when allowed) / ``freeze`` (the live
    episode id) / ``cause`` (the certification that opened it) / ``relation``
    and ``repaired`` (the granting ``repairs`` relation and the landing it
    names, when the exemption grants).

    The STRUCTURAL rule, kept structural at the enforcement point: this face
    takes NO kind parameter — there is nothing a caller can claim about
    itself. On an unfrozen line every landing passes (the freeze does not
    exist, so there is nothing to exempt). On a frozen line the ONLY path
    through is a CURRENT ``repairs`` relation recorded BY ``ticket_id``
    naming a landing on THIS line — read through the ONE relation reader
    (``relations_of`` as_actor side) and judged by ``_repair_grants`` (which
    re-checks every field it consumes). A ticket with no relation at all is
    refused ``freeze_landing_refused`` — the same named refusal covers every
    self-declaration attempt, because a self-assertion is not an input here.
    A relation that names nothing on this line (or a superseded one, or a
    patch-id-named one without the ``patch_ids`` map) is refused with
    ``_repair_grants``' own named reason, plus the freeze id and cause.
    """
    if not isinstance(line, str) or not line.strip():
        raise CertifyError("line_missing")
    if not (isinstance(ticket_id, str) and ticket_id.strip()):
        raise CertifyError("ticket_id_missing")
    if patch_ids is not None and not isinstance(patch_ids, dict):
        raise CertifyError("patch_ids_not_map")
    fs = freeze_state(rows, line)
    if not fs["frozen"]:
        return {"allowed": True, "reason": "", "freeze": None,
                "cause": None, "relation": None, "repaired": None}
    ep, cause = fs["episode"], fs["cause"]
    rels = relations_of(rows, ticket_id, patch_ids)["as_actor"]["repairs"]
    if not rels:
        return {"allowed": False, "reason": "freeze_landing_refused",
                "freeze": ep, "cause": cause, "relation": None,
                "repaired": None}
    last_why = "repair_target_unresolved"
    for entry in rels:
        rel_id = entry.get("id")
        row = next((r for r in rows
                    if isinstance(r, dict) and r.get("id") == rel_id), None)
        if row is None:  # the reader only lists current rows; never guessed
            last_why = "repair_relation_row_missing:%s" % rel_id
            continue
        why = _repair_grants(rows, line, ticket_id, row, patch_ids)
        if not why:
            repaired = None
            ev = row.get("evidence")
            ev_ref = ev.get("ref") if isinstance(ev, dict) else None
            for ref in (row.get("to"), ev_ref):
                if not (isinstance(ref, str) and ref.strip()):
                    continue
                hit = _repair_target_landing(rows, line, ref, patch_ids)
                if hit is not None:
                    repaired = hit.get("id")
                    break
            return {"allowed": True, "reason": "", "freeze": ep,
                    "cause": cause, "relation": rel_id, "repaired": repaired}
        last_why = why
    return {"allowed": False, "reason": last_why, "freeze": ep,
            "cause": cause, "relation": None, "repaired": None}


def open_freeze_summary(rows, line, patch_ids=None):
    """The promotion signer's freeze face (t261009-67, goals 167/166), read
    from the ledger alone: the live freeze episode, the certification that
    caused it, the derived culprit, and the CHAIN OF FIXES — every landing
    made on the line while this episode has been open, each joined to the
    current ``repairs`` relations recorded by its ticket (the ONE reader,
    as_actor side; a repair whose target cannot be resolved here is listed
    with ``repaired: null`` — the gap stays visible, never guessed closed).
    Under an open freeze those landings are exactly the exempt fix landings,
    so this list is also the next red's candidate-culprit chain read off the
    records (goal 166: the next fix names the previous fix's landing).
    ``pending_fixes`` names the remedy work already RECORDED (a current
    ``repairs`` relation naming a landing on this line) whose ticket has not
    landed yet — the fix "that will reopen" the freeze (item 167), visible
    before its landing exists, read from the same records."""
    if not isinstance(line, str) or not line.strip():
        raise CertifyError("line_missing")
    fs = freeze_state(rows, line)
    base = {"frozen": fs["frozen"], "freeze": fs["episode"],
            "cause": fs["cause"], "culprit": fs["culprit"],
            "opened_at": None, "fix_landings": [], "pending_fixes": []}
    if not fs["frozen"]:
        return base
    episodes = _of_kind(rows, KIND_FREEZE, line)
    base["opened_at"] = episodes[-1].get("at") if episodes else None
    for ldg in _of_kind(rows, KIND_LANDING, line):
        at = ldg.get("at")
        if not isinstance(at, int) or isinstance(at, bool):
            continue
        if base["opened_at"] is not None and at < base["opened_at"]:
            continue
        ticket = ldg.get("ticket")
        repairs = []
        if isinstance(ticket, str) and ticket.strip():
            face = relations_of(rows, ticket, patch_ids)
            for entry in face["as_actor"]["repairs"]:
                rel_id = entry.get("id")
                row = next((r for r in rows if isinstance(r, dict)
                            and r.get("id") == rel_id), None)
                repaired = None
                if row is not None:
                    ev = row.get("evidence")
                    ev_ref = ev.get("ref") if isinstance(ev, dict) else None
                    for ref in (row.get("to"), ev_ref):
                        if not (isinstance(ref, str) and ref.strip()):
                            continue
                        hit = _repair_target_landing(rows, line, ref,
                                                     patch_ids)
                        if hit is not None:
                            repaired = hit.get("id")
                            break
                repairs.append({"id": rel_id, "repaired": repaired})
        base["fix_landings"].append({"landing": ldg.get("id"),
                                     "ticket": ticket, "at": at,
                                     "repairs": repairs})
    # The fixes recorded but not yet landed: current repairs relations whose
    # target resolves on THIS line and whose actor ticket has no landing
    # during this episode — the "will reopen" side of item 167.
    landed = {f["ticket"] for f in base["fix_landings"]}
    for rel in _current_relation_rows(rows):
        if rel.get("kind") != REL_KIND_REPAIRS:
            continue
        actor = rel.get("from")
        if not (isinstance(actor, str) and actor.strip()) or actor in landed:
            continue
        ev = rel.get("evidence")
        ev_ref = ev.get("ref") if isinstance(ev, dict) else None
        targets = [t for t in (rel.get("to"), ev_ref)
                   if isinstance(t, str) and t.strip()]
        if any(_repair_target_landing(rows, line, t, patch_ids) is not None
               for t in targets):
            base["pending_fixes"].append({"ticket": actor,
                                          "relation": rel.get("id")})
    return base


def ticket_wait_state(rows, line, landing, is_green, now_ms,
                      wait_bound_ms=None):
    """The waiting ticket's face, derived from the records (goal 14/16).

    Returns a dict: ``state`` (waiting / certified / red_implicated /
    reverted), ``waiting_since`` (the landing's own ``at`` — the
    record order decides, not a clock race), ``waiting_for`` (the id of the
    certification this landing is queued behind — the line's latest one; None
    while none exists yet; for ``reverted`` it names the withdrawal relation),
    ``covered_by`` (the green certification id that ended the wait, if any),
    ``withdrawn_by`` (for ``reverted`` only: the id of the CURRENT
    ``withdraws`` relation that ended the landing's life — the face names
    the withdrawal, derived, never stored), and ``overdue`` (True only once
    the wait has outlived the declared ``wait_bound_ms`` — surfaced, not
    silently tolerated; the patrol consumes it once the surfaces exist).

    ``waiting`` and ``red_implicated`` never look the same: implicated means
    the landing sits in the derived range of a RED certification on this
    line; waiting means the covering certification simply has not arrived.

    ``is_green`` is the same injected run reader ``landable`` takes. Here the
    loud contract is stricter: once the line has ANY certification, a caller
    that cannot read runs must say so with a callable that answers honestly
    — ``None`` reads as a plausible default (every cert green) and is refused
    by name. A caller with no certification on the line may pass None: there
    is nothing to misread yet.
    """
    if not isinstance(landing, dict) or landing.get("kind") != KIND_LANDING:
        raise CertifyError("landing_not_landing")
    if landing.get("line") != line:
        raise CertifyError("landing_not_on_line")
    if not isinstance(now_ms, int) or isinstance(now_ms, bool):
        raise CertifyError("now_ms_not_ms")
    if wait_bound_ms is not None and (not isinstance(wait_bound_ms, int)
                                      or isinstance(wait_bound_ms, bool)
                                      or wait_bound_ms <= 0):
        raise CertifyError("wait_bound_not_positive_ms")
    certs = _of_kind(rows, KIND_CERT, line)
    if certs and not callable(is_green):
        raise CertifyError("is_green_not_injected")

    def _green(cert):
        return bool(is_green(cert["run"])) if callable(is_green) else True

    base = {"waiting_since": landing["at"], "waiting_for": None,
            "covered_by": None, "overdue": False}
    # reverted (t261009-64): the landing's ticket is the ``to`` of a CURRENT
    # ``withdraws`` relation — the ticket's life is over regardless of any
    # later red, so this face outranks red_implicated. Checked AFTER the
    # input validation above (a caller with certs on the line and no
    # ``is_green`` is still refused by name), from the module-local current
    # relation rows (certify never imports promote).
    for rel in _current_relation_rows(rows):
        rel_id = rel.get("id")
        if (rel.get("kind") == REL_KIND_WITHDRAWS
                and rel.get("to") == landing.get("ticket")
                and isinstance(rel_id, str) and rel_id.startswith("rel-")):
            return dict(base, state=WAIT_REVERTED,
                        waiting_for=rel_id, withdrawn_by=rel_id)
    # red_implicated: in the derived range of a red certification (goal 16's
    # "red and implicated" — distinct from plain waiting by construction).
    for cert in certs:
        if _green(cert):
            continue
        if any(l["id"] == landing["id"]
               for l in _red_range(rows, line, cert)):
            return dict(base, state=WAIT_RED_IMPLICATED,
                        waiting_for=cert["id"])
    # certified (t261011-23): range-based, the same rule as the outcome face
    # and the red path — inside a GREEN certification's range.
    covering = _covering_green_cert(rows, line, landing, is_green)
    if covering is not None:
        return dict(base, state=WAIT_CERTIFIED,
                    covered_by=covering["id"])
    last = certs[-1] if certs else None
    state = dict(base, state=WAIT_WAITING,
                 waiting_for=last["id"] if last else None)
    if wait_bound_ms is not None and now_ms - landing["at"] >= wait_bound_ms:
        state["overdue"] = True
    return state


def needs_slot(state):
    """Does this ticket face hold a concurrency slot? No face of a landed
    ticket does (goals 14/15): waiting holds none — that is the stall this
    design removes; ``red_implicated`` also keeps *waiting* for the
    certification that finally covers it; ``certified`` and ``reverted``
    are ends — the ticket's life is over, there is nothing left to
    schedule. The whitelist is the seam: a state the scheduler does not
    know is refused by name, never defaulted into (or out of) capacity. A
    future working state would have to be added here on purpose."""
    if not isinstance(state, dict):
        raise CertifyError("wait_state_not_face")
    s = state.get("state")
    if s == WAIT_WAITING or s == WAIT_RED_IMPLICATED:
        return False
    if s == WAIT_CERTIFIED or s == WAIT_REVERTED:
        return False
    raise CertifyError("wait_state_unknown:%r" % (s,))


# ---- the line round (T2.3, t261009-30) --------------------------------------
#
# One round = decide (should_certify) -> guard -> run the suite on the line's
# head -> record the run's certification (and the freeze / range growth that
# follows a red / an unavailable proof). The suite itself and the run store
# stay behind INJECTED seams (``runner`` / the read/append callables): the
# engine never imports the integration support layer, and the subprocess form
# of the runner (its own checkout of the candidate revisions) is the wiring
# ticket's face — this module only refuses a runner pointed at the delivered
# checkout (``refuse_delivered_checkout``).

CHAIN_LIMIT = 4
"""Max chained rounds ONE ``run_line_round`` invocation may run (host order
261009: when a round ends the next starts at once while anything is still
waiting — without a bound a fast landing stream would loop forever inside one
tick). The bound is declared, its exceed-face is named, and rows are left
untouched by the exceed itself; the next trigger re-enters normally."""

STATE_CERTIFIED = "certified"
STATE_RED = "red"
STATE_GREW = "grew"
END_IDLE = "idle"
END_JOINED = "joined"
END_CHAIN_LIMIT = "chain_limit_exceeded"


def guard_held(path):
    """Is a certification in flight? Reads the guard file's state; a corrupt
    guard is a loud failure, never read as 'free' (same discipline as
    guard_acquire). An absent guard file is simply not held."""
    gp = Path(path).parent / GUARD_NAME
    try:
        with open(str(gp), encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return False
    except (ValueError, OSError) as e:
        raise CertifyError("guard_unreadable:%s" % e)
    if not isinstance(state, dict):
        raise CertifyError("guard_unreadable:guard_not_object")
    return bool(state.get("held"))


def candidate_set(covered_landings):
    """The revision set a round certifies: per repository, the HEAD revision
    across the range's landings (the landings are in seq order, so the last
    one naming a repo wins). A set of repository revisions, not a branch
    (goal 18)."""
    head = {}
    for landing in covered_landings:
        for r in landing.get("repos", []):
            head[r["repo"]] = r["revision"]
    return [{"repo": k, "revision": v} for k, v in head.items()]


def refuse_delivered_checkout(tree, main_checkout):
    """Upfront constraint: the whole-suite run lives where its own output
    cannot touch the delivered checkout. The runner seam carries this in its
    subprocess form; this helper is the named refusal a wiring call site runs
    BEFORE pointing a runner at a tree. The same path (realpath-resolved, so
    a symlink alias does not slip through) is refused by name."""
    a = os.path.realpath(str(tree))
    b = os.path.realpath(str(main_checkout))
    if a == b:
        raise CertifyError("tree_is_delivered_checkout:%s" % a)


def run_line_round(line, trigger, guard_path, runner, read_rows, append_rows,
                   judged_by, booked_red, backstop_ms=None, now_ms=None,
                   chain_limit=CHAIN_LIMIT, lane_reds=None):
    """Run the line's certification round(s): at most one per tick, chained
    while anything is still waiting, bounded by ``chain_limit``.

    Injected seams (the engine never imports the integration support layer):
    ``read_rows() -> (rows, bad)`` over the delivery ledger, ``append_rows(
    batch)`` through the shared flock writer, and ``runner(candidate_repos)
    -> run header`` — the full suite executed against the candidate revision
    set in a tree of its own (never the delivered checkout; see
    refuse_delivered_checkout). A runner that cannot produce a proof raises
    CouldNotRun or returns a shape build_certification refuses: the round
    records range growth and opens nothing (goal 24).

    Returns {"rounds": [...], "end": {"state", "reason"}}. ``end`` is one of:
    idle (nothing to certify — the loop waits for the next landing), joined
    (a round was asked for while one ran: this tick joins the next one
    instead of starting a second serial slot), chain_limit_exceeded (named,
    rows untouched by the exceed itself), or the loop exhausted its chain
    budget. Chaining re-checks the SAME records order: after a round that
    recorded a certification the derived range is closed, so the loop idles
    and the next trigger re-enters; after a round that could not run the
    range is still open, so the loop retries within the bound (that is the
    chain host order 261009 asks for — bounded, never unbounded). The guard
    is released on EVERY path (success, runner error, refusal, cancellation)
    — a guard left held would pin the tick."""
    if not isinstance(chain_limit, int) or isinstance(chain_limit, bool) \
            or chain_limit < 1:
        raise CertifyError("chain_limit_invalid:%r" % (chain_limit,))
    rounds = []
    while True:
        rows, bad = read_rows()
        if bad:
            raise CertifyError("ledger_has_malformed_lines:%d" % len(bad))
        go, why = should_certify(trigger, rows, line, guard_held(guard_path),
                                 now_ms=now_ms, backstop_ms=backstop_ms)
        if not go:
            state = END_JOINED if why == "guard_held" else END_IDLE
            return {"rounds": rounds, "end": {"state": state, "reason": why}}
        if len(rounds) >= chain_limit:
            return {"rounds": rounds,
                    "end": {"state": END_CHAIN_LIMIT,
                            "reason": "chain_limit:%d" % chain_limit}}
        guard = guard_acquire(guard_path, judged_by)
        if guard is None:  # raced between the read and the acquire: join
            return {"rounds": rounds,
                    "end": {"state": END_JOINED, "reason": "guard_held"}}
        try:
            rng = derive_range(rows, line)
            if not rng["covered_landings"]:
                return {"rounds": rounds,
                        "end": {"state": END_IDLE, "reason": "range_empty"}}
            candidate = candidate_set(rng["covered_landings"])
            try:
                header = runner(candidate)
                cert = build_certification(candidate, header, booked_red,
                                           judged_by, at_ms=now_ms, line=line)
                verdict = run_verdict(header["cases"])
                batch = [cert]
                if verdict == "red":
                    batch += open_freeze_rows(cert, at_ms=now_ms)
                res = append_rows(batch)
                if res["written"] != len(batch):
                    raise CertifyError("round_append_rejected:%r"
                                       % (res["rejected"],))
                entry = {"state": STATE_CERTIFIED if verdict == "green"
                         else STATE_RED,
                         "cert": cert["id"], "run": cert["run"],
                         "verdict": verdict, "candidate": candidate}
                if verdict == "red":
                    # Re-read: the ladder is judged from the records' order
                    # (seq), which only exists after the append.
                    rows2, bad2 = read_rows()
                    if bad2:
                        raise CertifyError(
                            "ledger_has_malformed_lines:%d" % len(bad2))
                    red_cert = _of_kind(rows2, KIND_CERT, line)[-1]
                    frz = _of_kind(rows2, KIND_FREEZE, line)[-1]
                    entry["freeze"] = frz["id"]
                    try:
                        action, target = next_red_action(rows2, line, red_cert,
                                                         lane_reds)
                    except AlreadySearchedError:
                        action, target = "already_searched", None
                    entry["next"] = action
                    if action == "isolated":
                        append_rows([freeze_change_row(
                            frz["id"], CHANGE_ATTRIBUTION, judged_by,
                            "red ladder isolated the culprit",
                            value=target["id"], at_ms=now_ms, line=line)])
                        entry["attribution"] = target["id"]
                rounds.append(entry)
            except CouldNotRun as e:
                append_rows([could_not_run_row(line, str(e), at_ms=now_ms)])
                rounds.append({"state": STATE_GREW, "reason": str(e)})
        finally:
            guard_release(guard_path)
        trigger = "change"  # a chained round re-evaluates as a change tick
    # unreachable: every branch above returns


# ---- the tick call site (t261009-50) ----------------------------------------

#: The scheduled backstop interval: how long a quiet line waits before the
#: tick asks anyway. The line declaration is the natural per-line home, but
#: develop_line.py is outside this ticket's write set — a module constant with
#: an env override ships now, a per-line declared field is the follow-up.
LINE_BACKSTOP_MS_DEFAULT = 24 * 60 * 60 * 1000
BACKSTOP_MS_ENV = "SANDBAR_LINE_BACKSTOP_MS"
#: The declared full-suite runner command (the production ``runner`` seam for
#: run_line_round). Unset means the tick cannot reach a round for the line —
#: a named, operator-visible ``runner_missing``, never a silent idle and
#: never a ledger row (t261009-46 owns wiring a real runner).
RUNNER_CMD_ENV = "SANDBAR_LINE_ROUND_RUNNER"
RUNNER_TIMEOUT_ENV = "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S"
RUNNER_TIMEOUT_S_DEFAULT = 3600
#: Who the tick says judged when it asks on the schedule's behalf.
TICK_JUDGED_BY = "dispatcher-scan"
#: The expected-red inventory version in force when the tick asks (the
#: certification record refuses an empty booked_red by name — the tick
#: carries this declared default until the inventory versioning ticket
#: declares a real source).
TICK_BOOKED_RED = "scan-default-v1"


def backstop_ms_from_env(env=None):
    """The tick's backstop interval. Unset → the default; a set but
    non-integer or non-positive value is a named error, never a guess."""
    env = os.environ if env is None else env
    raw = str(env.get(BACKSTOP_MS_ENV, "")).strip()
    if not raw:
        return LINE_BACKSTOP_MS_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        raise CertifyError("backstop_ms_not_int:%r" % raw)
    if value < 1:
        raise CertifyError("backstop_ms_not_positive:%r" % raw)
    return value


def runner_timeout_s_from_env(env=None):
    env = os.environ if env is None else env
    raw = str(env.get(RUNNER_TIMEOUT_ENV, "")).strip()
    if not raw:
        return RUNNER_TIMEOUT_S_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        raise CertifyError("runner_timeout_not_int:%r" % raw)
    if value < 1:
        raise CertifyError("runner_timeout_not_positive:%r" % raw)
    return value


def resolve_runner(line, env=None):
    """The production runner seam. Returns a callable
    ``runner(candidate_repos) -> run header`` built from the declared command,
    or None when no runner is declared (``runner_missing`` — the tick records
    it on the operator surface and moves on; spec (4)). The command runs with
    ``SANDBAR_LINE_ROUND_CANDIDATES`` (the candidate revision set as JSON) in
    its environment, in a tree of its own; it must print one JSON run header
    (``{"id": "run-…", "cases": {"ran", "failed", "env_failed"}}``) on
    success. A nonzero exit, a malformed header, a timeout or an OS-level
    failure raises CouldNotRun — the round's own "could not run" path records
    range growth and opens nothing (goal 24).

    t261011-21 (host order 261011 defect 2): the runner is spawned as its
    own session (``start_new_session=True``) and registered in
    ``_INFLIGHT_RUNNERS`` while it lives, so a timed-out or cancelled tick
    can reap the WHOLE process group instead of orphaning a full suite
    (the 17:19 incident: the activity failed at 30 min and runner pid
    97387 kept running). The reap is the t261006-08 shape, sync twin:
    TERM first (the runner's own signal handlers reclaim the run tree),
    bounded wait, KILL, bounded wait; ESRCH/EPERM tolerate + direct-child
    fallback (same disposition as agent_activities.reap_spawn_group); the
    group-escape residual is declined — the repo-level sweep tooling stays
    the net (the ticket's fault-mode table)."""
    env = os.environ if env is None else env
    cmd = str(env.get(RUNNER_CMD_ENV, "")).strip()
    if not cmd:
        return None
    timeout_s = runner_timeout_s_from_env(env)

    import subprocess

    def runner(candidate_repos):
        run_env = dict(env)
        run_env["SANDBAR_LINE_ROUND_CANDIDATES"] = json.dumps(candidate_repos)
        try:
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=run_env,
                start_new_session=True)
        except OSError as e:
            raise CouldNotRun("runner_unreachable:%s" % e)
        # registered strictly AFTER a successful spawn: a failed Popen
        # never enters the registry (no leak between Popen and register)
        _INFLIGHT_RUNNERS[proc.pid] = {
            "proc": proc, "line": str(line), "at": time.time()}
        try:
            try:
                out, err = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                reap_runner_proc(proc, tag="line-round-runner")
                raise CouldNotRun("runner_timeout:%ds" % timeout_s)
            except BaseException:
                # a cancelled/killed waiter must not leave the tree alive
                reap_runner_proc(proc, tag="line-round-runner")
                raise
        finally:
            _INFLIGHT_RUNNERS.pop(proc.pid, None)
        if proc.returncode != 0:
            raise CouldNotRun("runner_failed_exit_%d:%s"
                              % (proc.returncode, (err or "").strip()[-200:]))
        try:
            header = json.loads(out)
        except ValueError:
            raise CouldNotRun("runner_header_malformed")
        if not isinstance(header, dict):
            raise CouldNotRun("runner_header_not_object")
        return header

    return runner


#: Spawned line-round runner processes this worker still owns
#: (pid -> {"proc", "line", "at"}). Consumed by reap_inflight_runners /
#: shutdown_inflight_ticks; an entry is removed the moment its wait ends.
_INFLIGHT_RUNNERS = {}
#: In-flight tick contexts (project_key -> {"guard_path", "at"}), registered
#: by line_round_tick_activity so an activity-level abort can leave the ONE
#: named ledger row the ticket demands (host order 261011 defect 3).
_INFLIGHT_TICKS = {}
#: Bounded waits of the TERM-first reap (short on purpose: the runner's own
#: TERM path reclaims its run tree in seconds).
_REAP_TERM_WAIT_S = 10.0
_REAP_KILL_WAIT_S = 5.0


def reap_runner_proc(proc, tag=""):
    """TERM the runner's process group -> bounded wait -> KILL -> bounded
    wait; the zombie is collected either way. Never raises for a group
    already gone (ESRCH) or a group we may not signal (EPERM) — falls back
    to signalling the direct child, best effort. Idempotent on an
    already-exited proc. Other OSErrors propagate (same stance as
    agent_activities._reap_agent_proc)."""
    import errno
    import signal
    import subprocess
    if getattr(proc, "returncode", None) is not None:
        return ""

    def _sig(sig_value):
        try:
            os.killpg(os.getpgid(proc.pid), sig_value)
        except OSError as e:
            if e.errno not in (errno.ESRCH, errno.EPERM):
                raise
            try:
                proc.send_signal(sig_value)
            except (ProcessLookupError, OSError):
                pass

    def _wait_bounded(t):
        try:
            proc.wait(timeout=t)
            return True
        except subprocess.TimeoutExpired:
            return False

    _sig(signal.SIGTERM)
    if not _wait_bounded(_REAP_TERM_WAIT_S):
        _sig(signal.SIGKILL)
        _wait_bounded(_REAP_KILL_WAIT_S)
    note = "reaped pid=%s returncode=%s" % (proc.pid, proc.returncode)
    if tag:
        note = "%s %s" % (tag, note)
    return note


def reap_inflight_runners(reason=""):
    """Reap every registered runner (a timed-out / cancelled tick must not
    orphan a full suite — host order 261011 defect 2). Idempotent: a pid
    whose wait already ended was popped by the wait's own finally or a
    previous pass. Returns the list of reaped pids; never raises for a
    gone group, so it can run on the cancellation path before the
    original exception is re-raised."""
    reaped = []
    for pid, info in list(_INFLIGHT_RUNNERS.items()):
        proc = info.get("proc")
        _INFLIGHT_RUNNERS.pop(pid, None)
        if proc is None:
            continue
        reap_runner_proc(proc, tag="[line-round-reap]")
        reaped.append(pid)
    return reaped


def abort_inflight_ticks(reason, append_rows_fn=None, now_ms=None):
    """The abort-row face (host order 261011 defect 3): for every tick
    context whose guard is STILL held (a round was genuinely in flight),
    append ONE ``could_not_run`` row per in-flight runner line naming why —
    a dead round must never look like no round. Rows land through
    ``append_rows_fn`` when the caller injects one, else through the
    context's own ledger path (the activity/shutdown faces). Scoped on
    purpose: a held guard is only a FILTER here; this face NEVER releases
    a guard (the release belongs exclusively to run_line_round's finally —
    a foreign guard stays untouched). An append failure is named on stderr
    and never masks the caller's original exception. Returns the appended
    lines."""
    import sys as _sys
    appended = []
    reason = str(reason or "activity_aborted").strip()
    for project_key, ctx in list(_INFLIGHT_TICKS.items()):
        guard_path = ctx.get("guard_path")
        ledger = ctx.get("ledger")
        write = append_rows_fn
        if write is None and ledger:
            write = lambda batch: append_rows(batch, str(ledger))  # noqa: E731
        try:
            if not guard_path or not guard_held(guard_path):
                continue
            lines = sorted({str(info.get("line") or "<unknown>")
                            for info in _INFLIGHT_RUNNERS.values()})
            for line in lines:
                row = could_not_run_row(
                    line, "activity_aborted:%s" % reason, at_ms=now_ms)
                if write is not None:
                    write([row])
                appended.append(line)
        except Exception as e:  # noqa: BLE001 — never mask the re-raise
            _sys.stderr.write(
                "LINE_ROUND_ABORT row_failed:%s:%s: %s\n"
                % (project_key, reason, e))
    return appended


def shutdown_inflight_ticks():
    """Worker-shutdown face (t261011-21 review C2): reap every in-flight
    runner and write the abort rows on graceful stop, so a stopped worker
    cannot re-create the orphan shape by another door. Registered via
    atexit at import; SIGKILL stays unnetted (the sweep tooling is that
    net, unchanged). Idempotent by construction. The abort rows are written
    BEFORE the reap clears the registry — the rows name the in-flight
    lines, which only the still-populated registry knows."""
    appended = abort_inflight_ticks("worker_shutdown")
    reaped = reap_inflight_runners(reason="worker_shutdown")
    _INFLIGHT_TICKS.clear()
    return {"reaped": reaped, "appended": appended}


import atexit as _atexit  # noqa: E402 — registered once at import

_atexit.register(shutdown_inflight_ticks)


def line_round_tick(project_key, load_lines, read_rows, append_rows,
                    resolve_runner_fn, guard_path, now_ms, backstop_ms=None,
                    judged_by=TICK_JUDGED_BY, booked_red=TICK_BOOKED_RED,
                    chain_limit=CHAIN_LIMIT, lane_reds=None, env=None):
    """One scheduled tick's ask, per declared line (t261009-50 spec 1-5).

    This is the CALL SITE, not a second round: it reads the records, asks
    ``should_certify`` (the one decision) with the superset trigger, maps the
    reason to the trigger string, and hands the ask to ``run_line_round``
    (the one round, with its guard, chaining and checkout refusal). It adds
    no bookkeeping beyond the returned entries — what this tick already did.

    Per line, exactly once per tick:
    - idle (no event, no backstop due): ``{"state": "idle", "reason": …}`` —
      the tick starts no round and writes nothing;
    - ``runner_missing``: the declared runner is absent — a named entry on
      the operator surface only, never a delivery-ledger row;
    - otherwise the round runs (or joins a round already in flight —
      ``run_line_round``'s own join rule answers, the guard is left as found,
      zero rows written) and the entry carries the round's ``trigger`` and
      ``end`` so the two trigger shapes stay distinguishable on the record;
    - every ``CertifyError`` is caught per line as a named ``error`` entry —
      one broken line never takes the tick down, and the tick never looks
      like "nothing to do" when a line could not be reached.
    """
    try:
        lines = load_lines(project_key)
    except Exception as e:
        return {"lines": [{"error": "line_declaration_unreadable:%s"
                           % (type(e).__name__,)}],
                "summary": "line_round_tick: declaration unreadable (%s)"
                           % (type(e).__name__,)}
    if backstop_ms is not None and (isinstance(backstop_ms, bool)
                                    or not isinstance(backstop_ms, int)
                                    or backstop_ms < 1):
        # Named refusal at the face (spec 4 / arbitration gen0 F6c): a
        # non-int backstop must never reach should_certify's comparison as a
        # raw TypeError — every declared line gets the named per-line error
        # entry and the tick's result stays whole.
        named = "backstop_ms_not_int:%r" % (backstop_ms,)
        return {"lines": [{"line": line, "state": "error", "error": named}
                          for line in sorted(lines)],
                "summary": "line_round_tick: %s" % named}
    if now_ms is not None and (isinstance(now_ms, bool)
                               or not isinstance(now_ms, int)):
        named = "backstop_needs_now_ms:%r" % (now_ms,)
        return {"lines": [{"line": line, "state": "error", "error": named}
                          for line in sorted(lines)],
                "summary": "line_round_tick: %s" % named}
    entries = []
    rows, bad = read_rows()
    if bad:
        named = "ledger_has_malformed_lines:%d" % len(bad)
        return {"lines": [{"error": named}],
                "summary": "line_round_tick: %s" % named}
    for line in sorted(lines):
        try:
            go, why = should_certify("backstop", rows, line,
                                     guard_held(guard_path), now_ms=now_ms,
                                     backstop_ms=backstop_ms)
        except CertifyError as e:
            entries.append({"line": line, "state": "error",
                            "error": str(e)})
            continue
        if not go and why in ("range_empty", "backstop_not_elapsed"):
            entries.append({"line": line, "state": "idle", "reason": why})
            continue
        runner = resolve_runner_fn(line, env)
        if runner is None:
            entries.append({"line": line, "state": "runner_missing"})
            continue
        trigger = "change" if why == "range_non_empty" else "backstop"
        try:
            res = run_line_round(line, trigger, guard_path, runner, read_rows,
                                 append_rows, judged_by, booked_red,
                                 backstop_ms=backstop_ms, now_ms=now_ms,
                                 chain_limit=chain_limit, lane_reds=lane_reds)
        except CertifyError as e:
            entries.append({"line": line, "state": "error", "error": str(e)})
            continue
        entries.append({"line": line, "state": res["end"]["state"],
                        "trigger": trigger, "reason": why,
                        "rounds": res["rounds"]})
    asked = [e for e in entries if "rounds" in e]
    failed = [e["line"] for e in entries if e.get("state") in
              ("error", "runner_missing")]
    idle = [e["line"] for e in entries if e.get("state") == "idle"]
    summary = ("line_round_tick: %d lines, asked %d, idle %d, not-runnable %s"
               % (len(entries), len(asked), len(idle),
                  failed if failed else "none"))
    return {"lines": entries, "summary": summary}


def declared_line_projects(projects_root=None):
    """The projects whose develop dir declares at least one line — the tick's
    enumeration (the scan is engine-level; lines are per project). A project
    without ``data/develop/lines.json`` is simply not a line project; a
    declared but UNREADABLE file is left to line_round_tick's own named
    handling (never silently dropped here)."""
    from shared import perkey_projects_root  # local: keep module import-light

    root = Path(projects_root) if projects_root else perkey_projects_root()
    try:
        entries = sorted(root.iterdir())
    except OSError as e:
        raise CertifyError("projects_root_unreadable:%s" % e)
    return [d.name for d in entries
            if (d / "data" / "develop" / "lines.json").is_file()]


def line_round_tick_engine():
    """The engine-level tick body: one ask per declared line of every
    line-declaring project. This is what the scan tick's activity calls;
    one project's failure is an entry, never the tick's death (spec 4)."""
    out = {}
    try:
        projects = declared_line_projects()
    except CertifyError as e:
        return {"projects": {}, "summary": "line_round_tick: %s" % e}
    for project_key in projects:
        try:
            out[project_key] = line_round_tick_activity(project_key)
        except Exception as e:  # the activity body itself failed loudly
            out[project_key] = {
                "lines": [{"error": "tick_activity_failed:%s:%s"
                           % (type(e).__name__, e)}],
                "summary": "line_round_tick: activity failed (%s)"
                           % (type(e).__name__,)}
    total = sum(len(r.get("lines", [])) for r in out.values())
    failed = [k for k, r in out.items()
              if any(l.get("state") in ("error", "runner_missing")
                     for l in r.get("lines", []))]
    summary = "line_round_tick: %d projects, %d lines, not-runnable %s" \
        % (len(out), total, failed if failed else "none")
    return {"projects": out, "summary": summary}


def line_round_tick_activity(project_key):
    """The production body of the scan tick's line-round activity. The
    ``@activity.defn`` wrapper and its ALL_ACTIVITIES registration live in
    activities.py (the single activity registration face; t261009-50 wiring),
    and the DispatcherScanWorkflow patched block calls that wrapper — the
    exact pending patch is in integration/t261009-50/wiring-handoff.md.
    Determinism: file IO and the runner subprocess belong in the activity,
    never in workflow code (DispatcherScanWorkflow's contract)."""
    from develop_line import load_lines  # local: develop_line imports us

    ledger = ledger_path(project_key)
    guard_path = str(ledger.parent / "tick-anchor")
    # t261011-21 defect 3: registered so an activity-level abort
    # (abort_inflight_ticks) can find this tick's guard and leave the ONE
    # named row; popped the moment the body returns either way.
    _INFLIGHT_TICKS[str(project_key)] = {
        "guard_path": guard_path, "ledger": str(ledger), "at": time.time()}
    try:
        return line_round_tick(
            project_key,
            load_lines=load_lines,
            read_rows=lambda: read_rows(ledger),
            append_rows=lambda batch: append_rows(batch, ledger),
            resolve_runner_fn=resolve_runner,
            guard_path=guard_path,
            now_ms=int(time.time() * 1000),
            backstop_ms=backstop_ms_from_env())
    finally:
        _INFLIGHT_TICKS.pop(str(project_key), None)


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
