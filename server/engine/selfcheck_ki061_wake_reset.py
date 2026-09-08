#!/usr/bin/env python3
"""selfcheck_ki061_wake_reset —— KI-061 仲裁超限 blocked 唤醒重跑（260908 票）两相主闸。

真 SDK 实例（temporalio.testing.WorkflowEnvironment.start_local 本地 test server——
time-skipping 环境双 worker 切换会 wedge（任务调度后无人认领），实测弃用；本地 test
server 非真部署 server、零模型/零真 agent——全部活动 stub）跨 worker 代码切换，
区分「真修」与「假绿」：

  相一（复刻 t260907-10 02:12 卡死）：worker 代码带 SANDBAR_TEST_DISABLE_KI061=1
    （等价修复前行为）驱动到测试集 6 轮超限 blocked，发 retry_qc 唤醒一次，
    断言 settle→再 blocked、arbitrate 无 respawn（复现 memoized 死循环）。
  相二（等价换修复后 worker）：同环境起新 worker（开关关=修复启用），先注入
    host_ruling 宿主终裁再发 retry_qc，断言：
      ① arbitrate 真 respawn（第 7 次调用，gen 递增）——memo 毒化未吞掉重置；
      ② prompt 含宿主终裁（host_rulings 注入面消费）；
      ③ verdict=pass 走到 merge 人审门（过闸）且 workflow task 全程不 failing。

回归位：rework 唤醒不触发重置（主循环顶处理）——由相二前置 rework 探针覆盖不可行
（rework 会改 phase），改为单测层断言（见 tests/test_t260908_01_ki061_wake_reset.py）。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。资源回收：env/worker 全部 async with
终态回收；stub 零临时文件。

照 pattern 声明（selfcheck_epic_next / selfcheck_integ_loop）：零模型零真 agent（stub
回执）、退出码契约、无 wall-clock 时序断言（轮询 poll + 超时护栏）——均已带过来；
唯一的 pattern 例外是本地 test server（主闸必需，260908 票 review 附条件①已声明，
降级路径见方案 v2 §3-S3）。

用法（engine 目录）：.venv/bin/python selfcheck_ki061_wake_reset.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from temporalio import activity, workflow  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

import dev_lane  # noqa: E402
from shared import (  # noqa: E402
    HostRulingRequest,
    IntegrationRunResult,
    MergeCheckResult,
    ReviewGateResult,
    SettleLaneResult,
    StageResult,
    UiEvidenceResult,
    TicketInput,
    UiEvidenceDeclResult,
    WorkspacePrepResult,
    HumanGateContext,
)

Q = "ki061-selfcheck-q"
CTRL = {"arb_calls": 0, "arb_prompts": [], "arb_gens": []}
RULING_NOTE = "宿主 260908 终裁：终裁生效，判 pass 过闸"
STAGE_OK = "ok"


# ---------- 活动桩（全部零 IO，回执=结果 dataclass 内存形态） ----------

@activity.defn(name="prepare_workspace")
async def stub_prepare_workspace(args) -> WorkspacePrepResult:
    return WorkspacePrepResult(ok=True, kind="dir", action="ensured", path="/tmp/ki061-stub")


@activity.defn(name="ui_evidence_decl")
async def stub_ui_evidence_decl(args) -> UiEvidenceDeclResult:
    return UiEvidenceDeclResult(mode="absent", note="stub")


@activity.defn(name="prepare_ui_evidence")
async def stub_prepare_ui_evidence(args) -> "UiEvidenceResult":
    return UiEvidenceResult(ok=True, shots=[])


@activity.defn(name="verify_review_gate")
async def stub_verify_review_gate(args) -> ReviewGateResult:
    return ReviewGateResult(git_error="", lane_commits=1, shots_path_error="", png_count=0)


@activity.defn(name="settle_lane")
async def stub_settle_lane(args) -> SettleLaneResult:
    return SettleLaneResult(note="stub 落盘", lane_commits=1)


@activity.defn(name="ui_changed_paths")
async def stub_ui_changed_paths(args):
    return {"paths": []}


@activity.defn(name="run_integration_tests")
async def stub_run_integration_tests(args) -> IntegrationRunResult:
    return IntegrationRunResult(ran=2, passed=0, failed=2, env_fail=0,
                                details=[{"name": "a", "exit": 1}, {"name": "b", "exit": 2}])


@activity.defn(name="merge_check")
async def stub_merge_check(args) -> MergeCheckResult:
    return MergeCheckResult(green=True, checks=[{"item": "stub", "green": True, "detail": ""}])


@activity.defn(name="prepare_conflict_resolution")
async def stub_prepare_conflict_resolution(args) -> str:
    return ""


@activity.defn(name="settle_conflict_resolution")
async def stub_settle_conflict_resolution(args) -> SettleLaneResult:
    return SettleLaneResult(note="stub", lane_commits=1)


@activity.defn(name="prepare_human_gate")
async def stub_prepare_human_gate(args) -> "HumanGateContext":
    return HumanGateContext(ok=True, context_text="stub", note="stub")


@activity.defn(name="merge")
async def stub_merge(args) -> str:
    return "stub"


@activity.defn(name="archive_ticket")
async def stub_archive_ticket(args) -> str:
    return "stub"


@activity.defn(name="teardown_lane")
async def stub_teardown_lane(args) -> str:
    return "stub"


@activity.defn(name="suggest_next")
async def stub_suggest_next(args) -> StageResult:
    return StageResult(status="ok", summary="stub")


def _agent_stub(step_id: str, script):
    """agent 段桩工厂：按 script(step) 回 StageResult，并录 prompt/gen。"""

    @activity.defn(name=step_id)
    async def stub(args) -> StageResult:
        return script(step_id, args)

    return stub


def _script(step_id: str, args) -> StageResult:
    if not isinstance(args, dict):  # 无类型签名桩收到 dict 载荷（dataclass 序列化形态）
        args = vars(args)
    if step_id == "arbitrate":
        CTRL["arb_calls"] += 1
        CTRL["arb_prompts"].append(str(args.get("prompt") or ""))
        CTRL["arb_gens"].append(int(args.get("gen") if args.get("gen") is not None else -1))
        n = CTRL["arb_calls"]
        if n <= 5:  # 1..5 轮：tests-fault 在限内，回路重跑
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 %d 轮测试集仍红，迭代" % n,
                               report="r", evidence="e")
        if n == 6:  # 第 6 轮：票面「6 轮超限」口径（route 用自增前轮数，此轮仍迭代）
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 6 轮超限",
                               report="r", evidence="e")
        if n == 7:  # 第 7 轮：tests_rounds=6>5 → route=blocked 转人工
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 7 轮（route=blocked）",
                               report="r", evidence="e")
        # 第 7 次（修复后唤醒重跑）：采纳宿主终裁判 pass
        return StageResult(status=STAGE_OK,
                           summary="verdict=pass 采纳宿主终裁，过闸",
                           report="r", evidence="e")
    if step_id == "review_plan":
        return StageResult(status=STAGE_OK, summary="verdict=pass 方案审通过",
                           report="r", evidence="e", deliverables=["docs/x.md"])
    if step_id == "create_plan":
        return StageResult(status=STAGE_OK, summary="方案完成", report="r", evidence="e",
                           deliverables=[".sandbar/stage_create_plan_gen0.json"])
    return StageResult(status=STAGE_OK, summary="stub %s 完成" % step_id,
                       report="r", evidence="e")


STUBS = [
    stub_prepare_workspace, stub_ui_evidence_decl, stub_prepare_ui_evidence,
    stub_verify_review_gate, stub_settle_lane, stub_ui_changed_paths,
    stub_run_integration_tests, stub_merge_check, stub_prepare_conflict_resolution,
    stub_settle_conflict_resolution, stub_prepare_human_gate, stub_merge,
    stub_archive_ticket, stub_teardown_lane, stub_suggest_next,
] + [_agent_stub(s, _script) for s in
     ("create_plan", "review_plan", "implement", "design_integration_tests",
      "arbitrate", "acceptance_walkthrough")]


# ---------- 断言框架 ----------

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


async def wait_for(handle, cond_fn, timeout_s: float, label: str) -> bool:
    """轮询 snapshot 断言（无 wall-clock 时序耦合，超时只作护栏）。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    snap = None
    while loop.time() < deadline:
        try:
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
        except Exception:
            await asyncio.sleep(0.2)
            continue
        if snap and cond_fn(snap):
            return True
        await asyncio.sleep(0.05)
    print("TIMEOUT %s；末次 snapshot=%s" % (label, snap), file=sys.stderr)
    return False


