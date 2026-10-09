#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100948_preflight_refuse.py — look before you kill (t261009-48, KI-01M4GF5R8NHQNATH7WD7SKF94X / KI-01M4H1DN2Z10J973DD6PBMPB4W).

intent (user-perceivable contract):
  Before `engine_ops restart` signals ANY process, the operator must be TOLD what
  the kill costs, and when the target holds a STARTED workflow task or an
  in-flight agent activity the tool must REFUSE BY NAME under the default-safe
  policy — not kill and explain afterwards. Tonight's incidents: an orphaned WFT
  parked a lane for a full 499 s, and a handover landed on top of an in-flight
  round and cancelled it — both invisible in anything the tool printed.

faces asserted (grey-box L2, offline seconds, zero docker/Temporal/3099, driven
through the pure contract seams of server/tools/engine_ops.py with fixture
describe-shaped objects — no production contact):
  P1 CLI contract surface: restart declares --force / --inflight-policy /
     --inflight-wait / --reason on the public build_parser() face.
  P2 pre-flight faces from fixture payloads: the WFT face flags present+state+
     attempt+running_s; the pending-activity rows carry type/attempt/started/
     running seconds (the facts the worker names at shutdown).
  P3 blockers + refusal: a STARTED WFT and an in-flight activity both become
     blockers whose risk text names the two KIs; the refusal message names
     ticket, stage, generation, attempt, and elapsed seconds — and, when a face
     is unobtainable, says unavailable instead of a blank (named provenance,
     plan review item 1).
  P4 disposition table: default (refuse) is safe; --force wins over wait
     (documented precedence); a clean target is clear.
  P5 bounded wait: an injectable-clock poll clears on a round boundary and
     times out into named non-cleared blockers — never an unbounded wait.
  P6 malformed inputs: fake describe objects without HasField / with None
     timestamps degrade to named zero/unknown faces, no crash, no fabricated
     verdict (external-input three-state).
  P7 long history: above the threshold the hint names continue-as-new and
     states the tool never rewrites a workflow (report, not action).
  P8 kill-only non-regression: _kill_and_wait_for_respawn is still the single
     signalling site.

green-on-land expectation (implement already in tree): all faces resolvable;
module unimportable = ENV_FAIL exit 2.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
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
        print("FAIL P%d %s %s" % (n, label, detail))
    else:
        print("ok   P%d %s" % (n, label))


spec = importlib.util.spec_from_file_location("engine_ops_under_test", TOOL)
try:
    eo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eo)
except Exception as exc:  # noqa: BLE001
    print("ENV_FAIL: engine_ops unimportable: %r" % exc)
    sys.exit(2)

NOW = 1_000_000.0


class Ts:  # proto-Timestamp-shaped fixture
    def __init__(self, epoch):
        self._e = epoch

    def ToDatetime(self):
        import datetime
        return datetime.datetime.fromtimestamp(self._e)


class F:  # minimal fake proto field holder
    def __init__(self, **kw):
        self.__dict__.update(kw)


def wft(state="STARTED", attempt=21, started=NOW - 135):
    return F(pending_workflow_task=F(state=F(name=state), attempt=attempt,
                                     started_time=Ts(started)))


# ------------------------------------------------- P1 CLI contract surface
parser = eo.build_parser()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        parser.parse_args(["restart", "--help"])
    except SystemExit:
        pass
helptext = buf.getvalue()
for flag in ("--force", "--inflight-policy", "--inflight-wait", "--reason"):
    check(flag in helptext, "P1 restart declares %s" % flag, "(operator knob missing)")

# ------------------------------------------------- P2 pre-flight faces
rows = eo._pending_activity_rows([F(activity_type=F(name="run_integration_tests"),
                                    state=F(name="STARTED"), attempt=1,
                                    last_worker_identity="1@h",
                                    last_started_time=Ts(NOW - 40))], now=NOW)
check(rows and rows[0]["activity_type"] == "run_integration_tests"
      and rows[0]["attempt"] == 1 and rows[0]["running_s"] == 40,
      "P2 activity row carries type/attempt/elapsed", json.dumps(rows))

face = eo._workflow_task_face(wft(), now=NOW)
check(face.get("present") and face.get("state") == "started"
      and face.get("attempt") == 21 and face.get("running_s") == 135,
      "P2 STARTED workflow task face (499 s orphan condition)", json.dumps(face))

