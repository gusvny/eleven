#!/usr/bin/env python3
"""sc_t26100966_relations_reader.py — a ticket's relations are readable in
BOTH directions from the one stored side, and the promotion record names the
repairs (and withdrawals) it contains (ticket t261009-66, host order 261009
P2-d, docs/design/ticket-relations-v1.md: "One direction is stored; the other
side is derived", "Not storing both directions as two rows", and "the
promotion record names both the tickets it covers and the repairs it
contains").

Run directly:
python3 integration/t261009-66/sc_t26100966_relations_reader.py
(cwd = repo root).

Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
3099/7233. Every ledger is a real temp file written through the engine's own
writer (record_relation + append_rows); every proof is read back FROM DISK
(read_rows), never from a return value. The real store is never written.

The user-perceivable contract this entry owns (t261009-66 spec (1)(2)(3)):

  A  ONE DECLARED READER ANSWERS BOTH DIRECTIONS — asked about a ticket, it
     reports what that ticket repairs/withdraws/supersedes (the stored, acting
     side) AND what repaired/withdrew/superseded it (the derived, benefited
     side), with the derived side labelled as derived; the answer comes from
     the ledger file on disk, and READING writes nothing back (no second
     stored row is ever created — byte-identical file after the read). All
     three target naming forms resolve on the benefited side (landing id,
     ticket id, patch identity via the caller-supplied explicit map); a
     patch-id-named relation asked about WITHOUT the map stays VISIBLE in an
     unresolved bucket naming the relation id — a gap on the record, never a
     silent drop, never a guess.

  B  THE READER IS CORRECTION-AWARE — a superseded (corrected) relation
     appears on NEITHER side of the answer; the correcting row does. A
     corrected relation must never present itself as current (spec (3)).

  C  ONE IMPLEMENTATION, NOT TWO — the reader importable from
     develop_promote IS the reader defined in develop_certify (the same
     object), so no consumer can grow a second direction-matching logic; and
     the derived answer mirrors the stored answer for the same pair (the same
     relation ids on both views).

  D  THE PROMOTION RECORD NAMES ITS REPAIRS — a promotion built over a real
     ledger read back from disk carries a `repairs` field naming the current
     repairs AND withdrawals relations recorded by the tickets it covers
     (each entry citing the rel- id, its kind, from and to); repairs by
     tickets it does NOT cover are not named; a promotion over a ledger with
     no relations keeps the field as an empty list (stable row shape); a
     legacy promotion row written before the field existed still validates
     (additive-only), and a hand-written row carrying a malformed repairs
     field is refused by name — the naming field is validated, never
     trusted. The promotion row itself is proven from the FILE (appended and
     read back), not from the builder's return value.

Intent split: the relation ROW contract (evidence shape, recorder
entitlement, correction mechanics) belongs to t261009-62; the freeze
exemption consumer and the repaired-side outcome face belong to t261009-63;
the withdrawal wiring consumer belongs to t261009-64; ticket_outcome's
per-field reading is pre-existing and its refactor is declared debt — never
re-asserted here. This entry owns the two-direction READ face and the
promotion naming face only.

Environment: engine tree absent = ENV_FAIL exit 2. Pre-implementation tree
red = FAIL named (TDD signal); green required at the integration gate/merge.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import develop_certify as dc  # noqa: E402
    import develop_promote as dp  # noqa: E402
except Exception as exc:
    print("ENV_FAIL: engine modules unimportable (engine tree absent): %s"
          % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

PASS = 0
FAIL = 0
TMPDIRS = []

EV = {"what": "revision", "ref": "a" * 40}
LINE = "main"
REPO_A = "sandbar"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def tmpdir(tag):
    d = tempfile.mkdtemp(prefix=tag)
    TMPDIRS.append(d)
    return d


def rel(kind, from_t, to_t, at, supersedes=None, recorded_by="host",
        reason="attribution on the record", evidence=EV):
    return dp.record_relation(kind, from_ticket=from_t, to_ticket=to_t,
                              recorded_by=recorded_by, reason=reason,
                              evidence=evidence, supersedes_relation=supersedes,
                              at_ms=at)


def landing_row(ticket, at, ldg_id, revision="rev1111"):
    return {"kind": dc.KIND_LANDING, "id": ldg_id, "ticket": ticket,
            "line": LINE, "actor": ticket, "at": at,
            "repos": [{"repo": REPO_A, "revision": revision}]}


def cert_row(at, cert_id, revision="rev1111"):
    return {"kind": dc.KIND_CERT, "id": cert_id, "line": LINE,
            "run": "run-1", "booked_red": "no", "judged_by": "patrol",
            "at": at,
            "repos": [{"repo": REPO_A, "revision": revision}]}


def reader():
    """Capability discovery by contract name: the declared reader. A missing
    capability is a named FAIL (TDD signal), never an import crash."""
    fn = getattr(dc, "relations_of", None)
    if fn is None:
        ok(False, "PRE dc.relations_of exists (the declared two-direction "
                  "reader is in the tree)")
        return None
    ok(True, "PRE dc.relations_of exists")
    return fn


def disk_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def main():
    rels = reader()
    if rels is None:
        print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
        sys.exit(1)

    # ---------- A. both directions from the one stored side, from disk ------
    d = tmpdir("sc_t26100966_a_")
    path = os.path.join(d, "delivery.jsonl")
    fix, red = "t-fix", "t-red"
    r1 = rel(dc.REL_KIND_REPAIRS, fix, red, 1791510000001)
    r2 = rel(dc.REL_KIND_WITHDRAWS, fix, red, 1791510000002)
    dp.append_rows([landing_row(red, 1791510000000, "ldg-red"), r1, r2], path)
    rows, bad = dc.read_rows(path)
    ok(not bad and len(rows) == 3, "A0 the real temp ledger holds the three "
                                   "rows and reads back clean")
    before = disk_bytes(path)

    ans = rels(rows, fix)
    act = ans.get("as_actor") or {}
    ok(any(e.get("id") == r1["id"] for e in act.get("repairs", [])),
       "A1 the ACTING side answers what the ticket repairs (stored "
       "direction, rel id named)")
    ok(any(e.get("id") == r2["id"] for e in act.get("withdraws", [])),
       "A2 the acting side answers what the ticket withdraws")

    ans_red = rels(rows, red)
    ben = ans_red.get("as_benefited") or {}
    ok(any(e.get("id") == r1["id"] for e in ben.get("repairs", [])),
       "A3 the BENEFITED side answers what repaired it (derived direction, "
       "same rel id)")
    ok(any(e.get("id") == r2["id"] for e in ben.get("withdraws", [])),
       "A4 the benefited side answers what withdrew it")
    derived = ben.get("repairs", []) + ben.get("withdraws", [])
    ok(all(e.get("derived") for e in derived),
       "A5 every derived-side entry is LABELLED as derived (never presented "
       "as a stored row)")

    ok(disk_bytes(path) == before,
       "A6 READING writes nothing back — the ledger file is byte-identical "
       "after the read (no second stored row, design Nongoal honoured)")

    # ticket-level supersedes kind, both directions
    r3 = rel(dc.REL_KIND_SUPERSEDES, fix, red, 1791510000003)
    dp.append_rows([r3], path)
    rows, _b = dc.read_rows(path)
    ans = rels(rows, fix)
    ans_red = rels(rows, red)
    ok(any(e.get("id") == r3["id"] for e in (ans.get("as_actor") or {})
           .get("supersedes", [])),
       "A7 supersedes is readable on the acting side")
    ok(any(e.get("id") == r3["id"] for e in (ans_red.get("as_benefited") or
                                             {}).get("supersedes", [])),
       "A8 supersedes is readable on the benefited side")

    # ---------- A (cont). the three naming forms, and the honest gap --------
    d2 = tmpdir("sc_t26100966_a9_")
    p2 = os.path.join(d2, "delivery.jsonl")
    f2, red2 = "t-fix2", "t-red2"
    ldg = "ldg-red2"
    by_ldg = rel(dc.REL_KIND_REPAIRS, f2, ldg, 1791510000011)
    by_ticket = rel(dc.REL_KIND_REPAIRS, f2, red2, 1791510000012)
    pid = "deadbeef01"
    by_patch = rel(dc.REL_KIND_REPAIRS, f2, pid, 1791510000013,
                   evidence={"what": "patch_id", "ref": pid})
    dp.append_rows([landing_row(red2, 1791510000010, ldg),
                    by_ldg, by_ticket, by_patch], p2)
    rows2, _b = dc.read_rows(p2)
    ans = rels(rows2, red2, patch_ids={ldg: pid})
    got = sorted(e.get("id") for e in
                 (ans.get("as_benefited") or {}).get("repairs", []))
    ok(got == sorted([by_ldg["id"], by_ticket["id"], by_patch["id"]]),
       "A9 all three target naming forms resolve on the benefited side "
       "(landing id, ticket id, patch identity via the explicit map)")
    ans_nomap = rels(rows2, red2)
    ben = (ans_nomap.get("as_benefited") or {})
    unres = ans_nomap.get("unresolved") or ben.get("unresolved") or []
    ok(by_patch["id"] in unres
       and not any(e.get("id") == by_patch["id"]
                   for e in ben.get("repairs", [])),
       "A10 a patch-id-named relation without the map stays VISIBLE in the "
       "unresolved bucket naming the rel id (a gap on the record, never "
       "silently dropped, never guessed)")
    ok(all("deadbeef" not in json.dumps(e)
           for e in ben.get("repairs", [])),
       "A11 the unresolved relation never leaks into the resolved answer")

    # ---------- B. correction-aware: superseded appears on NEITHER side -----
    d3 = tmpdir("sc_t26100966_b_")
    p3 = os.path.join(d3, "delivery.jsonl")
    f3, red3 = "t-fix3", "t-red3"
    wrong = rel(dc.REL_KIND_REPAIRS, f3, red3, 1791510000021)
    dp.append_rows([landing_row(red3, 1791510000020, "ldg-red3"), wrong], p3)
    right = rel(dc.REL_KIND_REPAIRS, f3, red3, 1791510000022,
                supersedes=wrong["id"])
    dp.append_rows([right], p3)
    rows3, _b = dc.read_rows(p3)
    ans_actor = rels(rows3, f3)
    ans_ben = rels(rows3, red3)
    actor_ids = [e.get("id") for e in
                 (ans_actor.get("as_actor") or {}).get("repairs", [])]
    ben_ids = [e.get("id") for e in
               (ans_ben.get("as_benefited") or {}).get("repairs", [])]
    ok(wrong["id"] not in actor_ids and wrong["id"] not in ben_ids,
       "B1 a superseded (corrected) relation appears on NEITHER side of the "
       "answer — never current (spec (3))")
    ok(right["id"] in actor_ids and right["id"] in ben_ids,
       "B2 the correcting row is the one both sides see")

    # ---------- C. one implementation, mirrored answers ---------------------
    ok(getattr(dp, "relations_of", None) is rels,
       "C1 develop_promote.relations_of IS develop_certify.relations_of — "
       "one implementation, importable from both halves (no second "
       "direction logic)")
    d4 = tmpdir("sc_t26100966_c_")
    p4 = os.path.join(d4, "delivery.jsonl")
    f4, red4 = "t-fix4", "t-red4"
    r = rel(dc.REL_KIND_REPAIRS, f4, red4, 1791510000031)
    dp.append_rows([landing_row(red4, 1791510000030, "ldg-red4"), r], p4)
    rows4, _b = dc.read_rows(p4)
    a_from = rels(rows4, f4)
    a_to = rels(rows4, red4)
    stored = [e.get("id") for e in (a_from.get("as_actor") or {})
              .get("repairs", [])]
    derived = [e.get("id") for e in (a_to.get("as_benefited") or {})
               .get("repairs", [])]
    ok(stored == derived == [r["id"]],
       "C2 the derived answer MIRRORS the stored answer (same relation ids "
       "on both views of the same fact)")

    # ---------- D. the promotion record names its repairs -------------------
    d5 = tmpdir("sc_t26100966_d_")
    p5 = os.path.join(d5, "delivery.jsonl")
    covered, mate, other = "t-covered", "t-mate", "t-other"
    ldg_c, ldg_m, ldg_o = "ldg-cov", "ldg-mate", "ldg-oth"
    rep = rel(dc.REL_KIND_REPAIRS, covered, "ldg-prey", 1791510000041)
    wd = rel(dc.REL_KIND_WITHDRAWS, mate, "t-prey", 1791510000042)
    stray = rel(dc.REL_KIND_REPAIRS, other, "ldg-prey", 1791510000043)
    dp.append_rows([
        landing_row(covered, 1791510000040, ldg_c),
        landing_row(mate, 1791510000040, ldg_m),
        landing_row(other, 1791510000040, ldg_o),
        landing_row("t-prey", 1791510000040, "ldg-prey",
                    revision="rev-prey"),
        cert_row(1791510000044, "cert-1"),
        rep, wd, stray,
    ], p5)
    disk5, _b = dc.read_rows(p5)
    promo = dp.build_promotion(
        "cert-1", LINE, [covered, mate],
        main_before=[{"repo": REPO_A, "revision": "rev0000"}],
        main_after=[{"repo": REPO_A, "revision": "rev1111"}],
        signer="host", at_ms=1791510000045, delivery_rows=disk5,
        patch_id_fn=lambda rev, repo: "pid-%s" % rev)
    names = {e.get("id"): e for e in (promo.get("repairs") or [])}
    ok(rep["id"] in names and names.get(rep["id"], {}).get("from") == covered
       and names.get(rep["id"], {}).get("to") == "ldg-prey",
       "D1 the promotion record names the repair a covered ticket recorded "
       "(rel id + from + to)")
    ok(wd["id"] in names and names.get(wd["id"], {}).get("kind")
       == dc.REL_KIND_WITHDRAWS,
       "D2 the withdrawal a covered ticket recorded is named too, with its "
       "kind on the entry (remedy work, same design sentence)")
    ok(stray["id"] not in names,
       "D3 a repair by a ticket the promotion does NOT cover is not named")
    ok(all(str(k).startswith("rel-") for k in names),
       "D4 every named entry cites a rel- id (the ledger stays the source; "
       "the field is a naming, not a second truth)")

    # reader-side proof: the row lands in the FILE and reads back with the
    # field — never proven from the builder's return value alone
    dp.append_rows([promo], p5)
    disk6, _b = dc.read_rows(p5)
    back = [r for r in disk6 if r.get("kind") == dc.KIND_PROMOTION]
    ok(back and sorted(e.get("id") for e in (back[-1].get("repairs") or []))
       == sorted(names),
       "D5 the promotion row read back FROM DISK carries the repairs naming "
       "(readers on the file face see it)")
    clean, why = dc.validate_row(back[-1])
    ok(clean is not None,
       "D6 the promotion row with the repairs field validates through the "
       "shared validator")

    # stable shape when there is nothing to name
    d7 = tmpdir("sc_t26100966_d7_")
    p7 = os.path.join(d7, "delivery.jsonl")
    solo = "t-solo"
    dp.append_rows([
        landing_row(solo, 1791510000050, "ldg-solo"),
        cert_row(1791510000051, "cert-2"),
    ], p7)
    disk7, _b = dc.read_rows(p7)
    promo2 = dp.build_promotion(
        "cert-2", LINE, [solo],
        main_before=[{"repo": REPO_A, "revision": "rev0000"}],
        main_after=[{"repo": REPO_A, "revision": "rev1111"}],
        signer="host", at_ms=1791510000052, delivery_rows=disk7)
    ok(promo2.get("repairs") == [],
       "D7 a promotion over a relation-free ledger keeps the field as an "
       "EMPTY list (stable row shape, never a missing key)")

    # legacy row without the field still validates; malformed field refuses
    legacy = dict(promo2)
    legacy["id"] = "prom-legacy"
    legacy.pop("repairs", None)
    clean, _w = dc.validate_row(legacy)
    ok(clean is not None,
       "D8 a legacy promotion row written before the field existed still "
       "validates (additive-only, old rows untouched)")
    for label, junk in (
            ("a list of strings", ["rel-x"]),
            ("a dict entry without a rel- id", [{"from": "a", "to": "b"}]),
            ("a bare string", "rel-x"),
    ):
        badrow = dict(promo2)
        badrow["id"] = "prom-bad-%d" % len(label)
        badrow["repairs"] = junk
        clean, why = dc.validate_row(badrow)
        ok(clean is None,
           "D9 a promotion row carrying %s as repairs is refused by name "
           "(%s) — the naming field is validated, never trusted"
           % (label, why))

    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
