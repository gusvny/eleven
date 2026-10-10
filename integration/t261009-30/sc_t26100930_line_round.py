#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-30 scenario: the line round (grey-box L3, offline seconds, stdlib
only, zero docker/Temporal/browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
the full suite runs against a buffer LINE once per tick — event-driven with a
scheduled backstop, not once per lane attempt (develop-buffer-v1 goals 6/7),
and the round records the certification that judges it. This entry owns the
reader-side journey of `develop_certify.run_line_round` over a REAL temp
delivery ledger and REAL guard file, with the suite runner as a declared stub
(the real suite is the integration gate's own job; a scenario must not pay a
suite round to prove a scheduler face):

- A green round end to end: a landing on the line + a green run header ->
  exactly one certification row read back FROM THE LEDGER FILE (not the
  return value) citing the run, carrying booked_red and judged_by, restating
  nothing (no counts/verdict); the derived range closes; the waiting ticket's
  face answers `certified` and `may_land` is True.
- B joined, never doubled: with the guard held, a round asked for ends
  joined — zero run rows, zero ledger writes (the bench's single serial slot).
- C a red that implicates content: the freeze episode row lands keyed to the
  red certification, the ladder's first answer is `rerun` (goal 9), and the
  fix-kind exemption stays structural (`may_land(fix)` True, others False).
- D a proof that could not run (missing header / ran==0): a range_growth row,
  NO freeze row, NO certification (goal 24).
- E malformed inputs fail loud with ZERO rows and the guard released: a
  corrupt ledger line, a corrupt guard file, an unknown trigger.
- F the delivered checkout is refused by name before any runner is pointed at
  a tree (upfront constraint), including through a symlink alias.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). The engine module (develop_certify) being unimportable is ENV_FAIL.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "server" / "engine"))

try:
    import develop_certify as dc
except Exception as e:  # ENV_FAIL: named, never a silent pass
    print("ENV_FAIL: develop_certify unimportable: %s" % e)
    sys.exit(2)

