#!/usr/bin/env python3
"""t260921-05 场景①：host 形态收口/扫尾链零 docker 依赖（灰盒 L3，hermetic）。

intent（用户可感知，宿主令 260921）：机器无 docker / daemon 假死时跑工单，票首的
容器扫尾（prepare_workspace 首活动 gc）与票尾的收口拆容器（teardown_lane）既不敲
docker CLI（零调用、不卡 30 秒超时），也不留「agent 容器回收」脏 warn——工单收口
干净、全程秒级。实案回归面：t260913_05 五条红当日（docker rm timeout 30s 假死形态）。

依据：①工单要求行为 1)「host 下容器拆/扫不得调用 docker（无容器=直接返回空）」+
验收①②的链路级投影；②KI 清单无本面既有登记（gen0 核过）——本票实案即新故障模式，
本条=事故回归面；③对外契约=SANDBAR_AGENT_RUNTIME 旋钮 host 缺省、SANDBAR_DOCKER_BIN
注入缝、teardown warns 只装异常面（收口干净=用户可感知）。

high-level steps：hermetic env（host 缺省不设旋钮 + SANDBAR_DOCKER_BIN=只记录快败桩，
误调用立即显红）+ tmp 真 git 混合泳道（根仓+repo_a 成员仓+清单镜像）→
①直调 teardown_lane 全链：回执 ok 且 error 干净（零容器回收 warn）；
②直调 prepare_workspace（首活动 gc 扫尾链）：回执 ok；
③桩日志 0 行（零 docker 调用——宿主令核心断言）；
④全程墙钟有界（回归成 30 秒等待即红）；
⑤PATH 屏蔽 docker 变体（无桩在场）重跑拆道链：同样干净——证明零调用不依赖桩。

intent 分工（防 intent 级重复）：t260913-04-wiring-contract 的 host 零调用断言锁
agent spawn 执行面；本条锁拆/扫收口链。merge 内联清理收口（agent_activities 的
merge 路径）与 teardown 同走 remove_container 原语（intent 同源），不另造链。
悬挂超时形态（daemon 假死真等 30 秒）归 developer L1 的 0.3s 快测子用例；本条以
「零调用」断言覆盖「不等待」。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。模式闸（t260921-05 implement 段）已落地，本条
当前即应全绿；红=宿主令回归（闸被绕过/拆掉），非预期红。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26092105_case as F  # noqa: E402

C = F.Checker("t260921-05-host-closeout-zero-docker")

aa, shared = F.import_engine_activities()

TICKET_TD = "t26092105za"        # 拆道链（桩变体）
TICKET_PW = "t26092105zb"        # 首活动扫尾链
TICKET_NOPATH = "t26092105zc"    # PATH 屏蔽变体
WALL_BUDGET_S = F.bounded(10)    # 拆道+扫尾全程预算（回归成 30s 级等待即超界）


def leg_teardown_under_recording_net():
    """①拆道全链（host 缺省 + 只记录快败桩）：回执干净、零调用。"""
    tmp = F.tmp_root("teardown")
    try:
        root = F.make_mixed_project(tmp)
        lane, entries = F.make_mixed_lane(root, TICKET_TD, aa.MULTI_MANIFEST_REL)
        fake, log, _state = F.make_prog_docker(
            tmp / "bin", default_exit=72, blocked_prefix="sandbar-ut-net")
        # 直调活动：@activity.defn 保留原函数可 await，asyncio.run 直调即 L1 同款跑法
        # （零 Temporal server）。
        import asyncio
        with F.env_slice({"SANDBAR_DOCKER_BIN": str(fake),
                          "SANDBAR_TARGET_HOST": "127.0.0.1:1"},
                         del_keys=("SANDBAR_AGENT_RUNTIME",)):
            res = asyncio.run(aa.teardown_lane(
                shared.MergeArgs(ticket_id=TICKET_TD, worktree=str(lane),
                                 branch="lane/%s-root" % TICKET_TD,
                                 repo_worktrees=entries)))
        if res.ok and res.error == "":
            C.ok("①host 拆道回执干净", "ok=True 且 error 空（零「%s」warn）" % F.WARN_MARK)
        else:
            C.fail("①host 拆道回执干净",
                   "ok=%s error=%r（host 形态收口不得留容器回收 warn）"
                   % (res.ok, res.error))
        calls = F.read_calls(log)
        if calls:
            C.fail("③零 docker 调用（拆道链）",
                   "记录桩被调用 %d 次，首条=%r——host 形态拆/扫必须零调用" % (len(calls), calls[0]))
        else:
            C.ok("③零 docker 调用（拆道链）", "记录桩日志 0 行")
    finally:
        F.cleanup(tmp)


def leg_prepare_workspace_gc():
    """②首活动扫尾链（prepare_workspace 的 gc 段）：回执 ok 不被扫尾面污染。"""
    tmp = F.tmp_root("prepare")
    try:
        root = F.make_mixed_project(tmp)
        fake, log, _state = F.make_prog_docker(
            tmp / "bin", default_exit=72, blocked_prefix="sandbar-ut-net")
        import asyncio
        with F.env_slice({"SANDBAR_DOCKER_BIN": str(fake),
                          "SANDBAR_TARGET_HOST": "127.0.0.1:1"},
                         del_keys=("SANDBAR_AGENT_RUNTIME",)):
            prep = shared.WorkspacePrep(
                ticket_id=TICKET_PW,
                workspace={"type": "worktree", "path": str(root / ".lane" / TICKET_PW)},
                branch="lane/%s-root" % TICKET_PW)
            res = asyncio.run(aa.prepare_workspace(prep))
        if res.ok:
            C.ok("②首活动扫尾回执 ok", "prepare_workspace 正常（gc 扫尾不污染建道）")
        else:
            C.fail("②首活动扫尾回执 ok", "ok=%s error=%r" % (res.ok, getattr(res, "error", "")))
        calls = F.read_calls(log)
        if calls:
            C.fail("③零 docker 调用（扫尾链）",
                   "记录桩被调用 %d 次，首条=%r——host 形态 gc 必须零调用" % (len(calls), calls[0]))
        else:
            C.ok("③零 docker 调用（扫尾链）", "记录桩日志 0 行")
    finally:
        F.cleanup(tmp)


def leg_path_shielded():
    """⑤PATH 屏蔽 docker 变体（无桩在场）：拆道链同样干净——零调用不依赖桩。"""
    shielded_path = "/usr/bin:/bin"
    probe = __import__("subprocess").run(
        ["git", "--version"], env={"PATH": shielded_path, "HOME": str(F.tmp_root("ph"))},
        capture_output=True, text=True)
    if probe.returncode != 0:
        C.na("⑤PATH 屏蔽变体", "该环境 /usr/bin:/bin 下无可用 git（系统状态条件，无验证对象）")
        return
    tmp = F.tmp_root("nopath")
    try:
        root = F.make_mixed_project(tmp)
        lane, entries = F.make_mixed_lane(root, TICKET_NOPATH, aa.MULTI_MANIFEST_REL)
        import asyncio
        with F.env_slice({"PATH": shielded_path},
                         del_keys=("SANDBAR_AGENT_RUNTIME", "SANDBAR_DOCKER_BIN")):
            res = asyncio.run(aa.teardown_lane(
                shared.MergeArgs(ticket_id=TICKET_NOPATH, worktree=str(lane),
                                 branch="lane/%s-root" % TICKET_NOPATH,
                                 repo_worktrees=entries)))
        if res.ok and res.error == "":
            C.ok("⑤PATH 屏蔽变体拆道干净", "无桩无 docker 下 ok=True 且 error 空")
        else:
            C.fail("⑤PATH 屏蔽变体拆道干净",
                   "ok=%s error=%r（PATH 屏蔽 docker 时收口必须零依赖且干净）"
                   % (res.ok, res.error))
    finally:
        F.cleanup(tmp)


def main():
    import time
    t0 = time.monotonic()
    leg_teardown_under_recording_net()
    leg_prepare_workspace_gc()
    elapsed = time.monotonic() - t0
    if elapsed < WALL_BUDGET_S:
        C.ok("④墙钟有界", "拆道+扫尾全程 %.2fs < %ds（无 30 秒级等待）" % (elapsed, WALL_BUDGET_S))
    else:
        C.fail("④墙钟有界", "全程 %.2fs ≥ %ds——出现 30 秒级等待形态（宿主令直接违反）"
               % (elapsed, WALL_BUDGET_S))
    leg_path_shielded()
    C.finish()


if __name__ == "__main__":
    main()
