#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102619_round_only_red_judged.py — a round-only red no longer freezes
the line; a real assertion red still does (ticket t261026-19).

Run directly:
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B \
      integration/t261026-19/sc_t26102619_round_only_red_judged.py
(cwd = repo root).

Grey-box L3, offline seconds: the REAL develop_certify round entry over the
shared t261009-30 tmp delivery-ledger fixture (real append_rows/read_rows,
real flock, fake injected runner) and the REAL integration/line_round_runner
receipt face — zero docker/Temporal/browser, never touches 3099/7233.

Incident this entry owns (the five freezes of 2026-10-26 before noon): each
round produced exactly ONE content red whose own receipt names NO failing
assertion, `should_freeze` keyed on the relative new-regression count, so
every such round opened a freeze and blocked every landing until a human
thawed it. The distinguishing evidence — the case's receipt (FAIL_REASON /
assertion line) — sits in the run record but the judge never read it.

Contract under test (fail-closed):
  - a new-regression is CONTENT GUILT only when its receipt names a failing
    assertion; otherwise it is ROUND-ONLY: named on the certification, never
    green, and it opens NO freeze;
  - three consecutive round-only reds of the SAME case escalate to a freeze
    naming the case (the case is sick, not the revision); fewer, or
    interleaved cases, do not;
  - missing/unparseable receipt evidence fails CLOSED to the old behaviour
    (content guilt freezes); a legacy header without receipts freezes;
  - everything else unchanged: env-only red never freezes, a real assertion
    red freezes immediately.

Legs:
  A  THE INCIDENT SHAPE — one new-regression whose receipt names no assertion:
     round ends red, NO freeze episode, the round-only case is named with a
     count, the verdict never reads green.
  B  TEETH UNCHANGED — a receipt naming an assertion (reason assert_mismatch
     / an assertion line in the evidence) opens exactly one freeze.
  C  ENV-ONLY UNCHANGED — the t261024-30 shape still certifies without a
     freeze (regression guard against re-coupling the env face).
  D  FAIL-CLOSED — legacy header without fail_receipts freezes; an
     unparseable receipt (list/dict shapes) freezes; a regression name absent
     from the receipts map freezes; a present receipt with no assertion line
     never silently greens.
  E  ESCALATION — two consecutive round-only reds of one case open no freeze;
     the third does, naming the case; an interleaved different case resets
     the per-case streak.
  F  RUNNER RECEIPT FACE — line_round_runner lifts per-case receipts
     ({reason, evidence, status}) for fail/not-checked rows into the relayed
     header; an unreadable suite log degrades to an absent map (the judge
     then fails closed), never a fabricated clean receipt.

Pre-implementation tree: legs A/D/E/F red = the named TDD signal; green
required at the integration gate / merge. Engine tree or fixture missing =
ENV_FAIL exit 2.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "integration" / "t261009-30"))
sys.path.insert(0, str(ROOT / "integration"))
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


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


mod = fx.load_module()
if mod is None:
    env_fail("server/engine/develop_certify.py missing or unimportable")
run_round = fx.round_entry(mod)
if run_round is None:
    env_fail("run_line_round entry missing in develop_certify.py")

AT = 1700000000000
PROJECT = "itg2619-proj"
CASE = "sc-lane-map-mock-chrome"        # the 718578ef round's victim
CASE_OTHER = "sc-stale-cache-heal-journey"  # the 2c9b4f8e round's victim


def receipt(reason=None, evidence=None, status="fail"):
    """The receipt shape the REAL runner lifts (line_round_runner.fail_receipts):
    empty reason/evidence fields are DROPPED, so a receipt that names nothing
    is exactly {"status": "fail"} — never empty strings."""
    r = {"status": status}
    if reason is not None:
        r["reason"] = reason
    if evidence is not None:
        r["evidence"] = evidence
    return r


def round_only_header(rid, case=CASE):
    """The 718578ef shape: exactly ONE content red, its receipt carries NO
    failing assertion (no FAIL_REASON, no assertion line)."""
    return {"id": rid,
            "cases": {"ran": 720, "failed": 1, "env_failed": 0},
            "failed_names": [case],
            "unverified_names": [],
            "fail_receipts": {case: receipt()}}


def assertion_header(rid, case=CASE):
    """The same shape with a receipt that DOES name a failing assertion."""
    h = round_only_header(rid, case)
    h["fail_receipts"] = {case: receipt(
        reason="assert_mismatch",
        evidence="E           AssertionError: expected 3 got 4")}
    return h


