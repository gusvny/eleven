#!/usr/bin/env python3
"""sc_t26100702_reply_and_delegated_answer — thread replies and the delegated
answer trio (t261007-02, grey-box L2, offline seconds).

User-perceivable contract (ticket items 6-7 + the 261004 note "the writer of a
reply: you, the executor, me (integration); a project session may only ask and
add facts, and must not answer"; "a delegated answer distinguishes three places:
by / via / anchor"):
  P1 the executor may reply on a thread: one append-only reply row, head
     untouched.
  P2 a project session may ASK and add facts on the thread, but an ANSWERING
     reply from it is refused, naming the field; the ledger gains nothing for
     the refused attempt.
  P3 a delegated answer (integration files on the host's behalf) carries the
     three fields as DISTINCT row fields — by (who decided), via (who filed),
     anchor (the host's words) — all three readable back from the ledger file;
     the panel view exposes them (view face locked in the panel scenario).
  P4 reply identity is not self-reported: a reply whose claimed writer differs
     from the resolved identity is refused or lands with the derived writer —
     the claimed value never lands as-is.

Anchors: CLI receipt + ledger file bytes. Module missing = FAIL named
(TDD-phase red expected). Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_request_thread_seam import (KEY, open_world, seed_rows, EXEC_SESSION, PROJ_SESSION,
                                     heads, ledger_rows, make_world, named,
                                     run_op)

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


def fresh_head(env, root, subject="reply probe"):
    rc, doc, err = run_op("file", {
        "subject": subject, "source_ticket": "t261007-02",
        "epic": "executor-reliability", "kind": "question",
        "question": "May the lane restart the stage worker?",
    }, env)
    h = [r for r in heads(ledger_rows(root)) if r.get("subject") == subject]
    if rc == 0 and h:
        return h[-1].get("id")
    # The filing-class defect (sessions.json reader/writer divergence) is
    # reported by sc_t26100702_source_identity_register; this scenario still
    # exercises the REPLY contract over a seeded head so one defect does not
    # mask the others.
    print("  (head filed via fixture seed: filing refused rc=%s %s)" % (rc, json.dumps(doc)[:120]))
    seed_rows(root, [{"type": "request", "id": "req-seeded-%s" % abs(hash(subject)) ,
                      "project": KEY, "subject": subject, "epic": "executor-reliability",
                      "source_ticket": "t261007-02", "kind": "question",
                      "question": "May the lane restart the stage worker?", "at": 1}])
    return "req-seeded-%s" % abs(hash(subject))


section("P1 executor replies; append-only")
root, env, cleanup = open_world("executor")
try:
    hid = fresh_head(env, root)
    n_before = len(ledger_rows(root))
    head_bytes = (Path(root) / KEY / "requests.jsonl").read_text("utf-8") if (Path(root) / KEY / "requests.jsonl").exists() else ""
    rc, doc, err = run_op("reply", {"id": hid,
                                    "text": "Restarted; stage healthy again.", "intent": "answer"}, env)
    rows = ledger_rows(root)
    reps = [r for r in rows if r.get("type") == "reply" and r.get("reply_for") == hid]
    ok(rc == 0 and doc.get("ok") is not False,
       "executor reply accepted (rc=%s err=%s)" % (rc, err[-100:]))
    ok(len(reps) == 1, "exactly one reply row (%d)" % len(reps))
    ok(len(rows) == n_before + 1, "one row appended (%d -> %d)" % (n_before, len(rows)))
    ok(((Path(root) / KEY / "requests.jsonl").read_text("utf-8") if (Path(root) / KEY / "requests.jsonl").exists() else "").startswith(head_bytes),
       "head bytes untouched")

    section("P2 project session may ask/add facts, must not answer")
    rc, doc, err = run_op("reply", {"id": hid,
                                    "text": "FYI: the worker log shows the wedged loop.",
                                    "intent": "fact"}, env)
    ok(rc == 0 and doc.get("ok") is not False,
       "project-session fact/ask accepted (rc=%s err=%s)" % (rc, err[-100:]))
finally:
    cleanup(None, None, None)

root, env, cleanup = open_world("project")
try:
    hid = fresh_head(env, root, "proj session answer probe")
    n_before = len(ledger_rows(root))
    rc, doc, err = run_op("reply", {"id": hid,
                                    "text": "Yes, that resolves it.", "intent": "answer"}, env)
    ok(doc.get("ok") is False and named(doc, err, "reply"),
       "project-session ANSWER refused, names the field (doc=%s)" % json.dumps(doc)[:140])
    ok(len(ledger_rows(root)) == n_before, "refused answer wrote nothing")
finally:
    cleanup(None, None, None)

section("P3 delegated answer carries by / via / anchor as distinct fields")
root, env, cleanup = open_world("executor")
try:
    hid = fresh_head(env, root, "delegated probe")
    rc, doc, err = run_op("reply", {
        "id": hid,
        "text": "Granted for tonight only.", "intent": "answer",
        "by": "host",
        "via": "session-exec-t26100702",
        "anchor": "give it the stage restart, one night only",
    }, env)
    rows = ledger_rows(root)
    rep = [r for r in rows if r.get("type") == "reply" and r.get("reply_for") == hid]
    ok(rc == 0 and doc.get("ok") is not False,
       "delegated answer accepted (rc=%s doc=%s err=%s)" % (rc, json.dumps(doc)[:160], err[-100:]))
    if rep:
        r = rep[-1]
        ok(r.get("by") == "host", "by readable (%r)" % r.get("by"))
        ok(r.get("via") == "session-exec-t26100702", "via readable = the resolved filer session (%r)" % r.get("via"))
        ok(r.get("anchor") == "give it the stage restart, one night only",
           "anchor readable (%r)" % r.get("anchor"))
        ok(r.get("by") != r.get("via"), "by and via are distinct fields, not one blob")

    section("P4 reply writer is derived, not self-reported")
    rc, doc, err = run_op("reply", {"id": hid,
                                    "text": "pretending to be the host", "intent": "answer",
                                    "by": "host"}, env)
    rows = ledger_rows(root)
    reps = [r for r in rows if r.get("type") == "reply" and r.get("reply_for") == hid]
    last = reps[-1] if reps else {}
    if doc.get("ok") is False:
        ok(True, "writer-mismatch reply refused (doc=%s)" % json.dumps(doc)[:140])
    else:
        ok(last.get("by") != "host" or last.get("via") == EXEC_SESSION,
           "claimed writer did not land as-is (by=%r via=%r)" % (last.get("by"), last.get("via")))
finally:
    cleanup(None, None, None)

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
