#!/usr/bin/env python3
"""t260903-02 集成场景 t01：② 并行分叉的用户可感知契约锁（integration 设计，t260903-02）。

用户场景：泳道提速②——机械集成测试结果产出后，仲裁（arbitrate）与验收走查
（acceptance_walkthrough）并行分叉。用户可感知的故障面（本场景只锁契约承诺，
不锚实现细节）：
  A. 分叉边走 _run_agent_step/_enter 时若用 phase 值 "acceptance"（非 STAGES id）
     会让 _step raise「未知步骤」把 workflow 卡死（t260901-04 同款）——
     契约：新分支边名一律 STAGES id。
  B. tests-fault 时仲裁改的测试集必须先落账再重跑机械测试——契约：
     单点 settle 在 verdict 解析之前（否则重跑跑在未落账状态、blocked 时工作区留脏）。
  C. 仲裁非 pass 时并行走查结果作废必须留痕可解释——契约：分支内有「作废」timeline 文案。

跑法：python3 -B integration/t260903-02/sc_fork_contract.py（纯源码断言，零依赖零网络）。
契约基线 = 方案 v3（.suyou/stage_create_plan_gen2.json，review_plan gen2 通过）。
注意：本场景断言实现后状态——实现段完成前运行会红，集成道在 implement 之后跑才有效。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE.parents[1] / "server" / "dsh" / "temporal-poc" / "dev_lane.py").read_text("utf-8")

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


def section(t):
    print("\n== %s" % t)


def branch_body(phase_value):
    """抽取 `if phase == "<值>":` 到下一个同级 if phase 分支之间的分支体（找不到返回 None）。"""
    m = re.search(r'if phase == "%s":(.*?)(?=\n            if phase == )' % re.escape(phase_value),
                  SRC, re.S)
    return m.group(1) if m else None


section("A 分叉边名 = STAGES id（防未知步骤卡死）")
body = branch_body("arb_acc_parallel")
ok(body is not None, "arb_acc_parallel 分支存在且可抽取")
if body:
    ok(re.search(r'_run_agent_step\(\s*"acceptance"(?!_walkthrough)', body) is None,
       "边不走 phase 值 \"acceptance\" 调 _run_agent_step（_step 会 raise）")
    ok(re.search(r'_enter\(\s*"acceptance"(?!_walkthrough)', body) is None,
       "边不走 phase 值 \"acceptance\" 调 _enter（同款卡死面）")
    ok('"acceptance_walkthrough"' in body,
       "走查边以 STAGES id acceptance_walkthrough 表达")

section("B 单点 settle 先于 verdict 判定（测试集改动先落账）")
if body:
    i_settle = body.find("SettleLaneArgs(")
    i_parse = body.find("parse_arbitration_summary(")
    ok(i_settle >= 0, "新分支有单点 settle_lane 调用")
    ok(i_parse >= 0, "新分支有 verdict 解析")
    ok(0 <= i_settle < i_parse, "settle 调用位于 verdict 解析之前（时序承诺）")

section("C 非 pass 作废留痕（timeline 可解释）")
if body:
    ok("作废" in body, "tests-fault/code-fault 时走查结果作废有留痕文案")

print("\nt01 结果：pass=%d fail=%d" % (PASS, FAIL))
print("SUMMARY pass=%d skip=0 fail=%d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
