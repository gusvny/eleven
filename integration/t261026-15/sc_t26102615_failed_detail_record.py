#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26102615_failed_detail_record.py — a red run's persisted record carries
the failing cases' own evidence (ticket t261026-15).

Run directly:
python3 integration/t261026-15/sc_t26102615_failed_detail_record.py
(cwd = repo root).

Grey-box L3, offline seconds: the REAL run-record write path
(run_scenarios.build_failed_detail / write_run_header through
write_run_record) over a real scenario_ledger store on a tmp dir via
SANDBAR_SCENARIO_LEDGER_DIR; every assertion is read back FROM THE LEDGER
FILE (reader-side, never the writer's return value). Zero docker/Temporal/
browser, never touches 3099/7233. No suite subprocess is spawned — the
planted cases are fixed stub spec rows, so the evidence is deterministic
(no external source, no re-run).

R1  THE ACCEPTANCE LINE — a run with a planted red case leaves, in the
    persisted run header read back from scenario-runs.jsonl, the failing
    case's assertion line and observed value VERBATIM plus its duration.
R2  GREEN ABSENCE — a run whose cases all pass persists a header with NO
    failed_detail key at all (absence, never an empty map).
R3  THE SIZE BOUND — a red case whose tail is megabytes contributes its
    last DETAIL_TAIL_CHARS characters, never its whole log, and the
    assertion survives at the tail's end.
R4  GREEN-WITH-TAILS REFUSES — a green header handed a failed_detail is
    refused at the store write face (failed_detail_on_green), zero bytes
    written for that header (the fake summary the field exists to prevent).

Pre-implementation tree: red is the expected TDD signal; green required at
the integration gate / merge. run_scenarios unimportable = ENV_FAIL exit 2.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def spec_line(name, status, dur_s):
    """The per-case spec line the suite's consumers parse (status pass/fail)."""
    print(json.dumps({
        "name": name, "suite": "t261026-15", "status": status,
        "cause": "unknown", "reason": "", "dur_s": dur_s, "attempt": 1,
        "started": "", "git_sha": "", "evidence": "", "artifacts": [],
    }), flush=True)


try:
    import run_scenarios as rs
    import scenario_ledger as sl
except Exception as _e:  # noqa: BLE001 — the declared environment face
    print("ENV_FAIL [t261026-15-failed-detail-record] exit=2 "
          "run_scenarios/scenario_ledger unimportable: %s: %s"
          % (type(_e).__name__, _e), flush=True)
    sys.exit(2)

CASE = "t260904-04-stale-cache-heal-journey"
ASSERTION = "assert healed == 1, observed 0"
TAIL = ("FAIL [%s] exit=1 (12.3s)\n" % CASE
        + "    " + ASSERTION + "\n"
        + "E           assert 0 == 1\n"
        + "E            +  where 0 = healed_value")


def red_case(name=CASE):
    return {"name": name, "suite": "full", "status": "fail",
            "cause": "unknown", "reason": "", "dur_s": 12.3, "attempt": 1,
            "started": "", "git_sha": "", "evidence": "", "artifacts": []}


def green_case(name="green-case"):
    c = red_case(name)
    c["status"] = "pass"
    return c


COMMIT = "ab" * 20
ENV_FP = hashlib.sha256(b"t261026-15-fixture").hexdigest()
SOURCE = "lane:t261026-15"
BOUND = sl.DETAIL_TAIL_CHARS


def write_run(spec_cases, counts, timings, extra_detail=None):
    """One real run-record write through the production path; the ledger dir
    is already pinned at the tmp store by the caller."""
    detail = rs.build_failed_detail(spec_cases, timings)
    if extra_detail is not None:
        detail = extra_detail
    return rs.write_run_record(
        spec_cases, counts, 9.0, started_at_ms=1_800_000_000_000,
        commit=COMMIT, env_fp=ENV_FP, conc_width=1, pool_config="",
        narrowed=False, failed_detail=detail)


def persisted_headers():
    headers, _bad = sl.read_runs(sl.runs_path())
    return {h["id"]: h for h in headers}


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ[sl.LEDGER_DIR_ENV] = td
        os.environ["SANDBAR_INTEG_LEDGER_SOURCE"] = SOURCE
        os.environ.pop(rs.LEDGER_OWNER_ENV, None)   # never the gate-owned shape

        # ---- R1: the planted red's evidence rides the persisted header ----
        run_id, face = write_run(
            [red_case(), green_case()],
            {"ran": 2, "passed": 1, "failed": 1, "env_failed": 0},
            [{"name": CASE, "tail": TAIL, "dur_s": 12.3}])
        ok(bool(run_id) and face.get("header_written") == 1,
           "R1 write ok (run id %s)" % run_id)
        hdr = persisted_headers().get(run_id or "")
        ok(hdr is not None, "R1 header read back from the ledger FILE")
        detail = (hdr or {}).get("failed_detail") or {}
        ok(set(detail) == {CASE}, "R1 exactly the red case is named")
        entry = detail.get(CASE) or {}
        ok(ASSERTION in entry.get("evidence", ""),
           "R1 assertion line verbatim in the persisted record")
        ok("observed 0" in entry.get("evidence", ""),
           "R1 observed value verbatim in the persisted record")
        ok(entry.get("dur_s") == 12.3, "R1 duration rides beside the tail")

        # ---- R2: a green round carries NO per-case tails ----
        green_id, green_face = write_run(
            [green_case(), green_case("green-case-2")],
            {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0},
            [{"name": "green-case", "tail": "some output"}])
        ok(bool(green_id) and green_face.get("header_written") == 1,
           "R2 green write ok")
        ghdr = persisted_headers().get(green_id or "")
        ok(ghdr is not None and "failed_detail" not in ghdr,
           "R2 green header carries NO failed_detail key")

        # ---- R3: a megabyte tail contributes its bound, not its log ----
        huge = ("x" * 1_000_000) + "\n" + TAIL
        big_id, big_face = write_run(
            [red_case("big-case")],
            {"ran": 1, "passed": 0, "failed": 1, "env_failed": 0},
            [{"name": "big-case", "tail": huge, "dur_s": 1.0}])
        ok(bool(big_id) and big_face.get("header_written") == 1,
           "R3 oversized write ok")
        bhdr = persisted_headers().get(big_id or "")
        ev = (((bhdr or {}).get("failed_detail") or {})
              .get("big-case") or {}).get("evidence", "")
        ok(0 < len(ev) <= BOUND,
           "R3 evidence bounded to %d chars (got %d)" % (BOUND, len(ev)))
        ok(ev.endswith(TAIL.strip()),
           "R3 the assertion survives at the tail's end")

        # ---- R4: green-with-tails is refused at the store write face ----
        fake_id, fake_face = write_run(
            [green_case()],
            {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0},
            [],
            extra_detail={CASE: {"evidence": "fake tail", "dur_s": None}})
        reasons = [r.get("reason", "")
                   for r in (fake_face.get("header_rejected") or [])]
        ok(fake_face.get("header_written", 0) == 0
           and any(r == "failed_detail_on_green" for r in reasons),
           "R4 green-with-tails refused by name at the write face")
        ok(fake_id is not None   # rows were booked; only the header refused
           and (persisted_headers().get(fake_id or "") is None),
           "R4 the refused header never lands")

        # the scenario's own verdict rows (suite consumer face)
        spec_line("t261026-15-failed-detail-record", "fail" if FAIL else "pass",
                  0.0)
        print("SUMMARY pass=%d fail=%d env_fail=0" % (PASS, FAIL), flush=True)
        return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
