"""t261028-56 L1: one gate-row rule for the engine's merge_check faces.

Defect (t261028-46/-48 family): the engine writes gate receipts in TWO shapes —
script gates `{check, level: 'green'|'red', count}` and agent/human gates
`{item, by, done, green}` — but the merge_check faces counted reds with
`not c.get("green")`, so every GREEN script row was counted as a red. The count
then contradicted the console face (which reads both shapes).

Fix: `gate_row_field_verdict` / `gate_row_verdict` / `gate_row_name` /
`gate_row_reds` in dev_lane.py (mirrors of the console's `receiptBool` /
`receiptRowView`), used by both merge_check faces (dev lane + quickmanual lane),
by the red texts, by the blocked_detail face and by the quiet-baseline coverage
predicate. The client/engine agreement fixture (same rows through both sides)
lives in server/plugins/workbench/tests/t261028-56-verdict-readers.mjs.

Run: server/engine/.venv/bin/python -m pytest \
      server/engine/tests/test_t261028_56_gate_row_shapes.py -q
"""
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane as dl  # noqa: E402

# Real receipt shapes (verbatim keys, measured on live ticket faces).
SCRIPT_GREEN_ROW = {"check": "write-set whitelist", "level": "green", "count": 0}
SCRIPT_RED_ROW = {"check": "lint", "level": "red", "count": 2, "note": "two files"}
AGENT_GREEN_ROW = {"item": "Lane branch has commits", "green": True, "id": "lane_commits"}
AGENT_RED_ROW = {"item": "Worktree is clean", "green": False, "id": "clean",
                 "detail": "dirty files: 2"}

# The agreement fixture is shared with the node battery (same rows, same file
# footer): do not edit one side alone.
AGREEMENT_ROWS = [
    {"check": "write-set whitelist", "level": "green", "count": 0},
    {"check": "lint", "level": "red", "count": 2, "note": "two files touched"},
    {"item": "Lane branch has commits", "green": True, "id": "lane_commits"},
    {"item": "Worktree is clean", "green": False, "id": "clean", "detail": "dirty files: 2"},
    {"id": "id_only_green", "green": True},
    {"item": "no verdict field at all"},
    {"verdict": "green", "item": "run-style wording on a row"},
    {"item": "conflicting", "green": False, "level": "green"},
    "bare scalar row",
    None,
    7,
    True,
]


def test_field_verdict_reads_booleans_and_the_two_gate_words():
    assert dl.gate_row_field_verdict(True) is True
    assert dl.gate_row_field_verdict(False) is False
    assert dl.gate_row_field_verdict("green") is True
    assert dl.gate_row_field_verdict(" GREEN ") is True
    assert dl.gate_row_field_verdict("red") is False
    # Malformed three-state: missing / unknown word / wrong type invent nothing.
    for bad in (None, "maybe", "", 0, 1, [], {}, ["green"]):
        assert dl.gate_row_field_verdict(bad) is None, bad


def test_row_verdict_reads_both_shapes():
    assert dl.gate_row_verdict(SCRIPT_GREEN_ROW) is True
    assert dl.gate_row_verdict(SCRIPT_RED_ROW) is False
    assert dl.gate_row_verdict(AGENT_GREEN_ROW) is True
    assert dl.gate_row_verdict(AGENT_RED_ROW) is False
    # Field order: green -> level -> verdict -> done.
    assert dl.gate_row_verdict({"verdict": "green"}) is True
    assert dl.gate_row_verdict({"done": True}) is True
    # Conflicting signals resolve red: a reader never upgrades a row.
    assert dl.gate_row_verdict({"green": False, "level": "green"}) is False
    assert dl.gate_row_verdict({"green": True, "level": "red"}) is False
    # No signal -> None (the row is shown red, never invented green).
    assert dl.gate_row_verdict({"item": "no verdict field"}) is None
    assert dl.gate_row_verdict({}) is None
    assert dl.gate_row_verdict("x") is None
    assert dl.gate_row_verdict(None) is None


def test_row_name_reads_item_then_check_then_id():
    assert dl.gate_row_name(AGENT_RED_ROW) == "Worktree is clean"
    assert dl.gate_row_name(SCRIPT_RED_ROW) == "lint"
    assert dl.gate_row_name({"id": "id_only_green", "green": True}) == "id_only_green"
    assert dl.gate_row_name({"item": "named", "check": "also", "id": "id"}) == "named"
    assert dl.gate_row_name("bare scalar row") == "bare scalar row"
    assert dl.gate_row_name({}) == ""
    assert dl.gate_row_name(None) == ""
    # A green row with no identity and no payload names nothing.
    assert dl.gate_row_name({"green": True}) == ""