async def main() -> int:
    async with await WorkflowEnvironment.start_local() as env:
        inp = TicketInput(
            ticket_id="t260908-01-selfcheck", template_id="dev-lane",
            title="KI-061 两相主闸", lane="dir",
            workspace={"type": "dir", "path": "/tmp/ki061-selfcheck-ws"},
            write_set=[],
            no_file_changes=True,  # 跳「泳道 0 commit」机械闸（stub 无真泳道）
            user_request="selfcheck", body="selfcheck")
        handle = await env.client.start_workflow(
            dev_lane.DevLaneWorkflow.run, inp, id="ki061-selfcheck", task_queue=Q)

        # ---- 相一：复刻 02:12 卡死（开关开=修复前行为）----
        # 注意：Temporal worker 的 workflow sandbox 会独立重导入 dev_lane，对模块属性
        # 打猴补丁传不进去——只能走环境变量（sandbox import 期读定，worker 构造期生效）。
        os.environ["SANDBAR_TEST_DISABLE_KI061"] = "1"
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            # 并行分支期 meta.stage=arb_acc_parallel；route 判定用自增前轮数 → 第 7 次调用才 blocked
            # 并行分叉期 meta.stage=分叉内最后进入的单边（acceptance_walkthrough）
            def _stuck(s):
                return s["stage_state"] == "blocked" and s["stage"] in (
                    "arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
            ok(await wait_for(handle, _stuck, 30, "相一进入超限 blocked"),
               "相一：测试集迭代超限转 blocked（仲裁段）")
            n0 = CTRL["arb_calls"]
            ok(n0 == 7, "相一：arbitrate 调了 7 次（1..6 迭代 + 第 7 轮 route=blocked），实际 %d" % n0)

            await handle.signal("retry_qc", "selfcheck")
            await asyncio.sleep(1.5)  # 观察窗：期望 settle→再 blocked，而非 respawn
            n1 = CTRL["arb_calls"]
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
            ok(n1 == n0, "相一：retry_qc 唤醒后 arbitrate 无 respawn（%d→%d，memoized 复现卡死）"
               % (n0, n1))
            ok(_stuck(snap), "相一：唤醒后 settle→再 blocked（02:12 形态复现）snap=%s/%s"
               % (snap["stage"], snap["stage_state"]))

        # ---- 相二：换修复后 worker（开关关=修复启用），先终裁再唤醒 ----
        os.environ.pop("SANDBAR_TEST_DISABLE_KI061", None)
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            await asyncio.sleep(1.0)  # 等 worker2 poller 就绪再发信号
            await handle.signal("host_ruling",
                                HostRulingRequest(who="host", note=RULING_NOTE))
            await handle.signal("retry_qc", "selfcheck")
            await asyncio.sleep(3.0)
            ok(await wait_for(handle, lambda s: s["stage"] == "merge", 30,
                              "相二走到 merge 人审门"), "相二：verdict=pass 过闸到 merge 人审门")
            n2 = CTRL["arb_calls"]
            ok(n2 == 8, "相二：arbitrate 真 respawn（7→8 次，gen=%s）" % CTRL["arb_gens"][-1:])
            ok(CTRL["arb_gens"][-1] > CTRL["arb_gens"][0], "相二：arbitrate gen 递增（非 memo 重放）")
            ok(RULING_NOTE in CTRL["arb_prompts"][-1],
               "相二：重跑 arbitrate 的 prompt 含宿主终裁（host_rulings 注入消费）")
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
            ok(snap["stage"] == "merge" and snap["stage_state"] == "awaiting-human",
               "相二：终态=merge 人审门挂起等 sign（awaiting-human）")

    print("PASS=%d FAIL=%d" % (PASS, FAIL), file=sys.stderr)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
