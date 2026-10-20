#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_quickmanual_faces.py — quickmanual lane: builtin registration face + fixture
surface isolation + stage-chain contract (t261019-32, grey-box L2, read-only,
offline seconds, zero docker / zero Temporal / zero 3099).

intent (the user-perceivable behavior this entry owns):
  A. The NO-HALF-REGISTRATION invariant (arbitrate gen0 item 1): every id on the
     names face is also on the class face with the same class name — a names-only
     registration would let a ticket be accepted onto a workflow no worker runs.
     The quickmanual template is deliberately absent from both faces until its
     named step-0 amendment (names + display + default_gate_for + class face +
     generated yaml + guard widenings, one atomic step); the invariant holds
     before and after.
  B. The fixture template surface stays as is: with SANDBAR_FIXTURE_TEMPLATES unset the
     fixture id is invisible; with it set, the ONLY added id is `fixture-two-step` —
     and no half-registered id ever appears on either run.
  C. The stage chain is the design's chain and nothing else: open -> work ->
     run_integration_tests -> merge_check -> merge; none of create_plan /
     review_plan / design_integration_tests / arbitrate / acceptance_walkthrough /
     ui_evidence appears anywhere in the chain (a quick lane has no second role).
  D. The mandatory-evidence contract is present on the public input face:
     TicketInput carries a defaulted `evidence` field (existing tickets replay with
     the key missing; new quick tickets declare {kind, name}).
  E. Suite anti-drift: every live builtin template id appears in
     integration/run_scenarios.py — the narrowing-guard entries (t260904-08 /
     t260927-05 / t260924-04) must be widened to the new default face in the same
     change as any registration, or the suite silently asserts an outdated face.

Intent split (no duplication): the pure-function truth tables (evidence validator,
work_done intake, no-self-sign matcher) belong to developer L1
(server/engine/tests/test_quickmanual_lane.py per the plan); the default-face equality
assertions belong to the existing narrowing-guard scenarios themselves (updated in
place by the implement stage); this entry uniquely owns the cross-table agreement
face (A), the fixture-env delta face (B), the chain shape on the live class (C),
the public input field (D) and the suite anti-drift sweep (E).

Three states: engine interpreter missing / temporalio import failure = ENV_FAIL exit 2;
a broken assertion = exit 1; all green = exit 0. Pre-implement red is the expected
TDD signal; must be green at arbitrate/merge.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
from lib_gate import Fail, poc_python, require_bench  # noqa: E402

ENGINE = os.path.join(REPO, "server", "engine")
TID_QM = "quickmanual-lane"
FIXTURE_ID = "fixture-two-step"
CHAIN = ["open", "work", "run_integration_tests", "merge_check", "merge"]
BANNED = ["create_plan", "review_plan", "design_integration_tests",
          "arbitrate", "acceptance_walkthrough", "ui_evidence"]

PROBE_SRC = r'''#!/usr/bin/env python3
"""Read-only probe: dump the public registration faces as JSON."""
import json, os, sys

sys.path.insert(0, os.environ["PROBE_ENGINE"])
try:
    import workflows_v2  # noqa: F401  (import first: triggers the shared-face glue)
except ModuleNotFoundError as e:
    if "temporalio" in str(e):
        print("ENV_FAIL: engine interpreter lacks temporalio: %s" % e)
        sys.exit(2)
    raise
import shared

names = dict(shared.TEMPLATE_CLASS_NAMES)
display = dict(getattr(shared, "TEMPLATE_DISPLAY_NAMES", {}) or {})
classes = {k: getattr(v, "__name__", str(v)) for k, v in
           workflows_v2.TEMPLATE_CLASSES.items()}

# The chain shape is read from the LIVE CLASS (dev_lane), independent of the
# registration faces: the template's registration is the named step-0 amendment,
# and this entry must pin the class's shape both before and after it lands.
sys.path.insert(0, os.environ["PROBE_ENGINE"])
import dev_lane  # noqa: E402

stages = None
banned_in_chain = []
wf = getattr(dev_lane, "QuickmanualLaneWorkflow", None)
if wf is not None:
    stages = []
    for st in (getattr(wf, "STAGES", None) or ()):
        sid = getattr(st, "id", None) or (st.get("id") if isinstance(st, dict) else None)
        stages.append(str(sid) if sid is not None else str(st))
    low = [s.lower() for s in stages]
    banned_in_chain = [b for b in json.loads(os.environ["PROBE_BANNED"]) if b in low]

fields = {}
try:
    import dataclasses
    for f in dataclasses.fields(shared.TicketInput):
        req = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        fields[f.name] = {"required": req,
                          "type": str(f.type)}
except Exception as e:  # noqa: BLE001
    fields = {"_error": "%s: %s" % (type(e).__name__, e)}

print(json.dumps({"names": names, "display": display, "classes": classes,
                  "stages": stages, "banned_in_chain": banned_in_chain,
                  "input_fields": fields}, ensure_ascii=False))
'''


