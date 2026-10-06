#!/usr/bin/env python3
"""sc_check_doc_mech_wiring.py — doc-face mechanical layer wiring + retirement
hygiene source-lock + pure replay (t261006-11, grey-box L2/L3 offline seconds,
zero docker/Temporal/browser, pure stdlib; temporalio-unimportable-safe,
sc_check_inspection_produce_chain pattern).

User-perceivable contract under test: the DAILY doc-face period (instance
docs-sync, scan_face=doc) now runs the mechanical layer and its findings land
in the SAME pipes as agent findings (verify/report/verdict/dedupe — design doc
section 3 "产出形态：四条管道只走一套"); and the RETIRED module stays retired
(its rules are re-carried narrowed/fixed in the new module, its header points
at the successor, and nothing in the live path wires the retired scanner).

Run: python3 integration/t261006-11/sc_check_doc_mech_wiring.py  (cwd=repo root)
Exit: 0 pass / 1 fail (named) / 2 env.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, "server", "engine")

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  FAIL %s" % label)


def read(rel):
    with open(os.path.join(ENGINE, rel), encoding="utf-8") as f:
        return f.read()


def main():
    print("== sc_check_doc_mech_wiring (t261006-11)")
    try:
        MECH = read("inspection_doc_mech.py")
        mech_present = True
    except FileNotFoundError:
        MECH = ""
        mech_present = False
    ok(mech_present, "successor module server/engine/inspection_doc_mech.py exists "
                     "(TDD-phase red expected until implement lands)")
    ACT = read("activities.py")
    FLOW = read("inspection_flow.py")
    RET = read("inspection_scan_doc.py")

    # ---- A: the doc-face period actually runs the mechanical layer ----
    ok("run_inspection_doc_mech" in ACT,
       "activity run_inspection_doc_mech registered in activities.py")
    ok("run_inspection_doc_mech" in FLOW or "doc_mech" in FLOW,
       "period flow invokes the mechanical layer for the doc face")
    # merge into the same pipes: mechanical findings must join the findings
    # payload that feeds verify_inspection_findings / write_inspection_report
    ok("doc_mech" in FLOW and ("verify_inspection_findings" in FLOW or "findings" in FLOW),
       "mechanical findings are merged into the inspect-stage findings payload (single-sourced pipes)")

    # ---- B: retired module stays retired ----
    import re
    retired_calls = [l.strip() for l in FLOW.splitlines()
                     if re.search(r"\brun_inspection_scan\s*\(", l)
                     and "run_inspection_scan_doc_mech" not in l]
    ok(not retired_calls,
       "retired run_inspection_scan is never CALLED in the live period flow "
       "(mentions must be comments/replay registration only) — calls=%s" % retired_calls[:2])
    ok("t261006-11" in RET or "inspection_doc_mech" in RET,
       "retirement header in inspection_scan_doc.py names its successor (ticket-updated)")
    ok("禁接线" in RET,
       "retirement header keeps the do-not-wire warning (legacy replay only)")

    # ---- C: rule coverage lock — all seven rule families declared in the module ----
    for fam in ("m1", "m2", "m3", "m4", "m5", "m6", "m7"):
        ok(fam in MECH.lower(), "module declares rule family %s" % fam.upper())
    ok("doc-exempt" in MECH,
       "explicit in-comment exemption form (<!-- doc-exempt: ... -->) implemented per design")

    # ---- D: pure replay — the module over this real repo returns the agent shape ----
    cli = os.path.join(ENGINE, "inspection_doc_mech.py")
    if os.path.exists(cli):
        p = subprocess.run([sys.executable, cli, "--repo-root", ROOT],
                           capture_output=True, text=True, timeout=120, cwd=ROOT)
        if p.returncode == 2:
            print("  ENV %s" % p.stderr[-200:])
            return 2
        ok(p.returncode == 0, "CLI over the real library exits 0 (err=%s)" % p.stderr[-200:])
        try:
            out = json.loads(p.stdout.strip().splitlines()[-1])
            findings = out.get("findings", [])
            bad = [f.get("scan") for f in findings
                   if f.get("severity") not in ("high", "med", "low")
                   or not f.get("id") or not f.get("evidence")]
            ok(not bad, "real-library findings carry the agent shape — bad=%s" % bad[:4])
        except (ValueError, IndexError) as e:
            ok(False, "CLI output is single-line JSON with findings+meta (%s)" % e)
    else:
        ok(False, "CLI exists for the real-library replay (red until implement)")

    print("\n%d ok / %d FAIL" % (PASS, FAIL))
    if FAILURES:
        print("FAIL named:")
        for f in FAILURES:
            print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
