#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261022_12_handback_faces.py — quickmanual lane main-sync conflict handback:
per-lane conflict vocabulary on the shared main-sync helper (t261022-12, grey-box
L2, read-only offline seconds, zero docker / zero Temporal / zero 3099).

intent (the user-perceivable behavior this entry owns):
  A. The quickmanual lane has NO agent stage and none may be invented: the live
     class chain stays open > work > run_integration_tests > merge_check > merge
     with no `implement` anywhere (the measured fault was the shared conflict
     loop asking for a stage the template deliberately does not have).
  B. The per-lane vocabulary the handback contract is declared on public class
     attributes: the quickmanual lane hands a main-sync conflict back to its own
     working stage ("work"); the dev lane and the light lane keep the agent
     resolution step ("implement") — unchanged behavior where the stage exists.
  C. The change is replay-gated: the handback patch id exists, so histories that
     recorded the old command sequence replay unchanged.

Intent split (no duplication): the end-to-end conflict journey (create -> park ->
conflict -> handback reason content -> session resolves -> work_done -> lane
completes) is owned by sc_t261022_12_main_sync_handback (engine pool); developer
L1 owns the workflow-level stub matrices; this entry uniquely owns the live-class
vocabulary face and the chain shape after the change.

Three states: engine interpreter missing / temporalio import failure = ENV_FAIL
exit 2; a broken assertion = exit 1; all green = exit 0. Pre-implement red is the
expected TDD signal; must be green at arbitrate/merge.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
from lib_gate import Fail, poc_python, require_bench  # noqa: E402

ENGINE = os.path.join(REPO, "server", "engine")
CHAIN = ["open", "work", "run_integration_tests", "merge_check", "merge"]
BANNED = ["create_plan", "review_plan", "design_integration_tests",
          "arbitrate", "acceptance_walkthrough", "ui_evidence", "implement"]

PROBE_SRC = r'''#!/usr/bin/env python3
"""Read-only probe: dump the live per-lane conflict vocabulary as JSON."""
import json, os, sys

sys.path.insert(0, os.environ["PROBE_ENGINE"])
try:
    import workflows_v2  # noqa: F401  (import first: triggers the shared-face glue)
except ModuleNotFoundError as e:
    if "temporalio" in str(e):
        print("ENV_FAIL: engine interpreter lacks temporalio: %s" % e)
        sys.exit(2)
    raise
import dev_lane  # noqa: E402
import light_lane  # noqa: E402

def chain(cls):
    return [s.id for s in cls.STAGES]

def attr(cls, name):
    return getattr(cls, name, "<<absent>>")

qm = dev_lane.QuickmanualLaneWorkflow
dev = dev_lane.DevLaneWorkflow
light = light_lane.LightLaneWorkflow
out = {
    "qm_chain": chain(qm),
    "dev_chain": chain(dev),
    "qm_work_stage": attr(qm, "MAIN_SYNC_WORK_STAGE"),
    "dev_work_stage": attr(dev, "MAIN_SYNC_WORK_STAGE"),
    "light_work_stage": attr(light, "MAIN_SYNC_WORK_STAGE"),
    "dev_resolve_step": attr(dev, "MAIN_SYNC_RESOLVE_STEP"),
    "handback_patch_id": getattr(dev_lane, "MAIN_SYNC_CONFLICT_HANDBACK_PATCH_ID", "<<absent>>"),
}
print(json.dumps(out))
'''


def main() -> int:
    fail = Fail("t261022-12 main-sync handback vocabulary faces")
    stats = {"pass": 0}

    def check(cond, msg):
        r = fail.check(cond, msg)
        if r:
            stats["pass"] += 1
        return r

    bench = require_bench(fail)
    if bench is None:
        fail.finish()
        return 2
    py = poc_python(bench)

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix="_probe.py", delete=False) as f:
        f.write(PROBE_SRC)
        probe = f.name
    env = dict(os.environ)
    env["PROBE_ENGINE"] = ENGINE
    env["PYTHONPYCACHEPREFIX"] = os.path.join(REPO, "out", "pycache")
    p = subprocess.run([py, "-B", probe], env=env, capture_output=True,
                       text=True, timeout=300)  # SANCTIONED-WAIT: offline probe subprocess bound (seconds-scale, fail-closed on timeout)
    os.unlink(probe)
    if "ENV_FAIL" in (p.stdout or ""):
        print(p.stdout.strip())
        fail.bail("engine environment cannot import the engine modules: %s"
                  % (p.stdout or p.stderr).strip()[:200], 2)
    if p.returncode != 0:
        fail.bail("probe failed (environment): rc=%d %s"
                  % (p.returncode, ((p.stderr or "") + (p.stdout or ""))[:300]), 2)
    try:
        face = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        fail.bail("probe printed no JSON face: %r" % (p.stdout or "")[:200], 2)

    # A. the quickmanual chain stays agent-free
    check(face.get("qm_chain") == CHAIN,
          "A quickmanual chain is exactly %r (got %r)" % (CHAIN, face.get("qm_chain")))
    check(not (set(face.get("qm_chain") or []) & set(BANNED)),
          "A no agent/dev-only stage (incl. implement) sits in the quickmanual chain")
    # B. per-lane conflict vocabulary
    check(face.get("qm_work_stage") == "work",
          "B the quickmanual lane hands a main-sync conflict back to its own work "
          "stage (MAIN_SYNC_WORK_STAGE=%r)" % (face.get("qm_work_stage"),))
    check(face.get("dev_work_stage") in (None, "<<absent>>"),
          "B the dev lane keeps the agent resolution step (work stage override "
          "absent: %r)" % (face.get("dev_work_stage"),))
    check(face.get("light_work_stage") in (None, "<<absent>>"),
          "B the light lane keeps the agent resolution step too (got %r)"
          % (face.get("light_work_stage"),))
    check(face.get("dev_resolve_step") == "implement",
          "B the shared helper's agent step for dev/light stays 'implement' "
          "(got %r)" % (face.get("dev_resolve_step"),))
    # C. replay gate declared
    pid = face.get("handback_patch_id")
    check(isinstance(pid, str) and pid and pid != "<<absent>>",
          "C the handback sits behind a declared patch id (got %r)" % (pid,))

    print("t261022-12 handback faces: %d checks passed" % stats["pass"])
    fail.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
