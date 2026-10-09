#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100930_round_red_freeze_exempt.py — the round's red face: a red that
implicates content opens the freeze keyed to its certification, the bounded
red ladder answers next, and the fix-ticket exemption stays structural
(t261009-30 spec (d), develop-buffer goals 9/10/16/17/24).

Run directly:
python3 integration/t261009-30/sc_t26100930_round_red_freeze_exempt.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + guard files on a tmp
store, fake injected runner, zero docker/Temporal/browser, never touches
3099. Judged through the public faces of server/engine/develop_certify.py
(the round entry run_line_round plus freeze_state / may_land / derive_range /
next_red_action).

User-perceivable contract this entry owns:

  R1  a red round (the cited run failed cases) records the certification AND
      opens exactly one freeze episode whose cause is the red certification's
      id — never editable fields on the episode body — and the round's face
      names the freeze and the ladder's next step.
  R2  the culprit range is DERIVED from the records (the landings the red
      certification covered) and freeze_state reads frozen from the records
      alone.
  F1  on a frozen line only the structurally exempt fix kind may land — a
      change ticket answers no, and the exemption is judged from the records
      (a caller-declared structural fact), never from a ticket's own claim.
      An undeclared kind is refused by name, never silently deadlocked.
  F2  could-not-run on a frozen line opens NOTHING new — the freeze rule
      keys on content red, never on an unavailable proof (goal 24); the
      range grows and the chain retries within its bound.

Pre-implementation tree: red is the expected TDD signal; green required at
the integration gate / merge. Engine tree missing = ENV_FAIL exit 2.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_round_fixture as fx  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(t):
    print("\n%s" % t)


mod = fx.load_module()
section("module presence")
ok(mod is not None, "M0 develop_certify.py exists and imports"
   if mod else "M0 develop_certify.py missing (pre-implementation tree)")
if mod is None:
    sys.exit(1)
run_round = fx.round_entry(mod)
ok(run_round is not None, "M1 round entry present"
   if run_round is not None else
   "M1 round entry run_line_round missing (pre-implementation tree, TDD red)")
if run_round is None:
    sys.exit(1)

AT = 1700000000000
LINE = "default"
BASE, CULPRIT = "rev-base", "rev-culprit"

section("R red round: certification + freeze episode keyed to it")
root, ledger, guard = fx.round_fixture(mod)
fx.append(mod, ledger, [fx.landing_row("t-fix-carrier", BASE, AT - 2000)])
fx.append(mod, ledger, [mod.build_certification(
    fx.line_repos(BASE), fx.run_header("run-0", 5, 0), booked_red="br@0",
    judged_by="itg30", at_ms=AT - 1000, line=LINE)])
fx.append(mod, ledger, [fx.landing_row("t-x", CULPRIT, AT - 500)])

runner = fx.FakeRunner(headers=[fx.run_header("run-1", 9, failed=2)])
res = fx.round_call(mod, ledger, guard, runner, trigger="change", now_ms=AT,
                    lane_reds=["ldg-t-fix-carrier"])
rows, bad = mod.read_rows(str(ledger))
ok(not bad, "R0 ledger clean after the red round")
certs = [r for r in rows if r.get("kind") == mod.KIND_CERT]
ok(len(certs) == 2 and certs[-1].get("run") == "run-1",
   "R1a the red certification is recorded (a red cert is still a cert)")
freezes = [r for r in rows if r.get("kind") == mod.KIND_FREEZE]
ok(len(freezes) == 1, "R1b exactly one freeze episode opened")
if freezes and len(certs) == 2:
    ok(freezes[-1].get("cause") == certs[-1]["id"],
       "R1c the freeze's cause is the red certification's id")
    ok(not ({"state", "closure", "culprit"} & set(freezes[-1])),
       "R1d the episode body carries no mutable fields")
red_entry = [e for e in res.get("rounds", []) if e.get("verdict") == "red"]
ok(bool(red_entry) and red_entry[-1].get("freeze") == freezes[-1]["id"],
   "R1e the round's own face names the freeze it opened")
ok(bool(red_entry) and isinstance(red_entry[-1].get("next"), str),
   "R1f the round's face names the ladder's next step (goal 9, bounded "
   "escalation)")
st = mod.freeze_state(rows, LINE)
ok(st.get("frozen"), "R2a the line reads frozen from the records alone")
ok(st.get("cause") == certs[-1]["id"],
   "R2b the live freeze names its cause (the red cert)")

section("R2c the implicated candidate the red certified")
ok(len(runner.calls) == 1
   and runner.calls[0]["candidate"] == fx.line_repos(CULPRIT),
   "R2c the red round certified exactly the landings after the previous "
   "certification (the implicated range's head)")

section("F the freeze exemption is structural, and proof loss freezes nothing")
ok(mod.may_land(rows, LINE, "fix"),
   "F1a the structurally exempt fix kind still answers landable on a frozen "
   "line (goal 16/17)")
ok(not mod.may_land(rows, LINE, "chore"),
   "F1b a declared non-exempt kind (chore) answers NOT landable while "
   "frozen")
try:
    mod.may_land(rows, LINE, "fxi")
    undeclared_ok = False
except mod.CertifyError:
    undeclared_ok = True
ok(undeclared_ok,
   "F1c an undeclared (misspelled fix) kind is refused BY NAME, never "
   "silently deadlocked")
# proof loss after the red: growth rows, never a second freeze; the chain
# retries within its bound (the range stays open) and stops NAMED.
n_freezes = len(freezes)
# a fresh landing re-opens the derived range; the round's proof is then
# unavailable, so the chain retries growth rows within its bound
fx.append(mod, ledger, [fx.landing_row("t-y", "rev-y", AT + 900)])
res2 = fx.round_call(mod, ledger, guard,
                     fx.FakeRunner(error=mod.CouldNotRun("runner_dead")),
                     trigger="change", now_ms=AT + 1000,
                     lane_reds=["ldg-t-fix-carrier", "ldg-t-y"])
rows, _ = mod.read_rows(str(ledger))
ok(len([r for r in rows if r.get("kind") == mod.KIND_FREEZE]) == n_freezes,
   "F2a could-not-run opened NO second freeze")
ok(any(r.get("kind") == mod.KIND_RANGE_GROWTH for r in rows),
   "F2b could-not-run grew the range instead (goal 24)")
ok(res2.get("end", {}).get("state") == mod.END_CHAIN_LIMIT,
   "F2c the retry chain stops at its declared bound, named — never an "
   "unbounded loop")
g = mod.guard_acquire(guard, "itg30-f-probe")
ok(g is not None, "F2d the guard is released after the growth chain")
if g is not None:
    mod.guard_release(guard)

print("\nsummary: pass=%d fail=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
