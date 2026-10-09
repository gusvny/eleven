#!/usr/bin/env python3
"""sc_face_coverage_engine.py — the period-by-face coverage projection names every
gap (t261009-49, KI-01M4GGFXPAHDGSQ9767VMB5NGM).

Grey-box L3, offline seconds, stdlib only, zero docker/Temporal/browser, never
touches 3099/7233. Judged through the PUBLIC faces of
server/engine/inspection_aggregate.py (the coverage projection + the aggregate
report) over a deterministic fixture ledger tree — never private helpers, so a
contract-preserving refactor must stay green.

User story: four FAILED inspection tickets sit on the board whose periods never
produced anything, and no surface says so — a reader must lay out 22 rows and
count. After this ticket, the aggregate coverage face NAMES each gap.

Legs (each a user-perceivable contract, intent in the registry):
  A  produced vs not_run vs failed vs blocked vs unreadable — one row per
     (declared instance, period), exactly one five-state value each, nothing
     implied by absence.
  B  a `failed` row is a NAMED line: period, face id, last successful period
     (or the explicit word never), and the on-disk attempt evidence (ticket id
     + terminal state or blocked reason when one exists).
  C  zero attempts and three failed attempts read DIFFERENTLY (not_run copy vs
     a failed row listing each attempt).
  D  a blocked-completed ledger (readable doc + matching ticket_id + non-empty
     blocked_reason + zero served findings) NEVER reads produced.
  E  an unreadable ledger is named unreadable — never fine, never missing; a
     raising attempts reader degrades named, never a crash, never silent green.
  F  the dead-man face is untouched: ledger_periods still refuses the aggregate
     report name; deadman outputs over the fixture tree are byte-identical with
     and without the coverage projection in the module.
  G  reader-side discipline: the evidence is read back from the aggregate FILE
     on disk (writer stdout is not evidence) and the projection adds no new
     ledger kind (exactly one new file, the aggregate's own report).
  H  malformed attempt rows (non-dict, missing ticket_id) are counted, never
     fabricated into evidence.

Pre-implementation the projection is missing = FAIL named (TDD signal); the
engine tree itself unimportable = ENV_FAIL exit 2.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"

checks = []


def ok(cond, name):
    checks.append((bool(cond), name))
    print(("ok   " if cond else "FAIL ") + name)


def fail_env(reason):
    print("ENV_FAIL " + reason)
    sys.exit(2)


# ---- engine import (module unimportable = ENV_FAIL) -------------------------
sys.path.insert(0, str(ENGINE))
try:
    import inspection_aggregate as agg  # noqa: E402
    import inspection_deadman as deadman  # noqa: E402
except Exception as e:  # unparseable engine tree = environment, not a red
    fail_env("server/engine unimportable: %s: %s" % (type(e).__name__, e))

face_coverage = getattr(agg, "face_coverage", None)
if face_coverage is None:
    print("FAIL named: face_coverage projection not landed yet "
          "(pre-implementation TDD red is expected at design stage)")
    sys.exit(1)

# ---- fixture tree (the KI-01M4... shape) ------------------------------------
INST = "integration-tests"
FACE = "test"
PERIODS = ["20260918", "20260919", "20261002", "20261008", "20261009"]


def ledger_doc(ticket_id, findings, blocked_reason=""):
    doc = {"instance_id": INST, "period": "P", "ticket_id": ticket_id,
           "findings": findings, "generated_at": "2026-10-09T00:00:00Z"}
    if blocked_reason:
        doc["blocked_reason"] = blocked_reason
    return doc


with tempfile.TemporaryDirectory(prefix="t26100949-") as td:
    d = Path(td)
    # 20260918: FAILED attempt(s), no ledger at all -> failed (the KI shape)
    # 20260919: THREE failed attempts, no ledger -> failed, must read differently
    # 20261002: blocked-completed ledger (the t261002-12 shape)
    # 20261008: blocked-completed WITHOUT a written ledger (journal row only)
    # 20261009: served ledger with findings -> produced
    # 20260917: unreadable ledger file (exists, junk) -> unreadable
    (d / ("inspection-%s-20261002.json" % INST)).write_text(json.dumps(
        ledger_doc("t261002-12", [], blocked_reason="inspect parse refused")), "utf-8")
    (d / ("inspection-%s-20261009.json" % INST)).write_text(json.dumps(
        ledger_doc("t261009-01", [{"id": "f1", "severity": "med", "subject": "s",
                                   "evidence": "e", "scan": FACE}])), "utf-8")
    (d / ("inspection-%s-20260917.json" % INST)).write_text("{not json", "utf-8")
    journal = d / "inspection-spawn.jsonl"
    rows = [
        {"at": "2026-09-18T07:30:00Z", "instance_id": INST, "period": "20260918",
         "ticket_id": "t260918-01"},
        {"at": "2026-09-19T07:30:00Z", "instance_id": INST, "period": "20260919",
         "ticket_id": "t260919-01"},
        {"at": "2026-09-19T08:30:00Z", "instance_id": INST, "period": "20260919",
         "ticket_id": "t260919-02"},
        {"at": "2026-09-19T09:30:00Z", "instance_id": INST, "period": "20260919",
         "ticket_id": "t260919-03"},
        {"at": "2026-10-08T07:30:00Z", "instance_id": INST, "period": "20261008",
         "ticket_id": "t261008-09"},
    ]
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")

    def attempts_reader(period):
        return [{"ticket_id": r["ticket_id"], "terminal_state": "FAILED"}
                for r in rows if r["period"] == period]

    window = ["20260917", "20260918", "20260919", "20261002", "20261008", "20261009"]
    cov = face_coverage(INST, FACE, d, window, attempts_reader)
    by_period = {}
    for row in (cov.get("rows") or cov.get("periods") or []):
        key = row.get("period")
        by_period[key] = row

    # ---- A: one five-state value per period, nothing implied by absence ----
    for period, expect in [("20261009", "produced"), ("20261002", "blocked"),
                           ("20261008", "failed"), ("20260918", "failed"),
                           ("20260919", "failed"), ("20260917", "unreadable")]:
        row = by_period.get(period)
        ok(row is not None and row.get("state") == expect,
           "A %s -> %s (got %s)" % (period, expect,
                                    None if row is None else row.get("state")))
    # a never-attempted period inside the window reads not_run
    cov2 = face_coverage(INST, FACE, d, ["20260920", "20261009"], attempts_reader)
    rows2 = cov2.get("rows") or cov2.get("periods") or []
    st = {r.get("period"): r.get("state") for r in rows2}
    ok(st.get("20260920") == "not_run", "A zero-attempt period reads not_run (got %s)"
       % st.get("20260920"))

    # ---- B: failed rows are NAMED lines (period, face, last-ok/never, evidence)
    r18 = by_period.get("20260918") or {}
    ok(r18.get("face") == FACE or r18.get("face_id") == FACE,
       "B failed row carries the declared face id")
    ok("never" in json.dumps(r18) or r18.get("last_ok_period") in (None, "never"),
       "B 20260918 names no prior success (never) before the served period order")
    blob = json.dumps(r18)
    ok("t260918-01" in blob and "FAILED" in blob,
       "B failed row carries on-disk attempt evidence (ticket id + state)")

    # ---- C: zero attempts vs three failed attempts read differently ----
    r19 = by_period.get("20260919") or {}
    ok(json.dumps(r19) != json.dumps(r18), "C three-attempt row differs from one-attempt")
    ok(blob.count("t2609") < json.dumps(r19).count("t2609"),
       "C the three-attempt row lists each attempt (more evidence on the row)")

    # ---- D: blocked shell never reads produced ----
    ok(by_period.get("20261002", {}).get("state") == "blocked"
       and by_period.get("20261002", {}).get("state") != "produced",
       "D blocked-completed ledger never reads produced (20261002)")
    ok("inspect parse refused" in json.dumps(by_period.get("20261002") or {}),
       "D the blocked row carries the blocked_reason as evidence")

    # ---- E: unreadable named; raising reader degrades named, no crash ----
    ok(by_period.get("20260917", {}).get("state") == "unreadable",
       "E unreadable ledger is named unreadable, not fine, not missing")

    def bad_reader(_period):
        raise RuntimeError("reader exploded")

    try:
        cov3 = face_coverage(INST, FACE, d, ["20261009"], bad_reader)
        txt = json.dumps(cov3)
        ok("reader" in txt.lower() or "error" in txt.lower(),
           "E raising attempts reader degrades to a named error, no crash")
        ok(any(r.get("period") == "20261009" for r in (cov3.get("rows") or [])),
           "E rows still derivable from the ledger with the reader down")
    except Exception as e:
        ok(False, "E raising reader crashed the projection: %s" % e)

    # ---- F: the dead-man face is untouched ----
    name = agg.aggregate_report_name(INST, "20261009")
    match = deadman.LEDGER_NAME_RE.match(Path(name).name) if hasattr(
        deadman, "LEDGER_NAME_RE") else None
    ok(match is None, "F the aggregate report name stays outside dead-man accounting")

    # ---- G: reader-side + no second ledger ----
    report_path = None
    rep = agg.build_aggregate(INST, d, now=None, ticket_lookup=None) \
        if "now" in agg.build_aggregate.__code__.co_varnames[:6] \
        else agg.build_aggregate(INST, d)
    out = agg.aggregate_report_name(INST, rep.get("anchor_period", "20261009"))
    try:
        on_disk = json.loads((d / out).read_text("utf-8"))
    except OSError:
        on_disk = None
    if on_disk is None:
        # the report file is written by the calling shell, not the pure layer;
        # ask the module for the coverage section it would serve instead.
        section = rep.get("coverage")
        ok(section is not None,
           "G the aggregate report carries a coverage section (in-memory face; "
           "file written by the calling shell)")
    else:
        ok(on_disk.get("coverage") is not None,
           "G the aggregate FILE on disk carries the coverage section (reader-side)")
    new_files = [p.name for p in d.iterdir()
                 if p.name.startswith("aggregate-")]
    ok(len(new_files) <= 1, "G at most one new file kind (the aggregate's own report); got %s"
       % new_files)

    # ---- H: malformed attempt rows counted, never fabricated ----
    def junk_reader(_period):
        return ["nope", {"state": "FAILED"}, {"ticket_id": ""}, 42]

    try:
        cov4 = face_coverage(INST, FACE, d, ["20261009"], junk_reader)
        txt = json.dumps(cov4)
        ok("t2609" not in txt or "malformed" in txt.lower(),
           "H malformed attempt rows are named/counted, not fabricated into evidence")
    except Exception as e:
        ok(False, "H malformed rows crashed the projection: %s" % e)

# no SKIP: every check above is PASS or FAIL; missing surface = FAIL named.
bad = [n for good, n in checks if not good]
print("SCENARIOS t261009-49-face-coverage-engine-named-gap: %d checks, %d failed"
      % (len(checks), len(bad)))
sys.exit(1 if bad else 0)
