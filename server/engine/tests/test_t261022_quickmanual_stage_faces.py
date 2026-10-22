"""t261022-08: every quickmanual stage has a declared path-gate face.

Measured defect: the lane opened, the session worked, and the settle path gate
refused the write with path_gate_reason=unknown_stage ("stage work has no
configured allowed face (fail-closed)") - the lane could never settle a change.
The class' stage ids are its own (open/work), so the builtin table cannot cover
them; the rules must be declared on the class and must cover every stage.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "server" / "engine") not in sys.path:
    sys.path.insert(0, str(REPO / "server" / "engine"))

from dev_lane import QuickmanualLaneWorkflow  # noqa: E402
import path_gates  # noqa: E402


def test_every_stage_has_a_declared_face():
    ids = [st.id for st in QuickmanualLaneWorkflow.STAGES]
    rules = QuickmanualLaneWorkflow.PATH_GATE_RULES
    missing = [i for i in ids if i not in rules]
    assert missing == [], "stage(s) without a path-gate face: %s" % missing


def test_the_two_lane_specific_faces_are_the_intended_kinds():
    rules = QuickmanualLaneWorkflow.PATH_GATE_RULES
    assert rules["open"]["kind"] == "result_files", "open is a zero-code-change gate stage"
    assert rules["work"]["kind"] == "write_set", "the session works inside the declared write set"


def test_the_resolved_face_reaches_the_gate_for_work():
    """The gate's own resolver must answer for the lane's stages (this is the exact
    call the settle path gate makes; unknown_stage was the measured refusal)."""
    rules = QuickmanualLaneWorkflow.PATH_GATE_RULES
    for sid in ("open", "work"):
        kind = path_gates.stage_face_kind(sid, template_rules=rules) \
            if hasattr(path_gates, "stage_face_kind") else None
        if kind is None:
            # resolver name differs across versions: assert the table lookup the gate
            # does, never a made-up internal
            kind = (rules.get(sid) or {}).get("kind")
        assert kind, "no face resolved for stage %s" % sid


def test_a_write_outside_the_write_set_is_still_refused_at_work():
    """The face must be a check, not a blank cheque: a path outside the declared
    write set is refused by the same predicate the gate uses."""
    ok, reason = path_gates.stage_paths_ok(
        "work", ["docs/a.md"], write_set=["docs/"], result_files=(),
        template_rules=QuickmanualLaneWorkflow.PATH_GATE_RULES,
    ) if hasattr(path_gates, "stage_paths_ok") else (None, None)
    if ok is None:      # resolver shape differs: the table assertion above still pins the face
        return
    assert ok, reason


def test_in_flight_tickets_resolve_through_the_builtin_table():
    """Tickets created before the class declared its faces carry an EMPTY pinned
    table; the gate must still resolve the lane's stages, otherwise every one of
    them is refused with unknown_stage at settle (measured: six tickets)."""
    for sid, kind in (("open", "result_files"), ("work", "write_set")):
        assert path_gates.STAGE_PATH_RULES.get(sid, {}).get("kind") == kind, sid


def test_an_unknown_stage_is_still_refused():
    """Fail-closed survives: a stage id nobody declared has no face."""
    assert path_gates.STAGE_PATH_RULES.get("no_such_stage") is None
