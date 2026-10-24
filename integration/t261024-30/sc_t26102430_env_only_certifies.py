#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102430_env_only_certifies.py — an env-only round certifies green,
unconditionally (ticket t261024-30 acceptance 1+3).

Run directly:
python3 integration/t261024-30/sc_t26102430_env_only_certifies.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + guard files on a tmp
store via the shared t261009-30 round fixture (real append_rows/read_rows,
real flock, fake injected runner), zero docker/Temporal/browser, never
touches 3099/7233.

Incident this entry owns (the four rounds 14:03/15:24/16:25/17:13 shape):
a run header whose ONLY failures are environment (failed == 0,
env_failed > 0) — the terminal face books red (its own stricter rule), the
run's content is clean, and the round must still book exactly ONE
certification, green, citing the run, with the env-unverified count named
on the round's receipt. Today the write is not unconditional on that path:
the round books a red cert or nothing, the line stays frozen and the
landing queue cannot move.

E1  THE INCIDENT SHAPE, POSITIVE — a header {ran:725, failed:0,
    env_failed:18, failed_names:[], unverified_names:[18 names]} ends the
    round with exactly ONE new certification row read back FROM THE LEDGER,
    citing the run id; the round's returned entry answers green and NAMES
    the env-unverified count (18).
E2  NO FREEZE, NO GROWTH — an env-only run opens no freeze episode (goal
    24: freeze keys on content red) and books no range growth: the run
    PROVED the content clean.
E3  REPLAY OF THE OLD SHAPE — the same header shape through a second,
    independent round books the same single record again (never zero,
    never two): the write is unconditional, not a one-shot accident.
E4  CONTENT RED STILL RED — the same shape with a real content failure
    (a regression name outside the unverified set) does NOT green: the
    content rule keeps its teeth.

Pre-implementation tree: red is the expected TDD signal; green required at
the integration gate / merge. Engine tree missing = ENV_FAIL exit 2.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "t261009-30"))
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


def env_only_header(rid):
    """The 16:25 round shape: content clean, environment failing, the
    unverified set published separately (the 261019 contract)."""
    return {"id": rid,
            "cases": {"ran": 725, "failed": 0, "env_failed": 18},
            "failed_names": [],
            "unverified_names": ["sc-env-unverified-%02d" % i
                                 for i in range(18)]}


def content_red_header(rid):
    h = env_only_header(rid)
    h["cases"]["failed"] = 1
    h["failed_names"] = ["sc-new-regression-one"]
    h["unverified_names"] = h["unverified_names"][:2]
    return h


mod = fx.load_module()
if mod is None:
    fx.env_fail("server/engine/develop_certify.py missing or unimportable")
run_round = fx.round_entry(mod)
if run_round is None:
    fx.env_fail("run_line_round entry missing in develop_certify.py")

AT = 1700000000000
PROJECT = "itg2430-proj"


def one_round(rid, header):
    """One tick over a fresh fixture ledger seeded with a landing, a green
    certification of the base revision and a second landing. The round runs
    on the PROJECT path (the production path: relative verdict rule) with
    the per-project store pointed at the fixture root — no main baseline
    can be established there, which is exactly the fail-closed branch the
    fix had to make env-only-green. Returns (rows_after, bad_lines,
    result, certs_before)."""
    root, ledger, guard = fx.round_fixture(at_ms=AT)
    prev_rev, head_rev = "rev-base", "rev-head"
    fx.append(mod, ledger, [fx.landing_row("t-a", prev_rev, AT - 2000)])
    fx.append(mod, ledger, [mod.build_certification(
        fx.line_repos(prev_rev),
        {"id": "run-0", "cases": {"ran": 5, "failed": 0, "env_failed": 0},
         "failed_names": [], "unverified_names": []},
        booked_red="br@0", judged_by="itg2430", at_ms=AT - 1000,
        line="default")])
    fx.append(mod, ledger, [fx.landing_row("t-b", head_rev, AT - 500)])
    base_rows, _ = mod.read_rows(str(ledger))
    certs_before = len([r for r in base_rows
                        if r.get("kind") == mod.KIND_CERT])
    runner = fx.FakeRunner(headers=[header])
    old = {k: os.environ.get(k) for k in ("SANDBAR_PROJECTS_DIR",)}
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    try:
        res = fx.round_call(mod, ledger, guard, runner, trigger="change",
                            now_ms=AT, project=PROJECT)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    rows, bad = mod.read_rows(str(ledger))
    return rows, bad, res, certs_before


def certs_of(rows):
    return [r for r in rows if r.get("kind") == mod.KIND_CERT]


def kind_count(rows, kind):
    return len([r for r in rows if r.get("kind") == kind])


def end_of(res):
    """The LAST round entry of the tick (the loop may chain on and end
    idle once the range is empty - the verdict lives on the round)."""
    if isinstance(res, dict) and res.get("rounds"):
        return res["rounds"][-1]
    return {}


section("E1 the incident shape: env-only run certifies green, unconditionally")
header1 = env_only_header("run-env-only-1")
rows, bad, res, certs_before = one_round("run-env-only-1", header1)
ok(not bad, "E1a ledger clean after the round")
certs = certs_of(rows)
ok(len(certs) - certs_before == 1,
   "E1b exactly ONE certification row appended by the round "
   "(got %d new)" % (len(certs) - certs_before))
if certs:
    ok(certs[-1].get("run") == "run-env-only-1",
       "E1c the certification cites the run id")
end = end_of(res)
ok(end.get("verdict") == "green" or end.get("state") == mod.STATE_CERTIFIED,
   "E1d the round's receipt answers green on the env-only shape "
   "(end=%r)" % (end,))
ok(header1.get("verdict_rule") == "relative-content-v1",
   "E1f the record SAYS WHICH RULE it used (verdict_rule=%r)"
   % (header1.get("verdict_rule"),))
receipt = (end.get("relative") or {}) if isinstance(end, dict) else {}
named = receipt.get("unverified") or end.get("unverified") or []
ok(header1.get("unverified_count") == 18,
   "E1e the run record NAMES the env-unverified count "
   "(unverified_count=%r)" % (header1.get("unverified_count"),))

section("E2 no freeze, no growth on an env-only run")
ok(kind_count(rows, mod.KIND_FREEZE) == 0,
   "E2a no freeze row on an env-only run (goal 24)")
ok(kind_count(rows, mod.KIND_RANGE_GROWTH) == 0,
   "E2b no range-growth row either: the run PROVED the content clean")

section("E3 replay of the old shape books the same single record, never zero")
rows2, bad2, res2, certs_before2 = one_round(
    "run-env-only-2", env_only_header("run-env-only-2"))
ok(not bad2, "E3a replay ledger clean")
ok(len(certs_of(rows2)) - certs_before2 == 1,
   "E3b the replay books exactly one record again (got %d)"
   % (len(certs_of(rows2)) - certs_before2))
ok(kind_count(rows2, mod.KIND_FREEZE) == 0,
   "E3c the replay opens no freeze")

section("E4 the content rule keeps its teeth")
rows3, bad3, res3, certs_before3 = one_round(
    "run-content-red-1", content_red_header("run-content-red-1"))
ok(not bad3, "E4a ledger clean")
end3 = end_of(res3)
ok(end3.get("verdict") == "red" or end3.get("state") == mod.STATE_RED,
   "E4b a real content failure is still red (end=%r)" % (end3,))
ok(kind_count(rows3, mod.KIND_FREEZE) == 1,
   "E4c a content red opens exactly one freeze episode")

print("\nSUMMARY pass=%d fail=%d env_fail=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
