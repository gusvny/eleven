#!/usr/bin/env python3
"""Guard against the four spec revisions and the FLOW_BRIEF clauses quietly
rolling back (merged guard) (10->3 guard merge, host-ordered t260902)."""
import subprocess
import sys

CMDS = ['node integration/t260902-12/test_yml_spec_landed.mjs', 'python3 integration/t260902-12/test_flow_brief_landed.py', 'python3 integration/t260902-12/test_project_agnostic.py']

ran = failed = 0
for c in CMDS:
    p = subprocess.run(["/bin/sh", "-c", c], capture_output=True, text=True, timeout=900)
    ran += 1
    print(("PASS" if p.returncode == 0 else "FAIL") + " :: " + c[:70], flush=True)
    failed += p.returncode != 0
print("GUARD ran=%d fail=%d" % (ran, failed))
sys.exit(1 if failed else 0)
