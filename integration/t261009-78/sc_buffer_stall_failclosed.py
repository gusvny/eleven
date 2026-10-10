#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_buffer_stall_failclosed.py — "cannot tell" is never rendered as "fine"
(t261009-78, grey-box L2, offline seconds, zero docker/Temporal/browser).

intent (user-perceivable; ticket t261009-78 fail-closed discipline): a patrol
operator must never mistake a blind watchdog for a healthy fleet —
  A  no delivery ledger supplied -> the face says so BY NAME (a named
     cannot-run entry), it is never an empty/clean findings list;
  B  malformed ledger rows (a non-object row, a row of an unknown kind) are
     degraded BY NAME — no crash, and the affected face never reads as clean;
  C  the line HAS certifications but no run-verdict reader was supplied ->
     cert coverage is an explicit UNKNOWN (named), never assumed green into
     silence and never asserted uncovered into a false alarm;
  D  a malformed declaration (non-integer threshold) resolves to the default
     WITH a named per-key problem and the source surfaced — never silently;
  E  a patch-id-named relation while the patch-id map was not supplied is an
     honest named note about OUR blindness — not a dangling-target finding
     blaming the ledger;
  F  the new findings' copy is English (261004 STE rule) with data fields
     untranslated — no CJK ideographs or fullwidth punctuation on the face;
  G  the existing thrashing legs are untouched: the same quiet-ticket fixture
     that fires nothing above still fires rerun-rounds on a thrashing timeline
     (regression face for "existing semantics unchanged").

intent split: the per-input parse truth tables belong to developer L1; this
scenario owns the user-perceivable honesty contract of the findings face. The
machine-pin shape is out of scope and not asserted. Pre-implement tree red =
the expected TDD signal; green required at the integration gate / merge.
Engine module unimportable = ENV_FAIL exit 2.

Run directly (cwd = repo root):
  python3 integration/t261009-78/sc_buffer_stall_failclosed.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from lib_stall_harness import (  # noqa: E402
    NOW_MS, WINDOW_MS, blob, call_lane_findings, cert_row, check_outcomes,
    contract_fn, english_copy_ok, in_flight_facts, landing_row,
    load_watchdog, relation_row,
)

LINE = "line-main"


