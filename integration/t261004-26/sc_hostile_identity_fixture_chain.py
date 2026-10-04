#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_hostile_identity_fixture_chain.py — the caller-identity fixture discipline
holds end to end under a hostile inherited identity (t261004-26 B1, gray-box L3,
offline seconds, zero docker/ports/Temporal, never touches 3099/7233).

intent (reviewer-perceivable): the -0023 property mechanised for the whole
family — the tested surface is declared by the fixture and NEVER inherited.
An inherited SANDBAR_CALLER_PROJECT must not flip an identity-gated guard
scenario green->red, the single cleaning point must scrub identity like it
scrubs narrowing knobs (strip-then-inject: a fixture deliberately testing the
inherited path injects via extra and wins), and the L12 guard must SEE identity
(a spawn site with neither the cleaning point nor a call-scoped caller
declaration is red, named file).

Contract asserted (behavior, not implementation):
  A1 py cleaning point: under a hostile env (identity + narrowing knobs), the
     cleaned env carries NEITHER identity name; an explicit extra identity
     survives (strip-then-inject, the deliberate-test way out stays open);
  A2 mjs cleaning point: same contract on the node side;
  B  hostile-identity e2e: the two guard scenarios fixed on main (79e4cb6:
     refs-gate, write-set gate) run GREEN with a hostile foreign identity and a
     hostile narrowing knob inherited into their env (the regression property,
     driven from outside the fixtures, not by their own sub-cases);
  C  L12 sees identity: planted probe files under integration/ (reverted in
     finally) — C1 a naked spawn site turns lint red and the output NAMES the
     probe; C4 a comment-only `caller_project=` token never whitelists it;
     C2 a site routing through the cleaning point and C3 a site with
     caller_project inside the balanced spawn call are each accepted;
  D  residue: probes removed, lint back to baseline green (hygiene applies to
     this scenario too).

