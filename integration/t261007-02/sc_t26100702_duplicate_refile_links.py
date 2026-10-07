#!/usr/bin/env python3
"""sc_t26100702_duplicate_refile_links — duplicate re-file links instead of
opening, and the four link kinds with machine-only supersede (t261007-02,
grey-box L2, offline seconds).

User-perceivable contract (ticket items 3, 9 + the 261004 note "when a re-file
of the same (source ticket + ownership + subject) has an unresolved item, it
should link rather than open a new one; a mechanical check is required"):
  D1 re-filing the same (source_ticket, epic, subject) while an OPEN head with
     that family key exists appends ONE link row and NO new request head; the
     receipt points at the existing item. The family stays one — this is the
     acceptance case "a duplicate re-file links instead of opening a new item".
  D2 a DIFFERENT family (different subject / epic / source ticket) still opens
     its own head — the mechanical check must not swallow legal new items.
  D3 the guard only guards OPEN items: once the head is terminal (resolved), a
     re-file of the same family opens a fresh head.
  D4 four link kinds: duplicates / follows_up / blocks each append a link row
     and do NOT change either side's state; a supersedes link appends a
     superseded state row on the TARGET, set by the machine — and a manual
     superseded state row stays refused (locked in
     t26100702-state-machine-permissions S3).

Anchors: CLI receipt + ledger file bytes. Module missing = FAIL named
(TDD-phase red expected). Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_request_thread_seam import (KEY, open_world, heads, ledger_rows, make_world,
                                     run_op, seed_rows)

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(t):
    print("\n%s" % t)


def body(subject, epic="executor-reliability", ticket="t261007-02"):
    return {"subject": subject, "source_ticket": ticket, "epic": epic,
            "kind": "finding", "question": "Family probe: %s" % subject}


root, env, cleanup = open_world("executor")
try:
    section("D1 duplicate re-file links, never opens")
    rc, doc, _ = run_op("file", body("flock window"), env)
    assert rc == 0
    n_before = len(ledger_rows(root))
    heads_before = len(heads(ledger_rows(root)))
    rc, doc, err = run_op("file", body("flock window"), env)
    rows = ledger_rows(root)
    links = [r for r in rows if r.get("type") == "link"]
    ok(rc == 0 and doc.get("ok") is not False,
       "duplicate re-file succeeds as a link op (rc=%s err=%s)" % (rc, err[-100:]))
    ok(len(heads(rows)) == heads_before,
       "no new head opened (%d heads)" % len(heads(rows)))
    ok(len(links) == 1, "exactly one link row appended (%d)" % len(links))
    ok(str(doc.get("linked_to", "")) != "" or any(l.get("kind") == "duplicates" for l in links),
       "receipt points at the existing item (linked_to=%r)" % doc.get("linked_to"))

    section("D2 different families still open their own heads")
    for i, b in enumerate((body("other subject"),
                           body("flock window", epic="localization"),
                           body("flock window", ticket="t261005-03"))):
        rc, doc, err = run_op("file", b, env)
        ok(rc == 0 and doc.get("ok") is not False,
           "family %d opens its own head (rc=%s err=%s)" % (i, rc, err[-80:]))
    ok(len(heads(ledger_rows(root))) == heads_before + 3,
       "three new heads for three new families (%d)"
       % len(heads(ledger_rows(root))))

    section("D3 the guard only guards OPEN items")
    rows = ledger_rows(root)
    open_head = [r for r in heads(rows) if r.get("subject") == "flock window"
                 and r.get("epic") == "executor-reliability"
                 and r.get("source_ticket") == "t261007-02"][-1]
    rc, doc, err = run_op("state", {"id": open_head.get("id"),
                                    "state": "resolved",
                                    "evidence": "t261007-02"}, env)
    ok(rc == 0, "head resolved to free the family (rc=%s doc=%s err=%s)" % (rc, json.dumps(doc)[:160], err[-80:]))
    heads_before = len(heads(ledger_rows(root)))
    rc, doc, err = run_op("file", body("flock window"), env)
    rows = ledger_rows(root)
    ok(rc == 0 and len(heads(rows)) == heads_before + 1,
       "re-file after terminal state opens a fresh head (%d)"
       % len(heads(rows)))

    section("D4 four link kinds; supersede is machine-set on the target")
    a = [r for r in heads(rows) if r.get("subject") == "other subject"][-1]
    b = heads(rows)[-1]
    for kind in ("duplicates", "follows_up", "blocks"):
        n = len(ledger_rows(root))
        rc, doc, err = run_op("link", {"from": b.get("id"), "to": a.get("id"),
                                       "kind": kind}, env)
        rows2 = ledger_rows(root)
        lk = [r for r in rows2 if r.get("type") == "link" and r.get("kind") == kind
              and r.get("to") == a.get("id")]
        ok(rc == 0 and len(lk) == 1,
           "%s link appended (rc=%s count=%d)" % (kind, rc, len(lk)))
        ok(len(rows2) == n + 1 and not any(
            r.get("type") == "state" and r.get("state_for") in (a.get("id"), b.get("id"))
            for r in rows2[n:]),
           "%s link changes nobody's state" % kind)
    n = len(ledger_rows(root))
    rc, doc, err = run_op("link", {"from": b.get("id"), "to": a.get("id"),
                                   "kind": "supersedes"}, env)
    rows3 = ledger_rows(root)
    sup = [r for r in rows3 if r.get("type") == "state"
           and r.get("state_for") == a.get("id") and r.get("state") == "superseded"]
    ok(rc == 0, "supersedes link accepted (rc=%s err=%s)" % (rc, err[-80:]))
    ok(len(sup) >= 1, "superseded state row auto-set on the TARGET (%d)" % len(sup))
    ok(len(rows3) >= n + 2, "link row + derived state row both landed (%d -> %d)"
       % (n, len(rows3)))
finally:
    cleanup(None, None, None)

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
