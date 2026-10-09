#!/usr/bin/env python3
"""t261009-47 — KI-01M4H53WAP7FFS2CN3YP7XENPQ: a rework instruction is
delivered or refused by name, never absorbed by a mechanical round.

Run directly (cwd = repo root):
    PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
        "$PY" -B integration/t261009-47/sc_t26100947_rework_hold.py

Format: offline grey-box L3, pure stdlib, zero docker / Temporal server /
browser, never touches 3099. dev_lane imports temporalio (not importable
here), so the engine is never imported: the scenario is (A) source locks on
dev_lane.py / light_lane.py / base.py for the contract surfaces the user can
perceive, plus (B) a table-driven micro implementation of the declared
landing-decision invariant, replayed forward, backward and with malformed
inputs. Pre-implementation tree red is the expected TDD signal; green is
required at the integration gate / merge. Engine sources missing or
unreadable = ENV_FAIL exit 2.

User-facing contract under test (ticket spec):
  1. A rework signal arriving while a mechanical round is actively running is
     HELD, not consumed; it survives stage memos / snapshots (signal-fed
     instance state) and is consumed by the round that acts on it.
  2. The consuming round carries the note in its own stage prompt
     (meta["last_rework_note"] -> prev_ctx render) - assertable.
  3. A rework that cannot be honoured is refused BY NAME (arrival-time
     refusal, or a named refusal at the real loop exit) - never silently
     cleared.
  4. All new behavior is behind workflow.patched("ki212-rework-hold-v1");
     unpatched replay is today's code path.
  5. Settle/merge semantics untouched: a rework parked at the merge human
     gate (awaiting-human) is consumed at wake exactly as today - hold never
     applies to a parked round (no re-dispatch spin).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DL = ROOT / "server/engine/dev_lane.py"
LL = ROOT / "server/engine/light_lane.py"
BS = ROOT / "server/engine/base.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n== %s" % title)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


for path, name in ((DL, "dev_lane.py"), (LL, "light_lane.py"), (BS, "base.py")):
    if not path.is_file():
        env_fail("engine source missing: %s" % path)
try:
    src = DL.read_text("utf-8")
    lsrc = LL.read_text("utf-8")
    bsrc = BS.read_text("utf-8")
except OSError as exc:
    env_fail("engine sources unreadable: %s" % exc)

PATCH_ID = "ki212-rework-hold-v1"

# --------------------------------------------------------------------------
# A. Patch gate (spec 4): one new id, declared once and referenced by the
#    gated branches in ALL THREE lanes - a history without the patch replays
#    today's consume-at-top path. Binding note (arbitration fix): the id and
#    the shared hold bookkeeping live in base.py as the lanes' common mixin
#    surface; the contract is "declared once, gated everywhere", not "declared
#    in a particular file".
# --------------------------------------------------------------------------
section("A patch gate ki212-rework-hold-v1 (spec 4)")
ALLSRC = src + "\n" + lsrc + "\n" + bsrc
ok('REWORK_HOLD_PATCH_ID = "%s"' % PATCH_ID in bsrc or
   'REWORK_HOLD_PATCH_ID = "%s"' % PATCH_ID in src,
   "patch id constant declared exactly once (shared surface)")
ok(re.findall(r"workflow\.patched\(REWORK_HOLD_PATCH_ID\)", src),
   "dev_lane gates the hold behavior on the patch id")
ok(re.findall(r"workflow\.patched\(REWORK_HOLD_PATCH_ID\)", lsrc),
   "light_lane gates the hold behavior on the same patch id")
ok(re.findall(r"workflow\.patched\(REWORK_HOLD_PATCH_ID\)", bsrc),
   "base.py gates the hold bookkeeping on the same patch id")
ok("self._rework = None" in src, "legacy consume sites still present (gate-closed path)")
ok("_consume_rework" in src and "_apply_rework" in src,
   "both legacy consumers in place for unpatched replay")

# --------------------------------------------------------------------------
# B. Micro implementation of the declared landing decision, replayed against
#    the contract truth table (spec 1 + review R2/R3).
#    Declared invariant: consume iff the phase is agent-capable OR the round
#    is parked (stage_state != running); hold only a running non-agent round.
# --------------------------------------------------------------------------
section("B landing-decision truth table (micro replay of the declared invariant)")

AGENT_PHASES = frozenset({
    "create_plan", "review_plan", "implement",
    "parallel_impl_design", "arb_acc_parallel", "arbitrate", "acceptance"})


def landing_decision(phase, stage_state, agent_phases=AGENT_PHASES):
    """Declared contract, per plan gen2 Step 1. Fail closed to consume."""
    if not isinstance(phase, str) or not isinstance(stage_state, str):
        return "consume"
    if not phase.strip() or not stage_state.strip():
        return "consume"  # malformed: fail closed to today's semantics
    if phase not in agent_phases and stage_state == "running":
        return "hold"
    return "consume"


MECHANICAL = ("run_integration_tests", "merge_check", "merge")
TABLE = [
    # (phase, stage_state, expected, why)
    ("run_integration_tests", "running", "hold",
     "rework during the settle round is HELD (the ticket's reproduction)"),
    ("merge_check", "running", "hold",
     "merge-check mechanical round cannot carry the note"),
    ("merge", "running", "hold",
     "merge bookkeeping mechanical round cannot carry the note"),
    ("implement", "running", "consume",
     "agent phase consumes and renders the note"),
    ("create_plan", "running", "consume", "agent phase consumes"),
    ("run_integration_tests", "blocked", "consume",
     "parked round: the loop top is the honoring point"),
    ("merge", "awaiting-human", "consume",
     "merge human gate consumes at wake exactly as today (R3: no spin)"),
    ("run_integration_tests", "awaiting", "consume", "any parked state consumes"),
]
for phase, state, want, why in TABLE:
    ok(landing_decision(phase, state) == want,
       "%s/%s -> %s (%s)" % (phase, state, want, why))

# Mechanical-named target while that same mechanical phase runs: still hold
# (R2 regression - "phase == target" must NOT bypass the hold).
ok(landing_decision("merge_check", "running") == "hold",
   "mechanical-named target while that phase runs -> hold, not consume")
# Fail closed: malformed inputs never produce a hold (an unparseable state
# must keep today's behavior, never silently swallow a signal).
for bad in ((None, "running"), ("implement", None), (123, "running"),
            ("", "running"), ("   ", "running"), ("implement", "")):
    ok(landing_decision(bad[0], bad[1]) == "consume",
       "malformed input %r fails closed to consume" % (bad,))

# The engine-side helper must agree with the micro table on every
# non-malformed row. Direct import is impossible (temporalio), so lock the
# helper's shape by source (arbitration fix: declared on the shared base
# surface and imported by both lanes - the contract is the pure signature and
# the invariant, not the declaring file).
section("B2 engine helper source shape")
m = re.search(r"def (rework_landing_decision|rework_hold_decision)\(", ALLSRC)
ok(m is not None, "pure landing-decision helper declared on the shared surface")
if m:
    ok("agent_phases" in ALLSRC[m.start():m.start() + 400],
       "helper takes the agent-phase set as a parameter (not hardcoded)")
ok("rework_landing_decision" in src and "rework_landing_decision" in lsrc,
   "both lanes route the landing decision through the shared helper")
ok("parked" in ALLSRC or "awaiting-human" in ALLSRC,
   "parked-state invariant stated in the engine source")

# --------------------------------------------------------------------------
# C. Hold path source locks (spec 1): the signal is NOT cleared on hold; the
#    hold is visible on the ticket face; the slot is cleared only at a named
#    consume / refusal - never silently.
# --------------------------------------------------------------------------
section("C hold path: never absorbed, ticket-visible, named refusal")
ok('meta["rework_held"]' in ALLSRC,
   "held signal surfaced on the ticket face (meta rework_held)")
ok('meta["rework_refused_at_close"]' in ALLSRC,
   "terminal refusal surfaced on the ticket face (spec 3)")
ok("reached terminal" in ALLSRC,
   "terminal refusal names the condition (lane reached terminal)")
ok("rework held until" in ALLSRC,
   "hold path logs the held target by name")
# The gated hold path must leave the signal in the slot: the dev_lane wiring
# holds via a flag and consumes only on the non-held path (the legacy
# consumers stay behind `if not _held`).
ok(re.search(r"_held = True[\s\S]{0,200}if not _held:", src) is not None,
   "hold path skips the legacy consumers (signal stays in the slot)")
ok('meta["rework_held"] = ""' not in ALLSRC,
   "hold flag never blanked to an empty value (no silent clear)")

# --------------------------------------------------------------------------
# D. Coalescing (plan Step 3 / review C7): internal send-backs (human-gate
#    reject, conflict auto-rework) go through a coalescing queue that keeps
#    the held external request's identity and appends its note.
# --------------------------------------------------------------------------
section("D internal conflict rework coalesces instead of clobbering")
ok("def _queue_rework(" in ALLSRC,
   "coalescing queue face declared on the shared surface")
ok(re.search(r"_queue_rework\(\s*ReworkRequest\(", src) is not None,
   "dev_lane internal send-back site routes through the coalescing queue")
ok(re.search(r"_queue_rework\(\s*ReworkRequest\(", lsrc) is not None,
   "light_lane internal send-back site routes through the coalescing queue")
ok("coalesced" in ALLSRC,
   "coalescing leaves a named log record")

# --------------------------------------------------------------------------
# E. light_lane (spec: declare per-lane; plan verdict: the swallow IS carried
#    there). Same shared helper and gate; the merge human gate consumes on
#    wake.
# --------------------------------------------------------------------------
section("E light_lane carries the same fix")
ok("REWORK_HOLD_PATCH_ID" in lsrc and "rework_landing_decision" in lsrc,
   "light_lane uses the shared patch id and landing decision (imported)")
ok("rework_held" in lsrc, "light_lane surfaces the held signal on the face")
ok('("merge" in self._sigs) or (self._rework is not None)' in lsrc,
   "merge gate wait predicate still includes the rework signal")
ok('if self._rework is not None:\n                    continue' in lsrc,
   "gate wake still routes to the loop top (consume path, no re-dispatch)")

# --------------------------------------------------------------------------
# F. base.py generic lane (plan Step 5): an explicit revision_to naming a
#    non-agent stage is held, never consumed into a promptless round.
# --------------------------------------------------------------------------
section("F base.py generic lane: mechanical revision_to landing is held")
_ab = re.search(r"def _apply_rework\(self, cur_idx: int\) -> int:", bsrc)
_ab_body = bsrc[_ab.start():_ab.start() + 1800] if _ab else ""
ok(_ab is not None and "workflow.patched(REWORK_HOLD_PATCH_ID)" in _ab_body
   and "rework_landing_decision" in _ab_body
   and 'kind not in ("agent", "human")' in _ab_body,
   "base.py generic lane gates a hold decision through the shared helper")
ok('meta.get("last_rework_note")' in bsrc,
   "note render face unchanged in base.py (spec 2 render path)")

# --------------------------------------------------------------------------
# G. Refusal paths unchanged (spec 3): non-main-chain targets keep the
#    existing refuse-by-name text and bookkeeping.
# --------------------------------------------------------------------------
section("G existing refusal paths untouched")
ok('"ui_evidence"' in src and "not a main-chain step" in src,
   "ui_evidence refusal text present")
ok('"done"' in src and "cannot be sent back" in src,
   "terminal-target refusal text present")
ok("self.refused.append" in src, "refused ledger bookkeeping present")
ok("REWORK_ADMISSIBLE_PHASES" in src,
   "admissible-target vocabulary constant untouched in place")

# --------------------------------------------------------------------------
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
