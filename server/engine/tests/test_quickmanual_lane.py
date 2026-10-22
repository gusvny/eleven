"""quickmanual-lane UT (t261019-32): stage/registration declaration, the manual
work stage intake, the evidence gate, the no-self-sign check, the gate verdict
and the registration face.

Coverage map (= plan gen1 blocks, review-passed):
  A. STAGES is exactly the five stages, first = open; no create_plan /
     review_plan / design_integration_tests / arbitrate / acceptance_walkthrough /
     implement anywhere; the rework vocabulary excludes them (refused by name).
  B. Reuse source-locks: the class calls the parent's / the engine's shared
     machinery (_prepare_workspace_step, settle_lane, _integ_run_args,
     _main_sync_before_gate, the same activities for merge_check / merge /
     archive / teardown) and does NOT re-implement gates (no second gate-spec
     table beyond the declaration mirror, no hand-rolled landing).
  C. Evidence validator matrix: each valid kind passes; malformed inputs
     (non-dict, missing/blank kind, unknown kind, missing/blank/whitespace name,
     non-string shapes, over-long name) are refused with a NAMED reason; the
     name is stripped on success (external-input discipline, stub-fixed).
  D. work_done intake: missing / empty / whitespace-only session refused by name
     and never parked; a valid payload is accepted with strip + defaults; the
     cross-project gate refusal consumes the signal without parking.
  E. No-self-sign: the recorded working session's exact id is refused with the
     no-self-sign reason; any other signer falls through to the parent handler
     (refused there for not-awaiting-human, NOT with the no-self-sign why); an
     empty worked_by never triggers the gate.
  F. Gate verdict truth table (same table as light-lane): error=red, product
     red=red, blockers=red, env_fail without a named channel=red, named env
     reds + no product red=green, all green=green.
  G. Blocked digest caps: at most FACE_NAME_LIMIT names then "+N more", line and
     char caps hold (the face is a human digest, never a machine list).
  H. Registration face: shared names/display faces carry the id; the machine
     gate is declared for (quickmanual-lane, run_integration_tests); the fixture
     template env surface stays fixture-only; the class face
     (workflows_v2.TEMPLATE_CLASSES / ALL_WORKFLOWS_V2) and the generated
     server/workflows/quickmanual-lane.yaml register in the named follow-up step
     after the host amends the declared paths (plan gen1 step 0) - pinned as
     xfail(strict=False) so the lock lights up red now and flips green exactly
     when that step lands.
  I. SDK definition: the class carries its own definition (run = its own, name =
     the class name); the parent's and light-lane's definitions are unchanged.

No network, no real Temporal, no real git (conftest only adds sys.path).
Run: repo root `server/engine/.venv/bin/python -m pytest server/engine/tests/test_quickmanual_lane.py -q`.
"""
from __future__ import annotations

import datetime
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import light_lane  # noqa: E402
import shared  # noqa: E402

NOW_DT = datetime.datetime(2026, 10, 19, 12, 0, 0, tzinfo=datetime.timezone.utc)

QMW = dev_lane.QuickmanualLaneWorkflow

_EXCLUDED_STAGES = ("create_plan", "review_plan", "design_integration_tests",
                    "implement", "arbitrate", "acceptance_walkthrough")


@pytest.fixture(autouse=True)
def _workflow_shell():
    """dev_lane's workflow facade name is pinned to an offline shell
    (test_light_lane_lane.py's same discipline)."""
    saved = dev_lane.workflow
    shell = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    dev_lane.workflow = shell
    yield
    dev_lane.workflow = saved


async def _wake_immediately(_cond):
    return None


def _mk_wf(meta=None, gens=None):
    """A QuickmanualLaneWorkflow shell without a Temporal runtime."""
    wf = object.__new__(QMW)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = dict(gens or {})
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.gate_runs = []
    wf.human_context = {}
    wf.signatures = {}
    wf.ticket_id = "t-ut-quick"
    wf._detail_face_on = True
    wf.refused = []
    wf.engine_version = 2
    wf._quick_work_done = None
    return wf


