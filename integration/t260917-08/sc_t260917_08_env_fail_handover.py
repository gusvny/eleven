#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-08 场景：agent bash 沙箱不可用=一等环境信号（env_fail）+ 移交命令 worker 承接。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
四条子用例离线桩（不起真台；以固定桩串/tmp 文件桩复现 t260917-05 实证形态——工单验收
①「模拟沙箱不可用（可注入桩）」、②「交接清单被后续段消费并执行（可离线桩）」口径）：

- 子用例1 承接执行（验收②）：run_handover_legs 真跑 3 条命令（过 / 红 exit 3 / 畸形 cmd
  不执行）→ 单列计数 ran=3/过=1/败=2、details 名全带 handover: 前缀、失败命令 exit 可辨；
  IntegrationRunResult 主口径 ran/passed/failed 保持缺省 0（红线④机械面：移交命令
  单列计数，不进任何闸判定）。
- 子用例2 信号+文案+不停摆（验收①）：classify_env_block 命中 t260917-05 日志原话桩串
  与 KI-083 消息；_apply_env_signal 以 tmp 日志文件桩补位归因（[worker 归因] 前缀、
  agent 自报优先不覆盖、无信号零改动）；dev_lane 壳 _block_agent_failed → blocked
  文案点名「agent 沙箱不可用（环境）」+ 出路（retry_qc/rework/票不停摆）且非
  「实现缺位」；移交命令入债表 → 拾取 → 销账 → 二轮拾取为空（不重复执行，review C1）。
- 子用例3 R4 空清单不洗白：env_note_for(env_fail+空清单) 点名「不当作已验证」+ 弃单记名；
  agent_env_failed_reason(ok+env_fail)==""（ok 段不误报失败文案，与阶段 status 不混同）。
- 子用例4 旋钮剥除（L4）：桩旋钮注入本进程 env → 命令子进程自报 env 观测=三旋钮全
  MISS、对照变量可见（桩行为不漏进被测子进程换假行为——review R2 纪律）。

