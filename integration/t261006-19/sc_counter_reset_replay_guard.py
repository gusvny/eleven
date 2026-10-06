#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-19 场景：main-sync 冲突计数复位族 replay-safe 契约（灰盒 L2/L3，离线
秒级，零 docker 零 Temporal 零 3099，隔离内存面零生产写入）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
e9daa05（t261006-07）在 dev_lane 主回路加了四处**无 patched 门**的冲突计数复位
（rework / retry_qc 信号处理器 + 两处 settle 成功复位）。修复前开出的 run 在
超限 blocked 面记录的下一个活动是 concurrency_renew；换码后重放，同一唤醒穿越会
触发 rework/retry_qc 处理器把计数清零 → 路由从 blocked 翻成 resolve → 新码调度
implement agent 活动，与 history 里的 concurrency_renew 错位 ⇒ TMPRL1100 永久
冻结（实案 t261005-10 / t261006-13，KI-212；同族 KI-201 与 t261005-14/-15）。
修复=COUNTER_RESET_PATCH_ID 门（marker 臂 + E9DAA05 落地时刻时锚臂）。本场景锁的
用户可感知契约：

- S1 重放面（本票点名回归，修复落地前红=TDD 信号）：pre-fix history 形状
  （marker=False 且 start_time 在 e9daa05 落地时刻之前）下，超限计数在 rework
  与 retry_qc 唤醒穿越后**保持超限** → 冲突路由判定维持 blocked（history 记录的
  方向）→ 后续命令仍是 concurrency_renew（与 history 续接），绝不冒出新的
  implement agent 活动——重放命令流与 history 续接，不冻结。
- S2 窗口 (b) 正证：marker=False 且 start_time 在落地时刻之后 ⇒ 复位照常生效
  （超限计数清零、路由回 resolve）——守卫不许把 t261006-07 的修复语义从新票/
  窗口内票上静默摘掉。
- S3 marker 臂主判据：marker=True 时无论 start_time 取值（含落地时刻之前）⇒
  复位生效。
- S4 降级探针（外部输入三态钩）：info() 缺失 / 无 start_time / None / 非
  datetime / naive datetime / info() 抛异常 ⇒ 不抛，判定回落 marker 臂
  （降级探针永不崩工作流任务，只丢时锚臂）。
- S5 源形状锁（家族面）：COUNTER_RESET_PATCH_ID 与 E9DAA05_LANDED_AT 常量在位
  （锚值漂移=S2 红点名）；dev_lane.py 中 rework / retry_qc 两个信号处理器内的
  计数复位各自落在 _counter_reset_active 判定罩内（未来摘掉任何一处罩=红），
  且全文件 _counter_reset_active 调用位 >= 4（两处 settle 成功复位也在罩内）。

intent 级分工（防重复）：t261005-14-gate-replay-compat 独占 CL-1 并发闸族
（acquire/release/renew）的 patched 单臂真值表与双 lane 罩形状；t261005-15 锁
CL-1 时锚臂三窗口；本条独有面 = **冲突计数复位族**（COUNTER_RESET_PATCH_ID
门：信号处理器复位 + settle 成功复位 + 本族自己的时锚）——不同 patch 族、不同
故障面（超限计数清零翻路由，不是闸命令增删）。developer L1
（test_t261006_19_counter_reset_replay.py，白盒随实现）锁单类形状与静态锁细节；
真实 Temporal 全 history Replayer 回放与两张冻结票（t261005-10 /
t261006-13）修复后的 live 查询证明归 engine 池/验证段，不在本条（离线零 docker）。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（闸内无 SKIP）。引擎模块
（dev_lane/shared）不可导入=ENV_FAIL 点名。修复落地前 S1/S5 红属预期（TDD
信号）；arbitrate/merge 期必须绿。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t261004-32"))
sys.path.insert(0, str(HERE.parents[1] / "server" / "engine"))

from lib_t26100432 import check, env_fail, summary  # noqa: E402

#: 事故声明值：e9daa05（t261006-07 squash）落地时刻（2026-10-06 15:25:58 +0800
#: = 07:25:58 UTC）。场景优先读实现侧常量（改名不 rot）；实现常量未落地（TDD
#: 阶段）才用本声明值兜底——实现常量若与事故事实漂移，S2 的窗口正证会红点名。
DECLARED_E9DAA05_LANDED_AT = datetime(2026, 10, 6, 7, 25, 58, tzinfo=timezone.utc)

