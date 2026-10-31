#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26103131_failing_leg_record.py — a red case's persisted record NAMES
its failing legs (ticket t261031-14, KI-439; carried by ticket t261031-31).
Transplanted to ticket t261031-31 (the re-created workflow of ticket
t261031-14) and moved under its own ticket directory: the own-scenario
derivation is PATH-KEYED (run_scenarios.own_set_entries matches
`integration/<ticket_id>/` in the registry command), so a case living in
the cancelled ticket's directory belongs to nobody (KI-445). The registry
ENTRY NAME stays `t261031-14-...` (other faces anchor it).

Run directly:
python3 integration/t261031-31/sc_t26103131_failing_leg_record.py
(cwd = repo root).

Grey-box L3, offline seconds: the REAL write path (run_scenarios.
parse_case_legs / build_failed_detail through write_run_record) over a real
scenario_ledger store projected to a tmp dir via SANDBAR_SCENARIO_LEDGER_DIR.
Every assertion is read back FROM THE LEDGER FILE (`scenario-runs.jsonl`), never
from the writer's return value. No suite subprocess, no docker/Temporal/browser,
never touches 3099/7233.

The incident this entry exists for: the 22:15Z round booked
t261022-14-review-panel-face red with SUMMARY pass=17 fail=12, and the retained
evidence was the last ~1200 characters of that case's log — every line an "ok"
line. Twelve red legs, zero of them nameable from the record.

A1  THE INCIDENT SHAPE, POSITIVE — a red case whose leg rows are printed EARLY
    and whose TAIL holds only ok lines + a SUMMARY: the persisted record names
    every failing leg with one reason line each, read back from the ledger
    file. The same tail parsed on its own names nothing (the incident is
    reproduced by the fixture, so the leg cannot be a tail artifact).
A2  THE GREEN CONTROL — the same round with a passing case persists a header
    with NO failed_detail key at all (the t261026-15 absence rule is intact).
A3  HONESTY ON UNPARSEABLE INPUT — a red case whose output holds no leg row
    records that fact BY NAME (legs_parse == "unrecognized" plus a reason
    line), never a clean-looking empty list; a case that counts failing legs in
    its own SUMMARY without naming them lands as "summary_only" with the count.
A4  THE ENV SHAPE — an ENV_FAIL case in a content-red round carries the SAME
    entry shape with legs_parse == "env_fail" and its ENV_FAIL reason line.
A5  STILL BOUNDED — the leg list never exceeds the store's bound, every reason
    is one short line, the evidence tail keeps its 1200-char bound, and a
    louder red (more leg rows than the bound) says how many it omitted.

Pre-implementation tree: red is the expected TDD signal; green required at the
integration gate / merge. run_scenarios/scenario_ledger unimportable =
ENV_FAIL exit 2.
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
NAME = "t261031-14-failing-leg-record"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def spec_line(name, status, dur_s, evidence=""):
    print(json.dumps({
        "name": name, "suite": "t261031-14", "status": status,
        "cause": "unknown", "reason": "", "dur_s": dur_s, "attempt": 1,
        "started": "", "git_sha": "", "evidence": evidence,
        "artifacts": [],
    }), flush=True)


try:
    import run_scenarios as rs
    import scenario_ledger as sl
except Exception as _e:  # noqa: BLE001 — the declared environment face
    print("ENV_FAIL [%s] exit=2 run_scenarios/scenario_ledger unimportable: "
          "%s: %s" % (NAME, type(_e).__name__, _e), flush=True)
    sys.exit(2)

COMMIT = "ab" * 20
ENV_FP = hashlib.sha256(b"t261031-14-fixture").hexdigest()
SOURCE = "lane:t261031-14"
BOUND = sl.DETAIL_TAIL_CHARS
LEG_MAX = sl.DETAIL_LEG_MAX
NAME_CHARS = sl.DETAIL_LEG_NAME_CHARS
REASON_CHARS = sl.DETAIL_LEG_REASON_CHARS

LEGS = [
    ("P1/dark md-click opens reviewer", "click did not open the reviewer"),
    ("P3/dark four block kinds persist to lane file", "done=2 expected=4"),
    ("P5/dark edited block: thread survives or is outdated",
     "outdated=0 stillVisible=false"),
    ("P6/dark minimap marks + open counts + click", "nav missing"),
    ("P7/dark TOC lists h1 and h2", "h2 count 0"),
    ("P8/dark lane path + agent notice", "lane path missing from the panel"),
    ("P9/dark rail collapse control", "rail-toggle missing"),
    ("X1 zero pageerror", "pageerror count: 2"),
]


