#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260924-05 · KI-116：巡检套件零信号 + 超时三层错配的回归棒（L1 单测，零 IO）。

锁定四组契约（方案 v2 步3/步4 的不等式组与畸形输入用例）：
  A. 预算不等式组（四条）+ env 覆盖同抬（算式派生，非人守纪律）；
  B. 子进程 env 组装面：worker 路由旋钮/桩旋钮全剥除，显式注入面不吞；
  C. _run_scenarios 回执形状判定：畸形回执显式红，不落全零回执冒充绿；
  D. verify_lane integ 面：超时载荷解析 fail-closed；解析面零场景信号（含被拆除的
     「ran==0 且有规范行且 exit==0」静默逃逸口）一律显式 err。
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'tools'))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import inspection_flow as flow  # noqa: E402
import verify_lane as vl  # noqa: E402


# ---------------- A. 预算不等式组 ----------------

def test_inequality_group_default():
    """四条不等式：guard < INTEG_RUN_TO；guard < SUITE_TO；
    verify_lane 缺省超时 ≤ guard（第三层不得晚于内层守卫）；守卫 = BATCH+300。"""
    guard = timedelta(seconds=aa.INTEG_GUARD_SEC)
    assert aa.INTEG_GUARD_SEC == aa.BATCH_TIMEOUT_SEC + 300
    assert guard < dev_lane.INTEG_RUN_TO
    assert guard < flow.SUITE_TO
    assert vl.INTEG_DEFAULT_TIMEOUT_SEC <= aa.INTEG_GUARD_SEC


def test_derived_from_single_source():
    """外层预算必须**派生**自内层守卫（算式成对锁），不允许再手写常量。

    260927 更新：套件段活动超时 SUITE_TO 的算式**升级**（不是放宽）——
    旧式 `INTEG_GUARD_SEC + 1800`（缺省 5100s≈85min）被实测套件墙钟 87min 击穿
    （供给 ≈40min + 跑者 ≈47min），活动在跑者差约 2 分钟收尾时被判死，随即拆泳道、
    孤儿写盘撞 ENOENT、迟到回执覆盖权威件。新式 = 供给上限 + 跑者总预算 + 余量
    （见下方 test_suite_budget_* 三条新断言）；旧式的语义（「必须严格大于内层守卫」
    「必须是同一算出点的派生量」）由 test_inequality_group_default 与本函数保留。"""
    assert dev_lane.INTEG_RUN_TO == timedelta(seconds=aa.INTEG_GUARD_SEC + 300)
    assert flow.SUITE_TO == timedelta(seconds=flow.suite_timeout_of(
        flow.INTEG_SUPPLY_TO_SEC, flow.SUITE_RUN_BUDGET_SEC, flow.SUITE_MARGIN_SEC))
    # 旧式（guard+1800）已退役：这里显式钉住「新算式不是手写常量」——
    # 三项任一被改，SUITE_TO 必须跟着动（改常量不改算式=本行必红）。
    for _delta in (-60.0, 60.0):
        assert flow.suite_timeout_of(flow.INTEG_SUPPLY_TO_SEC,
                                     flow.SUITE_RUN_BUDGET_SEC + _delta,
                                     flow.SUITE_MARGIN_SEC) \
            != flow.SUITE_TO.total_seconds()


# ---------------- A2. 260927 套件段三段预算（供给 / 跑者 / 活动超时） ----------------

def test_suite_budget_three_stage_inequalities():
    """260927 新不等式组（旧断言只加不减）：
      INTEG_GUARD_SEC < 跑者总预算 < SUITE_TO
      供给上限 + 跑者总预算 + 余量 ≤ SUITE_TO
    三段必须同源派生——任何一处手写都会重新长出「活动比实际需要更早判死」的错配。"""
    guard = float(aa.INTEG_GUARD_SEC)
    budget = float(flow.SUITE_RUN_BUDGET_SEC)
    suite_to = flow.SUITE_TO.total_seconds()
    assert guard < budget < suite_to, (guard, budget, suite_to)
    assert (flow.INTEG_SUPPLY_TO_SEC + budget + flow.SUITE_MARGIN_SEC) <= suite_to
    # 供给段是**独立具名预算**：必须给足实测 40min 量级（不是 900s 单条上限冒充段预算）
    assert flow.INTEG_SUPPLY_TO_SEC >= 3600.0
    # 跑者总预算不低于实测量化基线（319 场景 sum(wall)=2630s，最慢单场景 310s）
    assert budget >= flow.MIN_SUITE_RUN_BUDGET_SEC >= 5400.0


