#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-15 场景：CL-1 并发闸三窗口时锚判定（灰盒 L2/L3，离线秒级，零 docker
零 Temporal 零 3099，隔离内存面零生产写入）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
t261005-14 用 workflow.patched() 单臂守卫 CL-1 并发闸族，marker 只能由「带守卫的
代码」写出 ⇒ 存在第三窗口（b）：CL-1（07:20）之后、守卫（16:15）之前开出的票，
history 里**有** concurrency_acquire、却**没有** marker——重放时守卫跳过闸、命令流
错位、TMPRL1100 永久冻结（实案 t261005-09/-10）。修复=在 patched() 之外加时锚臂
（workflow 自身 start_time 对 CL-1 落地时刻的比较；start_time 属于 history，重放
恒定 ⇒ 判定确定）。本场景锁的用户可感知契约：

- R1 窗口 (b)（本票点名回归，现行树红=事故本体）：patched()=False 且 start_time
  在 CL-1 落地时刻之后 ⇒ dev-lane 与 light-lane 的 run 入口第一条命令必须是
  concurrency_acquire（与 history 里的闸事件对齐——跳过=冻结）；两发射 helper
  （release / renew）同样必须照常发射。
- R2 窗口 (a)：patched()=False 且 start_time 在落地时刻之前 ⇒ 第一条命令
  prepare_workspace、helper 零发射（老历史逐字重放不破）。
- R3 窗口 (c) 正证：patched()=True 时无论 start_time 取值（含落地时刻之前）⇒
  闸照常走（marker 臂仍是主判据，时锚不倒挂收窄新票）。
- R4 边界：start_time **恰好等于**落地时刻 ⇒ 闸走（闭区间含时刻本身）。
- R5 降级探针（外部输入三态钩，畸形/缺失不许崩工作流任务）：info() 整个缺失
  / start_time 为 None / start_time 为非 datetime（字符串）/ naive datetime ⇒
  不得抛，判定回落到 patched() 臂——这条同时保证 t261005-14 场景的旧桩
  （无 info()）在修复落地后依旧成立。

intent 级分工（防重复）：t261005-14-gate-replay-compat 独占 patched() 单臂真值
表 + 静态罩形状 + 空 project key 面（其桩面无 info()，由本条 R5 兜住不破）；
t261004-32 两场景锁额度账语义与声明拒绝矩阵；t260917-04 / t260908-01 锁各自
patch 族；本条独有面 = **start_time 时锚臂**（窗口 b 的历史形状、边界闭区间、
降级探针回落）。真实 Temporal 全 history Replayer 回放与两张冻结票修复后的
live 查询证明归 engine 池/验证段，不在本条（离线零 docker）。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（闸内无 SKIP）。引擎模块
（dev_lane/light_lane）不可导入=ENV_FAIL 点名。修复落地前 R1/R4 红属预期
（TDD 信号）；arbitrate/merge 期必须绿。
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t261004-32"))
sys.path.insert(0, str(HERE.parents[1] / "server" / "engine"))

from lib_t26100432 import check, env_fail, summary  # noqa: E402

#: 事故声明值：CL-1 落地时刻（775bdb1，2026-10-05 07:20:14 +0800）。场景优先读
#: 实现侧常量（改名不 rot）；读不到才用本声明值兜底——两值若漂移，实现侧常量
#: 对不上事故事实，本条 R4 边界会红（锚必须钉在 775bdb1 的落地瞬间）。
DECLARED_CL1_LANDED_AT = datetime(2026, 10, 4, 23, 20, 14, tzinfo=timezone.utc)


class StopSentinel(Exception):
    """Raised by the stubbed execute_activity after recording the command name."""


def make_stub_workflow(patched_value, recorded, info_obj):
    """Workflow facade stub: patched() answers fixed; info() returns the given
    object (its start_time attribute drives the time anchor arm); the first
    activity or sleep records its name and stops the probe."""

    class _StubWorkflow:
        @staticmethod
        def patched(_patch_id):
            return patched_value

        @staticmethod
        def info():
            if info_obj is _MISSING:
                raise AttributeError("info")
            return info_obj

        @staticmethod
        def execute_activity(fn, *a, **kw):
            recorded.append(getattr(fn, "name", getattr(fn, "__name__", str(fn))))
            raise StopSentinel()

        @staticmethod
        def sleep(*a, **kw):
            raise StopSentinel()

        @staticmethod
        def now():
            return 0.0

    return _StubWorkflow


class _Info:
    def __init__(self, start_time):
        self.start_time = start_time


class _InfoNoStart:
    """An info() whose object carries no start_time attribute at all."""


_MISSING = object()


