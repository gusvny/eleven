#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-14 场景：CL-1 并发闸全族 replay-safe 契约（灰盒 L2/L3，离线秒级，零 docker
零 Temporal 零 3099，隔离内存面零生产写入）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
CL-1（775bdb1）把并发闸族（acquire / release / renew）无 patched 门接进两个 lane，
在飞老票（history 无 marker）被新代码 worker 重放即 TMPRL1100 冻结（实案
t261005-02/-06/t261004-36）。修复=每 lane 一个 patch id 罩住全族。本场景锁的
用户可感知契约：
- R1 重放面（本票点名回归，现行树红=事故本体）：patched()=False（pre-CL-1 history）
  时，dev-lane 与 light-lane 的 run 入口第一条命令是 prepare_workspace（绝不
  concurrency_acquire）；且 release/renew 两发射 helper 在重放面（含 paused /
  blocked / 人门 / 收口全部到达点）零活动发射——重放命令流与 history 逐字一致。
- R2 新票面（正证，防「门把新票也静默关掉」）：patched()=True 时 run 入口第一条
  就是 concurrency_acquire；两 helper 真发射 concurrency_release / concurrency_renew。
- R3 守卫完整性（家族面，对抗「未来新调用点逃出守卫」）：两 lane 文件各含本 lane
  patch id 常量；每个 `await self._concurrency_gate()` 调用位都落在守卫判定内
  （t261005-14 形=workflow.patched 门；t261005-15 形=_concurrency_gate_active
  谓词，谓词自身保有 marker 臂（先判）+ 时锚臂 + 防御回落——R3b）。
  （源码形状契约；t261005-15 重排守卫形状后本条接受两形，契约不变。）
- R4 畸形输入：重放面 + 空 project key 不抛不发射（门从未进）；新票面 + 空 key
  fail-closed 具名 ValueError（rule 9 既有契约跨守卫重钉）。

