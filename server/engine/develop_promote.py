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
import shared  # noqa: E402  (develop_dir / perkey roots)

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
                    delivery_rows=(), is_green=None, patch_id_fn=None,
                    tickets_contained_fn=None):
    """Build one promotion row, or raise PromotionRefused with a named
    reason. Every check answers a spec sentence:

    - a named certification that exists and is green (spec (b));
    - every ticket carried has a landing contained in the certified
      revision (the promotion delivers content that was proven);
    - NO candidate re-introduces a withdrawn patch (t261009-64): the
      landed guard (``check_withdrawn``) fires on the real builder. A hit
      refuses ``withdrawn_patch_present:<rel-id>:<ticket>:<patch-id>`` —
      which withdrawal relation, which candidate ticket, which patch
      identity. When the patch id cannot be recomputed to enrich the
      reason, the original guard refusal (relation id only) is re-raised,
      so the withdrawal diagnosis is never masked by the recompute. A
      ledger carrying any ``withdraws`` relation WITHOUT an injected
      ``patch_id_fn`` refuses ``withdrawn_guard_unavailable`` — the guard
      never silently shrinks; this deliberately over-refuses on
      withdrawal-bearing ledgers whose candidates do not overlap the
      withdrawal. A withdrawal-FREE ledger is byte-for-byte unaffected.
    - ``main_after`` equals the certified revision per repository (what
      main becomes is what was certified, nothing else);
    - signer present; delegation fields stand together (spec (a)).
    """
    has_withdrawals = any(isinstance(r, dict)
                          and r.get("kind") == REL_KIND_WITHDRAWS
                          for r in delivery_rows)
    if has_withdrawals and not callable(patch_id_fn):
        raise PromotionRefused("withdrawn_guard_unavailable")
    cert = check_certification(cert_id, delivery_rows, is_green=is_green)
    cert_repos = _repos_map(cert["repos"])
    for t in tickets or []:
        landing = _ticket_landing(delivery_rows, t)
        if landing is None:
            raise PromotionRefused("tickets_not_covered:%s" % t)
        lrev = _repos_map(landing["repos"])
        for repo, rev in lrev.items():
            carried = cert_repos.get(repo) == rev
            if not carried and tickets_contained_fn is not None:
                # 261015: the rule this function's own docstring states
                # ("a landing CONTAINED in the certified revision"), injected
                # by the caller that can do git work. Without the seam the
                # exact-equality rule stands, so every existing caller and
                # test keeps the previous semantics.
                carried = bool(tickets_contained_fn(rev, repo))
            if not carried:
                raise PromotionRefused("tickets_not_covered:%s" % t)
            if has_withdrawals:
                # t261009-64: the withdrawal guard fires HERE, on the real
                # builder (spec: the refusal must not live in a test-only
                # helper). check_withdrawn owns the guard semantics; this
                # face only enriches its refusal with the ticket and the
                # patch identity. A withdrawal-free ledger never reaches
                # this call, so the adapter (real git work) is never
                # consulted on the unaffected path. Cost note (review
                # cond. 2): the guard set is rebuilt per (ticket, repo)
                # call — O(tickets x repos) guard constructions, fine at
                # ledger scale; the seam for a future perf pass is hoisting
                # withdrawn_patch_ids out of the loop.
                try:
                    check_withdrawn(t, delivery_rows, patch_id_fn, repo)
                except PromotionRefused as exc:
                    if not str(exc).startswith("withdrawn_patch_present:"):
                        raise
                    rel_id = str(exc).split(":", 1)[1]
                    try:
                        pid = patch_id_fn(rev, repo)
                    except PatchIdUnavailable:
                        # review cond. 1: the recompute failure must not
                        # mask the withdrawal diagnosis — fall back to the
                        # original guard refusal (relation id only)
                        raise PromotionRefused(
                            "withdrawn_patch_present:%s" % rel_id) from exc
                    raise PromotionRefused(
                        "withdrawn_patch_present:%s:%s:%s"
                        % (rel_id, t, pid)) from exc
    if (on_behalf_of is None) != (authority is None):
        raise PromotionRefused("delegation_incomplete")
    if not _valid_str(signer):
        raise PromotionRefused("promotion_missing_signer")
    after = _repos_map(main_after)
    if after != cert_repos:
        raise PromotionRefused("main_after_not_certified_revision")
    # t261009-66: the promotion NAMES the remedy work that rode with it —
    # the current ``repairs`` AND ``withdraws`` relations recorded BY the
    # covered tickets, read back from ``delivery_rows`` (the ledger rows,
    # never a return value). Withdrawals ride under the same field name:
    # withdrawal is work too (record-models: "withdrawal is work, not a
    # record"), so the entry carries its ``kind`` and the name ``repairs``
    # reads as "remedy relations" here. Direction logic goes through the
    # ONE reader (``relations_of`` as_actor side) — no second matching
    # implementation. Legacy rows without the field stay valid; a new row
    # always carries it (empty list when none) for a stable shape.
    named, repairs = set(), []
    for t in dict.fromkeys(tickets or []):
        face = dc.relations_of(delivery_rows, t)
        for kind in (REL_KIND_REPAIRS, REL_KIND_WITHDRAWS):
            for entry in face["as_actor"][kind]:
                if entry["id"] in named:
                    continue
                named.add(entry["id"])
                repairs.append({"id": entry["id"], "from": entry["from"],
                                "to": entry["to"], "kind": entry["kind"]})
    row = {
        "kind": KIND_PROMOTION,
        "id": dc.mint_id("prom", at_ms=at_ms),
        "certification": cert_id,
        "line": line,
        "repos": list(cert["repos"]),
        "tickets": list(tickets),
        "main_before": list(main_before),
        "main_after": list(main_after),
        "repairs": repairs,
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
                    evidence, supersedes_relation=None, at_ms=None):
    """Build one relation row (record-models §B shape: the ``kind`` FIELD is
    the relation kind, the ``rel-`` prefix is the family). This is how a
    withdrawal is recorded — as work and a relation, NEVER as a revert
    record type (spec (e)).

    ``evidence`` (t261009-62) is the row's declared-shape statement of WHAT
    the attribution is about: ``{"what": <one of dc.RELATION_EVIDENCE_WHATS>,
    "ref": "<non-empty string>"}``. A row without usable evidence, or one
    recorded by the ticket that benefits (recorder ``ticket:<from>``), is
    refused by name through the shared validator — never silently accepted.

    ``supersedes_relation`` (t261009-62) corrects a wrong relation by a NEW
    row: name the old row's id and the older row drops out of
    ``current_relations`` while staying byte-identical in the file.
    """
    row = {
        "id": dc.mint_id("rel", at_ms=at_ms),
        "from": from_ticket,
        "to": to_ticket,
        "kind": rel_kind,
        "recorded_by": recorded_by,
        "reason": reason,
        "evidence": evidence,
        "at": int(at_ms) if at_ms is not None else int(time.time() * 1000),
    }
    if supersedes_relation is not None:
        row["supersedes_relation"] = supersedes_relation
    clean, why = validate_row(row)
    if clean is None:
        raise PromoteError(why)
    return clean


