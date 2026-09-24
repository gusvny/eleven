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
    """外层预算必须**派生**自 INTEG_GUARD_SEC（算式成对锁），不允许再手写常量。"""
    assert dev_lane.INTEG_RUN_TO == timedelta(seconds=aa.INTEG_GUARD_SEC + 300)
    assert flow.SUITE_TO == timedelta(seconds=aa.INTEG_GUARD_SEC + 1800)


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
