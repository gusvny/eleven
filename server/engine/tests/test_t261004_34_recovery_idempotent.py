#!/usr/bin/env python3
"""t261004-34 (-0004) quarantine-recovery IDEMPOTENCE unit battery (L1).

The t261004-25 recovery marked only the manifest item of the batch it consumed,
so a path quarantined N times (t261004-18: five batches) came back from the next
unmarked batch on every settle — a deliberate removal was impossible (observed
restore -> delete -> restore on that ticket). This battery pins the two closing
mechanisms in agent_activities._recover_quarantined_test_face:
  - mark the same path recovered=true across ALL historical batches;
  - a processed-path ledger (.sandbar/quarantine/recovered-paths.json) that
    treats an intentional removal as explicit intent: a ledgered path is never
    auto-restored again.
Plus the mandatory malformed-input faces (junk ledger, junk manifest, junk item
shapes). Run: python3 -m pytest server/engine/tests/test_t261004_34_recovery_idempotent.py -q
(unit run, not an integration entry).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AA = None


def _aa():
    global AA
    if AA is None:
        import agent_activities as aa  # reachable only where the engine venv has temporalio
        AA = aa
    return AA


TEST_F = "server/engine/tests/test_t261004_34_grants_write_entry.py"
LEDGER = ".sandbar/quarantine/recovered-paths.json"


def _mk_batch(cwd, batch, item, archive_bytes=b"def test_x():\n    pass\n"):
    bdir = cwd / ".sandbar" / "quarantine" / batch
    bdir.mkdir(parents=True, exist_ok=True)
    if archive_bytes is not None:
        arch = cwd / item["archive"]
        arch.parent.mkdir(parents=True, exist_ok=True)
        arch.write_bytes(archive_bytes)
    (bdir / "manifest.json").write_text(
        json.dumps({"ticket_stage": "implement", "gen": 0, "ts": 1,
                    "items": [item]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return bdir / "manifest.json"


def _item(batch, f=TEST_F, **over):
    it = {"path": f, "xy": "??", "action": "moved",
          "archive": ".sandbar/quarantine/%s/%s" % (batch, f), "ts": 1}
    it.update(over)
    return it


def _manifests(cwd):
    return sorted((cwd / ".sandbar" / "quarantine").glob("unauth-*/manifest.json"))


def test_two_batches_one_settle_restores_once_marks_both(tmp_path):
    b1, b2 = "unauth-implement-gen0", "unauth-implement-gen1"
    mf1 = _mk_batch(tmp_path, b1, _item(b1))
    mf2 = _mk_batch(tmp_path, b2, _item(b2))
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert (tmp_path / TEST_F).is_file()
    assert sum(n.startswith("recovered:") for n in notes) == 1
    # BOTH historical batches are marked, not only the consumed one
    for mf in (mf1, mf2):
        it = json.loads(mf.read_text(encoding="utf-8"))["items"][0]
        assert it["recovered"] is True and it["recovered_ts"] > 0, mf
    # and the ledger holds the path
    led = json.loads((tmp_path / LEDGER).read_text(encoding="utf-8"))
    assert TEST_F in led["paths"]


def test_second_settle_restores_nothing_again(tmp_path):
    b1, b2 = "unauth-implement-gen0", "unauth-implement-gen1"
    _mk_batch(tmp_path, b1, _item(b1))
    _mk_batch(tmp_path, b2, _item(b2))
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    n1 = len(notes)
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    # second settle: zero re-restore; the only new lines are the named
    # processed-path skips (one per historical batch — visible, not silent)
    skips = [n for n in notes[n1:] if n.startswith(
        "recovery skip (path already in processed-path ledger")]
    assert len(skips) == 2
    assert all(TEST_F in n for n in skips)
    assert not any(n.startswith("recovered:") for n in notes[n1:])
    assert (tmp_path / TEST_F).is_file()


def test_deliberate_removal_is_respected(tmp_path):
    b1, b2 = "unauth-implement-gen0", "unauth-implement-gen1"
    _mk_batch(tmp_path, b1, _item(b1))
    _mk_batch(tmp_path, b2, _item(b2))
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert (tmp_path / TEST_F).is_file()
    # the lane deliberately deletes the restored file
    (tmp_path / TEST_F).unlink()
    notes.clear()
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    # NOT resurrected; all batches stay consumed (zero re-restore, zero new
    # recovery note — the t261004-25 quiet-idempotence pin stays intact; the
    # ledger is the authority here and the NAMED skip face is pinned by
    # test_ledger_blocks_even_when_marks_are_lost)
    assert not (tmp_path / TEST_F).exists()
    assert not any(n.startswith("recovered:") for n in notes)
    led = json.loads((tmp_path / LEDGER).read_text(encoding="utf-8"))
    assert TEST_F in led["paths"]


def test_ledger_blocks_even_when_marks_are_lost(tmp_path):
    # the ledger, not the manifest marks, is the authority
    _mk_batch(tmp_path, "unauth-implement-gen0", _item("unauth-implement-gen0"))
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    (tmp_path / TEST_F).unlink()
    # an attacker/lane rewrite drops the recovered marks but keeps the archive
    mf = _manifests(tmp_path)[0]
    m = json.loads(mf.read_text(encoding="utf-8"))
    m["items"][0].pop("recovered", None)
    m["items"][0].pop("recovered_ts", None)
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    notes.clear()
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert not (tmp_path / TEST_F).exists()
    assert any("processed-path" in n for n in notes)


def test_malformed_ledger_holds_back_whole_recovery(tmp_path):
    _mk_batch(tmp_path, "unauth-implement-gen0", _item("unauth-implement-gen0"))
    lp = tmp_path / LEDGER
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("{not json", encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    # fail toward do-not-restore, and the skip is named
    assert not (tmp_path / TEST_F).exists()
    assert any("ledger unreadable" in n for n in notes)


def test_ledger_without_paths_object_holds_back(tmp_path):
    _mk_batch(tmp_path, "unauth-implement-gen0", _item("unauth-implement-gen0"))
    lp = tmp_path / LEDGER
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text('{"nope": 1}', encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert not (tmp_path / TEST_F).exists()
    assert any("no paths object" in n for n in notes)


def test_junk_item_shapes_skip_named_no_crash(tmp_path):
    # external-input discipline: junk manifest contents never raise, never restore
    bdir = tmp_path / ".sandbar" / "quarantine" / "unauth-implement-gen0"
    bdir.mkdir(parents=True)
    (bdir / "manifest.json").write_text(json.dumps({"items": [
        "a string item",
        {"action": "moved"},                        # path/archive missing
        {"path": 17, "action": "moved"},            # non-str path
        {"path": TEST_F, "action": "reverted"},     # not moved
        {"path": TEST_F, "action": "moved", "archive": 5},
    ]}), encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert not (tmp_path / TEST_F).exists()
    assert not any(n.startswith("recovered:") for n in notes)


def test_malformed_manifest_keeps_named_skip(tmp_path):
    # regression pin of the -25 fault face, now alongside the ledger
    bdir = tmp_path / ".sandbar" / "quarantine" / "unauth-implement-gen0"
    bdir.mkdir(parents=True)
    (bdir / "manifest.json").write_text("{junk", encoding="utf-8")
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert any("manifest unreadable" in n for n in notes)


def test_requarantine_after_recovery_is_named_not_restored(tmp_path):
    # a NEW batch for a ledgered path (wrongful re-quarantine after recovery):
    # not auto-restored, and this skip IS named (unmarked item reaches the
    # ledger check) — the intentional-removal intent wins, visibly
    _mk_batch(tmp_path, "unauth-implement-gen0", _item("unauth-implement-gen0"))
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    (tmp_path / TEST_F).unlink()
    _mk_batch(tmp_path, "unauth-implement-gen7", _item("unauth-implement-gen7"))
    notes.clear()
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert not (tmp_path / TEST_F).exists()
    assert any("processed-path" in n and TEST_F in n for n in notes)


def test_ledger_absent_is_clean_noop(tmp_path):
    # no quarantine area at all: zero notes, zero files
    notes = []
    _aa()._recover_quarantined_test_face(tmp_path, "t261004-34", notes)
    assert notes == []
    assert not (tmp_path / LEDGER).exists()
