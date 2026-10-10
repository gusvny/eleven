#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-59 scenario: the production call site is WIRED (grey-box L3,
offline seconds, stdlib + importable engine modules only, zero
docker/Temporal-server/browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
the scheduled scan tick actually REACHES the line round in production — the
workflow body carries the replay-safe patched ask, and the activity it
executes is REGISTERED on the worker's single activity face, so the wiring
cannot silently decay into "a call to an activity nobody runs" (the exact
KI-01M4HBC9ANXZXQRDQR54Z9C0MZ form: mechanism landed, call site unclaimed).
This entry owns the WIRING faces the offline tick scenarios deliberately do
not bind (they drive the tick face with injected seams; this one pins that
the production graph connects):

- W1 registration: the activity the workflow executes
  (`line_round_tick_engine`) is present in `activities.ALL_ACTIVITIES` —
  an executed-but-unregistered activity is a runtime activity-not-found on
  every tick, i.e. a broken hook that spec (4) forbids.
- W2 the ask exists in the tick body: `DispatcherScanWorkflow.run`'s source
  carries the `workflow.patched(...)` ask for `LINE_ROUND_PATCH_ID` and
  produces the `line_rounds` result key (source-text pin — the deliverable
  of this ticket IS that this call exists; a rename must come back through
  review, not be absorbed here).
- W3 the patch id is a real, distinct patch id (non-empty string, not
  colliding with the other dispatcher-scan patch ids — replay safety
  depends on distinct ids).
- W4 registry sanity: every `ALL_ACTIVITIES` entry is a callable (the
  registration face must stay well-formed after the new line lands).

The engine modules import temporalio; without the engine venv this is
ENV_FAIL exit 2 (named), never a silent pass. Pre-wiring tree = FAIL named
(TDD signal).

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate).
"""
import inspect
import sys

ENGINE = "server/engine"
sys.path.insert(0, ENGINE)

try:
    import activities
    import workflows
except Exception as e:  # ENV_FAIL: named, never a silent pass
    print("ENV_FAIL: engine wiring modules unimportable "
          "(engine venv required): %s" % e)
    sys.exit(2)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def names(reg):
    out = []
    for a in reg:
        out.append(getattr(a, "__name__", "") or str(a))
    return out


def main():
    reg = activities.ALL_ACTIVITIES
    check("W4pre the registration face is a well-formed list of callables",
          isinstance(reg, list) and len(reg) > 0
          and all(callable(a) for a in reg), repr(names(reg)[:3]))

    # ---- W1: the executed activity is REGISTERED
    n = names(reg)
    check("W1 line_round_tick_engine is registered in ALL_ACTIVITIES "
          "(executed-but-unregistered = activity-not-found every tick)",
          "line_round_tick_engine" in n,
          "registered: %s" % [x for x in n if "round" in x or "scan" in x])

    # ---- W2: the ask exists in the tick body (source-text pin)
    src = inspect.getsource(workflows.DispatcherScanWorkflow.run)
    pid = getattr(workflows, "LINE_ROUND_PATCH_ID", None)
    check("W2a the workflow body asks under LINE_ROUND_PATCH_ID "
          "(workflow.patched present in run)",
          isinstance(pid, str) and "LINE_ROUND_PATCH_ID" in src
          and "workflow.patched(" in src, "")
    check("W2b the tick body produces the line_rounds result key",
          "line_rounds" in src, "")

    # ---- W3: the patch id is real and distinct (replay safety)
    others = [v for k, v in vars(workflows).items()
              if k.endswith("PATCH_ID") and k != "LINE_ROUND_PATCH_ID"
              and isinstance(v, str)]
    check("W3 LINE_ROUND_PATCH_ID is a non-empty id distinct from the "
          "other dispatcher-scan patch ids",
          isinstance(pid, str) and pid.strip() != "" and pid not in others,
          "id=%r others=%s" % (pid, others))

    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