def make_shell(cls, patched_value, recorded, info_obj, project_key="t26100515-proj"):
    """Instance shell of a lane workflow with the facade swapped into BOTH lane
    modules (light_lane shares the emitting helpers with dev_lane — same lesson
    as the t261005-14 harness)."""
    wf = object.__new__(cls)
    stub = make_stub_workflow(patched_value, recorded, info_obj)
    for mod_name in ("dev_lane", "light_lane"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod.workflow = stub
    wf.ticket_id = "t26100515-fixture"
    wf.meta = {}
    wf._paused = True
    wf._log = lambda *a, **k: None
    wf._touch = lambda: None
    wf._conc_project = lambda: project_key
    wf._init = lambda inp: None
    wf._prepare_workspace_step = lambda: recorded.append("prepare_workspace") or (_ for _ in ()).throw(StopSentinel())
    return wf


def first_run_command(cls, patched_value, info_obj, project_key="t26100515-proj"):
    """Drive the lane's run entry one command deep; returns the first recorded
    command name, or '<error:Type>' when the probed path raised (a degraded
    info() probe must never land here — that is the R5 contract)."""
    recorded = []
    saved = {m: sys.modules[m].workflow for m in ("dev_lane", "light_lane")
             if m in sys.modules}
    try:
        wf = make_shell(cls, patched_value, recorded, info_obj, project_key)
        try:
            asyncio.run(wf.run(None))
        except StopSentinel:
            pass
        except Exception as e:
            return "<error:%s>" % type(e).__name__
        return recorded[0] if recorded else "<none>"
    finally:
        for m, w in saved.items():
            sys.modules[m].workflow = w


def helper_emits(cls, helper_name, patched_value, info_obj, project_key="t26100515-proj"):
    """Call a release/renew helper on a shell; True=emitted a concurrency
    activity, False=silent, '<error:Type>'=raised."""
    recorded = []
    saved = {m: sys.modules[m].workflow for m in ("dev_lane", "light_lane")
             if m in sys.modules}
    try:
        wf = make_shell(cls, patched_value, recorded, info_obj, project_key)
        args = {}
        if helper_name.endswith("release") and "if_paused" not in helper_name:
            args = {"cause": "paused"}
        elif helper_name.endswith("renew"):
            args = {"reason": "stage-end"}
        try:
            asyncio.run(getattr(wf, helper_name)(**args))
        except StopSentinel:
            return any(n.startswith("concurrency_") for n in recorded)
        except Exception as e:
            return "<error:%s>" % type(e).__name__
        return any(n.startswith("concurrency_") for n in recorded)
    finally:
        for m, w in saved.items():
            sys.modules[m].workflow = w


def main():
    try:
        import dev_lane
        import light_lane
    except Exception as e:
        env_fail("engine lane modules unavailable: %s: %s" % (type(e).__name__, e))

    dev, light = dev_lane.DevLaneWorkflow, light_lane.LightLaneWorkflow
    anchor = getattr(dev_lane, "CL1_GATE_LANDED_AT", None)
    if anchor is None:
        # Implementation constant not landed yet (TDD phase): pin the declared
        # incident instant so the red faces are still about the anchor, not
        # about a missing attribute.
        anchor = DECLARED_CL1_LANDED_AT
    after = anchor + timedelta(hours=1)
    before = anchor - timedelta(hours=1)
    naive_before = datetime(2026, 10, 4, 22, 20, 14)  # naive: same wall clock, no tz

    # ------------- R1 window (b): history HAS the gate, no marker -----------
    print("\n== R1 window (b): start after CL-1, no marker -> the gate RUNS")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, False, _Info(after))
        check("%s window(b): first command is concurrency_acquire (got %s)"
              % (lane, first), first == "concurrency_acquire")
        for helper in ("_concurrency_release", "_concurrency_renew"):
            emits = helper_emits(cls, helper, False, _Info(after))
            check("%s window(b): %s emits (got %s)" % (lane, helper, emits),
                  emits is True)

    # ------------- R2 window (a): pre-CL-1 history skips --------------------
    print("\n== R2 window (a): start before CL-1, no marker -> verbatim replay")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, False, _Info(before))
        check("%s window(a): first command is prepare_workspace (got %s)"
              % (lane, first), first == "prepare_workspace")
        for helper in ("_concurrency_release", "_concurrency_renew"):
            emits = helper_emits(cls, helper, False, _Info(before))
            check("%s window(a): %s silent (got %s)" % (lane, helper, emits),
                  emits is False)

    # ------------- R3 window (c): marker arm stays primary ------------------
    print("\n== R3 window (c): marker present -> gate runs regardless of time")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, True, _Info(before))
        check("%s window(c): first command is concurrency_acquire (got %s)"
              % (lane, first), first == "concurrency_acquire")

    # ------------- R4 boundary: exactly the anchor instant ------------------
    print("\n== R4 boundary: start_time == anchor -> gate runs (inclusive)")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, False, _Info(anchor))
        check("%s boundary: first command is concurrency_acquire (got %s)"
              % (lane, first), first == "concurrency_acquire")

    # ------------- R5 degraded probes: malformed/missing info() -------------
    print("\n== R5 degraded info() probes: never raise, fall back to patched()")
    degraded = [
        ("info() missing entirely", _MISSING),
        ("start_time attribute absent", _InfoNoStart()),
        ("start_time=None", _Info(None)),
        ("start_time not a datetime", _Info("2026-10-05T07:20:14+00:00")),
        ("start_time naive datetime", _Info(naive_before)),
    ]
    for label, info_obj in degraded:
        for lane, cls in (("dev-lane", dev), ("light-lane", light)):
            first = first_run_command(cls, False, info_obj)
            check("%s %s: no raise, patched=False -> prepare_workspace (got %s)"
                  % (lane, label, first), first == "prepare_workspace")
            first = first_run_command(cls, True, info_obj)
            check("%s %s: no raise, patched=True -> concurrency_acquire (got %s)"
                  % (lane, label, first), first == "concurrency_acquire")

    summary()


if __name__ == "__main__":
    main()
