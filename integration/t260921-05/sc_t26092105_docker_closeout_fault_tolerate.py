#!/usr/bin/env python3
"""t260921-05 场景②：docker 形态收口/扫尾的故障容忍与语义冻结（灰盒 L3，hermetic 全桩）。

intent（用户可感知）：docker 模式（生产形态）下 daemon 故障时，收口照样完成不被拦、
异常面点名进 warns、绝不把失败吞成「已拆」；daemon 缺席时扫尾诚实降级留痕——模式闸
落地后此语义零漂移（本条=冻结守卫，防闸误伤 docker 形态；工单边界「不改生产语义、
不放宽容错口径」的机械面）。

依据：①工单要求行为 2)4) + 验收③的链路级投影（失败注入时引擎仍按既有口径留痕且
不外抛、收口不被拦）；③对外契约=teardown warns 只装异常面（成功=零 warn）、
remove/gc 幂等不外抛、SANDBAR_DOCKER_BIN 可注入、容器名 sandbar-agent-<ticket>。

high-level steps：docker 模式 + 可编程故障桩（rm/ps/info 快败注入）→
①teardown_lane：回执 ok=True（收口不被拦）且「agent 容器回收」点名异常面且不含
「已拆」（不吞成已拆）；
②桩日志含 rm -f sandbar-agent-<ticket>（调用形状契约+可注入性——闸不误伤 docker 形态）；
③gc：daemon 缺席容忍 note（「docker 不可用，跳过容器扫尾」）不外抛；
④桩切成功态重跑拆道链：error 干净（成功/无容器=零 warn 的 warns 契约）。

intent 分工（防 intent 级重复）：t260913-04-lifecycle-gc 锁真 docker 健康路径的回收
终态与不误杀安全阀；本条锁故障注入下的容忍语义（快败形态）。悬挂（sleep 超时）形态
归 developer L1 的 0.3s 快测子用例（场景秒级纪律 + t260920-01 等待预算化精神），不在此
真等 30 秒。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。容忍语义已存在，本条当前即应绿（守卫场景）；
模式闸落地后必须仍绿。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_t26092105_case as F  # noqa: E402

C = F.Checker("t260921-05-docker-closeout-fault-tolerate")

aa, shared = F.import_engine_activities()
import agent_runtime as ar  # noqa: E402  # remove/gc 原语真源在 agent_runtime（非 aa）

TICKET_FAULT = "t26092105zd"     # 故障注入子用例
TICKET_RECOVER = "t26092105ze"   # 恢复态对照子用例


def _teardown(root, ticket, entries, fake):
    lane, entries = F.make_mixed_lane(root, ticket, aa.MULTI_MANIFEST_REL)
    with F.env_slice({"SANDBAR_AGENT_RUNTIME": "docker",
                      "SANDBAR_DOCKER_BIN": str(fake),
                      "SANDBAR_TARGET_HOST": "127.0.0.1:1"}):
        return asyncio.run(aa.teardown_lane(
            shared.MergeArgs(ticket_id=ticket, worktree=str(lane),
                             branch="lane/%s-root" % ticket,
                             repo_worktrees=entries)))


def main():
    # ---- ①②故障注入：收口不被拦 + 异常面点名 + 不吞成已拆 + 调用形状可注入 ----
    tmp = F.tmp_root("fault")
    try:
        root = F.make_mixed_project(tmp)
        fake, log, state = F.make_prog_docker(tmp / "bin", default_exit=0)
        (state / "rm-fail").write_text("1")
        (state / "info-fail").write_text("1")
        (state / "ps-fail").write_text("1")
        res = _teardown(root, TICKET_FAULT, None, fake)
        if res.ok:
            C.ok("①故障态收口不被拦", "ok=True（容器故障不拦收口）")
        else:
            C.fail("①故障态收口不被拦", "ok=%s error=%r" % (res.ok, res.error))
        if F.WARN_MARK in (res.error or "") and F.REMOVED_MARK not in (res.error or ""):
            C.ok("①异常面点名且不吞成已拆",
                 "error 含「%s」且不含「%s」" % (F.WARN_MARK, F.REMOVED_MARK))
        else:
            C.fail("①异常面点名且不吞成已拆",
                   "error=%r（必须点名容器回收异常且不得出现「%s」）"
                   % (res.error, F.REMOVED_MARK))
        calls = F.read_calls(log)
        want = "rm -f sandbar-agent-%s" % TICKET_FAULT
        if any(want in c for c in calls):
            C.ok("②docker 形态调用形状与可注入性", "桩日志含 %r" % want)
        else:
            C.fail("②docker 形态调用形状与可注入性",
                   "桩日志=%r（docker 模式必须经 SANDBAR_DOCKER_BIN 发 rm -f 拆除指令）"
                   % calls[:5])
        # ---- ③daemon 缺席：gc 诚实降级留痕不外抛 ----
        with F.env_slice({"SANDBAR_AGENT_RUNTIME": "docker",
                          "SANDBAR_DOCKER_BIN": str(fake),
                          "SANDBAR_TARGET_HOST": "127.0.0.1:1"}):
            notes = ar.gc_stale_containers()
        if isinstance(notes, list) and any(F.GC_UNAVAILABLE_MARK in n for n in notes):
            C.ok("③gc daemon 缺席容忍", "notes=%r" % notes)
        else:
            C.fail("③gc daemon 缺席容忍",
                   "notes=%r（info 失败形态必须返回「%s…」容忍 note 且不外抛）"
                   % (notes, F.GC_UNAVAILABLE_MARK))
    finally:
        F.cleanup(tmp)

    # ---- ④恢复态对照：成功拆除=零 warn（warns 契约=只装异常面）----
    tmp2 = F.tmp_root("recover")
    try:
        root2 = F.make_mixed_project(tmp2)
        fake2, _log2, state2 = F.make_prog_docker(tmp2 / "bin", default_exit=0)
        if (state2 / "rm-fail").exists():
            (state2 / "rm-fail").unlink()
        res2 = _teardown(root2, TICKET_RECOVER, None, fake2)
        if res2.ok and F.WARN_MARK not in (res2.error or ""):
            C.ok("④恢复态收口干净", "桩成功态下 error 无「%s」（成功=零 warn）" % F.WARN_MARK)
        else:
            C.fail("④恢复态收口干净",
                   "ok=%s error=%r（成功拆除不得留容器回收 warn）" % (res2.ok, res2.error))
    finally:
        F.cleanup(tmp2)

    C.finish()


if __name__ == "__main__":
    main()
