#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100948_handover_record.py — the decision is recorded (t261009-48, spec item 3).

intent (user-perceivable contract):
  A handover performed through `engine_ops restart` leaves a record naming WHO
  asked, WHY, what was IN FLIGHT at the moment of the kill, and WHICH
  disposition was chosen (waited / forced / refused). A handover that had to
  abort a round says so on the record itself, not only on the ticket face.
  Evidence is read READER-SIDE: the jsonl file on its absolute path, never the
  writer's return value (t261004-27 lesson: writer says ok, reader sees nothing).

faces asserted (grey-box L2, offline seconds, zero docker/Temporal/3099; the
record directory is redirected to a scenario-private tmp via the module-level
DATA seam — the production data dir is never touched, and it is restored in
finally):
  R1 build_handover_record carries scope/ticket/requested_by/reason/policy,
     the frozen in-flight face (blockers + stage + gen + history), and the
     disposition — the whole who/why/what/which tuple on one line.
  R2 aborted_a_round is true ONLY for disposition=forced with blockers; a
     refused / waited handover never claims an abort (plan review item 3).
  R3 append_handover_record writes one complete JSON line that the READER
     parses back from the file (refused dispositions recorded too).
  R4 a pre-existing corrupt line (garbage bytes / torn tail) does not break
     the append — the reader still finds new well-formed lines after the junk.
  R5 the surfaced record path is ABSOLUTE (boundary discipline).
  R6 two consecutive appends both survive as separate complete lines (single
     O_APPEND write, no clobber, no half-line).
  R7 a write failure (unwritable target) is named in the returned face and
     never raised into the handover itself.

green-on-land expectation (implement already in tree): all faces resolvable;
module unimportable = ENV_FAIL exit 2.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOL = REPO / "server" / "tools" / "engine_ops.py"

fails = []
n = 0


def check(cond, label, detail=""):
    global n
    n += 1
    if not cond:
        fails.append("%s %s" % (label, detail))
        print("FAIL R%d %s %s" % (n, label, detail))
    else:
        print("ok   R%d %s" % (n, label))


spec = importlib.util.spec_from_file_location("engine_ops_under_test", TOOL)
try:
    eo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eo)
except Exception as exc:  # noqa: BLE001
    print("ENV_FAIL: engine_ops unimportable: %r" % exc)
    sys.exit(2)

tmp = Path(tempfile.mkdtemp(prefix="sc-t26100948-record-"))
real_data = eo.DATA
eo.DATA = tmp
try:
    BLOCKERS = [{"kind": "in_flight_activity", "activity": "run_integration_tests",
                 "attempt": 1, "running_s": 135}]
    PREFLIGHT = {"ticket": "t-fix", "stage_face": {"stage": "run_integration_tests",
                                                   "gen": 11},
                 "history": {"event_count": 47029, "size_bytes": 8084901}}

    # ---------------- R1/R2 the record tuple + abort-flag discipline
    rec = eo.build_handover_record(scope="lane:t-fix", tid="t-fix",
                                   reason="land engine fix", policy="refuse",
                                   preflight=PREFLIGHT, blockers=BLOCKERS,
                                   disposition="forced", outcome="signalled")
    for key in ("scope", "ticket", "requested_by", "reason", "inflight_policy",
                "inflight_at_decision", "disposition", "aborted_a_round", "outcome"):
        check(key in rec, "R1 record carries %s" % key, str(sorted(rec)))
    infl = rec["inflight_at_decision"]
    check(infl.get("blockers") == BLOCKERS and infl.get("gen") == 11
          and infl.get("history", {}).get("event_count") == 47029,
          "R1 in-flight face frozen on the record", json.dumps(infl)[:160])
    check(bool(rec["requested_by"]) and "engine_ops" in rec["requested_by"],
          "R1 who asked is named", rec["requested_by"][:80])
    check(rec["aborted_a_round"] is True,
          "R2 forced-on-inflight declares aborted_a_round", str(rec["aborted_a_round"]))
    for disp in ("refused", "refused", "wait", "clear"):
        r2 = eo.build_handover_record(scope="lane:t-fix", tid="t-fix", reason="x",
                                      policy="refuse", preflight=PREFLIGHT,
                                      blockers=BLOCKERS, disposition=disp,
                                      outcome="not-signalled")
        if r2["aborted_a_round"]:
            check(False, "R2 %s never claims an abort" % disp, str(r2["aborted_a_round"]))
            break
    else:
        check(True, "R2 only a forced kill may declare aborted_a_round")

    # ---------------- R3 refused disposition lands on the file, reader-side
    check(eo.append_handover_record(rec).get("written") is True, "R3 append reports ok")
    rec_refused = eo.build_handover_record(scope="lane:t-fix", tid="t-fix",
                                           reason="saw in-flight round",
                                           policy="refuse", preflight=PREFLIGHT,
                                           blockers=BLOCKERS,
                                           disposition="refused",
                                           outcome="refused")
    check(eo.append_handover_record(rec_refused).get("written") is True,
          "R3 refusal append ok")
    lines = [json.loads(x) for x in
             (tmp / "worker-handovers.jsonl").read_text().splitlines() if x.strip()]
    check(len(lines) == 2 and lines[-1]["disposition"] == "refused",
          "R3 reader parses both lines from the file (refusal recorded)",
          "%d lines" % len(lines))

    # ---------------- R4 corrupt pre-existing line tolerated
    with (tmp / "worker-handovers.jsonl").open("a") as fh:
        fh.write("\x00garbage-not-json{\n")
    check(eo.append_handover_record(rec).get("written") is True,
          "R4 append after garbage ok")
    parsed = []
    for ln in (tmp / "worker-handovers.jsonl").read_text().splitlines():
        try:
            parsed.append(json.loads(ln))
        except ValueError:
            pass
    check(len(parsed) == 3, "R4 reader still finds well-formed lines after junk",
          "%d parsed of" % len(parsed))

    # ---------------- R5 absolute path
    p = eo.handover_record_path()
    check(p.is_absolute() and str(p).endswith("worker-handovers.jsonl"),
          "R5 record path is absolute", str(p))

    # ---------------- R6 consecutive appends survive
    ok1 = eo.append_handover_record(rec)
    ok2 = eo.append_handover_record(rec_refused)
    parsed2 = []
    for ln in (tmp / "worker-handovers.jsonl").read_text().splitlines():
        try:
            parsed2.append(json.loads(ln))
        except ValueError:
            pass
    check(ok1.get("written") and ok2.get("written") and len(parsed2) == 5,
          "R6 consecutive appends both survive complete", "%d lines" % len(parsed2))

    # ---------------- R7 write failure named, never raised
    eo.DATA = tmp / "blocked" / "not-a-dir"
    face = eo.append_handover_record(rec)
    check(face.get("written") is False and "failed" in face.get("note", ""),
          "R7 unwritable target names the failure", json.dumps(face))
finally:
    eo.DATA = real_data
    shutil.rmtree(tmp, ignore_errors=True)

print("SCENARIO_SUMMARY %s checks=%d fails=%d" % (HERE.name, n, len(fails)))
sys.exit(1 if fails else 0)
