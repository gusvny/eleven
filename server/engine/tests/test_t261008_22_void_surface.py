"""t261008-22 — the named void surface for terminal blocked inspection tickets.

Covers (plan v2 Steps 1-2, engine half):
  - void_period_ticket happy path: journal row (at/instance/period/ticket_id/who/
    reason) + period ledger doc `voided` field carrying the SAME who/reason verbatim
    (face × record agreement, acceptance 4); blocked_reason and findings untouched
    (void must not read as success, reject rule "do not hide the rejected findings").
  - every refusal named + zero side effects (byte-identical ledger dir): empty/blank
    reason, empty who, over-bound who/reason, agent-role who, missing doc (live /
    redirected shell family), wrong ticket id, served (blocked_reason empty), double
    void (idempotence naming the FIRST disposition).
  - read_void_journal: absent file = [], torn lines counted with with_malformed=True,
    never fatal for other tickets.
  - voided_ticket_row: first-signature-wins; empty ticket_id never matches.
  - CLI (cmd_void via main dispatch shape): ok receipt shape + named refusals on the
    same fixture ledger (SANDBAR_INSPECTION_DIR pinned to a tmp dir).
  - period lexics parity: _void_period_lexical_error vs inspection_trigger._valid_period.

Offline: zero Temporal / docker / network; ledger dirs are tmp_path fixtures.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspection_ticketing as tick  # noqa: E402

INST = "integration-tests"
PERIOD = "20261002"
TICKET = "t261002-12"
WHO = "host"
REASON = "inspect output carried two findings blocks; parser refused to guess; voided by hand"
# Fixture DATA, not copy: mirrors the live t261002-12 blocked_reason verbatim
# (unicode escapes keep this source ASCII; the journal/doc bytes carry the real text).
BLOCKED_REASON = "findings \u56f4\u680f\u5757\u5fc5\u987b\u6070\u4e00\u5757\uff0c\u5b9e\u9645 2 \u5757"


def seed_blocked(root: Path, ticket_id=TICKET, blocked_reason=BLOCKED_REASON, period=PERIOD):
    d = root / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    p = d / tick.ledger_file_name(INST, period)
    doc = {"ticket_id": ticket_id, "kind": "inspection", "stage": "inspect",
           "blocked_reason": blocked_reason, "findings": [{"severity": "low", "text": "n"}]}
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d


def dir_digest(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


def void(d, **kw):
    base = dict(instance_id=INST, period=PERIOD, ticket_id=TICKET, who=WHO, reason=REASON)
    base.update(kw)
    return tick.void_period_ticket(d, **base)


def test_happy_path_records_who_reason_in_both_faces(tmp_path):
    d = seed_blocked(tmp_path)
    out = void(d)
    assert out["ok"] is True
    v = out["voided"]
    assert v["who"] == WHO and v["reason"] == REASON and v["ticket_id"] == TICKET
    rows = tick.read_void_journal(d)
    mine = [r for r in rows if r.get("ticket_id") == TICKET]
    assert len(mine) == 1
    assert mine[0]["who"] == WHO and mine[0]["reason"] == REASON
    assert mine[0]["instance"] == INST and mine[0]["period"] == PERIOD
    assert isinstance(mine[0]["at"], float)
    doc = tick.read_period_ledger_doc(d, INST, PERIOD)
    assert isinstance(doc.get("voided"), dict)
    assert doc["voided"]["who"] == WHO and doc["voided"]["reason"] == REASON


def test_void_preserves_blocked_face_and_findings(tmp_path):
    d = seed_blocked(tmp_path)
    before = tick.read_period_ledger_doc(d, INST, PERIOD)
    assert void(d)["ok"] is True
    after = tick.read_period_ledger_doc(d, INST, PERIOD)
    for k in ("blocked_reason", "findings", "ticket_id", "kind", "stage"):
        assert after[k] == before[k]


@pytest.mark.parametrize("kw,frag", [
    (dict(reason=""), "reason"),
    (dict(reason="   "), "reason"),
    (dict(who=""), "who"),
    (dict(who="developer"), "agent"),
    (dict(who="x" * 65), "who"),
    (dict(reason="y" * 2001), "reason"),
    (dict(period="20261332"), "period"),
    (dict(period="abc"), "period"),
])
def test_shape_refusals_named_zero_writes(tmp_path, kw, frag):
    d = seed_blocked(tmp_path)
    before = dir_digest(d)
    out = void(d, **kw)
    assert out["ok"] is False and frag in out["error"]
    assert dir_digest(d) == before


@pytest.mark.parametrize("seed,frag", [
    ("absent", "unreadable"),
    ("served", "served"),
    ("wrongtid", "does not match"),
])
def test_population_refusals_named_zero_writes(tmp_path, seed, frag):
    if seed == "absent":
        d = tmp_path / "l"
        d.mkdir()
    elif seed == "served":
        d = seed_blocked(tmp_path, blocked_reason="")
    else:
        d = seed_blocked(tmp_path, ticket_id="t-other")
    before = dir_digest(d)
    out = void(d)
    assert out["ok"] is False and frag in out["error"]
    assert dir_digest(d) == before


def test_double_void_refuses_and_names_first(tmp_path):
    d = seed_blocked(tmp_path)
    assert void(d)["ok"] is True
    before = dir_digest(d)
    out = void(d, who="host-2", reason="second attempt")
    assert out["ok"] is False
    assert WHO in out["error"] and REASON in out["error"]
    assert dir_digest(d) == before
    assert len(tick.read_void_journal(d)) == 1


def test_torn_journal_row_counted_not_fatal(tmp_path):
    d = seed_blocked(tmp_path)
    with open(d / tick.VOID_JOURNAL_NAME, "a", encoding="utf-8") as f:
        f.write("{torn line\n")
    seed_blocked(tmp_path, ticket_id="t2", period="20261009")
    out = void(d, period="20261009", ticket_id="t2")
    assert out["ok"] is True
    rows, malformed = tick.read_void_journal(d, with_malformed=True)
    assert malformed == 1
    assert len([r for r in rows if r.get("ticket_id") == "t2"]) == 1


def test_voided_ticket_row_first_signature_wins(tmp_path):
    d = seed_blocked(tmp_path)
    assert tick.voided_ticket_row(tick.read_void_journal(d), TICKET) is None
    assert void(d)["ok"] is True
    row = tick.voided_ticket_row(tick.read_void_journal(d), TICKET)
    assert row is not None and row["who"] == WHO
    assert tick.voided_ticket_row(tick.read_void_journal(d), "") is None


def test_cli_void_end_to_end(tmp_path, monkeypatch):
    d = seed_blocked(tmp_path)
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(d))
    import inspection_trigger as trig
    args = trig.argparse.Namespace(instance=INST, period=PERIOD, ticket_id=TICKET,
                                   who=WHO, reason=REASON)
    out = trig.cmd_void(args)
    assert out["ok"] is True and out["voided"]["who"] == WHO
    again = trig.cmd_void(args)
    assert again["ok"] is False and "already voided" in again["error"]


def test_period_lexics_parity_with_trigger():
    from inspection_trigger import _valid_period
    for p in ["20261002", "20261002-2", "20261002-0", "20261332", "abc", "2026100", ""]:
        assert bool(_valid_period(p)) == bool(tick._void_period_lexical_error(p)), p