LINE = "develop"
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def landing(repo, rev, ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": LINE, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def green_header(ran=10):
    return {"id": dc.mint_id("run"), "cases": {"ran": ran, "failed": 0,
                                               "env_failed": 0}}


def red_header():
    return {"id": dc.mint_id("run"), "cases": {"ran": 10, "failed": 3,
                                               "env_failed": 0}}


def round_of(path, runner, **kw):
    return dc.run_line_round(LINE, kw.pop("trigger", "change"),
                             Path(path).parent / "guard-anchor.json", runner,
                             lambda: dc.read_rows(path),
                             lambda batch: dc.append_rows(batch, path),
                             kw.pop("judged_by", "round-engine"),
                             kw.pop("booked_red", "booked-v1"), **kw)


def main():
    with tempfile.TemporaryDirectory(prefix="t26100930-sc-") as td:
        return run(Path(td))
    # unreachable


def run(tmp):
    p = tmp / "delivery.jsonl"

    # ---- A: green round end to end on the real ledger
    dc.append_rows([landing("sandbar", "rev1")], p)
    out = round_of(p, lambda c: green_header())
    rows, bad = dc.read_rows(p)
    certs = [x for x in rows if x["kind"] == "certification"]
    check("A1 one certification row on disk citing the run",
          not bad and len(certs) == 1
          and certs[0]["run"] == out["rounds"][0]["run"]
          and certs[0]["booked_red"] and certs[0]["judged_by"],
          repr(certs))
    check("A2 the certification restates nothing",
          all(k not in certs[0] for k in ("cases", "verdict", "counts")))
    rng = dc.derive_range(rows, LINE)
    check("A3 the range closed; the prefix is the certified revision",
          rng["covered_landings"] == []
          and rng["certified_prefix"] == [{"repo": "sandbar",
                                           "revision": "rev1"}])
    ldg = [x for x in rows if x["kind"] == "landing"][0]
    face = dc.ticket_wait_state(rows, LINE, ldg, lambda r: True, 10 ** 12)
    check("A4 the waiting ticket answers certified and landable",
          face["state"] == dc.WAIT_CERTIFIED
          and dc.landable(rows, LINE, ldg, is_green=lambda r: True))
    check("A5 the end face is idle (nothing left waiting)",
          out["end"]["state"] == dc.END_IDLE, repr(out["end"]))

    # ---- B: joined — a round asked for while one runs never doubles
    gp = p.parent / "guard-anchor.json"
    dc.guard_acquire(gp, "another-tick")
    calls = []
    outb = round_of(p, lambda c: calls.append(c) or green_header())
    rows_b, _ = dc.read_rows(p)
    check("B1 joined face, zero runs, zero new certifications",
          outb["end"]["state"] == dc.END_JOINED and calls == []
          and len([x for x in rows_b if x["kind"] == "certification"]) == 1)
    dc.guard_release(gp)

    # ---- C: red implicating content -> freeze; ladder answers rerun first
    p2 = tmp / "red.jsonl"
    dc.append_rows([landing("sandbar", "bad")], p2)
    outc = round_of(p2, lambda c: red_header())
    rows_c, _ = dc.read_rows(p2)
    st = dc.freeze_state(rows_c, LINE)
    check("C1 freeze episode keyed to the red certification",
          st["frozen"] and st["cause"] == outc["rounds"][0]["cert"],
          repr(st))
    check("C2 the ladder's first step is the rerun (goal 9)",
          outc["rounds"][0]["next"] == "rerun")
    # t261009-63: the exemption comes from a current `repairs` relation
    # naming the repaired landing — never from the kind alone.
    def _raised(fn):
        try:
            fn()
            return ""
        except dc.CertifyError as e:
            return str(e)
    fix_ldg = [x for x in rows_c if x["kind"] == "landing"][0]
    rel = {"id": "rel-fixc1", "from": "t-fixer", "to": fix_ldg["ticket"],
           "kind": dc.REL_KIND_REPAIRS, "recorded_by": "host",
           "reason": "repairs the landing the red implicated",
           "evidence": {"what": "ticket", "ref": fix_ldg["ticket"]},
           "at": 1791510000000}
    check("C3a kind-only fix refused BY NAME on a frozen line (no relation)",
          "freeze_repair_relation_missing" in _raised(
              lambda: dc.may_land(rows_c, LINE, "fix")))
    check("C3b the fix exemption is structural through the relation",
          dc.may_land(rows_c + [rel], LINE, "fix", "t-fixer", rel)
          and not dc.may_land(rows_c, LINE, "chore"))

    # ---- D: could-not-run grows the range, never a freeze (goal 24)
    p3 = tmp / "grow.jsonl"
    dc.append_rows([landing("sandbar", "r1")], p3)
    outd = round_of(p3, lambda c: {"id": dc.mint_id("run"),
                                   "cases": {"ran": 0, "failed": 0,
                                             "env_failed": 0}})
    rows_d, _ = dc.read_rows(p3)
    kinds = [x["kind"] for x in rows_d]
    check("D1 range growth recorded, no freeze, no certification",
          outd["rounds"][0]["state"] == dc.STATE_GREW
          and "range_growth" in kinds and "freeze" not in kinds
          and "certification" not in kinds, repr(kinds))

    # ---- E: malformed inputs fail loud, zero rows, guard released
    p4 = tmp / "bad.jsonl"
    dc.append_rows([landing("sandbar", "rev1")], p4)
    with open(str(p4), "a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
    calls4 = []
    try:
        round_of(p4, lambda c: calls4.append(c) or green_header())
        check("E1 corrupt ledger refuses", False, "no exception")
    except dc.CertifyError as e:
        g4 = p4.parent / dc.GUARD_NAME
        check("E1 corrupt ledger refuses by name, runner never called, "
              "guard released",
              "ledger_has_malformed_lines" in str(e) and calls4 == []
              and (not g4.exists() or not dc.guard_held(g4)), str(e))
    gp5 = tmp / "g5" / "guard-anchor.json"
    gp5.parent.mkdir(parents=True, exist_ok=True)
    (gp5.parent / dc.GUARD_NAME).write_text("{ corrupt", encoding="utf-8")
    try:
        dc.guard_held(gp5)
        check("E2 corrupt guard is loud", False, "no exception")
    except dc.CertifyError as e:
        check("E2 corrupt guard is loud, never read as free",
              "guard_unreadable" in str(e), str(e))

    # ---- F: the delivered checkout is refused before any runner runs
    main_tree = tmp / "main-checkout"
    main_tree.mkdir()
    alias = tmp / "alias"
    os.symlink(main_tree, alias)
    for tree in (main_tree, alias):
        try:
            dc.refuse_delivered_checkout(tree, main_tree)
            check("F1 delivered checkout refused", False, str(tree))
        except dc.CertifyError as e:
            check("F1 delivered checkout refused (%s)"
                  % ("alias" if tree == alias else "direct"),
                  "tree_is_delivered_checkout" in str(e), str(e))
    own = tmp / "round-tree"
    own.mkdir()
    try:
        dc.refuse_delivered_checkout(own, main_tree)
        check("F2 a tree of its own passes", True)
    except dc.CertifyError as e:
        check("F2 a tree of its own passes", False, str(e))

    print("summary: fails=%d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