def test_suite_run_budget_from_single_source():
    """跑者总预算算式唯一算出点 = suite_run_budget_of（派生自守卫，落地下限）：
    运维抬 SANDBAR_INTEG_BATCH_TIMEOUT_SEC 时预算自动同抬；往小调时不缩到截断真套件
    的地步（floor）。"""
    assert flow.SUITE_RUN_BUDGET_SEC == flow.suite_run_budget_of(aa.INTEG_GUARD_SEC)
    assert flow.suite_run_budget_of(6000.0) == 12000.0          # 抬守卫 → 同抬
    assert flow.suite_run_budget_of(100.0) == flow.MIN_SUITE_RUN_BUDGET_SEC  # 缩守卫 → floor
    # 显式投影入口与单一真源同值（旧调用面 `timeout − margin` 保留）
    assert flow.suite_run_budget_sec() == flow.SUITE_RUN_BUDGET_SEC


def test_inspection_chain_and_gate_outlive_runner_budget():
    """跑者必须**先于**闸内截止与活动超时收口（否则「点名收口」又变成「硬杀」）：
      跑者总预算 < 子进程链截止 < SUITE_TO；跑者总预算 < 闸内截止 ≤ SUITE_TO。
    闸内截止 = 供给 + 跑者 + 余量（闸只做上界，不替谁判预算）。"""
    budget = float(flow.SUITE_RUN_BUDGET_SEC)
    chain = aa.integ_subprocess_timeout(budget)
    gate = aa._inspection_gate_timeout(budget, flow.INTEG_SUPPLY_TO_SEC)
    suite_to = flow.SUITE_TO.total_seconds()
    assert budget < chain < suite_to, (budget, chain, suite_to)
    assert budget < gate <= suite_to, (budget, gate, suite_to)
    # 闸内截止 + 余量 = 活动超时（两数同源于同一组三段预算，不多出第四个手写数）
    assert gate + aa.INTEG_CHAIN_MARGIN_SEC <= suite_to
    # 每票集测段（预算缺省 0）逐字回落旧行为：链截止 = 内层守卫、闸截止 = 内层守卫
    assert aa.integ_subprocess_timeout(0.0) == float(aa.INTEG_GUARD_SEC)
    assert aa._inspection_gate_timeout(0.0, 0.0) == float(aa.INTEG_GUARD_SEC)


def test_env_override_single_knob(monkeypatch):
    """运维覆盖 SANDBAR_INTEG_BATCH_TIMEOUT_SEC：单点函数随 env 同抬（派生链同一
    算出点，覆盖即三处同抬——「覆盖时须同步抬高 dev_lane.INTEG_RUN_TO」的人守纪律
    退役）。"""
    monkeypatch.setenv("SANDBAR_INTEG_BATCH_TIMEOUT_SEC", "600")
    assert aa.integ_batch_timeout_sec() == 600
    monkeypatch.delenv("SANDBAR_INTEG_BATCH_TIMEOUT_SEC", raising=False)
    assert aa.integ_batch_timeout_sec() == 3000


def test_verify_lane_timeout_payload_parsing(monkeypatch):
    """超时三级回落（arbitrate gen1 发现 3）：载荷 integ_timeout_sec → env
    SANDBAR_INTEG_BATCH_TIMEOUT_SEC → 常量缺省 3000。env 是运维契约面（独立入口
    admin call + env、无载荷键也须生效）；畸形 fail-closed 红，不静默回落。"""
    monkeypatch.delenv(vl.INTEG_TIMEOUT_ENV, raising=False)
    assert vl._integ_timeout_sec({}) == (vl.INTEG_DEFAULT_TIMEOUT_SEC, None)
    assert vl._integ_timeout_sec({"integ_timeout_sec": 120}) == (120, None)
    assert vl._integ_timeout_sec({"integ_timeout_sec": "120"}) == (120, None)
    monkeypatch.setenv(vl.INTEG_TIMEOUT_ENV, "77")      # env 回落生效
    assert vl._integ_timeout_sec({}) == (77, None)
    assert vl._integ_timeout_sec({"integ_timeout_sec": "5"}) == (5, None)  # 载荷优先
    monkeypatch.setenv(vl.INTEG_TIMEOUT_ENV, "abc")     # env 畸形同 fail-closed
    t, err = vl._integ_timeout_sec({})
    assert err and vl.INTEG_TIMEOUT_ENV in err
    monkeypatch.delenv(vl.INTEG_TIMEOUT_ENV, raising=False)
    for blank in ("", "  ", None):
        assert vl._integ_timeout_sec({"integ_timeout_sec": blank}) == \
            (vl.INTEG_DEFAULT_TIMEOUT_SEC, None)   # 空白/None 视同缺键（走 env→缺省）
    for bad in ("abc", 0, -5, object()):
        t, err = vl._integ_timeout_sec({"integ_timeout_sec": bad})
        assert err, "畸形值 %r 必须显式红" % (bad,)
        assert "integ_timeout_sec" in err, "载荷畸形须点名载荷键（acceptance gen2 修正锚）"


# ---------------- B. 子进程 env 组装面 ----------------

