#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101126_round_evidence_kept.py — t261011-26, the round's evidence is
KEPT at a stable path and the rolling bookkeeping can never eat a live round
(grey-box L3, the REAL integration/line_round_runner.py as a subprocess over
a real git fixture tree + a stub suite, offline seconds, zero docker/
Temporal-server/browser, never touches 3099/7233; the real ledgers are never
written).

intent (user words: the suite log "deletes it with shutil.rmtree when the
round ends - the evidence is gone at exactly the moment someone would want
to look at it"; and a second round starting must not erase the first one's
visibility):
    A. RETAINED LOG: after a round ends, its suite log survives at the
       stable per-round path (rounds/<run_id>/suite.log under the declared
       face dir) with the suite's own judged lines intact — the evidence is
       no longer the temp dir's casualty, and it is read from the READER
       side (the file face), not from a writer receipt.
    B. ROLLING RETENTION: seeded old run dirs beyond the declared keep
       window are pruned, the NEWEST rounds are kept, and the just-finished
       round's own evidence is never its own prune's victim.
    C. LIVE-ROUND SAFETY (the review_plan condition): a face dir already
       carrying a live pointer naming ANOTHER round (an overlapping round
       or a straggler) survives this round's finish — the live
       current.json of a different run_id is NOT deleted, and the run dir
       that pointer names is NOT pruned even when it is old. Deletion and
       pruning key on the run_id read from the face on disk, never on
       "whatever is in rounds/".
    D. HONEST BOOKKEEPING: a prune that removes something says so on
       stderr (named, non-fatal), and a face dir with nothing to prune
       produces no error at all.

Layering / intent split (no intent-level duplication):
  - the live-face content, terminal-outcome vocabulary and the degrade
    face belong to the sibling t261011-26-round-progress-face entry;
  - retention arithmetic and prune-policy unit truth tables belong to
    developer L1 (the in-ticket unit battery);
  - the runner->header contract and could-not-run family belong to
    t261009-77-line-round-runner / t261011-18.

Three states: the runner or git missing = ENV_FAIL exit 2; the declared
retention/safety faces missing = FAIL named (TDD signal pre-implement),
must be green at the integration gate / merge.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261011-26-round-evidence-kept"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402
from lib_t26101126_fixture import (Fixture, CURRENT,  # noqa: E402
                                   RUNNER, seed_run_dir)

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

if not RUNNER.is_file():
    env_fail("line_round_runner missing", str(RUNNER))
try:
    fx = Fixture()
except Exception as e:  # noqa: BLE001
    env_fail("fixture tree unbuildable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

# ---- A: the suite log survives the round, at the stable path ----
fd = fx.face_dir("keep")
proc = fx.run_round("green", face_dir=fd)
run_dirs = sorted(d for d in (fd / "rounds").glob("*") if d.is_dir()) \
    if (fd / "rounds").is_dir() else []
ok(proc.returncode == 0 and len(run_dirs) == 1,
   "A0 the round completes and leaves exactly one run dir",
   "rc=%d stderr=%r dirs=%r"
   % (proc.returncode, (proc.stderr or "")[-160:],
      [d.name for d in run_dirs]))
if run_dirs:
    log = run_dirs[0] / "suite.log"  # sibling of the terminal face.json
    body = ""
    if log.is_file():
        try:
            body = log.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
    ok(log.is_file() and "PASS [sc_alpha]" in body
       and "INTEG_SUMMARY" in body,
       "A the suite log is RETAINED at the stable per-round path with the "
       "judged lines intact",
       "log=%s body head=%r" % (log, body[:160]))
else:
    ok(False, "A retained-log leg (skipped: no run dir landed)",
       "nothing under %s" % (fd / "rounds"))

# ---- B: rolling retention keeps the newest, prunes the old ----
fd2 = fx.face_dir("retain")
for i in range(12):
    seed_run_dir(fd2, "run-seed%02d" % i, age_orders=i)
proc2 = fx.run_round("green", face_dir=fd2)
dirs2 = sorted((fd2 / "rounds").glob("*"), key=lambda d: d.stat().st_mtime) \
    if (fd2 / "rounds").is_dir() else []
n_seeds_left = sum(1 for d in dirs2 if d.name.startswith("run-seed"))
ok(proc2.returncode == 0 and n_seeds_left < 12,
   "B1 rolling retention prunes seeded old rounds (the window is finite)",
   "rc=%d kept_total=%d seeds_left=%d"
   % (proc2.returncode, len(dirs2), n_seeds_left))
fresh = [d for d in dirs2 if (d / "face.json").is_file()
         and d.name.startswith("run-")] or dirs2
newest = fresh[-1] if fresh else None
ok(newest is not None and (newest / "suite.log").is_file(),
   "B2 the just-finished round's own evidence survives its own prune",
   "newest=%r contents=%r" % (newest.name if newest else None,
                              [c.name for c in newest.iterdir()] if newest else []))

# ---- C: a live pointer naming another round is never eaten ----
fd3 = fx.face_dir("overlap")
live_dir = seed_run_dir(fd3, "run-livestranger", live_pointer=True)
before = (fd3 / CURRENT).read_text(encoding="utf-8")
proc3 = fx.run_round("green", face_dir=fd3)
after = (fd3 / CURRENT).read_text(encoding="utf-8") \
    if (fd3 / CURRENT).is_file() else None
ok(proc3.returncode == 0,
   "C0 a round completes in a face dir already carrying a live stranger "
   "pointer", "rc=%d stderr=%r" % (proc3.returncode, (proc3.stderr or "")[-160:]))
pointer_kept = after is not None \
    and json.loads(before).get("run_id") == json.loads(after).get("run_id")
dir_kept = live_dir.is_dir() and (live_dir / "suite.log").is_file()
ok(pointer_kept,
   "C1 finish() does NOT delete a live pointer naming ANOTHER run "
   "(overlapping-round safety)",
   "before=%r after=%r" % (before[:80], (after or "GONE")[:80]))
ok(dir_kept,
   "C2 the run dir a live pointer names is NEVER pruned, even when old",
   "live dir exists=%s" % live_dir.is_dir())

# ---- D: honest bookkeeping ----
fd4 = fx.face_dir("clean")
proc4 = fx.run_round("green", face_dir=fd4)
ok(proc4.returncode == 0 and "prune" not in (proc4.stderr or "").lower(),
   "D1 a face dir with nothing to prune is silent (no noise, no error)",
   "rc=%d stderr=%r" % (proc4.returncode, (proc4.stderr or "")[-120:]))
pruned_said = "prune" in (proc2.stderr or "").lower() \
    or "retention" in (proc2.stderr or "").lower() \
    or "rounds" in (proc2.stderr or "").lower()
ok(pruned_said,
   "D2 a prune that removed seeded rounds is NAMED on stderr (non-fatal)",
   "stderr tail=%r" % (proc2.stderr or "")[-200:])

finish(NAME)
