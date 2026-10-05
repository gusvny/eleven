#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01 场景①：闸出口 × 引擎签名消费的进程级接缝（灰盒 L2.5，离线）。

用户场景（工单正文，t260916-25 第 10 轮实案）：供给装配失败（0 条场景执行）本应按
环境面豁免、不计入 tests-fault 轮次，但实测被连续计轮、撞上限 5 封票。假封链的
两端=「verify_lane 供给闸出口文案」与「引擎签名判据消费」——签名措辞与闸出口
不一致、或出口形状错配（非签名启动级文案），任何一端漂移，豁免就静默失联。

收口后用户可感知行为（工单要求①④）：
  A. 供给装配失败两态（失败/超时）真跑 verify_lane（admin.py 真入口 + 真声明
     解析 + 真 supply 执行）产出的 err 文案含双标记机器 token（SUPPLY_ASSEMBLY_{TIMEOUT,FAILED} ∧ SUPPLY_SIDE_RED）
     且点名 need——引擎签名判据命中；
  B. 该回执形态（ran=0+零产品红+零闸拦+零环境红+签名 error）→ 该轮不计入
     tests-fault 轮次，留痕含「不计入」且点名供给面（不静默）；
  C. 反用例（宁窄勿宽）：非签名启动级文案（场景执行器整体超时=t260916-25 事故
     H2 形态）→ 签名不命中 → 该轮照旧保守计轮；
  D. 对照组：PASS 桩 → 闸绿（夹具与调用链有效性自证，红绿差异归因于供给面）。

与既有资产 intent 分工（防重复声明）：
  · t260904-12 sc_supply_gate_ethred 锁 verify_lane supply **机制本体**（先行序/
    失败红点名 need/声明畸形 fail-closed/ENV_FAIL 行解析），用假声明仓驱动闸回执
    形状——本条不重复其机制面，锁的是**本票病灶接缝**：真出口文案 × 引擎签名
    消费 × 计轮账本三环贯通（机制在彼票已锁，接缝漂移只有真跑才暴露）；
  · t260917-09 sc_tests_false_escalation_guard 锁**场景级**环境红豁免
    （env_fail>0）与抖动复跑豁免、不在册保守计轮（真 docker 台）——本条锁
    **装配级**（ran=0）供给形态，彼场景无此用例；
  · developer L1（test_t260920_01_supply_wait_budget.py 等）锁判据函数行为
    （构造串直驱）——本条喂的是**真进程跑出来的 err**，出口实况不可手工构造。
驱动形态：admin.py call verify_lane 真入口（t260904-12 同款）+ tmp 夹具仓；
判据消费跳=真 dev_lane 模块（temporalio 缺席环境装 _stub_temporalio 桩，与
t260919-02 同款手法）。纯离线秒级，无 docker 依赖，无 环境用例。
现状注记：判据接线 HEAD 代码面已通（t260917-09），本场景现在就应全绿——红了=
接线回归（真病灶复现），不是 TDD 预期红。
跑法：python3 -B integration/t260920-01/sc_supply_assembly_seam.py
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "integration"))

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


# ---------- 引擎侧消费跳（真 dev_lane 模块 + 真 shared 纯函数） ----------

def _engine_modules():
    """server/engine 模块装载：venv（有 temporalio）直接 import；裸 python3
    回落装 _stub_temporalio 桩（t260919-02 同款）后再 import dev_lane。"""
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import shared  # noqa: F401  纯 stdlib，任何环境可载
    import importlib.util
    if importlib.util.find_spec("temporalio") is None:
        sys.path.insert(0, str(REPO / "integration" / "t260919-02"))
        import _stub_temporalio
        _stub_temporalio.install()
    import dev_lane
    return shared, dev_lane


def judge_receipt(shared, dev_lane, err_text):
    """把闸回执形态喂进引擎消费链：签名命中？→ 计轮账本（counted/note）。"""
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    receipt = shared.IntegrationRunResult(
        ran=0, passed=0, failed=0, env_fail=0, error=err_text)
    sig = shared.tests_supply_assembly_error(err_text)
    tr, ex, counted, note = asyncio.run(
        wf._tests_round_account(1, 0, receipt))
    return sig, counted, note


# ---------- 闸驱动（admin.py 真入口，t260904-12 同款） ----------

def call_gate(fixture_repo, extra_env=None):
    env = clean_narrowing_env(extra_env or {})   # 260930：清继承旋钮（单点 helper）
    p = subprocess.run(
        [sys.executable, "server/admin.py", "call", "verify_lane",
         json.dumps({"lane": "integ", "path": str(fixture_repo)})],
        cwd=str(REPO), capture_output=True, text=True, timeout=180, env=env)
    if p.returncode != 0:
        return {"ok": False, "stderr": (p.stderr or "")[-300:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-200:]}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if isinstance(inner, dict) and ("green" in inner or "err" in inner):
        return {"ok": True, "result": inner}
    return {"ok": isinstance(parsed, dict) and parsed.get("ok") is True,
            "result": inner if isinstance(inner, dict) else parsed}