def _ir(**kw):
    base = dict(ran=3, passed=3, failed=0, env_fail=0, details=[], error="")
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _ir_red(names, **kw):
    det = [{"name": n, "cmd": "", "exit": 1, "output_tail": ""} for n in names]
    kw.setdefault("ran", len(names))
    kw.setdefault("passed", 0)
    kw.setdefault("failed", len(names))
    return _ir(details=det, **kw)


# ======================================================================
# A. Stage declaration + excluded stages absent
# ======================================================================

def test_stage_chain_is_the_quickmanual_walk():
    ids = [s.id for s in QMW.STAGES]
    assert ids == ["open", "work", "run_integration_tests", "merge_check", "merge"]
    # linear chain, first = open
    assert QMW.STAGES[0].id == "open"
    for s in QMW.STAGES[:-1]:
        assert s.next == QMW.STAGES[ids.index(s.id) + 1].id
    # the human gate is merge and only merge
    assert [s.id for s in QMW.STAGES if getattr(s, "exit", "") == "human"] == ["merge"]
    # no agent stage anywhere (the work stage spawns no agent): no stage
    # declares "agent" in its executor mix
    assert all("agent" not in tuple(s.parts) for s in QMW.STAGES)


def test_excluded_stages_are_absent_and_refused_as_rework_targets():
    ids = [s.id for s in QMW.STAGES]
    for bad in _EXCLUDED_STAGES:
        assert bad not in ids
    wf = _mk_wf(meta={"stage": "work"})
    for bad in _EXCLUDED_STAGES:
        wf._rework = shared.ReworkRequest(who="host", target_stage=bad, note="x")
        landing, refusal = wf._consume_quick_rework("work")
        assert landing == "" and refusal and bad in refusal
        assert wf._rework is None  # refusals consume the signal, never a residue
    # the legitimate vocabulary lands (role resolved from this class's STAGES)
    for tgt in ("open", "work", "run_integration_tests", "merge_check", "merge"):
        wf2 = _mk_wf(meta={"stage": "merge"})
        wf2._rework = shared.ReworkRequest(who="host", target_stage=tgt, note="back")
        landing, refusal = wf2._consume_quick_rework("merge")
        assert landing == tgt and refusal == ""
        assert wf2.meta["stage"] == tgt
        assert wf2.meta["role"] == wf2._step(tgt).role


def test_machine_gate_declaration_on_the_class():
    gate = QMW.STAGES[2].gate
    assert gate.tool == "verify_lane" and gate.args.get("lane") == "integ"
    # the shared default_gate_for mirror lands with the atomic registration step
    # (pinned in the xfail below), never before it - no half registration


# ======================================================================
# B. Reuse source-locks (no second implementation of the shared machinery)
# ======================================================================

def test_run_reuses_the_shared_machinery():
    # run() is a thin fail-named boundary; the orchestration lives in
    # _run_quickmanual (acceptance gen2: a fault there must become a named
    # blocked, never an invisible stall).
    src = (inspect.getsource(QMW.run) + inspect.getsource(QMW._run_quickmanual)
           + inspect.getsource(QMW._quick_gate_round))
    for needle in ("_prepare_workspace_step", "settle_lane", "_effective_write_set",
                   "_protected_authz_records", "_main_sync_before_gate",
                   "run_integration_tests", "merge_check", "prepare_human_gate",
                   "archive_ticket", "teardown_lane", "_integ_run_args",
                   "_record_authz_uses", "_pin_settle_refusal"):
        assert needle in src, needle
    # the work stage waits for the session signal and records the identity face
    assert "work_done" in src and "worked_by" in src
    # the fail-named boundary: run wraps the body; an escaping fault becomes a
    # named blocked on the face (never an invisible stall), and the pre-open
    # steps land trace entries so a stall is locatable to one step
    assert "traceback" in inspect.getsource(QMW.run).lower()
    assert "_blocked(" in inspect.getsource(QMW.run)
    assert "pre-open: workspace ready" in inspect.getsource(QMW._run_quickmanual)


