#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""develop_promote — the human-signed promotion of a certified prefix, the
three-stage ticket outcome, and the withdrawal guard.

Ticket t261009-23 (develop-buffer design goals 11, 14, 23-27; design source
docs/design/develop-buffer-v1.md; record shapes
docs/reference/ledger-record-models-v1.md section A "promotion", section
"withdrawal is work, not a record", section "projection", section B
"relation").

What this module owns:

- The **promotion record** (goal 11, spec (a)+(b)+(d)): the act of moving a
  certified range to ``main``, approved by a person. It records THREE
  separate things that a merged field could not machine-check: ``signer``
  (who actually signed), ``on_behalf_of`` (whose authority was exercised —
  delegation is allowed and recorded as such), and ``authority`` (the named
  order the signature rests on). It names the certification it rests on; a
  promotion that cannot name one is refused BY NAME, never defaulted.
  ``main_before`` / ``main_after`` / ``tickets`` / the moment make the record
  the durable account of what a person approved — it lives in an append-only
  ledger, never in main, so a later rewrite of main's history (a
  withdrawal) cannot touch it (spec (d)).

- The **ticket outcome projection** (goal 14, spec (c)): ``landed``,
  ``certified`` and ``delivered`` as three INDEPENDENT derived fields —
  never one status enum, because "a closed ticket" and "a delivered ticket"
  must stay tellable apart. Derived only, carries the cursor it was computed
  up to, droppable and rebuildable; the rebuild-and-compare is the drift
  check; no other record may cite it.

