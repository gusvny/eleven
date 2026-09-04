#!/usr/bin/env python3
"""UT 工序与 verify test 道落地防回退（合并守卫）（10→3 合并守卫，t260902 宿主令）。"""
import subprocess
import sys

CMDS = ['python3 integration/t260902-10/test_verify_test_contract.py', 'python3 integration/t260902-10/test_ki015_whitelist.py', 'python3 integration/t260902-10/test_lane_declaration.py']

ran = failed = 0
for c in CMDS:
    p = subprocess.run(["/bin/sh", "-c", c], capture_output=True, text=True, timeout=900)
    ran += 1
    print(("PASS" if p.returncode == 0 else "FAIL") + " :: " + c[:70], flush=True)
    failed += p.returncode != 0
print("GUARD ran=%d fail=%d" % (ran, failed))
sys.exit(1 if failed else 0)
