#!/usr/bin/env python3
"""sc_t26100702_source_identity_register — three source classes, register-derived
project, read-back proof (t261007-02, grey-box L2, offline seconds).

User-perceivable contract (ticket item 5 + KI-195 reader-side discipline):
  R1 the three legal classes file: executor-session (named in the project's
     executor_sessions), project-session (present in the project's
     sessions.json), lane-agent (engine-injected channel). Each row carries the
     class and the register-derived project.
  R2 anything else is refused with a named reason: an unknown session nobody
     declares, and a missing/rotten register (sessions.json absent) — never a
     silent default identity, never a crash. Ledger gains nothing.
  R3 the project is derived, never self-reported: a caller who claims another
     project does not get that claim honored — the row (read back from the
     ledger FILE the panel reads, not from the receipt) carries the
     register-derived project; where the contract is refuse, the refusal names
     the project field.
  R4 epic ownership hard check: a code outside the register is refused naming
     epic; a registered code passes; `none` without a reason is refused;
     `none` with a reason passes. source_ticket is NOT cross-checked against
     the epic (a fact and a judgement are two meanings): an empty source ticket
     with a real epic, and a source ticket whose own epic differs, both file.

Anchors: CLI receipt + ledger file bytes. Module missing = FAIL named
(TDD-phase red expected). Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_request_thread_seam import (KEY, EXEC_SESSION, PROJ_SESSION, open_world,
                                     heads, ledger_rows, make_world, named,
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


BODY = {
    "subject": "copy language gate",
    "source_ticket": "t261004-28",
    "epic": "localization",
    "kind": "finding",
    "question": "Does the migration trip the copy language gate?",
}


def row_for(rows, subject):
    h = [r for r in heads(rows) if r.get("subject") == subject]
    return h[-1] if h else None


section("R1 three legal source classes file with the derived project")
for role, sess, label in (("executor", EXEC_SESSION, "executor-session"),
                          ("project", PROJ_SESSION, "project-session"),
                          ("lane", None, "lane-agent")):
    root, env, cleanup = open_world(role)
    try:
        rc, doc, err = run_op("file", dict(BODY), env)
        rows = ledger_rows(root)
        r = row_for(rows, BODY["subject"])
        ok(rc == 0 and doc.get("ok") is not False and r is not None,
           "%s files (rc=%s err=%s)" % (label, rc, err[-100:]))
        if r:
            ok(r.get("source_class") == label,
               "row carries source_class=%s (%r)" % (label, r.get("source_class")))
            ok(r.get("project") == KEY,
               "row project = register-derived key (%r)" % r.get("project"))
            if sess:
                ok(r.get("raised_by") == sess,
                   "raised_by = the register-named session (%r)" % r.get("raised_by"))
    finally:
        cleanup(None, None, None)

section("R2 unknown source refused, named, nothing written")
root, env, cleanup = open_world("unknown")
try:
    rc, doc, err = run_op("file", dict(BODY), env)
    ok(doc.get("ok") is False and named(doc, err, "source_class"),
       "undeclared session refused naming source_class (doc=%s)" % json.dumps(doc)[:140])
    ok(len(ledger_rows(root)) == 0, "ledger empty after refusal (%d)" % len(ledger_rows(root)))
finally:
    cleanup(None, None, None)

# rotten register: sessions.json present but garbage -> declared refusal, not a default identity
root, env, cleanup = open_world("project")
try:
    (Path(root) / KEY / "sessions.json").write_text("{not a register", "utf-8")
    rc, doc, err = run_op("file", dict(BODY), env)
    ok(doc.get("ok") is False,
       "rotten sessions.json -> named refusal, not a silent default (doc=%s)"
       % json.dumps(doc)[:140])
    ok(len(ledger_rows(root)) == 0, "rotten register wrote nothing")
finally:
    cleanup(None, None, None)

section("R3 project is derived, never self-reported (reader-side read-back)")
root, env, cleanup = open_world("executor")
try:
    rc, doc, err = run_op("file", dict(BODY, project="someone-elses-project"), env)
    rows = ledger_rows(root)
    r = row_for(rows, BODY["subject"])
    if doc.get("ok") is False:
        ok(named(doc, err, "project"),
           "self-reported foreign project refused naming project (%s)" % json.dumps(doc)[:140])
        ok(r is None, "no row landed for the refused claim")
    else:
        ok(r is not None and r.get("project") == KEY,
           "row read back from the ledger carries the derived project (%r)"
           % (r.get("project") if r else None))
        ok(r.get("project") != "someone-elses-project",
           "the self-reported value did not land")
finally:
    cleanup(None, None, None)

section("R4 epic register check; ticket and epic never cross-checked")
root, env, cleanup = open_world("executor")
try:
    rc, doc, err = run_op("file", dict(BODY, epic="not-in-register"), env)
    ok(doc.get("ok") is False and named(doc, err, "epic"),
       "epic outside the register refused naming epic (%s)" % json.dumps(doc)[:140])
    rc, doc, err = run_op("file", dict(BODY, epic="none"), env)
    ok(doc.get("ok") is False and named(doc, err, "epic"),
       "epic=none without a reason refused (%s)" % json.dumps(doc)[:140])
    rc, doc, err = run_op("file", dict(BODY, epic="none",
                                       epic_reason="no epic owns copy tone yet"), env)
    r = row_for(ledger_rows(root), BODY["subject"])
    ok(rc == 0 and doc.get("ok") is not False and r is not None
       and r.get("epic") == "none" and bool(r.get("epic_reason")),
       "epic=none + reason files (rc=%s)" % rc)
    # fact vs judgement: empty source ticket with a real epic
    rc, doc, err = run_op("file", dict(BODY, subject="no-ticket-fact", source_ticket=""), env)
    r2 = row_for(ledger_rows(root), "no-ticket-fact")
    ok(rc == 0 and r2 is not None,
       "empty source ticket with a registered epic files (fact may be empty)")
    # judgement never checked against the source ticket's epic
    rc, doc, err = run_op("file", dict(BODY, subject="cross-epic-is-legal"), env)
    r3 = row_for(ledger_rows(root), "cross-epic-is-legal")
    ok(rc == 0 and r3 is not None,
       "source ticket + unrelated owning epic both accepted (no cross-check)")
finally:
    cleanup(None, None, None)

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
