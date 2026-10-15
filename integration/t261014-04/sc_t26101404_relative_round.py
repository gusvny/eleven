#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261014-04 scenario: the inline relative certification caliber at the round
level (grey-box L2/L3, offline seconds, stdlib only, zero docker/Temporal/
browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
the line round judges the line RELATIVE to main. Green means "the line
introduces no new fail name against main's baseline". Main's standing debt is
carried, not counted against the line. The baseline is one suite run cached by
main's EXACT tip. Ticket t261014-04 exists because a stale line read main's
debt as its own regression and the line froze over it.

This entry drives the REAL round entry (`develop_certify.run_line_round`) with
`project` set, over a REAL project store, a REAL git checkout with branch
`main`, a REAL delivery ledger and a REAL guard file. The suite runner is a
declared stub (the real suite is the integration gate's own job). Every claim
is read back FROM DISK or from the round's own records; a writer's receipt is
not evidence here.

- A carried debt reads GREEN and is NAMED. The line's fail set is a subset of
  main's baseline, plus one roster-listed flaky name. The verdict is green, the
  certification row cites the run and restates nothing, no freeze opens, the
  run record on disk carries the three-way detail (carried_debt /
  new_regressions / flaky_hits), and the baseline was built once keyed by
  main's tip.
- B one new regression reads RED and is NAMED. new_regressions holds exactly
  the new name, carried_debt still names main's debt, and exactly one freeze
  episode opens keyed to that certification. A and B differ by one name, so
  the pair pins the discriminator: carried debt alone never freezes.
- C the baseline cache is keyed by main's exact tip. Round 2 hits the cache and
  the baseline suite does NOT run again (the common round stays one run). A
  main move rebuilds the baseline under the NEW tip, so a stale cache is never
  read.
- D an unbuildable baseline is fail-closed. The round reads RED with the reason
  named, and no cache entry is written, so a later round retries instead of
  trusting a failed baseline. A guessed green is impossible on this path.

Intent split (no intent-level duplication): the absolute round journey (green
round, red -> freeze ladder, range growth, slot/chain, delivered-checkout
refusal) belongs to `t261009-30-line-round` and its siblings; the runner's own
name-set derivation belongs to t261009-77 and t261013-04; the round's live face
belongs to t261011-26. THIS entry owns the round's RELATIVE judgment, the
baseline cache keyed by main's tip, and the three-way record read back from
disk.

Cost tier: the `ro` pool, seconds, offline, no docker, no browser, no
exclusive pool. The whole case runs against temp fixtures; it never writes the
repository.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). A missing engine module, a missing git binary, or an unusable project
store is ENV_FAIL.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))

#: Project key prefix of the fixture stores (shared.PROJECT_KEY_RE shape);
#: each bench appends its own tag, so the benches never share a store.
PROJECT_PREFIX = "itg-rel-261014"
LINE = "develop"
FAILS = []

try:
    import develop_certify as dc
except Exception as e:  # ENV_FAIL: named, never a silent pass
    print("ENV_FAIL: develop_certify unimportable: %s" % e)
    sys.exit(2)

if not ENGINE.is_dir():
    print("ENV_FAIL: engine tree missing at %s" % ENGINE)
    sys.exit(2)
try:
    _g = subprocess.run(["git", "--version"], capture_output=True, text=True,
                        timeout=60)
except OSError as e:
    print("ENV_FAIL: git unavailable: %s" % e)
    sys.exit(2)
if _g.returncode != 0:
    print("ENV_FAIL: git unusable: %s" % (_g.stderr or "")[:200])
    sys.exit(2)


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def git(args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                       text=True, timeout=120)  # SANCTIONED-WAIT: a ceiling on a bounded local git call (no condition is waited on; the bench asserts from the store right after it returns)
    if p.returncode != 0:
        raise AssertionError("git %s failed: %s"
                             % (" ".join(args), (p.stderr or p.stdout)[-300:]))
    return (p.stdout or "").strip()