DEV_LANE_SRC = HERE.parents[1] / "server" / "engine" / "dev_lane.py"


class StopSentinel(Exception):
    """Raised by the stubbed execute_activity after recording the command name."""


class _Info:
    def __init__(self, start_time):
        self.start_time = start_time


class _InfoNoStart:
    """An info() object carrying no start_time attribute at all."""


class _InfoRaising:
    """An info() that raises (the degenerate-probe contract: never fatal)."""

    def __call__(self):
        raise RuntimeError("degraded probe")


_MISSING = object()


def make_stub_workflow(patched_value, recorded, info_obj):
    class _StubWorkflow:
        @staticmethod
        def patched(_patch_id):
            return patched_value

        @staticmethod
        def info():
            if info_obj is _MISSING:
                raise AttributeError("info")
            if info_obj is _RAISING:
                raise RuntimeError("degraded probe")
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


_RAISING = object()


def make_shell(cls, patched_value, info_obj):
    """A DevLaneWorkflow instance shell with the facade stubbed into dev_lane,
    carrying the pre-fix surviving state: an over-cap conflict counter and a
    prior-batch signature (exactly what a pre-e9daa05 history holds when a wake
    crossing re-executes the main-sync conflict route)."""
    import dev_lane

    recorded = []
    wf = object.__new__(cls)
    saved = sys.modules["dev_lane"].workflow
    try:
        sys.modules["dev_lane"].workflow = make_stub_workflow(
            patched_value, recorded, info_obj)
        wf.ticket_id = "t26100619-fixture"
        wf.meta = {}
        wf.timeline = []
        wf.refused = []
        wf._sigs = {}
        wf._rework = None
        wf._retry_token = 0
        wf._log = lambda *a, **k: None
        wf._touch = lambda: None
        wf._cross_project_gate = lambda *a, **k: True
        wf._now_iso = lambda: "2026-10-06T00:00:00Z"
        # pre-fix surviving state: over the cap, with a prior batch signature
        wf._conflict_rounds = dev_lane.MAX_CONFLICT_ROUNDS + 1
        wf._prev_conflict_files = ["repo:src/a.py"]
        yield wf, recorded
    finally:
        sys.modules["dev_lane"].workflow = saved


def route_verdict(wf):
    """The public route face the main loop consumes (shared.py pure function via
    the lane's import) — 'resolve' schedules the implement agent activity,
    'blocked:...' leads to the blocked face and its concurrency_renew."""
    import dev_lane
    return dev_lane.main_sync_conflict_route(
        wf._conflict_rounds, ["repo:src/a.py"], wf._prev_conflict_files,
        dev_lane.MAX_CONFLICT_ROUNDS)


def wake_and_route(signal_name, patched_value, info_obj):
    """Fire the human signal handler on a pre-fix shell, then read the route
    verdict and every command the replay scheduled. Returns (verdict, commands,
    error-or-None) — a degraded probe surfaces as error, never a crash."""
    import dev_lane

    gen = make_shell(dev_lane.DevLaneWorkflow, patched_value, info_obj)
    wf, recorded = next(gen)
    try:
        try:
            if signal_name == "rework":
                wf.rework(dev_lane.ReworkRequest(
                    who="host", target_stage="implement", note="ki212 wake"))
            else:
                wf.retry_qc(who="host")
            verdict = route_verdict(wf)
            return verdict, list(recorded), None
        except Exception as e:
            return None, list(recorded), "%s: %s" % (type(e).__name__, e)
    finally:
        gen.close()


