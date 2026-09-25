#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260925-17 场景②：叉内路径闸拒 blocked 醒后重驱的源码锁（KI-120 离线面）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
离线秒级（零 docker 零 Temporal）锁 dev_lane 修复的**机制形状**，防回归三面——
  L1 唤醒复位纪律：dev_lane 内每一处「path_gate 闸拒 → _blocked」落点，其邻近
  窗口必须同时有 (a) workflow.patched 门（唯一 patch id 族，在飞票重放兼容——
  t260917-04 Nondeterminism 事故族的三修先例）与 (b) 被挡边的簿记复位
  （arb_done/impl_done/design_done = False 形）——缺任一＝醒后吃滞留簿记，
  KI-120 的「空 reason 稳态」结构性复发；
  L2 昂贵边保留：叉内闸拒复位不得连带清 walkthrough 边（acc_done/acc_res）——
  KI-024 语义：walkthrough 结果与闸无关，重跑是用户可感知的成本回归；
  L3 报错精确：闸拒 blocked 的 reason 必须带机读 path_gate_reason= 签名
  （票面点名卡因，「blocked 不得无因」的静态半边；动态半边归场景①）。

intent 分工：机制真值（复位后 pend 重算、授权上下文进新 prompt、重放兼容）归
场景①（真台旅程）与 developer L1（server/engine/tests UT 壳）——本条只锁源码
形状不变量，是防「改回去」的常驻闸，不替代行为面。窗口±80 行的邻近性判据是
灰盒绑定：断言落在「闸拒落点必须带门与复位」这一已三次事故背书的纪律上，
不锚 PATCH_ID 字面值与行号。dev_lane.py 缺席/不可读＝FAIL（TDD 信号）。
pool=ro（离线秒级）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DEV_LANE = os.path.join(REPO, "server", "engine", "dev_lane.py")
WINDOW = 80  # 邻近窗口（行）：闸拒落点与门/复位的最大距离

FAILS = []
CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append("%s：%s" % (name, detail))
        print("FAIL  %s — %s" % (name, detail))
    else:
        print("ok    %s" % name)


def main():
    if not os.path.isfile(DEV_LANE):
        print("FAIL  dev_lane.py 缺席：%s（TDD 信号）" % DEV_LANE)
        return 1
    with open(DEV_LANE, encoding="utf-8") as f:
        lines = f.readlines()

    # 落点扫描：_blocked( 落点且窗口内 (a) 含闸拒签名（settle 回执的机读键
    # path_gate_reason= 字面，或闸拒判定 helper settle_path_gate_refused——
    # 实现可收拢单点，两种形态都认）(b) 含 fork 簿记旗（arb_done/impl_done/
    # design_done）——两者同时在场才判定为「并行叉内的闸拒 blocked 落点」。
    # 串行段闸拒落点不含簿记旗（醒后主循环按 phase 原步重入、无 done 旗短路）
    # 不在本锁执法面——那正是 KI-120 的 differentiator，收窄是判据不是疏漏。
    def _gate_sig(win):
        return "path_gate_reason=" in win or "settle_path_gate_refused" in win \
            or "gate_refused(" in win

    # 锚定方式：以「闸拒条件行」为锚（if settle_path_gate_refused(...) /
    # error 带 path_gate_reason= 判定），分支 span＝条件行→本分支 continue；
    # span 内必须真有 _blocked( 落点（闸拒→blocked 的落点本体）。从 _blocked
    # 邻近反推会把同域的其它 blocked 出口（超限守卫/格式纠正等）误卷进执法面。
    COND_SHAPE = re.compile(
        r"if\s+.*?(settle_path_gate_refused|gate_refused)\s*\("
        r'|path_gate_reason="\s*in\s')
    gate_sites = []
    for j, ln in enumerate(lines):
        if not COND_SHAPE.search(ln):
            continue
        end = next((k for k in range(j, min(len(lines), j + 40))
                    if re.match(r"^\s*continue\b", lines[k])), None)
        if end is None:
            continue
        span_lines = lines[j:end + 1]
        if any("_blocked(" in x for x in span_lines):
            gate_sites.append((j, end, "".join(span_lines)))
    check("叉内闸拒落点在场", len(gate_sites) >= 1,
          "dev_lane 内未找到「path_gate 签名+fork 簿记旗」同窗的 _blocked 落点"
          "（扫描面失配？）")
    print("info  闸拒落点行：%s" % ([c + 1 for c, _e, _s in gate_sites],))

    RESET_SHAPE = re.compile(r"\b(arb_done|impl_done|design_done)\s*=\s*False\b")
    for cond_i, end_i, span in gate_sites:
        tag = "L%d" % (cond_i + 1)
        check("%s patched 门守分支" % tag,
              "workflow.patched(" in span,
              "闸拒分支（条件 L%d→continue L%d）内无 workflow.patched 门——在飞票"
              "重放兼容纪律（t260917-04 三修先例）失守" % (cond_i + 1, end_i + 1))
        check("%s 分支内醒后复位" % tag,
              bool(RESET_SHAPE.search(span)),
              "闸拒分支内无被挡边簿记复位（arb_done/impl_done/design_done = False）"
              "——醒后吃滞留簿记＝KI-120 复发形")
        check("%s 昂贵边保留" % tag,
              not re.search(r"\bacc_done\s*=\s*False\b", span)
              and not re.search(r"\bacc_res\s*=\s*None\b", span),
              "闸拒分支连带清了 acceptance 边（acc_done/acc_res）——walkthrough "
              "与闸无关，重跑=用户可感知成本回归（KI-024 语义破面）")

    # 对照面：既有的非闸拒复位出口（格式纠正/超限守卫）仍在——锁修复不拆旧纪律
    joined = "".join(lines)
    check("既有复位出口未被拆（格式纠正 t260905-10 形）",
          "arb_done = False" in joined,
          "dev_lane 内 arb_done=False 全族消失——既有出口被误拆")
    check("超限 KI-061 守卫仍在",
          "_blocked_over_limit" in joined,
          "KI-061 唤醒复位守卫被拆——超限 blocked 死锁回归面")

    print("\n%d checks, %d failed" % (len(CHECKS), len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
