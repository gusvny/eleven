#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102108_request_layer_gate -- the request-layer contract catches every
measured defect class of the executor request inbox (t261021-08, L3, tier:
offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233; pool "ro").

Ticket t261021-08 (plan rev2, review gen2 conditional pass). This ticket's
write set is integration/ only, so the ENGINE enforcement is a follow-up
ticket (handover spec: HANDOFF-request-layer-fix.md in this directory). What
this scenario pins HERE, against a fixture ledger shaped like the measured
live one (synthetic rows, zero real ~/.sandbar data):

  G1 the CURRENT write face still accepts the measured defect shapes
     (elided-ticket question, no-op-recheck default, cross-role notice) --
     proof the defect is real at today's write path;
  G2 the delivered contract library (lib_request_contract.py, the executable
     spec the fix ticket ports verbatim) catches all seven measured classes
     over the fixture ledger, evidence-first (row ids);
  G3 the fold: duplicate condition keys converge to ONE open card with the
     updated count/last_seen; resolved and expired heads leave the open list
     and stay in history; legacy rows are classified, never dropped; above
     the cap the digest lists ages and defaults;
  G4 reader-side-evidence discipline (KI-195): fold and digest are asserted
     on the ledger FILE read back from disk plus the fold output -- never on
     a writer receipt alone (the seam's run_op swallows non-JSON stdout).

Anchors: lib_request_contract output + ledger file bytes. Stdlib only;
TemporaryDirectory reclaim via the seam's open_world.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t261007-02"))
import lib_request_contract as rc  # noqa: E402
from lib_request_thread_seam import KEY, open_world, run_op  # noqa: E402

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  RED %s" % label)


def section(t):
    print("\n%s" % t)


def seed_ledger(root):
    """Fixture copies of the seven measured defect shapes + one good row."""
    d = Path(root)
    rows = [
        {"type": "request", "id": "good1", "at": 1000, "project": "proj",
         "kind": "blocker",
         "question": "t261021-08 L16 red blocks t261021-08 merge: proceed?",
         "ticket": "t261021-08", "line": "line-a", "stage": "merge",
         "decision": "yes/no", "cause": "content red on line-a",
         "condition_key": "blocker:proj:t261021-08:content red",
         "default_action": {"action": "hold the merge", "after_ms": 3600000},
         "expires_at": 9999999999999, "audience": "host"},
        # D1 x2: the same condition, one card per round (round id in the text
        # only -- the key stays clean, so the fold can converge them)
        {"type": "request", "id": "dup1", "at": 2000, "project": "proj",
         "kind": "run-silent",
         "question": "t261019-25 line-a run-silent: round 7 ended with no row",
         "ticket": "t261019-25", "line": "line-a", "stage": "run",
         "decision": "yes/no", "cause": "silent end",
         "condition_key": "run-silent:proj:t261019-25:silent end",
         "default_action": {"action": "retry the round", "after_ms": 60000},
         "expires_at": 9999999999999, "audience": "host"},
        {"type": "request", "id": "dup2", "at": 3000, "project": "proj",
         "kind": "run-silent",
         "question": "t261019-25 line-a run-silent: round 8 ended with no row",
         "ticket": "t261019-25", "line": "line-a", "stage": "run",
         "decision": "yes/no", "cause": "silent end",
         "condition_key": "run-silent:proj:t261019-25:silent end",
         "default_action": {"action": "retry the round", "after_ms": 60000},
         "expires_at": 9999999999999, "audience": "host"},
        {"type": "request-update", "id": "u1", "at": 3500,
         "condition_key": "run-silent:proj:t261019-25:silent end",
         "count": 1, "last_seen": 3500},
        {"type": "request", "id": "elided", "at": 4000, "project": "proj",
         "kind": "blocker", "question": "45 stops on an identical face",
         "line": "line-a", "stage": "run", "decision": "yes/no",
         "condition_key": "blocker:proj:line-a:identical face stop",
         "expires_at": 9999999999999, "audience": "host"},
        {"type": "request", "id": "why1", "at": 4100, "project": "proj",
         "kind": "finding",
         "question": "Gate receipt counts 8 over the list. Why?",
         "line": "line-a", "stage": "run",
         "condition_key": "finding:proj:line-a:gate receipt count",
         "expires_at": 9999999999999, "audience": "host"},
        {"type": "request", "id": "noop", "at": 4200, "project": "proj",
         "kind": "question", "question": "t261019-25: ledger gap?",
         "ticket": "t261019-25", "line": "line-a", "stage": "run",
         "decision": "yes/no",
         "default_action": "run-watch re-checks the records next tick",
         "condition_key": "question:proj:t261019-25:ledger gap",
         "expires_at": 9999999999999, "audience": "host"},
        {"type": "request", "id": "null", "at": 4300, "project": "proj",
         "kind": "blocker", "question": "t261019-25: stale blocker",
         "ticket": "t261019-25", "line": "line-a", "stage": "run",
         "decision": "yes/no",
         "condition_key": "blocker:proj:t261019-25:stale blocker",
         "expires_at": None, "audience": "host"},
        {"type": "request", "id": "cross", "at": 4400, "project": "proj",
         "kind": "notice",
         "question": "annex request_thread.py -- for the integration role",
         "ticket": "t261021-08", "line": "line-a", "stage": "run",
         "decision": "yes/no", "audience": "integration",
         "condition_key": "notice:proj:t261021-08:annex thread face",
         "expires_at": 9999999999999},
        {"type": "request", "id": "old-legacy", "at": 10, "project": "proj",
         "kind": "blocker", "question": "45 stops on an identical face"},
    ]
    p = d / "requests.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


root, env, cleanup = open_world("executor")
try:
    section("G1 today's write face: the measured shapes never enter anonymously")
    # Two-sided pin: the engine either ACCEPTS the measured defect shape
    # (the defect is real today) or REFUSES it with a NAMED field (the write
    # face already guards this class). A crash, a bare refusal with no named
    # field, or a silent ok=True that loses the question is the red.
    for label, body in (
        ("elided-ticket question",
         {"kind": "finding",
          "subject": "identical-face stop",
          "question": "45 stops on an identical face",
          "epic": "none", "epic_reason": "fixture: no registered epic",
          "default_action": "answer in the panel"}),
        ("no-op-recheck default",
         {"kind": "question",
          "subject": "records gap on line-a",
          "question": "t261019-25: records gap on line-a?",
          "epic": "none", "epic_reason": "fixture: no registered epic",
          "default_action": "run-watch re-checks the records next tick"}),
        ("cross-role notice into the host ledger",
         {"kind": "notice",
          "subject": "annex the thread face",
          "question": "annex the thread face (integration side action)",
          "audience": "integration",
          "epic": "none", "epic_reason": "fixture: no registered epic",
          "default_action": "answer in the panel"}),
    ):
        rc_, doc, _err = run_op("file", body, env)
        decided = (rc_ == 0 and doc.get("ok") is True) or \
            (doc.get("ok") is False and str(doc.get("field") or "").strip())
        ok(decided, "%s gets a DECIDED outcome at the write path -- accepted "
           "(defect real) or refused naming the failed field (rc=%s field=%s)"
           % (label, rc_, doc.get("field")))

    # the measured run-silent disease, reproduced at the REAL write face: the
    # per-round value rides the SUBJECT family key, so the re-file guard does
    # not link them and the ledger gains one head per round (defect real).
    for rid in ("r7", "r8"):
        run_op("file", {"kind": "run-silent",
                        "subject": "run-silent on line-a round %s" % rid,
                        "question": "run-silent on line-a round %s: no run row" % rid,
                        "dedupe_key": "run-silent:line-a:%s" % rid,
                        "line": "line-a", "detail": "ended without a run row",
                        "epic": "none",
                        "epic_reason": "fixture: no registered epic",
                        "default_action": "answer in the panel"}, env)
    _ledger = Path(root) / "requests.jsonl"
    if not _ledger.exists():
        _ledger = Path(root) / KEY / "requests.jsonl"
    _rows_now = [json.loads(l) for l in _ledger.read_text("utf-8").splitlines()
                 if l.strip()]
    _silent = [r for r in _rows_now if r.get("type") == "request"
               and str(r.get("kind")) == "run-silent"]
    ok(len(_silent) == 2,
       "one card PER ROUND is real today: two run-silent filings with the "
       "round in the subject land as %d separate heads" % len(_silent))
    ok(all(r.get("expires_at") is None for r in _silent),
       "the filed run-silent heads carry no expiry (behavior 6 gap is real)")

    section("G2 the contract detectors catch all seven measured classes")
    rows = seed_ledger(root)
    found = rc.run_all_detectors(rows)
    ok("dup2" in found["duplicate_condition_keys"]
       and "dup1" not in found["duplicate_condition_keys"],
       "D1 duplicate condition keys (dup2 red, first instance kept)")
    ok("elided" in found["elided_ticket_ids"], "D2 elided ticket ids")
    ok("why1" in found["why_questions"], "D3 why-questions")
    ok("noop" in found["noop_defaults"], "D4 no-op-recheck defaults")
    ok("null" in found["null_expiry"], "D5 null expires_at")
    ok("cross" in found["cross_role_notices"], "D6 cross-role notices")
    ok("good1" not in set(sum(found.values(), [])),
       "the well-formed row is never named by any detector")

    section("G3/G4 the fold, asserted on the ledger FILE + the fold output")
    on_disk = []
    with (Path(root) / "requests.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                on_disk.append(json.loads(line))
    ok(len(on_disk) >= len(rows), "ledger file read back (%d rows on disk)"
       % len(on_disk))
    view = rc.fold_updates(on_disk, now_ms=5000, cap=4)
    dup = [h for h in view["heads"]
           if h.get("condition_key") == "run-silent:proj:t261019-25:silent end"]
    ok(len(dup) == 1 and dup[0]["count"] == 3 and dup[0]["last_seen"] == 3500,
       "the duplicated condition folds to ONE head: two same-key heads plus "
       "one update row converge (count=3, last_seen=3500)")
    ok(len([h for h in view["open"] if h["id"].startswith("dup")]) == 1,
       "the open list shows the condition once")
    ok(view["orphans"] == 0, "no orphan updates")
    ok("old-legacy" in view["legacy"]
       and any(h["id"] == "old-legacy" for h in view["open"]),
       "the legacy row is classified legacy and still visible, never dropped")
    cap_rows = [{"type": "request", "id": "cap%d" % i, "at": 100 + i,
                 "project": "proj", "kind": "question",
                 "question": "t261021-08 cap filler %d" % i,
                 "condition_key": "question:proj:t261021-08:filler %d" % i,
                 "expires_at": 9999999999999, "audience": "host"}
                for i in range(6)]
    view2 = rc.fold_updates(on_disk + cap_rows, now_ms=5000, cap=4)
    d = view2["digest"]
    ok(isinstance(d, dict) and d["type"] == "request-digest"
       and len(view2["open"]) == 4 and len(d["folded"]) >= 1,
       "one digest card above the cap (open list held at 4, folded >= 1)")
    ok(all("age_ms" in e and "has_default" in e for e in d["folded"]),
       "digest entries carry ages and which carry a default")
    folded_ids = {e["id"] for e in d["folded"]}
    ok(all(h.get("folded_into") == d["id"]
           for h in view2["heads"] if h["id"] in folded_ids),
       "folded heads are marked folded_into (read from the fold output)")
    resolved_rows = on_disk + [{"type": "resolved", "id": "res1",
                                "head": "null", "at": 4900}]
    view3 = rc.fold_updates(resolved_rows, now_ms=5000)
    ok(not any(h["id"] == "null" for h in view3["open"])
       and any(h["id"] == "null" for h in view3["heads"]),
       "a resolved head leaves the open list and stays in history (no host "
       "dismissal needed)")
finally:
    cleanup(None, None, None)

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
