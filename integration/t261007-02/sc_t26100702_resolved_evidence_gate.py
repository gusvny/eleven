#!/usr/bin/env python3
"""sc_t26100702_resolved_evidence_gate — no evidence means no resolved
(t261007-02, grey-box L2, offline seconds, zero docker/browser).

User-perceivable contract (ticket item 2 + the 261004 note "the party doing the
work lands it with evidence (ticket number / commit hash); whoever cannot write
the evidence is not allowed to resolve it"):
  E1 resolved with NO evidence (missing / empty / whitespace / non-string) is
     refused, names the evidence field, and writes NOTHING (fail-closed: no
     half state row, head stays open).
  E2 evidence shapes that are neither a ticket id nor a commit id are refused
     ("it's done", a date, a 3-char shard) — no evidence means no resolved.
  E3 the legal shapes pass: a ticket id (tNNNNNN-NN) and a commit id
     (7..40 hex) each produce exactly one resolved state row.
  E4 the ticket's three named refusal faces stay named refusals, not crashes:
     a bad-JSON argv and a non-object argv exit non-zero with a named error and
     an untouched ledger (malformed-input acceptance).

Anchors: CLI receipt + ledger bytes; reader-side read-back. Module missing =
FAIL named (TDD-phase red expected). Stdlib only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_request_thread_seam import (CLI, KEY, heads, ledger_rows, make_world,
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


def fresh_head(env, root, subject):
    rc, doc, err = run_op("file", {
        "subject": subject, "source_ticket": "t261007-02",
        "epic": "executor-reliability", "kind": "finding",
        "question": "Evidence gate probe: %s" % subject,
    }, env)
    assert rc == 0, err
    h = [r for r in heads(ledger_rows(root)) if r.get("subject") == subject]
    return h[-1].get("id")


if not CLI.exists():
    section("F engine thread module present")
    ok(False, "server/engine/request_thread.py exists (module missing = FAIL named)")
    print("\nFAIL %d/%d" % (PASS, PASS + FAIL))
    sys.exit(1)

with make_world("executor") as (root, env):
    section("E1 no evidence -> refused, nothing written")
    hid = fresh_head(env, root, "gate-no-evidence")
    for label, over in (("evidence key absent", {}),
                        ("evidence empty string", {"evidence": ""}),
                        ("evidence whitespace", {"evidence": "   "}),
                        ("evidence non-string", {"evidence": {"ref": 1}})):
        n_before = len(ledger_rows(root))
        rc, doc, err = run_op("state", dict({"id": hid, "state": "resolved"}, **over), env)
        ok(doc.get("ok") is False and ("evidence" in json.dumps(doc) or "evidence" in err),
           "resolved with %s refused and names evidence (doc=%s)" % (label, json.dumps(doc)[:100]))
        ok(len(ledger_rows(root)) == n_before,
           "%s: ledger unchanged (%d rows)" % (label, len(ledger_rows(root))))

    section("E2 non-evidence shapes refused")
    for label, ev in (("prose", "it is done, trust me"),
                      ("date", "2026-10-07"),
                      ("too-short shard", "9bd")):
        rc, doc, err = run_op("state", {"id": hid, "state": "resolved",
                                        "evidence": ev}, env)
        ok(doc.get("ok") is False and ("evidence" in json.dumps(doc) or "evidence" in err),
           "evidence=%s refused (%s)" % (label, json.dumps(doc)[:100]))
    ok(not any(r.get("type") == "state" and r.get("state") == "resolved"
               and r.get("state_for") == hid for r in ledger_rows(root)),
       "head still open after every refusal")

    section("E3 legal evidence shapes accepted")
    for label, ev in (("ticket id", "t261006-11"), ("commit id", "9bd4c1eab")):
        hid_x = fresh_head(env, root, "gate-ok-%s" % label.replace(" ", "-"))
        rc, doc, err = run_op("state", {"id": hid_x, "state": "resolved",
                                        "evidence": ev}, env)
        rows = ledger_rows(root)
        ok(rc == 0 and doc.get("ok") is not False,
           "%s accepted (rc=%s err=%s)" % (label, rc, err[-100:]))
        st = [r for r in rows if r.get("type") == "state" and r.get("state_for") == hid_x
              and r.get("state") == "resolved"]
        ok(len(st) == 1 and st[0].get("evidence") == ev,
           "exactly one resolved row carrying the evidence (%r)" % (st[0].get("evidence") if st else None))

    section("E4 malformed argv stays a named refusal, not a crash")
    n_before = len(ledger_rows(root))
    p = subprocess.run([sys.executable, str(CLI), "{not json"],
                       capture_output=True, text=True, env=env, timeout=60)
    ok(p.returncode != 0 and "JSON" in (p.stdout + p.stderr),
       "bad-JSON argv refused with a named error (rc=%s)" % p.returncode)
    p = subprocess.run([sys.executable, str(CLI), "[1,2]"],
                       capture_output=True, text=True, env=env, timeout=60)
    ok(p.returncode != 0 and (p.stdout + p.stderr).strip() != "",
       "non-object argv refused with a message (rc=%s)" % p.returncode)
    ok(len(ledger_rows(root)) == n_before, "malformed argv wrote nothing")

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
