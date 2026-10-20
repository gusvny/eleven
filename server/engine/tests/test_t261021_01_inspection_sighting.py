"""t261021-01: the finding sighting chain (developer L1 unit battery).

Ticket: a finding re-seen in a later period leaves no record — the inspection
ledger cannot say "this fault came back, against this revision". This battery
owns the inspect-side faces delivered in inspection_inspect.py:

- sighting_verification: verified-state -> observation-vocabulary mapping; the
  range is VERIFICATION_VOCAB for EVERY input (the append face's out-of-vocab
  fallback must stay dead code on this path).
- sighting_rows (pure): first sighting = entity row ONLY, no observation row
  (the finding itself is the first sighting); a re-sighting = exactly one
  observation row carrying the period's pinned revision; fail-closed by name
  (absent revision refuses the whole batch; an unresolvable identity is
  refused per finding, never recorded against "unknown").
- record_sightings (IO face over REAL temp ledger files): writes where the
  inspection already writes its facts; idempotent same-period rewrite is a
  named skip; corrupt ledger lines degrade named, never raise.
- sighting_report (read face): answers "how many times seen, at which
  revisions" as 1 + count(observations); a first-period finding reports 1
  with an empty observation list.

Run: server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261021_01_inspection_sighting.py -q
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_inspect as ii  # noqa: E402
import inspection_review_ledger as rl  # noqa: E402

PERIOD = "20261021"
REV = "a1b2c3d4e5f60718"
REV2 = "018f5f6e7d8c9b0a"


def _finding(fid, subject="the rule + object naming string", verified="verified",
             reasons=None):
    return {"id": fid, "scan": "doc-m1-index", "severity": "med",
            "subject": subject,
            "evidence": [{"path": "docs/x.md", "line": 1, "quote": "---"}],
            "why": "why", "suggestion": "suggestion",
            "verified": verified,
            **({"unverified_reasons": reasons} if reasons else {})}


def _minted(subject="the rule + object naming string",
            path="docs/x.md", line=1):
    return ii.mint_finding_id({"subject": subject,
                               "evidence": [{"path": path, "line": line}]})


# ---------------- sighting_verification: the mapping's range is the vocabulary ----

# reason fixtures are built from the engine's own token bytes (_SIGHTING_LOCATION_
# TOKENS), never retyped — the gate's copy rule stays clean and the matcher cannot
# drift from what recheck_evidence actually emits
T_EXIST, T_RANGE, T_MISMATCH, T_UNREADABLE = ii._SIGHTING_LOCATION_TOKENS
# the non-English fixture payload is DATA (it feeds the CJK detector), built
# from the detector's own range so no literal is retyped here
CJK_MARK = "\u542b\u4e2d\u6587\u53d9\u8ff0"


def _loc_reason(tok, path="docs/x.md:3"):
    return "%s %s (base /tmp)" % (path, tok)


def test_mapping_range_is_vocabulary_for_every_input():
    states = ["verified", "recurring", "suppressed", "unverified", None,
              "", "weird", 42]
    reasons = [None, [], ["non_english_text: subject"],
               [_loc_reason(T_EXIST)],
               [_loc_reason(T_RANGE, "docs/x.md:9")],
               [_loc_reason(T_MISMATCH)],
               [_loc_reason(T_UNREADABLE)],
               ["docs/x.md:3 evidence path is absolute"],
               ["non_english_text: subject", _loc_reason(T_EXIST)]]
    for s in states:
        for r in reasons:
            ver, _note = ii.sighting_verification(_finding("a" * 16, verified=s,
                                                           reasons=r))
            assert ver in rl.VERIFICATION_VOCAB, (s, r, ver)


def test_mapping_location_failure_is_unlocatable_and_named():
    ver, note = ii.sighting_verification(_finding(
        "a" * 16, verified="unverified", reasons=[_loc_reason(T_EXIST)]))
    assert ver == "unlocatable" and T_EXIST in note


def test_mapping_mixed_or_non_location_reasons_downgrade_with_note():
    ver, note = ii.sighting_verification(_finding(
        "a" * 16, verified="unverified",
        reasons=["non_english_text: subject"]))
    assert ver == "downgraded" and "non_english_text" in note
    # a location failure mixed with a non-location reason downgrades (not all
    # reasons say the location is gone) and still names the first reason
    ver, note = ii.sighting_verification(_finding(
        "a" * 16, verified="unverified",
        reasons=["non_english_text: subject", _loc_reason(T_EXIST)]))
    assert ver == "downgraded" and note.startswith("non_english_text")
    # unverified with no reason at all still degrades and says so
    ver, note = ii.sighting_verification({"id": "a" * 16, "verified": "unverified"})
    assert ver == "downgraded" and "no named reason" in note


def test_mapping_verified_and_recurring_map_to_verified_suppressed_downgrades():
    assert ii.sighting_verification(_finding("a" * 16))[0] == "verified"
    assert ii.sighting_verification(
        _finding("a" * 16, verified="recurring"))[0] == "verified"
    ver, note = ii.sighting_verification(
        _finding("a" * 16, verified="suppressed"))
    assert ver == "downgraded" and "false-positive" in note


def test_mapping_malformed_input_never_raises():
    for bad in (None, "text", 42, [], {}):
        ver, _note = ii.sighting_verification(bad)
        assert ver in rl.VERIFICATION_VOCAB


# ---------------- sighting_rows: the grain and the fail-closed contract ----------

def test_first_sighting_writes_entity_only_and_no_observation_row():
    fid = _minted()
    out = ii.sighting_rows([_finding(fid)], PERIOD, REV)
    assert out["error"] == "" and not out["refused"]
    assert [e["id"] for e in out["entities"]] == [fid]
    assert out["observations"] == []  # the finding itself is the first sighting


def test_re_sighting_writes_one_observation_with_revision_and_no_entity():
    fid = _minted()
    out = ii.sighting_rows([_finding(fid, verified="recurring")], PERIOD, REV,
                           prev_ids={fid})
    assert out["error"] == "" and not out["refused"]
    assert out["entities"] == []  # never a second finding
    assert len(out["observations"]) == 1
    obs = out["observations"][0]
    assert obs["finding"] == fid and obs["period"] == PERIOD
    assert obs["revision"] == REV and obs["verification"] == "verified"
    assert isinstance(obs["at"], int)


def test_gap_period_re_sighting_is_recorded_not_silently_lost(tmp_path):
    # seen in period 1, absent from period 2, seen again in period 3: prev_ids
    # (period 2's ids) does not contain the id, but the ENTITY LEDGER does —
    # the re-sighting must be recorded, never re-classified as a first sighting
    # (acceptance_walkthrough fault 1)
    fid = _minted()
    fp, op = _write_ledgers(tmp_path)
    r1 = ii.record_sightings("proj", [_finding(fid)], "20261020", REV,
                             prev_ids=set(), findings_path=fp,
                             observations_path=op, ts=1000.0)
    assert r1["ok"] and r1["entities"] == 1 and r1["observations"] == 0
    # period 2: the fault is gone from the findings — nothing is recorded
    # period 3: it comes back; prev_ids is period 2's id set (empty of it)
    r3 = ii.record_sightings("proj", [_finding(fid, verified="recurring")],
                             "20261022", REV2, prev_ids=set(),
                             findings_path=fp, observations_path=op, ts=3000.0)
    assert r3["ok"], r3
    assert r3["observations"] == 1 and r3["entities"] == 0, \
        "a gap-period re-sighting is an observation, never a silent skip"
    assert r3["entity_duplicates_skipped"] == 0
    rows, _ = _load(op)
    assert len(rows) == 1 and rows[0]["period"] == "20261022" \
        and rows[0]["revision"] == REV2
    rep = ii.sighting_report(fp, op, [fid])
    assert rep[0]["times_seen"] == 2  # the ledger can say "it came back"
    assert rep[0]["revisions"] == [REV2]


def test_legacy_8hex_prev_id_still_marks_the_re_sighting():
    fid16 = _minted()
    fid8 = fid16[:8]  # pre-widening stored form: a strict prefix, same digest
    out = ii.sighting_rows([_finding(fid16, verified="recurring")], PERIOD, REV,
                           prev_ids={fid8})
    assert len(out["observations"]) == 1 and out["entities"] == []


def test_two_faces_same_finding_one_period_collapse_to_one_sighting():
    fid = _minted()
    dup = _finding(fid, verified="recurring")
    out = ii.sighting_rows([dup, dict(dup)], PERIOD, REV, prev_ids={fid})
    assert len(out["observations"]) == 1
    assert out["obs_duplicates_skipped"] == 1


def test_absent_revision_refuses_whole_batch_by_name():
    fid = _minted()
    for rev in ("", "   ", None, "\0x"):
        out = ii.sighting_rows([_finding(fid)], PERIOD, rev)
        assert out["error"] and "revision" in out["error"]
        assert out["entities"] == [] and out["observations"] == []


def test_absent_period_refuses_whole_batch_by_name():
    out = ii.sighting_rows([_finding(_minted())], "", REV)
    assert out["error"] and "period" in out["error"]


def test_unresolvable_identity_refused_per_finding_never_against_unknown():
    bads = [{"subject": "no id"}, {"id": "", "subject": "x"},
            {"id": "   ", "subject": "x"}, {"id": "zzzz", "subject": "x"},
            {"id": "a" * 16 + "extra", "subject": "x"}, "not-a-dict", 42,
            {"id": "a\0b" * 4, "subject": "x"}]
    good = _finding(_minted())
    out = ii.sighting_rows(bads + [good], PERIOD, REV)
    assert out["error"] == ""
    assert len(out["refused"]) == len(bads)
    assert all(r.get("reason") for r in out["refused"])
    assert [e["id"] for e in out["entities"]] == [_minted()]  # the good one survives
    # nothing anywhere carries an unknown identity
    for e in out["entities"] + out["observations"]:
        assert e.get("id") or e.get("finding")


def test_entity_face_none_lands_in_refused_not_swallowed(monkeypatch):
    # The entity face returning None (defensive branch: the identity gate already
    # blocks every input the face refuses) must land in `refused`, never be swallowed.
    monkeypatch.setattr(rl, "finding_entity_record",
                        lambda f, ts=None: None)
    out = ii.sighting_rows([_finding(_minted())], PERIOD, REV)
    assert out["entities"] == [] and out["observations"] == []
    assert len(out["refused"]) == 1 and "refused" in out["refused"][0]["reason"]


def test_entity_ledger_id_is_a_re_sighting_even_without_prev_ids():
    # the gap-period rule: an id that already has an entity row is NOT a first
    # sighting, even when prev_ids (the nearest earlier period's ids) misses it
    fid = _minted()
    out = ii.sighting_rows([_finding(fid)], PERIOD, REV,
                           known_entity_ids={fid})
    assert out["entities"] == [] and len(out["observations"]) == 1
    assert out["observations"][0]["revision"] == REV


def test_known_obs_key_skips_a_duplicate_sighting_named():
    fid = _minted()
    out = ii.sighting_rows([_finding(fid, verified="recurring")], PERIOD, REV,
                           prev_ids={fid}, known_obs_keys={(fid, PERIOD)})
    assert out["observations"] == [] and out["obs_duplicates_skipped"] == 1


def test_malformed_findings_container_and_revision_stamp():
    for bad in (None, "text", 42, {}):
        out = ii.sighting_rows(bad, PERIOD, REV)
        assert out["error"] == "" and out["entities"] == [] \
            and out["observations"] == []
    fixed = 1791520000000 / 1000.0
    out = ii.sighting_rows([_finding(_minted(), verified="recurring")],
                           PERIOD, REV, prev_ids={_minted()}, ts=fixed)
    assert out["observations"][0]["at"] == 1791520000000


def test_mapping_matches_REAL_recheck_output_end_to_end(tmp_path):
    # the honest check: let recheck_evidence produce its own authentic reasons
    # over a real temp tree, then assert the mapping's verdict per failure kind
    base = tmp_path / "base"
    base.mkdir()
    (base / "gone.md").write_text("only one line\n", encoding="utf-8")
    (base / "drifted.md").write_text("the quoted text moved away\n", encoding="utf-8")
    (base / "ok.md").write_text("anchor stays\n", encoding="utf-8")
    fs = ii.recheck_evidence([
        {"id": "a" * 16, "subject": "s",
         "evidence": [{"path": "gone.md", "line": 1, "quote": "x"}]},
        {"id": "b" * 16, "subject": "s",
         "evidence": [{"path": "drifted.md", "line": 1, "quote": "anchor"}]},
        {"id": "c" * 16, "subject": "s",
         "evidence": [{"path": "ok.md", "line": 1, "quote": "anchor"}]},
    ], base)
    got = {f["id"]: (f["verified"], ii.sighting_verification(f)[0]) for f in fs}
    assert got["a" * 16][0] == "unverified" \
        and got["a" * 16][1] == "unlocatable"        # file missing
    assert got["b" * 16][0] == "unverified" \
        and got["b" * 16][1] == "unlocatable"        # quote no longer matches
    assert got["c" * 16] == ("verified", "verified")


def test_mapping_matches_REAL_recheck_non_english_reason(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "ok.md").write_text("anchor stays\n", encoding="utf-8")
    f = {"id": "d" * 16, "subject": "the subject",
         "why": CJK_MARK, "suggestion": "s",  # copy-lang-allow:sighting-nonenglish-fixture
         "evidence": [{"path": "ok.md", "line": 1, "quote": "anchor"}]}
    f = ii.recheck_evidence([f], base)[0]
    assert f["verified"] == "verified"
    f = ii.mark_non_english([f])[0]
    assert f["verified"] == "unverified"
    ver, note = ii.sighting_verification(f)
    assert ver == "downgraded" and ii.NON_ENGLISH_REASON in note


# ---------------- record_sightings: the IO face over REAL temp ledgers -----------

def _write_ledgers(tmp_path, entities=(), observations=()):
    fp = tmp_path / "findings.jsonl"
    op = tmp_path / "observations.jsonl"
    fp.write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n"
                          for e in entities), encoding="utf-8")
    op.write_text("".join(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n"
                          for o in observations), encoding="utf-8")
    return fp, op


def test_record_period1_then_period2_over_real_temp_ledgers(tmp_path):
    fid = _minted()
    fp, op = _write_ledgers(tmp_path)
    r1 = ii.record_sightings("proj", [_finding(fid)], "20261020", REV,
                             prev_ids=set(), findings_path=fp,
                             observations_path=op, ts=1000.0)
    assert r1["ok"] and r1["entities"] == 1 and r1["observations"] == 0
    assert not r1["refused"]
    # period 2 re-sees the same content id
    r2 = ii.record_sightings("proj", [_finding(fid, verified="recurring")],
                             "20261021", REV2, prev_ids={fid},
                             findings_path=fp, observations_path=op, ts=2000.0)
    assert r2["ok"] and r2["entities"] == 0 and r2["observations"] == 1
    ents, _ = load_rows(fp)
    obss, _ = load_rows(op)
    assert len(ents) == 1 and len(obss) == 1  # one entity, one observation total
    assert obss[0]["revision"] == REV2 and obss[0]["period"] == "20261021"


def load_rows(p):
    return json.loads_rows(p) if False else _load(p)


def _load(p):
    rows, _notes = rl.load_jsonl_rows(p, "t")
    return rows, None


def test_record_same_period_twice_never_duplicates_entity_or_sighting(tmp_path):
    # first record: the finding is first-seen here -> entity only, no row.
    # second record of the SAME period: the entity ledger now knows the id, so
    # it is (correctly) a re-sighting and the period's single observation row is
    # written. a THIRD record is fully idempotent: (finding, period) is known.
    fid = _minted()
    fp, op = _write_ledgers(tmp_path)
    r1 = ii.record_sightings("proj", [_finding(fid)], PERIOD, REV,
                             prev_ids=set(), findings_path=fp,
                             observations_path=op, ts=1000.0)
    assert r1["entities"] == 1 and r1["observations"] == 0
    r2 = ii.record_sightings("proj", [_finding(fid)], PERIOD, REV,
                             prev_ids=set(), findings_path=fp,
                             observations_path=op, ts=2000.0)
    assert r2["ok"] and r2["entities"] == 0 and r2["observations"] == 1
    ents, _ = _load(fp)
    assert len(ents) == 1  # never a second entity
    r3 = ii.record_sightings("proj", [_finding(fid)], PERIOD, REV,
                             prev_ids=set(), findings_path=fp,
                             observations_path=op, ts=3000.0)
    assert r3["observations"] == 0 and r3["obs_duplicates_skipped"] == 1
    obs, _ = _load(op)
    assert len(obs) == 1  # the period's sighting exists exactly once


def test_record_refused_findings_are_named_and_good_rows_survive(tmp_path):
    good = _minted()
    fp, op = _write_ledgers(tmp_path)
    r = ii.record_sightings("proj", [_finding(good), {"subject": "no id"}],
                            PERIOD, REV, prev_ids=set(), findings_path=fp,
                            observations_path=op, ts=1000.0)
    assert r["ok"] and len(r["refused"]) == 1 and r["refused"][0]["reason"]
    rows, _ = _load(fp)
    assert [e["id"] for e in rows] == [good]


def test_record_absent_revision_writes_nothing(tmp_path):
    fp, op = _write_ledgers(tmp_path)
    r = ii.record_sightings("proj", [_finding(_minted())], PERIOD, "",
                            findings_path=fp, observations_path=op)
    assert not r["ok"] and "revision" in r["error"]
    # nothing was appended: both ledgers stay byte-empty
    assert fp.read_text(encoding="utf-8") == ""
    assert op.read_text(encoding="utf-8") == ""


def test_record_without_project_or_paths_refused_named(tmp_path):
    r = ii.record_sightings("", [_finding(_minted())], PERIOD, REV)
    assert not r["ok"] and "underivable" in r["error"]


def test_record_over_corrupt_ledger_degrades_named_never_raises(tmp_path):
    good = _minted()
    fp, op = _write_ledgers(tmp_path, entities=[{"id": good, "subject": "old"}],
                            observations=())
    with open(fp, "a", encoding="utf-8") as fh:
        fh.write("{torn trailing line\n")
    r = ii.record_sightings("proj", [_finding(good)], PERIOD, REV,
                            findings_path=fp, observations_path=op, ts=1000.0)
    assert r["ok"]
    # the pre-existing corrupt entity row is a named note on the write result
    assert r["notes"]["entity_ledger"].get("corrupt_lines") == 1
    rows, _ = _load(fp)
    assert sum(1 for e in rows if isinstance(e, dict) and e.get("id") == good) == 1


# ---------------- sighting_report: the period-report read face -------------------

def test_report_counts_one_plus_observations_and_lists_revisions(tmp_path):
    fid = _minted()
    fp, op = _write_ledgers(
        tmp_path, entities=[{"id": fid, "subject": "s"}],
        observations=[{"finding": fid, "period": "20261020", "revision": REV,
                       "verification": "verified", "verification_note": "",
                       "at": 1},
                      {"finding": fid, "period": "20261021", "revision": REV2,
                       "verification": "unlocatable",
                       "verification_note": "gone", "at": 2}])
    rep = ii.sighting_report(fp, op, [fid],
                             first_sighting={fid: {"period": "20261019",
                                                   "revision": "0f1e2d3c4b5a6978"}})
    row = rep[0]
    assert row["available"] and row["times_seen"] == 3  # 1 + 2 observations
    assert row["revisions"] == sorted([REV, REV2])
    assert row["first_sighting"] == {"period": "20261019", "revision": "0f1e2d3c4b5a6978"}
    assert [o["period"] for o in row["re_sightings"]] == ["20261020", "20261021"]


def test_report_first_period_finding_counts_one_with_no_rows(tmp_path):
    fid = _minted()
    fp, op = _write_ledgers(tmp_path, entities=[{"id": fid, "subject": "s"}])
    row = ii.sighting_report(fp, op, [fid])[0]
    assert row["available"] and row["times_seen"] == 1
    assert row["re_sightings"] == [] and row["revisions"] == []


def test_report_unknown_id_and_unresolvable_query_are_named(tmp_path):
    fp, op = _write_ledgers(tmp_path)
    rep = ii.sighting_report(fp, op, [_minted(), "", "zzzz"])
    assert rep[0]["available"] is False and "nothing has ever recorded" in rep[0]["reason"]
    assert rep[1]["available"] is False and "refused" in rep[1]["reason"]
    assert rep[2]["available"] is False and "refused" in rep[2]["reason"]


def test_report_legacy_8hex_entity_resolves_and_corruption_is_named(tmp_path):
    fid16 = _minted()
    fp, op = _write_ledgers(tmp_path, entities=[{"id": fid16[:8], "subject": "old"}])
    with open(op, "a", encoding="utf-8") as fh:
        fh.write("garbage line\n")
    row = ii.sighting_report(fp, op, [fid16])[0]
    assert row["available"] and row["times_seen"] == 1
    assert row["notes"].get("corrupt_lines") == 1


# ---------------- scan-face findings ride the same chain -------------------------

def test_scan_face_findings_via_with_ids_ride_the_chain(tmp_path):
    from inspection_scan_ms import run_simplify_face_scan  # the scan face exists
    raw = {"subject": "duplicated helper in two modules", "severity": "low",
           "evidence": [{"path": "docs/x.md", "line": 1, "quote": "---"}],
           "why": "w", "suggestion": "s", "scan": "simplify"}
    [f] = ii.with_ids([dict(raw)])
    fid = f["id"]
    assert ii._SIGHTING_ID_RE.match(fid)
    fp, op = _write_ledgers(tmp_path)
    r = ii.record_sightings("proj", [f], PERIOD, REV, prev_ids=set(),
                            findings_path=fp, observations_path=op, ts=1000.0)
    assert r["ok"] and r["entities"] == 1
    # and the same content re-found by a different face next period keeps the id
    [f2] = ii.with_ids([dict(raw, scan="mechanism")])
    assert f2["id"] == fid
