#!/usr/bin/env python3
"""sc_promotion_one_seq_space.py — the promotion (and the withdrawal
relations) live in the SAME ledger file and seq space as landings and
certifications: one ledger, one seq, no cross-file comparison
(t261009-29, the delivery-family single ordering space).

Run directly: python3 integration/t261009-29/sc_promotion_one_seq_space.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS
entry).

Grey-box L3, offline seconds, plain-dict rows over a real temp
delivery.jsonl, zero docker/Temporal/browser, never touches 3099/7233.

The user-perceivable contract this entry owns (developer L1 owns validator
matrices and per-field truth tables):

  A  ONE FILE, ONE SEQ: a promotion row and a withdraws relation row land
     in delivery.jsonl through the same shared append face — no sibling
     ledger file is created — and the seq values across landing →
     certification → promotion → relation are one strictly increasing
     sequence. "The landings after the previous certification" style
     questions are answerable ACROSS kinds by seq alone.

  B  THE PROMOTION KEEPS EVERY FIELD: the row read back FROM THE LEDGER
     FILE ON DISK (reader side — the writer's ok is not the evidence)
     carries certification, tickets, main_before / main_after per
     repository, signer, on_behalf_of, authority, at — and gains the seq
     the shared writer assigned.

  C  THE PROJECTION READS ONE SPACE: ticket_outcome takes ONE rows list;
     a ticket is reported delivered when its promotion sits in the shared
     space, and as_of is a single delivery cursor (no per-file cursor
     pair — the report no longer needs to say which comparisons cross
     files, because none do).

  D  THE GUARD READS THE SAME SPACE: a withdraws relation recorded in the
     one file still arms the promotion guard — re-introducing the
     withdrawn landing's patch identity refuses by name
     (withdrawn_patch_present:<rel-id>); the guard is not weakened by the
     merge.

Intent split: validator refusal matrices, migration order and the legacy
read-refusal face belong to sc_legacy_promotion_ledger_migration (sibling
entry) and developer L1; this entry owns the single-space journey (append
through one writer, read back from disk, project and guard across kinds).

Pre-implementation tree = FAIL named (TDD signal); green required at the
integration gate / merge. develop_promote / develop_certify not landed =
FAIL named, exit 1.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import develop_certify as dc  # noqa: E402
except Exception as exc:
    print("FAIL: develop_certify not landed (TDD signal, pre-implementation "
          "tree): %s" % exc)
    print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
    sys.exit(1)

try:
    import develop_promote as dp  # noqa: E402
except Exception as exc:
    print("FAIL: develop_promote not landed (TDD signal, pre-implementation "
          "tree): %s" % exc)
    print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
    sys.exit(1)

PASS = 0
FAIL = 0
NA = 0
TMPDIRS = []


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


def tmpdir(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    TMPDIRS.append(d)
    return d


def shaped(row):
    clean, why = dc.validate_row(row)
    if clean is None:
        raise AssertionError("fixture row refused by the store's own "
                             "validator: %s" % why)
    return clean


def landing(ticket, rev, at):
    return shaped({"kind": "landing", "id": "ldg-%s" % ticket,
                   "ticket": ticket, "line": "main", "actor": "dev",
                   "repos": [{"repo": "r", "revision": rev}], "at": at})


def certification(cid, ticket, rev, at):
    return shaped({"kind": "certification", "id": cid, "line": "main",
                   "repos": [{"repo": "r", "revision": rev}],
                   "run": "run-%s" % cid, "booked_red": "no",
                   "judged_by": "host", "at": at})


def main():
    led = os.path.join(tmpdir("sc_t26100929_one_space_"), "delivery.jsonl")

    # ---------- A. one file, one seq ----------
    section("A one writer, one file, one increasing seq across kinds")
    rev = "a" * 40
    dc.append_rows([landing("t-1", rev, 1000)], led)
    dc.append_rows([certification("cert-1", "t-1", rev, 2000)], led)
    prom = dp.build_promotion(
        "cert-1", "main", ["t-1"],
        main_before=[{"repo": "r", "revision": "b" * 40}],
        main_after=[{"repo": "r", "revision": rev}],
        signer="host", at_ms=3000, delivery_rows=dc.read_rows(led)[0])
    dc.append_rows([prom], led)
    # the withdrawing ticket carries its own landing, so the relation's
    # reverted_at path (which reads the withdrawing ticket's landing) is
    # resolvable — the fixture exercises the guard, not the unknown-target
    # refusal (that face is t261009-23's entry).
    dc.append_rows([landing("t-2", "c" * 40, 2500)], led)
    rel = dp.record_relation("withdraws", "t-2", "t-1", "host", "undo t-1",
                       {"what": "ticket", "ref": "t-1"})
    dc.append_rows([rel], led)

    ok(not os.path.exists(os.path.join(os.path.dirname(led),
                                       "promotion.jsonl")),
       "A1 no sibling promotion ledger file exists next to delivery.jsonl "
       "(the split is gone, not papered over)")
    rows, _cur = dc.read_rows(led)
    kinds = [r.get("kind") for r in rows]
    ok(kinds == ["landing", "certification", "promotion", "landing",
                 "withdraws"],
       "A2 all four kinds live in the one file in write order (%r)" % kinds)
    seqs = [r.get("seq") for r in rows]
    ok(all(isinstance(s, int) for s in seqs)
       and all(b > a for a, b in zip(seqs, seqs[1:])),
       "A3 the shared writer assigned one strictly increasing seq across "
       "kinds (%r)" % seqs)
    ok(rows[2]["seq"] > rows[1]["seq"] and rows[2]["seq"] < seqs[-1],
       "A4 the promotion's seq is comparable to landings and certifications "
       "by seq alone (the ordering question the doc promises)")

    # ---------- B. the promotion keeps every field, read from disk ----------
    section("B the promotion row on disk keeps its whole surface")
    on_disk = [r for r in rows if r.get("id") == prom["id"]]
    ok(len(on_disk) == 1, "B1 the promotion row reads back from "
       "delivery.jsonl on disk (reader side, not the return value)")
    p = on_disk[0]
    ok(p.get("certification") == "cert-1"
       and p.get("tickets") == ["t-1"]
       and p.get("main_before") == [{"repo": "r", "revision": "b" * 40}]
       and p.get("main_after") == [{"repo": "r", "revision": rev}]
       and p.get("signer") == "host"
       and p.get("at") == 3000
       and isinstance(p.get("seq"), int),
       "B2 certification, tickets, main_before/main_after, signer, at are "
       "all on the row, plus the shared writer's seq")

    # ---------- C. the projection reads one space ----------
    section("C ticket_outcome consumes ONE rows list")
    view = dp.ticket_outcome(rows, "t-1")
    ok(view.get("delivered_in") == prom["id"],
       "C1 a promotion in the shared space is the delivery the projection "
       "reports (delivered_in=%r)" % view.get("delivered_in"))
    as_of = view.get("as_of")
    ok(isinstance(as_of, dict) and set(as_of) == {"delivery"},
       "C2 as_of is a single delivery cursor — no per-file cursor pair "
       "remains (%r)" % as_of)
    ok(view.get("landed_at") == [{"repo": "r", "revision": rev}]
       and view.get("certified_by") == "cert-1",
       "C3 the three-stage reading survives the merge: landed_at and "
       "certified_by still answerable from the same list")

    # ---------- D. the guard reads the same space ----------
    section("D the withdrawal guard stays armed inside the one file")
    guard = dp.withdrawn_patch_ids(rows,
                                   lambda rev_, repo: "pid-t-1", "r")
    ok("pid-t-1" in guard,
       "D1 the relation row in the shared file arms the guard set (%r)"
       % (guard,))
    refused = None
    try:
        dp.check_withdrawn("t-1", rows, lambda rev_, repo: "pid-t-1", "r")
    except Exception as exc:
        refused = str(exc)
    ok(refused is not None and "withdrawn_patch_present" in refused,
       "D2 re-introducing the withdrawn landing's patch identity refuses "
       "by name (%r) — the merge did not hollow the guard" % refused)

    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
