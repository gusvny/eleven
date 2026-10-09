"""KI-212 (t261009-47) — rework hold: an instruction is delivered or refused by
name, never absorbed by a mechanical round.

Coverage:
  A. `rework_landing_decision` truth table (base.py): hold ONLY a non-agent phase
     in the running state; every parked state (blocked / awaiting-human /
     awaiting) consumes — review R3 invariant (no merge-gate spin wedge).
  B. Malformed inputs fail closed to consume, never raise.
  C. ReworkHoldMixin bookkeeping on a minimal instance: hold-face idempotency,
     coalescing format (C7: external note + who, `|` separator, internal note +
     attribution), terminal named refusal (R1/C6: original target named, slot
     cleared only via the refusal).
  D. Wiring source locks: the hold branch in dev_lane/light_lane sits behind the
     patch gate and before any consume; the signal is never set to None on the
     hold path; terminal guards exist at the real loop exits only; the merge-gate
     wait predicates still name the rework signal (R3 wake path unchanged); the
     internal human-gate reject sites go through the coalescing queue.
  E. Unpatched gate closed → consume paths referenced verbatim (patch id declared
     once, imported by both lane modules — one id covers both call sites, same as
     the settle-rerun precedent).

UT runs with the workflow shell stubs (no real Temporal / network / git).
Run: repo root `server/engine/.venv/bin/python -m pytest server/engine/tests/test_t261009_47_rework_hold.py -q`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import base  # noqa: E402
import dev_lane  # noqa: E402
import light_lane  # noqa: E402
from shared import ReworkRequest  # noqa: E402

PATCH = base.REWORK_HOLD_PATCH_ID
AGENT = dev_lane.AGENT_CAPABLE_PHASES
LIGHT_AGENT = light_lane.LIGHT_AGENT_PHASES


def _d(phase, target, state, agents=AGENT):
    return base.rework_landing_decision(phase, target, state, agents)


# ---------------------------------------------------------------- A: truth table

def test_hold_only_running_mechanical_phase():
    d, why = _d("run_integration_tests", "implement", "running")
    assert d == "hold" and "run_integration_tests" in why
    d, _ = _d("merge_check", "merge_check", "running")
    assert d == "hold"  # R2: a mechanical-named target is held like any other
    d, _ = _d("merge", "", "running")
    assert d == "hold"


def test_consume_on_every_parked_state():
    for st in ("blocked", "awaiting-human", "awaiting"):
        d, _ = _d("run_integration_tests", "implement", st)
        assert d == "consume", st
        d, _ = _d("merge", "implement", st)
        assert d == "consume", st


def test_consume_on_agent_capable_phase_even_if_not_target():
    for ph in sorted(AGENT):
        d, _ = _d(ph, "implement", "running")
        assert d == "consume", ph


def test_consume_everything_when_not_running_regardless_of_phase():
    d, _ = _d("", "", "blocked")
    assert d == "consume"


# ---------------------------------------------------------------- B: malformed inputs

def test_malformed_inputs_fail_closed_to_consume():
    for args in (("", "", ""), (None, None, None), ("run_integration_tests", "   ", "running")):
        d, _ = _d(*args)
    # never raises; a non-set agent_phases is treated as empty
    d, _ = _d("run_integration_tests", "implement", "running", agents=None)
    assert d == "hold"
    d, _ = _d("run_integration_tests", "implement", "running", agents=5)
    assert d == "consume"  # non-set agent_phases → fail closed to consume
    d, _ = _d("run_integration_tests", "x" * 100000 + "\n\u4e2d\u6587", "running")
    assert d == "hold"


# ---------------------------------------------------------------- C: mixin bookkeeping

class _Shell(base.ReworkHoldMixin):
    """Minimal instance: only what the mixin touches. patched() is injectable."""

    def __init__(self, patched=True):
        self.meta = {}
        self.refused = []
        self._rework = None
        self.logs = []
        self._patched = patched

    def _log(self, note, status=None):
        self.logs.append(note)

    def _touch(self):
        self.meta["touched"] = self.meta.get("touched", 0) + 1

    def _now_iso(self):
        return "2026-10-10T00:00:00Z"

    def _patched_fn(self, pid):
        return pid == PATCH and self._patched


def _patch_workflow(monkeypatch, value=True):
    import base as b
    monkeypatch.setattr(b.workflow, "patched", lambda pid: value)


def test_note_rework_held_face_and_idempotency(monkeypatch):
    _patch_workflow(monkeypatch)
    sh = _Shell()
    sh._rework = ReworkRequest(who="host", target_stage="implement", note="fix the red")
    sh._note_rework_held("implement", "held: running mechanical round")
    face = sh.meta["rework_held"]
    assert face["target"] == "implement" and face["note"] == "fix the red"
    assert face["who"] == "host" and face["why"]
    assert sh.meta["touched"] == 1
    # same target+note → no duplicate log/touch (no mechanical-round log spam)
    sh._note_rework_held("implement", "held: running mechanical round")
    assert sh.meta["touched"] == 1 and len(sh.logs) == 1


def test_queue_rework_coalesces_and_keeps_both_attributions(monkeypatch):
    _patch_workflow(monkeypatch)
    sh = _Shell()
    sh._rework = ReworkRequest(who="host", target_stage="implement",
                               note="please fix the failing gate")
    sh._queue_rework(
        ReworkRequest(who="engine", target_stage="implement",
                      note="merge dry-run conflict"),
        "main-sync conflict")
    req = sh._rework
    assert req.target_stage == "implement" and req.who == "host"  # external identity kept
    assert "please fix the failing gate (host)" in req.note        # C7: external note first
    assert " | internal main-sync conflict send-back: merge dry-run conflict (engine)" in req.note


def test_queue_rework_unpatched_overwrites_old_shape(monkeypatch):
    _patch_workflow(monkeypatch, value=False)  # gate closed: byte-for-byte old behavior
    sh = _Shell()
    sh._rework = ReworkRequest(who="host", target_stage="implement", note="held")
    inner = ReworkRequest(who="engine", target_stage="implement", note="internal")
    sh._queue_rework(inner, "main-sync conflict")
    assert sh._rework is inner  # old overwrite semantics, untouched


def test_terminal_refusal_names_original_target_and_clears_slot(monkeypatch):
    _patch_workflow(monkeypatch)
    sh = _Shell()
    sh._rework = ReworkRequest(who="host", target_stage="implement", note="do the thing")
    sh._refuse_held_rework_at_close()
    rec = sh.refused[-1]
    assert rec["want"] == "rework(implement)" and rec["who"] == "host"      # C6: original target
    assert "terminal (done)" in rec["why"] and "not absorbed" in rec["why"]
    face = sh.meta["rework_refused_at_close"]
    assert face["target"] == "implement" and face["note"] == "do the thing"
    assert sh._rework is None  # cleared only via the named refusal


def test_terminal_refusal_empty_target_names_default(monkeypatch):
    _patch_workflow(monkeypatch)
    sh = _Shell()
    sh._rework = ReworkRequest(who="host", target_stage="", note="n")
    sh._refuse_held_rework_at_close()
    assert sh.refused[-1]["want"] == "rework(default target = <landing>)"
    assert sh._rework is None


def test_terminal_guard_noop_without_signal(monkeypatch):
    _patch_workflow(monkeypatch)
    sh = _Shell()
    sh._refuse_held_rework_at_close()
    assert sh.refused == [] and sh._rework is None


# ---------------------------------------------------------------- D: wiring source locks

def _src(mod):
    return open(POC / mod).read()


def test_dev_lane_rework_branch_holds_before_consuming():
    src = _src("dev_lane.py")
    i = src.index("if self._rework is not None:", src.index("while phase != \"done\""))
    branch = src[i:i + 6000]
    assert "_held = False" in branch
    assert branch.index("workflow.patched(REWORK_HOLD_PATCH_ID)")
    assert branch.index("_note_rework_held") < branch.index("_consume_rework(fb)")
    # the hold path never clears the signal
    hold_seg = branch[:branch.index("if not _held:")]
    assert "self._rework = None" not in hold_seg
    # fall-through, not a continue that would spin on the hold branch
    assert "fall through to normal" in branch
    assert "hold branch without ever running the round" in branch
    assert "refused by name exactly as before" in branch  # C3


def test_dev_lane_terminal_guard_after_real_loop_exit():
    src = _src("dev_lane.py")
    i = src.index("# Close out")
    tail = src[i:i + 700]
    assert "_refuse_held_rework_at_close" in tail
    assert tail.index("REWORK_HOLD_PATCH_ID") < tail.index('self.meta["status"] = "closed"')


def test_light_lane_hold_and_terminal_guard():
    src = _src("light_lane.py")
    i = src.index("if self._rework is not None:", src.index("while phase != \"done\""))
    branch = src[i:i + 4000]
    assert "_note_rework_held" in branch and "_consume_light_rework(phase)" in branch
    assert branch.index("_note_rework_held") < branch.index("_consume_light_rework(phase)")
    j = src.rindex('self.meta["status"] = "closed"')  # structural marker: the close-out tail
    tail = src[j - 400:j + 400]
    assert "_refuse_held_rework_at_close" in tail
    assert tail.index("_refuse_held_rework_at_close") < j  # guard runs before close-out


def test_base_lane_hold_guard_and_terminal_guard():
    src = _src("base.py")
    i = src.index("def _apply_rework")
    body = src[i:src.index("def _prepare_workspace")]
    assert "REWORK_HOLD_PATCH_ID" in body and '_note_rework_held' in body
    assert body.index('stage_state') < body.index("req = self._rework")  # guard runs before consuming
    j = src.index("# All stages done")
    assert "_refuse_held_rework_at_close" in src[j:j + 400]


def test_parallel_stages_clear_consumes_only_not_on_hold():
    # KI-024 clear is part of the CONSUME bookkeeping: a held signal must not
    # touch the running parallel section's own edge pins.
    src = _src("dev_lane.py")
    i = src.index("if self._rework is not None:", src.index("while phase != \"done\""))
    branch = src[i:i + 7000]
    assert branch.index("_held = False") < branch.index("set_parallel_stages(self.meta, [])")
    seg = branch[branch.index("if not _held:"):branch.index("set_parallel_stages")]
    assert "Consuming\n                    # only (KI-212)" in seg


def test_gate_wake_predicates_still_name_rework():
    # R3: the parked-wake path is the honoring point — the predicates must keep
    # naming the rework signal (a regression here would wedge the held signal at
    # the gates).
    for mod in ("dev_lane.py", "light_lane.py"):
        src = _src(mod)
        assert src.count("self._rework is not None") >= 2, mod
        assert 'lambda: ("merge" in self._sigs) or (self._rework is not None)' in src, mod


def test_internal_rework_sites_use_coalescing_queue():
    for mod in ("dev_lane.py", "light_lane.py", "base.py"):
        src = _src(mod)
        assert "_queue_rework(" in src, mod
        if mod == "base.py":
            # the only surviving direct assignment is inside the mixin itself
            i0 = src.index("class ReworkHoldMixin")
            i1 = src.index("class TicketPauseMixin")
            outside = src[:i0] + src[i1:]
            assert "self._rework = ReworkRequest(" not in outside, mod
        else:
            assert "self._rework = ReworkRequest(" not in src, mod


def test_single_patch_id_shared_by_both_lanes():
    assert dev_lane.REWORK_HOLD_PATCH_ID == light_lane.REWORK_HOLD_PATCH_ID == PATCH
    assert PATCH == "ki212-rework-hold-v1"
    # the mixin is actually in both class hierarchies
    assert issubclass(dev_lane.DevLaneWorkflow, base.ReworkHoldMixin)
    assert issubclass(light_lane.LightLaneWorkflow, base.ReworkHoldMixin)
    assert issubclass(base.TicketWorkflowBase, base.ReworkHoldMixin)


def test_agent_capable_phase_sets_exclude_mechanical():
    mech = {"run_integration_tests", "merge_check", "merge",
            "parallel_impl_design", "integ_join", "integration_review",
            "arb_acc_parallel", "done"}
    assert not (AGENT & mech)
    assert AGENT <= dev_lane.PHASE_MAIN_CHAIN
    assert LIGHT_AGENT == {"implement"}  # light lane: one agent phase only
