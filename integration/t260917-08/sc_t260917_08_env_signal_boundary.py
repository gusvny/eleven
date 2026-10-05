#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-08 场景（integration 面）：env 一等信号的活动边界装配——桩旋钮注入 →
活动入口 → 幂等缓存重放 → 日志扫描补位 → 归因不污染。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
工单验收①的**入口面**：信号位（env_fail/env_reason/handover_runs/handover_dropped）
必须在「活动边界」真实在位——不是内部函数直调可见，而是从真实活动入口进（桩旋钮
注入）、经幂等缓存重放不丢、缓存命中时日志扫描补位、且归因不被陈旧日志污染。
与同票 sc_t260917_08_env_fail_handover.py 分工：彼守离线消费面（命令执行器/债表/文案/
R4 空清单语义），本条守**装配面**（M1 四挂点中「幂等缓存①/桩旋钮②」两条的行为面 +
N2 重放不丢 + 污染对抗）——内部函数单测过≠入口接线在。

四条子用例（离线桩，零网络零 docker；temporalio.testing.ActivityEnvironment 驱动共享段
实现——全部 agent 段活动的唯一入口，输出=段回执公开契约 StageResult）：

- 子用例1 桩旋钮注入→活动边界（验收①入口面+结果契约层）：SANDBAR_AGENT_STUB_ENV_FAIL/
  _ENV_REASON/_HANDOVER（JSON 文件路径形式）→ 段回执 status=ok（信号不翻转红绿，
  红线④正面）、env_fail=true、env_reason 自报原文保真、合法条目归一保留、畸形条目记名
  dropped（不静默丢）；**磁盘结果文件**四新键成套在位（结果契约层=幂等锚点）。
- 子用例2 幂等缓存重放不丢信号（t260917-05 实证承接面：worker 死在「交付后、归位前」→
  重放）：同 result_file 二次调用走缓存命中 → env_fail/命令/dropped 全数存活（N2
  并集保留），status 仍 ok。
- 子用例3 缓存命中+日志扫描补位（M1 挂点①行为面）：**旧格式回执**（无任何 env 键）+
  spawn 日志含 t260917-05 原话 → env_fail=true 补位、env_reason 带「[worker 归因]」
  前缀（与 agent 自报可分辨）并点名 sandbox_apply；对照=同回执+日志读不到 → 零改动
  （无信号不硬造）。
- 子用例4 归因不污染（对抗面，M1 裁定②）：桩路径**有意不挂**日志扫描——桩回执（无
  env 旋钮）+ 陈旧日志含 sandbox 字样 → env_fail 恒 False、命令/弃单均空（老载荷
  零改动面）。若有人为「归一化」把扫描挂上桩路径，陈旧日志会伪造环境归因——本子用例
  即钉死该回归。

驱动：引擎模块进程内直调（cmd 用 venv python；temporalio/venv 缺席=import 失败 →
exit 2 ENV_FAIL 点名环境缺件，不假绿）。全部活动调用在一个事件循环内 await（py3.9
ActivityEnvironment 兼容）；产物落 tempfile 目录一次性清理；env 旋钮用后恢复。
三态：全绿=exit 0；断言红=exit 1（产品红）；环境缺件=exit 2（ENV_FAIL）。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)

try:
    import agent_activities  # noqa: E402
    from shared import AgentStageArgs  # noqa: E402
    from temporalio.testing import ActivityEnvironment  # noqa: E402