def test_no_second_gate_implementation():
    src = inspect.getsource(QMW)
    # the pre-gate main sync is the parent's single implementation, not a copy
    assert "async def _main_sync_before_gate" not in src
    # the verdict delegates to the parent's red-name single writers
    assert "def _quick_gate_verdict" in src
    assert "_tests_red_names" in src and "_tests_env_red_names" in src
    # the main-sync texts come from light-lane's English block (lazy import), not
    # a second copy
    assert "import light_lane" in inspect.getsource(QMW._quick_main_sync_texts)


# ======================================================================
# C. Evidence validator matrix (malformed input discipline)
# ======================================================================

@pytest.mark.parametrize("kind", ["l1_battery", "scenario", "check"])
def test_evidence_valid_kinds_pass(kind):
    ok, reason, norm = shared.quick_evidence_validate({"kind": kind, "name": " proof "})
    assert ok and reason == "" and norm == {"kind": kind, "name": "proof"}


@pytest.mark.parametrize("raw,frag", [
    ("nope", "must be an object"),
    (None, "must be an object"),
    ([], "must be an object"),
    ({}, "kind missing"),
    ({"name": "x"}, "kind missing"),
    ({"kind": "  ", "name": "x"}, "kind missing"),
    ({"kind": "battery", "name": "x"}, "not one of"),
    ({"kind": "scenario"}, "name missing"),
    ({"kind": "scenario", "name": ""}, "name missing"),
    ({"kind": "scenario", "name": "   "}, "name missing"),
    ({"kind": "scenario", "name": 7}, "name must be a string"),
    ({"kind": 7, "name": "x"}, "kind must be a string"),
    ({"kind": "check", "name": "x" * 501}, "over"),
])
def test_evidence_malformed_inputs_are_named_and_refused(raw, frag):
    ok, reason, norm = shared.quick_evidence_validate(raw)
    assert not ok and norm == {}
    assert frag in reason


def test_evidence_boundary_name_length_passes():
    ok, reason, _ = shared.quick_evidence_validate(
        {"kind": "check", "name": "x" * shared.QUICK_WORK_EVIDENCE_REF_LIMIT})
    assert ok and reason == ""


# ======================================================================
# D. work_done intake
# ======================================================================

def _intake_wf():
    wf = _mk_wf()
    wf._cross_project_gate = lambda *a, **k: True
    return wf


def test_work_done_blank_sessions_are_refused_and_never_park():
    for bad in ("", "   ", None):
        wf = _intake_wf()
        wf.work_done(shared.WorkDoneSignal(session=bad or ""))
        assert wf._quick_work_done is None
        assert wf.refused and "session id" in wf.refused[-1]["why"]


def test_work_done_valid_payload_is_accepted_normalized():
    wf = _intake_wf()
    wf.work_done(shared.WorkDoneSignal(session=" sess-9 ", role=" host ",
                                       note="done", evidence_ref="tests/x.py"))
    assert wf._quick_work_done == {"session": "sess-9", "role": "host",
                                   "note": "done", "evidence_ref": "tests/x.py"}
    assert wf.refused == []
    # role defaults, note truncated to the intake limit
    wf2 = _intake_wf()
    wf2.work_done(shared.WorkDoneSignal(
        session="s", note="n" * (shared.QUICK_WORK_NOTE_INPUT_LIMIT + 50)))
    assert wf2._quick_work_done["role"] == "session"
    assert len(wf2._quick_work_done["note"]) == shared.QUICK_WORK_NOTE_INPUT_LIMIT


