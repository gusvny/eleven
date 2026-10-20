"""t261016-10 — the dismiss existence gate must cover the inspection store too.

Residual of t261009-31: the gate in tools/ticket.py read the engine ticket-list
only, so a reserved-then-superseded inspection id (the host's t261008-17: alive
only as a pointer's `supersedes_ticket_id` and a spawn-journal row) was refused
after the click and the row stayed on the board.

Covers:
  - inspection_ticketing.inspection_known_ticket_ids: pointer `ticket_id` +
    `supersedes_ticket_id`, spawn-journal `ticket_id`, reopen-journal
    `terminated_ticket_id` / `new_ticket_id` / `collapsed_ticket_ids`;
    tolerance carried from the module's own readers (missing files = empty,
    malformed pointer / malformed line skipped, blank dropped).
  - tools/ticket.py gate: ticket-list DOWN + inspection store UP -> the
    reserved id dismisses (the t261008-17 regression: press -> receipt ->
    journal row -> restore back); BOTH sources down -> refuse by name, zero
    writes; an id in neither source -> refused naming both checked sources.
  - dev-lane path unchanged: an id proven by the ticket-list dismisses with the
    same journal shape and the same human+reason rules (who = agent role name
    still refused).

Offline: zero Temporal / docker / network; stores and journals are tmp_path
fixtures (malformed-input cases are stub files, never a live source).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspection_ticketing as it  # noqa: E402
import ticket_dismiss as td  # noqa: E402

WHO = "host"
REASON = "failed period run; the finding is recorded; the row leaves the board"
RESERVED = "t261008-17"
LIVE = "t261008-27"


def write_pointer(d, instance, period, ticket_id, supersedes=""):
    payload = {"ticket_id": ticket_id, "instance_id": instance, "period": period,
               "project_key": "sandbar", "supersedes_ticket_id": supersedes}
    (Path(d) / ("inspection-%s-%s.ticket" % (instance, period))).write_text(
        json.dumps(payload), "utf-8")


def write_journal(d, name, rows):
    with open(Path(d) / name, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


@pytest.fixture()
def tool():
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import ticket as t
    return t


@pytest.fixture()
def inspection_store(tmp_path, monkeypatch):
    """The t261008-17 shape: a period pointer whose live ticket superseded a
    reserved id, plus spawn/reopen journals vouching for the whole chain."""
    store = tmp_path / "inspection"
    store.mkdir()
    write_pointer(store, "simplify-face", "20261008", LIVE, supersedes=RESERVED)
    write_journal(store, "inspection-spawn.jsonl", [
        {"at": 1.0, "instance": "simplify-face", "period": "20261008",
         "face": "cron", "decision": "triggered", "period_state": "live",
         "ticket_id": LIVE, "alarm": False, "note": "spawned"}])
    write_journal(store, "inspection-reopen.jsonl", [
        {"at": 2.0, "instance": "simplify-face", "period": "20261008",
         "terminated_ticket_id": RESERVED, "new_ticket_id": LIVE,
         "collapsed_ticket_ids": ["t261008-19"]}])
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(store))
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path / "dismiss"))
    # Hermetic under the FULL suite: shared.__getattr__ caches the first resolved
    # value back into globals(), so whichever test touches shared.INSPECTION_DIR
    # first would freeze it for everyone and the env pin above would be ignored.
    # The module attribute is the declared injection seam (same discipline as
    # shared.PROJECTS_YAML: an explicit attribute wins over the lazy default;
    # monkeypatch removes it on teardown, restoring laziness).
    import shared  # noqa: PLC0415
    monkeypatch.setattr(shared, "INSPECTION_DIR", str(store), raising=False)
    return store


# ---- module-level: the inspection store population -----------------------------

def test_store_population_covers_pointer_spawn_reopen_ids(inspection_store):
    ids = it.inspection_known_ticket_ids(inspection_store)
    assert {RESERVED, LIVE, "t261008-19"} <= ids


def test_store_population_tolerates_malformed_inputs(inspection_store):
    # malformed pointer (torn JSON) and malformed journal lines are skipped,
    # never a crash; a well-formed id elsewhere still vouches
    (inspection_store / "inspection-bad-20260101.ticket").write_text("{torn", "utf-8")
    with open(inspection_store / "inspection-spawn.jsonl", "a", encoding="utf-8") as f:
        f.write("not-json\n")
        f.write(json.dumps({"ticket_id": ""}) + "\n")          # blank dropped
        f.write("[1,2]\n")                                     # non-dict skipped
    write_journal(inspection_store, "inspection-reopen.jsonl", [
        {"terminated_ticket_id": "", "new_ticket_id": "t261008-28"}])
    ids = it.inspection_known_ticket_ids(inspection_store)
    assert {RESERVED, LIVE, "t261008-19", "t261008-28"} <= ids
    assert "" not in ids


def test_store_population_missing_dir_is_empty(tmp_path):
    assert it.inspection_known_ticket_ids(tmp_path / "nope") == set()


# ---- tools gate: the t261008-17 regression --------------------------------------

def test_reserved_id_dismisses_on_inspection_store_alone(tool, inspection_store,
                                                         monkeypatch):
    # ticket-list down, store up: the reserved id (no ticket face anywhere)
    # must still dismiss — press -> receipt -> journal row -> restore back
    monkeypatch.setattr(tool, "_known_ticket_ids", lambda: None)
    out = tool.run({"op": "dismiss", "id": RESERVED, "who": WHO, "reason": REASON})
    assert out["ok"] is True and out["dismissed"]["ticket_id"] == RESERVED
    assert out["population_sources"] == ["inspection-store"]
    rows = td.read_dismiss_journal(td.journal_dir())
    assert [r["action"] for r in rows] == ["dismiss"]
    assert rows[0]["who"] == WHO and rows[0]["reason"] == REASON
    back = tool.run({"op": "restore", "id": RESERVED, "by": WHO, "reason": "undo"})
    assert back["ok"] is True and back["restored"]["ticket_id"] == RESERVED
    rows = td.read_dismiss_journal(td.journal_dir())
    assert rows[-1]["action"] == "restore"


def test_both_sources_down_refuses_named_and_zerowrite(tool, monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(tmp_path / "no-store"))
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(tool, "_inspection_ticketing_mod",
                        lambda: (_ for _ in ()).throw(RuntimeError("store unreadable")))
    monkeypatch.setattr(tool, "_known_ticket_ids", lambda: None)
    with pytest.raises(ValueError) as ei:
        tool.run({"op": "dismiss", "id": RESERVED, "who": WHO, "reason": REASON})
    # ASCII needle (L11 copy gate): the refusal names the unprovable existence
    # check (ticket-list AND inspection store both unreadable -> refuse, no guess)
    assert "ticket-list" in str(ei.value)
    assert not (td.journal_dir() / td.DISMISS_JOURNAL_NAME).exists()


def test_id_in_neither_source_refused_naming_both(tool, inspection_store,
                                                  monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(tool, "_known_ticket_ids", lambda: {"t260929-11"})
    with pytest.raises(ValueError) as ei:
        tool.run({"op": "dismiss", "id": "t260101-01", "who": WHO, "reason": REASON})
    msg = str(ei.value)
    assert "unknown ticket" in msg and "engine ticket-list" in msg \
        and "inspection store" in msg
    assert not (td.journal_dir() / td.DISMISS_JOURNAL_NAME).exists()


# ---- dev-lane path unchanged -----------------------------------------------------

def test_devlane_path_same_journal_shape_and_rules(tool, inspection_store,
                                                   monkeypatch):
    monkeypatch.setattr(tool, "_known_ticket_ids", lambda: {"t260929-11"})
    out = tool.run({"op": "dismiss", "id": "t260929-11", "who": WHO, "reason": REASON})
    assert out["ok"] is True
    assert "engine-ticket-list" in out["population_sources"]
    rows = td.read_dismiss_journal(td.journal_dir())
    assert set(rows[0].keys()) == {"at", "ticket_id", "who", "reason", "action"}
    # the human+reason rules stay: an agent role signature is refused
    with pytest.raises(ValueError) as ei:
        tool.run({"op": "dismiss", "id": "t260929-11", "who": "developer",
                  "reason": REASON})
    assert "only a human" in str(ei.value)
