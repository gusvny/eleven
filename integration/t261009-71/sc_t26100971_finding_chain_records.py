#!/usr/bin/env python3
"""sc_t26100971_finding_chain_records.py — `originates from a finding`
becomes a declared relation kind with live consumers (ticket t261009-71,
develop-buffer Phase 2 P2-f record half).

Run directly:
python3 integration/t261009-71/sc_t26100971_finding_chain_records.py
(cwd = repo root).

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser,
never touches 3099/7233. Every ledger lives in a temp dir; the real project
store is never written.

The user-perceivable contract this entry owns (ticket spec (1)-(4)):

  A  THE KIND IS DECLARED, THE SAME WAY THE OTHER THREE ARE —
     `originates from a finding` is in the relation vocabulary with an
     entry in the recorder-permission table; a row built through the
     engine's own writer validates, lands in the delivery-ledger FILE, and
     still validates when read back from disk; the existing three kinds
     stay present; an UNKNOWN kind is refused BY NAME; the benefiting
     ticket may not record its own origin (relation_self_benefit
     discipline); evidence may cite the finding ref.

  B  BOTH DIRECTIONS ANSWER, FROM THE LEDGER FILE ON DISK — the ticket's
     face answers "which finding did I come from" and the finding's face
     answers "which tickets were opened from me"; the stored side stays
     ONE direction (reading writes nothing back — the file is
     byte-identical after the read); a corrected (superseded) origin
     relation drops out of both faces; a legacy 8-hex finding id still
     resolves on the finding side (t261009-69 widening discipline).

  C  CLOSING IS BY CONTENT, NOT BY TICKET — the read face distinguishes,
     BY STATUS WORDS, "work opened but the content is still confirmed"
     (work_opened_content_present) from "closed: the quoted content is
     gone" (closed_content_gone) from "no work at all" (open_no_work)
     from "never seen"; the branch is confirmed-vs-not on the NEWEST
     observation, and the newest verification token is reported VERBATIM
     (the models doc's own content-gone sighting is `downgraded` with a
     note naming which check failed — closure keyed only on `unlocatable`
     would leave demonstrably-gone findings open; review_plan comment 1);
     `downgraded` and `unlocatable` stay distinguishable on the face.

  D  NOT FILED TWICE — a finding whose content-minted id is already in the
     entity ledger answers already_filed, from the ENTITY (the id), never
     from prose; a never-seen id answers not-filed; an absent entity
     ledger degrades with a named note.

  E  DEGRADE AND NAME, NEVER SILENT — a corrupt ledger line never raises
     while the good rows survive; malformed relation rows are filtered,
     not crashed on; an absent delivery ledger is a named empty; a
     finding id is never shown as a ticket (an unrelated ticket's face
     stays quiet).

Anchors are the public contract names of develop_certify /
develop_promote / inspection_review_ledger, never line numbers — a
contract-preserving refactor stays green. Intent split: the relation ROW
contract (evidence shape, recorder entitlement, correction mechanics)
belongs to t261009-62 and is only re-proven as far as this kind must obey
it; the two-direction reader's own truth table belongs to t261009-66; the
finding entity/observation ledgers belong to t261009-69 (fixtures here go
through their writers); the freeze-exemption consumer belongs to
t261009-63. Engine modules unimportable = ENV_FAIL exit 2.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


try:
    import develop_certify as dc  # noqa: E402
    import develop_promote as dp  # noqa: E402
    import inspection_inspect as insp  # noqa: E402
    import inspection_review_ledger as rev  # noqa: E402
except Exception as e:  # engine tree absent/unimportable
    print("ENV_FAIL: engine modules unimportable (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(2)

KIND = dc.REL_KIND_ORIGINATES
TICKET = "t261009-71"
OTHER = "t261009-99"
LEGACY_ID = "deadbeef"           # an old 8-hex stored finding id

FINDING = {"subject": "lazy path constant", "severity": "high",
           "scan": "simplify", "why": "it is recomputed",
           "suggestion": "hoist it",
           "evidence": [{"path": "server/engine/x.py", "line": 10,
                         "quote": "P = slow_fn()"}]}

missing = [n for n in ("record_relation", "current_relations")
           if not hasattr(dp, n)]
missing += [n for n in ("RELATION_KINDS", "RELATION_RECORDER_RULES",
                        "relations_of", "read_rows", "validate_row")
            if not hasattr(dc, n)]
missing += [n for n in ("finding_history", "finding_work_of",
                        "origin_finding_of", "finding_closure",
                        "finding_already_filed", "finding_entity_record")
            if not hasattr(rev, n)]
if missing:
    print("FAIL missing contract faces: %s" % ", ".join(missing))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, len(missing)))
    sys.exit(1)


def write_row(ledger, row):
    """Append one row as the JSONL line it must be on disk."""
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def origin_row(fid, rid=None, recorded_by="integration",
               at=1791510000000, **over):
    """A well-shaped originates relation row through the engine's writer."""
    row = dp.record_relation(
        KIND, TICKET, "finding:%s" % fid, recorded_by,
        "the finding named this work's cause",
        {"what": "finding", "ref": fid},
        at_ms=at)
    if rid:
        row["id"] = rid
    row.update(over)
    return row