def test_work_done_cross_project_refusal_consumes_without_parking():
    wf = _mk_wf()
    wf._cross_project_gate = lambda *a, **k: False
    wf.work_done(shared.WorkDoneSignal(session="s1"))
    assert wf._quick_work_done is None and wf.refused == []


# ======================================================================
# E. No-self-sign
# ======================================================================

def test_sign_working_session_is_refused_by_name():
    wf = _mk_wf(meta={"worked_by": {"session": "sess-1", "role": "host"}})
    wf.sign(shared.Signature(who="sess-1", gate="merge", decision="approve"))
    assert wf.refused and "no self-sign" in wf.refused[-1]["why"]
    assert "merge" not in getattr(wf, "_sigs", {})


def test_sign_other_signers_fall_through_to_the_parent_handler():
    wf = _mk_wf(meta={"worked_by": {"session": "sess-1", "role": "host"}})
    # the parent handler runs its own rules: not awaiting-human -> refused there,
    # with the parent's reason (NOT the no-self-sign one)
    wf.sign(shared.Signature(who="executor-x", gate="merge"))
    assert wf.refused and "no self-sign" not in wf.refused[-1]["why"]
    assert wf.refused[-1]["who"] == "executor-x"


def test_sign_without_worked_by_never_triggers_the_gate():
    wf = _mk_wf()
    wf.sign(shared.Signature(who="host", gate="merge"))
    assert wf.refused and "no self-sign" not in wf.refused[-1]["why"]


# ======================================================================
# F. Gate verdict truth table
# ======================================================================

def test_gate_verdict_red_on_error():
    wf = _mk_wf()
    assert wf._quick_gate_verdict(_ir(error="verify_lane integ produced no valid "
                                           "output")) == "red"


def test_gate_verdict_red_on_product_reds_and_blockers():
    wf = _mk_wf()
    assert wf._quick_gate_verdict(_ir_red(["sc_a", "sc_b"])) == "red"
    assert wf._quick_gate_verdict(_ir(failed=1, blockers=["sc_blocked"])) == "red"


def test_gate_verdict_red_on_unnameable_env_red():
    wf = _mk_wf()
    # env_fail > 0 with no named env-red channel = red (no named channel = no
    # exemption, the B2 rule)
    assert wf._quick_gate_verdict(_ir(env_fail=2)) == "red"


def test_gate_verdict_green_paths():
    wf = _mk_wf()
    assert wf._quick_gate_verdict(_ir()) == "green"
    assert wf._quick_gate_verdict(_ir(ran=0, passed=0)) == "green"
    # named environment reds are recorded, not blocking (the named channel is
    # present, so the exemption holds)
    assert wf._quick_gate_verdict(_ir(env_fail=1, env_red=["sc_env"])) == "green"


# ======================================================================
# G. Blocked digest caps
# ======================================================================

def test_blocked_digest_is_a_human_digest_not_a_machine_list():
    wf = _mk_wf()
    names = ["sc_%02d" % i for i in range(9)]
    text = wf._quick_gate_blocked_text(_ir_red(names), "quick_gate_red", 1)
    assert "sc_00" in text and "sc_04" in text
    assert "sc_05" not in text and "+4 more" in text
    assert len(text.splitlines()) <= QMW.FACE_MAX_LINES
    assert len(text) <= QMW.FACE_MAX_CHARS
    assert "rework(to_stage=work)" in text and "retry_qc" in text
    # the full set still travels in the receipt
    receipt = wf._quick_gate_receipt(_ir_red(names), 0)
    assert receipt["violations"] == names
    assert receipt["status"] == "failed"


def test_blocked_digest_green_receipt_status():
    wf = _mk_wf()
    receipt = wf._quick_gate_receipt(_ir(), 0)
    assert receipt["status"] == "ok"


# ======================================================================
# H. Registration face
# ======================================================================

