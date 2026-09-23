#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证前主同步 main 的真编排契约（t260922-18，灰盒 L3，混合台架：Temporal 本地测试
服务器 + dev_lane 真 workflow + 真 git 泳道 + 真 git 活动 + 可控桩脑，零 docker 零模型）。

intent（登记于 run_scenarios.py SCENARIOS）：宿主拍板「只在机械验证前由 worker 并一次
main——被验证的树=将要被合并的树」。本场景锁该承诺的**运行时编排行为与票面可感知面**：

- 时点与被验证树：每一轮 run_integration_tests 跑闸发生时，泳道 HEAD 已包含本轮开工
  后前进的 main tip（探针桩在跑闸被调时刻捕获泳道 HEAD，逐轮断言 main tip 为其祖先）
  ——首轮验证树即「main+票改动」的 merge commit（双亲），老票不再以 merge_check 冲突
  形态才第一次知道 main 前进（KI-082 清偿回归）；
- 幂等：已追平后的后续验证轮不产生新 merge commit（快路径零动作），但跑闸每轮真跑
  （探针桩逐轮被调=「同步后必重跑」的编排面证据，无旧报告复用分支）；
- 证据上台面：验证轮票面 results["run_integration_tests"] 含主同步证据（「主同步」
  +「main@」子串），冲突消解轨迹进 timeline/handoffs；
- 冲突回路回实现段：main 与票文件相撞 → 主同步留冲突现场 → agent 消解步收到
  「冲突标记」提示词与「不要 git commit」令 → worker 代提交 → 票自动回 implement
  适配 main 变更 → 收敛后再验证绿、终到 merge 人审门；
- 不可达响亮转人工：main ref 不存在的票在验证相位 blocked（stage=run_integration_tests、
  状态 blocked、blocked 面含「主同步」与「不存在」），且跑闸探针零调用（同步失败
  拦在跑闸之前，绝不静默跳过同步继续跑闸）。

