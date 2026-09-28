#!/usr/bin/env python3
"""probe_inspection_wiring.py — child probe of sc_ledger_second_family_wiring
(t260928-20, inspection family ledger wiring).

Runs INSIDE the engine venv (temporalio importable). Drives the REAL
server/engine classes (InspectionPeriodicWorkflow mixin face + the real
event_ledger append path) against real files in a tmp dir
(SANDBAR_EVENT_LEDGER_DIR). Prints per-assertion ✓/✗ and ends with
BEHAVIOR_PASS=<n> / BEHAVIOR_FAIL=<n>. Exit 0 always (the parent counts
ENV_FAIL via its own temporalio probe); exit 2 only when temporalio itself
is missing.

Stub discipline (grey-box, binds to the PUBLIC workflow context seam only —
patched / info / now / logger / execute_activity — never to private
inspection internals beyond the documented _enter write point):
- workflow.patched -> True (new-instance path; the patched-False zero-change
  face is a source lock + L1 unit face in the plan S5, not re-probed here);
- workflow.execute_activity -> forwards the payload to the REAL
  event_ledger.append_event with a tmp ledger dir and the enabled gate
  pre-satisfied (the gate itself is ticket-13's already-locked intent).
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

try:
    import temporalio
    from temporalio import workflow as _wfmod
except Exception as exc:  # pragma: no cover
    print("ENV_FAIL: temporalio 不可导入：%r" % (exc,))
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server/engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclass 解析需要模块先在 sys.modules
    spec.loader.exec_module(mod)
    return mod


TMP = Path(tempfile.mkdtemp(prefix="t260928-20-probe-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)   # L8：全终态回收
LEDGER = TMP / "ledger"
LEDGER.mkdir(parents=True, exist_ok=True)

# ---- stub the temporal workflow context seam (must precede base.py import) --
def _patched(_pid):
    return True


class _Info:
    run_id = "run-A111"
    workflow_id = "inspection-periodic-TEST"
    task_queue = "tq"


class _Logger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


import event_ledger as el  # noqa: E402

ACTIVITY_CALLS = []


async def _execute_activity(fn, arg, **kwargs):
    # 真活动体直调：把 flush 的载荷经真 append_event 落到 tmp 账本目录
    # （enabled 闸由 skip 显式满足——闸行为归 t260928-13 意图，不在此重锁）。
    ACTIVITY_CALLS.append(arg)
    return el.append_event(arg, ledger_dir=LEDGER, skip_enabled_gate=True)


_wfmod.patched = _patched
_wfmod.info = lambda: _Info()
_wfmod.now = lambda: datetime(2026, 9, 28, 12, 0, 0)
_wfmod.logger = _Logger()
_wfmod.execute_activity = _execute_activity

base = load_module("base_under_test", ROOT / "server/engine/base.py")
insp = load_module("insp_under_test", ROOT / "server/engine/inspection_flow.py")


def lines_of(project):
    p = LEDGER / ("%s.jsonl" % project)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def make_wf(cls, project_key, run_id):
    import dataclasses
    wf = object.__new__(cls)
    wf.timeline = []
    wf.stage = ""
    wf.stage_state = ""
    try:
        inp = cls.INPUT_CLS()
    except TypeError:
        # 输入 dataclass 带必填字段：按注释类型给哑值（本探针只走 _enter 写点，
        # 不触 run 主链——必填字段本身不是被锁面）。
        kw = {}
        for f in dataclasses.fields(cls.INPUT_CLS):
            if f.default is dataclasses.MISSING and \
                    f.default_factory is dataclasses.MISSING:
                kw[f.name] = 0 if f.type in ("int",) else (
                    [] if "List" in str(f.type) else "probe-%s" % f.name)
        inp = cls.INPUT_CLS(**kw)
    wf._input = inp
    if inp is not None:
        inp.project_key = project_key
    wf._ledger_run_id = run_id
    wf._patched = True    # 新实例路径（snapshot 门内 additive 键需门判 True）
    # snapshot 消费面所需的实例属性（本探针只走 _enter/snapshot，不给 run 主链）
    for attr, val in (("status", "running"), ("decision", ""), ("face", ""),
                      ("_gate_err", ""), ("_close_sig", None)):
        if not hasattr(wf, attr):
            setattr(wf, attr, val)
    return wf


def has_mixin(cls):
    # 双导入身份护栏：inspection_flow 以真名 import base，本探针以别名装载——
    # issubclass 会因模块对象不同而误红；按类名判 MRO（mixin 名即公开契约面）。
    return any(c.__name__ == "TicketEventLedgerMixin" for c in cls.__mro__)


import asyncio  # noqa: E402

run = asyncio.run


print("\n== B1 接线面：一迁移一行（真模块 × 真文件）")
try:
    P = insp.InspectionPeriodicWorkflow
    P.INPUT_CLS = insp.InspectionPeriodicInput
    ok(has_mixin(P), "InspectionPeriodicWorkflow 已接入 TicketEventLedgerMixin")
    wf = make_wf(P, "proj-insp", "run-A111")
    wf._enter("setup", "running", "hello ledger")
    ok(len(wf.timeline) == 1, "_enter 后 timeline 恰一条（票面形状不变面）")
    ok(len(wf._ledger_pending or []) == 1, "_enter 后账面 pending 恰一条（一迁移一行）")
    run(wf._ledger_flush())
    rows = lines_of("proj-insp")
    ok(len(rows) == 1, "账本文件恰一行（真文件面）")
    if rows:
        r = rows[0]
        ok(r.get("project") == "proj-insp", "project=_input.project_key（族身份解析）")
        ok(r.get("scope") == "project", "scope=project（票族行）")
        ok(r.get("gen") == 0, "gen=0（族无代次维：documented constant，非捏造）")
        ok(r.get("stage") == "setup" and r.get("state") == "running",
           "stage/state 与票面迁移一致（诚实面）")
        ok(len((LEDGER / "proj-insp.jsonl").read_bytes().splitlines()[0]) < 4096,
           "行 <4KB")
    else:
        ok(False, "账本行缺席（TDD 红属预期）")
except Exception as e:  # noqa: BLE001
    ok(False, "接线面探针异常（TDD 红属预期）：%s: %s" % (type(e).__name__, e))

print("\n== B2 重入去重 × 新 run 不吞（run_id 维度）")
try:
    wf2 = make_wf(P, "proj-insp", "run-A111")   # 同 run 重放同迁移
    wf2._enter("setup", "running", "hello ledger")
    run(wf2._ledger_flush())
    ok(len(lines_of("proj-insp")) == 1, "同 run 同迁移重入不产生重复行（idem 去重）")
    wf3 = make_wf(P, "proj-insp", "run-B222")   # 合法新 run（复跑/重生）
    wf3._enter("setup", "running", "hello ledger")
    run(wf3._ledger_flush())
    rows = lines_of("proj-insp")
    ok(len(rows) == 2, "新 run 的同票同 seq 出新行（run_id 维不误吞）")
    ok(len({r.get("run_id") for r in rows}) == 2, "两行 run_id 可辨")
except Exception as e:  # noqa: BLE001
    ok(False, "重入/新 run 探针异常：%s: %s" % (type(e).__name__, e))

print("\n== B3 rebuild 派生投影面（snapshot 带 ledger_marks，C1）")
try:
    snap = wf3.snapshot() if hasattr(wf3, "snapshot") else {}
    ok(isinstance(snap, dict) and "ledger_marks" in snap,
       "inspection snapshot 暴露 ledger_marks（rebuild 权威轨，review C1）")
    marks = snap.get("ledger_marks") or []
    exp = el.expected_lines(wf3.timeline, "proj-insp",
                            ticket=_Info.workflow_id, marks=marks)
    have = {r["idem"] for r in lines_of("proj-insp")}
    ok(bool(exp) and all(e["idem"] in have for e in exp),
       "timeline+marks 可重导出账面行（派生投影闭环，取消面权威可兑现）")
except Exception as e:  # noqa: BLE001
    ok(False, "rebuild 面探针异常（TDD 红属预期）：%s: %s" % (type(e).__name__, e))

print("\n== B4 project 族空身份不冒充 engine 行（review C2）")
try:
    before = len(lines_of("proj-insp"))
    wf4 = make_wf(P, "", "run-C333")            # 身份解析失败面（旧载荷/旁路起票）
    wf4._enter("setup", "running", "no identity")
    run(wf4._ledger_flush())
    rows = lines_of("proj-insp")
    ok(len(rows) == before, "空身份 project 行被跳过（不落账）")
    allengine = [r for r in rows if r.get("scope") == "engine"]
    ok(not allengine, "project 族绝不产出 scope=engine 行（不冒充执行器行）")
    ok(not (LEDGER / ".jsonl").exists(), "账本目录无畸形 `.jsonl` 文件")
except Exception as e:  # noqa: BLE001
    ok(False, "空身份探针异常：%s: %s" % (type(e).__name__, e))

print("\n== B5 Produce 链同款接线（第二类）")
try:
    Q = insp.InspectionProduceWorkflow
    Q.INPUT_CLS = insp.InspectionProduceInput
    ok(has_mixin(Q), "InspectionProduceWorkflow 已接入 mixin")
    qf = make_wf(Q, "proj-insp", "run-D444")
    qf._enter("setup", "running", "produce entry")
    run(qf._ledger_flush())
    rows = lines_of("proj-insp")
    ok(any(r.get("ticket") and r.get("stage") == "setup" and
           r.get("run_id") == "run-D444" for r in rows),
       "produce 迁移同样落账（第二链用户可感知面）")
except Exception as e:  # noqa: BLE001
    ok(False, "produce 探针异常（TDD 红属预期）：%s: %s" % (type(e).__name__, e))

print("BEHAVIOR_PASS=%d" % PASS)
print("BEHAVIOR_FAIL=%d" % FAIL)
sys.exit(0)