- The **withdrawal relation and the promotion guard** (spec (e)): there is
  NO revert record type. A withdrawal is a ticket whose change is the undo;
  the ledger keeps a ``withdraws`` RELATION row ("this work withdraws that
  ticket's landing"), and the promotion check refuses — by name — a
  candidate whose patch identity matches a withdrawn landing. A git failure
  during the patch-id computation refuses too (``patch_id_unavailable``);
  it NEVER degrades to an empty guard set, because an empty set silently
  allows re-introduction, which is the exact defect spec (e) exists to
  prevent. Scope limit kept honest (record-models doc): the relation names a
  ticket's landing, the guard compares patch ids; an exact withdrawal
  matches exactly, a partial one must say so in the relation's reason.

Ledger decision (t261009-29 — the split this module was born with is removed):
the delivery ledger's kind set now admits ``promotion`` and the §B relation
kinds (``withdraws`` / ``repairs`` / ``supersedes``), so landings,
certifications, promotions and relations share ONE file
(``delivery.jsonl``), ONE writer (``develop_certify.append_rows``) and ONE
seq space. That is what makes "the landings after the previous
certification" computable across the whole family, and the projection's
derived facts all come from that one space — there is no cross-file
comparison left, because there is no second file. The relations joined the
same space with the promotion (recorded decision, ticket item 4): the
withdrawal guard and ``reverted_at`` already join relations to promotions
and landings, so a separate relation file would have re-created the
cross-file comparison one level down.

Legacy ``promotion.jsonl`` (the sibling file this module used before
t261009-29) is either MIGRATED — ``migrate_legacy_promotion_ledger``
appends its rows into the delivery ledger in ``at``-then-file order, so the
shared writer assigns seqs in that order, then renames the file — or
REFUSED BY NAME: any read or append face that finds an unmigrated legacy
file holding rows raises ``legacy_promotion_file_not_migrated`` instead of
silently reading "no promotions".

Borrowed-implementation dispositions (the pattern is
develop_certify.py's store face, which itself carries
integration/scenario_ledger.py's; the git subprocess family is
agent_activities._git, borrowed exactly like develop_line does):

- flock whole-append serialisation under ``<dir>/.lock``, single write +
  fsync: **carried** — and now trivially shared, because the promotion
  family writes through ``develop_certify.append_rows`` itself.
- duplicate-id refusal on append: **carried**.
- malformed/partial lines on read: **carried via develop_certify.read_rows**
  (bad lines collected, capped, append refuses a ledger that has any).
- append never rewrites ledger bytes: **carried** (migration RENAMES the
  legacy file, it never rewrites it).
- loud maintenance failures: **carried** — a wrong-shaped field is a named
  refusal, never a guess.
- ULID mint: **reused from develop_certify.mint_id** (same shape, same
  process-monotonic discipline; the shape is pinned by the record-models
  document).
- bounded-timeout git subprocess: **carried** — timeouts, non-zero exits and
  a missing binary each become a named error (``patch_id_unavailable``),
  never a silent empty result (review condition 4).

Coexistence: nothing on the running flow imports this module yet, so no
production ``promotion.jsonl`` exists today — the migration face is built
and tested against fixture files, and the refusal is the guard for any
straggler that turns up later.

Ordering space (t261009-29, closing the limit t261009-27 stated): ONE file,
ONE seq space. The landing→certification rule ("cert seq > landing seq"),
promotion selection (``delivered_in``), and every relation reading
(``withdrawn_at``, ``reverted_at``, ``superseded_by/at``) all read the same
list; within-file seq monotonicity is the shared writer's own, and no
comparison spans files because there is one file.
"""

import os
import subprocess
import time
from pathlib import Path

from agent_activities import _git  # noqa: E402  (borrowed, never re-implemented)
import develop_certify as dc  # noqa: E402

RECORD_VERSION = 1

#: The LEGACY promotion/relation ledger file — the sibling file this module
#: used before t261009-29 joined the ordering space. It exists now only as
#: the migration input and the named refusal; the live ledger is the
#: delivery ledger (``develop_certify.MAIN_NAME``).
PROMOTION_NAME = "promotion.jsonl"

#: Aliases of the shared kind set — the delivery ledger's writer owns the
#: names now; this module re-exports them so existing importers keep
#: working.
KIND_PROMOTION = dc.KIND_PROMOTION
#: Relation rows follow the record-models §B shape literally: the ``kind``
#: FIELD carries the relation kind and the ``rel-`` id prefix carries the
#: family — so family detection is by id prefix, not by this field.
REL_KIND_WITHDRAWS = dc.REL_KIND_WITHDRAWS
REL_KIND_REPAIRS = dc.REL_KIND_REPAIRS
#: A newer ticket took this one's place. Derived ending face only (goal 14):
#: the outcome view reads ``supersedes`` relations; nothing else consumes
#: them yet. Registered together with the validator (review condition):
#: a kind declared here but rejected by the validator would be an ending
#: derived from rows the writer refuses to store.
REL_KIND_SUPERSEDES = dc.REL_KIND_SUPERSEDES
RELATION_KINDS = dc.RELATION_KINDS

#: Product kinds of the outcome view (goal 14): which fact ends a ticket.
#: These are the VIEW's names, not the tickets' raw ``kind`` strings.
PRODUCT_KIND_CHANGE = "change"
PRODUCT_KIND_REPORT = "report"
PRODUCT_KIND_VERIFICATION = "verification"
PRODUCT_KIND_UNKNOWN = "unknown"

#: Named mapping from the kind a ticket actually carries to the product kind
#: the projection reports. Explicit table, never prose and never a guess
#: (review condition 1): a raw kind not in this table reads ``unknown`` by
#: name instead of defaulting to ``change``.
#: - landable change kinds (develop_certify ``LANDABLE_KINDS`` + the plain
#:   ``change`` name) end through the delivery path;
#: - an inspection period (the real ticket shape: ``kind: "inspection"``)
#:   and a plain ``report`` are report products — the ticket's findings and
#:   the stamped period cursor are the product;
#: - a verification ticket's product is its verdict.
TICKET_KIND_TO_PRODUCT = {
    "change": PRODUCT_KIND_CHANGE,
    "fix": PRODUCT_KIND_CHANGE,
    "chore": PRODUCT_KIND_CHANGE,
    "inspection": PRODUCT_KIND_REPORT,
    "report": PRODUCT_KIND_REPORT,
    "verification": PRODUCT_KIND_VERIFICATION,
    "verify": PRODUCT_KIND_VERIFICATION,
}


class PromoteError(Exception):
    """A named failure of the promotion face. Raised, never guessed."""


class PromotionRefused(PromoteError):
    """A promotion that may not be recorded. ``.reason`` names why — the
    caller shows it to the human, it is never swallowed or defaulted."""


class PatchIdUnavailable(PromoteError):
    """The patch identity of a revision could not be computed (git non-zero
    exit, timeout, missing binary). The guard refuses; it never degrades to
    an empty set (an empty set silently allows re-introduction)."""


class WithdrawnTargetUnknown(PromoteError):
    """A ``withdraws`` relation names a ticket with no landing in the ledger
    — the guard cannot compute what it must refuse, so it refuses loudly."""


# ---- paths ------------------------------------------------------------------

def promotion_path(project, ledger_dir=None):
    """Resolve the LEGACY promotion ledger path (the sibling file). Kept for
    the migration face and for tests of that face; the live ledger resolves
    through ``develop_certify.ledger_path``."""
    d = ledger_dir or os.environ.get(dc.LEDGER_DIR_ENV, "").strip() or None
    if d:
        return Path(d) / PROMOTION_NAME
    home = Path(os.path.expanduser("~"))
    return home / ".sandbar" / "projects" / str(project) / "ledger" / PROMOTION_NAME


# ---- row validation ---------------------------------------------------------

def _bad(why):
    return None, why


def _valid_str(value):
    return isinstance(value, str) and value.strip() != ""


def validate_row(row):
    """Validate one candidate row through the SHARED validator: the delivery
    ledger's kind set admits the promotion and relation kinds since
    t261009-29, so there is exactly one validator and one refusal table —
    this module keeps none of its own. Unknown kind / missing field / wrong
    shape is refused by name, never guessed around."""
    return dc.validate_row(row)


# ---- store face (the delivery ledger IS the promotion ledger now) -----------

def legacy_promotion_path(delivery_path):
    """The legacy sibling file next to a delivery ledger path (the file this
    module wrote before t261009-29 joined the ordering space)."""
    return Path(delivery_path).parent / PROMOTION_NAME


def _unmigrated_legacy_rows(delivery_path):
    """Rows still sitting in the legacy file, [] when there is none (or when
    the target IS the legacy file — the migration face reads it directly)."""
    legacy = legacy_promotion_path(delivery_path)
    if Path(delivery_path).resolve() == legacy.resolve():
        return []
    rows, _bad = dc.read_rows(legacy)
    return rows


def _refuse_unmigrated_legacy(delivery_path):
    """The guard every consumer-reachable face sits behind: a legacy
    ``promotion.jsonl`` holding rows is a MIGRATION DEBT, never a silence —
    reading it as "no promotions" is exactly the failure the ticket forbids
    by name."""
    rows = _unmigrated_legacy_rows(delivery_path)
    if rows:
        raise PromoteError("legacy_promotion_file_not_migrated:%s:%d"
                           % (PROMOTION_NAME, len(rows)))


def read_promotion_rows(path):
    """Read the shared ledger via the loud shared reader (malformed lines
    collected and reported, never silently skipped). An unmigrated legacy
    ``promotion.jsonl`` next to the ledger refuses by name first."""
    _refuse_unmigrated_legacy(path)
    return dc.read_rows(path)


def append_rows(rows, path):
    """Validate + append through the SHARED writer — one flock, one write +
    fsync, monotonic seq assigned in the critical section, duplicate ids
    refused, all-rejected means zero bytes land, existing bytes never
    rewritten. ``path`` is the delivery ledger: landings, certifications,
    promotions and relations take their seqs from the one space. An
    unmigrated legacy ``promotion.jsonl`` refuses by name first — new-space
    writes must not start while the old space still holds rows."""
    _refuse_unmigrated_legacy(path)
    try:
        return dc.append_rows(rows, path)
    except dc.CertifyError as exc:
        # the shared writer's loud store errors keep this module's own
        # contract: the caller of THIS face catches PromoteError, the name
        # travels verbatim
        raise PromoteError(str(exc))


def migrate_legacy_promotion_ledger(delivery_path, legacy_path=None):
    """Fold the legacy sibling file into the delivery ledger's ordering
    space. The seq assignment order is the ticket's stated order: ``at``
    first, file position breaking ties (a stable sort — equal ``at`` keeps
    the order the rows were read in). Every refusal is by name:

    - ``legacy_has_malformed_lines`` — a torn line is a fact, not noise;
    - ``legacy_row_invalid:<id>:<why>`` — a row the shared validator refuses;
    - ``legacy_row_duplicate:<id>`` — twice inside the legacy file itself;
    - ``id_already_in_delivery_ledger:<id>`` — already folded (a previous
      migration that died before the rename, or double-booked work).

    On success the legacy file is RENAMED (never rewritten) to
    ``promotion.jsonl.migrated`` — append-only discipline kept, and a second
    run is a clean no-op (nothing to read)."""
    delivery_path = Path(delivery_path)
    legacy = Path(legacy_path) if legacy_path is not None \
        else legacy_promotion_path(delivery_path)
    if legacy.resolve() == delivery_path.resolve():
        raise PromoteError("legacy_file_is_delivery_ledger")
    if not legacy.exists():
        return {"migrated": 0, "renamed": False, "seqs": []}
    rows, bad = dc.read_rows(legacy)
    if bad:
        raise PromoteError("legacy_has_malformed_lines:%d" % len(bad))
    indexed = sorted(enumerate(rows),
                     key=lambda p: (p[1].get("at")
                                    if dc._valid_at(p[1].get("at")) else 0,
                                    p[0]))
    ordered, in_legacy = [], set()
    for _i, row in indexed:
        clean, why = dc.validate_row(row)
        if clean is None:
            raise PromoteError("legacy_row_invalid:%s:%s"
                               % (row.get("id"), why))
        if clean.get("id") in in_legacy:
            raise PromoteError("legacy_row_duplicate:%s" % clean["id"])
        in_legacy.add(clean["id"])
        ordered.append(clean)
    existing, dbad = dc.read_rows(delivery_path)
    if dbad:
        raise PromoteError("ledger_has_malformed_lines:%d" % len(dbad))
    in_ledger = {r.get("id") for r in existing if isinstance(r, dict)}
    for row in ordered:
        if row.get("id") in in_ledger:
            raise PromoteError("id_already_in_delivery_ledger:%s"
                               % row["id"])
    res = dc.append_rows(ordered, delivery_path)
    if res["rejected"] or res["written"] != len(ordered):
        raise PromoteError("migration_append_refused:%s" % res["rejected"])
    os.replace(str(legacy), str(legacy) + ".migrated")
    return {"migrated": len(ordered), "renamed": True,
            "seqs": res["seqs"]}


# ---- the promotion ----------------------------------------------------------

def check_certification(cert_id, delivery_rows, is_green=None):
    """The certification a promotion names must EXIST in the delivery ledger
    and, when the caller can read runs, be GREEN. ``is_green`` maps a run id
    to bool (injected; None means every certification counts — a caller that
    cannot read runs must say so, not guess; the same rule as
    develop_certify.landable)."""
    if not (isinstance(cert_id, str) and cert_id.startswith("cert-")):
        raise PromotionRefused("promotion_without_named_certification")
    certs = [r for r in delivery_rows
             if isinstance(r, dict) and r.get("kind") == dc.KIND_CERT
             and r.get("id") == cert_id]
    if not certs:
        raise PromotionRefused("certification_not_in_ledger:%s" % cert_id)
    cert = certs[0]
    if callable(is_green) and not is_green(cert.get("run")):
        raise PromotionRefused("certification_not_green:%s" % cert_id)
    return cert


def _repos_map(repos):
    return {r["repo"]: r["revision"] for r in repos}


def _ticket_landing(delivery_rows, ticket):
    """The ticket's landing row (latest by the delivery ledger's seq). None
    when the ticket never landed — ``tickets_not_covered`` then."""
    rows = [r for r in delivery_rows
            if isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING
            and r.get("ticket") == ticket and isinstance(r.get("seq"), int)]
    rows.sort(key=lambda r: r["seq"])
    return rows[-1] if rows else None


def build_promotion(cert_id, line, tickets, main_before, main_after, signer,
                    on_behalf_of=None, authority=None, note=None, at_ms=None,
                    delivery_rows=(), is_green=None):
    """Build one promotion row, or raise PromotionRefused with a named
    reason. Every check answers a spec sentence:

    - a named certification that exists and is green (spec (b));
    - every ticket carried has a landing contained in the certified
      revision (the promotion delivers content that was proven);
    - ``main_after`` equals the certified revision per repository (what
      main becomes is what was certified, nothing else);
    - signer present; delegation fields stand together (spec (a)).
    """
    cert = check_certification(cert_id, delivery_rows, is_green=is_green)
    cert_repos = _repos_map(cert["repos"])
    for t in tickets or []:
        landing = _ticket_landing(delivery_rows, t)
        if landing is None:
            raise PromotionRefused("tickets_not_covered:%s" % t)
        lrev = _repos_map(landing["repos"])
        for repo, rev in lrev.items():
            if cert_repos.get(repo) != rev:
                raise PromotionRefused("tickets_not_covered:%s" % t)
    if (on_behalf_of is None) != (authority is None):
        raise PromotionRefused("delegation_incomplete")
    if not _valid_str(signer):
        raise PromotionRefused("promotion_missing_signer")
    after = _repos_map(main_after)
    if after != cert_repos:
        raise PromotionRefused("main_after_not_certified_revision")
    row = {
        "kind": KIND_PROMOTION,
        "id": dc.mint_id("prom", at_ms=at_ms),
        "certification": cert_id,
        "line": line,
        "repos": list(cert["repos"]),
        "tickets": list(tickets),
        "main_before": list(main_before),
        "main_after": list(main_after),
        "signer": signer,
        "on_behalf_of": on_behalf_of,
        "authority": authority,
        "note": note,
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }
    clean, why = validate_row(row)
    if clean is None:
        raise PromotionRefused(why)
    return clean


def record_promotion(row, path):
    """Append one built promotion row; a refusal comes back as the append
    result's ``rejected`` entry or as a loud store error."""
    return append_rows([row], path)


