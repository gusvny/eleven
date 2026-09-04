#!/usr/bin/env python3
"""文档/链路与代码真源漂移检测（合并守卫）（10→3 合并守卫，t260902 宿主令）。"""
import subprocess
import sys

CMDS = ['node integration/baselines/lane-stages-chain.mjs', 'node integration/baselines/lane-yaml-chain.mjs', 'node integration/baselines/lane-readme-sync.mjs', 'node integration/baselines/lanediagram-removed.mjs']

ran = failed = 0
for c in CMDS:
    p = subprocess.run(["/bin/sh", "-c", c], capture_output=True, text=True, timeout=900)
    ran += 1
    print(("PASS" if p.returncode == 0 else "FAIL") + " :: " + c[:70], flush=True)
    failed += p.returncode != 0
print("GUARD ran=%d fail=%d" % (ran, failed))
sys.exit(1 if failed else 0)