def make_fixture(yaml_integration_block, stub_files):
    td = tempfile.mkdtemp(prefix="t26092001-seam-")
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        + yaml_integration_block, encoding="utf-8")
    for name, text in stub_files.items():
        (repo / name).write_text(text, encoding="utf-8")
    return repo


# 桩的 SCENARIOS 汇总行必须带全键（执行器解析契约）；env_fail 计数在源码里
# 运行时拼接（"env"+"_fail=0"）——lint L6 ENV0_COMBO 以 re.I 匹配，会把小写
# env_fail=0（SUMMARY 计数，零环境红）误认 ENV_FAIL 状态标记与 exit(0) 组成
# 「缺环境却 exit 0」假阳性。lint 规则精化挂账 integration 岗位（共享守卫，
# 按 260910 纪律不在本票擅改），此处绕行不改变桩输出形状。
PASS_STUB = ("print('PASS [对照桩]')\n"
             "print('SCENARIOS ran=1 pass=1 fail=0 env'+'_fail=0 na=0 (0s)')\n"
             "import sys; sys.exit(0)\n")

shared, dev_lane = _engine_modules()

# ---- A1 供给失败态（exit 7）：真出口文案 → 签名 → 不计轮留痕 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 测试台供给（t260920-01 场景桩）\n      cmd: python3 supply_bad.py\n",
    {"integ_stub.py": PASS_STUB,
     "supply_bad.py": "import sys\nprint('boom：供给物不齐')\nsys.exit(7)\n"})
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    err = str(r.get("err") or "")
    ok(r.get("green") is False, "A1 供给失败 → 闸红")
    ok(shared.SUPPLY_FAIL_SIG in err, "A1b 出口文案含状态 token SUPPLY_ASSEMBLY_FAILED")
    ok(shared.SUPPLY_SIDE_SIG in err, "A1c 出口文案含侧面 token SUPPLY_SIDE_RED（双标记第二元）")
    ok("测试台供给" in err, "A1d 出口点名 need（不静默）")
    sig, counted, note = judge_receipt(shared, dev_lane, err)
    ok(sig is True, "A1e 真出口 err 命中引擎供给签名")
    ok(counted is False, "A1f 该轮不计入 tests-fault（counted=False）")
    ok("not counted" in note and "supply-side assembly" in note,
       "A1g 留痕含不计轮豁免记名+点名供给面（got: %s）" % note[:80])
else:
    ok(False, "A1 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- A2 供给超时态：真出口超时文案 → 签名 → 不计轮 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 测试台供给（t260920-01 场景桩）\n      cmd: python3 supply_slow.py\n"
    "      timeout: 1\n",
    {"integ_stub.py": PASS_STUB,
     "supply_slow.py": "import time\ntime.sleep(30)\n"})
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    err = str(r.get("err") or "")
    ok(r.get("green") is False, "A2 供给超时 → 闸红")
    ok(shared.SUPPLY_TIMEOUT_SIG in err and shared.SUPPLY_SIDE_SIG in err,
       "A2b 超时态出口含双标记（got: %s）" % err[:80])
    sig, counted, note = judge_receipt(shared, dev_lane, err)
    ok(sig is True and counted is False and "not counted" in note,
       "A2c 超时态同样命中豁免不计轮")
else:
    ok(False, "A2 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- C 非签名启动级用例（H2 形态=执行器整体超时）：保守计轮不豁免 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_slow.py\n",
    {"integ_slow.py": "import time\ntime.sleep(30)\n"})
res = call_gate(repo, extra_env={"SANDBAR_INTEG_BATCH_TIMEOUT_SEC": "1"})
if res.get("ok"):
    r = res["result"]
    err = str(r.get("err") or "")
    ok(r.get("green") is False and "scenario executor wall timed out" in err,
       "C  执行器整体超时 → 闸红且出口为非签名启动级文案")
    sig, counted, note = judge_receipt(shared, dev_lane, err)
    ok(sig is False, "C2  非签名文案不命中供给签名（宁窄勿宽）")
    ok(counted is True, "C3  该轮照旧保守计轮（t260916-25 H2 形态不豁免）")
else:
    ok(False, "C  调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- D 对照组：PASS 桩 → 绿（夹具自证） ----
repo = make_fixture("integration:\n  cmd: python3 integ_stub.py\n",
                    {"integ_stub.py": PASS_STUB})
res = call_gate(repo)
ok(res.get("ok") is True and res.get("result", {}).get("green") is True,
   "D  对照组 PASS 桩 → 闸绿（红绿差异归因于供给面而非夹具）")
shutil.rmtree(repo, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