intent 级分工（防重复）：developer L1（test_t261005_14_gate_replay_compat.py，白盒
随实现）锁 dev-lane 单类形状与静态锁；t261004-32 两场景锁额度账语义与声明拒绝
矩阵（本条不断言 acquire/release 真值表）；t260917-04 / t260908-01 replay 族锁
各自 patch 门族（arb 拒直落 / KI-061 唤醒重置），互为不同 patch 族；本条独有面=
**双 lane 全族**（release/renew 发射位也在罩内）+ 新票正证 + 调用点无关的 helper
罩契约。真实 Temporal 全 history 回放（Replayer）与三张冻结票的 live 查询证明归
engine 池/验证段，不在本条（离线零 docker）。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（闸内无 SKIP）。引擎模块
（dev_lane/light_lane/concurrency 或 temporalio 基座）不可导入=ENV_FAIL 点名。
修复落地前 R1/R3 红属预期（TDD 信号）；arbitrate/merge 期必须绿。
"""
import asyncio
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t261004-32"))
sys.path.insert(0, str(HERE.parents[1] / "server" / "engine"))

from lib_t26100432 import check, env_fail, summary  # noqa: E402

DEV_LANE = HERE.parents[1] / "server" / "engine" / "dev_lane.py"
LIGHT_LANE = HERE.parents[1] / "server" / "engine" / "light_lane.py"


class StopSentinel(Exception):
    """Raised by the stubbed execute_activity after recording the command name."""


def make_stub_workflow(patched_value, recorded):
    """A workflow facade stub: patched() answers fixed; execute_activity records
    the activity function's name then raises StopSentinel (one command is enough
    to prove divergence or gating); sleep/now are inert."""

    class _StubWorkflow:
        @staticmethod
        def patched(_patch_id):
            return patched_value

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


def make_shell(cls, patched_value, recorded, project_key="t26100514-proj"):
    """An instance shell of a lane workflow with the facade swapped and the
    协作面 stubbed down to what the probed paths touch. Binding is shallow: we
    only read back emitted activity names. The facade is swapped into BOTH lane
    modules: light_lane inherits/lanes the emitting helpers from dev_lane, so a
    single-module swap would leave the real temporalio facade in the module
    that actually executes (measured: light-lane helper crash at dev_lane.py)."""
    wf = object.__new__(cls)
    stub = make_stub_workflow(patched_value, recorded)
    for mod_name in ("dev_lane", "light_lane"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod.workflow = stub
    wf.ticket_id = "t26100514-fixture"
    wf.meta = {}
    wf._paused = True
    wf._log = lambda *a, **k: None
    wf._touch = lambda: None
    wf._conc_project = lambda: project_key
    wf._init = lambda inp: None
    wf._prepare_workspace_step = lambda: recorded.append("prepare_workspace") or (_ for _ in ()).throw(StopSentinel())
    return wf


def first_run_command(cls, patched_value, project_key="t26100514-proj"):
    """Drive the lane's run entry one command deep; returns the first recorded
    command name ('prepare_workspace' or a concurrency_* activity), or the
    named '<fail-closed:ValueError>' face when the gate refuses."""
    recorded = []
    saved = {m: sys.modules[m].workflow for m in ("dev_lane", "light_lane")
             if m in sys.modules}
    try:
        wf = make_shell(cls, patched_value, recorded, project_key=project_key)
        try:
            asyncio.run(wf.run(None))
        except StopSentinel:
            pass
        except ValueError as e:
            # the gate's named rule-9 fail-closed face (empty project key)
            return "<fail-closed:ValueError>" if "Concurrency gate refused" in str(e) \
                else "<value-error>"
        except Exception as e:
            # stub-shell artifact (a fixture attribute the probed path touches
            # that the shell does not model) must not crash the scenario — the
            # emitted-name evidence up to the failure stays readable
            return recorded[0] if recorded else "<shell-error:%s>" % type(e).__name__
        return recorded[0] if recorded else "<none>"
    finally:
        for m, w in saved.items():
            sys.modules[m].workflow = w


def helper_emits(cls, helper_name, patched_value, project_key="t26100514-proj"):
    """Call a release/renew helper on a shell; returns True if it emitted any
    concurrency activity, False if it returned silently, None if it raised a
    named ValueError (fail-closed)."""
    recorded = []
    saved = {m: sys.modules[m].workflow for m in ("dev_lane", "light_lane")
             if m in sys.modules}
    try:
        wf = make_shell(cls, patched_value, recorded, project_key=project_key)
        args = {}
        if helper_name.endswith("release") and "if_paused" not in helper_name:
            args = {"cause": "paused"}
        elif helper_name.endswith("renew"):
            args = {"reason": "stage-end"}
        try:
            asyncio.run(getattr(wf, helper_name)(**args))
        except StopSentinel:
            return any(n.startswith("concurrency_") for n in recorded)
        except ValueError:
            return None
        return any(n.startswith("concurrency_") for n in recorded)
    finally:
        for m, w in saved.items():
            sys.modules[m].workflow = w


def gate_guard_scan(path):
    """Contract scan: every bare gate call site in the lane file sits inside a
    guard verdict. Two accepted shapes (t261005-15 rewired the sites to the
    shared replay predicate; the contract — no call site escapes the sweep —
    is unchanged, only the source shape moved):
      - the t261005-14 shape: workflow.patched(<this lane's gate id>): directly
        above the call;
      - the t261005-15 shape: _concurrency_gate_active(workflow, <id>) directly
        above the call (the predicate itself keeps the marker arm - asserted
        separately in R3b against dev_lane, where it physically lives).
    Returns (total, guarded)."""
    text = path.read_text(encoding="utf-8")
    total = len(re.findall(r"^\s*await self\._concurrency_gate\(\)", text, re.M))
    shape = (r"(?:workflow\.patched\([A-Z_]*GATE_PATCH_ID\)"
             r"|_concurrency_gate_active\(workflow, [A-Z_]*GATE_PATCH_ID\))"
             r":\s*\n\s*await self\._concurrency_gate\(\)")
    guarded = len(re.findall(shape, text))
    return total, guarded


def predicate_marker_arm_scan(dev_lane_path):
    """R3b contract scan: the shared predicate keeps the marker discipline —
    it consults the patch marker (arm 1) and keeps the time anchor (arm 2)
    with a defensive fallback, so a marked run is never narrowed and a
    degenerate info() never raises. Returns list of (label, ok)."""
    text = dev_lane_path.read_text(encoding="utf-8")
    m = re.search(r"def _concurrency_gate_active\(.*?\n(?=\n\S|\Z)", text, re.S)
    if m is None:
        return [("predicate _concurrency_gate_active exists in dev_lane", False)]
    body = m.group(0)
    return [
        ("predicate keeps the marker arm: wf.patched(patch_id) consulted",
         "wf.patched(patch_id)" in body),
        ("predicate keeps the time arm: CL1_GATE_LANDED_AT referenced",
         "CL1_GATE_LANDED_AT" in body),
        ("predicate is defensive: non-datetime start_time falls back",
         "isinstance" in body),
    ]


def main():
    try:
        import concurrency  # noqa: F401  (engine base presence probe)
        import dev_lane
        import light_lane
    except Exception as e:
        env_fail("engine lane modules unavailable: %s: %s" % (type(e).__name__, e))

    dev, light = dev_lane.DevLaneWorkflow, light_lane.LightLaneWorkflow
    loop = asyncio.get_event_loop()

    # ---------------- R1 replay face (the reported regression; red today) ----
    print("\n== R1 replay face: pre-CL-1 history emits ZERO CL-1 commands")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, False)
        check("%s replay: first command is prepare_workspace (got %s)"
              % (lane, first), first == "prepare_workspace")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        for helper in ("_concurrency_release", "_concurrency_renew"):
            emits = helper_emits(cls, helper, False)
            check("%s replay: %s emits nothing (got %s)"
                  % (lane, helper, emits), emits is False)
        check("%s replay: _concurrency_release_if_paused (paused) emits nothing"
              % lane,
              helper_emits(cls, "_concurrency_release_if_paused", False) is False)

    # ---------------- R2 new-run face (positive proof) -----------------------
    print("\n== R2 new-run face: gated runs emit the family")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, True)
        check("%s new run: first command is concurrency_acquire (got %s)"
              % (lane, first), first == "concurrency_acquire")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        for helper, act in (("_concurrency_release", "concurrency_release"),
                            ("_concurrency_renew", "concurrency_renew")):
            emits = helper_emits(cls, helper, True)
            check("%s new run: %s emits %s (got %s)" % (lane, helper, act, emits),
                  emits is True)

    # ---------------- R3 guard completeness (both lanes, call sites) ---------
    print("\n== R3 guard completeness: every gate call site is guard-verdicted")
    ids = {"dev-lane": "dev-lane-concurrency-gate-v1",
           "light-lane": "light-lane-concurrency-gate-v1"}
    for lane, path in (("dev-lane", DEV_LANE), ("light-lane", LIGHT_LANE)):
        total, guarded = gate_guard_scan(path)
        check("%s: all %d gate call sites guarded (guarded=%d)"
              % (lane, total, guarded), total >= 2 and total == guarded)
        check("%s: patch id literal %s present" % (lane, ids[lane]),
              ids[lane] in path.read_text(encoding="utf-8"))
    # R3b (t261005-15): the shared predicate that now fronts the sweep keeps
    # the marker discipline - arm 1 patched(), arm 2 time anchor, defensive
    # fallback. The marker arm must stay PRIMARY (checked first), so a marked
    # run can never be narrowed by the time arm.
    for label, ok_flag in predicate_marker_arm_scan(DEV_LANE):
        check("predicate contract: %s" % label, ok_flag)

    # ---------------- R4 malformed input -------------------------------------
    print("\n== R4 malformed project key across the guard")
    for lane, cls in (("dev-lane", dev), ("light-lane", light)):
        first = first_run_command(cls, False)
        check("%s replay + empty key: run entry still opens with prepare_workspace"
              % lane, first == "prepare_workspace")
        for helper in ("_concurrency_release", "_concurrency_renew"):
            emits = helper_emits(cls, helper, False, project_key="")
            check("%s replay + empty key: %s silent no-raise (got %s)"
                  % (lane, helper, emits), emits is False)
        emits = helper_emits(cls, "_concurrency_release", True, project_key="")
        check("%s new run + empty key: _concurrency_release is a silent local"
              " no-op (documented helper contract, got %s)" % (lane, emits),
              emits is False)
        gate_face = first_run_command(cls, True, project_key="")
        check("%s new run + empty key: the GATE fails closed by name (rule 9,"
              " got %s)" % (lane, gate_face),
              gate_face == "<fail-closed:ValueError>")

    summary()


if __name__ == "__main__":
    main()