except Exception as e:  # 环境缺件（venv 不在位/temporalio 缺席）=环境红，不是产品红
    print("ENV_FAIL 引擎模块/temporalio.testing 不可导入（环境缺件，非被测红）：%s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

KNOBS = ("SANDBAR_AGENT_STUB", "SANDBAR_AGENT_STUB_FILES",
         "SANDBAR_AGENT_STUB_ENV_FAIL", "SANDBAR_AGENT_STUB_ENV_REASON",
         "SANDBAR_AGENT_STUB_HANDOVER")

# t260917-05 implement agent 日志原话（工单正文逐字）——补位归因的实证桩串。
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


def _args(tmp, result_file, log_file, gen=0):
    return AgentStageArgs(ticket_id="t26091708-sc", stage_id="implement",
                          role="developer", prompt="p",
                          workspace={"path": tmp}, result_file=result_file,
                          log_file=log_file, gen=gen, skip_settle=True)


async def leg1_stub_knobs_to_activity_boundary(tmp):
    """子用例1：桩旋钮注入 → 活动边界（验收①入口面 + 磁盘结果契约层）。"""
    print("—— 子用例1 桩旋钮注入→活动边界")
    hv_file = os.path.join(tmp, "handover.json")
    # 2 合法条目（名字带首尾空白=剥除面）+ 1 畸形条目（cmd 全空白）+ 1 非对象条目
    with open(hv_file, "w", encoding="utf-8") as f:
        json.dump([{"name": " pytest-engine ", "cmd": " python3 -m pytest -q "},
                   {"name": "lint", "cmd": "python3 integration/lint_tests.py"},
                   {"name": "blank-cmd", "cmd": "   "},
                   "not-a-dict"], f, ensure_ascii=False)
    os.environ["SANDBAR_AGENT_STUB"] = "1"
    os.environ["SANDBAR_AGENT_STUB_ENV_FAIL"] = "1"
    os.environ["SANDBAR_AGENT_STUB_ENV_REASON"] = T0505_LOG
    os.environ["SANDBAR_AGENT_STUB_HANDOVER"] = hv_file
    env = ActivityEnvironment()
    rf = os.path.join(tmp, "result.json")
    res = await env.run(agent_activities._run_agent_stage_impl,
                        _args(tmp, rf, os.path.join(tmp, "agent.log")))
    check("子用例1：信号不翻转红绿（env_fail=true 段仍 status=ok，红线④正面）",
          res.status == "ok", res.status)
    check("子用例1：env_fail 一等位在位（活动边界可见，不靠开日志）",
          res.env_fail is True, res.env_fail)
    check("子用例1：env_reason 自报原文保真（旋钮直注不改写）",
          res.env_reason == T0505_LOG, res.env_reason)
    names = [l.get("name") for l in (res.handover_runs or [])]
    check("子用例1：合法条目归一保留（name 剥空白、保序）",
          names == ["pytest-engine", "lint"], res.handover_runs)
    dropped = res.handover_dropped or []
    check("子用例1：畸形条目逐条记名不静默丢（空白 cmd + 非对象）",
          any("item2" in d and "name/cmd" in d for d in dropped)
          and any("not an object" in d for d in dropped),
          dropped)
    try:
        raw = json.loads(Path(rf).read_text("utf-8"))
    except Exception as e:
        raw = {"_err": "%s: %s" % (type(e).__name__, e)}
    check("子用例1：磁盘结果文件四新键成套在位（结果契约层=幂等锚点）",
          raw.get("env_fail") is True and raw.get("env_reason") == T0505_LOG
          and len(raw.get("handover_runs") or []) == 2
          and len(raw.get("handover_dropped") or []) == 2,
          {k: raw.get(k) for k in ("env_fail", "env_reason",
                                   "handover_runs", "handover_dropped")})
    return rf


async def leg2_cache_replay_keeps_signal(tmp, rf):
    """子用例2：幂等缓存重放不丢信号（-05 实证：worker 死在交付后归位前 → 重放）。"""
    print("—— 子用例2 幂等缓存重放不丢信号（N2）")
    env = ActivityEnvironment()
    res = await env.run(agent_activities._run_agent_stage_impl,
                        _args(tmp, rf, os.path.join(tmp, "agent.log"), gen=0))
    check("子用例2：缓存重放 env_fail/命令/弃单全数存活（重放不丢信号）",
          res.env_fail is True and len(res.handover_runs or []) == 2
          and len(res.handover_dropped or []) == 2,
          (res.env_fail, res.handover_runs, res.handover_dropped))
    check("子用例2：重放路径 status 仍 ok（缓存不改判定）", res.status == "ok", res.status)


async def leg3_cache_hit_log_scan_fills(tmp):
    """子用例3：缓存命中+日志扫描补位（M1 挂点①）+ 日志读不到对照零改动。"""
    print("—— 子用例3 缓存命中日志扫描补位（M1 挂点①）")
    env = ActivityEnvironment()
    rf = os.path.join(tmp, "old_receipt.json")
    with open(rf, "w", encoding="utf-8") as f:
        json.dump({"status": "ok", "summary": "旧格式回执（无 env 键）",
                   "report": "", "deliverables": [], "files_changed": [],
                   "evidence": "e"}, f, ensure_ascii=False)
    log = os.path.join(tmp, "spawn.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("…agent 输出…%s…" % T0505_LOG)
    res = await env.run(agent_activities._run_agent_stage_impl,
                        _args(tmp, rf, log, gen=1))
    check("子用例3：旧格式回执+日志原话 → env_fail 补位=true（死在归位前的实证形态）",
          res.env_fail is True, (res.env_fail, res.env_reason))
    check("子用例3：补位归因带 [worker 归因] 前缀（与 agent 自报可分辨）且点名 sandbox_apply",
          str(res.env_reason or "").startswith("[worker 归因] ")
          and "sandbox_apply" in str(res.env_reason or ""), res.env_reason)
    res2 = await env.run(agent_activities._run_agent_stage_impl,
                         _args(tmp, rf, os.path.join(tmp, "absent.log"), gen=1))
    check("子用例3：对照=日志读不到 → 零改动不硬造（env_fail=False）",
          res2.env_fail is False and res2.env_reason == "",
          (res2.env_fail, res2.env_reason))


async def leg4_stub_path_not_polluted_by_stale_log(tmp):
    """子用例4：归因不污染（对抗面）——桩路径有意不挂日志扫描（M1 裁定②）。"""
    print("—— 子用例4 归因不污染（陈旧日志假信号对抗）")
    env = ActivityEnvironment()
    log = os.path.join(tmp, "stale.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("上代遗留：bash 沙箱 sandbox_apply: Operation not permitted …")
    os.environ["SANDBAR_AGENT_STUB"] = "1"   # 桩路径，无任何 env 旋钮
    for k in ("SANDBAR_AGENT_STUB_ENV_FAIL", "SANDBAR_AGENT_STUB_ENV_REASON",
              "SANDBAR_AGENT_STUB_HANDOVER"):
        os.environ.pop(k, None)
    res = await env.run(agent_activities._run_agent_stage_impl,
                        _args(tmp, os.path.join(tmp, "r4.json"), log, gen=2))
    check("子用例4：桩路径不吞陈旧日志假信号（env_fail 恒 False，归因不被污染）",
          res.env_fail is False and res.env_reason == "",
          (res.env_fail, res.env_reason))
    check("子用例4：无旋钮老载荷零改动面（命令/弃单均空）",
          res.handover_runs == [] and res.handover_dropped == [],
          (res.handover_runs, res.handover_dropped))


async def _run_all(tmp):
    rf = await leg1_stub_knobs_to_activity_boundary(tmp)
    if rf:
        await leg2_cache_replay_keeps_signal(tmp, rf)
    await leg3_cache_hit_log_scan_fills(tmp)
    await leg4_stub_path_not_polluted_by_stale_log(tmp)


def main():
    print("t260917-08 env 一等信号·活动边界装配（离线桩四条子用例）")
    tmp = tempfile.mkdtemp(prefix="t26091708-sig-")
    saved = {k: os.environ.get(k) for k in KNOBS}
    try:
        try:
            asyncio.run(_run_all(tmp))
        except Exception as e:
            traceback.print_exc()
            check("场景体无未捕获异常", False, "%s: %s" % (type(e).__name__, e))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    finish("t260917-08 活动边界装配场景汇总")


if __name__ == "__main__":
    main()