def one_round(rid, header, root_ledger_guard=None, **kw):
    """One tick over a fixture ledger seeded with a landing, a green base
    certification and a second landing (the t261024-30 production-path
    shape: relative verdict, no main baseline -> new-regression set is the
    content fail set). When root_ledger_guard is given, the round runs on
    THAT store (consecutive-round legs) instead of a fresh fixture: a fresh
    landing is appended first, so the consecutive rounds are driven by the
    production change trigger — a ``manual`` round on a project line
    resolves the DECLARED branch tip (line_head_candidate, 261015) and
    idles named on a fixture without a lines.json declaration, which is not
    a drivable consecutive-round shape here."""
    manual = bool(kw.pop("manual", False))
    if root_ledger_guard is None:
        root, ledger, guard = fx.round_fixture(at_ms=AT)
        prev_rev, head_rev = "rev-base", "rev-head"
        fx.append(mod, ledger, [fx.landing_row("t-a", prev_rev, AT - 2000)])
        fx.append(mod, ledger, [mod.build_certification(
            fx.line_repos(prev_rev),
            {"id": "run-0", "cases": {"ran": 5, "failed": 0, "env_failed": 0},
             "failed_names": [], "unverified_names": []},
            booked_red="br@0", judged_by="itg2619", at_ms=AT - 1000,
            line="default")])
        fx.append(mod, ledger, [fx.landing_row("t-b", head_rev, AT - 500)])
        certs_before = 2 - 1  # the base cert is the only cert so far
    else:
        root, ledger, guard = root_ledger_guard
        # a fresh landing drives the next change round (the settle contract:
        # a round certifies what the line landed, in the records' order)
        fx.append(mod, ledger, [fx.landing_row("t-%s" % rid, "rev-%s" % rid,
                                               AT + sum(ord(c) for c in rid))])
        rows, _ = mod.read_rows(str(ledger))
        certs_before = len([r for r in rows if r.get("kind") == mod.KIND_CERT])
    runner = fx.FakeRunner(headers=[header])
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    try:
        res = fx.round_call(mod, ledger, guard, runner,
                            trigger="manual" if manual else "change",
                            now_ms=AT, project=PROJECT,
                            runs_store=str(root / "runs.jsonl"))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old
    rows, bad = mod.read_rows(str(ledger))
    return (root, ledger, guard), rows, bad, res, certs_before


def end_of(res):
    if isinstance(res, dict) and res.get("rounds"):
        return res["rounds"][-1]
    return {}


def certs_of(rows):
    return [r for r in rows if r.get("kind") == mod.KIND_CERT]


def kind_count(rows, kind):
    return len([r for r in rows if r.get("kind") == kind])


def round_only_names(entry):
    """The certification's round-only naming, wherever the contract puts it
    (the cert row, the round entry, or the cited run record)."""
    out = []
    for src in (entry.get("cert_row"), entry,
                (entry.get("relative") or {})):
        if not isinstance(src, dict):
            continue
        v = src.get("round_only") or src.get("round_only_names")
        if isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out


# ---- A: the incident shape --------------------------------------------------
section("A the five-freeze-day shape: a receipt-less red no longer freezes")
(store_a, rows_a, bad_a, res_a, before_a) = one_round(
    "run-ro-1", round_only_header("run-ro-1"))
ok(not bad_a, "A0 ledger readable after the round")
end_a = end_of(res_a)
ok(end_a.get("verdict") == "red" or end_a.get("state") == mod.STATE_RED,
   "A1 the round is still RED — round-only never silently green (end=%r)"
   % (end_a,))
ok(kind_count(rows_a, mod.KIND_FREEZE) == 0,
   "A2 NO freeze episode opens on a receipt-less red (got %d freeze rows)"
   % kind_count(rows_a, mod.KIND_FREEZE))
ok(len(certs_of(rows_a)) - before_a == 1,
   "A3 the round still books exactly ONE certification (got %d)"
   % (len(certs_of(rows_a)) - before_a))
named = round_only_names(end_a)
if not named:
    cert = certs_of(rows_a)[-1] if certs_of(rows_a) else {}
    named = round_only_names({"cert_row": cert})
ok(CASE in named,
   "A4 the certification names the round-only case BY NAME (named=%r)"
   % (named,))