def test_red_set_reads_both_shapes_and_the_retired_predicate_did_not():
    """The anti-proof: the shipped predicate counted every green script row."""
    checks = [SCRIPT_GREEN_ROW, SCRIPT_RED_ROW, AGENT_GREEN_ROW, AGENT_RED_ROW]
    old = [c for c in checks if not c.get("green")]
    new = dl.gate_row_reds(checks)
    assert len(old) == 3, "the retired predicate counts 3 reds (2 of them green script rows)"
    assert new == [SCRIPT_RED_ROW, AGENT_RED_ROW], new
    assert len(new) == 1 + 1


def test_red_set_keeps_unproven_scalar_and_malformed_rows_visible():
    checks = ["bare scalar row", None, 7, True, {}, [], {"level": "weird"}, {"green": True},
              {"green": "red"}]
    reds = dl.gate_row_reds(checks)
    # Shown red: the scalar, the number, the json array, the unnamed row with no
    # verdict, the unknown verdict word, the explicit red word. Dropped: null,
    # a bare boolean, and the green row.
    assert "bare scalar row" in reds and 7 in reds and [] in reds
    assert {} in reds and {"level": "weird"} in reds and {"green": "red"} in reds
    assert None not in reds and True not in reds and {"green": True} not in reds
    assert len(reds) == 6


def test_red_set_malformed_container_is_not_a_row_source():
    assert dl.gate_row_reds(None) == []
    assert dl.gate_row_reds("no") == []
    assert dl.gate_row_reds({}) == []


def test_agreement_fixture_is_the_pinned_twin():
    """Pinned values: the node battery feeds the SAME rows through the console
    reader and asserts equal red count / per-row verdict / per-row name."""
    assert len(dl.gate_row_reds(AGREEMENT_ROWS)) == 6
    verdicts = [dl.gate_row_verdict(r) for r in AGREEMENT_ROWS]
    assert verdicts == [True, False, True, False, True, None, True, False,
                        None, None, None, None]
    names = [dl.gate_row_name(r) for r in AGREEMENT_ROWS]
    assert names == ["write-set whitelist", "lint", "Lane branch has commits", "Worktree is clean",
                     "id_only_green", "no verdict field at all", "run-style wording on a row",
                     "conflicting", "bare scalar row", "", "7", ""]


def test_quiet_baseline_coverage_judges_the_shared_red_set():
    """Routing direction: a GREEN script row is not an uncovered red, so it may
    not by itself keep a covered round from proceeding (the older predicate
    failed closed on it forever). A real red still needs its quiet verdicts."""
    covered = dict(AGENT_RED_ROW)
    covered["quiet_verdicts"] = [{"green": True, "name": "flake"}]
    assert dl.quiet_baseline_covered([SCRIPT_GREEN_ROW, covered]) is True
    assert dl.quiet_baseline_covered([SCRIPT_GREEN_ROW]) is False
    assert dl.quiet_baseline_covered([SCRIPT_GREEN_ROW, AGENT_RED_ROW]) is False
    assert dl.quiet_baseline_covered([SCRIPT_GREEN_ROW, SCRIPT_RED_ROW]) is False
    # Unchanged for the agent-only face the engine produces today.
    assert dl.quiet_baseline_covered([AGENT_GREEN_ROW, covered]) is True
    assert dl.quiet_baseline_covered([AGENT_GREEN_ROW, AGENT_RED_ROW]) is False


def test_both_merge_check_faces_count_through_the_shared_rule():
    """Source lock: the two gate_runs writers (dev lane + quickmanual lane) may
    not re-derive the count with their own predicate (t261028-56)."""
    src = (POC / "dev_lane.py").read_text("utf-8")
    assert src.count('"red_count": len(gate_row_reds(mc.checks))') == 2
    assert 'len([c for c in mc.checks if not c.get("green")])' not in src
    assert 'for c in mc.checks if not c.get("green")' not in src
    assert src.count("def gate_row_verdict(") == 1
    assert src.count("def gate_row_reds(") == 1
    assert src.count("def gate_row_name(") == 1
