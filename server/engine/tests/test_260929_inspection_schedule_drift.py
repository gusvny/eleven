"""260929 单测（KI-163）：声明↔调度器对账（纯函数面）。

病根（260929 排查「巡检静默」时发现）：`inspection.yaml` 里 `enabled: true` 只表示
「准不准跑」，真正接线是 `schedule-up`；两者之间此前**没有任何对账面**——于是
`docs-sync`（周一 10:00）与 `simplify-face`（周一 08:00）声明在册、Temporal 上零 Schedule，
**永不触发且无人知**（谁也不会去查一个自己没有调度的实例）。本单测锁三态判据与处方分流：

  missing（enabled 却无 Schedule）· orphan（有 Schedule 却已停用/除名）· paused（在但暂停）
  ——各态独立点名，alarmed=任一非空（CLI 据此 exit 1）；列表失败=「查不了」不许冒充「无漂移」。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_inspection_schedule_drift.py -q
"""
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_trigger as trig  # noqa: E402

DECL = [{"project": "sandbar", "id": "integration-tests", "enabled": True},
        {"project": "sandbar", "id": "docs-sync", "enabled": True},
        {"project": "sandbar", "id": "simplify-face", "enabled": True},
        {"project": "sandbar", "id": "mechanism-face", "enabled": False},
        {"project": "sandbar", "id": "stage-capacity", "enabled": False}]


def test_missing_schedule_is_the_ki163_case():
    rep = trig.schedule_drift_report(DECL, ["sandbar-inspection-integration-tests"], [])
    assert rep["missing"] == ["sandbar-inspection-docs-sync",
                              "sandbar-inspection-simplify-face"], \
        "enabled 却无 Schedule＝永不触发（docs-sync/simplify-face 实况）"
    assert rep["orphan"] == [] and rep["paused"] == []
    assert rep["alarmed"] is True


def test_disabled_instances_are_not_wanted():
    rep = trig.schedule_drift_report(DECL, ["sandbar-inspection-integration-tests"])
    assert not any("mechanism-face" in x or "stage-capacity" in x for x in rep["want"]), \
        "enabled=false 的占位实例不要求接线（它们**不该**有 Schedule）"


def test_orphan_schedule_is_drift_the_other_way():
    rep = trig.schedule_drift_report(
        [{"project": "sandbar", "id": "integration-tests", "enabled": True}],
        ["sandbar-inspection-integration-tests", "sandbar-inspection-docs-sync"])
    assert rep["orphan"] == ["sandbar-inspection-docs-sync"], \
        "调度器上有 Schedule 但声明已停用/除名＝反向漂移（声明说停、实际还在跑）"
    assert rep["alarmed"] is True


def test_paused_schedule_never_fires_too():
    """暂停与「无 Schedule」后果相同（都不触发），但处方不同 → 分开列。"""
    rep = trig.schedule_drift_report(DECL, ["sandbar-inspection-integration-tests"], [])
    assert rep["missing"], "前置：docs-sync/simplify-face 报缺"
    rep2 = trig.schedule_drift_report(
        [{"project": "sandbar", "id": "integration-tests", "enabled": True}],
        ["sandbar-inspection-integration-tests"], ["sandbar-inspection-integration-tests"])
    assert rep2["paused"] == ["sandbar-inspection-integration-tests"]
    assert rep2["missing"] == [] and rep2["alarmed"] is True


def test_all_wired_and_running_is_clean():
    rep = trig.schedule_drift_report(
        [{"project": "sandbar", "id": "integration-tests", "enabled": True}],
        ["sandbar-inspection-integration-tests"], [])
    assert rep["alarmed"] is False and rep["missing"] == rep["orphan"] == rep["paused"] == []


def test_non_inspection_schedules_are_out_of_scope():
    """dispatcher-scan 之流不属巡检对账面（别的机制有自己的对账）。"""
    rep = trig.schedule_drift_report(
        [{"project": "sandbar", "id": "integration-tests", "enabled": True}],
        ["sandbar-inspection-integration-tests", "sandbar-dispatcher-scan",
         "suyou-dispatcher-scan"], [])
    assert rep["alarmed"] is False and rep["orphan"] == []


def test_malformed_inputs_degrade_not_boom():
    assert trig.schedule_drift_report(None, None, None)["alarmed"] is False
    rep = trig.schedule_drift_report([None, "x", {}, {"id": ""}], ["junk"], None)
    assert rep["missing"] == [] and rep["orphan"] == [] and rep["alarmed"] is False


def test_cli_registers_the_drift_face():
    """接线锁：子命令在册 + 回执带 alarmed（main 的 exit-1 语义靠它）。"""
    src = Path(trig.__file__).read_text("utf-8")
    assert 'sub.add_parser("schedule-drift"' in src
    assert '"schedule-drift": cmd_schedule_drift' in src
    assert 'if result.get("ok")' in src and 'result["result"].get("alarmed")' in src
    assert 'return _err("调度器列表失败（无法对账，别当「无漂移」）' in src, \
        "查不了必须显式报错，不许冒充「没有漂移」"