cert_last = certs_of(rows_a)[-1] if certs_of(rows_a) else {}
serialized = repr(cert_last) + repr(end_a)
ok(CASE in serialized and ("round_only" in serialized
                           or "round-only" in serialized),
   "A5 the naming is a labeled round-only face, not a bare name list")

# ---- B: teeth unchanged ------------------------------------------------------
section("B a real assertion red still freezes immediately")
(store_b, rows_b, bad_b, res_b, before_b) = one_round(
    "run-assert-1", assertion_header("run-assert-1"))
ok(not bad_b, "B0 ledger readable")
end_b = end_of(res_b)
ok(end_b.get("verdict") == "red", "B1 the assertion red is red")
ok(kind_count(rows_b, mod.KIND_FREEZE) == 1,
   "B2 exactly ONE freeze episode opens on the assertion red (got %d)"
   % kind_count(rows_b, mod.KIND_FREEZE))

# ---- C: env-only unchanged (t261024-30 regression guard) ---------------------
section("C env-only red still never freezes")
env_header = {"id": "run-env-1",
              "cases": {"ran": 720, "failed": 0, "env_failed": 12},
              "failed_names": [],
              "unverified_names": ["sc-env-%02d" % i for i in range(12)]}
(store_c, rows_c, bad_c, res_c, before_c) = one_round("run-env-1", env_header)
ok(not bad_c, "C0 ledger readable")
ok(end_of(res_c).get("verdict") == "green",
   "C1 the env-only round certifies green (t261024-30 unchanged)")
ok(kind_count(rows_c, mod.KIND_FREEZE) == 0,
   "C2 no freeze on the env-only shape")

# ---- D: fail-closed on missing/unparseable evidence --------------------------
section("D fail-closed: missing or unparseable receipts are content guilt")
legacy = round_only_header("run-legacy-1")
del legacy["fail_receipts"]  # a legacy header predating the receipts face
(store_d1, rows_d1, bad_d1, res_d1, before_d1) = one_round(
    "run-legacy-1", legacy)
ok(not bad_d1, "D0 ledger readable")
ok(kind_count(rows_d1, mod.KIND_FREEZE) == 1,
   "D1 a header WITHOUT a receipts field freezes (old behaviour, "
   "got %d)" % kind_count(rows_d1, mod.KIND_FREEZE))

garbage = round_only_header("run-garbage-1")
garbage["fail_receipts"] = {CASE: ["not", "a", "dict"]}
(store_d2, rows_d2, bad_d2, res_d2, before_d2) = one_round(
    "run-garbage-1", garbage)
ok(kind_count(rows_d2, mod.KIND_FREEZE) == 1,
   "D2 an unparseable receipt (list shape) is content guilt (got %d)"
   % kind_count(rows_d2, mod.KIND_FREEZE))
garbage2 = round_only_header("run-garbage-2")
garbage2["fail_receipts"] = {CASE: {"reason": {"k": 1},
                                    "evidence": ["x"], "status": "fail"}}
(store_d3, rows_d3, bad_d3, res_d3, before_d3) = one_round(
    "run-garbage-2", garbage2)
ok(kind_count(rows_d3, mod.KIND_FREEZE) == 1,
   "D3 an unparseable receipt (dict-typed reason/list evidence) is content "
   "guilt (got %d)" % kind_count(rows_d3, mod.KIND_FREEZE))

absent = round_only_header("run-absent-1", case=CASE)
absent["failed_names"] = [CASE, CASE_OTHER]
absent["fail_receipts"] = {CASE: receipt()}  # CASE_OTHER has no receipt
(store_d4, rows_d4, bad_d4, res_d4, before_d4) = one_round(
    "run-absent-1", absent)
ok(kind_count(rows_d4, mod.KIND_FREEZE) == 1,
   "D4 a regression whose name is absent from the receipts map is content "
   "guilt (got %d)" % kind_count(rows_d4, mod.KIND_FREEZE))
nomix = round_only_names(end_of(res_d4))
if not nomix:
    c4 = certs_of(rows_d4)[-1] if certs_of(rows_d4) else {}
    nomix = round_only_names({"cert_row": c4})
ok(CASE in nomix and CASE_OTHER not in nomix,
   "D5 the same round names its round-only case and does NOT misname the "
   "content-guilty one (named=%r)" % (nomix,))

# ---- E: escalation ------------------------------------------------------------
section("E three consecutive round-only reds of the SAME case escalate")
store_e = one_round("run-esc-1", round_only_header("run-esc-1"))
ok(kind_count(store_e[1], mod.KIND_FREEZE) == 0,
   "E1 red one opens no freeze")