def run_probe(py, env_extra):
    env = dict(os.environ)
    env["PROBE_ENGINE"] = ENGINE
    env["PROBE_TID"] = TID_QM
    env["PROBE_BANNED"] = json.dumps(BANNED)
    env.update(env_extra or {})
    p = subprocess.run([py, "-c", PROBE_SRC], capture_output=True, text=True,
                       # SANCTIONED-WAIT: bounded client call, not a state wait
                       timeout=120, env=env)
    if p.returncode == 2 and "ENV_FAIL" in (p.stdout or ""):
        print(p.stdout.strip())
        sys.exit(2)
    if p.returncode != 0:
        print("ENV_FAIL: probe crashed rc=%d\n%s\n%s"
              % (p.returncode, (p.stdout or "")[-400:], (p.stderr or "")[-400:]))
        sys.exit(2)
    return json.loads((p.stdout or "").strip().splitlines()[-1])


def main():
    fail = Fail("quickmanual-lane faces (t261019-32, read-only)")
    stats = {"pass": 0}

    def check(cond, msg):
        r = fail.check(cond, msg)
        if r:
            stats["pass"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    if not os.path.isdir(ENGINE):
        print("ENV_FAIL: engine dir missing: %s" % ENGINE)
        sys.exit(2)

    # ---------- A: the NO-HALF-REGISTRATION invariant (arbitrate gen0 item 1) ----------
    base = run_probe(py, {"SANDBAR_FIXTURE_TEMPLATES": ""})
    names, classes, display = base["names"], base["classes"], base["display"]
    # every id on the names face is on the class face with the same class name:
    # a names-only id would let a ticket be accepted onto a workflow no worker
    # runs. True today (the quickmanual template is deliberately absent from both
    # faces pending its atomic registration) and true after it lands.
    half = sorted(n for n in names if classes.get(n) != names[n])
    check(half == [],
          "A no half registration: names-face ids all present on the class face "
          "with the same class name (mismatched=%r)" % half)
    check(all((not n.startswith("fixture")) or os.environ.get("SANDBAR_FIXTURE_TEMPLATES") == "1"
              or n not in names for n in (FIXTURE_ID,)),
          "A the fixture id is env-gated, never a plain builtin slot")

    # ---------- B: fixture surface stays as is ----------
    env_on = run_probe(py, {"SANDBAR_FIXTURE_TEMPLATES": "1"})
    delta = sorted(set(env_on["names"]) - set(base["names"]))
    check(delta == [FIXTURE_ID],
          "B SANDBAR_FIXTURE_TEMPLATES=1 adds exactly %r (got %r)"
          % ([FIXTURE_ID], delta))
    check(all(n not in env_on["names"] for n in half),
          "B no half-registered id appears with the fixture env either")

    # ---------- C: the stage chain is the design's chain ----------
    check(base["stages"] == CHAIN,
          "C the live class STAGES == open>work>run_integration_tests>merge_check>"
          "merge (got %r)" % (base["stages"],))
    check(base["banned_in_chain"] == [],
          "C no plan/review/test-design/arbitrate/walkthrough/ui_evidence stage "
          "(got %r)" % (base["banned_in_chain"],))

    # ---------- D: mandatory-evidence field on the public input face ----------
    flds = base["input_fields"]
    check("_error" not in flds and "evidence" in flds,
          "D TicketInput carries an `evidence` field (got %s)"
          % (sorted(flds)[:8] if "_error" not in flds else flds.get("_error")))
    if "evidence" in flds:
        check(flds["evidence"]["required"] is False,
              "D evidence is defaulted (existing tickets replay with the key missing)")

    # ---------- E: this ticket's own suite change kept the guards in step ----------
    # Scope: the BUILTIN ids only, observed through the ISOLATION seam: a probe with
    # SANDBAR_PROJECTS_DIR pointed at an empty registry returns the pure builtin face
    # (project-external ids merged by the per-project glue on this machine — e.g.
    # part-intake — are declared by their own projects and must not be required to
    # appear in this repo's suite).
    src_path = os.path.join(REPO, "integration", "run_scenarios.py")
    if not os.path.isfile(src_path):
        print("ENV_FAIL: scenario list missing: %s" % src_path)
        sys.exit(2)
    with open(src_path, encoding="utf-8") as f:
        suite_src = f.read()
    with tempfile.TemporaryDirectory(prefix="qm-faces-empty-registry-") as empty_reg:
        iso = run_probe(py, {"SANDBAR_PROJECTS_DIR": empty_reg})
    builtin = [tid for tid in sorted(iso["names"])
               if not tid.startswith("fixture")]
    missing = [tid for tid in builtin if tid not in suite_src]
    check(missing == [],
          "E every builtin template id appears in run_scenarios.py "
          "(the default-face guards were widened in the same change; "
          "builtin=%r missing=%r)" % (builtin, missing))

    fail.finish()


if __name__ == "__main__":
    sys.exit(main())
