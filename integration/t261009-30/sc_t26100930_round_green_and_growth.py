#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100930_round_green_and_growth.py — the line round's green face and
its could-not-run face, plus the trigger/backstop wiring (t261009-30 spec
(a)+(d), develop-buffer goals 6/7/8/24).

Run directly:
python3 integration/t261009-30/sc_t26100930_round_green_and_growth.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + guard files on a tmp
store, fake injected runner (the module's declared dependency seam), zero
docker/Temporal/browser, never touches 3099. Judged through the public faces
of server/engine/develop_certify.py — the round entry run_line_round (one
invocation per tick, chained rounds inside it) plus derive_range / landable /
ticket_wait_state / should_certify. A contract-preserving refactor must stay
green.

User-perceivable contract this entry owns (one round per tick, not one per
lane attempt):

  G1  a green round runs ONCE against the line's head — per repository the
      HEAD revision across the landings after the line's previous
      certification — and appends exactly ONE certification row citing the
      run id (never restating counts/verdict).
  G2  after the green round the derived range is empty, the certified prefix
      is the candidate set, and the waiting landing answers
      ticket_wait_state=certified and landable — "may this land in main?"
      is answerable mechanically from recorded facts (goal 7/8).
  G3  the guard is RELEASED when the round ends (every terminal path) — the
      next tick is not pinned by a ghost holder (KI-228 family).
  C1  could-not-run: a runner that yields no usable header (raising
      CouldNotRun; a missing header; a run that executed nothing) records
      range growth and NO certification and NO freeze (goal 24), and the
      line still answers landable for the certified prefix.
  T1  the trigger wiring is should_certify: a change trigger over a
      non-empty range runs; an empty range ends the loop idle BY NAME and
      starts nothing; the backstop refuses before its window and, once
      elapsed, proves the line's head like any tick (an empty range under a
      backstop still idles — the round proves a candidate set, and there is
      none new).

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
ok(mod is not None, "M0 server/engine/develop_certify.py exists and imports"
   if mod else "M0 develop_certify.py missing (pre-implementation tree)")
if mod is None:
    print("FAIL: module missing; remaining faces unjudgeable")
    sys.exit(1)

run_round = fx.round_entry(mod)
ok(run_round is not None,
   "M1 the round entry (run_line_round) is present"
   if run_round is not None else
   "M1 round entry run_line_round missing (pre-implementation tree, TDD red)")
if run_round is None:
    print("FAIL: round entry missing; remaining faces unjudgeable")
    sys.exit(1)

AT = 1700000000000
LINE = "default"

# ---- G1/G2/G3: one green round on the line's head --------------------------
section("G green round: once per tick on the line's head, recorded, prefix grows")
root, ledger, guard = fx.round_fixture(mod)
prev_rev, head_rev = "rev-base", "rev-head"
fx.append(mod, ledger, [fx.landing_row("t-a", prev_rev, AT - 2000)])
fx.append(mod, ledger, [mod.build_certification(
    fx.line_repos(prev_rev), fx.run_header("run-0", 5, 0), booked_red="br@0",
    judged_by="itg30", at_ms=AT - 1000, line=LINE)])
fx.append(mod, ledger, [fx.landing_row("t-b", head_rev, AT - 500)])

runner = fx.FakeRunner(headers=[fx.run_header("run-1", 7, 0)])
res = fx.round_call(mod, ledger, guard, runner, trigger="change", now_ms=AT)
ok(len(runner.calls) == 1, "G1 exactly one run started (one round per tick)")
if runner.calls:
    cand = {r["repo"]: r["revision"] for r in runner.calls[0]["candidate"]}
    ok(cand == {"sandbar": head_rev},
       "G1b the candidate is the line's head (landings after the previous "
       "certification), not the whole line")
rows, bad = mod.read_rows(str(ledger))
ok(not bad, "G1c ledger clean after the round")
certs = [r for r in rows if r.get("kind") == mod.KIND_CERT]
ok(len(certs) == 2, "G1d exactly one certification row appended by the round")
if len(certs) == 2:
    ok(certs[-1].get("run") == "run-1",
       "G1e the certification CITES the run id (no counts/verdict restated)")
    ok(not ({"cases", "verdict", "counts"} & set(certs[-1])),
       "G1f the certification restates nothing from the run")
ok(res.get("end", {}).get("state") == mod.END_IDLE,
   "G1g the loop ends idle after the range closed (next trigger re-enters)")
rng = mod.derive_range(rows, LINE)
ok(not rng["covered_landings"], "G2 the derived range is empty after green")
ok(rng["certified_prefix"] == fx.line_repos(head_rev),
   "G2b the certified prefix is the round's candidate set")
landing = [r for r in rows if r.get("kind") == mod.KIND_LANDING
           and r.get("ticket") == "t-b"][-1]
st = mod.ticket_wait_state(rows, LINE, landing, lambda rid: rid == "run-1",
                           AT + 1000)
ok(st.get("state") == mod.WAIT_CERTIFIED,
   "G2c the waiting landing answers certified (goal 14)")
ok(mod.landable(rows, LINE, landing, lambda rid: rid == "run-1"),
   "G2d the landing answers landable — mechanical, no human memory (goal 7/8)")
