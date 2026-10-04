#!/usr/bin/env python3
"""t261004-25 ticket-test-face carve-out unit tests (L1).

Three faces under test (an out-of-write-set lawful deliverable must have a
defined, visible, recoverable path to land):
  1. the path_gates.is_ticket_test_face predicate + judge_stage_paths wiring on
     three kinds (every pass named);
  2. agent_activities._recover_quarantined_test_face (malformed inputs skip
     named, never silent);
  3. the verify_lane write-set whitelist fallback (_ws_refuse single point,
     _code on both judge sources, green note).

No network / real Temporal in UT; git is used only inside tmp repos to build
diff fixtures (zero fetch/push).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_gates as pg  # noqa: E402

HERE = Path(__file__).resolve().parent


# ---------------- 1. predicate ----------------

def test_predicate_match_engine_test():
    assert pg.is_ticket_test_face(
        "server/engine/tests/test_t261004_25_gate.py", "t261004-25")


def test_predicate_match_integration_face():
    assert pg.is_ticket_test_face(
        "integration/t261004-25/test_t261004_25_x.py", "t261004-25")


def test_predicate_other_ticket_not_mine():
    assert not pg.is_ticket_test_face(
        "server/engine/tests/test_t261004_26_x.py", "t261004-25")


def test_predicate_slug_dash_matches_underscore():
    assert pg.is_ticket_test_face(
        "server/engine/tests/test_t261004_19_open_ticket_gate.py", "t261004-19")


@pytest.mark.parametrize("tid", ["", None, "a/b", "x\\y", "  "])
def test_predicate_malformed_ticket_id_false(tid):
    assert not pg.is_ticket_test_face(
        "server/engine/tests/test_t261004_25_x.py", tid)


@pytest.mark.parametrize("p", [
    "server/engine/tests/helper_t261004_25.py",     # no test_ prefix
    "server/engine/tests/test_t261004_25_x.mjs",    # not .py
    "server/engine/tests/test_other.py",            # no slug
    "server/engine/test_t261004_25_x.py",           # no tests/ segment, not under integration/
    "server/tests/test_t261004_25_x.py",            # has a tests segment: True (control for the negatives)
])
def test_predicate_name_and_face_bounds(p):
    if p == "server/tests/test_t261004_25_x.py":
        assert pg.is_ticket_test_face(p, "t261004-25")
    else:
        assert not pg.is_ticket_test_face(p, "t261004-25")


@pytest.mark.parametrize("p", [
    "../evil/test_t261004_25_x.py",
    "/abs/test_t261004_25_x.py",
    "a/../test_t261004_25_x.py",
])
def test_predicate_unsafe_path_false(p):
    assert not pg.is_ticket_test_face(p, "t261004-25")


def test_predicate_normalizes_equivalent_spellings():
    # Equivalent spellings neither bypass nor get misjudged: same verdict after
    # normalization.
    assert pg.is_ticket_test_face(
        "./server/engine/tests//test_t261004_25_x.py", "t261004-25")


# ---------------- 1. judge_stage_paths wiring ----------------

WS = ["server/engine/executor_grants.py"]


def test_judge_implement_carves_ticket_test_and_names_it():
    notes = []
    ok, viol, reason = pg.judge_stage_paths(
        "implement", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="t261004-25", notes_out=notes)
    assert ok and viol == [] and reason == ""
    assert notes == ["%s: server/engine/tests/test_t261004_25_gate.py"
                     % pg.TICKET_TEST_FACE_NOTE]


def test_judge_implement_still_refuses_other_out_of_set():
    ok, viol, reason = pg.judge_stage_paths(
        "implement", ["server/engine/evil.py"],
        write_set=WS, ticket_id="t261004-25")
    assert not ok and viol == ["server/engine/evil.py"] and reason == "unauthorized_path"


def test_judge_carve_applies_even_with_empty_write_set():
    # Missing/empty write set: the ticket test face is still lawful (invariant 3),
    # every other file stays write_set_missing.
    ok, viol, reason = pg.judge_stage_paths(
        "implement", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=[], ticket_id="t261004-25")
    assert ok and reason == ""


def test_judge_join_kind_carves():
    ok, viol, reason = pg.judge_stage_paths(
        "integ_join", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="t261004-25")
    assert ok


def test_judge_self_heal_kind_carves():
    ok, viol, reason = pg.judge_stage_paths(
        "merge_check", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="t261004-25")
    assert ok


def test_judge_carve_not_on_result_files_kind():
    # The result_files kind (create_plan and other zero-code stages) does not
    # widen: a test-face file is still refused there.
    ok, viol, reason = pg.judge_stage_paths(
        "create_plan", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="t261004-25")
    assert not ok and reason == "unauthorized_path"


def test_judge_old_ticket_zero_behavior_change():
    # No ticket_id (old tickets): predicate always False, byte-identical old
    # behavior.
    ok, viol, reason = pg.judge_stage_paths(
        "implement", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="")
    assert not ok and reason == "unauthorized_path"


def test_judge_unknown_stage_still_fail_closed():
    ok, viol, reason = pg.judge_stage_paths(
        "no_such_stage", ["server/engine/tests/test_t261004_25_gate.py"],
        write_set=WS, ticket_id="t261004-25")
    assert not ok and reason == "unknown_stage"


def test_judge_carve_note_not_duplicated():
    notes = []
    pg.judge_stage_paths("implement",
                         ["server/engine/tests/test_t261004_25_gate.py",
                          "server/engine/evil.py"],
                         write_set=WS, ticket_id="t261004-25", notes_out=notes)
    assert notes.count("%s: server/engine/tests/test_t261004_25_gate.py"
                       % pg.TICKET_TEST_FACE_NOTE) == 1


# ---------------- 2. quarantine recovery ----------------

AA = None


def _aa():
    global AA
    if AA is None:
        import agent_activities as aa  # reachable only where the engine venv has temporalio
        AA = aa
    return AA


def _mk_quarantine(cwd, batch, item, archive_bytes=b"def test_x():\n    pass\n"):
    bdir = cwd / ".sandbar" / "quarantine" / batch
    bdir.mkdir(parents=True, exist_ok=True)
    if archive_bytes is not None:
        arch = cwd / item.get("archive")
        arch.parent.mkdir(parents=True, exist_ok=True)
        arch.write_bytes(archive_bytes)
    (bdir / "manifest.json").write_text(
        json.dumps({"ticket_stage": "implement", "gen": 0, "ts": 1,
                    "items": [item]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return bdir / "manifest.json"


TEST_F = "server/engine/tests/test_t261004_18_grants_write_entry.py"


def test_recovery_restores_and_marks_manifest(tmp_path):
    mf = _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": TEST_F, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + TEST_F, "ts": 1})
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert (tmp_path / TEST_F).is_file()
    m = json.loads(mf.read_text(encoding="utf-8"))
    assert m["items"][0]["recovered"] is True and m["items"][0]["recovered_ts"] > 0
    assert any(n.startswith("recovered:") and TEST_F in n for n in notes)
    assert not (tmp_path / ".sandbar/quarantine/unauth-implement-gen0" / TEST_F).exists()


def test_recovery_idempotent(tmp_path):
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": TEST_F, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + TEST_F, "ts": 1})
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert len(notes) == 1  # second round already recovered: zero action, zero new note


def test_recovery_missing_archive_named_skip(tmp_path):
    mf = _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": TEST_F, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + TEST_F, "ts": 1},
        archive_bytes=None)
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert not (tmp_path / TEST_F).exists()
    assert any("archived file missing" in n for n in notes)
    assert "recovered" not in json.loads(mf.read_text(encoding="utf-8"))["items"][0]


def test_recovery_malformed_manifest_named_skip(tmp_path):
    bdir = tmp_path / ".sandbar" / "quarantine" / "unauth-implement-gen0"
    bdir.mkdir(parents=True)
    (bdir / "manifest.json").write_text("{not json", encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert any("manifest unreadable" in n for n in notes)


def test_recovery_manifest_without_items_named_skip(tmp_path):
    bdir = tmp_path / ".sandbar" / "quarantine" / "unauth-implement-gen0"
    bdir.mkdir(parents=True)
    (bdir / "manifest.json").write_text('{"ticket_stage": "implement"}', encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert any("no items list" in n for n in notes)


def test_recovery_reverted_items_untouched(tmp_path):
    p = "server/engine/lib_x.py"
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": p, "xy": " M", "action": "reverted",
        "diff": "server__engine__lib_x.py.diff", "ts": 1}, archive_bytes=None)
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert not (tmp_path / p).exists()  # reverted items untouched (restore is a human-review face)


def test_recovery_directory_archive_named_skip(tmp_path):
    # Original path is a test-face .py but the archive site is a directory (odd
    # quarantine shape) - never moved automatically, left human.
    f = "server/engine/tests/test_t261004_18_x.py"
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": f, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + f, "ts": 1},
        archive_bytes=None)
    (tmp_path / ".sandbar/quarantine/unauth-implement-gen0" / f).mkdir(
        parents=True, exist_ok=True)
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert any("archive is a directory" in n for n in notes)
    assert not (tmp_path / f).exists()


def test_recovery_other_ticket_file_untouched(tmp_path):
    p = "server/engine/tests/test_t261004_99_other.py"
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": p, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + p, "ts": 1})
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert not (tmp_path / p).exists() and notes == []


def test_recovery_empty_ticket_id_noop(tmp_path):
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": TEST_F, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + TEST_F, "ts": 1})
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "", notes)
    assert not (tmp_path / TEST_F).exists() and notes == []


def test_recovery_occupied_target_named_skip(tmp_path):
    dst = tmp_path / TEST_F
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"occupied")
    _mk_quarantine(tmp_path, "unauth-implement-gen0", {
        "path": TEST_F, "xy": "??", "action": "moved",
        "archive": ".sandbar/quarantine/unauth-implement-gen0/" + TEST_F, "ts": 1})
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert dst.read_bytes() == b"occupied"
    assert any("original path occupied" in n for n in notes)


def test_recovery_no_quarantine_dir_noop(tmp_path):
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-18", notes)
    assert notes == []


# ---------------- 3. verify_lane write-set fallback ----------------

def _ws_check(checks):
    """Select the write-set whitelist record by its stable ASCII machine key
    (verify_lane.WS_CHECK_ID) - never by the display name (L15 send-back round 2:
    tests must not depend on copy). Fails loudly if the key is missing, so the
    selector cannot rot silently."""
    hits = [c for c in checks if c.get("id") == _vl().WS_CHECK_ID]
    assert hits, "write-set check record lost its machine key: %r" % (checks,)
    return hits[0]


def _vl():
    sys.path.insert(0, str(HERE.parent.parent / "tools"))
    import verify_lane as vl
    return vl


def test_ws_refuse_single_point():
    vl = _vl()
    assert vl._ws_refuse("server/engine/evil.py", [], "t261004-25") == (True, False)
    assert vl._ws_refuse("server/engine/tests/test_t261004_25_x.py", [],
                         "t261004-25") == (False, True)
    assert vl._ws_refuse("server/engine/tests/test_t261004_25_x.py", [],
                         "") == (True, False)  # no ticket id: fail-closed


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, check=True)


@pytest.fixture
def lane_repo(tmp_path):
    """tmp lane repo fixture: first commit = base (verify.yaml); second commit adds
    an own-ticket test-face file and an out-of-set non-test file (both judgeable on
    the diff base...HEAD)."""
    root = tmp_path / "lane"
    (root / "server/engine/tests").mkdir(parents=True)
    (root / "server").mkdir(exist_ok=True)
    _git(["init", "-q", "."], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "t"], root)
    (root / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n", encoding="utf-8")
    _git(["add", "verify.yaml"], root)
    _git(["commit", "-qm", "base"], root)
    base = _git(["rev-parse", "HEAD"], root).stdout.strip()
    (root / "server/engine/tests/test_t261004_25_x.py").write_text("def t():\n    pass\n")
    (root / "server/engine/evil.py").write_text("EVIL = 1\n")
    _git(["add", "-A"], root)
    _git(["commit", "-qm", "work"], root)
    return root, base


def test_code_write_allow_branch_carves_and_names(lane_repo):
    # The fixture diff holds two files: the own-ticket test face (admitted + named
    # note) and the out-of-set evil.py (still red, named).
    root, base = lane_repo
    vl = _vl()
    checks = vl._code({"path": str(root), "base": base, "ticket_id": "t261004-25"})
    ws = _ws_check(checks)
    assert ws["level"] == "red"  # evil.py still red (the pass covers only the own-ticket test face)
    assert any("evil.py" in it.get("detail", "") for it in ws["items"])
    assert "test_t261004_25_x.py" in ws["note"]  # the pass is named on the green note, not in red items


def test_code_write_allow_branch_still_reds_non_test(lane_repo):
    root, base = lane_repo
    vl = _vl()
    checks = vl._code({"path": str(root), "base": base, "ticket_id": "t261004-25"})
    ws = _ws_check(checks)
    assert ws["level"] == "red"
    assert any("evil.py" in it.get("detail", "") for it in ws["items"])


def test_code_ticket_write_set_branch_carves_too(lane_repo):
    # Review comment 2: the ticket write_set branch applies equally (single
    # decision point).
    root, base = lane_repo
    vl = _vl()
    checks = vl._code({"path": str(root), "base": base,
                       "ticket_id": "t261004-25",
                       "write_set": ["server/engine/executor_grants.py"]})
    ws = _ws_check(checks)
    assert ws["level"] == "red"  # evil.py still red (precise write-set judge)
    assert "test_t261004_25_x.py" in ws["note"]  # test-face file admitted and named (green note)


def test_code_no_ticket_id_byte_identical_old_behavior(lane_repo):
    root, base = lane_repo
    vl = _vl()
    checks = vl._code({"path": str(root), "base": base})
    ws = _ws_check(checks)
    assert ws["level"] == "red"
    assert "note" not in ws  # no ticket id: zero new behavior, zero new note
