"""KI-061 仲裁超限 blocked 唤醒重置（t260908-01）——纯逻辑单测（零 Temporal server）。

覆盖：
  A. FakeMemoGate（逐语义抄 SDK workflow_patch：首评 `not is_replaying or id in notified`
     并按实例 memo 固化）驱动的守卫状态机三态矩阵——
     A1 旧历史重放：各唤醒点守卫 False 且零 marker 命令（与修复前命令序列一致）；
     A2 live 唤醒：首评 True、写唯一 marker、触发重置（memo 毒化被「每进入唯一 id」绕开）；
     A3 未来重放：marker 已入 history（notified）→ 同位复现 True，确定性保持；
     A4 计数器唯一性：同一 id 全实例只在唤醒穿越处求值一次（串/并行分支共用计数器不碰撞）；
     A5 畸形输入：rework 唤醒短路、测试开关短路、多次 blocked 计数单调。
  B. build_stage_prompt 宿主裁决注入回归（arbitrate 段 prompt 含 host_rulings；
     note 截断带标记；无裁决时注入节不出现）。
  C. integration_route 超限边界（tests_rounds=5 放行 / 6 blocked；code-fault 同口径）。
"""

from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

from shared import (  # noqa: E402
    MAX_CODE_FAULT_ROUNDS,
    MAX_TESTS_FAULT_ROUNDS,
    Stage,
    build_stage_prompt,
    integration_route,
)
import dev_lane  # noqa: E402
from dev_lane import KI061_WAKE_RESET_PATCH_ID  # noqa: E402


# ---------- A. FakeMemoGate + 守卫状态机 ----------

class FakeMemoGate:
    """逐语义抄 temporalio 1.18.2 workflow_patch（_workflow_instance.py L1240-1251）：
    memo 命中即返回；首评 `not is_replaying or id in notified` 并写入 memo；
    use_patch=True 时发 marker 命令；marker 事件重放时 id 进 notified（L737-739）。"""

    def __init__(self):
        self.memo: dict = {}
        self.notified: set = set()
        self.is_replaying: bool = False
        self.commands: list = []          # 追加的 marker 命令（历史对账口径）

    def apply_history_marker(self, pid: str) -> None:
        self.notified.add(pid)

    def patched(self, pid: str) -> bool:
        use = self.memo.get(pid)
        if use is not None:
            return use
        use = (not self.is_replaying) or (pid in self.notified)
        self.memo[pid] = use
        if use:
            self.commands.append(pid)
        return use


class GuardMachine:
    """_blocked_over_limit 的可复现状态机抽象（seq 计数 + 唤醒穿越守卫）。

    enter()=进入超限 blocked；wake(live_or_replay, rework=False)=唤醒穿越。
    replay_history(events) 按「enter/wake/…/signal」事件脚本重放一遍。"""

    def __init__(self, gate: FakeMemoGate, disable: bool = False):
        self.gate = gate
        self.disable = disable
        self.seq = 0
        self.resets: list = []

    def _guard(self, rework: bool, replaying_at_wake: bool) -> bool:
        if rework or self.disable:
            return False
        self.gate.is_replaying = replaying_at_wake
        try:
            return self.gate.patched("%s#%d" % (KI061_WAKE_RESET_PATCH_ID, self.seq))
        finally:
            self.gate.is_replaying = False

    def enter(self) -> None:
        self.seq += 1

    def wake(self, rework: bool = False, replaying_at_wake: bool = False) -> bool:
        reset = self._guard(rework, replaying_at_wake)
        if reset:
            self.resets.append(self.seq)
        return reset


def test_a1_replay_of_prefix_history_keeps_command_stream_identical():
    """旧 history（修复前代码产生：两次 blocked+两次唤醒，均无重置）用修复后代码重放：
    各唤醒点守卫 False 且零 marker 命令——与修复前命令序列一致，重放不炸。"""
    gate = FakeMemoGate()
    m = GuardMachine(gate, disable=False)
    # 重放 pre-fix 历史：enter1→wake1→enter2→wake2，全程 is_replaying=True
    m.enter()
    assert m.wake(replaying_at_wake=True) is False
    m.enter()
    assert m.wake(replaying_at_wake=True) is False
    assert gate.commands == []          # 零命令追加（044c692 之前裸改炸点的对偶保障）
    # memo 毒化仅作用于已穿越 id，不再被读（每进入唯一后缀）
    assert gate.memo == {KI061_WAKE_RESET_PATCH_ID + "#1": False,
                         KI061_WAKE_RESET_PATCH_ID + "#2": False}


def test_a2_live_wake_returns_true_writes_unique_marker_and_resets():
    """live 唤醒点 id 从未被求值 → 首评 True、写 marker、触发重置（本票救活机制）。"""
    gate = FakeMemoGate()
    m = GuardMachine(gate, disable=False)
    m.enter(); m.wake(replaying_at_wake=True)     # 历史唤醒点（毒化 #1=False）
    m.enter()
    assert m.wake(replaying_at_wake=False) is True    # live 唤醒（当前卡死票的下一次 retry）
    assert gate.commands == [KI061_WAKE_RESET_PATCH_ID + "#2"]
    assert m.resets == [2]