def main():
    lw, err = load_watchdog()
    if lw is None:
        print("ENV_FAIL: %s" % err)
        sys.exit(2)
    lane_findings, ferr = contract_fn(
        lw, ["lane_findings"], "the lane findings face")
    if lane_findings is None:
        print("FAIL: %s" % ferr)
        sys.exit(1)
    stall_facts_fn, serr = contract_fn(
        lw, ["stall_facts", "buffer_stall_facts", "facts_from_ledger",
             "ledger_stall_facts"],
        "the delivery-ledger facts builder (stall_facts)")
    if stall_facts_fn is None:
        print("FAIL: %s" % serr)
        sys.exit(1)
    resolve_thr, rerr = contract_fn(
        lw, ["resolve_stall_thresholds", "resolve_buffer_thresholds"],
        "the stall thresholds resolver")
    if resolve_thr is None:
        print("FAIL: %s" % rerr)
        sys.exit(1)

    tickets = [in_flight_facts("t-wait")]
    landing = landing_row("ldg-wait", "t-wait", LINE, NOW_MS - WINDOW_MS - 1)
    results = []

    def try_call(**kw):
        try:
            return call_lane_findings(lane_findings, tickets, **kw)
        except TypeError as exc:
            print("FAIL: lane_findings refuses the stall contract "
                  "(not landed): %r" % (exc,))
            sys.exit(1)

    # ---- A: no ledger supplied -> named cannot-run, never a clean fleet ----
    findings, meta = try_call()
    txt = blob(findings)
    ok = len(findings) > 0
    detail = "absent stall facts produced an EMPTY findings list (clean-fleet lie)"
    if ok and not ("ledger" in txt.lower() or "not supplied" in txt.lower()
                   or "cannot" in txt.lower()):
        ok = False
        detail = "findings present but none names the absent ledger: %s" % txt[:200]
    results.append(("A no ledger supplied is named, never read as clean",
                    ok, "" if ok else detail))

    # ---- B: malformed ledger rows degrade by name, no crash, no clean fleet -
    rows_bad = [
        "not-a-row",                                  # row not an object
        {"kind": "landing", "id": "ldg-bad", "at": NOW_MS},  # missing fields
        {"kind": "kind-from-the-future", "id": "x-1", "at": NOW_MS},
        landing,
    ]
    try:
        facts = stall_facts_fn(rows_bad, lines=[LINE])
    except Exception as exc:
        print("FAIL: stall_facts crashed on malformed rows instead of "
              "degrading by name: %r" % (exc,))
        sys.exit(1)
    notes_txt = blob(facts if isinstance(facts, dict) else {})
    findings, _m = try_call(stall_facts=facts)
    ok = len(findings) > 0 or bool(notes_txt.strip("{}[]"))
    detail = ("malformed rows left neither a named note nor any finding "
              "(face reads clean = fail-closed breach)")
    named = ("not-a-row" in notes_txt or "unknown" in notes_txt.lower()
             or "row" in notes_txt.lower())
    results.append(("B malformed ledger rows degrade by name", ok and named,
                    "" if (ok and named) else detail))

    # ---- C: certs exist but no run-reader -> explicit unknown, not silence --
    rows_c = [landing,
              cert_row("cert-1", LINE, NOW_MS - WINDOW_MS // 2)]
    facts_c = stall_facts_fn(rows_c, lines=[LINE])
    findings, meta_c = try_call(stall_facts=facts_c)   # no run-verdict reader
    face = blob(findings) + blob([meta_c])
    txt = face + blob(facts_c)
    covered_claimed = "covered" in txt.lower() and "unknown" not in txt.lower()
    ok = ("unknown" in txt.lower() or "coverage" in txt.lower()
          or "unverified" in txt.lower())
    detail = ("certs present without a run-reader: neither a named unknown nor "
              "any signal — face reads as fine (fail-closed breach)")
    if covered_claimed:
        ok = False
    results.append(("C cert coverage without a run-reader is an explicit "
                    "unknown", ok, "" if ok else detail))

    # ---- D: malformed declaration resolves to default WITH a named problem --
    try:
        resolved = resolve_thr({"cert_wait_overdue_min": "soon",
                                "freeze_without_remedy_min": -5})
    except Exception as exc:
        print("FAIL: thresholds resolver crashed on a malformed declaration "
                "instead of degrading by name: %r" % (exc,))
        sys.exit(1)
    thr = resolved[0] if isinstance(resolved, tuple) else resolved
    rest = resolved[1:] if isinstance(resolved, tuple) else ()
    rest_txt = blob(list(rest))
    ok = (isinstance(thr, dict)
          and isinstance(thr.get("cert_wait_overdue_min"), int)
          and isinstance(thr.get("freeze_without_remedy_min"), int)
          and ("default" in rest_txt.lower() or "problem" in rest_txt.lower()
               or "source" in rest_txt.lower()))
    detail = ("malformed declaration did not surface a named per-key fallback: "
              "resolved=%s rest=%s" % (thr, rest_txt[:200]))
    results.append(("D malformed declaration falls back by name with the "
                    "source surfaced", ok, "" if ok else detail))

    # ---- E: patch-named relation without the patch map = honest note --------
    rows_e = [relation_row("rel-p1", "repairs", "t-wait", "patch-deadbeef",
                           NOW_MS,
                           evidence={"what": "patch_id",
                                     "ref": "patch-deadbeef"}),
              landing]
    facts_e = stall_facts_fn(rows_e, lines=[LINE])   # no patch_ids supplied
    findings, _m = try_call(stall_facts=facts_e)
    txt = blob(findings)
    ok = "rel-p1" not in txt
    detail = "missing patch map still produced a dangling-target finding: %s" % (
        [f for f in findings if "rel-p1" in blob([f])])
    named = "patch" in (txt + blob(facts_e)).lower()
    results.append(("E missing patch map is a named note, not a dangling "
                    "finding", ok and named, "" if (ok and named) else detail))

    # ---- F: findings copy is English, data untranslated --------------------
    rows_f = [landing,
              relation_row("rel-d1", "withdraws", "t-wait", "ldg-nowhere",
                           NOW_MS)]
    facts_f = stall_facts_fn(rows_f, lines=[LINE])
    findings, _m = try_call(stall_facts=facts_f)
    ok, why = english_copy_ok(findings)
    ok = ok and bool(findings)
    results.append(("F new findings copy is English (no CJK on the face)",
                    ok, "" if ok else why))

    # ---- G: the existing thrashing legs are untouched ----------------------
    now = 1_790_430_000.0
    thrashing = in_flight_facts("t-thrash")
    thrashing.update({
        "suite_rounds": 4,
        "suite_entries": [now - 4 * 1800, now - 3 * 1800,
                          now - 2 * 1800, now - 1800],
        "verdict": "fail", "verdict_at": now - 900.0,
        "last_activity_at": now - 60.0,
    })
    findings, _m = lane_findings([thrashing], now_ts=now)
    toks = set()
    for f in findings or []:
        toks.update(str(l) for l in (f.get("legs") or []))
        if f.get("leg"):
            toks.add(str(f["leg"]))
    ok = "rerun-rounds" in toks
    detail = "thrashing timeline no longer fires rerun-rounds: toks=%s" % (
        sorted(toks))
    results.append(("G existing rerun-rounds leg unchanged", ok,
                    "" if ok else detail))

    check_outcomes(results)


if __name__ == "__main__":
    main()
