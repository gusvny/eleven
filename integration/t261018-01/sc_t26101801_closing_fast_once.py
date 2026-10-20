#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101801_closing_fast_once.py — t261018-01: the develop-buffer closing
run is the DECLARED FAST SET, exactly once, and the release verdict reads it.

Grey-box L3, the real server/engine decision seam (dev_lane closing-face
planner + patch-id gates) and the real run_scenarios.py --print-fast-set
declaration face, offline seconds, zero docker/Temporal/browser, never touches
3099/7233.

intent (user-perceivable behaviour; truth source = ticket t261018-01 user
request + host order 261016 verbatim 「全量快集只在最后跑一次」/「只有快集，
永远没有全量跑」+ review_plan gen0 conditional comments 1 and 2):
    A. CLOSING = FULL FAST SET — the closing run's caliber is exactly the
       declared fast-set membership read from the ONE declared CLI face in
       this worktree (never a hand-kept second list, never the full suite).
    B. EXACTLY ONCE, UNAMBIGUOUS — the closing wiring says BY NAME that the
       run is the one closing run of the attempt and that the release verdict
       reads it, so a rework-then-repass ticket never leaves the release
       verdict pointing at an ambiguous run (review_plan comment 1).
    C. REFUSALS ARE NAMED, NEVER FULL — an empty member list, a REFUSED
       declaration, a query error, or malformed declaration output is a named
       refusal before any run; the full suite is never the fallback.
    D. LEGACY SURVIVES — the t261011-10 closing branch stays consulted for
       older histories (KI-061 replay discipline): the old patch id remains
       declared and the closing seam still gates on it.

Intent split (anti-duplication):
  · the CLI declaration/refusal faces themselves belong to t261009-16
    (this entry CONSUMES that face);
  · the gate-round scoped feedback face belongs to
    sc_t26101801_buffer_scoped_feedback;
  · the pure refusal truth tables belong to developer L1.

Pre-implement red is the expected TDD signal; green required at the
integration gate/merge. dev_lane unimportable = ENV_FAIL exit 2.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "server", "engine")
RUNNER = os.path.join(REPO, "integration", "run_scenarios.py")

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(("PASS" if cond else "FAIL") + " " + name +
          ((" — " + detail) if (detail and not cond) else ""), flush=True)
    if not cond:
        FAILURES.append(name)


sys.path.insert(0, ENGINE)
try:
    import dev_lane  # noqa: E402
except Exception as exc:
    print("ENV_FAIL: server/engine dev_lane unimportable: %r" % (exc,))
    sys.exit(2)

NEW_PATCH_ID = getattr(dev_lane, "DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID", None)
closing_plan = getattr(dev_lane, "closing_face_plan", None)

# A — the real declared face feeds the closing caliber
if not os.path.exists(RUNNER):
    print("ENV_FAIL: integration/run_scenarios.py missing")
    sys.exit(2)
# L25 wait-bound discipline (t261011-22): the query bound is injectable and
# seconds-scale; when it fires the failing check is NAMED, never a silent
# wall wait on a production-scale bound (override: FAST_SET_QUERY_TIMEOUT_S).
FAST_SET_QUERY_TIMEOUT_S = int(
    os.environ.get("FAST_SET_QUERY_TIMEOUT_S", "30"))
try:
    proc = subprocess.run(
        [sys.executable, RUNNER, "--print-fast-set"],
        capture_output=True, text=True, timeout=FAST_SET_QUERY_TIMEOUT_S)
except subprocess.TimeoutExpired:
    check("A declared fast-set face answers within the injectable query "
          "bound", False,
          "the %ss bound fired and named this check (override with "
          "FAST_SET_QUERY_TIMEOUT_S); the declaration query is an offline "
          "read and must answer in seconds" % FAST_SET_QUERY_TIMEOUT_S)
    print("checks=%d failures=%d" % (CHECKS[0], len(FAILURES)))
    sys.exit(1)
declared = [ln.strip() for ln in proc.stdout.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
check("A declared fast-set face yields a non-empty membership",
      proc.returncode == 0 and len(declared) > 0,
      "rc=%d stdout=%r" % (proc.returncode, declared[:3]))

if closing_plan is None:
    check("A closing_face_plan seam exists", False,
          "dev_lane.closing_face_plan missing (pre-implement red expected)")
    check("C refusal shapes probe runs", False, "planner missing")
else:
    plan = closing_plan(declared, "")
    check("A closing caliber is exactly the declared fast set",
          plan.run_only == sorted(set(n.strip() for n in declared if n.strip()))
          and plan.error == "",
          "got %r declared %r" % (plan.run_only[:5], declared[:5]))
    # A — the honest structural form: the face echoes its declared input set,
    # adds nothing, invents nothing.
    echoed = closing_plan(["fast-1", "fast-2"], "").run_only
    check("A the closing caliber echoes the declaration, adds nothing",
          echoed == ["fast-1", "fast-2"], "got %r" % (echoed,))

    # C — refusal shapes are named, never a full fallback
    for label, members, err in [
            ("empty members", [], ""),
            ("refused declaration", ["sc_x"], "declaration REFUSED"),
            ("query error", ["sc_x"], "query timed out"),
            ("malformed output", {"no": "members"}, ""),
            ("whitespace/None members", ["", None], "")]:
        out = closing_plan(members, err)
        check("C %s -> named refusal, no run" % label,
              out.run_only == [] and out.error.strip() != "",
              "got run_only=%r error=%r" % (out.run_only, out.error[:60]))

# B/D — wiring: once-per-attempt naming and the legacy gate survive
with open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8") as fh:
    src = fh.read()
lines = src.splitlines()
gates = [i for i, ln in enumerate(lines)
         if "workflow.patched(" in ln
         and "DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID" in ln]
check("B closing wiring is gated on the new patch id", bool(gates),
      "no gated closing site found")
gate_i = gates[0] if gates else -1
block = "\n".join(lines[gate_i:gate_i + 40]) if gates else ""
check("B the closing run is declared EXACTLY ONCE per attempt, by name",
      bool(gates) and ("once" in block.lower()),
      "gated closing block lacks the once-per-attempt statement")
check("B the release verdict reads the closing run",
      bool(gates) and ("verdict" in block.lower() or "closing" in block.lower()),
      "gated closing block does not name the verdict/closing face")
old_id = getattr(dev_lane, "DEV_BUFFER_FAST_PROOF_PATCH_ID", None)
check("D t261011-10 patch id still declared", bool(old_id),
      "DEV_BUFFER_FAST_PROOF_PATCH_ID missing")
check("D legacy closing seam still consulted in source",
      old_id in src and "workflow.patched" in src,
      "source lost the legacy gate")

print("checks=%d failures=%d" % (CHECKS[0], len(FAILURES)))
sys.exit(1 if FAILURES else 0)
