#!/usr/bin/env python3
"""selfcheck_pause — 工单段间暂停（t260908-01）的离线契约子用例。

分层定位：行为级旅程（真 Temporal 台+桩脑链：暂停→不派段→恢复→走完、refused
反馈、pause×rework、通用性夹具模板）归 integration/t260908-01/sc_ticket_pause_gate.py；
本自检守**离线可证的契约面**（零 Temporal、零 docker、纯 stdlib+引擎 venv）：

  1. 常量/数据：PAUSE_PATCH_ID / PAUSE_NOTE_INPUT_LIMIT=20000（host_ruling 同源值）
     / PauseRequest(who, note="")；
  2. mixin 接线：TicketWorkflowBase 与 DevLaneWorkflow 的 MRO 均含 TicketPauseMixin；
     DevLaneWorkflow.__dict__ 无自有 pause/resume/_pause_gate（零私有逻辑=逻辑全在
     通用层，拍板④的机械审计面）；
  3. paused 二态快照纯函数子用例：_pause_snapshot 三态（未暂停/pending/at_gate）；
  4. 反馈文案源码锁（KI-051 语义词锚）：refused 五笔文案在场——R4 老实例拒收
     （「启动于暂停功能上线前」）、who 非空、note 超限、已暂停幂等、未暂停空态；
  5. 人门通道锁：pause/resume 只出现在 client.py 信号通道与 base 通用层——grep 引擎
     面断言 agent_activities.py 零 pause/resume 信号发送面（agent 无发送入口，拍板②）；
  6. 夹具模板 env 门：默认面 TEMPLATE_CLASS_NAMES 恰 {dev-lane}（收窄守卫不破）；
     SANDBAR_FIXTURE_TEMPLATES=1 子进程导入=含 fixture-two-step（同门感知）。

退出码 0=全绿；非 0=有红（细节在 stdout）。
用法（引擎目录）：.venv/bin/python selfcheck_pause.py（temporalio 缺失时退化为
仅 1/4/5/6 子用例——2/3 子用例需要 import 引擎模块，标注降级原因，不静默假绿）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)


def main():
    print("== 1 常量与数据面")
    import shared
    check(shared.PAUSE_PATCH_ID == "ticket-pause-v1",
          "PAUSE_PATCH_ID=ticket-pause-v1（回放安全 marker，独立于 KI-003 breathe）")
    check(shared.PAUSE_NOTE_INPUT_LIMIT == 20000,
          "PAUSE_NOTE_INPUT_LIMIT=20000（host_ruling intake gate 同源值，独立常量）")
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(shared.PauseRequest)}
    check(set(fields) == {"who", "note"} and fields["note"].default == "",
          "PauseRequest(who, note='') 形状（与 Signature/ReworkRequest 同族）")

    print("== 2/3 mixin 接线与二态快照（需引擎 venv import 面）")
    try:
        import base as engine_base
        import dev_lane
        import_ok = True
    except Exception as e:
        import_ok = False
        print("  降级：引擎模块不可导入（%s: %s）——2/3 子用例跳过（非假绿，venv 在场时必须过）"
              % (type(e).__name__, e))
    if import_ok:
        mixin = engine_base.TicketPauseMixin
        check(mixin in engine_base.TicketWorkflowBase.__mro__,
              "TicketWorkflowBase 继承 TicketPauseMixin")
        check(mixin in dev_lane.DevLaneWorkflow.__mro__,
              "DevLaneWorkflow 继承 TicketPauseMixin（mixin 继承=信号/门/快照随之继承）")
        own = set(dev_lane.DevLaneWorkflow.__dict__)
        check(not ({"pause", "resume", "_pause_gate", "_pause_snapshot"} & own),
              "dev_lane 零私有暂停逻辑（__dict__ 无 pause/resume/_pause_gate/_pause_snapshot）")
        m = engine_base.TicketPauseMixin()
        check(m._pause_snapshot() == {"paused": False, "paused_phase": ""},
              "_pause_snapshot 未暂停={paused:False, paused_phase:''}")
        m._paused = True
        check(m._pause_snapshot() == {"paused": True, "paused_phase": "pending"},
              "_pause_snapshot 已受理未达门口=pending")
        m._paused_at_gate = True
        check(m._pause_snapshot() == {"paused": True, "paused_phase": "at_gate"},
              "_pause_snapshot 已停段间门口=at_gate")

    print("== 4 反馈文案源码锁（语义词锚，KI-051）")
    src = (POC / "base.py").read_text("utf-8")
    for frag, label in [
        ("启动于暂停功能上线前", "R4 老实例拒收文案（patched 前置分支）"),
        ("必填非空", "who 空白拒收文案"),
        ("超限", "note 超限拒收文案"),
        ("已处于暂停", "重复 pause 幂等拒收文案"),
        ("未处于暂停", "空态 resume 拒收文案"),
        ("PAUSE_NOTE_INPUT_LIMIT", "intake gate 消费 PAUSE_NOTE_INPUT_LIMIT"),
    ]:
        check(frag in src, "base.py 含 %s" % label)
    dl = (POC / "dev_lane.py").read_text("utf-8")
    check("class DevLaneWorkflow(TicketPauseMixin)" in dl,
          "dev_lane 类声明接线（mixin 基类）")
    check(dl.count("await self._pause_gate()") == 1,
          "dev_lane 主循环恰一个段间门调用点（接线 ≤5 行验收口径）")
    check("**self._pause_snapshot()" in dl, "dev_lane snapshot 并入 paused 二态键")

    print("== 5 人门通道锁（agent 面零发送入口）")
    cli_src = (POC / "client.py").read_text("utf-8")
    check('op in ("pause", "resume")' in cli_src and 'handle.signal(op, req)' in cli_src,
          "client.py ticket op=pause/resume 信号通道在场")
    aa = (POC / "agent_activities.py").read_text("utf-8")
    check('signal("pause"' not in aa and 'signal("resume"' not in aa
          and "signal('pause'" not in aa and "signal('resume'" not in aa,
          "agent_activities 零 pause/resume 信号发送面（仅人门，拍板②）")

    print("== 6 夹具模板 env 门（收窄守卫同门感知）")
    check(dict(shared.TEMPLATE_CLASS_NAMES) == {"dev-lane": "DevLaneWorkflow"},
          "默认面 TEMPLATE_CLASS_NAMES 恰 {dev-lane}（sc_template_face_narrowing 不破）")
    check(set(shared.TEMPLATE_DISPLAY_NAMES) == {"dev-lane"},
          "默认面 TEMPLATE_DISPLAY_NAMES 恰 {dev-lane}")
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import shared, workflows_v2;"
         "print(sorted(shared.TEMPLATE_CLASS_NAMES), sorted(workflows_v2.TEMPLATE_CLASSES))"
         % str(POC)],
        env={**os.environ, "SANDBAR_FIXTURE_TEMPLATES": "1"},
        capture_output=True, text=True, timeout=60)
    check(probe.returncode == 0 and "fixture-two-step" in probe.stdout,
          "SANDBAR_FIXTURE_TEMPLATES=1 子进程：两表同门含 fixture-two-step（实得 %s%s）"
          % (probe.stdout.strip()[:120], probe.stderr.strip()[-160:]))

    print("SELFCHECK pause: passed=%d failed=%d" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
