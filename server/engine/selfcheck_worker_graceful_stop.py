#!/usr/bin/env python3
"""selfcheck_worker_graceful_stop — worker 优雅停三场景主闸（t260916-29）。

Runs against a real SDK instance (temporalio.testing.WorkflowEnvironment.start_local
local test server — 随机端口、独立数据、零碰生产 3099/7233；零模型/零真 agent——全部
活动是内存 stub）and exercises the REAL worker.py shutdown machinery end to end:

  场景 A（grace 生效，工单要求①）：worker 以 SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC=3
    起跑，stub agent 活动在飞时对本进程发 SIGTERM → 走 worker.install_stop_signal_handlers
    + worker._graceful_shutdown（与 run_worker 同一条真路径）→ 宽限期内放行 stub →
    断言 activity 完成回报 ok、停机日志逐票点名（票/段）、终态清单记 completed。
  场景 B（取消可辨，要求②）：grace=0 复现事故旧行为 → SDK 以 is_worker_shutdown
    取消在飞活动 → agent_activities.worker_termination_guard 转成
    type=worker_terminated 的 ApplicationError → 工作流侧
    shared.classify_worker_termination/format_agent_stage_failure 产出
    「worker 被外部终止（停机/重载）…（票 X 段 Y）」——断言分类为真、文案带票号段号。
  场景 C（重跑兜底，要求④）：同 B 首跑被停机取消 →
    shared.retry_once_on_worker_termination（patched 门开）自动重跑一次 → 第二次由
    接棒的 worker2 跑成 → 断言恰好 2 次执行、最终 ok（不落 blocked）。

Regression anchor for the t260916-29 incident family（260916 22:17/22:37 两轮全票
假「活动故障」）：本文件场景 B 即其回归形态；KI 登记由 integration 验收段处置。

Exit code 0 = all green; non-zero = at least one red (details on stderr).
Resource cleanup: env/workers all reclaimed via async-with/finalizers; the stubs
create zero temp files; timeouts are guardrails only (no wall-clock assertions).

Pattern declaration (same as selfcheck_ki061_wake_reset): zero model, zero real
agent (stub receipts), the exit-code contract, no wall-clock timing assertions,
local test server — all carried over. The only pattern exceptions: (a) this
selfcheck drives shutdown via real SIGTERM + worker._graceful_shutdown instead of
switching worker code in place; (b) scenario B intentionally sets grace=0 to
reproduce the pre-fix behavior. KI-093 discipline: stub activities own no process
groups and reap nothing — the guard/registry face only, engine spawn/reap logic
untouched.

Usage (engine directory): .venv/bin/python selfcheck_worker_graceful_stop.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

import agent_activities  # noqa: E402
import worker as worker_mod  # noqa: E402
from selfcheck_graceful_stop_probe import CTRL, ProbeWorkflow, guarded_probe  # noqa: E402

Q_A = "t26091629-selfcheck-a"
Q_B = "t26091629-selfcheck-b"
Q_C = "t26091629-selfcheck-c"


# ---------- assertion framework（ki061 同款） ----------

PASS = 0
FAIL = 0


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok - %s" % label)
    else:
        FAIL += 1
        print("FAIL - %s" % label, file=sys.stderr)


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())

    def texts(self):
        return list(self.records)

    def clear(self):
        self.records = []


async def wait_until(cond_fn, timeout_s: float, label: str) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if cond_fn():
            return True
        await asyncio.sleep(0.05)
    print("TIMEOUT %s" % label, file=sys.stderr)
    return False


async def _run_scenario(env, capture: _LogCapture, *, queue, ticket, stage, mode,
                        grace_env: str, worker2_activities: bool, release: bool) -> dict:
    """单场景骨架：起 worker1（指定 grace）→ 探针在飞 → SIGTERM → 真停机路径 →
    worker2 接棒收尾。返回探针工作流结果。release=True 时放行首跑（场景 A）。"""
    os.environ["SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"] = grace_env
    capture.clear()
    CTRL["calls"].pop(ticket, None)
    CTRL["entered"].pop(ticket, None)
    CTRL["release"][ticket] = asyncio.Event()
    handle = await env.client.start_workflow(
        ProbeWorkflow.run, {"mode": mode, "ticket": ticket, "stage": stage},
        id="selfcheck-%s" % ticket, task_queue=queue)
    w1 = Worker(env.client, task_queue=queue, workflows=[ProbeWorkflow],
                activities=[guarded_probe], **worker_mod._worker_extra_kwargs())
    t1 = asyncio.create_task(w1.run())
    ok(await wait_until(lambda: CTRL["entered"].get(ticket) is True, 15,
                        "worker1 起跑且探针在飞 %s" % ticket),
       "起跑：探针活动在飞（%s）" % ticket)
    # worker2 先起再停 worker1：停机后 workflow 任务/重跑由它接棒
    w2 = Worker(env.client, task_queue=queue, workflows=[ProbeWorkflow],
                activities=[guarded_probe] if worker2_activities else [],
                **worker_mod._worker_extra_kwargs())
    t2 = asyncio.create_task(w2.run())
    await asyncio.sleep(0.5)  # worker2 poller 预热（无墙钟断言，仅顺序保障）
    stop = worker_mod.install_stop_signal_handlers()
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(stop.wait(), 10)
    shutdown_task = asyncio.create_task(
        worker_mod._graceful_shutdown([w1], [t1], None))
    if release:
        # 场景 A：宽限已开启（shutdown 发起、poll 已停）再放行——真正检验 grace 窗口
        await asyncio.sleep(0.2)
        CTRL["release"][ticket].set()
    await asyncio.wait_for(shutdown_task, 30)
    try:
        result = await asyncio.wait_for(handle.result(), 40)
    except Exception as e:
        result = {"status": "raised", "text": "%s: %s" % (type(e).__name__, e)}
    finally:
        t2.cancel()
        try:
            await asyncio.gather(t2, return_exceptions=True)
        except Exception:
            pass
    await asyncio.sleep(0.3)  # 让 worker2 的终态日志/注册表落定（护栏非断言）
    return result


async def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    capture = _LogCapture()
    logging.getLogger().addHandler(capture)
    async with await WorkflowEnvironment.start_local() as env:
        # ---- 场景 A：grace 生效（要求①）----
        res_a = await _run_scenario(env, capture, queue=Q_A,
                                    ticket="t-selfcheck-a", stage="slow_stage_a",
                                    mode="plain", grace_env="3",
                                    worker2_activities=True, release=True)
        texts = capture.texts()
        named = [t for t in texts if "停机点名" in t and "t-selfcheck-a" in t]
        ok(res_a.get("status") == "ok" and res_a.get("res", {}).get("ok") is True,
           "A：宽限期内 stub 收尾，workflow 结果 ok（%s）" % res_a)
        ok(bool(named), "A：停机日志点名在飞活动（票/段）：%s" % (named[:1] or ["<无>"]))
        ok(any("graceful_shutdown_timeout=3.0s" in t for t in texts),
           "A：停机日志带宽限值（3.0s）")
        outcomes = [e for e in agent_activities.recent_stage_outcomes()
                    if e.get("ticket") == "t-selfcheck-a"]
        ok(bool(outcomes) and outcomes[0]["outcome"] == "completed",
           "A：注册表终态=completed（%s）" % outcomes[:1])

        # ---- 场景 B：取消可辨（要求②）----
        res_b = await _run_scenario(env, capture, queue=Q_B,
                                    ticket="t-selfcheck-b", stage="slow_stage_b",
                                    mode="classify", grace_env="0",
                                    worker2_activities=False, release=False)
        ok(res_b.get("status") == "failed" and res_b.get("classified") is True,
           "B：停机取消被分类为 worker_terminated（%s）" % res_b)
        txt = res_b.get("text") or ""
        ok("worker 被外部终止（停机/重载）" in txt and "t-selfcheck-b" in txt
           and "slow_stage_b" in txt,
           "B：票面文案点名 worker 终止+票号段号（%s）" % txt)
        ok("活动故障（已重试）" not in txt, "B：不再出现无信息旧文案")
        outcomes_b = [e for e in agent_activities.recent_stage_outcomes()
                      if e.get("ticket") == "t-selfcheck-b"]
        ok(bool(outcomes_b) and outcomes_b[0]["outcome"] == "worker_terminated",
           "B：注册表终态=worker_terminated（%s）" % outcomes_b[:1])

        # ---- 场景 C：自动重跑一次（要求④）----
        res_c = await _run_scenario(env, capture, queue=Q_C,
                                    ticket="t-selfcheck-c", stage="slow_stage_c",
                                    mode="retry", grace_env="0",
                                    worker2_activities=True, release=False)
        ok(res_c.get("status") == "ok" and CTRL["calls"].get("t-selfcheck-c") == 2,
           "C：停机取消后自动重跑一次成功（calls=%s，res=%s）"
           % (CTRL["calls"].get("t-selfcheck-c"), res_c))

    print("PASS=%d FAIL=%d" % (PASS, FAIL), file=sys.stderr)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