def test_registration_landed_atomically_on_every_face():
    """261022 host order: the step-0 amendment landed, so the atomicity contract is
    asserted in the other direction. A half registration (names without display /
    gate / class / yaml, or the reverse) is still the failure this pins: every face
    must agree, and creation must accept the id."""
    assert shared.TEMPLATE_CLASS_NAMES.get("quickmanual-lane") == "QuickmanualLaneWorkflow"
    assert shared.TEMPLATE_DISPLAY_NAMES.get("quickmanual-lane") == "Quickmanual Lane"
    assert "quickmanual-lane" in shared.BUILTIN_TEMPLATE_KEYS
    gate = shared.default_gate_for("quickmanual-lane", "run_integration_tests")
    assert gate is not None and gate.tool == "verify_lane"
    import workflows_v2
    assert workflows_v2.TEMPLATE_CLASSES.get("quickmanual-lane") is QMW
    # the worker face keeps the SINGLE registration (workflows.ALL_WORKFLOWS carries
    # the class); a second copy in ALL_WORKFLOWS_V2 makes the replayer see two
    # workflows of one name and fail its whole-set validation.
    import workflows
    assert QMW in workflows.ALL_WORKFLOWS
    assert QMW not in workflows_v2.ALL_WORKFLOWS_V2
    yaml = (POC.parent / "workflows" / "quickmanual-lane.yaml")
    assert yaml.is_file(), "generated template yaml missing: %s" % yaml
    # the class itself is implemented and importable (the registration step only
    # wires the faces around it)
    assert QMW.TEMPLATE_ID == "quickmanual-lane"


def test_fixture_template_surface_stays_fixture_only():
    # SANDBAR_FIXTURE_TEMPLATES gates only the fixture template - the quickmanual
    # template must never ride that surface (ticket red line)
    assert os_environ_get(shared.FIXTURE_TEMPLATES_ENV) != "1" or \
        shared.TEMPLATE_CLASS_NAMES.get("fixture-two-step") == "FixtureTwoStepWorkflow"
    src = inspect.getsource(shared)
    reg = "if os.environ.get(FIXTURE_TEMPLATES_ENV) == \"1\":"
    assert src.count(reg) == 2  # names + display faces, unchanged blocks
    assert "quickmanual-lane" not in src.split(reg)[-1][:400]


def os_environ_get(name):
    import os
    return os.environ.get(name)


def test_creation_fails_closed_until_the_registration_lands():
    # with the template absent from every face, both creation entries refuse with
    # a named error - never a half-started workflow with no registered worker
    import template_topology  # noqa: PLC0415
    assert template_topology.export_template_topology("quickmanual-lane") is None


# ======================================================================
# I. SDK definition faces
# ======================================================================

def test_own_definition_parent_and_light_lane_unchanged():
    d = QMW.__temporal_workflow_definition
    assert d is not None and d.name == "QuickmanualLaneWorkflow"
    assert d.run_fn.__qualname__.startswith("QuickmanualLaneWorkflow")
    assert "work_done" in d.signals and "sign" in d.signals
    assert "snapshot" in d.queries
    pd = dev_lane.DevLaneWorkflow.__temporal_workflow_definition
    assert pd.name == "DevLaneWorkflow" and "work_done" not in pd.signals
    ld = light_lane.LightLaneWorkflow.__temporal_workflow_definition
    assert ld.name == "LightLaneWorkflow" and "work_done" not in ld.signals


def test_snapshot_adds_only_additive_keys():
    wf = _mk_wf(meta={"worked_by": {"session": "s", "role": "r", "at": "t"},
                      "quick_evidence": {"kind": "check", "name": "n"},
                      "template_id": "quickmanual-lane", "status": "running",
                      "stage": "work", "stage_state": "awaiting"})
    face = wf.snapshot()
    assert face["worked_by"] == {"session": "s", "role": "r", "at": "t"}
    assert face["quick_evidence"] == {"kind": "check", "name": "n"}
    # the parent's keys are still there (shape never breaks for old consumers)
    for key in ("meta", "template_id", "stage", "status"):
        assert key in face