Three states: python/node absent across the declared chain = ENV_FAIL exit 2;
guard faces that depend on the t261004-26 implementation not yet landed = FAIL
named (TDD-phase red expected; arbitrate/merge must be green). Intent split:
lib_env L1 truth tables and the predicate unit cases belong to the developer
battery; the -0023 hostile sub-cases inside the two fixed scenarios belong to
79e4cb6; this entry pins the family chain from outside. Run directly:
python3 integration/t261004-26/sc_hostile_identity_fixture_chain.py (cwd=repo root).
"""
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
LINT = REPO / "integration" / "lint_tests.py"
LIB_PY = REPO / "integration" / "lib_env.py"
LIB_MJS = REPO / "integration" / "lib_env.mjs"
REFS_SC = REPO / "integration" / "t260904-18" / "sc_t260904_18_refs_gate.py"
WS_SC = REPO / "integration" / "t260915-04" / "sc_t260915_04_write_set_root_entry_gate.py"

FOREIGN = "t26foreign26"          # hostile caller identity (valid key shape, not ours)
HOSTILE = {
    "SANDBAR_CALLER_PROJECT": FOREIGN,
    "SANDBAR_CALLER_IDENTITY_SRC": "env",
    "SANDBAR_SCENARIO_ONLY": "server/plugins/entirely-unrelated/",
}
IDENTITY_NAMES = ("SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC")

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


def venv_py():
    # t260907-10 zero-residue: only the current engine venv path + sys.executable;
    # the pre-migration venv location is retired (CLAUDE.md rule 5) and no leg
    # for it may appear here.
    for c in ("server/engine/.venv/bin/python",):
        p = REPO / c
        if p.exists():
            return str(p)
    return sys.executable


def run(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=REPO, env=e, capture_output=True,
                          text=True, errors="backslashreplace", timeout=600)


def leg_a(side):
    """A1/A2: the declared cleaning point scrubs identity; extra wins."""
    if side == "py":
        code = (
            "import json,os,sys;sys.path.insert(0,'integration');import lib_env as L;"
            "hostile=L.clean_narrowing_env(base=dict(os.environ));"
            "declared=L.clean_narrowing_env({'SANDBAR_CALLER_PROJECT':'t26decl26'},"
            "base=dict(os.environ));"
            "knobs=L.inherited_narrowing_knobs(dict(os.environ));"
            "names=['SANDBAR_CALLER_PROJECT','SANDBAR_CALLER_IDENTITY_SRC'];"
            "print(json.dumps({'hostile':{k:hostile.get(k) for k in names},"
            "'declared':declared.get('SANDBAR_CALLER_PROJECT'),"
            "'knobs':sorted(knobs)}))")
        cmd = [venv_py(), "-c", code]
    else:
        code = (
            "import {cleanNarrowingEnv,inheritedNarrowingKnobs} from 'file://%s';"
            "const names=['SANDBAR_CALLER_PROJECT','SANDBAR_CALLER_IDENTITY_SRC'];"
            "const hostile=cleanNarrowingEnv({},process.env);"
            "const declared=cleanNarrowingEnv({SANDBAR_CALLER_PROJECT:'t26decl26'},process.env);"
            "console.log(JSON.stringify({hostile:Object.fromEntries(names.map(k=>[k,hostile[k]??null])),"
            "declared:declared.SANDBAR_CALLER_PROJECT,"
            "knobs:Object.keys(inheritedNarrowingKnobs(process.env)).sort()}))"
            % LIB_MJS)
        cmd = ["node", "--input-type=module", "-e", code]
    cp = run(cmd, env=HOSTILE)
    if cp.returncode != 0:
        ok(False, "A(%s) cleaning-point driver runs" % side, cp.stderr[-200:])
        return
    try:
        body = json.loads(cp.stdout.strip().splitlines()[-1])
    except Exception as exc:                                  # noqa: BLE001
        ok(False, "A(%s) output parses" % side, "%s | %r" % (exc, cp.stdout[-120:]))
        return
    for n in IDENTITY_NAMES:
        ok(body.get("hostile", {}).get(n) is None,
           "A(%s) hostile inherited identity scrubbed (%s absent)" % (side, n),
           body.get("hostile"))
    ok(body.get("declared") == "t26decl26",
       "A(%s) fixture-declared identity survives (strip-then-inject)" % side,
       body.get("declared"))
    ok(any(k.startswith("SANDBAR_SCENARIO_") for k in body.get("knobs", [])),
       "A(%s) inherited-knob diagnostic still names the knob" % side,
       body.get("knobs"))


def leg_b():
    """B: the two main-fixed guard scenarios stay green under hostile inheritance."""
    for label, sc in (("refs-gate", REFS_SC), ("write-set-gate", WS_SC)):
        if not sc.is_file():
            ok(False, "B %s scenario file present" % label, sc)
            continue
        cp = run([venv_py(), str(sc)], env=HOSTILE)
        ok(cp.returncode == 0,
           "B %s green under hostile inherited identity + hostile narrowing knob"
           % label,
           "rc=%s %s" % (cp.returncode, (cp.stdout + cp.stderr)[-200:]))


PROBE_NAKED = ("import subprocess, sys\n"
               "subprocess.run([sys.executable, 'integration/run_scenarios.py'])\n"
               "# caller_project=t26decl26   <- comment-only token must NOT whitelist\n")
PROBE_OK = ("import subprocess, sys\n"
            "from lib_env import clean_narrowing_env\n"
            "subprocess.run([sys.executable, 'integration/run_scenarios.py'],"
            " env=clean_narrowing_env())\n")
PROBE_DECL = ("import subprocess, sys\n"
              "subprocess.run([sys.executable, 'integration/run_scenarios.py'],"
              " caller_project='t26decl26')\n")


def leg_c_and_d():
    """C: planted probes bite (reverted in finally). D: residue green."""
    p1 = REPO / "integration" / "t26100426_probe_naked.py"
    p2 = REPO / "integration" / "t26100426_probe_ok.py"
    try:
        p1.write_text(PROBE_NAKED, encoding="utf-8")
        cp = run([sys.executable, str(LINT)])
        ok(cp.returncode != 0, "C1 naked spawn-site probe turns lint red",
           "rc=%s" % cp.returncode)
        ok("t26100426_probe_naked.py" in cp.stdout,
           "C1 red line names the probe file", cp.stdout[-300:])
        ok("t26100426_probe_ok.py" not in cp.stdout,
           "C1 clean probe not implicated", cp.stdout[-300:])

        p1.write_text(PROBE_DECL, encoding="utf-8")
        cp = run([sys.executable, str(LINT)])
        # Post-implement: caller_project INSIDE the balanced spawn call whitelists.
        ok("t26100426_probe_naked.py" not in cp.stdout,
           "C3 explicit caller_project inside the balanced call passes (L12 sees identity)",
           cp.stdout[-300:] or "lint rc=%s" % cp.returncode)

        p1.write_text(PROBE_NAKED)
        p2.write_text(PROBE_OK, encoding="utf-8")
        cp = run([sys.executable, str(LINT)])
        ok("t26100426_probe_ok.py" not in cp.stdout,
           "C2 probe routed through the cleaning point passes", cp.stdout[-300:])
    finally:
        for p in (p1, p2):
            p.unlink(missing_ok=True)
    cp = run([sys.executable, str(LINT)])
    ok(cp.returncode == 0, "D residue: probes removed, lint back to baseline green",
       cp.stdout[-200:])


def main():
    print("== t261004-26 hostile-identity fixture chain (B1 family)")
    if not LIB_PY.is_file() or not LIB_MJS.is_file():
        print("ENV_FAIL: cleaning point missing: integration/lib_env.py / lib_env.mjs")
        return 2
    leg_a("py")
    if run(["node", "--version"]).returncode != 0:
        print("ENV_FAIL: node missing (mjs cleaning-point sub-cases have no face)")
        return 2
    leg_a("mjs")
    leg_b()
    leg_c_and_d()
    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
