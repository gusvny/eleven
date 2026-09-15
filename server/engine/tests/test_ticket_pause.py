"""ticket_pause 段间暂停（t260908-01）单测：数据形状/二态快照纯函数/mixin 接线。

行为级旅程归 integration/t260908-01/sc_ticket_pause_gate.py（真台+桩脑）；
畸形输入与拒收文案的实例级行为需要 workflow runtime（signal handler 内
workflow.patched 脱离 runtime 不可调）——故纯离线层只锁可证面，不做伪覆盖
（review_plan 附条件②：行为场景不断言触发不了的分支）。
"""
import dataclasses

import pytest

import shared
from base import TicketCrossProjectMixin, TicketPauseMixin, TicketWorkflowBase
from dev_lane import DevLaneWorkflow


def test_pause_request_shape():
    fields = {f.name: f for f in dataclasses.fields(shared.PauseRequest)}
    # t260915-12：pause/resume 纳入跨项目闸盖章面——caller_project/cross_project_note
    # 带默认值（重放安全，老历史解码兼容）
    assert set(fields) == {"who", "note", "caller_project", "cross_project_note"}
    assert fields["note"].default == ""
    assert fields["caller_project"].default == ""
    assert fields["cross_project_note"].default == ""
    req = shared.PauseRequest(who="op-local")
    assert req.note == "" and req.caller_project == ""


def test_pause_constants():
    assert shared.PAUSE_PATCH_ID == "ticket-pause-v1"
    assert shared.PAUSE_NOTE_INPUT_LIMIT == 20000
    # 与 host_ruling intake gate 同值同源但独立常量（不互相绑死）
    assert shared.PAUSE_NOTE_INPUT_LIMIT == shared.HOST_RULING_NOTE_INPUT_LIMIT


def test_mixin_wiring_both_templates():
    assert TicketPauseMixin in TicketWorkflowBase.__mro__
    assert TicketCrossProjectMixin in TicketWorkflowBase.__mro__
    assert TicketPauseMixin in DevLaneWorkflow.__mro__
    assert TicketCrossProjectMixin in DevLaneWorkflow.__mro__
    # dev_lane 零私有暂停/闸逻辑（拍板④机械审计面）
    own = set(DevLaneWorkflow.__dict__)
    assert not ({"pause", "resume", "_pause_gate", "_pause_snapshot",
                 "_cross_project_gate"} & own)


@pytest.mark.parametrize("paused,at_gate,want", [
    (False, False, {"paused": False, "paused_phase": ""}),
    (True, False, {"paused": True, "paused_phase": "pending"}),
    (True, True, {"paused": True, "paused_phase": "at_gate"}),
])
def test_pause_snapshot_phases(paused, at_gate, want):
    m = TicketPauseMixin()
    m._paused = paused
    m._paused_at_gate = at_gate
    assert m._pause_snapshot() == want


def test_default_template_tables_stay_narrow():
    """夹具模板 env 门不污染默认面（sc_template_face_narrowing 同口径）。"""
    assert dict(shared.TEMPLATE_CLASS_NAMES) == {"dev-lane": "DevLaneWorkflow"}
    assert set(shared.TEMPLATE_DISPLAY_NAMES) == {"dev-lane"}
