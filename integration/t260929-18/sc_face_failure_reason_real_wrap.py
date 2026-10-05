#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260929-18 场景①：票面失败文案走**真实 Temporal 包裹路**（灰盒 L3）。

intent（工单 ACCEPTANCE 逐字：真实包裹路、禁止手搓 ActivityError+cause 顶替）：
agent 段活动失败时，票面 blocked 文案必须携带活动抛出的真实可行动消息（谁失败、
为何、怎么救），不得退化为无信息包装串「Activity task failed」；同时 t260916-29
契约反向锁——worker_terminated 专用文案必须赢过链挖掘。全部子用例经
temporalio.testing.WorkflowEnvironment（本机随机端口测试服务，零碰生产
3099/7233）+ 真实 Worker 真实执行 stub 活动：异常由 SDK 真实包裹成 ActivityError，
工作流侧走生产唯一出口 format_agent_stage_failure（生产 catch 位同款）。

子用例：
- A1 主面（t260929-15 同形）：活动 raise RuntimeError(可行动 detail) → 文案含
  detail 且点名根因类型（RuntimeError）；外层 ActivityError 如实点名；
- A2 非退化：包装串话术仍在（外层如实展示）但 detail 在场＝不再是唯一内容；
- A3 确定性：同形 history 再跑一遍 → 同文案（行程级锚，契约要求②）；
- B 反向锁（t260916-29）：活动 raise ApplicationError(type=worker_terminated)
  → 文案是「worker 被外部终止…」专用面，不做链挖掘、不出现包装串话术；
- C 零消息活动失败：活动 raise RuntimeError("") → 不炸、绝不编造（文案里不得
  出现没发生的可行动 detail）。实测定性（260929 本场景首轮实跑）：Temporal 服务端
  对空消息活动失败会在链上自动填占位消息 "Application error"——真实链永不为空，
  工单 5(c) 的「空消息→显式不可得」在真路不可达，该面由场景② M5（全空链契约面）
  承接；本条只钉真路可钉的「不炸不编造」，服务端占位行为作为发现上报（KI 登记
  归 integration 岗）。

intent 分工（防 intent 级重复）：
- developer L1 UT（server/engine/tests）＝formatter 纯函数矩阵（白盒可随实现重写）；
  本条＝真 worker+真服务端的包裹语义（SDK 怎么包链是它的对外行为，UT 桩钉不住
  ——正是本票缺陷的原始形态：helper 在、包裹链没走到）；
- 场景②（t260929-18 malformed matrix）＝SDK 造不出来的畸形链（成环/野 cause/
  超深链）的契约面；本条只打 SDK 能真造出的三形。

三态契约：temporalio/引擎 venv 缺席或本机测试服务起不来=ENV_FAIL exit 2 点名；
实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))                             # integration/
sys.path.insert(0, os.path.join(_HERE, "..", "..", "server", "engine"))  # shared

from lib_env import env_fail  # noqa: E402
from lib_result import spec_line  # noqa: E402

REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
SCENARIO = "t260929-18-face-reason-real-wrap"

CASES = []  # (sub_name, ok, evidence)


def case(name, ok_, evidence):
    CASES.append((name, bool(ok_), evidence))


def _temporalio_ready():
    try:
        import temporalio  # noqa: F401
        return True
    except Exception:
        return False


def _reexec_with_engine_venv():
    """当前解释器无 temporalio → 引擎 venv 回落链重自exec；没有 → ENV_FAIL。"""
    if _temporalio_ready():
        return
    from shared import engine_venv_python  # stdlib-only，安全
    py = engine_venv_python(REPO)
    if py is None:
        env_fail("引擎 venv（temporalio）缺失：server/engine/.venv 与旧路径回落均无解释器，"
                 "真实包裹路无从执行")
    os.execv(str(py), [str(py), __file__])


async def main_async():
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
    except Exception as e:
        env_fail("temporalio 不可导入：%r" % (e,))
    sys.path.insert(0, _HERE)
    from face_wrap_probe import (ACTIONABLE_DETAIL, FaceProbeWorkflow,
                                 face_probe_activity)

    try:
        env = await WorkflowEnvironment.start_local()
    except Exception as e:
        env_fail("本机 Temporal 测试服务起不来（WorkflowEnvironment.start_local）：%r" % (e,))

    async with env:
        async with Worker(env.client, task_queue="t26092918-face-probe",
                          workflows=[FaceProbeWorkflow],
                          activities=[face_probe_activity]):

            async def run_probe(mode, ticket):
                return await env.client.execute_workflow(
                    FaceProbeWorkflow.run,
                    {"mode": mode, "ticket": ticket, "stage": "implement"},
                    id="t26092918-%s" % ticket,
                    task_queue="t26092918-face-probe")

            # ---------- A 主面：真实 raise → 文案携带可行动 detail ----------
            r1 = await run_probe("raise", "t260929-18a")
            text1 = r1.get("text", "")
            case("A1-actionable-detail-reaches-face",
                 r1.get("status") == "failed"
                 and ACTIONABLE_DETAIL in text1
                 and r1.get("exc_type") == "ActivityError"
                 and "RuntimeError" in text1,
                 "exc_type=%s text=%r" % (r1.get("exc_type"), text1[:300]))
            case("A2-not-generic-wrapper-only",
                 "Activity task failed" in text1 and ACTIONABLE_DETAIL in text1,
                 "text=%r" % text1[:300])
            r2 = await run_probe("raise", "t260929-18a2")
            case("A3-deterministic-same-history-same-text",
                 r2.get("text") == text1,
                 "text1=%r text2=%r" % (text1[:150], r2.get("text", "")[:150]))

            # ---------- B 反向锁：worker_terminated 专用文案赢 ----------
            rb = await run_probe("worker_terminated", "t260929-18b")
            textb = rb.get("text", "")
            case("B-worker-terminated-wording-wins",
                 "worker terminated externally" in textb
                 and ACTIONABLE_DETAIL not in textb
                 and "Activity task failed" not in textb,
                 "text=%r" % textb[:300])

            # ---------- C 零消息活动失败：不炸、不编造（服务端占位行为见头注实测定性） ----------
            rc = await run_probe("empty_msg", "t260929-18c")
            textc = rc.get("text", "")
            case("C-empty-message-no-crash-no-fabrication",
                 rc.get("status") == "failed"
                 and ACTIONABLE_DETAIL not in textc,
                 "text=%r" % textc[:300])


def main():
    _reexec_with_engine_venv()
    try:
        asyncio.run(main_async())
    except SystemExit:
        raise  # lib_env.env_fail 的 exit 2（环境红）原样透传，不改判
    except Exception as e:  # noqa: BLE001 —— 执行期崩溃=场景自身故障，按 FAIL 红
        case("X-run-crash", False, "crash=%r" % (e,))
    npass = sum(1 for _, ok_, _ in CASES if ok_)
    for name, ok_, ev in CASES:
        sys.stdout.write(spec_line("%s/%s" % (SCENARIO, name),
                                   "pass" if ok_ else "fail",
                                   cause="self" if ok_ else "unknown",
                                   reason="" if ok_ else "assertion red",
                                   evidence=ev, suite=SCENARIO))
    sys.stdout.write("SUMMARY %s: ran=%d pass=%d fail=%d\n"
                     % (SCENARIO, len(CASES), npass, len(CASES) - npass))
    sys.exit(0 if npass == len(CASES) else 1)


if __name__ == "__main__":
    main()
