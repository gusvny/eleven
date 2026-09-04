#!/usr/bin/env python3
"""UT 工序与 verify test 道落地防回退（合并守卫）（10→3 合并守卫，t260902 宿主令）。"""
import subprocess
import sys

CMDS = ['python3 integration/t260902-10/test_verify_test_contract.py', 'python3 integration/t260902-10/test_ki015_whitelist.py', 'python3 integration/t260902-10/test_lane_declaration.py']

# 三态聚合（t260904-12）：子检 exit 2=ENV_FAIL 环境红（供给面）、exit 1=FAIL 产品红；
# 汇总退出码沿套件优先级：fail>0→1（产品红优先）、env_fail>0→2、全过→0。
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
