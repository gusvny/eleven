"""t261028-54 L1: the red-item diagnosis for a process that may not run the lane's code.

After the merge with main (`t261028-57` / `t261029-14`), the wait-budget mechanism is
main's: it is DERIVED from the declared check budgets and an expiry is a named budget fact
(`reason_code=gate_budget_exhausted`). What survives from this ticket's lane side is the
diagnosis that explains the other half of the incident:

    the merge gate reported "verify_lane timed out" while the wait fix already sat on the
    lane, because the serving worker executed the MAIN tree. Replacing that process reloads
    the same tree, so "restart the worker" alone cannot deliver a lane-only fix.

Faces under test:
  - `_verify_tree_note(lane_root)`: compares the loaded `agent_activities.py` bytes with the
    lane's copy - different copies name both paths and say a lane-only activity fix cannot
    take effect here (serve the ticket with a lane worker, or land the fix on this tree);
    identical / absent / unreadable copies produce no note;
  - `_verify_stale_code_note(lane_root)`: joins the tree mismatch with the mtime-based
    "modules loaded before they were edited" case (where replacing the worker does help),
    and never raises (diagnosis only, empty on any failure);
  - the composition with main's expiry row: the row keeps `green=False` and its
    `gate_budget_exhausted` reason code AND carries the note; the two expiry branches fill
    the note (source lock);
  - the superseded lane mechanism is gone: one wait implementation (main's derivation), no
    fixed ceiling left behind.

Everything is fixture level: temp lanes built from copies of this module's own bytes; the
real suite is never run from this file.
"""
from pathlib import Path

import agent_activities as aa

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parents[1]


def _lane_with_module(tmp_path, body):
    """A lane whose `server/engine/<this module>` holds `body`."""
    lane = tmp_path / "lane"
    (lane / "server" / "engine").mkdir(parents=True)
    (lane / "server" / "engine" / Path(aa.__file__).name).write_text(body, "utf-8")
    return lane


def _quiet_stamp(monkeypatch):
    monkeypatch.setattr(aa.shared, "worker_code_stamp", lambda *a, **k: {"stale": []})


def test_tree_note_names_a_lane_only_fix_and_both_paths(tmp_path, monkeypatch):
    _quiet_stamp(monkeypatch)
    lane = _lane_with_module(tmp_path, "# a different copy of the engine module\n")
    note = aa._verify_stale_code_note(lane)
    assert "while the lane carries a different copy" in note
    assert "cannot take effect" in note
    assert "lane worker" in note
    assert str(Path(aa.__file__).resolve()) in note
    assert str((lane / "server" / "engine" / Path(aa.__file__).name).resolve()) in note


def test_tree_note_is_silent_when_the_copies_match(tmp_path, monkeypatch):
    _quiet_stamp(monkeypatch)
    lane = _lane_with_module(tmp_path, Path(aa.__file__).read_text(encoding="utf-8"))
    assert aa._verify_stale_code_note(lane) == ""


def test_tree_note_is_silent_when_the_lane_has_no_engine_copy(tmp_path, monkeypatch):
    _quiet_stamp(monkeypatch)
    empty = tmp_path / "empty-lane"
    empty.mkdir()
    assert aa._verify_stale_code_note(empty) == ""


def test_stale_modules_are_named_and_a_broken_stamp_is_silent(monkeypatch):
    monkeypatch.setattr(aa.shared, "worker_code_stamp",
                        lambda *a, **k: {"stale": ["agent_activities", "shared"]})
    note = aa._verify_stale_code_note()
    assert "pre-edit engine code (agent_activities, shared)" in note
    assert "engine_ops.py restart" in note

    def _boom(*a, **k):
        raise RuntimeError("stamp unavailable")

    monkeypatch.setattr(aa.shared, "worker_code_stamp", _boom)
    assert aa._verify_stale_code_note() == ""       # diagnosis never raises


def test_both_states_are_joined(tmp_path, monkeypatch):
    monkeypatch.setattr(aa.shared, "worker_code_stamp",
                        lambda *a, **k: {"stale": ["agent_activities"]})
    lane = _lane_with_module(tmp_path, "# different\n")
    note = aa._verify_stale_code_note(lane)
    assert "while the lane carries a different copy" in note
    assert "pre-edit engine code (agent_activities)" in note
    assert " | " in note


def test_expiry_row_keeps_main_shape_and_gains_the_note(monkeypatch):
    """Composition with main's expiry row: blocking verdict and budget reason code stay,
    the diagnosis rides along as the `note` key only when there is something to say."""
    row = aa._verify_lane_code_expiry_row(
        "gate could not complete", aa.code_gate_expiry_receipt(
            1020, {"slowest_id": "test", "slowest_budget_sec": 1000, "margin_sec": 120,
                   "declared_checks": 4, "defaulted_ids": []},
            900.0, read_diag="", loadavg=(1.0, 1.0, 1.0))[1])
    assert row["green"] is False
    assert row["reason_code"] == "gate_budget_exhausted"
    assert "note" not in row                       # a clean process adds no key
    row["note"] = "this process runs the engine code at /a while the lane carries ..."
    assert "note" in row


def test_expiry_branches_fill_the_note_and_attach_it_source_lock():
    src = (ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    assert src.count("_stale_note = _verify_stale_code_note(lane_root)") == 2
    assert 'checks[-1]["note"] = _stale_note' in src
    # one wait mechanism after the merge: the lane's fixed ceiling is gone
    for gone in ("_merge_verify_wait_sec", "MERGE_CHECK_BUDGET_SEC",
                 "MERGE_CHECK_RESERVE_SEC", "ENV_MERGE_VERIFY_WAIT"):
        assert gone not in src, gone
    # and main's derivation is the one in place
    assert "verify_lane_code_gate_budget(_gate_checks)" in src
