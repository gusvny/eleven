#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_guard_statement_level_faces.py — the two blind guards see their own target
(t261004-26 B3, gray-box L3, offline seconds, zero docker/ports/Temporal).

intent (reviewer-perceivable): request -0013 and the -0014 note — a guard that
matches a literal source shape cannot see the very defect it guards (the -23
fix WAS an extra wrapping parenthesis), and a text-blind term gate forces the
family's own docs/tests to contort to name a banned term. This entry pins:

  A  surrogate family anchor, clean tree: the declared guard entry
     (`integration/sc_emit_surrogate_guard.py`) runs green on the untouched
     tree (the anchor's baseline face; leg A/B black boxes ride along);
  B  statement-level predicate bites the -23 shape: through the declared pure
     predicate lib (`integration/lib_emit_anchor.py`) — a compliant print with
     backslashreplace is clean; the exact -23 wrap (one extra parenthesis pair)
     WITHOUT the fallback is red; the same wrap WITH the fallback is clean;
     a multi-line wrapped call is seen; a syntax-error input is fail-closed red
     NAMING the input (never a silent skip);
  C  L7 sanctioned mention: planted probe file under integration/ (reverted in
     finally) — an unmarked banned-term occurrence turns lint red naming the
     probe; the same occurrence on a `terminology-mention` marked line leaves
     the whole lint green AND the mention visible in the gate output (mentions
     listed for review, not silently swallowed); the term baseline file is
     byte-untouched by the whole leg;
  D  residue: probes removed, lint back to baseline green.

Intent split: the full predicate truth table (ALLOW entries, attribute-print
family, ensure_ascii variants) belongs to the developer L1 battery on the same
lib; the -0014 wording of the exemption list belongs to 79e4cb6; this entry
pins the guard-chain faces from outside. Pre-implement = FAIL named (TDD-phase
red expected; arbitrate/merge must be green). Run directly:
python3 integration/t261004-26/sc_guard_statement_level_faces.py (cwd=repo root).
"""
import hashlib
import importlib.util
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
GUARD = REPO / "integration" / "sc_emit_surrogate_guard.py"
LIB = REPO / "integration" / "lib_emit_anchor.py"
LINT = REPO / "integration" / "lint_tests.py"
BASELINE = REPO / "integration" / "terminology-baseline.json"
TERM_MARK = "terminology-mention"
# The banned term itself, so this file never carries a free CJK literal (the
# L15 copy-language gate owns that face); only the probe writes it.
TERM = "\u817f"

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok " + label)
    else:
        FAIL += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def run(cmd):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          errors="backslashreplace", timeout=600)


def leg_a():
    cp = run([sys.executable, str(GUARD)])
    ok(cp.returncode == 0, "A family anchor green on the clean tree (baseline face)",
       "rc=%s %s" % (cp.returncode, (cp.stdout + cp.stderr)[-200:]))


def predicate_fn():
    """Load the declared pure-predicate lib; find its (text, filename) entry."""
    if not LIB.is_file():
        return None
    spec = importlib.util.spec_from_file_location("lib_emit_anchor", LIB)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:                                  # noqa: BLE001
        ok(False, "B predicate lib loads", repr(exc))
        return None
    fns = [f for f in (getattr(mod, n) for n in dir(mod) if callable(getattr(mod, n)))
           if getattr(f, "__module__", None) == "lib_emit_anchor"
           and getattr(f, "__code__", None) and f.__code__.co_argcount == 2]
    return fns[0] if len(fns) == 1 else None


COMPLIANT = ('import json\n'
             'print(json.dumps(payload, ensure_ascii=False).encode("utf-8",'
             ' "backslashreplace").decode("utf-8"))\n')
WRAP_NO_FB = ('import json\n'
              'print((json.dumps(payload, ensure_ascii=False)))\n')
WRAP_FB = ('import json\n'
           'print((json.dumps(payload, ensure_ascii=False).encode("utf-8",'
           ' "backslashreplace").decode("utf-8")))\n')
WRAP_FB_MULTILINE = ('import json\n'
                     'print((\n'
                     '    json.dumps(payload, ensure_ascii=False)\n'
                     '    .encode("utf-8", "backslashreplace")\n'
                     '    .decode("utf-8")\n'
                     '))\n')
SYNTAX_ERR = 'def broken(:\n  print((json.dumps(x, ensure_ascii=False)))\n'


def leg_b():
    fn = predicate_fn()
    if fn is None:
        ok(False, "B pure predicate present (lib_emit_anchor, one 2-arg entry)",
           "lib missing or ambiguous")
        return
    ok(not fn(COMPLIANT, "compliant.py"), "B1 compliant exit (with fallback) is clean",
       fn(COMPLIANT, "c.py"))
    ok(bool(fn(WRAP_NO_FB, "wrap_nofb.py")),
       "B2 the -23 wrap (one extra parenthesis pair) WITHOUT fallback is red",
       fn(WRAP_NO_FB, "w.py"))
    ok(not fn(WRAP_FB, "wrap_fb.py"), "B3 the same wrap WITH fallback is clean",
       fn(WRAP_FB, "w.py"))
    ok(not fn(WRAP_FB_MULTILINE, "wrap_ml.py"),
       "B4 multi-line wrapped call with fallback is clean", fn(WRAP_FB_MULTILINE, "w.py"))
    v = fn(SYNTAX_ERR, "broken.py")
    ok(bool(v) and "broken.py" in str(v),
       "B5 syntax-error input fail-closed red naming the file (never a silent skip)", v)


def leg_c():
    baseline_sha = hashlib.sha256(BASELINE.read_bytes()).hexdigest()
    p = REPO / "integration" / "t26100426_probe_term.py"
    try:
        # CJK confined to the banned term itself: a free CJK comment would trip
        # the L15 copy-language gate instead of the L7 face under test.
        p.write_text("X = '%s'\n" % TERM, encoding="utf-8")
        cp = run([sys.executable, str(LINT)])
        ok(cp.returncode != 0, "C1 unmarked banned-term probe turns lint red",
           "rc=%s" % cp.returncode)
        ok("t26100426_probe_term.py" in cp.stdout, "C1 red line names the probe",
           cp.stdout[-300:])
        p.write_text("X = '%s'  # %s: sanctioned mention for this family's docs/tests\n"
                     % (TERM, TERM_MARK), encoding="utf-8")
        cp = run([sys.executable, str(LINT)])
        ok(cp.returncode == 0,
           "C2 marked mention is not counted (whole lint green with probe planted)",
           cp.stdout[-300:])
        ok(TERM_MARK in cp.stdout,
           "C2 marked mention visible in the gate output (listed, not swallowed)",
           TERM_MARK)
    finally:
        p.unlink(missing_ok=True)
    ok(hashlib.sha256(BASELINE.read_bytes()).hexdigest() == baseline_sha,
       "C3 term baseline file byte-untouched by the leg")


def main():
    print("== t261004-26 guard statement-level faces (B3)")
    leg_a()
    leg_b()
    leg_c()
    cp = run([sys.executable, str(LINT)])
    ok(cp.returncode == 0, "D residue: probes removed, lint back to baseline green",
       cp.stdout[-200:])
    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