def red_case(name, evidence=""):
    return {"name": name, "suite": "full", "status": "fail",
            "cause": "self", "reason": "assert_mismatch", "dur_s": 12.3,
            "attempt": 1, "started": "", "git_sha": "",
            "evidence": evidence, "artifacts": []}


def env_case(name, evidence=""):
    return {"name": name, "suite": "full", "status": "not-checked",
            "cause": "external", "reason": "other", "dur_s": 3.0,
            "attempt": 1, "started": "", "git_sha": "",
            "evidence": evidence, "artifacts": []}


def green_case(name="green-case"):
    c = red_case(name)
    c["status"] = "pass"
    return c


def case_output(legs, n_ok=40, summary_fail=None):
    """The measured shape: leg rows FIRST, then a long run of ok lines (so the
    bounded tail holds NO leg row — exactly the t261022-14 record)."""
    lines = ["  FAIL %s — %s" % (leg, reason) for leg, reason in legs]
    lines += ["  ok P2/dark row %02d — added blocks: 3" % i
              for i in range(n_ok)]
    if summary_fail is not None:
        lines.append("SUMMARY pass=%d fail=%d env_fail=0 na=0"
                     % (n_ok, summary_fail))
    return "\n".join(lines) + "\n"


def timings_row(name, out, dur_s=12.3, env_like=False):
    """One timings row as the suite's emit site builds it: the bounded tail
    plus the leg block read from the FULL output (t261031-14)."""
    return {"name": name, "tail": out[-1200:], "dur_s": dur_s,
            "legs": rs.parse_case_legs(out, env_like=env_like)}


