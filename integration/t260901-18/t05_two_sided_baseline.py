#!/usr/bin/env python3
"""t05 two-sided baseline: a ticket's own write differs from BOTH baselines.

Intent (what this protects): main and the line have DIVERGED. Each side carries
commits the other lacks. A lane sits on its own line and has also synced main.
Measure the write set against one side only and the other side's work is
charged to this ticket as an out-of-set write (measured on t261012-02: vs main
the diff misjudged 3 files of the line; vs the line it misjudged 7 files of
main). The whitelist therefore judges the INTERSECTION of the two three-dot
diffs. Four things must hold:
  (1) neither side's merged-in work is charged to this ticket;
  (2) this ticket's own files are still judged, and a real out-of-set write is
      still red (no false green);
  (3) a file carried by conflict resolution, present on neither side, is still
      red (the KI-01M4PAVBP6E smuggle form is not relaxed);
  (4) base_other absent or equal to base gives a result byte-identical to the
      old caliber (legacy tickets are unchanged).
Plus the wiring: merge_check must really pass the second baseline down.

High-level steps (how to reach and assert):
  Build a repo where the sides diverge: c0 baseline; on main, c1 adds
  main-side.txt (main's own work); the line `lane-line` forks from c0 and c2
  adds line-side.txt (the line's own work); the ticket branch `lane/t05` forks
  from the line tip, c3 adds own/own.txt (this ticket's write), then c4 merges
  main in — so the lane carries both sides' work. Then:
  A  Intersection caliber (base=merge-base(main,br), base_other=merge-base
     (lane-line,br), write_set=own/) -> zero red;
  B  Positive control: narrow the write set to other/ -> exactly one red, this
     ticket's own file (a real out-of-set write is still caught);
  C  Smuggle control: add a file present on neither side -> it must go red,
     while both sides' work is still not charged in the same run;
  D  Legacy control: base_other absent and base_other==base give identical
     readings, and the old caliber DOES charge the line's work (so A's green
     is not a vacuous pass);
  E  Wiring: run the real merge_check (REPO_ROOT at the fake repo), intercept
     the verify_lane call, and assert the payload carries base (line side) and
     base_other (main side), each equal to its own merge-base.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t18lib import (ok, finish, import_engine, VerifyLaneCapture,  # noqa: E402
                    git, make_repo, commit, mkdtemp, rmtree, write_verify_yaml,
                    whitelist_items, verify_lane_code)


def _mb(repo, a, b):
    return git(repo, "merge-base", a, b).stdout.strip()


def main() -> int:
    tmp = mkdtemp()
    try:
        repo = make_repo(tmp)
        write_verify_yaml(repo)
        (repo / "base.txt").write_text("b\n", "utf-8")
        c0 = commit(repo, "c0 baseline")
        git(repo, "branch", "-M", "main")
        (repo / "main-side.txt").write_text("m\n", "utf-8")
        commit(repo, "c1 main-side")                       # main's own work
        git(repo, "branch", "lane-line", c0)               # the line forks from c0
        git(repo, "checkout", "-q", "lane-line")
        (repo / "line-side.txt").write_text("l\n", "utf-8")
        commit(repo, "c2 line-side")                       # the line's own work
        git(repo, "checkout", "-q", "-b", "lane/t05")      # ticket branch from the line tip
        (repo / "own").mkdir()
        (repo / "own" / "own.txt").write_text("o\n", "utf-8")
        commit(repo, "c3 own")                             # this ticket's write
        git(repo, "merge", "-q", "--no-edit", "main")      # sync main: the lane carries both
        br = "lane/t05"
        mb_main = _mb(repo, "main", br)                    # main-side baseline
        mb_line = _mb(repo, "lane-line", br)               # line-side baseline
        ok(mb_main and mb_line and mb_main != mb_line,
           "topology is valid: both baselines exist and differ (%s… / %s…)"
           % (mb_main[:7], mb_line[:7]))

        # A. Intersection caliber: neither side's work is charged to this ticket
        wa = whitelist_items(verify_lane_code(repo, mb_main, ["own/"], base_other=mb_line))
        ok(wa == [], "A: intersection caliber is red-free (neither side's merged-in "
                     "work counts as this ticket's write): %s" % (wa or "[]"))

        # B. Positive control: a real out-of-set write is still red
        wb = whitelist_items(verify_lane_code(repo, mb_main, ["other/"], base_other=mb_line)) or []
        got = [it.get("detail", "") for it in wb]
        ok(len(wb) == 1 and "own/own.txt" in got[0],
           "B: narrowing the write set -> exactly one red, own/own.txt (a real "
           "out-of-set write is caught, no more no less): %s" % (got or "[]"))

        # C. Smuggle control: a file present on neither side must stay red
        (repo / "smuggled.txt").write_text("s\n", "utf-8")
        commit(repo, "c5 smuggled")
        mb_main_c, mb_line_c = _mb(repo, "main", br), _mb(repo, "lane-line", br)
        wc = whitelist_items(verify_lane_code(repo, mb_main_c, ["own/"], base_other=mb_line_c)) or []
        ok(any("smuggled.txt" in it.get("detail", "") for it in wc),
           "C: a file present on neither side is judged red (the intersection "
           "does not let smuggle through): %s" % [it.get("detail", "") for it in wc])
        ok(not any(("main-side.txt" in it.get("detail", "") or
                    "line-side.txt" in it.get("detail", "")) for it in wc),
           "C: in the same run, neither side's work is charged to this ticket")
        git(repo, "reset", "-q", "--hard", "HEAD~1")       # back to a clean state for D

        # D. Legacy control: absent base_other and base_other==base read identically
        d1 = whitelist_items(verify_lane_code(repo, mb_main, ["own/"]))
        d2 = whitelist_items(verify_lane_code(repo, mb_main, ["own/"], base_other=mb_main))
        ok(d1 == d2, "D: base_other==base is byte-identical to absent (legacy unchanged): "
                     "%s vs %s" % (d1, d2))
        # The control must not be vacuous: the old caliber really charges the
        # line's work in this topology, so A's green is meaningful.
        ok(bool(d1) and any("line-side.txt" in it.get("detail", "") for it in d1),
           "D: the old caliber does charge the line's work (the control is non-empty, "
           "so A's green has content): %s" % d1)
        ok(not any("own/own.txt" in it.get("detail", "") for it in (d1 or [])),
           "D: under the old caliber this ticket's own write is still inside the "
           "write set (the control contains only the wrongly charged side)")

        # E. Wiring: the real merge_check must pass the second baseline down
        aa, MergeCheckArgs = import_engine()
        saved = aa.REPO_ROOT
        try:
            aa.REPO_ROOT = repo
            args = MergeCheckArgs(ticket_id="t260901-18-it-t05",
                                  worktree=str(repo), branch=br,
                                  base_ref=c0, write_set=["own/"],
                                  base_other_ref="lane-line")
            with VerifyLaneCapture(aa) as cap:
                asyncio.run(aa.merge_check(args))
        finally:
            aa.REPO_ROOT = saved
        pay = cap.payload or {}
        ok(pay.get("base") == mb_line,
           "E: payload.base is the line-side merge-base (%s…)" % str(mb_line)[:7])
        ok(pay.get("base_other") == mb_main,
           "E: payload.base_other is the main-side merge-base (the second baseline "
           "is really passed down)")
        ok(pay.get("base") != pay.get("base_other"),
           "E: the two baselines really differ (not the same value twice)")
        return finish()
    finally:
        rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())
