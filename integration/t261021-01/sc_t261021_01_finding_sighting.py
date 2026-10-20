#!/usr/bin/env python3
"""sc_t261021_01_finding_sighting.py — the finding sighting record (t261021-01).

Ticket: a finding SEEN AGAIN in a later period leaves no record today — the
inspection ledger cannot say "this fault came back, against this revision".
Design source: docs/reference/ledger-record-models-v1.md section D (finding
observation, proposed). Accepted plan rev2 (review_plan gen1 pass) declares
this surface in server/engine/inspection_inspect.py:

  sighting_rows(findings, period, revision, ...)   pure builder
  record_sightings(project_key, findings, period, revision,
                   prev_ids=None, findings_path=None, observations_path=None)
  sighting_report(findings_path, observations_path, finding_ids,
                  first_sighting=None)

over the existing store faces in inspection_review_ledger.py
(finding_ledger_path, FINDINGS_LEDGER_NAME="findings.jsonl",
OBSERVATIONS_LEDGER_NAME="observations.jsonl").

Grey-box L3 (understands the sighting grain, binds only to the public faces
and the on-disk ledger rows — the reader side, never writer receipts).
Offline seconds; zero docker / Temporal-server / browser; never touches
3099/7233.

Run: python3 integration/sc_t261021_01_finding_sighting.py   (cwd = repo root)

Pre-implement tree red = the named TDD signal (declared surface absent is a
FAIL naming the missing face, not an anonymous crash); green required at the
integration gate / merge.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root (file lives two levels under integration/)
sys.path.insert(0, str(ROOT / "server" / "engine"))

import inspection_inspect as insp  # noqa: E402
import inspection_review_ledger as rled  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


def declared_surface():
    """The accepted plan's declared faces; a missing one is a NAMED fail."""
    missing = [n for n in ("sighting_rows", "record_sightings", "sighting_report")
               if not hasattr(insp, n)]
    if missing:
        print("FAIL: declared sighting surface absent in inspection_inspect.py: %s"
              % ", ".join(missing))
        print("(pre-implement tree red is the named TDD signal for t261021-01)")
        sys.exit(1)