def current_relations(rows):
    """The current-state view of the relation ledger (t261009-62): every
    relation row EXCEPT the ones another row supersedes. Corrections are
    new rows, never edits — so a reader that answers "what are the current
    relations" must read through the ``supersedes_relation`` linkage, not
    trust first records.

    Deliberately NOT ``validate_row``: this filter decides only (a) is the
    line a parseable dict carrying a ``rel-`` id and (b) is it superseded
    by another such row. Legacy rows written before ``evidence`` existed
    stay visible here — a write-time rule going silent at read time would
    be the writer-says-ok/reader-can't-see failure class. A dangling
    ``supersedes_relation`` (naming an id no row carries) never matches, so
    the correcting row simply stays current. A supersedes cycle (A names B,
    B names A) makes BOTH non-current: the file's honest state is that
    neither claim stands, and the chain is still readable in the raw rows.
    """
    rels = [r for r in rows
            if isinstance(r, dict) and isinstance(r.get("id"), str)
            and r["id"].startswith("rel-")]
    superseded = set()
    for r in rels:
        target = r.get("supersedes_relation")
        if isinstance(target, str) and target.startswith("rel-"):
            superseded.add(target)
    return [r for r in rels if r["id"] not in superseded]


#: The ONE relation reader (t261009-66), re-exported as the same object so
#: promote-side faces call one name and no second direction implementation
#: appears (import direction: promote -> certify — the implementation lives
#: in develop_certify, beside the ledger kinds it reads).
relations_of = dc.relations_of