驱动：引擎模块进程内直调（cmd 用 venv python；temporalio 缺席=import 失败 →
exit 2 ENV_FAIL 点名环境缺件，不假绿）。子进程命令只跑 python -c 短命令，
cwd=tempfile 目录，超时路 kill+wait 排空（全终态回收）。
三态：本场景全绿=exit 0；断言红=exit 1（产品红）；引擎模块缺环境=exit 2（ENV_FAIL）。
"""
import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)

try:
    import agent_activities  # noqa: E402
    import dev_lane  # noqa: E402
    import shared  # noqa: E402
    from shared import StageResult  # noqa: E402
except Exception as e:  # 环境缺件（venv 不在位/temporalio 缺席）=环境红，不是产品红
    print("ENV_FAIL 引擎模块不可导入（环境缺件，非被测红）：%s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

PY = sys.executable

# t260917-05 implement agent 日志原话（工单正文逐字）——环境归因的实证桩串。
T0505_LOG = ("被阻塞：bash 沙箱 sandbox_apply: Operation not permitted（三种模式均拒），"
             "pytest/node/场景/build 一行未跑")

_checks = []


def check(name, cond, detail=""):
    _checks.append((name, bool(cond), detail))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("｜" + str(detail)[:200]) if (detail and not cond) else ""))


def finish(title):
    bad = [c for c in _checks if not c[1]]
    print("\n%s：%d 查 / %d 过 / %d 败" % (title, len(_checks),
                                          len(_checks) - len(bad), len(bad)))
    sys.exit(1 if bad else 0)


# ---------- dev_lane 壳（test_t260917_01 _mk_wf 族同款，免 Temporal） ----------

async def _wake_immediately(cond) -> None:
    return None


def _mk_wf():
    import datetime
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: datetime.datetime(2026, 9, 17, 12, 0, 0,
                                      tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t26091708-sc"
    wf._detail_face_on = True
    wf.engine_version = 2
    return wf


# ---------- 子用例1：交接清单被后续段消费并执行（验收②） ----------

def leg1_handover_consumed_and_executed(tmp):
    print("—— 子用例1 承接执行：run_handover_legs 真跑（可离线桩）")
    legs = [
        {"name": "ut-green", "cmd": "%s -c \"print('leg1-ok')\"" % PY},
        {"name": "ut-red", "cmd": "%s -c 'import sys; sys.exit(3)'" % PY},
        {"name": "ut-broken", "cmd": "echo 'unbalanced"},   # 畸形：解析失败不执行
    ]
    out = asyncio.run(agent_activities.run_handover_legs(
        legs, cwd=Path(tmp)))
    check("子用例1：交接清单被逐条执行（ran=3）", out["ran"] == 3, out)
    check("子用例1：过=1 败=2（失败命令含畸形命令 fail-closed）",
          out["passed"] == 1 and out["failed"] == 2, out)
    names = [d["name"] for d in out["details"]]
    check("子用例1：details 全带 handover: 前缀（与场景明细同形状可单源消费）",
          names == ["handover:ut-green", "handover:ut-red", "handover:ut-broken"],
          names)
    reds = [d for d in out["details"] if d["exit"] != 0]
    check("子用例1：失败命令 exit 可辨（3 与畸形 -1）",
          any(d["exit"] == 3 for d in reds) and len(reds) == 2,
          [(d["name"], d["exit"]) for d in reds])
    broken = [d for d in out["details"] if d["name"] == "handover:ut-broken"][0]
    check("子用例1：畸形 cmd 未被执行（解析失败记名，fail-closed）",
          "解析失败" in broken["output_tail"], broken["output_tail"])
    # 红线④机械面：移交命令单列计数，主口径零沾染
    ir = shared.IntegrationRunResult()
    check("子用例1：主口径保持 0（命令计数不进闸判定，IntegrationRunResult 缺省面）",
          (ir.ran, ir.passed, ir.failed) == (0, 0, 0)
          and (ir.handover_ran, ir.handover_passed, ir.handover_failed) == (0, 0, 0))


# ---------- 子用例2：env 信号一等形式 + blocked 文案点名 + 不停摆（验收①） ----------

def leg2_env_signal_and_face_text(tmp):
    print("—— 子用例2 信号+文案+不停摆（注入桩复现 t260917-05）")
    why = agent_activities.classify_env_block(T0505_LOG)
    check("子用例2：日志原话桩串命中环境词表（sandbox_apply denied）",
          "agent bash 沙箱不可用" in why and "sandbox_apply" in why, why)
    why2 = agent_activities.classify_env_block(
        "dsh: no sandbox backend is usable（fail-closed）")
    check("子用例2：KI-083 消息命中（no sandbox backend）",
          "no sandbox backend is usable" in why2, why2)

    log_file = os.path.join(tmp, "agent.log")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(T0505_LOG)
    res = StageResult(status="ok")
    out = agent_activities._apply_env_signal(res, log_file, "t26091708-sc",
                                             "implement")
    check("子用例2：无自报时日志扫描补位 env_fail=true（一等形式，不靠开日志）",
          out.env_fail is True, out.env_fail)
    check("子用例2：补位归因带 [worker 归因] 前缀（与 agent 自报可分辨）",
          out.env_reason.startswith("[worker 归因] "), out.env_reason)
    self_report = StageResult(status="ok", env_fail=True, env_reason="自报原文")
    kept = agent_activities._apply_env_signal(self_report, log_file,
                                              "t26091708-sc", "implement")
    check("子用例2：agent 自报优先不覆盖",
          kept.env_reason == "自报原文" and kept is self_report)

    wf = _mk_wf()
    bad = StageResult(status="failed", summary="实现未完成",
                      env_fail=True, env_reason="sandbox_apply: Operation not permitted")
    wf._handover_debt_put("implement", bad)
    asyncio.run(wf._block_agent_failed("implement", bad))
    blocked = [e for e in wf.timeline if e.get("state") == "blocked"]
    check("子用例2：blocked 文案点名「agent 沙箱不可用（环境）」",
          len(blocked) == 1 and "agent 沙箱不可用（环境）" in blocked[0]["reason"],
          blocked and blocked[0].get("reason"))
    reason = blocked[0]["reason"]
    check("子用例2：文案与实现缺位分开（明示非实现缺位）", "非实现缺位" in reason, reason)
    check("子用例2：给出后续出路（retry_qc/rework）", "retry_qc" in reason
          and "rework" in reason, reason)
    check("子用例2：票不停摆声明（验证交由后续段 worker 执行面承接）",
          "不停摆" in reason and "worker 执行面承接" in reason, reason)
    # blocked 段无命令可交时债表保持空（不造垃圾债；put 的语义分支见 G4/G5 UT）
    check("子用例2：无命令可交时债表不造垃圾条目",
          wf.meta.get("env_handover_pending") in (None, []),
          wf.meta.get("env_handover_pending"))
    # 承接机制：put → 集测拾取 → 销账 → 二轮拾取为空（不重复执行，review C1）
    wf2 = _mk_wf()
    wf2._handover_debt_put(
        "implement", StageResult(status="failed", env_fail=True,
                                 handover_runs=[{"name": "a", "cmd": "echo 1"},
                                                {"name": "b", "cmd": "echo 2"}]))
    picked = wf2._handover_debt_legs()
    check("子用例2：移交命令入债表（{stage,name,cmd}）", len(picked) == 2, picked)
    wf2._handover_debt_clear()
    check("子用例2：集测拾取销账后二轮拾取为空（不重复执行）",
          wf2._handover_debt_legs() == [])


# ---------- 子用例3：R4 空清单不洗白（ok+env_fail+空清单 ≠ 已验证） ----------

def leg3_empty_legs_not_washed_green():
    print("—— 子用例3 R4 空清单语义")
    note = shared.env_note_for(StageResult(status="ok", env_fail=True))
    check("子用例3：空清单注记点名「不当作已验证」",
          "未验证且无移交命令" in note and "不当作已验证" in note, note)
    note2 = shared.env_note_for(StageResult(
        status="ok", env_fail=True,
        handover_dropped=["条目0:非对象", "条目1:cmd 缺失或非字符串"]))
    check("子用例3：弃单记名进注记（不静默丢）", "弃 2 条" in note2, note2)
    check("子用例3：ok+env_fail 不误报失败文案（信号与 status 不混同）",
          shared.agent_env_failed_reason(
              StageResult(status="ok", env_fail=True)) == "")
    note3 = shared.env_note_for(StageResult(
        status="ok", env_fail=True,
        handover_runs=[{"name": "a", "cmd": "c"}, {"name": "b", "cmd": "d"}]))
    check("子用例3：有命令注记=移交语义（票面可见）",
          "移交 2 条命令待执行" in note3 and "a" in note3, note3)
    arb = dev_lane.FLOW_BRIEF["arbitrate"]
    check("子用例3：仲裁契约句在场（env_fail 段=验证未闭环不得当已验证）",
          "验证未闭环" in arb and "不得当已验证" in arb)


# ---------- 子用例4：桩旋钮不漏进被测子进程（L4） ----------

def leg4_stub_knobs_stripped():
    print("—— 子用例4 旋钮剥除")
    saved = {k: os.environ.get(k)
             for k in ("SANDBAR_AGENT_STUB", "SANDBAR_AGENT_STUB_ENV_FAIL",
                       "SANDBAR_AGENT_STUB_HANDOVER", "SANDBAR_SC_CONTROL")}
    try:
        os.environ["SANDBAR_AGENT_STUB"] = "1"
        os.environ["SANDBAR_AGENT_STUB_ENV_FAIL"] = "1"
        os.environ["SANDBAR_AGENT_STUB_HANDOVER"] = "[]"
        os.environ["SANDBAR_SC_CONTROL"] = "visible"
        probe = ("import os; print(os.environ.get('SANDBAR_AGENT_STUB','MISS'),"
                 "os.environ.get('SANDBAR_AGENT_STUB_ENV_FAIL','MISS'),"
                 "os.environ.get('SANDBAR_AGENT_STUB_HANDOVER','MISS'),"
                 "os.environ.get('SANDBAR_SC_CONTROL','MISS'))")
        out = asyncio.run(agent_activities.run_handover_legs(
            [{"name": "env-probe", "cmd": "%s -c \"%s\"" % (PY, probe)}],
            cwd=Path(tempfile.gettempdir())))
        tail = out["details"][0]["output_tail"]
        check("子用例4：三桩旋钮在命令子进程 env 中全被剥除（不漏进换假行为）",
              "MISS MISS MISS" in tail, tail)
        check("子用例4：对照变量正常透传（剥除面不误伤）", "visible" in tail, tail)
        check("子用例4：探针命令自身绿（exit 0）", out["passed"] == 1 and out["failed"] == 0)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    print("t260917-08 env_fail 一等环境信号 + 移交命令承接（离线桩四条子用例）")
    tmp = tempfile.mkdtemp(prefix="t26091708-sc-")
    try:
        leg1_handover_consumed_and_executed(tmp)
        leg2_env_signal_and_face_text(tmp)
        leg3_empty_legs_not_washed_green()
        leg4_stub_knobs_stripped()
    except Exception as e:
        traceback.print_exc()
        check("场景体无未捕获异常", False, "%s: %s" % (type(e).__name__, e))
    finish("t260917-08 场景汇总")


if __name__ == "__main__":
    main()