def write_run(spec_cases, counts, timings, detail=None):
    """One real run-record write through the production path; the ledger dir is
    already pinned at the tmp store by the caller."""
    if detail is None:
        detail = rs.build_failed_detail(spec_cases, timings)
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

        # ---- A1: the incident shape — the record NAMES the red legs ----
        case = "t261022-14-review-panel-face"
        out = case_output(LEGS, n_ok=40, summary_fail=len(LEGS))
        trow = timings_row(case, out)
        ok(not any(("  FAIL %s" % leg) in trow["tail"] for leg, _r in LEGS),
           "A1 fixture reproduces the incident: NO red leg row survives in the "
           "bounded tail")
        ok(rs.parse_case_legs(trow["tail"]).get("legs_parse")
           in ("unrecognized", "summary_only"),
           "A1 the tail alone names no leg (unrecognized / summary_only) - a "
           "tail cannot answer this question")
        red_id, red_face = write_run(
            [red_case(case), green_case()],
            {"ran": 2, "passed": 1, "failed": 1, "env_failed": 0}, [trow])
        ok(bool(red_id) and red_face.get("header_written") == 1,
           "A1 the red round's header was written (run id %s)" % red_id)
        hdr = persisted_headers().get(red_id or "")
        ok(hdr is not None, "A1 header read back from the ledger FILE")
        entry = ((hdr or {}).get("failed_detail") or {}).get(case) or {}
        ok(entry.get("legs_parse") == "parsed",
           "A1 the persisted entry says parsed (got %r)"
           % (entry.get("legs_parse"),))
        names = [row.get("leg") for row in entry.get("legs") or []
                 if isinstance(row, dict)]
        for leg, _reason in LEGS:
            ok(leg in names,
               "A1 persisted record NAMES the failing leg %r" % (leg[:48],))
        reasons = {row.get("leg"): row.get("reason")
                   for row in entry.get("legs") or [] if isinstance(row, dict)}
        ok(all(isinstance(reasons.get(leg), str) and reasons.get(leg)
               for leg, _r in LEGS),
           "A1 every named leg carries one reason line")
        ok(reasons.get(LEGS[1][0]) == LEGS[1][1],
           "A1 the reason line is the case's own text verbatim")
        ok(entry.get("dur_s") == 12.3, "A1 the duration rides beside the legs")
        ok(0 < len(entry.get("evidence") or "") <= BOUND,
           "A1 the evidence tail is still the auxiliary bound (%d chars)"
           % len(entry.get("evidence") or ""))

        # ---- A2: the green control — no detail key at all ----
        g_id, g_face = write_run(
            [green_case(), green_case("green-case-2")],
            {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0},
            [{"name": "green-case", "tail": "some output",
              "legs": rs.parse_case_legs("  ok a\n")}])
        ok(bool(g_id) and g_face.get("header_written") == 1,
           "A2 green write ok (run id %s)" % g_id)
        g_hdr = persisted_headers().get(g_id or "")
        ok(g_hdr is not None and "failed_detail" not in g_hdr,
           "A2 green header carries NO failed_detail key (absence, read back "
           "from the FILE)")

        # ---- A3: unparseable and summary-only are NAMED, never empty ----
        bad_out = "total nonsense line one\ntotal nonsense line two\n"
        sum_out = case_output([], n_ok=29, summary_fail=12)
        b_id, b_face = write_run(
            [red_case("unparseable-case", evidence="total nonsense line two"),
             red_case("summary-only-case", evidence="SUMMARY fail=12")],
            {"ran": 2, "passed": 0, "failed": 2, "env_failed": 0},
            [timings_row("unparseable-case", bad_out),
             timings_row("summary-only-case", sum_out)])
        ok(bool(b_id) and b_face.get("header_written") == 1,
           "A3 the unparseable round's header was written")
        b_hdr = persisted_headers().get(b_id or "")
        b_detail = (b_hdr or {}).get("failed_detail") or {}
        un = b_detail.get("unparseable-case") or {}
        ok(un.get("legs_parse") == "unrecognized",
           "A3 a red with no parsable leg row records unrecognized by name")
        ok(isinstance(un.get("legs_note"), str) and un["legs_note"].strip(),
           "A3 it carries the reason line naming what was looked for")
        ok("legs" not in un,
           "A3 never a clean-looking empty leg list (no legs key at all)")
        so = b_detail.get("summary-only-case") or {}
        ok(so.get("legs_parse") == "summary_only",
           "A3 a case that only counts fails in SUMMARY lands as summary_only")
        ok("fail=12" in (so.get("legs_note") or ""),
           "A3 that note names the count it could not turn into leg names")

        # ---- A4: an ENV_FAIL case carries the same shape + reason line ----
        env_out = ("[ENV_FAIL] stage console unavailable: spawn ENOENT\n"
                   "SUMMARY pass=0 fail=0 env_fail=1 na=0\n")
        e_id, e_face = write_run(
            [red_case("content-red"), env_case("env-red-case")],
            {"ran": 2, "passed": 0, "failed": 1, "env_failed": 1},
            [timings_row("content-red", case_output(LEGS[:2], n_ok=5,
                                                   summary_fail=2)),
             timings_row("env-red-case", env_out, dur_s=3.0, env_like=True)])
        ok(bool(e_id) and e_face.get("header_written") == 1,
           "A4 the mixed round's header was written")
        e_detail = ((persisted_headers().get(e_id or "") or {})
                    .get("failed_detail") or {})
        env_entry = e_detail.get("env-red-case") or {}
        ok(env_entry.get("legs_parse") == "env_fail",
           "A4 the env case rides the SAME shape (legs_parse=env_fail)")
        ok("stage console unavailable" in (env_entry.get("legs_note") or ""),
           "A4 its ENV_FAIL reason line is in the persisted record")
        ok("legs" not in env_entry,
           "A4 an env entry carries no leg list (nothing was measured)")
        ok((e_detail.get("content-red") or {}).get("legs_parse") == "parsed",
           "A4 the content red beside it still names its legs")

        # ---- A5: still bounded ----
        loud = [("leg-%02d" % i, "reason %02d" % i) for i in range(LEG_MAX + 6)]
        l_id, l_face = write_run(
            [red_case("loud-case")],
            {"ran": 1, "passed": 0, "failed": 1, "env_failed": 0},
            [timings_row("loud-case", case_output(loud, n_ok=3))])
        ok(bool(l_id) and l_face.get("header_written") == 1,
           "A5 the loud round's header was written")
        l_entry = (((persisted_headers().get(l_id or "") or {})
                    .get("failed_detail") or {}).get("loud-case") or {})
        legs = l_entry.get("legs") or []
        ok(0 < len(legs) <= LEG_MAX,
           "A5 the leg list is bounded to %d (got %d)" % (LEG_MAX, len(legs)))
        ok(l_entry.get("legs_omitted") == 6,
           "A5 the omitted leg rows are COUNTED (got %r)"
           % (l_entry.get("legs_omitted"),))
        ok(all(len(r.get("leg", "")) <= NAME_CHARS
               and len(r.get("reason", "")) <= REASON_CHARS for r in legs),
           "A5 every leg name and reason line stays inside its bound")

        # the scenario's own verdict rows (suite consumer face)
        spec_line(NAME, "fail" if FAIL else "pass", 0.0)
        print("SUMMARY pass=%d fail=%d env_fail=0" % (PASS, FAIL), flush=True)
        return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