g = mod.guard_acquire(guard, "itg30-after-round")
ok(g is not None, "G3 the guard is released when the round ends (next tick "
   "is not pinned by a ghost holder)")
if g is not None:
    mod.guard_release(guard)

# ---- C1: could-not-run grows the range, never freezes ----------------------
section("C could-not-run: unavailable proof -> range growth, no freeze")
for label, header, err in [
        ("C1a runner raises CouldNotRun", None,
         mod.CouldNotRun("run_header_missing")),
        ("C1b run executed nothing (ran==0)", fx.run_header("run-2", 0),
         None)]:
    root2, ledger2, guard2 = fx.round_fixture(mod)
    fx.append(mod, ledger2, [fx.landing_row("t-c", "rev-x", AT)])
    r2 = fx.FakeRunner(headers=[header] if header is not None else [],
                       error=err)
    fx.round_call(mod, ledger2, guard2, r2, trigger="change", now_ms=AT,
                  chain_limit=1)  # one round per invocation: the growth face,
    # not the chain-retry face (the retry face belongs to scenario 3)
    rows2, bad2 = mod.read_rows(str(ledger2))
    ok(not bad2, label + ": ledger clean")
    growth = [r for r in rows2 if r.get("kind") == mod.KIND_RANGE_GROWTH]
    ok(len(growth) >= 1, label + ": range-growth row(s) recorded (goal 24)")
    ok(not [r for r in rows2 if r.get("kind") == mod.KIND_FREEZE],
       label + ": NO freeze opened")
    ok(not [r for r in rows2 if r.get("kind") == mod.KIND_CERT],
       label + ": no certification recorded (nothing to cite)")
    rng2 = mod.derive_range(rows2, LINE)
    ok(len(rng2["covered_landings"]) == 1,
       label + ": the range still holds the landing (it grew, it did not "
       "certify)")
    g2 = mod.guard_acquire(guard2, "itg30-c-probe")
    ok(g2 is not None, label + ": guard released on the growth path")
    if g2 is not None:
        mod.guard_release(guard2)

# ---- T1: the trigger wiring is should_certify ------------------------------
section("T trigger wiring: change vs backstop decided by should_certify")
root3, ledger3, guard3 = fx.round_fixture(mod)
fx.append(mod, ledger3, [fx.landing_row("t-d", "rev-y", AT)])
go, why = mod.should_certify("change", mod.read_rows(str(ledger3))[0], LINE,
                             False)
ok(go and why == "range_non_empty",
   "T1a a change trigger over a non-empty range decides to run")
fx.round_call(mod, ledger3, guard3,
              fx.FakeRunner(headers=[fx.run_header("run-3", 4, 0)]),
              trigger="change", now_ms=AT)
rows3, _ = mod.read_rows(str(ledger3))
go, why = mod.should_certify("change", rows3, LINE, False)
ok(not go and why == "range_empty",
   "T1b an empty range refuses the change trigger by name")
runner3b = fx.FakeRunner(headers=[fx.run_header("run-4", 4, 0)])
res3 = fx.round_call(mod, ledger3, guard3, runner3b, trigger="change",
                     now_ms=AT)
ok(len(runner3b.calls) == 0 and res3.get("end", {}).get("reason")
   == "range_empty",
   "T1c no run started when the decision refuses (round honours the decision)")
# backstop: before the window it refuses; once elapsed the DECISION says yes,
# but the round is a run over the line's HEAD — an empty range still ends the
# loop idle BY NAME (there is no new revision set to prove; the certified
# prefix stays landable). The backstop's run happens over a non-empty range.
last = mod.derive_range(rows3, LINE)["previous_certification"]
go, why = mod.should_certify("backstop", rows3, LINE, False,
                             now_ms=last["at"] + 999, backstop_ms=1000)
ok(not go and why == "backstop_not_elapsed",
   "T1d backstop refuses before the window elapses")
go, why = mod.should_certify("backstop", rows3, LINE, False,
                             now_ms=last["at"] + 1000, backstop_ms=1000)
ok(go and why == "backstop_elapsed",
   "T1e backstop decision passes once the window elapses")
runner3c = fx.FakeRunner(headers=[fx.run_header("run-5", 2, 0)])
res3c = fx.round_call(mod, ledger3, guard3, runner3c, trigger="backstop",
                      now_ms=last["at"] + 1000, backstop_ms=1000)
ok(len(runner3c.calls) == 0
   and res3c.get("end", {}).get("reason") == "range_empty",
   "T1f a backstop over an empty range runs nothing (the round proves a "
   "candidate set, and there is none new)")
# and over a non-empty range the backstop round certifies like any tick
fx.append(mod, ledger3, [fx.landing_row("t-e", "rev-z",
                                        last["at"] + 1100)])
res3d = fx.round_call(mod, ledger3, guard3, runner3c, trigger="backstop",
                      now_ms=last["at"] + 1200, backstop_ms=1000)
rows3, _ = mod.read_rows(str(ledger3))
certs3 = [r for r in rows3 if r.get("kind") == mod.KIND_CERT]
ok(len(runner3c.calls) == 1 and len(certs3) == 2
   and certs3[-1].get("run") == "run-5",
   "T1g a backstop round over a non-empty range certifies, citing its run")

print("\nsummary: pass=%d fail=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
