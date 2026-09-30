#!/usr/bin/env python3
"""selfcheck_t260916_19_join_escape — 并行汇合段路径闸 blocked 死结的出路可达性
（工单 t260916-19 验收①，实案=dengzhufpv t260916-11）。

Runs against a real SDK instance (temporalio.testing.WorkflowEnvironment.
start_local local test server — the time-skipping environment wedges when two
workers switch, tasks stay unclaimed after scheduling, so it was dropped in
practice; the local test server is not a real deployment server, zero model /
zero real agent — every activity is a stub) and switches worker code across
two phases to separate a real fix from a false green. Pattern declaration
identical to selfcheck_ki061_wake_reset (two-phase worker switch, exit-code
contract, poll+timeout guardrails only, async-with full teardown).

  Phase one (reproduce the t260916-11 stuck state): worker code runs with
    SANDBAR_TEST_DISABLE_REWORK_ESCAPE=1 (equivalent to pre-fix behavior) until
    the integ_join settle returns a path-gate refusal and the ticket goes
    blocked; then rework(to_stage=design_integration_tests) is sent — asserting
    the OLD silent-fallback behavior: the design edge does NOT re-run and the
    settle is re-judged red with an unchanged workspace (the deadlock loop).
  Phase two (equivalent to the fixed worker): switch the env off in the same
    workflow instance, send rework(to_stage=design_integration_tests) again,
    asserting:
      1. the design edge genuinely re-runs (design stub called again, gen+1);
      2. the settle no longer reds (stub turns green = "workspace remediated"),
         and the main chain reaches the merge human gate (awaiting-human);
      3. no workflow task failure along the way.

Exit code 0 = all green; non-zero = at least one red (details on stderr).
Resource cleanup: env/worker are all reclaimed via async-with finalizers; the
stubs create zero temp files.

The refusal receipt (path_gate_reason= + gate_refusal structured detail) mirrors
what agent_activities.settle_lane produces on a real unauthorized-path red —
stub-level, no real git involved (the B-step remediation behavior is covered by
tests/test_t260916_19_gate_deadlock.py with real temp repos).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402
import temporalio.activity as activity  # noqa: E402

import dev_lane  # noqa: E402
from shared import (  # noqa: E402
    HumanGateContext,
    IntegrationRunResult,
    MergeCheckResult,
    ReviewGateResult,
    SettleLaneResult,
    StageResult,
    TicketInput,
    UiEvidenceDeclResult,
    UiEvidenceResult,
    WorkspacePrepResult,
)

Q = "t26091619-selfcheck-q"
# 相分桶（phase=1|2）：两相是两个独立 workflow 实例（各自历史一致）。同一实例跨
# worker 切换环境开关会破坏重放决定性（worker2 重放相一历史时门已开 → 分支不同 →
# TMPRL1100 NonDeterministicError，实测）——两相法必须换实例，开关只在实例存续期
# 内保持恒定。
CTRL = {"phase": 1, "settle": [0, 0], "design": [0, 0], "design_gens": [[], []],
        "impl": [0, 0]}
STAGE_OK = "ok"

# settle_lane 的闸拒回执（镜像 agent_activities 真实产物的形状：机读键+结构化明细）
REFUSAL_NOTE = (
    "阶段路径闸拒绝落盘（path_gate_reason=unauthorized_path）：段 integ_join 不允许改 "
    "integration/rogue.py（本段只许：写集内文件 ∪ integration/ + 结果文件）——"
    "合法出路：rework 打回 design_integration_tests 修 integration/ 面内容"
    "（场景/登记表/共享测试工具），或建票把文件列入写集，或回 main 侧走票"
)
GATE_REFUSAL = {
    "check_id": "path_gate@integ_join",
    "item": "段×允许面路径闸",
    "red": True,
    "reason_code": "unauthorized_path",
    "files": ["integration/rogue.py"],
    "judged_files": ["integration/rogue.py"],
    "next_action": "按回执出路处置越权文件或建票",
    "evidence": REFUSAL_NOTE,
}


# ---------- activity stubs (all zero IO; receipts are in-memory dataclass shapes) ----------

@activity.defn(name="prepare_workspace")
async def stub_prepare_workspace(args) -> WorkspacePrepResult:
    return WorkspacePrepResult(ok=True, kind="dir", action="ensured", path="/tmp/t26091619-stub")


@activity.defn(name="ui_evidence_decl")
async def stub_ui_evidence_decl(args) -> UiEvidenceDeclResult:
    return UiEvidenceDeclResult(mode="absent", note="stub")


@activity.defn(name="prepare_ui_evidence")
async def stub_prepare_ui_evidence(args) -> UiEvidenceResult:
    return UiEvidenceResult(ok=True, shots=[])


@activity.defn(name="verify_review_gate")
async def stub_verify_review_gate(args) -> ReviewGateResult:
    return ReviewGateResult(git_error="", lane_commits=1, shots_path_error="", png_count=0)


@activity.defn(name="settle_lane")
async def stub_settle_lane(args) -> SettleLaneResult:
    """integ_join 汇合落盘（按相分桶）：相一恒拒（死结复现：复判同红）；相二第 1 次
    拒（blocked 进死结态）、出路重跑设计边后第 2 次=干净（模拟越权已处置）。"""
    i = CTRL["phase"] - 1
    CTRL["settle"][i] += 1
    if CTRL["phase"] == 1 or CTRL["settle"][i] == 1:
        return SettleLaneResult(note=REFUSAL_NOTE, lane_commits=3, error=REFUSAL_NOTE,
                                gate_refusal=dict(GATE_REFUSAL))
    return SettleLaneResult(note="工作区已干净，无需代落盘", lane_commits=3, error="")


@activity.defn(name="ui_changed_paths")
async def stub_ui_changed_paths(args):
    return {"paths": []}


@activity.defn(name="run_integration_tests")
async def stub_run_integration_tests(args) -> IntegrationRunResult:
    return IntegrationRunResult(ran=2, passed=2, failed=0, env_fail=0,
                                details=[{"name": "a", "exit": 0}, {"name": "b", "exit": 0}])


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
async def stub_prepare_human_gate(args) -> HumanGateContext:
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


def _agent_stub(step_id: str, script):
    @activity.defn(name=step_id)
    async def stub(args) -> StageResult:
        return script(step_id, args)

    return stub


def _script(step_id: str, args) -> StageResult:
    if not isinstance(args, dict):  # the untyped stub receives the dict payload (dataclass serialization shape)
        args = vars(args)
    i = CTRL["phase"] - 1
    if step_id == "design_integration_tests":
        CTRL["design"][i] += 1
        CTRL["design_gens"][i].append(int(args.get("gen") if args.get("gen") is not None else -1))
    if step_id == "implement":
        CTRL["impl"][i] += 1
    if step_id == "arbitrate":
        return StageResult(status=STAGE_OK,
                           summary="verdict=pass 集成测试全绿，判过闸",
                           report="r", evidence="e")
    return StageResult(status=STAGE_OK, summary="stub %s 完成" % step_id,
                       report="r", evidence="e")


STUBS = [
    stub_prepare_workspace, stub_ui_evidence_decl, stub_prepare_ui_evidence,
    stub_verify_review_gate, stub_settle_lane, stub_ui_changed_paths,
    stub_run_integration_tests, stub_merge_check, stub_prepare_conflict_resolution,
    stub_settle_conflict_resolution, stub_prepare_human_gate, stub_merge,
    stub_archive_ticket, stub_teardown_lane,
] + [_agent_stub(s, _script) for s in
     ("create_plan", "review_plan", "implement", "design_integration_tests",
      "arbitrate", "acceptance_walkthrough")]


# ---------- assertion framework ----------

from selfcheck_common import Selfcheck  # noqa: E402  t261001-04：ok() 收敛到唯一定义，输出格式逐字不变

_rep = Selfcheck(ok_fmt="ok - %s", fail_fmt="FAIL - %s", fail_stream=sys.stderr)
ok = _rep.ok


async def wait_for(handle, cond_fn, timeout_s: float, label: str) -> bool:
    """Poll the snapshot for a condition (no wall-clock timing coupling; the
    timeout is only a guardrail)."""
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
    try:
        env = await WorkflowEnvironment.start_local()
    except Exception as e:
        # ENV_FAIL 纪律（t260904-12 三态化）：没验成且原因归环境 ≠ 通过——点名缺什么
        # 退出 2，不假红也不假绿。首次运行需下载 Temporal dev server 二进制（外网）；
        # 二进制就位后本场景在无网环境可复跑。
        print("ENV_FAIL: Temporal dev server 不可用（首次运行需外网下载二进制：%s: %s）"
              % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 2
    async with env:
        # ---- phase one：独立 workflow 实例（env 开关在实例存续期恒定=重放决定性） ----
        os.environ["SANDBAR_TEST_DISABLE_REWORK_ESCAPE"] = "1"
        CTRL["phase"] = 1
        # note: the Temporal worker's workflow sandbox re-imports dev_lane on its
        # own, so monkeypatching module attributes does not reach it — the only
        # channel is environment variables (read at sandbox import time, effective
        # at worker construction).
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            handle = await env.client.start_workflow(
                dev_lane.DevLaneWorkflow.run,
                TicketInput(ticket_id="t26091619-selfcheck-p1", template_id="dev-lane",
                            title="t260916-19 join 出路可达性（相一死结复现）", lane="dir",
                            workspace={"type": "dir", "path": "/tmp/t26091619-selfcheck-ws"},
                            write_set=[],
                            no_file_changes=True,  # skip the "lane has 0 commits" mechanical gate (the stub has no real lane)
                            user_request="selfcheck", body="selfcheck"),
                id="t26091619-selfcheck-p1", task_queue=Q)
            ok(await wait_for(handle, lambda s: s["stage_state"] == "blocked", 90,
                              "相一进入 integ_join 闸拒 blocked"),
               "相一：汇合 settle 闸拒 → blocked（死结态进入）")
            settle0 = CTRL["settle"][0]
            design0 = CTRL["design"][0]
            ok(design0 == 1, "相一：design 边已跑 1 次（初始分叉），实际 %d" % design0)
            ok(settle0 == 1, "相一：settle_lane 调了 1 次（拒绝），实际 %d" % settle0)

            await handle.signal("rework", dev_lane.ReworkRequest(
                who="selfcheck", note="按出路打回设计集成测试段",
                target_stage="design_integration_tests"))
            ok(await wait_for(handle, lambda s: s["stage_state"] == "blocked"
                              and CTRL["settle"][0] >= 2, 30,
                              "相一 rework 后复判再 blocked"),
               "相一：rework 后旧路径静默回落 → settle 复判同一红 → 再 blocked（死结复现）")
            await asyncio.sleep(1.0)
            ok(CTRL["design"][0] == design0,
               "相一：design 边零重跑（%d→%d，词表缺口静默回落实锤）"
               % (design0, CTRL["design"][0]))
            ok(CTRL["settle"][0] == settle0 + 1,
               "相一：settle_lane 空转复判（%d→%d，工作区未变必然复红）"
               % (settle0, CTRL["settle"][0]))
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
            ok("path_gate_reason=" in str(snap.get("blocked_reason") or ""),
               "相一：blocked_reason 上台面且含闸拒机读键")
            # 相一使命完成：终决收尾（不再演进历史，避免跨 worker 重放）
            await handle.cancel()

        # ---- phase two：修后 worker + 全新 workflow 实例（历史各自一致） ----
        os.environ.pop("SANDBAR_TEST_DISABLE_REWORK_ESCAPE", None)
        CTRL["phase"] = 2
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            handle = await env.client.start_workflow(
                dev_lane.DevLaneWorkflow.run,
                TicketInput(ticket_id="t26091619-selfcheck-p2", template_id="dev-lane",
                            title="t260916-19 join 出路可达性（相二修后直达）", lane="dir",
                            workspace={"type": "dir", "path": "/tmp/t26091619-selfcheck-ws"},
                            write_set=[],
                            no_file_changes=True,
                            user_request="selfcheck", body="selfcheck"),
                id="t26091619-selfcheck-p2", task_queue=Q)
            ok(await wait_for(handle, lambda s: s["stage_state"] == "blocked", 90,
                              "相二进入 blocked（同相一链路，修后 worker）"),
               "相二：同链路进 blocked，出路可达性待验")
            design0 = CTRL["design"][1]
            settle0 = CTRL["settle"][1]

            # 反用例（验收①）：非词表非别名的目标 → 显式拒收，不回落、不空转
            await handle.signal("rework", dev_lane.ReworkRequest(
                who="selfcheck", note="反用例：词表外目标",
                target_stage="acceptance_walkthrough"))
            ok(await wait_for(handle, lambda s: "【rework 拒收】" in str(s.get("blocked_reason") or ""),
                              30, "相二非法目标显式拒收"),
               "相二：rework(to_stage=acceptance_walkthrough) → 显式拒收上台面（【rework 拒收】前缀）")
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
            ok("design_integration_tests" in str(snap.get("blocked_reason") or ""),
               "相二：拒收文案点名别名出路")
            ok(CTRL["settle"][1] == settle0,
               "相二：拒收零副作用（settle 不复判 %d 次）" % CTRL["settle"][1])
            ok(CTRL["design"][1] == design0,
               "相二：拒收零副作用（design 边不动 %d 次）" % CTRL["design"][1])

            # 正用例：别名直达——design 边真重跑，主链推进到 merge 人审门
            await handle.signal("rework", dev_lane.ReworkRequest(
                who="selfcheck", note="按出路打回设计集成测试段（修后）",
                target_stage="design_integration_tests"))
            ok(await wait_for(handle, lambda s: s["stage"] == "merge"
                              and s["stage_state"] == "awaiting-human", 90,
                              "相二走到 merge 人审门"),
               "相二：rework(to_stage=design_integration_tests) 直达设计边重跑 → 主链推进到 merge 人审门")
            ok(CTRL["design"][1] == design0 + 1,
               "相二：design 边真重跑（%d→%d 次，gen=%s 非重放）"
               % (design0, CTRL["design"][1], CTRL["design_gens"][1][-1:]))
            ok(CTRL["design_gens"][1][-1] > CTRL["design_gens"][1][0],
               "相二：design gen 递增（真重跑非 memo）")
            ok(CTRL["settle"][1] == settle0 + 2,
               "相二：settle 恰好两跳后到人审门（%d→%d：integ_join 转绿 1 次 + "
               "arb_acc 汇合段落盘 1 次，零空转复判）"
               % (settle0, CTRL["settle"][1]))
            ok(CTRL["impl"][1] == 1,
               "相二：implement 边未被重跑（结果保留，%d 次）" % CTRL["impl"][1])
    print("PASS=%d FAIL=%d" % (_rep.passes, _rep.fails), file=sys.stderr)
    return 0 if _rep.fails == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
