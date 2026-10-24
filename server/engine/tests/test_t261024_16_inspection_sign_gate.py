#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261024-16: the inspection human-gate sign handler judges in the right order.

Defect (measured by integration/t260915-08/sc_inspection_sign_journey.py on the
plain-process bench): the sign handler ran the cross-project judge BEFORE
validate_close_signature, so under the t260925-08 default
``undeclared_policy()=refuse`` an undeclared caller's refusal text (the
cross-project why) masked BOTH the agent self-sign refusal (no "agent" token on
the face) AND the human sign (``_close_sig`` never set -> the ticket never
closed). Fix under test here:
  1. handler order = authorize -> validate_close_signature -> cross-project
     judge -> accept, so every refusal names its own rule;
  2. at the sign call site the judge runs with policy="record": an undeclared
     caller's valid human signature is accepted AND the record row is booked
     into the workflow timeline (this family has no cross_project_uses face);
  3. guards kept: agent role names refused by name, malformed/absent who
     fail-closed, a declared mismatched caller still refused.

UT zero Temporal runtime (inspection_flow.workflow stubbed), zero network,
zero git. Run: repo root ``server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261024_16_inspection_sign_gate.py -q``.
"""
import datetime
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspection_flow as flow  # noqa: E402
import shared  # noqa: E402
from shared import Signature  # noqa: E402

NOW_DT = datetime.datetime(2026, 10, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)
UNDECLARED = shared.CALLER_UNDECLARED_MARK
GATE = flow.CLOSE_GATE_ID


@contextmanager
def _stub_workflow():
    """Zero-runtime stub for the module-level ``workflow`` seam: info() raises
    (the handler's SA read must fall back to the payload chain), now() and the
    logger answer inertly."""
    old = flow.workflow
    flow.workflow = SimpleNamespace(
        info=lambda: (_ for _ in ()).throw(RuntimeError("no runtime in UT")),
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    try:
        yield
    finally:
        flow.workflow = old


def _mk_wf(project_key="sandbar"):
    """Handler-direct shape (the module's own UT convention for signal truth)."""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    wf._gate_err = ""
    wf._close_sig = None
    wf._input = SimpleNamespace(project_key=project_key)
    wf.stage = "close"
    wf.stage_state = "awaiting-human"
    wf.timeline = []
    return wf


def _sign(wf, sig):
    with _stub_workflow():
        fn = flow.InspectionPeriodicWorkflow.__dict__["sign"]
        fn = getattr(fn, "__func__", fn)
        fn(wf, sig)


def _sig(who, gate=GATE, decision="approve", caller_project=UNDECLARED):
    return Signature(who=who, gate=gate, decision=decision, note="",
                     caller_project=caller_project, cross_project_note="")


# ---------- symptom 1: the agent self-sign refusal names its rule ----------

def test_agent_self_sign_refused_by_name_even_undeclared_caller():
    wf = _mk_wf()
    _sign(wf, _sig("developer"))
    assert wf._close_sig is None
    # Byte-identical to the refusal the case polls for (pinned substrings: the
    # agent token; the self-sign token comes from the validator itself).
    _, err = flow.validate_close_signature(_sig("developer"))
    assert wf._gate_err == err and "agent" in wf._gate_err


def test_every_agent_role_name_refused_by_name():
    for who in sorted(flow.AGENT_ROLE_NAMES):
        wf = _mk_wf()
        _sign(wf, _sig(who))
        assert wf._close_sig is None, who
        assert "agent" in wf._gate_err, who


def test_wrong_gate_refusal_names_the_gate_not_the_project():
    wf = _mk_wf()
    _sign(wf, _sig("human-scenario", gate="not-the-inspection-gate"))
    assert wf._close_sig is None
    assert "gate" in wf._gate_err and "inspection-close" in wf._gate_err


def test_malformed_and_absent_who_stay_fail_closed():
    for who in ("", "   "):
        wf = _mk_wf()
        _sign(wf, _sig(who))
        assert wf._close_sig is None and wf._gate_err
    wf = _mk_wf()
    _sign(wf, _sig("x" * 65))
    assert wf._close_sig is None and "who" in wf._gate_err


def test_bad_decision_refused():
    wf = _mk_wf()
    _sign(wf, _sig("human-scenario", decision="maybe"))
    assert wf._close_sig is None and "approve" in wf._gate_err


def test_authorize_payload_still_rejected_first():
    wf = _mk_wf()
    sig = _sig("human-scenario")
    object.__setattr__(sig, "authorize", SimpleNamespace(kind="x"))
    _sign(wf, sig)
    assert wf._close_sig is None and "no authorization face" in wf._gate_err


# ---------- symptom 2: an undeclared human sign is accepted and recorded ----------

def test_undeclared_human_sign_accepted_and_recorded_in_timeline():
    wf = _mk_wf()
    _sign(wf, _sig("human-scenario"))
    assert wf._gate_err == ""
    assert wf._close_sig is not None
    assert wf._close_sig["who"] == "human-scenario"
    # C1: the record leg is NOT silently dropped — the family's in-memory audit
    # face (timeline) carries the record row.
    rows = [r for r in wf.timeline if "cross-project gate record" in str(r.get("reason"))]
    assert len(rows) == 1
    assert UNDECLARED in rows[0]["reason"] and "sandbar" in rows[0]["reason"]


def test_declared_same_project_sign_accepted_without_record_row():
    wf = _mk_wf()
    _sign(wf, _sig("human-scenario", caller_project="sandbar"))
    assert wf._close_sig is not None and wf._gate_err == ""
    assert not [r for r in wf.timeline if "cross-project gate record" in str(r.get("reason"))]


def test_declared_mismatched_caller_still_refused():
    wf = _mk_wf()
    _sign(wf, _sig("human-scenario", caller_project="dengzhufpv"))
    assert wf._close_sig is None
    assert "cross-project" in wf._gate_err or "does not match" in wf._gate_err


def test_no_project_face_target_sign_accepted():
    # Empty target (old payloads / engine pieces) stays allow, unchanged semantics.
    wf = _mk_wf(project_key="")
    _sign(wf, _sig("human-scenario"))
    assert wf._close_sig is not None and wf._gate_err == ""


def test_first_signature_wins_second_ignored():
    wf = _mk_wf()
    _sign(wf, _sig("human-one"))
    _sign(wf, _sig("human-two"))
    assert wf._close_sig["who"] == "human-one"


# ---------- guard: judge ordering pinned at source ----------

def test_source_lock_validate_runs_before_cross_project_judge():
    src = (REPO / "server/engine/inspection_flow.py").read_text(encoding="utf-8")
    handler = src.split("def sign(self, sig: Signature) -> None:", 1)[1]
    handler = handler.split("@workflow.signal", 1)[0]
    v = handler.index("validate_close_signature(sig)")
    j = handler.index("cross_project_judge(")
    a = handler.index('self._close_sig = payload')
    assert v < j < a, "handler order must be validate -> judge -> accept"
    assert 'policy="record"' in handler, "sign call site must pin policy=record"