def load_rows(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text("utf-8").splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def digest(paths):
    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        h.update(p.read_bytes() if p.exists() else b"<absent>")
    return h.hexdigest()


def finding(subject, path, line, quote, severity="med"):
    return {"subject": subject, "severity": severity, "scan": "integ-sc",
            "evidence": [{"path": path, "line": line, "quote": quote}],
            "why": "the cited page is not registered",
            "suggestion": "register it"}


RECUR = finding("doc page exists but is not registered in docs/index.json",
                "docs/design/a.md", 1, "---")
FRESH = finding("roadmap milestone table still names a retired milestone",
                "docs/design/b.md", 7, "| M9 |")
GAP = finding("lint gate copy still carries the retired Chinese wording",
              "docs/design/c.md", 3, "# 见")
PERIOD1, REV1 = "20261020", "aaaa1111"
PERIOD2, REV2 = "20261021", "bbbb2222"
PERIOD3, REV3 = "20261022", "cccc3333"


def main():
    declared_surface()
    with tempfile.TemporaryDirectory(prefix="sc_t261021_01_") as tmp:
        fp = Path(tmp) / rled.FINDINGS_LEDGER_NAME
        op = Path(tmp) / rled.OBSERVATIONS_LEDGER_NAME
        KW = {"findings_path": str(fp), "observations_path": str(op)}

        insp.with_ids([RECUR, FRESH, GAP])
        ok(RECUR["id"] and len(RECUR["id"]) == 16, "content ids minted (16 hex)")
        ok(len(GAP["id"]) == 16, "the gap-period fixture mints its id too")

        # ---- A. first sighting: entity rows ONLY, no sighting row ----
        section("A first sighting = the finding itself, no observation row")
        notes1 = insp.record_sightings("t261021-01-sc", [RECUR, FRESH, GAP],
                                       PERIOD1, REV1, **KW)
        ents = load_rows(fp)
        obs = load_rows(op)
        ok({e["id"] for e in ents} == {RECUR["id"], FRESH["id"], GAP["id"]},
           "all findings have entity rows after period 1")
        ok(obs == [], "period 1 writes ZERO observation rows (the finding is the "
                      "first sighting)")
        ok(not any("unknown" in json.dumps(n1) for n1 in [notes1]),
           "period-1 notes never record anything against 'unknown'")

        # ---- B. re-seen in a later period: one row, revision pinned ----
        section("B a finding seen again is recorded, against its revision")
        rec2 = dict(RECUR)  # same content -> same id across periods
        notes2 = insp.record_sightings("t261021-01-sc", [rec2], PERIOD2, REV2,
                                       prev_ids=[RECUR["id"]], **KW)
        obs = load_rows(op)
        ents_after = load_rows(fp)
        ok(len(obs) == 1, "exactly one sighting row for the re-seen finding")
        row = obs[0]
        ok(row.get("finding") == RECUR["id"], "the row joins the finding identity")
        ok(row.get("period") == PERIOD2, "the row names the seeing period")
        ok(row.get("revision") == REV2,
           "the row pins the revision it was seen at (%s)" % REV2)
        ok(len(ents_after) == len(ents),
           "no second entity — the re-sighting adds no entity row")
        ok(not ({"subject", "evidence", "why", "suggestion"} & set(row)),
           "the sighting never duplicates the finding text")

        # ---- B2. gap-period re-sighting: seen, absent, seen again ----
        # (acceptance_walkthrough fault 1: prev_ids only carries the NEAREST
        # earlier period's ids; the entity ledger must decide recurrence too,
        # else the ledger silently loses "this fault came back")
        section("B2 a gap-period re-sighting is recorded, never silently lost")
        before_b2 = (len(load_rows(fp)), len(load_rows(op)))
        notes_b2 = insp.record_sightings("t261021-01-sc", [dict(GAP)],
                                         PERIOD3, REV3,
                                         prev_ids=[RECUR["id"]],  # period 2's ids: GAP absent from it
                                         **KW)
        obs_b2 = [r for r in load_rows(op)
                  if r.get("finding") == GAP["id"]]
        ents_b2 = load_rows(fp)
        ok(len(obs_b2) == 1,
           "the gap-period re-sighting writes its observation row (writer-says-ok"
           " / reader-sees-nothing is the shape this fixes)")
        ok(obs_b2 and obs_b2[0].get("period") == PERIOD3
           and obs_b2[0].get("revision") == REV3,
           "the gap-period row pins (finding, period, revision)")
        ok(len(ents_b2) == before_b2[0],
           "still no second entity for the gap-period re-sighting")
        rep_b2 = insp.sighting_report(str(fp), str(op), [GAP["id"]],
                                      first_sighting={GAP["id"]: {
                                          "period": PERIOD1, "revision": REV1}})
        fr = rep_b2[0] if isinstance(rep_b2, list) and rep_b2 else {}
        ok(fr.get("times_seen") == 2,
           "the read face answers 'seen 2 times' across the gap")

        # ---- C. the period report answers 'how often / at which revisions' ----
        section("C the read face answers 'how many times, at which revisions'")
        rep = insp.sighting_report(str(fp), str(op), [RECUR["id"], FRESH["id"]],
                                   first_sighting={RECUR["id"]: {
                                       "period": PERIOD1, "revision": REV1}})
        by_id = {r.get("finding"): r for r in rep} if isinstance(rep, list) else {}
        rep_recur = by_id.get(RECUR["id"])
        rep_fresh = by_id.get(FRESH["id"])
        ok(rep_recur is not None and rep_recur.get("available") is True,
           "the report carries the recurring finding")
        ok(rep_recur is not None and rep_recur.get("times_seen") == 2,
           "the recurring finding answers 'seen 2 times'")
        ok(rep_recur is not None and REV2 in (rep_recur.get("revisions") or []),
           "the report lists the revision it was re-seen at")
        ok(rep_recur is not None
           and (rep_recur.get("first_sighting") or {}).get("revision") == REV1,
           "the first sighting's revision is named in the report, not on a row")
        ok(rep_fresh is not None and rep_fresh.get("times_seen") == 1,
           "a first-period-only finding answers 'seen 1 time' without a row")

        # ---- D. fail-closed: absent revision refuses the WHOLE batch ----
        section("D fail-closed: absent revision refused by name, nothing written")
        before = digest([fp, op])
        notes_d = insp.record_sightings("t261021-01-sc", [RECUR], PERIOD2,
                                        None, **KW)
        ok(digest([fp, op]) == before,
           "an absent revision writes nothing (byte-identical ledgers)")
        ok("unknown" not in json.dumps(load_rows(op)),
           "no sighting is ever recorded against 'unknown'")
        ok(bool(notes_d) and json.dumps(notes_d) != "{}",
           "the refusal is named in the returned notes")

        # ---- E. fail-closed: unresolvable identity refused by name ----
        section("E fail-closed: unresolvable finding identity refused per finding")
        bad = {"subject": "", "evidence": []}  # no mintable identity
        n_before_e = len(load_rows(op))
        notes_e = insp.record_sightings("t261021-01-sc", [bad], PERIOD2, REV2,
                                        **KW)
        obs_e = load_rows(op)
        ok(len(obs_e) == n_before_e,
           "the unresolvable finding gets no sighting row (row count unchanged)")
        ok(bool(notes_e) and "refus" in json.dumps(notes_e).lower(),
           "the refusal names the refused finding (refused list in notes)")

        # ---- F. malformed input: named refusal, never a raise ----
        section("F malformed input degrades named, never crashes")
        for label, payload in (
                ("non-dict entry", ["not a dict"]),
                ("NUL in id", [{"id": "a\0b", "subject": "s"}]),
                ("empty batch", [])):
            try:
                n = insp.record_sightings("t261021-01-sc", payload, PERIOD2,
                                          REV2, **KW)
                ok(True, "%s handled without raising" % label)
            except Exception as e:  # noqa: BLE001
                ok(False, "%s raised %s" % (label, type(e).__name__))

        # ---- G. cross-face same-period collapse: one problem, one sighting ----
        section("G two faces, same content, one period = one sighting")
        dup = dict(RECUR)
        insp.record_sightings("t261021-01-sc", [dup], PERIOD2, REV2,
                              prev_ids=[RECUR["id"]], **KW)
        obs_g = [r for r in load_rows(op) if r.get("period") == PERIOD2
                 and r.get("finding") == RECUR["id"]]
        ok(len(obs_g) == 1, "a same-period duplicate adds no second row")

        # ---- H. idempotent rewrite of a past period ----
        section("H re-recording an already-recorded period changes nothing")
        n_obs = len(load_rows(op))
        notes_h = insp.record_sightings("t261021-01-sc", [RECUR], PERIOD2, REV2,
                                        prev_ids=[RECUR["id"]], **KW)
        ok(len(load_rows(op)) == n_obs, "no duplicate rows after the re-record")
        ok(bool(notes_h) and json.dumps(notes_h) != "{}",
           "the duplicate re-record is named in the notes (obs_duplicates_skipped)")

    print("\n%d passed, %d failed" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
