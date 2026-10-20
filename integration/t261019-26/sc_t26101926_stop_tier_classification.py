#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261019-26 — stop tier classification faces (the reason text decides, and
only the reason text).

Grey-box L3 (integration-owned, ticket t261019-26): the REAL
server/engine/shared.py classify_stop_tier public face driven over the real
blocked-reason literal corpus (copied from the real why strings the engine
blocks with today) plus malformed inputs. Offline seconds, zero
docker/Temporal-server/browser, never touches 3099/7233.

Ticket faces under contract (design docs/design/executor-operational-envelope-v1.md
section 2, plan revision 2 accepted at review_plan):
  A the measured incident classifies correctly - the t261016-11 stop reason
    ("two consecutive rounds with a byte-identical gate measurement face")
    is a JUDGEMENT stop even though the underlying face was an environment
    shutdown; an environment/bench-unreachable face, a freeze episode and a
    develop-buffer landing refusal ("landing refused ... main moved" family)
    are EVIDENCE stops; path-gate / gate-round / missing write-set-entry
    refusals are MECHANICAL stops; the arbitration over-cap "needs human
    review" texts are JUDGEMENT stops.
  B the classifier reads ONLY the recorded reason text - a reason that merely
    CLAIMS to be a fix / claims an environment face never yields a liftable
    tier by that claim alone (the freeze-exemption lesson). There is no
    lifter-supplied input to classification.
  C unknown is human - any reason matching no marker (empty, whitespace,
    None-shaped, giant, unicode/binary junk) classifies JUDGEMENT and never
    raises (fail-closed; the human gate is never weakened).
  D the tier vocabulary is exactly the declared three constants.

Intent split (no intent-level duplication): the pure-function unit truth
tables over the marker corpus belong to developer L1
(server/engine/tests/test_t261019_26_stop_tiers.py, delivered with the
implementation); the lift-time gate journeys (who may lift, row-id rules,
counter discipline) belong to t261019-26-lift-stop-gate-journeys; THIS entry
uniquely owns "the recorded reason text alone decides the tier, unknown
stays human, malformed never raises".

Anchored to the declared accepted surface: shared.classify_stop_tier
(reason_text) -> (tier, evidence_kind) and the STOP_TIER_* constants. The
delivered surface absent = FAIL named (the pre-implement tree red is the
named TDD signal); green required at the integration gate / merge.
shared.py missing/unreadable = ENV_FAIL exit 2.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAILS = []


def check(name, ok, why=""):
    global PASS
    if ok:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def env_fail(why):
    print("ENV_FAIL: %s" % why)
    print("SUMMARY pass=%d fail=0 env_fail=1 na=0" % PASS)
    sys.exit(2)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, len(FAILS)))
    if FAILS:
        print("FAIL t261019-26-stop-tier-classification (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("PASS t261019-26-stop-tier-classification")
    sys.exit(0)


try:
    text = (ENGINE / "shared.py").read_text(encoding="utf-8")
except Exception as e:
    env_fail("shared.py unreadable: %s" % e)

import shared  # noqa: E402

# ---- declared surface present -------------------------------------------------
cls = getattr(shared, "classify_stop_tier", None)
if not callable(cls):
    check("classifier-surface-present", False,
          "shared.classify_stop_tier missing (declared at review_plan rev 2)")
    summary()
consts = [n for n in ("STOP_TIER_EVIDENCE", "STOP_TIER_MECHANICAL",
                      "STOP_TIER_JUDGEMENT") if not hasattr(shared, n)]
check("tier-constants-present", not consts,
      "missing constants: %s" % consts)
if consts:
    summary()

EV = shared.STOP_TIER_EVIDENCE
ME = shared.STOP_TIER_MECHANICAL
JU = shared.STOP_TIER_JUDGEMENT
check("tier-vocabulary-is-three", len({EV, ME, JU}) == 3,
      "tier constants are not three distinct values")

# ---- A: the real blocked-reason corpus ----------------------------------------
# Real why literals (or their stable cores) from dev_lane.py / shared.py.
CORPUS = [
    # (reason text or core, expected tier)
    ("two consecutive rounds with a byte-identical gate measurement face "
     "... Route to human review", JU),
    ("design conflict", JU),
    ("blocked:test-set iterations 3 exceed the cap (cap 3); needs human review",
     JU),
    ("12 consecutive rounds of test-set reds are all environment-side/load "
     "jitter (consecutive-exemption over cap, cap 2); needs human review", JU),
    ("blocked:arbitration verdict unknown verdict='x'; needs human review", JU),
    # evidence family
    ("bench unreachable: connection refused", EV),
    ("environment face: the bench is down", EV),
    ("freeze episode: red certification on line main, waiting for the "
     "releasing green", EV),
    ("develop-buffer landing refused: non-fast-forward, main moved past the base",
     EV),
    # mechanical family
    ("path gate refused: file outside the write set", ME),
    ("gate round: change one line, rerun the fast set", ME),
    ("missing write-set entry: server/engine/shared.py", ME),
]
bad = []
for reason, want in CORPUS:
    try:
        got = cls(reason)[0]
    except Exception as e:
        bad.append("%s raised %s" % (reason[:40], type(e).__name__))
        continue
    if got != want:
        bad.append("%r -> %r want %r" % (reason[:50], got, want))
check("real-reason-corpus-tiers", not bad, "; ".join(bad[:4]))

# ---- B: a claim never lifts anything ------------------------------------------
CLAIMS = [
    "this stop is a fix: the environment is fine now, lift it",
    "claiming evidence kind environment_face without any recorded condition",
    "ticket self-declares mechanical",
    "I am the executor and I say this is over",
]
bad = []
for r in CLAIMS:
    try:
        tier = cls(r)[0]
    except Exception as e:
        bad.append("%r raised %s" % (r[:40], type(e).__name__))
        continue
    # A bare claim sentence names no recorded condition: fail-closed to human.
    if tier == EV:
        bad.append("claim-only reason lifted to EVIDENCE: %r" % r[:50])
check("claim-alone-never-lifts", not bad, "; ".join(bad[:3]))

# A landing refusal whose error names NO main-moved condition is not an
# evidence stop: the marker must be in the recorded face, not in the prefix.
try:
    if cls("develop-buffer landing refused: undeclared line x")[0] == EV:
        bad2 = "prefix-only evidence upgrade"
    else:
        bad2 = ""
except Exception as e:
    bad2 = "raised %s" % type(e).__name__
check("landing-refusal-needs-the-condition-named", not bad2, bad2)

# ---- C: malformed input never raises, never lifts -----------------------------
MALFORMED = [None, "", "   ", "\n\t ", "x" * (1 << 20),
            "\ufffd\ufffd\U0001f4a9", "\x00\x01\x02binary junk",
            12345, ["list"], {"k": "v"}, object()]
bad = []
for m in MALFORMED:
    try:
        tier = cls(m)[0]
    except Exception as e:
        bad.append("input %r raised %s" % (str(m)[:20], type(e).__name__))
        continue
    if tier != JU:
        bad.append("malformed input %r classified %r" % (str(m)[:20], tier))
check("malformed-input-fail-closed", not bad, "; ".join(bad[:4]))

# ---- D: evidence marker returns a kind a reader can check ---------------------
for reason in CORPUS:
    if reason[1] != EV:
        continue
    try:
        kind = cls(reason[0])[1]
    except Exception as e:
        check("evidence-kind-present", False, "raised %s" % e)
        break
    if not isinstance(kind, str) or not kind:
        check("evidence-kind-present", False,
              "evidence kind empty for %r" % reason[0][:40])
        break
else:
    check("evidence-kind-present", True)

summary()