class Bench:
    """One fixture store: a real git checkout with branch main (the baseline's
    key source), a real delivery ledger, a real guard file, a real run record
    path, and a stub runner that answers by the requested revision."""

    def __init__(self, root, tag):
        self.root = root / tag
        # The store lives under the env-overridden projects root: that is the
        # directory shared.develop_dir() resolves, so the baseline cache and the
        # fixture repo must both sit there.
        self.projects = Path(os.environ["SANDBAR_PROJECTS_DIR"])
        self.key = "%s-%s" % (PROJECT_PREFIX, tag)
        self.wt = (self.projects / self.key / "data" / "develop" / "wt"
                   / "sandbar")
        self.wt.mkdir(parents=True)
        git(["init", "-q"], self.wt)
        git(["config", "user.email", "itg@example.invalid"], self.wt)
        git(["config", "user.name", "itg"], self.wt)
        (self.wt / "main.txt").write_text("main base\n", encoding="utf-8")
        git(["add", "main.txt"], self.wt)
        git(["commit", "-q", "-m", "main base"], self.wt)
        git(["branch", "-M", "main"], self.wt)
        self.ledger = self.root / "delivery.jsonl"
        self.guard = self.root / "guard" / dc.GUARD_NAME
        self.guard.parent.mkdir(parents=True)
        self.runs = self.root / "scenario-runs.jsonl"
        self.calls = []
        self.baseline_fails = []
        self.line_fails = []
        self.baseline_ok = True
        #: When set, the round candidate's answer is this raw header instead of
        #: the well-formed one (leg E drives malformed name sets).
        self.raw_line_header = None

    # ---- fixture writes go through the module's own public writers
    def land(self, revision, ticket):
        res = dc.append_rows(
            [{"kind": "landing", "id": dc.mint_id("ldg"), "ticket": ticket,
              "line": LINE, "repos": [{"repo": "sandbar",
                                       "revision": revision}],
              "actor": "itg", "at": 1700000000000 + len(self.rows())}],
            str(self.ledger))
        if res["rejected"]:
            raise AssertionError("fixture landing rejected: %r"
                                 % (res["rejected"],))

    def rows(self):
        rows, bad = dc.read_rows(str(self.ledger))
        if bad:
            raise AssertionError("fixture ledger malformed: %r" % (bad,))
        return rows

    def kinds(self, kind):
        return [r for r in self.rows() if r["kind"] == kind]

    def main_tip(self):
        return git(["rev-parse", "HEAD"], self.wt)

    def move_main(self, note):
        (self.wt / "main.txt").write_text(note + "\n", encoding="utf-8")
        git(["add", "main.txt"], self.wt)
        git(["commit", "-q", "-m", note], self.wt)
        return self.main_tip()

    def header(self, fails, failed=None):
        return {"id": dc.mint_id("run"),
                "cases": {"ran": 10,
                          "failed": len(fails) if failed is None else failed,
                          "env_failed": 0},
                "failed_names": list(fails)}

    def __call__(self, candidate):
        """The declared runner seam: runner(candidate_repos) -> run header."""
        revision = candidate[0]["revision"]
        self.calls.append(revision)
        if revision == self.main_tip():          # the baseline request
            if not self.baseline_ok:
                return {"id": dc.mint_id("run"), "cases": None}
            return self.header(self.baseline_fails)
        if self.raw_line_header is not None:     # a malformed candidate answer
            return dict(self.raw_line_header, id=dc.mint_id("run"))
        return self.header(self.line_fails)

    def round(self, roster=None, trigger="change", chain_limit=None):
        self.calls = []
        extra = {} if chain_limit is None else {"chain_limit": chain_limit}
        return dc.run_line_round(
            line=LINE, trigger=trigger, guard_path=str(self.guard),
            runner=self,
            read_rows=lambda: dc.read_rows(str(self.ledger)),
            append_rows=lambda batch: dc.append_rows(batch, str(self.ledger)),
            judged_by="itg-261014", booked_red="booked-itg-v1",
            runs_store=str(self.runs), project=self.key, roster=roster,
            **extra)