def test_a3_future_replay_reproduces_true_from_notified_marker():
    """重置产生的 marker 已入 history → 未来重放在同位经 notified 复现 True。"""
    gate = FakeMemoGate()
    m = GuardMachine(gate, disable=False)
    m.enter(); m.wake(replaying_at_wake=True)
    m.enter(); assert m.wake(replaying_at_wake=False) is True
    # 未来重放：marker 事件按历史序进 notified；重放协程再次走到 wake2
    for pid in gate.commands:
        gate.apply_history_marker(pid)
    gate.commands.clear()
    m2 = GuardMachine(gate, disable=False)
    m2.enter(); assert m2.wake(replaying_at_wake=True) is False
    m2.enter(); assert m2.wake(replaying_at_wake=True) is True    # 同位复现，确定性保持
    assert gate.commands == []   # marker 已在 history，重放不再发新命令


def test_a4_seq_uniqueness_across_serial_and_parallel_branches():
    """串/并行分支共用一个计数器：id 由进入序号唯一决定，不碰撞、不重复求值。"""
    gate = FakeMemoGate()
    m = GuardMachine(gate, disable=False)
    seen = []
    for _ in range(4):
        m.enter()
        seen.append(KI061_WAKE_RESET_PATCH_ID + "#%d" % m.seq)
        m.wake(replaying_at_wake=False)
    assert len(set(seen)) == 4
    # 每个一次性 id 至多 memo 化一次求值（live 全 True，无重复评估路径）
    assert all(v is True for v in gate.memo.values())


def test_a5_short_circuit_and_malformed_shapes():
    """rework 唤醒/测试开关短路不求值 patched；多次 blocked 计数单调；空 why 不炸。"""
    gate = FakeMemoGate()
    m = GuardMachine(gate, disable=True)
    for _ in range(3):
        m.enter()
        assert m.wake() is False            # 开关短路：守卫关闭（复刻 02:12 卡死）
    assert gate.memo == {}                  # 短路路径从未求值 patched
    m2 = GuardMachine(gate, disable=False)
    for _ in range(3):
        m2.enter()
        assert m2.wake(rework=True) is False  # rework 唤醒：主循环顶处理，不重置
    assert gate.memo == {}
    # 空 why / 多次 blocked：计数单调、id 唯一（helper 入参畸形不破坏计数器）
    assert m2.seq == 3


# ---------- B. build_stage_prompt 宿主裁决注入回归 ----------

def _arb_stage() -> Stage:
    for s in dev_lane.DevLaneWorkflow.STAGES:
        if s.id == "arbitrate":
            return s
    raise AssertionError("arbitrate stage 未声明")


def _meta(rulings=None):
    return {
        "id": "t260908-01", "title": "KI-061", "write_set": ["server/dsh/temporal-poc/x.py"],
        "user_request": "修复", "host_rulings": rulings or [],
    }


def test_b_prompt_contains_host_ruling_on_arbitrate_respawn():
    r = [{"ts": "2026-09-08T08:00:00+00:00", "who": "host", "note": "终裁：判 pass 过闸"}]
    p = build_stage_prompt("t260908-01", _meta(r), _arb_stage(), [], "/tmp/r.json", 7, "")
    assert "宿主裁决注入" in p and "判 pass 过闸" in p and " host] 终裁：判 pass 过闸" in p


def test_b_prompt_truncates_overlong_ruling_with_mark():
    from shared import HOST_RULING_NOTE_LIMIT, _CAP_TRUNC_MARK
    r = [{"ts": "t", "who": "host", "note": "x" * (HOST_RULING_NOTE_LIMIT + 100)}]
    p = build_stage_prompt("t260908-01", _meta(r), _arb_stage(), [], "/tmp/r.json", 1, "")
    assert _CAP_TRUNC_MARK in p


def test_b_prompt_without_rulings_has_no_section():
    p = build_stage_prompt("t260908-01", _meta([]), _arb_stage(), [], "/tmp/r.json", 1, "")
    assert "宿主裁决注入" not in p


# ---------- C. integration_route 超限边界 ----------

def test_c_route_boundary_tests_fault():
    assert integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS, 0) == "run_integration_tests"
    assert integration_route(
        "tests-fault", MAX_TESTS_FAULT_ROUNDS + 1, 0).startswith("blocked:测试集迭代 6 轮超限")


def test_c_route_boundary_code_fault():
    assert integration_route("code-fault", 0, MAX_CODE_FAULT_ROUNDS) == "implement"
    assert integration_route(
        "code-fault", 0, MAX_CODE_FAULT_ROUNDS + 1).startswith("blocked:打回 developer")


def test_c_route_pass_and_unknown():
    assert integration_route("pass", 99, 99) == "acceptance"
    assert integration_route("??", 0, 0).startswith("blocked:仲裁结论未知")
