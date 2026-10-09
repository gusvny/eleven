#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100930_round_slot_chain_checkout.py — the round's single serial slot,
its chaining, its malformed-input refusals, and the delivered-checkout
boundary (t261009-30 spec (a slot)+(b)+(c), host order 261009, develop-buffer
goal 6 upfront constraint).

Run directly:
python3 integration/t261009-30/sc_t26100930_round_slot_chain_checkout.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + guard files on a tmp
store, fake injected runner, zero docker/Temporal/browser, never touches
3099. Judged through the public faces of server/engine/develop_certify.py
(the round entry run_line_round plus guard_acquire/guard_release/
should_certify/refuse_delivered_checkout).

User-perceivable contract this entry owns:

  S1  a round asked for while the serial slot is held JOINS the next one —
      no second run starts, no rows are written by the joining caller, the
      end face names the join, and once the slot frees the same ask runs.
  C1  rounds CHAIN (host order 261009): a landing recorded while a round
      runs is covered by the next round starting at once, inside the same
      tick, bounded by the declared chain limit; with nothing waiting the
      loop idles (no run, no rows).
  M1  malformed inputs fail LOUD and leave zero rows: a corrupt ledger line,
      an unknown trigger — never read as green, never silently skipped.
  M2  a runner returning garbage (not a run header) is the could-not-run
      face — range growth, never read as green — with the guard released.
  K1  the delivered checkout is untouchable: the module refuses, BY NAME, a
      runner pointed at the delivered checkout (the twice-bitten t261008-33
      incident class), including through a symlink alias.