def main():
    try:
        import dev_lane
        import shared  # noqa: F401  (route true source import face)
    except Exception as e:
        env_fail("engine modules unavailable: %s: %s" % (type(e).__name__, e))

    anchor = getattr(dev_lane, "E9DAA05_LANDED_AT", None)
    if anchor is None:
        anchor = DECLARED_E9DAA05_LANDED_AT
    before = anchor - timedelta(hours=1)
    after = anchor + timedelta(hours=1)
    naive_before = datetime(2026, 10, 5, 22, 25, 58)  # same wall clock, no tz

    for signal_name in ("rework", "retry_qc"):
        # ---- S1 pre-fix replay face: the counter survives, route stays blocked
        print("\n== S1 pre-fix history (%s): reset skipped, route stays blocked"
              % signal_name)
        verdict, cmds, err = wake_and_route(signal_name, False, _Info(before))
        check("%s pre-fix: wake crossing raises nothing (got %s)"
              % (signal_name, err), err is None)
        check("%s pre-fix: route stays blocked after the wake (got %r)"
              % (signal_name, verdict),
              isinstance(verdict, str) and verdict.startswith("blocked:"))
        check("%s pre-fix: no agent activity scheduled where history holds "
              "concurrency_renew (got %s)" % (signal_name, cmds),
              cmds == [])

        # ---- S2 window (b): post-anchor no-marker run keeps the fix semantics
        print("\n== S2 window (b) (%s): start after e9daa05, no marker -> the "
              "reset FIRES" % signal_name)
        verdict, cmds, err = wake_and_route(signal_name, False, _Info(after))
        check("%s window(b): wake crossing raises nothing (got %s)"
              % (signal_name, err), err is None)
        check("%s window(b): counter reset -> route resolves (got %r)"
              % (signal_name, verdict), verdict == "resolve")

        # ---- S3 marker arm stays primary -----------------------------------
        print("\n== S3 marker (%s): patched=True -> reset fires regardless of "
              "time" % signal_name)
        verdict, _, err = wake_and_route(signal_name, True, _Info(before))
        check("%s marker: no raise (got %s)" % (signal_name, err), err is None)
        check("%s marker: counter reset -> route resolves (got %r)"
              % (signal_name, verdict), verdict == "resolve")

    # ---- S4 degraded probes: malformed/missing info() never raises ----------
    print("\n== S4 degraded info() probes: fall back to the marker verdict")
    degraded = [
        ("info() missing entirely", _MISSING),
        ("start_time attribute absent", _InfoNoStart()),
        ("start_time=None", _Info(None)),
        ("start_time not a datetime", _Info("2026-10-06T15:25:58+08:00")),
        ("start_time naive datetime", _Info(naive_before)),
        ("info() raises", _RAISING),
    ]
    for label, info_obj in degraded:
        verdict, _, err = wake_and_route("rework", False, info_obj)
        check("rework %s: no raise (got %s)" % (label, err), err is None)
        check("rework %s: fallback = marker False -> route stays blocked (got %r)"
              % (label, verdict),
              isinstance(verdict, str) and verdict.startswith("blocked:"))
        verdict, _, err = wake_and_route("retry_qc", True, info_obj)
        check("retry_qc %s: no raise (got %s)" % (label, err), err is None)
        check("retry_qc %s: fallback = marker True -> route resolves (got %r)"
              % (label, verdict), verdict == "resolve")

    # ---- S5 source-shape lock (family face) --------------------------------
    print("\n== S5 source lock: the four reset sites sit inside the guard")
    src = DEV_LANE_SRC.read_text(encoding="utf-8")
    lines = src.splitlines()
    check("COUNTER_RESET_PATCH_ID constant present",
          "COUNTER_RESET_PATCH_ID" in src)
    check("E9DAA05_LANDED_AT constant present", "E9DAA05_LANDED_AT" in src)
    check("_counter_reset_active call sites >= 4 (two signal handlers + two "
          "settle-success resets)",
          src.count("_counter_reset_active(") >= 4)

    def handler_gated(handler_name):
        """The counter reset inside the named @workflow.signal handler sits
        within 8 lines of a _counter_reset_active verdict."""
        for i, line in enumerate(lines):
            if ("def %s(" % handler_name) in line:
                window = lines[i:i + 40]
                for j, w in enumerate(window):
                    if w.strip().startswith("self._conflict_rounds = 0"):
                        look = window[max(0, j - 8):j + 1]
                        return any("_counter_reset_active" in x for x in look)
                return False
        return False

    check("rework signal handler's reset is gated", handler_gated("rework"))
    check("retry_qc signal handler's reset is gated", handler_gated("retry_qc"))

    summary()


if __name__ == "__main__":
    main()
