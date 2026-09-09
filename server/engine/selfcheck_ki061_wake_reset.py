#!/usr/bin/env python3
"""selfcheck_ki061_wake_reset — the KI-061 two-phase main gate: waking an
over-limit blocked ticket to re-run (ticket 260908).

Runs against a real SDK instance (temporalio.testing.WorkflowEnvironment.
start_local local test server — the time-skipping environment wedges when two
workers switch, tasks stay unclaimed after scheduling, so it was dropped in
practice; the local test server is not a real deployment server, zero model /
zero real agent — every activity is a stub) and switches worker code across
two phases to separate a real fix from a false green:

  Phase one (reproduce the 02:12 stuck state of t260907-10): worker code runs
    with SANDBAR_TEST_DISABLE_KI061=1 (equivalent to pre-fix behavior) until the
    test set exceeds the 6-round limit and goes blocked; then one retry_qc wake
    signal is sent, asserting settle -> blocked again and no arbitrate respawn
    (the memoized infinite loop is reproduced).
  Phase two (equivalent to the fixed worker): start a new worker in the same
    environment (switch off = fix enabled), inject a host_ruling first, then
    send retry_qc, asserting:
      1. arbitrate really respawns (7th call, gen increments) — the poisoned
         memo did not swallow the reset;
      2. the prompt carries the host ruling (the host_rulings injection surface
         is consumed);
      3. verdict=pass reaches the merge human gate (passes the gate) and no
         workflow task fails along the way.

Regression slot: a rework wake must not trigger the reset (handled at the top of
the main loop) — covering this with a rework probe before phase two is not
possible (rework changes the phase), so it is asserted at the unit-test layer
instead (see tests/test_t260908_01_ki061_wake_reset.py).

Exit code 0 = all green; non-zero = at least one red (details on stderr).
Resource cleanup: env/worker are all reclaimed via async-with finalizers; the
stubs create zero temp files.

Pattern declaration (same as selfcheck_epic_next / selfcheck_integ_loop): zero
model, zero real agent (stub receipts), the exit-code contract, no wall-clock
timing assertions (poll + timeout guardrails only) — all carried over; the only
pattern exception is the local test server (required by the main gate,
declared in the 260908 review condition 1, degradation path in plan v2
section 3-S3).

Usage (engine directory): .venv/bin/python selfcheck_ki061_wake_reset.py
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


# ---------- activity stubs (all zero IO; receipts are in-memory dataclass shapes) ----------

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
    """Factory for agent-stage stubs: returns StageResult per script(step) and
    records the prompt/gen."""

    @activity.defn(name=step_id)
    async def stub(args) -> StageResult:
        return script(step_id, args)

    return stub


def _script(step_id: str, args) -> StageResult:
    if not isinstance(args, dict):  # the untyped stub receives the dict payload (dataclass serialization shape)
        args = vars(args)
    if step_id == "arbitrate":
        CTRL["arb_calls"] += 1
        CTRL["arb_prompts"].append(str(args.get("prompt") or ""))
        CTRL["arb_gens"].append(int(args.get("gen") if args.get("gen") is not None else -1))
        n = CTRL["arb_calls"]
        if n <= 5:  # rounds 1..5: tests-fault within the limit, the loop re-runs
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 %d 轮测试集仍红，迭代" % n,
                               report="r", evidence="e")
        if n == 6:  # round 6: the ticket's "6 rounds over limit" wording (route uses the pre-increment round count, so this round still iterates)
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 6 轮超限",
                               report="r", evidence="e")
        if n == 7:  # round 7: tests_rounds=6>5 -> route=blocked, hand to a human
            return StageResult(status=STAGE_OK,
                               summary="verdict=tests-fault 第 7 轮（route=blocked）",
                               report="r", evidence="e")
        # 7th call (post-fix wake re-run): adopt the host ruling and judge pass
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


# ---------- assertion framework ----------

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
    async with await WorkflowEnvironment.start_local() as env:
        inp = TicketInput(
            ticket_id="t260908-01-selfcheck", template_id="dev-lane",
            title="KI-061 两相主闸", lane="dir",
            workspace={"type": "dir", "path": "/tmp/ki061-selfcheck-ws"},
            write_set=[],
            no_file_changes=True,  # skip the "lane has 0 commits" mechanical gate (the stub has no real lane)
            user_request="selfcheck", body="selfcheck")
        handle = await env.client.start_workflow(
            dev_lane.DevLaneWorkflow.run, inp, id="ki061-selfcheck", task_queue=Q)

        # ---- phase one: reproduce the 02:12 stuck state (switch on = pre-fix behavior) ----
        # note: the Temporal worker's workflow sandbox re-imports dev_lane on its
        # own, so monkeypatching module attributes does not reach it — the only
        # channel is environment variables (read at sandbox import time, effective
        # at worker construction).
        os.environ["SANDBAR_TEST_DISABLE_KI061"] = "1"
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            # during the parallel branch meta.stage=arb_acc_parallel; the route decision
            # uses the pre-increment round count -> only the 7th call goes blocked;
            # during the fan-out meta.stage is the last single-sided stage entered
            # (acceptance_walkthrough)
            def _stuck(s):
                return s["stage_state"] == "blocked" and s["stage"] in (
                    "arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
            ok(await wait_for(handle, _stuck, 30, "相一进入超限 blocked"),
               "相一：测试集迭代超限转 blocked（仲裁段）")
            n0 = CTRL["arb_calls"]
            ok(n0 == 7, "相一：arbitrate 调了 7 次（1..6 迭代 + 第 7 轮 route=blocked），实际 %d" % n0)

            await handle.signal("retry_qc", "selfcheck")
            await asyncio.sleep(1.5)  # observation window: expect settle -> blocked again, not a respawn
            n1 = CTRL["arb_calls"]
            snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
            ok(n1 == n0, "相一：retry_qc 唤醒后 arbitrate 无 respawn（%d→%d，memoized 复现卡死）"
               % (n0, n1))
            ok(_stuck(snap), "相一：唤醒后 settle→再 blocked（02:12 形态复现）snap=%s/%s"
               % (snap["stage"], snap["stage_state"]))

        # ---- phase two: switch to the fixed worker (switch off = fix enabled), ruling before wake ----
        os.environ.pop("SANDBAR_TEST_DISABLE_KI061", None)
        async with Worker(env.client, task_queue=Q, workflows=[dev_lane.DevLaneWorkflow],
                          activities=STUBS):
            await asyncio.sleep(1.0)  # wait for worker2's poller before signalling
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
