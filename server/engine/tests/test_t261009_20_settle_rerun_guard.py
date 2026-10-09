"""t261009-20: the settle-rerun route change (7993697a / t261009-17) must be
history-aware. Both routing sites that read `settle_shape_needs_rerun` change
WHICH command the workflow schedules (rework / merge_check instead of the old
_blocked-for-a-human), so each must sit behind a `workflow.patched()` boolean
gate (SETTLE_RERUN_PATCH_ID). Without the gate, an in-flight history created
before the landing replays under code that schedules different commands ->
TMPRL1100 -> the wedged-workflow family (t261008-47).

L1 evidence only: AST source-discipline tests plus unit tests of the guarded
decision expression. No integration entry point (host order 260921).
"""

import ast
from pathlib import Path

import pytest

import dev_lane  # noqa: E402

DEV_LANE = Path(dev_lane.__file__)


def _module_ast():
    return ast.parse(DEV_LANE.read_text(encoding="utf-8"))


def _is_call_to(node: ast.AST, *names: str) -> bool:
    return (isinstance(node, ast.Call)
            and ast.unparse(node.func) in names)


def _settle_rerun_routing_ifs():
    """Every `if` whose test calls settle_shape_needs_rerun."""
    out = []
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.If) and any(
                _is_call_to(n, "settle_shape_needs_rerun")
                for n in ast.walk(node.test)):
            out.append(node)
    return out


def test_both_settle_rerun_sites_are_patch_gated():
    ifs = _settle_rerun_routing_ifs()
    assert len(ifs) == 2, "expected exactly the two t261009-17 routing sites"
    for node in ifs:
        unparsed = ast.unparse(node.test)
        assert "workflow.patched(SETTLE_RERUN_PATCH_ID)" in unparsed, (
            "settle-rerun routing site is not patch-gated: %s" % unparsed)


def test_guard_is_last_operand_of_the_and_chain():
    """Pure predicate and cap first, history read last — ordering is a comment
    contract (logs fire identically); assert it stays that way."""
    for node in _settle_rerun_routing_ifs():
        operands = [ast.unparse(v) for v in node.test.values]  # type: ignore[attr-defined]
        assert operands[-1] == "workflow.patched(SETTLE_RERUN_PATCH_ID)"


def test_patch_id_unique_in_module():
    ids = [n.value for n in ast.walk(_module_ast())
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and n.value.endswith("-v1") or
           (isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "patch" in n.value.lower())]
    # Direct source grep is the honest check: the literal must appear exactly
    # once as a definition and never collide with another *_PATCH_ID value.
    src = DEV_LANE.read_text(encoding="utf-8")
    assert src.count('SETTLE_RERUN_PATCH_ID = "') == 1
    assert src.count('"dev-lane-settle-rerun-v1"') == 1
    del ids  # grep-based assertions above are the contract


def test_routing_decision_itself_unchanged():
    """The guarded expression must keep its original three operands — the gate
    adds history-awareness, it must not rename or drop the routing facts."""
    for node in _settle_rerun_routing_ifs():
        unparsed = ast.unparse(node.test)
        assert "not sres.ok" in unparsed
        assert "settle_shape_needs_rerun(sres.error)" in unparsed
        assert "self._conflict_rounds < MAX_CONFLICT_ROUNDS" in unparsed


class _Sres:
    def __init__(self, ok, error):
        self.ok = ok
        self.error = error


def _guarded_decision(sres, rounds, patched_value):
    """Byte-for-byte the expression both sites now evaluate."""
    return (not sres.ok
            and dev_lane.settle_shape_needs_rerun(sres.error)
            and rounds < dev_lane.MAX_CONFLICT_ROUNDS
            and patched_value)


NO_HUMAN_INFO = ("measured: no merge in progress (MERGE_HEAD does not exist); "
                 "unmerged entries: 0; dirty files: 0; marker residue: none")


def test_pre_guard_history_takes_old_path_verbatim():
    """patched()=False (marker absent from a pre-guard history) -> the new
    branch is NOT taken -> the old blocked commands replay exactly."""
    assert _guarded_decision(_Sres(False, NO_HUMAN_INFO), 0, False) is False


def test_post_guard_history_takes_rerun_path():
    assert _guarded_decision(_Sres(False, NO_HUMAN_INFO), 0, True) is True


def test_guard_cannot_resurrect_a_green_settle():
    assert _guarded_decision(_Sres(True, ""), 0, True) is False


@pytest.mark.parametrize("bad", [None, "", "  ",
                                 "dirty files: -1",
                                 "unmerged entries: 0 but dirty files: 2",
                                 "unmerged entries: 0; dirty files: 0",
                                 "unmerged entries: 3; dirty files: 0; "
                                 "marker residue: none"])
def test_malformed_and_human_actionable_errors_stay_on_old_path(bad):
    """Malformed / human-actionable settle payloads: the predicate must be
    False (fail-closed onto the old blocked path) whatever the marker is."""
    assert dev_lane.settle_shape_needs_rerun(bad) is False
    assert _guarded_decision(_Sres(False, bad), 0, True) is False


def test_cap_short_circuits_before_the_guard():
    assert _guarded_decision(_Sres(False, NO_HUMAN_INFO),
                             dev_lane.MAX_CONFLICT_ROUNDS, True) is False