def put_finding(findings, fid, **over):
    ent = rev.finding_entity_record(dict(FINDING, id=fid, **over))
    if ent:
        write_row(findings, ent)


def observe(observations, f_id, verification, note, period="20261007"):
    write_row(observations, {"finding": f_id, "period": period,
                             "verification": verification,
                             "verification_note": note,
                             "at": 1791520000000})


def refused_by(recorder, *needle):
    """Run a writer-shaped call; return the refusal text, or '' when it
    was accepted. Accepts either a tuple-returning validator or an
    exception-raising writer."""
    try:
        res = recorder()
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)
    if isinstance(res, tuple):
        return res[1] or ""
    return ""


tmp = Path(tempfile.mkdtemp(prefix="sc_t26100971_"))
try:
    ledger = tmp / "delivery.jsonl"
    findings = tmp / "findings.jsonl"
    observations = tmp / "observations.jsonl"

    # ---------- A the kind is declared ----------
    section("A the kind is declared, the same way the other three are")
    ok(KIND in dc.RELATION_KINDS,
       "the vocabulary carries %r" % KIND)
    ok(KIND in dc.RELATION_RECORDER_RULES,
       "the recorder-permission table carries the kind (fail-closed "
       "without an entry is the table's discipline)")
    ok(all(k in dc.RELATION_KINDS
           for k in ("withdraws", "repairs", "supersedes")),
       "the existing three kinds are unchanged and still present")
    ok("finding" in dc.RELATION_EVIDENCE_WHATS,
       "the evidence subject vocabulary admits a finding ref")

    fid = insp.mint_finding_id(FINDING)
    ok(len(fid) >= 16, "the finding id is content-minted (%s...)" % fid[:8])
    row = origin_row(fid)
    ok(row["id"].startswith("rel-") and row["kind"] == KIND,
       "a well-shaped row is accepted through the engine's own writer")
    write_row(ledger, row)
    stored_rows, _bad = dc.read_rows(str(ledger))
    back = dc.validate_row(stored_rows[-1])
    ok(isinstance(back, tuple) and back[0] is not None,
       "the row still validates when read back FROM DISK")

    r_unknown = refused_by(lambda: dp.record_relation(
        "caused by", TICKET, "finding:%s" % fid, "integration",
        "reason", {"what": "finding", "ref": fid}))
    ok("caused by" in r_unknown,
       "an UNKNOWN kind is refused BY NAME (got %r)" % r_unknown)

    r_self = refused_by(lambda: dp.record_relation(
        KIND, TICKET, "finding:%s" % fid, "ticket:" + TICKET,
        "I say I answer it", {"what": "finding", "ref": fid}))
    ok("self_benefit" in r_self,
       "the benefited ticket cannot record its own origin by name "
       "(got %r)" % r_self)

    r_ev = refused_by(lambda: dp.record_relation(
        KIND, TICKET, "finding:%s" % fid, "integration", "reason",
        {"what": "cake", "ref": fid}))
    ok("what" in r_ev,
       "evidence outside the declared subject vocabulary is refused by "
       "name (got %r)" % r_ev)

    # ---------- B both directions, from the ledger file on disk ----------
    section("B both directions answer, from the ledger file on disk")
    write_row(ledger, origin_row(LEGACY_ID, at=1791510000001))

    rows, _ = dc.read_rows(str(ledger))
    ticket_face = dc.relations_of(rows, TICKET)
    ok(any(e.get("kind") == KIND
           for e in ticket_face["as_actor"].get(KIND, [])),
       "the ticket's face answers 'which finding did I come from' "
       "(the stored acting side)")

    disk_before = ledger.read_bytes()
    opening = rev.finding_work_of(str(ledger), fid)
    ok(opening.get("available") is True and
       any(t.get("ticket") == TICKET for t in opening.get("tickets", [])),
       "the finding's face answers 'which tickets were opened from me'")
    ok(opening.get("tickets", [{}])[0].get("id", "").startswith("rel-")
       if opening.get("tickets") else False,
       "each answer cites the relation id, not prose")
    ok(ledger.read_bytes() == disk_before,
       "reading wrote nothing back — the file is byte-identical "
       "(the one stored direction is preserved)")

    legacy = rev.finding_work_of(str(ledger), LEGACY_ID)
    ok(legacy.get("available") is True and
       any(t.get("ticket") == TICKET for t in legacy.get("tickets", [])),
       "a legacy 8-hex stored finding id still resolves on the finding "
       "side (history is not renumbered)")
    ok(all(str(t.get("id_form", "")) for t in legacy.get("tickets", [])),
       "the answer says WHICH naming form matched (id_form is named, "
       "never blank)")
    # a BARE legacy id exercises the prefix rule on the finding face
    bare_leg = tmp / "bare_legacy.jsonl"
    write_row(bare_leg, dict(origin_row(LEGACY_ID, at=1791510000005),
                             to=LEGACY_ID))
    legacy_bare = rev.finding_work_of(str(bare_leg), LEGACY_ID
                                      + fid[:8])
    ok(any("legacy" in str(t.get("id_form", "")) for t in
           legacy_bare.get("tickets", [])),
       "a bare legacy id matching by PREFIX has the rule named on the "
       "answer (id_form names the prefix rule)")

    ticket_ref = rev.origin_finding_of(str(ledger), TICKET)
    ok(ticket_ref.get("available") is True and
       ticket_ref.get("findings"),
       "the ticket's own origin face answers over the ledger FILE "
       "(origin_finding_of)")
    quiet = rev.origin_finding_of(str(ledger), OTHER)
    ok(quiet.get("available") is True and not quiet.get("findings")
       and "reason" in quiet,
       "an unrelated ticket's face stays quiet — BY NAME, never guessed")

    # correction: the origin was wrong; a new row supersedes it
    corr = origin_row(fid, at=1791510000002,
                      reason="wrong finding, corrected")
    corr["supersedes_relation"] = row["id"]
    ok(dc.validate_row(corr)[0] is not None,
       "the correcting row validates")
    write_row(ledger, corr)
    after = rev.finding_work_of(str(ledger), fid)
    ok(all(t.get("id") != row["id"] for t in after.get("tickets", []))
       and any(t.get("id") == corr["id"] for t in after.get("tickets", [])),
       "a corrected origin drops out of the finding's face while the "
       "correcting row shows")
    t_after = dc.relations_of(dc.read_rows(str(ledger)), TICKET)
    ok(all(e.get("id") != row["id"]
           for e in t_after["as_actor"].get(KIND, [])),
       "the corrected origin drops out of the ticket's face too")

    # ---------- C closing is by content, not by ticket ----------
    section("C closing is by content, not by ticket")

    def closure(f):
        return rev.finding_closure(str(ledger), str(findings),
                                   str(observations), f)

    # finding A: work opened, newest sighting still verifies
    put_finding(findings, fid)
    observe(observations, fid, "verified", "the quoted line is still there")
    st_a = closure(fid)
    ok(st_a.get("status") == "work_opened_content_present",
       "work opened + content confirmed = %s (got %r)"
       % ("work_opened_content_present", st_a.get("status")))

    # finding B: the models doc's own content-gone sighting —
    # `downgraded` + the note naming which check failed
    fid_b = insp.mint_finding_id(dict(FINDING, subject="second finding"))
    put_finding(findings, fid_b, subject="second finding")
    write_row(ledger, origin_row(fid_b, at=1791510000003))
    observe(observations, fid_b, "downgraded",
            "the quoted line is no longer in the file at that path")
    st_b = closure(fid_b)
    ok(st_b.get("status") == "closed_content_gone",
       "content-gone (recorded `downgraded`, the models doc's own "
       "example) CLOSES the finding — not only `unlocatable` "
       "(got %r)" % st_b.get("status"))
    ok(st_b.get("newest_verification") == "downgraded",
       "the newest verification token is reported VERBATIM — the tokens "
       "stay distinguishable on the face")

    # finding C: work opened, no sighting at all — named, not closed
    fid_c = insp.mint_finding_id(dict(FINDING, subject="third finding"))
    put_finding(findings, fid_c, subject="third finding")
    write_row(ledger, origin_row(fid_c, at=1791510000004))
    st_c = closure(fid_c)
    ok(st_c.get("status") == "work_opened_no_sighting",
       "work opened but zero sightings is a NAMED state, not a close "
       "(got %r)" % st_c.get("status"))

    # finding D: seen and verified, but no work ever opened
    fid_d = insp.mint_finding_id(dict(FINDING, subject="fourth finding"))
    put_finding(findings, fid_d, subject="fourth finding")
    observe(observations, fid_d, "verified", "still there")
    st_d = closure(fid_d)
    ok(st_d.get("status") == "open_no_work",
       "content confirmed + no originating relation = open_no_work "
       "(got %r)" % st_d.get("status"))

    st_none = closure("ffffffff" * 4)
    ok(st_none.get("status") == "never_seen"
       and st_none.get("available") is False,
       "a never-seen finding answers never_seen by name, never guessed "
       "closed")

    # a ticket alone is NOT a close: drop the newest sighting to
    # verified and the status flips back even though work stays opened
    observe(observations, fid_b, "verified", "re-appeared", period="20261008")
    st_b2 = closure(fid_b)
    ok(st_b2.get("status") == "work_opened_content_present",
       "a NEWER verified sighting reopens — closing tracks the NEWEST "
       "state, not the first ticket")

    # ---------- D not filed twice ----------
    section("D not filed twice")
    d_yes = rev.finding_already_filed(str(findings), fid)
    ok(d_yes.get("already_filed") is True and d_yes.get("available") is True,
       "a finding whose content-minted id is in the entity ledger answers "
       "already_filed")
    d_no = rev.finding_already_filed(str(findings), "e" * 32)
    ok(d_no.get("already_filed") is False,
       "a never-seen id answers not-filed")
    put_finding(findings, LEGACY_ID)   # an old 8-hex entity row
    d_legacy = rev.finding_already_filed(str(findings), LEGACY_ID
                                         + fid[:8])
    ok(d_legacy.get("already_filed") is True
       and "legacy" in str(d_legacy.get("resolution")),
       "the widening rule applies to dedupe too, with the match rule "
       "named (resolution=%r)" % d_legacy.get("resolution"))
    d_absent = rev.finding_already_filed(str(tmp / "nope.jsonl"), fid)
    ok(d_absent.get("already_filed") is False
       and d_absent.get("notes"),
       "an absent entity ledger answers not-filed WITH a named note, "
       "never raises")

    # ---------- E degrade and name, never silent ----------
    section("E degrade and name, never silent")
    bad = tmp / "bad.jsonl"
    bad.write_text(json.dumps(origin_row(fid)) + "\nnot json at all\n",
                   encoding="utf-8")
    try:
        opening_bad = rev.finding_work_of(str(bad), fid)
        ok(opening_bad.get("available") is True
           and opening_bad.get("notes", {}).get(
               "delivery_ledger_corrupt_lines") == 1,
           "a corrupt ledger line never raises — it is counted and NAMED "
           "while the good row still answers")
    except Exception as e:
        ok(False, "a corrupt ledger line RAISED (%s: %s) — degrade, "
                  "never crash" % (type(e).__name__, e))

    empty = rev.finding_work_of(str(tmp / "absent.jsonl"), fid)
    ok(empty.get("available") is True and not empty.get("tickets")
       and "absent" in json.dumps(empty.get("notes")),
       "an absent delivery ledger is a named empty on the finding's face")

    bare = tmp / "bare.jsonl"
    write_row(bare, dict(origin_row(fid), to=fid))   # no finding: prefix
    opening_bare = rev.finding_work_of(str(bare), fid)
    ok(opening_bare.get("tickets")
       and opening_bare["tickets"][0].get("id_form") == "exact",
       "the bare finding-id naming form still resolves on the finding "
       "face (id_form names the form)")
    rel_bare = dc.relations_of(dc.read_rows(str(bare)), TICKET)
    ok(all(e.get("to") == fid
           for e in rel_bare["as_actor"].get(KIND, [])),
       "the ticket's face shows the STORED ref, never rewrites it into "
       "a ticket id")
    other_face = dc.relations_of(dc.read_rows(str(bare)), fid)
    ok(not other_face["as_actor"].get(KIND),
       "a finding id is never shown as a TICKET actor on any face")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