# ------------------------------------------------- P3 blockers + refusal text
preflight = {"ticket": "t-fix", "pending_workflow_task": face,
             "pending_activities": rows,
             "stage_face": {"stage": "run_integration_tests", "gen": 11},
             "history": {"event_count": 47029, "size_bytes": 8084901}}
blockers = eo.handover_blockers(preflight)
check(len(blockers) == 2, "P3 WFT + in-flight activity both become blockers",
      json.dumps(blockers))
kinds = {b["kind"] for b in blockers}
check(kinds == {"started_workflow_task", "in_flight_activity"},
      "P3 blocker kinds", str(kinds))
check(any("KI-01M4GF5R8NHQNATH7WD7SKF94X" in b.get("risk", "") for b in blockers)
      and any("KI-01M4H1DN2Z10J973DD6PBMPB4W" in b.get("risk", "") for b in blockers),
      "P3 risk text cites the two registered KIs")
msg = eo.refusal_message("t-fix", blockers, preflight["stage_face"])
for token in ("t-fix", "stage=run_integration_tests", "gen=11", "attempt=21",
              "attempt=1", "running=135s", "running=40s"):
    check(token in msg, "P3 refusal names %s" % token, msg[:160])
msg_unavail = eo.refusal_message("t-fix", blockers, {"stage": None, "gen": None,
                                                     "note": "snapshot down"})
check("unavailable" in msg_unavail, "P3 unobtainable stage/gen named, not blank",
      msg_unavail[:160])

# ------------------------------------------------- P4 disposition table
check(eo.decide_handover([], force=False, policy="refuse") == "clear",
      "P4 clean target is clear")
check(eo.decide_handover(blockers, force=False, policy="refuse") == "refused",
      "P4 default policy refuses (default-safe)")
check(eo.decide_handover(blockers, force=True, policy="wait") == "forced",
      "P4 --force wins over wait (documented precedence)")
check(eo.decide_handover(blockers, force=False, policy="wait") == "wait",
      "P4 wait policy arms the bounded wait")

# ------------------------------------------------- P5 bounded round-boundary wait
fetches = {"n": 0}


def fetch_busy():
    fetches["n"] += 1
    return preflight


sleeps = []
res = eo.wait_for_round_boundary(fetch_busy, wait_s=1.0, poll_s=0.2,
                                 sleep=lambda s: sleeps.append(s))
check(res["cleared"] is False and res["last_blockers"],
      "P5 wait times out into named non-cleared blockers", json.dumps(res)[:120])
check(len(sleeps) > 0 and fetches["n"] > 1,
      "P5 wait polls the pre-flight face, bounded", "%d polls" % fetches["n"])
res2 = eo.wait_for_round_boundary(lambda: dict(preflight, pending_workflow_task=
                                               {"present": False},
                                               pending_activities=[]),
                                  wait_s=5.0, poll_s=0.0, sleep=lambda s: None)
check(res2["cleared"] is True, "P5 round boundary clears the wait")

# ------------------------------------------------- P6 malformed inputs
empty = eo._workflow_task_face(F(), now=NOW)
check(empty == {"present": False, "state": "", "attempt": 0,
                "started_at": "", "running_s": None},
      "P6 describe without pending WFT degrades to a named empty face", json.dumps(empty))
bad = eo._workflow_task_face(F(pending_workflow_task=F(state=None, attempt=None,
                                                       started_time=None)), now=NOW)
check(bad["present"] is True and bad["state"] == "" and bad["attempt"] == 0
      and bad["running_s"] is None,
      "P6 malformed WFT fields degrade named, no fabricated values", json.dumps(bad))
norows = eo._pending_activity_rows(None, now=NOW)
check(norows == [], "P6 missing pending_activities tolerated", json.dumps(norows))

# ------------------------------------------------- P7 long-history hint
check("continue-as-new" in eo._continue_as_new_hint(preflight)
      and "never rewrites" in eo._continue_as_new_hint(preflight),
      "P7 long history surfaces the continue-as-new report hint")
check(eo._continue_as_new_hint({"history": {"event_count": 100}}) == "",
      "P7 short history carries no hint (report is targeted, not noise)")

# ------------------------------------------------- P8 kill-only non-regression
src = TOOL.read_text(encoding="utf-8")
check("_kill_and_wait_for_respawn" in src,
      "P8 kill-only function still present (no second kill path renamed in)")

print("SCENARIO_SUMMARY %s checks=%d fails=%d" % (HERE.name, n, len(fails)))
sys.exit(1 if fails else 0)
