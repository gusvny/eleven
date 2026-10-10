#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-50 — the wiring tripwire: the scan tick's line-round activity is
registered on the single activity face, and the scan workflow module carries
the call site (import-level; no Temporal server needed)."""

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))


def test_activity_registered():
    import activities
    names = {getattr(a, "__name__", str(a)) for a in activities.ALL_ACTIVITIES}
    assert "line_round_tick_engine" in names


def test_workflow_module_imports_call_site():
    import workflows
    assert hasattr(workflows, "LINE_ROUND_PATCH_ID")
    assert workflows.LINE_ROUND_PATCH_ID == "dispatcher-scan-line-round"


def test_engine_body_reachable_through_activity_name():
    import develop_certify
    assert callable(develop_certify.line_round_tick_engine)
