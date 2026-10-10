"""t261009-69: the finding entity / observation split unit tests.

Covers the ticket's five MUST-BECOME-TRUE points on the pure + thin-IO faces:
- (1) mint at 16 hex, stable across periods for the same rule+object
      (`legacy_id_matches` contract included);
- (2) observation is its own record, no id, keyed (finding, period); re-seeing
      appends an observation, never a second entity (duplicate suppression with
      a named count);
- (3) the read face (`finding_history`) answers first-seen / periods-seen
      count+list / last sighting FROM the ledger;
- (4) malformed/absent inputs degrade and NAME, never raise: corrupt/torn
      ledger lines dropped and counted, unreadable/missing ledger = named empty,
      an out-of-vocabulary verification degrades to `downgraded` with the raw
      value named, an unverified finding still gets its observation;
- (5) history is not renumbered: a stored 8-hex id resolves by prefix and the
      result states which resolution rule matched (`id_resolution`).
Malformed-input cases use fabricated fixture files only — no external source.
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_inspect as ins  # noqa: E402
import inspection_review_ledger as rl  # noqa: E402


# ---------- fixtures ----------

def finding(**kw) -> dict:
    f = {
        "subject": "guard asserts a deleted function src/a.py:12",
        "severity": "med",
        "evidence": [{"path": "src/a.py", "line": 12, "quote": "assert old_fn()"}],
        "why": "the guarded object no longer exists",
        "verified": "verified",
        "scan": "agent",
    }
    f.update(kw)
    return f


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
                    encoding="utf-8")


@pytest.fixture()
def ledger_dir(tmp_path):
    return tmp_path


# ---------- (1) mint: 16 hex, stable, legacy resolution ----------

def test_mint_is_16_hex_and_stable_across_periods():
    a = ins.with_ids([finding()])[0]
    b = ins.with_ids([finding(why="re-worded next period")])[0]
    assert len(a["id"]) == 16
    assert all(c in "0123456789abcdef" for c in a["id"])
    assert a["id"] == b["id"], "a later sighting of the same content mints the SAME id"


def test_legacy_id_matches_contract():
    wide = "3d4b305e1f7a9c02"
    assert ins.legacy_id_matches(wide, wide)                       # exact
    assert ins.legacy_id_matches("3d4b305e", wide)                 # 8-hex prefix
    assert ins.legacy_id_matches(" 3D4B305E ", wide)               # case/space tolerant
    assert not ins.legacy_id_matches("3d4b305f", wide)             # different prefix
    assert not ins.legacy_id_matches("3d4b30", wide)               # wrong stored width
    assert not ins.legacy_id_matches("", wide)                     # empty
    assert not ins.legacy_id_matches(None, wide)                   # non-str
    assert not ins.legacy_id_matches("zzzzzzzz", wide)             # non-hex
    assert not ins.legacy_id_matches(wide[:9], wide)               # 9-hex: not a legacy shape


# ---------- (2) entity + observation records ----------

def test_entity_row_shape_and_malformed_rejection():
    f = ins.with_ids([finding()])[0]
    rec = rl.finding_entity_record(f, ts=100.0)
    assert rec["id"] == f["id"] and rec["subject"] and rec["minted_at"] == 100.0
    assert rec["evidence"] == [{"path": "src/a.py", "line": 12}]
    assert rl.finding_entity_record({"subject": "no id"}) is None
    assert rl.finding_entity_record("not a dict") is None
    assert rl.finding_entity_record(None) is None


def test_observation_row_has_no_id_and_key_is_finding_period():
    rec = rl.finding_observation_record("abc123", "20261007",
                                        rl.VERIFICATION_VERIFIED, "", ts=1791520000.0)
    assert set(rec) == {"finding", "period", "verification",
                        "verification_note", "at"}, "an observation carries NO id"
    assert rec["at"] == 1791520000000, "at is milliseconds since the epoch"


def test_observation_unverified_still_recorded_and_out_of_vocab_named():
    # requirement 4: a finding that cannot be verified this period still gets an
    # observation SAYING SO; an out-of-vocabulary outcome degrades AND names.
    rec = rl.finding_observation_record("abc123", "20261007",
                                        rl.VERIFICATION_UNLOCATABLE,
                                        "the quoted line is gone", ts=1.0)
    assert rec["verification"] == rl.VERIFICATION_UNLOCATABLE
    assert rec["verification_note"] == "the quoted line is gone"
    rec2 = rl.finding_observation_record("abc123", "20261007", "", ts=1.0)
    assert rec2["verification"] == rl.VERIFICATION_DOWNGRADED
    assert "absent" in rec2["verification_note"], "the raw outcome is named"
    rec3 = rl.finding_observation_record("abc123", "20261007", "weird", ts=1.0)
    assert "weird" in rec3["verification_note"]
    assert rl.finding_observation_record("", "20261007", "verified") is None
    assert rl.finding_observation_record("abc", "", "verified") is None


# ---------- append faces: one entity, many observations ----------

def test_append_findings_skips_duplicate_entity_and_names_malformed(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    f = ins.with_ids([finding()])[0]
    notes1 = rl.append_findings(fp, [f])
    assert notes1["ledger_written"] == 1
    notes2 = rl.append_findings_ex(fp, [f], existing_ids={f["id"]})
    assert notes2.get("entity_duplicates_skipped") == 1, "re-seeing never re-mints an entity"
    assert "ledger_written" not in notes2
    notes3 = rl.append_findings(fp, [{"subject": "no minted id"}])
    assert notes3.get("entity_rows_malformed") == 1, "malformed finding is named, not written"
    rows, _ = rl.load_jsonl_rows(fp, "entity")
    assert len(rows) == 1


def test_append_observations_dedupe_on_finding_period(ledger_dir):
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    r1 = rl.finding_observation_record("abc", "20261007", "verified", ts=1.0)
    r2 = rl.finding_observation_record("abc", "20261008", "verified", ts=2.0)
    notes = rl.append_observations(op, [r1, r2])
    assert notes["ledger_written"] == 2
    rows, _ = rl.load_jsonl_rows(op, "obs")
    keys = rl.observation_keys(rows)
    notes2 = rl.append_observations(op, [r1, r1], known_keys=keys)
    assert notes2.get("observation_duplicates_skipped") == 2, \
        "same (finding, period) is never appended twice"
    rows2, _ = rl.load_jsonl_rows(op, "obs")
    assert len(rows2) == 2


# ---------- read face: the age query ----------

def test_finding_history_answers_first_seen_periods_last(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    fid = "3d4b305e1f7a9c02"
    write_jsonl(fp, [{"id": fid, "subject": "s", "severity": "med",
                      "scan": "agent", "evidence": [], "minted_at": 1.0}])
    write_jsonl(op, [
        {"finding": fid, "period": "20261001", "verification": "verified",
         "verification_note": "", "at": 1000},
        {"finding": fid, "period": "20261005", "verification": "downgraded",
         "verification_note": "the quoted line is gone", "at": 2000},
        {"finding": fid, "period": "20261003", "verification": "verified",
         "verification_note": "", "at": 1500},
    ])
    h = rl.finding_history(fp, op, fid)
    assert h["available"] and h["reason"] == ""
    assert h["first_seen"] == "20261001"
    assert h["periods_seen"] == ["20261001", "20261003", "20261005"]
    assert h["periods_seen_count"] == 3
    assert h["last_sighting"]["period"] == "20261005"
    assert h["last_sighting"]["verification"] == "downgraded"
    assert h["id_resolution"] == "exact"


def test_finding_history_resolves_legacy_8hex_without_renumbering(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    write_jsonl(fp, [{"id": "3d4b305e", "subject": "old ledger row", "severity": "med",
                      "scan": "agent", "evidence": [], "minted_at": 1.0}])
    write_jsonl(op, [{"finding": "3d4b305e", "period": "20260901",
                      "verification": "verified", "verification_note": "", "at": 5}])
    h = rl.finding_history(fp, op, "3d4b305e1f7a9c02")
    assert h["available"] and h["first_seen"] == "20260901"
    assert "legacy" in h["id_resolution"] and "not renumbered" in h["id_resolution"]


def test_finding_history_names_absent_and_orphan_sightings(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    h0 = rl.finding_history(fp, op, "3d4b305e1f7a9c02")
    assert not h0["available"] and "not in the entity ledger" in h0["reason"]
    write_jsonl(fp, [{"id": "3d4b305e1f7a9c02", "subject": "s", "severity": "med",
                      "scan": "agent", "evidence": [], "minted_at": 1.0}])
    write_jsonl(op, [{"finding": "deadbeefdeadbeef", "period": "20261001",
                      "verification": "verified", "verification_note": "", "at": 1}])
    h1 = rl.finding_history(fp, op, "3d4b305e1f7a9c02")
    assert h1["available"]
    assert h1["periods_seen_count"] == 0
    assert "zero sightings" in h1["reason"]
    assert not h1["orphan_sightings"], "orphans belong to OTHER findings, not this one"
    assert rl.finding_history(fp, op, "")["reason"]            # no id -> refused, named


def test_finding_history_torn_and_corrupt_rows_degrade_named(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    write_jsonl(fp, [{"id": "3d4b305e1f7a9c02", "subject": "s", "severity": "med",
                      "scan": "agent", "evidence": [], "minted_at": 1.0}])
    write_jsonl(op, [{"finding": "3d4b305e1f7a9c02", "period": "20261001",
                      "verification": "verified", "verification_note": "", "at": 1}])
    with open(op, "a", encoding="utf-8") as fh:
        fh.write('{"finding": "3d4b305e1f7a9c02", "period": "2026100\n')   # torn tail
        fh.write('"just a string"\n')                                       # non-dict row
    h = rl.finding_history(fp, op, "3d4b305e1f7a9c02")
    assert h["available"] and h["periods_seen_count"] == 1, "corrupt rows do not kill the query"
    assert h["notes"].get("corrupt_lines") == 2, "the gap is counted, not hidden"


def test_finding_history_unreadable_ledger_degrades_named(ledger_dir):
    fp = ledger_dir / rl.FINDINGS_LEDGER_NAME
    fp.write_bytes(b"\xff\xfe\x00bad")  # readable bytes but valid rows? force OSError path via a directory
    op = ledger_dir / rl.OBSERVATIONS_LEDGER_NAME
    op_dir = ledger_dir / "obs_is_a_dir"
    op_dir.mkdir()
    h = rl.finding_history(fp, op_dir, "3d4b305e1f7a9c02")
    assert not h["available"] and "not in the entity ledger" in h["reason"]
    assert h["notes"], "the read failure is named in the notes"


# ---------- cross-period dedupe across the widening boundary ----------

def test_dedupe_marks_widened_resighting_recurring_against_legacy_prev_ids():
    wide = ins.with_ids([finding()])[0]
    prev = {wide["id"][:8]}          # a pre-widening period ledger stores 8 hex
    out = ins.dedupe_and_suppress([dict(wide)], prev_ids=prev, fake_ids=[])
    assert out[0]["recurring"] is True, "the same finding is recurring across the widening"
    fake = {"another0123456789abcdef"[:8]}
    f2 = dict(ins.with_ids([finding(subject="other obj",
                                    evidence=[{"path": "b.py", "line": 2, "quote": "q"}])])[0])
    f2["id"] = "another0123456789abcdef"
    out2 = ins.dedupe_and_suppress([f2], prev_ids=set(), fake_ids=fake)
    assert out2[0]["suppressed"] is True, "a legacy false-positive still suppresses"
    assert ins.id_in_legacy_set("", {"abc"}) is False
    assert ins.id_in_legacy_set(None, {"abc"}) is False
    assert ins.id_in_legacy_set("abc", None) is False
    assert ins.id_in_legacy_set("abddef0123456789", {"abddef02"}) is False, "a different prefix never matches"


# ---------- aggregate: cross-period legacy merge (requirement 5) ----------

def test_aggregate_merges_legacy_8hex_with_widened_id(tmp_path):
    import inspection_aggregate as ag
    d = tmp_path
    old = {"findings": [{"id": "3d4b305e", "severity": "med", "subject": "s",
                         "scan": "agent", "verified": "verified"}]}
    new = {"findings": [{"id": "3d4b305e1f7a9c02", "severity": "med", "subject": "s",
                         "scan": "agent", "verified": "verified"}]}
    (d / "inspection-inst-20261001.json").write_text(json.dumps(old))
    (d / "inspection-inst-20261007.json").write_text(json.dumps(new))
    (d / "inspection-inst-20261007-verdicts.json").write_text(json.dumps(
        {"entries": [{"finding_id": "3d4b305e", "verdict": "to-fix"}]}))
    out = ag.build_aggregate("inst", str(d), window_days=10)
    assert out["finding_id_width"] == 16
    assert "8-hex prefix" in out["legacy_id_note"], "the receipt states how old ids are treated"
    ids = sorted(e["id"] for e in out["still_open"])
    assert ids == ["3d4b305e1f7a9c02"], "the same finding across the widening is ONE thing"
    entry = out["still_open"][0]
    assert entry["first_seen"] == "20261001", "age is computed across the widening"
    assert entry["verdict"] == "to-fix", "a verdict stored under the 8-hex id still matches"


def test_aggregate_keeps_distinct_findings_distinct(tmp_path):
    import inspection_aggregate as ag
    d = tmp_path
    doc = {"findings": [
        {"id": "3d4b305e1f7a9c02", "severity": "med", "subject": "a", "scan": "agent",
         "verified": "verified"},
        {"id": "3d4b305f1f7a9c02", "severity": "med", "subject": "b", "scan": "agent",
         "verified": "verified"},
    ]}
    (d / "inspection-inst-20261007.json").write_text(json.dumps(doc))
    out = ag.build_aggregate("inst", str(d), window_days=10)
    assert len(out["still_open"]) == 2, "a 1-hex difference is never a legacy match"
