#!/usr/bin/env python3
"""sc_legacy_promotion_ledger_migration.py — the legacy promotion.jsonl is
either migrated into delivery.jsonl in `at`-then-file order or refused BY
NAME on the read face; it is never silently read as "no promotions"
(t261009-29 ticket item (2)).

Run directly:
python3 integration/t261009-29/sc_legacy_promotion_ledger_migration.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS
entry).

Grey-box L3, offline seconds, temp files only, zero docker/Temporal/
browser, never touches 3099/7233.

The user-perceivable contract this entry owns (developer L1 owns the
migration function's unit truth table):

  A  MIGRATION PRESERVES THE DECLARED ORDER: legacy rows are appended so
     the shared writer assigns seqs in `at` order (ties broken by file
     order), the legacy file is renamed out of the way (append-only
     discipline — ledger bytes are never rewritten), and the delivery
     ledger is the only promotion ledger left.

  B  UNMIGRATED LEGACY ROWS ARE LOUD: with a promotion.jsonl holding rows
     next to the delivery ledger, the consumer-reachable faces (read AND
     append) refuse by name
     (legacy_promotion_file_not_migrated:promotion.jsonl:<n>) — an
     unmigrated ledger must never surface as "no promotions".

  C  AN EMPTY LEGACY FILE IS NOT DATA: zero legacy rows is a stated no-op
     (file still renamed, result says zero), not a refusal and not
     silence.

  D  MALFORMED LEGACY INPUT REFUSES BY NAME AND APPENDS NOTHING: a torn
     line, a non-object row or a row the shared validator refuses aborts
     the migration with a named reason and leaves the delivery ledger
     without the batch and the legacy file unmigrated in place (no
     partial migration, no half-migrated state).

  E  DUPLICATES REFUSE BY NAME, NAMING WHICH CHECK FAILED: twice inside
     the legacy file is legacy_row_duplicate:<id>; an id already folded
     into the delivery ledger is id_already_in_delivery_ledger:<id>.

Intent split: the single-space journey (one writer, projection, guard) is
sc_promotion_one_seq_space; validator refusal matrices belong to developer
L1; this entry owns the legacy-file journey (migrate / refuse / never
silent) judged through the public migration and read faces.

Pre-implementation tree = FAIL named (TDD signal); green required at the
integration gate / merge. develop_promote not landed = FAIL named, exit 1.
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


def prom_row(pid, ticket, at, rev=None):
    return {"kind": "promotion", "id": pid, "certification": "cert-%s" % pid,
            "line": "main", "repos": [{"repo": "r",
                                       "revision": rev or ("a" * 40)}],
            "tickets": [ticket],
            "main_before": [{"repo": "r", "revision": "b" * 40}],
            "main_after": [{"repo": "r", "revision": rev or ("a" * 40)}],
            "signer": "host", "on_behalf_of": None, "authority": None,
            "note": None, "at": at}


def write_legacy(d, rows_or_lines):
    path = os.path.join(d, "promotion.jsonl")
    with open(path, "w") as fh:
        for item in rows_or_lines:
            fh.write(item if isinstance(item, str)
                     else json.dumps(item) + "\n")
    return path


def refused_by(fn):
    """Run fn, return its exception text or None when it did not refuse."""
    try:
        fn()
        return None
    except Exception as exc:
        return str(exc)


def main():
    # ---------- A. migration preserves at-then-file order ----------
    section("A legacy rows migrate in `at` order, file order breaks ties")
    d = tmpdir("sc_t26100929_mig_")
    led = os.path.join(d, "delivery.jsonl")
    legacy = write_legacy(d, [prom_row("prom-c", "t-3", 3000),
                              prom_row("prom-a", "t-1", 1000),
                              prom_row("prom-b", "t-2", 2000)])
    res = dp.migrate_legacy_promotion_ledger(led, legacy)
    ok(res.get("migrated") == 3 and res.get("renamed") is True,
       "A1 the result states the migration: 3 rows, file renamed (%r)"
       % (res,))
    rows, _cur = dc.read_rows(led)
    ids = [r.get("id") for r in rows]
    ok(ids == ["prom-a", "prom-b", "prom-c"],
       "A2 seqs were assigned in `at` order (1000,2000,3000), read back "
       "from disk (%r)" % ids)
    ok(res.get("seqs") == sorted(res.get("seqs") or [])
       and len(res.get("seqs") or []) == 3,
       "A3 the shared writer's seqs came back monotonic in the result")
    ok(not os.path.exists(legacy)
       and os.path.exists(legacy + ".migrated"),
       "A4 the legacy file is renamed out of the way, not rewritten")
    res2 = dp.migrate_legacy_promotion_ledger(led)
    rows2, _c2 = dc.read_rows(led)
    ok(res2.get("migrated") == 0 and rows2 == rows,
       "A5 a second migration run is a stated no-op (ledger "
       "byte-identical)")

    # ---------- B. unmigrated legacy rows are loud ----------
    section("B an unmigrated legacy ledger with rows refuses by name")
    d2 = tmpdir("sc_t26100929_loud_")
    led2 = os.path.join(d2, "delivery.jsonl")
    write_legacy(d2, [prom_row("prom-x", "t-9", 1000), prom_row("prom-y",
                                                                "t-8", 2000)])
    r_read = refused_by(lambda: dp.read_promotion_rows(led2))
    ok(r_read is not None
       and r_read.startswith("legacy_promotion_file_not_migrated:"
                             "promotion.jsonl:2"),
       "B1 the promotion read face refuses by name, naming the file and "
       "the row count (%r)" % r_read)
    r_app = refused_by(lambda: dp.append_rows(
        [prom_row("prom-new", "t-7", 3000)], led2))
    ok(r_app is not None
       and "legacy_promotion_file_not_migrated" in r_app,
       "B2 new-space writes refuse too — no new rows while the old space "
       "still holds rows (%r)" % r_app)

    # ---------- C. an empty legacy file is not data ----------
    section("C a zero-row legacy file is a stated no-op")
    d3 = tmpdir("sc_t26100929_empty_")
    led3 = os.path.join(d3, "delivery.jsonl")
    legacy3 = write_legacy(d3, [])
    res3 = dp.migrate_legacy_promotion_ledger(led3, legacy3)
    ok(res3.get("migrated") == 0 and res3.get("renamed") is True,
       "C1 a zero-row migration is stated (0 rows, still renamed) (%r)"
       % (res3,))
    ok(not os.path.exists(led3) or len(dc.read_rows(led3)[0]) == 0,
       "C2 nothing was appended for zero legacy rows")

    # ---------- D. malformed legacy input refuses, appends nothing ----------
    section("D malformed legacy rows refuse by name, no partial append")
    d4 = tmpdir("sc_t26100929_bad_")
    led4 = os.path.join(d4, "delivery.jsonl")
    for label, bad, why in [
            ("a torn line", "{not json\n", "legacy_has_malformed_lines"),
            ("a non-object JSON row", json.dumps([1, 2]) + "\n",
             "legacy_has_malformed_lines"),
            ("a validator-refused row",
             json.dumps(prom_row("prom-z", "t-8", "not-a-number")) + "\n",
             "legacy_row_invalid")]:
        legacy4 = write_legacy(d4, [prom_row("prom-ok", "t-7", 1000), bad])
        r = refused_by(lambda: dp.migrate_legacy_promotion_ledger(led4,
                                                                  legacy4))
        ok(r is not None and why in r,
           "D %s refuses by name, naming which check failed (%r)"
           % (label, r))
        ok(not os.path.exists(led4) or len(dc.read_rows(led4)[0]) == 0,
           "D %s appended nothing (no partial migration)" % label)
        ok(os.path.exists(legacy4)
           and not os.path.exists(legacy4 + ".migrated"),
           "D %s leaves the legacy file unmigrated in place" % label)

    # ---------- E. duplicates refuse by name ----------
    section("E duplicate legacy rows refuse by name, naming the check")
    d5 = tmpdir("sc_t26100929_dup_")
    led5 = os.path.join(d5, "delivery.jsonl")
    legacy5 = write_legacy(d5, [prom_row("prom-d", "t-5", 1000),
                                prom_row("prom-d", "t-5", 2000)])
    r = refused_by(lambda: dp.migrate_legacy_promotion_ledger(led5, legacy5))
    ok(r is not None and "legacy_row_duplicate:prom-d" in r,
       "E1 a duplicate id inside the legacy file refuses as "
       "legacy_row_duplicate:<id> (%r)" % r)
    d6 = tmpdir("sc_t26100929_dup2_")
    led6 = os.path.join(d6, "delivery.jsonl")
    dc.append_rows([prom_row("prom-e", "t-6", 500)], led6)
    legacy6 = write_legacy(d6, [prom_row("prom-e", "t-6", 1000)])
    r = refused_by(lambda: dp.migrate_legacy_promotion_ledger(led6, legacy6))
    ok(r is not None and "id_already_in_delivery_ledger:prom-e" in r,
       "E2 a legacy id already folded into the delivery ledger refuses as "
       "id_already_in_delivery_ledger:<id> (%r)" % r)

    for d_ in TMPDIRS:
        shutil.rmtree(d_, ignore_errors=True)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
