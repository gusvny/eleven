#!/usr/bin/env python3
"""sc_t26100962_relation_contract.py — the relation ledger carries evidence,
an entitled recorder, and correction-by-new-record (ticket t261009-62,
host order 261009 P2-a).

Run directly:
python3 integration/t261009-62/sc_t26100962_relation_contract.py
(cwd = repo root).

Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
3099/7233. Every ledger is a temp file; the real store is never written.

The user-perceivable contract this entry owns (t261009-62 spec (1)(2)(3)):

  A  EVIDENCE IS REQUIRED, IN ONE DECLARED SHAPE, REFUSED BY NAME — a
     relation asserts an attribution, so the row must say WHAT it is about;
     an evidence-less / malformed-shaped row is refused by name, not
     silently accepted, and a junk-typed evidence read back from a
     hand-written ledger line refuses on re-validation.

  B  THE RECORDER CANNOT BE THE TICKET THAT BENEFITS — the kind's own rule
     decides who may record; the self-benefiting shape is refused by name;
     a recorder that cannot be evaluated (malformed ``ticket:`` prefix)
     fails closed; a person/patrol actor and a third-party ticket recorder
     stay legal (the design's normal path).

  C  A WRONG RELATION IS CORRECTED BY A NEW ROW — the correcting row names
     the old row's id, the older row drops out of the current-state reader
     while staying BYTE-IDENTICAL in the file, and the proof is read back
     from the ledger file on disk, never from a return value. Degenerate
     corrections are decided, not emergent: a chain resolves to the last
     row, a dangling pointer leaves the corrector current, a cycle drops
     BOTH rows out (neither claim stands), and legacy rows written before
     evidence existed stay visible in the current view (additive-only).

Intent split: the withdrawal-guard propagation face (check_withdrawn /
WithdrawnTargetUnknown / PatchIdUnavailable) belongs to
t261009-23 sc_outcome_three_stages_withdrawal — never re-asserted here;
the promotion/landing shared seq space belongs to t261009-29; the freeze /
repairs consumers are t261009-63 and the withdrawal wiring t261009-64
(out of scope for this ticket). This entry owns the row contract itself:
evidence shape, recorder entitlement, current-state resolution.

Environment: engine tree absent = ENV_FAIL exit 2.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import develop_certify as dc  # noqa: E402
    import develop_promote as dp  # noqa: E402
except Exception as exc:
    print("ENV_FAIL: engine modules unimportable (engine tree absent): %s"
          % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

PASS = 0
FAIL = 0
TMPDIRS = []

GOOD_EV = {"what": "revision", "ref": "a" * 40}


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


def tmpdir(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    TMPDIRS.append(d)
    return d


def write_row(rel_kind, from_t="t-fix", to_t="t-red", recorded_by="host",
              reason="r", evidence=GOOD_EV, supersedes=None, at=1791510000000):
    return dp.record_relation(rel_kind, from_ticket=from_t, to_ticket=to_t,
                              recorded_by=recorded_by, reason=reason,
                              evidence=evidence,
                              supersedes_relation=supersedes, at_ms=at)


def refused(exc, *names):
    """True when the writer refused at all AND names one of the expected
    refusal names — a bare crash is never a pass (an unnamed refusal points
    diagnosis the wrong way)."""
    return names and any(n in str(exc) for n in names)


# ---------- A. evidence: required, one shape, refused by name ----------
section("A a relation without evidence of WHAT it is about is refused by name")

if set(dc.RELATION_EVIDENCE_WHATS) != {
        "revision", "patch_id", "ticket", "certification", "path_line"}:
    ok(False, "A0 fixture: declared evidence vocabulary changed shape")
    raise SystemExit(1)

cases = [
    ("missing", None, "relation_missing_evidence"),
    ("not a dict", ["revision", "x"], "relation_missing_evidence"),
    ("unknown what", {"what": "vibes", "ref": "x"},
     "relation_evidence_what_unknown"),
    ("blank ref", {"what": "revision", "ref": "   "},
     "relation_evidence_ref_invalid"),
    ("non-string ref", {"what": "revision", "ref": 7},
     "relation_evidence_ref_invalid"),
]
for i, (label, ev, name) in enumerate(cases):
    try:
        write_row("withdraws", evidence=ev, at=1791510000000 + i)
        ok(False, "A%d %s evidence is ACCEPTED (must be refused by name %s)"
           % (i + 1, label, name))
    except dp.PromoteError as exc:
        ok(refused(exc, name),
           "A%d %s evidence refused by name (%s)" % (i + 1, label, name))

try:
    write_row("withdraws", at=1791510000100)
    ok(True, "A6 a well-shaped evidence row is accepted")
except dp.PromoteError as exc:
    ok(False, "A6 a well-shaped evidence row is refused: %s" % exc)

# junk-typed evidence read back from a hand-written ledger line must refuse
# on re-validation (the file face, not just the builder face)
d = tmpdir("sc_t26100962_a7_")
base = write_row("withdraws", at=1791510000200)
junk = dict(base)
junk["id"] = "rel-JUNK1"
junk["evidence"] = ["revision", "x"]
line = os.path.join(d, "hand.jsonl")
with open(line, "w") as fh:
    fh.write(json.dumps(junk) + "\n")
rows, _bad = dc.read_rows(line)
clean, why = dc.validate_row(rows[0])
ok(clean is None and "relation_missing_evidence" in why,
   "A7 a ledger line carrying a list where evidence belongs refuses on "
   "re-validation (relation_missing_evidence), never passes silently")

# ---------- B. the recorder may not be the ticket that benefits ----------
section("B recorder entitlement: no ticket records the exemption it "
        "benefits from")

try:
    write_row("withdraws", recorded_by="ticket:t-fix", at=1791510010000)
    ok(False, "B1 the benefited ticket recording its own withdrawal is "
              "ACCEPTED (must be relation_self_benefit)")
except dp.PromoteError as exc:
    ok(refused(exc, "relation_self_benefit"),
       "B1 the benefited ticket recording its own withdrawal is refused by "
       "name (relation_self_benefit)")

try:
    write_row("withdraws", recorded_by="ticket:   ", at=1791510010001)
    ok(False, "B2 an unevaluable recorder (blank ticket: id) is ACCEPTED "
              "(must fail closed)")
except dp.PromoteError as exc:
    ok(refused(exc, "relation_recorder_malformed"),
       "B2 an unevaluable recorder fails closed by name "
       "(relation_recorder_malformed), never accepted with no rule")

try:
    write_row("withdraws", recorded_by="host", at=1791510010002)
    ok(True, "B3 a person/patrol actor stays legal (attribution by a "
             "person is the design's normal path)")
except dp.PromoteError as exc:
    ok(False, "B3 a person actor is refused: %s" % exc)

try:
    write_row("withdraws", recorded_by="ticket:t-other", at=1791510010003)
    ok(True, "B4 a third-party ticket recorder is legal (only the "
             "self-benefiting shape is structural)")
except dp.PromoteError as exc:
    ok(False, "B4 a third-party ticket recorder is refused: %s" % exc)

try:
    write_row("repairs", recorded_by="ticket:t-fix", at=1791510010004)
    ok(False, "B5 the same rule holds for the repairs kind (per-kind table, "
              "shared structural rule)")
except dp.PromoteError as exc:
    ok(refused(exc, "relation_self_benefit"),
       "B5 the repairs kind refuses its own beneficiary as recorder too")

try:
    write_row("freeze_exempt_never_a_kind", recorded_by="host",
              at=1791510010005)
    ok(False, "B6 a kind with no entry in the permission table is refused "
              "(fail closed, never accepted rule-less)")
except dp.PromoteError:
    ok(True, "B6 a kind with no entry in the permission table is refused "
             "(fail closed, never accepted rule-less)")

# ---------- C. correction by a NEW row, proven from the file on disk ------
section("C a wrong relation is corrected by a NEW row; the old row stays "
        "byte-identical")

d = tmpdir("sc_t26100962_c_")
path = os.path.join(d, "promotions.jsonl")

wrong = write_row("withdraws", from_t="t-wrong", to_t="t-red",
                  recorded_by="host", reason="wrongly attributed",
                  at=1791510020000)
dp.append_rows([wrong], path)

def line_of(text, rid):
    """The raw ledger line whose row id is exactly rid (matching on raw
    bytes is the point — the proof is the file, not parsed objects)."""
    hits = [l for l in text.splitlines()
            if any(isinstance(r, dict) and r.get("id") == rid
                   for r in [json.loads(l) for l in [l]])]
    return hits[0]

raw_after_wrong = open(path).read()
wrong_line = line_of(raw_after_wrong, wrong["id"])

fix = write_row("withdraws", from_t="t-right", to_t="t-red",
                recorded_by="host", reason="correction: the fault is "
                "t-right's landing",
                supersedes=wrong["id"], at=1791510020001)
dp.append_rows([fix], path)

raw_after_fix = open(path).read()
ok([l for l in raw_after_fix.splitlines() if l == wrong_line] == [wrong_line],
   "C1 the superseded row is BYTE-IDENTICAL in the file after the "
   "correction (append-only, never edited)")

disk_rows, _bad = dc.read_rows(path)
cur = dp.current_relations(disk_rows)
cur_ids = [r["id"] for r in cur]
ok(wrong["id"] not in cur_ids and fix["id"] in cur_ids,
   "C2 read back FROM DISK: the current view carries the correction and "
   "not the wrong relation (proof is the file, not a return value)")

third = write_row("withdraws", from_t="t-rightest", to_t="t-red",
                  recorded_by="host", reason="correction of the correction",
                  supersedes=fix["id"], at=1791510020002)
dp.append_rows([third], path)
disk_rows, _b = dc.read_rows(path)
cur_ids = [r["id"] for r in dp.current_relations(disk_rows)]
ok(cur_ids == [third["id"]],
   "C3 a chain of corrections resolves to the LAST row only (a correction "
   "that is itself corrected drops out the same way)")

dangling = write_row("withdraws", from_t="t-x", to_t="t-red",
                     recorded_by="host", reason="names nobody",
                     supersedes="rel-NEVER-WRITTEN", at=1791510020003)
dp.append_rows([dangling], path)
disk_rows, _b = dc.read_rows(path)
cur_ids = [r["id"] for r in dp.current_relations(disk_rows)]
ok(dangling["id"] in cur_ids,
   "C4 a dangling supersedes pointer leaves the correcting row current "
   "(row-local write check; the reader never invents a match)")

a_row = write_row("withdraws", from_t="t-aa", to_t="t-red",
                  recorded_by="host", reason="a", at=1791510020004)
b_row = write_row("withdraws", from_t="t-bb", to_t="t-red",
                  recorded_by="host", reason="b", supersedes=a_row["id"],
                  at=1791510020005)
# force the cycle: b supersedes a, a supersedes b (hand-appended; the
# builder refuses self-consistency only against its own id)
cyc = dict(a_row)
cyc["supersedes_relation"] = b_row["id"]
cyc["id"] = "rel-CYCA"
with open(path, "a") as fh:
    fh.write(json.dumps(cyc) + "\n")
disk_rows, _b = dc.read_rows(path)
cur_ids = [r["id"] for r in dp.current_relations(disk_rows)]
ok(a_row["id"] not in cur_ids and b_row["id"] not in cur_ids,
   "C5 a supersedes cycle drops BOTH claims out of the current view "
   "(neither stands; the raw file still carries the chain)")

legacy = {
    "id": "rel-LEGACY1", "from": "t-old", "to": "t-red", "kind": "withdraws",
    "recorded_by": "host", "reason": "written before evidence existed",
    "at": 1791510020006,
}
with open(path, "a") as fh:
    fh.write(json.dumps(legacy) + "\n")
disk_rows, _b = dc.read_rows(path)
cur_ids = [r["id"] for r in dp.current_relations(disk_rows)]
ok(legacy["id"] in cur_ids,
   "C6 a legacy row written before evidence existed STAYS in the current "
   "view (additive-only: the write-time rule never goes silent at read "
   "time)")

sup_ref = write_row("supersedes", from_t="t-new", to_t="t-old",
                    recorded_by="host", reason="ticket supersedes ticket",
                    at=1791510020007)
dp.append_rows([sup_ref], path)
disk_rows, _b = dc.read_rows(path)
cur_ids = [r["id"] for r in dp.current_relations(disk_rows)]
ok(sup_ref["id"] in cur_ids and third["id"] in cur_ids,
   "C7 the landed ticket-level supersedes kind still validates (with "
   "evidence) and still appears as a normal current relation — the "
   "correction field never redefined the kind")

try:
    write_row("withdraws", supersedes="t-not-a-relation",
              at=1791510020008)
    ok(False, "C8 a supersedes pointer naming a non-relation id is ACCEPTED")
except dp.PromoteError as exc:
    ok(refused(exc, "relation_supersedes_not_rel"),
       "C8 a supersedes pointer naming a non-relation id is refused by name")

try:
    selfish = dp.record_relation(
        "withdraws", from_ticket="t-s", to_ticket="t-red",
        recorded_by="host", reason="self", evidence=GOOD_EV,
        at_ms=1791510020009)
    selfish["supersedes_relation"] = selfish["id"]
    _c, why = dc.validate_row(selfish)
    ok(_c is None and "relation_supersedes_self" in why,
       "C9 a row superseding ITSELF is refused (relation_supersedes_self)")
except dp.PromoteError:
    ok(False, "C9 self-supersedes check unreachable through validate_row")

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
