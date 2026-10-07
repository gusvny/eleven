#!/usr/bin/env python3
"""sc_t26100702_state_machine_permissions — the five-state thread machine and
its fixed who-may-set table (t261007-02, grey-box L2, offline seconds, zero
docker/browser, red-line zero-touch 3099).

User-perceivable contract (ticket item 2 + the 261004 design note "states are
set by who is allowed, written fixed"):
  S1 open -> resolved: the doer (executor channel) sets resolved WITH evidence;
     the row lands as its own append-only state row; the head row is never
     rewritten (the head's original bytes are still present).
  S2 answered -> resolved: same transition works from answered (seeded).
  S3 who-may-set refusals: the doer must NOT be able to set answered or
     dismissed (host-only, panel); a manual superseded must be refused
     (machine-only, on a supersedes link). Refusal names the field, ledger
     gains no row.
  S4 terminal states accept no further state rows: a second state row on an
     already-resolved head is refused; the ledger stays unchanged.
  S5 expiry never mutates state: a head whose expires_at is long past is still
     open — no state row appears, the state stays open (expiry drives display
     and reminder level only; it never closes and never silences).

Anchors: CLI exit code + printed receipt + ledger file bytes read back from
<projects_root>/<key>/requests.jsonl (the file the panel reads). No internal
names. Module missing = FAIL with the name (TDD-phase red expected;
arbitrate/merge green). Stdlib only; temp tree reclaimed by context manager.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_request_thread_seam import (CLI, EXEC_SESSION, KEY, heads, ledger_rows,
                                     make_world, named, run_op, seed_rows)

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


def file_head(env):
    return run_op("file", {
        "subject": "ledger lock races",
        "source_ticket": "t261007-02",
        "epic": "executor-reliability",
        "kind": "finding",
        "question": "Concurrent state rows can interleave under the flock?",
        "detail": "check-then-append window",
    }, env)


def head_id(rows):
    h = heads(rows)
    return h[-1].get("id") if h else None


if not CLI.exists():
    section("F engine thread module present")
    ok(False, "server/engine/request_thread.py exists (module missing = FAIL named)")
    print("\nFAIL %d/%d" % (PASS, PASS + FAIL))
    sys.exit(1)

with make_world("executor") as (root, env):
    section("T0 head filing precondition (executor channel)")
    rc, doc, err = file_head(env)
    ok(rc == 0 and doc.get("ok") is not False,
       "head files cleanly (rc=%s doc=%s err=%s)" % (rc, json.dumps(doc)[:120], err[-120:]))
    hid = head_id(ledger_rows(root))
    ok(bool(hid), "head id readable from ledger (%r)" % hid)

    section("S1 open -> resolved with evidence (doer, own append-only row)")
    n_before = len(ledger_rows(root))
    head_bytes_before = (Path(root) / KEY / "requests.jsonl").read_text("utf-8") if (Path(root) / KEY / "requests.jsonl").exists() else ""
    rc, doc, err = run_op("state", {"id": hid, "state": "resolved",
                                    "evidence": "t261006-11"}, env)
    rows = ledger_rows(root)
    st = [r for r in rows if r.get("type") == "state" and r.get("state_for") == hid
          and r.get("state") == "resolved"]
    ok(rc == 0 and doc.get("ok") is not False,
       "resolved accepted with a ticket-id evidence (rc=%s err=%s)" % (rc, err[-120:]))
    ok(len(st) == 1, "exactly one resolved state row (%d)" % len(st))
    ok(len(rows) == n_before + 1, "one new row appended, nothing rewritten (%d -> %d)"
       % (n_before, len(rows)))
    ok(((Path(root) / KEY / "requests.jsonl").read_text("utf-8") if (Path(root) / KEY / "requests.jsonl").exists() else "").startswith(head_bytes_before),
       "head row bytes untouched (append-only)")

    section("S2 answered -> resolved (seeded answered state)")
    rc, doc, _ = file_head(env)
    hid2 = head_id(ledger_rows(root))
    seed_rows(root, [{"type": "state", "state_for": hid2, "state": "answered",
                      "by": "host", "at": 1}])
    rc, doc, err = run_op("state", {"id": hid2, "state": "resolved",
                                    "evidence": "9bd4c1e"}, env)
    rows = ledger_rows(root)
    ok(rc == 0 and doc.get("ok") is not False,
       "resolved from answered accepted with a commit-id evidence (rc=%s err=%s)"
       % (rc, err[-120:]))
    ok(any(r.get("type") == "state" and r.get("state_for") == hid2
           and r.get("state") == "resolved" for r in rows),
       "resolved state row present for the answered head")

    section("S3 who-may-set refusals (doer cannot host-set; superseded is machine-only)")
    rc, doc, _ = file_head(env)
    hid3 = head_id(ledger_rows(root))
    n_before = len(ledger_rows(root))
    for bad_state in ("answered", "dismissed", "superseded"):
        rc, doc, err = run_op("state", {"id": hid3, "state": bad_state}, env)
        ok(doc.get("ok") is False and named(doc, err, bad_state),
           "doer setting %s refused, names the field (rc=%s doc=%s)"
           % (bad_state, rc, json.dumps(doc)[:120]))
    ok(len(ledger_rows(root)) == n_before,
       "refused state attempts wrote nothing (%d rows)" % len(ledger_rows(root)))

    section("S4 terminal states accept no further state rows")
    rc, doc, err = run_op("state", {"id": hid, "state": "dismissed"}, env)
    ok(doc.get("ok") is False and named(doc, err, "state"),
       "state row on an already-resolved head refused (%s)" % json.dumps(doc)[:120])
    ok(len(ledger_rows(root)) == n_before, "terminal refusal wrote nothing")

    section("S5 expiry never mutates state")
    rc, doc, _ = run_op("file", {
        "subject": "already stale finding",
        "source_ticket": "",
        "epic": "localization",
        "kind": "finding",
        "question": "Stale copy in the panel header?",
        "expires_at": 1,
    }, env)
    hid5 = head_id(ledger_rows(root))
    rows = ledger_rows(root)
    h5 = [r for r in heads(rows) if r.get("id") == hid5]
    ok(rc == 0 and bool(h5), "expired-but-open head still files (rc=%s)" % rc)
    ok(not any(r.get("type") == "state" and r.get("state_for") == hid5 for r in rows),
       "expiry produced no state row (state stays open)")

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
