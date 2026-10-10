"""t261009-71: the finding chain gets its records — ``originates from a
finding`` as a declared relation kind with LIVE consumers.

Coverage:
- vocabulary: the kind is declared (RELATION_KINDS, recorder-permission
  table, evidence ``what`` vocabulary) — "only kinds with a live consumer";
- validator: an originates row validates; the ticket that benefits may not
  record its own origin (relation_self_benefit, fail closed); an unknown
  kind is still refused by name; malformed shapes refused by name;
- both directions over the ledger FILE on disk (never a return value):
  finding face answers "which tickets were opened from me" (exact,
  finding-prefixed and legacy 8-hex forms named); ticket face answers
  "which finding did I come from" through the ONE declared reader
  (relations_of), consumed, never re-implemented;
- a finding id (``finding:``-prefixed, ``fi-``-prefixed, or bare content
  hex) NEVER appears as a ticket on any read face; it is named as a
  finding ref instead;
- the closing rule: a finding is closed when its QUOTED CONTENT IS GONE
  (newest sighting not verified — the models doc's own content-gone
  example is ``downgraded``), not merely when a ticket was opened; the two
  states are distinguishable, and the newest verification is reported
  verbatim so ``downgraded`` and ``unlocatable`` stay named;
- dedupe: a finding already filed under its content-minted id is answered
  (exact and legacy prefix), derived from the entity, not prose;
- degradation by name: absent ledgers, corrupt lines, empty ids — never a
  raise, never a silent guess.

Run: PYTHONPYCACHEPREFIX=.sandbar/pycache python3 -B -m pytest
server/engine/tests/test_t261009_71_finding_relations.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import develop_certify as dc
import develop_promote as dp
import inspection_review_ledger as irl

FID16 = "3d4b305e1f7a9c02"
FID8 = FID16[:8]


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8")
    return path


def _origin_rel(from_ticket="t261009-71", to="finding:" + FID16,
                recorded_by="integration", fid=FID16):
    return dp.record_relation(
        dc.REL_KIND_ORIGINATES, from_ticket, to, recorded_by,
        "opened from the inspection finding",
        {"what": "finding", "ref": fid}, at_ms=1791505000000)


# ---- vocabulary -------------------------------------------------------------


def test_kind_declared_with_recorder_rule_and_evidence_form():
    assert dc.REL_KIND_ORIGINATES == "originates from a finding"
    assert dc.REL_KIND_ORIGINATES in dc.RELATION_KINDS
    assert dc.REL_KIND_ORIGINATES in dc.RELATION_RECORDER_RULES
    assert "finding" in dc.RELATION_EVIDENCE_WHATS
    # the promote half re-exports the same tuple object — no second list
    assert dp.RELATION_KINDS is dc.RELATION_KINDS


def test_existing_three_kinds_unchanged():
    assert dc.REL_KIND_WITHDRAWS == "withdraws"
    assert dc.REL_KIND_REPAIRS == "repairs"
    assert dc.REL_KIND_SUPERSEDES == "supersedes"
    for k in (dc.REL_KIND_WITHDRAWS, dc.REL_KIND_REPAIRS,
              dc.REL_KIND_SUPERSEDES):
        assert dc.RELATION_RECORDER_RULES[k] is dc._relation_recorder_not_beneficiary


# ---- validator --------------------------------------------------------------


def test_originates_row_validates_and_record_relation_builds_it():
    row = _origin_rel()
    clean, why = dc.validate_row(row)
    assert clean is not None and why == ""


def test_benefiting_ticket_cannot_record_its_own_origin():
    # record_relation refuses loudly, so the row is built by hand here —
    # the rule under test lives in the shared validator
    row = dict(_origin_rel())
    row["recorded_by"] = "ticket:t261009-71"
    clean, why = dc.validate_row(row)
    assert clean is None
    assert why.startswith("relation_self_benefit:t261009-71")


def test_originates_row_malformed_shapes_refused_by_name():
    base = _origin_rel()
    for mutate, expect in (
        ({"reason": ""}, "relation_missing_reason"),
        ({"evidence": None}, "relation_missing_evidence"),
        ({"evidence": {"what": "prose", "ref": FID16}},
         "relation_evidence_what_unknown"),
        ({"evidence": {"what": "finding", "ref": ""}},
         "relation_evidence_ref_invalid"),
        ({"recorded_by": "ticket:"}, "relation_recorder_malformed"),
    ):
        row = dict(base)
        row.update(mutate)
        clean, why = dc.validate_row(row)
        assert clean is None, expect
        assert expect in why, why


def test_unknown_kind_still_refused_by_name():
    row = dict(_origin_rel())
    row["kind"] = "blesses"
    clean, why = dc.validate_row(row)
    assert clean is None
    assert why.startswith("kind_unknown")


# ---- both directions, over the ledger file ----------------------------------


def test_finding_face_answers_which_tickets(tmp_path):
    rel = _origin_rel()
    path = _write_jsonl(tmp_path / "p.jsonl", [rel])
    path = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel(to=FID16)])
    out = irl.finding_work_of(path, FID16)
    assert out["available"] is True
    assert [t["ticket"] for t in out["tickets"]] == ["t261009-71"]
    assert out["tickets"][0]["id_form"] == "exact"


def test_finding_face_matches_finding_prefixed_and_legacy_8hex(tmp_path):
    rows = [
        _origin_rel(from_ticket="t261009-72", to="finding:" + FID16),
        _origin_rel(from_ticket="t261009-73", to="fi-" + FID16),
    ]
    # legacy: a stored relation naming the OLD 8-hex id keeps resolving
    legacy = dp.record_relation(
        dc.REL_KIND_ORIGINATES, "t261009-74", FID8, "integration",
        "legacy id form", {"what": "finding", "ref": FID8},
        at_ms=1791505000001)
    rows.append(legacy)
    path = _write_jsonl(tmp_path / "p.jsonl", rows)
    out = irl.finding_work_of(path, FID16)
    got = {t["ticket"]: t["id_form"] for t in out["tickets"]}
    assert got == {"t261009-72": "finding-prefixed",
                   "t261009-73": "finding-prefixed",
                   "t261009-74": "legacy 8-hex prefix"}


def test_ticket_face_answers_which_finding_via_relations_of(tmp_path):
    path = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    out = irl.origin_finding_of(path, "t261009-71")
    assert out["available"] is True
    assert len(out["findings"]) == 1
    assert out["findings"][0]["to"] == "finding:" + FID16
    assert out["findings"][0]["derived"] is False
    # and the finding ref is named as a finding, never as a ticket
    assert out["finding_refs"] == [{"id": out["findings"][0]["id"],
                                    "ref": "finding:" + FID16,
                                    "kind": dc.REL_KIND_ORIGINATES}]


def test_ticket_face_named_refusal_without_origin(tmp_path):
    path = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    out = irl.origin_finding_of(path, "t261009-99")
    assert out["available"] is True and out["findings"] == []
    assert "no originating finding" in out["reason"]


def test_underivable_ledger_path_refused_by_name():
    out = irl.origin_finding_of(None, "t261009-71")
    assert out["available"] is False
    assert out["reason"] != ""


def test_superseded_correction_drops_wrong_origin(tmp_path):
    good = _origin_rel()
    wrong = dp.record_relation(
        dc.REL_KIND_ORIGINATES, "t261009-80", "finding:" + FID16,
        "integration", "wrong attribution",
        {"what": "finding", "ref": FID16}, at_ms=1791505000002)
    fix = dp.record_relation(
        dc.REL_KIND_ORIGINATES, "t261009-80", "finding:" + FID16,
        "integration", "corrected", {"what": "finding", "ref": FID16},
        supersedes_relation=wrong["id"], at_ms=1791505000003)
    path = _write_jsonl(tmp_path / "p.jsonl", [good, wrong, fix])
    out = irl.finding_work_of(path, FID16)
    tickets = [t["ticket"] for t in out["tickets"]]
    assert "t261009-80" in tickets  # the CORRECTING row stays current
    assert sum(1 for t in out["tickets"] if t["ticket"] == "t261009-80") == 1


# ---- a finding id is never a ticket -----------------------------------------


def test_finding_ref_never_mints_a_phantom_ticket(tmp_path):
    for form in ("finding:" + FID16, "fi-" + FID16, FID16, FID8):
        path = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel(to=form)])
        rel = dc.relations_of(irl._current_relations_from_disk(path)[0],
                              "t261009-71")
        assert rel["ticket"] == "t261009-71"
        assert rel["as_benefited"][dc.REL_KIND_ORIGINATES] == [], form
        assert rel["as_actor"][dc.REL_KIND_ORIGINATES], form


def test_reader_notes_finding_refs_rather_than_guessing(tmp_path):
    path = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel(to=FID16)])
    rel = dc.relations_of(irl._current_relations_from_disk(path)[0],
                          "t261009-71")
    assert rel["finding_refs"] == [{"id": rel["as_actor"]
                                    [dc.REL_KIND_ORIGINATES][0]["id"],
                                    "ref": FID16,
                                    "kind": dc.REL_KIND_ORIGINATES}]
    # ...and the ticket face surfaces the same named refs
    out = irl.origin_finding_of(path, "t261009-71")
    assert out["finding_refs"][0]["ref"] == FID16


# ---- the closing rule -------------------------------------------------------


def _entity_and_sightings(tmp_path, sightings):
    findings = tmp_path / "findings.jsonl"
    obs = tmp_path / "observations.jsonl"
    ent = irl.finding_entity_record(
        {"id": FID16, "subject": "lazy path constant",
         "severity": "medium", "scan": "docs-sync",
         "evidence": [{"path": "a/b.py", "line": 3, "quote": "x = 1"}]})
    _write_jsonl(findings, [ent])
    _write_jsonl(obs, [irl.finding_observation_record(
        FID16, per, ver, note, ts=1791505000000 + i * 1000)
        for i, (per, ver, note) in enumerate(sightings)])
    return findings, obs


def test_closed_when_quoted_content_gone_downgraded_doc_example(tmp_path):
    ledger = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    findings, obs = _entity_and_sightings(tmp_path, [
        ("20261008", "verified", ""),
        # the models doc's own content-gone sighting: downgraded, named note
        ("20261009", "downgraded",
         "the quoted line is no longer in the file at that path"),
    ])
    out = irl.finding_closure(ledger, findings, obs, FID16)
    assert out["status"] == "closed_content_gone"
    assert out["work_opened"] is True
    assert out["newest_verification"] == "downgraded"
    assert out["newest_period"] == "20261009"


def test_closed_on_unlocatable_and_tokens_stay_distinguishable(tmp_path):
    ledger = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    findings, obs = _entity_and_sightings(tmp_path, [
        ("20261009", "unlocatable", "file gone"),
    ])
    out = irl.finding_closure(ledger, findings, obs, FID16)
    assert out["status"] == "closed_content_gone"
    assert out["newest_verification"] == "unlocatable"


def test_work_opened_but_content_still_present_is_not_closed(tmp_path):
    ledger = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    findings, obs = _entity_and_sightings(tmp_path,
                                          [("20261009", "verified", "")])
    out = irl.finding_closure(ledger, findings, obs, FID16)
    assert out["status"] == "work_opened_content_present"


def test_open_no_work_vs_never_seen_distinguishable(tmp_path):
    findings, obs = _entity_and_sightings(tmp_path,
                                          [("20261009", "verified", "")])
    out = irl.finding_closure(tmp_path / "absent.jsonl", findings, obs, FID16)
    assert out["status"] == "open_no_work" and out["work_opened"] is False
    out2 = irl.finding_closure(tmp_path / "absent.jsonl",
                               tmp_path / "nf.jsonl",
                               tmp_path / "no.jsonl", FID16)
    assert out2["status"] == "never_seen" and out2["available"] is False
    assert out2["reason"] != ""


def test_entity_without_sightings_named_not_guessed(tmp_path):
    ledger = _write_jsonl(tmp_path / "p.jsonl", [_origin_rel()])
    findings = tmp_path / "findings.jsonl"
    ent = irl.finding_entity_record(
        {"id": FID16, "subject": "s", "severity": "low", "scan": "x",
         "evidence": []})
    _write_jsonl(findings, [ent])
    out = irl.finding_closure(ledger, findings,
                              tmp_path / "observations.jsonl", FID16)
    assert out["status"] == "work_opened_no_sighting"
    assert "zero sightings" in out["reason"]


# ---- dedupe -----------------------------------------------------------------


def test_already_filed_exact_and_legacy_prefix(tmp_path):
    findings, _ = _entity_and_sightings(tmp_path, [])
    out = irl.finding_already_filed(findings, FID16)
    assert out["already_filed"] is True and out["resolution"] == "exact"
    # the widening rule is one-directional BY DECLARATION: a stored 8-hex
    # id resolves to a 16-hex query, never the reverse — history is not
    # renumbered, so a 16-hex entity does not answer an 8-hex query
    out8 = irl.finding_already_filed(findings, FID8)
    assert out8["already_filed"] is False
    findings8 = _write_jsonl(tmp_path / "f8.jsonl", [
        irl.finding_entity_record(
            {"id": FID8, "subject": "old", "severity": "low", "scan": "x",
             "evidence": []})])
    outl = irl.finding_already_filed(findings8, FID16)
    assert outl["already_filed"] is True
    assert outl["resolution"] == "legacy 8-hex prefix"


def test_not_filed_and_absent_ledger_named(tmp_path):
    findings, _ = _entity_and_sightings(tmp_path, [])
    out = irl.finding_already_filed(findings, "b" * 16)
    assert out["already_filed"] is False
    assert "not filed before" in out["reason"]
    out2 = irl.finding_already_filed(tmp_path / "absent.jsonl", FID16)
    assert out2["already_filed"] is False and out2["available"] is True
    assert "finding-entity" in str(out2["notes"])


def test_empty_ids_refused_by_name(tmp_path):
    for fn, args in ((irl.finding_work_of, (tmp_path / "p.jsonl", "")),
                     (irl.origin_finding_of, (tmp_path / "p.jsonl", "")),
                     (irl.finding_closure, (tmp_path / "p.jsonl",
                                            tmp_path / "f", tmp_path / "o",
                                            "")),
                     (irl.finding_already_filed, (tmp_path / "f", ""))):
        out = fn(*args)
        assert out["available"] is False
        assert "refused" in out["reason"]


# ---- degradation by name ----------------------------------------------------


def test_absent_and_corrupt_delivery_ledger_degrade_by_name(tmp_path):
    absent = irl._current_relations_from_disk(tmp_path / "no.jsonl")
    assert absent[0] == [] and "absent" in absent[1]["delivery_ledger_note"]
    p = tmp_path / "torn.jsonl"
    rel = _origin_rel()
    p.write_text(json.dumps(rel) + "\n{torn\n", encoding="utf-8")
    rels, notes = irl._current_relations_from_disk(p)
    assert len(rels) == 1
    assert notes["delivery_ledger_corrupt_lines"] == 1