# ---- the driver (t261013: the human-signed act, wired) -----------------------

def _is_green_reader(project):
    """The run-verdict reader: the cited run's verdict read straight from the
    per-project scenario-runs JSONL (stdlib only — the engine never imports
    the integration support layer, develop_certify's rule). Unknown or
    unreadable -> not green, never guessed."""
    import json as _json
    runs_file = (shared.perkey_projects_root() / str(project) / "ledger"
                 / "scenario-runs.jsonl")

    def _is_green(run_id):
        try:
            with open(str(runs_file), encoding="utf-8") as fh:
                for ln in fh:
                    s = ln.strip()
                    if not s:
                        continue
                    try:
                        obj = _json.loads(s)
                    except ValueError:
                        continue
                    if isinstance(obj, dict) and obj.get("id") == run_id:
                        return obj.get("verdict") == "green"
        except Exception:
            return None
        return None
    return _is_green


def _latest_green_cert(rows, line_id, project):
    """The line's latest certification whose cited run reads green. None ->
    the caller refuses (a promotion never rests on a red or unreadable cert)."""
    is_green = _is_green_reader(project)
    certs = [r for r in rows if isinstance(r, dict)
             and r.get("kind") == dc.KIND_CERT and r.get("line") == line_id]
    certs.sort(key=lambda r: r.get("seq") or 0)
    for cert in reversed(certs):
        if is_green(cert.get("run")):
            return cert
    return None


def _covered_tickets(rows, line_id, cert_repos, contained_fn=None):
    """The tickets whose landings sit inside the certified revision — what a
    promotion delivers. Derived from the records' order, never stored.

    ``contained_fn(rev, repo) -> bool`` is the general rule the builder's own
    docstring states ("every ticket carried has a landing CONTAINED in the
    certified revision"). Without it the v1 exact-equality rule stands (a
    certified revision is itself a landing revision, so exactly that landing
    is carried) — byte-for-byte the previous behaviour, which is why the
    default is unchanged. With it, a certification of the line's tip carries
    every landing its ancestry contains and main does not have yet — the shape
    a buffer line reaches once it has been advanced past its last landing
    (261015: main merged into the line, all eight of the line's landings
    still undelivered).
    """
    out = []
    for r in rows:
        if not (isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING
                and r.get("line") == line_id):
            continue
        t = r.get("ticket")
        lrev = {x["repo"]: x["revision"] for x in r.get("repos", [])
                if isinstance(x, dict)}
        if not lrev:
            continue
        if contained_fn is not None:
            carried = all(contained_fn(v, k) for k, v in lrev.items())
        else:
            # carried = its landing revision IS the certified revision per repo
            # (build_promotion enforces the same rule on the same rows)
            carried = all(cert_repos.get(k) == v for k, v in lrev.items())
        if carried and isinstance(t, str) and t.strip() and t not in out:
            out.append(t)
    return out


