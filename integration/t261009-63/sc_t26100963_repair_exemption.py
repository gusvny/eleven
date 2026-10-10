#!/usr/bin/env python3
"""sc_t26100963_repair_exemption.py — the repairs relation grows its two
consumers: the freeze exemption asks WHICH landing is repaired, and the
repaired side says who repaired it (ticket t261009-63, host order 261009
P2-b).

Run directly:
python3 integration/t261009-63/sc_t26100963_repair_exemption.py
(cwd = repo root).

Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
3099/7233. Every ledger is a temp file; the real store is never written.

The user-perceivable contract this entry owns (t261009-63 spec (1)(2)(3)):

  A  WITHOUT A RELATION THE EXEMPTION DOES NOT APPLY — on a frozen line a
     fix that merely declares itself a fix cannot land: the refusal names
     the MISSING RELATION, not a generic "no". A malformed repair fact
     (not a dict, wrong kind, foreign ``from``, unresolvable target) is
     refused by name, never guessed into an exemption; a relation never
     mints a kind (a non-exempt kind stays refused with a relation in
     hand); an unfrozen line behaves exactly as before, relation or not.

  B  WITH A CURRENT repairs RELATION NAMING THE LANDING, THE FIX LANDS —
     three naming forms (landing id, ticket id whose landing sits on the
     line, patch identity via an explicit map); a cross-line target is a
     SCOPING refusal (a freeze on L is caused by a red on L, so only L's
     own landing justifies landing into L), not silent acceptance; a
     superseded (corrected) repair relation grants nothing. Proof is read
     back FROM DISK through the real writer/reader, never from a return
     value.

  C  THE REPAIRED SIDE SAYS WHO REPAIRED IT — the outcome view of the
     ticket whose landing (or whose own work) was repaired reports
     ``repaired_by``/``repaired_at`` for every naming form the exemption
     accepts; a patch-id relation that cannot be mapped stays VISIBLE
     (``repaired_unresolved``) instead of silently reading "never
     repaired"; a repair is a fact about the ticket's cause, so it never
     changes ``ending``.

Intent split: the relation ROW contract itself (evidence shape, recorder
entitlement, correction-by-new-record mechanics) belongs to t261009-62 —
never re-asserted here beyond what the consumers need to be proven
correction-aware; the withdrawal wiring consumer belongs to t261009-64;
the freeze open/close decisions belong to t261009-30/-41. This entry owns
the two READ faces the constant never had.

Pre-implementation tree red = FAIL named (TDD signal); green required at
the integration gate / merge. Engine modules unimportable = ENV_FAIL
exit 2.
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

LINE = "develop"
OTHER_LINE = "sandbox"
EV_PATCH = {"what": "patch_id", "ref": "p" * 40}


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


def refused(exc, *names):
    """True when the face refused at all AND names one of the expected
    refusal names — a bare crash is never a pass (an unnamed refusal
    points diagnosis the wrong way)."""
    return names and any(n in str(exc) for n in names)


def landing(ticket, line=LINE, at=1000):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": line, "repos": [{"repo": "r", "revision": "rev-" + ticket}],
            "actor": "test", "at": at}


def freeze_open(at=1100):
    """A red with an open freeze episode on LINE — the minimal honest
    frozen state: the episode is an entity, its closure would be another
    record, and none exists here."""
    cert = {"kind": "certification", "id": dc.mint_id("cert", at),
            "line": LINE, "repos": [{"repo": "r", "revision": "bad"}],
            "run": dc.mint_id("run", at), "booked_red": "booked-v1",
            "judged_by": "round-engine", "at": at}
    ep = {"kind": "freeze", "id": dc.mint_id("frz", at + 1), "line": LINE,
          "cause": cert["id"], "at": at + 1}
    return [cert, ep]


def repair_row(from_t, to_t, at=2000, evidence=None, supersedes=None):
    return dp.record_relation("repairs", from_ticket=from_t, to_ticket=to_t,
                              recorded_by="host", reason="the red is mine",
                              evidence=evidence or {"what": "ticket",
                                                    "ref": to_t},
                              supersedes_relation=supersedes, at_ms=at)


def lp(d):
    """The ledger FILE inside one scenario tmpdir (the store path is a
    file, never the directory itself)."""
    return os.path.join(d, "ledger.jsonl")


def frozen_ledger(d, *extra):
    """Seed a REAL temp ledger with the frozen state plus any extra rows,
    through the engine's own writer, and return the rows READ BACK FROM
    DISK — the reader side of the reader-side-evidence discipline."""
    dc.append_rows(list(freeze_open()) + list(extra), lp(d))
    rows, _b = dc.read_rows(lp(d))
    return rows


def outcome(disk_rows, ticket, patch_ids=None):
    return dp.ticket_outcome(disk_rows, ticket, patch_ids=patch_ids)


# ---------- A. no relation, no exemption ------------------------------------
section("A a self-declared fix cannot land on a frozen line — the refusal "
        "names the missing relation")

d0 = tmpdir("t26100963-a-")
rows = frozen_ledger(d0)
ok(dc.freeze_state(rows, LINE)["frozen"] is True,
   "A0 fixture: the line is frozen (open freeze episode, no closure)")

try:
    dc.may_land(rows, LINE, "fix", ticket="t-fix")
    ok(False, "A1 a kind-only fix on a frozen line is ACCEPTED (must be "
              "refused by name)")
except dc.CertifyError as exc:
    ok(refused(exc, "freeze_repair_relation_missing"),
       "A1 a kind-only fix on a frozen line is refused BY NAME naming the "
       "missing relation (%s)" % exc)

# The three malformed-repair faces, each named, each not an exemption.
bad_repairs = [
    ("not a dict", "junk"),
    ("missing the from key", {"kind": "repairs", "to": "t-red"}),
    ("wrong relation kind",
     {"kind": "withdraws", "from": "t-fix", "to": "t-red", "id": "rel-x",
      "at": 1}),
]
for i, (label, rep) in enumerate(bad_repairs):
    try:
        dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=rep)
        ok(False, "A%d %s repair is ACCEPTED (must be refused by name)"
           % (i + 2, label))
    except dc.CertifyError as exc:
        ok(refused(exc, "repair_relation_not_record",
                   "repair_relation_not_repairs", "repair_from_not_ticket"),
           "A%d %s repair is refused by name (%s)" % (i + 2, label, exc))

try:
    dc.may_land(rows, LINE, "fix", ticket="t-fix",
                repair={"kind": "repairs", "from": "t-other", "to": "t-red",
                        "id": "rel-y", "at": 1})
    ok(False, "A5 a repair relation FROM ANOTHER TICKET is ACCEPTED")
except dc.CertifyError as exc:
    ok(refused(exc, "repair_from_not_ticket"),
       "A5 a foreign-from repair relation is refused by name — the relation "
       "must belong to THIS work (%s)" % exc)

try:
    granted = dc.may_land(rows, LINE, "chore",
                          ticket="t-chore",
                          repair={"kind": "repairs", "from": "t-chore",
                                  "to": "t-red", "id": dc.mint_id("rel", 1),
                                  "at": 1})
    ok(granted is False,
       "A6 a relation never MINTS a kind: chore stays refused (False) with "
       "a well-formed repairs relation in hand")
except dc.CertifyError as exc:
    ok(refused(exc, "ticket_kind_undeclared"),
       "A6 a relation never MINTS a kind: chore stays refused with a valid "
       "repairs relation in hand (%s)" % exc)

# Unfrozen line: byte-for-byte the old contract, relation or not.
d_open = tmpdir("t26100963-a2-")
dc.append_rows([landing("t1", at=500)], lp(d_open))
open_rows, _b = dc.read_rows(lp(d_open))
ok(dc.freeze_state(open_rows, LINE)["frozen"] is False,
   "A7 fixture: the unfrozen line reads unfrozen")
ok(dc.may_land(open_rows, LINE, "fix") is True
   and dc.may_land(open_rows, LINE, "chore") is True,
   "A7 an unfrozen line takes every declared kind without any relation")
ok(dc.may_land(open_rows, LINE, "fix", repair={"kind": "repairs",
                                               "from": "t-fix",
                                               "to": "t1", "id": "rel-a7",
                                               "at": 1}) is True,
   "A8 an unfrozen line ignores a repair fact — nothing changes for any "
   "declared kind when no freeze stands")

# ---------- B. a current relation naming the landing grants the landing -----
section("B with a current repairs relation, the fix lands — read from disk")

d1 = tmpdir("t26100963-b-")
ldg = landing("t-red", at=900)
rel = repair_row("t-fix", ldg["id"], at=2000)
rows = frozen_ledger(d1, ldg, rel)
ok(dc.freeze_state(rows, LINE)["frozen"] is True, "B0 fixture: frozen")
ok(dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=rel) is True,
   "B1 a landing-id-named repairs relation lets the fix land on the "
   "frozen line (rows read back from disk)")

# ticket-named form: the relation names the ticket whose latest landing
# sits on this line.
d2 = tmpdir("t26100963-b2-")
ldg2 = landing("t-red", at=950)
rel2 = repair_row("t-fix", "t-red", at=2001)
rows = frozen_ledger(d2, ldg2, rel2)
ok(dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=rel2) is True,
   "B2 a ticket-named repairs relation (target's latest landing on THIS "
   "line) lets the fix land")

# patch-identity form: only through the caller-supplied explicit map.
d3 = tmpdir("t26100963-b3-")
ldg3 = landing("t-red", at=960)
rel3 = dp.record_relation("repairs", from_ticket="t-fix",
                          to_ticket="t-fix-lands-elsewhere",
                          recorded_by="host", reason="same patch",
                          evidence=EV_PATCH, at_ms=2002)
rows = frozen_ledger(d3, ldg3, rel3)
try:
    dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=rel3)
    ok(False, "B3 a patch-id relation WITHOUT a map is ACCEPTED (must "
              "refuse, never guess)")
except dc.CertifyError as exc:
    ok(refused(exc, "repair_target_unresolved"),
       "B3 a patch-id relation without a patch map is refused by name — "
       "fail-closed, never guessed into an exemption (%s)" % exc)
ok(dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=rel3,
               patch_ids={ldg3["id"]: EV_PATCH["ref"]}) is True,
   "B4 a patch-id relation WITH the explicit map lets the fix land")

# scoping: a target on ANOTHER line is not an exemption for this line.
d4 = tmpdir("t26100963-b4-")
x_ldg = landing("t-red", line=OTHER_LINE, at=970)
x_rel = repair_row("t-fix", x_ldg["id"], at=2003)
rows = frozen_ledger(d4, x_ldg, x_rel)
try:
    dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=x_rel)
    ok(False, "B5 a CROSS-LINE repair target grants the exemption here")
except dc.CertifyError as exc:
    ok(refused(exc, "repair_target_unresolved"),
       "B5 a cross-line target is a SCOPING refusal on this line's freeze "
       "(the relation stays valid project-level; it just names no landing "
       "on THIS line) (%s)" % exc)

# corrections: a superseded repair relation grants nothing, on either face.
d5 = tmpdir("t26100963-b5-")
ldg5 = landing("t-red", at=980)
wrong = repair_row("t-fix", ldg5["id"], at=2004)
fixup = repair_row("t-fix", "t-other-red", at=2005, supersedes=wrong["id"])
rows = frozen_ledger(d5, ldg5, wrong, fixup)
try:
    dc.may_land(rows, LINE, "fix", ticket="t-fix", repair=wrong)
    ok(False, "B6 the superseded (corrected) repair relation STILL grants "
              "the exemption when handed in")
except dc.CertifyError as exc:
    ok(refused(exc, "repair_relation_superseded", "repair_target_unresolved"),
       "B6 a corrected repair relation grants nothing on the freeze face "
       "(corrections are new rows, never edits) (%s)" % exc)
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") is None,
   "B7 the corrected relation leaves the repaired ticket's face without a "
   "repairer — neither consumer reads a dead row")

# ---------- C. the repaired side says who repaired it ------------------------
section("C the beneficiary face: repaired_by / repaired_at, from disk")

d6 = tmpdir("t26100963-c-")
ldg6 = landing("t-red", at=990)
rel6 = repair_row("t-fix", ldg6["id"], at=2006)
rows = frozen_ledger(d6, ldg6, rel6)
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") == "t-fix",
   "C1 the ticket whose LANDING was repaired says who repaired it "
   "(landing-named form, read from disk)")
ok(oc.get("repaired_at") == 2006,
   "C2 repaired_at is the relation's at, not a clock")
ok(oc.get("ending") not in (None,) and oc["ending"] != "repaired",
   "C3 a repair never changes ending — it is a fact about the cause, not "
   "an ending of the work")

d7 = tmpdir("t26100963-c2-")
ldg7 = landing("t-red", at=991)
rel7 = repair_row("t-fix", "t-red", at=2007)
rows = frozen_ledger(d7, ldg7, rel7)
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") == "t-fix",
   "C4 the ticket-named form reads from the same face — either side of "
   "the relation resolves to a readable outcome")

d8 = tmpdir("t26100963-c3-")
ldg8 = landing("t-red", at=992)
rel8 = dp.record_relation("repairs", from_ticket="t-fix",
                          to_ticket="t-any", recorded_by="host",
                          reason="patch identity", evidence=EV_PATCH,
                          at_ms=2008)
rows = frozen_ledger(d8, ldg8, rel8)
oc = outcome(rows, "t-red", patch_ids={ldg8["id"]: EV_PATCH["ref"]})
ok(oc.get("repaired_by") == "t-fix",
   "C5 the patch-id form credits the owner of the patched landing (with "
   "the explicit map)")
oc_nomap = outcome(rows, "t-red")
ok(oc_nomap.get("repaired_by") is None
   and oc_nomap.get("repaired_at") is None,
   "C6 without the map the face refuses to claim: no repairer is named, "
   "never guessed")
ok(bool(oc_nomap.get("repaired_unresolved"))
   and rel8["id"] in oc_nomap.get("repaired_unresolved", []),
   "C7 the unmapped relation stays VISIBLE (repaired_unresolved names the "
   "relation id) — a gap on the record, not silence")

# newest wins; ties break by relation id; invalid at keeps the who, drops
# the when (mirroring superseded_by's honest timestamp face).
d9 = tmpdir("t26100963-c4-")
ldg9 = landing("t-red", at=993)
r_old = repair_row("t-fix", ldg9["id"], at=2009)
r_new = repair_row("t-fix2", ldg9["id"], at=2010)
rows = frozen_ledger(d9, ldg9, r_old, r_new)
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") == "t-fix2",
   "C8 the NEWEST current repair relation wins (the later remedy is the "
   "one that repaired it)")
d10 = tmpdir("t26100963-c5-")
ldg10 = landing("t-red", at=994)
r_a = repair_row("t-fix", ldg10["id"], at=2011)
r_b = repair_row("t-fix2", ldg10["id"], at=2011)
r_b["id"] = "rel-" + "z" * 26  # force the id tie-break, same at
rows = frozen_ledger(d10, ldg10, r_a, r_b)
ok([r["id"] for r in rows].count(r_b["id"]) == 1,
   "C9 fixture: both same-at repair relations are on disk, the z-id one "
   "LAST (the tie-break must pick it by id, not by file order)")
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") == "t-fix2",
   "C9 ties break by relation id (a deterministic answer, not an "
   "execution-order accident)")
d11 = tmpdir("t26100963-c6-")
ldg11 = landing("t-red", at=995)
r_bad = repair_row("t-fix", ldg11["id"], at=2012)
r_bad["at"] = "not-a-ms"
# The writer honestly refuses an invalid-at relation, so the read-face
# case is built the way history actually arrives at it: a legacy /
# hand-written line in the file (the t261009-62 junk-typed read-back
# pattern), never through the writer.
with open(lp(d11), "a") as fh:
    fh.write(json.dumps(ldg11) + "\n")
    fh.write(json.dumps(r_bad) + "\n")
rows, _b = dc.read_rows(lp(d11))
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") == "t-fix" and oc.get("repaired_at") is None,
   "C10 an invalid relation at keeps the WHO honest and drops the WHEN "
   "(repaired_at None) — same conscious trade-off as superseded_by")
d12 = tmpdir("t26100963-c7-")
rows = frozen_ledger(d12)
oc = outcome(rows, "t-red")
ok(oc.get("repaired_by") is None and oc.get("repaired_at") is None
   and not oc.get("repaired_unresolved"),
   "C11 no repair anywhere: the face stays quiet (None, no unresolved "
   "list) — absence is not an error and not a claim")

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