def runs_on_disk(bench):
    p = Path(bench.runs)
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def run(root):
    debt = ["sc_debt_a", "sc_debt_b"]
    roster = {"entries": [{"name": "sc_flaky_a", "verdict": "isolated"}]}

    # ---- A: carried debt reads green, is named, and freezes nothing
    a = Bench(root, "a")
    tip = a.main_tip()
    a.baseline_fails = list(debt)
    a.line_fails = debt + ["sc_flaky_a"]      # main's debt + one known-flaky name
    a.land("line-1", "t-land-1")
    out = a.round(roster=roster)
    entry = out["rounds"][0]
    rel = ((entry.get("relative") or {}).get("per_repo") or {}).get("sandbar") or {}
    check("A1 carried debt reads GREEN (state certified)",
          entry.get("verdict") == "green" and entry.get("state") == dc.STATE_CERTIFIED,
          repr(entry))
    check("A2 main's debt is NAMED as carried and no regression is claimed",
          rel.get("carried_debt") == debt and rel.get("new_regressions") == [],
          repr(rel))
    check("A3 the roster-listed flaky name is NAMED, never read as a regression",
          rel.get("flaky_hits") == ["sc_flaky_a"], repr(rel))
    check("A4 the baseline was built once, keyed by main's exact tip",
          rel.get("note") == "cache_built:sandbar@%s" % tip[:12]
          and a.calls == ["line-1", tip], repr([a.calls, rel.get("note")]))
    cache = dc.baseline_path(a.key, "sandbar", tip)
    check("A5 the cache file exists at the declared path, carrying that tip",
          cache.is_file()
          and json.loads(cache.read_text(encoding="utf-8"))["main_tip"] == tip,
          str(cache))
    certs = a.kinds("certification")
    check("A6 the certification cites the run and restates nothing",
          len(certs) == 1 and certs[0]["run"] == entry["run"]
          and all(k not in certs[0]
                  for k in ("cases", "verdict", "counts", "relative")),
          repr(certs))
    check("A7 no freeze opens over carried debt",
          a.kinds("freeze") == [] and "freeze" not in entry,
          repr(a.kinds("freeze")))
    rr = runs_on_disk(a)
    check("A8 the run record ON DISK carries the round's relative judgment",
          len(rr) == 1 and rr[0].get("verdict") == "green"
          and rr[0].get("relative", {}).get("per_repo", {}).get("sandbar", {})
          .get("carried_debt") == debt, repr(rr))

    # ---- B: one new regression reads red, is named, and freezes
    a.baseline_fails = list(debt)
    a.line_fails = debt + ["sc_new_c"]
    a.land("line-2", "t-land-2")
    out_b = a.round()
    entry_b = out_b["rounds"][0]
    rel_b = entry_b["relative"]["per_repo"]["sandbar"]
    check("B1 one new name reads RED",
          entry_b.get("verdict") == "red" and entry_b.get("state") == dc.STATE_RED,
          repr(entry_b))
    check("B2 new_regressions names exactly it; carried debt stays named",
          rel_b.get("new_regressions") == ["sc_new_c"]
          and rel_b.get("carried_debt") == debt, repr(rel_b))
    fz = a.kinds("freeze")
    check("B3 exactly one freeze episode, keyed to that certification",
          len(fz) == 1 and fz[0].get("cause") == entry_b.get("cert")
          and entry_b.get("freeze") == fz[0]["id"],
          repr([fz, entry_b.get("freeze")]))
    check("C1 the second round hits the cache (no second baseline run)",
          a.calls == ["line-2"]
          and rel_b.get("note") == "cache_hit:sandbar@%s" % tip[:12],
          repr([a.calls, rel_b.get("note")]))

    # ---- C: a main move rebuilds the baseline under the new tip
    tip2 = a.move_main("main moves")
    a.baseline_fails = list(debt)
    a.line_fails = list(debt)
    a.land("line-3", "t-land-3")
    out_c = a.round()
    rel_c = out_c["rounds"][0]["relative"]["per_repo"]["sandbar"]
    cache2 = dc.baseline_path(a.key, "sandbar", tip2)
    check("C2 a main move rebuilds the baseline under the NEW tip",
          tip2 != tip and a.calls == ["line-3", tip2]
          and rel_c.get("note") == "cache_built:sandbar@%s" % tip2[:12]
          and cache2.is_file(),
          repr([tip2[:12], a.calls, rel_c.get("note")]))
    check("C3 the stale cache for the old tip is not read (green, named)",
          out_c["rounds"][0].get("verdict") == "green"
          and rel_c.get("carried_debt") == debt, repr(rel_c))

    # ---- D: an unbuildable baseline is fail-closed, never a guessed green
    d = Bench(root, "d")
    d.baseline_ok = False
    d.baseline_fails = list(debt)
    d.line_fails = list(debt)
    tip_d = d.main_tip()
    d.land("line-1", "t-land-1")
    out_d = d.round()
    entry_d = out_d["rounds"][0]
    rel_d = entry_d["relative"]["per_repo"]["sandbar"]
    check("D1 an unbuildable baseline reads RED with the reason named",
          entry_d.get("verdict") == "red"
          and rel_d.get("note") == "baseline_run_failed:sandbar",
          repr(rel_d))
    check("D2 no cache entry is written for a failed baseline run",
          not dc.baseline_path(d.key, "sandbar", tip_d).exists(),
          str(dc.baseline_path(d.key, "sandbar", tip_d)))
    rr_d = runs_on_disk(d)
    check("D3 the run record on disk reads red, never a fabricated green",
          len(rr_d) == 1 and rr_d[0].get("verdict") == "red", repr(rr_d))

    # ---- E: an unusable line name set is fail-closed (the t261014-04
    #      arbitrate code-fault's regression pin). A name set that is absent, or
    #      empty while the header's own counts report failures, is a proof that
    #      could not be judged: the round grows the range. It is never green
    #      (a stale runner, or the runner's documented empty set when the suite
    #      log is unreadable, would otherwise book a fabricated green that can
    #      reach promotion), and it never spends a baseline run either.
    counts_red = {"cases": {"ran": 10, "failed": 3, "env_failed": 0}}
    for label, raw in (("E1 the name set is ABSENT",
                        dict(counts_red)),
                       ("E2 the name set is EMPTY while 3 cases failed",
                        dict(counts_red, failed_names=[]))):
        e = Bench(root, label[:2].strip().lower())
        e.baseline_fails = list(debt)
        e.raw_line_header = raw
        e.land("line-1", "t-land-1")
        out_e = e.round(chain_limit=1)
        kinds = [r["kind"] for r in e.rows()]
        check("%s -> could-not-run (range growth), not green and not a red"
              % label,
              out_e["rounds"][-1].get("state") == dc.STATE_GREW
              and dc.KIND_RANGE_GROWTH in kinds
              and dc.KIND_CERT not in kinds and dc.KIND_FREEZE not in kinds,
              repr([out_e["rounds"][-1], kinds]))
        check("%s -> no baseline run is spent on an unjudgeable proof" % label,
              e.calls == ["line-1"], repr(e.calls))
        check("%s -> the guard is released" % label,
              (not Path(e.guard).exists()) or not dc.guard_held(str(e.guard)),
              str(e.guard))

    # ---- E3: the positive control — the guard is precise, not blanket. An
    #      empty name set with zero failures is a legitimately clean line and
    #      still reads green.
    e3 = Bench(root, "e3")
    e3.baseline_fails = list(debt)
    e3.raw_line_header = {"cases": {"ran": 10, "failed": 0, "env_failed": 0},
                          "failed_names": []}
    e3.land("line-1", "t-land-1")
    out_e3 = e3.round(chain_limit=1)
    check("E3 an empty name set with zero failures still reads GREEN",
          out_e3["rounds"][-1].get("verdict") == "green"
          and dc.KIND_CERT in [r["kind"] for r in e3.rows()],
          repr(out_e3["rounds"][-1]))
    return 1 if FAILS else 0


def main():
    with tempfile.TemporaryDirectory(prefix="t26101404-sc-") as td:
        root = Path(td)
        old = os.environ.get("SANDBAR_PROJECTS_DIR")
        # An absolute, isolated projects root: the fixture store never touches
        # the real one (shared.perkey_projects_root reads this env fresh).
        os.environ["SANDBAR_PROJECTS_DIR"] = str(root / "projects-root")
        try:
            rc = run(root)
        finally:
            if old is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old
    print("summary: fails=%d" % len(FAILS))
    return rc


if __name__ == "__main__":
    sys.exit(main())
