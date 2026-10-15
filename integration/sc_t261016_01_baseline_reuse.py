#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-01 — the line round reuses (and NAMES) main's baseline across main
tips, and the round face carries the measured wall clock.

Grey-box L3 (integration-owned): the REAL server/engine/develop_certify
``run_line_round`` face driven over a real tmp git repo (the line worktree the
baseline's main-tip resolution reads) with an injected stub runner, real tmp
delivery ledger through the engine's own read/append faces. Offline seconds,
zero docker/Temporal-server/browser, never touches 3099/7233.

Ticket faces under contract (user-perceivable):
  A a main advance that cannot touch the judged surface (docs-only commit)
    reuses the ancestor's cached baseline: ONE suite run (the line run only),
    and the run record NAMES the reuse — baseline_source "reused",
    baseline_tip (measured at) vs judged_tip (reused for), and the
    mechanical note baseline_reused:<repo>@<old12>:for:<new12>.
  B a main advance on the judged surface (server/engine commit) REBUILDS:
    the baseline suite runs, the record says rebuilt at the NEW tip, and the
    NEW fail set is what the line is judged against (old main debt must not
    excuse a failure main no longer carries — the false-green hole).
  C every ambiguity fails closed to a rebuild, never a guessed reuse:
    a corrupted cached baseline JSON and a cached non-ancestor tip each end
    in a rebuild named on the record.
  D the round row carries the measured wall clock (duration_ms, int > 0) so
    the <=30min target is judgeable from the record itself.

Shared fixture technique with the t261009-30 family (tmp repo + stub runner);
the steps are shared, the intent is not: this entry owns the cross-tip reuse
naming, the rebuild-vs-reuse record face, and the wall-clock field.

Pre-implement tree red on A/B/C/D = the named TDD signal; green required at
the integration gate / merge. git unavailable or the engine modules
unimportable = ENV_FAIL exit 2. Scenario contract: PASS/FAIL/ENV_FAIL only —
no SKIP.
"""

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop"


# ---- fixture (shared technique with the t261009-30 family) -----------------

def _git(path, *args):
    p = subprocess.run(["git", "-C", str(path)] + list(args),
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (args[0], p.stderr[:200]))
    return p.stdout.strip()


def _git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=30)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


class Stage:
    """One isolated project store + a real git repo as the line worktree."""

    def __init__(self, root):
        self.root = root
        self.projects = root / "projects"
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.projects)
        self.repo = (self.projects / "sandbar" / "data" / "develop" / "wt"
                     / "sandbar")
        self.repo.mkdir(parents=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "it@t26101601")
        _git(self.repo, "config", "user.name", "it")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "x.md").write_text("d0\n", encoding="utf-8")
        (self.repo / "a.txt").write_text("a0\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "m0")
        self.main_tip = _git(self.repo, "rev-parse", "refs/heads/main")
        self.ledger = root / "delivery.jsonl"
        dc.append_rows([self._landing()], self.ledger)

    def _landing(self):
        return {"kind": "landing", "id": dc.mint_id("ldg", 1),
                "ticket": "t1", "line": LINE,
                "repos": [{"repo": "sandbar", "revision": "rev1"}],
                "actor": "scenario", "at": 1}

    def advance_main(self, rel_path, text, msg):
        p = self.repo / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", msg)
        return _git(self.repo, "rev-parse", "refs/heads/main")

    def runner(self, calls, line_fails, main_fails_by_tip):
        def run(cand):
            rev = cand[0]["revision"]
            calls.append(rev)
            if rev == "rev1":
                return {"id": dc.mint_id("run"),
                        "cases": {"ran": 10, "failed": len(line_fails),
                                  "env_failed": 0},
                        "failed_names": list(line_fails)}
            fails = main_fails_by_tip.get(rev, [])
            return {"id": dc.mint_id("run"),
                    "cases": {"ran": 10, "failed": len(fails),
                              "env_failed": 0},
                    "failed_names": list(fails)}
        return run

    def round(self, runner, trigger="change"):
        """One round on the change trigger (the scheduled round's own shape:
        the candidate derives from the ledger's landings — no line
        declaration fixture needed)."""
        return dc.run_line_round(
            LINE, trigger, str(self.root / "guard.json"), runner,
            lambda: dc.read_rows(self.ledger),
            lambda batch: dc.append_rows(batch, self.ledger),
            "scenario", "booked-v1", project="sandbar",
            roster={"entries": []})

    def reseed_landing(self):
        """A second landing row so a second round has a range to certify."""
        rows, _ = dc.read_rows(self.ledger)
        dc.append_rows([{"kind": "landing",
                         "id": dc.mint_id("ldg", 2), "ticket": "t2",
                         "line": LINE,
                         "repos": [{"repo": "sandbar", "revision": "rev1"}],
                         "actor": "scenario", "at": 2}], self.ledger)

    def rel(self, out):
        return out["rounds"][0]["relative"]["per_repo"]["sandbar"]


# ---- cases -----------------------------------------------------------------

def case_a_named_reuse_after_non_surface_advance(stage):
    """Docs-only main advance -> reuse, named, ONE suite run."""
    old = stage.main_tip
    dc.write_baseline("sandbar", "sandbar", old, ["d1"], [])
    new = stage.advance_main("docs/x.md", "d1\n", "docs only")
    calls = []
    out = stage.round(stage.runner(calls, ["d1"], {}))
    rel = stage.rel(out)
    problems = []
    if out["rounds"][0]["verdict"] != "green":
        problems.append("verdict=%r not green" % out["rounds"][0]["verdict"])
    if calls != ["rev1"]:
        problems.append("suite ran %d times, reuse must run ONE suite: %r"
                        % (len(calls), calls))
    if rel.get("baseline_source") != "reused":
        problems.append("baseline_source=%r not 'reused' (silent or missing "
                        "naming)" % rel.get("baseline_source"))
    if rel.get("baseline_tip") != old:
        problems.append("baseline_tip=%r not the measured-at tip"
                        % rel.get("baseline_tip"))
    if rel.get("judged_tip") != new:
        problems.append("judged_tip=%r not the reused-for tip"
                        % rel.get("judged_tip"))
    note = rel.get("note", "")
    if not note.startswith("baseline_reused:sandbar@%s:for:%s"
                           % (old[:12], new[:12])):
        problems.append("note=%r does not name the reuse mechanically"
                        % note)
    return problems


def case_b_judged_surface_advance_rebuilds(stage):
    """server/engine commit on main -> rebuild; NEW fail set is judged."""
    old = stage.main_tip
    dc.write_baseline("sandbar", "sandbar", old, ["OLDDEBT"], [])
    new = stage.advance_main("server/engine/x.py", "x = 1\n", "product change")
    calls = []
    # the line fails OLDDEBT too — main's NEW fail set no longer carries it,
    # so the line's OLDDEBT must be a NEW regression (the old baseline must
    # not excuse it: the false-green hole this face closes)
    out = stage.round(stage.runner(calls, ["OLDDEBT"],
                                   {new: [], old: ["OLDDEBT"]}))
    rel = stage.rel(out)
    problems = []
    if len(calls) != 2:
        problems.append("expected line run + baseline rebuild (2 calls), "
                        "got %r" % calls)
    if rel.get("baseline_source") != "rebuilt":
        problems.append("baseline_source=%r not 'rebuilt' after a "
                        "judged-surface commit" % rel.get("baseline_source"))
    if rel.get("baseline_tip") != new or rel.get("judged_tip") != new:
        problems.append("tips %r/%r not both the new tip (rebuilt at judged)"
                        % (rel.get("baseline_tip"), rel.get("judged_tip")))
    if rel.get("new_regressions") != ["OLDDEBT"]:
        problems.append("new_regressions=%r — the stale baseline excused a "
                        "failure main no longer carries" % rel.get(
                            "new_regressions"))
    if not rel.get("note", "").startswith("cache_built:sandbar@%s" % new[:12]):
        problems.append("note=%r does not name the rebuild" % rel.get("note"))
    return problems


def case_c_ambiguity_fails_closed_to_rebuild(stage):
    """Corrupted cache and non-ancestor tip each rebuild, never guess."""
    old = stage.main_tip
    dc.write_baseline("sandbar", "sandbar", old, ["d1"], [])
    cache = dc.baseline_path("sandbar", "sandbar", old)
    cache.write_text("{not json", encoding="utf-8")
    new = stage.advance_main("docs/x.md", "d2\n", "docs again, cache broken")
    calls = []
    out = stage.round(stage.runner(calls, ["d1"], {new: ["d1"]}))
    rel = stage.rel(out)
    problems = []
    if len(calls) != 2:
        problems.append("corrupted cache did not force the baseline run "
                        "(calls=%r)" % calls)
    if rel.get("baseline_source") != "rebuilt":
        problems.append("corrupted cache -> baseline_source=%r, not "
                        "'rebuilt' (a guessed reuse?)" % rel.get(
                            "baseline_source"))
    # non-ancestor cached tip: a commit on a parallel branch is NOT reachable
    # from main, so a cache keyed on it must never be reused for main
    _git(stage.repo, "checkout", "-q", "-b", "parallel")
    (stage.repo / "a.txt").write_text("side\n", encoding="utf-8")
    _git(stage.repo, "add", "-A")
    _git(stage.repo, "commit", "-qm", "side")
    _git(stage.repo, "checkout", "-q", "main")  # keep main checked out
    para = _git(stage.repo, "rev-parse", "parallel")
    stage.advance_main("a.txt", "a1\n", "advance main past the branch point")
    dc.write_baseline("sandbar", "sandbar", para, ["d1"], [])
    stage.reseed_landing()
    calls2 = []
    out2 = stage.round(stage.runner(calls2, [], {}))
    rel2 = stage.rel(out2)
    if rel2.get("baseline_source") != "rebuilt":
        problems.append("non-ancestor cached tip -> baseline_source=%r, not "
                        "'rebuilt'" % rel2.get("baseline_source"))
    if len(calls2) != 2:
        problems.append("non-ancestor tip did not force the baseline run "
                        "(calls=%r)" % calls2)
    return problems


def case_d_wall_clock_on_the_round_row(stage):
    """The round row carries the measured wall clock."""
    calls = []
    out = stage.round(stage.runner(calls, [], {}))
    row = out["rounds"][0]
    problems = []
    if "duration_ms" not in row:
        problems.append("round row has no duration_ms — the <=30min target "
                        "is not judgeable from the record")
    else:
        v = row["duration_ms"]
        if not isinstance(v, int) or v <= 0:
            problems.append("duration_ms=%r not a positive int" % (v,))
    return problems


CASES = [
    ("A named reuse after a non-surface main advance (docs-only)",
     case_a_named_reuse_after_non_surface_advance),
    ("B judged-surface advance (server/engine) rebuilds and judges the NEW "
     "fail set", case_b_judged_surface_advance_rebuilds),
    ("C ambiguity (corrupted cache, non-ancestor tip) fails closed to "
     "rebuild", case_c_ambiguity_fails_closed_to_rebuild),
    ("D round row carries the measured wall clock (duration_ms)",
     case_d_wall_clock_on_the_round_row),
]


def main():
    if not _git_available():
        print("ENV_FAIL: git unavailable")
        return 2
    for mod in ("shared",):
        if not (ENGINE / (mod + ".py")).exists():
            print("ENV_FAIL: engine module missing: %s" % mod)
            return 2
    ran = failed = 0
    for name, fn in CASES:
        ran += 1
        root = Path(tempfile.mkdtemp(prefix="sc-t261016-01-"))
        try:
            stage = Stage(root)
            problems = fn(stage)
        except Exception as e:  # noqa: BLE001
            problems = ["exception: %s" % e]
            traceback.print_exc()
        finally:
            import shutil
            shutil.rmtree(str(root), ignore_errors=True)
        if problems:
            failed += 1
            print("FAIL :: %s" % name, flush=True)
            for p in problems:
                print("       - %s" % p, flush=True)
        else:
            print("PASS :: %s" % name, flush=True)
    print("SCENARIO t261016-01 ran=%d fail=%d" % (ran, failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
