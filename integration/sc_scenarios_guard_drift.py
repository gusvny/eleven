#!/usr/bin/env python3
"""文档/链路与代码真源漂移检测（合并守卫）（10→3 合并守卫，t260902 宿主令）。

三态分类（t260904-19 gen10 对齐 pipeline 守卫壳）：baseline 退 2=环境缺供
（如 lane-stages-chain 在无 temporalio venv 的 worktree 的行为腿降级）=ENV_FAIL，
不是产品红——旧二态版把 env_fail 形态计成 fail=守卫壳三态计数不一致（KI 提案 B
的现存实例，本票修正）。汇总退出码沿套件优先级：fail>0→1、env_fail>0→2、全过→0。
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