Pre-implementation tree: red is the expected TDD signal; green required at
the integration gate / merge. Engine tree missing = ENV_FAIL exit 2.
"""

import os
import sys
import tempfile
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


def ledger_digest(path):
    p = Path(path)
    if not p.is_file():
        return b""
    return p.read_bytes()


_ALIAS_PARENTS = []


def _alias_dir():
    import atexit
    import shutil
    d = tempfile.mkdtemp(prefix="sandbar-itg30-alias-")
    _ALIAS_PARENTS.append(d)
    atexit.register(shutil.rmtree, d, ignore_errors=True)
    return os.path.join(d, "alias")


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

# ---- S1: the single serial slot --------------------------------------------
section("S single serial slot: a joining round starts nothing")
root, ledger, guard = fx.round_fixture(mod)
fx.append(mod, ledger, [fx.landing_row("t-s", "rev-s", AT)])
held = mod.guard_acquire(guard, "someone-else-round")
ok(held is not None, "S0 fixture: the slot is held by an in-flight round")
before = ledger_digest(ledger)
runner = fx.FakeRunner(headers=[fx.run_header("run-join", 3, 0)])
res = fx.round_call(mod, ledger, guard, runner, trigger="change", now_ms=AT)
ok(len(runner.calls) == 0,
   "S1a the joining round started NO run (never a second serial slot)")
ok(ledger_digest(ledger) == before,
   "S1b the joining round wrote ZERO rows")
ok(res.get("end", {}).get("state") == mod.END_JOINED
   and res.get("end", {}).get("reason") == "guard_held",
   "S1c the end face names the join (this tick joins the next one, it is "
   "not a silent drop)")
rows, _ = mod.read_rows(str(ledger))
go, why = mod.should_certify("change", rows, LINE, True)
ok(not go and why == "guard_held",
   "S1d the decision face names the held guard too")
mod.guard_release(guard)
res2 = fx.round_call(mod, ledger, guard, runner, trigger="change", now_ms=AT)
ok(len(runner.calls) == 1,
   "S1e once the slot frees, the round runs (the join became the next round)")

# ---- C1: chaining ------------------------------------------------------------
section("C chaining: a landing mid-round is covered by the next round at once")
chain, chain_ledger, chain_guard = fx.round_fixture(mod)
fx.append(mod, chain_ledger, [fx.landing_row("t-c0", "rev-c0", AT)])


landed = {"done": False}


def land_midround():
    if landed["done"]:
        return
    landed["done"] = True
    fx.append(mod, chain_ledger, [fx.landing_row("t-late", "rev-late",
                                                 AT + 10)])


# first proof unavailable (growth row keeps the range open), a landing
# arrives during the retry, second proof green: two rounds, one tick.
runner_chain = fx.FakeRunner(
    headers=[fx.run_header("run-c2", 4, 0)],
    error=mod.CouldNotRun("runner_cold"), error_once=True,
    side_effect=land_midround)
resc = fx.round_call(mod, chain_ledger, chain_guard, runner_chain,
                     trigger="change", now_ms=AT)
ok(len(runner_chain.calls) == 2 and len(resc.get("rounds", [])) == 2,
   "C1a while anything is still waiting the next round starts at once "
   "inside the same tick (the growth did not idle the loop; host order "
   "261009, bounded by the chain limit)")
rows_c, _ = mod.read_rows(str(chain_ledger))
rng = mod.derive_range(rows_c, LINE)
ok(not rng["covered_landings"],
   "C1b after the chain the derived range is empty again (nothing left "
   "waiting)")
certs_c = [r for r in rows_c if r.get("kind") == mod.KIND_CERT]
ok(len(certs_c) == 1 and certs_c[-1].get("run") == "run-c2",
   "C1c the chained round recorded ITS certification citing its own run "
   "(the growth round recorded a growth row, not a certification)")
ok(runner_chain.calls[-1]["candidate"] == fx.line_repos("rev-late"),
   "C1d the chained round's candidate is the line's head INCLUDING the "
   "mid-round landing")
# now nothing is waiting: the loop must go idle
runner_idle = fx.FakeRunner(headers=[fx.run_header("run-c3", 4, 0)])
resi = fx.round_call(mod, chain_ledger, chain_guard, runner_idle,
                     trigger="change", now_ms=AT)
ok(len(runner_idle.calls) == 0 and resi.get("end", {}).get("reason")
   == "range_empty",
   "C2 with nothing waiting the loop idles (no run, no rows)")
g = mod.guard_acquire(chain_guard, "itg30-c-probe")
ok(g is not None, "C3 the guard is released after the chain")
if g is not None:
    mod.guard_release(chain_guard)

# ---- M1: corrupt ledger / unknown trigger: loud, zero rows ------------------
section("M malformed inputs: named refusals, zero rows")
corrupt = fx.round_fixture(mod)
fx.append(mod, corrupt[1], [fx.landing_row("t-m", "rev-m", AT)])
with open(str(corrupt[1]), "a", encoding="utf-8") as fh:
    fh.write("{not json at all\n")
before_m = ledger_digest(corrupt[1])
try:
    fx.round_call(mod, corrupt[1], corrupt[2],
                  fx.FakeRunner(headers=[fx.run_header("run-m", 3, 0)]),
                  trigger="change", now_ms=AT)
    loud = False
except Exception as e:
    loud = "malformed" in str(e)
ok(loud, "M1a a corrupt ledger fails loud with the named reason, never "
   "reads as an empty line")
ok(ledger_digest(corrupt[1]) == before_m,
   "M1b zero rows written on the corrupt ledger (append never touches a "
   "ledger with malformed lines)")
ok(mod.guard_acquire(corrupt[2], "itg30-m-probe") is not None,
   "M1c the guard slot is free after the refusal (no ghost holder, KI-228 "
   "family)")
mod.guard_release(corrupt[2])

unknown = fx.round_fixture(mod)  # an EMPTY range: the refusal face
try:
    fx.round_call(mod, unknown[1], unknown[2],
                  fx.FakeRunner(headers=[fx.run_header("run-u", 3, 0)]),
                  trigger="whenever", now_ms=AT)
    unknown_refused = False
except Exception as e:
    unknown_refused = "trigger_unknown" in str(e)
ok(unknown_refused, "M3a an unknown trigger is refused by name")
rows_u, _ = mod.read_rows(str(unknown[1]))
ok(not any(r.get("kind") == mod.KIND_CERT for r in rows_u),
   "M3b no certification from an unknown trigger")
ok(mod.guard_acquire(unknown[2], "itg30-u-probe") is not None,
   "M3c the guard slot is free after the unknown-trigger refusal")
mod.guard_release(unknown[2])

# ---- M2: garbage runner output is could-not-run, never green ----------------
section("M2 garbage runner output: range growth, guard released")
garbage = fx.round_fixture(mod)
fx.append(mod, garbage[1], [fx.landing_row("t-g", "rev-g", AT)])
resg = fx.round_call(mod, garbage[1], garbage[2],
                     fx.FakeRunner(headers=[{"nonsense": True}]),
                     trigger="change", now_ms=AT, chain_limit=1)
rows_g, bad_g = mod.read_rows(str(garbage[1]))
ok(not bad_g, "M2a ledger clean after a garbage runner answer")
ok(any(r.get("kind") == mod.KIND_RANGE_GROWTH for r in rows_g)
   and not any(r.get("kind") == mod.KIND_CERT for r in rows_g),
   "M2b garbage runner output is could-not-run (range growth), never read "
   "as green")
ok(resg.get("rounds", [{}])[-1].get("state") == mod.STATE_GREW,
   "M2c the round's face names the growth")
ok(mod.guard_acquire(garbage[2], "itg30-g-probe") is not None,
   "M2d the guard is released after the growth")
mod.guard_release(garbage[2])

# ---- K1: the delivered checkout is untouchable ------------------------------
section("K the delivered checkout boundary (upfront constraint)")
DELIVERED = Path.cwd()
for label, tree in [("K1a the checkout itself", str(DELIVERED)),
                    ("K1b a symlink alias of it",
                     _alias_dir())]:
    if "alias" in tree:
        os.symlink(DELIVERED, tree)
    try:
        mod.refuse_delivered_checkout(tree, DELIVERED)
        refused = False
    except mod.CertifyError as e:
        refused = "tree_is_delivered_checkout" in str(e)
    ok(refused, label + " is refused BY NAME")
try:
    mod.refuse_delivered_checkout(str(Path(tempfile.mkdtemp())), DELIVERED)
    own_ok = True
except mod.CertifyError:
    own_ok = False
ok(own_ok, "K1c a tree of its own passes the refusal (the constraint is the "
   "delivered checkout, not running at all)")

print("\nsummary: pass=%d fail=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
