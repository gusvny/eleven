#!/usr/bin/env python3
"""Regression guard for the landed UT procedure and the verify-test lane
(merged guard) (10->3 guard merge, host-ordered t260902)."""
import subprocess
import sys

CMDS = ['python3 integration/t260902-10/test_verify_test_contract.py', 'python3 integration/t260902-10/test_ki015_whitelist.py', 'python3 integration/t260902-10/test_lane_declaration.py']

# Three-state aggregation (t260904-12): child check exit 2 = ENV_FAIL
# environment red (supply side), exit 1 = FAIL product red; the summary exit
# code follows the suite priority: fail>0 -> 1 (product red first),
# env_fail>0 -> 2, all green -> 0.
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
    if p.returncode != 0:
        # 失败尾段透传（t260910-14 arbitrate gen2）：子检查（test_lane_declaration
        # 的 pytest 走廊）偶发红时，无尾段则无法定位元凶 UT——透传子检查自报的
        # 结论行（含 rc 与原因尾串），让下一期闸直接点名；只加可见性，不动断言。
        tail = ((p.stdout or "") + (p.stderr or "")).strip().replace("\n", " | ")
        print("    tail[%s]: %s" % (c.split("/")[-1], tail[-500:]), flush=True)
print("GUARD ran=%d fail=%d env_fail=%d" % (ran, failed, env_failed))
sys.exit(1 if failed else 2 if env_failed else 0)
