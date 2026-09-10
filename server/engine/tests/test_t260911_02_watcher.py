"""t260911-02 单测：watcher 装配面——workflow id 确定性（C-2）、输入形状、期号/票号
扩展、以及注册面（workflows.ALL_WORKFLOWS / activities.ALL_ACTIVITIES 含新件）。

workflow 体本身的行为断言走隔离台集成场景（temporalio 依赖运行时）；本文件只锁
可离线判定的装配契约。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_flow as flow


def test_watcher_workflow_id_deterministic_and_locked():
    # C-2：同声明重跑 schedule-up 必命中同一 workflow——形状变更=运维契约变更
    assert flow.watcher_workflow_id("docs-sync") == "inspection-watcher-docs-sync"
    assert flow.watcher_workflow_id("a") == "inspection-watcher-a"
    assert flow.watcher_workflow_id("docs-sync") == flow.watcher_workflow_id("docs-sync")


def test_watcher_workflow_id_rejects_malformed():
    for bad in ("", "UPPER", "../evil", "-lead", "x" * 65):
        with pytest.raises(ValueError):
            flow.watcher_workflow_id(bad)


def test_period_regex_accepts_both_forms():
    for good in ("20260911", "20260911-1", "20260911-42"):
        assert flow.PERIOD_RE.match(good)
    for bad in ("2026-09-11", "2026091", "20260911-", "20260911-0", "20260911-01"):
        assert not flow.PERIOD_RE.match(bad)
    # 20261399-2 形状合法但非真实日历日——日历校验在 trigger._valid_period（同票①分工）
    assert flow.PERIOD_RE.match("20261399-2")
    from inspection_trigger import _valid_period
    assert _valid_period("20261399-2") is not None


def test_ticket_id_accepts_count_period():
    assert flow.inspection_ticket_id("docs-sync", "20260911-3") == "inspection-docs-sync-20260911-3"
    with pytest.raises(ValueError):
        flow.inspection_ticket_id("docs-sync", "20260911-0")


def test_validate_trigger_args_period_message_updated():
    assert flow.validate_trigger_args("docs-sync", "20260911-2") is None
    err = flow.validate_trigger_args("docs-sync", "bad")
    assert err and "bucket" in err


def test_watcher_input_defaults():
    inp = flow.InspectionWatcherInput(instance_id="i", n=5, project_key="k")
    assert inp.poll_seconds == 60.0 and inp.scan_face == "test"
    assert inp.baseline == -1 and inp.cron == "" and inp.cron_anchor == ""


def test_watcher_registered_in_all_workflows():
    import workflows
    names = [w.__name__ for w in workflows.ALL_WORKFLOWS]
    assert "InspectionTicketCountWatcherWorkflow" in names
    assert "InspectionPeriodicWorkflow" in names


def test_watcher_activities_registered():
    import activities
    assert "count_archived_tickets" in [a.__name__ for a in activities.ALL_ACTIVITIES]
    assert "trigger_inspection_period" in [a.__name__ for a in activities.ALL_ACTIVITIES]


def test_max_iterations_capped():
    # 无界历史治理：continue_as_new 节流必须存在且为正
    assert 0 < flow.WATCHER_MAX_ITERATIONS <= 10000