store_e = one_round("run-esc-2", round_only_header("run-esc-2"),
                    root_ledger_guard=store_e[0])
ok(kind_count(store_e[1], mod.KIND_FREEZE) == 0,
   "E2 red two still opens no freeze (two is not the signal)")
store_e = one_round("run-esc-3", round_only_header("run-esc-3"),
                    root_ledger_guard=store_e[0])
ok(kind_count(store_e[1], mod.KIND_FREEZE) == 1,
   "E3 red three escalates to exactly one freeze naming the case (got %d)"
   % kind_count(store_e[1], mod.KIND_FREEZE))
esc_rows = store_e[1]
freeze_rows = [r for r in esc_rows if r.get("kind") == mod.KIND_FREEZE]
# the record model puts the NAME on the escalation freeze's own attribution
# change record (the episode refuses mutable/culprit fields by schema), so
# the face that names the case is episode + its change rows
freeze_ids = {r["id"] for r in freeze_rows}
esc_change_rows = [r for r in esc_rows
                   if r.get("kind") == mod.KIND_FREEZE_CHANGE
                   and r.get("freeze") in freeze_ids]
ok(bool(freeze_rows)
   and CASE in repr(freeze_rows) + repr(esc_change_rows),
   "E4 the escalation freeze NAMES the sick case (case=%s)" % CASE)

section("E2 an interleaved different case resets the per-case streak")
store_f = one_round("run-mix-1", round_only_header("run-mix-1", case=CASE))
store_f = one_round("run-mix-2",
                    round_only_header("run-mix-2", case=CASE_OTHER),
                    root_ledger_guard=store_f[0])
store_f = one_round("run-mix-3", round_only_header("run-mix-3", case=CASE),
                    root_ledger_guard=store_f[0])
ok(kind_count(store_f[1], mod.KIND_FREEZE) == 0,
   "F1 three reds, no case three times in a row: NO escalation (got %d)"
   % kind_count(store_f[1], mod.KIND_FREEZE))

# ---- G: the runner lifts the receipts into the header -------------------------
def _receipt_legs(lrr, tmp):
    log = tmp / "suite.log"
    log.write_text(
        '{"name":"%s","status":"fail","reason":"assert_mismatch",'
        '"evidence":"AssertionError: x"}\n'
        '{"name":"sc-no-reason","status":"fail","reason":"","evidence":""}\n'
        '{"name":"sc-env-refused","status":"not-checked",'
        '"reason":"connect_refused","evidence":""}\n'
        '{"name":"sc-passed","status":"pass","reason":"","evidence":""}\n'
        'not json at all\n' % CASE, encoding="utf-8")
    try:
        lift = getattr(lrr, "fail_receipts", None)
    except AttributeError:
        lift = None
    if lift is None:
        ok(False, "G1 line_round_runner exposes a per-case receipt face "
                  "(fail_receipts) — NOT LANDED (the named TDD signal)")
    else:
        got = lift(str(log))
        ok(isinstance(got, dict) and CASE in got,
           "G1 the assertion case's receipt rides the face")
        ok(isinstance(got.get(CASE), dict)
           and got[CASE].get("reason") == "assert_mismatch",
           "G2 the receipt carries the reason verbatim (never a paraphrase)")
        ok(got.get("sc-no-reason") == {"status": "fail"},
           "G3 the receipt-less red is present with NO text fields (visible, "
           "never swallowed): %r" % (got.get("sc-no-reason"),))
        ok("sc-env-refused" in got,
           "G4 the not-checked env case is in the receipts face too "
           "(status distinguishes it at the judge)")
        ok("sc-passed" not in got,
           "G5 a passing case carries no receipt (the face is the red face)")
        ok(lift(str(tmp / "absent.log")) == {}
           or lift(str(tmp / "absent.log")) is None,
           "G6 an unreadable log degrades to an absent map — the judge then "
           "fails closed, never a fabricated clean receipt")


section("G the runner receipt face: per-case receipts ride the header")
try:
    import line_round_runner as lrr  # noqa: E402 (integration/ on sys.path)
except Exception as e:  # noqa: BLE001
    lrr = None
    print("  note: line_round_runner import failed: %s: %s"
          % (type(e).__name__, e))
if lrr is None:
    ok(False, "G0 integration/line_round_runner.py imports")
else:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="sandbar-itg2619-"))
    try:
        _receipt_legs(lrr, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