def promote_buffer(project, line_id, signer, authority=None, on_behalf_of=None,
                   note=None, at_ms=None, repo_paths=None):
    """The human-signed promotion act (design goal 11): move main to the
    line's latest GREEN certified revision (fast-forward only), then record.

    The order is deliberate: VALIDATE everything (the cert is green, every
    covered ticket landed inside the certified revision, no withdrawn patch
    re-enters, fast-forward is possible) BEFORE touching any ref. A refusal
    raises PromotionRefused with a named reason and moves nothing. The act
    itself moves the ref via update-ref (works from any worktree) and then,
    when the main checkout sits on main with a clean tree, follows with a
    ``merge --ff-only`` there so the working tree tracks the new tip; a dirty
    or not-on-main checkout is named in the record's note, never forced.

    Returns the recorded promotion row."""
    import develop_line as dl  # local: promote -> certify -> (line decl)
    if not _valid_str(signer):
        raise PromotionRefused("promotion_missing_signer")
    rows, bad = dc.read_rows(dc.ledger_path(project))
    if bad:
        raise PromotionRefused("delivery_ledger_malformed:%d" % len(bad))
    cert = _latest_green_cert(rows, line_id, project)
    if cert is None:
        raise PromotionRefused("no_green_certification:%s" % line_id)
    line = dl.load_lines(project).get(line_id)
    if line is None:
        raise PromotionRefused("line_not_declared:%s" % line_id)
    cert_repos = _repos_map(cert["repos"])

    has_withdrawals = any(isinstance(r, dict)
                          and r.get("kind") == REL_KIND_WITHDRAWS
                          for r in rows)

    main_before, main_after = [], []
    for repo_meta in line.repositories:
        name = repo_meta.name
        repo = (repo_paths or {}).get(name)
        if repo is None:
            # the line worktree is a checkout of the shared repository —
            # ref moves work from it (update-ref needs no checkout state)
            repo = shared.develop_dir(project) / "wt" / name
        repo = Path(repo)
        crev = cert_repos.get(name)
        if not crev:
            raise PromotionRefused("cert_missing_repo:%s" % name)
        cur = _git(["rev-parse", "--verify", "refs/heads/main"], repo)
        if cur.returncode != 0:
            raise PromotionRefused("main_unresolvable:%s" % name)
        cur = cur.stdout.strip()
        mb = _git(["merge-base", "refs/heads/main", crev], repo)
        if mb.returncode != 0 or mb.stdout.strip() != cur:
            raise PromotionRefused(
                "promotion_not_fast_forward:%s" % name)
        main_before.append({"repo": name, "revision": cur})
        main_after.append({"repo": name, "revision": crev})

    def _pid_fn(rev, repo_name):
        return patch_id(rev, (repo_paths or {}).get(repo_name)
                        or shared.develop_dir(project) / "wt" / repo_name)

    # 261015: what this promotion delivers is every landing the certified
    # revision CONTAINS that main does not carry yet. The v1 exact-equality
    # rule only ever carried the landing sitting exactly on the certified
    # revision, so a line advanced past its last landing (a merge, a fix)
    # could not be promoted at all: its tip was certified but carried nothing.
    main_before_map = _repos_map(main_before)

    def _contained_fn(rev, repo_name, _paths=repo_paths, _cert=cert_repos,
                      _main=main_before_map):
        path = (_paths or {}).get(repo_name) \
            or shared.develop_dir(project) / "wt" / repo_name
        cert_rev = _cert.get(repo_name)
        main_rev = _main.get(repo_name)
        if not cert_rev or not main_rev:
            return False
        if _git(["merge-base", "--is-ancestor", rev, cert_rev],
                path).returncode != 0:
            return False
        # already inside main (delivered by an earlier promotion): not carried
        # again — a promotion row names the tickets it delivers, and a repeat
        # would claim work main already had.
        return _git(["merge-base", "--is-ancestor", rev, main_rev],
                    path).returncode != 0

    tickets = _covered_tickets(rows, line_id, cert_repos,
                               contained_fn=_contained_fn)

    row = build_promotion(
        cert["id"], line_id, tickets, main_before, main_after, signer,
        on_behalf_of=on_behalf_of, authority=authority, note=note,
        at_ms=at_ms, delivery_rows=rows, is_green=_is_green_reader(project),
        patch_id_fn=_pid_fn if has_withdrawals else None,
        tickets_contained_fn=_contained_fn)
    # validated — now the act, per repo. When the main checkout sits on main
    # with a clean tree, ONE fast-forward merge moves ref AND worktree together
    # (update-ref would strand the worktree behind the moved ref); otherwise
    # only the ref moves (update-ref works from any worktree) and the stale
    # worktree is named in the record, never forced.
    sync_notes = []
    for repo_meta in line.repositories:
        name = repo_meta.name
        repo = Path((repo_paths or {}).get(name)
                    or shared.develop_dir(project) / "wt" / name)
        crev = cert_repos[name]
        # 261015: the line is a LINKED worktree of the main repository
        # (.git/worktrees/<name>), so --absolute-git-dir names the worktree's
        # private git dir and its parent is NOT a work tree: the fast-forward
        # died with "main_ff_failed: ... this operation must be run in a work
        # tree" and the promotion could not complete at all (live catch, the
        # first promotion attempt of the merged line). The COMMON git dir's
        # parent is the main checkout on every layout — plain checkout and
        # linked worktree alike — and is the form this repository already uses
        # elsewhere (git rev-parse --path-format=absolute --git-common-dir).
        common = _git(["rev-parse", "--path-format=absolute",
                       "--git-common-dir"], repo)
        main_co = Path(common.stdout.strip()).parent if common.returncode == 0 \
            else None
        synced_inplace = False
        if main_co is not None:
            cur_br = _git(["rev-parse", "--abbrev-ref", "HEAD"], main_co)
            dirty = _git(["status", "--porcelain"], main_co)
            if cur_br.returncode == 0 and cur_br.stdout.strip() == "main" \
                    and not (dirty.stdout or "").strip():
                m = _git(["merge", "--ff-only", crev], main_co)
                if m.returncode == 0:
                    synced_inplace = True
                else:
                    raise PromoteError("main_ff_failed:%s:%s"
                                       % (name, (m.stderr or "")[-200:]))
        if not synced_inplace:
            u = _git(["update-ref", "refs/heads/main", crev], repo)
            if u.returncode != 0:
                raise PromoteError("main_ref_move_failed:%s:%s"
                                   % (name, (u.stderr or "")[-200:]))
            sync_notes.append("%s main checkout not on a clean main — the ref "
                              "moved; the operator reconciles the worktree"
                              % name)
    res = record_promotion(row, dc.ledger_path(project))
    if res["written"] != 1:
        raise PromoteError("promotion_append_rejected:%r" % (res["rejected"],))
    if sync_notes:
        row["worktree_sync_notes"] = sync_notes
    return row


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
        rel_id = row.get("id")
        # t261009-64 incidental robustness fix: a row carrying the withdraws
        # kind but no usable rel- id used to crash with a bare KeyError —
        # a malformed withdrawal claim refuses loudly instead
        if not (isinstance(rel_id, str) and rel_id.startswith("rel-")):
            raise WithdrawnTargetUnknown(
                "withdrawn_relation_id_invalid:%r" % (rel_id,))
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


