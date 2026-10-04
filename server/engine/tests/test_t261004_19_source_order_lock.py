"""t261004-19 source-order lock — the epic assignment in cmd_ticket_start must
precede the executor gate's consumption of the epic.

Defect class (arbitrate gen1 code-fault): the gate call
`await _executor_open_epic_count(project, epic)` was once placed before the
epic-linkage assignment block, so any ticket-start without --epic died with an
UnboundLocalError before the gate could produce its named refusal (the named
refusal face was displaced by an internal crash; three integration scenarios
went red). This lock pins "epic is assigned first, consumed after" as a
mechanical truth (source-order comparison, same discipline as the t260901-25
source locks); fail-closed: if either anchor cannot be extracted that is a
reported line, never a silent pass.
"""
import pathlib
import re

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client.py"


def _line_of(src, pattern):
    m = re.search(pattern, src)
    return m.start() if m else None


def test_epic_assigned_before_executor_gate_consumes_it():
    src = CLIENT.read_text(encoding="utf-8")
    # Only the cmd_ticket_start body (from its header to the next top-level async def).
    start = _line_of(src, r"async def cmd_ticket_start")
    assert start is not None, "cmd_ticket_start not found (fail-closed)"
    nxt = re.search(r"\nasync def |\n\ndef ", src[start + 10:])
    body = src[start: start + 10 + (nxt.start() if nxt else len(src))]
    assign = _line_of(body, r"epic = validate_epic_code\(")
    consume = _line_of(body, r"await _executor_open_epic_count\(project, epic\)")
    assert assign is not None, "epic-linkage assignment anchor not extractable (fail-closed)"
    assert consume is not None, "executor gate epic-consumption anchor not extractable (fail-closed)"
    assert assign < consume, (
        "cmd_ticket_start order drift: epic is assigned AFTER the executor gate "
        "consumes it — any ticket-start without --epic crashes with UnboundLocalError "
        "instead of the named refusal (t261004-19 arbitrate gen1 code-fault)")


def test_epic_validation_keeps_single_assignment_in_start_body():
    src = CLIENT.read_text(encoding="utf-8")
    start = _line_of(src, r"async def cmd_ticket_start")
    nxt = re.search(r"\nasync def |\n\ndef ", src[start + 10:])
    body = src[start: start + 10 + (nxt.start() if nxt else len(src))]
    hits = re.findall(r"^\s*epic = validate_epic_code\(", body, re.M)
    assert len(hits) == 1, "epic-linkage strict validation must stay the single assignment point"
