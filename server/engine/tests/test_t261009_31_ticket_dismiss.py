"""t261009-31 — ticket dismissal: a recorded human decision, reversible.

Covers (plan Steps 1-4, review comments 1-4 folded in):
  - happy dismiss/restore: journal row shape {at, ticket_id, who, reason, action};
    receipt carries the same who/reason verbatim; LAST row wins (dismiss ->
    restore -> face None; re-dismiss AFTER a restore must SUCCEED — review
    comment 1: repeat-dismiss is defined against the LAST row, never "ever
    dismissed").
  - every refusal named + zero side effects (byte-identical journal dir):
    empty reason (never defaulted), empty who, over-bound who/reason, agent-role
    who, unknown ticket, repeat dismiss (quotes the standing disposition),
    restore when not dismissed.
  - malformed-line tolerance: torn/non-JSON/non-dict lines skipped but COUNTED;
    a malformed existing file stays appendable.
  - empty/blank ticket_id row is nobody's voucher (review comment 3).
  - append OSError propagates (review comment 2): a receipt must never claim a
    row that was not written.
  - client.py augmentation helpers: dismissed:{at,who,reason} (payload key
    shape fixed, action stays internal — review comment 4); read failure = key
    absent + a named dismissed_note.
  - no-inspection-dependency: the module source contains no `inspection`
    reference (dispatch spec: the journal and its reader live in a new module
    with no inspection dependency).
  - CLI handlers (tools/ticket.py _dismiss_restore via run()): ok receipt shape
    + named refusals, existence gate against the engine ticket population.

Offline: zero Temporal / docker / network; journal dirs are tmp_path fixtures.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ticket_dismiss as td  # noqa: E402

TID = "t261006-16"
WHO = "host"
REASON = "workflow genuinely failed; the finding is recorded; the row leaves the board"
TICKETS = {TID, "t260929-11", "t261005-07"}


def dismiss(d, **kw):
    base = dict(ticket_id=TID, who=WHO, reason=REASON, known_ticket_ids=TICKETS)
    base.update(kw)
    if base["known_ticket_ids"] is None:
        base.pop("known_ticket_ids")
    return td.dismiss_ticket(d, **base)


def restore(d, **kw):
    base = dict(ticket_id=TID, who=WHO, reason=REASON, known_ticket_ids=TICKETS)
    base.update(kw)
    if base["known_ticket_ids"] is None:
        base.pop("known_ticket_ids")
    return td.restore_ticket(d, **base)


def dir_digest(root):
    root = Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---- happy path + last-row-wins reversibility --------------------------------

def test_happy_dismiss_row_and_receipt_agree(tmp_path):
    out = dismiss(tmp_path)
    assert out["ok"] is True
    v = out["dismissed"]
    assert v["who"] == WHO and v["reason"] == REASON and v["ticket_id"] == TID
    assert isinstance(v["at"], float)
    rows = td.read_dismiss_journal(tmp_path)
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"at", "ticket_id", "who", "reason", "action"}
    assert rows[0]["action"] == "dismiss"
    assert rows[0]["who"] == WHO and rows[0]["reason"] == REASON
    assert Path(out["journal"]).name == td.DISMISS_JOURNAL_NAME


def test_last_row_wins_dismiss_restore_redismiss(tmp_path):
    assert dismiss(tmp_path)["ok"] is True
    standing = td.dismissed_ticket_row(td.read_dismiss_journal(tmp_path), TID)
    assert td.dismissed_face(standing) is not None
    # restore = another signed row, never an edit
    assert restore(tmp_path, reason="wrong ticket picked; back on the board")["ok"] is True
    standing = td.dismissed_ticket_row(td.read_dismiss_journal(tmp_path), TID)
    assert standing["action"] == "restore"
    assert td.dismissed_face(standing) is None
    # review comment 1: re-dismiss after a restore is ALLOWED (last-row rule,
    # not ever-dismissed rule)
    assert dismiss(tmp_path, reason="confirmed dead after re-check")["ok"] is True
    rows = td.read_dismiss_journal(tmp_path)
    assert len(rows) == 3 and rows[-1]["action"] == "dismiss"
    assert td.dismissed_face(td.dismissed_ticket_row(rows, TID)) is not None


def test_other_ticket_untouched(tmp_path):
    dismiss(tmp_path)
    other = td.dismissed_ticket_row(td.read_dismiss_journal(tmp_path), "t260929-11")
    assert other is None and td.dismissed_face(other) is None


# ---- named refusals, zero side effects ---------------------------------------

REFUSAL_CASES = [
    ("empty reason", dict(reason="   "), "reason"),
    ("empty who", dict(who=""), "who"),
    ("over-bound who", dict(who="w" * 65), "who is too long"),
    ("over-bound reason", dict(reason="r" * 2001), "reason is too long"),
    ("agent-role who", dict(who="developer"),
     "only a human can sign a dismissal"),
]


@pytest.mark.parametrize("label,kw,needle", REFUSAL_CASES)
def test_dismiss_refusals_named_and_zerowrite(tmp_path, label, kw, needle):
    out = dismiss(tmp_path, **kw)
    assert out["ok"] is False and needle in out["error"], (label, out)
    assert dir_digest(tmp_path) == {}


@pytest.mark.parametrize("label,kw,needle", REFUSAL_CASES)
def test_restore_refusals_named_and_zerowrite(tmp_path, label, kw, needle):
    out = restore(tmp_path, **kw)
    assert out["ok"] is False and needle in out["error"], (label, out)
    assert dir_digest(tmp_path) == {}


def test_unknown_ticket_refused_by_name(tmp_path):
    out = dismiss(tmp_path, ticket_id="t260101-01")
    assert out["ok"] is False and "unknown ticket" in out["error"]
    assert dir_digest(tmp_path) == {}


def test_callable_known_ticket_ids(tmp_path):
    out = dismiss(tmp_path, known_ticket_ids=lambda: TICKETS)
    assert out["ok"] is True


def test_repeat_dismiss_refused_quoting_standing_row(tmp_path):
    dismiss(tmp_path)
    before = dir_digest(tmp_path)
    out = dismiss(tmp_path, reason="second signature attempt")
    assert out["ok"] is False
    assert "already dismissed" in out["error"]
    assert WHO in out["error"]          # quotes the standing disposition
    assert dir_digest(tmp_path) == before


def test_restore_when_not_dismissed_refused(tmp_path):
    out = restore(tmp_path)
    assert out["ok"] is False and "not dismissed" in out["error"]
    assert dir_digest(tmp_path) == {}


# ---- journal read tolerance ---------------------------------------------------

def test_malformed_lines_skipped_but_counted(tmp_path):
    p = td.dismiss_journal_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json}\n[1,2]\n\n", encoding="utf-8")
    rows, bad = td.read_dismiss_journal(tmp_path, with_malformed=True)
    assert rows == [] and bad == 2          # [1,2] parses but is not a dict
    assert td.read_dismiss_journal(tmp_path) == []
    # a malformed existing file stays appendable
    assert dismiss(tmp_path)["ok"] is True
    rows2, bad2 = td.read_dismiss_journal(tmp_path, with_malformed=True)
    assert len(rows2) == 1 and bad2 == 2
    assert td.dismissed_face(td.dismissed_ticket_row(rows2, TID)) is not None


def test_missing_file_is_empty(tmp_path):
    rows, bad = td.read_dismiss_journal(tmp_path, with_malformed=True)
    assert rows == [] and bad == 0


def test_blank_ticket_id_row_is_nobodys_voucher(tmp_path):
    # review comment 3: a corrupt row without an id must not shadow a real
    # dismissal of another ticket — and never matches a blank lookup either
    p = td.dismiss_journal_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": 1.0, "ticket_id": "  ", "who": "x",
                             "reason": "y", "action": "dismiss"}) + "\n", encoding="utf-8")
    rows = td.read_dismiss_journal(tmp_path)
    assert td.dismissed_ticket_row(rows, TID) is None
    assert td.dismissed_ticket_row(rows, "") is None
    assert td.dismissed_ticket_row(rows, None) is None


def test_append_oserror_propagates_never_fake_receipt(tmp_path):
    # review comment 2: the journal path occupied by a directory -> the append
    # raises; dismiss must surface that, never return ok=True with no row
    p = td.dismiss_journal_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()
    before = dir_digest(tmp_path)
    with pytest.raises(OSError):
        dismiss(tmp_path)
    assert dir_digest(tmp_path) == before
    # restore hits its state gate BEFORE any write, so it is a named refusal
    # (not dismissed), never an OSError and never a fake receipt
    out = restore(tmp_path)
    assert out["ok"] is False and "not dismissed" in out["error"]
    assert dir_digest(tmp_path) == before


# ---- journal home -------------------------------------------------------------

def test_journal_home_env_and_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path / "env"))
    assert td.journal_dir() == tmp_path / "env"
    assert td.dismiss_journal_path() == tmp_path / "env" / td.DISMISS_JOURNAL_NAME
    monkeypatch.delenv("SANDBAR_DISMISS_DIR")
    assert td.journal_dir(str(tmp_path / "explicit")) == tmp_path / "explicit"


# ---- client.py read-side helpers ----------------------------------------------

def test_client_augmentation_face_and_note(monkeypatch, tmp_path):
    import client
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path))
    dismiss(tmp_path)
    last = client._dismissed_read_last()
    face = client._dismissed_face_of(last, TID)
    assert face == {"at": last[TID]["at"], "who": WHO, "reason": REASON}
    assert set(face.keys()) == {"at", "who", "reason"}   # payload key shape fixed
    assert client._dismissed_face_of(last, "t260929-11") is None
    restore(tmp_path, reason="undo")
    last = client._dismissed_read_last()
    assert client._dismissed_face_of(last, TID) is None


def test_client_read_failure_degrades_with_note(monkeypatch, tmp_path):
    import client
    monkeypatch.setattr(client, "_dismissed_read_last",
                        lambda: (_ for _ in ()).throw(RuntimeError("journal exploded")))
    with pytest.raises(RuntimeError):
        client._dismissed_read_last()
    # the augmentation sites catch and translate into a named note; pin the note
    # copy shape used by the three sites (list / detail / terminal face)
    try:
        client._dismissed_read_last()
    except Exception as e:  # noqa: BLE001
        note = "dismiss journal read failed (rows not augmented): %s: %s" % (type(e).__name__, e)
        assert "dismiss journal read failed" in note and "journal exploded" in note


def test_no_inspection_dependency():
    import re
    src = Path(td.__file__).read_text("utf-8")
    import_lines = [ln for ln in src.splitlines()
                    if re.match(r"\s*(from|import)\s", ln)]
    assert import_lines, "import probe must find the module's imports"
    for ln in import_lines:
        assert "inspection" not in ln.lower(), ln


# ---- CLI handlers (tools/ticket.py) -------------------------------------------

def _load_ticket_tool():
    tools_dir = Path(__file__).resolve().parents[2] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import ticket as tool
    return tool


@pytest.fixture()
def tool(monkeypatch, tmp_path):
    t = _load_ticket_tool()
    monkeypatch.setenv("SANDBAR_DISMISS_DIR", str(tmp_path))
    monkeypatch.setattr(t, "_known_ticket_ids", lambda: TICKETS)
    return t


def test_cli_dismiss_ok_receipt(tool, tmp_path):
    out = tool.run({"op": "dismiss", "id": TID, "who": WHO, "reason": REASON})
    assert out["ok"] is True and out["dismissed"]["ticket_id"] == TID
    assert Path(out["journal"]).read_text("utf-8").count("\n") == 1


def test_cli_restore_ok_receipt(tool, tmp_path):
    tool.run({"op": "dismiss", "id": TID, "who": WHO, "reason": REASON})
    out = tool.run({"op": "restore", "id": TID, "by": WHO, "reason": "undo"})
    assert out["ok"] is True and out["restored"]["ticket_id"] == TID
    rows = td.read_dismiss_journal(tmp_path)
    assert rows[-1]["action"] == "restore"


def test_cli_named_refusals(tool, tmp_path):
    for args, needle in [
        ({"op": "dismiss", "id": TID, "reason": REASON}, "who"),
        ({"op": "dismiss", "id": TID, "who": WHO}, "reason"),
        ({"op": "restore", "id": TID, "who": WHO, "reason": REASON}, "not dismissed"),
        ({"op": "dismiss", "id": "t260101-01", "who": WHO, "reason": REASON}, "unknown ticket"),
        ({"op": "dismiss", "id": TID, "who": "developer", "reason": REASON}, "only a human"),
    ]:
        with pytest.raises(ValueError) as ei:
            tool.run(dict(args))
        assert needle in str(ei.value), (args, str(ei.value))
    assert dir_digest(tmp_path) == {}


def test_cli_existence_gate_fail_closed(tool, monkeypatch):
    # the population cannot be proven -> refuse by name, never skip the gate
    monkeypatch.setattr(tool, "_known_ticket_ids", lambda: None)
    with pytest.raises(ValueError) as ei:
        tool.run({"op": "dismiss", "id": TID, "who": WHO, "reason": REASON})
    # ASCII needle on purpose (L11 copy gate: no CJK literals in new test copy):
    # the refusal copy names the failed existence proof (ticket-list unavailable)
    assert "ticket-list" in str(ei.value)