def test_integ_subprocess_env_strips_worker_knobs(monkeypatch):
    """两封闭元组（TEST_STUB + WORKER_ROUTING 共 4+ 键）必须全剥；显式注入面
    （LEDGER_SOURCE / SWEEP_ORPHANS / SCENARIO_ONLY）与运维超时旋钮不得被吞。"""
    for k in ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES",
              "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_INTERVAL_SEC",
              "SANDBAR_AGENT_STUB"):
        monkeypatch.setenv(k, "leak")
    env = aa.integ_subprocess_env({
        "SANDBAR_INTEG_LEDGER_SOURCE": "inspection",
        "SANDBAR_STAGE_SWEEP_ORPHANS": "on",
        "SANDBAR_SCENARIO_ONLY": "a,b",
    })
    for k in ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES",
              "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_INTERVAL_SEC",
              "SANDBAR_AGENT_STUB"):
        assert k not in env, "路由/桩旋钮 %s 漏进子进程链" % k
    assert env["SANDBAR_INTEG_LEDGER_SOURCE"] == "inspection"
    assert env["SANDBAR_STAGE_SWEEP_ORPHANS"] == "on"
    assert env["SANDBAR_SCENARIO_ONLY"] == "a,b"


# ---------------- C. 回执形状判定 ----------------

def test_receipt_err_malformed_payloads():
    """畸形回执逐条显式红：缺 result / result 非映射 / ok=False / 顶层非映射。"""
    assert aa._integ_receipt_err({"ok": True, "result": {"ran": 3}}) is None
    assert aa._integ_receipt_err({"ok": True})          # 缺 result → 红
    assert aa._integ_receipt_err({"ok": True, "result": "junk"})   # 非映射 → 红
    assert aa._integ_receipt_err({"ok": False, "result": {"err": "boom"}}) == "boom"
    assert aa._integ_receipt_err({})                    # 空 → 红
    assert aa._integ_receipt_err("not-a-dict")          # 顶层非映射 → 红


# ---------------- D. verify_lane integ 面 ----------------

def test_parse_integ_run_counts():
    ran, p, f, ef, scen, err = vl._parse_integ_run(
        "PASS [t1] (1.0s)\nFAIL [t2] exit=1\n    tail line\n"
        "ENV_FAIL [t3] exit=2\n", 0)
    assert (ran, p, f, ef) == (3, 1, 1, 1)
    assert err is None
    assert [s["name"] for s in scen] == ["t1", "t2", "t3"]


def test_parse_integ_run_zero_signal_explicit_red():
    """零场景信号显式红（真空转面）：空输出 exit=0；纯噪音 exit=0；非零退出。
    判据与闸判定面同源（文本行 ∨ 规范行 ∨ INTEG_SUMMARY.ran>0，arbitrate 打回令）。"""
    _, _, _, _, _, e1 = vl._parse_integ_run("", 0)
    assert e1 and "零场景信号" in e1
    _, _, _, _, _, e2 = vl._parse_integ_run("some noise, no contract lines\n", 0)
    assert e2 and "零场景信号" in e2
    _, _, _, _, _, e3 = vl._parse_integ_run("some crash log\n", 3)
    assert e3 and "未产出结果" in e3 and "exit=3" in e3


def test_parse_integ_run_spec_protocol_not_miskilled():
    """规范行协议/汇总行在场=信号在场，不因缺 PASS 文本行或 exit≠0 误杀
    （arbitrate gen0/gen1 两轮打回令：判定顺序=信号判定先于退出码分家，真红以
    cases 承载、台账写入面同源）。汇总行 ran=0 不构成信号（零汇总+零行=红）。"""
    spec = '{"name":"case-x","status":"pass"}\nINTEG_SUMMARY {"ran":1,"pass":1,"fail":0}\n'
    ran, p, f, ef, scen, err = vl._parse_integ_run(spec, 0)
    assert ran == 0 and err is None
    # exit≠0 + 信号在场：仍不红（发现 1 修正点——合法红执行器交闸判定面）
    red_spec = ('{"name":"case-x","status":"fail"}\n'
                'INTEG_SUMMARY {"ran":1,"pass":0,"fail":1}\n')
    assert vl._parse_integ_run(red_spec, 1)[5] is None
    assert vl._parse_integ_run('{"name":"c","status":"pass"}\n', 1)[5] is None
    assert vl._parse_integ_run('INTEG_SUMMARY {"ran":2,"pass":2}\n', 1)[5] is None
    _, _, _, _, _, err4 = vl._parse_integ_run('INTEG_SUMMARY {"ran":0}\n', 0)
    assert err4 and "零场景信号" in err4
    # 无信号 + exit≠0 仍是「未产出结果」红（fail-closed 不放松）
    _, _, _, _, _, err5 = vl._parse_integ_run("noise\n", 1)
    assert err5 and "未产出结果" in err5


def test_parse_integ_run_half_line_no_crash():
    """半截行（`PASS [x` 无闭括号）不崩不计数，随零信号面显式红——畸形输入不静默绿。"""
    ran, p, f, ef, scen, err = vl._parse_integ_run("PASS [x\n", 0)
    assert ran == 0 and not scen and err