def record_relation(rel_kind, from_ticket, to_ticket, recorded_by, reason,
                    at_ms=None):
    """Build one relation row (record-models §B shape: the ``kind`` FIELD is
    the relation kind, the ``rel-`` prefix is the family). This is how a
    withdrawal is recorded — as work and a relation, NEVER as a revert
    record type (spec (e))."""
    row = {
        "id": dc.mint_id("rel", at_ms=at_ms),
        "from": from_ticket,
        "to": to_ticket,
        "kind": rel_kind,
        "recorded_by": recorded_by,
        "reason": reason,
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }
    clean, why = validate_row(row)
    if clean is None:
        raise PromoteError(why)
    return clean


# ---- the withdrawal guard ---------------------------------------------------

def patch_id(revision, repo_path, timeout=60):
    """The stable patch identity of one revision: ``git diff-tree -p
    --root <rev>`` piped through ``git patch-id --stable``. ``repo_path`` is
    a checkout on disk (the NAME-to-path adapter is the caller's). The first
    call borrows the engine's bounded-timeout ``_git``; the second needs
    stdin so it runs as its own bounded subprocess. Every failure mode
    (non-zero exit, timeout, missing binary) raises PatchIdUnavailable —
    never an empty answer."""
    if not _valid_str(revision) or not _valid_str(str(repo_path)):
        raise PatchIdUnavailable("patch_id_bad_input")
    try:
        diff = _git(["diff-tree", "-p", "--root", revision], Path(repo_path),
                    timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PatchIdUnavailable("patch_id_timeout:%s" % revision)
    except OSError as exc:  # missing binary, unwritable cwd, ...
        raise PatchIdUnavailable("patch_id_git_unavailable:%s" % exc)
    if diff.returncode != 0:
        raise PatchIdUnavailable("patch_id_difftree_failed:%s" % revision)
    try:
        pid = subprocess.run(["git", "patch-id", "--stable"],
                             cwd=str(repo_path), input=diff.stdout,
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PatchIdUnavailable("patch_id_timeout:%s" % revision)
    except OSError as exc:
        raise PatchIdUnavailable("patch_id_git_unavailable:%s" % exc)
    if pid.returncode != 0:
        raise PatchIdUnavailable("patch_id_patchid_failed:%s" % revision)
    first = pid.stdout.strip().split("\n")[0].strip().split(" ")[0]
    if not first:
        raise PatchIdUnavailable("patch_id_empty:%s" % revision)
    return first


def withdrawn_patch_ids(rows, patch_id_fn, repo):
    """The guard set: patch id -> the relation id that forbids it. Built from
    every ``withdraws`` relation, resolved through the withdrawn ticket's
    landing — both from the ONE ledger list (t261009-29: one ordering
    space). Unknown target and unavailable patch id both refuse loudly —
    the guard NEVER silently shrinks. ``repo`` is the repository NAME as the
    records spell it; ``patch_id_fn(revision, repo_name)`` is the injected
    adapter that resolves that name to a checkout (the engine never guesses
    the wiring — the same seam rule as develop_certify's ``is_green``)."""
    landings = [r for r in rows
                if isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING
                and isinstance(r.get("seq"), int)]
    latest = {}
    for l in sorted(landings, key=lambda r: r["seq"]):
        latest[l["ticket"]] = l
    guard = {}
    for row in sorted(rows, key=lambda r: r.get("seq") or 0):
        if row.get("kind") != REL_KIND_WITHDRAWS:
            continue
        rel_id = row["id"]
        target = latest.get(row.get("to"))
        if target is None:
            raise WithdrawnTargetUnknown(
                "withdrawn_target_unknown:%s" % rel_id)
        for r in target.get("repos", []):
            if r.get("repo") != repo:
                continue
            guard[patch_id_fn(r["revision"], repo)] = rel_id
    return guard


def check_withdrawn(candidate_ticket, rows, patch_id_fn, repo):
    """Refuse — by name — a promotion candidate whose content re-introduces
    a withdrawn patch (spec (e)). Raises PromotionRefused
    (``withdrawn_patch_present:<rel-id>``), WithdrawnTargetUnknown or
    PatchIdUnavailable; returns the (possibly empty) guard set when clean.
    ``rows`` is the ONE ledger list (landings, certifications, promotions,
    relations together)."""
    landing = _ticket_landing(rows, candidate_ticket)
    if landing is None:
        raise PromotionRefused("tickets_not_covered:%s" % candidate_ticket)
    guard = withdrawn_patch_ids(rows, patch_id_fn, repo)
    lrev = _repos_map(landing["repos"])
    rev = lrev.get(repo)
    if rev is not None:
        pid = patch_id_fn(rev, repo)
        if pid in guard:
            raise PromotionRefused(
                "withdrawn_patch_present:%s" % guard[pid])
    return guard


# ---- the outcome projection (derived only; three stages stay distinct) ------

def ticket_outcome(rows, ticket, is_green=None, ticket_record=None):
    """The ticket's outcome as a derived view (record-models projection
    rules): three INDEPENDENT fields — ``landed_at`` (the revision set the
    ticket put on the line), ``certified_by`` (a green certification whose
    seq is after the landing's), ``delivered_in`` (a promotion row carrying
    the ticket) — plus the ending faces:

    Ordering space (t261009-29): ``rows`` is the ONE ledger list — landings,
    certifications, promotions and relations together. NO comparison crosses
    files, because there is one file: the cert-after-landing rule, the
    promotion selection and every relation reading all read the same seq
    space the shared writer assigns.

    - ``reverted_at``: a ``withdraws`` relation against this ticket whose
      own landing was later delivered (today's face, unchanged);
    - ``withdrawn_at``: a ``withdraws`` relation whose ``to`` is this
      ticket — the ticket's own landing was withdrawn and never delivered.
      The relation IS the recorded judgement (record-models, withdrawal is
      work, not a record), so it sets ``withdrawn_at`` whether or not the
      withdrawing ticket itself has a landing; the loud
      ``WithdrawnTargetUnknown`` raise stays only on the ``reverted_at``
      path, where the withdrawing ticket's landing is the fact being read;
    - ``superseded_by`` / ``superseded_at``: the newest ``supersedes``
      relation whose ``to`` is this ticket (relation ``at``, then relation
      id, break ties). Coexistence is the point: a ticket can be delivered
      and later superseded, so these sit beside ``delivered_in`` rather
      than replacing it;
    - ``ending``: which ending applies, in precedence order
      reverted > superseded > withdrawn > ended > open. A convenience
      summary — never a status enum; every independent field behind it
      stays readable on its own.

    The product's kind (goal 14): ``product_kind`` is read from what the
    ticket actually carries — ``ticket_record["kind"]`` through the named
    ``TICKET_KIND_TO_PRODUCT`` table. A kind the table does not know reads
    ``unknown`` BY NAME, never a default to ``change``. The kind decides
    which fact ends the ticket (record-models "agreed, waiting to be
    built" item 8):

    - ``change``: the delivery path — ``ended_by`` is ``certification``
      (the covering certification is where the life ends) with the
      certification's moment, or ``delivery`` when a promotion exists
      without a readable covering certification;
    - ``report``: the ticket's findings are recorded and its period cursor
      is stamped (non-empty ``findings`` AND a ``period`` on the ticket
      record) — ``ended_by: "findings"``, ``ended_at`` the ticket's own
      moment when it carries one;
    - ``verification``: a verdict is recorded on the ticket —
      ``ended_by: "verdict"``;
    - ``unknown``: no ending fact is derived; a landing without a covering
      certification still reads ``waiting_since`` as before.

    A report or verification ticket is NEVER reported waiting: its ending
    fact is not a landing, so "waiting since the landing" is meaningless
    for it even if a landing row exists.

    Carries the cursor it was computed up to (``as_of``), is droppable and
    rebuildable (``compare_outcomes`` is the drift check), and no other
    record may cite it — the view has no ``id``, no ``seq`` and no ``at``
    of its own.
    """
    if not _valid_str(ticket):
        raise PromoteError("ticket_not_named")
    landings = [r for r in rows
                if isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING
                and r.get("ticket") == ticket and isinstance(r.get("seq"), int)]
    landings.sort(key=lambda r: r["seq"])
    landing = landings[-1] if landings else None

    certified_by = None
    certified_at = None
    if landing is not None:
        certs = [r for r in rows
                 if isinstance(r, dict) and r.get("kind") == dc.KIND_CERT
                 and isinstance(r.get("seq"), int) and r["seq"] > landing["seq"]]
        certs.sort(key=lambda r: r["seq"])
        for c in certs:
            if callable(is_green) and not is_green(c.get("run")):
                continue
            crev = _repos_map(c["repos"])
            if all(crev.get(repo) == rev
                   for repo, rev in _repos_map(landing["repos"]).items()):
                certified_by = c["id"]
                certified_at = c.get("at")
                break

    proms = [r for r in rows
             if isinstance(r, dict) and r.get("kind") == KIND_PROMOTION
             and isinstance(r.get("seq"), int) and ticket in r.get("tickets", [])]
    proms.sort(key=lambda r: r["seq"])
    delivered_in = proms[-1]["id"] if proms else None

    reverted_at = None
    withdrawn_at = None
    if delivered_in is not None:
        for rel in rows:
            if not isinstance(rel, dict) or rel.get("kind") != REL_KIND_WITHDRAWS:
                continue
            if rel.get("to") != ticket:
                continue
            wlanding = _ticket_landing(rows, rel.get("from"))
            if wlanding is None:
                raise WithdrawnTargetUnknown(
                    "withdrawn_target_unknown:%s" % rel.get("id"))
            wproms = [r for r in rows
                      if isinstance(r, dict) and r.get("kind") == KIND_PROMOTION
                      and rel.get("from") in r.get("tickets", [])
                      and isinstance(r.get("seq"), int)]
            if wproms:
                reverted_at = min(r.get("at") or 0 for r in wproms) or reverted_at
    # The ticket's OWN withdrawal face: the relation is the recorded
    # judgement, so it fires regardless of whether the withdrawing ticket
    # itself has a landing (that landing matters only to ``reverted_at``).
    for rel in rows:
        if not isinstance(rel, dict) or rel.get("kind") != REL_KIND_WITHDRAWS:
            continue
        if rel.get("to") != ticket or not dc._valid_at(rel.get("at")):
            continue
        at = rel["at"]
        if withdrawn_at is None or at < withdrawn_at:
            withdrawn_at = at

    superseded_by = None
    superseded_at = None
    for rel in rows:
        if not isinstance(rel, dict) or rel.get("kind") != REL_KIND_SUPERSEDES:
            continue
        if rel.get("to") != ticket or not _valid_str(rel.get("from")):
            continue
        at = rel.get("at") if dc._valid_at(rel.get("at")) else 0
        if (superseded_at is None or at > superseded_at
                or (at == superseded_at and _valid_str(rel.get("id"))
                    and (superseded_by is None or rel["id"] > superseded_by))):
            superseded_by = rel.get("from")
            superseded_at = rel.get("at") if at else None

    # The product's kind, read from what the ticket carries. A record that
    # is not a dict, or whose kind is not a known raw string, reads
    # ``unknown`` by name.
    product_kind = PRODUCT_KIND_UNKNOWN
    ended_by = None
    ended_at = None
    if isinstance(ticket_record, dict):
        raw_kind = ticket_record.get("kind")
        if isinstance(raw_kind, str):
            product_kind = TICKET_KIND_TO_PRODUCT.get(
                raw_kind, PRODUCT_KIND_UNKNOWN)
    record_at = ticket_record.get("at") if (
        isinstance(ticket_record, dict)
        and dc._valid_at(ticket_record.get("at"))) else None
    if product_kind == PRODUCT_KIND_REPORT:
        findings = ticket_record.get("findings")
        period = ticket_record.get("period")
        if isinstance(findings, list) and findings and _valid_str(period):
            ended_by = "findings"
            # The ticket's own moment when it carries one; otherwise the
            # stamped period cursor itself is the moment the record names.
            ended_at = record_at if record_at is not None else period
    elif product_kind == PRODUCT_KIND_VERIFICATION:
        if _valid_str(ticket_record.get("verdict")):
            ended_by, ended_at = "verdict", record_at
    elif product_kind == PRODUCT_KIND_CHANGE:
        if certified_by is not None:
            ended_by, ended_at = "certification", certified_at
        elif delivered_in is not None:
            ended_by, ended_at = "delivery", None

    # waiting stays the landing's own face — and only for a product whose
    # ending fact IS a landing (change, or a kind we cannot name, where a
    # landing genuinely awaits its certification). A report/verification
    # ticket is never "waiting since the landing".
    if landing is not None and certified_by is None and product_kind not in (
            PRODUCT_KIND_REPORT, PRODUCT_KIND_VERIFICATION):
        waiting_since = landing["at"]
    else:
        waiting_since = None

    if reverted_at is not None:
        ending = "reverted"
    elif superseded_by is not None:
        ending = "superseded"
    elif withdrawn_at is not None:
        ending = "withdrawn"
    elif ended_by is not None:
        ending = "ended"
    else:
        ending = "open"

    # The single cursor of the one ordering space (t261009-29): there is no
    # second file, so ``as_of`` carries the delivery ledger's max seq alone.
    d_seq = max([r.get("seq") for r in rows
                 if isinstance(r, dict) and isinstance(r.get("seq"), int)] or [0])
    return {
        "landed_at": list(landing["repos"]) if landing else None,
        "certified_by": certified_by,
        "delivered_in": delivered_in,
        "reverted_at": reverted_at,
        "withdrawn_at": withdrawn_at,
        "superseded_by": superseded_by,
        "superseded_at": superseded_at,
        "product_kind": product_kind,
        "ended_by": ended_by,
        "ended_at": ended_at,
        "ending": ending,
        "waiting_since": waiting_since,
        "as_of": {"delivery": d_seq},
    }


#: The fields ``compare_outcomes`` judges. ``as_of`` is deliberately NOT in
#: it: two views computed at different cursors legitimately differ in the
#: cursor alone, so the cursor is reported, never counted as drift.
OUTCOME_COMPARE_FIELDS = (
    "landed_at", "certified_by", "delivered_in", "reverted_at",
    "withdrawn_at", "superseded_by", "superseded_at",
    "product_kind", "ended_by", "ended_at", "ending", "waiting_since",
)


def compare_outcomes(baseline, rebuilt):
    """The rebuild-and-compare (goal 14): given a cached projection and a
    fresh rebuild, report whether they agree and NAME the field that
    disagrees when they do not — that is what makes "the projection is
    what is wrong" a checkable statement instead of a promise.

    Pure function over two views; touches no ledger. ``as_of`` cursors are
    returned beside the verdict (``baseline_as_of`` / ``rebuilt_as_of``)
    so the caller can tell a stale baseline from real drift, but a cursor
    difference alone is NOT a disagreement. An absent field and a ``None``
    field read as the same answer. Malformed input is refused by name.
    """
    for name, view in (("baseline", baseline), ("rebuilt", rebuilt)):
        if not isinstance(view, dict):
            raise PromoteError("outcome_not_object:%s" % name)
    differs_in = [f for f in OUTCOME_COMPARE_FIELDS
                  if baseline.get(f) != rebuilt.get(f)]
    return {
        "agrees": not differs_in,
        "differs_in": differs_in,
        "baseline_as_of": baseline.get("as_of"),
        "rebuilt_as_of": rebuilt.get("as_of"),
    }
