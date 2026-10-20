#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101801_buffer_scoped_feedback.py — t261018-01: the develop-buffer
gate-round feedback face is change-scoped, never the fast set, never full.

Grey-box L3, the real server/engine decision seam (dev_lane develop-buffer
planners and patch-id gates) driven over fixture shapes, offline seconds, zero
docker/Temporal/browser, never touches 3099/7233.

intent (user-perceivable behaviour; truth source = ticket t261018-01 user
request + host order 261016 verbatim 「应该只跑自己相关的，全量快集只在最后
跑一次」/「只有快集，永远没有全量跑」+ KI-01M551AR1XT01W9DNR2AN88B52):
    A. SHARED PATH STAYS SCOPED — the feedback face is structurally a function
       of scenario NAMES only: its signature takes no fast-set input and no
       mode input, so a change whose file set includes the shared runner path
       (integration/run_scenarios.py, the path that today yields surface
       mode=full) cannot widen the round to fast members or the full suite —
       the escalation levers do not exist on this face.
    B. UNION IS EXACT — the feedback set is exactly own ∪ prev-red: deduped,
       stable order, no fast-set member, nothing fabricated.
    C. ZERO SCENARIOS IS A NAMED SUPPLY REFUSAL — a round that assembles zero
       scenarios is refused BY NAME (carrying the KI id) BEFORE any run; the
       full suite is never the fallback; round-1 docs-only lands here too.
    D. NO FULL CALIBER IN THE WIRING — every gate site gated on the new patch
       id either consumes the scoped/closing planner or refuses; none of them
       constructs the full-suite caliber (an empty only_names run).
    E. VERSION GATE — the new behaviour lives behind its OWN patch id
       (KI-061: in-flight histories replay byte-identically), distinct from
       the t261011-10 fast-proof id and the surface-plan id.

Intent split (anti-duplication):
  · the per-round union own ∪ FAST members face of the OLD patch id belongs to
    sc_t26101110_fast_proof_membership (legacy replay; not re-asserted here);
  · the degraded/named refusal table of the old id belongs to
    sc_t26101110_proof_degradation_named;
  · the closing-run face belongs to sc_t26101801_closing_fast_once;
  · the planner unit truth tables (malformed inputs, whitespace names) belong
    to developer L1 (server/engine/tests/test_t261018_01_buffer_scoped_
    feedback.py).

Pre-implement red is the expected TDD signal; green required at the
integration gate/merge. dev_lane unimportable = ENV_FAIL exit 2.
"""
import inspect
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "server", "engine")

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

KI_SUPPLY = "01M551AR1XT01W9DNR2AN88B52"

NEW_PATCH_ID = getattr(dev_lane, "DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID", None)
scoped_plan = getattr(dev_lane, "scoped_feedback_plan", None)

# A — no escalation lever exists on the feedback face
if scoped_plan is None:
    check("A scoped_feedback_plan seam exists", False,
          "dev_lane.scoped_feedback_plan missing (pre-implement red expected)")
else:
    params = inspect.signature(scoped_plan).parameters
    check("A feedback face takes NO fast-set input",
          not any("fast" in p.lower() for p in params),
          "params=%r" % (list(params),))
    check("A feedback face takes NO caliber/mode input",
          not any(p.lower() in ("mode", "caliber", "full") for p in params),
          "params=%r" % (list(params),))

    # B — union is exactly own ∪ prev-red
    own = ["sc-b", "sc-a", "sc-a"]
    prev_red = ["sc-c", "sc-a"]
    names = scoped_plan(own, prev_red).run_only
    check("B union is exactly own ∪ prev-red, deduped, stable",
          names == ["sc-a", "sc-b", "sc-c"], "got %r" % (names,))
    check("B fast-set members can never enter (face has no fast input)",
          not any("fast" in n.lower() for n in names), "got %r" % (names,))

    # C — zero assembled scenarios = named supply refusal, never a run
    empty = scoped_plan([], [])
    check("C empty assembly is refused, not an empty run",
          empty.run_only == [] and empty.blocked_reason != "",
          "got %r" % (empty,))
    check("C refusal names the supply-side KI", KI_SUPPLY in empty.blocked_reason,
          "reason %r lacks KI id" % (empty.blocked_reason,))
    check("C round-1 docs-only shape lands on the same named refusal",
          scoped_plan([]).blocked_reason != "",
          "optional prev-red default missing")

# D — structural: no planner output can be the full-suite caliber
if scoped_plan is None:
    check("D no-full-caliber probe runs", False,
          "planner missing (pre-implement red expected)")
else:
    with open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    gates = [i for i, ln in enumerate(lines)
             if "workflow.patched(" in ln
             and "DEV_BUFFER_SCOPED_FEEDBACK_PATCH_ID" in ln]
    check("D new patch id gates at least one behaviour site", bool(gates),
          "no gated site found")
    for i in gates:
        # the gated region = the gate line plus a bounded window of its body
        # (the enclosing statement may span lines; a fixed window is enough to
        # see what the gate consumes and what it never builds)
        j = min(i + 1, len(lines))
        while j < len(lines) and j < i + 40:
            ln = lines[j]
            if ln.strip() and len(ln) - len(ln.lstrip()) < \
                    len(lines[i]) - len(lines[i].lstrip()):
                break
            j += 1
        block = "\n".join(lines[i:j])
        label = "D gate site @%d" % (i + 1)
        check(label + " consumes a planner or refuses",
              any(tok in block for tok in
                  ("scoped_feedback_plan", "closing_face_plan", "blocked_reason",
                   "refus")),
              "block has no planner/refusal consumption")
        check(label + " never builds the full-suite caliber",
              '"full"' not in block and "'full'" not in block,
              "block contains a full-caliber literal")

# E — version gate: new patch id exists and is distinct (KI-061)
ids = {
    "new": NEW_PATCH_ID,
    "fast-proof": getattr(dev_lane, "DEV_BUFFER_FAST_PROOF_PATCH_ID", None),
    "surface": getattr(dev_lane, "SURFACE_PLAN_PATCH_ID", None),
}
check("E new patch id declared", bool(ids["new"]), "missing constant")
check("E patch ids pairwise distinct",
      len({v for v in ids.values() if v}) == len([v for v in ids.values() if v]),
      "ids=%r" % (ids,))

print("checks=%d failures=%d" % (CHECKS[0], len(FAILURES)))
sys.exit(1 if FAILURES else 0)
