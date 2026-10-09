#!/usr/bin/env python3
"""sc_t26100927_outcome_endings_kind_compare.py — the ticket-outcome projection
grows the three faces design goal 14 still owes: endings that are not
deliveries (withdrawn / superseded) coexisting with landed / certified /
delivered, the product's kind deciding which fact ends the ticket (never a
forever-"waiting" report or verification ticket), and a rebuild-and-compare
that can name the field where the projection disagrees with the facts
(t261009-27 spec items (1)-(5), develop-buffer goal 14).

Run directly:
python3 integration/t261009-27/sc_t26100927_outcome_endings_kind_compare.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, plain-dict ledger rows only (no git fixture, no
docker/Temporal/browser, never touches 3099/7233; nothing on disk is written).
Judged through the public faces develop_promote.ticket_outcome /
compare_outcomes / RELATION_KINDS — a contract-preserving refactor must stay
green; no assertion anchors on internal helpers or row order beyond what the
public view promises.

The user-perceivable contract this entry owns:

  A  ENDINGS THAT ARE NOT DELIVERIES (spec 1). A ticket that was delivered and
     later superseded reports BOTH faces at once (delivered_in AND
     superseded_by/superseded_at, the view naming which ending applies); a
     ticket whose landing was withdrawn and never delivered reports
     withdrawn_at (the relation's own moment) without needing a promotion; the
     three-stage reading (landed_at / certified_by / delivered_in /
     reverted_at) stays answerable for a ticket that landed, was delivered and
     was later withdrawn. Every ending field is derived — no new stored field
     appears anywhere.

  B  THE PRODUCT'S KIND (spec 2). The view carries the product's kind read
     from what the ticket actually carries: a real inspection-period ticket
     shape (kind "inspection", instance_id, period, findings) reads as a
     report product whose ending fact is its findings + stamped period, a
     verification ticket's ending fact is its verdict, a change ticket still
     ends through the delivery path, and an unreadable kind is reported as
     unknown BY NAME — never a silent default to change. A report or
     verification ticket is never reported waiting, even if a landing row
     exists for it: "waiting since the landing" is meaningless when the
     ending fact is not a landing — that is the collapse the four states
     exist to prevent.

  C  REBUILD-AND-COMPARE (spec 3). Given a cached view and a fresh rebuild
     over facts that moved, the comparison reports disagreement and names the
     exact fields that moved (the projection, not the facts, is what is
     wrong); two views that differ only in their as_of cursor agree; two
     identical views agree; malformed inputs are refused by name, never
     coerced.

  D  WHAT MUST NOT CHANGE (spec 4). The view still carries the four
     independent fields (no status enum), waiting_since keeps its own moment
     for a landed-not-yet-certified change ticket, as_of stays with both
     cursors, and the view still has no id, no seq and no at of its own.

  E  THE ORDERING-SPACE LIMIT, OBSERVED NOT HIDDEN (spec 5). delivered_in
     names a promotion-file id while landed_at / certified_by derive from the
     delivery ledger — the cross-file face the follow-up ticket must preserve;
     a promotion whose seq is lower than the delivery cursor still counts as
     the delivery (seq is never compared across the two files).

Intent split (no intent-level duplication): the three-stage distinctness
truth table and the withdrawal-guard propagation are owned by
t261009-23-sc_outcome_three_stages_withdrawal (kept green here only as the
spec-4 regression leg); the KI-192 inspection-period supersede-chain
adjudication is owned by t261003-03-sc_ki192_supersede_adjudication — this
entry owns the ticket-outcome projection's superseded ENDING derivation and
the compare face; relation vocabulary/corrections belong to the record-models
family. Projection field truth tables belong to developer L1
(server/engine/tests/, the t261009-27 ticket-outcome battery).

tier: the public develop_promote outcome/compare faces over plain-dict
ledgers (offline seam, no stage);
cost: seconds

Environment: develop_promote import failure = FAIL named, exit 1 (TDD signal,
pre-implementation tree); anything else failing prints FAIL named and exits 1.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import develop_promote as dp  # noqa: E402
except Exception as exc:
    print("FAIL: develop_promote not landed (TDD signal, pre-implementation "
          "tree): %s" % exc)
    print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
    sys.exit(1)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


LINE = "buffer-line"
REPO_NAME = "sandbar"
T = "t261009-27"


def landing(ticket, seq, at, rev="a1b2c3d4"):
    return {"kind": "landing", "id": "ldg-%d" % seq, "ticket": ticket,
            "line": LINE, "repos": [{"repo": REPO_NAME, "revision": rev}],
            "actor": "sc", "at": at, "seq": seq}


def cert(seq, at, rev="a1b2c3d4"):
    return {"kind": "certification", "id": "cert-%d" % seq, "line": LINE,
            "repos": [{"repo": REPO_NAME, "revision": rev}],
            "run": "run-%d" % seq, "booked_red": "none",
            "judged_by": "sc", "at": at, "seq": seq}


def promotion(seq, pid, tickets, at):
    return {"kind": "promotion", "id": pid, "line": LINE,
            "tickets": list(tickets), "signer": "host", "note": "sc",
            "at": at, "seq": seq}


def relation(kind, src, dst, rid, at, reason="sc relation"):
    return {"kind": kind, "id": rid, "from": src, "to": dst,
            "recorded_by": "integration", "reason": reason,
            "at": at, "v": "relation-v1"}


def view(drows, prows, ticket, ticket_record=None):
    if ticket_record is None:
        return dp.ticket_outcome(drows, prows, ticket)
    return dp.ticket_outcome(drows, prows, ticket, ticket_record=ticket_record)


# ---- A. endings that are not deliveries ------------------------------------

section("A. endings that are not deliveries coexist with the three stages")

drows_a = [landing(T, 1, 1000), cert(2, 2000)]
prows_a = [promotion(1, "prom-261009-01", [T], 3000),
           relation("supersedes", "t261009-26", T, "rel-261009-01", 4000,
                    "the follow-up ticket took this one's place")]
v = view(drows_a, prows_a, T)
ok(v.get("landed_at") and v.get("certified_by") and v.get("delivered_in"),
   "A1 delivered face intact: landed/certified/delivered all still set")
ok(v.get("superseded_by") == "t261009-26" and v.get("superseded_at") == 4000,
   "A1 superseded face present beside delivery: superseded_by/at derived "
   "from the supersedes relation")
ok("ending" in v, "A1 the view names which ending applies (summary field)")

drows_w = [landing(T, 1, 1000)]
prows_w = [relation("withdraws", "t261009-28", T, "rel-261009-02", 5000,
                    "wrong approach, withdrawn")]
v = view(drows_w, prows_w, T)
ok(v.get("withdrawn_at") == 5000,
   "A2 withdrawn_at set from the relation's own moment — no promotion "
   "needed (withdrawn and never delivered)")
ok(v.get("delivered_in") is None and v.get("reverted_at") is None,
   "A2 withdrawn-never-delivered is not reported delivered or reverted")
ok(v.get("ending") == "withdrawn",
   "A2 the ending face names withdrawn")

drows_r = [landing(T, 1, 1000), cert(2, 2000),
           landing("t261009-28", 3, 4000, rev="9c8b7a6d")]
prows_r = [promotion(1, "prom-261009-01", [T], 3000),
           promotion(2, "prom-261009-02", ["t261009-28"], 6000),
           relation("withdraws", "t261009-28", T, "rel-261009-03", 5000,
                    "revert of the delivered change")]
v = view(drows_r, prows_r, T)
ok(all(v.get(f) for f in ("landed_at", "certified_by", "delivered_in")),
   "A3 three-stage reading survives: landed/certified/delivered all still "
   "answerable after the withdrawal")
ok(v.get("reverted_at"), "A3 reverted_at still derived for the withdrawn "
   "landing whose undo was delivered")

# ---- B. the product's kind --------------------------------------------------

section("B. the product's kind decides which fact ends the ticket")

report_ticket = {"kind": "inspection", "instance_id": "docs-sync",
                 "period": "20261010", "at": 8000,
                 "findings": [{"id": "f1", "severity": "medium"}]}
drows_b = [landing(T, 1, 1000)]  # even a landing row must not mean waiting
v = view(drows_b, [], T, ticket_record=report_ticket)
ok(v.get("product_kind") == "report",
   "B1 a real inspection-period ticket shape (kind inspection) reads as a "
   "report product, read from what the ticket carries")
ok(v.get("ended_by") == "findings" and v.get("ended_at"),
   "B1 a report ticket with findings and a stamped period is ENDED — "
   "ended_by names the fact")
ok(v.get("waiting_since") is None,
   "B1 a report ticket is never reported waiting — not even with a landing "
   "row (the forever-waiting collapse is prevented)")

unended_report = {"kind": "inspection", "instance_id": "docs-sync",
                  "period": "20261010", "findings": []}
v = view([], [], T, ticket_record=unended_report)
ok(v.get("ended_at") is None and v.get("waiting_since") is None,
   "B1 a report ticket with no findings yet is neither ended nor waiting — "
   "it is open, not stuck")

verdict_ticket = {"kind": "verification", "verdict": "pass", "at": 7000}
v = view([], [], T, ticket_record=verdict_ticket)
ok(v.get("product_kind") == "verification" and v.get("ended_by") == "verdict"
   and v.get("ended_at") == 7000,
   "B2 a verification ticket ends when its verdict is recorded, ended_at "
   "from the verdict's own moment")

v = view([], [], T, ticket_record=None)
ok(v.get("product_kind") == "unknown",
   "B3 no ticket record: the kind is unknown BY NAME, never silently change")
ok(v.get("waiting_since") is None and v.get("landed_at") is None,
   "B3 an unknown-kind ticket with no landing is not reported waiting either")

v = view(drows_b, [], T, ticket_record={"kind": 42})
ok(v.get("product_kind") == "unknown",
   "B3 a non-string kind is unknown by name, not coerced")

change_ticket = {"kind": "chore"}
drows_c = [landing(T, 1, 1000)]
v = view(drows_c, [], T, ticket_record=change_ticket)
ok(v.get("product_kind") == "change" and v.get("waiting_since") == 1000,
   "B4 a change ticket still ends through the delivery path: waiting since "
   "its landing while no certification covers it")
v = view(drows_c + [cert(2, 2000)], [], T, ticket_record=change_ticket)
ok(v.get("certified_by") and v.get("waiting_since") is None,
   "B4 the covering certification ends a change ticket's wait (goal 14)")

# ---- C. rebuild-and-compare --------------------------------------------------

section("C. rebuild-and-compare names the field that moved")

drows_c1 = [landing(T, 1, 1000)]
baseline = view(drows_c1, [], T)
drows_c2 = drows_c1 + [cert(2, 2000)]
prows_c2 = [promotion(1, "prom-261009-01", [T], 3000)]
rebuilt = view(drows_c2, prows_c2, T)
try:
    cmp = dp.compare_outcomes(baseline, rebuilt)
    ok(cmp.get("agrees") is False,
       "C1 a stale cached view against a fresh rebuild reports disagreement")
    moved = set(cmp.get("differs_in") or [])
    ok({"certified_by", "delivered_in"} <= moved,
       "C1 the comparison names the exact fields that moved "
       "(got: %s)" % sorted(moved))
    ok("baseline_as_of" in cmp and "rebuilt_as_of" in cmp,
       "C1 both cursors are reported so the reader can tell the baseline is "
       "behind (as_of present on the comparison)")
except AttributeError:
    ok(False, "C1 compare_outcomes not landed (TDD signal)")

same = view(drows_c1, [], T)
cmp = dp.compare_outcomes(same, dict(same))
ok(cmp.get("agrees") is True and not (cmp.get("differs_in") or []),
   "C2 two identical views agree with no differing fields")

stale_only = dict(same)
stale_only["as_of"] = {"delivery": 99, "promotion": 0}
cmp = dp.compare_outcomes(stale_only, same)
ok(cmp.get("agrees") is True,
   "C2 an as_of-only cursor drift is reported, not counted as disagreement "
   "(the caller decides staleness)")

refused = False
try:
    dp.compare_outcomes("not-a-view", same)
except Exception as exc:
    refused = "outcome" in str(exc).lower() or "view" in str(exc).lower()
ok(refused, "C3 a malformed baseline is refused by name, never coerced")

# ---- D. what must not change -------------------------------------------------

section("D. the projection's own invariants hold on every face")

for label, vv in (("D1 endings face", view(drows_a, prows_a, T)),
                  ("D1 kind face", view([], [], T,
                                        ticket_record=report_ticket)),
                  ("D1 compare face", baseline)):
    ok(not ({"id", "seq", "at"} & set(vv)),
       "%s: no id, no seq, no at of its own" % label)
    ok(isinstance(vv.get("as_of"), dict)
       and set(vv["as_of"]) == {"delivery", "promotion"},
       "%s: the as_of cursor carries both files" % label)
    ok(all(f in vv for f in ("landed_at", "certified_by", "delivered_in",
                             "reverted_at", "waiting_since")),
       "%s: the four independent fields stay four (no status enum)" % label)

# ---- E. the ordering-space limit, observed ----------------------------------

section("E. cross-file delivery identity, seq never compared across files")

drows_e = [landing(T, 1, 1000), cert(2, 2000)]
prows_e = [promotion(1, "prom-261009-01", [T], 500)]
v = view(drows_e, prows_e, T)
ok(v.get("delivered_in") == "prom-261009-01",
   "E1 a promotion whose seq is below the delivery cursor still counts: "
   "delivered_in names the promotion-file id while landed_at/certified_by "
   "come from the delivery ledger — seq is never compared across the two "
   "files (the limit the follow-up ticket must preserve)")

# ---- summary ------------------------------------------------------------------

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