# ---- the repair readers (t261009-63) ----------------------------------------

def repairing_relations(rows, from_ticket):
    """The CURRENT ``repairs`` relations recorded BY ``from_ticket``
    (t261009-63) — the remedy side of the repair relation, read from the
    one ledger list. A SELECTOR, not a validator: it filters by kind,
    ``from`` and the ``current_relations`` correction linkage, and returns
    those raw rows. Consumers re-check the fields they use (``may_land``
    re-validates in full — the judge never trusts a helper's filter;
    ``ticket_outcome`` checks ``at``/``id`` as it selects)."""
    return [r for r in current_relations(rows)
            if r.get("kind") == REL_KIND_REPAIRS
            and r.get("from") == from_ticket]


def _patch_named(rel):
    """Does this relation name a patch identity via its evidence? (t261009-63:
    the ``repaired_unresolved`` bucket is only honest for relations whose
    target is a patch identity — a ticket- or landing-named relation that
    credits nobody is simply about someone else, never a gap to report.)"""
    ev = rel.get("evidence")
    return isinstance(ev, dict) and ev.get("what") == "patch_id" \
        and isinstance(ev.get("ref"), str) and ev["ref"].strip() != ""


def _repair_credit(rows, ticket, patch_ids):
    """The repaired side of the relation (t261009-63): who repaired the
    ticket/landing of ``ticket``. A current ``repairs`` relation credits
    ``ticket`` through ANY of its three target forms — ``to`` equal to the
    ticket; ``to`` a ``ldg-`` landing id whose landing row names the
    ticket; or a patch identity (``to``/evidence ref) matched against the
    caller-supplied ``patch_ids={landing_id: pid}`` map, inverted: a pid
    of a landing whose ``ticket`` is the credited one. Without the map a
    patch-id-named relation is NEVER a silent nothing: it lands in
    ``repaired_unresolved`` so the gap stays visible, never guessed.
    Selection mirrors the ``superseded_by`` loop exactly (non-dict rows
    and rows with an unusable ``from``/``id`` skipped; an invalid ``at``
    still wins with a None timestamp — the honest timestamp face of a
    recorded repair)."""
    landings = {}
    by_pid = {}
    if isinstance(patch_ids, dict):
        for r in rows:
            if isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING \
                    and isinstance(r.get("ticket"), str):
                landings[r.get("id")] = r
                pid = patch_ids.get(r.get("id"))
                if isinstance(pid, str) and pid:
                    by_pid[pid] = r["ticket"]
    else:
        for r in rows:
            if isinstance(r, dict) and r.get("kind") == dc.KIND_LANDING \
                    and isinstance(r.get("id"), str):
                landings[r.get("id")] = r

    def _credits(rel):
        to = rel.get("to")
        if to == ticket:
            return True
        if isinstance(to, str) and to.startswith("ldg-"):
            landing = landings.get(to)
            return landing is not None and landing.get("ticket") == ticket
        refs = []
        ev = rel.get("evidence")
        if isinstance(ev, dict) and ev.get("what") == "patch_id" \
                and isinstance(ev.get("ref"), str):
            refs.append(ev["ref"])
        if isinstance(to, str):
            refs.append(to)
        return any(by_pid.get(ref) == ticket for ref in refs)

    repaired_by = None
    repaired_at = None
    # The winning relation's OWN id: the at-tie must compare id against id
    # (arbitration t261009-63 gen1 — comparing against ``repaired_by``, the
    # ticket NAME, made the tie-break order-dependent, since ``rel-…`` sorts
    # before any ticket id).
    repaired_rel_id = None
    unresolved = []
    for rel in current_relations(rows):
        if rel.get("kind") != REL_KIND_REPAIRS:
            continue
        if not _valid_str(rel.get("from")):
            continue
        if not _credits(rel):
            if not isinstance(patch_ids, dict) and _patch_named(rel):
                unresolved.append(rel.get("id"))
            continue
        at = rel.get("at") if dc._valid_at(rel.get("at")) else 0
        if (repaired_at is None or at > repaired_at
                or (at == repaired_at and _valid_str(rel.get("id"))
                    and (repaired_rel_id is None
                         or rel["id"] > repaired_rel_id))):
            repaired_by = rel.get("from")
            repaired_at = rel["at"] if at else None
            repaired_rel_id = rel.get("id")
    return repaired_by, repaired_at, unresolved