分界（防 intent 级重复）：
- developer UT（test_t260922_18_main_sync.py）锁纯函数矩阵/活动回执新键/legacy dict
  兼容/**源码结构断言**（patched 门、前置检查→同步→跑闸源序）——本场景不重复结构
  锁，只锁运行时行为与票面文本（浅绑定：锚「主同步」等子串与公开 snapshot 面，
  不锚实现内部名与整句文案）；
- selfcheck_conflict_resolution（developer 侧）守既有 merge_check 冲突回路闭环与
  其结构序——本场景只在真编排里消费该回路（作为主同步的冲突出口），不重放其矩阵；
- t260922-12 场景族守结果台账采信边界（sync 换 commit→旧账失配的第二层保险）——
  本场景不触台账；
- t260916-26/t260915-05 系真 docker 台全链场景守缺件预检/红卡观测面——本场景用
  temporalio 本地测试服务器（ki061 selfcheck 同款先例），守的是主同步编排本体。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
git/temporalio 缺失或本地测试服务器起不来 = ENV_FAIL exit 2 点名（无 stdlib 替代）。
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_main_sync_fixture import (  # noqa: E402
    commit_files, drop_branch, git, git_ok, head, is_ancestor, make_lane,
    make_repo, merge_commits,
)

# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# workflow/活动全程不触真 Temporal 部署面（本地测试服务器自足）。
os.environ.setdefault("SANDBAR_TARGET_HOST", "127.0.0.1:9")
ENGINE = REPO_ENG = HERE.parents[1] / "server" / "engine"
sys.path.insert(0, str(ENGINE))

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label, flush=True)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""),
              file=sys.stderr, flush=True)


# ---------- 桩脑（可控多态）与探针 ----------
# CTRL 按 ticket_id 分票记账；两票串行（票 1 到 merge 人审门挂起后才起票 2），
# CURRENT 指向当前活动票，桩据此路由到对应的夹具泳道/主仓。
CTRL = {}
CURRENT = {"tid": None}


def _ticket_ctrl(tid):
    return CTRL.setdefault(tid, {"impl": 0, "arb": 0, "gate": [],
                                 "resolve_prompts": [], "lane": "", "repo": ""})


FEATURE = "feature.md"


def _advance_or_touch(c):
    """实现态第 n 次：先让 main 前进（第 1 次无害文件、第 2 次与票文件相撞），
    再写泳道票文件（同区域相撞版）。第 3 次起只做适配、不再动 main。
    全程只写工作区文件（agent 桩无 git 元数据权；落盘由 settle_lane 真 activity 代做）。"""
    lane, repo = c["lane"], c["repo"]
    n = c["impl"] + 1
    c["impl"] = n
    if n == 1:
        commit_files(repo, {"main_note.md": "main 前进第一步\n"}, "main 前进（票开工后）")
        commit_files(lane, {FEATURE: "功能第一版第一行\n共同尾行\n"}, "票改动 v1")
    elif n == 2:
        commit_files(repo, {FEATURE: "main 版第一行\n共同尾行\n"}, "main 相撞前进")
        commit_files(lane, {FEATURE: "泳道版第一行\n共同尾行\n"}, "票改动 v2")
    else:
        p = Path(lane) / FEATURE
        p.write_text(p.read_text(encoding="utf-8") + "适配 main 变更 %d\n" % n,
                     encoding="utf-8")


async def main() -> int:
    if not git_ok():
        print("ENV_FAIL: git 缺失，真编排子用例不可验（exit 2）")
        return 2
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        import dev_lane
        from shared import (HumanGateContext, IntegrationRunResult, StageResult,
                            TicketInput, UiEvidenceDeclResult, UiEvidenceResult)
        import agent_activities as aa
    except Exception as e:
        print("ENV_FAIL: temporalio/引擎模块不可用：%r（exit 2）" % (e,))
        return 2

    td = tempfile.mkdtemp(prefix="t26092218-gate-")
    repo = make_repo(td + "/proj")
    lane = make_lane(repo, "t260922-18-gate")
    CTRL.clear()
    TID = "t260922-18-gate"
    c = _ticket_ctrl(TID)
    c["lane"], c["repo"] = str(lane), str(repo)
    CURRENT["tid"] = TID

    # ---- 桩（agent 步与跑闸探针；merge 及之后不为被测面，桩绿以放行链路）----
    def make_agent_stub(step_id):
        async def stub(args) -> StageResult:
            payload = args if isinstance(args, dict) else vars(args)
            prompt = str(payload.get("prompt") or "")
            c = CTRL[CURRENT["tid"]]
            if step_id == "implement":
                if "冲突标记" in prompt:
                    c["resolve_prompts"].append(prompt)
                    p = Path(c["lane"]) / FEATURE
                    p.write_text("合并后第一行（两边语义都保留）\n共同尾行\n",
                                 encoding="utf-8")
                    return StageResult(status="ok", summary="冲突已解（未 commit）",
                                       report="r", evidence="e")
                _advance_or_touch(c)
                return StageResult(status="ok", summary="实现完成 %d" % c["impl"],
                                   report="r", evidence="e")
            if step_id == "arbitrate":
                c["arb"] += 1
                if c["arb"] == 1:
                    return StageResult(status="ok",
                                       summary="verdict=code-fault 集成测试报告：实现问题打回",
                                       report="r", evidence="e")
                return StageResult(status="ok", summary="verdict=pass 过闸",
                                   report="r", evidence="e")
            if step_id == "review_plan":
                return StageResult(status="ok", summary="verdict=pass 方案审通过",
                                   report="r", evidence="e", deliverables=["docs/x.md"])
            return StageResult(status="ok", summary="stub %s 完成" % step_id,
                               report="r", evidence="e")
        stub.__name__ = step_id
        from temporalio import activity as _act
        return _act.defn(name=step_id)(stub)

    async def probe_gate(args) -> IntegrationRunResult:
        """跑闸探针桩：被调时刻捕获泳道 HEAD 与 main 祖先关系（时点的直接证据）。"""
        payload = args if isinstance(args, dict) else vars(args)
        tid = str(payload.get("ticket_id") or CURRENT["tid"])
        c = CTRL.setdefault(tid, _ticket_ctrl(tid))
        wt = str(payload.get("worktree") or "") or c["lane"]
        tip = git("rev-parse", "main", cwd=c["repo"], check=False).stdout.strip()
        c["gate"].append({"head": head(wt), "main_tip": tip,
                          "main_in_tree": bool(tip) and is_ancestor(tip, head(wt), wt)})
        return IntegrationRunResult(ran=1, passed=1, failed=0, env_fail=0,
                                    details=[{"name": "stub-scenario", "cmd": "true",
                                              "exit": 0, "output_tail": ""}],
                                    error="")

    async def stub_merge_check(args):
        from shared import MergeCheckResult
        return MergeCheckResult(green=True,
                                checks=[{"item": "stub", "green": True, "detail": ""}])

    async def stub_ui_decl(args) -> UiEvidenceDeclResult:
        return UiEvidenceDeclResult(mode="absent", note="stub")

    async def stub_ui_evidence(args) -> UiEvidenceResult:
        return UiEvidenceResult(ok=True, skipped=True, detail="stub 非 UI 票跳过")

    async def stub_ui_changed(args):
        from shared import UiChangedPathsResult
        return UiChangedPathsResult()

    async def stub_human_gate(args) -> HumanGateContext:
        return HumanGateContext(ok=True, context_text="stub", note="stub")

    from temporalio import activity as _act

    def named(fn, name):
        """桩注册单点：统一 @activity.defn(name=...) 包装（Worker 要求活动带 defn）。"""
        fn.__name__ = name
        return _act.defn(name=name)(fn)

    def make_named_stub(name):
        async def stub(args) -> str:
            return "stub"
        return named(stub, name)

    STUBS = ([aa.prepare_workspace, aa.verify_review_gate, aa.settle_lane,
              aa.prepare_conflict_resolution, aa.settle_conflict_resolution,
              named(probe_gate, "run_integration_tests"),
              named(stub_merge_check, "merge_check"),
              named(stub_ui_decl, "ui_evidence_decl"),
              named(stub_ui_evidence, "prepare_ui_evidence"),
              named(stub_ui_changed, "ui_changed_paths"),
              named(stub_human_gate, "prepare_human_gate")]
             + [make_agent_stub(s) for s in ("create_plan", "review_plan",
                                             "design_integration_tests", "implement",
                                             "arbitrate", "acceptance_walkthrough")]
             + [make_named_stub(s) for s in ("merge", "archive_ticket", "teardown_lane")])
    # 说明：merge/archive/teardown 桩只为防编排意外推进时 workflow 失败掩盖断言；
    # 票在 merge 人审门（awaiting-human）挂起，merge 活动在正常旅程中不会被调度。

    async def wait_for(handle, cond_fn, timeout_s, label):
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
        print("TIMEOUT %s；末次 snapshot stage=%s state=%s" %
              (label, (snap or {}).get("stage"), (snap or {}).get("stage_state")),
              file=sys.stderr)
        return False

    env_fail = 0
    try:
        env_ctx = await WorkflowEnvironment.start_local()
    except Exception as e:
        print("ENV_FAIL: temporalio 本地测试服务器起不来：%r（exit 2）" % (e,))
        return 2
    async with env_ctx as env:
        Q = "t260922-18-gate-q"
        inp = TicketInput(
            ticket_id=TID, template_id="dev-lane", title="验证前主同步",
            lane="dir", workspace={"type": "dir", "path": str(lane)},
            worktree=str(lane), branch="lane/" + TID,
            base_ref=git("rev-parse", "main", cwd=repo).stdout.strip(),
            write_set=[FEATURE], no_file_changes=False,
            user_request="宿主拍板：机械验证前由 worker 并一次 main", body="t260922-18")
        handle = await env.client.start_workflow(
            dev_lane.DevLaneWorkflow.run, inp, id=TID, task_queue=Q)
        async with Worker(env.client, task_queue=Q,
                          workflows=[dev_lane.DevLaneWorkflow], activities=STUBS):
            print("== 相A/B/C 一张票：首轮同步→证据→code-fault 回实现→相撞冲突→消解回实现→幂等再验证")
            reached = await wait_for(handle, lambda s: s["stage"] == "merge", 90,
                                     "票走到 merge 人审门")
            ok(reached, "G8 全链走通：票终到 merge 人审门（awaiting-human）",
               "stage 未到 merge")
            if reached:
                snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
                ok(snap.get("stage_state") == "awaiting-human",
                   "G8b 终态=merge awaiting-human", str(snap.get("stage_state")))
                ok(not (snap.get("blocked_reason") or ""),
                   "G9 全程零 blocked（blocked_reason 空）", str(snap.get("blocked_reason"))[:200])

            ok(len(c["gate"]) == 2,
               "G1 抵达跑闸的验证轮恰 2 轮且逐轮真跑（冲突轮被同步截停在跑闸前=时点执法，"
               "无旧报告复用分支）", str(len(c["gate"])))
            ok(all(g["main_in_tree"] for g in c["gate"]),
               "G2 每轮跑闸时 main tip 均为泳道 HEAD 祖先（被验证树=main+票改动）",
               str([(g["head"][:8], g["main_in_tree"]) for g in c["gate"]]))
            if c["gate"]:
                first = c["gate"][0]
                ok(parents2(first["head"], lane), "G3 首轮验证 HEAD=双亲 merge commit"
                   "（main 前进在票开工后，同步真落 merge）")
            mcs = merge_commits(lane)
            ok(len(mcs) == 2,
               "G4 幂等：全旅程恰 2 个 merge commit（首轮同步 1 个+消解代提交 1 个；"
               "第 3 轮已追平同步零新增=快路径零动作）", str(len(mcs)))
            if reached:
                snap = await handle.query(dev_lane.DevLaneWorkflow.snapshot)
                ri = (snap.get("results") or {}).get("run_integration_tests") or {}
                blob = str(ri.get("summary") or "") + str(ri.get("evidence") or "")
                ok("主同步" in blob and "main@" in blob,
                   "G5 主同步证据上台面（票面 summary/evidence 含「主同步」与「main@」）",
                   blob[:200])
                tl = str(snap.get("timeline") or "") + str(snap.get("handoffs") or "")
                ok("主同步冲突消解" in tl,
                   "G6 冲突消解轨迹进 timeline/handoffs", tl[-200:])
            ok(len(c["resolve_prompts"]) == 1
               and "冲突标记" in c["resolve_prompts"][0]
               and "不要 git commit" in c["resolve_prompts"][0],
               "G7 消解步提示词含冲突现场与「不要 git commit」令",
               str(len(c["resolve_prompts"])))

        # ---- 相D 第二张票：main 不可达 → blocked 响亮在跑闸之前 ----
        print("== 相D main 不可达：blocked 响亮、绝不静默跳过同步继续跑闸")
        repo2 = make_repo(td + "/proj2")
        drop_branch(repo2)
        lane2 = make_lane(repo2, "t260922-18-loud")
        TID2 = "t260922-18-loud"
        c2 = _ticket_ctrl(TID2)
        c2["lane"], c2["repo"] = str(lane2), str(repo2)
        CURRENT["tid"] = TID2
        inp2 = TicketInput(
            ticket_id=TID2, template_id="dev-lane", title="main 不可达",
            lane="dir", workspace={"type": "dir", "path": str(lane2)},
            worktree=str(lane2), branch="lane/" + TID2, base_ref="",
            write_set=[FEATURE], no_file_changes=False,
            user_request="main ref 不存在的票", body="t260922-18")
        # 实现态桩共享：票 2 首次实现会写 repo2 的 main_note.md——main 分支已删，
        # commit 落在 repo2 当前分支（detach HEAD）上，不影响「main ref 不存在」前提。
        handle2 = await env.client.start_workflow(
            dev_lane.DevLaneWorkflow.run, inp2, id=TID2, task_queue=Q)
        async with Worker(env.client, task_queue=Q,
                          workflows=[dev_lane.DevLaneWorkflow], activities=STUBS):
            blocked = await wait_for(
                handle2,
                lambda s: s["stage"] == "run_integration_tests"
                and s["stage_state"] == "blocked", 90, "票 2 验证相位 blocked")
            ok(blocked, "D1 main 不可达 → 验证相位 blocked（不静默跳过）")
            if blocked:
                snap2 = await handle2.query(dev_lane.DevLaneWorkflow.snapshot)
                why = str(snap2.get("blocked_reason") or "") + \
                    str(snap2.get("blocked_detail") or "")
                ok("主同步" in why, "D2 blocked 面点名主同步", why[:200])
                ok("不存在" in why, "D2b blocked 面含错误原文特征（响亮可诊断）", why[:200])
            ok(len(c2["gate"]) == 0, "D3 跑闸零调用（同步失败拦在跑闸之前）",
               str(len(c2["gate"])))

    print("PASS=%d FAIL=%d" % (pass_n, fail_n), file=sys.stderr)
    if fail_n == 0 and pass_n == 0:
        print("ENV_FAIL: 未产生任何断言（异常路径）", file=sys.stderr)
        return 2
    return 0 if fail_n == 0 else 1


def parents2(commit, wt):
    return len(git("rev-list", "--parents", "-n", "1", commit, cwd=wt).stdout.split()) - 1 == 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
