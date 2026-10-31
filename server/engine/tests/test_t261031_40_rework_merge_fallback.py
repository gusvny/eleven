# -*- coding: utf-8 -*-
"""t261031-32: a rework with a VALID target lands, whatever the caller's fallback is.

Measured fault (261031, two tickets wedged): t261031-17 and t261031-20 were refused at
landing with "proven revision ... does not contain current main - a landing must carry
the main it was judged against". The remedy named there is one more green gate round
anchored on the current lane HEAD, so integration sent the send-back. Both attempts
were refused:

  want='rework(run_integration_tests) fallback()'
  why='fallback is not in the rework vocabulary (pure guard, this literal should never
       appear)'

Root cause, in two parts:
  1) `_consume_rework` returns an EMPTY landing phase when it refuses a signal, and the
     main loop took that value as its `phase`. The next round derived the fallback as
     `fb = ... else phase`, i.e. the empty string, and `_auto_rework` then validated that
     empty fallback and refused a VALID target (run_integration_tests is a main-chain
     step). The ticket could never be re-anchored: it parked at merge forever.
  2) `_auto_rework` validated the fallback although the fallback is returned ONLY when
     the TARGET is refused - a valid target never needs it.

Rules under test (this battery is the ticket's declared evidence):
  (a) the incident shape: a rework to run_integration_tests from a merge-blocked round
      whose phase went empty LANDS on run_integration_tests;
  (b) a valid target with an empty or unknown fallback lands and the ticket log names
      the failed fallback check - no "landing validation failed" hiding the cause;
  (c) the real guards still bite: an invalid target is refused BY NAME, `ui_evidence`
      is refused, `done` is refused, and a genuinely invalid fallback is still refused
      where it can be returned (an invalid target never hands garbage to the loop);
  (d) a refused signal keeps the round's own phase (an empty phase surfaced as
      "unknown internal phase" on the next wake);
  (e) replay discipline: a pre-fix history replays the OLD branch verbatim and issues
      no command, and the first LIVE round after the deploy takes the fix - the reason
      the gate uses one fresh patch id per round instead of a fixed one (KI-061: the
      SDK memoizes the first `patched()` verdict per id, so a fixed id read during
      replay stays False forever and the parked tickets would never reach the fix).

Harness: the UT-shell idiom of tests/test_260930_unknown_phase_hardening.py - no
Temporal runtime, no git, no network. `dev_lane.workflow` is replaced by a model of the
SDK patch manager whose semantics are copied from the installed
temporalio/worker/_workflow_instance.py::workflow_patch (1.18.2): first verdict per id
is memoized, a True verdict emits one marker command, a False verdict emits none.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import dev_lane as dl  # noqa: E402

DEV_LANE_PY = ENGINE / "dev_lane.py"
INCIDENT_TARGET = "run_integration_tests"


# ---------------------------------------------------------------- SDK patch model

class FakePatchManager:
    """Model of temporalio 1.18.2 `workflow.patched()`
    (worker/_workflow_instance.py::workflow_patch):

        use_patch = self._patches_memoized.get(id)
        if use_patch is not None: return use_patch
        use_patch = not self._is_replaying or id in self._patches_notified
        self._patches_memoized[id] = use_patch
        if use_patch: <one marker command>

    `replaying` flips to False when the instance reaches live code; `markers` are the
    patch ids the replayed history already carries."""

    def __init__(self, replaying=False, markers=()):
        self.replaying = bool(replaying)
        self.markers = set(markers)
        self.memo = {}
        self.commands = []

    def patched(self, pid):
        cached = self.memo.get(pid)
        if cached is not None:
            return cached
        use = (not self.replaying) or pid in self.markers
        self.memo[pid] = use
        if use:
            self.commands.append(("marker", pid))
        return use

    def markers_issued(self):
        return [c[1] for c in self.commands if c[0] == "marker"]


@pytest.fixture()
def sdk(monkeypatch):
    """A live (non-replaying) SDK model installed as `dev_lane.workflow`."""
    mgr = FakePatchManager()
    monkeypatch.setattr(dl, "workflow", SimpleNamespace(patched=mgr.patched))
    return mgr


# ---------------------------------------------------------------- UT shell

class _Shell:
    """Accounting surface of the rework landing path only (no workflow commands)."""

    _auto_rework = dl.DevLaneWorkflow._auto_rework
    _safe_phase = dl.DevLaneWorkflow._safe_phase
    _consume_rework = dl.DevLaneWorkflow._consume_rework
    _rework_fallback_phase = dl.DevLaneWorkflow._rework_fallback_phase

    def __init__(self, stage="merge", stage_state="blocked", status="dispatched",
                 role="integration"):
        self.meta = {"stage": stage, "stage_state": stage_state, "status": status,
                     "role": role, "log": []}
        self.timeline = []
        self.refused = []
        self._rework = None
        self.memo_calls = []

    # --- booking surface -------------------------------------------------
    def _now_epoch(self):
        return 1793437000

    def _now_iso(self):
        return "2026-10-31T09:00:00+00:00"

    def _log(self, note, status=None):
        self.meta.setdefault("log", []).append(
            {"ts": self._now_epoch(), "status": status or self.meta.get("status", ""),
             "note": note})

    def _mark(self, step, state, reason=""):
        self.timeline.append({"at": self._now_iso(), "stage": step, "state": state,
                              "reason": reason})

    def _touch(self):
        self.meta["updated"] = self._now_epoch()

    def _persist_stage_memo(self, stage, note=""):
        self.memo_calls.append((stage, note))

    def _step(self, step_id):
        for s in dl.DevLaneWorkflow.STAGES:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    # --- helpers ---------------------------------------------------------
    def ask(self, target, who="integration", note="re-anchor the gate round"):
        """Park a pending rework signal exactly as the signal handler writes it."""
        self._rework = dl.ReworkRequest(target_stage=target, note=note, who=who)

    def log_text(self):
        return "\n".join(e.get("note", "") for e in self.meta.get("log") or [])

    def refusal_notes(self):
        return [r for r in self.refused if str(r.get("want", "")).startswith("rework(")]


def _round(shell, phase):
    """One main-loop rework round: the loop-top fallback hint, then the consume.
    Returns (fb, landing_phase, edge, refusal_note)."""
    fb = shell._rework_fallback_phase(phase)
    landing, edge, note = shell._consume_rework(fb)
    return fb, landing, edge, note


# ================================================================ (a) incident shape

def test_incident_shape_empty_round_phase_still_lands(sdk):
    """The measured shape: the round is parked at merge and its `phase` went empty
    (the previous refusal returned no landing). A rework to run_integration_tests must
    land there; before the fix the empty value reached the landing guard and the valid
    target was refused."""
    w = _Shell(stage="merge", stage_state="blocked")
    w.ask(INCIDENT_TARGET)
    fb, landing, edge, note = _round(w, "")          # phase blanked by a refusal
    assert fb == "merge", "the round's parked phase is the usable fallback"
    assert (landing, edge, note) == (INCIDENT_TARGET, None, "")
    assert w.meta["stage"] == INCIDENT_TARGET
    assert w.meta["role"] == dl.PHASE_MAIN_ROLES[INCIDENT_TARGET]
    assert w.meta["status"] == "rework" and w.meta["stage_state"] == "awaiting"
    assert w._rework is None, "the signal is consumed (no residue)"
    assert w.refusal_notes() == [], "a valid target is not refused"
    log = w.log_text()
    assert "rework landing: the round phase ''" in log, \
        "the repair names the round phase it replaced: %s" % log
    assert "empty or not a phase" not in log, \
        "the fallback that landed was valid, so no fallback check failed: %s" % log


def test_incident_shape_does_not_need_the_parked_phase_to_be_merge(sdk):
    """The repair is not merge-specific: any parked main-chain phase works."""
    for parked in ("merge_check", "run_integration_tests", "implement"):
        w = _Shell(stage=parked, stage_state="blocked")
        w.ask(INCIDENT_TARGET)
        fb, landing, _, note = _round(w, "")
        assert fb == parked and note == "" and landing == INCIDENT_TARGET, parked


# ================================================================ (b) rule

def test_valid_target_lands_with_empty_fallback_and_log_names_the_check(sdk):
    """The rule itself, at the landing: the fallback is returned only by a refused
    TARGET, so an empty/unknown fallback cannot block a valid landing. The failed
    fallback check is named on the ticket log."""
    for bad in ("", "bogus_phase", "done"):
        w = _Shell(stage="merge")
        assert w._auto_rework(INCIDENT_TARGET, "note", "integration", bad) == \
            INCIDENT_TARGET, repr(bad)
        assert w.meta["stage"] == INCIDENT_TARGET
        assert w.refusal_notes() == [], "no refusal record for a landed target"
        log = w.log_text()
        assert "fallback %r" % bad in log, log
        assert "empty or not a phase" in log, log
        assert "lands" in log, log


def test_valid_target_with_empty_fallback_is_not_wedged_through_the_consume(sdk):
    """Gate matrix row: valid target + empty fallback does not wedge the ticket - the
    round moves on to the target and the ticket face says why the fallback was ignored."""
    w = _Shell(stage="merge")
    w.ask(INCIDENT_TARGET)
    phase, edge, note = w._consume_rework("")     # the pre-fix value, fed directly
    assert (phase, edge, note) == (INCIDENT_TARGET, None, "")
    assert w.meta["stage"] == INCIDENT_TARGET
    assert "empty or not a phase" in w.log_text()


# ================================================================ (c) guards kept

def test_invalid_target_refused_by_name(sdk):
    """`work` was integration's first attempt in the incident: a dev-lane has no work
    stage, so it is refused BY NAME and nothing lands."""
    w = _Shell(stage="merge")
    w.ask("work")
    _, phase, edge, note = _round(w, "merge")
    assert (phase, edge) == ("", None)
    assert note.startswith("[rework refused] target work ")
    assert "work" in note
    assert w.meta["stage"] == "merge", "a refused signal lands nowhere"
    assert w.refusal_notes(), "the refusal is booked"
    assert w.refusal_notes()[0]["want"] == "rework(work)"


@pytest.mark.parametrize("target", ["ui_evidence", "done"])
def test_ui_evidence_and_done_refused_by_name(sdk, target):
    w = _Shell(stage="merge")
    w.ask(target)
    _, phase, edge, note = _round(w, "merge")
    assert (phase, edge) == ("", None), target
    assert note.startswith("[rework refused] target %s " % target), note
    assert w.meta["stage"] == "merge"
    assert w.refusal_notes()[0]["want"] == "rework(%s)" % target


def test_genuinely_invalid_fallback_still_bites_and_never_returns_garbage(sdk):
    """The pure guard keeps its tooth where the fallback can actually be returned: an
    invalid TARGET still refuses, and an invalid fallback never flows into the loop."""
    w = _Shell(stage="")
    got = w._auto_rework("no_such_step", "note", "integration", "")
    assert got in dl.PHASE_MAIN_CHAIN and got != "done", \
        "an empty phase must never be handed back to the loop (got %r)" % (got,)
    assert got == dl.REWORK_PHASE_FALLBACK
    wants = [r["want"] for r in w.refused]
    assert "rework(no_such_step)" in wants, wants
    assert "phase-clamp" in wants, "the clamp is booked loudly, never silent"

    w2 = _Shell(stage="merge")
    assert w2._auto_rework("no_such_step", "note", "integration", "bogus_phase") == "merge"
    assert [r["want"] for r in w2.refused] == ["rework(no_such_step)"]


# ================================================================ (d) honest receipts

def test_receipt_names_the_failed_check_not_a_generic_landing_failure(sdk, monkeypatch):
    """The copy that cost the measurement hour: the refusal must name which check
    failed, not say "landing validation failed"."""
    src = DEV_LANE_PY.read_text("utf-8")
    assert "landing validation failed" not in src, \
        "the generic copy hides the cause (t261031-32)"

    # invalid target: the receipt carries the refusal reason by name
    w = _Shell(stage="merge")
    w.ask("work")
    _, _, _, note = _round(w, "merge")
    assert "landing validation failed" not in note
    assert "work" in note and INCIDENT_TARGET in note, \
        "the receipt names the refused target and the admissible list: %s" % note

    # old history (gate False): a valid target plus an empty fallback is still refused,
    # and the booking names the fallback check instead of a generic failure.
    mgr = FakePatchManager(replaying=True)
    monkeypatch.setattr(dl, "workflow", SimpleNamespace(patched=mgr.patched))
    w2 = _Shell(stage="merge")
    w2.ask(INCIDENT_TARGET)
    _, landing, _, note = _round(w2, "")
    assert landing == "" and note.startswith("[rework refused] target ")
    assert "fallback" in note and "valid main-chain step" in note, note
    assert w2.refusal_notes()[0]["want"] == "rework(%s) fallback()" % INCIDENT_TARGET
    assert "valid main-chain step" in w2.refusal_notes()[0]["why"]


# ================================================================ (e) replay discipline

def test_pre_fix_history_replays_the_old_branch_and_the_first_live_round_is_fixed(
        sdk, monkeypatch):
    """One instance, one patch manager: the recorded pre-fix rounds replay verbatim
    (empty fallback, refusal, ZERO commands), then the live round after the deploy takes
    the fix. A FIXED patch id would be memoized False here and the ticket would stay
    wedged - the fresh-id-per-round choice is what makes the remedy reach the parked
    tickets."""
    mgr = sdk
    w = _Shell(stage="merge", stage_state="blocked")

    # --- replayed pre-fix rounds (the wedged history, two refused signals)
    mgr.replaying = True
    w.ask("work")
    _, _, _, note1 = _round(w, "merge")
    assert note1.startswith("[rework refused] target work ")
    w.ask(INCIDENT_TARGET)
    _, landing2, _, note2 = _round(w, "")          # phase blanked by the first refusal
    assert landing2 == "" and "fallback" in note2, \
        "the pre-fix shape must replay verbatim (this is the wedge)"
    assert mgr.commands == [], "a False verdict issues no command: replay is safe"

    # --- the live round: a worker restart reached live code, the host re-sends
    mgr.replaying = False
    w.ask(INCIDENT_TARGET)
    fb, landing, _, note = _round(w, "")
    assert fb == "merge" and landing == INCIDENT_TARGET and note == ""
    assert w.meta["stage"] == INCIDENT_TARGET
    assert mgr.markers_issued(), "the live round records its patch markers"
    assert len(mgr.markers_issued()) == len(set(mgr.markers_issued())), \
        "every marker id is fresh (never reused, never poisoned)"

    # --- a later replay of the SAME history: the ids it wrote are now in history, so
    # the replayed rounds decide exactly as the live ones did (#1 refused, #2 refused
    # the pre-fix shape, #3 landed). No command is issued for a False verdict.
    mgr2 = FakePatchManager(replaying=True, markers=mgr.markers_issued())
    monkeypatch.setattr(dl, "workflow", SimpleNamespace(patched=mgr2.patched))
    w2 = _Shell(stage="merge", stage_state="blocked")
    w2.ask("work")
    _, _, _, re_note1 = _round(w2, "merge")
    assert re_note1.startswith("[rework refused] target work ")
    w2.ask(INCIDENT_TARGET)
    _, re_landing2, _, re_note2 = _round(w2, "")
    assert re_landing2 == "" and "fallback" in re_note2
    w2.ask(INCIDENT_TARGET)
    re_fb, re_landing, _, re_note = _round(w2, "")
    assert re_fb == "merge" and re_landing == INCIDENT_TARGET and re_note == "", \
        "the fix is replayed from its marker, not re-decided"
    assert w2.meta["stage"] == INCIDENT_TARGET


def test_refused_signal_keeps_the_round_phase_source_lock(sdk):
    """Wiring lock (R3: a test present is not a test wired): the loop top repairs the
    fallback hint, and a refusal restores the round's phase instead of blanking it."""
    src = DEV_LANE_PY.read_text("utf-8")
    assert "fb = self._rework_fallback_phase(phase)" in src
    branch = src[src.index("if getattr(self, \"_rework_escape_on\", False):"):]
    branch = branch[:branch.index("if edge == \"design\":")]
    assert "_round_phase = phase" in branch
    assert branch.index("_round_phase = phase") < branch.index("_consume_rework(fb)")
    assert "_rework_landing_on" in branch and "phase = _round_phase" in branch
    # the gate is one fresh id per pending-rework round (never a fixed id)
    assert '"%s#wake%d" % (REWORK_LANDING_FALLBACK_PATCH_ID, n)' in src
    assert '"%s#land%d" % (REWORK_LANDING_FALLBACK_PATCH_ID, _ln)' in src
    assert "workflow.patched(REWORK_LANDING_FALLBACK_PATCH_ID)" not in src, \
        "a fixed id would be frozen False by the first replay (KI-061)"