# ---- the outcome projection (derived only; three stages stay distinct) ------

def ticket_outcome(rows, ticket, is_green=None, ticket_record=None,
                   patch_ids=None):
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
    - ``repaired_by`` / ``repaired_at`` / ``repaired_unresolved``
      (t261009-63): the newest current ``repairs`` relation that credits
      this ticket (relation ``at``, then relation id, break ties; an
      invalid ``at`` still wins with a None timestamp — the honest face of
      a recorded repair). A relation credits the ticket through ANY of its
      three target forms: ``to`` equal to the ticket; ``to`` a ``ldg-``
      landing id whose landing row names the ticket; or a patch identity
      matched against the explicit ``patch_ids={landing_id: pid}`` input.
      Without the map a patch-id-named relation is recorded in
      ``repaired_unresolved`` (its id) instead of being silently dropped —
      the gap stays visible, never guessed. A repair is a CAUSE fact, not
      an ending: it never changes ``ending``.
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
            # 261016 ruling (rule C): ORDER decides, revision identity does not.
            # The per-repo equality that used to sit here was the "residual
            # non-head divergence" t261011-23 registered as a named gap: only the
            # range's head landing could ever equal the certified revision, so
            # every earlier landing read as uncertified forever — the same defect
            # the wait face's release rule fixes. A green certification recorded
            # after the landing is a verdict on a line state that contains it.
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

    # The repaired side (t261009-63): who repaired this ticket/landing,
    # derived from current ``repairs`` relations. A cause fact beside the
    # endings — never an ending of its own; ``repaired_unresolved`` names
    # the patch-id relations the caller's map could not place.
    repaired_by, repaired_at, repaired_unresolved = _repair_credit(
        rows, ticket, patch_ids)

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
        "repaired_by": repaired_by,
        "repaired_at": repaired_at,
        "repaired_unresolved": repaired_unresolved,
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
    "repaired_by", "repaired_at", "repaired_unresolved",
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
