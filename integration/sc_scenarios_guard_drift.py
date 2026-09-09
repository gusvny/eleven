#!/usr/bin/env python3
"""Doc/lane vs code truth-source drift detection (merged guard) (10->3 guard
merge, host-ordered t260902).

Three-state classification (t260904-19 gen10, aligned with the pipeline guard
shell): a baseline exiting 2 = missing environment supply (e.g.
lane-stages-chain's behavior leg degrading in a worktree without a temporalio
venv) = ENV_FAIL, not product red — the old two-state version counted the
env_fail shape as fail, which made the guard shell's three-state counts
disagree (a live instance of KI proposal B, fixed by that ticket). The summary
exit code follows the suite priority: fail>0 -> 1, env_fail>0 -> 2, all green
-> 0.
"""
import subprocess
import sys

CMDS = ['node integration/baselines/lane-stages-chain.mjs', 'node integration/baselines/lane-yaml-chain.mjs', 'node integration/baselines/lane-readme-sync.mjs', 'node integration/baselines/lanediagram-removed.mjs']

ran = failed = env_failed = 0
for c in CMDS:
    p = subprocess.run(["/bin/sh", "-c", c], capture_output=True, text=True, timeout=900)
    ran += 1
    if p.returncode == 0:
        verdict = "PASS"
    elif p.returncode == 2:
        verdict = "ENV_FAIL"
        env_failed += 1
    else:
        verdict = "FAIL"
        failed += 1
    print(verdict + " :: " + c[:70], flush=True)
print("GUARD ran=%d fail=%d env_fail=%d" % (ran, failed, env_failed))
sys.exit(1 if failed else 2 if env_failed else 0)
